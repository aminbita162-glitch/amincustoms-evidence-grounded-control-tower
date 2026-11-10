"""Commit message validation (Part 1 §4.9, §4.3).

``gate commit-check <file>`` reads a commit message from a file and checks:

* the first line matches the format ``<type>(<scope>): <summary> [Pxx-Tyy]``
  where *type* is one of feat, fix, test, docs, refactor, build, ci, chore,
  the summary is at most 72 characters, and the task id is ``Pxx-<suffix>``;
* no trailer line has a key in the closed list Co-Authored-By, Signed-off-by,
  Generated-by, Reviewed-by, Acked-by, Tested-by;
* no URL (``http://`` or ``https://``) appears anywhere in the message.

Returns 0 if the message is clean, 1 if a violation is found, 2 on usage
error.  The same check runs in CI over every commit of the pull request.

Spec: Part 1 §4.9.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

__all__ = [
    "COMMIT_TYPES",
    "FORBIDDEN_TRAILERS",
    "check_commit_message",
    "main",
]

COMMIT_TYPES: frozenset[str] = frozenset(
    {"feat", "fix", "test", "docs", "refactor", "build", "ci", "chore"}
)

FORBIDDEN_TRAILERS: frozenset[str] = frozenset(
    {
        "co-authored-by",
        "signed-off-by",
        "generated-by",
        "reviewed-by",
        "acked-by",
        "tested-by",
    }
)

_MAX_SUMMARY = 72

_TYPE_ALTERNATION = "|".join(COMMIT_TYPES)
# <type>(<scope>): <summary> [Pxx-Tyy]
# The task id suffix may be Tnn, ENDn, STUB, etc.
_COMMIT_FORMAT_RE = re.compile(rf"^({_TYPE_ALTERNATION})\(([^)]+)\): (.+) \[P\d+-[A-Z0-9]+\]$")

_URL_RE = re.compile(r"https?://", re.IGNORECASE)

_TRAILER_RE = re.compile(r"^([A-Za-z][A-Za-z-]*):\s*(.*)$")


def check_commit_message(text: str) -> list[str]:
    """Return a list of violation descriptions (empty = clean)."""
    violations: list[str] = []
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        violations.append("empty commit message")
        return violations

    first = lines[0]
    match = _COMMIT_FORMAT_RE.match(first)
    if match is None:
        violations.append("first line does not match commit format §4.3")
    else:
        summary = match.group(3)
        if len(summary) > _MAX_SUMMARY:
            violations.append(f"summary exceeds {_MAX_SUMMARY} characters ({len(summary)})")

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        trailer_match = _TRAILER_RE.match(stripped)
        if trailer_match:
            key = trailer_match.group(1).lower()
            if key in FORBIDDEN_TRAILERS:
                violations.append(f"forbidden trailer: {trailer_match.group(1)}")

    if _URL_RE.search(text):
        violations.append("URL found in commit message")

    return violations


def main(file_path: Path | None = None) -> int:
    """Entry point: ``gate commit-check <file>``.

    When *file_path* is ``None``, reads the file from ``sys.argv[1]``.
    """
    if file_path is None:
        args = sys.argv[1:]
        if len(args) != 1:
            print("usage: gate commit-check <file>", file=sys.stderr)
            return 2
        file_path = Path(args[0])
    if not file_path.is_file():
        print(f"commit-check: file not found: {file_path}", file=sys.stderr)
        return 2
    text = file_path.read_text(encoding="utf-8")
    violations = check_commit_message(text)
    if violations:
        for v in violations:
            print(f"commit-check: {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
