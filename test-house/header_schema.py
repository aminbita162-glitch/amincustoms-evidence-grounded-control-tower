"""Mandatory test header schema for the AminCustoms test house (P00-T04).

Every test function must carry a header with these fields:
    id, title, purpose, level, requirement, input, expected, risk, capability.

The header may appear in the function's docstring (as ``Field: value`` lines)
or in the comment block immediately preceding the function.

Spec: Part 4 §4.5.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "REQUIRED_FIELDS",
    "FIELD_ALIASES",
    "VALID_LEVELS",
    "TestHeader",
    "HeaderError",
    "parse_header",
    "validate_header",
    "validate_id",
]

# The nine required header fields, in canonical order.
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

# Aliases that map to each canonical field name.
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

# Valid speed-class levels.
VALID_LEVELS: frozenset[str] = frozenset({"fast", "slow", "e2e"})

# Test id format: T-AREA-SUFFIX (e.g., T-GATE-0009, T-GATE-SELFTEST).
_ID_RE = re.compile(r"T-[A-Z]+-[A-Z0-9][A-Z0-9-]*$")


@dataclass(frozen=True)
class TestHeader:
    """Parsed header from a test function's docstring or comment block."""

    fields: dict[str, str]

    @property
    def id(self) -> str:
        return self.fields.get("id", "")

    @property
    def title(self) -> str:
        return self.fields.get("title", "")

    @property
    def level(self) -> str:
        return self.fields.get("level", "")

    @property
    def capability(self) -> str:
        return self.fields.get("capability", "")


class HeaderError(Exception):
    """A header validation error."""


def validate_id(test_id: str) -> bool:
    """Return True if *test_id* matches the T-AREA-SUFFIX format."""
    return bool(_ID_RE.match(test_id))


def parse_header(text: str) -> dict[str, str]:
    """Extract ``Field: value`` pairs from *text*.

    Handles both comment lines (``# field: value``) and plain lines
    (``field: value`` from docstrings).  Only fields listed in
    :data:`FIELD_ALIASES` are recognised; the first occurrence of each
    canonical field wins.
    """
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if not line:
                continue
        match = re.match(r"^([A-Za-z][A-Za-z ]*):\s*(.*)$", line)
        if not match:
            continue
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        canonical = FIELD_ALIASES.get(key)
        if canonical is not None and canonical not in result:
            result[canonical] = value
    return result


def validate_header(fields: dict[str, str], function_name: str) -> list[str]:
    """Validate a parsed header.  Returns a list of error messages (empty = OK)."""
    errors: list[str] = []
    for field_name in REQUIRED_FIELDS:
        if field_name not in fields or not fields[field_name]:
            errors.append(f"{function_name}: missing required field '{field_name}'")
    test_id = fields.get("id", "")
    if test_id and not validate_id(test_id):
        errors.append(f"{function_name}: invalid id format '{test_id}'")
    level = fields.get("level", "")
    if level and level not in VALID_LEVELS:
        errors.append(f"{function_name}: invalid level '{level}' (must be fast, slow, or e2e)")
    return errors
