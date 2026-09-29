"""Coverage, failure, duplicate and link-review files derived from current output."""

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from vi_dbpedia_data.models import DOMAIN_FIELDS, CountryRecord
from vi_dbpedia_data.utils import (
    ROOT,
    normalize_key,
    read_csv,
    read_json,
    utc_now,
    write_csv,
    write_json,
)
from vi_dbpedia_data.validate import duplicates, load_pipeline, validate_dataset

FIELDS = [
    "title_vi",
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
REVIEW_COLUMNS = [
    "page_id",
    "title_vi",
    "source_url",
    "wikidata_id",
    "english_title",
    "english_wikipedia_url",
    "english_dbpedia_candidate",
    "review_status",
    "notes",
]


def _debug_rows(records: list[CountryRecord], interim: list[dict]) -> list[dict | None]:
    """Pair interim rows with processed records even when redirects share IDs."""
    by_id: dict[int, list[dict]] = defaultdict(list)
    for row in interim:
        if row.get("page_id") is not None:
            by_id[int(row["page_id"])].append(row)
    used = Counter()
    result = []
    for record in records:
        index = used[record.page_id]
        used[record.page_id] += 1
        entries = by_id[record.page_id]
        result.append(entries[index] if index < len(entries) else None)
    return result


def _source_present(debug: dict, field: str) -> bool:
    keys = debug.get("canonical_source_keys")
    if keys is not None:
        # A present but blank parameter still counts as source-present.
        return bool(keys.get(field))
    return debug.get("parse_status", {}).get(field) in {
        "present",
        "explicit_none",
        "parse_failed",
        "ambiguous",
    }


def field_coverage(records: list[CountryRecord], interim: list[dict] | None = None) -> list[dict]:
    count = len(records)
    debug_rows = _debug_rows(records, interim or [])
    rows = []
    for field in FIELDS:
        available = sum(
            getattr(record, field) is not None and getattr(record, field) != []
            for record in records
        )
        row = {
            "field": field,
            "available_count": available,
            "missing_count": count - available,
            "coverage_percentage": round(100 * available / count, 2) if count else 0.0,
            "value_coverage_percentage": round(100 * available / count, 2) if count else 0.0,
        }
        if field in DOMAIN_FIELDS:
            known = [
                debug
                for debug in debug_rows
                if debug is not None and field in debug.get("parse_status", {})
            ]
            present = sum(_source_present(debug, field) for debug in known)
            row.update(
                {
                    "source_available_count": present,
                    "source_missing_count": len(known) - present,
                    "source_unknown_count": count - len(known),
                    "source_coverage_percentage": round(100 * present / count, 2)
                    if count and len(known) == count
                    else None,
                    "explicit_none_count": sum(
                        debug["parse_status"][field] == "explicit_none" for debug in known
                    ),
                }
            )
        else:
            row.update(
                {
                    "source_available_count": None,
                    "source_missing_count": None,
                    "source_unknown_count": None,
                    "source_coverage_percentage": None,
                    "explicit_none_count": None,
                }
            )
        rows.append(row)
    return rows


def generate_reports(root: Path = ROOT) -> dict:
    records, interim, manifest, structural = load_pipeline(root)
    results = validate_dataset(root)
    coverage = field_coverage(records, interim)
    counts = Counter(result.status for result in results)
    duplicate_ids, duplicate_titles = duplicates(records)
    raw_ids = Counter(row["page_id"] for row in manifest if row.get("page_id"))
    raw_titles = Counter(
        normalize_key(row["canonical_title"]) for row in manifest if row.get("canonical_title")
    )
    all_ids = {str(page_id) for page_id in duplicate_ids} | {
        key for key, value in raw_ids.items() if value > 1
    }
    all_titles = duplicate_titles | {key for key, value in raw_titles.items() if value > 1}
    candidate_path = root / "data/candidates/countries.json"
    summary = {
        "candidate_count": len(read_json(candidate_path))
        if candidate_path.exists()
        else len(manifest),
        "selected_count": len(manifest),
        "collected_count": sum(
            row["collection_status"] in {"collected", "skipped"} for row in manifest
        ),
        "failed_collection_count": sum(row["collection_status"] == "failed" for row in manifest),
        "processed_count": len(records),
        "valid_count": counts["valid"],
        "warning_count": counts["warning"],
        "invalid_count": counts["invalid"],
        "duplicate_page_ids": len(all_ids),
        "duplicate_titles": len(all_titles),
        "with_english_link": sum(bool(row.english_title) for row in records),
        "without_english_link": sum(not row.english_title for row in records),
        "coverage": {row["field"]: row["coverage_percentage"] for row in coverage},
        "value_coverage": {row["field"]: row["value_coverage_percentage"] for row in coverage},
        "source_field_coverage": {
            row["field"]: row["source_coverage_percentage"]
            for row in coverage
            if row["field"] in DOMAIN_FIELDS
        },
        "generation_timestamp": utc_now().isoformat(),
    }
    out = root / "data/reports"
    write_json(out / "summary.json", summary)
    write_csv(
        out / "field_coverage.csv",
        coverage,
        [
            "field",
            "available_count",
            "missing_count",
            "coverage_percentage",
            "value_coverage_percentage",
            "source_available_count",
            "source_missing_count",
            "source_unknown_count",
            "source_coverage_percentage",
            "explicit_none_count",
        ],
    )
    status_rows = [
        {
            "page_id": record.page_id,
            "title_vi": record.title_vi,
            "field": field,
            "status": (debug or {}).get("parse_status", {}).get(field, "unknown"),
            "source_parameter_present": _source_present(debug, field) if debug else "",
            "raw_keys": json.dumps(
                (debug or {}).get("canonical_source_keys", {}).get(field, []), ensure_ascii=False
            ),
            "reason": (debug or {}).get("field_reasons", {}).get(field, ""),
        }
        for record, debug in zip(records, _debug_rows(records, interim), strict=True)
        for field in DOMAIN_FIELDS
    ]
    write_csv(
        out / "field_status.csv",
        status_rows,
        [
            "page_id",
            "title_vi",
            "field",
            "status",
            "source_parameter_present",
            "raw_keys",
            "reason",
        ],
    )
    missing = []
    for record, debug in zip(records, _debug_rows(records, interim), strict=True):
        for field in FIELDS:
            if getattr(record, field) is not None and getattr(record, field) != []:
                continue
            status = (debug or {}).get("parse_status", {}).get(field, "unknown")
            reason = (
                (debug or {})
                .get("field_reasons", {})
                .get(
                    field,
                    "No interim source inspection available"
                    if field in DOMAIN_FIELDS
                    else "No canonical metadata value",
                )
            )
            missing.append(
                {
                    "page_id": record.page_id,
                    "title_vi": record.title_vi,
                    "field": field,
                    "status": status if field in DOMAIN_FIELDS else "not_available",
                    "reason": reason,
                    "source_parameter_present": _source_present(debug, field)
                    if debug is not None and field in DOMAIN_FIELDS
                    else "",
                }
            )
    write_csv(
        out / "missing_values.csv",
        missing,
        ["page_id", "title_vi", "field", "status", "reason", "source_parameter_present"],
    )
    collisions = [
        {
            "page_id": entry.get("page_id"),
            "title_vi": entry.get("canonical_title"),
            "normalized_key": key,
            "occurrence_count": len(occurrences),
            "raw_keys": json.dumps([item["raw_key"] for item in occurrences], ensure_ascii=False),
            "raw_values": json.dumps(
                [item["raw_value"] for item in occurrences], ensure_ascii=False
            ),
        }
        for entry in interim
        for key, occurrences in entry.get("normalized_key_collisions", {}).items()
    ]
    write_csv(
        out / "normalized_key_collisions.csv",
        collisions,
        ["page_id", "title_vi", "normalized_key", "occurrence_count", "raw_keys", "raw_values"],
    )
    failures = [
        {
            "page_id": entry.get("page_id"),
            "title_vi": entry.get("canonical_title"),
            "field": field,
            "status": status,
            "raw_value": entry.get("canonical_raw_values", {}).get(field),
            "error": " | ".join(entry.get("parse_errors", [])),
        }
        for entry in interim
        for field, status in entry.get("parse_status", {}).items()
        if status in {"parse_failed", "ambiguous"}
    ]
    failures.extend(
        {
            "page_id": row.get("page_id"),
            "title_vi": row.get("canonical_title"),
            "field": "record",
            "status": "invalid",
            "raw_value": "",
            "error": " | ".join(row["parse_errors"]),
        }
        for row in structural
    )
    failures.extend(
        {
            "page_id": entry.get("page_id"),
            "title_vi": entry.get("canonical_title"),
            "field": "infobox",
            "status": entry.get("template_selection"),
            "raw_value": "",
            "error": " | ".join(entry.get("parse_errors", [])),
        }
        for entry in interim
        if entry.get("template_selection")
        in {
            "not_found",
            "ambiguous_alias",
            "ambiguous_heuristic",
        }
    )
    write_csv(
        out / "parse_errors.csv",
        failures,
        ["page_id", "title_vi", "field", "status", "raw_value", "error"],
    )
    dup_rows = []
    for row in manifest:
        if (
            row.get("page_id") in all_ids
            or normalize_key(row.get("canonical_title", "")) in all_titles
        ):
            dup_rows.append({**row, "reason": "shared page ID/title (redirect or duplicate)"})
    write_csv(
        out / "duplicates.csv",
        dup_rows,
        [
            "candidate_wikidata_id",
            "requested_title",
            "page_id",
            "canonical_title",
            "collection_status",
            "raw_file_path",
            "error",
            "reason",
        ],
    )
    links = [
        {
            "page_id": record.page_id,
            "title_vi": record.title_vi,
            "wikidata_id": record.wikidata_id,
            "english_title": record.english_title,
            "english_wikipedia_url": record.english_wikipedia_url,
            "english_dbpedia_candidate": record.english_dbpedia_candidate,
        }
        for record in records
    ]
    write_csv(
        out / "link_candidates.csv",
        links,
        [
            "page_id",
            "title_vi",
            "wikidata_id",
            "english_title",
            "english_wikipedia_url",
            "english_dbpedia_candidate",
        ],
    )
    return summary


def review_sample(root: Path = ROOT, *, seed: int = 42, size: int = 20) -> list[dict]:
    records, _, _, _ = load_pipeline(root)
    if len(records) < size:
        raise ValueError(f"Need {size} processed countries for review; found {len(records)}")
    ordered = sorted(records, key=lambda record: (record.page_id, record.title_vi))
    sample = random.Random(seed).sample(ordered, size)
    rows = [
        {
            **{field: getattr(record, field) for field in REVIEW_COLUMNS[:-2]},
            "review_status": "",
            "notes": "",
        }
        for record in sample
    ]
    path = root / "data/reports/manual_link_review.csv"
    if path.exists() and any(
        row["review_status"].strip() or row["notes"].strip() for row in read_csv(path)
    ):
        raise FileExistsError(f"Manual reviews exist; move or back up {path} before regenerating")
    write_csv(path, rows, REVIEW_COLUMNS)
    return rows


def review_summary(root: Path = ROOT) -> dict:
    rows = read_csv(root / "data/reports/manual_link_review.csv")
    counts = Counter(row["review_status"].strip().casefold() for row in rows)
    invalid = set(counts) - {"", "correct", "incorrect", "uncertain"}
    if invalid:
        raise ValueError(f"Unknown review statuses: {sorted(invalid)}")
    definitive = counts["correct"] + counts["incorrect"]
    return {
        "reviewed_count": len(rows) - counts[""],
        "correct_count": counts["correct"],
        "incorrect_count": counts["incorrect"],
        "uncertain_count": counts["uncertain"],
        "unreviewed_count": counts[""],
        "observed_accuracy": round(counts["correct"] / definitive, 4) if definitive else None,
    }
