"""Tests for the coverage baseline ratchet (P00-T10).

Every test carries a header (id, title, purpose, level, requirement, input,
expected result, risk, capability) per Part 4 §4.5.

These tests exercise the pure baseline functions — ``load_baselines``,
``save_baselines``, ``check_baseline_decrease`` and ``update_baselines`` —
against temporary files.  They prove that the ratchet is monotonic: a measured
value below the recorded floor is rejected (never written) and reported as a
decrease, while a value at or above the floor is kept.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.gate.phase.baselines import (
    BaselineError,
    check_baseline_decrease,
    load_baselines,
    save_baselines,
    update_baselines,
)

# ---------------------------------------------------------------------------
# T-BASELINE-0001 — Empty baselines are seeded with the measured floor
# ---------------------------------------------------------------------------
# id: T-BASELINE-0001
# title: Empty baselines are seeded with the measured floor
# purpose: Verify that updating an empty baselines file writes the measured
#          coverage values as the first floor.
# level: fast
# requirement: P00-T10, Part 1 §8.2
# input: an empty baselines.json and a measured coverage dict
# expected: update_baselines writes the measured values; no decreases
# risk: the first measured floor is not recorded
# capability: phase-machinery


@pytest.mark.fast
def test_update_baselines_seeds_empty(tmp_path: Path) -> None:
    """An empty baselines file is seeded with the measured values."""
    path = tmp_path / "baselines.json"
    measured = {"tools/gate": {"branch_coverage": 0.42, "line_coverage": 0.55}}
    updated, decreases = update_baselines(path, measured)
    assert updated == measured
    assert decreases == []
    save_baselines(path, updated)
    assert load_baselines(path) == measured


# ---------------------------------------------------------------------------
# T-BASELINE-0002 — A higher measured value ratchets the floor up
# ---------------------------------------------------------------------------
# id: T-BASELINE-0002
# title: A higher measured value ratchets the floor up
# purpose: Verify that a measured value above the baseline is written.
# level: fast
# requirement: P00-T10, Part 1 §8.2
# input: a baseline of 0.50 and a measured value of 0.80
# expected: update_baselines writes 0.80; no decreases
# risk: an improving coverage value is not recorded
# capability: phase-machinery


@pytest.mark.fast
def test_update_baselines_ratchets_up(tmp_path: Path) -> None:
    """A measured value above the baseline is written (ratchet only rises)."""
    path = tmp_path / "baselines.json"
    save_baselines(path, {"tools/gate": {"branch_coverage": 0.50, "line_coverage": 0.50}})
    measured = {"tools/gate": {"branch_coverage": 0.80, "line_coverage": 0.75}}
    updated, decreases = update_baselines(path, measured)
    assert updated == measured
    assert decreases == []


# ---------------------------------------------------------------------------
# T-BASELINE-0003 — A lowered measured value is rejected (ratchet never lowers)
# ---------------------------------------------------------------------------
# id: T-BASELINE-0003
# title: A lowered measured value is rejected and the floor is kept
# purpose: Verify that a measured value below the baseline is NOT written — the
#          ratchet keeps the higher floor and reports the decrease.  This is
#          the T-GATE-0030 acceptance: a lowered value is rejected.
# level: fast
# requirement: P00-T10, Part 1 §8.2
# input: a baseline of 0.90 and a measured value of 0.70
# expected: update_baselines keeps 0.90 and reports a decrease; the file on
#           disk still holds 0.90
# risk: a coverage regression lowers the recorded floor
# capability: phase-machinery


@pytest.mark.fast
def test_update_baselines_rejects_decrease(tmp_path: Path) -> None:
    """A measured value below the baseline is rejected; the floor is kept."""
    path = tmp_path / "baselines.json"
    floor = {"tools/gate": {"branch_coverage": 0.90, "line_coverage": 0.90}}
    save_baselines(path, floor)
    measured = {"tools/gate": {"branch_coverage": 0.70, "line_coverage": 0.80}}
    updated, decreases = update_baselines(path, measured)
    # the ratchet never lowers — the existing floor is kept
    assert updated == floor
    assert len(decreases) == 2
    assert any("0.7" in d and "0.9" in d for d in decreases)
    assert any("0.8" in d and "0.9" in d for d in decreases)
    # saving the ratcheted result leaves the floor untouched on disk
    save_baselines(path, updated)
    assert load_baselines(path) == floor


# ---------------------------------------------------------------------------
# T-BASELINE-0004 — A partial decrease keeps the improved key, rejects the other
# ---------------------------------------------------------------------------
# id: T-BASELINE-0004
# title: Mixed measured values keep the improved key and reject the decreased one
# purpose: Verify that when one key improves and another decreases, the
#          improved key is written and the decreased key keeps its floor.
# level: fast
# requirement: P00-T10, Part 1 §8.2
# input: baseline branch=0.80 line=0.80, measured branch=0.90 line=0.70
# expected: written branch=0.90 line=0.80; one decrease reported for line
# risk: a per-key decrease is silently accepted
# capability: phase-machinery


@pytest.mark.fast
def test_update_baselines_mixed_up_and_down(tmp_path: Path) -> None:
    """An improved key is written while a decreased key keeps its floor."""
    path = tmp_path / "baselines.json"
    save_baselines(
        path,
        {"tools/gate": {"branch_coverage": 0.80, "line_coverage": 0.80}},
    )
    measured = {"tools/gate": {"branch_coverage": 0.90, "line_coverage": 0.70}}
    updated, decreases = update_baselines(path, measured)
    assert updated == {"tools/gate": {"branch_coverage": 0.90, "line_coverage": 0.80}}
    assert len(decreases) == 1
    assert "0.7" in decreases[0] and "0.8" in decreases[0]


# ---------------------------------------------------------------------------
# T-BASELINE-0005 — check_baseline_decrease flags a lowered value
# ---------------------------------------------------------------------------
# id: T-BASELINE-0005
# title: check_baseline_decrease flags a lowered value
# purpose: Verify that the check helper reports a decrease when measured is
#          below the baseline and reports nothing when at or above.
# level: fast
# requirement: P00-T10, Part 1 §8.2
# input: baseline 0.90, measured 0.80 (decrease) then 0.95 (no decrease)
# expected: a non-empty list for the decrease; an empty list when at or above
# risk: a coverage regression is not detected by the check
# capability: phase-machinery


@pytest.mark.fast
def test_check_baseline_decrease_flags_and_clears() -> None:
    """check_baseline_decrease reports a decrease and clears at or above."""
    baselines = {"tools/gate": {"branch_coverage": 0.90, "line_coverage": 0.90}}
    below = {"tools/gate": {"branch_coverage": 0.80, "line_coverage": 0.85}}
    assert check_baseline_decrease(baselines, below)
    at_or_above = {"tools/gate": {"branch_coverage": 0.90, "line_coverage": 1.00}}
    assert check_baseline_decrease(baselines, at_or_above) == []


# ---------------------------------------------------------------------------
# T-BASELINE-0006 — baselines.json validates against its schema
# ---------------------------------------------------------------------------
# id: T-BASELINE-0006
# title: baselines.json validates against its schema
# purpose: Verify that a seeded baselines.json loads cleanly (schema-valid) and
#          that a malformed file is rejected.
# level: fast
# requirement: P00-T10, Part 1 §8.2
# input: a well-formed baselines.json and a malformed one (non-number value)
# expected: load_baselines returns the values for the well-formed file and
#           raises BaselineError for the malformed one
# risk: an invalid baselines file is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_baselines_schema_valid_and_invalid(tmp_path: Path) -> None:
    """A schema-valid baselines.json loads; a malformed one is rejected."""
    path = tmp_path / "baselines.json"
    save_baselines(
        path,
        {"tools/gate": {"branch_coverage": 0.8765, "line_coverage": 0.9123}},
    )
    loaded = load_baselines(path)
    assert loaded["tools/gate"]["line_coverage"] == 0.9123
    assert loaded["tools/gate"]["branch_coverage"] == 0.8765
    # malformed: a string where a number is expected
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"tools/gate": {"line_coverage": "not a number"}}),
        encoding="utf-8",
    )
    with pytest.raises(BaselineError):
        load_baselines(bad)


# ---------------------------------------------------------------------------
# T-BASELINE-0007 — A missing measured component reports a decrease
# ---------------------------------------------------------------------------
# id: T-BASELINE-0007
# title: A missing measured component reports a decrease
# purpose: Verify that a component present in the baseline but absent from the
#          measured dict is reported as a decrease (missing from measured).
# level: fast
# requirement: P00-T10, Part 1 §8.2
# input: baseline for tools/gate, measured dict without tools/gate
# expected: check_baseline_decrease reports the missing component
# risk: a dropped component silently passes the check
# capability: phase-machinery


@pytest.mark.fast
def test_check_baseline_decrease_missing_component() -> None:
    """A component in the baseline but missing from measured is a decrease."""
    baselines = {"tools/gate": {"branch_coverage": 0.90, "line_coverage": 0.90}}
    measured: dict[str, dict[str, float]] = {}
    decreases = check_baseline_decrease(baselines, measured)
    assert decreases
    assert any("missing from measured" in d for d in decreases)
