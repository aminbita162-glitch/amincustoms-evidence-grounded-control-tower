"""Tests for the index gate and golden path regeneration (P00-T04).

Tests T-GATE-0009 to T-GATE-0014 cover the index gate: missing header fields,
duplicate ids, stale index, unmarked tests, order-dependent detection, and
byte-identical regeneration.  Golden path tests cover refusal of out-of-list
paths, refusal of a dirty tree, and committing golden files alone.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tools.gate.gates.golden import regenerate
from tools.gate.gates.index import check_index, generate_index, write_index
from tools.gate.gates.seeds import run_under_seeds

REPO_ROOT = Path(__file__).resolve().parents[2]

# Five pinned seeds from docs/state/seeds.toml.
PINNED_SEEDS: list[int] = [11, 223, 3517, 48611, 590417]


def _write(path: Path, content: str) -> None:
    """Write *content* to *path*, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# A well-formed test file with a complete header.
_GOOD_TEST = """import pytest


@pytest.mark.fast
def test_good() -> None:
    \"\"\"id: T-GATE-GOOD
    title: Good test
    purpose: A well-formed test with a complete header
    level: fast
    requirement: P00-T04
    input: nothing
    expected: passes
    risk: none
    capability: none
    \"\"\"
    assert True
"""

# A test file missing several required header fields.
_BAD_TEST_MISSING = """import pytest


@pytest.mark.fast
def test_bad_missing() -> None:
    \"\"\"id: T-GATE-BAD1
    title: Bad test missing fields
    \"\"\"
    assert True
"""

# A test file with a duplicate id but a different header.
_DUP_TEST_A = """import pytest


@pytest.mark.fast
def test_dup_a() -> None:
    \"\"\"id: T-GATE-DUP
    title: Dup A
    purpose: First duplicate
    level: fast
    requirement: P00-T04
    input: nothing
    expected: passes
    risk: none
    capability: none
    \"\"\"
    assert True
"""

_DUP_TEST_B = """import pytest


@pytest.mark.fast
def test_dup_b() -> None:
    \"\"\"id: T-GATE-DUP
    title: Dup B
    purpose: Second duplicate
    level: fast
    requirement: P00-T04
    input: nothing
    expected: passes
    risk: none
    capability: none
    \"\"\"
    assert True
"""

# A test file without a speed-class marker.
_UNMARKED_TEST = """import pytest


def test_unmarked() -> None:
    \"\"\"id: T-GATE-UNMARKED
    title: Unmarked test
    purpose: A test without a speed marker
    level: fast
    requirement: P00-T04
    input: nothing
    expected: passes
    risk: none
    capability: none
    \"\"\"
    assert True
"""

# An order-dependent test file (test_c fails unless a and b ran first).
_ORDER_TEST = """import pytest

_order: list[str] = []


@pytest.mark.fast
def test_a() -> None:
    _order.append("a")


@pytest.mark.fast
def test_b() -> None:
    _order.append("b")


@pytest.mark.fast
def test_c() -> None:
    assert "a" in _order and "b" in _order, f"order: {_order}"
"""


# ---------------------------------------------------------------------------
# T-GATE-0009 — Missing header field fails
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_missing_header_field(tmp_path: Path) -> None:
    """id: T-GATE-0009
    title: Missing header field fails
    purpose: A test function missing a required header field is detected by the index gate
    level: fast
    requirement: P00-T04
    input: a temp test file with a test missing required header fields
    expected: check_index reports a violation for the missing field
    risk: a test with an incomplete header passes the index gate
    capability: none
    """
    test_dir = tmp_path / "test-house"
    _write(test_dir / "test_bad.py", _BAD_TEST_MISSING)
    violations = check_index(test_dir)
    assert any("missing required field" in v.message for v in violations), (
        f"expected a missing-field violation, got: {[v.message for v in violations]}"
    )


# ---------------------------------------------------------------------------
# T-GATE-0010 — Duplicate id fails
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_duplicate_id(tmp_path: Path) -> None:
    """id: T-GATE-0010
    title: Duplicate id fails
    purpose: Two test functions with the same id but different headers are detected
    level: fast
    requirement: P00-T04
    input: two temp test files with the same id but different headers
    expected: check_index reports a duplicate-id violation
    risk: two different tests share the same id without detection
    capability: none
    """
    test_dir = tmp_path / "test-house"
    _write(test_dir / "test_dup_a.py", _DUP_TEST_A)
    _write(test_dir / "test_dup_b.py", _DUP_TEST_B)
    violations = check_index(test_dir)
    assert any("duplicate id" in v.message for v in violations), (
        f"expected a duplicate-id violation, got: {[v.message for v in violations]}"
    )


# ---------------------------------------------------------------------------
# T-GATE-0011 — Stale index fails
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_stale_index(tmp_path: Path) -> None:
    """id: T-GATE-0011
    title: Stale index fails
    purpose: An INDEX.md that does not match the current test state is detected
    level: fast
    requirement: P00-T04
    input: a temp test directory with an out-of-date INDEX.md
    expected: check_index reports a stale-index violation
    risk: the test index is hand-written rather than generated
    capability: none
    """
    test_dir = tmp_path / "test-house"
    _write(test_dir / "test_good.py", _GOOD_TEST)
    write_index(test_dir)
    # Add a new test file — the existing INDEX.md is now stale.
    _write(test_dir / "test_extra.py", _GOOD_TEST.replace("T-GATE-GOOD", "T-GATE-EXTRA"))
    violations = check_index(test_dir)
    assert any("stale" in v.message.lower() for v in violations), (
        f"expected a stale-index violation, got: {[v.message for v in violations]}"
    )


# ---------------------------------------------------------------------------
# T-GATE-0012 — Unmarked test fails
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_unmarked_test(tmp_path: Path) -> None:
    """id: T-GATE-0012
    title: Unmarked test fails
    purpose: A test function without a speed-class marker is detected
    level: fast
    requirement: P00-T04
    input: a temp test file with a test that lacks @pytest.mark.fast/slow/e2e
    expected: check_index reports a missing-marker violation
    risk: a test runs without a speed class and exceeds its time budget
    capability: none
    """
    test_dir = tmp_path / "test-house"
    _write(test_dir / "test_unmarked.py", _UNMARKED_TEST)
    violations = check_index(test_dir)
    assert any("marker" in v.message.lower() for v in violations), (
        f"expected a missing-marker violation, got: {[v.message for v in violations]}"
    )


# ---------------------------------------------------------------------------
# T-GATE-0013 — Order-dependent fixture detected by repeat check
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_order_dependent_detected(tmp_path: Path) -> None:
    """id: T-GATE-0013
    title: Order-dependent fixture detected by repeat check
    purpose: Running an order-dependent test under different seeds catches at least one failure
    level: fast
    requirement: P00-T04
    input: a temp test file with three order-dependent tests run under five pinned seeds
    expected: at least one seed produces a non-zero exit code
    risk: an order-dependent test passes under every seed and hides a fixture leak
    capability: none
    """
    test_file = tmp_path / "test_order.py"
    _write(test_file, _ORDER_TEST)
    results = run_under_seeds(test_file, PINNED_SEEDS)
    failed = [r for r in results if r.exit_code != 0]
    assert len(failed) > 0, (
        f"expected at least one failure among seeds {PINNED_SEEDS}, "
        f"got: {[(r.seed, r.exit_code) for r in results]}"
    )


# ---------------------------------------------------------------------------
# T-GATE-0014 — Index is byte-identical on regeneration
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_index_byte_identical(tmp_path: Path) -> None:
    """id: T-GATE-0014
    title: Index is byte-identical on regeneration
    purpose: Generating the index twice produces the same bytes
    level: fast
    requirement: P00-T04
    input: a temp test directory scanned twice
    expected: both generated index strings are identical
    risk: the index is non-deterministic and changes between runs
    capability: none
    """
    test_dir = tmp_path / "test-house"
    _write(test_dir / "test_good.py", _GOOD_TEST)
    first = generate_index(test_dir)
    second = generate_index(test_dir)
    assert first == second, "index is not byte-identical on regeneration"


# ---------------------------------------------------------------------------
# T-GATE-GOLDEN-001 — Golden regenerate refuses a path outside the golden list
# ---------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    """Environment for git commands."""
    env = dict(os.environ)
    if "DEVELOPER_DIR" not in env:
        env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return env


def _init_repo(path: Path) -> None:
    """Initialise a git repo with a test identity."""
    env = _git_env()
    subprocess.run(["git", "init"], cwd=str(path), env=env, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(path),
        env=env,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path),
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.mark.fast
def test_golden_refuses_outside(tmp_path: Path) -> None:
    """id: T-GATE-GOLDEN-001
    title: Golden regenerate refuses a path outside the golden list
    purpose: A path not listed in golden-paths.toml is refused
    level: fast
    requirement: P00-T04
    input: a temp git repo with golden-paths.toml listing only golden.txt
    expected: regenerate returns 1 for a path not in the list
    risk: an unlisted file is committed as a golden file
    capability: none
    """
    _init_repo(tmp_path)
    _write(tmp_path / "golden-paths.toml", 'paths = ["golden.txt"]\n')
    _write(tmp_path / "other.txt", "content\n")
    code = regenerate(
        ["other.txt"],
        "reason",
        "P00-T04",
        tmp_path / "golden-paths.toml",
        tmp_path,
    )
    assert code == 1


# ---------------------------------------------------------------------------
# T-GATE-GOLDEN-002 — Golden regenerate refuses a dirty tree
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_golden_refuses_dirty(tmp_path: Path) -> None:
    """id: T-GATE-GOLDEN-002
    title: Golden regenerate refuses a dirty tree
    purpose: A tree with non-golden uncommitted changes is refused
    level: fast
    requirement: P00-T04
    input: a temp git repo with a dirty golden file and a dirty non-golden file
    expected: regenerate returns 1 because the tree has non-golden changes
    risk: a golden commit includes non-golden changes
    capability: none
    """
    _init_repo(tmp_path)
    _write(tmp_path / "golden-paths.toml", 'paths = ["golden.txt"]\n')
    _write(tmp_path / "golden.txt", "old\n")
    _write(tmp_path / "other.txt", "old\n")
    env = _git_env()
    subprocess.run(
        ["git", "add", "-A"], cwd=str(tmp_path), env=env, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path),
        env=env,
        check=True,
        capture_output=True,
    )
    # Modify both files — only golden.txt should be dirty for regenerate.
    _write(tmp_path / "golden.txt", "new\n")
    _write(tmp_path / "other.txt", "new\n")
    code = regenerate(
        ["golden.txt"],
        "reason",
        "P00-T04",
        tmp_path / "golden-paths.toml",
        tmp_path,
    )
    assert code == 1


# ---------------------------------------------------------------------------
# T-GATE-GOLDEN-003 — Golden regenerate commits golden files alone
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_golden_commits_alone(tmp_path: Path) -> None:
    """id: T-GATE-GOLDEN-003
    title: Golden regenerate commits golden files alone
    purpose: A successful regenerate commits only the golden file with the right message
    level: fast
    requirement: P00-T04
    input: a temp git repo with a dirty golden file and no other changes
    expected: regenerate returns 0 and the commit contains only golden.txt
    risk: a golden commit includes other files or has the wrong message format
    capability: none
    """
    _init_repo(tmp_path)
    _write(tmp_path / "golden-paths.toml", 'paths = ["golden.txt"]\n')
    _write(tmp_path / "golden.txt", "old\n")
    env = _git_env()
    subprocess.run(
        ["git", "add", "-A"], cwd=str(tmp_path), env=env, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path),
        env=env,
        check=True,
        capture_output=True,
    )
    # Modify only the golden file.
    _write(tmp_path / "golden.txt", "new\n")
    code = regenerate(
        ["golden.txt"],
        "update golden",
        "P00-T04",
        tmp_path / "golden-paths.toml",
        tmp_path,
    )
    assert code == 0
    # Verify the commit contains only golden.txt.
    show = subprocess.run(
        ["git", "show", "--stat", "--oneline", "HEAD"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "golden.txt" in show.stdout
    assert "test(golden): update golden [P00-T04]" in show.stdout
    # Ensure no other file was committed in this commit.
    diff = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    changed = [line.strip() for line in diff.stdout.strip().splitlines() if line.strip()]
    assert changed == ["golden.txt"], f"expected only golden.txt, got: {changed}"
