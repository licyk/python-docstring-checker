"""Tests for the Google-style docstring checker."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from python_docstring_checker.checker import CheckOptions, check_paths
from python_docstring_checker.cli import main
from python_docstring_checker.google import parse_google_docstring
from python_docstring_checker.types import is_type_like, normalize_type, types_equal


def write_source(tmp_path: Path, source: str, name: str = "sample.py") -> Path:
    """Write a temporary Python source file."""
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def issue_codes(path: Path, options: CheckOptions | None = None) -> list[str]:
    """Return issue codes for one file."""
    return [issue.code for issue in check_paths([path], options)]


def test_accepts_valid_google_style_docstrings(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs.

Attributes:
    VALUE (int): A module value.
"""

VALUE: int = 1


class Service:
    """Service docs.

    Attributes:
        path (str | None): Path value.
    """

    kind: str = "basic"
    """Kind docs."""

    def __init__(self, path: str | None) -> None:
        """Initialize service.

        Args:
            path (Optional[str]): Path value.
        """
        self.path: str | None = path

    def build(self, count: int, *items: str, flag: bool = False, **extra: str) -> list[str]:
        """Build values.

        Args:
            count (int): Item count.
            *items (str): Extra items.
            flag (bool): Feature flag.
            **extra (str): Extra values.

        Returns:
            List[str]: Built values.
        """
        return list(items)
''',
    )

    assert check_paths([path]) == []


def test_reports_parameter_mismatch_and_missing_types(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def func(name: str, count: int) -> None:
    """Do work.

    Args:
        name (int): Name value.
        extra (str): Extra value.
    """
    return None
''',
    )

    codes = issue_codes(path)
    assert Counter(codes) == Counter(["ARG003", "ARG001", "ARG002"])


def test_reports_signature_parameter_missing_annotation_from_doc_type(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def add(a, b: str) -> None:
    """Add values.

    Args:
        a (int): First value.
        b (str): Second value.
    """
    return None
''',
    )

    issues = check_paths([path])

    assert [issue.code for issue in issues] == ["ARG006"]
    assert issues[0].confidence == "high"
    assert "missing a signature type annotation" in issues[0].message


def test_signature_parameter_annotation_satisfies_doc_type(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def add(a: int, b: str) -> None:
    """Add values.

    Args:
        a (int): First value.
        b (str): Second value.
    """
    return None
''',
    )

    assert check_paths([path]) == []


def test_signature_parameter_type_mismatch_does_not_report_missing_annotation(
    tmp_path: Path,
) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def add(a: str) -> None:
    """Add value.

    Args:
        a (int): First value.
    """
    return None
''',
    )

    assert issue_codes(path) == ["ARG003"]


def test_untyped_signature_and_untyped_doc_arg_do_not_report_arg006(
    tmp_path: Path,
) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def add(a) -> None:
    """Add value.

    Args:
        a: First value.
    """
    return None
''',
    )

    assert check_paths([path]) == []


def test_reports_missing_signature_annotations_for_varargs(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def collect(*items, **extra) -> None:
    """Collect values.

    Args:
        *items (str): Items.
        **extra (int): Extra values.
    """
    return None
''',
    )

    issues = check_paths([path])

    assert [issue.code for issue in issues] == ["ARG006", "ARG006"]
    messages = {issue.message for issue in issues}
    assert any("Parameter '*items'" in message for message in messages)
    assert any("Parameter '**extra'" in message for message in messages)


def test_missing_signature_annotation_low_confidence_for_unparseable_doc_type(
    tmp_path: Path,
) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def parse(value) -> None:
    """Parse value.

    Args:
        value (list[str): Value.
    """
    return None
''',
    )

    issues = check_paths([path])

    assert [issue.code for issue in issues] == ["ARG006"]
    assert issues[0].confidence == "low"


def test_reports_missing_returns_and_return_type_mismatch(tmp_path: Path) -> None:
    missing_path = write_source(
        tmp_path,
        '''
"""Module docs."""


def build() -> Path:
    """Build path."""
    return Path("x")
''',
        "missing_return.py",
    )
    mismatch_path = write_source(
        tmp_path,
        '''
"""Module docs."""


def build() -> str:
    """Build text.

    Returns:
        int: Built value.
    """
    return "x"
''',
        "mismatch_return.py",
    )

    assert issue_codes(missing_path) == ["RET001"]
    assert issue_codes(mismatch_path) == ["RET003"]


def test_reports_unexpected_return_section(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def noop() -> None:
    """Do nothing.

    Returns:
        str: Nothing.
    """
    return None
''',
    )

    assert issue_codes(path) == ["RET002"]


def test_reports_missing_raises_for_direct_raise(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def fail() -> None:
    """Fail."""
    raise RuntimeError("boom")
''',
    )

    issues = check_paths([path])

    assert [issue.code for issue in issues] == ["RAI001"]
    assert "RuntimeError" in issues[0].message


def test_accepts_documented_direct_raise_and_broad_exception(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def fail_specific() -> None:
    """Fail.

    Raises:
        RuntimeError: Failure.
    """
    raise RuntimeError("boom")


def fail_broad() -> None:
    """Fail broadly.

    Raises:
        Exception: Failure.
    """
    raise ValueError("boom")
''',
    )

    assert check_paths([path]) == []


def test_reraise_requires_caught_exception(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def parse() -> None:
    """Parse.

    Raises:
        ValueError: Invalid value.
    """
    try:
        int("x")
    except ValueError:
        raise
''',
    )

    assert check_paths([path]) == []


def test_wrapped_exception_requires_new_exception(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def parse() -> None:
    """Parse.

    Raises:
        RuntimeError: Parsing failed.
    """
    try:
        int("x")
    except ValueError as exc:
        raise RuntimeError("failed") from exc
''',
    )

    assert check_paths([path]) == []


def test_tuple_reraise_reports_all_caught_exceptions(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def parse() -> None:
    """Parse."""
    try:
        int("x")
    except (ValueError, TypeError):
        raise
''',
    )

    issues = check_paths([path])

    assert [issue.code for issue in issues] == ["RAI001", "RAI001"]
    messages = {issue.message for issue in issues}
    assert any("ValueError" in message for message in messages)
    assert any("TypeError" in message for message in messages)


def test_strict_reports_documented_raise_not_directly_raised(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def parse() -> None:
    """Parse.

    Raises:
        RuntimeError: Parsing failed.
    """
    return None
''',
    )

    assert check_paths([path]) == []
    assert issue_codes(path, CheckOptions(strictness="strict")) == ["RAI002"]


def test_unknown_raise_reports_low_confidence_when_undocumented(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def parse() -> None:
    """Parse."""
    raise make_error()
''',
    )

    issues = check_paths([path])

    assert [issue.code for issue in issues] == ["RAI003"]
    assert issues[0].confidence == "low"


def test_unknown_raise_with_existing_raises_is_strict_only(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def parse() -> None:
    """Parse.

    Raises:
        RuntimeError: Parsing failed.
    """
    raise make_error()
''',
    )

    assert check_paths([path]) == []
    assert Counter(issue_codes(path, CheckOptions(strictness="strict"))) == Counter(
        ["RAI002", "RAI003"]
    )


def test_generator_must_use_yields(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def numbers():
    """Yield numbers.

    Returns:
        int: A number.
    """
    yield 1
''',
    )

    assert issue_codes(path) == ["RET001", "RET005"]


def test_return_section_accepts_indented_type_items(tmp_path: Path) -> None:
    names = ["Any", "Path", "LogCapture", "ExceptionReporter", "dict[str, Any]"]

    for index, type_name in enumerate(names):
        path = write_source(
            tmp_path,
            f'''
"""Module docs."""


def func_{index}() -> {type_name}:
    """Return a value.

    Returns:
        {type_name}:
            Returned value.
    """
    return value
''',
            f"returns_{index}.py",
        )

        assert check_paths([path]) == []


def test_arg_parser_accepts_colon_before_type(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def func(value: str | None) -> None:
    """Use value.

    Args:
        value: (str | None):
            Optional value.
    """
    return None
''',
    )

    assert check_paths([path]) == []


def test_arg_parser_keeps_malformed_type_like_args() -> None:
    parsed = parse_google_docstring(
        """Get GPUs.

Args:
    list[GPUDeviceInfo]:
        GPU info list.
"""
    )

    assert parsed.args == {}
    assert len(parsed.malformed_args) == 1
    assert parsed.malformed_args[0].name == "list[GPUDeviceInfo]"
    assert parsed.malformed_args[0].description == "GPU info list."


def test_arg_parser_does_not_treat_description_as_malformed_arg() -> None:
    parsed = parse_google_docstring(
        """Use a value.

Args:
    value (str):
        Main value.
        Path:
            This is part of the description.
"""
    )

    assert list(parsed.args) == ["value"]
    assert parsed.malformed_args == ()


def test_reports_type_like_args_entry_as_possible_return_doc(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def get_windows_gpu_list() -> list[GPUDeviceInfo]:
    """Get GPUs.

    Args:
        list[GPUDeviceInfo]:
            GPU info list.
    """
    return []
''',
    )

    issues = check_paths([path])

    assert [issue.code for issue in issues] == ["ARG005", "RET001"]
    assert issues[0].confidence == "high"
    assert "matches the return annotation" in issues[0].message


def test_reports_type_like_args_entry_with_missing_real_parameter(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def build(name: str) -> list[str]:
    """Build values.

    Args:
        list[str]:
            Built values.
    """
    return [name]
''',
    )

    issues = check_paths([path])

    assert Counter(issue.code for issue in issues) == Counter(
        ["ARG001", "ARG005", "RET001"]
    )


def test_reports_type_like_args_entry_with_low_confidence(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def build() -> list[str]:
    """Build values.

    Args:
        dict[str, str]:
            Built values.
    """
    return []
''',
    )

    issues = check_paths([path])

    assert [issue.code for issue in issues] == ["ARG005", "RET001"]
    assert issues[0].confidence == "low"
    assert "looks like a type" in issues[0].message


def test_correct_returns_section_does_not_report_type_like_args(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def build() -> list[str]:
    """Build values.

    Returns:
        list[str]:
            Built values.
    """
    return []
''',
    )

    assert check_paths([path]) == []


def test_generator_type_like_args_entry_points_to_yields(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def numbers():
    """Yield values.

    Args:
        int:
            A number.
    """
    yield 1
''',
    )

    issues = check_paths([path])

    assert [issue.code for issue in issues] == ["ARG005", "RET001"]
    assert issues[0].confidence == "low"
    assert "Yields" in issues[0].message


def test_nested_yield_does_not_make_outer_function_a_generator(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def outer() -> str:
    """Return text.

    Returns:
        str: Text value.
    """
    def inner():
        """Yield numbers.

        Yields:
            int: Number.
        """
        yield 1

    return "x"
''',
    )

    assert check_paths([path]) == []


def test_reports_missing_docstrings_and_attributes(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
VALUE = 1


class Box:
    data: int = 1

    def __init__(self):
        self.name = "x"

    def _private(self):
        pass
''',
    )

    codes = issue_codes(path, CheckOptions(strictness="strict"))
    assert Counter(codes) == Counter(
        [
            "DOC001",
            "ATR001",
            "DOC002",
            "ATR001",
            "ATR001",
            "DOC003",
            "DOC003",
        ]
    )


def test_balanced_default_skips_common_noise(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""

logger = object()
__all__ = ["public"]
DEFAULT_VALUE = 1
_cache = {}


def _helper():
    pass


def public() -> None:
    """Public function."""

    def nested():
        pass

    return None


class Widget:
    """Widget docs."""

    def __init__(self) -> None:
        self.frame = object()

    def __str__(self) -> str:
        return "widget"
''',
    )

    assert check_paths([path]) == []


def test_balanced_attribute_policy_only_checks_documented_attributes(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


class Config:
    """Config docs."""

    value: int = 1
''',
    )

    assert check_paths([path]) == []
    assert issue_codes(path, CheckOptions(strictness="strict")) == ["ATR001"]


def test_documented_attribute_policy_keeps_type_mismatch_checks(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


class Config:
    """Config docs.

    Attributes:
        value (str): Value.
    """

    value: int = 1
''',
    )

    assert issue_codes(path) == ["ATR002"]


def test_balanced_validates_documented_init_without_requiring_one(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


class Config:
    """Config docs."""

    def __init__(self, value: str) -> None:
        """Initialize config.

        Args:
            value (int): Value.
        """
        self.value = value
''',
    )

    assert issue_codes(path) == ["ARG003"]


def test_skips_test_files_by_default_but_strict_can_check_them(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
def test_missing_docstring():
    pass
''',
        "test_sample.py",
    )

    assert check_paths([path]) == []
    assert issue_codes(path, CheckOptions(strictness="strict")) == ["DOC001", "DOC003"]


def test_public_mode_only_checks_public_objects(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


class _Private:
    pass


def _helper():
    pass


def public() -> str:
    """Public function."""
    return "x"
''',
    )

    assert issue_codes(path, CheckOptions(strictness="public")) == ["RET001"]


def test_public_mode_uses_static_all_exports(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""

__all__ = ["exported"]


def exported() -> str:
    """Exported function."""
    return "x"


def internal() -> str:
    """Internal function."""
    return "x"
''',
    )

    balanced_codes = issue_codes(path, CheckOptions(strictness="balanced"))
    public_codes = issue_codes(path, CheckOptions(strictness="public"))

    assert balanced_codes == ["RET001", "RET001"]
    assert public_codes == ["RET001"]


def test_ignore_decorator_skips_object(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


@overload
def func(value: str) -> str:
    pass
''',
    )

    issues = check_paths([path], CheckOptions(ignore_decorators=("overload",)))
    assert issues == []


def test_property_setter_does_not_require_duplicate_docstring(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


class Progress:
    """Progress docs."""

    def __init__(self) -> None:
        """Initialize progress."""
        self._name = ""
        """Stored name."""

    @property
    def name(self) -> str:
        """Current name.

        Returns:
            str: Current name.
        """
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value
''',
    )

    assert check_paths([path], CheckOptions(strictness="strict")) == []


def test_balanced_ignores_common_framework_override_methods(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


class Formatter:
    """Formatter docs."""

    def format(self, record: object) -> str:
        return str(record)
''',
    )

    assert check_paths([path]) == []
    assert issue_codes(path, CheckOptions(strictness="strict")) == ["DOC003"]


def test_empty_init_module_docstring_is_optional_by_default(tmp_path: Path) -> None:
    path = write_source(tmp_path, "", "__init__.py")

    assert check_paths([path]) == []
    issues = check_paths([path], CheckOptions(ignore_empty_init_modules=False))
    assert [issue.code for issue in issues] == ["DOC001"]


def test_balanced_does_not_require_docstring_types_but_still_checks_mismatches(tmp_path: Path) -> None:
    missing_type_path = write_source(
        tmp_path,
        '''
"""Module docs."""


def parse(url: str) -> None:
    """Parse a URL.

    Args:
        url:
            URL.
    """
    return None
''',
        "missing_type.py",
    )
    mismatch_path = write_source(
        tmp_path,
        '''
"""Module docs."""


def parse(url: str) -> None:
    """Parse a URL.

    Args:
        url (int):
            URL.
    """
    return None
''',
        "mismatch.py",
    )

    assert check_paths([missing_type_path]) == []
    assert issue_codes(missing_type_path, CheckOptions(strictness="strict")) == ["ARG004"]
    assert issue_codes(mismatch_path) == ["ARG003"]


def test_adjacent_attribute_docstring_satisfies_module_attribute(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""

VALUE = 1
"""Value docs."""
''',
    )

    assert check_paths([path]) == []


def test_type_normalization_common_equivalences() -> None:
    assert types_equal("Optional[str]", "str | None")
    assert types_equal("List[Path]", "list[Path]")
    assert types_equal("Union[int, str, None]", "str | int | None")
    assert normalize_type("typing.Dict[str, typing.Any]") == "dict[str, Any]"


def test_type_like_detection_avoids_plain_dotted_names() -> None:
    assert is_type_like("typing.List[str]")
    assert is_type_like("models.GPUDeviceInfo")
    assert not is_type_like("config.value")


def test_cli_json_and_exit_code(tmp_path: Path, capsys) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def func() -> str:
    """Return text."""
    return "x"
''',
    )

    exit_code = main(["--format", "json", str(path)])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 1
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["files"] == 1
    assert payload["summary"]["codes"] == {"RET001": 1}
    assert payload["summary"]["confidence"] == {"high": 1}
    assert payload["issues"][0]["code"] == "RET001"
    assert payload["issues"][0]["confidence"] == "high"


def test_cli_text_output_groups_by_file_and_summarizes(tmp_path: Path, capsys) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def func() -> str:
    """Return text."""
    return "x"
''',
    )

    exit_code = main([str(path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Docstring Check Report" in output
    assert "Total issues: 1" in output
    assert "Files affected: 1" in output
    assert "By code: RET001=1" in output
    assert str(path) in output
    assert "L5: RET001 [high] func" in output


def test_cli_text_output_success_message(tmp_path: Path, capsys) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def func() -> None:
    """Do nothing."""
    return None
''',
    )

    exit_code = main([str(path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.strip() == "Docstring check passed: no issues found."


def test_cli_compact_output_keeps_legacy_shape(tmp_path: Path, capsys) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def func() -> str:
    """Return text."""
    return "x"
''',
    )

    exit_code = main(["--format", "compact", str(path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert output.startswith(f"{path}:5: RET001 func:")
    assert "Docstring Check Report" not in output


def test_cli_json_lines_output(tmp_path: Path, capsys) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def func() -> str:
    """Return text."""
    return "x"
''',
    )

    exit_code = main(["--format", "json-lines", str(path)])
    output = capsys.readouterr().out.strip()
    payload = json.loads(output)

    assert exit_code == 1
    assert payload["code"] == "RET001"
    assert payload["file"] == str(path)


def test_cli_show_source_with_context(tmp_path: Path, capsys) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def func() -> str:
    """Return text."""
    return "x"
''',
    )

    exit_code = main(["--show-source", "--source-context", "0", str(path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "> 5 | def func() -> str:" in output
    assert "  4 |" not in output


def test_ignore_code(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        '''
"""Module docs."""


def func() -> str:
    """Return text."""
    return "x"
''',
    )

    issues = check_paths([path], CheckOptions(ignore_codes=frozenset({"RET001"})))
    assert issues == []


def test_cli_reads_pyproject_config(tmp_path: Path, capsys) -> None:
    source_path = write_source(
        tmp_path,
        '''
def _private():
    pass
''',
    )
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(
        '''
[tool.python-docstring-checker]
strictness = "strict"
ignore-codes = ["DOC001"]
''',
        encoding="utf-8",
    )

    exit_code = main(["--config", str(config_path), str(source_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "DOC003" in output
    assert "DOC001" not in output


def test_cli_reads_require_docstring_types_config(tmp_path: Path, capsys) -> None:
    source_path = write_source(
        tmp_path,
        '''
"""Module docs."""


def parse(url: str) -> None:
    """Parse URL.

    Args:
        url:
            URL.
    """
    return None
''',
    )
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(
        '''
[tool.python-docstring-checker]
require-docstring-types = true
''',
        encoding="utf-8",
    )

    exit_code = main(["--config", str(config_path), str(source_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "ARG004" in output


def test_cli_reads_output_config_and_cli_overrides(tmp_path: Path, capsys) -> None:
    source_path = write_source(
        tmp_path,
        '''
"""Module docs."""


def func() -> str:
    """Return text."""
    return "x"
''',
    )
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(
        '''
[tool.python-docstring-checker]
format = "compact"
show-source = true
source-context = 0
''',
        encoding="utf-8",
    )

    exit_code = main(["--config", str(config_path), str(source_path)])
    compact_output = capsys.readouterr().out

    assert exit_code == 1
    assert compact_output.startswith(f"{source_path}:5: RET001 func:")
    assert "> 5 | def func() -> str:" in compact_output

    exit_code = main(["--config", str(config_path), "--format", "json", str(source_path)])
    json_output = capsys.readouterr().out
    payload = json.loads(json_output)

    assert exit_code == 1
    assert payload["summary"]["total"] == 1
    assert "issues" in payload
