"""Tests for the risk schema validator (P01-T02).

Every test carries a header (id, title, purpose, level, requirement ids,
input, expected result, risk covered, owning capability) per Part 4 §4.5.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = REPO_ROOT / "risk-management" / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import link_checker  # noqa: E402
import loader  # noqa: E402
import validator  # noqa: E402


def test_risk_schema_valid() -> None:
    """id: T-RISK-0003
    title: risk record validates against risk schema
    purpose: Verify that a valid risk record passes schema validation.
    level: fast
    requirement: P01-T02 acceptance
    input: a valid risk record
    expected: no errors
    risk: invalid records would corrupt the risk register
    capability: none
    """
    schema = loader.load_schema("risk")
    record: dict[str, object] = {
        "id": "RSK-P-01",
        "title": "Wrong ALLOW",
        "area": "product",
        "description": "A wrong ALLOW on a case.",
        "inherent_likelihood": 3,
        "inherent_severity": 5,
        "residual_likelihood": 2,
        "residual_severity": 3,
        "treatment": "reduce",
        "controls": ["CTL-P-01"],
        "owner_area": "core",
        "accountable": "OWNER",
        "status": "open",
        "review_date": "2026-11",
        "source": "P7-RISK section 4",
    }
    errors = validator.validate_record(record, schema)
    assert errors == [], f"expected no errors, got {errors}"


def test_risk_schema_invalid() -> None:
    """id: T-RISK-0003
    title: invalid risk record fails schema validation
    purpose: Verify that an invalid risk record is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: a risk record missing required fields
    expected: errors reported
    risk: invalid records would corrupt the risk register
    capability: none
    """
    schema = loader.load_schema("risk")
    record: dict[str, object] = {
        "id": "RSK-P-01",
        "title": "Wrong ALLOW",
    }
    errors = validator.validate_record(record, schema)
    assert len(errors) > 0, "expected errors for missing required fields"


def test_control_schema_valid() -> None:
    """id: T-RISK-0004
    title: control record validates against control schema
    purpose: Verify that a valid control record passes schema validation.
    level: fast
    requirement: P01-T02 acceptance
    input: a valid control record
    expected: no errors
    risk: invalid controls would break risk linkage
    capability: none
    """
    schema = loader.load_schema("control")
    record: dict[str, object] = {
        "id": "CTL-P-01",
        "title": "Label and lattice tests",
        "type": "preventive",
        "mechanism": "Gate-enforced label and lattice checks.",
        "lifecycle_status": "PLANNED",
        "target_phase": "P03",
        "source": "P7-RISK section 11",
    }
    errors = validator.validate_record(record, schema)
    assert errors == [], f"expected no errors, got {errors}"


def test_control_schema_invalid() -> None:
    """id: T-RISK-0004
    title: invalid control record fails schema validation
    purpose: Verify that an invalid control record is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: a control with an invalid type value
    expected: errors reported
    risk: invalid controls would break risk linkage
    capability: none
    """
    schema = loader.load_schema("control")
    record: dict[str, object] = {
        "id": "CTL-P-01",
        "title": "Bad control",
        "type": "invalid_type",
        "mechanism": "test",
        "lifecycle_status": "PLANNED",
        "source": "test",
    }
    errors = validator.validate_record(record, schema)
    assert len(errors) > 0, "expected errors for invalid type"


def test_hazard_schema_valid() -> None:
    """id: T-RISK-0005
    title: hazard record validates against hazard schema
    purpose: Verify that a valid hazard record passes schema validation.
    level: fast
    requirement: P01-T02 acceptance
    input: a valid hazard record
    expected: no errors
    risk: invalid hazards would break the hazard chain
    capability: none
    """
    schema = loader.load_schema("hazard")
    record: dict[str, object] = {
        "id": "HZ-01",
        "title": "Wrong release decision",
        "area": "product",
        "cause": "Wrong ALLOW",
        "hazardous_situation": "Goods released without correct clearance.",
        "harm": "Regulatory penalty.",
        "controls": ["CTL-P-01"],
        "source": "P7-RISK section 6",
    }
    errors = validator.validate_record(record, schema)
    assert errors == [], f"expected no errors, got {errors}"


def test_hazard_schema_invalid() -> None:
    """id: T-RISK-0005
    title: invalid hazard record fails schema validation
    purpose: Verify that an invalid hazard record is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: a hazard missing required fields
    expected: errors reported
    risk: invalid hazards would break the hazard chain
    capability: none
    """
    schema = loader.load_schema("hazard")
    record: dict[str, object] = {"id": "HZ-01", "title": "Bad hazard"}
    errors = validator.validate_record(record, schema)
    assert len(errors) > 0, "expected errors for missing required fields"


def test_threat_schema_valid() -> None:
    """id: T-RISK-0006
    title: threat record validates against threat schema
    purpose: Verify that a valid threat record passes schema validation.
    level: fast
    requirement: P01-T02 acceptance
    input: a valid threat record
    expected: no errors
    risk: invalid threats would miss security exposures
    capability: none
    """
    schema = loader.load_schema("threat")
    record: dict[str, object] = {
        "id": "THR-M-01",
        "title": "Document-borne injection",
        "area": "security",
        "description": "Adversarial content in a document.",
        "trust_boundary": "external documents",
        "controls": ["CTL-P-03"],
        "source": "P7-RISK section 7",
    }
    errors = validator.validate_record(record, schema)
    assert errors == [], f"expected no errors, got {errors}"


def test_threat_schema_invalid() -> None:
    """id: T-RISK-0006
    title: invalid threat record fails schema validation
    purpose: Verify that an invalid threat record is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: a threat missing required fields
    expected: errors reported
    risk: invalid threats would miss security exposures
    capability: none
    """
    schema = loader.load_schema("threat")
    record: dict[str, object] = {"id": "THR-M-01", "title": "Bad threat"}
    errors = validator.validate_record(record, schema)
    assert len(errors) > 0, "expected errors for missing required fields"


def test_acceptance_schema_valid() -> None:
    """id: T-RISK-0007
    title: acceptance record validates against acceptance schema
    purpose: Verify that a valid acceptance record passes schema validation.
    level: fast
    requirement: P01-T02 acceptance
    input: a valid acceptance record
    expected: no errors
    risk: invalid acceptance would allow unreviewed risk
    capability: none
    """
    schema = loader.load_schema("acceptance")
    record: dict[str, object] = {
        "id": "ACC-001",
        "risk_id": "RSK-P-01",
        "residual_score": 12,
        "reason": "Owner accepts residual risk.",
        "decision_id": "D-35",
        "expiry_date": "2027-05",
        "review_date": "2026-11",
        "accountable": "OWNER",
    }
    errors = validator.validate_record(record, schema)
    assert errors == [], f"expected no errors, got {errors}"


def test_acceptance_schema_invalid() -> None:
    """id: T-RISK-0007
    title: invalid acceptance record fails schema validation
    purpose: Verify that an acceptance with wrong accountable is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: an acceptance with accountable != OWNER
    expected: errors reported
    risk: invalid acceptance would allow unreviewed risk
    capability: none
    """
    schema = loader.load_schema("acceptance")
    record: dict[str, object] = {
        "id": "ACC-001",
        "risk_id": "RSK-P-01",
        "residual_score": 12,
        "reason": "test",
        "decision_id": "D-35",
        "expiry_date": "2027-05",
        "review_date": "2026-11",
        "accountable": "AGENT",
    }
    errors = validator.validate_record(record, schema)
    assert len(errors) > 0, "expected errors for accountable != OWNER"


def test_review_schema_valid() -> None:
    """id: T-RISK-0008
    title: review record validates against review schema
    purpose: Verify that a valid review record passes schema validation.
    level: fast
    requirement: P01-T02 acceptance
    input: a valid review record
    expected: no errors
    risk: invalid reviews would skip required risk checks
    capability: none
    """
    schema = loader.load_schema("review")
    record: dict[str, object] = {
        "id": "REV-P01",
        "phase": "P01",
        "review_date": "2026-11",
        "risks_new_or_changed": ["RSK-P-01"],
        "controls_added": ["CTL-P-01"],
    }
    errors = validator.validate_record(record, schema)
    assert errors == [], f"expected no errors, got {errors}"


def test_review_schema_invalid() -> None:
    """id: T-RISK-0008
    title: invalid review record fails schema validation
    purpose: Verify that an invalid review record is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: a review missing required fields
    expected: errors reported
    risk: invalid reviews would skip required risk checks
    capability: none
    """
    schema = loader.load_schema("review")
    record: dict[str, object] = {"id": "REV-P01"}
    errors = validator.validate_record(record, schema)
    assert len(errors) > 0, "expected errors for missing required fields"


def test_incident_schema_valid() -> None:
    """id: T-RISK-0009
    title: incident record validates against incident schema
    purpose: Verify that a valid incident record passes schema validation.
    level: fast
    requirement: P01-T02 acceptance
    input: a valid incident record
    expected: no errors
    risk: invalid incidents would lose audit trail
    capability: none
    """
    schema = loader.load_schema("incident")
    record: dict[str, object] = {
        "id": "INC-001",
        "title": "Test incident",
        "date": "2026-11",
        "area": "product",
        "description": "A test incident.",
        "status": "open",
    }
    errors = validator.validate_record(record, schema)
    assert errors == [], f"expected no errors, got {errors}"


def test_incident_schema_invalid() -> None:
    """id: T-RISK-0009
    title: invalid incident record fails schema validation
    purpose: Verify that an invalid incident record is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: an incident with invalid status
    expected: errors reported
    risk: invalid incidents would lose audit trail
    capability: none
    """
    schema = loader.load_schema("incident")
    record: dict[str, object] = {
        "id": "INC-001",
        "title": "Bad incident",
        "date": "2026-11",
        "area": "test",
        "description": "test",
        "status": "invalid",
    }
    errors = validator.validate_record(record, schema)
    assert len(errors) > 0, "expected errors for invalid status"


def test_drill_schema_valid() -> None:
    """id: T-RISK-0010
    title: drill record validates against drill schema
    purpose: Verify that a valid drill record passes schema validation.
    level: fast
    requirement: P01-T02 acceptance
    input: a valid drill record
    expected: no errors
    risk: invalid drills would skip continuity tests
    capability: none
    """
    schema = loader.load_schema("drill")
    record: dict[str, object] = {
        "id": "DRL-001",
        "title": "Restore drill",
        "type": "restore",
        "planned_date": "2027-01",
        "status": "planned",
    }
    errors = validator.validate_record(record, schema)
    assert errors == [], f"expected no errors, got {errors}"


def test_drill_schema_invalid() -> None:
    """id: T-RISK-0010
    title: invalid drill record fails schema validation
    purpose: Verify that an invalid drill record is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: a drill with invalid type
    expected: errors reported
    risk: invalid drills would skip continuity tests
    capability: none
    """
    schema = loader.load_schema("drill")
    record: dict[str, object] = {
        "id": "DRL-001",
        "title": "Bad drill",
        "type": "invalid",
        "planned_date": "2027-01",
        "status": "planned",
    }
    errors = validator.validate_record(record, schema)
    assert len(errors) > 0, "expected errors for invalid type"


def test_unique_ids_pass() -> None:
    """id: T-RISK-0011
    title: unique ids pass validation
    purpose: Verify that records with unique ids pass.
    level: fast
    requirement: P01-T02 acceptance
    input: two records with different ids
    expected: no errors
    risk: duplicate ids would confuse cross-references
    capability: none
    """
    records: list[dict[str, object]] = [
        {"id": "RSK-P-01", "title": "A"},
        {"id": "RSK-P-02", "title": "B"},
    ]
    errors = validator.validate_unique_ids(records)
    assert errors == [], f"expected no errors, got {errors}"


def test_unique_ids_fail() -> None:
    """id: T-RISK-0011
    title: duplicate ids fail validation
    purpose: Verify that records with duplicate ids are rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: two records with the same id
    expected: errors reported
    risk: duplicate ids would confuse cross-references
    capability: none
    """
    records: list[dict[str, object]] = [
        {"id": "RSK-P-01", "title": "A"},
        {"id": "RSK-P-01", "title": "B"},
    ]
    errors = validator.validate_unique_ids(records)
    assert len(errors) > 0, "expected errors for duplicate ids"


def test_references_pass() -> None:
    """id: T-RISK-0012
    title: valid control references pass
    purpose: Verify that references to existing controls pass.
    level: fast
    requirement: P01-T02 acceptance
    input: a record referencing an existing control
    expected: no errors
    risk: broken references would link risks to missing controls
    capability: none
    """
    records: list[dict[str, object]] = [
        {"id": "RSK-P-01", "controls": ["CTL-P-01"]},
    ]
    all_control_ids: set[str] = {"CTL-P-01"}
    errors = link_checker.check_references(records, all_control_ids)
    assert errors == [], f"expected no errors, got {errors}"


def test_references_fail() -> None:
    """id: T-RISK-0012
    title: broken control references fail
    purpose: Verify that references to non-existent controls are rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: a record referencing a missing control
    expected: errors reported
    risk: broken references would link risks to missing controls
    capability: none
    """
    records: list[dict[str, object]] = [
        {"id": "RSK-P-01", "controls": ["CTL-NONEXISTENT"]},
    ]
    all_control_ids: set[str] = {"CTL-P-01"}
    errors = link_checker.check_references(records, all_control_ids)
    assert len(errors) > 0, "expected errors for missing control reference"


def test_lifecycle_planned_with_target() -> None:
    """id: T-RISK-0013
    title: PLANNED control with target_phase passes
    purpose: Verify that a PLANNED control with a target_phase passes.
    level: fast
    requirement: P01-T02 acceptance
    input: a PLANNED control with target_phase P03
    expected: no errors
    risk: missing target phase would leave controls without a plan
    capability: none
    """
    controls: list[dict[str, object]] = [
        {"id": "CTL-P-01", "lifecycle_status": "PLANNED", "target_phase": "P03"},
    ]
    errors = validator.validate_control_lifecycle(controls, set())
    assert errors == [], f"expected no errors, got {errors}"


def test_lifecycle_planned_without_target() -> None:
    """id: T-RISK-0013
    title: PLANNED control without target_phase fails
    purpose: Verify that a PLANNED control without a target_phase is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: a PLANNED control without target_phase
    expected: errors reported
    risk: missing target phase would leave controls without a plan
    capability: none
    """
    controls: list[dict[str, object]] = [
        {"id": "CTL-P-01", "lifecycle_status": "PLANNED"},
    ]
    errors = validator.validate_control_lifecycle(controls, set())
    assert len(errors) > 0, "expected errors for PLANNED without target_phase"


def test_control_overdue_pass() -> None:
    """id: T-RISK-0014
    title: PLANNED control with unreached target_phase passes
    purpose: Verify that a PLANNED control whose target_phase is not yet
    reached passes.
    level: fast
    requirement: P01-T02 acceptance
    input: a PLANNED control with target_phase P03
    expected: no errors
    risk: overdue controls would leave risks unmitigated
    capability: none
    """
    controls: list[dict[str, object]] = [
        {"id": "CTL-P-01", "lifecycle_status": "PLANNED", "target_phase": "P03"},
    ]
    errors = validator.validate_control_lifecycle(controls, set())
    assert errors == [], f"expected no errors, got {errors}"


def test_control_overdue_fail() -> None:
    """id: T-RISK-0014
    title: PLANNED control with reached target_phase fails as overdue
    purpose: Verify that a PLANNED control whose target_phase has been
    reached is flagged as overdue.
    level: fast
    requirement: P01-T02 acceptance
    input: a PLANNED control with target_phase P00 (completed)
    expected: errors reported (overdue)
    risk: overdue controls would leave risks unmitigated
    capability: none
    """
    controls: list[dict[str, object]] = [
        {"id": "CTL-P-01", "lifecycle_status": "PLANNED", "target_phase": "P00"},
    ]
    errors = validator.validate_control_lifecycle(controls, set())
    assert len(errors) > 0, "expected errors for overdue control"
    assert "overdue" in errors[0], f"expected 'overdue' in error, got {errors[0]}"


def test_verified_with_known_test_id() -> None:
    """id: T-RISK-0015
    title: VERIFIED control with known test id passes
    purpose: Verify that a VERIFIED control with an existing test id passes.
    level: fast
    requirement: P01-T02 acceptance
    input: a VERIFIED control with verifying_test_ids referencing an existing test
    expected: no errors
    risk: unverified controls would be claimed as verified
    capability: none
    """
    controls: list[dict[str, object]] = [
        {
            "id": "CTL-P-01",
            "lifecycle_status": "VERIFIED",
            "verifying_test_ids": ["T-RISK-0001"],
        },
    ]
    test_ids: set[str] = {"T-RISK-0001"}
    errors = validator.validate_control_lifecycle(controls, test_ids)
    assert errors == [], f"expected no errors, got {errors}"


def test_verified_with_unknown_test_id() -> None:
    """id: T-RISK-0015
    title: VERIFIED control with unknown test id fails
    purpose: Verify that a VERIFIED control referencing an unknown test id
    is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: a VERIFIED control with verifying_test_ids referencing a non-existent test
    expected: errors reported
    risk: unverified controls would be claimed as verified
    capability: none
    """
    controls: list[dict[str, object]] = [
        {
            "id": "CTL-P-01",
            "lifecycle_status": "VERIFIED",
            "verifying_test_ids": ["T-NONEXISTENT-9999"],
        },
    ]
    test_ids: set[str] = {"T-RISK-0001"}
    errors = validator.validate_control_lifecycle(controls, test_ids)
    assert len(errors) > 0, "expected errors for unknown test id"


def test_risk_fields_pass() -> None:
    """id: T-RISK-0016
    title: risk with area and accountable passes
    purpose: Verify that a risk with both area and accountable passes.
    level: fast
    requirement: P01-T02 acceptance
    input: a risk record with area and accountable
    expected: no errors
    risk: missing area or accountable would leave risks unowned
    capability: none
    """
    records: list[dict[str, object]] = [
        {"id": "RSK-P-01", "area": "product", "accountable": "OWNER"},
    ]
    errors = validator.validate_risk_fields(records)
    assert errors == [], f"expected no errors, got {errors}"


def test_risk_fields_fail() -> None:
    """id: T-RISK-0016
    title: risk without area or accountable fails
    purpose: Verify that a risk missing area or accountable is rejected.
    level: fast
    requirement: P01-T02 acceptance
    input: a risk record without area and without accountable
    expected: errors reported
    risk: missing area or accountable would leave risks unowned
    capability: none
    """
    records: list[dict[str, object]] = [
        {"id": "RSK-P-01"},
    ]
    errors = validator.validate_risk_fields(records)
    assert len(errors) > 0, "expected errors for missing area and accountable"
