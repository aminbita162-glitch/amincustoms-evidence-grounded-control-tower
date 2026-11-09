"""Tests for the build chain and cost telemetry (P00-T12).

Every test carries a header (id, title, purpose, level, requirement, input,
expected result, risk, capability) per Part 4 §4.5.

Tests T-PHASE-0031 and T-PHASE-0032 cover the build chain of Part 6 §6.17:
a known-answer vector for the entry hash, and verification detecting
altered, deleted, reordered and re-linked entries.  Tests T-PHASE-0069
through T-PHASE-0072 cover the cost telemetry of Part 6 §6.18: the
overhead/task split, overhead limits, total-only enforcement, and
part-limit provenance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.gate.phase.chain import (
    DOMAIN_TAG,
    ChainEntry,
    append_chain_entry,
    compute_entry_hash,
    read_chain,
    verify_chain,
)
from tools.gate.phase.telemetry import (
    TELEMETRY_LABEL,
    TelemetryError,
    check_overhead_limits,
    load_telemetry,
    save_telemetry,
    validate_telemetry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    phase: str = "P00",
    prev_hash: str = "",
    report_hash: str = "a" * 64,
    ledger_hash: str = "b" * 64,
    directive_hash: str = "c" * 64,
    state_hash: str = "d" * 64,
    prev_merge_hash: str = "",
) -> dict[str, object]:
    """Create a chain entry dict without entry_hash."""
    return {
        "phase": phase,
        "prev_hash": prev_hash,
        "report_hash": report_hash,
        "ledger_hash": ledger_hash,
        "directive_hash": directive_hash,
        "state_hash": state_hash,
        "prev_merge_hash": prev_merge_hash,
    }


def _write_chain(path: Path, entries: list[dict[str, object]]) -> None:
    """Write entries as JSONL, computing entry_hash for each."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    prev_hash = ""
    for entry in entries:
        entry["prev_hash"] = prev_hash
        entry["entry_hash"] = compute_entry_hash(entry)
        lines.append(json.dumps(entry, sort_keys=True))
        prev_hash = str(entry["entry_hash"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_telemetry(
    tool_calls_overhead: int = 10,
    tool_calls_task: int = 50,
    tokens_overhead: int = 100,
    tokens_task: int = 500,
    retries: dict[str, int] | None = None,
    stop_count: int = 0,
    label: str = TELEMETRY_LABEL,
) -> dict[str, object]:
    return {
        "tool_calls_overhead": tool_calls_overhead,
        "tool_calls_task": tool_calls_task,
        "tokens_overhead": tokens_overhead,
        "tokens_task": tokens_task,
        "retries": retries if retries is not None else {},
        "stop_count": stop_count,
        "label": label,
    }


# ---------------------------------------------------------------------------
# T-PHASE-0031 — Known-answer vector for the entry hash
# ---------------------------------------------------------------------------

# id: T-PHASE-0031
# title: Known-answer vector for the entry hash
# purpose: Verify that compute_entry_hash is deterministic and produces a
#          reproducible SHA-256 using the domain tag ctc/build/v1.
# level: fast
# requirement: P00-T12, Part 6 §6.17
# input: a known entry dict without entry_hash
# expected: the hash is deterministic and matches a recomputed value
# risk: the entry hash is non-deterministic or uses the wrong domain tag
# capability: phase-machinery


@pytest.mark.fast
def test_entry_hash_known_answer() -> None:
    """compute_entry_hash is deterministic and uses the ctc/build/v1 tag."""
    entry = _make_entry()
    hash1 = compute_entry_hash(entry)
    hash2 = compute_entry_hash(entry)
    assert hash1 == hash2
    assert len(hash1) == 64
    # Recompute manually to confirm the domain tag is included.
    import hashlib

    fields = {k: v for k, v in entry.items() if k != "entry_hash"}
    payload = f"{DOMAIN_TAG}:{json.dumps(fields, sort_keys=True, ensure_ascii=False)}"
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert hash1 == expected
    # The entry_hash field must not affect the hash.
    entry_with_hash = dict(entry)
    entry_with_hash["entry_hash"] = "ignored"
    assert compute_entry_hash(entry_with_hash) == hash1


# ---------------------------------------------------------------------------
# T-PHASE-0032 — Verification detects tampered chains and empty is valid
# ---------------------------------------------------------------------------

# id: T-PHASE-0032
# title: Chain verification detects altered, deleted, reordered, re-linked
# purpose: Verify that verify_chain detects an altered entry, a deleted
#          entry, a reordered entry, and a re-linked entry.  Also verify
#          that an empty chain is valid and that telemetry validates with
#          the SELF-REPORTED label.
# level: fast
# requirement: P00-T12, Part 6 §6.17, §6.18
# input: a valid 3-entry chain, tampered copies, and an empty chain
# expected: verify_chain returns non-empty for tampered, empty for valid/empty
# risk: a tampered chain is not detected or a valid chain is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_verify_clean_chain(tmp_path: Path) -> None:
    """A valid chain produces no violations."""
    chain_path = tmp_path / "CHAIN.jsonl"
    entries = [_make_entry(phase="P00"), _make_entry(phase="P01"), _make_entry(phase="P02")]
    _write_chain(chain_path, entries)
    assert verify_chain(chain_path) == []


@pytest.mark.fast
def test_verify_empty_chain(tmp_path: Path) -> None:
    """An empty chain file is valid."""
    chain_path = tmp_path / "CHAIN.jsonl"
    chain_path.write_text("", encoding="utf-8")
    assert verify_chain(chain_path) == []


@pytest.mark.fast
def test_verify_altered_entry(tmp_path: Path) -> None:
    """An altered entry (changed field) is detected."""
    chain_path = tmp_path / "CHAIN.jsonl"
    entries = [_make_entry(phase="P00"), _make_entry(phase="P01"), _make_entry(phase="P02")]
    _write_chain(chain_path, entries)
    # Alter entry 2's report_hash without recomputing entry_hash.
    lines = chain_path.read_text(encoding="utf-8").splitlines()
    entry2 = json.loads(lines[1])
    entry2["report_hash"] = "z" * 64
    lines[1] = json.dumps(entry2, sort_keys=True)
    chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    violations = verify_chain(chain_path)
    assert violations
    assert any("entry_hash mismatch" in v for v in violations)


@pytest.mark.fast
def test_verify_deleted_entry(tmp_path: Path) -> None:
    """A deleted middle entry is detected (prev_hash mismatch)."""
    chain_path = tmp_path / "CHAIN.jsonl"
    entries = [_make_entry(phase="P00"), _make_entry(phase="P01"), _make_entry(phase="P02")]
    _write_chain(chain_path, entries)
    # Delete entry 2 (middle).  Entry 3's prev_hash still points to
    # entry 2's hash, which no longer matches entry 1's entry_hash.
    lines = chain_path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    violations = verify_chain(chain_path)
    assert violations
    assert any("prev_hash mismatch" in v for v in violations)


@pytest.mark.fast
def test_verify_reordered_entries(tmp_path: Path) -> None:
    """Reordered entries are detected (prev_hash mismatch)."""
    chain_path = tmp_path / "CHAIN.jsonl"
    entries = [_make_entry(phase="P00"), _make_entry(phase="P01"), _make_entry(phase="P02")]
    _write_chain(chain_path, entries)
    # Swap entries 1 and 2 (lines 0 and 1).
    lines = chain_path.read_text(encoding="utf-8").splitlines()
    lines[0], lines[1] = lines[1], lines[0]
    chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    violations = verify_chain(chain_path)
    assert violations
    assert any("prev_hash mismatch" in v for v in violations)


@pytest.mark.fast
def test_verify_relinked_entry(tmp_path: Path) -> None:
    """A re-linked entry (prev_hash changed to a wrong value) is detected."""
    chain_path = tmp_path / "CHAIN.jsonl"
    entries = [_make_entry(phase="P00"), _make_entry(phase="P01"), _make_entry(phase="P02")]
    _write_chain(chain_path, entries)
    # Change entry 3's prev_hash to a wrong value.
    lines = chain_path.read_text(encoding="utf-8").splitlines()
    entry3 = json.loads(lines[2])
    entry3["prev_hash"] = "0" * 64
    lines[2] = json.dumps(entry3, sort_keys=True)
    chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    violations = verify_chain(chain_path)
    assert violations
    assert any("prev_hash mismatch" in v for v in violations)


@pytest.mark.fast
def test_append_chain_entry_computes_hash(tmp_path: Path) -> None:
    """append_chain_entry computes entry_hash and appends a valid line."""
    chain_path = tmp_path / "CHAIN.jsonl"
    entry = _make_entry(phase="P00")
    append_chain_entry(chain_path, entry)
    entries = read_chain(chain_path)
    assert len(entries) == 1
    assert entries[0]["entry_hash"] == compute_entry_hash(entries[0])
    assert verify_chain(chain_path) == []


@pytest.mark.fast
def test_telemetry_validates_with_label() -> None:
    """Telemetry with the SELF-REPORTED label and all fields passes."""
    data = _make_telemetry()
    assert validate_telemetry(data) == []


@pytest.mark.fast
def test_telemetry_without_label_fails() -> None:
    """Telemetry without the SELF-REPORTED label fails validation."""
    data = _make_telemetry(label="")
    errors = validate_telemetry(data)
    assert errors
    assert any("label" in e for e in errors)


# ---------------------------------------------------------------------------
# T-PHASE-0069 — Telemetry without overhead/task split fails
# ---------------------------------------------------------------------------

# id: T-PHASE-0069
# title: Telemetry without overhead/task split fails
# purpose: Verify that a phase report or telemetry that does not split
#          overhead from task work (missing tool_calls_overhead or
#          tool_calls_task) fails the telemetry check.
# level: fast
# requirement: P00-T12, Part 6 §6.18
# input: a telemetry dict missing the overhead/task split
# expected: validate_telemetry returns a non-empty error list
# risk: overhead and task work are not separated, hiding overhead costs
# capability: phase-machinery


@pytest.mark.fast
def test_telemetry_missing_overhead_split_fails() -> None:
    """Telemetry missing the overhead/task split fails validation."""
    data: dict[str, object] = {
        "label": TELEMETRY_LABEL,
        "stop_count": 0,
        "retries": {},
    }
    errors = validate_telemetry(data)
    assert errors
    assert any("tool_calls_overhead" in e for e in errors)
    assert any("tool_calls_task" in e for e in errors)


@pytest.mark.fast
def test_telemetry_missing_tokens_split_fails() -> None:
    """Telemetry missing the tokens overhead/task split fails."""
    data: dict[str, object] = {
        "label": TELEMETRY_LABEL,
        "tool_calls_overhead": 10,
        "tool_calls_task": 50,
        "stop_count": 0,
        "retries": {},
    }
    errors = validate_telemetry(data)
    assert errors
    assert any("tokens_overhead" in e for e in errors)


# ---------------------------------------------------------------------------
# T-PHASE-0070 — Overhead exceeding its limit stops naming the overhead part
# ---------------------------------------------------------------------------

# id: T-PHASE-0070
# title: Overhead exceeding its limit triggers a violation naming overhead
# purpose: Verify that a fixture phase whose overhead exceeds its limit
#          triggers a violation and the violation names the overhead part.
# level: fast
# requirement: P00-T12, Part 6 §6.18
# input: telemetry with overhead=100 and limits overhead=50
# expected: check_overhead_limits returns a violation mentioning overhead
# risk: overhead exceeding its limit is not detected or not named
# capability: phase-machinery


@pytest.mark.fast
def test_overhead_exceeds_limit_stops() -> None:
    """Overhead exceeding its limit is a violation naming the overhead part."""
    data = _make_telemetry(tool_calls_overhead=100, tool_calls_task=50)
    limits: dict[str, int] = {"overhead": 50}
    violations = check_overhead_limits(data, limits)
    assert violations
    assert any("overhead" in v for v in violations)


@pytest.mark.fast
def test_task_exceeds_limit_stops() -> None:
    """Task exceeding its limit is a violation naming the task part."""
    data = _make_telemetry(tool_calls_overhead=10, tool_calls_task=200)
    limits: dict[str, int] = {"task": 100}
    violations = check_overhead_limits(data, limits)
    assert violations
    assert any("task" in v for v in violations)


@pytest.mark.fast
def test_overhead_within_limit_passes() -> None:
    """Overhead within its limit passes."""
    data = _make_telemetry(tool_calls_overhead=40, tool_calls_task=50)
    limits: dict[str, int] = {"overhead": 50, "task": 100}
    assert check_overhead_limits(data, limits) == []


# ---------------------------------------------------------------------------
# T-PHASE-0071 — No part limits (limits=None) only enforces the total
# ---------------------------------------------------------------------------

# id: T-PHASE-0071
# title: No part limits — only total enforced
# purpose: Verify that with no part limits set (limits=None), only the total
#          is enforced: a total within limit passes, exceeding total fails.
# level: fast
# requirement: P00-T12, Part 6 §6.18
# input: telemetry with a total_limit, overhead+task within and exceeding it
# expected: within passes, exceeding fails; parts are not checked
# risk: part limits are enforced when they should not be, or total is not
# capability: phase-machinery


@pytest.mark.fast
def test_no_part_limits_total_within_passes() -> None:
    """With limits=None, a total within limit passes."""
    data = _make_telemetry(tool_calls_overhead=50, tool_calls_task=50)
    data["total_limit"] = 200
    assert check_overhead_limits(data, None) == []


@pytest.mark.fast
def test_no_part_limits_total_exceeding_fails() -> None:
    """With limits=None, a total exceeding the limit fails."""
    data = _make_telemetry(tool_calls_overhead=150, tool_calls_task=100)
    data["total_limit"] = 200
    violations = check_overhead_limits(data, None)
    assert violations
    assert any("total exceeds limit" in v for v in violations)


@pytest.mark.fast
def test_no_part_limits_no_total_limit_passes() -> None:
    """With limits=None and no total_limit, everything passes."""
    data = _make_telemetry(tool_calls_overhead=10000, tool_calls_task=10000)
    assert check_overhead_limits(data, None) == []


# ---------------------------------------------------------------------------
# T-PHASE-0072 — Part limit in telemetry but not in decision record fails
# ---------------------------------------------------------------------------

# id: T-PHASE-0072
# title: Part limit in telemetry but not in decision record fails
# purpose: Verify that a part limit present in the telemetry but not in the
#          decision record (limits dict) fails the check.
# level: fast
# requirement: P00-T12, Part 6 §6.18
# input: telemetry with overhead_limit, limits dict without overhead
# expected: check_overhead_limits returns a violation about the limit
# risk: a limit is changed outside the decision record and not detected
# capability: phase-machinery


@pytest.mark.fast
def test_part_limit_not_in_decision_record_fails() -> None:
    """A limit field in telemetry but not in the decision record fails."""
    data = _make_telemetry(tool_calls_overhead=10, tool_calls_task=50)
    data["overhead_limit"] = 100
    limits: dict[str, int] = {"task": 100}
    violations = check_overhead_limits(data, limits)
    assert violations
    assert any("overhead" in v and "decision record" in v for v in violations)


@pytest.mark.fast
def test_part_limit_in_decision_record_passes() -> None:
    """A limit field in telemetry that IS in the decision record passes."""
    data = _make_telemetry(tool_calls_overhead=10, tool_calls_task=50)
    data["overhead_limit"] = 100
    limits: dict[str, int] = {"overhead": 100, "task": 100}
    violations = check_overhead_limits(data, limits)
    assert not any("decision record" in v for v in violations)


# ---------------------------------------------------------------------------
# Telemetry save/load round trip
# ---------------------------------------------------------------------------

# id: T-PHASE-0073
# title: Telemetry save/load round trip
# purpose: Verify that save_telemetry then load_telemetry round-trips
#          correctly and validates the label.
# level: fast
# requirement: P00-T12, Part 6 §6.18
# input: a valid telemetry dict saved and loaded
# expected: loaded dict matches the saved one
# risk: telemetry is corrupted on save/load
# capability: phase-machinery


@pytest.mark.fast
def test_telemetry_save_load_round_trip(tmp_path: Path) -> None:
    """save_telemetry then load_telemetry round-trips correctly."""
    data = _make_telemetry(retries={"P00-T01": 2}, stop_count=1)
    path = tmp_path / "telemetry.json"
    save_telemetry(path, data)
    loaded = load_telemetry(path)
    assert loaded["label"] == TELEMETRY_LABEL
    assert loaded["tool_calls_overhead"] == 10
    assert loaded["stop_count"] == 1


@pytest.mark.fast
def test_telemetry_load_invalid_label_fails(tmp_path: Path) -> None:
    """load_telemetry raises TelemetryError for an invalid label."""
    path = tmp_path / "telemetry.json"
    path.write_text('{"label": "WRONG"}\n', encoding="utf-8")
    with pytest.raises(TelemetryError, match="label"):
        load_telemetry(path)


@pytest.mark.fast
def test_chain_entry_dataclass_fields() -> None:
    """ChainEntry has all required fields."""
    entry = ChainEntry()
    assert entry.phase == ""
    assert entry.prev_hash == ""
    assert entry.entry_hash == ""
    assert DOMAIN_TAG == "ctc/build/v1"
