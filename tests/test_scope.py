"""Scope is a local policy layer; neither discovery nor Wikipedia is queried."""

import yaml

from vi_dbpedia_data import cli
from vi_dbpedia_data.models import CandidateCountry
from vi_dbpedia_data.scope import generate_scope_from_saved, load_approved_candidates
from vi_dbpedia_data.utils import ROOT, read_csv, read_json, write_json


def candidate(qid: str, title: str, *types: str) -> CandidateCountry:
    return CandidateCountry(
        wikidata_id=qid,
        title_vi=title,
        instance_qids=list(types),
        discovery_method="wikidata_direct_country_or_sovereign_state",
    )


def prepare(tmp_path, candidates):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    policy_path = config / "scope_policy.yaml"
    if not policy_path.exists():
        policy_path.write_text(
            (ROOT / "config/scope_policy.yaml").read_text("utf-8"), encoding="utf-8"
        )
    saved = [item.model_dump() for item in candidates]
    write_json(tmp_path / "data/candidates/countries.json", saved)
    return saved


def test_direct_sovereign_country_only_and_canonical_substitutions(tmp_path):
    discovered = [
        candidate("Q1", "Direct sovereign", "Q3624078", "Q6256"),
        candidate("Q2", "Only country", "Q6256"),
        candidate("Q35", "Đan Mạch", "Q6256"),
        candidate("Q756617", "Vương quốc Đan Mạch", "Q3624078", "Q6256"),
        candidate("Q55", "Hà Lan", "Q6256"),
        candidate("Q29999", "Vương quốc Hà Lan", "Q3624078", "Q6256"),
        candidate("Q3", "Unknown"),
    ]
    original = prepare(tmp_path, discovered)
    approved, summary = generate_scope_from_saved(tmp_path)
    decisions = {
        row["wikidata_id"]: row
        for row in read_csv(tmp_path / "data/candidates/scope_decisions.csv")
    }
    assert list(decisions["Q1"]) == [
        "wikidata_id",
        "vi_title",
        "decision",
        "reason",
        "replacement_for",
    ]
    assert {qid: row["decision"] for qid, row in decisions.items()} == {
        "Q1": "include",
        "Q2": "exclude",
        "Q35": "include",
        "Q756617": "exclude",
        "Q55": "include",
        "Q29999": "exclude",
        "Q3": "review",
    }
    assert decisions["Q35"]["replacement_for"] == "Q756617"
    assert decisions["Q756617"]["replacement_for"] == "Q35"
    assert "canonical country article Q35" in decisions["Q756617"]["reason"]
    assert decisions["Q55"]["replacement_for"] == "Q29999"
    assert "canonical country article Q55" in decisions["Q29999"]["reason"]
    assert [item.wikidata_id for item in approved] == ["Q1", "Q35", "Q55"]
    assert load_approved_candidates(tmp_path) == approved
    assert [
        row["wikidata_id"] for row in read_csv(tmp_path / "data/candidates/approved_countries.csv")
    ] == ["Q1", "Q35", "Q55"]
    assert summary["discovered_count"] == 7
    assert summary["approved_count"] == 3
    assert summary["excluded_count"] == 3
    assert summary["review_count"] == 1
    assert summary["substitution_count"] == 2
    assert "not a geopolitical" in summary["type_policy"]
    assert read_json(tmp_path / "data/candidates/countries.json") == original
    assert read_json(tmp_path / "data/reports/scope_summary.json") == summary


def test_count_recomputed_after_universe_changes_and_review_override(tmp_path):
    discovered = [
        candidate("Q35", "Đan Mạch", "Q6256"),
        candidate("Q756617", "Vương quốc Đan Mạch", "Q3624078"),
        candidate("Q1", "Sovereign 1", "Q3624078"),
    ]
    prepare(tmp_path, discovered)
    _, before = generate_scope_from_saved(tmp_path)
    assert before["approved_count"] == 2
    config = tmp_path / "config/scope_policy.yaml"
    policy = yaml.safe_load(config.read_text("utf-8"))
    policy["manual_overrides"] = [
        {"wikidata_id": "Q1", "decision": "review", "reason": "Manual source inspection"}
    ]
    config.write_text(yaml.safe_dump(policy, allow_unicode=True), "utf-8")
    prepare(
        tmp_path,
        [
            *discovered,
            candidate("Q4", "Sovereign 4", "Q3624078"),
            candidate("Q5", "Sovereign 5", "Q3624078"),
        ],
    )
    approved, after = generate_scope_from_saved(tmp_path)
    assert after["discovered_count"] == 5
    assert after["approved_count"] == 3  # Q35 plus new Q4 and Q5; recomputed, not fixed
    assert after["review_count"] == 1
    assert [item.wikidata_id for item in approved] == ["Q35", "Q4", "Q5"]
    decisions = {
        row["wikidata_id"]: row
        for row in read_csv(tmp_path / "data/candidates/scope_decisions.csv")
    }
    assert decisions["Q1"]["reason"] == "Manual source inspection"


def test_scope_command_is_offline_and_keeps_discovery_rows(tmp_path, monkeypatch):
    original = prepare(tmp_path, [candidate("Q1", "Sovereign", "Q3624078")])
    (tmp_path / "config/settings.yaml").write_text(
        (ROOT / "config/settings.yaml").read_text("utf-8"), encoding="utf-8"
    )

    def network_forbidden(*_args, **_kwargs):
        raise AssertionError("Scope must not invoke discovery or collection")

    monkeypatch.setattr(cli, "discover", network_forbidden)
    monkeypatch.setattr(cli, "collect", network_forbidden)
    assert cli.main(["--root", str(tmp_path), "scope"]) == 0
    assert read_json(tmp_path / "data/candidates/countries.json") == original
    assert read_json(tmp_path / "data/reports/scope_summary.json")["approved_count"] == 1
