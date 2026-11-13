"""Cross-reference checker for the risk management system (P01-T02).

Checks that every id referenced by a record (controls, risk_id, etc.)
exists in the appropriate register.
"""

from __future__ import annotations


def check_references(
    records: list[dict[str, object]],
    all_control_ids: set[str],
) -> list[str]:
    """Check that control references in records point to existing controls.

    Args:
        records: list of risk/hazard/threat records with a 'controls' field.
        all_control_ids: set of all valid control ids.

    Returns:
        List of error messages for missing control references.
    """
    errors: list[str] = []
    for record in records:
        rid = record.get("id", "?")
        if not isinstance(rid, str):
            rid = "?"
        controls = record.get("controls", [])
        if not isinstance(controls, list):
            continue
        for ctrl_id in controls:
            if not isinstance(ctrl_id, str):
                errors.append(f"{rid}: control reference is not a string")
                continue
            if ctrl_id not in all_control_ids:
                errors.append(f"{rid}: control '{ctrl_id}' does not exist")
    return errors


def check_acceptance_references(
    acceptances: list[dict[str, object]],
    all_risk_ids: set[str],
) -> list[str]:
    """Check that acceptance records reference existing risks."""
    errors: list[str] = []
    for acc in acceptances:
        aid = acc.get("id", "?")
        if not isinstance(aid, str):
            aid = "?"
        risk_id = acc.get("risk_id", "")
        if not isinstance(risk_id, str):
            risk_id = ""
        if risk_id not in all_risk_ids:
            errors.append(f"{aid}: references unknown risk '{risk_id}'")
    return errors
