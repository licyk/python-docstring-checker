"""AST-based Google-style docstring consistency checker."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable

from docstring_checker.google import DocItem, ParsedDocstring, parse_google_docstring
from docstring_checker.models import Issue
from docstring_checker.types import (
    comparison_confidence,
    is_none_type,
    is_type_like,
    types_equal,
)


DEFAULT_EXCLUDES = (
    ".git/*",
    "__pycache__/*",
    ".venv/*",
    "venv/*",
    "build/*",
    "dist/*",
)

STRICTNESS_VALUES = {"strict", "balanced", "public"}
ATTRIBUTE_POLICY_VALUES = {"strict", "documented", "off"}
DEFAULT_BALANCED_IGNORED_METHOD_NAMES = ("format", "emit", "handle", "invalidate_caches")


@dataclass(frozen=True)
class CheckOptions:
    """Options controlling path scanning and diagnostic filtering."""

    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    ignore_codes: frozenset[str] = field(default_factory=frozenset)
    strictness: str = "balanced"
    ignore_names: tuple[str, ...] = ()
    ignore_paths: tuple[str, ...] = ()
    ignore_decorators: tuple[str, ...] = ()
    check_tests: bool | None = None
    check_private: bool | None = None
    check_nested: bool | None = None
    attribute_policy: str | None = None
    ignore_method_names: tuple[str, ...] = ()
    require_docstring_types: bool | None = None
    ignore_empty_init_modules: bool = True

    def should_check_tests(self) -> bool:
        """Return whether test files should be checked."""
        if self.check_tests is not None:
            return self.check_tests
        return self.strictness == "strict"

    def should_check_private(self) -> bool:
        """Return whether private and dunder objects should be checked."""
        if self.check_private is not None:
            return self.check_private
        return self.strictness == "strict"

    def should_check_nested(self) -> bool:
        """Return whether nested functions and classes should be checked."""
        if self.check_nested is not None:
            return self.check_nested
        return self.strictness == "strict"

    def effective_attribute_policy(self) -> str:
        """Return the effective attribute checking policy."""
        if self.attribute_policy is not None:
            return self.attribute_policy
        if self.strictness == "strict":
            return "strict"
        return "documented"

    def effective_ignore_method_names(self) -> tuple[str, ...]:
        """Return method names skipped by the active policy."""
        if self.strictness == "strict":
            return self.ignore_method_names
        return DEFAULT_BALANCED_IGNORED_METHOD_NAMES + self.ignore_method_names

    def should_require_docstring_types(self) -> bool:
        """Return whether missing docstring types should be reported."""
        if self.require_docstring_types is not None:
            return self.require_docstring_types
        return self.strictness == "strict"


@dataclass(frozen=True)
class ParameterInfo:
    """Function parameter metadata extracted from an AST signature."""

    name: str
    display_name: str
    annotation: str | None


@dataclass(frozen=True)
class AttributeInfo:
    """Attribute metadata extracted from module, class, or instance assignment."""

    name: str
    line: int
    annotation: str | None = None
    scope: str = "module"


@dataclass(frozen=True)
class RaiseInfo:
    """Exception metadata extracted from a raise statement."""

    name: str | None = None
    confidence: str = "high"


def check_paths(paths: Iterable[str | Path], options: CheckOptions | None = None) -> list[Issue]:
    """Check all Python files found under the provided paths."""
    checker_options = options or CheckOptions()
    if checker_options.strictness not in STRICTNESS_VALUES:
        raise ValueError(
            "strictness must be one of: " + ", ".join(sorted(STRICTNESS_VALUES))
        )
    if checker_options.effective_attribute_policy() not in ATTRIBUTE_POLICY_VALUES:
        raise ValueError(
            "attribute_policy must be one of: "
            + ", ".join(sorted(ATTRIBUTE_POLICY_VALUES))
        )
    issues: list[Issue] = []
    exclude_patterns = checker_options.exclude + checker_options.ignore_paths

    for file_path in discover_python_files(paths, exclude_patterns):
        if _is_test_path(file_path) and not checker_options.should_check_tests():
            continue
        issues.extend(DocstringChecker(file_path, checker_options).check())

    ignored = checker_options.ignore_codes
    if ignored:
        issues = [issue for issue in issues if issue.code not in ignored]

    return sorted(issues)


def discover_python_files(paths: Iterable[str | Path], exclude: Iterable[str] = ()) -> list[Path]:
    """Return Python files under paths, honoring fnmatch-style excludes."""
    discovered: list[Path] = []
    exclude_patterns = tuple(exclude)

    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file() and path.suffix == ".py":
            candidates = [path]
        elif path.is_dir():
            candidates = path.rglob("*.py")
        else:
            continue

        for candidate in candidates:
            if not _is_excluded(candidate, exclude_patterns):
                discovered.append(candidate)

    return sorted(set(discovered))


class DocstringChecker:
    """Check a single Python file for Google-style docstring consistency."""

    def __init__(self, path: str | Path, options: CheckOptions | None = None) -> None:
        """Initialize the checker for one source file."""
        self.path = Path(path)
        self.options = options or CheckOptions()
        self.issues: list[Issue] = []
        self._class_stack: list[ast.ClassDef] = []
        self._qualname_stack: list[str] = []
        self._module_exports: set[str] | None = None

    def check(self) -> list[Issue]:
        """Run the checker for the configured path."""
        source = self.path.read_text(encoding="utf-8")

        try:
            tree = ast.parse(source, filename=str(self.path))
        except SyntaxError as exc:
            self._add_issue(
                line=exc.lineno or 1,
                code="SYN001",
                object_name="<module>",
                message=f"Syntax error: {exc.msg}",
            )
            return self.issues

        self._module_exports = (
            _module_exports(tree.body) if self.options.strictness == "public" else None
        )
        self._check_module(tree)
        self._visit_body(tree.body, parent_kind="module")
        return self.issues

    def _check_module(self, node: ast.Module) -> None:
        docstring = ast.get_docstring(node, clean=True)
        parsed = parse_google_docstring(docstring)

        if docstring is None and not self._should_ignore_missing_module_docstring(node):
            self._add_issue(1, "DOC001", "<module>", "Module is missing a docstring.")

        self._check_attributes(
            owner_name="<module>",
            owner_doc=parsed,
            attributes=_module_attributes(node.body),
            adjacent_docs=_adjacent_attribute_docs(node.body, "module"),
        )

    def _should_ignore_missing_module_docstring(self, node: ast.Module) -> bool:
        return (
            self.options.ignore_empty_init_modules
            and self.path.name == "__init__.py"
            and _is_empty_module(node)
        )

    def _visit_body(self, body: list[ast.stmt], parent_kind: str) -> None:
        for statement in body:
            if isinstance(statement, ast.ClassDef):
                if self._should_check_class(statement, parent_kind):
                    self._visit_class(statement)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if self._should_check_function(statement, parent_kind):
                    self._visit_function(statement, parent_kind)

    def _visit_class(self, node: ast.ClassDef) -> None:
        self._qualname_stack.append(node.name)
        self._class_stack.append(node)

        docstring = ast.get_docstring(node, clean=True)
        parsed = parse_google_docstring(docstring)
        object_name = self._qualname()

        if docstring is None:
            self._add_issue(
                node.lineno,
                "DOC002",
                object_name,
                "Class is missing a docstring.",
            )

        self._check_attributes(
            owner_name=object_name,
            owner_doc=parsed,
            attributes=_class_attributes(node.body) + _instance_attributes(node.body, self.options),
            adjacent_docs={
                **_adjacent_attribute_docs(node.body, "class"),
                **_method_adjacent_attribute_docs(node.body),
            },
        )

        self._visit_body(node.body, parent_kind="class")
        self._class_stack.pop()
        self._qualname_stack.pop()

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        parent_kind: str,
    ) -> None:
        self._qualname_stack.append(node.name)
        object_name = self._qualname()
        docstring = ast.get_docstring(node, clean=True)

        if docstring is None:
            self._add_issue(
                node.lineno,
                "DOC003",
                object_name,
                "Function or method is missing a docstring.",
            )
        else:
            parsed = parse_google_docstring(docstring)
            self._check_parameters(
                node,
                parsed,
                object_name,
                is_method=parent_kind == "class",
            )
            self._check_returns(node, parsed, object_name)
            self._check_raises(node, parsed, object_name)

        if self.options.should_check_nested():
            self._visit_body(node.body, parent_kind="function")
        self._qualname_stack.pop()

    def _should_check_class(self, node: ast.ClassDef, parent_kind: str) -> bool:
        if not self._is_exported_module_object(node.name, parent_kind):
            return False
        if _matches_any(node.name, self.options.ignore_names):
            return False
        if _has_ignored_decorator(node, self.options.ignore_decorators):
            return False
        if parent_kind == "function" and not self.options.should_check_nested():
            return False
        if not self.options.should_check_private() and _is_private_or_dunder(node.name):
            return False
        return True

    def _should_check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        parent_kind: str,
    ) -> bool:
        if not self._is_exported_module_object(node.name, parent_kind):
            return False
        if _matches_any(node.name, self.options.ignore_names):
            return False
        if _is_property_setter_or_deleter(node):
            return False
        if parent_kind == "class" and _matches_any(
            node.name, self.options.effective_ignore_method_names()
        ):
            return False
        if _has_ignored_decorator(node, self.options.ignore_decorators):
            return False
        if parent_kind == "function" and not self.options.should_check_nested():
            return False
        if not self.options.should_check_private() and _is_private_or_dunder(node.name):
            if node.name == "__init__" and ast.get_docstring(node, clean=True) is not None:
                return True
            return False
        return True

    def _is_exported_module_object(self, name: str, parent_kind: str) -> bool:
        if parent_kind != "module" or self._module_exports is None:
            return True
        return name in self._module_exports

    def _check_parameters(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        docstring: ParsedDocstring,
        object_name: str,
        is_method: bool,
    ) -> None:
        expected = _function_parameters(node, is_method=is_method)
        documented_by_name = {
            _canonical_param_name(item.name): item for item in docstring.args.values()
        }
        expected_by_name = {param.name: param for param in expected}
        type_like_extra_args: list[DocItem] = []

        for param in expected:
            item = documented_by_name.get(param.name)
            if item is None:
                self._add_issue(
                    node.lineno,
                    "ARG001",
                    object_name,
                    f"Parameter '{param.display_name}' is missing from Args.",
                )
                continue

            if param.annotation is None:
                if item.type is not None:
                    self._add_issue(
                        node.lineno,
                        "ARG006",
                        object_name,
                        "Parameter "
                        f"'{param.display_name}' is documented with type "
                        f"'{item.type}' but is missing a signature type annotation.",
                        confidence=comparison_confidence(item.type, item.type),
                    )
                continue

            if item.type is None:
                if self.options.should_require_docstring_types():
                    self._add_issue(
                        node.lineno,
                        "ARG004",
                        object_name,
                        f"Parameter '{param.display_name}' is missing a docstring type.",
                    )
            elif not types_equal(item.type, param.annotation):
                self._add_issue(
                    node.lineno,
                    "ARG003",
                    object_name,
                    "Parameter "
                    f"'{param.display_name}' type mismatch: docstring has "
                    f"'{item.type}', signature has '{param.annotation}'.",
                    confidence=comparison_confidence(item.type, param.annotation),
                )

        for item in docstring.args.values():
            canonical_name = _canonical_param_name(item.name)
            if canonical_name not in expected_by_name:
                if is_type_like(item.name):
                    type_like_extra_args.append(item)
                    continue
                self._add_issue(
                    node.lineno,
                    "ARG002",
                    object_name,
                    f"Parameter '{item.name}' is documented but not present in the signature.",
                )

        self._check_malformed_args(
            node=node,
            docstring=docstring,
            object_name=object_name,
            items=[*docstring.malformed_args, *type_like_extra_args],
        )

    def _check_malformed_args(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        docstring: ParsedDocstring,
        object_name: str,
        items: list[DocItem],
    ) -> None:
        if not items:
            return

        return_annotation = _unparse_optional(node.returns)
        has_yield = _has_yield(node)
        has_value_return = _has_value_return(node)
        expects_return_doc = has_value_return or (
            return_annotation is not None and not is_none_type(return_annotation)
        )
        missing_target_section = (
            has_yield and docstring.yields is None
        ) or (
            not has_yield and expects_return_doc and docstring.returns is None
        )
        target_section = "Yields" if has_yield else "Returns"
        seen: set[str] = set()

        for item in items:
            if item.name in seen:
                continue
            seen.add(item.name)

            matches_return_annotation = (
                return_annotation is not None
                and types_equal(item.name, return_annotation)
            )
            confidence = "high" if matches_return_annotation else "low"

            if matches_return_annotation:
                message = (
                    f"Args entry '{item.name}' is not a parameter. It matches "
                    f"the return annotation; move it to a {target_section} section."
                )
            elif missing_target_section:
                message = (
                    f"Args entry '{item.name}' is not a parameter. It looks like "
                    f"a type, not an argument name; move it to a {target_section} "
                    "section if it documents the returned value."
                )
            else:
                message = (
                    f"Args entry '{item.name}' is not a parameter. It looks like "
                    "a type, not an argument name; remove it from Args."
                )

            self._add_issue(
                node.lineno,
                "ARG005",
                object_name,
                message,
                confidence=confidence,
            )

    def _check_returns(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        docstring: ParsedDocstring,
        object_name: str,
    ) -> None:
        return_annotation = _unparse_optional(node.returns)
        has_value_return = _has_value_return(node)
        has_yield = _has_yield(node)

        if has_yield:
            if docstring.yields is None:
                self._add_issue(
                    node.lineno,
                    "RET001",
                    object_name,
                    "Generator function is missing a Yields section.",
                )
            if docstring.returns is not None:
                self._add_issue(
                    node.lineno,
                    "RET005",
                    object_name,
                    "Generator function should document yielded values with Yields, not Returns.",
                )
            return

        expects_return_doc = has_value_return or (
            return_annotation is not None and not is_none_type(return_annotation)
        )

        if expects_return_doc:
            if docstring.returns is None:
                self._add_issue(
                    node.lineno,
                    "RET001",
                    object_name,
                    "Function returns a value but is missing a Returns section.",
                )
                return

            self._check_return_type(
                node=node,
                object_name=object_name,
                actual_annotation=return_annotation,
                documented=docstring.returns,
                section_name="Returns",
            )
            return

        if docstring.returns is not None and not is_none_type(docstring.returns.type):
            self._add_issue(
                node.lineno,
                "RET002",
                object_name,
                "Function does not return a value but documents a non-None return.",
            )

    def _check_return_type(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        object_name: str,
        actual_annotation: str | None,
        documented: DocItem,
        section_name: str,
    ) -> None:
        if actual_annotation is None:
            return

        if documented.type is None:
            if self.options.should_require_docstring_types():
                self._add_issue(
                    node.lineno,
                    "RET004",
                    object_name,
                    f"{section_name} section is missing a type.",
                )
        elif not types_equal(documented.type, actual_annotation):
            self._add_issue(
                node.lineno,
                "RET003",
                object_name,
                f"{section_name} type mismatch: docstring has "
                f"'{documented.type}', signature has '{actual_annotation}'.",
                confidence=comparison_confidence(documented.type, actual_annotation),
            )

    def _check_raises(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        docstring: ParsedDocstring,
        object_name: str,
    ) -> None:
        raised = _function_raises(node)
        documented = tuple(docstring.raises)
        known_raised = tuple(
            sorted(
                {item.name for item in raised if item.name is not None},
                key=_exception_sort_key,
            )
        )
        has_unknown_raise = any(item.name is None for item in raised)

        for exception_name in known_raised:
            if not _is_exception_documented(exception_name, documented):
                self._add_issue(
                    node.lineno,
                    "RAI001",
                    object_name,
                    f"Exception '{exception_name}' is raised but missing from Raises.",
                )

        if has_unknown_raise and (
            self.options.strictness == "strict" or not documented
        ):
            self._add_issue(
                node.lineno,
                "RAI003",
                object_name,
                "Function raises an exception whose type cannot be determined statically.",
                confidence="low",
            )

        if self.options.strictness == "strict":
            for documented_name in sorted(documented, key=_exception_sort_key):
                if _is_broad_exception(documented_name):
                    continue
                if not any(
                    _exception_names_match(exception_name, documented_name)
                    for exception_name in known_raised
                ):
                    self._add_issue(
                        node.lineno,
                        "RAI002",
                        object_name,
                        f"Exception '{documented_name}' is documented in Raises but not directly raised.",
                    )

    def _check_attributes(
        self,
        owner_name: str,
        owner_doc: ParsedDocstring,
        attributes: list[AttributeInfo],
        adjacent_docs: dict[str, str],
    ) -> None:
        documented = owner_doc.attributes
        seen: set[str] = set()

        for attribute in attributes:
            if attribute.name in seen:
                continue
            seen.add(attribute.name)

            doc_item = documented.get(attribute.name)
            has_adjacent_doc = attribute.name in adjacent_docs
            if not self._should_check_attribute(attribute, doc_item, has_adjacent_doc):
                continue

            if doc_item is None and not has_adjacent_doc:
                self._add_issue(
                    attribute.line,
                    "ATR001",
                    owner_name,
                    f"Attribute '{attribute.name}' is missing a docstring.",
                )
                continue

            if (
                doc_item is not None
                and doc_item.type is not None
                and attribute.annotation is not None
                and not types_equal(doc_item.type, attribute.annotation)
            ):
                self._add_issue(
                    attribute.line,
                    "ATR002",
                    owner_name,
                    "Attribute "
                    f"'{attribute.name}' type mismatch: docstring has "
                    f"'{doc_item.type}', assignment has '{attribute.annotation}'.",
                    confidence=comparison_confidence(doc_item.type, attribute.annotation),
                )

    def _should_check_attribute(
        self,
        attribute: AttributeInfo,
        doc_item: DocItem | None,
        has_adjacent_doc: bool,
    ) -> bool:
        if _matches_any(attribute.name, self.options.ignore_names):
            return False

        if (
            attribute.scope == "module"
            and self._module_exports is not None
            and attribute.name not in self._module_exports
        ):
            return False

        policy = self.options.effective_attribute_policy()
        if policy == "off":
            return False

        has_documentation = doc_item is not None or has_adjacent_doc
        if policy == "documented":
            return has_documentation

        if policy == "strict":
            return True

        return False

    def _add_issue(
        self,
        line: int,
        code: str,
        object_name: str,
        message: str,
        confidence: str = "high",
    ) -> None:
        self.issues.append(
            Issue(
                file=str(self.path),
                line=line,
                code=code,
                object=object_name,
                message=message,
                confidence=confidence,
            )
        )

    def _qualname(self) -> str:
        return ".".join(self._qualname_stack)


def _function_parameters(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    is_method: bool,
) -> list[ParameterInfo]:
    params: list[ParameterInfo] = []
    args = list(node.args.posonlyargs) + list(node.args.args)

    for arg in args:
        params.append(
            ParameterInfo(
                name=arg.arg,
                display_name=arg.arg,
                annotation=_unparse_optional(arg.annotation),
            )
        )

    if is_method and params and params[0].name in {"self", "cls"}:
        params = params[1:]

    if node.args.vararg is not None:
        params.append(
            ParameterInfo(
                name=node.args.vararg.arg,
                display_name=f"*{node.args.vararg.arg}",
                annotation=_unparse_optional(node.args.vararg.annotation),
            )
        )

    for arg in node.args.kwonlyargs:
        params.append(
            ParameterInfo(
                name=arg.arg,
                display_name=arg.arg,
                annotation=_unparse_optional(arg.annotation),
            )
        )

    if node.args.kwarg is not None:
        params.append(
            ParameterInfo(
                name=node.args.kwarg.arg,
                display_name=f"**{node.args.kwarg.arg}",
                annotation=_unparse_optional(node.args.kwarg.annotation),
            )
        )

    return params


def _function_raises(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[RaiseInfo]:
    finder = _RaiseFinder()
    for statement in node.body:
        finder.visit(statement)
    return finder.raises


def _exception_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None

    if isinstance(node, ast.Call):
        name = _exception_name(node.func)
        return name if is_type_like(name) else None

    if isinstance(node, ast.Name):
        return node.id if is_type_like(node.id) else None

    if isinstance(node, ast.Attribute):
        try:
            name = ast.unparse(node)
        except Exception:
            return None
        return name if is_type_like(name) else None

    return None


def _handler_exception_names(node: ast.AST | None) -> list[str | None]:
    if node is None:
        return [None]

    if isinstance(node, ast.Tuple):
        names: list[str | None] = []
        for element in node.elts:
            names.extend(_handler_exception_names(element))
        return names

    return [_exception_name(node)]


def _is_exception_documented(exception_name: str, documented: Iterable[str]) -> bool:
    return any(
        _is_broad_exception(documented_name)
        or _exception_names_match(exception_name, documented_name)
        for documented_name in documented
    )


def _exception_names_match(left: str, right: str) -> bool:
    return left == right or _short_exception_name(left) == _short_exception_name(right)


def _short_exception_name(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _is_broad_exception(name: str) -> bool:
    return _short_exception_name(name) in {"Exception", "BaseException"}


def _exception_sort_key(name: str) -> tuple[str, str]:
    return (_short_exception_name(name), name)


def _module_attributes(body: list[ast.stmt]) -> list[AttributeInfo]:
    attrs: list[AttributeInfo] = []
    for statement in body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            attrs.extend(_attributes_from_assignment(statement, scope="module"))
    return attrs


def _class_attributes(body: list[ast.stmt]) -> list[AttributeInfo]:
    attrs: list[AttributeInfo] = []
    for statement in body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            attrs.extend(_attributes_from_assignment(statement, scope="class"))
    return attrs


def _instance_attributes(body: list[ast.stmt], options: CheckOptions) -> list[AttributeInfo]:
    attrs: list[AttributeInfo] = []
    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if options.strictness != "strict" and statement.name != "__init__":
                continue
            for inner_statement in _iter_function_statements(statement):
                if isinstance(inner_statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    if options.strictness != "strict" and not isinstance(inner_statement, ast.AnnAssign):
                        continue
                    attrs.extend(_attributes_from_assignment(inner_statement, scope="instance"))
    return attrs


def _attributes_from_assignment(
    statement: ast.Assign | ast.AnnAssign | ast.AugAssign,
    scope: str,
) -> list[AttributeInfo]:
    annotation = _assignment_annotation(statement)
    targets: list[ast.expr]

    if isinstance(statement, ast.Assign):
        targets = list(statement.targets)
    else:
        targets = [statement.target]

    attrs: list[AttributeInfo] = []
    for target in targets:
        for name in _target_names(target, scope):
            attrs.append(
                AttributeInfo(
                    name=name,
                    line=getattr(statement, "lineno", 1),
                    annotation=annotation,
                    scope=scope,
                )
            )
    return attrs


def _target_names(target: ast.expr, scope: str) -> list[str]:
    if scope in {"module", "class"}:
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            names: list[str] = []
            for element in target.elts:
                names.extend(_target_names(element, scope))
            return names
        return []

    if scope == "instance":
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            return [target.attr]
        if isinstance(target, (ast.Tuple, ast.List)):
            names = []
            for element in target.elts:
                names.extend(_target_names(element, scope))
            return names
        return []

    return []


def _assignment_annotation(statement: ast.Assign | ast.AnnAssign | ast.AugAssign) -> str | None:
    if isinstance(statement, ast.AnnAssign):
        return _unparse_optional(statement.annotation)

    if isinstance(statement, ast.Assign):
        return statement.type_comment

    return None


def _adjacent_attribute_docs(body: list[ast.stmt], scope: str) -> dict[str, str]:
    docs: dict[str, str] = {}

    for index, statement in enumerate(body[:-1]):
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue

        next_statement = body[index + 1]
        doc = _literal_string(next_statement)
        if doc is None:
            continue

        for attribute in _attributes_from_assignment(statement, scope=scope):
            docs[attribute.name] = doc

    return docs


def _method_adjacent_attribute_docs(body: list[ast.stmt]) -> dict[str, str]:
    docs: dict[str, str] = {}

    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            docs.update(_adjacent_attribute_docs(statement.body, "instance"))

    return docs


def _literal_string(statement: ast.stmt) -> str | None:
    if (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    ):
        return statement.value.value
    return None


def _iter_function_statements(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterable[ast.stmt]:
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield statement
        for child in ast.iter_child_nodes(statement):
            if isinstance(child, ast.stmt):
                yield from _iter_statement_tree(child)


def _iter_statement_tree(statement: ast.stmt) -> Iterable[ast.stmt]:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return

    yield statement
    for child in ast.iter_child_nodes(statement):
        if isinstance(child, ast.stmt):
            yield from _iter_statement_tree(child)


def _has_value_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for statement in _iter_function_statements(node):
        if isinstance(statement, ast.Return) and not _is_none_literal(statement.value):
            return True
    return False


def _has_yield(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    finder = _YieldFinder()
    for statement in node.body:
        finder.visit(statement)
        if finder.found:
            return True
    return False


def _is_none_literal(node: ast.expr | None) -> bool:
    return node is None or (isinstance(node, ast.Constant) and node.value is None)


def _unparse_optional(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    return ast.unparse(node)


def _canonical_param_name(name: str) -> str:
    return name.lstrip("*")


def _module_exports(body: list[ast.stmt]) -> set[str] | None:
    for statement in body:
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            if any(_is_name(target, "__all__") for target in statement.targets):
                value = statement.value
        elif isinstance(statement, ast.AnnAssign) and _is_name(statement.target, "__all__"):
            value = statement.value

        if value is not None:
            return _literal_string_set(value)

    return None


def _literal_string_set(node: ast.expr | None) -> set[str] | None:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: set[str] = set()
        for element in node.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                return None
            values.add(element.value)
        return values
    return None


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_empty_module(node: ast.Module) -> bool:
    return len(node.body) == 0


def _is_test_path(path: Path) -> bool:
    parts = set(path.parts)
    name = path.name
    return "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py")


def _is_private_or_dunder(name: str) -> bool:
    return name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def _matches_any(value: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if fnmatch(value, pattern):
            return True
    return False


def _has_ignored_decorator(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    patterns: Iterable[str],
) -> bool:
    if not patterns:
        return False

    pattern_tuple = tuple(patterns)
    for decorator in node.decorator_list:
        names = _decorator_names(decorator)
        if any(_matches_any(name, pattern_tuple) for name in names):
            return True
    return False


def _is_property_setter_or_deleter(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        for name in _decorator_names(decorator):
            if name.endswith(".setter") or name.endswith(".deleter"):
                return True
    return False


def _decorator_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Call):
        return _decorator_names(node.func)

    try:
        full_name = ast.unparse(node)
    except Exception:
        return set()

    return {full_name, full_name.rsplit(".", 1)[-1]}


def _is_excluded(path: Path, patterns: tuple[str, ...]) -> bool:
    path_text = path.as_posix()
    name_text = path.name
    for pattern in patterns:
        normalized = pattern.replace("\\", "/")
        if (
            fnmatch(path_text, normalized)
            or fnmatch(name_text, normalized)
            or fnmatch(path_text, f"*/{normalized}")
        ):
            return True
    return False


class _YieldFinder(ast.NodeVisitor):
    """Find yields without descending into nested scopes."""

    def __init__(self) -> None:
        """Initialize the visitor."""
        self.found = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Skip nested functions."""
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Skip nested async functions."""
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Skip nested classes."""
        return

    def visit_Yield(self, node: ast.Yield) -> None:
        """Mark a yield expression as found."""
        self.found = True

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        """Mark a yield-from expression as found."""
        self.found = True


class _RaiseFinder(ast.NodeVisitor):
    """Find raised exceptions without descending into nested scopes."""

    def __init__(self) -> None:
        """Initialize the visitor."""
        self.raises: list[RaiseInfo] = []
        self._handler_stack: list[list[str | None]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Skip nested functions."""
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Skip nested async functions."""
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Skip nested classes."""
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Skip nested lambda scopes."""
        return

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """Track the active except handler for bare re-raises."""
        self._handler_stack.append(_handler_exception_names(node.type))
        for statement in node.body:
            self.visit(statement)
        self._handler_stack.pop()

    def visit_Raise(self, node: ast.Raise) -> None:
        """Record the statically visible raised exception."""
        if node.exc is None:
            if not self._handler_stack:
                self.raises.append(RaiseInfo(confidence="low"))
                return

            for exception_name in self._handler_stack[-1]:
                if exception_name is None:
                    self.raises.append(RaiseInfo(confidence="low"))
                else:
                    self.raises.append(RaiseInfo(name=exception_name))
            return

        exception_name = _exception_name(node.exc)
        if exception_name is None:
            self.raises.append(RaiseInfo(confidence="low"))
        else:
            self.raises.append(RaiseInfo(name=exception_name))
