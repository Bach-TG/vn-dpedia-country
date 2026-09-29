"""Semantic candidate discovery; no factual country values come from Wikidata."""

import json
import logging
import random
from pathlib import Path
from urllib.parse import unquote, urlparse

from vi_dbpedia_data.models import CandidateCountry
from vi_dbpedia_data.utils import ROOT, HttpClient, Settings, normalize_key, write_csv, write_json

LOG = logging.getLogger(__name__)

# Direct instances first. The fallback broadens the type hierarchy when the
# primary response is small; both provenance strings remain visible in output.
PRIMARY = """
SELECT DISTINCT ?item ?viArticle ?enArticle WHERE {
  VALUES ?type { wd:Q3624078 wd:Q6256 }
  ?item wdt:P31 ?type .
  FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }
  ?viArticle schema:about ?item; schema:isPartOf <https://vi.wikipedia.org/> .
  OPTIONAL { ?enArticle schema:about ?item; schema:isPartOf <https://en.wikipedia.org/> . }
} ORDER BY ?item
"""
FALLBACK = """
SELECT DISTINCT ?item ?viArticle ?enArticle WHERE {
  ?item wdt:P31/wdt:P279* wd:Q3624078 .
  FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }
  ?viArticle schema:about ?item; schema:isPartOf <https://vi.wikipedia.org/> .
  OPTIONAL { ?enArticle schema:about ?item; schema:isPartOf <https://en.wikipedia.org/> . }
} ORDER BY ?item
"""


def _title(url: str) -> str:
    return unquote(urlparse(url).path.removeprefix("/wiki/")).replace("_", " ")


def _query(
    client: HttpClient, settings: Settings, query: str, method: str
) -> list[CandidateCountry]:
    response = client.get_json(settings.wikidata_sparql_url, {"query": query, "format": "json"})
    result = []
    for binding in response["results"]["bindings"]:
        qid = binding["item"]["value"].rsplit("/", 1)[-1]
        vi_url = binding["viArticle"]["value"]
        result.append(
            CandidateCountry(
                wikidata_id=qid,
                title_vi=_title(vi_url),
                wikipedia_url=vi_url,
                english_title_hint=_title(binding["enArticle"]["value"])
                if "enArticle" in binding
                else None,
                discovery_method=method,
                discovery_methods=[method],
            )
        )
    return result


def deduplicate(candidates: list[CandidateCountry]) -> list[CandidateCountry]:
    """Never conflate different QIDs on a shared sitelink without logging it."""
    by_qid: dict[str, CandidateCountry] = {}
    by_title: dict[str, CandidateCountry] = {}
    unique = []
    for candidate in candidates:
        title = normalize_key(candidate.title_vi)
        same_qid = by_qid.get(candidate.wikidata_id) if candidate.wikidata_id else None
        same_title = by_title.get(title)
        existing = same_qid or same_title
        if existing:
            if same_title and same_title.wikidata_id != candidate.wikidata_id:
                LOG.warning(
                    "Conflicting QIDs for %s: %s / %s",
                    title,
                    same_title.wikidata_id,
                    candidate.wikidata_id,
                )
                existing.discovery_conflicts.append(
                    f"{candidate.wikidata_id or 'no QID'} ({candidate.discovery_method})"
                )
            elif same_qid and normalize_key(existing.title_vi) != title:
                existing.discovery_conflicts.append(
                    f"alternate vi title: {candidate.title_vi} ({candidate.discovery_method})"
                )
                by_title[title] = existing
            if not existing.discovery_methods:
                existing.discovery_methods.append(existing.discovery_method)
            for method in candidate.discovery_methods or [candidate.discovery_method]:
                if method not in existing.discovery_methods:
                    existing.discovery_methods.append(method)
            continue
        unique.append(candidate)
        if not candidate.discovery_methods:
            candidate.discovery_methods.append(candidate.discovery_method)
        if candidate.wikidata_id:
            by_qid[candidate.wikidata_id] = candidate
        by_title[title] = candidate
    return unique


def discover(
    settings: Settings, root: Path = ROOT, client: HttpClient | None = None
) -> list[CandidateCountry]:
    client = client or HttpClient(settings)
    results = []
    try:
        results = _query(client, settings, PRIMARY, "wikidata_direct_country_or_sovereign_state")
    except (RuntimeError, KeyError) as exc:
        LOG.warning("Primary discovery failed; trying class-hierarchy fallback: %s", exc)
    if len(results) < 150:
        try:
            results.extend(_query(client, settings, FALLBACK, "wikidata_sovereign_state_hierarchy"))
        except (RuntimeError, KeyError) as exc:
            if not results:
                raise RuntimeError("Both Wikidata candidate queries failed") from exc
            LOG.warning(
                "Fallback query failed; retaining %d direct candidates: %s", len(results), exc
            )
    results = deduplicate(results)
    if not results:
        raise RuntimeError("No country candidates returned by Wikidata")
    LOG.info(
        "Discovered %d candidates (inspect provenance; coverage is not guaranteed)", len(results)
    )
    out = root / "data/candidates"
    rows = [candidate.model_dump() for candidate in results]
    write_json(out / "countries.json", rows)
    write_csv(
        out / "countries.csv",
        [
            {
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                for key, value in row.items()
            }
            for row in rows
        ],
        list(CandidateCountry.model_fields),
    )
    return results


def pilot_candidates(
    candidates: list[CandidateCountry],
    settings: Settings,
    reference_qids: dict[str, str] | None = None,
) -> list[CandidateCountry]:
    """Keep the fixed references, then choose 15 more with a stable local RNG."""
    reference_qids = reference_qids or {}
    by_title = {normalize_key(item.title_vi): item for item in candidates}
    by_qid = {item.wikidata_id: item for item in candidates if item.wikidata_id}
    references = []
    for title in settings.reference_titles:
        known = by_title.get(normalize_key(title))
        qid = reference_qids.get(title)
        if known is None and qid in by_qid:
            # A reference title can redirect to a different Wikidata sitelink.
            original = by_qid[qid]
            known = original.model_copy(
                update={
                    "title_vi": title,
                    "discovery_methods": [*original.discovery_methods, "reference_redirect_title"],
                }
            )
        references.append(
            known
            or CandidateCountry(
                title_vi=title,
                discovery_method="reference_title",
                discovery_methods=["reference_title"],
            )
        )
    selected_titles = {normalize_key(item.title_vi) for item in references}
    selected_qids = {item.wikidata_id for item in references if item.wikidata_id}
    selected_qids.update(reference_qids.values())
    others = sorted(
        (
            item
            for item in candidates
            if normalize_key(item.title_vi) not in selected_titles
            and item.wikidata_id not in selected_qids
        ),
        key=lambda item: (item.wikidata_id or "", item.title_vi),
    )
    needed = settings.pilot_size - len(references)
    if needed < 0 or len(others) < needed:
        raise ValueError(f"Pilot needs {needed} non-reference candidates; only {len(others)} found")
    return references + random.Random(settings.pilot_seed).sample(others, needed)
