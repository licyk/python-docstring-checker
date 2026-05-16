"""Command-line interface for the Google docstring checker."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Sequence

from docstring_checker.checker import DEFAULT_EXCLUDES, CheckOptions, check_paths
from docstring_checker.output import OUTPUT_FORMATS, OutputOptions, format_report


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    config_path = _resolve_config_path(args.config)
    if args.config is not None and config_path is not None and not config_path.exists():
        parser.error(f"config file not found: {config_path}")

    config = _load_tool_config(config_path)
    strictness = args.strictness or _config_get(config, "strictness", default="balanced")
    output_format = args.format or _config_get(config, "format", default="text")
    if output_format not in OUTPUT_FORMATS:
        parser.error(
            "format must be one of: " + ", ".join(sorted(OUTPUT_FORMATS))
        )
    ignore_empty_init_modules = _option_bool(
        args.ignore_empty_init_modules,
        config,
        "ignore-empty-init-modules",
        "ignore_empty_init_modules",
    )

    options = CheckOptions(
        exclude=tuple(DEFAULT_EXCLUDES)
        + tuple(_config_list(config, "exclude"))
        + tuple(args.exclude or ()),
        ignore_codes=frozenset(
            _config_list(config, "ignore-codes", "ignore_codes")
            + sorted(_split_codes(args.ignore_code or []))
        ),
        strictness=str(strictness),
        ignore_names=tuple(_config_list(config, "ignore-names", "ignore_names"))
        + tuple(args.ignore_name or ()),
        ignore_paths=tuple(_config_list(config, "ignore-paths", "ignore_paths"))
        + tuple(args.ignore_path or ()),
        ignore_decorators=tuple(
            _config_list(config, "ignore-decorators", "ignore_decorators")
        )
        + tuple(args.ignore_decorator or ()),
        attribute_policy=args.attribute_policy
        or _config_get(config, "attribute-policy", "attribute_policy", default=None),
        ignore_method_names=tuple(
            _config_list(config, "ignore-method-names", "ignore_method_names")
        )
        + tuple(args.ignore_method_name or ()),
        require_docstring_types=_option_bool(
            args.require_docstring_types,
            config,
            "require-docstring-types",
            "require_docstring_types",
        ),
        ignore_empty_init_modules=True
        if ignore_empty_init_modules is None
        else ignore_empty_init_modules,
        check_tests=_option_bool(args.check_tests, config, "check-tests", "check_tests"),
        check_private=_option_bool(args.check_private, config, "check-private", "check_private"),
        check_nested=_option_bool(args.check_nested, config, "check-nested", "check_nested"),
    )
    show_source = _option_bool(args.show_source, config, "show-source", "show_source")
    source_context = args.source_context
    if source_context is None:
        source_context = _config_int(config, "source-context", "source_context", default=1)
    if source_context < 0:
        parser.error("source context must be greater than or equal to 0")

    output_options = OutputOptions(
        format=str(output_format),
        show_source=False if show_source is None else show_source,
        source_context=source_context,
    )
    issues = check_paths(args.paths, options)

    report = format_report(issues, output_options)
    if report:
        sys.stdout.write(report + "\n")

    return 1 if issues else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m docstring_checker",
        description="Check Python Google-style docstrings against AST signatures.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path(".")],
        help="Python files or directories to scan. Defaults to the current directory.",
    )
    parser.add_argument(
        "--format",
        choices=tuple(sorted(OUTPUT_FORMATS)),
        default=None,
        help="Output format. Defaults to config value or text.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Config file to read. Defaults to pyproject.toml when present.",
    )
    parser.add_argument(
        "--strictness",
        choices=("strict", "balanced", "public"),
        default=None,
        help="Checking policy. Defaults to config value or balanced.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        help="fnmatch-style path pattern to exclude. May be passed multiple times.",
    )
    parser.add_argument(
        "--ignore-code",
        action="append",
        default=None,
        help="Diagnostic code to ignore. Comma-separated values are accepted.",
    )
    parser.add_argument(
        "--ignore-name",
        action="append",
        default=None,
        help="Attribute name or fnmatch-style pattern to ignore.",
    )
    parser.add_argument(
        "--ignore-path",
        action="append",
        default=None,
        help="fnmatch-style path pattern to ignore.",
    )
    parser.add_argument(
        "--ignore-decorator",
        action="append",
        default=None,
        help="Decorator name or fnmatch-style pattern whose objects should be skipped.",
    )
    parser.add_argument(
        "--attribute-policy",
        choices=("strict", "documented", "off"),
        default=None,
        help="Attribute checking policy. Defaults to strict in strict mode, otherwise documented.",
    )
    parser.add_argument(
        "--ignore-method-name",
        action="append",
        default=None,
        help="Method name or fnmatch-style pattern to ignore.",
    )
    parser.add_argument(
        "--require-docstring-types",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Whether Args/Returns entries must include explicit docstring types.",
    )
    parser.add_argument(
        "--ignore-empty-init-modules",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Whether empty __init__.py files are allowed without module docstrings.",
    )
    parser.add_argument(
        "--check-tests",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Whether to check test files.",
    )
    parser.add_argument(
        "--check-private",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Whether to check private and dunder objects.",
    )
    parser.add_argument(
        "--check-nested",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Whether to check nested functions and classes.",
    )
    parser.add_argument(
        "--show-source",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Whether to show source context in text and compact reports.",
    )
    parser.add_argument(
        "--source-context",
        type=int,
        default=None,
        help="Number of context lines around each source issue. Defaults to 1.",
    )
    return parser


def _resolve_config_path(path: Path | None) -> Path | None:
    if path is not None:
        return path

    default = Path("pyproject.toml")
    return default if default.exists() else None


def _load_tool_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}

    data = _load_toml(path)
    tool = data.get("tool", {})
    if not isinstance(tool, dict):
        return {}

    config = tool.get("docstring-checker", {})
    return config if isinstance(config, dict) else {}


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:
        return _load_minimal_docstring_checker_toml(path)

    with path.open("rb") as file:
        return tomllib.load(file)


def _load_minimal_docstring_checker_toml(path: Path) -> dict[str, Any]:
    section = False
    config: dict[str, Any] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line == "[tool.docstring-checker]"
            continue
        if not section or "=" not in line:
            continue

        key, value = line.split("=", 1)
        config[key.strip()] = _parse_minimal_toml_value(value.strip())

    return {"tool": {"docstring-checker": config}}


def _parse_minimal_toml_value(value: str) -> Any:
    if value in {"true", "false"}:
        return value == "true"

    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]

    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [
            item.strip().strip('"').strip("'")
            for item in inner.split(",")
            if item.strip()
        ]

    return value


def _config_get(config: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in config:
            return config[key]
    return default


def _config_list(config: dict[str, Any], *keys: str) -> list[str]:
    value = _config_get(config, *keys, default=[])
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _config_int(config: dict[str, Any], *keys: str, default: int) -> int:
    value = _config_get(config, *keys, default=default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _option_bool(cli_value: bool | None, config: dict[str, Any], *keys: str) -> bool | None:
    if cli_value is not None:
        return cli_value

    value = _config_get(config, *keys, default=None)
    return value if isinstance(value, bool) else None


def _split_codes(values: list[str]) -> set[str]:
    codes: set[str] = set()
    for value in values:
        for part in value.split(","):
            cleaned = part.strip()
            if cleaned:
                codes.add(cleaned)
    return codes

