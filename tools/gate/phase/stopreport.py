"""STOP report validation for the AminCustoms phase machinery (P00-T05, P00-T13).

Validates a STOP report (Part 1 §12.4) against the required fields:
phase, task, condition, what happened, attempts, evidence, decision needed,
options, untouched.

Spec: Part 1 §12.4, §7.5 (recovery).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

__all__ = [
    "STOP_REPORT_FIELDS",
    "validate_stopreport",
    "check_stopreport_file",
    "main",
]

# Required fields for a STOP report (Part 1 §12.4).
STOP_REPORT_FIELDS: tuple[str, ...] = (
    "phase",
    "task",
    "condition",
    "what_happened",
    "attempts",
    "evidence",
    "decision_needed",
    "options",
    "untouched",
)


def validate_stopreport(text: str) -> list[str]:
    """Validate a STOP report.

    Accepts either a ``Field: value`` text format or a JSON object.
    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []
    fields: dict[str, str] = {}

    # Try JSON first.
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            raw: object = json.loads(stripped)
        except json.JSONDecodeError as exc:
            return [f"invalid JSON: {exc}"]
        if not isinstance(raw, dict):
            return ["STOP report is not a JSON object"]
        for key in STOP_REPORT_FIELDS:
            value = raw.get(key)
            if value is not None:
                fields[key] = str(value)
    else:
        # Parse Field: value lines.
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            colon = line.find(":")
            if colon < 0:
                continue
            key = line[:colon].strip().lower().replace(" ", "_")
            value = line[colon + 1 :].strip()
            fields[key] = value

    # Check required fields.
    for field_name in STOP_REPORT_FIELDS:
        if field_name not in fields or not fields[field_name]:
            errors.append(f"missing required field {field_name!r}")

    # Check for extra fields.
    for field_name in fields:
        if field_name not in STOP_REPORT_FIELDS:
            errors.append(f"extra field {field_name!r} not in STOP report schema")

    return errors


def check_stopreport_file(path: Path) -> int:
    """Read and validate a STOP report file.

    Returns 0 if valid, 1 if missing fields, 2 if file not found.
    """
    if not path.is_file():
        print(f"stopreport: file not found: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    errors = validate_stopreport(text)
    if errors:
        for err in errors:
            print(f"stopreport: {err}", file=sys.stderr)
        return 1
    return 0


def main(args: list[str]) -> int:
    """CLI entry for ``gate stopreport check <file>``."""
    if not args or args[0] != "check":
        print("usage: gate stopreport check <file>", file=sys.stderr)
        return 2
    if len(args) < 2:
        print("usage: gate stopreport check <file>", file=sys.stderr)
        return 2
    return check_stopreport_file(Path(args[1]))
