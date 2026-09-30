"""Conservative, traceable conversions of Vietnamese Wikipedia infobox values."""

import re
import unicodedata
from urllib.parse import unquote

import mwparserfromhell

from vi_dbpedia_data.markup import (
    LIST_NAMES,
    is_currency_sign_target,
    is_currency_symbol_label,
    is_file_target,
    is_status_qualifier,
    list_items,
    normalize_resource_text,
    strip_annotations,
    template_name,
)
from vi_dbpedia_data.models import ResourceRef
from vi_dbpedia_data.utils import article_url

_REF = re.compile(r"<ref\b[^>]*>.*?</ref\s*>|<ref\b[^>]*/\s*>", re.I | re.S)
_FORMATNUM = re.compile(r"\{\{\s*formatnum\s*:\s*([\d.,\s]+?)\s*\}\}", re.I)
_NUMBER = re.compile(r"^-?\d[\d., \u00a0]*$")


def clean_text(value: str) -> str:
    """Keep ordinary Vietnamese spaces, newlines and accents; discard citation tags."""
    value = _REF.sub("", value)
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    return unicodedata.normalize("NFC", value).replace("\xa0", " ").strip()


def plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", mwparserfromhell.parse(clean_text(value)).strip_code()).strip()


def indicates_official_languages(value: str) -> bool:
    """The type label, not the generic `languages` key, must assert official status."""
    text = unicodedata.normalize("NFC", plain_text(value)).casefold()
    return (
        bool(re.search(r"ngôn\s+ngữ|tiếng", text))
        and bool(re.search(r"chính\s+thức", text))
        and not bool(re.search(r"(?:không|phi)\s+chính\s+thức", text))
        and not bool(
            re.search(
                r"công\s+nhận|recognised|recognized|thiểu\s+số|minority|"
                r"khu\s+vực|regional",
                text,
            )
        )
    )


def explicit_none_reason(field: str, value: str) -> str | None:
    """Recognize explicit absence in source text, not from a country's identity.

    The capital assertion may be inside a footnote. Do not interpret weaker
    qualifiers such as 'de facto' as a declaration of absence.
    """
    if field == "capital" and re.search(r"không\s+có\s+thủ\s+đô\s+chính\s+thức", value, re.I):
        return "Source explicitly states there is no official capital"
    text = plain_text(value).casefold().strip(" .:;!?")
    if text == "không có":
        return "Source explicitly states there is none"
    if field == "official_languages" and text == "không có ngôn ngữ chính thức":
        return "Source explicitly states there is no official language"
    return None


def _unique_resources(refs: list[ResourceRef]) -> list[ResourceRef]:
    """Use the wiki target as identity, retaining the first source display label."""
    seen: set[str] = set()
    result = []
    for ref in refs:
        key = unicodedata.normalize("NFC", ref.wiki_title or ref.label_vi).strip().casefold()
        if key not in seen:
            result.append(ref)
            seen.add(key)
    return result


def resources(value: str, *, field: str | None = None) -> list[ResourceRef]:
    code = mwparserfromhell.parse(strip_annotations(value))
    lists = [
        template
        for template in code.filter_templates(recursive=False)
        if template_name(template) in LIST_NAMES
    ]
    # A plainlist of official languages takes precedence over a separately
    # labeled collapsible list of languages with merely special status.
    primary = [item for item in lists if template_name(item) in {"plainlist", "plain list"}]
    selected = primary or lists
    if selected:
        if len(selected) != 1:
            return []
        items = [item for item in list_items(selected[0]) if strip_annotations(item).strip()]
        if any(re.search(r"de\s*jure|de\s*facto", strip_annotations(item), re.I) for item in items):
            return []  # Distinct legal-status sections cannot be flattened.
        parts = [resources(item, field=field) for item in items]
        if not parts or not all(parts):
            return []
        return _unique_resources([ref for group in parts for ref in group])
    # Other template output is not necessarily visible in wikitext.
    if code.filter_templates(recursive=False):
        return []
    segments = [part.strip() for part in str(code).splitlines() if part.strip()]
    if len(segments) > 1:
        parts = [resources(part, field=field) for part in segments if not part.startswith("(")]
        return (
            _unique_resources([ref for group in parts for ref in group])
            if parts and all(parts)
            else []
        )
    links = code.filter_wikilinks(recursive=False)
    if links:
        source = str(code)
        prefix = source.split("[[", 1)[0]
        if re.sub(r"[\s'\"()]+", "", prefix):
            return []  # a link following an unlinked name may be just a qualifier
        scope = (
            re.search(
                r"là\s+ngôn\s+ngữ\s+chính\s+thức\s+tại\b|"
                r"(?:được\s+sử\s+dụng|áp\s+dụng)\s+(?:ở|tại)\b",
                source,
                re.I,
            )
            if field == "official_languages"
            else None
        )
        refs = []
        cursor = 0
        for link in links:
            link_pos = source.find(str(link), cursor)
            cursor = link_pos + len(str(link))
            target = normalize_resource_text(clean_text(str(link.title)).split("#", 1)[0])
            normalized = target.replace("_", " ").casefold()
            if (
                not target
                or is_file_target(target)
                or re.match(r"^(?:category|thể loại)\s*:", normalized)
                or normalized.startswith("ký hiệu ")
                or "{{" in target
            ):
                continue
            if normalized in {"de facto", "de jure", "iso 4217"}:
                continue
            label = (
                normalize_resource_text(plain_text(str(link.text)))
                if link.text is not None
                else normalize_resource_text(target.replace("_", " "))
            )
            if is_currency_symbol_label(label):
                continue
            if field == "currencies" and is_currency_sign_target(target):
                continue
            if (
                field == "capital"
                and is_status_qualifier(label, target)
                and re.search(rf"\(\s*{re.escape(str(link))}\s*\)", source)
            ):
                continue
            # An immediately trailing parenthetical language link qualifies
            # the preceding direct value; it is not a list separator.
            if (
                field == "official_languages"
                and refs
                and re.search(rf"\(\s*{re.escape(str(link))}\s*\)\s*$", source)
                and re.search(r"\]\]\s*\(\s*$", source[:link_pos])
            ):
                continue
            if scope and link_pos >= scope.start():
                continue
            # A parenthetical dialect label qualifies the preceding language;
            # it is not another official language in the same source field.
            if re.match(r"(?:phương ngữ|dialect)\b", label, re.I) and re.search(
                rf"\(\s*{re.escape(str(link))}\s*\)", str(code)
            ):
                continue
            if label:
                refs.append(ResourceRef(label_vi=label, wiki_title=target.replace("_", " ")))
        return _unique_resources(refs)
    # Only explicitly separated unlinked names; retain no fabricated Wikipedia title.
    text = normalize_resource_text(code.strip_code())
    text = re.sub(r"\s*\([A-Z]{3}\)\s*$", "", text)
    if (
        not text
        or text.endswith(":")
        or "{{" in text
        or "}}" in text
        or text.casefold()
        in {
            "—",
            "–",
            "-",
            "?",
            "n/a",
            "không rõ",
            "chưa rõ",
            "không có",
        }
    ):
        return []
    parts = re.split(r"\s*(?:[,;\n]|\s+và\s+)\s*", text, flags=re.I)
    return [
        ResourceRef(label_vi=part, wiki_title=None)
        for part in parts
        if part and not (field == "currencies" and is_currency_symbol_label(part))
    ]


def _numeric_text(value: str) -> str:
    text = clean_text(strip_annotations(value))
    text = re.sub(r"(?<=\d)[¹²³⁴⁵⁶⁷⁸⁹⁰]+$", "", text).strip()
    text = re.sub(r"\{\{\s*(?:increase|decrease)(?:neutral)?\s*\}\}", "", text, flags=re.I)
    text = _FORMATNUM.sub(lambda match: match[1].strip(), text)
    if "{{" in text or "}}" in text:
        return ""
    return plain_text(text).replace("\u202f", " ")


def _number(value: str, *, decimal: bool) -> float | int | None:
    """Use Vietnamese dot/comma grouping only for groups of exactly three digits.

    Thus 41.285 is 41,285, while 744.3 has a fractional part and stays 744.3.
    Ambiguous mixed or irregular grouping is rejected instead of guessed.
    """
    value = value.strip().replace(" ", "")
    if not _NUMBER.fullmatch(value):
        return None
    sign = -1 if value.startswith("-") else 1
    digits = value.lstrip("-")
    if digits.isdigit():
        return sign * (float(digits) if decimal else int(digits))
    if "." in digits and "," in digits and decimal:
        separator = "." if digits.rfind(".") > digits.rfind(",") else ","
        grouped, fraction = digits.rsplit(separator, 1)
        grouping = "," if separator == "." else "."
        if (
            fraction.isdigit()
            and 1 <= len(fraction) <= 2
            and re.fullmatch(rf"\d{{1,3}}(?:\{grouping}\d{{3}})+", grouped)
        ):
            return sign * float(grouped.replace(grouping, "") + "." + fraction)
        return None
    if "." in digits and "," in digits:
        return None
    separator = "." if "." in digits else ","
    if re.fullmatch(rf"\d{{1,3}}(?:\{separator}\d{{3}})+", digits):
        return sign * (
            float(digits.replace(separator, "")) if decimal else int(digits.replace(separator, ""))
        )
    if decimal and re.fullmatch(rf"\d+\{separator}\d{{1,2}}", digits):
        return sign * float(digits.replace(separator, "."))
    return None


def population(value: str) -> int | None:
    text = _numeric_text(value)
    text = re.sub(r"\s*\([^()\d]+\)\s*$", "", text)
    number = _number(text, decimal=False)
    return number if isinstance(number, int) else None


def population_options(value: str) -> list[int] | None:
    """Recognize structured distinct numbers, never choose a scope arbitrarily."""
    clean = strip_annotations(value)
    code = mwparserfromhell.parse(clean)
    lists = [t for t in code.filter_templates(recursive=False) if template_name(t) in LIST_NAMES]
    if len(lists) == 1:
        parts = list_items(lists[0])
        numbers = [population(part) for part in parts]
        found = [number for number in numbers if number is not None]
        return found if len(found) > 1 else None
    parts = clean.splitlines()
    if len(parts) < 2:
        return None
    numbers = [population(part) for part in parts]
    return numbers if all(number is not None for number in numbers) else None


def semantic_ambiguity(field: str, value: str) -> str | None:
    """Flag irreducible legal-status distinctions and numeric ranges."""
    contextual = clean_text(value)  # Legal qualifiers can occur inside <small>.
    if (
        field == "official_languages"
        and re.search(r"không\s+có", contextual, re.I)
        and re.search(r"de\s*facto", contextual, re.I)
    ):
        return "de jure absence and de facto languages cannot be one unqualified field"
    if (
        field == "official_languages"
        and re.search(r"de\s*facto", contextual, re.I)
        and re.search(r"thiểu\s+số|minority", contextual, re.I)
    ):
        return "de facto language and official minority-language scopes require review"
    # A plainlist plus a separate status group is handled by the list parser;
    # a lone nested 'other' group is not safely equivalent to a direct value.
    if (
        field == "official_languages"
        and re.search(r"\{\{\s*collapsible\s+list", value, re.I)
        and not re.search(r"\{\{\s*plain\s*list", value, re.I)
    ):
        return "direct language plus collapsible list has unclear same-field membership"
    if (
        field == "currencies"
        and re.search(r"de\s*jure", contextual, re.I)
        and re.search(r"de\s*facto", contextual, re.I)
    ):
        return "separate de jure and de facto currency sections require review"
    if field in {"population_total", "area_km2"}:
        text = _numeric_text(value)
        match = re.fullmatch(r"\s*(\d[\d., ]*)\s*[–—-]\s*(\d[\d., ]*)\s*", text)
        if match:
            parser = population if field == "population_total" else area
            options = [parser(match[1]), parser(match[2])]
            if all(option is not None for option in options) and options[0] != options[1]:
                return f"numeric range has no single canonical value: {options}"
    return None


def _unambiguous_sq_mi(value: str) -> float | None:
    text = re.sub(r"\s*(?:sq\.?\s*mi|mi²)\s*$", "", _numeric_text(value), flags=re.I)
    if re.fullmatch(r"0[.,]\d{3}", text):
        return float(text.replace(",", "."))
    if re.fullmatch(r"\d{1,3}[.,]\d{3}", text):
        return None  # This source also has ambiguous grouping.
    number = _number(text, decimal=True)
    return float(number) if number is not None else None


def area(value: str, *, sq_mi_raw: str | None = None) -> float | None:
    value = re.sub(r"(km)\s*<sup>\s*2\s*</sup>", r"\1²", value, flags=re.I)
    text = _numeric_text(value)
    match = re.fullmatch(r"(.*?)\s*(km²|km2|km\^2|sq\.?\s*mi|mi²)?\s*", text, flags=re.I)
    if not match:
        return None
    number = _number(match[1], decimal=True)
    if number is None:
        return None
    unit = match[2] or "km²"  # mapped numeric-only area values use the km² convention
    if sq_mi_raw and unit.lower().startswith("km"):
        # A single separator + three trailing digits is ambiguous. An
        # independent *infobox* sq-mile value can disambiguate it, but an
        # ambiguous sq-mile number or article prose cannot.
        components = re.fullmatch(r"(\d{1,3})[.,](\d{3})", match[1].strip())
        miles = _unambiguous_sq_mi(sq_mi_raw)
        if components and miles is not None and miles > 0:
            decimal = float(f"{components[1]}.{components[2]}")
            expected = miles * 2.589988110336
            fits = [
                candidate
                for candidate in (float(number), decimal)
                if abs(candidate - expected) / expected <= 0.05
            ]
            if len(fits) == 1:
                return fits[0]
            # Different area definitions can disagree without implying a
            # decimal separator error. Retain the original interpretation if
            # this independent measurement cannot decide the two scales.
    return (
        round(float(number) * 2.589988110336, 6)
        if unit.lower().startswith(("sq", "mi"))
        else float(number)
    )


def calling_codes(value: str) -> list[str]:
    """Normalize only visible direct dialling-code text, not note contents."""
    text = plain_text(strip_annotations(value))
    if "{{" in text or "}}" in text:
        return []
    if re.search(r"\(\s*(?:approx\.?|khoảng|ước tính)", text, re.I):
        return []
    text = re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]", "", text)
    # Parenthesized prose (e.g. an alternative dialling route) is explanatory.
    text = re.sub(r"\([^)]*[A-Za-zÀ-ỹ][^)]*\)", "", text).strip()
    text = re.sub(r"(?<=\d)\s+(-\d{3})(?!\d)", r"\1", text)
    codes = []
    for segment in re.split(r"\s*[,;/\n]\s*", text):
        segment = segment.strip()
        if not segment:
            continue
        match = re.fullmatch(r"\+?(\d{1,4})(?:[ -](\d{1,4}|\dxx))?", segment, re.I)
        if not match:
            return []
        first, second = match.groups()
        codes.append("+" + first + ("-" + second if second else ""))
    return list(dict.fromkeys(codes))


def english_links(title: str | None) -> tuple[str | None, str | None, str | None]:
    if not title:
        return None, None, None
    title = unicodedata.normalize("NFC", unquote(title)).replace("_", " ").strip()
    if not title:
        return None, None, None
    return title, article_url(title, lang="en"), article_url(title, dbpedia=True)
