"""Tests for the docs gate (P00-T09).

Every test carries a header (id, title, purpose, level, requirement ids, input,
expected result, risk covered, owning capability) per Part 4 §4.5.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.gate.gates.docs import (
    check_docs,
    check_links,
)

# ---------------------------------------------------------------------------
# T-DOCS-0001 — Missing honesty line fails
# ---------------------------------------------------------------------------
# id: T-DOCS-0001
# title: A missing honesty line makes the docs gate fail
# purpose: Verify that a README missing one of the two required honesty lines
#          is rejected by the docs gate.
# level: fast
# requirement ids: P00-T09, Part 8 §8.3
# scenario ids: S-DOCS-HONESTY
# input: a README with the first honesty line removed
# expected result: check_docs returns a non-empty list containing "required line"
# risk covered: the honesty statement is dropped from the README without detection
# owning capability: docs-gate


def _valid_readme(row_count: int = 3) -> str:
    """Generate a valid README with the given number of Build Progress rows."""
    lines: list[str] = [
        "A person's worth lies in their honesty.",
        "This holds regardless of position, title or role.",
        "",
        "# AminCustoms Evidence-Grounded Control Tower",
        "",
        "Evidence-grounded advisory pre-checks for customs and transit cases.",
        "",
        "## 9 Build Progress",
        "",
        "| Phase | Name | Status |",
        "|---|---|---|",
    ]
    for i in range(row_count):
        lines.append(f"| P{i:02d} | Phase {i} | \u2610 |")
    return "\n".join(lines) + "\n"


def _phases_toml(count: int = 3) -> str:
    """Generate a phases.toml with the given number of phases."""
    parts: list[str] = []
    for i in range(count):
        parts.append(f"[phase.P{i:02d}]")
        parts.append(f'name = "Phase {i}"')
        parts.append('class = "S"')
        parts.append("capabilities = []")
        parts.append("depends_on = []")
        parts.append("")
    return "\n".join(parts)


@pytest.mark.fast
def test_missing_honesty_line_fails(tmp_path: Path) -> None:
    """A missing honesty line makes the docs gate fail."""
    readme = _valid_readme().replace("A person's worth lies in their honesty.\n", "")
    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme, encoding="utf-8")
    phases_path = tmp_path / "phases.toml"
    phases_path.write_text(_phases_toml(), encoding="utf-8")
    errors = check_docs(readme_path, phases_path)
    assert errors
    assert any("required line" in e for e in errors)


# ---------------------------------------------------------------------------
# T-DOCS-0002 — Code block fails
# ---------------------------------------------------------------------------
# id: T-DOCS-0002
# title: A fenced code block makes the docs gate fail
# purpose: Verify that a README containing a triple-backtick code block is
#          rejected by the docs gate.
# level: fast
# requirement ids: P00-T09, Part 8 §8.3
# scenario ids: S-DOCS-CODEBLOCK
# input: a valid README with a fenced code block appended
# expected result: check_docs returns a non-empty list containing "code block"
# risk covered: code blocks appear in the README in place of generated content
# owning capability: docs-gate


@pytest.mark.fast
def test_code_block_fails(tmp_path: Path) -> None:
    """A fenced code block makes the docs gate fail."""
    readme = _valid_readme() + "\n```\ncode\n```\n"
    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme, encoding="utf-8")
    phases_path = tmp_path / "phases.toml"
    phases_path.write_text(_phases_toml(), encoding="utf-8")
    errors = check_docs(readme_path, phases_path)
    assert any("code block" in e for e in errors)


# ---------------------------------------------------------------------------
# T-DOCS-0003 — Row mismatch fails
# ---------------------------------------------------------------------------
# id: T-DOCS-0003
# title: A Build Progress row count mismatch makes the docs gate fail
# purpose: Verify that a README whose Build Progress row count does not match
#          the phase count in phases.toml is rejected by the docs gate.
# level: fast
# requirement ids: P00-T09, Part 6 §6.2
# scenario ids: S-DOCS-ROWMISMATCH
# input: a README with 2 Build Progress rows and a phases.toml with 3 phases
# expected result: check_docs returns a non-empty list containing "Build Progress"
# risk covered: the Build Progress table drifts from the phase table
# owning capability: docs-gate


@pytest.mark.fast
def test_row_mismatch_fails(tmp_path: Path) -> None:
    """A Build Progress row count mismatch makes the docs gate fail."""
    readme = _valid_readme(row_count=2)
    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme, encoding="utf-8")
    phases_path = tmp_path / "phases.toml"
    phases_path.write_text(_phases_toml(count=3), encoding="utf-8")
    errors = check_docs(readme_path, phases_path)
    assert any("Build Progress" in e for e in errors)


# ---------------------------------------------------------------------------
# T-DOCS-0004 — Broken link fails
# ---------------------------------------------------------------------------
# id: T-DOCS-0004
# title: A broken local link makes the docs gate fail
# purpose: Verify that a README containing a markdown link to a non-existent
#          local file is rejected by the docs gate.
# level: fast
# requirement ids: P00-T09, Part 8 §8.3
# scenario ids: S-DOCS-BROKENLINK
# input: a valid README with a link to a non-existent file
# expected result: check_docs returns a non-empty list containing "broken link"
# risk covered: the README links to a file that does not exist
# owning capability: docs-gate


@pytest.mark.fast
def test_broken_link_fails(tmp_path: Path) -> None:
    """A broken local link makes the docs gate fail."""
    readme = _valid_readme() + "\n[broken](nonexistent.md)\n"
    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme, encoding="utf-8")
    phases_path = tmp_path / "phases.toml"
    phases_path.write_text(_phases_toml(), encoding="utf-8")
    errors = check_docs(readme_path, phases_path)
    assert any("broken link" in e for e in errors)


# ---------------------------------------------------------------------------
# T-DOCS-0005 — Tick set only by the phase-end command
# ---------------------------------------------------------------------------
# id: T-DOCS-0005
# title: A hand-edited tick in Build Progress makes the docs gate fail
# purpose: Verify that a Build Progress row with a tick when no phase is
#          completed is rejected by the docs gate; the tick may be set only
#          by the phase-end command after updating STATE.json.
# level: fast
# requirement ids: P00-T09, Part 8 §8.3
# scenario ids: S-DOCS-TICK
# input: a valid README with a tick on P00, no STATE.json
# expected result: check_docs returns a non-empty list containing "tick"
# risk covered: a Build Progress tick is hand-edited rather than set by the phase-end command
# owning capability: docs-gate


@pytest.mark.fast
def test_hand_edited_tick_fails(tmp_path: Path) -> None:
    """A hand-edited tick in Build Progress makes the docs gate fail."""
    readme = _valid_readme().replace("| P00 | Phase 0 | \u2610 |", "| P00 | Phase 0 | \u2713 |")
    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme, encoding="utf-8")
    phases_path = tmp_path / "phases.toml"
    phases_path.write_text(_phases_toml(), encoding="utf-8")
    errors = check_docs(readme_path, phases_path, state_path=None)
    assert any("tick" in e for e in errors)


# ---------------------------------------------------------------------------
# T-DOCS-0006 — Forbidden pattern fails
# ---------------------------------------------------------------------------
# id: T-DOCS-0006
# title: A forbidden pattern in the README makes the docs gate fail
# purpose: Verify that a README containing a marketing adjective or a
#          compliance-claim phrase is rejected by the docs gate.
# level: fast
# requirement ids: P00-T09, Part 8 §8.3, P7-RISK §3
# scenario ids: S-DOCS-FORBIDDEN
# input: a valid README with a forbidden pattern ("powerful") appended
# expected result: check_docs returns a non-empty list containing "forbidden pattern"
# risk covered: marketing or compliance-claim wording appears in the README
# owning capability: docs-gate


@pytest.mark.fast
def test_forbidden_pattern_fails(tmp_path: Path) -> None:
    """A forbidden pattern in the README makes the docs gate fail."""
    readme = _valid_readme() + "\nThis system is powerful and elegant.\n"
    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme, encoding="utf-8")
    phases_path = tmp_path / "phases.toml"
    phases_path.write_text(_phases_toml(), encoding="utf-8")
    errors = check_docs(readme_path, phases_path)
    assert any("forbidden pattern" in e for e in errors)


# ---------------------------------------------------------------------------
# T-DOCS-LINKS — check_links skips external and anchor links
# ---------------------------------------------------------------------------
# id: T-DOCS-LINKS
# title: check_links skips http, https and anchor links
# purpose: Verify that check_links does not flag external or anchor links,
#          only local relative links that do not resolve.
# level: fast
# requirement ids: P00-T09, Part 8 §8.3
# scenario ids: S-DOCS-LINKS-SKIP
# input: a text with http, https and anchor links
# expected result: check_links returns an empty list
# risk covered: external or anchor links are incorrectly flagged as broken
# owning capability: docs-gate


@pytest.mark.fast
def test_check_links_skips_external_and_anchor(tmp_path: Path) -> None:
    """check_links skips http, https and anchor links."""
    text = "[external](https://example.com)\n[anchor](#section)\n[http](http://example.org)\n"
    errors = check_links(text, tmp_path / "README.md")
    assert errors == []
