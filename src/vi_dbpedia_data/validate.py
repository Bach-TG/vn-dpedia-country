"""Non-destructive per-record validation, including collection/interim failures."""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import ValidationError

from vi_dbpedia_data.models import CandidateCountry, CountryRecord, ValidationResult
from vi_dbpedia_data.normalize import english_links
from vi_dbpedia_data.utils import (
    ROOT,
    is_vi_wikipedia_url,
    normalize_key,
    read_csv,
    read_json,
    write_json,
)

QUALITY_FIELDS = [
    "abstract_vi",
    "capital",
    "population_total",
    "area_km2",
    "currencies",
    "official_languages",
    "calling_codes",
    "wikidata_id",
    "english_title",
]


def duplicates(records: list[CountryRecord]) -> tuple[set[int], set[str]]:
    ids = Counter(item.page_id for item in records)
    titles = Counter(normalize_key(item.title_vi) for item in records)
    return (
        {key for key, count in ids.items() if count > 1},
        {key for key, count in titles.items() if count > 1},
    )


def validate_records(
    records: list[CountryRecord],
    interim: list[dict] | None = None,
    manifest: list[dict] | None = None,
    candidates: list[CandidateCountry] | None = None,
) -> list[ValidationResult]:
    interim = interim or []
    manifest = manifest or []
    candidate_hints = {
        item.wikidata_id: item.english_title_hint
        for item in candidates or []
        if item.wikidata_id and item.english_title_hint
    }
    duplicate_ids, duplicate_titles = duplicates(records)
    by_id: dict[int, list[dict]] = defaultdict(list)
    for row in manifest:
        if row.get("page_id"):
            by_id[int(row["page_id"])].append(row)
    debug_by_id: dict[int, list[dict]] = defaultdict(list)
    for row in interim:
        if row.get("page_id"):
            debug_by_id[int(row["page_id"])].append(row)
    used = Counter()
    results = []
    for record in records:
        index = used[record.page_id]
        used[record.page_id] += 1
        debug = debug_by_id[record.page_id]
        field_status = debug[index].get("parse_status", {}) if index < len(debug) else {}
        related = by_id[record.page_id]
        errors, warnings = [], []
        if record.page_id <= 0 or not record.title_vi.strip():
            errors.append("Missing or invalid identity")
        if record.page_id in duplicate_ids:
            errors.append("Duplicate page ID / redirect")
        if normalize_key(record.title_vi) in duplicate_titles:
            errors.append("Duplicate canonical title")
        if not is_vi_wikipedia_url(record.source_url):
            errors.append("Source URL is not HTTPS vi.wikipedia.org")
        if manifest and not related:
            errors.append("No successful collection manifest entry")
        elif related and any(
            row["collection_status"] not in {"collected", "skipped"} for row in related
        ):
            errors.append("Collection failed")
        if record.population_total is not None and record.population_total <= 0:
            errors.append("Population must be positive")
        if record.area_km2 is not None and record.area_km2 <= 0:
            errors.append("Area must be positive")
        for row in related:
            qid = row.get("candidate_wikidata_id")
            if qid and record.wikidata_id and qid != record.wikidata_id:
                warnings.append(f"Candidate/pageprops QID mismatch: {qid} / {record.wikidata_id}")
            if (
                qid in candidate_hints
                and record.english_title
                and (normalize_key(candidate_hints[qid]) != normalize_key(record.english_title))
            ):
                warnings.append("Wikidata English sitelink hint differs from vi Wikipedia langlink")
            if row.get("canonical_title") and row["canonical_title"] != record.title_vi:
                warnings.append("Manifest canonical title disagrees with processed title")
        expected_title, wiki_url, dbpedia_uri = english_links(record.english_title)
        if (
            record.english_title,
            record.english_wikipedia_url,
            record.english_dbpedia_candidate,
        ) != (expected_title, wiki_url, dbpedia_uri):
            errors.append("English title / derived URL inconsistency")
        for field in QUALITY_FIELDS:
            value = getattr(record, field)
            empty = value is None or value == [] or (isinstance(value, str) and not value.strip())
            status = field_status.get(field)
            if status == "explicit_none" and not empty:
                errors.append(f"Contradictory explicit_none and canonical value: {field}")
            if empty and status != "explicit_none":
                detail = {
                    "source_missing": "Source missing",
                    "parse_failed": "Parse failed",
                    "ambiguous": "Ambiguous source",
                    "present": "Unexpected empty canonical value",
                }.get(status, "Missing")
                warnings.append(f"{detail} {field}")
        for field in ("capital", "currencies", "official_languages"):
            if any(not ref.label_vi.strip() for ref in getattr(record, field)):
                errors.append(f"Empty {field} resource label")
        if any(
            not re.fullmatch(r"\+\d{1,4}(?:-\d{1,4}|-\dxx)?", code, re.I)
            for code in record.calling_codes
        ):
            warnings.append("Malformed calling code")
        if index < len(debug):
            warnings.extend(
                f"Parse error: {message}" for message in debug[index].get("parse_errors", [])
            )
        results.append(
            ValidationResult(
                page_id=record.page_id,
                title_vi=record.title_vi,
                status="invalid" if errors else "warning" if warnings else "valid",
                reasons=list(dict.fromkeys(errors + warnings)),
            )
        )
    # Structural extraction failures and failed/missing collections are visible too.
    for page_id, entries in debug_by_id.items():
        for entry in entries[used[page_id] :]:
            results.append(
                ValidationResult(
                    page_id=page_id,
                    title_vi=entry.get("canonical_title", ""),
                    status="invalid",
                    reasons=["No canonical record", *entry.get("parse_errors", [])],
                )
            )
    for row in manifest:
        if row.get("collection_status") not in {"collected", "skipped"} or (
            row.get("page_id") and int(row["page_id"]) not in debug_by_id
        ):
            results.append(
                ValidationResult(
                    page_id=int(row["page_id"]) if row.get("page_id") else None,
                    title_vi=row.get("canonical_title") or row.get("requested_title", ""),
                    status="invalid",
                    reasons=[row.get("error") or "Missing collected/processed page"],
                )
            )
    return results


def load_pipeline(
    root: Path = ROOT,
) -> tuple[list[CountryRecord], list[dict], list[dict], list[dict]]:
    path = root / "data/processed/countries.json"
    raw_records = read_json(path)  # fail loudly if process has never been run
    records, structural = [], []
    for row in raw_records:
        try:
            records.append(CountryRecord.model_validate(row))
        except ValidationError as exc:
            structural.append(
                {
                    "page_id": row.get("page_id"),
                    "canonical_title": row.get("title_vi", ""),
                    "parse_errors": [f"Invalid processed JSON: {exc}"],
                }
            )
    interim_path = root / "data/interim/extracted.jsonl"
    interim = (
        [json.loads(line) for line in interim_path.read_text("utf-8").splitlines() if line.strip()]
        if interim_path.exists()
        else []
    )
    manifest_path = root / "data/raw/collection_manifest.csv"
    manifest = read_csv(manifest_path) if manifest_path.exists() else []
    return records, interim, manifest, structural


def validate_dataset(root: Path = ROOT) -> list[ValidationResult]:
    records, interim, manifest, structural = load_pipeline(root)
    path = root / "data/candidates/countries.json"
    candidates = (
        [CandidateCountry.model_validate(row) for row in read_json(path)] if path.exists() else []
    )
    results = validate_records(records, interim, manifest, candidates)
    for row in structural:
        missing = next(
            (
                result
                for result in results
                if result.page_id == row["page_id"]
                and result.status == "invalid"
                and "No canonical record" in result.reasons
            ),
            None,
        )
        if missing is not None:
            missing.reasons.extend(row["parse_errors"])
        else:
            results.append(
                ValidationResult(
                    page_id=row["page_id"],
                    title_vi=row["canonical_title"],
                    status="invalid",
                    reasons=row["parse_errors"],
                )
            )
    write_json(root / "data/reports/validation.json", [row.model_dump() for row in results])
    return results
