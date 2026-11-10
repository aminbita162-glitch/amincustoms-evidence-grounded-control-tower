"""Phase entry/exit checks for the AminCustoms phase machinery (P00-T05).

Implements the entry verification checks of Part 1 §8.2 and the exit
verification checks of Part 1 §9.1, plus the golden-commit rule of §4.8 and
the phases-table loader for ``tools/gate/phases.toml`` (Part 6 §6.2).

Every check returns a :class:`CheckResult` with a PASS/FAIL flag and evidence.
The caller (CLI or test) aggregates results to produce the Entry/Exit
Verification Report (§12.1/§12.2).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tools.gate.phase.baselines import check_baseline_decrease
from tools.gate.phase.state import State

__all__ = [
    "CheckResult",
    "PhaseEntry",
    "PhaseCheckError",
    "ENTRY_CHECKS",
    "EXIT_CHECKS",
    "ENTRY_REPORT_FIELDS",
    "EXIT_REPORT_FIELDS",
    "PHASE_REPORT_FIELDS",
    "load_phases",
    "git_env",
    "git_run",
    "check_clean_tree",
    "check_directive_hash",
    "check_merge_proof",
    "check_previous_branch_deleted",
    "check_done_lines",
    "check_task_commits",
    "check_dependencies",
    "check_previous_merge_hash",
    "check_awaiting_merge_cleared",
    "check_state_consistency",
    "check_baseline_decrease_result",
    "check_golden_commit",
    "validate_report_fields",
    "check_phase_entry",
    "check_phase_exit",
]


class PhaseCheckError(Exception):
    """A phase check error."""


@dataclass(frozen=True)
class CheckResult:
    """Result of a single entry/exit check item."""

    item: str
    passed: bool
    evidence: str

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True)
class PhaseEntry:
    """One phase from ``phases.toml``."""

    id: str
    name: str
    budget_class: str
    capabilities: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


# Required fields for the report templates (Part 1 §12).
ENTRY_REPORT_FIELDS: tuple[str, ...] = (
    "phase",
    "directive_hash",
    "previous_merge_hash",
    "results",
    "decision",
)

EXIT_REPORT_FIELDS: tuple[str, ...] = (
    "phase",
    "results",
    "attempts",
    "updated_artifacts",
    "ignored_instructions",
    "deviations",
)

PHASE_REPORT_FIELDS: tuple[str, ...] = (
    "entry_report",
    "exit_report",
    "commit_table",
    "self_review",
    "directive_hash",
    "budgets_used",
    "label_counts",
)

# Names of the entry checks in order (Part 1 §8.2).
ENTRY_CHECKS: tuple[str, ...] = (
    "directive_hash",
    "previous_report",
    "merge_proof",
    "clean_tree",
    "state_consistency",
    "previous_branch_deleted",
    "dependencies",
    "awaiting_merge_cleared",
)

# Names of the exit checks in order (Part 1 §9.1).
EXIT_CHECKS: tuple[str, ...] = (
    "done_lines",
    "task_commits",
    "test_suite",
    "cross_check",
    "license_data_label_secret_hygiene",
)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def git_env() -> dict[str, str]:
    """Environment for git subprocess calls (sets DEVELOPER_DIR)."""
    env = dict(os.environ)
    if "DEVELOPER_DIR" not in env:
        env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return env


def git_run(args: list[str], repo_root: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command in *repo_root* and return the completed process."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        env=git_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _git_out(args: list[str], repo_root: Path) -> str:
    """Run a git command and return stdout stripped (empty on failure)."""
    result = git_run(args, repo_root)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Phases table loader (Part 6 §6.2)
# ---------------------------------------------------------------------------


def load_phases(path: Path) -> dict[str, PhaseEntry]:
    """Load ``phases.toml`` into a ``{id: PhaseEntry}`` mapping."""
    try:
        with path.open("rb") as stream:
            raw: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PhaseCheckError(f"cannot load phases {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PhaseCheckError(f"phases {path} is not a table")
    phase_table: object = raw.get("phase")
    if not isinstance(phase_table, dict):
        raise PhaseCheckError(f"phases {path} has no [phase.*] tables")
    entries: dict[str, PhaseEntry] = {}
    for phase_id, value in phase_table.items():
        if not isinstance(value, dict):
            raise PhaseCheckError(f"phase.{phase_id} must be a table")
        name = str(value.get("name", ""))
        budget_class = str(value.get("class", value.get("budget_class", "")))
        caps_raw = value.get("capabilities", [])
        deps_raw = value.get("depends_on", [])
        capabilities = tuple(str(c) for c in caps_raw) if isinstance(caps_raw, list) else ()
        depends_on = tuple(str(d) for d in deps_raw) if isinstance(deps_raw, list) else ()
        entries[str(phase_id)] = PhaseEntry(
            id=str(phase_id),
            name=name,
            budget_class=budget_class,
            capabilities=capabilities,
            depends_on=depends_on,
        )
    return entries


# ---------------------------------------------------------------------------
# Entry checks (Part 1 §8.2)
# ---------------------------------------------------------------------------


def check_clean_tree(repo_root: Path) -> CheckResult:
    """8.2: working tree is clean (``git status --porcelain`` is empty)."""
    output = _git_out(["status", "--porcelain"], repo_root)
    if output:
        lines = output.splitlines()
        return CheckResult(
            "clean_tree",
            False,
            f"dirty tree: {len(lines)} path(s) changed — {', '.join(lines[:5])}",
        )
    return CheckResult("clean_tree", True, "working tree clean")


def check_directive_hash(state: State, directive_path: Path) -> CheckResult:
    """8.2: ``state.directive_hash`` matches the SHA-256 of ``directive.txt``."""
    if not directive_path.is_file():
        return CheckResult(
            "directive_hash",
            False,
            f"directive file not found: {directive_path}",
        )
    digest = hashlib.sha256(directive_path.read_bytes()).hexdigest()
    if state.directive_hash == digest:
        return CheckResult(
            "directive_hash",
            True,
            f"directive hash matches ({digest[:12]})",
        )
    return CheckResult(
        "directive_hash",
        False,
        f"state hash {state.directive_hash[:12]} != actual {digest[:12]}",
    )


def check_merge_proof(repo_root: Path) -> CheckResult:
    """8.2a: the merge commit of the previous phase has two parents.

    Finds the last merge commit (a commit with 2+ parents) on the current
    branch.  If none exists the merge was either a squash (single-parent
    commit) or a rebase (no merge commit at all); both are failures.
    """
    merge_line = _git_out(["log", "--merges", "-1", "--format=%H %P"], repo_root)
    if merge_line:
        parts = merge_line.split()
        parents = parts[1:]
        if len(parents) == 2:
            return CheckResult(
                "merge_proof",
                True,
                f"merge commit {parts[0][:8]} has 2 parents",
            )
        return CheckResult(
            "merge_proof",
            False,
            f"merge commit {parts[0][:8]} has {len(parents)} parent(s), expected 2",
        )
    # No merge commit — distinguish squash (1 parent) from rebase (no merge)
    last_line = _git_out(["log", "-1", "--format=%H %P"], repo_root)
    if last_line:
        parts = last_line.split()
        parents = parts[1:]
        if len(parents) == 1:
            return CheckResult(
                "merge_proof",
                False,
                f"last commit {parts[0][:8]} has 1 parent (squash merge, no 2-parent merge)",
            )
    return CheckResult(
        "merge_proof",
        False,
        "no merge commit found on current branch (rebase merge, no merge commit)",
    )


def check_previous_branch_deleted(repo_root: Path, branch_name: str) -> CheckResult:
    """8.2c: the previous phase's branch is deleted locally and on the remote."""
    local = _git_out(["branch", "--list", branch_name], repo_root)
    if local:
        return CheckResult(
            "previous_branch_deleted",
            False,
            f"local branch {branch_name!r} still exists",
        )
    remote = _git_out(["branch", "-r", "--list", f"origin/{branch_name}"], repo_root)
    if remote:
        return CheckResult(
            "previous_branch_deleted",
            False,
            f"remote branch origin/{branch_name!r} still exists",
        )
    return CheckResult(
        "previous_branch_deleted",
        True,
        f"branch {branch_name!r} deleted locally and remotely",
    )


def check_previous_merge_hash(state: State, repo_root: Path) -> CheckResult:
    """8.3: ``state.previous_merge_hash`` equals the actual merge commit hash."""
    if state.previous_merge_hash is None:
        return CheckResult(
            "previous_merge_hash",
            True,
            "no previous merge hash (first phase)",
        )
    actual = _git_out(["log", "--merges", "-1", "--format=%H"], repo_root)
    if not actual:
        return CheckResult(
            "previous_merge_hash",
            False,
            "state has a previous_merge_hash but no merge commit found",
        )
    if actual == state.previous_merge_hash:
        return CheckResult(
            "previous_merge_hash",
            True,
            f"matches merge commit {actual[:8]}",
        )
    return CheckResult(
        "previous_merge_hash",
        False,
        f"state.previous_merge_hash {state.previous_merge_hash[:8]} "
        f"!= actual merge commit {actual[:8]}",
    )


def check_awaiting_merge_cleared(state: State) -> CheckResult:
    """After merge proven, ``awaiting_merge_phase`` must be ``None``."""
    if state.awaiting_merge_phase is None:
        return CheckResult(
            "awaiting_merge_cleared",
            True,
            "awaiting_merge_phase is None",
        )
    return CheckResult(
        "awaiting_merge_cleared",
        False,
        f"awaiting_merge_phase is {state.awaiting_merge_phase!r} (not cleared after merge)",
    )


def check_state_consistency(state: State, repo_root: Path) -> CheckResult:
    """8.2: the state file is consistent with the ledger and commit history.

    Checks that ``last_completed_phase`` in the state matches the highest
    phase that has a ledger file with at least one DONE line.
    """
    ledger_dir = repo_root / "docs" / "ledger"
    highest_done = 0
    if ledger_dir.is_dir():
        for ledger_file in ledger_dir.glob("P*.md"):
            phase_id = ledger_file.stem
            if not (phase_id.startswith("P") and phase_id[1:].isdigit()):
                continue
            content = ledger_file.read_text(encoding="utf-8")
            if "DONE" in content:
                num = int(phase_id[1:])
                if num > highest_done:
                    highest_done = num
    state_num = (
        int(state.last_completed_phase[1:]) if state.last_completed_phase[1:].isdigit() else 0
    )
    if state_num != highest_done:
        return CheckResult(
            "state_consistency",
            False,
            f"state last_completed_phase P{state_num:02d} != ledger highest P{highest_done:02d}",
        )
    return CheckResult(
        "state_consistency",
        True,
        f"state matches ledger (last completed P{highest_done:02d})",
    )


def check_dependencies(
    phase_id: str,
    phases: dict[str, PhaseEntry],
    state: State,
    parked_phases: set[str] | None = None,
) -> CheckResult:
    """8.2d: every phase in ``depends_on`` is DONE and merged.

    A dependency that is PARKED, stopped or not merged is a STOP that names it.
    A PARKED or stopped phase outside ``depends_on`` does not block entry (8.2e).
    """
    if phase_id not in phases:
        return CheckResult("dependencies", False, f"unknown phase {phase_id!r}")
    deps = phases[phase_id].depends_on
    parked = parked_phases or set()
    completed_num = (
        int(state.last_completed_phase[1:]) if state.last_completed_phase[1:].isdigit() else 0
    )
    for dep in deps:
        if dep in parked:
            return CheckResult(
                "dependencies",
                False,
                f"dependency {dep} is PARKED (STOP: decide on {dep})",
            )
        dep_num = int(dep[1:]) if dep[1:].isdigit() else -1
        if dep_num > completed_num:
            return CheckResult(
                "dependencies",
                False,
                f"dependency {dep} is not done (last completed: {state.last_completed_phase})",
            )
    return CheckResult(
        "dependencies",
        True,
        f"all {len(deps)} dependencies done and merged",
    )


# ---------------------------------------------------------------------------
# Exit checks (Part 1 §9.1)
# ---------------------------------------------------------------------------


def _parse_ledger_done(repo_root: Path, phase_id: str) -> set[str]:
    """Return the set of task ids with DONE lines for *phase_id*."""
    ledger = repo_root / "docs" / "ledger" / f"{phase_id}.md"
    if not ledger.is_file():
        return set()
    done: set[str] = set()
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.endswith("DONE"):
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("P"):
                done.add(parts[0])
    return done


def check_done_lines(
    repo_root: Path,
    phase_id: str,
    expected_tasks: list[str],
) -> CheckResult:
    """9.1: every expected task has its DONE line in the ledger."""
    done = _parse_ledger_done(repo_root, phase_id)
    missing = [t for t in expected_tasks if t not in done]
    if missing:
        return CheckResult(
            "done_lines",
            False,
            f"missing DONE lines: {', '.join(missing)}",
        )
    return CheckResult(
        "done_lines",
        True,
        f"all {len(expected_tasks)} tasks have DONE lines",
    )


def check_task_commits(
    repo_root: Path,
    expected_tasks: list[str],
) -> CheckResult:
    """9.1: every expected task has its commit (by task id in the message)."""
    missing: list[str] = []
    for task in expected_tasks:
        # Search for a commit whose message contains the task id
        result = git_run(["log", "--all", "--format=%s", "--grep", task], repo_root)
        if task not in result.stdout:
            missing.append(task)
    if missing:
        return CheckResult(
            "task_commits",
            False,
            f"missing commits for: {', '.join(missing)}",
        )
    return CheckResult(
        "task_commits",
        True,
        f"all {len(expected_tasks)} tasks have commits",
    )


# ---------------------------------------------------------------------------
# Golden-commit check (Part 1 §4.8)
# ---------------------------------------------------------------------------


def check_golden_commit(
    repo_root: Path,
    commit_hash: str,
    golden_paths: list[str],
) -> CheckResult:
    """4.8: a commit that changes a golden file must contain only golden files.

    The commit message must have scope ``golden`` (``test(golden): <reason>``)
    and state a reason.  A golden file in the same commit as a non-golden
    source change is a failure.
    """
    files_out = _git_out(["show", "--name-only", "--format=", commit_hash], repo_root)
    files = [f.strip() for f in files_out.splitlines() if f.strip()]
    golden_changed = [f for f in files if f in golden_paths]
    if not golden_changed:
        return CheckResult(
            "golden_commit",
            True,
            "no golden files in this commit",
        )
    non_golden = [f for f in files if f not in golden_paths]
    if non_golden:
        return CheckResult(
            "golden_commit",
            False,
            f"commit {commit_hash[:8]} changes golden paths {golden_changed} "
            f"together with non-golden paths {non_golden}",
        )
    msg = _git_out(["show", "-s", "--format=%B", commit_hash], repo_root)
    first_line = msg.splitlines()[0] if msg else ""
    if not first_line.startswith("test(golden):"):
        return CheckResult(
            "golden_commit",
            False,
            f"commit {commit_hash[:8]} changes golden files but message "
            f"lacks 'test(golden):' scope; got {first_line!r}",
        )
    reason = first_line.split("test(golden):", 1)[1].strip()
    if not reason:
        return CheckResult(
            "golden_commit",
            False,
            f"commit {commit_hash[:8]} has scope golden but no reason",
        )
    return CheckResult(
        "golden_commit",
        True,
        f"commit {commit_hash[:8]} changes only golden files with reason",
    )


# ---------------------------------------------------------------------------
# Baseline check (wrapper returning CheckResult)
# ---------------------------------------------------------------------------


def check_baseline_decrease_result(
    baselines: dict[str, dict[str, float]],
    measured: dict[str, dict[str, float]],
) -> CheckResult:
    """Check that measured coverage is not below baselines."""
    decreases = check_baseline_decrease(baselines, measured)
    if decreases:
        return CheckResult(
            "baseline_decrease",
            False,
            "; ".join(decreases),
        )
    return CheckResult("baseline_decrease", True, "no baseline decreases")


# ---------------------------------------------------------------------------
# Report field validation (Part 1 §12)
# ---------------------------------------------------------------------------


def validate_report_fields(
    report: dict[str, object],
    required_fields: tuple[str, ...],
) -> list[str]:
    """Validate that *report* has exactly the required fields.

    Returns a list of error messages (empty = valid):
      - missing required field
      - extra field not in the required set
    """
    errors: list[str] = []
    for field_name in required_fields:
        if field_name not in report:
            errors.append(f"missing required field {field_name!r}")
    for field_name in report:
        if field_name not in required_fields:
            errors.append(f"extra field {field_name!r} not in required set")
    return errors


# ---------------------------------------------------------------------------
# Aggregate entry/exit (Part 1 §8.2 / §9.1)
# ---------------------------------------------------------------------------


def check_phase_entry(
    phase_id: str,
    phases: dict[str, PhaseEntry],
    state: State,
    directive_path: Path,
    repo_root: Path,
    branch_name: str | None = None,
    parked_phases: set[str] | None = None,
) -> list[CheckResult]:
    """Run all entry checks for *phase_id* (Part 1 §8.2)."""
    results: list[CheckResult] = []
    results.append(check_directive_hash(state, directive_path))
    results.append(check_state_consistency(state, repo_root))
    if phase_id == "P00":
        results.append(CheckResult("merge_proof", True, "no previous phase (first phase)"))
    else:
        results.append(check_merge_proof(repo_root))
    results.append(check_clean_tree(repo_root))
    if branch_name is not None:
        results.append(check_previous_branch_deleted(repo_root, branch_name))
    results.append(check_previous_merge_hash(state, repo_root))
    results.append(check_awaiting_merge_cleared(state))
    results.append(check_dependencies(phase_id, phases, state, parked_phases=parked_phases))
    return results


def check_phase_exit(
    phase_id: str,
    expected_tasks: list[str],
    repo_root: Path,
) -> list[CheckResult]:
    """Run all exit checks for *phase_id* (Part 1 §9.1)."""
    results: list[CheckResult] = []
    results.append(check_done_lines(repo_root, phase_id, expected_tasks))
    results.append(check_task_commits(repo_root, expected_tasks))
    results.append(check_clean_tree(repo_root))
    return results
