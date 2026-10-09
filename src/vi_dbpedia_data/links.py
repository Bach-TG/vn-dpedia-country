"""Verify English DBpedia owl:sameAs targets against the public DBpedia endpoint.

The vi Wikipedia interlanguage link remains the identity evidence. This check
only corrects it: a DBpedia redirect is replaced by its target, and a resource
that DBpedia lacks or treats as a disambiguation page is not linked. Network
failures leave a link unverified rather than removing it.
"""

import logging
from pathlib import Path

from vi_dbpedia_data.models import CountryRecord
from vi_dbpedia_data.normalize import english_links
from vi_dbpedia_data.utils import (
    ROOT,
    HttpClient,
    Settings,
    read_csv,
    read_json,
    utc_now,
    write_csv,
)

LOG = logging.getLogger(__name__)
LINK_CHECK_PATH = Path("data/reports/dbpedia_link_check.csv")
LINK_CHECK_COLUMNS = [
    "page_id",
    "title_vi",
    "english_title",
    "dbpedia_uri",
    "status",
    "sameas_uri",
    "dbpedia_label_en",
    "dbpedia_is_country",
    "checked_at",
    "error",
]
#: Statuses whose `sameas_uri` is emitted as owl:sameAs.
LINKED_STATUSES = {"verified", "redirect_resolved"}
SPARQL_JSON = "application/sparql-results+json"
BATCH_SIZE = 50

# Virtuoso (DBpedia) rejects EXISTS inside BIND, hence OPTIONAL + SAMPLE.
# Main resources have an English label; redirect pages and stale encoded
# IRIs do not.
QUERY = """PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?uri (SAMPLE(?l) AS ?label) (SAMPLE(?r) AS ?redirect)
       (SAMPLE(?d) AS ?disambiguates) (SAMPLE(?c) AS ?country) WHERE {{
  VALUES ?uri {{ {values} }}
  OPTIONAL {{ ?uri rdfs:label ?l FILTER(lang(?l) = "en") }}
  OPTIONAL {{ ?uri dbo:wikiPageRedirects ?r }}
  OPTIONAL {{ ?uri dbo:wikiPageDisambiguates ?d }}
  OPTIONAL {{ ?uri a ?c FILTER(?c = dbo:Country) }}
}} GROUP BY ?uri"""


def dbpedia_candidate(record: CountryRecord) -> str | None:
    """English DBpedia IRI derived from the vi Wikipedia interlanguage title.

    Derived again from `english_title` rather than read from the stored
    candidate, so records processed before the IRI fix still map correctly.
    """
    return english_links(record.english_title)[2]


def _lookup(
    client: HttpClient, settings: Settings, uris: list[str]
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    failed: dict[str, str] = {}
    for start in range(0, len(uris), BATCH_SIZE):
        batch = uris[start : start + BATCH_SIZE]
        query = QUERY.format(values=" ".join(f"<{uri}>" for uri in batch))
        try:
            response = client.get_json(
                settings.dbpedia_sparql_url,
                {"query": query, "format": SPARQL_JSON},
                accept=SPARQL_JSON,
            )
        except RuntimeError as exc:
            LOG.warning("DBpedia link check failed for %d URIs: %s", len(batch), exc)
            failed.update(dict.fromkeys(batch, str(exc)))
            continue
        for binding in response["results"]["bindings"]:
            found[binding["uri"]["value"]] = {key: value["value"] for key, value in binding.items()}
    return found, failed


def _classify(
    uri: str, found: dict[str, dict[str, str]], failed: dict[str, str]
) -> tuple[str, str, dict[str, str], str]:
    """Return (status, owl:sameAs target or "", DBpedia facts, error)."""
    if uri in failed:
        return "error", "", {}, failed[uri]
    info = found.get(uri, {})
    status, target = "verified", uri
    if "redirect" in info:
        status, target = "redirect_resolved", info["redirect"]
        if target in failed:
            return "error", "", {}, failed[target]
        info = found.get(target, {})
    if "disambiguates" in info:
        return "disambiguation", "", info, ""
    if "label" not in info:
        return "not_found", "", info, ""
    return status, target, info, ""


def check_dbpedia_links(
    settings: Settings, root: Path = ROOT, client: HttpClient | None = None
) -> list[dict]:
    client = client or HttpClient(settings)
    records = [
        CountryRecord.model_validate(item)
        for item in read_json(root / "data/processed/countries.json")
    ]
    candidates = {record.page_id: dbpedia_candidate(record) for record in records}
    found, failed = _lookup(client, settings, sorted({uri for uri in candidates.values() if uri}))
    redirects = sorted(
        {info["redirect"] for info in found.values() if "redirect" in info} - found.keys()
    )
    targets, failed_targets = _lookup(client, settings, redirects)
    found.update(targets)
    failed.update(failed_targets)
    checked_at = utc_now().isoformat()
    rows = []
    for record in sorted(records, key=lambda item: item.page_id):
        uri = candidates[record.page_id]
        if not uri:
            continue
        status, target, info, error = _classify(uri, found, failed)
        rows.append(
            {
                "page_id": record.page_id,
                "title_vi": record.title_vi,
                "english_title": record.english_title,
                "dbpedia_uri": uri,
                "status": status,
                "sameas_uri": target,
                "dbpedia_label_en": info.get("label", ""),
                "dbpedia_is_country": "country" in info if status != "error" else "",
                "checked_at": checked_at,
                "error": error,
            }
        )
    write_csv(root / LINK_CHECK_PATH, rows, LINK_CHECK_COLUMNS)
    return rows


def load_link_checks(root: Path = ROOT) -> dict[str, dict[str, str]]:
    """Saved link checks by candidate IRI; empty when `link-check` has not run."""
    path = root / LINK_CHECK_PATH
    return {row["dbpedia_uri"]: row for row in read_csv(path)} if path.exists() else {}


def resolve_sameas(uri: str | None, checks: dict[str, dict[str, str]]) -> tuple[str | None, str]:
    """Return (owl:sameAs target or None, link status) for a DBpedia candidate."""
    if not uri:
        return None, "no_english_link"
    check = checks.get(uri)
    if check is None or check["status"] == "error":
        return uri, "unverified"
    if check["status"] in LINKED_STATUSES:
        return check["sameas_uri"], check["status"]
    return None, check["status"]
