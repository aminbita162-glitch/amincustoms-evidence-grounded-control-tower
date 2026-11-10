"""Selftest gate — the gate of gates (Part 6 §6.13).

Runs every active gate (except ``selftest`` itself) on its violation and clean
fixtures: the violation fixture must make the gate fail and the clean fixture
must make it pass. Also fails when the active set lacks a gate the schedule
requires for the current phase, or when an active gate lacks either fixture.

Invokable as ``python -m tools.gate.gates.selftest``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools.gate.runner import (
    SCHEDULE,
    default_env,
    load_catalogue,
    read_current_phase,
    run_selftest,
)


def _repo_root() -> Path:
    """Resolve the repository root from this module's location."""
    # tools/gate/gates/selftest.py -> parents[3] is the repository root.
    return Path(__file__).resolve().parents[3]


def _gate_package_dir() -> Path:
    """The ``tools/gate`` package directory (parent of this module's package)."""
    # tools/gate/gates/selftest.py -> parents[1] is tools/gate/.
    return Path(__file__).resolve().parents[1]


def main() -> int:
    """Entry point: load the catalogue, run selftest, return the exit code."""
    catalogue_path = _gate_package_dir() / "catalogue.toml"
    repo_root = _repo_root()
    log_dir = repo_root / ".gate-logs"
    state_path = repo_root / "docs" / "state" / "STATE.json"
    catalogue = load_catalogue(catalogue_path)
    current_phase = read_current_phase(state_path)
    env = default_env(repo_root)
    code = run_selftest(
        catalogue=catalogue,
        current_phase=current_phase,
        project_root=repo_root,
        schedule=SCHEDULE,
        env=env,
    )
    # ensure the log directory exists even on a clean pass
    log_dir.mkdir(parents=True, exist_ok=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
