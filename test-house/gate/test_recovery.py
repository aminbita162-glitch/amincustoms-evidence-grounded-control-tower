"""Tests for recovery check and STOP rehearsal (P00-T13).

Tests T-PHASE-0033 through T-PHASE-0040 cover the STOP rehearsal: a STOP at
each task boundary resumes to the identical tree hash.  Tests T-PHASE-0061
through T-PHASE-0068 cover interruption recovery: an interruption inside
every task recovers to the identical final tree hash.

Spec: Part 1 §7.5, §7.5a, §12.4, §12.6; Part 6 §6.16 (P00-T13).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from gate.replay_fixture import (
    add_done_line,
    commit_task_file_only,
    create_fixture_repo,
    make_dirty,
    make_dirty_phase_end,
    run_all_phase_end_steps,
    run_all_tasks,
    run_phase_end_step,
    run_task,
    run_tasks,
    tree_hash,
)
from tools.gate.phase.quarantine import (
    INTERRUPTION_RECORD_FIELDS,
    create_bundle,
    quarantine_tree,
    validate_interruption_record,
    verify_bundle,
)
from tools.gate.phase.recovery import check_recovery, check_recovery_interruption
from tools.gate.phase.stopreport import check_stopreport_file, validate_stopreport

PHASE_ID = "P01"


def _git_env() -> dict[str, str]:
    """Environment for git subprocess calls (sets DEVELOPER_DIR)."""
    env = dict(os.environ)
    env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return env


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command in *cwd* (raises on failure)."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=_git_env(),
        capture_output=True,
        text=True,
        check=True,
    )


def _cleanup_interruption_records(repo: Path) -> None:
    """Remove interruption record files created by quarantine_tree."""
    int_dir = repo / "docs" / "phase-reports"
    if int_dir.exists():
        for f in int_dir.glob(f"{PHASE_ID}-INT-*.md"):
            f.unlink()


# --------------------------------------------------------------------------- #
# T-PHASE-0033 — STOP at each boundary resumes to identical tree hash
# --------------------------------------------------------------------------- #
# id: T-PHASE-0033
# title: STOP at each boundary of a ten-task fixture phase resumes to identical tree hash
# purpose: Verify that a STOP at each task boundary, when resumed, reaches the
#          same final tree hash as an uninterrupted run.
# level: slow
# requirement: P00-T13, Part 1 §7.5, Part 6 §6.16
# input: a temp fixture repo with 10 tasks; for each boundary, run 1..N, STOP, resume N+1..10
# expected: final tree hash matches the uninterrupted run for every boundary
# risk: a STOP at a boundary corrupts the state or produces a different result
# capability: phase-machinery


@pytest.mark.slow
def test_stop_at_each_boundary_resumes(tmp_path: Path) -> None:
    """STOP at each boundary resumes to the identical tree hash."""
    repo = create_fixture_repo(tmp_path / "uninterrupted")
    run_all_tasks(repo)
    expected_hash = tree_hash(repo)

    for boundary in range(10):
        repo = create_fixture_repo(tmp_path / f"stop-{boundary}")
        if boundary > 0:
            run_tasks(repo, 1, boundary)
        assert check_recovery(repo, PHASE_ID) == 0
        run_tasks(repo, boundary + 1, 10)
        assert tree_hash(repo) == expected_hash


# --------------------------------------------------------------------------- #
# T-PHASE-0034 — STOP report with missing field fails check
# --------------------------------------------------------------------------- #
# id: T-PHASE-0034
# title: STOP report with missing field fails the check
# purpose: Verify that a STOP report missing a required field fails validation.
# level: fast
# requirement: P00-T13, Part 1 §12.4
# input: a STOP report file with missing fields
# expected: check_stopreport_file returns 1 and validate_stopreport returns errors
# risk: an incomplete STOP report is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_stop_report_missing_field_fails(tmp_path: Path) -> None:
    """A STOP report with a missing field fails the check."""
    report = tmp_path / "stop-report.md"
    report.write_text(
        "phase: P01\ntask: P01-T05\ncondition: 8.2d\nwhat_happened: test\n",
        encoding="utf-8",
    )
    errors = validate_stopreport(report.read_text(encoding="utf-8"))
    assert errors
    assert check_stopreport_file(report) == 1


# --------------------------------------------------------------------------- #
# T-PHASE-0035 — Dirty tree without STOP report fails recovery
# --------------------------------------------------------------------------- #
# id: T-PHASE-0035
# title: Dirty tree without an explaining STOP report fails recovery
# purpose: Verify that a dirty working tree without a STOP report fails the
#          recovery check.
# level: fast
# requirement: P00-T13, Part 1 §7.5
# input: a temp fixture repo with an uncommitted change and no STOP report
# expected: check_recovery returns 1
# risk: a dirty tree without an explanation is accepted at recovery
# capability: phase-machinery


@pytest.mark.fast
def test_dirty_without_stop_report_fails(tmp_path: Path) -> None:
    """A dirty tree without a STOP report fails the recovery check."""
    repo = create_fixture_repo(tmp_path)
    (repo / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
    assert check_recovery(repo, PHASE_ID) == 1


# --------------------------------------------------------------------------- #
# T-PHASE-0036 — Task re-run on finished tree changes nothing
# --------------------------------------------------------------------------- #
# id: T-PHASE-0036
# title: Task re-run on a finished tree changes nothing (idempotency)
# purpose: Verify that re-running a task on a tree that already contains its
#          result changes nothing (idempotency).
# level: slow
# requirement: P00-T13, Part 6 §6.16
# input: a finished fixture repo with all 10 tasks done; re-run task 5
# expected: tree hash is unchanged after the re-run
# risk: a re-run corrupts the tree or adds duplicate commits
# capability: phase-machinery


@pytest.mark.slow
def test_task_rerun_changes_nothing(tmp_path: Path) -> None:
    """Re-running a task on a finished tree changes nothing."""
    repo = create_fixture_repo(tmp_path)
    run_all_tasks(repo)
    before_hash = tree_hash(repo)
    run_task(repo, 5)
    after_hash = tree_hash(repo)
    assert before_hash == after_hash


# --------------------------------------------------------------------------- #
# T-PHASE-0037 — STOP report with all fields passes check
# --------------------------------------------------------------------------- #
# id: T-PHASE-0037
# title: STOP report with all required fields passes the check
# purpose: Verify that a valid STOP report passes the check_stopreport_file
#          validation.
# level: fast
# requirement: P00-T13, Part 1 §12.4
# input: a STOP report file with all 9 required fields
# expected: check_stopreport_file returns 0
# risk: a valid STOP report is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_stop_report_valid_passes(tmp_path: Path) -> None:
    """A STOP report with all required fields passes the check."""
    report = tmp_path / "stop-report.md"
    report.write_text(
        "phase: P01\n"
        "task: P01-T05\n"
        "condition: 8.2d\n"
        "what_happened: dependency not merged\n"
        "attempts: 2\n"
        "evidence: git log\n"
        "decision_needed: merge or park P00\n"
        "options: merge or park\n"
        "untouched: nothing\n",
        encoding="utf-8",
    )
    assert check_stopreport_file(report) == 0


# --------------------------------------------------------------------------- #
# T-PHASE-0038 — Dirty tree with STOP report passes recovery
# --------------------------------------------------------------------------- #
# id: T-PHASE-0038
# title: Dirty tree with an explaining STOP report passes recovery
# purpose: Verify that a dirty working tree with a STOP report passes the
#          recovery check.
# level: fast
# requirement: P00-T13, Part 1 §7.5
# input: a temp fixture repo with an uncommitted change and a STOP report
# expected: check_recovery returns 0
# risk: a dirty tree with a STOP report is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_dirty_with_stop_report_passes(tmp_path: Path) -> None:
    """A dirty tree with a STOP report passes the recovery check."""
    repo = create_fixture_repo(tmp_path)
    (repo / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
    report_dir = repo / "docs" / "phase-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "P01-STOP-1.md").write_text(
        "phase: P01\n"
        "task: P01-T05\n"
        "condition: 8.2\n"
        "what_happened: test\n"
        "attempts: 0\n"
        "evidence: none\n"
        "decision_needed: proceed\n"
        "options: proceed\n"
        "untouched: nothing\n",
        encoding="utf-8",
    )
    assert check_recovery(repo, PHASE_ID) == 0


# --------------------------------------------------------------------------- #
# T-PHASE-0039 — Clean tree passes recovery
# --------------------------------------------------------------------------- #
# id: T-PHASE-0039
# title: Clean tree passes the recovery check
# purpose: Verify that a clean working tree passes the recovery check.
# level: fast
# requirement: P00-T13, Part 1 §7.5
# input: a temp fixture repo with a clean tree
# expected: check_recovery returns 0
# risk: a clean tree is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_clean_tree_passes_recovery(tmp_path: Path) -> None:
    """A clean tree passes the recovery check."""
    repo = create_fixture_repo(tmp_path)
    assert check_recovery(repo, PHASE_ID) == 0


# --------------------------------------------------------------------------- #
# T-PHASE-0040 — STOP at boundary 0 resumes to identical hash
# --------------------------------------------------------------------------- #
# id: T-PHASE-0040
# title: STOP at boundary 0 (no tasks run) resumes to identical tree hash
# purpose: Verify that a STOP before any task is run, when resumed, reaches the
#          same final tree hash as an uninterrupted run.
# level: slow
# requirement: P00-T13, Part 1 §7.5, Part 6 §6.16
# input: a temp fixture repo; STOP before task 1, then resume all 10
# expected: final tree hash matches the uninterrupted run
# risk: a STOP at boundary 0 produces a different result
# capability: phase-machinery


@pytest.mark.slow
def test_stop_at_boundary_0_resumes(tmp_path: Path) -> None:
    """STOP at boundary 0 (no tasks run) resumes to the identical tree hash."""
    repo = create_fixture_repo(tmp_path / "uninterrupted")
    run_all_tasks(repo)
    expected_hash = tree_hash(repo)

    repo = create_fixture_repo(tmp_path / "stop-0")
    assert check_recovery(repo, PHASE_ID) == 0
    run_all_tasks(repo)
    assert tree_hash(repo) == expected_hash


# --------------------------------------------------------------------------- #
# T-PHASE-0061 — Interruption inside every task recovers to identical hash
# --------------------------------------------------------------------------- #
# id: T-PHASE-0061
# title: Interruption inside every task recovers to identical tree hash
# purpose: Verify that an interruption in the middle of every task, when
#          recovered via quarantine, reaches the same final tree hash as an
#          uninterrupted run.
# level: slow
# requirement: P00-T13, Part 1 §7.5a, Part 6 §6.16
# input: a temp fixture repo; for each task, interrupt mid-task, quarantine, re-run
# expected: final tree hash matches the uninterrupted run for every task
# risk: an interruption corrupts the state or produces a different result
# capability: phase-machinery


@pytest.mark.slow
def test_interruption_every_task_recovers(tmp_path: Path) -> None:
    """Interruption inside every task recovers to the identical tree hash."""
    repo = create_fixture_repo(tmp_path / "uninterrupted")
    run_all_tasks(repo)
    expected_hash = tree_hash(repo)

    for task_num in range(1, 11):
        repo = create_fixture_repo(tmp_path / f"int-{task_num}")
        if task_num > 1:
            run_tasks(repo, 1, task_num - 1)
        make_dirty(repo, task_num)
        assert quarantine_tree(repo, PHASE_ID) == 0
        _cleanup_interruption_records(repo)
        run_task(repo, task_num)
        if task_num < 10:
            run_tasks(repo, task_num + 1, 10)
        assert tree_hash(repo) == expected_hash


# --------------------------------------------------------------------------- #
# T-PHASE-0062 — Bundle reproduces dirty tree; tree restored after verification
# --------------------------------------------------------------------------- #
# id: T-PHASE-0062
# title: Bundle reproduces dirty tree on temp copy; tree restored only after verification
# purpose: Verify that the bundle reproduces the dirty tree hash on a temporary
#          copy and that the working tree is restored to HEAD only after
#          verification passes.
# level: slow
# requirement: P00-T13, Part 1 §7.5a(b)
# input: a temp fixture repo with a dirty tree; create and verify the bundle
# expected: verify_bundle returns True; after quarantine, dirty files are gone
# risk: the tree is restored before verification or the bundle is incorrect
# capability: phase-machinery


@pytest.mark.slow
def test_bundle_verification_and_restore(tmp_path: Path) -> None:
    """Bundle reproduces dirty tree on temp copy; tree restored after verification."""
    repo = create_fixture_repo(tmp_path)
    run_tasks(repo, 1, 4)
    make_dirty(repo, 5)

    bundle_dir = repo / ".gate-quarantine"
    create_bundle(repo, bundle_dir)
    assert verify_bundle(repo, bundle_dir)

    assert quarantine_tree(repo, PHASE_ID) == 0

    # Tree restored: T05.txt should not exist.
    assert not (repo / "T05.txt").exists()
    # Ledger should not have the T05 DONE line.
    ledger = repo / "docs" / "ledger" / "P01.md"
    assert "P01-T05 DONE" not in ledger.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# T-PHASE-0063 — Changed path outside Files of interrupted task is a STOP
# --------------------------------------------------------------------------- #
# id: T-PHASE-0063
# title: Changed path outside Files of interrupted task is a STOP
# purpose: Verify that a changed path outside the Files of the interrupted task
#          is a STOP and changes nothing.
# level: fast
# requirement: P00-T13, Part 1 §7.5a(a)
# input: a temp fixture repo with a dirty path outside the task's Files
# expected: check_recovery_interruption returns 1; the dirty file still exists
# risk: an out-of-scope change is silently accepted
# capability: phase-machinery


@pytest.mark.fast
def test_outside_path_stops(tmp_path: Path) -> None:
    """A changed path outside the Files of the interrupted task is a STOP."""
    repo = create_fixture_repo(tmp_path)
    run_tasks(repo, 1, 4)
    (repo / "outside.txt").write_text("outside\n", encoding="utf-8")
    assert check_recovery_interruption(repo, PHASE_ID) == 1
    assert (repo / "outside.txt").exists()


# --------------------------------------------------------------------------- #
# T-PHASE-0064 — Interruption between commit and DONE line resumes without second commit
# --------------------------------------------------------------------------- #
# id: T-PHASE-0064
# title: Interruption between task commit and DONE line resumes without second commit
# purpose: Verify that an interruption between a task commit and its DONE line
#          resumes without a second commit of the task file.
# level: slow
# requirement: P00-T13, Part 1 §7.5a
# input: a temp fixture repo; task 5 file committed without DONE, then DONE added
# expected: final tree hash matches uninterrupted; T05.txt in only 1 commit
# risk: the task file is committed twice or the tree hash differs
# capability: phase-machinery


@pytest.mark.slow
def test_interruption_between_commit_and_done(tmp_path: Path) -> None:
    """Interruption between task commit and DONE line resumes without second commit."""
    repo = create_fixture_repo(tmp_path / "uninterrupted")
    run_all_tasks(repo)
    expected_hash = tree_hash(repo)

    repo = create_fixture_repo(tmp_path / "interrupted")
    run_tasks(repo, 1, 4)
    commit_task_file_only(repo, 5)
    add_done_line(repo, 5)
    run_tasks(repo, 6, 10)

    assert tree_hash(repo) == expected_hash
    log = _git(["log", "--oneline", "--", "T05.txt"], repo).stdout.strip()
    assert len(log.splitlines()) == 1


# --------------------------------------------------------------------------- #
# T-PHASE-0065 — Interruption in each phase-end step resumes at that step
# --------------------------------------------------------------------------- #
# id: T-PHASE-0065
# title: Interruption in each phase-end step resumes at that step
# purpose: Verify that an interruption in each step of the phase-end sequence
#          recovers and resumes at that step, reaching the same final state.
# level: slow
# requirement: P00-T13, Part 1 §7.5a, Part 6 §6.16
# input: a temp fixture repo; for each phase-end step, interrupt, quarantine, re-run
# expected: final tree hash matches the uninterrupted run
# risk: an interruption in the phase-end sequence corrupts the state
# capability: phase-machinery


@pytest.mark.slow
def test_interruption_phase_end_steps(tmp_path: Path) -> None:
    """Interruption in each phase-end step resumes at that step."""
    repo = create_fixture_repo(tmp_path / "uninterrupted")
    run_all_tasks(repo)
    run_all_phase_end_steps(repo)
    expected_hash = tree_hash(repo)

    for step in range(1, 4):
        repo = create_fixture_repo(tmp_path / f"end-step-{step}")
        run_all_tasks(repo)
        for s in range(1, step):
            run_phase_end_step(repo, s)
        make_dirty_phase_end(repo, step)
        assert quarantine_tree(repo, PHASE_ID) == 0
        _cleanup_interruption_records(repo)
        run_phase_end_step(repo, step)
        for s in range(step + 1, 4):
            run_phase_end_step(repo, s)
        assert tree_hash(repo) == expected_hash


# --------------------------------------------------------------------------- #
# T-PHASE-0066 — Stale lock removed only when no git process runs
# --------------------------------------------------------------------------- #
# id: T-PHASE-0066
# title: Stale index.lock removed only when no git process runs
# purpose: Verify that a stale .git/index.lock is removed by quarantine_tree
#          only after verifying no git process is running.
# level: slow
# requirement: P00-T13, Part 1 §7.5a(b)
# input: a temp fixture repo with a dirty tree and a stale index.lock
# expected: quarantine_tree returns 0; the stale lock is removed
# risk: a stale lock blocks recovery or is removed unsafely
# capability: phase-machinery


@pytest.mark.slow
def test_stale_lock_removed(tmp_path: Path) -> None:
    """A stale index.lock is removed when no git process is running."""
    repo = create_fixture_repo(tmp_path)
    run_tasks(repo, 1, 4)
    make_dirty(repo, 5)

    index_lock = repo / ".git" / "index.lock"
    index_lock.write_text("stale\n", encoding="utf-8")
    assert index_lock.exists()

    assert quarantine_tree(repo, PHASE_ID) == 0
    assert not index_lock.exists()


# --------------------------------------------------------------------------- #
# T-PHASE-0067 — Interruption record validates
# --------------------------------------------------------------------------- #
# id: T-PHASE-0067
# title: Interruption record validates with all required fields
# purpose: Verify that an interruption record with all §12.6 fields passes
#          validation.
# level: fast
# requirement: P00-T13, Part 1 §12.6
# input: a valid interruption record text
# expected: validate_interruption_record returns an empty error list
# risk: a valid interruption record is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_interruption_record_validates() -> None:
    """An interruption record with all required fields validates."""
    record = (
        "phase: P01\n"
        "interrupted_task: P01-T05\n"
        "last_done_task: P01-T04\n"
        "bundle_hash: abc123def456\n"
        "paths: T05.txt, docs/ledger/P01.md\n"
        "untouched: all other tasks\n"
    )
    errors = validate_interruption_record(record)
    assert not errors
    assert len(INTERRUPTION_RECORD_FIELDS) == 6


# --------------------------------------------------------------------------- #
# T-PHASE-0068 — Dirty tree without --interruption command is still a STOP
# --------------------------------------------------------------------------- #
# id: T-PHASE-0068
# title: Dirty tree without the --interruption command is still a STOP
# purpose: Verify that a dirty tree without the interruption recovery command
#          is still a STOP (the regular recovery check fails).
# level: fast
# requirement: P00-T13, Part 1 §7.5, §7.5a
# input: a temp fixture repo with a dirty tree and no STOP report
# expected: check_recovery returns 1; the dirty file still exists
# risk: a dirty tree without the interruption command is silently accepted
# capability: phase-machinery


@pytest.mark.fast
def test_dirty_without_interruption_stops(tmp_path: Path) -> None:
    """A dirty tree without the --interruption command is still a STOP."""
    repo = create_fixture_repo(tmp_path)
    run_tasks(repo, 1, 4)
    make_dirty(repo, 5)
    assert check_recovery(repo, PHASE_ID) == 1
    assert (repo / "T05.txt").exists()
