"""Golden path regeneration gate (P00-T04).

``gate golden regenerate <path...> --reason <text>`` accepts only paths listed
in ``tools/gate/golden-paths.toml``, refuses to run when the tree has any other
uncommitted change, and commits the golden files alone as
``test(golden): <reason> [Pxx-Tyy]`` with the old and new SHA-256 of each path
in the commit body.

Invokable as ``python -m tools.gate.gates.golden``.

Spec: Part 1 §4.8, Part 4 §4.5.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from tools.gate.runner import hash_file

__all__ = [
    "GoldenError",
    "load_golden_paths",
    "regenerate",
    "main",
]


class GoldenError(Exception):
    """A golden gate error."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_env() -> dict[str, str]:
    """Environment for git subprocess calls."""
    env = dict(os.environ)
    if "DEVELOPER_DIR" not in env:
        env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return env


def load_golden_paths(path: Path) -> list[str]:
    """Load the allowed golden paths from ``golden-paths.toml``."""
    try:
        with path.open("rb") as stream:
            raw: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GoldenError(f"cannot load golden-paths.toml: {exc}") from exc
    if not isinstance(raw, dict):
        return []
    paths_raw = raw.get("paths")
    if not isinstance(paths_raw, list):
        return []
    return [str(p) for p in paths_raw if isinstance(p, str)]


def _git_status_porcelain(repo_root: Path) -> list[str]:
    """Return the list of dirty paths from ``git status --porcelain``."""
    env = _git_env()
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env=env,
        check=True,
    )
    dirty: list[str] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            dirty.append(parts[1])
    return dirty


def _git_file_hash_at_head(repo_root: Path, path: str) -> str:
    """SHA-256 of *path* as it exists at HEAD (``"(new)"`` if not tracked)."""
    env = _git_env()
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        capture_output=True,
        cwd=str(repo_root),
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return "(new)"
    return hashlib.sha256(result.stdout).hexdigest()


def regenerate(
    paths: list[str],
    reason: str,
    task_id: str,
    golden_paths_file: Path | None = None,
    repo_root: Path | None = None,
) -> int:
    """Regenerate golden files and commit them alone.

    Returns 0 on success, 1 on refusal (bad path or dirty tree).
    """
    if golden_paths_file is None:
        golden_paths_file = _gate_dir() / "golden-paths.toml"
    if repo_root is None:
        repo_root = _repo_root()

    allowed = load_golden_paths(golden_paths_file)
    for p in paths:
        if p not in allowed:
            print(f"golden: path {p!r} is not in the golden paths list", file=sys.stderr)
            return 1

    dirty = _git_status_porcelain(repo_root)
    non_golden = [p for p in dirty if p not in paths]
    if non_golden:
        print(
            f"golden: tree has non-golden changes: {non_golden}",
            file=sys.stderr,
        )
        return 1

    env = _git_env()

    # Record old and new hashes.
    hash_lines: list[str] = []
    for p in paths:
        old_hash = _git_file_hash_at_head(repo_root, p)
        new_hash = hash_file(repo_root / p)
        hash_lines.append(f"{p}: {old_hash} -> {new_hash}")

    # Stage only the golden paths.
    for p in paths:
        subprocess.run(
            ["git", "add", "--", p],
            cwd=str(repo_root),
            env=env,
            check=True,
            capture_output=True,
        )

    # Build the commit message.
    msg = f"test(golden): {reason}"
    if task_id:
        msg += f" [{task_id}]"
    msg += "\n\n" + "\n".join(hash_lines) + "\n"

    msg_file = repo_root / ".git" / "GOLDEN_COMMIT_MSG"
    msg_file.parent.mkdir(parents=True, exist_ok=True)
    msg_file.write_text(msg, encoding="utf-8")
    try:
        subprocess.run(
            ["git", "commit", "-F", str(msg_file)],
            cwd=str(repo_root),
            env=env,
            check=True,
            capture_output=True,
        )
    finally:
        if msg_file.exists():
            msg_file.unlink()

    return 0


def main() -> int:
    """Entry point for the golden gate."""
    args = sys.argv[1:]
    if not args:
        print(
            "usage: gate golden regenerate <path...> --reason <text> [--task <id>]",
            file=sys.stderr,
        )
        return 2
    command = args[0]
    if command != "regenerate":
        print(f"unknown command: {command}", file=sys.stderr)
        return 2
    rest = args[1:]
    reason = ""
    task_id = ""
    paths: list[str] = []
    i = 0
    while i < len(rest):
        if rest[i] == "--reason":
            if i + 1 >= len(rest):
                print("error: --reason requires a value", file=sys.stderr)
                return 2
            reason = rest[i + 1]
            i += 2
        elif rest[i] == "--task":
            if i + 1 >= len(rest):
                print("error: --task requires a value", file=sys.stderr)
                return 2
            task_id = rest[i + 1]
            i += 2
        else:
            paths.append(rest[i])
            i += 1
    if not reason or not paths:
        print(
            "usage: gate golden regenerate <path...> --reason <text> [--task <id>]",
            file=sys.stderr,
        )
        return 2
    return regenerate(paths, reason, task_id)


if __name__ == "__main__":
    sys.exit(main())
