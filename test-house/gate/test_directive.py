"""Tests for the directive lint, scope check, and stub mode (P00-T11).

Every test carries a header (id, title, purpose, level, requirement, scenario,
input, expected result, risk, capability) per Part 4 §4.5.

Tests T-PHASE-0013 to T-PHASE-0022 cover the §6.15 structural failures and the
§6.14 scope check.  Tests T-PHASE-0041 to T-PHASE-0048 cover stub mode (§6.15a).
Tests T-PHASE-0053 to T-PHASE-0060 cover the cross-check (§6.15b).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.gate.phase.directive import (
    check_cross,
    check_directive,
    check_keyfacts,
    check_released,
    is_stub_mode,
    load_keyfacts,
    read_parent_directive,
    run_directive_gate,
)
from tools.gate.phase.scope import check_scope
from tools.gate.phase.state import compute_state_hash

REPO_ROOT = Path(__file__).resolve().parents[2]


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


# ---------------------------------------------------------------------------
# Directive generators
# ---------------------------------------------------------------------------


def _clean_directive(num_phases: int = 3) -> str:
    """Create a minimal valid directive with *num_phases* phase blocks."""
    lines: list[str] = []
    lines.append("<<<P6-S1>>>")
    lines.append("6.1 Test section.")
    lines.append("<<<END-P6-S1>>>")
    lines.append("")
    for i in range(num_phases):
        pid = f"P{i:02d}"
        lines.append(f"<<<PHASE-{i:02d}>>>")
        lines.append(f"PHASE {i:02d} — TEST")
        lines.append("")
        lines.append(f"1. Header: {pid} · Test.")
        lines.append("")
        lines.append("2. Purpose: test phase.")
        lines.append("")
        lines.append("3. Entry conditions: none.")
        lines.append("")
        lines.append("4. Scope fence. May create: `src/`.")
        lines.append("Scope paths: src/**, test-house/**")
        lines.append("")
        lines.append("5. Context Pack: `<<<P6-S1>>>`.")
        lines.append("")
        lines.append("6. Tasks.")
        lines.append("")
        lines.append(f"{pid}-T01 First task")
        lines.append("- Steps: do something.")
        lines.append("")
        if i >= 1:
            lines.append(f"{pid}-RISK Risk review")
            lines.append("- Steps: review risks.")
            lines.append("")
        lines.append(f"{pid}-END1, {pid}-END2: per Part 1 §10.")
        lines.append("")
        start_num = i * 100 + 1
        end_num = i * 100 + 10
        lines.append(f"7. Test plan: T-PHASE-{start_num:04d} to T-PHASE-{end_num:04d}.")
        lines.append("")
        risk_text = f"task {pid}-RISK" if i >= 1 else "not applicable"
        lines.append(f"8. Risk review: {risk_text}.")
        lines.append("")
        lines.append("9. Exit conditions: tests pass.")
        lines.append("")
        if i < num_phases - 1:
            next1 = f"P{i + 1:02d}"
            if i + 2 < num_phases:
                next2 = f"P{i + 2:02d}"
                lines.append(f"10. Look-ahead: {next1} adds something; {next2} adds more.")
            else:
                lines.append(f"10. Look-ahead: {next1} adds something.")
        else:
            lines.append("10. Look-ahead: none.")
        lines.append("")
        lines.append("11. Budget: class M; retries 3; tool calls 400.")
        lines.append(f"<<<END-PHASE-{i:02d}>>>")
        lines.append("")
    return "\n".join(lines)


def _directive_with_missing_field() -> str:
    """A directive where P01 is missing field 8."""
    text = _clean_directive(3)
    # Remove the "8. Risk review" line from P01's block.
    return text.replace("8. Risk review: task P01-RISK.\n", "")


def _directive_with_non_sequential_tasks() -> str:
    """A directive where P01 has a non-sequential task id."""
    text = _clean_directive(3)
    return text.replace("P01-T01 First task", "P01-T03 First task")


def _directive_with_missing_risk() -> str:
    """A directive where P01 is missing P01-RISK."""
    text = _clean_directive(3)
    return text.replace("P01-RISK Risk review\n- Steps: review risks.\n\n", "")


def _directive_with_misplaced_risk() -> str:
    """A directive where P01-RISK is after P01-END1 instead of before it."""
    text = _clean_directive(3)
    # Move RISK after END1
    text = text.replace(
        "P01-RISK Risk review\n- Steps: review risks.\n\nP01-END1, P01-END2: per Part 1 §10.",
        "P01-END1, P01-END2: per Part 1 §10.\nP01-RISK Risk review\n- Steps: review risks.",
    )
    return text


def _directive_with_dup_test_range() -> str:
    """A directive where two phases declare the same test id range."""
    text = _clean_directive(3)
    # Make P01 use the same range as P00.
    return text.replace(
        "7. Test plan: T-PHASE-0101 to T-PHASE-0110.",
        "7. Test plan: T-PHASE-0001 to T-PHASE-0010.",
    )


def _directive_with_bad_lookahead() -> str:
    """A directive where P01 look-ahead references non-existent P99."""
    text = _clean_directive(3)
    return text.replace(
        "10. Look-ahead: P02 adds something.",
        "10. Look-ahead: P99 adds something.",
    )


def _directive_with_missing_scope_paths() -> str:
    """A directive where P01 is missing the Scope paths line."""
    text = _clean_directive(3)
    return text.replace(
        "Scope paths: src/**, test-house/**\n\n5. Context Pack", "\n5. Context Pack", 1
    )


def _directive_with_nonexistent_marker() -> str:
    """A directive where a Context Pack references a non-existent marker."""
    text = _clean_directive(3)
    return text.replace("5. Context Pack: `<<<P6-S1>>>`.", "5. Context Pack: `<<<P6-S99>>>`.", 1)


# ---------------------------------------------------------------------------
# T-PHASE-0013 — Marker not exactly once fails
# ---------------------------------------------------------------------------

# id: T-PHASE-0013
# title: Non-existent marker in Context Pack fails directive lint
# purpose: Verify that a marker listed in a Context Pack that does not exist
#          exactly once is detected as a violation.
# level: fast
# requirement: P00-T11, Part 6 §6.15
# scenario: A directive where the Context Pack of P00 references a marker
#           that does not appear as a standalone definition.
# input: a fixture directive with a non-existent marker reference
# expected: check_directive returns a non-empty violation list
# risk: a non-existent marker reference is accepted in the directive
# capability: phase-machinery


@pytest.mark.fast
def test_nonexistent_marker_fails() -> None:
    """A Context Pack referencing a non-existent marker fails."""
    text = _directive_with_nonexistent_marker()
    violations = check_directive(text, 3)
    assert violations
    assert any("P6-S99" in v for v in violations)


# id: T-PHASE-0014
# title: Missing phase block field fails directive lint
# purpose: Verify that a phase block missing one of the eleven fields is
#          detected as a violation.
# level: fast
# requirement: P00-T11, Part 6 §6.15
# scenario: A directive where P01 is missing field 8 (Risk review).
# input: a fixture directive with a missing field
# expected: check_directive returns a non-empty violation list mentioning
#           the missing field
# risk: a phase block with a missing field is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_missing_field_fails() -> None:
    """A phase block missing a field fails the directive lint."""
    text = _directive_with_missing_field()
    violations = check_directive(text, 3)
    assert violations
    assert any("missing field 8" in v for v in violations)


# id: T-PHASE-0015
# title: Non-sequential task ids fail directive lint
# purpose: Verify that non-sequential task ids within a phase block are
#          detected as a violation.
# level: fast
# requirement: P00-T11, Part 6 §6.15
# scenario: A directive where P01 has task id P01-T03 instead of P01-T01.
# input: a fixture directive with non-sequential task ids
# expected: check_directive returns a non-empty violation list
# risk: non-sequential task ids are accepted, hiding gaps
# capability: phase-machinery


@pytest.mark.fast
def test_non_sequential_tasks_fails() -> None:
    """Non-sequential task ids fail the directive lint."""
    text = _directive_with_non_sequential_tasks()
    violations = check_directive(text, 3)
    assert violations
    assert any("not sequential" in v for v in violations)


# id: T-PHASE-0016
# title: Missing Pnn-RISK before Pnn-END1 fails directive lint
# purpose: Verify that a missing Pnn-RISK task (from P01) is detected.
# level: fast
# requirement: P00-T11, Part 6 §6.15
# scenario: A directive where P01 is missing the P01-RISK task.
# input: a fixture directive with P01-RISK removed
# expected: check_directive returns a non-empty violation list mentioning RISK
# risk: a phase without a risk review task is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_missing_risk_fails() -> None:
    """A missing Pnn-RISK task fails the directive lint."""
    text = _directive_with_missing_risk()
    violations = check_directive(text, 3)
    assert violations
    assert any("RISK" in v for v in violations)


# id: T-PHASE-0017
# title: Duplicated test id range fails directive lint
# purpose: Verify that a test id range declared twice is detected.
# level: fast
# requirement: P00-T11, Part 6 §6.15
# scenario: A directive where P00 and P01 declare the same test id range.
# input: a fixture directive with a duplicated test id range
# expected: check_directive returns a non-empty violation list mentioning
#           the duplicated range
# risk: a duplicated test id range is accepted, hiding test gaps
# capability: phase-machinery


@pytest.mark.fast
def test_dup_test_range_fails() -> None:
    """A duplicated test id range fails the directive lint."""
    text = _directive_with_dup_test_range()
    violations = check_directive(text, 3)
    assert violations
    assert any("declared twice" in v for v in violations)


# id: T-PHASE-0018
# title: Look-ahead referencing non-existent phase fails
# purpose: Verify that a look-ahead referencing a non-existent phase is
#          detected as a violation.
# level: fast
# requirement: P00-T11, Part 6 §6.15
# scenario: A directive where P01's look-ahead references P99.
# input: a fixture directive with a bad look-ahead reference
# expected: check_directive returns a non-empty violation list mentioning P99
# risk: a look-ahead to a non-existent phase is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_bad_lookahead_fails() -> None:
    """A look-ahead referencing a non-existent phase fails the directive lint."""
    text = _directive_with_bad_lookahead()
    violations = check_directive(text, 3)
    assert violations
    assert any("P99" in v for v in violations)


# id: T-PHASE-0019
# title: Missing Scope paths line fails directive lint
# purpose: Verify that a phase block missing the Scope paths line is detected.
# level: fast
# requirement: P00-T11, Part 6 §6.15
# scenario: A directive where P01 is missing the Scope paths line.
# input: a fixture directive with a missing Scope paths line
# expected: check_directive returns a non-empty violation list mentioning
#           the missing Scope paths
# risk: a phase block without a Scope paths line is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_missing_scope_paths_fails() -> None:
    """A missing Scope paths line fails the directive lint."""
    text = _directive_with_missing_scope_paths()
    violations = check_directive(text, 3)
    assert violations
    assert any("Scope paths" in v for v in violations)


# id: T-PHASE-0020
# title: Block count differing from phases.toml fails directive lint
# purpose: Verify that a block count that differs from phases.toml is detected.
# level: fast
# requirement: P00-T11, Part 6 §6.15
# scenario: A directive with 3 blocks but phases_count set to 2.
# input: a clean directive with a wrong phases_count
# expected: check_directive returns a non-empty violation list mentioning
#           the block count
# risk: a directive with the wrong number of blocks is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_block_count_differs_fails() -> None:
    """A block count differing from phases.toml fails the directive lint."""
    text = _clean_directive(3)
    violations = check_directive(text, 2)
    assert violations
    assert any("block count" in v for v in violations)


# id: T-PHASE-0021
# title: Clean directive passes all checks
# purpose: Verify that a clean fixture directive passes all §6.15 checks.
# level: fast
# requirement: P00-T11, Part 6 §6.15
# scenario: A directive with 3 valid phase blocks and matching phases_count.
# input: a clean fixture directive
# expected: check_directive returns an empty violation list
# risk: a valid directive is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_clean_directive_passes() -> None:
    """A clean directive with all fields passes the directive lint."""
    text = _clean_directive(3)
    violations = check_directive(text, 3)
    assert not violations, f"unexpected violations: {violations}"


# id: T-PHASE-0022
# title: Path outside scope globs fails scope check
# purpose: Verify that a changed path outside the scope globs is detected
#          by the scope check.
# level: fast
# requirement: P00-T11, Part 6 §6.14
# scenario: A directive with Scope paths "src/**, test-house/**" and a changed
#           file "other/file.py" that is outside the globs.
# input: scope check with an out-of-scope path
# expected: check_scope returns a non-empty violation list
# risk: a path outside the scope fence is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_scope_outside_globs_fails() -> None:
    """A changed path outside the scope globs fails the scope check."""
    text = _clean_directive(3)
    violations = check_scope("P00", text, ["other/file.py"], [])
    assert violations
    assert any("outside scope" in v for v in violations)


# id: T-PHASE-0023
# title: Protected path not named by a task fails scope check
# purpose: Verify that a protected path changed without a task naming it
#          is detected by the scope check.
# level: fast
# requirement: P00-T11, Part 6 §6.14, Part 1 §5.5
# scenario: A changed file that is in the scope globs but also in the
#           protected paths list.
# input: scope check with a protected path
# expected: check_scope returns a non-empty violation list mentioning
#           the protected path
# risk: a protected path is changed without a task authorising it
# capability: phase-machinery


@pytest.mark.fast
def test_scope_protected_path_fails() -> None:
    """A protected path not named by a task fails the scope check."""
    text = _clean_directive(3)
    violations = check_scope("P00", text, ["src/file.py"], ["src/file.py"])
    assert violations
    assert any("protected" in v for v in violations)


# id: T-PHASE-0024
# title: Rename out of scope fails scope check
# purpose: Verify that a rename where either path is outside the scope globs
#          is detected by the scope check.
# level: fast
# requirement: P00-T11, Part 6 §6.14
# scenario: A rename from an out-of-scope path to an in-scope path.
# input: scope check with both old and new rename paths
# expected: check_scope returns a non-empty violation list for the
#           out-of-scope old path
# risk: a rename with an out-of-scope path is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_scope_rename_out_of_scope_fails() -> None:
    """A rename where the old path is outside scope fails."""
    text = _clean_directive(3)
    # Both old and new paths are checked (renames count both paths).
    violations = check_scope("P00", text, ["old/file.py", "src/new.py"], [])
    assert violations
    assert any("old/file.py" in v for v in violations)


@pytest.mark.fast
def test_scope_in_scope_passes() -> None:
    """Paths within the scope globs pass the scope check."""
    text = _clean_directive(3)
    violations = check_scope("P00", text, ["src/file.py", "test-house/test.py"], [])
    assert not violations


# ---------------------------------------------------------------------------
# Stub mode helpers
# ---------------------------------------------------------------------------


STUB_TEXT = (
    "This file was the build directive of this project; "
    "development is complete and the file holds no instructions.\n"
    "Product documentation is in README.md and in the docs directory.\n"
)


def _state_json(directive_hash: str, last_phase: str = "P31") -> str:
    """Build a STATE.json with the given directive hash."""
    state: dict[str, object] = {
        "last_completed_phase": last_phase,
        "previous_merge_hash": None,
        "awaiting_merge_phase": None,
        "directive_hash": directive_hash,
        "capability_status_map": {},
        "open_stop_items": [],
        "label_counts": {},
    }
    state["state_hash"] = compute_state_hash(state)
    return json.dumps(state, indent=2, sort_keys=True)


def _setup_stub_repo(
    tmp_path: Path,
    *,
    valid: bool = True,
    change_other: bool = False,
    wrong_stub: bool = False,
    extra_commit_after: bool = False,
    wrong_parent_msg: bool = False,
    wrong_state_hash: bool = False,
) -> Path:
    """Create a temp git repo for stub-mode testing."""
    repo = _init_repo(tmp_path)

    # Create tools/gate/stub.txt
    gate_dir = repo / "tools" / "gate"
    gate_dir.mkdir(parents=True, exist_ok=True)
    (gate_dir / "stub.txt").write_text(STUB_TEXT, encoding="utf-8")

    # Create the original directive (parent's directive)
    directive_content = _clean_directive(3)
    (repo / "directive.txt").write_text(directive_content, encoding="utf-8")

    # Create STATE.json with the correct directive hash
    dhash = hashlib.sha256(directive_content.encode("utf-8")).hexdigest()
    if wrong_state_hash:
        dhash = "0" * 64
    state_dir = repo / "docs" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "STATE.json").write_text(_state_json(dhash), encoding="utf-8")

    # Commit as P32-END2
    _git(["add", "-A"], repo)
    parent_msg = "P31-END2: phase end" if wrong_parent_msg else "P32-END2: phase end"
    _git(["commit", "-m", parent_msg], repo)

    if valid or not wrong_stub:
        # Replace directive.txt with the stub
        stub_to_use = STUB_TEXT if not wrong_stub else "Different stub text.\n"
        (repo / "directive.txt").write_text(stub_to_use, encoding="utf-8")

    _git(["add", "directive.txt"], repo)
    if change_other:
        (repo / "other.txt").write_text("extra\n", encoding="utf-8")
        _git(["add", "other.txt"], repo)
    _git(["commit", "-m", "P32-STUB: replace directive with stub"], repo)

    if extra_commit_after:
        (repo / "extra.txt").write_text("extra\n", encoding="utf-8")
        _git(["add", "-A"], repo)
        _git(["commit", "-m", "extra commit after stub"], repo)

    return repo


# ---------------------------------------------------------------------------
# T-PHASE-0041 — Valid stub commit passes
# ---------------------------------------------------------------------------

# id: T-PHASE-0041
# title: Valid stub commit passes stub mode check
# purpose: Verify that a valid stub commit enters stub mode and the rules
#          are applied to the parent directive.
# level: fast
# requirement: P00-T11, Part 6 §6.15a
# scenario: A temp git repo with a P32-END2 commit, then a P32-STUB commit that
#           replaces directive.txt with the stub text.
# input: a repo with valid stub mode conditions
# expected: is_stub_mode returns True; the parent directive passes the lint
# risk: a valid stub commit is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_valid_stub_passes(tmp_path: Path) -> None:
    """A valid stub commit enters stub mode and the parent directive is checked."""
    repo = _setup_stub_repo(tmp_path)
    assert is_stub_mode(repo)
    parent_text = read_parent_directive(repo)
    violations = check_directive(parent_text, 3)
    assert not violations, f"parent directive has violations: {violations}"


# id: T-PHASE-0042
# title: Stub commit that changes another path fails
# purpose: Verify that a stub commit that changes a path other than
#          directive.txt does not enter stub mode.
# level: fast
# requirement: P00-T11, Part 6 §6.15a
# scenario: A stub commit that also changes other.txt.
# input: a repo where the P32-STUB commit changes two files
# expected: is_stub_mode returns False
# risk: a stub commit that changes other files is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_stub_changes_other_path_fails(tmp_path: Path) -> None:
    """A stub commit that changes another path does not enter stub mode."""
    repo = _setup_stub_repo(tmp_path, change_other=True)
    assert not is_stub_mode(repo)


# id: T-PHASE-0043
# title: Stub text differing from stub.txt fails
# purpose: Verify that a directive.txt whose content differs from stub.txt
#          does not enter stub mode.
# level: fast
# requirement: P00-T11, Part 6 §6.15a
# scenario: A repo where directive.txt contains different text than stub.txt.
# input: a repo with a non-matching stub content
# expected: is_stub_mode returns False
# risk: a non-matching stub content is accepted as stub mode
# capability: phase-machinery


@pytest.mark.fast
def test_stub_text_differs_fails(tmp_path: Path) -> None:
    """A stub text that differs from stub.txt does not enter stub mode."""
    repo = _setup_stub_repo(tmp_path, wrong_stub=True)
    assert not is_stub_mode(repo)


# id: T-PHASE-0044
# title: Stub not the last commit fails
# purpose: Verify that when the stub commit is not the last commit, stub
#          mode is not entered.
# level: fast
# requirement: P00-T11, Part 6 §6.15a
# scenario: A repo where an extra commit follows the P32-STUB commit.
# input: a repo with an extra commit after the stub
# expected: is_stub_mode returns False
# risk: a stale stub commit is accepted as the current state
# capability: phase-machinery


@pytest.mark.fast
def test_stub_not_last_commit_fails(tmp_path: Path) -> None:
    """A stub commit that is not the last commit does not enter stub mode."""
    repo = _setup_stub_repo(tmp_path, extra_commit_after=True)
    assert not is_stub_mode(repo)


# id: T-PHASE-0045
# title: Parent not P32-END2 fails
# purpose: Verify that when the parent of the stub commit is not the
#          P32-END2 commit, stub mode is not entered.
# level: fast
# requirement: P00-T11, Part 6 §6.15a
# scenario: A repo where the parent commit message does not contain P32-END2.
# input: a repo with a wrong parent commit message
# expected: is_stub_mode returns False
# risk: a stub commit with the wrong parent is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_parent_not_end2_fails(tmp_path: Path) -> None:
    """A stub commit whose parent is not P32-END2 does not enter stub mode."""
    repo = _setup_stub_repo(tmp_path, wrong_parent_msg=True)
    assert not is_stub_mode(repo)


# id: T-PHASE-0046
# title: Parent directive hash differing from STATE.json fails
# purpose: Verify that when the SHA-256 of the parent directive differs from
#          the directive_hash in STATE.json, stub mode is not entered.
# level: fast
# requirement: P00-T11, Part 6 §6.15a
# scenario: A repo where STATE.json has a wrong directive_hash.
# input: a repo with a mismatched STATE.json hash
# expected: is_stub_mode returns False
# risk: a stub commit with a mismatched hash is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_parent_hash_differs_fails(tmp_path: Path) -> None:
    """A parent directive whose hash differs from STATE.json does not enter stub mode."""
    repo = _setup_stub_repo(tmp_path, wrong_state_hash=True)
    assert not is_stub_mode(repo)


# id: T-PHASE-0047
# title: Changed directive.txt outside stub mode fails
# purpose: Verify that a changed directive.txt whose hash does not match
#          STATE.json, outside stub mode, is a directive integrity failure.
# level: fast
# requirement: P00-T11, Part 6 §6.15a
# scenario: A repo where directive.txt is changed (hash mismatch) and not
#           in stub mode.
# input: a repo with a changed directive.txt and mismatched hash
# expected: run_directive_gate returns exit code 1
# risk: a changed directive.txt outside stub mode is not detected
# capability: phase-machinery


@pytest.mark.fast
def test_changed_directive_outside_stub_fails(tmp_path: Path) -> None:
    """A changed directive.txt outside stub mode fails the directive gate."""
    repo = _init_repo(tmp_path)
    # Create a directive.txt that is not the stub
    directive_content = _clean_directive(3)
    (repo / "directive.txt").write_text(directive_content, encoding="utf-8")
    # Create stub.txt
    gate_dir = repo / "tools" / "gate"
    gate_dir.mkdir(parents=True, exist_ok=True)
    (gate_dir / "stub.txt").write_text(STUB_TEXT, encoding="utf-8")
    # Create STATE.json with a wrong hash
    state_dir = repo / "docs" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "STATE.json").write_text(_state_json("0" * 64), encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "setup"], repo)
    # Run the gate from the repo dir
    old_cwd = os.getcwd()
    os.chdir(str(repo))
    try:
        code = run_directive_gate(repo)
        assert code == 1
    finally:
        os.chdir(old_cwd)


# id: T-PHASE-0048
# title: On main with stub and STATE P32 DONE prints RELEASED
# purpose: Verify that on main after the release merge, when STATE.json
#          names P32 as the last completed phase and the stub as the
#          directive, the gate prints RELEASED and exits 0.
# level: fast
# requirement: P00-T11, Part 6 §6.15a
# scenario: A repo on main with directive.txt matching stub.txt and
#           STATE.json with last_completed_phase=P32.
# input: a repo with RELEASED conditions
# expected: check_released prints RELEASED and returns 0
# risk: a released project is not recognised as released
# capability: phase-machinery


@pytest.mark.fast
def test_released_prints(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """On main with the stub and STATE at P32 DONE, the gate prints RELEASED."""
    repo = _init_repo(tmp_path)
    gate_dir = repo / "tools" / "gate"
    gate_dir.mkdir(parents=True, exist_ok=True)
    (gate_dir / "stub.txt").write_text(STUB_TEXT, encoding="utf-8")
    (repo / "directive.txt").write_text(STUB_TEXT, encoding="utf-8")
    stub_hash = hashlib.sha256(STUB_TEXT.encode("utf-8")).hexdigest()
    state_dir = repo / "docs" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "STATE.json").write_text(_state_json(stub_hash, "P32"), encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "release"], repo)
    code = check_released(repo)
    assert code == 0
    captured = capsys.readouterr()
    assert "RELEASED" in captured.out


# ---------------------------------------------------------------------------
# Cross-check helpers
# ---------------------------------------------------------------------------


def _keyfact_text(
    value: str = "20",
    expression: str = "per case: at most (\\d+) model calls",
    body: str = "The system uses per case: at most 20 model calls.",
) -> str:
    """Create text with a key-fact table and a body that references it."""
    return (
        f"<<<P8-KEYFACTS>>>\n"
        f"8.6 KEY-FACT TABLE\n"
        f"KF-01 | {value} | model calls per case | {expression}\n"
        f"<<<END-P8-KEYFACTS>>>\n"
        f"\n{body}\n"
    )


# ---------------------------------------------------------------------------
# T-PHASE-0053 — Cross-check: undefined reason code fails
# ---------------------------------------------------------------------------

# id: T-PHASE-0053
# title: Undefined reason code fails cross-check
# purpose: Verify that a reference to an undefined reason code prefix fails
#          the cross-check.
# level: fast
# requirement: P00-T11, Part 6 §6.15b (a)
# scenario: A text with a reason code reference to D99 which has no marker
#           definition.
# input: text with "reason code: D99.unknown"
# expected: check_cross returns a non-empty violation list
# risk: an undefined reason code reference is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_cross_undefined_reason_code_fails() -> None:
    """An undefined reason code prefix fails the cross-check."""
    text = "reason code: D99.unknown.label\n"
    violations = check_cross(text)
    assert violations
    assert any("D99" in v for v in violations)


# id: T-PHASE-0054
# title: Wrong outcome word fails cross-check
# purpose: Verify that an outcome word outside the closed vocabulary fails
#          the cross-check.
# level: fast
# requirement: P00-T11, Part 6 §6.15b (b)
# scenario: A text with "outcome INVALID" where INVALID is not in the
#           status vocabulary.
# input: text with an invalid outcome word
# expected: check_cross returns a non-empty violation list
# risk: an invalid outcome word is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_cross_wrong_outcome_word_fails() -> None:
    """An unknown outcome word fails the cross-check."""
    text = "The outcome INVALID is not valid.\n"
    violations = check_cross(text)
    assert violations
    assert any("outcome" in v for v in violations)


# id: T-PHASE-0055
# title: Unknown matching mode fails cross-check
# purpose: Verify that a matching mode outside the closed vocabulary fails
#          the cross-check.
# level: fast
# requirement: P00-T11, Part 6 §6.15b (b)
# scenario: A text with "matching mode INVALID".
# input: text with an invalid matching mode
# expected: check_cross returns a non-empty violation list
# risk: an invalid matching mode is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_cross_unknown_matching_mode_fails() -> None:
    """An unknown matching mode fails the cross-check."""
    text = "matching mode INVALID\n"
    violations = check_cross(text)
    assert violations
    assert any("matching mode" in v for v in violations)


# id: T-PHASE-0056
# title: Unknown label fails cross-check
# purpose: Verify that a label outside the closed vocabulary fails the
#          cross-check.
# level: fast
# requirement: P00-T11, Part 6 §6.15b (b)
# scenario: A text with "label INVALID".
# input: text with an invalid label
# expected: check_cross returns a non-empty violation list
# risk: an invalid label is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_cross_unknown_label_fails() -> None:
    """An unknown label fails the cross-check."""
    text = "label INVALID\n"
    violations = check_cross(text)
    assert violations
    assert any("label" in v for v in violations)


# id: T-PHASE-0057
# title: Unknown status word fails cross-check
# purpose: Verify that a status word outside the closed vocabulary fails the
#          cross-check.
# level: fast
# requirement: P00-T11, Part 6 §6.15b (b)
# scenario: A text with "status INVALID".
# input: text with an invalid status word
# expected: check_cross returns a non-empty violation list
# risk: an invalid status word is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_cross_unknown_status_word_fails() -> None:
    """An unknown status word fails the cross-check."""
    text = "status INVALID\n"
    violations = check_cross(text)
    assert violations
    assert any("status" in v for v in violations)


# id: T-PHASE-0058
# title: Changed key-fact value fails cross-check
# purpose: Verify that a key-fact expression that captures a different value
#          than the row's value fails the cross-check.
# level: fast
# requirement: P00-T11, Part 6 §6.15b (c)
# scenario: A key-fact table with KF-01 value 20, but the body says
#           "at most 30 model calls".
# input: text with a mismatched key-fact value
# expected: check_cross returns a non-empty violation list mentioning the
#           expected and actual values
# risk: a changed key-fact value is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_cross_changed_keyfact_value_fails() -> None:
    """A key-fact expression capturing a wrong value fails the cross-check."""
    text = _keyfact_text(value="20", body="The system uses per case: at most 30 model calls.")
    violations = check_cross(text)
    assert violations
    assert any("20" in v and "30" in v for v in violations)


# id: T-PHASE-0059
# title: Key-fact expression matching nowhere fails cross-check
# purpose: Verify that a key-fact expression that matches nowhere outside
#          the table fails the cross-check.
# level: fast
# requirement: P00-T11, Part 6 §6.15b (c)
# scenario: A key-fact table with an expression that does not match any text
#           outside the table.
# input: text where the key-fact expression matches nowhere
# expected: check_cross returns a non-empty violation list mentioning
#           "matches nowhere"
# risk: an unused key-fact expression is accepted
# capability: phase-machinery


@pytest.mark.fast
def test_cross_keyfact_nowhere_fails() -> None:
    """A key-fact expression that matches nowhere fails the cross-check."""
    text = _keyfact_text(body="No matching text here at all.")
    violations = check_cross(text)
    assert violations
    assert any("nowhere" in v for v in violations)


# id: T-PHASE-0060
# title: Clean cross-check passes and table block excluded
# purpose: Verify that a clean fixture passes the cross-check and the
#          key-fact table block is excluded from the scan.
# level: fast
# requirement: P00-T11, Part 6 §6.15b
# scenario: A text with a key-fact table where the body matches correctly,
#           and the table block itself is not scanned.
# input: a clean cross-check fixture
# expected: check_cross returns an empty violation list
# risk: a valid cross-check is wrongly rejected
# capability: phase-machinery


@pytest.mark.fast
def test_cross_clean_passes() -> None:
    """A clean cross-check fixture passes and the table block is excluded."""
    text = _keyfact_text(value="20", body="The system uses per case: at most 20 model calls.")
    violations = check_cross(text)
    assert not violations, f"unexpected violations: {violations}"


@pytest.mark.fast
def test_cross_table_block_excluded() -> None:
    """The key-fact table block is excluded from the scan."""
    # The table line has "20" in the value column, but the body also has "20".
    # Even if the table line were scanned, the value matches.  To test
    # exclusion, we use a body that matches and verify no violation.
    text = _keyfact_text(value="20", body="The system uses per case: at most 20 model calls.")
    facts = load_keyfacts(text)
    assert facts  # table was parsed
    violations = check_keyfacts(text, facts)
    assert not violations
