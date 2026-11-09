"""Build chain — append-only hash chain of the build history (P00-T12).

The gate keeps ``docs/state/CHAIN.jsonl``, an append-only hash chain.  At
``Pnn-END2`` it appends one entry: phase id, hash of the previous entry, hash
of the phase report (merge field excluded), hash of the phase ledger,
directive hash, hash of STATE.json, and the merge commit hash of the previous
phase.  The entry hash uses the domain tag ``ctc/build/v1``.

``gate chain verify`` recomputes the chain offline; Entry Verification runs it
and any break is a STOP.  The chain is protected like the state file.

Spec: Part 6 §6.17, P00-T12.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ChainError",
    "ChainEntry",
    "CHAIN_ENTRY_FIELDS",
    "DOMAIN_TAG",
    "compute_entry_hash",
    "append_chain_entry",
    "read_chain",
    "verify_chain",
    "main",
]


class ChainError(Exception):
    """A chain read/write/verify error."""


# Domain tag for the entry hash (Part 6 §6.17).
DOMAIN_TAG = "ctc/build/v1"

# Fields that make up a chain entry (entry_hash is derived, not user-set).
CHAIN_ENTRY_FIELDS: tuple[str, ...] = (
    "phase",
    "prev_hash",
    "report_hash",
    "ledger_hash",
    "directive_hash",
    "state_hash",
    "prev_merge_hash",
)


@dataclass
class ChainEntry:
    """One entry in the build chain."""

    phase: str = ""
    prev_hash: str = ""
    report_hash: str = ""
    ledger_hash: str = ""
    directive_hash: str = ""
    state_hash: str = ""
    prev_merge_hash: str = ""
    entry_hash: str = ""


def compute_entry_hash(entry: dict[str, object]) -> str:
    """SHA-256 of *entry*'s fields (excluding ``entry_hash``) with the domain tag.

    The fields are serialized as sorted-key JSON and prefixed with
    ``ctc/build/v1:``.
    """
    fields = {k: v for k, v in entry.items() if k != "entry_hash"}
    payload = f"{DOMAIN_TAG}:{json.dumps(fields, sort_keys=True, ensure_ascii=False)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_chain_entry(path: Path, entry: dict[str, object]) -> None:
    """Compute ``entry_hash`` and append one JSON line to *path*.

    The ``entry_hash`` is always recomputed so the file is never written with a
    stale or handwritten hash.  The ``prev_hash`` should be set by the caller to
    the previous entry's ``entry_hash`` (empty string for the first entry).
    """
    entry["entry_hash"] = compute_entry_hash(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def read_chain(path: Path) -> list[dict[str, object]]:
    """Read all entries from *path* (one JSON object per line).

    Raises :class:`ChainError` if the file is missing or a line is not valid
    JSON.  An empty file returns an empty list (valid chain).
    """
    if not path.is_file():
        raise ChainError(f"chain file not found: {path}")
    entries: list[dict[str, object]] = []
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return entries
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            raw: object = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ChainError(f"chain file {path} line {i}: invalid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ChainError(f"chain file {path} line {i}: not a JSON object")
        entries.append(raw)
    return entries


def verify_chain(path: Path) -> list[str]:
    """Recompute the chain offline and return violations (empty = valid).

    Detects:
      - altered entry (entry_hash mismatch — a field was changed)
      - deleted entry (prev_hash points to a non-existent entry)
      - reordered entry (prev_hash doesn't match the previous entry's hash)
      - re-linked entry (prev_hash was changed to a wrong value)

    An empty chain file is valid (no entries to verify).
    """
    entries = read_chain(path)
    violations: list[str] = []
    prev_entry_hash = ""
    for i, entry in enumerate(entries):
        entry_num = i + 1
        stored_hash = str(entry.get("entry_hash", ""))
        expected_hash = compute_entry_hash(entry)
        if stored_hash != expected_hash:
            violations.append(
                f"entry {entry_num}: entry_hash mismatch "
                f"(stored {stored_hash[:12]} != expected {expected_hash[:12]}): "
                f"altered entry"
            )
        prev_stored = str(entry.get("prev_hash", ""))
        if prev_stored != prev_entry_hash:
            violations.append(
                f"entry {entry_num}: prev_hash mismatch "
                f"(expected {prev_entry_hash[:12]}, got {prev_stored[:12]}): "
                f"deleted, reordered or re-linked entry"
            )
        prev_entry_hash = expected_hash
    return violations


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Resolve the repository root from this module's location."""
    return Path(__file__).resolve().parents[3]


def main() -> int:
    """CLI entry: ``gate chain verify``.

    Reads ``CHAIN.jsonl``, runs :func:`verify_chain`, exits 0 if valid, 1 if
    violations, 2 if misconfiguration.
    """
    # Prefer cwd (selftest fixtures); fall back to repo root.
    cwd_chain = Path.cwd() / "CHAIN.jsonl"
    if cwd_chain.is_file():
        chain_path = cwd_chain
    else:
        chain_path = _repo_root() / "docs" / "state" / "CHAIN.jsonl"

    if not chain_path.is_file():
        print("chain: CHAIN.jsonl not found", file=sys.stderr)
        return 2

    try:
        violations = verify_chain(chain_path)
    except ChainError as exc:
        print(f"chain: {exc}", file=sys.stderr)
        return 2

    if violations:
        for v in violations:
            print(f"chain: {v}", file=sys.stderr)
        return 1

    print("chain: verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
