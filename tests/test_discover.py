from vi_dbpedia_data.discover import PRIMARY, _query, deduplicate, discover, pilot_candidates
from vi_dbpedia_data.models import CandidateCountry
from vi_dbpedia_data.utils import load_settings, read_json


def test_candidate_provenance_fallback_and_pilot(tmp_path):
    class Client:
        def get_json(self, _url, params):
            if "P279*" in params["query"]:
                start, stop = 2, 22
            else:
                start, stop = 1, 2
            return {
                "results": {
                    "bindings": [
                        {
                            "item": {"value": f"http://www.wikidata.org/entity/Q{index}"},
                            "viArticle": {
                                "value": f"https://vi.wikipedia.org/wiki/Quốc_gia_{index}"
                            },
                            "enArticle": {
                                "value": f"https://en.wikipedia.org/wiki/Country_{index}"
                            },
                        }
                        for index in range(start, stop)
                    ]
                }
            }

    settings = load_settings()
    candidates = discover(settings, tmp_path, client=Client())
    assert len(candidates) == 21
    assert candidates[0].english_title_hint == "Country 1"
    assert candidates[0].discovery_method == "wikidata_direct_country_or_sovereign_state"
    assert candidates[1].discovery_method == "wikidata_sovereign_state_hierarchy"
    assert len(read_json(tmp_path / "data/candidates/countries.json")) == 21
    pilot = pilot_candidates(candidates, settings)
    assert len(pilot) == 20
    assert [item.title_vi for item in pilot[:5]] == settings.reference_titles
    assert pilot == pilot_candidates(list(reversed(candidates)), settings)
    assert all(item.wikidata_id is None for item in pilot[:5])


def test_dedup_qid_then_vi_title():
    candidates = [
        CandidateCountry(wikidata_id="Q1", title_vi="X", discovery_method="a"),
        CandidateCountry(wikidata_id="Q1", title_vi="Y", discovery_method="b"),
        CandidateCountry(wikidata_id="Q2", title_vi="X", discovery_method="b"),
    ]
    unique = deduplicate(candidates)
    assert unique == candidates[:1]
    assert unique[0].discovery_methods == ["a", "b"]
    assert "Q2 (b)" in unique[0].discovery_conflicts


def test_duplicate_queries_retain_both_methods():
    unique = deduplicate(
        [
            CandidateCountry(wikidata_id="Q1", title_vi="X", discovery_method="direct"),
            CandidateCountry(wikidata_id="Q1", title_vi="X", discovery_method="hierarchy"),
        ]
    )
    assert unique[0].discovery_methods == ["direct", "hierarchy"]


def test_pilot_does_not_resample_a_redirected_reference():
    settings = load_settings()
    candidates = [
        CandidateCountry(
            wikidata_id="Q258", title_vi="Cộng hòa Nam Phi", discovery_method="wikidata"
        )
    ]
    candidates += [
        CandidateCountry(
            wikidata_id=f"Q{index}", title_vi=f"Nước {index}", discovery_method="wikidata"
        )
        for index in range(100, 125)
    ]
    pilot = pilot_candidates(candidates, settings, {"Nam Phi": "Q258"})
    assert len(pilot) == 20
    assert pilot[3].title_vi == "Nam Phi"
    assert pilot[3].wikidata_id == "Q258"
    assert all(item.title_vi != "Cộng hòa Nam Phi" for item in pilot[5:])
    assert len({item.wikidata_id for item in pilot[5:]}) == 15


def test_future_discovery_persists_instance_type_evidence_without_changing_inclusion():
    class Client:
        def get_json(self, _url, _params):
            return {
                "results": {
                    "bindings": [
                        {
                            "item": {"value": "http://www.wikidata.org/entity/Q55"},
                            "type": {"value": "http://www.wikidata.org/entity/Q6256"},
                            "viArticle": {"value": "https://vi.wikipedia.org/wiki/Hà_Lan"},
                        }
                    ]
                }
            }

    assert "?type" in PRIMARY
    candidate = _query(Client(), load_settings(), PRIMARY, "direct")[0]
    assert candidate.wikidata_id == "Q55"
    assert candidate.instance_qids == ["Q6256"]
    assert candidate.english_title_hint is None
