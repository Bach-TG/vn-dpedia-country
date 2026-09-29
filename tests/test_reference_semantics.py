"""Offline regressions from the inspected five-page Vietnamese Wikipedia reference set."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from vi_dbpedia_data.extract import extract_page
from vi_dbpedia_data.inspect_infobox import inspect_pages
from vi_dbpedia_data.models import RawPage
from vi_dbpedia_data.utils import load_mapping, load_settings, normalize_key, read_csv

SNIPPETS = yaml.safe_load(
    (Path(__file__).parent / "fixtures/reference_infobox_snippets.yaml").read_text("utf-8")
)


def page(title: str, *, source_title: str | None = None) -> RawPage:
    return RawPage(
        requested_title=title,
        page_id=list(SNIPPETS).index(source_title or title) + 1,
        canonical_title=title,
        source_url="https://vi.wikipedia.org/wiki/Reference",
        wikitext=SNIPPETS[source_title or title],
        retrieved_at=datetime.now(UTC),
    )


def refs(values):
    return [(ref.label_vi, ref.wiki_title) for ref in values]


@pytest.mark.parametrize(
    ("title", "capitals", "population", "area_km2", "currencies", "languages", "codes"),
    [
        (
            "Việt Nam",
            [("Hà Nội", "Hà Nội")],
            102300000,
            331212.0,
            [("Đồng", "Đồng (tiền)")],
            [("Tiếng Việt", "Tiếng Việt")],
            ["+84"],
        ),
        ("Nhật Bản", [("Tokyo", "Tokyo")], 122950000, 377975.0, [("Yên", "Yên Nhật")], [], ["+81"]),
        (
            "Singapore",
            [],
            6110200,
            744.3,
            [("Đô la Singapore", "Đô la Singapore")],
            [
                ("Tiếng Anh", "Tiếng Anh Singapore"),
                ("Tiếng Mã Lai", "Tiếng Mã Lai"),
                ("Tiếng Hoa", "Tiếng Hoa Singapore"),
                ("Tiếng Tamil", "Tiếng Tamil"),
            ],
            ["+65"],
        ),
        (
            "Cộng hòa Nam Phi",
            [
                ("Pretoria", "Pretoria"),
                ("Cape Town", "Cape Town"),
                ("Bloemfontein", "Bloemfontein"),
            ],
            63015904,
            1221037.0,
            [("Rand Nam Phi", "Rand Nam Phi")],
            [
                ("Tiếng Afrikaans", "Tiếng Afrikaans"),
                ("Tiếng Anh", "Tiếng Anh Nam Phi"),
                ("Tiếng Nam Ndebele", "Tiếng Nam Ndebele"),
                ("Tiếng Pedi", "Tiếng Pedi"),
                ("Tiếng Sotho", "Tiếng Sotho"),
                ("Tiếng Tswana", "Tiếng Tswana"),
                ("Ngôn ngữ ký hiệu Nam Phi", "Ngôn ngữ ký hiệu Nam Phi"),
                ("Tiếng Swazi", "Tiếng Swazi"),
                ("Tiếng Venda", "Tiếng Venda"),
                ("Tiếng Xhosa", "Tiếng Xhosa"),
                ("Tiếng Tsonga", "Tiếng Tsonga"),
                ("Tiếng Zulu", "Tiếng Zulu"),
            ],
            ["+27"],
        ),
        (
            "Thụy Sĩ",
            [("Bern", "Bern")],
            9060598,
            41285.0,
            [("Franc Thụy Sĩ", "Franc Thụy Sĩ")],
            [
                ("Tiếng Đức", "Tiếng Đức"),
                ("Pháp", "tiếng Pháp"),
                ("Ý", "tiếng Ý"),
                ("Romansh", "tiếng Romansh"),
            ],
            ["+41"],
        ),
    ],
)
def test_six_canonical_fields_from_reference_snippets(
    title, capitals, population, area_km2, currencies, languages, codes
):
    debug, record = extract_page(page(title), load_settings(), load_mapping())
    assert record is not None
    assert refs(record.capital) == capitals
    assert record.population_total == population
    assert record.area_km2 == area_km2
    assert refs(record.currencies) == currencies
    assert refs(record.official_languages) == languages
    assert record.calling_codes == codes
    for field in (
        "capital",
        "population_total",
        "area_km2",
        "currencies",
        "official_languages",
        "calling_codes",
    ):
        expected = (
            "explicit_none"
            if (title, field) in {("Nhật Bản", "official_languages"), ("Singapore", "capital")}
            else "present"
        )
        assert debug["parse_status"][field] == expected
    assert debug["parse_errors"] == []


def test_explicit_none_is_based_on_source_not_country_name():
    for source_title, field in (("Nhật Bản", "official_languages"), ("Singapore", "capital")):
        debug, record = extract_page(
            page("Không phải tên quốc gia", source_title=source_title),
            load_settings(),
            load_mapping(),
        )
        assert getattr(record, field) == []
        assert debug["parse_status"][field] == "explicit_none"
        assert debug["canonical_source_keys"][field]
        assert debug["field_reasons"][field].startswith("Source explicitly")
    japan, _ = extract_page(page("Nhật Bản"), load_settings(), load_mapping())
    assert any(
        normalize_key(key) == "recognised_national_languages" for key in japan["unmapped_keys"]
    )


def test_reference_normalized_key_collision_preserves_blank_and_nonblank():
    debug, _ = extract_page(page("Việt Nam"), load_settings(), load_mapping())
    collision = debug["normalized_key_collisions"]["languages_type"]
    assert len(collision) == 2
    assert [normalize_key(item["raw_key"]) for item in collision] == [
        "languages_type",
        "languages_type",
    ]
    assert collision[0]["raw_value"].strip() == "Ngôn ngữ thiểu số"
    assert collision[1]["raw_value"].strip() == ""


def test_duplicate_mapped_normalized_keys_are_resolved_or_flagged():
    raw = "{{Infobox country|Capital= |capital=[[Bern]]}}"
    debug, record = extract_page(
        page("Thụy Sĩ").model_copy(update={"wikitext": raw}), load_settings(), load_mapping()
    )
    assert [(ref.label_vi, ref.wiki_title) for ref in record.capital] == [("Bern", "Bern")]
    assert debug["parse_status"]["capital"] == "present"
    assert len(debug["normalized_key_collisions"]["capital"]) == 2
    assert len(debug["canonical_source_occurrences"]["capital"]) == 2
    assert debug["canonical_raw_values"]["capital"] == "[[Bern]]"

    conflicting = "{{Infobox country|Capital=[[Pretoria]]|capital=[[Bern]]}}"
    debug, record = extract_page(
        page("Thụy Sĩ").model_copy(update={"wikitext": conflicting}),
        load_settings(),
        load_mapping(),
    )
    assert record.capital == []
    assert debug["parse_status"]["capital"] == "ambiguous"
    assert len(debug["normalized_key_collisions"]["capital"]) == 2

    blank = "{{Infobox country|Capital= |capital= }}"
    debug, record = extract_page(
        page("Thụy Sĩ").model_copy(update={"wikitext": blank}), load_settings(), load_mapping()
    )
    assert record.capital == []
    assert debug["parse_status"]["capital"] == "source_missing"
    assert len(debug["canonical_source_keys"]["capital"]) == 2
    assert debug["field_reasons"]["capital"] == "Configured source parameter is blank"


def test_infobox_template_counts_and_duplicate_key_statistics(tmp_path):
    inspect_pages([page("Việt Nam")], load_settings(), tmp_path)
    template = read_csv(tmp_path / "data/reports/infobox_templates.csv")[0]
    assert template["all_template_count"] != template["selected_infobox_parameter_count"]
    assert int(template["selected_infobox_parameter_count"]) == 8
    frequency = {
        row["normalized_key"]: row
        for row in read_csv(tmp_path / "data/reports/infobox_key_frequency.csv")
    }
    assert frequency["languages_type"]["occurrence_count"] == "2"
    assert frequency["languages_type"]["page_count"] == "1"
