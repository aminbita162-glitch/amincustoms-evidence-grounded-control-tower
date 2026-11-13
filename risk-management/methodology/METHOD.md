# Risk Methodology

## Identification sources

Risks are identified from:

1. The product invariants (Part 3 section 3.1, I1 to I14).
2. The product requirements (Part 2 section 2.12, PR-01 to PR-17).
3. The threat model (Part 3 section 3.15) and trust boundaries.
4. The model safeguards (decision D-06, S1 to S7).
5. The verification register (V-01 to V-31).
6. The architecture decision (D-32, sections 2.3 to 2.5).
7. Hazards as chains: hazard, cause, hazardous situation, harm, control.

## Scoring

Each risk has an inherent likelihood and severity (1 to 5 each) and a
residual likelihood and severity after controls. The score is
likelihood times severity (range 1 to 25). Bands: 1 to 4 low, 5 to 9
medium, 10 to 14 high, 15 to 25 critical. Scales and anchors are in
`SCALES.yaml`.

## Treatment order

Treatments are applied in order: eliminate, reduce, detect, transfer,
accept. Only the owner accepts a risk; the agent proposes and never
accepts.

## Control lifecycle

Each control has a lifecycle status:

- **PLANNED**: the control is designed but not yet implemented; it names
  a target phase.
- **IMPLEMENTED**: the control is built but not yet verified.
- **VERIFIED**: the control is built and verified by an existing test id
  in the test index.

## Review triggers

Risk reviews run at:

- Every phase exit (the phase risk review task).
- Every incident.
- Every new dependency, model change or pack change.
- Every closure of a verification item that affects a label.
- At least every 3 months in operation (month-level).

## Register files

The methodology produces and maintains these register files:

- `risk-management/registers/product-risks.yaml` — product risks.
- `risk-management/registers/project-risks.yaml` — project risks.
- `risk-management/registers/hazards.yaml` — hazard analysis.
- `risk-management/registers/threats.yaml` — threat model.
- `risk-management/registers/ai-model-risks.yaml` — model risks.
- `risk-management/registers/data-legal-risks.yaml` — data and legal risks.
- `risk-management/controls/catalogue.yaml` — control catalogue.
- `risk-management/acceptance/` — acceptance records.
- `risk-management/incidents/LOG.yaml` — incident log.
- `risk-management/runbooks/` — runbook templates.
- `risk-management/continuity/DRILLS.yaml` — continuity drills.
- `risk-management/reviews/` — phase risk review records.
