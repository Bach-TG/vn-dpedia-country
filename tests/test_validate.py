from datetime import UTC, datetime

from vi_dbpedia_data.models import CandidateCountry, CountryRecord, ResourceRef
from vi_dbpedia_data.validate import validate_records


def record(page_id=1, title="Việt Nam", **changes):
    data = {
        "page_id": page_id,
        "title_vi": title,
        "abstract_vi": "intro",
        "source_url": "https://vi.wikipedia.org/wiki/Việt_Nam",
        "retrieved_at": datetime.now(UTC),
        "wikidata_id": "Q881",
        "capital": [ResourceRef(label_vi="Hà Nội")],
        "population_total": 100,
        "area_km2": 50.0,
        "currencies": [ResourceRef(label_vi="đồng")],
        "official_languages": [ResourceRef(label_vi="Tiếng Việt")],
        "calling_codes": ["+84"],
        "english_title": "Vietnam",
        "english_wikipedia_url": "https://en.wikipedia.org/wiki/Vietnam",
        "english_dbpedia_candidate": "http://dbpedia.org/resource/Vietnam",
    }
    return CountryRecord.model_validate({**data, **changes})


def test_duplicate_page_ids_and_titles():
    results = validate_records([record(), record(title="Việt Nam")])
    assert all(result.status == "invalid" for result in results)
    assert all("Duplicate page ID" in " ".join(result.reasons) for result in results)
    assert all("Duplicate canonical title" in " ".join(result.reasons) for result in results)
    other = validate_records([record(1), record(2)])
    assert all("Duplicate canonical title" in " ".join(result.reasons) for result in other)


def test_negative_values_are_reported_not_discarded():
    result = validate_records([record(population_total=-1, area_km2=-1.2)])[0]
    assert result.status == "invalid"
    assert "Population must be positive" in result.reasons
    assert "Area must be positive" in result.reasons


def test_qid_mismatch_warning_and_link_inconsistency():
    manifest = [
        {
            "page_id": "1",
            "candidate_wikidata_id": "Q999",
            "canonical_title": "Việt Nam",
            "collection_status": "collected",
        }
    ]
    result = validate_records([record()], manifest=manifest)[0]
    assert result.status == "warning"
    assert any("QID mismatch" in reason for reason in result.reasons)
    result = validate_records([record(english_dbpedia_candidate="wrong")])[0]
    assert result.status == "invalid"


def test_wikidata_english_hint_is_only_a_crosscheck():
    candidate = CandidateCountry(
        wikidata_id="Q881",
        title_vi="Việt Nam",
        english_title_hint="Other title",
        discovery_method="test",
    )
    manifest = [{"page_id": "1", "candidate_wikidata_id": "Q881", "collection_status": "collected"}]
    result = validate_records([record()], manifest=manifest, candidates=[candidate])[0]
    assert result.status == "warning"
    assert any("sitelink hint" in reason for reason in result.reasons)
    assert (
        record().english_title == "Vietnam"
    )  # hint never substitutes for the vi interlanguage title


def test_failed_collection_is_invalid():
    result = validate_records(
        [],
        manifest=[{"requested_title": "Japan", "collection_status": "failed", "error": "timeout"}],
    )[0]
    assert result.status == "invalid"
    assert "timeout" in result.reasons


def test_explicit_none_is_valid_while_missing_and_failed_source_warn():
    explicit = {
        "page_id": 1,
        "parse_status": {"official_languages": "explicit_none"},
        "field_reasons": {"official_languages": "Source explicitly states there is none"},
    }
    result = validate_records([record(official_languages=[])], interim=[explicit])[0]
    assert result.status == "valid"
    assert result.reasons == []

    missing = {"page_id": 1, "parse_status": {"official_languages": "source_missing"}}
    result = validate_records([record(official_languages=[])], interim=[missing])[0]
    assert result.status == "warning"
    assert "Source missing official_languages" in result.reasons

    failed = {
        "page_id": 1,
        "parse_status": {"official_languages": "parse_failed"},
        "parse_errors": ["official_languages: cannot parse template"],
    }
    result = validate_records([record(official_languages=[])], interim=[failed])[0]
    assert result.status == "warning"
    assert "Parse failed official_languages" in result.reasons
