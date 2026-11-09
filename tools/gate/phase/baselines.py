"""Coverage baselines read/write/check for the AminCustoms phase machinery (P00-T05).

``docs/state/baselines.json`` records the floor coverage values per component.
A phase that decreases coverage below its baseline is a STOP.

Schema::

    { "tools/gate": { "branch_coverage": 0.85, "line_coverage": 0.90 } }

Spec: Part 1 §8.2 (everything the phase had to update is updated); baseline
monotonicity is a phase-exit condition.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = [
    "BaselineError",
    "load_baselines",
    "save_baselines",
    "check_baseline_decrease",
]

_COVERAGE_KEYS: tuple[str, ...] = ("branch_coverage", "line_coverage")


class BaselineError(Exception):
    """A baselines file read/write error."""


def load_baselines(path: Path) -> dict[str, dict[str, float]]:
    """Load ``baselines.json`` from *path* (empty dict if missing)."""
    if not path.is_file():
        return {}
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError(f"cannot read baselines {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BaselineError(f"baselines {path} is not a JSON object")
    result: dict[str, dict[str, float]] = {}
    for component, entry in raw.items():
        if not isinstance(entry, dict):
            raise BaselineError(f"baselines[{component!r}] is not an object")
        result[str(component)] = {}
        for key in _COVERAGE_KEYS:
            if key in entry:
                value = entry[key]
                if not isinstance(value, int | float) or isinstance(value, bool):
                    raise BaselineError(f"baselines[{component!r}].{key} is not a number")
                result[str(component)][key] = float(value)
    return result


def save_baselines(path: Path, baselines: dict[str, dict[str, float]]) -> Path:
    """Write *baselines* to *path* as sorted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(baselines, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def check_baseline_decrease(
    baselines: dict[str, dict[str, float]],
    measured: dict[str, dict[str, float]],
) -> list[str]:
    """Return a list of decreases (empty = no decrease).

    For each component and coverage key present in *baselines*, if *measured*
    is strictly less than the baseline, the decrease is reported.
    """
    decreases: list[str] = []
    for component, baseline in baselines.items():
        meas = measured.get(component, {})
        for key in _COVERAGE_KEYS:
            floor = baseline.get(key)
            if floor is None:
                continue
            actual = meas.get(key)
            if actual is None:
                decreases.append(f"{component}.{key}: missing from measured (baseline {floor})")
            elif actual < floor:
                decreases.append(f"{component}.{key}: {actual} < baseline {floor} (decrease)")
    return decreases
