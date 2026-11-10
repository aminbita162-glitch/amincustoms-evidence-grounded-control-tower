"""Docs gate — README structural checks (P00-T09).

Checks ``README.md`` against the fixed texts of ``<<<P8-README-FIXED>>>`` and
the phase table of ``tools/gate/phases.toml``:

* Required lines present (honesty lines 1-2, project name, tagline).
* No code blocks (triple backtick).
* Forbidden patterns absent (marketing adjectives, compliance claims).
* Build Progress rows equal the phase count in ``phases.toml``.
* Links resolve (local relative links exist).
* The tick is set only by the phase-end command (no hand-edited ticks).

Invokable as ``python -m tools.gate.gates.docs``.
Exit codes: 0 all checks pass, 1 any check fails, 2 misconfiguration.

Spec: Part 6 §6.2, Part 8 §8.3, P00-T09.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path

__all__ = [
    "DocsError",
    "REQUIRED_HONESTY_LINES",
    "PROJECT_NAME",
    "PROJECT_TAGLINE",
    "FORBIDDEN_PATTERNS",
    "load_phases_count",
    "check_required_lines",
    "check_no_code_blocks",
    "check_forbidden_patterns",
    "check_build_progress",
    "check_links",
    "check_ticks",
    "check_docs",
    "main",
]


class DocsError(Exception):
    """A docs gate configuration error."""


REQUIRED_HONESTY_LINES: tuple[str, ...] = (
    "A person's worth lies in their honesty.",
    "This holds regardless of position, title or role.",
)

PROJECT_NAME = "Evidence-Grounded Control Tower"
PROJECT_TAGLINE = "Evidence-grounded advisory pre-checks for customs and transit cases."

FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "powerful",
    "elegant",
    "seamless",
    "robust",
    "cutting-edge",
    "industry-leading",
    "world-class",
    "revolutionary",
    "game-changing",
    "next-generation",
    "state-of-the-art",
    "best-in-class",
    "lightning-fast",
    "blazing fast",
    "compliant with",
    "in compliance with",
    "certified",
    "conforms to",
    "conformant",
    "meets the requirements of",
    "guarantees",
    "guaranteed",
    "risk-free",
    "no risk",
    "fully mitigated",
    "eliminates all",
)


def _repo_root() -> Path:
    """Resolve the repository root, respecting GATE_ROOT if set."""
    gate_root = os.environ.get("GATE_ROOT")
    if gate_root:
        return Path(gate_root).resolve()
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    """The ``tools/gate`` package directory (parent of this module's package)."""
    return Path(__file__).resolve().parents[1]


def load_phases_count(path: Path) -> int:
    """Count the ``[phase.PNN]`` entries in a ``phases.toml`` file."""
    try:
        with path.open("rb") as stream:
            raw: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DocsError(f"cannot load phases.toml: {exc}") from exc
    phase_table: object = raw.get("phase") if isinstance(raw, dict) else None
    if not isinstance(phase_table, dict):
        raise DocsError("phases.toml has no [phase.*] tables")
    return len(phase_table)


def check_required_lines(text: str) -> list[str]:
    """Check that the honesty lines, project name and tagline are present."""
    errors: list[str] = []
    for line in REQUIRED_HONESTY_LINES:
        if line not in text:
            errors.append(f"missing required line: {line}")
    if PROJECT_NAME not in text:
        errors.append(f"missing project name: {PROJECT_NAME}")
    if PROJECT_TAGLINE not in text:
        errors.append(f"missing project tagline: {PROJECT_TAGLINE}")
    return errors


def check_no_code_blocks(text: str) -> list[str]:
    """Check that the README contains no triple-backtick code blocks."""
    if "```" in text:
        return ["README contains a fenced code block (triple backtick)"]
    return []


def check_forbidden_patterns(text: str) -> list[str]:
    """Check that no forbidden patterns appear in the README."""
    errors: list[str] = []
    lower = text.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.lower() in lower:
            errors.append(f"forbidden pattern in README: {pattern}")
    return errors


def check_build_progress(text: str, phases_count: int) -> list[str]:
    """Check that the Build Progress row count matches the phases count."""
    rows = re.findall(r"^\|\s*P\d{2}\s*\|", text, re.MULTILINE)
    if len(rows) != phases_count:
        return [f"Build Progress has {len(rows)} rows, expected {phases_count}"]
    return []


def check_links(text: str, readme_path: Path) -> list[str]:
    """Check that markdown links in the README resolve."""
    errors: list[str] = []
    for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
        url = match.group(1).strip()
        if url.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target = readme_path.parent / url
        if not target.exists():
            errors.append(f"broken link: {url}")
    return errors


def check_ticks(text: str, last_completed_phase: str | None) -> list[str]:
    """Check that no Build Progress row has a hand-edited tick.

    A tick is allowed only for phases at or before the last completed phase
    recorded in ``STATE.json``.  When no state is available, no ticks are
    allowed at all (nothing has been completed).
    """
    errors: list[str] = []
    if last_completed_phase is None:
        completed_num = -1
    else:
        try:
            completed_num = int(last_completed_phase[1:])
        except ValueError, IndexError:
            completed_num = -1
    for match in re.finditer(r"^\|\s*(P\d{2})\s*\|.*$", text, re.MULTILINE):
        line = match.group(0)
        phase = match.group(1)
        phase_num = int(phase[1:])
        if "✓" in line and phase_num > completed_num:
            errors.append(f"Build Progress row {phase} has a tick but the phase is not completed")
    return errors


def check_docs(
    readme_path: Path,
    phases_path: Path,
    state_path: Path | None = None,
) -> list[str]:
    """Run all docs checks.  Returns a list of error messages (empty = pass)."""
    if not readme_path.is_file():
        return [f"README not found: {readme_path}"]
    try:
        text = readme_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read README: {exc}"]

    try:
        phases_count = load_phases_count(phases_path)
    except DocsError as exc:
        return [str(exc)]

    errors: list[str] = []
    errors.extend(check_required_lines(text))
    errors.extend(check_no_code_blocks(text))
    errors.extend(check_forbidden_patterns(text))
    errors.extend(check_build_progress(text, phases_count))
    errors.extend(check_links(text, readme_path))

    last_completed: str | None = None
    if state_path is not None and state_path.is_file():
        try:
            raw: object = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                value = raw.get("last_completed_phase")
                if isinstance(value, str):
                    last_completed = value
        except OSError, json.JSONDecodeError:
            pass
    errors.extend(check_ticks(text, last_completed))

    return errors


def main() -> int:
    """Entry point for the docs gate."""
    readme = Path.cwd() / "README.md"
    phases = _gate_dir() / "phases.toml"
    state = _repo_root() / "docs" / "state" / "STATE.json"
    errors = check_docs(readme, phases, state)
    if errors:
        for error in errors:
            print(f"docs: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
