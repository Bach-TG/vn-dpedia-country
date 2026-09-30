"""Local, auditable dataset-scope selection from the full candidate universe."""

import json
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from vi_dbpedia_data.models import CandidateCountry
from vi_dbpedia_data.utils import ROOT, read_csv, read_json, utc_now, write_csv, write_json

DECISION_COLUMNS = ["wikidata_id", "vi_title", "decision", "reason", "replacement_for"]


class Substitution(BaseModel):
    include_qid: str
    exclude_qid: str
    reason: str = Field(min_length=1)


class ScopeOverride(BaseModel):
    wikidata_id: str
    decision: Literal["include", "exclude", "review"]
    reason: str = Field(min_length=1)
    replacement_for: str | None = None


class ScopePolicy(BaseModel):
    sovereign_instance_qid: str
    substitutions: list[Substitution] = Field(default_factory=list)
    manual_overrides: list[ScopeOverride] = Field(default_factory=list)


def load_scope_policy(root: Path = ROOT) -> ScopePolicy:
    policy = ScopePolicy.model_validate(
        yaml.safe_load((root / "config/scope_policy.yaml").read_text(encoding="utf-8"))
    )
    substitute_qids = [
        qid for rule in policy.substitutions for qid in (rule.include_qid, rule.exclude_qid)
    ]
    overrides = [row.wikidata_id for row in policy.manual_overrides]
    if len(substitute_qids) != len(set(substitute_qids)):
        raise ValueError("Scope substitution QIDs must be unique and distinct")
    if len(overrides) != len(set(overrides)):
        raise ValueError("Duplicate manual scope override QID")
    return policy


def decide_scope(
    candidates: list[CandidateCountry], policy: ScopePolicy
) -> tuple[list[dict], list[CandidateCountry], dict]:
    """Decide scope by P31, then substitutions, then explicit reviewed overrides."""
    qids = [row.wikidata_id for row in candidates if row.wikidata_id]
    if len(qids) != len(set(qids)):
        raise ValueError("Cannot scope candidates with duplicate Wikidata QIDs")
    by_qid = {item.wikidata_id: item for item in candidates if item.wikidata_id}
    substitutions = {
        qid: ("include" if qid == rule.include_qid else "exclude", rule)
        for rule in policy.substitutions
        for qid in (rule.include_qid, rule.exclude_qid)
    }
    overrides = {item.wikidata_id: item for item in policy.manual_overrides}
    decisions, approved = [], []
    for candidate in candidates:
        qid = candidate.wikidata_id
        types = set(candidate.instance_qids)
        if not qid or not types:
            decision, reason = "review", "Missing QID or direct P31 type evidence"
        elif policy.sovereign_instance_qid in types:
            decision, reason = (
                "include",
                (f"Direct P31 {policy.sovereign_instance_qid} in saved candidate evidence"),
            )
        elif "Q6256" in types:
            decision, reason = (
                "exclude",
                (
                    "Country-type candidate without direct sovereign-state type; "
                    "outside this prototype's default dataset scope"
                ),
            )
        else:
            decision, reason = "review", "Direct type requires dataset-scope review"
        replacement_for = ""
        if qid in substitutions:
            decision, substitution = substitutions[qid]
            other = substitution.exclude_qid if decision == "include" else substitution.include_qid
            replacement_for = other
            reason = (
                f"Canonical country article replacing {other}: {substitution.reason}"
                if decision == "include"
                else f"Replaced by canonical country article {other}: {substitution.reason}"
            )
        if qid in overrides:
            override = overrides[qid]
            decision, reason = override.decision, override.reason
            replacement_for = override.replacement_for or ""
        decisions.append(
            {
                "wikidata_id": qid or "",
                "vi_title": candidate.title_vi,
                "decision": decision,
                "reason": reason,
                "replacement_for": replacement_for,
            }
        )
        if decision == "include":
            approved.append(candidate)
    counts = Counter(row["decision"] for row in decisions)
    final_decisions = {row["wikidata_id"]: row["decision"] for row in decisions}
    applied = sum(
        final_decisions.get(rule.include_qid) == "include"
        and final_decisions.get(rule.exclude_qid) == "exclude"
        for rule in policy.substitutions
    )
    summary = {
        "discovered_count": len(candidates),
        "approved_count": counts["include"],
        "excluded_count": counts["exclude"],
        "review_count": counts["review"],
        "type_policy": (
            f"Include direct P31 {policy.sovereign_instance_qid} by default; exclude country-only "
            "candidates unless substituted; review candidates without sufficient type evidence. "
            "Dataset scoping convention, not a geopolitical recognition judgement."
        ),
        "substitution_count": applied,
        "unresolved_substitutions": [
            {"include_qid": rule.include_qid, "exclude_qid": rule.exclude_qid}
            for rule in policy.substitutions
            if rule.include_qid not in by_qid or rule.exclude_qid not in by_qid
        ],
        "unused_manual_overrides": sorted(set(overrides) - set(by_qid)),
    }
    return decisions, approved, summary


def generate_scope(
    candidates: list[CandidateCountry], root: Path = ROOT
) -> tuple[list[CandidateCountry], dict]:
    """Write reproducible scope artifacts; never mutate the discovery files."""
    decisions, approved, summary = decide_scope(candidates, load_scope_policy(root))
    summary["generation_timestamp"] = utc_now().isoformat()
    write_csv(root / "data/candidates/scope_decisions.csv", decisions, DECISION_COLUMNS)
    rows = [item.model_dump() for item in approved]
    write_csv(
        root / "data/candidates/approved_countries.csv",
        [
            {
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                for key, value in row.items()
            }
            for row in rows
        ],
        list(CandidateCountry.model_fields),
    )
    write_json(root / "data/reports/scope_summary.json", summary)
    return approved, summary


def generate_scope_from_saved(root: Path = ROOT) -> tuple[list[CandidateCountry], dict]:
    candidates = [
        CandidateCountry.model_validate(item)
        for item in read_json(root / "data/candidates/countries.json")
    ]
    return generate_scope(candidates, root)


def load_approved_candidates(root: Path = ROOT) -> list[CandidateCountry]:
    """Read the generated approved CSV as the collection input."""
    approved = []
    for row in read_csv(root / "data/candidates/approved_countries.csv"):
        values = dict(row)
        for field in ("discovery_methods", "discovery_conflicts", "instance_qids"):
            values[field] = json.loads(values[field] or "[]")
        for field in ("wikidata_id", "wikipedia_url", "english_title_hint"):
            values[field] = values[field] or None
        approved.append(CandidateCountry.model_validate(values))
    return approved
