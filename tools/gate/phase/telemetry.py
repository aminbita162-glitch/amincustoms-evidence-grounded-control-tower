"""Cost telemetry — self-reported budget figures (P00-T12).

At ``Pnn-END2`` the gate copies the budget figures of the phase report (tool
calls and tokens split into fixed overhead and task work, retries used per
task, STOP count) into ``docs/state/telemetry.json``.  The figures are
self-reported by the agent and labelled so; they feed the calibration of
decision D-34 and are never used as evidence of correctness.

Spec: Part 6 §6.18, P00-T12.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "TelemetryError",
    "TelemetryData",
    "TELEMETRY_LABEL",
    "validate_telemetry",
    "check_overhead_limits",
    "save_telemetry",
    "load_telemetry",
]


class TelemetryError(Exception):
    """A telemetry read/write/validation error."""


def _to_int(value: object) -> int:
    """Convert a value to int, treating ``None`` or missing as 0."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value))
    except TypeError, ValueError:
        return 0


# The label that marks the figures as self-reported (Part 6 §6.18).
TELEMETRY_LABEL = "SELF-REPORTED"

# Required telemetry fields (the overhead/task split).
_TELEMETRY_FIELDS: tuple[str, ...] = (
    "tool_calls_overhead",
    "tool_calls_task",
    "tokens_overhead",
    "tokens_task",
    "retries",
    "stop_count",
    "label",
)


@dataclass
class TelemetryData:
    """The cost telemetry figures copied at ``Pnn-END2``."""

    tool_calls_overhead: int = 0
    tool_calls_task: int = 0
    tokens_overhead: int = 0
    tokens_task: int = 0
    retries: dict[str, int] = field(default_factory=dict)
    stop_count: int = 0
    label: str = TELEMETRY_LABEL


def validate_telemetry(data: dict[str, object]) -> list[str]:
    """Validate the structure of a telemetry dict.

    Returns a list of error messages (empty = valid):
      - ``label`` must equal ``"SELF-REPORTED"``
      - the overhead/task split must be present (``tool_calls_overhead`` /
        ``tool_calls_task``, ``tokens_overhead`` / ``tokens_task``)

    A telemetry entry without the label fails.  A phase report (or telemetry)
    that doesn't split overhead from task work fails (missing the
    overhead/task split).
    """
    errors: list[str] = []
    label = str(data.get("label", ""))
    if label != TELEMETRY_LABEL:
        errors.append(f"telemetry label is {label!r}, expected {TELEMETRY_LABEL!r}")
    for field_name in _TELEMETRY_FIELDS:
        if field_name == "label":
            continue
        if field_name not in data:
            errors.append(
                f"missing required telemetry field {field_name!r} (overhead/task split required)"
            )
    return errors


def check_overhead_limits(
    data: dict[str, object],
    limits: dict[str, int] | None,
) -> list[str]:
    """Check that the overhead figures do not exceed the set limits.

    - If *limits* is ``None``, only the total is enforced (against the
      ``total_limit`` field in *data* if present; otherwise nothing).
    - If *limits* is a dict, each part limit (``overhead``, ``task``) is
      enforced; exceeding a set limit is a violation.  The total is enforced
      against ``limits["total"]`` if present.
    - A limit field present in *data* but not in the *limits* (the decision
      record) fails: the limit was changed outside the owner's decision record.
    """
    violations: list[str] = []

    tool_calls_overhead = _to_int(data.get("tool_calls_overhead", 0))
    tool_calls_task = _to_int(data.get("tool_calls_task", 0))
    total = tool_calls_overhead + tool_calls_task

    if limits is None:
        # Only the total is enforced (no part limits).
        total_limit_raw = data.get("total_limit")
        if total_limit_raw is not None:
            total_limit = _to_int(total_limit_raw)
            if total > total_limit:
                violations.append(f"total exceeds limit ({total} > {total_limit})")
        return violations

    # limits is a dict — check total and parts.
    if "total" in limits and total > limits["total"]:
        violations.append(f"total exceeds limit ({total} > {limits['total']})")

    # Check part limits.
    part_checks: list[tuple[str, str]] = [
        ("overhead", "tool_calls_overhead"),
        ("task", "tool_calls_task"),
    ]
    for part_name, data_key in part_checks:
        if part_name in limits and data_key in data:
            value = _to_int(data[data_key])
            limit = limits[part_name]
            if value > limit:
                violations.append(f"overhead part {part_name} exceeds limit ({value} > {limit})")

    # A limit field present in the telemetry but not in the decision record.
    for key in data:
        if key.endswith("_limit"):
            limit_part = key[: -len("_limit")]
            if limit_part not in limits and limit_part != "total":
                violations.append(
                    f"limit {limit_part!r} present in telemetry but not in decision record"
                )

    return violations


def save_telemetry(path: Path, data: dict[str, object]) -> Path:
    """Write *data* to *path* as JSON (sorted keys, 2-space indent)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_telemetry(path: Path) -> dict[str, object]:
    """Read and validate ``telemetry.json`` from *path*.

    Raises :class:`TelemetryError` if the file is missing, not JSON, not an
    object, or fails validation.
    """
    if not path.is_file():
        raise TelemetryError(f"telemetry file not found: {path}")
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TelemetryError(f"cannot read telemetry file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise TelemetryError(f"telemetry file {path} is not a JSON object")
    errors = validate_telemetry(raw)
    if errors:
        raise TelemetryError(f"telemetry validation failed: {'; '.join(errors)}")
    return raw
