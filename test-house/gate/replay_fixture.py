"""Fixture generator for recovery and STOP rehearsal tests (P00-T13).

Creates a temporary git repository with a 10-task fixture phase and provides
helpers to simulate STOPs at task boundaries and interruptions mid-task.

Spec: Part 6 §6.16 (P00-T13).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PHASE_ID = "P01"
NUM_TASKS = 10


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


def _directive_text() -> str:
    """Create a minimal directive with a 10-task phase block."""
    lines = ["<<<PHASE-01>>>"]
    for i in range(1, NUM_TASKS + 1):
        lines.append(f"P01-T{i:02d}: create file {i:02d}")
        lines.append(f"- Files: `T{i:02d}.txt`, `docs/ledger/P01.md`")
    lines.append("<<<END-PHASE-01>>>")
    return "\n".join(lines) + "\n"


def create_fixture_repo(tmp_path: Path) -> Path:
    """Create a temp git repo with a 10-task fixture phase."""
    repo = tmp_path / "fixture-repo"
    repo.mkdir(parents=True)
    _git(["init", "--initial-branch=main"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    _git(["config", "commit.gpgsign", "false"], repo)
    (repo / "directive.txt").write_text(_directive_text(), encoding="utf-8")
    ledger = repo / "docs" / "ledger" / "P01.md"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("# P01 Ledger\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".gate-quarantine/\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "init"], repo)
    return repo


def run_task(repo: Path, task_num: int) -> None:
    """Run a single task: create file, add DONE line, commit (if changes)."""
    task_id = f"P01-T{task_num:02d}"
    filepath = repo / f"T{task_num:02d}.txt"
    filepath.write_text(f"Task {task_num:02d}\n", encoding="utf-8")
    ledger = repo / "docs" / "ledger" / "P01.md"
    content = ledger.read_text(encoding="utf-8")
    done_line = f"{task_id} DONE"
    if done_line not in content:
        lines = content.splitlines()
        lines.append(done_line)
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _git(["add", f"T{task_num:02d}.txt", "docs/ledger/P01.md"], repo)
    staged = _git(["diff", "--cached", "--name-only"], repo)
    if staged.stdout.strip():
        _git(["commit", "-m", f"feat: {task_id}"], repo)


def run_tasks(repo: Path, start: int, end: int) -> None:
    """Run tasks from *start* to *end* (inclusive)."""
    for i in range(start, end + 1):
        run_task(repo, i)


def run_all_tasks(repo: Path) -> None:
    """Run all 10 tasks."""
    run_tasks(repo, 1, NUM_TASKS)


def tree_hash(repo: Path) -> str:
    """Return the tree hash of HEAD."""
    return _git(["rev-parse", "HEAD^{tree}"], repo).stdout.strip()


def make_dirty(repo: Path, task_num: int) -> None:
    """Create a dirty tree mid-task (uncommitted changes for *task_num*)."""
    filepath = repo / f"T{task_num:02d}.txt"
    filepath.write_text(f"Task {task_num:02d}\n", encoding="utf-8")
    ledger = repo / "docs" / "ledger" / "P01.md"
    content = ledger.read_text(encoding="utf-8")
    done_line = f"P01-T{task_num:02d} DONE"
    if done_line not in content:
        lines = content.splitlines()
        lines.append(done_line)
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")


def commit_task_file_only(repo: Path, task_num: int) -> None:
    """Commit only the task file without the DONE line."""
    filepath = repo / f"T{task_num:02d}.txt"
    filepath.write_text(f"Task {task_num:02d}\n", encoding="utf-8")
    _git(["add", f"T{task_num:02d}.txt"], repo)
    _git(["commit", "-m", f"feat: P01-T{task_num:02d} file only"], repo)


def add_done_line(repo: Path, task_num: int) -> None:
    """Add a DONE line for a task and commit (ledger only)."""
    task_id = f"P01-T{task_num:02d}"
    ledger = repo / "docs" / "ledger" / "P01.md"
    content = ledger.read_text(encoding="utf-8")
    done_line = f"{task_id} DONE"
    if done_line not in content:
        lines = content.splitlines()
        lines.append(done_line)
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _git(["add", "docs/ledger/P01.md"], repo)
        _git(["commit", "-m", f"feat: {task_id} DONE"], repo)


def run_phase_end_step(repo: Path, step: int) -> None:
    """Run a phase-end step (create a file and commit)."""
    step_dir = repo / "phase-end"
    step_dir.mkdir(exist_ok=True)
    filepath = step_dir / f"END{step}.txt"
    filepath.write_text(f"Phase-end step {step}\n", encoding="utf-8")
    _git(["add", f"phase-end/END{step}.txt"], repo)
    staged = _git(["diff", "--cached", "--name-only"], repo)
    if staged.stdout.strip():
        _git(["commit", "-m", f"feat: P01-END{step}"], repo)


def run_all_phase_end_steps(repo: Path) -> None:
    """Run all phase-end steps (1 through 3)."""
    for step in range(1, 4):
        run_phase_end_step(repo, step)


def make_dirty_phase_end(repo: Path, step: int) -> None:
    """Create a dirty tree mid-phase-end-step (uncommitted changes)."""
    step_dir = repo / "phase-end"
    step_dir.mkdir(exist_ok=True)
    filepath = step_dir / f"END{step}.txt"
    filepath.write_text(f"Phase-end step {step}\n", encoding="utf-8")
