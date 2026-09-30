from datetime import UTC, datetime

from vi_dbpedia_data.models import CountryRecord, ResourceRef
from vi_dbpedia_data.reports import generate_reports
from vi_dbpedia_data.sanity import sanity_issues
from vi_dbpedia_data.utils import read_csv, write_json


def record(**values):
    return CountryRecord.model_validate(
        {
            "page_id": 7,
            "title_vi": "Nguồn",
            "source_url": "https://vi.wikipedia.org/wiki/Nguồn",
            "retrieved_at": datetime.now(UTC),
            **values,
        }
    )


def test_sanity_flags_without_modifying_processed_record():
    country = record(
        population_total=-1,
        area_km2=50_000_000,
        abstract_vi="Raw {{value}}",
        capital=[
            ResourceRef(label_vi="A", wiki_title="A"),
            ResourceRef(label_vi="A", wiki_title="A"),
            ResourceRef(label_vi=" ", wiki_title="Image:Badge.svg"),
        ],
        official_languages=[ResourceRef(label_vi="[[Raw]]", wiki_title="{{template}}")],
        calling_codes=["+7-6xx", "nonsense"],
    )
    values = country.model_dump(mode="json")
    flagged = sanity_issues([country])
    categories = {issue["category"] for issue in flagged}
    assert {
        "nonpositive_number",
        "implausible_magnitude_review",
        "duplicate_resource_ref",
        "empty_resource_label",
        "unresolved_markup",
        "file_as_resource_target",
        "malformed_calling_code",
        "calling_code_wildcard_review",
    } <= categories
    assert country.model_dump(mode="json") == values
    assert any(issue["canonical_field"] == "abstract_vi" for issue in flagged)


def test_sanity_accepts_small_country_and_populated_resource():
    assert (
        sanity_issues(
            [
                record(
                    population_total=500,
                    area_km2=0.49,
                    capital=[ResourceRef(label_vi="X", wiki_title="X")],
                    calling_codes=["+1-268"],
                )
            ]
        )
        == []
    )


def test_sanity_csv_and_summary_are_generated_locally(tmp_path):
    country = record(population_total=3_000_000_000)
    write_json(tmp_path / "data/processed/countries.json", [country.model_dump(mode="json")])
    summary = generate_reports(tmp_path)
    issues = read_csv(tmp_path / "data/reports/sanity_issues.csv")
    assert summary["sanity_issue_count"] == len(issues) == 1
    assert summary["sanity_issue_categories"] == {"implausible_magnitude_review": 1}
    assert issues[0]["canonical_field"] == "population_total"
