# Acceptance Record Template

<!--
  An acceptance record is a YAML file under risk-management/acceptance/
  (not this template).  Copy this template, fill in the fields, and name
  the file after the acceptance id (e.g. ACC-001.yaml).

  Only the owner accepts risk; the agent proposes, never accepts
  (Part 1 §3.1, Part 7 Risk Management section 4).

  Every acceptance references a decision record in docs/decisions/.
  The validator checks that the decision file exists and that the
  acceptance has not expired (Part 6 §6.5).
-->

## Fields

| field           | type    | required | description                                        |
|-----------------|---------|----------|----------------------------------------------------|
| id              | string  | yes      | Acceptance id, pattern `^ACC-`                     |
| risk_id         | string  | yes      | Risk id from a register                            |
| residual_score  | integer | yes      | Residual score (likelihood × severity, 1–25)      |
| reason          | string  | yes      | Owner's rationale for accepting the residual risk  |
| decision_id    | string  | yes      | Decision id in `docs/decisions/` (e.g. `D-35`)     |
| expiry_date    | string  | yes      | Expiry month (`YYYY-MM`)                            |
| review_date     | string  | yes      | Review month (`YYYY-MM`)                            |
| accountable     | string  | yes      | Always `OWNER`                                      |

## Example

```yaml
records:
  - id: ACC-001
    risk_id: RSK-P-01
    residual_score: 12
    reason: >
      Owner accepts the residual risk of a wrong ALLOW on a case
      where the model proposes but the gate has not yet been built.
    decision_id: D-35
    expiry_date: "2027-05"
    review_date: "2026-11"
    accountable: OWNER
```