"""Coverage test for invariant and requirement references (P01-T03).

Every invariant I1 to I14 (Part 3 §3.1) and every requirement PR-01 to
PR-17 (Part 2 §2.12) must be referenced by at least one risk or control
record in the risk-management registers.
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

_INVARIANTS = [f"I{n}" for n in range(1, 15)]
_REQUIREMENTS = [f"PR-{n:02d}" for n in range(1, 18)]


def _all_record_text(records: list[dict[str, object]]) -> str:
    """Concatenate all string values from a list of records."""
    parts: list[str] = []
    for record in records:
        for value in record.values():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        parts.append(item)
    return " ".join(parts)


@pytest.mark.fast
def test_invariant_requirement_coverage() -> None:
    """id: T-RISK-0017
    title: every invariant and requirement is referenced by a risk or control
    purpose: Verify that every invariant I1 to I14 and every requirement
    PR-01 to PR-17 is cited by at least one risk or control record.
    level: fast
    requirement: P01-T03 acceptance
    input: the product risk register and the control catalogue
    expected: every invariant and every requirement is referenced
    risk: an uncovered invariant or requirement would leave a design gap
    capability: none
    """
    risk_dir = REPO_ROOT / "risk-management"
    combined: list[dict[str, object]] = []

    register_files = [
        risk_dir / "registers" / "product-risks.yaml",
        risk_dir / "registers" / "project-risks.yaml",
        risk_dir / "registers" / "hazards.yaml",
        risk_dir / "registers" / "threats.yaml",
        risk_dir / "registers" / "ai-model-risks.yaml",
        risk_dir / "registers" / "data-legal-risks.yaml",
    ]
    for path in register_files:
        if path.exists():
            combined.extend(loader.load_register(path))

    catalogue = risk_dir / "controls" / "catalogue.yaml"
    if catalogue.exists():
        combined.extend(loader.load_register(catalogue))

    text = _all_record_text(combined)

    missing_invariants = [inv for inv in _INVARIANTS if inv not in text]
    missing_requirements = [req for req in _REQUIREMENTS if req not in text]

    assert not missing_invariants, (
        f"invariants not referenced by any risk or control: {missing_invariants}"
    )
    assert not missing_requirements, (
        f"requirements not referenced by any risk or control: {missing_requirements}"
    )
