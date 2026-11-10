"""State gate — validates STATE.json integrity (P00-T05).

Checks that ``docs/state/STATE.json`` is valid: it loads the state file
through :func:`tools.gate.phase.state.load_state`, which verifies the
``state_hash`` field (a SHA-256 of the remaining fields sorted by key).
A handwritten edit that changes any field without updating the hash
is detected and fails the gate.

Exit codes: 0 valid, 1 invalid state, 2 misconfiguration.

Invokable as ``python -m tools.gate.gates.state``.

Spec: Part 1 §8.2, Part 6 §6.17, P00-T05.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from tools.gate.phase.state import StateError, load_state

__all__ = [
    "check_state",
    "main",
]


def _repo_root() -> Path:
    """Resolve the repository root, respecting GATE_ROOT if set."""
    gate_root = os.environ.get("GATE_ROOT")
    if gate_root:
        return Path(gate_root).resolve()
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    """The ``tools/gate`` package directory (parent of this module's package)."""
    # tools/gate/gates/state.py -> parents[1] is tools/gate/.
    return Path(__file__).resolve().parents[1]


def check_state(repo_root: Path) -> int:
    """Validate ``docs/state/STATE.json`` in *repo_root*.

    Returns 0 if the state file is valid, 1 if it is invalid (hash mismatch,
    not found, or unparseable), 2 on misconfiguration.
    """
    state_path = repo_root / "docs" / "state" / "STATE.json"
    try:
        load_state(state_path)
    except StateError as exc:
        print(f"state: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"state: {exc}", file=sys.stderr)
        return 2
    return 0


def main() -> int:
    """Entry point for the state gate."""
    return check_state(_repo_root())


if __name__ == "__main__":
    sys.exit(main())
