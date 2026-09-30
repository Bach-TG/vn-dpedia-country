from datetime import UTC, datetime
from pathlib import Path

import yaml

from vi_dbpedia_data.extract import extract_page
from vi_dbpedia_data.models import CountryRecord, RawPage
from vi_dbpedia_data.normalize import area, resources
from vi_dbpedia_data.sanity import sanity_issues
from vi_dbpedia_data.utils import load_mapping, load_settings

FIXTURE = yaml.safe_load(
    (Path(__file__).parent / "fixtures/monaco_semantics.yaml").read_text("utf-8")
)


def test_area_uses_only_unambiguous_infobox_unit_crosscheck():
    assert area("2,084", sq_mi_raw="0,805") == 2.084
    assert area("2.084", sq_mi_raw="0.805") == 2.084
    assert area("41.285") == 41285.0
    assert area("41.285", sq_mi_raw="15.940") == 41285.0  # sq mi also ambiguous
    assert area("744.3") == 744.3
    assert area("2,831", sq_mi_raw="1,093") == 2831.0
    assert area("2,035", sq_mi_raw="719") == 2035.0


def test_monaco_source_mapped_without_country_identity_rule():
    page = RawPage(
        page_id=17,
        requested_title="Trang bất kỳ",
        canonical_title="Trang bất kỳ",
        source_url="https://vi.wikipedia.org/wiki/Test",
        wikitext=FIXTURE["wikitext"],
        extract=FIXTURE["abstract"],
        retrieved_at=datetime.now(UTC),
    )
    debug, record = extract_page(page, load_settings(), load_mapping())
    assert record.area_km2 == 2.084
    assert [(ref.label_vi, ref.wiki_title) for ref in record.official_languages] == [
        ("Tiếng Pháp", "Tiếng Pháp")
    ]
    assert "area_sq_mi" in debug["field_provenance"]["area_km2"]["crosscheck_sq_mi"]["raw_key"]
    assert debug["parse_status"]["area_km2"] == "present"
    assert debug["parse_status"]["official_languages"] == "present"
    assert resources("[[Tiếng Đức]], [[tiếng Pháp]]", field="official_languages") != []


def test_abstract_qa_flags_x1000_discrepancy_but_never_corrects_it():
    def record(value, *, abstract=FIXTURE["abstract"]):
        return CountryRecord(
            page_id=17,
            title_vi="Monaco",
            source_url="https://vi.wikipedia.org/wiki/Monaco",
            retrieved_at=datetime.now(UTC),
            abstract_vi=abstract,
            area_km2=value,
        )

    old = record(2084.0)
    issues = sanity_issues([old])
    assert [row["category"] for row in issues] == ["abstract_area_thousandfold_review"]
    assert old.area_km2 == 2084.0  # QA never alters canonical data.
    assert sanity_issues([record(2.084)]) == []
    assert sanity_issues([record(2084.0, abstract="Diện tích của đảo khác là 2,05 km²")]) == []
    assert sanity_issues([record(41285.0, abstract="Diện tích của Monaco là 41.285 km²")]) == []
