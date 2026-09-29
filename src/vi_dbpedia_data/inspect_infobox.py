"""Inspect country templates and retain all original parameter spelling/value text."""

import logging
from collections import Counter, defaultdict
from pathlib import Path

import mwparserfromhell
from pydantic import ValidationError

from vi_dbpedia_data.collect import selected_raw_pages
from vi_dbpedia_data.models import RawPage
from vi_dbpedia_data.utils import ROOT, Settings, normalize_key, read_json, write_csv

TEMPLATE_COLUMNS = [
    "country_title",
    "page_id",
    "template_name",
    "selection_method",
    "all_template_count",
    "selected_infobox_parameter_count",
    "other_templates",
]
KEY_COLUMNS = ["country_title", "template_name", "raw_key", "normalized_key", "raw_value"]
FREQUENCY_COLUMNS = [
    "normalized_key",
    "occurrence_count",
    "page_count",
    "coverage_percentage",
    "example_raw_keys",
    "example_values",
]
LOG = logging.getLogger(__name__)


def select_infobox(
    wikitext: str, settings: Settings, *, country_candidate: bool = False
) -> tuple[object | None, str, list[str]]:
    """Select an exact configured alias first; never guess from an unrelated template."""
    templates = mwparserfromhell.parse(wikitext).filter_templates(recursive=False)
    aliases = {normalize_key(alias) for alias in settings.infobox_template_aliases}
    names = [str(template.name).strip() for template in templates]
    exact = [template for template in templates if normalize_key(str(template.name)) in aliases]
    if len(exact) == 1:
        return exact[0], "configured_alias", names
    if len(exact) > 1:
        return None, "ambiguous_alias", names
    likely = [
        template
        for template in templates
        if any(
            word in normalize_key(str(template.name))
            for word in ("country", "quốc_gia", "quoc_gia")
        )
    ]
    if len(likely) == 1:
        return likely[0], "name_heuristic", names
    if country_candidate and not likely:
        fallback_aliases = {
            normalize_key(alias) for alias in settings.candidate_infobox_template_aliases
        }
        fallback = [
            template
            for template in templates
            if normalize_key(str(template.name)) in fallback_aliases
        ]
        if len(fallback) == 1:
            return fallback[0], "candidate_template_alias", names
        if len(fallback) > 1:
            return None, "ambiguous_candidate_alias", names
    return None, "ambiguous_heuristic" if likely else "not_found", names


def infobox_values(template: object) -> dict[str, list[str]]:
    """Use lists so even repeated infobox keys cannot silently overwrite raw values."""
    values: dict[str, list[str]] = defaultdict(list)
    for param in template.params:
        values[str(param.name)].append(str(param.value))
    return dict(values)


def _available_pages(paths: list[Path]) -> list[RawPage]:
    pages = []
    for path in paths:
        try:
            page = RawPage.model_validate(read_json(path))
            if path.stem != str(page.page_id):
                raise ValueError("Raw filename/page ID disagreement")
            pages.append(page)
        except (OSError, ValueError, ValidationError) as exc:
            LOG.warning("Cannot inspect %s: %s", path, exc)
    return pages


def inspect(
    settings: Settings,
    root: Path = ROOT,
    *,
    reference_only: bool = False,
    all_available: bool = False,
) -> dict:
    if reference_only and all_available:
        raise ValueError("Choose either reference-only or all available pages")
    if reference_only:
        path = root / "data/reference/pages.json"
        if not path.exists():
            raise FileNotFoundError(f"Run reference first: {path}")
        pages = _available_pages([root / item["raw_file_path"] for item in read_json(path)])
    elif all_available:
        pages = _available_pages(sorted((root / "data/raw/pages").glob("*.json")))
    else:
        pages = selected_raw_pages(root)
    return inspect_pages(pages, settings, root)


def inspect_pages(pages: list[RawPage], settings: Settings, root: Path) -> dict:
    templates, keys = [], []
    seen = set()
    for page in pages:
        if page.page_id in seen:
            continue
        seen.add(page.page_id)
        selected, method, names = select_infobox(
            page.wikitext, settings, country_candidate=bool(page.candidate_wikidata_id)
        )
        template_name = str(selected.name).strip() if selected else ""
        templates.append(
            {
                "country_title": page.canonical_title,
                "page_id": page.page_id,
                "template_name": template_name,
                "selection_method": method,
                "all_template_count": len(names),
                "selected_infobox_parameter_count": len(selected.params) if selected else 0,
                "other_templates": "; ".join(list(dict.fromkeys(names))[:20]),
            }
        )
        if selected:
            for param in selected.params:
                raw_key = str(param.name)
                keys.append(
                    {
                        "country_title": page.canonical_title,
                        "template_name": template_name,
                        "raw_key": raw_key,
                        "normalized_key": normalize_key(raw_key),
                        "raw_value": str(param.value),
                    }
                )
    occurrences = Counter(row["normalized_key"] for row in keys)
    examples: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in keys:
        key = row["normalized_key"]
        examples[key]["pages"].add(row["country_title"])
        examples[key]["keys"].add(row["raw_key"])
        examples[key]["values"].add(row["raw_value"])
    frequency = [
        {
            "normalized_key": key,
            "occurrence_count": count,
            "page_count": len(examples[key]["pages"]),
            "coverage_percentage": round(100 * len(examples[key]["pages"]) / len(seen), 2),
            "example_raw_keys": " | ".join(sorted(examples[key]["keys"])[:3]),
            "example_values": " | ".join(sorted(examples[key]["values"])[:3]),
        }
        for key, count in sorted(occurrences.items())
    ]
    reference_path = root / "data/reference/pages.json"
    reference_ids = (
        {item["page_id"] for item in read_json(reference_path)}
        if reference_path.exists()
        else set()
    )
    reference_titles = {
        row["country_title"] for row in templates if row["page_id"] in reference_ids
    }
    out = root / "data/reports"
    write_csv(out / "infobox_templates.csv", templates, TEMPLATE_COLUMNS)
    write_csv(out / "infobox_key_frequency.csv", frequency, FREQUENCY_COLUMNS)
    write_csv(
        out / "reference_infobox_keys.csv",
        [row for row in keys if row["country_title"] in reference_titles],
        KEY_COLUMNS,
    )
    return {
        "attempted": len(seen),
        "selected": sum(bool(row["template_name"]) for row in templates),
        "keys": len(keys),
    }
