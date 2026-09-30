"""Conservative MediaWiki AST cleanup shared by resource and scalar parsers."""

import html
import re
import unicodedata

import mwparserfromhell
from mwparserfromhell.nodes import Comment, Tag, Template, Wikilink

_NOTE_NAMES = {
    "efn",
    "efn-ur",
    "efn-ua",
    "ref",
    "refn",
    "ref label",
    "notetag",
    "sfn",
    "sfnp",
    "rp",
    "references",
    "chú thích",
    "coord",
    "tọa độ",
}
_PRESENTATION_NAMES = {
    "small",
    "smaller",
    "nobold",
    "code",
    "lang",
    "langx",
    "transl",
    "nihongo2",
    "smallsup",
    "sup",
    "flagicon image",
    "flagicon",
    "\\",
    "increase",
    "decrease",
    "increaseneutral",
    "decreaseneutral",
}
_NOTE_TAGS = {"ref", "small", "sup", "code"}
_FILE_NAMESPACES = {"file", "image", "tập tin", "hình"}
LIST_NAMES = {"ubl", "unbulleted list", "plainlist", "plain list", "flatlist", "hlist", "ublist"}
LINE_LIST_NAMES = {"plainlist", "plain list", "flatlist"}


def template_name(template: Template) -> str:
    return re.sub(r"\s+", " ", str(template.name).replace("_", " ").strip().casefold())


def normalize_resource_text(value: str) -> str:
    """Decode HTML entities and NBSPs without stripping Vietnamese accents."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", html.unescape(value))).strip()


def is_file_target(title: str) -> bool:
    target = normalize_resource_text(title).replace("_", " ")
    match = re.match(r"^:?\s*([^:]+?)\s*:", target)
    return bool(match and match[1].strip().casefold() in _FILE_NAMESPACES)


def is_currency_symbol_label(label: str) -> bool:
    label = normalize_resource_text(label)
    return bool(label) and all(unicodedata.category(char) == "Sc" for char in label)


def is_currency_sign_target(title: str) -> bool:
    title = normalize_resource_text(title).casefold()
    return bool(re.search(r"^ký\s+hiệu\b|\b(?:currency\s+)?(?:sign|symbol)$", title))


def is_status_qualifier(label: str, title: str) -> bool:
    text = f"{normalize_resource_text(label)} {normalize_resource_text(title)}".casefold()
    return bool(
        re.search(
            r"vị\s+thế|tình\s+trạng|quy\s+chế|công\s+nhận|"
            r"tranh\s+chấp|status|recognition",
            text,
        )
    )


def is_file_link(link: Wikilink) -> bool:
    return is_file_target(str(link.title))


def _is_note(template: Template) -> bool:
    name = template_name(template)
    if name in _NOTE_NAMES or name.startswith(("cite ", "chú thích ")):
        return True
    if name in {"un population", "un_population"}:
        return bool(template.params and str(template.params[0].value).strip().casefold() == "ref")
    if name.startswith("infobox"):
        return any(
            str(p.name).strip().casefold() == "child" and str(p.value).strip().casefold() == "yes"
            for p in template.params
        )
    return False


def strip_annotations(value: str) -> str:
    """Discard note-only nodes; unwrap only allowlisted semantic presentation.

    Unknown templates and parser functions remain visible so callers can report
    unresolved values instead of taking links from arbitrary nested markup.
    """
    code = mwparserfromhell.parse(value)
    for _ in range(10):
        changed = False
        for node in list(code.nodes):
            if isinstance(node, Comment):
                code.remove(node)
            elif isinstance(node, Tag):
                name = str(node.tag).strip().casefold()
                if name in _NOTE_TAGS:
                    code.remove(node)
                elif name == "br":
                    code.replace(node, "\n")
                elif name == "wbr":
                    code.remove(node)
                else:
                    continue
            elif isinstance(node, Wikilink) and is_file_link(node):
                code.remove(node)
            elif isinstance(node, Template):
                name = template_name(node)
                if _is_note(node) or name in _PRESENTATION_NAMES:
                    code.remove(node)
                elif name == "nowrap" and len(node.params) == 1:
                    code.replace(node, str(node.params[0].value))
                elif name == "*":
                    code.replace(node, "\n")
                else:
                    continue
            else:
                continue
            changed = True
        if not changed:
            break
    return str(code)


def list_items(template: Template) -> list[str]:
    """Read only top-level positional list values, not named style/citation data."""
    params = [
        str(param.value)
        for param in template.params
        if not param.showkey or str(param.name).strip().isdigit()
    ]
    if template_name(template) in LINE_LIST_NAMES:
        items = []
        for value in params:
            current = []
            for line in re.sub(r"<br\s*/?>", "\n", value, flags=re.I).splitlines():
                if re.match(r"^\s*[*#]\s*", line):
                    if current:
                        items.append("\n".join(current))
                    current = [re.sub(r"^\s*[*#]\s*", "", line)]
                elif line.strip():
                    current.append(line)
            if current:
                items.append("\n".join(current))
        return items
    return params
