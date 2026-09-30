"""Non-destructive, conservative checks on already-normalized records."""

import json
import re

from vi_dbpedia_data.markup import (
    is_currency_sign_target,
    is_currency_symbol_label,
    is_file_target,
    is_status_qualifier,
)
from vi_dbpedia_data.models import CountryRecord

RESOURCE_FIELDS = ("capital", "currencies", "official_languages")
CALLING_CODE = re.compile(r"\+\d{1,4}(?:-\d{1,4}|-\dxx)?", re.I)
MARKUP = re.compile(r"\[\[|\]\]|\{\{|\}\}|<\s*(?:ref|small|sup)\b", re.I)
PIXEL_LABEL = re.compile(r"\d+(?:\.\d+)?\s*px", re.I)
HTML_ENTITY = re.compile(r"&(?:[a-z][a-z0-9]+|#(?:\d+|x[0-9a-f]+));", re.I)
GEOGRAPHIC_SCOPE = re.compile(
    r"\b(?:island|islands|province|city|region)\b|"
    r"\b(?:đảo|quần đảo|thành phố|tỉnh|vùng)\b",
    re.I,
)
ABSTRACT_KM2 = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d{1,2})?)\s*km\s*(?:²|2|\^2)(?!\w)", re.I)


def _explicit_abstract_area(record: CountryRecord) -> list[float]:
    """Take only unambiguous, country-qualified area mentions for QA—not facts."""
    abstract = record.abstract_vi or ""
    values = []
    for match in ABSTRACT_KM2.finditer(abstract):
        context = abstract[max(0, match.start() - 110) : match.start()].casefold()
        if record.title_vi.casefold() not in context or not any(
            word in context for word in ("diện tích", "area")
        ):
            continue
        values.append(float(match[1].replace(",", ".")))
    return values


def sanity_issues(records: list[CountryRecord]) -> list[dict]:
    """Flag suspect values for inspection without changing their status or data."""
    issues = []
    for record in records:

        def flag(field: str, category: str, value: object, source: CountryRecord = record) -> None:
            issues.append(
                {
                    "page_id": source.page_id,
                    "title_vi": source.title_vi,
                    "canonical_field": field,
                    "category": category,
                    "value": json.dumps(value, ensure_ascii=False),
                }
            )

        if record.population_total is not None:
            if record.population_total <= 0:
                flag("population_total", "nonpositive_number", record.population_total)
            elif record.population_total < 100 or record.population_total > 2_000_000_000:
                flag("population_total", "implausible_magnitude_review", record.population_total)
        if record.area_km2 is not None:
            if record.area_km2 <= 0:
                flag("area_km2", "nonpositive_number", record.area_km2)
            elif record.area_km2 < 0.01 or record.area_km2 > 40_000_000:
                flag("area_km2", "implausible_magnitude_review", record.area_km2)
            if record.area_km2 > 0:
                abstract_values = [value for value in _explicit_abstract_area(record) if value > 0]
                ratios = [record.area_km2 / value for value in abstract_values]
                if any(800 <= ratio <= 1200 for ratio in ratios) and not any(
                    0.8 <= ratio <= 1.2 for ratio in ratios
                ):
                    flag(
                        "area_km2",
                        "abstract_area_thousandfold_review",
                        {
                            "processed_km2": record.area_km2,
                            "abstract_km2": abstract_values,
                        },
                    )
        for field in ("title_vi", "abstract_vi", "wikidata_id", "english_title"):
            value = getattr(record, field)
            if value and MARKUP.search(value):
                flag(field, "unresolved_markup", value)
            if value and HTML_ENTITY.search(value):
                flag(field, "unresolved_html_entity", value)
        for field in RESOURCE_FIELDS:
            seen = set()
            for ref in getattr(record, field):
                identity = (ref.wiki_title or ref.label_vi).strip().casefold()
                if identity in seen:
                    flag(field, "duplicate_resource_ref", ref.model_dump())
                seen.add(identity)
                if not ref.label_vi.strip():
                    flag(field, "empty_resource_label", ref.model_dump())
                if MARKUP.search(ref.label_vi) or (
                    ref.wiki_title and MARKUP.search(ref.wiki_title)
                ):
                    flag(field, "unresolved_markup", ref.model_dump())
                if HTML_ENTITY.search(ref.label_vi) or (
                    ref.wiki_title and HTML_ENTITY.search(ref.wiki_title)
                ):
                    flag(field, "unresolved_html_entity", ref.model_dump())
                if PIXEL_LABEL.fullmatch(ref.label_vi.strip()):
                    flag(field, "pixel_size_resource_label", ref.model_dump())
                if ref.wiki_title and is_file_target(ref.wiki_title):
                    flag(field, "file_as_resource_target", ref.model_dump())
                if field == "currencies":
                    if is_currency_symbol_label(ref.label_vi):
                        flag(field, "currency_symbol_label", ref.model_dump())
                    if ref.wiki_title and is_currency_sign_target(ref.wiki_title):
                        flag(field, "currency_sign_target", ref.model_dump())
                if field == "capital" and is_status_qualifier(ref.label_vi, ref.wiki_title or ""):
                    flag(field, "capital_status_qualifier", ref.model_dump())
                if field == "official_languages" and GEOGRAPHIC_SCOPE.search(
                    f"{ref.label_vi} {ref.wiki_title or ''}"
                ):
                    flag(field, "language_geographic_scope", ref.model_dump())
        for code in record.calling_codes:
            if not CALLING_CODE.fullmatch(code):
                flag("calling_codes", "malformed_calling_code", code)
            elif "x" in code.casefold():
                flag("calling_codes", "calling_code_wildcard_review", code)
    return issues
