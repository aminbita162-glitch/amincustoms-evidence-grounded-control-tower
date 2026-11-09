"""Index gate — generates test-house/INDEX.md and validates test headers (P00-T04).

Scans ``test-house/**/*.py`` for test functions, extracts the header from each
function's docstring or preceding comment block, and fails on:

  - an incomplete header (missing required field)
  - a duplicate id (same id from a different header block)
  - a stale index (INDEX.md doesn't match the current state)
  - a test without a speed-class marker (``@pytest.mark.fast``/``slow``/``e2e``)

Generates ``test-house/INDEX.md`` with one row per test id (id, title, level,
file, function name), sorted by id for byte-identical regeneration.

Invokable as ``python -m tools.gate.gates.index``.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "TestFunction",
    "IndexEntry",
    "Violation",
    "scan_directory",
    "check_index",
    "generate_index",
    "write_index",
    "main",
]

# ---------------------------------------------------------------------------
# Header schema (mirrored from test-house/header_schema.py so this module is
# self-contained and mypy-checkable without import-path tricks).
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "purpose",
    "level",
    "requirement",
    "input",
    "expected",
    "risk",
    "capability",
)

FIELD_ALIASES: dict[str, str] = {
    "id": "id",
    "title": "title",
    "purpose": "purpose",
    "level": "level",
    "requirement": "requirement",
    "requirement ids": "requirement",
    "scenario ids": "scenario",
    "input": "input",
    "expected": "expected",
    "expected result": "expected",
    "risk": "risk",
    "risk covered": "risk",
    "capability": "capability",
    "owning capability": "capability",
}

VALID_LEVELS: frozenset[str] = frozenset({"fast", "slow", "e2e"})

SPEED_MARKERS: frozenset[str] = frozenset(
    {"pytest.mark.fast", "pytest.mark.slow", "pytest.mark.e2e"}
)

_ID_RE = re.compile(r"T-[A-Z]+-[A-Z0-9][A-Z0-9-]*$")

_FIELD_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z ]*):\s*(.*)$")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestFunction:
    """A test function found during scanning."""

    function_name: str
    file_path: str
    fields: dict[str, str]
    speed: str | None


@dataclass(frozen=True)
class IndexEntry:
    """One row in the test index."""

    test_id: str
    title: str
    level: str
    file_path: str
    function_name: str


@dataclass(frozen=True)
class Violation:
    """An index gate violation."""

    message: str


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------


def _parse_header(text: str) -> dict[str, str]:
    """Extract ``Field: value`` pairs from *text* (comments or docstring)."""
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if not line:
                continue
        match = _FIELD_LINE_RE.match(line)
        if not match:
            continue
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        canonical = FIELD_ALIASES.get(key)
        if canonical is not None and canonical not in result:
            result[canonical] = value
    return result


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _decorator_dotted_name(node: ast.expr) -> str:
    """Get the dotted name of a decorator expression."""
    if isinstance(node, ast.Call):
        return _decorator_dotted_name(node.func)
    if isinstance(node, ast.Attribute):
        base = _decorator_dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _speed_class(node: ast.FunctionDef) -> str | None:
    """Return ``'fast'``, ``'slow'``, or ``'e2e'`` if the function has a marker."""
    for decorator in node.decorator_list:
        name = _decorator_dotted_name(decorator)
        if name in SPEED_MARKERS:
            return name.rsplit(".", 1)[-1]
    return None


def _first_line(node: ast.FunctionDef) -> int:
    """First line of the function including decorators."""
    if node.decorator_list:
        return min(d.lineno for d in node.decorator_list)
    return node.lineno


def _is_inside_stmt(line_no: int, ranges: list[tuple[int, int]]) -> bool:
    """Check whether *line_no* falls inside any top-level statement range."""
    return any(start <= line_no <= end for start, end in ranges)


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------


def _scan_file(py_file: Path, root: Path) -> list[TestFunction]:
    """Scan a single ``.py`` file for test functions with headers."""
    source = py_file.read_text(encoding="utf-8")
    if not source.strip():
        return []
    tree = ast.parse(source, filename=str(py_file))
    lines = source.splitlines(keepends=False)

    # Map first line (including decorators) -> FunctionDef for top-level test functions.
    test_nodes: dict[int, ast.FunctionDef] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name.startswith("test_"):
            test_nodes[_first_line(stmt)] = stmt

    # Line ranges of all top-level statements (to skip comments inside bodies).
    stmt_ranges: list[tuple[int, int]] = []
    for stmt in tree.body:
        start = stmt.lineno
        if (
            isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and stmt.decorator_list
        ):
            start = min(d.lineno for d in stmt.decorator_list)
        end = stmt.end_lineno if stmt.end_lineno is not None else stmt.lineno
        stmt_ranges.append((start, end))

    current_header: dict[str, str] = {}
    prev_was_comment = False
    results: list[TestFunction] = []
    rel_path = str(py_file.relative_to(root))

    for i, raw_line in enumerate(lines):
        line_no = i + 1
        line = raw_line.strip()

        if line_no in test_nodes:
            node = test_nodes[line_no]
            docstring = ast.get_docstring(node) or ""
            doc_fields = _parse_header(docstring)
            header = {**current_header, **doc_fields}
            # Normalise level to the first word (handles annotated levels like
            # "slow (uses real tool round-trips via the selftest fixtures)").
            level_raw = header.get("level", "")
            if level_raw:
                header["level"] = level_raw.split()[0]
            speed = _speed_class(node)
            results.append(
                TestFunction(
                    function_name=node.name,
                    file_path=rel_path,
                    fields=header,
                    speed=speed,
                )
            )
            prev_was_comment = False
        elif line.startswith("#") and not _is_inside_stmt(line_no, stmt_ranges):
            if not prev_was_comment:
                current_header = {}
            content = line.lstrip("#").strip()
            match = _FIELD_LINE_RE.match(content)
            if match:
                key = match.group(1).strip().lower()
                value = match.group(2).strip()
                canonical = FIELD_ALIASES.get(key)
                if canonical is not None:
                    current_header[canonical] = value
            prev_was_comment = True
        else:
            prev_was_comment = False

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_directory(directory: Path) -> list[TestFunction]:
    """Scan a directory tree for all test functions with their headers."""
    results: list[TestFunction] = []
    for py_file in sorted(directory.rglob("*.py")):
        if py_file.name in ("conftest.py", "__init__.py"):
            continue
        results.extend(_scan_file(py_file, directory))
    return results


def _unique_entries(functions: list[TestFunction]) -> list[IndexEntry]:
    """Collect one :class:`IndexEntry` per unique test id (first function wins)."""
    entries: dict[str, IndexEntry] = {}
    for func in functions:
        test_id = func.fields.get("id", "")
        if not test_id or test_id in entries:
            continue
        entries[test_id] = IndexEntry(
            test_id=test_id,
            title=func.fields.get("title", ""),
            level=func.fields.get("level", ""),
            file_path=func.file_path,
            function_name=func.function_name,
        )
    return sorted(entries.values(), key=lambda e: e.test_id)


def generate_index_content(functions: list[TestFunction]) -> str:
    """Generate the INDEX.md text from a list of test functions."""
    entries = _unique_entries(functions)
    lines: list[str] = [
        "# Test Index",
        "",
        "| id | title | level | file | function |",
        "|---|---|---|---|---|",
    ]
    for entry in entries:
        lines.append(
            f"| {entry.test_id} | {entry.title} | {entry.level} | "
            f"{entry.file_path} | {entry.function_name} |"
        )
    lines.append("")
    return "\n".join(lines)


def generate_index(directory: Path) -> str:
    """Generate the INDEX.md content for a directory."""
    return generate_index_content(scan_directory(directory))


def write_index(directory: Path) -> None:
    """Write the INDEX.md file to *directory*."""
    content = generate_index(directory)
    (directory / "INDEX.md").write_text(content, encoding="utf-8")


def check_index(directory: Path) -> list[Violation]:
    """Check the index for violations.  Returns a list (empty = clean)."""
    violations: list[Violation] = []
    functions = scan_directory(directory)

    # Validate headers and markers.
    seen_ids: dict[str, str] = {}
    for func in functions:
        for field_name in REQUIRED_FIELDS:
            if field_name not in func.fields or not func.fields[field_name]:
                violations.append(
                    Violation(
                        f"{func.file_path}::{func.function_name}: "
                        f"missing required field '{field_name}'"
                    )
                )
        test_id = func.fields.get("id", "")
        if test_id:
            if not _ID_RE.match(test_id):
                violations.append(
                    Violation(
                        f"{func.file_path}::{func.function_name}: invalid id format '{test_id}'"
                    )
                )
            header_sig = "|".join(f"{k}={func.fields[k]}" for k in sorted(func.fields))
            if test_id in seen_ids and seen_ids[test_id] != header_sig:
                violations.append(
                    Violation(
                        f"duplicate id '{test_id}' with different headers in {func.file_path}"
                    )
                )
            else:
                seen_ids[test_id] = header_sig
        level = func.fields.get("level", "")
        if level and level not in VALID_LEVELS:
            violations.append(
                Violation(f"{func.file_path}::{func.function_name}: invalid level '{level}'")
            )
        if func.speed is None:
            violations.append(
                Violation(
                    f"{func.file_path}::{func.function_name}: "
                    f"missing speed-class marker (@pytest.mark.fast/slow/e2e)"
                )
            )

    # Stale index check.
    index_path = directory / "INDEX.md"
    if index_path.is_file():
        expected = generate_index_content(functions)
        actual = index_path.read_text(encoding="utf-8")
        if actual != expected:
            violations.append(Violation("stale index: INDEX.md does not match current state"))

    return violations


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point: check the test index, write if clean, exit 0 or 1."""
    root = Path(__file__).resolve().parents[3]
    test_house = root / "test-house"
    violations = check_index(test_house)
    # Always write the current index so it stays up to date.
    write_index(test_house)
    if violations:
        for v in violations:
            print(f"index: {v.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
