from unittest.mock import Mock

import pytest
import requests

from vi_dbpedia_data.utils import HttpClient, load_settings, wiki_iri_name


def test_http_retry_timeout_user_agent_and_backoff(monkeypatch):
    delays = []
    monkeypatch.setattr("vi_dbpedia_data.utils.time.sleep", delays.append)
    session = Mock()
    session.headers = {}
    response = Mock(status_code=200)
    response.raise_for_status.return_value = None
    response.json.return_value = {"query": {"pages": []}}
    session.get.side_effect = [requests.Timeout("slow"), response]
    settings = load_settings()
    client = HttpClient(settings, session=session)
    assert client.get_json("https://vi.wikipedia.org/w/api.php", {"action": "query"}) == {
        "query": {"pages": []}
    }
    assert session.get.call_count == 2
    assert session.get.call_args.kwargs["timeout"] == settings.request_timeout
    assert "HUST" in session.headers["User-Agent"]
    assert settings.retry_backoff in delays


def test_http_non_retryable_api_error(monkeypatch):
    monkeypatch.setattr("vi_dbpedia_data.utils.time.sleep", lambda _: None)
    session = Mock()
    session.headers = {}
    response = Mock(status_code=200)
    response.raise_for_status.return_value = None
    response.json.return_value = {"error": {"code": "badtitle"}}
    session.get.return_value = response
    with pytest.raises(RuntimeError, match="API error"):
        HttpClient(load_settings(), session=session).get_json(
            "https://vi.wikipedia.org/w/api.php", {}
        )
    assert session.get.call_count == 1


def test_wiki_iri_name_matches_mediawiki_and_dbpedia_conventions():
    # Same page, same IRI: first letter and underscores are not significant.
    assert wiki_iri_name("tiếng_Pháp") == wiki_iri_name(" Tiếng  Pháp ") == "Tiếng_Pháp"
    # IRIs keep Unicode, apostrophes and commas; only IRI-unsafe characters are escaped.
    assert wiki_iri_name("Côte d'Ivoire") == "Côte_d'Ivoire"
    assert wiki_iri_name("Bonaire, Sint Eustatius and Saba") == "Bonaire,_Sint_Eustatius_and_Saba"
    assert wiki_iri_name('A "b" ?') == "A_%22b%22_%3F"
    with pytest.raises(ValueError):
        wiki_iri_name(" _ ")
