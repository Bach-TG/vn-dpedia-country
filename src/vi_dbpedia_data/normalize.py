"""Conservative, traceable conversions of Vietnamese Wikipedia infobox values."""

import re
import unicodedata
from urllib.parse import unquote

import mwparserfromhell

from vi_dbpedia_data.models import ResourceRef
from vi_dbpedia_data.utils import article_url

_REF = re.compile(r"<ref\b[^>]*>.*?</ref\s*>|<ref\b[^>]*/\s*>", re.I | re.S)
_FORMATNUM = re.compile(r"\{\{\s*formatnum\s*:\s*([\d.,\s]+?)\s*\}\}", re.I)
_NUMBER = re.compile(r"^-?\d[\d., \u00a0]*$")
_NOTE_TEMPLATES = {"efn", "sfn", "ref", "refn", "ref label"}
_LIST_TEMPLATES = {"plainlist", "unbulleted list", "ublist", "hlist"}
_DECORATION_TEMPLATES = {"transl", "nihongo2", "\\", "coord"}


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


def resources(value: str) -> list[ResourceRef]:
    source = mwparserfromhell.parse(value)
    for template in source.filter_templates(recursive=False):
        if str(template.name).strip().casefold() in _NOTE_TEMPLATES:
            source.remove(template)
    text = clean_text(str(source))
    code = mwparserfromhell.parse(text)
    lists = [
        template
        for template in code.filter_templates(recursive=False)
        if str(template.name).strip().casefold() in _LIST_TEMPLATES
    ]
    # A plainlist of official languages takes precedence over a separately
    # labeled collapsible list of languages with merely special status.
    primary = [item for item in lists if str(item.name).strip().casefold() == "plainlist"]
    selected = primary or lists
    if selected:
        if len(selected) != 1:
            return []
        values = [
            param
            for param in selected[0].params
            if not param.showkey or str(param.name).strip().isdigit()
        ]
        if str(selected[0].name).strip().casefold() == "plainlist":
            items = [
                re.sub(r"^\s*[*#]\s*", "", line)
                for param in values
                for line in str(param.value).splitlines()
                if line.strip()
            ]
        else:
            items = [str(param.value) for param in values]
        parts = [resources(item) for item in items]
        return [ref for group in parts for ref in group] if all(parts) else []
    for template in code.filter_templates(recursive=False):
        if str(template.name).strip().casefold() in _DECORATION_TEMPLATES:
            code.remove(template)
    # Other template output is not necessarily visible in wikitext.
    if code.filter_templates():
        return []
    links = code.filter_wikilinks()
    if links:
        prefix = str(code).split("[[", 1)[0]
        if re.sub(r"[\s'\"()]+", "", prefix):
            return []  # a link following an unlinked name may be just a qualifier
        refs = []
        for link in links:
            target = clean_text(str(link.title)).split("#", 1)[0].strip()
            normalized = target.replace("_", " ").casefold()
            if not target or normalized.startswith(
                ("file:", "tập tin:", "image:", "category:", "thể loại:")
            ):
                continue
            if normalized in {"de facto", "de jure", "iso 4217"}:
                continue
            label = (
                plain_text(str(link.text)) if link.text is not None else target.replace("_", " ")
            )
            # A parenthetical dialect label qualifies the preceding language;
            # it is not another official language in the same source field.
            if re.match(r"(?:phương ngữ|dialect)\b", label, re.I) and re.search(
                rf"\(\s*{re.escape(str(link))}\s*\)", str(code)
            ):
                continue
            if label:
                refs.append(ResourceRef(label_vi=label, wiki_title=target.replace("_", " ")))
        return [
            ResourceRef(label_vi=label, wiki_title=title)
            for label, title in dict.fromkeys((ref.label_vi, ref.wiki_title) for ref in refs)
        ]
    # Only explicitly separated unlinked names; retain no fabricated Wikipedia title.
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = mwparserfromhell.parse(text).strip_code().strip()
    if (
        not text
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
    return [ResourceRef(label_vi=part, wiki_title=None) for part in parts if part]


def _numeric_text(value: str) -> str:
    source = mwparserfromhell.parse(value)
    for template in source.filter_templates(recursive=False):
        if str(template.name).strip().casefold() in _NOTE_TEMPLATES:
            source.remove(template)
    text = clean_text(str(source))
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
    number = _number(_numeric_text(value), decimal=False)
    return number if isinstance(number, int) else None


def population_options(value: str) -> list[int] | None:
    """Parse explicit <br>-separated scalar alternatives without choosing one."""
    parts = re.split(r"<br\s*/?>", value, flags=re.I)
    if len(parts) < 2:
        return None
    numbers = [population(part) for part in parts]
    return numbers if all(number is not None for number in numbers) else None


def area(value: str) -> float | None:
    text = _numeric_text(value)
    match = re.fullmatch(r"(.*?)\s*(km²|km2|km\^2|sq\.?\s*mi|mi²)?\s*", text, flags=re.I)
    if not match:
        return None
    number = _number(match[1], decimal=True)
    if number is None:
        return None
    unit = match[2] or "km²"  # mapped numeric-only area values use the km² convention
    return (
        round(float(number) * 2.589988110336, 6)
        if unit.lower().startswith(("sq", "mi"))
        else float(number)
    )


def calling_codes(value: str) -> list[str]:
    text = _numeric_text(value)
    if not text:
        # Numeric cleanup rejects '+', so use markup-stripped text for phone codes.
        text = plain_text(clean_text(value)) if "{{" not in value else ""
    if not text or re.search(r"\{\{|\}\}", text):
        return []
    codes = re.findall(r"(?<!\w)\+\d{1,4}(?!\d)", text)
    remainder = re.sub(r"(?<!\w)\+\d{1,4}(?!\d)", "", text)
    if re.sub(r"[\s,;/()\-và]", "", remainder):
        return []
    return list(dict.fromkeys(codes))


def english_links(title: str | None) -> tuple[str | None, str | None, str | None]:
    if not title:
        return None, None, None
    title = unicodedata.normalize("NFC", unquote(title)).replace("_", " ").strip()
    if not title:
        return None, None, None
    return title, article_url(title, lang="en"), article_url(title, dbpedia=True)
