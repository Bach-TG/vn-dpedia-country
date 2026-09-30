import json
from datetime import UTC, datetime

from vi_dbpedia_data.extract import extract_page, process
from vi_dbpedia_data.inspect_infobox import inspect, inspect_pages, select_infobox
from vi_dbpedia_data.models import RawPage
from vi_dbpedia_data.reports import generate_reports
from vi_dbpedia_data.utils import (
    ROOT,
    load_mapping,
    load_settings,
    read_csv,
    read_json,
    write_csv,
    write_json,
)


def raw(title, page_id, wikitext, english="South Africa"):
    return RawPage(
        requested_title=title,
        page_id=page_id,
        canonical_title=title,
        source_url=f"https://vi.wikipedia.org/wiki/{title}",
        extract="Intro",
        wikitext=wikitext,
        revision_id=12,
        revision_timestamp="2026-01-01T00:00:00Z",
        pageprops_wikidata_id="Q258",
        langlinks={"en": english},
        retrieved_at=datetime.now(UTC),
    )


def test_multi_capital_and_languages_preserve_raw_values():
    page = raw(
        "Nam Phi",
        2,
        """{{Thông tin quốc gia
|capital = [[Pretoria]]<br>[[Cape Town]]<br>[[Bloemfontein]]
|population_total = 60.000.000
|area_total_km2 = 1.221.037
|official_languages = [[Tiếng Đức]], [[Tiếng Pháp]], [[Tiếng Ý]]
|calling_code = +27
|unmapped_observation = meaningful
}}""",
    )
    interim, record = extract_page(page, load_settings(), load_mapping())
    assert [capital.label_vi for capital in record.capital] == [
        "Pretoria",
        "Cape Town",
        "Bloemfontein",
    ]
    assert [lang.label_vi for lang in record.official_languages] == [
        "Tiếng Đức",
        "Tiếng Pháp",
        "Tiếng Ý",
    ]
    assert record.population_total == 60000000
    assert record.area_km2 == 1221037
    assert record.english_title == "South Africa"
    assert interim["canonical_raw_values"]["capital"].strip().startswith("[[Pretoria]]")
    assert interim["parse_status"]["capital"] == "present"
    assert "unmapped_observation " in interim["unmapped_keys"]
    assert "capital " in interim["raw_infobox"]


def test_ambiguous_alias_values_and_template_selection():
    settings = load_settings()
    page = raw("X", 3, "{{Infobox country|capital=[[A]]|thủ_đô=[[B]]|population_total=??}}")
    debug, record = extract_page(page, settings, load_mapping())
    assert record.capital == []
    assert debug["parse_status"]["capital"] == "ambiguous"
    assert debug["canonical_raw_values"]["capital"] == ["[[A]]", "[[B]]"]
    assert debug["parse_status"]["population_total"] == "parse_failed"
    assert (
        select_infobox(
            "{{Infobox sovereign country|capital=[[A]]|area_km2=4|currency=[[X]]"
            "|calling_code=+1|population_estimate=6}}",
            settings,
        )[1]
        == "name_heuristic"
    )
    assert select_infobox("{{Taxobox|foo=bar}}", settings)[1] == "not_found"


def test_explicit_absences_are_not_parse_failures():
    page = raw(
        "Singapore",
        4,
        "{{Infobox country|capital='''Singapore'''"
        "{{efn|Singapore không có thủ đô chính thức}} ([[Thành bang]])}}",
    )
    interim, record = extract_page(page, load_settings(), load_mapping())
    assert record.capital == []
    assert interim["parse_status"]["capital"] == "explicit_none"
    page = raw("Nhật Bản", 5, "{{Infobox country|official_languages=Không có<ref>x</ref>}}")
    interim, record = extract_page(page, load_settings(), load_mapping())
    assert record.official_languages == []
    assert interim["parse_status"]["official_languages"] == "explicit_none"


def test_selected_manifest_drives_inspection_process_and_reports(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "country_mapping.yaml").write_text(
        (ROOT / "config/country_mapping.yaml").read_text("utf-8"), encoding="utf-8"
    )
    pages = [
        raw(
            "Nam Phi", 2, "{{Infobox country|capital=[[Pretoria]]|population_total=99|area_km2=9}}"
        ),
        raw(
            "Thụy Sĩ",
            3,
            "{{Thông tin quốc gia|official_languages=[[Tiếng Đức]], [[Tiếng Pháp]]}}",
            "Switzerland",
        ),
    ]
    for page in pages:
        write_json(tmp_path / f"data/raw/pages/{page.page_id}.json", page.model_dump(mode="json"))
    write_csv(
        tmp_path / "data/raw/collection_manifest.csv",
        [
            {
                "requested_title": page.canonical_title,
                "page_id": page.page_id,
                "canonical_title": page.canonical_title,
                "candidate_wikidata_id": "Q258",
                "collection_status": "collected",
                "raw_file_path": f"data/raw/pages/{page.page_id}.json",
                "error": "",
            }
            for page in pages
        ],
        [
            "requested_title",
            "page_id",
            "canonical_title",
            "candidate_wikidata_id",
            "collection_status",
            "raw_file_path",
            "error",
        ],
    )
    write_json(
        tmp_path / "data/reference/pages.json",
        [{"page_id": 3, "raw_file_path": "data/raw/pages/3.json"}],
    )
    stats = inspect_pages(pages, load_settings(), tmp_path)
    assert stats["selected"] == 2
    assert [
        row["country_title"]
        for row in read_csv(tmp_path / "data/reports/reference_infobox_keys.csv")
    ] == ["Thụy Sĩ"]
    interim, processed = process(load_settings(), tmp_path)
    assert len(interim) == len(processed) == 2
    assert len(read_json(tmp_path / "data/processed/countries.json")) == 2
    csv_rows = read_csv(tmp_path / "data/processed/countries.csv")
    assert json.loads(csv_rows[1]["official_languages"])[0]["label_vi"] == "Tiếng Đức"
    summary = generate_reports(tmp_path)
    assert summary["processed_count"] == 2
    assert summary["with_english_link"] == 2
    assert summary["warning_count"] == 2
    assert summary["duplicate_page_ids"] == 0
    assert len(read_csv(tmp_path / "data/reports/field_coverage.csv")) == 10
    selected = tmp_path / "data/raw/collection_manifest.csv"
    manifest_rows = read_csv(selected)
    write_csv(selected, manifest_rows[:1], list(manifest_rows[0]))
    assert inspect(load_settings(), tmp_path)["attempted"] == 1
    assert inspect(load_settings(), tmp_path, all_available=True)["attempted"] == 2
    assert inspect(load_settings(), tmp_path, reference_only=True)["attempted"] == 1
