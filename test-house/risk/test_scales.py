"""Tests for risk scale validation (P01-T01).

Every test carries a header (id, title, purpose, level, requirement ids,
input, expected result, risk covered, owning capability) per Part 4 §4.5.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_RISK_SCRIPT = REPO_ROOT / "risk-management" / "tools" / "risk.py"


@pytest.mark.fast
def test_validate_scales_passes() -> None:
    """id: T-RISK-0001
    title: risk validate scales exits 0 on valid SCALES.yaml
    purpose: Verify that the scales file validates successfully.
    level: fast
    requirement: P01-T01 acceptance
    input: risk-management/methodology/SCALES.yaml
    expected: exit code 0
    risk: invalid scales would misclassify risk scores
    capability: none
    """
    result = subprocess.run(
        [sys.executable, str(_RISK_SCRIPT), "validate", "scales"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"expected exit 0, got {result.returncode}: {result.stderr}"


@pytest.mark.fast
def test_validate_scales_fails_on_bad_scales(tmp_path: Path) -> None:
    """id: T-RISK-0018
    title: risk validate scales fails on invalid scales
    purpose: Verify that a malformed scales file is rejected.
    level: fast
    requirement: P01-T01 acceptance
    input: a temporary SCALES.yaml with empty scales
    expected: exit code 1
    risk: invalid scales would misclassify risk scores
    capability: none
    """
    bad_scales = tmp_path / "SCALES.yaml"
    bad_scales.write_text(
        "likelihood:\n  scale: []\nseverity:\n  scale: []\n",
        encoding="utf-8",
    )
    env = {**os.environ, "SCALES_PATH": str(bad_scales)}
    result = subprocess.run(
        [sys.executable, str(_RISK_SCRIPT), "validate", "scales"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert result.returncode == 1, f"expected exit 1, got {result.returncode}: {result.stderr}"
