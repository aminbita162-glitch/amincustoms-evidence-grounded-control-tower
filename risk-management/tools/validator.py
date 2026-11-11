"""Schema validator for the risk management system (P01-T02).

Implements a lightweight JSON Schema validator (required fields, type
checking, enum, pattern, minimum/maximum, const, additionalProperties,
items) and higher-level validation rules (unique ids, lifecycle, risk
fields, cross-references).
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import link_checker  # noqa: E402
import loader  # noqa: E402

_RISK_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]

_COMPLETED_PHASES: set[str] = {"P00"}


def _check_type(value: object, expected: str) -> bool:
    """Check that *value* matches the JSON Schema *expected* type."""
    if expected == "object":
        return isinstance(value, dict)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return type(value) is int  # noqa: E721 — bool is not int
    if expected == "array":
        return isinstance(value, list)
    if expected == "boolean":
        return isinstance(value, bool)
    return False


def validate_record(record: dict[str, object], schema: dict[str, object]) -> list[str]:
    """Validate *record* against *schema*.

    Supports: required, type, enum, pattern, minimum, maximum, const,
    additionalProperties, items (with type), properties.
    """
    errors: list[str] = []
    rid = record.get("id", "?")
    if not isinstance(rid, str):
        rid = "?"
    required = schema.get("required", [])
    if isinstance(required, list):
        for field in required:
            field_name = field if isinstance(field, str) else "?"
            if field_name not in record:
                errors.append(f"{rid}: missing required field '{field_name}'")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    for key, value in record.items():
        if key not in properties:
            addl = schema.get("additionalProperties", True)
            if addl is False:
                errors.append(f"{rid}: unexpected field '{key}'")
            continue
        prop_schema = properties[key]
        if not isinstance(prop_schema, dict):
            continue
        expected_type = prop_schema.get("type")
        if isinstance(expected_type, str) and not _check_type(value, expected_type):
            errors.append(
                f"{rid}: field '{key}' must be {expected_type}, got {type(value).__name__}"
            )
            continue
        if "enum" in prop_schema:
            enum_vals = prop_schema["enum"]
            if isinstance(enum_vals, list) and value not in enum_vals:
                errors.append(f"{rid}: field '{key}' value '{value}' not in {enum_vals}")
        if "const" in prop_schema and value != prop_schema["const"]:
            errors.append(f"{rid}: field '{key}' must be '{prop_schema['const']}', got '{value}'")
        if "pattern" in prop_schema and isinstance(value, str):
            pattern = prop_schema["pattern"]
            if isinstance(pattern, str) and not re.match(pattern, value):
                errors.append(f"{rid}: field '{key}' value '{value}' does not match '{pattern}'")
        if "minimum" in prop_schema and isinstance(value, int) and not isinstance(value, bool):
            min_val = prop_schema["minimum"]
            if isinstance(min_val, int) and value < min_val:
                errors.append(f"{rid}: field '{key}' value {value} below minimum {min_val}")
        if "maximum" in prop_schema and isinstance(value, int) and not isinstance(value, bool):
            max_val = prop_schema["maximum"]
            if isinstance(max_val, int) and value > max_val:
                errors.append(f"{rid}: field '{key}' value {value} above maximum {max_val}")
        if expected_type == "array" and "items" in prop_schema and isinstance(value, list):
            item_schema = prop_schema["items"]
            if isinstance(item_schema, dict):
                item_type = item_schema.get("type")
                if isinstance(item_type, str):
                    for item in value:
                        if not _check_type(item, item_type):
                            errors.append(f"{rid}: field '{key}' contains non-{item_type} item")
    return errors


def validate_unique_ids(records: list[dict[str, object]]) -> list[str]:
    """Check that all records have unique ids."""
    errors: list[str] = []
    seen: set[str] = set()
    for record in records:
        rid = record.get("id", "")
        if not isinstance(rid, str) or not rid:
            errors.append("record without an id")
            continue
        if rid in seen:
            errors.append(f"duplicate id '{rid}'")
        seen.add(rid)
    return errors


def validate_control_lifecycle(
    controls: list[dict[str, object]],
    test_ids: set[str],
) -> list[str]:
    """Check control lifecycle rules.

    - PLANNED controls must have a target_phase.
    - PLANNED controls whose target_phase has been reached are overdue.
    - VERIFIED controls must have verifying_test_ids that exist in the index.
    """
    errors: list[str] = []
    for ctrl in controls:
        cid = ctrl.get("id", "?")
        if not isinstance(cid, str):
            cid = "?"
        status = ctrl.get("lifecycle_status", "")
        if not isinstance(status, str):
            status = ""
        if status == "PLANNED":
            target = ctrl.get("target_phase")
            if not isinstance(target, str) or not target:
                errors.append(f"{cid}: PLANNED control without target_phase")
            elif target in _COMPLETED_PHASES:
                errors.append(
                    f"{cid}: control overdue (target_phase {target} reached, still PLANNED)"
                )
        elif status == "VERIFIED":
            test_ids_field = ctrl.get("verifying_test_ids", [])
            if not isinstance(test_ids_field, list) or not test_ids_field:
                errors.append(f"{cid}: VERIFIED control without verifying_test_ids")
            elif isinstance(test_ids_field, list):
                for tid in test_ids_field:
                    if isinstance(tid, str) and tid not in test_ids:
                        errors.append(f"{cid}: VERIFIED control references unknown test id '{tid}'")
    return errors


def validate_risk_fields(records: list[dict[str, object]]) -> list[str]:
    """Check that every risk record has an area and an accountable role."""
    errors: list[str] = []
    for record in records:
        rid = record.get("id", "?")
        if not isinstance(rid, str):
            rid = "?"
        area = record.get("area")
        if not isinstance(area, str) or not area:
            errors.append(f"{rid}: risk without an area")
        accountable = record.get("accountable")
        if not isinstance(accountable, str) or not accountable:
            errors.append(f"{rid}: risk without an accountable role")
    return errors


def collect_referenced_controls(
    register_records: list[list[dict[str, object]]],
) -> set[str]:
    """Collect every control id referenced by the given register record lists."""
    referenced: set[str] = set()
    for records in register_records:
        for record in records:
            controls = record.get("controls", [])
            if not isinstance(controls, list):
                continue
            for cid in controls:
                if isinstance(cid, str):
                    referenced.add(cid)
    return referenced


def validate_orphan_controls(
    controls: list[dict[str, object]],
    referenced_ids: set[str],
) -> list[str]:
    """Check that every control in the catalogue is used by a register record.

    A control that no risk, hazard, threat or model risk references is orphan.
    """
    errors: list[str] = []
    for ctrl in controls:
        cid = ctrl.get("id", "?")
        if not isinstance(cid, str):
            cid = "?"
        if cid not in referenced_ids:
            errors.append(f"{cid}: orphan control (not used by any register record)")
    return errors


def validate_risk_has_controls(
    risk_records: list[dict[str, object]],
    acceptance_risk_ids: set[str] | None = None,
) -> list[str]:
    """Check that every risk has at least one control or an explicit acceptance.

    A risk with an empty controls list is accepted only if it has an acceptance
    record (identified by *acceptance_risk_ids*); otherwise it is a violation.
    """
    if acceptance_risk_ids is None:
        acceptance_risk_ids = set()
    errors: list[str] = []
    for record in risk_records:
        rid = record.get("id", "?")
        if not isinstance(rid, str):
            rid = "?"
        controls = record.get("controls", [])
        if isinstance(controls, list) and len(controls) > 0:
            continue
        if rid in acceptance_risk_ids:
            continue
        errors.append(f"{rid}: risk without a control or an acceptance request")
    return errors


def validate_acceptance(
    acceptances: list[dict[str, object]],
    decisions_dir: Path,
    now_month: str | None = None,
) -> list[str]:
    """Check that acceptance records reference existing decisions and are not expired.

    - Each acceptance's decision_id must correspond to a file in *decisions_dir*.
    - Each acceptance's expiry_date must not be in the past (month-level).
    """
    if now_month is None:
        now_month = datetime.datetime.now(datetime.UTC).strftime("%Y-%m")
    errors: list[str] = []
    for acc in acceptances:
        aid = acc.get("id", "?")
        if not isinstance(aid, str):
            aid = "?"
        decision_id = acc.get("decision_id")
        if isinstance(decision_id, str) and decision_id:
            decision_path = decisions_dir / f"{decision_id}.md"
            if not decision_path.exists():
                errors.append(f"{aid}: decision file not found: {decision_id}.md")
        expiry = acc.get("expiry_date")
        if isinstance(expiry, str) and expiry and expiry < now_month:
            errors.append(f"{aid}: acceptance expired (expiry {expiry})")
    return errors


def validate_all(repo_root: Path | None = None) -> int:
    """Run all validations on the risk-management directory.

    Returns 0 if all validations pass, 1 if any fails, 2 if misconfigured.
    """
    if repo_root is None:
        repo_root = _REPO_ROOT
    risk_dir = repo_root / "risk-management"
    errors: list[str] = []
    test_ids = loader.load_test_ids(repo_root / "test-house" / "INDEX.md")
    all_control_ids = loader.load_all_control_ids()
    controls = loader.load_register(risk_dir / "controls" / "catalogue.yaml")

    register_map: list[tuple[str, str]] = [
        ("registers/product-risks.yaml", "risk"),
        ("registers/project-risks.yaml", "risk"),
        ("registers/hazards.yaml", "hazard"),
        ("registers/threats.yaml", "threat"),
        ("registers/ai-model-risks.yaml", "risk"),
        ("registers/data-legal-risks.yaml", "risk"),
    ]
    all_register_records: list[list[dict[str, object]]] = []
    all_risk_records: list[dict[str, object]] = []
    for rel_path, schema_name in register_map:
        path = risk_dir / rel_path
        if not path.exists():
            continue
        records = loader.load_register(path)
        if not records:
            continue
        all_register_records.append(records)
        schema = loader.load_schema(schema_name)
        for record in records:
            errors.extend(validate_record(record, schema))
        errors.extend(validate_unique_ids(records))
        if schema_name == "risk":
            errors.extend(validate_risk_fields(records))
            all_risk_records.extend(records)
        errors.extend(link_checker.check_references(records, all_control_ids))

    if controls:
        control_schema = loader.load_schema("control")
        for ctrl in controls:
            errors.extend(validate_record(ctrl, control_schema))
        errors.extend(validate_unique_ids(controls))
        errors.extend(validate_control_lifecycle(controls, test_ids))
        referenced_ids = collect_referenced_controls(all_register_records)
        errors.extend(validate_orphan_controls(controls, referenced_ids))

    if all_risk_records:
        acceptance_risk_ids = loader.load_acceptance_risk_ids(risk_dir)
        errors.extend(validate_risk_has_controls(all_risk_records, acceptance_risk_ids))

    reviews_dir = risk_dir / "reviews"
    if reviews_dir.exists():
        review_schema = loader.load_schema("review")
        for review_file in sorted(reviews_dir.glob("P*.md.yaml")):
            records = loader.load_register(review_file)
            for record in records:
                errors.extend(validate_record(record, review_schema))

    incidents_path = risk_dir / "incidents" / "LOG.yaml"
    if incidents_path.exists():
        incident_schema = loader.load_schema("incident")
        incidents = loader.load_register(incidents_path)
        for inc in incidents:
            errors.extend(validate_record(inc, incident_schema))

    drills_path = risk_dir / "continuity" / "DRILLS.yaml"
    if drills_path.exists():
        drill_schema = loader.load_schema("drill")
        drills = loader.load_register(drills_path)
        for drl in drills:
            errors.extend(validate_record(drl, drill_schema))

    acceptance_dir = risk_dir / "acceptance"
    if acceptance_dir.exists():
        acceptance_schema = loader.load_schema("acceptance")
        all_acceptances: list[dict[str, object]] = []
        for acc_file in sorted(acceptance_dir.glob("*.yaml")):
            records = loader.load_register(acc_file)
            for record in records:
                errors.extend(validate_record(record, acceptance_schema))
            all_acceptances.extend(records)
        if all_acceptances:
            errors.extend(validate_unique_ids(all_acceptances))
            decisions_dir = repo_root / "docs" / "decisions"
            errors.extend(validate_acceptance(all_acceptances, decisions_dir))

    if errors:
        for e in errors:
            print(f"validate: {e}", file=sys.stderr)
        return 1
    return 0
