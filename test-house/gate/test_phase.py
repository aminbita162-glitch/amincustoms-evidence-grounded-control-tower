"""Tests for the Control Tower phase machinery (P00-T05).

Every test carries a header (id, title, purpose, level, requirement, input,
expected result, risk, capability) per Part 4 §4.5.

Tests T-PHASE-0001 through T-PHASE-0106 run against temporary git repositories
exercising entry/exit verification, state consistency, golden-commit, and
dependency checks.  Tests T-PHASE-0049 through T-PHASE-0052 cover self-review
validation.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.gate.phase.baselines import check_baseline_decrease
from tools.gate.phase.checks import (
    PHASE_REPORT_FIELDS,
    PhaseEntry,
    check_awaiting_merge_cleared,
    check_baseline_decrease_result,
    check_clean_tree,
    check_dependencies,
    check_directive_hash,
    check_done_lines,
    check_golden_commit,
    check_merge_proof,
    check_previous_branch_deleted,
    check_previous_merge_hash,
    check_state_consistency,
    load_phases,
    validate_report_fields,
)
from tools.gate.phase.selfreview import (
    CATEGORIES,
    MAX_FINDINGS,
    MAX_WORDS,
    validate_selfreview,
)
from tools.gate.phase.state import State, StateError, compute_state_hash, load_state, save_state
from tools.gate.phase.stopreport import validate_stopreport

REPO_ROOT = Path(__file__).resolve().parents[2]
DIRECTIVE_HASH = "7c594b12933a29dcf7f22de5887d96b1b6db767438918b5cf95901b187036c4b"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return env


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=_git_env(),
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with an initial commit on main."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "--initial-branch=main"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    _git(["config", "commit.gpgsign", "false"], repo)
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "init"], repo)
    return repo


def _write_ledger(repo: Path, phase: str, tasks: list[str]) -> None:
    """Write a ledger file with DONE lines for the given tasks."""
    ledger = repo / "docs" / "ledger" / f"{phase}.md"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {phase} Ledger"]
    for task in tasks:
        lines.append(f"{task} DONE")
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_task_commit(repo: Path, task_id: str, msg: str = "") -> str:
    """Create a commit for a task (adds a file and commits with task id)."""
    _git(["add", "-A"], repo)
    if not msg:
        msg = f"feat(scope): do something [{task_id}]"
    _git(["commit", "-m", msg, "--allow-empty"], repo)
    return _git(["rev-parse", "HEAD"], repo).stdout.strip()


def _make_merge(repo: Path, branch: str) -> str:
    """Create a branch, add a commit, merge it back with a merge commit."""
    _git(["checkout", "-b", branch], repo)
    target = repo / f"{branch}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", f"feat: work on {branch}"], repo)
    _git(["checkout", "main"], repo)
    _git(["merge", "--no-ff", branch, "-m", f"Merge branch '{branch}'"], repo)
    return _git(["rev-parse", "HEAD"], repo).stdout.strip()


def _make_squash_merge(repo: Path, branch: str) -> str:
    """Create a squash merge (single-parent commit)."""
    _git(["checkout", "-b", branch], repo)
    target = repo / f"{branch}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", f"feat: work on {branch}"], repo)
    _git(["checkout", "main"], repo)
    _git(["merge", "--squash", branch], repo)
    _git(["commit", "-m", f"squash merge {branch}"], repo)
    return _git(["rev-parse", "HEAD"], repo).stdout.strip()


def _make_rebase_merge(repo: Path, branch: str) -> str:
    """Create a rebase merge (no merge commit)."""
    _git(["checkout", "-b", branch], repo)
    target = repo / f"{branch}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", f"feat: work on {branch}"], repo)
    _git(["checkout", "main"], repo)
    _git(["rebase", branch], repo)
    return _git(["rev-parse", "HEAD"], repo).stdout.strip()


def _default_state(directive_hash: str = DIRECTIVE_HASH) -> State:
    return State(
        last_completed_phase="P00",
        previous_merge_hash=None,
        awaiting_merge_phase=None,
        directive_hash=directive_hash,
        capability_status_map={},
        open_stop_items=[],
        label_counts={},
    )


# ---------------------------------------------------------------------------
# T-PHASE-0001 — Missing DONE line fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0001
# title: Missing DONE line fails exit check
# purpose: Verify that a task without a DONE line in the ledger fails the
#          done-lines exit check.
# level: fast
# requirement: P00-T05, Part 1 §9.1
# input: a temp repo with a ledger missing one task's DONE line
# expected: check_done_lines returns passed=False
# risk: a task is counted complete without its DONE line
# capability: phase-machinery


@pytest.mark.fast
def test_missing_done_line_fails(tmp_path: Path) -> None:
    """A missing DONE line makes check_done_lines fail."""
    repo = _init_repo(tmp_path)
    _write_ledger(repo, "P01", ["P01-T01"])
    result = check_done_lines(repo, "P01", ["P01-T01", "P01-T02"])
    assert not result.passed
    assert "P01-T02" in result.evidence


# ---------------------------------------------------------------------------
# T-PHASE-0002 — Task commit without DONE fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0002
# title: Task commit without DONE line fails
# purpose: Verify that a task with a commit but no DONE line is detected.
# level: fast
# requirement: P00-T05, Part 1 §9.1
# input: a temp repo with a task commit but no DONE line for that task
# expected: check_done_lines returns passed=False for the missing task
# risk: a task commit is counted without the corresponding DONE line
# capability: phase-machinery


@pytest.mark.fast
def test_task_commit_without_done_fails(tmp_path: Path) -> None:
    """A task with a commit but no DONE line fails the done-lines check."""
    repo = _init_repo(tmp_path)
    _make_task_commit(repo, "P01-T01")
    _write_ledger(repo, "P01", [])  # no DONE lines at all
    result = check_done_lines(repo, "P01", ["P01-T01"])
    assert not result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0003 — Squash merge fails (only one parent)
# ---------------------------------------------------------------------------
# id: T-PHASE-0003
# title: Squash merge fails merge proof check
# purpose: Verify that a squash merge (single-parent commit) fails the
#          merge-proof check because the merge commit must have two parents.
# level: fast
# requirement: P00-T05, Part 1 §8.2a
# input: a temp repo with a squash-merged branch
# expected: check_merge_proof returns passed=False
# risk: a squash merge is accepted, losing individual task commits
# capability: phase-machinery


@pytest.mark.fast
def test_squash_merge_fails(tmp_path: Path) -> None:
    """A squash merge (single parent) fails the merge-proof check."""
    repo = _init_repo(tmp_path)
    _make_squash_merge(repo, "phase/01-slug")
    result = check_merge_proof(repo)
    assert not result.passed
    assert "squash" in result.evidence.lower() or "1 parent" in result.evidence


# ---------------------------------------------------------------------------
# T-PHASE-0004 — Rebase merge fails (no merge commit)
# ---------------------------------------------------------------------------
# id: T-PHASE-0004
# title: Rebase merge fails merge proof check
# purpose: Verify that a rebase merge (no merge commit) fails the
#          merge-proof check.
# level: fast
# requirement: P00-T05, Part 1 §8.2a
# input: a temp repo with a rebased branch
# expected: check_merge_proof returns passed=False
# risk: a rebase merge is accepted, losing the merge-commit structure
# capability: phase-machinery


@pytest.mark.fast
def test_rebase_merge_fails(tmp_path: Path) -> None:
    """A rebase merge (no merge commit) fails the merge-proof check."""
    repo = _init_repo(tmp_path)
    _make_rebase_merge(repo, "phase/01-slug")
    result = check_merge_proof(repo)
    assert not result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0005 — Dirty tree fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0005
# title: Dirty tree fails clean-tree check
# purpose: Verify that uncommitted changes make the clean-tree check fail.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: a temp repo with an uncommitted file
# expected: check_clean_tree returns passed=False
# risk: a dirty tree is accepted at phase entry
# capability: phase-machinery


@pytest.mark.fast
def test_dirty_tree_fails(tmp_path: Path) -> None:
    """Uncommitted changes make check_clean_tree fail."""
    repo = _init_repo(tmp_path)
    (repo / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
    result = check_clean_tree(repo)
    assert not result.passed
    assert "dirty" in result.evidence.lower()


# ---------------------------------------------------------------------------
# T-PHASE-0006 — STATE mismatch fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0006
# title: STATE mismatch fails state consistency check
# purpose: Verify that a state whose last_completed_phase doesn't match the
#          ledger fails the state-consistency check.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: a state with last_completed_phase=P02 but ledger only has P00
# expected: check_state_consistency returns passed=False
# risk: a stale or wrong state is accepted at phase entry
# capability: phase-machinery


@pytest.mark.fast
def test_state_mismatch_fails(tmp_path: Path) -> None:
    """A state whose last_completed_phase doesn't match the ledger fails."""
    repo = _init_repo(tmp_path)
    _write_ledger(repo, "P00", ["P00-T01"])
    state = _default_state()
    state.last_completed_phase = "P02"  # wrong — ledger only has P00
    result = check_state_consistency(state, repo)
    assert not result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0007 — Wrong directive hash fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0007
# title: Wrong directive hash fails directive hash check
# purpose: Verify that a state with a wrong directive_hash fails the check.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: a state with a wrong directive_hash
# expected: check_directive_hash returns passed=False
# risk: a changed directive is not detected at phase entry
# capability: phase-machinery


@pytest.mark.fast
def test_wrong_directive_hash_fails(tmp_path: Path) -> None:
    """A wrong directive hash makes check_directive_hash fail."""
    repo = _init_repo(tmp_path)
    directive = repo / "directive.txt"
    directive.write_text("directive content\n", encoding="utf-8")
    state = _default_state(directive_hash="0" * 64)
    result = check_directive_hash(state, directive)
    assert not result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0008 — Previous branch not deleted fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0008
# title: Previous branch not deleted fails check
# purpose: Verify that a previous phase's branch that still exists fails the
#          branch-deleted check.
# level: fast
# requirement: P00-T05, Part 1 §8.2c
# input: a temp repo where the previous phase's branch still exists
# expected: check_previous_branch_deleted returns passed=False
# risk: a stale branch is left behind, polluting the branch namespace
# capability: phase-machinery


@pytest.mark.fast
def test_previous_branch_not_deleted_fails(tmp_path: Path) -> None:
    """A previous phase's branch that still exists fails the check."""
    repo = _init_repo(tmp_path)
    _git(["checkout", "-b", "phase/01-slug"], repo)
    _git(["checkout", "main"], repo)
    result = check_previous_branch_deleted(repo, "phase/01-slug")
    assert not result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0009 — Missing report field fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0009
# title: Missing report field fails validation
# purpose: Verify that a phase report missing a required field fails
#          validation.
# level: fast
# requirement: P00-T05, Part 1 §12.5
# input: a report dict missing one required field
# expected: validate_report_fields returns a non-empty error list
# risk: an incomplete report is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_missing_report_field_fails() -> None:
    """A report missing a required field fails validation."""
    report: dict[str, object] = {
        "entry_report": "x",
        "exit_report": "x",
        "commit_table": [],
        "self_review": "",
        "directive_hash": "abc",
        "budgets_used": {},
    }
    errors = validate_report_fields(report, PHASE_REPORT_FIELDS)
    assert errors
    assert any("label_counts" in e for e in errors)


# ---------------------------------------------------------------------------
# T-PHASE-0010 — Extra report field fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0010
# title: Extra report field fails validation
# purpose: Verify that a phase report with an extra field fails validation.
# level: fast
# requirement: P00-T05, Part 1 §12.5
# input: a report dict with an extra field
# expected: validate_report_fields returns a non-empty error list
# risk: an unexpected field silently enters the report
# capability: phase-machinery


@pytest.mark.fast
def test_extra_report_field_fails() -> None:
    """A report with an extra field fails validation."""
    report: dict[str, object] = {
        "entry_report": "x",
        "exit_report": "x",
        "commit_table": [],
        "self_review": "",
        "directive_hash": "abc",
        "budgets_used": {},
        "label_counts": {},
        "extra_field": "should not be here",
    }
    errors = validate_report_fields(report, PHASE_REPORT_FIELDS)
    assert errors
    assert any("extra_field" in e for e in errors)


# ---------------------------------------------------------------------------
# T-PHASE-0011 — Handwritten STATE edit fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0011
# title: Handwritten STATE edit fails (state_hash mismatch)
# purpose: Verify that a hand-edited STATE.json (whose state_hash doesn't match
#          the recomputed hash) is rejected by load_state.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: a STATE.json with a wrong state_hash
# expected: load_state raises StateError
# risk: a handwritten state edit bypasses the state machine
# capability: phase-machinery


@pytest.mark.fast
def test_handwritten_state_edit_fails(tmp_path: Path) -> None:
    """A hand-edited STATE.json (wrong state_hash) is rejected by load_state."""
    state = _default_state()
    state.state_hash = "0" * 64  # wrong hash
    path = tmp_path / "STATE.json"
    path.write_text(
        json.dumps(
            {
                "last_completed_phase": state.last_completed_phase,
                "previous_merge_hash": state.previous_merge_hash,
                "awaiting_merge_phase": state.awaiting_merge_phase,
                "directive_hash": state.directive_hash,
                "capability_status_map": state.capability_status_map,
                "open_stop_items": state.open_stop_items,
                "label_counts": state.label_counts,
                "state_hash": "0" * 64,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(StateError, match="state_hash mismatch"):
        load_state(path)


# ---------------------------------------------------------------------------
# T-PHASE-0012 — Baseline decrease fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0012
# title: Baseline decrease fails check
# purpose: Verify that a measured coverage below the baseline is detected.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: baselines with 0.90 line coverage, measured at 0.80
# expected: check_baseline_decrease returns a non-empty list
# risk: a coverage regression is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_baseline_decrease_fails() -> None:
    """A measured coverage below the baseline is detected."""
    baselines = {"tools/gate": {"branch_coverage": 0.85, "line_coverage": 0.90}}
    measured = {"tools/gate": {"branch_coverage": 0.80, "line_coverage": 0.80}}
    decreases = check_baseline_decrease(baselines, measured)
    assert decreases
    result = check_baseline_decrease_result(baselines, measured)
    assert not result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0101 — Commit that changes a golden path together with another path fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0101
# title: Mixed golden and non-golden commit fails
# purpose: Verify that a commit changing a golden file together with a
#          non-golden file fails the golden-commit check.
# level: fast
# requirement: P00-T05, Part 1 §4.8
# input: a commit changing both a golden file and a source file
# expected: check_golden_commit returns passed=False
# risk: a golden file change shares a commit with a source change
# capability: phase-machinery


@pytest.mark.fast
def test_golden_mixed_commit_fails(tmp_path: Path) -> None:
    """A commit mixing golden and non-golden files fails."""
    repo = _init_repo(tmp_path)
    (repo / "golden.txt").write_text("golden\n", encoding="utf-8")
    (repo / "src.py").write_text("x = 1\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "feat: mixed change"], repo)
    commit = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    result = check_golden_commit(repo, commit, ["golden.txt"])
    assert not result.passed
    assert "non-golden" in result.evidence.lower() or "together" in result.evidence.lower()


# ---------------------------------------------------------------------------
# T-PHASE-0102 — Golden commit without scope golden or without a reason fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0102
# title: Golden commit without proper scope or reason fails
# purpose: Verify that a commit changing only golden files but without the
#          'test(golden):' scope or a reason fails the golden-commit check.
# level: fast
# requirement: P00-T05, Part 1 §4.8
# input: a commit changing only golden files with a wrong commit message
# expected: check_golden_commit returns passed=False
# risk: a golden file change has the wrong commit format
# capability: phase-machinery


@pytest.mark.fast
def test_golden_commit_wrong_scope_fails(tmp_path: Path) -> None:
    """A golden commit without 'test(golden):' scope fails."""
    repo = _init_repo(tmp_path)
    (repo / "golden.txt").write_text("golden v2\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "feat: update golden file"], repo)
    commit = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    result = check_golden_commit(repo, commit, ["golden.txt"])
    assert not result.passed


@pytest.mark.fast
def test_golden_commit_no_reason_fails(tmp_path: Path) -> None:
    """A golden commit with 'test(golden):' but no reason fails."""
    repo = _init_repo(tmp_path)
    (repo / "golden.txt").write_text("golden v2\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "test(golden): "], repo)
    commit = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    result = check_golden_commit(repo, commit, ["golden.txt"])
    assert not result.passed


@pytest.mark.fast
def test_golden_commit_valid_passes(tmp_path: Path) -> None:
    """A properly formatted golden commit passes."""
    repo = _init_repo(tmp_path)
    (repo / "golden.txt").write_text("golden v2\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "test(golden): update expected output"], repo)
    commit = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    result = check_golden_commit(repo, commit, ["golden.txt"])
    assert result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0103 — STATE previous_merge_hash not the merge commit fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0103
# title: Wrong previous_merge_hash fails check
# purpose: Verify that a state whose previous_merge_hash doesn't match the
#          actual merge commit fails the check.
# level: fast
# requirement: P00-T05, Part 1 §8.3
# input: a state with a wrong previous_merge_hash
# expected: check_previous_merge_hash returns passed=False
# risk: a wrong merge hash is recorded, breaking the chain
# capability: phase-machinery


@pytest.mark.fast
def test_wrong_previous_merge_hash_fails(tmp_path: Path) -> None:
    """A previous_merge_hash that doesn't match the actual merge fails."""
    repo = _init_repo(tmp_path)
    _make_merge(repo, "phase/01-slug")
    state = _default_state()
    state.previous_merge_hash = "0" * 64
    result = check_previous_merge_hash(state, repo)
    assert not result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0104 — awaiting_merge not cleared after merge proven fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0104
# title: awaiting_merge not cleared fails
# purpose: Verify that a state with awaiting_merge_phase set after the merge
#          is proven fails the check.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: a state with awaiting_merge_phase set
# expected: check_awaiting_merge_cleared returns passed=False
# risk: a stale awaiting_merge value blocks the next phase
# capability: phase-machinery


@pytest.mark.fast
def test_awaiting_merge_not_cleared_fails() -> None:
    """An awaiting_merge_phase that is not None after merge fails."""
    state = _default_state()
    state.awaiting_merge_phase = "P01"
    result = check_awaiting_merge_cleared(state)
    assert not result.passed


@pytest.mark.fast
def test_awaiting_merge_cleared_passes() -> None:
    """An awaiting_merge_phase of None passes."""
    state = _default_state()
    state.awaiting_merge_phase = None
    result = check_awaiting_merge_cleared(state)
    assert result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0105 — Phase whose independent predecessor is PARKED enters
# ---------------------------------------------------------------------------
# id: T-PHASE-0105
# title: PARKED predecessor outside depends_on does not block entry
# purpose: Verify that a phase whose previous (but not depended-on) phase is
#          PARKED can still enter (8.2e).
# level: fast
# requirement: P00-T05, Part 1 §8.2d, §8.2e
# input: a phase P03 whose predecessor P02 is PARKED but P03 depends_on P01
# expected: check_dependencies returns passed=True
# risk: a PARKED phase outside depends_on wrongly blocks entry
# capability: phase-machinery


@pytest.mark.fast
def test_parked_predecessor_enters() -> None:
    """A PARKED phase outside depends_on does not block entry."""
    phases = {
        "P01": _phase_entry("P01", depends_on=["P00"]),
        "P02": _phase_entry("P02", depends_on=["P01"]),
        "P03": _phase_entry("P03", depends_on=["P01"]),
    }
    state = _default_state()
    state.last_completed_phase = "P01"
    parked = {"P02"}
    result = check_dependencies("P03", phases, state, parked_phases=parked)
    assert result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0106 — Phase whose dependency is PARKED or not merged stops naming it
# ---------------------------------------------------------------------------
# id: T-PHASE-0106
# title: PARKED dependency stops entry naming the phase
# purpose: Verify that a phase whose depends_on contains a PARKED phase is a
#          STOP that names the PARKed phase.
# level: fast
# requirement: P00-T05, Part 1 §8.2d
# input: a phase P03 whose depends_on includes a PARKED phase P02
# expected: check_dependencies returns passed=False and names P02
# risk: a PARKED dependency is silently ignored
# capability: phase-machinery


@pytest.mark.fast
def test_parked_dependency_stops() -> None:
    """A PARKED phase in depends_on stops entry, naming it."""
    phases = {
        "P01": _phase_entry("P01", depends_on=["P00"]),
        "P02": _phase_entry("P02", depends_on=["P01"]),
        "P03": _phase_entry("P03", depends_on=["P02"]),
    }
    state = _default_state()
    state.last_completed_phase = "P01"
    parked = {"P02"}
    result = check_dependencies("P03", phases, state, parked_phases=parked)
    assert not result.passed
    assert "P02" in result.evidence


@pytest.mark.fast
def test_not_merged_dependency_stops() -> None:
    """A not-merged dependency stops entry, naming it."""
    phases = {
        "P00": _phase_entry("P00", depends_on=[]),
        "P01": _phase_entry("P01", depends_on=["P00"]),
        "P02": _phase_entry("P02", depends_on=["P01"]),
    }
    state = _default_state()
    state.last_completed_phase = "P00"
    result = check_dependencies("P02", phases, state, parked_phases=None)
    assert not result.passed
    assert "P01" in result.evidence


# ---------------------------------------------------------------------------
# T-PHASE-0107 — Proper merge passes merge proof
# ---------------------------------------------------------------------------
# id: T-PHASE-0107
# title: Proper two-parent merge passes merge proof
# purpose: Verify that a proper merge commit with two parents passes the
#          merge-proof check.
# level: fast
# requirement: P00-T05, Part 1 §8.2a
# input: a temp repo with a properly merged branch
# expected: check_merge_proof returns passed=True
# risk: a correct merge is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_proper_merge_passes(tmp_path: Path) -> None:
    """A proper two-parent merge passes the merge-proof check."""
    repo = _init_repo(tmp_path)
    _make_merge(repo, "phase/01-slug")
    result = check_merge_proof(repo)
    assert result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0108 — Clean tree passes
# ---------------------------------------------------------------------------
# id: T-PHASE-0108
# title: Clean tree passes clean-tree check
# purpose: Verify that a clean working tree passes the clean-tree check.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: a temp repo with a clean tree
# expected: check_clean_tree returns passed=True
# risk: a clean tree is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_clean_tree_passes(tmp_path: Path) -> None:
    """A clean working tree passes the clean-tree check."""
    repo = _init_repo(tmp_path)
    result = check_clean_tree(repo)
    assert result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0109 — Correct directive hash passes
# ---------------------------------------------------------------------------
# id: T-PHASE-0109
# title: Correct directive hash passes check
# purpose: Verify that a state with the correct directive_hash passes.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: a state whose directive_hash matches the file
# expected: check_directive_hash returns passed=True
# risk: a correct hash is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_correct_directive_hash_passes(tmp_path: Path) -> None:
    """A correct directive hash passes the check."""
    repo = _init_repo(tmp_path)
    directive = repo / "directive.txt"
    directive.write_text("directive content\n", encoding="utf-8")
    actual = hashlib.sha256(directive.read_bytes()).hexdigest()
    state = _default_state(directive_hash=actual)
    result = check_directive_hash(state, directive)
    assert result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0110 — Deleted branch passes
# ---------------------------------------------------------------------------
# id: T-PHASE-0110
# title: Deleted previous branch passes check
# purpose: Verify that a deleted previous branch passes the check.
# level: fast
# requirement: P00-T05, Part 1 §8.2c
# input: a temp repo where the previous branch was deleted
# expected: check_previous_branch_deleted returns passed=True
# risk: a correctly deleted branch is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_deleted_branch_passes(tmp_path: Path) -> None:
    """A deleted previous branch passes the check."""
    repo = _init_repo(tmp_path)
    _git(["checkout", "-b", "phase/01-slug"], repo)
    _git(["checkout", "main"], repo)
    _git(["branch", "-D", "phase/01-slug"], repo)
    result = check_previous_branch_deleted(repo, "phase/01-slug")
    assert result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0111 — Correct previous_merge_hash passes
# ---------------------------------------------------------------------------
# id: T-PHASE-0111
# title: Correct previous_merge_hash passes check
# purpose: Verify that a state whose previous_merge_hash matches the actual
#          merge commit passes.
# level: fast
# requirement: P00-T05, Part 1 §8.3
# input: a state with the correct merge hash
# expected: check_previous_merge_hash returns passed=True
# risk: a correct merge hash is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_correct_previous_merge_hash_passes(tmp_path: Path) -> None:
    """A correct previous_merge_hash passes the check."""
    repo = _init_repo(tmp_path)
    merge_hash = _make_merge(repo, "phase/01-slug")
    state = _default_state()
    state.previous_merge_hash = merge_hash
    result = check_previous_merge_hash(state, repo)
    assert result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0112 — State save/load round trip
# ---------------------------------------------------------------------------
# id: T-PHASE-0112
# title: State save/load round trip preserves all fields
# purpose: Verify that save_state then load_state returns the same state.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: a state written to disk and read back
# expected: loaded state matches the original
# risk: state is corrupted or lost on save/load
# capability: phase-machinery


@pytest.mark.fast
def test_state_save_load_round_trip(tmp_path: Path) -> None:
    """save_state then load_state round-trips correctly."""
    state = _default_state()
    state.last_completed_phase = "P01"
    state.previous_merge_hash = "abc123" * 10 + "a" * 4
    path = tmp_path / "STATE.json"
    save_state(path, state)
    loaded = load_state(path)
    assert loaded.last_completed_phase == "P01"
    assert loaded.previous_merge_hash == state.previous_merge_hash
    assert loaded.directive_hash == state.directive_hash


# ---------------------------------------------------------------------------
# T-PHASE-0025 — Baseline no decrease passes
# ---------------------------------------------------------------------------
# id: T-PHASE-0025
# title: No baseline decrease passes check
# purpose: Verify that measured coverage at or above baseline passes.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: baselines at 0.80, measured at 0.90
# expected: check_baseline_decrease returns an empty list
# risk: a valid coverage level is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_no_baseline_decrease_passes() -> None:
    """Measured coverage at or above baseline passes."""
    baselines = {"tools/gate": {"branch_coverage": 0.80, "line_coverage": 0.80}}
    measured = {"tools/gate": {"branch_coverage": 0.90, "line_coverage": 0.85}}
    decreases = check_baseline_decrease(baselines, measured)
    assert not decreases
    result = check_baseline_decrease_result(baselines, measured)
    assert result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0026 — Done lines all present passes
# ---------------------------------------------------------------------------
# id: T-PHASE-0026
# title: All DONE lines present passes check
# purpose: Verify that all expected tasks with DONE lines pass the check.
# level: fast
# requirement: P00-T05, Part 1 §9.1
# input: a ledger with all expected DONE lines
# expected: check_done_lines returns passed=True
# risk: a complete ledger is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_all_done_lines_pass(tmp_path: Path) -> None:
    """All expected tasks with DONE lines pass the check."""
    repo = _init_repo(tmp_path)
    _write_ledger(repo, "P01", ["P01-T01", "P01-T02"])
    result = check_done_lines(repo, "P01", ["P01-T01", "P01-T02"])
    assert result.passed


# ---------------------------------------------------------------------------
# T-PHASE-0027 — Phases table loads with 16 entries
# ---------------------------------------------------------------------------
# id: T-PHASE-0027
# title: phases.toml loads with 16 phase entries
# purpose: Verify that load_phases reads all 16 phases from phases.toml.
# level: fast
# requirement: P00-T05, Part 6 §6.2
# input: the real phases.toml file
# expected: 16 phases, P01 through P16
# risk: the phase table is incomplete or wrong
# capability: phase-machinery


@pytest.mark.fast
def test_phases_table_loads() -> None:
    """phases.toml loads with 16 phase entries (P01 through P16)."""
    phases = load_phases(REPO_ROOT / "tools" / "gate" / "phases.toml")
    assert len(phases) == 16
    for i in range(1, 17):
        phase_id = f"P{i:02d}"
        assert phase_id in phases
    assert phases["P01"].name == "Risk management system"
    assert phases["P16"].name == "Clocks, charges and landed cost"
    assert phases["P16"].budget_class == "L"


# ---------------------------------------------------------------------------
# T-PHASE-0028 — STOP report validation
# ---------------------------------------------------------------------------
# id: T-PHASE-0028
# title: STOP report with all required fields passes
# purpose: Verify that a STOP report with all required fields passes
#          validation.
# level: fast
# requirement: P00-T05, Part 1 §12.4
# input: a STOP report dict with all 9 required fields
# expected: validate_stopreport returns an empty error list
# risk: a valid STOP report is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_stop_report_valid() -> None:
    """A STOP report with all required fields passes validation."""
    report = (
        "phase: P01\n"
        "task: P01-T03\n"
        "condition: 8.2d\n"
        "what_happened: dependency not merged\n"
        "attempts: 2\n"
        "evidence: git log\n"
        "decision_needed: merge or park P00\n"
        "options: merge or park\n"
        "untouched: nothing\n"
    )
    errors = validate_stopreport(report)
    assert not errors


@pytest.mark.fast
def test_stop_report_missing_field_fails() -> None:
    """A STOP report missing a field fails validation."""
    report = "phase: P01\ntask: P01-T03\ncondition: 8.2d\nwhat_happened: dependency not merged\n"
    errors = validate_stopreport(report)
    assert errors


# ---------------------------------------------------------------------------
# T-PHASE-0029 — State hash computation
# ---------------------------------------------------------------------------
# id: T-PHASE-0029
# title: State hash is deterministic
# purpose: Verify that compute_state_hash is deterministic for the same input.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: two identical state dicts
# expected: same hash
# risk: the state hash is non-deterministic
# capability: phase-machinery


@pytest.mark.fast
def test_state_hash_deterministic() -> None:
    """compute_state_hash is deterministic."""
    data1 = {"a": 1, "b": 2, "state_hash": "ignore"}
    data2 = {"b": 2, "a": 1, "state_hash": "ignore"}
    assert compute_state_hash(data1) == compute_state_hash(data2)


# ---------------------------------------------------------------------------
# T-PHASE-0030 — Self-review with 10 findings passes
# ---------------------------------------------------------------------------
# id: T-PHASE-0030
# title: Self-review with 10 findings and no overflow passes
# purpose: Verify that a self-review with exactly 10 findings (the max) and
#          no overflow passes validation.
# level: fast
# requirement: P00-T05, Part 1 §9.3
# input: a self-review text with 10 valid findings
# expected: validate_selfreview returns an empty error list
# risk: a valid self-review is wrongly rejected
# capability: phase-machinery


def _make_finding(
    fid: str,
    category: str = "RISK",
    evidence: str = "file.py:1-10",
    impact: str = "This is wrong.",
    question: str = "Fix it?",
) -> str:
    return (
        f"### {fid}\n"
        f"- category: {category}\n"
        f"- evidence: {evidence}\n"
        f"- impact: {impact}\n"
        f"- question: {question}\n"
    )


@pytest.mark.fast
def test_selfreview_10_findings_passes() -> None:
    """A self-review with 10 valid findings passes."""
    text = "\n".join(_make_finding(f"F{i:03d}") for i in range(10))
    errors = validate_selfreview(text)
    assert not errors


# ---------------------------------------------------------------------------
# T-PHASE-0049 — 11th finding without overflow file fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0049
# title: 11th finding without OVERFLOW line fails
# purpose: Verify that a self-review with 11 findings and no OVERFLOW line
#          fails validation.
# level: fast
# requirement: P00-T05, Part 1 §9.3
# input: a self-review text with 11 findings and no OVERFLOW line
# expected: validate_selfreview returns a non-empty error list
# risk: more than 10 findings are listed without overflow handling
# capability: phase-machinery


@pytest.mark.fast
def test_11_findings_without_overflow_fails() -> None:
    """11 findings without an OVERFLOW line fails validation."""
    text = "\n".join(_make_finding(f"F{i:03d}") for i in range(11))
    errors = validate_selfreview(text)
    assert errors
    assert any("11" in e or "OVERFLOW" in e for e in errors)


# ---------------------------------------------------------------------------
# T-PHASE-0050 — OVERFLOW line whose counts differ from file fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0050
# title: OVERFLOW line with wrong counts fails
# purpose: Verify that an OVERFLOW line whose category counts don't match the
#          overflow file fails validation.
# level: fast
# requirement: P00-T05, Part 1 §9.3
# input: 10 findings + OVERFLOW line (total 5) but overflow file has 3
# expected: validate_selfreview returns a non-empty error list
# risk: overflow counts are wrong, hiding findings
# capability: phase-machinery


@pytest.mark.fast
def test_overflow_counts_differ_fails() -> None:
    """An OVERFLOW line whose total doesn't match the file fails."""
    main_text = "\n".join(_make_finding(f"F{i:03d}") for i in range(10))
    main_text += (
        "\nOVERFLOW: 5 further findings in docs/phase-reports/P01-overflow.md "
        "(CONTRADICTION 2, GAP 1, RISK 1, AMBIGUITY 0, DEBT 1)\n"
    )
    overflow_text = "\n".join(
        _make_finding(f"O{i:03d}", category=cat)
        for i, cat in enumerate(["CONTRADICTION", "GAP", "RISK"])
    )
    errors = validate_selfreview(main_text, overflow_content=overflow_text)
    assert errors
    assert any("5" in e and "3" in e for e in errors)


# ---------------------------------------------------------------------------
# T-PHASE-0051 — Overflow file without the line fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0051
# title: Overflow file without OVERFLOW line fails
# purpose: Verify that an overflow file exists but the OVERFLOW line is missing
#          from the self-review text fails validation.
# level: fast
# requirement: P00-T05, Part 1 §9.3
# input: 11 findings + overflow file content but no OVERFLOW line
# expected: validate_selfreview returns a non-empty error list
# risk: overflow findings exist but are not referenced in the report
# capability: phase-machinery


@pytest.mark.fast
def test_overflow_file_without_line_fails() -> None:
    """An overflow file without the OVERFLOW line fails."""
    main_text = "\n".join(_make_finding(f"F{i:03d}") for i in range(11))
    overflow_text = "\n".join(_make_finding(f"O{i:03d}") for i in range(3))
    errors = validate_selfreview(main_text, overflow_content=overflow_text)
    assert errors
    assert any("OVERFLOW" in e for e in errors)


# ---------------------------------------------------------------------------
# T-PHASE-0052 — Finding over 40 words fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0052
# title: Finding over 40 words fails
# purpose: Verify that a finding with more than 40 words fails validation.
# level: fast
# requirement: P00-T05, Part 1 §9.3
# input: a self-review with one finding exceeding 40 words
# expected: validate_selfreview returns a non-empty error list mentioning words
# risk: an over-long finding is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_finding_over_40_words_fails() -> None:
    """A finding with more than 40 words fails validation."""
    long_text = " ".join(["word"] * 50)
    text = _make_finding(
        "F001",
        evidence=long_text,
        impact="Impact here.",
        question="Question?",
    )
    errors = validate_selfreview(text)
    assert errors
    assert any("40" in e or "words" in e for e in errors)


# ---------------------------------------------------------------------------
# T-PHASE-0113 — Finding within 40 words passes
# ---------------------------------------------------------------------------
# id: T-PHASE-0113
# title: Finding within 40 words passes
# purpose: Verify that a finding with at most 40 words passes validation.
# level: fast
# requirement: P00-T05, Part 1 §9.3
# input: a self-review with one finding under 40 words
# expected: validate_selfreview returns an empty error list
# risk: a valid finding is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_finding_within_40_words_passes() -> None:
    """A finding with at most 40 words passes validation."""
    text = _make_finding("F001", evidence="file.py:1-10", impact="Short.", question="Fix?")
    errors = validate_selfreview(text)
    assert not errors


# ---------------------------------------------------------------------------
# T-PHASE-0114 — Missing finding category fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0114
# title: Finding missing category fails
# purpose: Verify that a finding missing its category fails validation.
# level: fast
# requirement: P00-T05, Part 1 §9.3
# input: a finding with an empty category
# expected: validate_selfreview returns a non-empty error list
# risk: a finding without a category is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_finding_missing_category_fails() -> None:
    """A finding missing its category fails validation."""
    text = _make_finding("F001", category="", evidence="f:1", impact="i", question="q")
    errors = validate_selfreview(text)
    assert errors
    assert any("category" in e for e in errors)


# ---------------------------------------------------------------------------
# T-PHASE-0115 — Invalid category fails
# ---------------------------------------------------------------------------
# id: T-PHASE-0115
# title: Invalid finding category fails
# purpose: Verify that a finding with an invalid category fails validation.
# level: fast
# requirement: P00-T05, Part 1 §9.3
# input: a finding with category 'BUG' (not in the allowed list)
# expected: validate_selfreview returns a non-empty error list
# risk: a finding with a wrong category is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_invalid_category_fails() -> None:
    """A finding with an invalid category fails validation."""
    text = _make_finding("F001", category="BUG", evidence="f:1", impact="i", question="q")
    errors = validate_selfreview(text)
    assert errors
    assert any("category" in e for e in errors)


# ---------------------------------------------------------------------------
# T-PHASE-0116 — Overflow with correct counts passes
# ---------------------------------------------------------------------------
# id: T-PHASE-0116
# title: Overflow with correct counts passes
# purpose: Verify that a self-review with 10 findings + correct OVERFLOW line
#          and matching overflow file passes validation.
# level: fast
# requirement: P00-T05, Part 1 §9.3
# input: 10 findings + OVERFLOW line (total 3, counts correct) + overflow file
# expected: validate_selfreview returns an empty error list
# risk: a valid overflow is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_overflow_correct_passes() -> None:
    """A self-review with correct overflow handling passes."""
    main_text = "\n".join(_make_finding(f"F{i:03d}") for i in range(10))
    overflow_findings = [
        ("O001", "CONTRADICTION"),
        ("O002", "GAP"),
        ("O003", "RISK"),
    ]
    main_text += (
        "\nOVERFLOW: 3 further findings in docs/phase-reports/P01-overflow.md "
        "(CONTRADICTION 1, GAP 1, RISK 1, AMBIGUITY 0, DEBT 0)\n"
    )
    overflow_text = "\n".join(_make_finding(fid, category=cat) for fid, cat in overflow_findings)
    errors = validate_selfreview(main_text, overflow_content=overflow_text)
    assert not errors


# ---------------------------------------------------------------------------
# T-PHASE-0117 — Max findings and word limit constants
# ---------------------------------------------------------------------------
# id: T-PHASE-0117
# title: Self-review constants match spec
# purpose: Verify that MAX_FINDINGS=10, MAX_WORDS=40, and CATEGORIES has 5.
# level: fast
# requirement: P00-T05, Part 1 §9.3
# input: the constants from selfreview
# expected: MAX_FINDINGS==10, MAX_WORDS==40, len(CATEGORIES)==5
# risk: the limits are wrong
# capability: phase-machinery


@pytest.mark.fast
def test_selfreview_constants() -> None:
    """Self-review constants match the spec."""
    assert MAX_FINDINGS == 10
    assert MAX_WORDS == 40
    assert len(CATEGORIES) == 5
    assert "CONTRADICTION" in CATEGORIES
    assert "DEBT" in CATEGORIES


# ---------------------------------------------------------------------------
# T-PHASE-0118 — State consistency with matching ledger passes
# ---------------------------------------------------------------------------
# id: T-PHASE-0118
# title: State consistency with matching ledger passes
# purpose: Verify that a state whose last_completed_phase matches the ledger
#          passes the state-consistency check.
# level: fast
# requirement: P00-T05, Part 1 §8.2
# input: a state and ledger that agree on P00
# expected: check_state_consistency returns passed=True
# risk: a consistent state is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_state_consistency_passes(tmp_path: Path) -> None:
    """A state consistent with the ledger passes."""
    repo = _init_repo(tmp_path)
    _write_ledger(repo, "P00", ["P00-T01"])
    state = _default_state()
    result = check_state_consistency(state, repo)
    assert result.passed


# ---------------------------------------------------------------------------
# Helper for PhaseEntry construction
# ---------------------------------------------------------------------------


def _phase_entry(
    pid: str,
    name: str = "test",
    budget_class: str = "M",
    capabilities: list[str] | None = None,
    depends_on: list[str] | None = None,
) -> PhaseEntry:
    return PhaseEntry(
        id=pid,
        name=name,
        budget_class=budget_class,
        capabilities=tuple(capabilities) if capabilities else (),
        depends_on=tuple(depends_on) if depends_on else (),
    )
