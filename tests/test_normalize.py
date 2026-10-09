import pytest

from vi_dbpedia_data.normalize import (
    area,
    calling_codes,
    clean_text,
    english_links,
    population,
    resources,
)


def test_nfc_and_whitespace():
    assert clean_text("  Vie\u0302\u0323t Nam  ") == "Việt Nam"
    assert clean_text(" A  B\nC ") == "A  B\nC"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234.567<ref name='a' />", 1234567),
        ("{{formatnum:1,234,567}}", 1234567),
        ("{{IncreaseNeutral}} {{formatnum:9060598}}<ref>{{cite web|title=x}}</ref>", 9060598),
        ("{{DecreaseNeutral}} 122.950.000<ref name='source' />", 122950000),
        ("{{IncreaseNeutral}} 6,110,200{{efn|Includes 3.640.000 others}}", 6110200),
        ("1 234 567", 1234567),
        ("1,5 triệu", None),
        ("2024: 1.234", None),
        ("1,2", None),
        ("-42", -42),
    ],
)
def test_population(raw, expected):
    assert population(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("331.212 km²", 331212.0),
        ("41.285", 41285.0),
        ("744.3", 744.3),
        ("1.234,56 km2", 1234.56),
        ("12.5 sq mi", pytest.approx(32.374851)),
        ("12 km² / 4 sq mi", None),
        ("không rõ", None),
    ],
)
def test_area(raw, expected):
    assert area(raw) == expected


def test_wiki_links_and_multiple_resources():
    assert resources("[[Tokyo]]")[0].model_dump() == {"label_vi": "Tokyo", "wiki_title": "Tokyo"}
    assert resources("[[Tokyo|Tōkyō]]")[0].model_dump() == {
        "label_vi": "Tōkyō",
        "wiki_title": "Tokyo",
    }
    assert [ref.label_vi for ref in resources("[[Tiếng Đức]], [[Tiếng Pháp]], [[Tiếng Ý]]")] == [
        "Tiếng Đức",
        "Tiếng Pháp",
        "Tiếng Ý",
    ]
    assert [
        ref.label_vi for ref in resources("[[Pretoria]]<br>[[Cape Town]]<br>[[Bloemfontein]]")
    ] == ["Pretoria", "Cape Town", "Bloemfontein"]
    assert resources("{{unknown|Tokyo}}") == []
    assert [
        ref.label_vi
        for ref in resources(
            "{{unbulleted list|[[Pretoria]] (chính phủ)|[[Cape Town]] (Nghị viện)"
            "|[[Bloemfontein]] (tư pháp)}}"
        )
    ] == ["Pretoria", "Cape Town", "Bloemfontein"]
    assert [
        ref.label_vi
        for ref in resources("{{unbulleted list|style=color:red|[[Pretoria]]|[[Cape Town]]}}")
    ] == ["Pretoria", "Cape Town"]
    assert resources("[[Tập_tin:Logo.png|22px]] [[Hà Nội]]")[0].label_vi == "Hà Nội"
    assert len(resources("[[Tập tin:CHE Bern COA.svg|18px]] [[Bern]] ([[de facto]])")) == 1
    assert resources("Không có<ref>no official language</ref>") == []
    assert (
        resources("'''Singapore'''{{efn|Singapore không có thủ đô chính thức}} ([[Thành bang]])")
        == []
    )
    assert resources("[[Yên Nhật|Yên]] (¥){{\\}}{{transl|ja|En}} {{nihongo2|円}}") == [
        resources("[[Yên Nhật|Yên]]")[0]
    ]


def test_plainlist_does_not_include_other_language_statuses():
    raw = (
        "'''[[Ngôn ngữ của Nam Phi|12 ngôn ngữ]]'''"
        "{{plainlist|\n* [[Tiếng Afrikaans]]\n* [[Tiếng Zulu]]}}"
    )
    raw += "{{collapsible list|title=ngôn ngữ đặc biệt|[[Tiếng Đức]]}}"
    assert [ref.label_vi for ref in resources(raw)] == ["Tiếng Afrikaans", "Tiếng Zulu"]


def test_calling_codes():
    assert calling_codes("+81") == ["+81"]
    assert calling_codes("+27, +268") == ["+27", "+268"]
    assert calling_codes("+27 (approx. 5)") == []


def test_english_link_urls():
    assert english_links("New York City") == (
        "New York City",
        "https://en.wikipedia.org/wiki/New_York_City",
        "http://dbpedia.org/resource/New_York_City",
    )
    # DBpedia resources are IRIs: the percent-encoded form is a different resource.
    assert english_links("Côte_d'Ivoire") == (
        "Côte d'Ivoire",
        "https://en.wikipedia.org/wiki/C%C3%B4te_d%27Ivoire",
        "http://dbpedia.org/resource/Côte_d'Ivoire",
    )
    assert english_links("São Tomé and Príncipe")[2] == (
        "http://dbpedia.org/resource/São_Tomé_and_Príncipe"
    )
    assert english_links(None) == (None, None, None)
