"""Tests for the risk policy compliance-phrase check (P01-T01).

Every test carries a header (id, title, purpose, level, requirement ids,
input, expected result, risk covered, owning capability) per Part 4 §4.5.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_RISK_SCRIPT = REPO_ROOT / "risk-management" / "tools" / "risk.py"
_POLICY = REPO_ROOT / "risk-management" / "policy" / "RISK-POLICY.md"


@pytest.mark.fast
def test_policy_has_no_forbidden_phrases() -> None:
    """id: T-RISK-0002
    title: RISK-POLICY.md contains no compliance-claim phrases
    purpose: Verify the policy does not claim compliance, certification or
    conformity with any standard.
    level: fast
    requirement: P01-T01 acceptance, Part 7 section 7.2 phrase list
    input: risk-management/policy/RISK-POLICY.md
    expected: exit code 0 (no forbidden phrase found)
    risk: a compliance claim would be a false statement about the product
    capability: none
    """
    result = subprocess.run(
        [sys.executable, str(_RISK_SCRIPT), "check-phrases", str(_POLICY)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"forbidden phrases in policy: {result.stderr}"


@pytest.mark.fast
def test_forbidden_phrase_detection_finds_violation(tmp_path: Path) -> None:
    """id: T-RISK-0035
    title: check-phrases catches a known compliance-claim violation
    purpose: Verify the phrase checker detects forbidden phrases in a file.
    level: fast
    requirement: P01-T01 acceptance, Part 7 section 7.2 phrase list
    input: a temporary file containing 'certified' and 'guaranteed'
    expected: exit code 1 (forbidden phrases detected)
    risk: a broken checker would miss real compliance claims
    capability: none
    """
    bad = tmp_path / "bad.md"
    bad.write_text(
        "This product is certified and guaranteed to be risk-free.",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(_RISK_SCRIPT), "check-phrases", str(bad)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 1, f"expected exit 1 (phrases detected), got {result.returncode}"
    assert "certified" in result.stderr
    assert "guaranteed" in result.stderr
