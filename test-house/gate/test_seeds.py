"""Tests for seed management and flakiness detection (P00-T04).

Tests T-GATE-0035 to T-GATE-0038 cover: order-dependent tests caught under
pinned seeds, same-seed reproducibility, ``gate seeds add`` appending a
regression seed with its test id, and hand-edited seeds.toml failing
verification.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.gate.gates.seeds import (
    SeedsConfig,
    add_seed,
    all_seeds,
    fresh_seed,
    load_seeds,
    run_under_seeds,
    save_seeds,
    verify_seeds,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Five pinned seeds from docs/state/seeds.toml.
PINNED_SEEDS: list[int] = [11, 223, 3517, 48611, 590417]

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

# A simple deterministic test file (always passes).
_STABLE_TEST = """import pytest


@pytest.mark.fast
def test_stable() -> None:
    assert True
"""


def _write(path: Path, content: str) -> None:
    """Write *content* to *path*, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# T-GATE-0035 — Order-dependent test caught under at least one pinned seed
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_order_dependent_pinned(tmp_path: Path) -> None:
    """id: T-GATE-0035
    title: Order-dependent test caught under at least one pinned seed
    purpose: An order-dependent test is detected by running it under the five pinned seeds
    level: fast
    requirement: P00-T04
    input: a temp test file with three order-dependent tests run under pinned seeds
    expected: at least one pinned seed produces a non-zero exit code
    risk: an order-dependent test passes under every pinned seed and hides a fixture leak
    capability: none
    """
    test_file = tmp_path / "test_order.py"
    _write(test_file, _ORDER_TEST)
    results = run_under_seeds(test_file, PINNED_SEEDS)
    failed = [r for r in results if r.exit_code != 0]
    assert len(failed) > 0, (
        f"expected at least one failure among pinned seeds {PINNED_SEEDS}, "
        f"got: {[(r.seed, r.exit_code) for r in results]}"
    )


# ---------------------------------------------------------------------------
# T-GATE-0036 — Same seed, worker count and selection reproduce same result
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_same_seed_reproducible(tmp_path: Path) -> None:
    """id: T-GATE-0036
    title: Same seed, worker count and selection reproduce same result
    purpose: Running the same test twice with the same seed produces identical exit codes
    level: fast
    requirement: P00-T04
    input: a stable test file run twice under the same seed
    expected: both runs produce exit code 0
    risk: the same seed produces different results and a flaky test goes undetected
    capability: none
    """
    test_file = tmp_path / "test_stable.py"
    _write(test_file, _STABLE_TEST)
    seed = 42
    run_a = run_under_seeds(test_file, [seed])
    run_b = run_under_seeds(test_file, [seed])
    assert run_a[0].exit_code == run_b[0].exit_code == 0


# ---------------------------------------------------------------------------
# T-GATE-0037 — gate seeds add appends a failing seed with its test id
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_seeds_add_appends_and_refuses_hand_edit(tmp_path: Path) -> None:
    """id: T-GATE-0037
    title: gate seeds add appends a failing seed with its test id and refuses a hand edit
    purpose: add_seed appends a regression seed with its test id and a hand edit fails verify
    level: fast
    requirement: P00-T04
    input: a temp seeds.toml and lock file, add_seed, then a hand edit of seeds.toml
    expected: the seed appears in the regression list; verify_seeds fails after hand edit
    risk: a regression seed is lost or seeds.toml is edited outside the gate command
    capability: none
    """
    seeds_path = tmp_path / "seeds.toml"
    lock_path = tmp_path / "seeds.lock"
    config = SeedsConfig(
        pinned=list(PINNED_SEEDS),
        regression=[],
        test_ids={},
    )
    save_seeds(seeds_path, config)
    # Create the lock file with the initial hash.
    from tools.gate.runner import hash_file

    lock_path.write_text(hash_file(seeds_path) + "\n", encoding="utf-8")

    # Add a regression seed.
    add_seed(seeds_path, lock_path, 999, "T-GATE-0035")
    loaded = load_seeds(seeds_path)
    assert 999 in loaded.regression
    assert loaded.test_ids.get("999") == "T-GATE-0035"

    # Verify passes after a legitimate add.
    assert verify_seeds(seeds_path, lock_path)

    # Hand-edit seeds.toml without updating the lock.
    _write(seeds_path, "this is not valid TOML]]]\n")
    assert not verify_seeds(seeds_path, lock_path)


# ---------------------------------------------------------------------------
# T-GATE-0038 — Regression seeds run in every later gate run; fresh seed
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_regression_and_fresh_seed(tmp_path: Path) -> None:
    """id: T-GATE-0038
    title: Regression seeds run in every later gate run; fresh seed printed; hand edit fails
    purpose: all_seeds includes regression seeds, fresh_seed returns a valid seed,
            and a hand-edited seeds.toml fails verify
    level: fast
    requirement: P00-T04
    input: a SeedsConfig with regression seeds; fresh_seed; a hand-edited seeds.toml
    expected: all_seeds includes regression seeds; fresh_seed > 0; verify fails after hand edit
    risk: regression seeds are dropped or seeds.toml is hand-edited without detection
    capability: none
    """
    # Regression seeds are included in all_seeds.
    config = SeedsConfig(
        pinned=list(PINNED_SEEDS),
        regression=[123, 456],
        test_ids={"123": "T-GATE-0035", "456": "T-GATE-0036"},
    )
    seeds = all_seeds(config)
    assert 123 in seeds
    assert 456 in seeds
    assert all(s in seeds for s in PINNED_SEEDS)

    # fresh_seed returns a positive integer.
    seed = fresh_seed()
    assert isinstance(seed, int)
    assert seed >= 0

    # Hand-edited seeds.toml fails the verify gate.
    seeds_path = tmp_path / "seeds.toml"
    lock_path = tmp_path / "seeds.lock"
    save_seeds(seeds_path, config)
    from tools.gate.runner import hash_file

    lock_path.write_text(hash_file(seeds_path) + "\n", encoding="utf-8")
    assert verify_seeds(seeds_path, lock_path)
    _write(seeds_path, "hand-edited invalid content\n")
    assert not verify_seeds(seeds_path, lock_path)
