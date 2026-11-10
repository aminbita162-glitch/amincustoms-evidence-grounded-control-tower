"""Scope check — Part 6 §6.14 (P00-T11).

``gate scope <NN>`` reads the ``Scope paths:`` line from the directive for the
given phase, lists every file changed on the phase branch against main
(``git diff --name-only main...HEAD``, renames count both paths), and fails on
any path outside the globs or on a protected path (Part 1 §5.5) that no task
names.

The agent never edits the ``Scope paths:`` line; it is a protected part of
the directive.

Spec: Part 6 §6.14; P00-T11.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

__all__ = [
    "ScopeError",
    "parse_scope_paths",
    "get_changed_files",
    "matches_glob",
    "check_scope",
    "run_scope_gate",
    "main",
]


class ScopeError(Exception):
    """A scope-check configuration or read error."""


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    if "DEVELOPER_DIR" not in env:
        env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return env


def _git_out(args: list[str], repo_root: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        env=_git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_PHASE_START_RE = re.compile(r"^<<<PHASE-(\d+)>>>")
_PHASE_END_RE = re.compile(r"^<<<END-PHASE-(\d+)>>>")
_SCOPE_PATHS_RE = re.compile(r"Scope paths:\s*(.*)")
_QUOTED_RE = re.compile(r"`([^`]+)`")


def parse_scope_paths(directive_text: str, phase_id: str) -> list[str]:
    """Parse the ``Scope paths:`` line for *phase_id* from the directive."""
    lines = directive_text.splitlines()
    in_block = False
    for _i, line in enumerate(lines):
        m = _PHASE_START_RE.match(line.strip())
        if m and f"P{int(m.group(1)):02d}" == phase_id:
            in_block = True
            continue
        if in_block:
            em = _PHASE_END_RE.match(line.strip())
            if em:
                break
            sm = _SCOPE_PATHS_RE.search(line)
            if sm:
                raw = sm.group(1).strip()
                return [p.strip() for p in raw.split(",") if p.strip()]
    raise ScopeError(f"phase {phase_id} not found or missing 'Scope paths:' line")


# ---------------------------------------------------------------------------
# Changed files
# ---------------------------------------------------------------------------


def get_changed_files(repo_root: Path) -> list[str]:
    """Get files changed on the current branch vs main (renames count both paths).

    Falls back to a ``.scope-changes`` file in *repo_root* when git is not
    available (used by selftest fixtures).
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", "main...HEAD"],
            cwd=str(repo_root),
            env=_git_env(),
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except subprocess.SubprocessError, OSError:
        # Fall back to .scope-changes file (for selftest fixtures).
        changes_file = repo_root / ".scope-changes"
        if changes_file.is_file():
            return [
                line.strip()
                for line in changes_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        return []
    files: list[str] = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith("D"):
            continue
        if status.startswith("R") and len(parts) >= 3:
            # Rename: count both old and new paths.
            files.append(parts[1])
            files.append(parts[2])
        else:
            files.append(parts[1])
    return files


# ---------------------------------------------------------------------------
# Glob matching
# ---------------------------------------------------------------------------


def matches_glob(path: str, glob: str) -> bool:
    """Check if *path* matches *glob*, supporting ``**`` recursive patterns."""
    if glob.endswith("/**"):
        prefix = glob[:-3]
        return path == prefix or path.startswith(prefix + "/")
    if "**" in glob:
        # Convert ** to a simple prefix match.
        head = glob.split("**")[0].rstrip("/")
        tail = glob.split("**")[1].lstrip("/")
        return path.startswith(head + "/") and (not tail or path.endswith(tail))
    return fnmatch.fnmatch(path, glob)


# ---------------------------------------------------------------------------
# Named-path extraction (task Files lists)
# ---------------------------------------------------------------------------


def _extract_named_paths(directive_text: str, phase_id: str) -> set[str]:
    """Extract all backtick-quoted paths from the Tasks section (field 6+) of the phase block.

    These are the paths that tasks in the phase explicitly name.  A protected
    path is allowed when it (or a parent directory) appears in this set.
    The scope fence (field 4) is excluded so that 'May create' paths
    do not falsely mark every file under a directory as task-named.
    """
    lines = directive_text.splitlines()
    in_block = False
    in_tasks = False
    named: set[str] = set()
    for line in lines:
        stripped = line.strip()
        m = _PHASE_START_RE.match(stripped)
        if m and f"P{int(m.group(1)):02d}" == phase_id:
            in_block = True
            in_tasks = False
            continue
        if in_block:
            em = _PHASE_END_RE.match(stripped)
            if em:
                break
            if re.match(r"^6\.\s", stripped):
                in_tasks = True
            if in_tasks:
                for qm in _QUOTED_RE.finditer(line):
                    path = qm.group(1).rstrip(".,;:!")
                    if "/" in path or path.endswith((".py", ".toml", ".json", ".yaml")):
                        named.add(path)
    return named


def _is_path_named(path: str, named_paths: set[str]) -> bool:
    """Check if *path* is covered by any named path (exact or directory prefix)."""
    for named in named_paths:
        if named == path:
            return True
        if named.endswith("/") and path.startswith(named):
            return True
        if path.startswith(named + "/"):
            return True
    return False


# ---------------------------------------------------------------------------
# Scope check
# ---------------------------------------------------------------------------


def check_scope(
    phase_id: str,
    directive_text: str,
    changed_files: list[str],
    protected_paths: list[str],
) -> list[str]:
    """Check that all changed files are within the scope globs.

    Fails on:
      - a path outside the globs
      - a protected path that no task in the phase names
    """
    scope_globs = parse_scope_paths(directive_text, phase_id)
    named_paths = _extract_named_paths(directive_text, phase_id)
    violations: list[str] = []
    for path in changed_files:
        if path.endswith("__init__.py"):
            continue
        if not any(matches_glob(path, g) for g in scope_globs):
            violations.append(f"path outside scope: {path}")
        elif path in protected_paths and not _is_path_named(path, named_paths):
            violations.append(f"protected path changed without task: {path}")
    return violations


# ---------------------------------------------------------------------------
# Protected paths loading
# ---------------------------------------------------------------------------


def _load_protected_paths(path: Path) -> list[str]:
    try:
        with path.open("rb") as stream:
            raw: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ScopeError(f"cannot load protected.toml: {exc}") from exc
    if not isinstance(raw, dict):
        raise ScopeError("protected.toml is not a table")
    paths_table: object = raw.get("paths")
    if not isinstance(paths_table, dict):
        raise ScopeError("protected.toml missing [paths] table")
    return sorted(str(p) for p in paths_table if isinstance(p, str))


# ---------------------------------------------------------------------------
# Gate entry point
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Resolve the repository root, respecting GATE_ROOT if set."""
    gate_root = os.environ.get("GATE_ROOT")
    if gate_root:
        return Path(gate_root).resolve()
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def run_scope_gate(
    repo_root: Path,
    phase_id: str,
    *,
    directive_text: str | None = None,
    changed_files: list[str] | None = None,
    protected_paths: list[str] | None = None,
) -> int:
    """Run the scope gate.  Returns 0 (pass), 1 (violation), 2 (misconfiguration)."""
    if directive_text is None:
        # Try cwd first (for selftest), then repo root.
        cwd_directive = Path.cwd() / "directive.txt"
        if cwd_directive.is_file():
            directive_text = cwd_directive.read_text(encoding="utf-8")
        else:
            directive_path = repo_root / "directive.txt"
            if not directive_path.is_file():
                print("scope: directive.txt not found", file=sys.stderr)
                return 2
            directive_text = directive_path.read_text(encoding="utf-8")
    if changed_files is None:
        changed_files = get_changed_files(repo_root)
    if protected_paths is None:
        protected_path = _gate_dir() / "protected.toml"
        cwd_protected = Path.cwd() / "protected.toml"
        if cwd_protected.is_file():
            protected_path = cwd_protected
        try:
            protected_paths = _load_protected_paths(protected_path)
        except ScopeError as exc:
            print(f"scope: {exc}", file=sys.stderr)
            return 2
    try:
        violations = check_scope(phase_id, directive_text, changed_files, protected_paths)
    except ScopeError as exc:
        print(f"scope: {exc}", file=sys.stderr)
        return 2
    if violations:
        for v in violations:
            print(f"scope: {v}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    """Entry point for the scope gate."""
    args = sys.argv[1:]
    phase_id = args[0] if args else "P00"
    return run_scope_gate(_repo_root(), phase_id)


if __name__ == "__main__":
    sys.exit(main())
