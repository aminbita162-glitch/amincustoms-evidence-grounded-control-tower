"""STOP report validation for the AminCustoms phase machinery (P00-T05).

Validates a STOP report (Part 1 §12.4) against the required fields:
phase, task, condition, what happened, attempts, evidence, decision needed,
options, untouched.

Spec: Part 1 §12.4, §7.5 (recovery).
"""

from __future__ import annotations

__all__ = [
    "STOP_REPORT_FIELDS",
    "validate_stopreport",
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
    import json

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
