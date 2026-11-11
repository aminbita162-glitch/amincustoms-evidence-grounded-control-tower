"""Threat and safeguard coverage tests (P01-T05).

T-RISK-0018: every threat of Part 3 section 3.15 has an entry in the threat
register.
T-RISK-0019: every safeguard S1 to S7 of decision-d06 maps to a model risk
and a control.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = REPO_ROOT / "risk-management" / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import loader  # noqa: E402

# Threats from Part 3 section 3.15 (Security Architecture).
_P3_S15_THREATS: tuple[str, ...] = (
    "prompt injection through documents",
    "tool abuse",
    "data exfiltration through the model",
    "poisoned reference data",
    "memory poisoning",
    "agent goal drift and runaway behavior",
    "evidence tampering and replay",
    "cross-case and cross-tenant leakage",
    "hostile files",
    "supply-chain compromise",
    "secret exposure",
)

# Safeguards from decision-d06 section 3.
_SAFEGUARDS: tuple[str, ...] = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")


@pytest.mark.fast
def test_threat_coverage_p3_s15() -> None:
    """id: T-RISK-0018
    title: every threat of Part 3 section 3.15 has an entry
    purpose: Verify that the threat register covers every threat listed in
    Part 3 section 3.15 (Security Architecture).
    level: fast
    requirement: P01-T05 acceptance
    input: the threat register and the Part 3 section 3.15 threat list
    expected: every threat is referenced by at least one entry
    risk: an uncovered threat would leave a security gap
    capability: none
    """
    threats_path = REPO_ROOT / "risk-management" / "registers" / "threats.yaml"
    records = loader.load_register(threats_path)
    assert records, "threat register is empty or missing"

    combined = " ".join(
        str(r.get("title", "")) + " " + str(r.get("description", "")) for r in records
    ).lower()

    missing = [t for t in _P3_S15_THREATS if t not in combined]
    assert not missing, f"threats from Part 3 §3.15 not covered by the threat register: {missing}"


@pytest.mark.fast
def test_safeguard_coverage_d06() -> None:
    """id: T-RISK-0019
    title: every safeguard S1 to S7 of decision-d06 maps to a model risk and a
    control
    purpose: Verify that every safeguard S1 to S7 of decision-d06 has a
    corresponding model risk entry with a control reference.
    level: fast
    requirement: P01-T05 acceptance
    input: the model risk register and the decision-d06 safeguard list
    expected: every safeguard S1 to S7 is referenced by a model risk with a
    control
    risk: an uncovered safeguard would leave a model safety gap
    capability: none
    """
    model_risks_path = REPO_ROOT / "risk-management" / "registers" / "ai-model-risks.yaml"
    records = loader.load_register(model_risks_path)
    assert records, "model risk register is empty or missing"

    combined = " ".join(
        str(r.get("description", ""))
        + " "
        + str(r.get("source", ""))
        + " "
        + str(r.get("cause", ""))
        for r in records
    )
    controls_present = all(
        isinstance(r.get("controls"), list) and r.get("controls") for r in records
    )
    assert controls_present, "some model risks lack control references"

    missing = [s for s in _SAFEGUARDS if s not in combined]
    assert not missing, (
        f"safeguards from decision-d06 not covered by model risk register: {missing}"
    )
