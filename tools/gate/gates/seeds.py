"""Seed management gate — pinned and regression seeds (P00-T04).

Manages ``docs/state/seeds.toml`` (a protected path) with two lists:

  - **pinned** — five fixed integers used for every gate run.
  - **regression** — seeds under which a test failed, appended by
    ``gate seeds add`` and included in every subsequent run.

A companion lock file (``docs/state/seeds.lock``) stores the SHA-256 of
``seeds.toml`` so that a hand edit (outside ``gate seeds add``) is detected
by ``gate seeds verify``.

Invokable as ``python -m tools.gate.gates.seeds``.

Spec: Part 4 §4.5 (Flakiness).
"""

from __future__ import annotations

import secrets
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tools.gate.runner import hash_file

__all__ = [
    "SeedsConfig",
    "SeedResult",
    "SeedsError",
    "load_seeds",
    "save_seeds",
    "add_seed",
    "verify_seeds",
    "list_seeds",
    "all_seeds",
    "fresh_seed",
    "run_under_seeds",
    "main",
]


class SeedsError(Exception):
    """A seeds configuration error."""


@dataclass
class SeedsConfig:
    """Parsed contents of seeds.toml."""

    pinned: list[int]
    regression: list[int]
    test_ids: dict[str, str]


@dataclass(frozen=True)
class SeedResult:
    """Result of running a test under a specific seed."""

    seed: int
    exit_code: int


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def load_seeds(path: Path) -> SeedsConfig:
    """Load and validate ``seeds.toml``."""
    try:
        with path.open("rb") as stream:
            raw: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SeedsError(f"cannot load seeds.toml: {exc}") from exc
    if not isinstance(raw, dict):
        raise SeedsError("seeds.toml is not a table")

    pinned_raw = raw.get("pinned")
    if not isinstance(pinned_raw, dict):
        raise SeedsError("seeds.toml missing [pinned] table")
    pinned_seeds_raw = pinned_raw.get("seeds")
    if not isinstance(pinned_seeds_raw, list):
        raise SeedsError("[pinned].seeds must be a list")
    pinned: list[int] = [
        s for s in pinned_seeds_raw if isinstance(s, int) and not isinstance(s, bool)
    ]

    regression_raw = raw.get("regression")
    if not isinstance(regression_raw, dict):
        raise SeedsError("seeds.toml missing [regression] table")
    regression_seeds_raw = regression_raw.get("seeds")
    if not isinstance(regression_seeds_raw, list):
        raise SeedsError("[regression].seeds must be a list")
    regression: list[int] = [
        s for s in regression_seeds_raw if isinstance(s, int) and not isinstance(s, bool)
    ]

    test_ids: dict[str, str] = {}
    test_ids_raw = regression_raw.get("test_ids")
    if isinstance(test_ids_raw, dict):
        for key, value in test_ids_raw.items():
            if isinstance(value, str):
                test_ids[str(key)] = value

    return SeedsConfig(pinned=pinned, regression=regression, test_ids=test_ids)


def save_seeds(path: Path, config: SeedsConfig) -> None:
    """Write ``seeds.toml`` in a deterministic format."""
    lines: list[str] = []
    lines.append("[pinned]")
    lines.append(f"seeds = [{', '.join(str(s) for s in config.pinned)}]")
    lines.append("")
    lines.append("[regression]")
    lines.append(f"seeds = [{', '.join(str(s) for s in config.regression)}]")
    if config.test_ids:
        lines.append("")
        lines.append("[regression.test_ids]")
        for seed_str, test_id in sorted(config.test_ids.items()):
            lines.append(f'"{seed_str}" = "{test_id}"')
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Lock file (hash-based integrity)
# ---------------------------------------------------------------------------


def _write_lock(lock_path: Path, seeds_path: Path) -> None:
    """Write the SHA-256 of *seeds_path* to *lock_path*."""
    lock_path.write_text(hash_file(seeds_path) + "\n", encoding="utf-8")


def _lock_hash(lock_path: Path) -> str | None:
    """Read the expected hash from the lock file."""
    if not lock_path.is_file():
        return None
    return lock_path.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def add_seed(seeds_path: Path, lock_path: Path, seed: int, test_id: str) -> None:
    """Append *seed* to the regression list with *test_id* and update the lock."""
    config = load_seeds(seeds_path)
    if seed not in config.regression:
        config.regression.append(seed)
    config.test_ids[str(seed)] = test_id
    save_seeds(seeds_path, config)
    _write_lock(lock_path, seeds_path)


def verify_seeds(seeds_path: Path, lock_path: Path) -> bool:
    """Return True if seeds.toml is valid and its hash matches the lock."""
    try:
        load_seeds(seeds_path)
    except SeedsError:
        return False
    expected = _lock_hash(lock_path)
    if expected is None:
        # First run — create the lock file.
        _write_lock(lock_path, seeds_path)
        return True
    return expected == hash_file(seeds_path)


def list_seeds(seeds_path: Path) -> int:
    """Print pinned and regression seeds.  Returns exit code."""
    config = load_seeds(seeds_path)
    print("pinned seeds:")
    for seed in config.pinned:
        print(f"  {seed}")
    print("regression seeds:")
    for seed in config.regression:
        test_id = config.test_ids.get(str(seed), "")
        print(f"  {seed} (test: {test_id})")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def all_seeds(config: SeedsConfig) -> list[int]:
    """All seeds used in a gate run (pinned + regression)."""
    return list(config.pinned) + list(config.regression)


def fresh_seed() -> int:
    """Generate a fresh random seed (printed before an exploratory run)."""
    return secrets.randbelow(2**32)


def run_under_seeds(
    test_file: Path,
    seeds: list[int],
    workers: int = 0,
) -> list[SeedResult]:
    """Run *test_file* under each *seed*, returning one :class:`SeedResult` per seed."""
    results: list[SeedResult] = []
    for seed in seeds:
        cmd: list[str] = [
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "--randomly-seed",
            str(seed),
            "--override-ini",
            "addopts=",
            "-q",
            "--tb=short",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ]
        if workers > 0:
            cmd.extend(["-n", str(workers)])
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            cwd=str(test_file.parent),
        )
        results.append(SeedResult(seed=seed, exit_code=proc.returncode))
    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main() -> int:
    """Entry point for the seeds gate."""
    args = sys.argv[1:]
    if not args:
        print("usage: gate seeds <add|list|verify> ...", file=sys.stderr)
        return 2
    root = _repo_root()
    seeds_path = root / "docs" / "state" / "seeds.toml"
    lock_path = root / "docs" / "state" / "seeds.lock"
    command = args[0]
    rest = args[1:]

    if command == "add":
        if len(rest) < 3 or rest[1] != "--test":
            print("usage: gate seeds add <seed> --test <id>", file=sys.stderr)
            return 2
        try:
            seed = int(rest[0])
        except ValueError:
            print(f"invalid seed: {rest[0]!r}", file=sys.stderr)
            return 2
        test_id = rest[2]
        add_seed(seeds_path, lock_path, seed, test_id)
        print(f"added seed {seed} for test {test_id}")
        return 0

    if command == "list":
        return list_seeds(seeds_path)

    if command == "verify":
        if verify_seeds(seeds_path, lock_path):
            print("seeds: OK")
            return 0
        print("seeds: verification failed", file=sys.stderr)
        return 1

    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
