from vi_dbpedia_data.collect import collect, collect_reference, selected_raw_pages
from vi_dbpedia_data.models import CandidateCountry
from vi_dbpedia_data.utils import load_settings, read_json, write_json


class FakeClient:
    def __init__(self):
        self.calls = 0

    def get_json(self, _url, params):
        self.calls += 1
        assert "rvlimit" not in params  # MediaWiki rejects rvlimit with batched titles.
        title = params["titles"]
        return {
            "query": {
                "redirects": [{"from": title, "to": "Nhật Bản"}] if title != "Nhật Bản" else [],
                "pages": [
                    {
                        "title": "Nhật Bản",
                        "pageid": 17,
                        "fullurl": "https://vi.wikipedia.org/wiki/Nhật_Bản",
                        "extract": "Một quốc gia",
                        "pageprops": {"wikibase_item": "Q17"},
                        "langlinks": [{"lang": "en", "title": "Japan"}],
                        "revisions": [
                            {
                                "revid": 100,
                                "timestamp": "2026-01-01T00:00:00Z",
                                "slots": {
                                    "main": {"content": "{{Infobox country|capital=[[Tokyo]]}}"}
                                },
                            }
                        ],
                    }
                ],
            }
        }


def test_resumable_and_force(tmp_path):
    client = FakeClient()
    candidate = CandidateCountry(wikidata_id="Q17", title_vi="Nhật Bản", discovery_method="test")
    settings = load_settings()
    first = collect([candidate], settings, tmp_path, client=client)
    assert first[0]["collection_status"] == "collected"
    assert client.calls == 1
    raw = tmp_path / "data/raw/pages/17.json"
    retrieved = read_json(raw)["retrieved_at"]
    assert read_json(raw)["langlinks"]["en"] == "Japan"
    assert (
        collect([candidate], settings, tmp_path, client=client)[0]["collection_status"] == "skipped"
    )
    assert client.calls == 1
    assert read_json(raw)["retrieved_at"] == retrieved
    assert (
        collect([candidate], settings, tmp_path, force=True, client=client)[0]["collection_status"]
        == "collected"
    )
    assert client.calls == 2
    assert len(selected_raw_pages(tmp_path)) == 1


def test_redirect_provenance_and_disambiguation(tmp_path):
    settings = load_settings()
    client = FakeClient()
    candidate = CandidateCountry(title_vi="Japan redirect", discovery_method="test")
    row = collect([candidate], settings, tmp_path, client=client)[0]
    assert row["canonical_title"] == "Nhật Bản"
    assert read_json(tmp_path / "data/raw/pages/17.json")["redirects"] == [
        {"from": "Japan redirect", "to": "Nhật Bản"}
    ]


def test_reference_exact_titles_even_without_discovery(tmp_path):
    class FailingClient:
        def get_json(self, _url, _params):
            raise RuntimeError("offline")

    rows = collect_reference(load_settings(), tmp_path, client=FailingClient())
    assert [row["requested_title"] for row in rows] == [
        "Việt Nam",
        "Nhật Bản",
        "Singapore",
        "Nam Phi",
        "Thụy Sĩ",
    ]
    assert all(row["collection_status"] == "failed" for row in rows)
    assert read_json(tmp_path / "data/reference/pages.json") == []


def test_invalid_existing_raw_file_is_not_overwritten(tmp_path):
    path = tmp_path / "data/raw/pages/17.json"
    write_json(path, {"page_id": 17, "wikitext": ""})
    candidate = CandidateCountry(title_vi="Nhật Bản", discovery_method="test")
    row = collect([candidate], load_settings(), tmp_path, client=FakeClient())[0]
    assert row["collection_status"] == "failed"
    assert read_json(path) == {"page_id": 17, "wikitext": ""}


def test_disambiguation_is_rejected(tmp_path):
    class DisambiguationClient(FakeClient):
        def get_json(self, url, params):
            result = super().get_json(url, params)
            result["query"]["pages"][0]["pageprops"]["disambiguation"] = ""
            return result

    candidate = CandidateCountry(title_vi="Nhật Bản", discovery_method="test")
    rows = collect([candidate], load_settings(), tmp_path, client=DisambiguationClient())
    assert rows[0]["collection_status"] == "failed"
    assert "Disambiguation" in rows[0]["error"]
