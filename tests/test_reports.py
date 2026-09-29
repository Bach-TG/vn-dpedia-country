import json
from datetime import UTC, datetime

import pytest

from vi_dbpedia_data.models import CountryRecord, ResourceRef
from vi_dbpedia_data.reports import field_coverage, generate_reports, review_sample, review_summary
from vi_dbpedia_data.utils import read_csv, write_csv, write_json


def test_scalar_and_list_coverage():
    shared = {"source_url": "https://vi.wikipedia.org/wiki/X", "retrieved_at": datetime.now(UTC)}
    records = [
        CountryRecord(
            page_id=1,
            title_vi="A",
            population_total=0,
            capital=[ResourceRef(label_vi="A")],
            **shared,
        ),
        CountryRecord(page_id=2, title_vi="B", population_total=None, capital=[], **shared),
    ]
    coverage = {row["field"]: row for row in field_coverage(records)}
    assert coverage["title_vi"]["coverage_percentage"] == 100
    assert coverage["population_total"]["available_count"] == 1
    assert coverage["capital"]["missing_count"] == 1
    assert coverage["capital"]["coverage_percentage"] == 50


def test_review_summary_does_not_invent_reviews(tmp_path):
    path = tmp_path / "data/reports/manual_link_review.csv"
    write_csv(
        path,
        [
            {"review_status": ""},
            {"review_status": "correct"},
            {"review_status": "incorrect"},
            {"review_status": "uncertain"},
        ],
        ["review_status"],
    )
    assert review_summary(tmp_path) == {
        "reviewed_count": 3,
        "correct_count": 1,
        "incorrect_count": 1,
        "uncertain_count": 1,
        "unreviewed_count": 1,
        "observed_accuracy": 0.5,
    }
    write_csv(path, [{"review_status": ""}], ["review_status"])
    assert review_summary(tmp_path)["observed_accuracy"] is None
    write_csv(path, [{"review_status": "made up"}], ["review_status"])
    with pytest.raises(ValueError):
        review_summary(tmp_path)


def test_review_sample_is_stable_and_preserves_human_edits(tmp_path):
    rows = [
        CountryRecord(
            page_id=index,
            title_vi=f"Quốc gia {index}",
            source_url=f"https://vi.wikipedia.org/wiki/{index}",
            retrieved_at=datetime.now(UTC),
        ).model_dump(mode="json")
        for index in range(1, 22)
    ]
    write_json(tmp_path / "data/processed/countries.json", rows)
    first = review_sample(tmp_path)
    assert len(first) == 20
    assert all(row["review_status"] == row["notes"] == "" for row in first)
    assert first == review_sample(tmp_path)
    path = tmp_path / "data/reports/manual_link_review.csv"
    edited = read_csv(path)
    edited[0]["review_status"] = "correct"
    write_csv(path, edited, list(edited[0]))
    with pytest.raises(FileExistsError):
        review_sample(tmp_path)


def test_duplicate_manifest_redirects_appear_in_report(tmp_path):
    record = CountryRecord(
        page_id=7,
        title_vi="Cộng hòa Nam Phi",
        source_url="https://vi.wikipedia.org/wiki/Cộng_hòa_Nam_Phi",
        retrieved_at=datetime.now(UTC),
    )
    write_json(tmp_path / "data/processed/countries.json", [record.model_dump(mode="json")])
    columns = [
        "candidate_wikidata_id",
        "requested_title",
        "page_id",
        "canonical_title",
        "collection_status",
        "raw_file_path",
        "error",
    ]
    write_csv(
        tmp_path / "data/raw/collection_manifest.csv",
        [
            {
                "requested_title": title,
                "page_id": 7,
                "canonical_title": "Cộng hòa Nam Phi",
                "collection_status": "skipped",
            }
            for title in ("Nam Phi", "Cộng hòa Nam Phi")
        ],
        columns,
    )
    summary = generate_reports(tmp_path)
    assert summary["duplicate_page_ids"] == summary["duplicate_titles"] == 1
    assert len(read_csv(tmp_path / "data/reports/duplicates.csv")) == 2


def test_source_presence_and_value_coverage_are_distinct(tmp_path):
    records = [
        CountryRecord(
            page_id=index,
            title_vi=f"Nước {index}",
            source_url="https://vi.wikipedia.org/wiki/Reference",
            retrieved_at=datetime.now(UTC),
        )
        for index in (1, 2)
    ]
    debug = [
        {
            "page_id": 1,
            "canonical_title": "Nước 1",
            "parse_status": {"capital": "explicit_none", "official_languages": "explicit_none"},
            "canonical_source_keys": {
                "capital": [" capital "],
                "official_languages": [" official_languages "],
            },
            "field_reasons": {
                "capital": "Source explicitly states there is no official capital",
                "official_languages": "Source explicitly states there is none",
            },
            "parse_errors": [],
        },
        {
            "page_id": 2,
            "canonical_title": "Nước 2",
            "parse_status": {
                "capital": "source_missing",
                "area_km2": "parse_failed",
                "currencies": "ambiguous",
            },
            "canonical_source_keys": {
                "capital": [],
                "area_km2": ["area_km2"],
                "currencies": ["currency", "currencies"],
            },
            "field_reasons": {
                "capital": "No configured source parameter in selected infobox",
                "area_km2": "Source value cannot be safely normalized",
                "currencies": "Conflicting non-empty source values",
            },
            "parse_errors": ["area_km2: cannot parse '?'"],
        },
    ]
    coverage = {row["field"]: row for row in field_coverage(records, debug)}
    assert coverage["capital"]["source_available_count"] == 1
    assert coverage["capital"]["source_coverage_percentage"] == 50
    assert coverage["capital"]["value_coverage_percentage"] == 0
    assert coverage["capital"]["explicit_none_count"] == 1
    assert coverage["official_languages"]["source_unknown_count"] == 1
    assert coverage["title_vi"]["source_coverage_percentage"] is None

    write_json(
        tmp_path / "data/processed/countries.json",
        [record.model_dump(mode="json") for record in records],
    )
    path = tmp_path / "data/interim/extracted.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in debug), "utf-8")
    summary = generate_reports(tmp_path)
    assert summary["source_field_coverage"]["capital"] == 50
    assert summary["value_coverage"]["capital"] == 0
    empty = {
        (row["page_id"], row["field"]): row
        for row in read_csv(tmp_path / "data/reports/missing_values.csv")
    }
    assert empty[("1", "capital")]["status"] == "explicit_none"
    assert empty[("1", "capital")]["source_parameter_present"] == "True"
    assert empty[("2", "capital")]["status"] == "source_missing"
    assert empty[("2", "capital")]["source_parameter_present"] == "False"
    assert [row["status"] for row in read_csv(tmp_path / "data/reports/parse_errors.csv")] == [
        "parse_failed",
        "ambiguous",
    ]


def test_blank_source_parameter_counts_as_source_present():
    record = CountryRecord(
        page_id=1,
        title_vi="X",
        source_url="https://vi.wikipedia.org/wiki/X",
        retrieved_at=datetime.now(UTC),
    )
    debug = {
        "page_id": 1,
        "parse_status": {"capital": "source_missing"},
        "canonical_source_keys": {"capital": ["capital"]},
    }
    capital = next(row for row in field_coverage([record], [debug]) if row["field"] == "capital")
    assert capital["source_available_count"] == 1
    assert capital["source_missing_count"] == 0
    assert capital["source_coverage_percentage"] == 100
    assert capital["value_coverage_percentage"] == 0


def test_collision_report_preserves_all_source_variants(tmp_path):
    record = CountryRecord(
        page_id=1,
        title_vi="Việt Nam",
        source_url="https://vi.wikipedia.org/wiki/Việt_Nam",
        retrieved_at=datetime.now(UTC),
    )
    write_json(tmp_path / "data/processed/countries.json", [record.model_dump(mode="json")])
    debug = {
        "page_id": 1,
        "canonical_title": "Việt Nam",
        "parse_status": {},
        "normalized_key_collisions": {
            "languages_type": [
                {"raw_key": "languages_type", "raw_value": "Ngôn ngữ thiểu số"},
                {"raw_key": "Languages type", "raw_value": ""},
            ]
        },
    }
    interim = tmp_path / "data/interim/extracted.jsonl"
    interim.parent.mkdir(parents=True, exist_ok=True)
    interim.write_text(json.dumps(debug, ensure_ascii=False) + "\n", "utf-8")
    generate_reports(tmp_path)
    row = read_csv(tmp_path / "data/reports/normalized_key_collisions.csv")[0]
    assert row["occurrence_count"] == "2"
    assert json.loads(row["raw_keys"]) == ["languages_type", "Languages type"]
    assert json.loads(row["raw_values"]) == ["Ngôn ngữ thiểu số", ""]
