"""Coverage baselines read/write/check for the Control Tower phase machinery (P00-T05).

``docs/state/baselines.json`` records the floor coverage values per component.
A phase that decreases coverage below its baseline is a STOP.

Schema::

    { "tools/gate": { "branch_coverage": 0.85, "line_coverage": 0.90 } }

Spec: Part 1 §8.2 (everything the phase had to update is updated); baseline
monotonicity is a phase-exit condition.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import cast

__all__ = [
    "BaselineError",
    "load_baselines",
    "save_baselines",
    "check_baseline_decrease",
    "measure_coverage",
    "update_baselines",
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


def _as_coverage_number(value: object, name: str) -> float:
    """Coerce a coverage JSON value to a non-negative ``float``."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise BaselineError(f"coverage totals.{name} is not a number")
    return float(value)


def measure_coverage(
    project_root: Path,
    component: str = "tools/gate",
) -> dict[str, float]:
    """Measure line and branch coverage for *component* via pytest-cov.

    Runs the project test suite with ``--cov=<component> --cov-branch`` and a
    JSON coverage report, then reads the aggregate ``totals`` to derive
    ``line_coverage`` (``covered_lines / num_statements``) and
    ``branch_coverage`` (``covered_branches / num_branches``), each in
    ``[0.0, 1.0]`` and rounded to four decimals.

    Raises :class:`BaselineError` if coverage cannot be measured (pytest
    missing, the JSON report not produced, or a malformed ``totals`` block).
    """
    pytest_bin = project_root / ".venv" / "bin" / "pytest"
    executable = str(pytest_bin) if pytest_bin.is_file() else "pytest"
    with tempfile.TemporaryDirectory() as tmp_dir:
        cov_json = Path(tmp_dir) / "coverage.json"
        cmd: list[str] = [
            executable,
            f"--cov={component}",
            "--cov-branch",
            f"--cov-report=json:{cov_json}",
            "-q",
            "--no-header",
            "-p",
            "no:randomly",
            "-o",
            "addopts=",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if not cov_json.is_file():
            raise BaselineError(
                f"coverage measurement failed (pytest exit {proc.returncode}); "
                f"stderr: {proc.stderr.strip()[:400]}"
            )
        raw_text = cov_json.read_text(encoding="utf-8")
    raw: object = json.loads(raw_text)
    if not isinstance(raw, dict):
        raise BaselineError("coverage JSON is not an object")
    totals_obj: object = raw.get("totals")
    if not isinstance(totals_obj, dict):
        raise BaselineError("coverage JSON has no totals object")
    totals = cast(dict[str, object], totals_obj)
    covered_lines = _as_coverage_number(totals.get("covered_lines"), "covered_lines")
    num_statements = _as_coverage_number(totals.get("num_statements"), "num_statements")
    covered_branches = _as_coverage_number(totals.get("covered_branches"), "covered_branches")
    num_branches = _as_coverage_number(totals.get("num_branches"), "num_branches")
    line_cov = covered_lines / num_statements if num_statements > 0 else 0.0
    branch_cov = covered_branches / num_branches if num_branches > 0 else 0.0
    return {
        "line_coverage": round(line_cov, 4),
        "branch_coverage": round(branch_cov, 4),
    }


def update_baselines(
    path: Path,
    measured: dict[str, dict[str, float]],
) -> tuple[dict[str, dict[str, float]], list[str]]:
    """Ratchet *measured* against the baselines in *path* (monotonic).

    For each component and coverage key, the higher of the existing baseline
    and the measured value is kept; a measured value strictly below the
    existing baseline is **not** written (the ratchet never lowers a floor).
    Returns ``(updated, decreases)`` where *decreases* lists every
    ``component.key`` whose measured value fell below the existing floor.
    """
    existing = load_baselines(path)
    updated: dict[str, dict[str, float]] = {}
    decreases: list[str] = []
    for component in sorted(set(existing) | set(measured)):
        floor_row = existing.get(component, {})
        measured_row = measured.get(component, {})
        row: dict[str, float] = {}
        for key in _COVERAGE_KEYS:
            floor = floor_row.get(key)
            value = measured_row.get(key)
            candidates = [c for c in (floor, value) if c is not None]
            if not candidates:
                continue
            chosen = max(candidates)
            row[key] = chosen
            if floor is not None and value is not None and value < floor:
                decreases.append(f"{component}.{key}: {value} < baseline {floor} (kept {chosen})")
        if row:
            updated[component] = row
    return updated, decreases
