"""Infobox key mapping, per-field parse outcomes, and canonical output."""

import json
import logging
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from vi_dbpedia_data.collect import selected_raw_pages
from vi_dbpedia_data.inspect_infobox import infobox_values, select_infobox
from vi_dbpedia_data.models import CountryRecord, RawPage
from vi_dbpedia_data.normalize import (
    area,
    calling_codes,
    english_links,
    explicit_none_reason,
    indicates_official_languages,
    population,
    population_options,
    resources,
)
from vi_dbpedia_data.utils import ROOT, Settings, load_mapping, normalize_key, write_json

LOG = logging.getLogger(__name__)
PARSERS = {
    "integer": population,
    "area_km2": area,
    "resource_list": resources,
    "string_list": calling_codes,
}


def _matching(occurrences: list[dict[str, str]], aliases: list[str]) -> list[dict[str, str]]:
    names = {normalize_key(alias) for alias in aliases}
    return [item for item in occurrences if normalize_key(item["raw_key"]) in names]


def _select_source(
    spec: dict, occurrences: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict, str | None]:
    """Return all direct source matches, chosen value occurrences, and provenance."""
    direct = _matching(occurrences, spec["aliases"])
    provenance: dict = {"selection_method": "direct_alias"}
    if priority := spec.get("source_priority"):
        for group in priority:
            options = _matching(occurrences, group["aliases"])
            if not any(item["raw_value"].strip() for item in options):
                continue
            year = next(
                (
                    item
                    for item in _matching(occurrences, group["year_aliases"])
                    if item["raw_value"].strip()
                ),
                None,
            )
            provenance = {
                "selection_method": "source_priority",
                "source_type": group["source_type"],
                "year_source_key": year["raw_key"] if year else None,
                "year_source_value": year["raw_value"] if year else None,
            }
            return direct, options, provenance, None
        return direct, direct, provenance, None

    fallback = spec.get("contextual_fallback")
    if direct or not fallback:
        return direct, direct, provenance, None
    typed = _matching(occurrences, fallback["type_aliases"])
    value = _matching(occurrences, fallback["value_aliases"])
    labels = {
        unicodedata.normalize("NFC", item["raw_value"].strip())
        for item in typed
        if item["raw_value"].strip()
    }
    provenance = {
        "selection_method": "contextual_fallback_considered",
        "type_occurrences": typed,
        "value_occurrences": value,
    }
    if len(labels) != 1 or not indicates_official_languages(next(iter(labels))):
        return direct, direct, provenance, "Language type does not clearly assert official status"
    if not value:
        return direct, direct, provenance, "Official language type has no languages parameter"
    provenance["selection_method"] = "contextual_official_languages"
    return value, value, provenance, None


def extract_page(
    page: RawPage, settings: Settings, mapping: dict
) -> tuple[dict, CountryRecord | None]:
    template, selection, _names = select_infobox(
        page.wikitext, settings, country_candidate=bool(page.candidate_wikidata_id)
    )
    raw = infobox_values(template) if template else {}
    occurrences: dict[str, list[dict[str, str]]] = defaultdict(list)
    source_occurrences = []
    for param in template.params if template else []:
        raw_key = str(param.name)
        item = {"raw_key": raw_key, "raw_value": str(param.value)}
        source_occurrences.append(item)
        occurrences[normalize_key(raw_key)].append(item)
    mapped = {normalize_key(alias) for spec in mapping.values() for alias in spec["aliases"]}
    interim = {
        "page_id": page.page_id,
        "canonical_title": page.canonical_title,
        "selected_template": str(template.name).strip() if template else None,
        "template_selection": selection,
        "raw_infobox": raw,
        "unmapped_keys": [key for key in raw if normalize_key(key) not in mapped],
        "normalized_key_collisions": {
            key: values for key, values in occurrences.items() if len(values) > 1
        },
        "canonical_source_occurrences": {},
        "canonical_source_keys": {},
        "field_provenance": {},
        "canonical_raw_values": {},
        "parse_status": {},
        "field_reasons": {},
        "parse_errors": [],
    }
    title, wikipedia_url, dbpedia_uri = english_links(page.langlinks.get("en"))
    record = {
        "page_id": page.page_id,
        "title_vi": page.canonical_title,
        "abstract_vi": page.extract,
        "source_url": page.source_url,
        "revision_id": page.revision_id,
        "revision_timestamp": page.revision_timestamp,
        "retrieved_at": page.retrieved_at,
        "wikidata_id": page.pageprops_wikidata_id,
        "english_title": title,
        "english_wikipedia_url": wikipedia_url,
        "english_dbpedia_candidate": dbpedia_uri,
    }
    if template is None:
        interim["parse_errors"].append(f"Country infobox {selection}")
    for field, spec in mapping.items():
        matches, chosen, provenance, missing_reason = _select_source(spec, source_occurrences)
        interim["canonical_source_occurrences"][field] = matches
        interim["canonical_source_keys"][field] = [item["raw_key"] for item in matches]
        interim["field_provenance"][field] = provenance
        # First non-empty occurrence wins only when all non-empty values agree.
        # Comparison ignores surrounding whitespace/NFC differences; original
        # spellings and all occurrences remain in interim for inspection.
        unique: dict[str, str] = {}
        for item in chosen:
            normalized_value = unicodedata.normalize("NFC", item["raw_value"].strip())
            if normalized_value:
                unique.setdefault(normalized_value, item["raw_value"])
        selected_raw = next(iter(unique.values())) if len(unique) == 1 else None
        interim["canonical_raw_values"][field] = (
            selected_raw if selected_raw is not None else [item["raw_value"] for item in chosen]
        )
        provenance["selected_source_keys"] = [
            item["raw_key"] for item in chosen if item["raw_value"].strip()
        ]
        default = [] if spec["type"].endswith("_list") else None
        record[field] = default
        if not unique:
            interim["parse_status"][field] = "source_missing"
            interim["field_reasons"][field] = (
                "Configured source parameter is blank"
                if matches
                else missing_reason or "No configured source parameter in selected infobox"
            )
        elif len(unique) > 1:
            interim["parse_status"][field] = "ambiguous"
            interim["field_reasons"][field] = "Conflicting non-empty source values"
            interim["parse_errors"].append(f"{field}: conflicting alias values {list(unique)!r}")
        elif reason := explicit_none_reason(field, selected_raw):
            interim["parse_status"][field] = "explicit_none"
            interim["field_reasons"][field] = reason
        else:
            parsed = PARSERS[spec["type"]](selected_raw)
            if parsed is None and spec["type"] == "integer":
                options = population_options(selected_raw)
                if options and len(set(options)) > 1:
                    interim["parse_status"][field] = "ambiguous"
                    interim["field_reasons"][field] = (
                        f"Multiple distinct plausible population values: {options}"
                    )
                    interim["parse_errors"].append(f"{field}: ambiguous values {options!r}")
                    continue
                if options:
                    parsed = options[0]
            if parsed is None or parsed == []:
                interim["parse_status"][field] = "parse_failed"
                interim["field_reasons"][field] = "Source value cannot be safely normalized"
                interim["parse_errors"].append(f"{field}: cannot parse {selected_raw!r}")
            else:
                interim["parse_status"][field] = "present"
                interim["field_reasons"][field] = (
                    f"Normalized {provenance.get('source_type', 'value')} from source parameter"
                    if provenance["selection_method"] == "source_priority"
                    else "Normalized from contextual official-language type"
                    if provenance["selection_method"] == "contextual_official_languages"
                    else "Normalized from source parameter"
                )
                record[field] = parsed
    try:
        country = CountryRecord.model_validate(record)
    except ValidationError as exc:
        interim["parse_errors"].append(f"Canonical model: {exc}")
        interim["record_status"] = "invalid"
        return interim, None
    interim["record_status"] = "processed"
    return interim, country


def process(settings: Settings, root: Path = ROOT) -> tuple[list[dict], list[CountryRecord]]:
    mapping = load_mapping(root)
    interim, records = [], []
    for page in selected_raw_pages(root):
        try:
            debug, record = extract_page(page, settings, mapping)
        except (ValueError, TypeError) as exc:
            LOG.error("Extraction failed for %s: %s", page.canonical_title, exc)
            debug = {
                "page_id": page.page_id,
                "canonical_title": page.canonical_title,
                "record_status": "invalid",
                "parse_errors": [str(exc)],
                "parse_status": {},
            }
            record = None
        interim.append(debug)
        if record is not None:
            records.append(record)
    out = root / "data/interim/extracted.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in interim),
        encoding="utf-8",
    )
    canonical = [record.model_dump(mode="json") for record in records]
    write_json(root / "data/processed/countries.json", canonical)
    # JSON-in-CSV cells preserves nested objects/lists and literal Unicode.
    csv_rows = [
        {
            key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            for key, value in row.items()
        }
        for row in canonical
    ]
    pd.DataFrame(csv_rows, columns=list(CountryRecord.model_fields)).to_csv(
        root / "data/processed/countries.csv", index=False, encoding="utf-8"
    )
    return interim, records
