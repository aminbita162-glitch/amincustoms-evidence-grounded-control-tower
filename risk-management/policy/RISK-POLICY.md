# Risk Policy

## Scope

This policy covers risk in the Customs and Transit Control Tower across two
dimensions:

1. **Product risk in use**: risks that arise when the product operates on
   cases — wrong ALLOW, wrong or invented extraction, document-borne prompt
   injection, rule pack staleness, wrong classification, missed screening
   hit, cross-tenant leakage, ledger tampering or loss, agent runaway, cost
   overrun, model provider outage or deprecation, solver plan errors, personal
   data in logs, SYNTHETIC data presented as real, explanation misread as
   advice, key compromise, and stale reference data treated as current.

2. **Project risk in build**: risks that arise during development —
   dev-agent drift or hallucinated fact, gate tampering, token budget
   overrun, dependency compromise, external terms not matching licence or
   data conditions, unverified source used, directive integrity, single-owner
   dependency, loss of repository, release differing from audited code, audit
   blind spot, and reduced analysis coverage.

The policy also covers **hazards** (chains of cause to harm), **threats**
(adversarial actions against trust boundaries), **model risk** (safeguards
S1 to S7 of decision D-06), **data and legal risk** (verification items
V-01, V-04, V-05, V-07, V-08, V-16), and **continuity** (restore,
crypto-erasure, exit to a second host).

## Roles

Only the owner accepts risk. The agent proposes risk treatments and
registers findings; it never accepts a risk. A risk above the register
threshold (residual score 10 or higher, or any residual severity 5) requires
a written owner acceptance recorded in `risk-management/acceptance/`.

## No compliance claims

This policy and the risk management system make no claim of compliance,
certification or conformity with any standard, regulation or framework.
Process references used during audits are reading aids, not conformance
targets.

## Residual-risk statement

Residual risks are listed in the register with their scores, controls and
acceptance status. Scores are estimates made with the stated scales and are
not measurements. This statement makes no claim of compliance, certification
or conformity with any standard or regulation.

## Labels

All data in this system carries a label (OFFICIAL, DERIVED, SECONDARY,
SIMULATED_RULE, SYNTHETIC, ASSUMPTION, UNVERIFIED). Risk scores are labelled
ASSUMPTION until measured values replace them under an owner decision.
