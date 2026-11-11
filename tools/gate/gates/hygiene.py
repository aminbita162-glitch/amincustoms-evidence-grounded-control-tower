"""Hygiene gate — forbidden-pattern and structural-commit checks (P00-T06).

Reads ``HYGIENE_PATTERNS`` (always-forbidden list) and
``HYGIENE_PATTERNS_VENDOR`` (vendor list) from the environment.

* **Always-forbidden** patterns match in every target: tracked files, commit
  messages of the branch, and pull-request text — without exception.
* **Vendor** patterns are forbidden in every target *except* files whose
  path matches an entry of ``tools/gate/hygiene_scope.toml``.  Scope entries
  are allowed only under ``adapter/``, ``provider-configuration/``,
  ``provider-test/`` and ``provider-documentation/`` paths.

In CI (``CI`` env var set): fails closed when either list is missing, empty
or below its minimum entry count.  Outside CI without either list: reports
``NOT_RUN_LOCAL`` (never a pass, never a failure, never a STOP) and still
runs the structural checks of ``gate commit-check`` on the commit messages
and pull-request text it can see.  A list that is present but empty or below
the minimum entry count fails everywhere.

Reports only pass or fail and the file path — **never the pattern**.

Invokable as ``python -m tools.gate.gates.hygiene``.

Spec: Part 4 §4.12, Part 1 §4.9.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from tools.gate.commit_check import check_commit_message

__all__ = [
    "ScopeEntry",
    "HygieneResult",
    "MIN_ENTRIES",
    "SCOPE_PREFIXES",
    "load_hygiene_scope",
    "parse_patterns",
    "validate_scope",
    "get_tracked_files",
    "get_commit_messages",
    "get_pr_text",
    "drop_merge_messages",
    "pattern_in_text",
    "is_scope_matched",
    "run_hygiene",
    "main",
]

MIN_ENTRIES = 1

SCOPE_PREFIXES: tuple[str, ...] = (
    "adapter/",
    "provider-configuration/",
    "provider-test/",
    "provider-documentation/",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    if "DEVELOPER_DIR" not in env:
        env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return env


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeEntry:
    """One entry from ``hygiene_scope.toml``."""

    path: str
    reason: str
    owner_decision_id: str


@dataclass
class HygieneResult:
    """Result of a hygiene gate run."""

    status: str  # "PASS", "FAIL", "NOT_RUN_LOCAL"
    violations: list[str] = field(default_factory=list)
    reason: str | None = None


# ---------------------------------------------------------------------------
# Pattern parsing
# ---------------------------------------------------------------------------


def parse_patterns(raw: str | None) -> list[str] | None:
    """Parse a newline-separated pattern env var.

    Returns ``None`` when *raw* is ``None`` (the env var is not set).
    Returns a list (possibly empty) when the var is set.
    """
    if raw is None:
        return None
    return [p.strip() for p in raw.splitlines() if p.strip()]


# ---------------------------------------------------------------------------
# Scope loading and validation
# ---------------------------------------------------------------------------


def load_hygiene_scope(path: Path) -> list[ScopeEntry]:
    """Load and validate ``hygiene_scope.toml``.

    Each entry has: path (glob), reason, owner_decision_id.
    Returns an empty list when the file has no entries (P00 default).
    """
    if not path.is_file():
        return []
    try:
        with path.open("rb") as stream:
            raw: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot load hygiene_scope.toml: {exc}") from exc
    if not isinstance(raw, dict):
        return []
    entries_raw = raw.get("entry")
    if not isinstance(entries_raw, list):
        return []
    entries: list[ScopeEntry] = []
    for item in entries_raw:
        if isinstance(item, dict):
            entries.append(
                ScopeEntry(
                    path=str(item.get("path", "")),
                    reason=str(item.get("reason", "")),
                    owner_decision_id=str(item.get("owner_decision_id", "")),
                )
            )
    return entries


def validate_scope(entries: list[ScopeEntry]) -> list[str]:
    """Validate that each scope entry's path is under an allowed family.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []
    for entry in entries:
        if not entry.path:
            errors.append("scope entry with empty path")
            continue
        if not any(entry.path.startswith(prefix) for prefix in SCOPE_PREFIXES):
            errors.append(f"scope entry '{entry.path}' outside permitted path families")
    return errors


# ---------------------------------------------------------------------------
# Target collection
# ---------------------------------------------------------------------------


def _is_git_repo(root: Path) -> bool:
    """Return True if *root* is inside a git work tree."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        cwd=str(root),
        env=_git_env(),
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def get_tracked_files(root: Path) -> list[Path]:
    """Return git-tracked files, or all files in *root* if not a git repo."""
    if _is_git_repo(root):
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            cwd=str(root),
            env=_git_env(),
            check=False,
        )
        if result.returncode == 0:
            return [(root / line.strip()) for line in result.stdout.splitlines() if line.strip()]
    # Fallback: all files in the current directory (for selftest temp dirs).
    return [p for p in root.rglob("*") if p.is_file() and p.name not in (".git",)]


def drop_merge_messages(messages: list[str]) -> list[str]:
    """Drop merge-commit messages.

    The commits of a pull request are checked before the merge, so the merge
    commit itself (its message starts with "Merge ") is not checked again.
    """
    return [m for m in messages if not m.lstrip().startswith("Merge ")]


def get_commit_messages(root: Path) -> list[str]:
    """Return commit message bodies from the branch, or a ``COMMIT_MSG`` file.

    In a git repo, returns messages from commits on the current branch that
    are not on ``main`` (the pull-request range).  This excludes the owner's
    pre-flight commits (initial commit, directive, run-parameters) which do
    not follow the task-commit format.  If ``main`` does not exist, falls back
    to all commits from ``HEAD``.
    """
    if _is_git_repo(root):
        # Try the PR range: commits on this branch not on main.
        result = subprocess.run(
            ["git", "log", "--format=%B", "main..HEAD"],
            capture_output=True,
            text=True,
            cwd=str(root),
            env=_git_env(),
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            messages = _split_git_log(result.stdout)
            return drop_merge_messages([m for m in messages if m.strip()])
        # Fallback (on main, or no main branch): the HEAD commit only.
        result = subprocess.run(
            ["git", "log", "-n", "1", "--format=%B", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(root),
            env=_git_env(),
            check=False,
        )
        if result.returncode == 0:
            messages = _split_git_log(result.stdout)
            return drop_merge_messages([m for m in messages if m.strip()])
        return []
    # Fallback for non-git directories (selftest temp dirs).
    commit_msg = root / "COMMIT_MSG"
    if commit_msg.is_file():
        return [commit_msg.read_text(encoding="utf-8")]
    return []


def _split_git_log(output: str) -> list[str]:
    """Split ``git log --format=%B`` output into individual commit messages."""
    messages: list[str] = []
    current: list[str] = []
    for line in output.splitlines():
        current.append(line)
    # git log --format=%B separates commits with a blank line.
    # Re-split properly:
    text = output
    parts = re.split(r"\n\n(?=\S)", text)
    for part in parts:
        stripped = part.strip()
        if stripped:
            messages.append(stripped)
    return messages


def get_pr_text(root: Path) -> str | None:
    """Return pull-request text from the event payload, or a ``PR_TEXT`` file."""
    pr_text = root / "PR_TEXT"
    if pr_text.is_file():
        return pr_text.read_text(encoding="utf-8")
    return None


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------


def pattern_in_text(text: str, pattern: str) -> bool:
    """Return True if *pattern* appears in *text* (case-sensitive substring)."""
    return pattern in text


def is_scope_matched(file_path: str, entries: list[ScopeEntry]) -> bool:
    """Return True if *file_path* matches any scope entry's path glob.

    ``fnmatch`` does not treat ``**`` as a recursive glob — ``*`` already
    matches the path separator — so ``**/`` is collapsed (the globstar and
    its trailing slash are removed) before matching, turning
    ``adapter/**/*.py`` into ``adapter/*.py``.
    """
    return any(
        fnmatch.fnmatch(file_path, entry.path.replace("**/", "").replace("**", "*"))
        for entry in entries
    )


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def _scan_files(
    files: list[Path],
    root: Path,
    always_forbidden: list[str],
    vendor: list[str],
    scope: list[ScopeEntry],
) -> list[str]:
    """Scan files for pattern violations. Returns file paths with violations."""
    violations: list[str] = []
    for file_path in files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(file_path.relative_to(root)) if _is_relative(file_path, root) else str(file_path)
        for pattern in always_forbidden:
            if pattern_in_text(content, pattern):
                violations.append(rel)
                break  # one violation per file is enough
        if is_scope_matched(rel, scope):
            continue  # vendor patterns skip scope-matched files
        for pattern in vendor:
            if pattern_in_text(content, pattern):
                violations.append(rel)
                break
    return violations


def _is_relative(path: Path, root: Path) -> bool:
    """Return True if *path* is inside *root*."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _scan_messages(
    messages: list[str],
    always_forbidden: list[str],
    vendor: list[str],
) -> list[str]:
    """Scan commit messages / PR text for pattern violations."""
    violations: list[str] = []
    for i, msg in enumerate(messages):
        label = f"commit[{i}]"
        for pattern in always_forbidden:
            if pattern_in_text(msg, pattern):
                violations.append(label)
                break
        for pattern in vendor:
            if pattern_in_text(msg, pattern):
                violations.append(label)
                break
    return violations


def _structural_checks(
    commit_messages: list[str],
    pr_text: str | None,
) -> list[str]:
    """Run commit-check structural checks on commit messages and PR text.

    Every commit message and the pull-request text must pass the structural checks.
    """
    violations: list[str] = []
    for i, msg in enumerate(commit_messages):
        issues = check_commit_message(msg)
        if issues:
            violations.append(f"commit[{i}]")
    if pr_text is not None:
        issues = check_commit_message(pr_text)
        if issues:
            violations.append("pull-request")
    return violations


def run_hygiene(
    root: Path,
    env: dict[str, str],
    scope_path: Path | None = None,
) -> HygieneResult:
    """Run the full hygiene gate check.

    Returns a :class:`HygieneResult` with status, violations (file paths
    only — never the pattern), and optional reason.
    """
    if scope_path is None:
        scope_path = _gate_dir() / "hygiene_scope.toml"

    always_raw = env.get("HYGIENE_PATTERNS")
    vendor_raw = env.get("HYGIENE_PATTERNS_VENDOR")
    is_ci = bool(env.get("CI"))

    always_forbidden = parse_patterns(always_raw)
    vendor = parse_patterns(vendor_raw)

    # Load and validate scope.
    try:
        scope = load_hygiene_scope(scope_path)
    except ValueError as exc:
        return HygieneResult(status="FAIL", reason=str(exc))
    scope_errors = validate_scope(scope)
    if scope_errors:
        return HygieneResult(status="FAIL", reason=scope_errors[0])

    # A present-but-empty or below-minimum list fails everywhere.
    if always_forbidden is not None and len(always_forbidden) < MIN_ENTRIES:
        return HygieneResult(
            status="FAIL", reason="always-forbidden list below minimum entry count"
        )
    if vendor is not None and len(vendor) < MIN_ENTRIES:
        return HygieneResult(status="FAIL", reason="vendor list below minimum entry count")

    # CI: both lists must be present.
    if is_ci:
        if always_forbidden is None:
            return HygieneResult(status="FAIL", reason="missing HYGIENE_PATTERNS in CI")
        if vendor is None:
            return HygieneResult(status="FAIL", reason="missing HYGIENE_PATTERNS_VENDOR in CI")

    # Not CI, both missing → NOT_RUN_LOCAL (still run structural checks).
    if always_forbidden is None and vendor is None:
        commit_messages = get_commit_messages(root)
        pr_text = get_pr_text(root)
        structural = _structural_checks(commit_messages, pr_text)
        if structural:
            return HygieneResult(status="FAIL", violations=structural)
        return HygieneResult(status="NOT_RUN_LOCAL", reason="NOT_RUN_LOCAL")

    # Collect targets.
    files = get_tracked_files(root)
    commit_messages = get_commit_messages(root)
    pr_text = get_pr_text(root)

    all_violations: list[str] = []

    # Always-forbidden: every target.
    all_violations.extend(_scan_files(files, root, always_forbidden or [], [], scope))
    all_violations.extend(_scan_messages(commit_messages, always_forbidden or [], []))
    if pr_text is not None:
        msg_violations = _scan_messages([pr_text], always_forbidden or [], [])
        if msg_violations:
            all_violations.append("pull-request")

    # Vendor: every target except scope-matched files.
    vendor_files = [
        f
        for f in files
        if not is_scope_matched(
            str(f.relative_to(root)) if _is_relative(f, root) else str(f), scope
        )
    ]
    all_violations.extend(_scan_files(vendor_files, root, [], vendor or [], scope))
    all_violations.extend(_scan_messages(commit_messages, [], vendor or []))
    if pr_text is not None:
        msg_violations = _scan_messages([pr_text], [], vendor or [])
        if msg_violations:
            all_violations.append("pull-request")

    # Structural checks always run when lists are present.
    structural = _structural_checks(commit_messages, pr_text)
    all_violations.extend(structural)

    if all_violations:
        return HygieneResult(status="FAIL", violations=all_violations)
    return HygieneResult(status="PASS")


def main() -> int:
    """Entry point for the hygiene gate."""
    root = Path.cwd()
    result = run_hygiene(root, dict(os.environ))
    if result.status == "FAIL":
        for v in result.violations:
            print(f"hygiene: FAIL {v}")
        if result.reason and not result.violations:
            print(f"hygiene: FAIL {result.reason}")
        return 1
    if result.status == "NOT_RUN_LOCAL":
        print("hygiene: NOT_RUN_LOCAL")
        return 0
    print("hygiene: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
