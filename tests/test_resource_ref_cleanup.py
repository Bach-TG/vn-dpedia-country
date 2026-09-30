from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from vi_dbpedia_data.extract import extract_page
from vi_dbpedia_data.markup import is_file_target, normalize_resource_text
from vi_dbpedia_data.models import RawPage, ResourceRef
from vi_dbpedia_data.normalize import resources
from vi_dbpedia_data.sanity import sanity_issues
from vi_dbpedia_data.utils import load_mapping, load_settings

SNIPPETS = yaml.safe_load(
    (Path(__file__).parent / "fixtures/resource_ref_cleanup_snippets.yaml").read_text("utf-8")
)


def page(value: str, field: str) -> RawPage:
    raw_key = {
        "currencies": "currency",
        "capital": "capital",
        "official_languages": "official_languages",
    }[field]
    return RawPage(
        requested_title="Kiểm thử",
        page_id=101,
        canonical_title="Kiểm thử",
        source_url="https://vi.wikipedia.org/wiki/Test",
        retrieved_at=datetime.now(UTC),
        wikitext="{{Infobox country|" + raw_key + "=" + value + "}}",
    )


@pytest.mark.parametrize(
    ("country", "field", "expected"),
    [
        ("Ukraina", "capital", [("Kyiv", "Kyiv")]),
        ("Thổ Nhĩ Kỳ", "currencies", [("Lira Thổ Nhĩ Kỳ", "Lira Thổ Nhĩ Kỳ")]),
        ("Đức", "currencies", [("Euro", "Euro")]),
        ("Armenia", "currencies", [("Dram Armenian", "Dram Armenian")]),
        ("Samoa", "currencies", [("Tālā", "Tālā")]),
        ("Nhà nước Palestine", "capital", [("Jerusalem", "Jerusalem"), ("Ramallah", "Ramallah")]),
        (
            "Colombia",
            "official_languages",
            [("Tiếng Tây Ban Nha", "Tiếng Tây Ban Nha"), ("Tiếng Anh", "Tiếng Anh")],
        ),
        ("Vương quốc Liên hiệp Anh và Bắc Ireland", "currencies", [("Bảng Anh", "Bảng Anh")]),
    ],
)
def test_annotated_resource_values_keep_only_semantic_entities(country, field, expected):
    raw = SNIPPETS[country][field]
    refs = resources(raw, field=field)
    assert [(ref.label_vi, ref.wiki_title) for ref in refs] == expected
    debug, country_record = extract_page(page(raw, field), load_settings(), load_mapping())
    assert [(ref.label_vi, ref.wiki_title) for ref in getattr(country_record, field)] == expected
    assert debug["parse_status"][field] == "present"


@pytest.mark.parametrize(
    ("country", "field", "expected"),
    [
        ("Pháp", "currencies", ["Euro", "Franc CFP"]),
        ("Cộng hòa Nam Phi", "capital", ["Pretoria", "Cape Town", "Bloemfontein"]),
        ("Sri Lanka", "capital", ["Sri Jayawardenepura Kotte", "Colombo"]),
        ("Panamá", "currencies", ["Balboa", "Đô la Mỹ"]),
        ("Nhà nước Palestine", "capital", ["Jerusalem", "Ramallah"]),
    ],
)
def test_legitimate_multi_resource_values_are_preserved(country, field, expected):
    refs = resources(SNIPPETS[country][field], field=field)
    assert [ref.label_vi for ref in refs] == expected
    if country == "Panamá":
        assert refs[0].wiki_title is None


@pytest.mark.parametrize(
    "target",
    [
        "File:flag.svg",
        "Image:flag.svg",
        "Tập tin:flag.svg",
        "Tập tin :flag.svg",
        "Hình:flag.svg",
        "Hình :flag.svg",
        " hình :flag.svg",
    ],
)
def test_file_namespaces_are_recognized_with_spaces_and_nbsp(target):
    assert is_file_target(target)
    assert resources(f"[[{target}|30px]] [[Kyiv]]", field="capital") == [
        ResourceRef(label_vi="Kyiv", wiki_title="Kyiv")
    ]


def test_html_entities_decode_without_losing_vietnamese_accents():
    assert normalize_resource_text("Bảng&nbsp;Anh") == "Bảng Anh"
    assert resources("[[Bảng&nbsp;Anh]]", field="currencies") == [
        ResourceRef(label_vi="Bảng Anh", wiki_title="Bảng Anh")
    ]
    assert resources("€", field="currencies") == []


def test_sanity_flags_resource_quality_heuristics_without_mutating_record():
    from vi_dbpedia_data.models import CountryRecord

    record = CountryRecord(
        page_id=1,
        title_vi="Test",
        source_url="https://vi.wikipedia.org/wiki/Test",
        retrieved_at=datetime.now(UTC),
        capital=[
            ResourceRef(label_vi="30px", wiki_title="Tập tin :Flag.svg"),
            ResourceRef(label_vi="công nhận giới hạn", wiki_title="Vị thế của Jerusalem"),
        ],
        currencies=[ResourceRef(label_vi="€", wiki_title="Euro sign")],
        official_languages=[
            ResourceRef(label_vi="Thành phố X", wiki_title="X City"),
            ResourceRef(label_vi="Bảng&nbsp;Anh", wiki_title=None),
        ],
    )
    unchanged = record.model_dump(mode="json")
    issues = sanity_issues([record])
    categories = {row["category"] for row in issues}
    assert {
        "file_as_resource_target",
        "pixel_size_resource_label",
        "currency_symbol_label",
        "currency_sign_target",
        "capital_status_qualifier",
        "language_geographic_scope",
        "unresolved_html_entity",
    } <= categories
    assert record.model_dump(mode="json") == unchanged
