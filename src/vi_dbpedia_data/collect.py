"""Batched official MediaWiki API collection into immutable per-page raw files."""

import logging
from pathlib import Path

from pydantic import ValidationError

from vi_dbpedia_data.models import CandidateCountry, RawPage
from vi_dbpedia_data.utils import (
    ROOT,
    HttpClient,
    Settings,
    article_url,
    read_json,
    utc_now,
    write_csv,
    write_json,
)

LOG = logging.getLogger(__name__)
MANIFEST_COLUMNS = [
    "candidate_wikidata_id",
    "requested_title",
    "page_id",
    "canonical_title",
    "collection_status",
    "raw_file_path",
    "error",
]


def existing_pages(root: Path) -> dict[str, RawPage]:
    """Index only well-formed raw files; never overwrite an invalid file implicitly."""
    pages = {}
    for path in sorted((root / "data/raw/pages").glob("*.json")):
        try:
            page = RawPage.model_validate(read_json(path))
            if path.stem != str(page.page_id):
                raise ValueError("filename does not match page ID")
        except (ValueError, ValidationError) as exc:
            LOG.warning("Ignoring invalid raw file %s: %s", path, exc)
            continue
        pages.setdefault(page.requested_title, page)
        pages.setdefault(page.canonical_title, page)
    return pages


def _batch_response(client: HttpClient, settings: Settings, titles: list[str]) -> dict:
    return client.get_json(
        settings.wikipedia_api_url,
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(titles),
            "redirects": "1",
            "prop": "info|extracts|revisions|pageprops|langlinks",
            "inprop": "url",
            "exintro": "1",
            "explaintext": "1",
            "exlimit": settings.batch_size,
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
            "ppprop": "wikibase_item|disambiguation",
            "lllang": "en",
            "lllimit": "max",
        },
    )


def _raw_page(candidate: CandidateCountry, query: dict) -> RawPage:
    normalized = {row["from"]: row["to"] for row in query.get("normalized", [])}
    redirects = {row["from"]: row["to"] for row in query.get("redirects", [])}
    title = normalized.get(candidate.title_vi, candidate.title_vi)
    visited = set()
    while title in redirects and title not in visited:
        visited.add(title)
        title = redirects[title]
    pages = {page["title"]: page for page in query["pages"]}
    page = pages.get(title)
    if page is None or page.get("missing") or page.get("invalid"):
        raise ValueError(f"No Wikipedia page for {candidate.title_vi!r}")
    if "disambiguation" in page.get("pageprops", {}):
        raise ValueError(f"Disambiguation page: {title}")
    revisions = page.get("revisions", [])
    revision = revisions[0] if revisions else {}
    content = revision.get("slots", {}).get("main", {}).get("content", revision.get("content"))
    if content is None:
        raise ValueError(f"No wikitext returned for {title}")
    return RawPage(
        candidate_wikidata_id=candidate.wikidata_id,
        requested_title=candidate.title_vi,
        page_id=page["pageid"],
        canonical_title=page["title"],
        redirects=[row for row in query.get("redirects", []) if row["from"] in visited],
        source_url=page.get("fullurl") or article_url(page["title"]),
        extract=page.get("extract") or None,
        wikitext=content,
        revision_id=revision.get("revid"),
        revision_timestamp=revision.get("timestamp"),
        pageprops_wikidata_id=page.get("pageprops", {}).get("wikibase_item"),
        langlinks={row["lang"]: row["title"] for row in page.get("langlinks", [])},
        retrieved_at=utc_now(),
    )


def _manifest_row(
    candidate: CandidateCountry, status: str, page: RawPage | None = None, error: str = ""
) -> dict:
    return {
        "candidate_wikidata_id": candidate.wikidata_id or "",
        "requested_title": candidate.title_vi,
        "page_id": page.page_id if page else "",
        "canonical_title": page.canonical_title if page else "",
        "collection_status": status,
        "raw_file_path": f"data/raw/pages/{page.page_id}.json" if page else "",
        "error": error,
    }


def collect(
    candidates: list[CandidateCountry],
    settings: Settings,
    root: Path = ROOT,
    *,
    force: bool = False,
    client: HttpClient | None = None,
) -> list[dict]:
    """One batch request per 20 uncached titles; manifest covers this selection only."""
    client = client or HttpClient(settings)
    indexed = existing_pages(root)
    rows: list[dict] = []
    remaining = []
    for candidate in candidates:
        cached = indexed.get(candidate.title_vi)
        if cached and not force:
            rows.append(_manifest_row(candidate, "skipped", cached))
        else:
            remaining.append(candidate)

    for start in range(0, len(remaining), settings.batch_size):
        batch = remaining[start : start + settings.batch_size]
        try:
            query = _batch_response(client, settings, [item.title_vi for item in batch])["query"]
        except (RuntimeError, KeyError) as exc:
            LOG.error("Collection batch failed: %s", exc)
            rows.extend(_manifest_row(item, "failed", error=str(exc)) for item in batch)
            continue
        for candidate in batch:
            try:
                page = _raw_page(candidate, query)
                path = root / f"data/raw/pages/{page.page_id}.json"
                if path.exists() and not force:
                    # Shared redirects resolve to one file; preserve the existing source record.
                    stored = RawPage.model_validate(read_json(path))
                    if stored.page_id != page.page_id:
                        raise ValueError("Raw filename/page ID conflict")
                    status = "skipped"
                else:
                    write_json(path, page.model_dump(mode="json"))
                    status = "collected"
                indexed[candidate.title_vi] = page
                rows.append(_manifest_row(candidate, status, page))
            except (ValueError, ValidationError, KeyError, TypeError) as exc:
                LOG.warning("Could not collect %s: %s", candidate.title_vi, exc)
                rows.append(_manifest_row(candidate, "failed", error=str(exc)))
    # Preserve input order for the selection and repeatable downstream processing.
    order = {item.title_vi: index for index, item in enumerate(candidates)}
    rows.sort(key=lambda row: order[row["requested_title"]])
    write_csv(root / "data/raw/collection_manifest.csv", rows, MANIFEST_COLUMNS)
    return rows


def collect_reference(
    settings: Settings, root: Path = ROOT, *, force: bool = False, client: HttpClient | None = None
) -> list[dict]:
    reference = [
        CandidateCountry(
            title_vi=title,
            discovery_method="reference_title",
            discovery_methods=["reference_title"],
        )
        for title in settings.reference_titles
    ]
    rows = collect(reference, settings, root, force=force, client=client)
    write_json(
        root / "data/reference/pages.json",
        [
            {
                "requested_title": row["requested_title"],
                "page_id": row["page_id"],
                "raw_file_path": row["raw_file_path"],
            }
            for row in rows
            if row["page_id"]
        ],
    )
    return rows


def selected_raw_pages(root: Path) -> list[RawPage]:
    """Follow the last collection manifest, not unrelated cached pages from earlier runs."""
    from vi_dbpedia_data.utils import read_csv

    path = root / "data/raw/collection_manifest.csv"
    if not path.exists():
        raise FileNotFoundError(f"Run reference or collect first: {path}")
    pages = []
    for row in read_csv(path):
        if row["collection_status"] not in {"collected", "skipped"}:
            continue
        raw_path = root / row["raw_file_path"]
        try:
            page = RawPage.model_validate(read_json(raw_path))
            if (
                str(page.page_id) != row["page_id"]
                or page.canonical_title != row["canonical_title"]
            ):
                raise ValueError("Manifest/raw identity disagreement")
            pages.append(page)
        except (OSError, ValueError, ValidationError) as exc:
            LOG.warning("Missing or invalid selected raw file %s: %s", raw_path, exc)
    return pages
