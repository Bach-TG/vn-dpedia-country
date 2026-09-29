import json

from vi_dbpedia_data.discover import deduplicate
from vi_dbpedia_data.models import CandidateCountry
from vi_dbpedia_data.reports import generate_candidate_audit
from vi_dbpedia_data.utils import read_csv, read_json, write_json


def test_candidate_type_evidence_and_review_flags_are_auditable_offline(tmp_path):
    candidates = [
        CandidateCountry(
            wikidata_id="Q1",
            title_vi="Quốc gia thử nghiệm",
            discovery_method="wikidata_direct_country_or_sovereign_state",
            instance_qids=["Q3624078"],
        ),
        CandidateCountry(
            wikidata_id="Q2",
            title_vi="Vùng thử nghiệm",
            english_title_hint="Example region",
            instance_qids=["Q6256"],
            discovery_method="wikidata_direct_country_or_sovereign_state",
        ),
        CandidateCountry(
            wikidata_id="Q3",
            title_vi="Không rõ loại",
            discovery_method="wikidata_sovereign_state_hierarchy",
        ),
    ]
    write_json(
        tmp_path / "data/candidates/countries.json", [item.model_dump() for item in candidates]
    )
    summary = generate_candidate_audit(tmp_path)
    rows = read_csv(tmp_path / "data/reports/candidate_audit.csv")
    assert summary["candidate_count"] == len(rows) == 3
    assert summary["instance_type_counts"] == {"Q3624078": 1, "Q6256": 1}
    assert summary["missing_instance_type_count"] == 1
    assert rows[0]["potential_review"] == "False"
    assert rows[1]["potential_review"] == "True"
    assert "sovereign-state status" in rows[1]["review_reason"]
    assert "territorial scope" in rows[1]["review_reason"]
    assert json.loads(rows[1]["instance_qids"]) == ["Q6256"]
    assert "Exact P31 type not saved" in rows[2]["review_reason"]
    assert read_json(tmp_path / "data/reports/candidate_summary.json")["candidate_count"] == 3


def test_type_bindings_are_merged_without_dropping_provenance():
    rows = [
        CandidateCountry(
            wikidata_id="Q1", title_vi="X", discovery_method="direct", instance_qids=[qid]
        )
        for qid in ("Q6256", "Q3624078")
    ]
    unique = deduplicate(rows)
    assert len(unique) == 1
    assert unique[0].instance_qids == ["Q6256", "Q3624078"]
    assert unique[0].discovery_methods == ["direct"]
