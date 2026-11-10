"""STATE.json read/write/validate for the Control Tower phase machinery (P00-T05).

The state file is the single source of truth for the phase runner: which phase
was last completed, the merge commit hash of the previous phase, the directive
hash, the awaiting-merge phase, capability statuses, open STOP items and label
counts.  It is protected against handwritten edits by a ``state_hash`` field
that is the SHA-256 of the remaining fields sorted by key.

Spec: Part 1 §8.2 (state consistency), §10 (phase-end state update); Part 6 §6.17
(build chain), §6.18 (cost telemetry).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

__all__ = [
    "StateError",
    "State",
    "STATE_FIELDS",
    "compute_state_hash",
    "load_state",
    "save_state",
    "validate_state",
    "default_state",
]


class StateError(Exception):
    """A state file read/write/validation error."""


# Fields that make up the state (state_hash is derived, not user-set).
STATE_FIELDS: tuple[str, ...] = (
    "last_completed_phase",
    "previous_merge_hash",
    "awaiting_merge_phase",
    "directive_hash",
    "capability_status_map",
    "open_stop_items",
    "label_counts",
)


@dataclass
class State:
    """The project state (``docs/state/STATE.json``)."""

    last_completed_phase: str = "P00"
    previous_merge_hash: str | None = None
    awaiting_merge_phase: str | None = None
    directive_hash: str = ""
    capability_status_map: dict[str, str] = field(default_factory=dict)
    open_stop_items: list[str] = field(default_factory=list)
    label_counts: dict[str, int] = field(default_factory=dict)
    state_hash: str = ""


def compute_state_hash(data: dict[str, object]) -> str:
    """SHA-256 of *data* with the ``state_hash`` key removed (sorted keys)."""
    copy = {k: v for k, v in data.items() if k != "state_hash"}
    payload = json.dumps(copy, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_state(data: dict[str, object]) -> State:
    """Build a :class:`State` from a raw dict, computing the hash."""
    csm_raw: object = data.get("capability_status_map")
    osi_raw: object = data.get("open_stop_items")
    lc_raw: object = data.get("label_counts")
    state = State(
        last_completed_phase=str(data.get("last_completed_phase", "P00")),
        previous_merge_hash=(
            str(data["previous_merge_hash"])
            if data.get("previous_merge_hash") is not None
            else None
        ),
        awaiting_merge_phase=(
            str(data["awaiting_merge_phase"])
            if data.get("awaiting_merge_phase") is not None
            else None
        ),
        directive_hash=str(data.get("directive_hash", "")),
        capability_status_map={
            str(k): str(v)
            for k, v in (csm_raw.items() if isinstance(csm_raw, dict) else ())
            if isinstance(v, (str, int, float, bool))
        },
        open_stop_items=[str(x) for x in (osi_raw if isinstance(osi_raw, list) else [])],
        label_counts={
            str(k): int(v)
            for k, v in (lc_raw.items() if isinstance(lc_raw, dict) else ())
            if isinstance(v, (int, float))
        },
    )
    state.state_hash = compute_state_hash(asdict(state))
    return state


def load_state(path: Path) -> State:
    """Load and validate STATE.json from *path*.

    Raises :class:`StateError` if the file is missing, not JSON, not an object,
    or the stored ``state_hash`` does not match the recomputed hash (handwritten
    edit).
    """
    if not path.is_file():
        raise StateError(f"state file not found: {path}")
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read state file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise StateError(f"state file {path} is not a JSON object")
    stored_hash = raw.get("state_hash", "")
    expected = compute_state_hash(raw)
    if stored_hash != expected:
        raise StateError(
            f"state file {path}: state_hash mismatch (handwritten edit detected): "
            f"stored {stored_hash!r} != expected {expected!r}"
        )
    return _to_state(raw)


def save_state(path: Path, state: State) -> Path:
    """Write *state* to *path* as JSON with a computed ``state_hash``.

    The hash is always recomputed so the file is never written with a stale or
    handwritten hash.
    """
    data = asdict(state)
    data["state_hash"] = compute_state_hash(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def validate_state(state: State, directive_hash: str) -> list[str]:
    """Check *state* for internal consistency.

    Returns a list of error messages (empty = valid):
      - ``directive_hash`` must match the actual directive hash
      - ``last_completed_phase`` must be a valid phase id (Pxx)
      - ``previous_merge_hash`` if set must be a 64-char hex string
      - ``awaiting_merge_phase`` if set must be a valid phase id
    """
    errors: list[str] = []
    if state.directive_hash != directive_hash:
        errors.append(
            f"directive_hash mismatch: state has {state.directive_hash!r} "
            f"but directive.txt hashes to {directive_hash!r}"
        )
    lcp = state.last_completed_phase
    if not (len(lcp) >= 2 and lcp[0] == "P" and lcp[1:].isdigit()):
        errors.append(f"last_completed_phase {lcp!r} is not a valid phase id")
    if state.previous_merge_hash is not None:
        pmh = state.previous_merge_hash
        if not (len(pmh) == 64 and all(c in "0123456789abcdef" for c in pmh)):
            errors.append(f"previous_merge_hash {pmh!r} is not a 64-char hex string")
    if state.awaiting_merge_phase is not None:
        amp = state.awaiting_merge_phase
        if not (len(amp) >= 2 and amp[0] == "P" and amp[1:].isdigit()):
            errors.append(f"awaiting_merge_phase {amp!r} is not a valid phase id")
    return errors


def default_state(directive_hash: str) -> State:
    """Create the initial P00 state."""
    state = State(
        last_completed_phase="P00",
        previous_merge_hash=None,
        awaiting_merge_phase=None,
        directive_hash=directive_hash,
        capability_status_map={},
        open_stop_items=[],
        label_counts={},
    )
    state.state_hash = compute_state_hash(asdict(state))
    return state
