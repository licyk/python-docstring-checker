"""Type annotation normalization for docstring/type-hint comparisons."""

from __future__ import annotations

import ast
import re


_ALIASES = {
    "AbstractSet": "set",
    "Deque": "deque",
    "Dict": "dict",
    "FrozenSet": "frozenset",
    "List": "list",
    "Sequence": "Sequence",
    "Set": "set",
    "Tuple": "tuple",
    "Type": "type",
}

_UNION_NAMES = {"Union", "typing.Union"}
_OPTIONAL_NAMES = {"Optional", "typing.Optional"}
_NONE_NAMES = {"None", "NoneType", "type(None)"}
_NO_RETURN_NAMES = {"NoReturn", "typing.NoReturn", "Never", "typing.Never"}
_TYPE_LIKE_NAMES = {
    "Any",
    "Callable",
    "Iterable",
    "Mapping",
    "MutableMapping",
    "None",
    "NoneType",
    "Optional",
    "Sequence",
    "Union",
    "bool",
    "bytes",
    "complex",
    "dict",
    "float",
    "frozenset",
    "int",
    "list",
    "object",
    "set",
    "str",
    "tuple",
    "type",
}


def normalize_type(type_text: str | None) -> str | None:
    """Normalize common Python type spellings into a stable comparable form."""
    if type_text is None:
        return None

    cleaned = _clean_type_text(type_text)
    if not cleaned:
        return None

    try:
        node = ast.parse(cleaned, mode="eval").body
    except SyntaxError:
        return _fallback_normalize(cleaned)

    return _normalize_node(node)


def types_equal(left: str | None, right: str | None) -> bool:
    """Return whether two type strings represent the same supported type."""
    return normalize_type(left) == normalize_type(right)


def comparison_confidence(left: str | None, right: str | None) -> str:
    """Return confidence for a type comparison."""
    if _is_parseable_type(left) and _is_parseable_type(right):
        return "high"
    return "low"


def is_none_type(type_text: str | None) -> bool:
    """Return whether a type string is effectively no return value."""
    normalized = normalize_type(type_text)
    return normalized in {"None", "NoReturn", "Never"}


def is_type_like(type_text: str | None) -> bool:
    """Return whether text looks like a type expression rather than prose."""
    if type_text is None:
        return False

    cleaned = _clean_type_text(type_text)
    if not cleaned:
        return False

    try:
        node = ast.parse(cleaned, mode="eval").body
    except SyntaxError:
        return False

    return _is_type_like_node(node, cleaned)


def _is_parseable_type(type_text: str | None) -> bool:
    if type_text is None:
        return True

    cleaned = _clean_type_text(type_text)
    if not cleaned:
        return True

    try:
        ast.parse(cleaned, mode="eval")
    except SyntaxError:
        return False
    return True


def _clean_type_text(type_text: str) -> str:
    cleaned = type_text.strip().strip("`")
    cleaned = cleaned.replace("typing.", "")
    cleaned = cleaned.replace("NoneType", "None")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _fallback_normalize(type_text: str) -> str:
    cleaned = _clean_type_text(type_text)
    cleaned = re.sub(r"\s*([,\[\]\|])\s*", r"\1", cleaned)
    return cleaned


def _normalize_node(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return _normalize_name(node.id)

    if isinstance(node, ast.Attribute):
        return _normalize_name(ast.unparse(node).replace("typing.", ""))

    if isinstance(node, ast.Constant):
        if node.value is None:
            return "None"
        if isinstance(node.value, str):
            return normalize_type(node.value) or repr(node.value)
        return repr(node.value)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _normalize_union(_flatten_union(node))

    if isinstance(node, ast.Subscript):
        base = _normalize_node(node.value)
        args = _normalize_subscript_args(node.slice)

        if base in _OPTIONAL_NAMES or base == "Optional":
            return _normalize_union(args + ["None"])

        if base in _UNION_NAMES or base == "Union":
            return _normalize_union(args)

        return f"{_normalize_name(base)}[{', '.join(args)}]"

    if isinstance(node, ast.Tuple):
        return ", ".join(_normalize_node(element) for element in node.elts)

    if isinstance(node, ast.List):
        return "[" + ", ".join(_normalize_node(element) for element in node.elts) + "]"

    return _fallback_normalize(ast.unparse(node))


def _normalize_name(name: str) -> str:
    name = name.replace("typing.", "")
    if name in _NONE_NAMES:
        return "None"
    if name in _NO_RETURN_NAMES:
        return name.split(".")[-1]
    return _ALIASES.get(name, name)


def _normalize_subscript_args(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Tuple):
        return [_normalize_node(element) for element in node.elts]
    return [_normalize_node(node)]


def _flatten_union(node: ast.AST) -> list[str]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flatten_union(node.left) + _flatten_union(node.right)
    return [_normalize_node(node)]


def _normalize_union(parts: list[str]) -> str:
    flattened: list[str] = []
    for part in parts:
        if " | " in part:
            flattened.extend(part.split(" | "))
        else:
            flattened.append(part)

    unique = sorted(set(flattened), key=lambda value: (value == "None", value))
    return " | ".join(unique)


def _is_type_like_node(node: ast.AST, original: str) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return True

    if isinstance(node, ast.Subscript):
        return True

    if isinstance(node, ast.Attribute):
        full_name = ast.unparse(node).replace("typing.", "")
        attr_name = full_name.rsplit(".", 1)[-1]
        return (
            original.startswith("typing.")
            or attr_name in _TYPE_LIKE_NAMES
            or attr_name in _ALIASES
            or attr_name[:1].isupper()
        )

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return is_type_like(node.value)

    if isinstance(node, ast.Tuple):
        return all(_is_type_like_node(element, original) for element in node.elts)

    if isinstance(node, ast.Name):
        name = node.id.replace("typing.", "")
        return (
            name in _TYPE_LIKE_NAMES
            or name in _ALIASES
            or name[:1].isupper()
            or original.startswith("typing.")
        )

    return False
