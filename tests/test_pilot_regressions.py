"""Representative offline snippets from the downloaded 20-country pilot."""

from datetime import UTC, datetime
from pathlib import Path

import yaml

from vi_dbpedia_data.extract import extract_page
from vi_dbpedia_data.inspect_infobox import select_infobox
from vi_dbpedia_data.models import RawPage
from vi_dbpedia_data.utils import load_mapping, load_settings

SNIPPETS = yaml.safe_load(
    (Path(__file__).parent / "fixtures/pilot_infobox_snippets.yaml").read_text("utf-8")
)


def page(title: str, *, candidate: bool = True) -> RawPage:
    return RawPage(
        page_id=list(SNIPPETS).index(title) + 100,
        requested_title=title,
        canonical_title=title,
        source_url="https://vi.wikipedia.org/wiki/Reference",
        wikitext=SNIPPETS[title],
        candidate_wikidata_id="Q55" if candidate else None,
        retrieved_at=datetime.now(UTC),
    )


def test_decorated_capitals_keep_only_top_level_city_links():
    for title, expected in (("Malaysia", "Kuala Lumpur"), ("Brasil", "Brasília")):
        debug, record = extract_page(page(title), load_settings(), load_mapping())
        assert [(ref.label_vi, ref.wiki_title) for ref in record.capital] == [(expected, expected)]
        assert debug["parse_status"]["capital"] == "present"
        assert debug["parse_errors"] == []


def test_contextual_official_language_mapping_is_source_driven():
    for title, expected in (("Malaysia", "Tiếng Malaysia"), ("Brasil", "Tiếng Bồ Đào Nha")):
        debug, record = extract_page(page(title), load_settings(), load_mapping())
        assert [ref.label_vi for ref in record.official_languages] == [expected]
        assert debug["parse_status"]["official_languages"] == "present"
        assert debug["field_provenance"]["official_languages"]["selection_method"] == (
            "contextual_official_languages"
        )
        assert any(
            "languages_type" in item["raw_key"]
            for item in debug["field_provenance"]["official_languages"]["type_occurrences"]
        )
        assert any(
            "languages" in key for key in debug["canonical_source_keys"]["official_languages"]
        )


def test_direct_language_field_outranks_contextual_and_nonofficial_type_rejected():
    direct = (
        "{{Infobox country|official_languages=Không có|languages_type="
        "Ngôn ngữ chính thức|languages=[[Tiếng Nhật]]}}"
    )
    debug, record = extract_page(
        page("Malaysia").model_copy(update={"wikitext": direct}), load_settings(), load_mapping()
    )
    assert record.official_languages == []
    assert debug["parse_status"]["official_languages"] == "explicit_none"
    assert debug["field_provenance"]["official_languages"]["selection_method"] == "direct_alias"

    debug, record = extract_page(page("Đài Loan"), load_settings(), load_mapping())
    assert record.official_languages == []
    assert debug["parse_status"]["official_languages"] == "source_missing"
    assert debug["field_provenance"]["official_languages"]["selection_method"] == (
        "contextual_fallback_considered"
    )

    recognised = "{{Infobox country|languages_type=Ngôn ngữ được công nhận chính thức"
    recognised += "|languages=[[Tiếng địa phương]]}}"
    debug, record = extract_page(
        page("Malaysia").model_copy(update={"wikitext": recognised}),
        load_settings(),
        load_mapping(),
    )
    assert record.official_languages == []
    assert debug["parse_status"]["official_languages"] == "source_missing"


def test_population_census_fallback_when_estimate_absent_or_blank():
    for title, value, year in (("Cabo Verde", 527326, "2025"), ("Iraq", 46118793, "2024")):
        debug, record = extract_page(page(title), load_settings(), load_mapping())
        assert record.population_total == value
        assert debug["parse_status"]["population_total"] == "present"
        provenance = debug["field_provenance"]["population_total"]
        assert provenance["source_type"] == "census"
        assert "population_census" in provenance["selected_source_keys"][0]
        assert "population_census_year" in provenance["year_source_key"]
        assert provenance["year_source_value"].strip() == year
    debug, record = extract_page(page("Cabo Verde"), load_settings(), load_mapping())
    assert record.calling_codes == []
    assert debug["parse_status"]["calling_codes"] == "source_missing"


def test_nonempty_estimate_preferred_over_census_even_if_ambiguous():
    debug, record = extract_page(page("Gruzia"), load_settings(), load_mapping())
    assert record.population_total is None
    assert debug["parse_status"]["population_total"] == "ambiguous"
    assert "3694608" in debug["field_reasons"]["population_total"]
    assert "4012104" in debug["field_reasons"]["population_total"]
    assert debug["field_provenance"]["population_total"]["source_type"] == "estimate"
    assert debug["parse_errors"] == ["population_total: ambiguous values [3694608, 4012104]"]


def test_candidate_scoped_political_division_infobox_maps_six_fields():
    settings = load_settings()
    assert select_infobox(SNIPPETS["Hà Lan"], settings)[1] == "not_found"
    assert (
        select_infobox(SNIPPETS["Hà Lan"], settings, country_candidate=True)[1]
        == "candidate_template_alias"
    )
    debug, record = extract_page(page("Hà Lan"), settings, load_mapping())
    assert debug["selected_template"] == "Infobox political division"
    assert debug["template_selection"] == "candidate_template_alias"
    assert [ref.label_vi for ref in record.capital] == ["Amsterdam"]
    assert record.population_total == 18420100
    assert record.area_km2 == 41865.0
    assert [ref.label_vi for ref in record.currencies] == ["Euro", "đô la Mỹ"]
    assert [ref.label_vi for ref in record.official_languages] == ["Tiếng Hà Lan"]
    assert record.calling_codes == ["+31", "+599"]
    assert all(status == "present" for status in debug["parse_status"].values())
    assert debug["field_provenance"]["population_total"]["source_type"] == "estimate"

    debug, record = extract_page(page("Hà Lan", candidate=False), settings, load_mapping())
    assert debug["template_selection"] == "not_found"
    assert record.capital == []
