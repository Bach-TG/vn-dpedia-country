from vi_dbpedia_data.links import (
    LINK_CHECK_PATH,
    check_dbpedia_links,
    load_link_checks,
    resolve_sameas,
)
from vi_dbpedia_data.utils import load_settings, read_csv, write_json

DBR = "http://dbpedia.org/resource/"


def _record(page_id: int, title_vi: str, english_title: str | None) -> dict:
    return {
        "page_id": page_id,
        "title_vi": title_vi,
        "source_url": "https://vi.wikipedia.org/wiki/X",
        "retrieved_at": "2024-01-02T00:00:00Z",
        "english_title": english_title,
    }


def _binding(uri: str, **values: str) -> dict:
    return {"uri": {"value": uri}} | {key: {"value": value} for key, value in values.items()}


class Client:
    """Fake DBpedia endpoint answering by the IRIs in the VALUES clause."""

    answers = {
        DBR + "Vietnam": _binding(DBR + "Vietnam", label="Vietnam", country=DBR + "x"),
        DBR + "Timor-Leste": _binding(DBR + "Timor-Leste", redirect=DBR + "East_Timor"),
        DBR + "East_Timor": _binding(DBR + "East_Timor", label="East Timor"),
        DBR + "Georgia": _binding(DBR + "Georgia", label="Georgia", disambiguates=DBR + "y"),
        DBR + "São_Tomé_and_Príncipe": _binding(DBR + "São_Tomé_and_Príncipe"),
    }

    def __init__(self):
        self.calls = []

    def get_json(self, _url, params, *, accept):
        assert accept == "application/sparql-results+json"
        self.calls.append(params["query"])
        bindings = [answer for uri, answer in self.answers.items() if f"<{uri}>" in params["query"]]
        return {"results": {"bindings": bindings}}


def test_check_dbpedia_links_classifies_and_saves(tmp_path):
    records = [
        _record(1, "Việt Nam", "Vietnam"),
        _record(2, "Đông Timor", "Timor-Leste"),
        _record(3, "Gruzia", "Georgia"),
        # An old percent-encoded candidate is re-derived as the DBpedia IRI.
        _record(4, "São Tomé và Príncipe", "São Tomé and Príncipe"),
        _record(5, "Không có liên kết", None),
    ]
    write_json(tmp_path / "data/processed/countries.json", records)
    client = Client()

    rows = check_dbpedia_links(load_settings(), tmp_path, client=client)

    assert [(row["page_id"], row["status"], row["sameas_uri"]) for row in rows] == [
        (1, "verified", DBR + "Vietnam"),
        (2, "redirect_resolved", DBR + "East_Timor"),
        (3, "disambiguation", ""),
        (4, "not_found", ""),
    ]
    assert rows[0]["dbpedia_is_country"] is True
    assert len(client.calls) == 2  # candidates, then redirect targets
    assert len(read_csv(tmp_path / LINK_CHECK_PATH)) == 4


def test_failed_requests_leave_links_unverified(tmp_path):
    write_json(tmp_path / "data/processed/countries.json", [_record(1, "Việt Nam", "Vietnam")])

    class Down:
        def get_json(self, *_args, **_kwargs):
            raise RuntimeError("Request failed")

    rows = check_dbpedia_links(load_settings(), tmp_path, client=Down())
    assert rows[0]["status"] == "error"
    checks = load_link_checks(tmp_path)
    assert resolve_sameas(DBR + "Vietnam", checks) == (DBR + "Vietnam", "unverified")


def test_resolve_sameas_without_checks():
    assert resolve_sameas(None, {}) == (None, "no_english_link")
    assert resolve_sameas(DBR + "Vietnam", {}) == (DBR + "Vietnam", "unverified")
