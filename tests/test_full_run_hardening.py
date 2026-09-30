"""Offline generalizations from the 197-page run; snippets retain relevant markup."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from vi_dbpedia_data.extract import extract_page
from vi_dbpedia_data.inspect_infobox import select_infobox
from vi_dbpedia_data.markup import strip_annotations
from vi_dbpedia_data.models import RawPage
from vi_dbpedia_data.normalize import area, calling_codes, population, resources
from vi_dbpedia_data.utils import ROOT, load_mapping, load_settings, read_json

DATA = yaml.safe_load(
    (Path(__file__).parent / "fixtures/full_run_markup_snippets.yaml").read_text("utf-8")
)


def page(field: str, value: str) -> RawPage:
    return RawPage(
        page_id=999,
        requested_title="Tình huống kiểm thử",
        canonical_title="Tình huống kiểm thử",
        source_url="https://vi.wikipedia.org/wiki/Test",
        retrieved_at=datetime.now(UTC),
        wikitext="{{Infobox country|" + field + "=" + value + "}}",
    )


def labels(refs):
    return [item.label_vi for item in refs]


def test_shared_ast_cleanup_drops_annotations_without_recursing_into_them():
    source = "[[Berlin]]<small>{{efn-ur|[[Bonn]]}}</small>{{NoteTag|[[Other city]]}}"
    source += "<ref>[[Citation]]</ref><!-- [[Comment]] -->{{flagicon image|seal.svg|link=Other}}"
    assert "[[Berlin]]" in strip_annotations(source)
    assert all(
        name not in strip_annotations(source)
        for name in ("Bonn", "Other city", "Citation", "Comment", "link=Other")
    )
    assert "{{#property:p38}}" in strip_annotations("[[{{#property:p38}}]]")


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Đức", ["Berlin"]),
        ("Hoa Kỳ", ["Washington, D.C."]),
        ("Kosovo", ["Priština"]),
        ("Cộng hòa Dân chủ Congo", ["Kinshasa"]),
        ("Thái Lan", ["Băng Cốc"]),
        ("Sri Lanka", ["Sri Jayawardenepura Kotte", "Colombo"]),
        ("Thành Vatican", ["Thành Vatican"]),
    ],
)
def test_capital_resources_keep_direct_values(title, expected):
    parsed = resources(DATA["capital"][title])
    assert labels(parsed) == expected
    if title == "Thành Vatican":
        assert parsed[0].wiki_title is None
    else:
        assert all(item.wiki_title for item in parsed)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Pháp", ["Euro", "Franc CFP"]),
        ("Albania", ["Lek"]),
        ("Panamá", ["Balboa", "Đô la Mỹ"]),
    ],
)
def test_currency_items_preserve_only_direct_resources(title, expected):
    values = resources(DATA["currencies"][title])
    assert labels(values) == expected
    if title == "Panamá":
        assert values[0].wiki_title is None
        assert values[1].wiki_title == "Đô la Mỹ"


@pytest.mark.parametrize(
    "raw",
    [
        "[[Euro]] ([[Euro|€]])",
        "[[Rupee Sri Lanka]] ([[Rupee Sri Lanka|Rs]])",
    ],
)
def test_repeated_wiki_target_keeps_first_resource_label(raw):
    refs = resources(raw)
    assert len(refs) == 1
    assert refs[0].label_vi == refs[0].wiki_title


def test_template_only_currency_and_multi_scope_currency_stay_unresolved():
    raw = DATA["currencies"]["Hoa Kỳ"]
    assert resources(raw) == []
    debug, record = extract_page(page("currency", raw), load_settings(), load_mapping())
    assert record.currencies == []
    assert debug["parse_status"]["currencies"] == "parse_failed"
    assert "Unresolved template" in debug["field_reasons"]["currencies"]

    raw = DATA["currencies"]["Zimbabwe"]
    debug, record = extract_page(page("currency", raw), load_settings(), load_mapping())
    assert record.currencies == []
    assert debug["parse_status"]["currencies"] == "ambiguous"
    assert "de jure" in debug["field_reasons"]["currencies"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Na Uy", ["Tiếng Na Uy", "Nhóm ngôn ngữ Sámi"]),
        ("Bắc Macedonia", ["Tiếng Macedonia", "Tiếng Albania"]),
        ("Cộng hòa Ireland", ["Tiếng Ireland", "Tiếng Anh"]),
        ("Tây Ban Nha", ["Tiếng Tây Ban Nha"]),
        ("Ý", ["Tiếng Ý"]),
        ("Madagascar", ["Tiếng Malagasy", "Tiếng Pháp"]),
        ("Rwanda", ["Tiếng Kinyarwanda", "Tiếng Anh", "Tiếng Pháp", "Tiếng Swahili"]),
        ("Palau", ["Tiếng Palau", "Tiếng Anh"]),
        ("Guinea Xích Đạo", ["Tiếng Tây Ban Nha", "Tiếng Pháp", "Tiếng Bồ Đào Nha"]),
    ],
)
def test_official_language_items_exclude_annotation_links(title, expected):
    refs = resources(DATA["official_languages"][title])
    assert labels(refs) == expected
    if title == "Guinea Xích Đạo":
        assert all(item.wiki_title is None for item in refs)


@pytest.mark.parametrize("title", ["Argentina", "Mauritius"])
def test_legal_status_language_distinction_is_ambiguous(title):
    debug, record = extract_page(
        page("official_languages", DATA["official_languages"][title]),
        load_settings(),
        load_mapping(),
    )
    assert record.official_languages == []
    assert debug["parse_status"]["official_languages"] == "ambiguous"


def test_collapsible_language_semantics_are_not_blindly_flattened():
    debug, record = extract_page(
        page("official_languages", DATA["official_languages"]["Haiti"]),
        load_settings(),
        load_mapping(),
    )
    assert record.official_languages == []
    assert debug["parse_status"]["official_languages"] == "ambiguous"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("[[Số điện thoại ở Pháp|+33]]{{efn-ur|Các đảo có +590 và +596}}", ["+33"]),
        ("[[Số điện thoại ở Ý|+39]]<sup>c</sup>", ["+39"]),
        ("+45³", ["+45"]),
        ("[[Mã vùng 268|+1-268]]", ["+1-268"]),
        ("1 758", ["+1-758"]),
        ("1 784", ["+1-784"]),
        ("[[Mã số điện thoại San Marino|+378]] (+39 0 549 khi gọi qua Ý)", ["+378"]),
        ("[[North American Numbering Plan|+1]] [[Area code 246|-246]]", ["+1-246"]),
        ("+7-6xx, +7-7xx", ["+7-6xx", "+7-7xx"]),
        ("[[Telephone numbers in Luxembourg|352]]", ["+352"]),
    ],
)
def test_calling_code_direct_values(raw, expected):
    assert calling_codes(raw) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Malta", 519562),
        ("Serbia", 6567783),
        ("Palau", 17663),
    ],
)
def test_population_wrapped_single_number(title, expected):
    assert population(DATA["population"][title]) == expected


@pytest.mark.parametrize("title", ["Nga", "Eritrea"])
def test_population_alternatives_remain_ambiguous(title):
    debug, record = extract_page(
        page("population_estimate", DATA["population"][title]), load_settings(), load_mapping()
    )
    assert record.population_total is None
    assert debug["parse_status"]["population_total"] == "ambiguous"


@pytest.mark.parametrize("title", ["Ấn Độ", "Saint Kitts và Nevis"])
def test_template_only_population_not_invented(title):
    debug, record = extract_page(
        page("population_estimate", DATA["population"][title]), load_settings(), load_mapping()
    )
    assert record.population_total is None
    assert debug["parse_status"]["population_total"] == "parse_failed"
    assert "Unresolved template" in debug["field_reasons"]["population_total"]


def test_area_superscript_and_range():
    assert area(DATA["area"]["Đan Mạch"]) == 42931.0
    assert area("331.212 km<sup>2</sup>") == 331212.0
    debug, record = extract_page(
        page("area_km2", DATA["area"]["Israel"]), load_settings(), load_mapping()
    )
    assert record.area_km2 is None
    assert debug["parse_status"]["area_km2"] == "ambiguous"


def test_navigation_heuristic_rejected_and_country_template_recovery():
    settings = load_settings()
    assert select_infobox("{{Quốc gia Bắc Mỹ}}", settings)[1] == "not_found"
    recoverable = "{{Infobox country\n| capital = [[Ottawa]]\n| population_estimate = 1000000\n"
    recoverable += "| area_km2 = 9984670\n| currency = [[Đô la Canada]]\n"
    recoverable += "| official_languages = [[Tiếng Anh]]\n| calling_code = +1\n}}"
    assert select_infobox(recoverable, settings)[0] is not None


@pytest.mark.parametrize(("page_id", "expected"), [(797, "Ottawa"), (33, "Stockholm")])
def test_saved_raw_lead_infobox_recovery_when_available(page_id, expected):
    """Local raw-cache regression; fresh checkouts still run every fixture test."""
    raw = ROOT / f"data/raw/pages/{page_id}.json"
    if not raw.exists():
        pytest.skip("Ignored local raw page is not available")
    page_data = RawPage.model_validate(read_json(raw))
    debug, record = extract_page(page_data, load_settings(), load_mapping())
    assert debug["template_selection"] == "recovered_lead_infobox"
    assert [ref.label_vi for ref in record.capital] == [expected]
