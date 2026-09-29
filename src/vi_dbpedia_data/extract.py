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
    population,
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


def extract_page(
    page: RawPage, settings: Settings, mapping: dict
) -> tuple[dict, CountryRecord | None]:
    template, selection, _names = select_infobox(page.wikitext, settings)
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
        aliases = {normalize_key(alias) for alias in spec["aliases"]}
        matches = [item for item in source_occurrences if normalize_key(item["raw_key"]) in aliases]
        interim["canonical_source_occurrences"][field] = matches
        interim["canonical_source_keys"][field] = [item["raw_key"] for item in matches]
        # First non-empty occurrence wins only when all non-empty values agree.
        # Comparison ignores surrounding whitespace/NFC differences; original
        # spellings and all occurrences remain in interim for inspection.
        unique: dict[str, str] = {}
        for item in matches:
            normalized_value = unicodedata.normalize("NFC", item["raw_value"].strip())
            if normalized_value:
                unique.setdefault(normalized_value, item["raw_value"])
        selected_raw = next(iter(unique.values())) if len(unique) == 1 else None
        interim["canonical_raw_values"][field] = (
            selected_raw if selected_raw is not None else [item["raw_value"] for item in matches]
        )
        default = [] if spec["type"].endswith("_list") else None
        record[field] = default
        if not unique:
            interim["parse_status"][field] = "source_missing"
            interim["field_reasons"][field] = (
                "Configured source parameter is blank"
                if matches
                else "No configured source parameter in selected infobox"
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
            if parsed is None or parsed == []:
                interim["parse_status"][field] = "parse_failed"
                interim["field_reasons"][field] = "Source value cannot be safely normalized"
                interim["parse_errors"].append(f"{field}: cannot parse {selected_raw!r}")
            else:
                interim["parse_status"][field] = "present"
                interim["field_reasons"][field] = "Normalized from source parameter"
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
