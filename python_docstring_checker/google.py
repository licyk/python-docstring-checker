"""Parser for the Google-style docstring sections used by the checker."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from python_docstring_checker.types import is_type_like


SECTION_NAMES = {
    "Args",
    "Arguments",
    "Attributes",
    "Parameters",
    "Raises",
    "Returns",
    "Yields",
}

ARG_SECTION_NAMES = {"Args", "Arguments", "Parameters"}

_SECTION_RE = re.compile(r"^([A-Z][A-Za-z ]+):\s*$")
_NAMED_ITEM_RE = re.compile(
    r"^\s*(?P<name>\*\*?[A-Za-z_]\w*|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
    r"\s*(?:(?:\((?P<type>[^)]*)\))|(?::\s*\((?P<type_after_colon>[^)]*)\)))?"
    r"\s*:\s*(?P<desc>.*)$"
)
_RETURN_ITEM_RE = re.compile(r"^\s*(?P<type>[^:]+?)\s*:\s*(?P<desc>.*)$")


@dataclass(frozen=True)
class DocItem:
    """An item parsed from a Google-style docstring section."""

    name: str
    type: str | None = None
    description: str = ""


@dataclass(frozen=True)
class ParsedDocstring:
    """Structured view of the Google-style sections in a docstring."""

    args: dict[str, DocItem] = field(default_factory=dict)
    malformed_args: tuple[DocItem, ...] = ()
    attributes: dict[str, DocItem] = field(default_factory=dict)
    raises: dict[str, DocItem] = field(default_factory=dict)
    returns: DocItem | None = None
    yields: DocItem | None = None


def parse_google_docstring(docstring: str | None) -> ParsedDocstring:
    """Parse supported Google-style sections from a docstring."""
    if not docstring:
        return ParsedDocstring()

    raw_sections = _collect_sections(docstring)

    args: dict[str, DocItem] = {}
    malformed_args: list[DocItem] = []
    for section_name in ARG_SECTION_NAMES:
        section_args, section_malformed_args = _parse_arg_items(
            raw_sections.get(section_name, [])
        )
        args.update(section_args)
        malformed_args.extend(section_malformed_args)

    return ParsedDocstring(
        args=args,
        malformed_args=tuple(malformed_args),
        attributes=_parse_named_items(raw_sections.get("Attributes", [])),
        raises=_parse_named_items(raw_sections.get("Raises", [])),
        returns=_parse_return_item(raw_sections.get("Returns", []), "return"),
        yields=_parse_return_item(raw_sections.get("Yields", []), "yield"),
    )


def _collect_sections(docstring: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in docstring.splitlines():
        match = _SECTION_RE.match(line.strip()) if _is_unindented(line) else None
        if match is not None:
            name = match.group(1)
            current = name if name in SECTION_NAMES else None
            if current is not None:
                sections.setdefault(current, [])
            continue

        if current is not None:
            sections[current].append(line)

    return sections


def _parse_arg_items(lines: list[str]) -> tuple[dict[str, DocItem], list[DocItem]]:
    return _parse_items(lines, collect_malformed=True)


def _parse_named_items(lines: list[str]) -> dict[str, DocItem]:
    items, _ = _parse_items(lines, collect_malformed=False)
    return items


def _parse_items(
    lines: list[str],
    collect_malformed: bool,
) -> tuple[dict[str, DocItem], list[DocItem]]:
    items: dict[str, DocItem] = {}
    malformed: list[DocItem] = []
    current_name: str | None = None
    current_malformed_index: int | None = None
    descriptions: dict[str, list[str]] = {}
    malformed_descriptions: dict[int, list[str]] = {}

    for line in lines:
        if not line.strip():
            continue

        match = _NAMED_ITEM_RE.match(line) if _is_probable_item_line(line) else None
        if match:
            name = match.group("name")
            item_type = match.group("type") or match.group("type_after_colon")
            item = DocItem(
                name=name,
                type=_clean_optional(item_type),
                description=match.group("desc").strip(),
            )
            items[name] = item
            current_name = name
            current_malformed_index = None
            descriptions[name] = [item.description] if item.description else []
            continue

        malformed_item = (
            _parse_malformed_arg_item(line) if collect_malformed else None
        )
        if malformed_item is not None:
            malformed.append(malformed_item)
            current_name = None
            current_malformed_index = len(malformed) - 1
            if malformed_item.description:
                malformed_descriptions[current_malformed_index] = [
                    malformed_item.description
                ]
            else:
                malformed_descriptions[current_malformed_index] = []
            continue

        if current_name is not None:
            descriptions[current_name].append(line.strip())
        elif current_malformed_index is not None:
            malformed_descriptions[current_malformed_index].append(line.strip())

    for name, desc_lines in descriptions.items():
        item = items[name]
        items[name] = DocItem(
            name=item.name,
            type=item.type,
            description=" ".join(part for part in desc_lines if part),
        )

    for index, desc_lines in malformed_descriptions.items():
        item = malformed[index]
        malformed[index] = DocItem(
            name=item.name,
            type=item.type,
            description=" ".join(part for part in desc_lines if part),
        )

    return items, malformed


def _parse_malformed_arg_item(line: str) -> DocItem | None:
    if not _is_probable_item_line(line):
        return None

    match = _RETURN_ITEM_RE.match(line)
    if match is None:
        return None

    type_text = _clean_optional(match.group("type"))
    if type_text is None or not is_type_like(type_text):
        return None

    return DocItem(
        name=type_text,
        type=type_text,
        description=match.group("desc").strip(),
    )


def _parse_return_item(lines: list[str], fallback_name: str) -> DocItem | None:
    content = [line for line in lines if line.strip()]
    if not content:
        return None

    first = content[0]
    match = _RETURN_ITEM_RE.match(first)
    if match:
        return DocItem(
            name=fallback_name,
            type=_clean_optional(match.group("type")),
            description=" ".join(
                [match.group("desc").strip()]
                + [line.strip() for line in content[1:]]
            ).strip(),
        )

    return DocItem(
        name=fallback_name,
        type=None,
        description=" ".join(line.strip() for line in content),
    )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    return cleaned or None


def _is_unindented(line: str) -> bool:
    return bool(line) and not line[0].isspace()


def _is_probable_item_line(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped or stripped == line:
        return False
    return len(line) - len(stripped) <= 4
