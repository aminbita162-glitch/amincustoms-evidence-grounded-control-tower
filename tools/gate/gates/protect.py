"""Protected paths gate (P00-T07).

Compares the content hash (SHA-256) of each protected file listed in
``tools/gate/protected.toml`` with the hashes recorded in
``docs/state/protected-hashes.json``.  The hashes file is written only by
``gate protect --update``, which refuses to run outside a task that names
the path (checked against the phase ledger or the git diff).  The gate
also fails if a pull request changes a protected path without an
owner-listed task in the phase ledger.

Exit codes: 0 all hashes match, 1 any mismatch, 2 misconfiguration.

Invokable as ``python -m tools.gate.gates.protect``.

Spec: Part 1 §5.5, P00-T07.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from tools.gate.runner import hash_file

__all__ = [
    "ProtectError",
    "load_protected_paths",
    "expand_paths",
    "load_hashes",
    "save_hashes",
    "check_protected",
    "update_hashes",
    "main",
]

# Names to skip when expanding directory entries (cache files, OS metadata).
_SKIP_NAMES: frozenset[str] = frozenset({"__pycache__", ".DS_Store", ".git"})


class ProtectError(Exception):
    """A protect gate configuration error."""


def _repo_root() -> Path:
    """Resolve the repository root, respecting GATE_ROOT if set."""
    gate_root = os.environ.get("GATE_ROOT")
    if gate_root:
        return Path(gate_root).resolve()
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    """The ``tools/gate`` package directory (parent of this module's package)."""
    # tools/gate/gates/protect.py -> parents[1] is tools/gate/.
    return Path(__file__).resolve().parents[1]


def _git_env() -> dict[str, str]:
    """Environment for git subprocess calls (sets DEVELOPER_DIR on macOS)."""
    env = dict(os.environ)
    if "DEVELOPER_DIR" not in env:
        env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return env


def load_protected_paths(path: Path) -> list[str]:
    """Load the list of protected paths from ``protected.toml``.

    The TOML uses a ``[paths]`` table whose keys are path strings mapped to
    ``true``.
    """
    try:
        with path.open("rb") as stream:
            raw: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProtectError(f"cannot load protected.toml: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProtectError("protected.toml is not a table")
    paths_table: object = raw.get("paths")
    if not isinstance(paths_table, dict):
        raise ProtectError("protected.toml missing [paths] table")
    return sorted(str(p) for p in paths_table if isinstance(p, str))


def _should_skip(name: str) -> bool:
    """Return True if a file/directory name should be skipped when expanding."""
    if name in _SKIP_NAMES:
        return True
    return name.endswith(".pyc")


def expand_paths(repo_root: Path, paths: list[str]) -> list[str]:
    """Expand directory entries to their individual file paths.

    Returns a sorted list of file paths relative to *repo_root*.  Paths that
    do not exist on disk are silently skipped (they may not be created yet).
    """
    result: set[str] = set()
    for p in paths:
        full = repo_root / p
        if full.is_dir():
            for item in full.rglob("*"):
                if item.is_file() and not _should_skip(item.name):
                    result.add(str(item.relative_to(repo_root)))
        elif full.is_file():
            result.add(p)
        # Missing paths are silently skipped.
    return sorted(result)


def load_hashes(path: Path) -> dict[str, str]:
    """Load ``protected-hashes.json`` as a path → SHA-256 mapping."""
    if not path.is_file():
        return {}
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtectError(f"cannot load protected-hashes.json: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProtectError("protected-hashes.json is not an object")
    return {str(k): str(v) for k, v in raw.items()}


def save_hashes(path: Path, hashes: dict[str, str]) -> None:
    """Write the hashes file deterministically (sorted keys, 2-space indent)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(sorted(hashes.items()))
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _hashes_rel_path(repo_root: Path, hashes_file: Path) -> str:
    """The repo-relative path string of the hashes file."""
    try:
        return str(hashes_file.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(hashes_file)


def check_protected(
    repo_root: Path,
    protected_paths_file: Path | None = None,
    hashes_file: Path | None = None,
) -> int:
    """Check that every protected file's hash matches the recorded hash.

    Returns 0 if all match, 1 if any mismatch or missing entry, 2 on
    misconfiguration (unreadable TOML/JSON).
    """
    if protected_paths_file is None:
        protected_paths_file = _gate_dir() / "protected.toml"
    if hashes_file is None:
        hashes_file = repo_root / "docs" / "state" / "protected-hashes.json"

    try:
        protected_paths = load_protected_paths(protected_paths_file)
    except ProtectError as exc:
        print(f"protect: {exc}", file=sys.stderr)
        return 2

    try:
        hashes = load_hashes(hashes_file)
    except ProtectError as exc:
        print(f"protect: {exc}", file=sys.stderr)
        return 2

    expanded = expand_paths(repo_root, protected_paths)
    hashes_rel = _hashes_rel_path(repo_root, hashes_file)

    violations: list[str] = []
    for rel_path in expanded:
        # Skip the hashes file itself — it cannot hash itself (circular).
        if rel_path == hashes_rel:
            continue
        full = repo_root / rel_path
        if not full.is_file():
            continue
        actual = hash_file(full)
        expected = hashes.get(rel_path)
        if expected is None:
            violations.append(f"protected file not in hashes: {rel_path}")
        elif actual != expected:
            violations.append(f"hash mismatch: {rel_path}")

    if violations:
        for v in violations:
            print(f"protect: {v}", file=sys.stderr)
        return 1
    return 0


def _git_changed_files(repo_root: Path) -> list[str]:
    """Return paths changed in the working tree (vs HEAD) plus untracked files."""
    env = _git_env()
    changed: set[str] = set()

    # Tracked changes (staged + unstaged vs HEAD).
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            env=env,
            check=False,
        )
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                changed.add(line)
    except OSError, subprocess.SubprocessError:
        pass

    # Untracked files not yet in the index.
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            env=env,
            check=False,
        )
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                changed.add(line)
    except OSError, subprocess.SubprocessError:
        pass

    return sorted(changed)


def _task_protected_paths(
    repo_root: Path,
    protected_paths: list[str],
    task_paths: list[str] | None,
) -> list[str]:
    """Return protected paths that a task authorises (git diff or explicit)."""
    expanded = set(expand_paths(repo_root, protected_paths))
    if task_paths is None:
        task_paths = _git_changed_files(repo_root)
    return [p for p in task_paths if p in expanded]


def update_hashes(
    repo_root: Path,
    protected_paths_file: Path | None = None,
    hashes_file: Path | None = None,
    task_paths: list[str] | None = None,
) -> int:
    """Update the hashes file with current file hashes.

    Refuses to run outside a task that names a protected path (checked against
    the git diff or the explicit *task_paths* list).  Returns 0 on success,
    1 if refused, 2 on misconfiguration.
    """
    if protected_paths_file is None:
        protected_paths_file = _gate_dir() / "protected.toml"
    if hashes_file is None:
        hashes_file = repo_root / "docs" / "state" / "protected-hashes.json"

    try:
        protected_paths = load_protected_paths(protected_paths_file)
    except ProtectError as exc:
        print(f"protect: {exc}", file=sys.stderr)
        return 2

    changed_protected = _task_protected_paths(repo_root, protected_paths, task_paths)
    if not changed_protected:
        print(
            "protect: --update refused: no task changes a protected path",
            file=sys.stderr,
        )
        return 1

    expanded = expand_paths(repo_root, protected_paths)
    hashes_rel = _hashes_rel_path(repo_root, hashes_file)

    hashes: dict[str, str] = {}
    for rel_path in expanded:
        if rel_path == hashes_rel:
            continue
        full = repo_root / rel_path
        if full.is_file():
            hashes[rel_path] = hash_file(full)

    save_hashes(hashes_file, hashes)
    print(f"protect: updated {len(hashes)} hashes", file=sys.stderr)
    return 0


def main() -> int:
    """Entry point for the protect gate."""
    args = sys.argv[1:]
    if args and args[0] == "--update":
        return update_hashes(_repo_root())
    return check_protected(_repo_root())


if __name__ == "__main__":
    sys.exit(main())
