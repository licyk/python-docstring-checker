"""Output formatting helpers for docstring checker reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
import json
from pathlib import Path

from python_docstring_checker.models import Issue


OUTPUT_FORMATS = {"text", "compact", "json", "json-lines"}


@dataclass(frozen=True)
class OutputOptions:
    """Options controlling report formatting."""

    format: str = "text"
    show_source: bool = False
    source_context: int = 1


def build_summary(issues: list[Issue]) -> dict[str, object]:
    """Build stable summary counters for a list of issues."""
    return {
        "total": len(issues),
        "files": len({issue.file for issue in issues}),
        "codes": _counter_dict(issue.code for issue in issues),
        "confidence": _counter_dict(issue.confidence for issue in issues),
        "low_confidence": sum(1 for issue in issues if issue.confidence != "high"),
    }


def format_text_report(issues: list[Issue], options: OutputOptions | None = None) -> str:
    """Format a human-friendly grouped report."""
    output_options = options or OutputOptions()
    if not issues:
        return "Docstring check passed: no issues found."

    summary = build_summary(issues)
    lines = [
        "Docstring Check Report",
        f"Total issues: {summary['total']}",
        f"Files affected: {summary['files']}",
        f"By code: {_format_counts(summary['codes'])}",
        f"By confidence: {_format_counts(summary['confidence'])}",
    ]
    if summary["low_confidence"]:
        lines.append(f"Low-confidence issues: {summary['low_confidence']}")

    grouped = _group_by_file(issues)
    source_cache: dict[str, list[str] | None] = {}
    for file_name, file_issues in grouped.items():
        lines.extend(["", file_name])
        for issue in file_issues:
            lines.append(
                f"  L{issue.line}: {issue.code} [{issue.confidence}] {issue.object}"
            )
            lines.append(f"    {issue.message}")
            if output_options.show_source:
                lines.extend(_format_source_context(issue, output_options, source_cache))

    return "\n".join(lines)


def format_compact_report(issues: list[Issue], options: OutputOptions | None = None) -> str:
    """Format the legacy one-line-per-issue report."""
    output_options = options or OutputOptions(format="compact")
    if not issues:
        return "No docstring issues found."

    source_cache: dict[str, list[str] | None] = {}
    lines: list[str] = []
    for issue in issues:
        confidence = "" if issue.confidence == "high" else f" [{issue.confidence}]"
        lines.append(
            f"{issue.file}:{issue.line}: {issue.code}{confidence} "
            f"{issue.object}: {issue.message}"
        )
        if output_options.show_source:
            lines.extend(_format_source_context(issue, output_options, source_cache))
    return "\n".join(lines)


def format_json_report(issues: list[Issue]) -> str:
    """Format the enhanced JSON report."""
    payload = {
        "summary": build_summary(issues),
        "issues": [issue.to_dict() for issue in issues],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def format_json_lines(issues: list[Issue]) -> str:
    """Format one JSON issue object per line."""
    return "\n".join(
        json.dumps(issue.to_dict(), ensure_ascii=False) for issue in issues
    )


def format_report(issues: list[Issue], options: OutputOptions) -> str:
    """Format issues using the selected output format."""
    if options.format == "text":
        return format_text_report(issues, options)
    if options.format == "compact":
        return format_compact_report(issues, options)
    if options.format == "json":
        return format_json_report(issues)
    if options.format == "json-lines":
        return format_json_lines(issues)
    raise ValueError(f"Unsupported output format: {options.format}")


def _counter_dict(values: Iterable[str]) -> dict[str, int]:
    counter = Counter(values)
    return {key: counter[key] for key in sorted(counter)}


def _format_counts(value: object) -> str:
    counts = value if isinstance(value, dict) else {}
    if not counts:
        return "none"
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))


def _group_by_file(issues: list[Issue]) -> dict[str, list[Issue]]:
    grouped: dict[str, list[Issue]] = defaultdict(list)
    for issue in issues:
        grouped[issue.file].append(issue)
    return dict(sorted(grouped.items()))


def _format_source_context(
    issue: Issue,
    options: OutputOptions,
    source_cache: dict[str, list[str] | None],
) -> list[str]:
    lines = _read_source(issue.file, source_cache)
    if lines is None:
        return []

    index = issue.line - 1
    if index < 0 or index >= len(lines):
        return []

    context = max(0, options.source_context)
    start = max(0, index - context)
    end = min(len(lines), index + context + 1)
    width = len(str(end))

    formatted: list[str] = []
    for current in range(start, end):
        marker = ">" if current == index else " "
        formatted.append(
            f"    {marker} {current + 1:>{width}} | {lines[current].rstrip()}"
        )
    return formatted


def _read_source(
    file_name: str,
    source_cache: dict[str, list[str] | None],
) -> list[str] | None:
    if file_name not in source_cache:
        try:
            source_cache[file_name] = (
                Path(file_name).read_text(encoding="utf-8").splitlines()
            )
        except OSError:
            source_cache[file_name] = None
    return source_cache[file_name]
