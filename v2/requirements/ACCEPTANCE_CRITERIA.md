# Acceptance Criteria

## Purpose and Status

This document is the checkable acceptance contract for the complete manager-facing demo. AC-01 through AC-20 refine the minimum criteria in the supplied build specification, while AC-21 through AC-24 add role enforcement, repeatable packaging, presentation quality, and demo-safety obligations required by the approved implementation plan.

All criteria are **DEMO DESIGN** obligations. At STEP-01 completion their implementation status is `NOT IMPLEMENTED`; subsequent batch gates must update status only when the referenced evidence exists.

## Status Values

`NOT IMPLEMENTED` means the owning application capability does not yet exist. `IN PROGRESS` means implementation exists but required validation is incomplete. `PASS` means the required evidence has been produced. `FAIL` means validation ran and the observable result did not meet the criterion.

## Criteria and Verification Mapping

| ID | Observable acceptance criterion | Primary validation | Expected evidence | Initial status |
| --- | --- | --- | --- | --- |
| AC-01 | A requester can create an invitation that persists with `INVITED` workflow status. | VAL-04 invitation API and browser flow | Invitation record, linked visit state, and audit event | `NOT IMPLEMENTED` |
| AC-02 | An invitation can be converted into linked person, company, site, and visit records with `PRE_REGISTERED` status. | VAL-04 registration flow | Linked records and registration audit event | `NOT IMPLEMENTED` |
| AC-03 | Synthetic evidence can be uploaded, extracted, edited, verified, rejected, or requested again. | VAL-04 evidence API and browser flow | Private object reference, editable extraction, lifecycle states, and audit events | `NOT IMPLEMENTED` |
| AC-04 | Evidence issue and expiry dates are persisted as timezone-aware values and displayed to users. | VAL-04 API and persistence assertions | Dates visible in evidence responses and cards | `NOT IMPLEMENTED` |
| AC-05 | Required SHEQ and site-rule training can be completed and persisted. | VAL-05 training API and browser flow | Completion records and person timeline entries | `NOT IMPLEMENTED` |
| AC-06 | Training tests store attempts, scores, pass or fail outcomes, completion times, and expiry. | VAL-05 service and API tests | Distinct attempt records with calculated result | `NOT IMPLEMENTED` |
| AC-07 | An active person or company blacklist entry blocks approval and gate access. | VAL-05 and VAL-06 blacklist tests | Blocked compliance check, forbidden approval or token action, and gate denial | `NOT IMPLEMENTED` |
| AC-08 | Only an approved, currently eligible visit can receive an active QR access token. | VAL-05 approval and token tests | Active token for eligible visit and rejected issue attempts for blocked visits | `NOT IMPLEMENTED` |
| AC-09 | The gate can evaluate a scanned, pasted, or seeded opaque token reference. | VAL-06 gate API and kiosk tests | Correct visit context loaded without personal data in QR payload | `NOT IMPLEMENTED` |
| AC-10 | Gate operators can run and see a deterministic identity result, confidence, provider mode, and `DEMO MODE` label. | VAL-06 match and mismatch tests | Typed provider result rendered on the gate screen | `NOT IMPLEMENTED` |
| AC-11 | The backend calculates the final gate decision and returns typed checks, reasons, and corrective actions. | VAL-06 gate-service tests | `GRANT` or `DENY` response with ordered checks and no duplicated frontend rules | `NOT IMPLEMENTED` |
| AC-12 | A granted gate decision can create one active presence record, and exit closes it. | VAL-07 entry and exit tests | `PRESENT` record followed by `EXITED` with timestamp | `NOT IMPLEMENTED` |
| AC-13 | A denied attempt persists reason codes, readable reasons, corrective actions, operator, provider mode, and timestamp. | VAL-06 denial tests | Immutable gate-event snapshot and audit event | `NOT IMPLEMENTED` |
| AC-14 | Site and date dashboard values derive from persisted visits, gate events, presence, approvals, and expiry data. | VAL-07 aggregate tests | Metrics change after entry and exit without frontend constants | `NOT IMPLEMENTED` |
| AC-15 | Expiry processing creates alerts and unique re-validation tasks for configured renewal windows. | VAL-08 demo-clock and expiry tests | 30-, 14-, 7-day or expired alert and non-duplicated task | `NOT IMPLEMENTED` |
| AC-16 | Expired blocking evidence or training changes compliance state and causes gate denial. | VAL-06 and VAL-08 gate evaluation after expiry | `EXPIRED` check and actionable `DENY` result | `NOT IMPLEMENTED` |
| AC-17 | Verified renewal completes re-validation, recalculates compliance, and restores eligibility. | VAL-08 renewal and second-gate flow | Completed task, updated audit trail, and later `GRANT` | `NOT IMPLEMENTED` |
| AC-18 | The complete lifecycle is visible in append-only audit history and the person timeline. | VAL-09 audit query and timeline inspection | Required events in chronological order with actor and reason | `NOT IMPLEMENTED` |
| AC-19 | The complete demo works without third-party credentials through deterministic local providers. | VAL-01 and VAL-11 no-credential execution | `DEMO MODE` providers and passing connected workflow | `NOT IMPLEMENTED` |
| AC-20 | A Playwright test completes the connected flow from invitation through re-validation and a second gate evaluation. | VAL-11 complete browser suite | Passing trace for the full lifecycle | `NOT IMPLEMENTED` |
| AC-21 | Seeded roles are enforced by the API and reflected in frontend navigation and actions. | VAL-03 API and browser role matrices | Forbidden responses and correct module visibility for all seven roles | `NOT IMPLEMENTED` |
| AC-22 | Docker Compose boot, migrations, deterministic seed, and reset repeat from clean volumes. | VAL-02 clean-environment cycles | Two successful migrate, seed, reset, and health cycles | `NOT IMPLEMENTED` |
| AC-23 | Major screens are responsive, accessible, manager-ready, and provide loading, empty, error, success, and permission states. | VAL-10 and VAL-12 quality checks and walkthrough | No broken, inaccessible, or dead-end major state at desktop and tablet widths | `NOT IMPLEMENTED` |
| AC-24 | Only synthetic data is committed, secrets are excluded, uploads are constrained, and QR payloads contain no raw personal data. | VAL-01, VAL-10, and VAL-12 safety inspection | Synthetic assets, private uploads, clean secret scan, and opaque QR content | `NOT IMPLEMENTED` |

## Validation Definitions

| Validation ID | Required method |
| --- | --- |
| VAL-01 | Inspect credential, environment, integration, and demo-data contracts and verify that every external capability has a named deterministic local fallback. |
| VAL-02 | Run clean Compose shutdown and volume removal, build and start services, migrate, seed, check health, reset, and repeat. |
| VAL-03 | Run API authorization tests and browser role-navigation checks for every seeded role. |
| VAL-04 | Run invitation, registration, evidence, extraction, verification, upload-safety, and audit tests plus the Steps 1-3 browser flow. |
| VAL-05 | Run training scoring, blacklist, compliance, approval, token issue, and token revoke tests plus the Steps 4-6 browser flow. |
| VAL-06 | Run gate decision tests for valid, expired, wrong-site, missing-approval, blacklist, evidence, training, identity, and precedence outcomes. |
| VAL-07 | Run entry, exit, roster, and dashboard aggregate tests and observe client refresh after gate activity. |
| VAL-08 | Advance demo time, run expiry processing, verify denial, renew the item, complete re-validation, and verify restored access. |
| VAL-09 | Query the audit API and person timeline for each required event in chronological order. |
| VAL-10 | Run backend lint and tests, frontend lint and typecheck, upload validation, accessibility checks, and secret scanning. |
| VAL-11 | Run the complete Playwright happy path, four denial scenarios, re-validation scenario, role checks, and clean-reset smoke test. |
| VAL-12 | Execute the manager walkthrough at desktop and tablet widths and inspect synthetic assets, QR contents, permissions, copy, and failure states. |

## Batch Ownership

Batch 0 owns AC-19, AC-22, and the initial safety foundation for AC-24. Batch 1 owns roles, audit foundations, and relational records. Batches 2 through 6 own the connected eleven-step workflow. Batch 7 owns final hardening and manager-facing quality. Batch 8 owns complete automated coverage, final documentation, and clean-room acceptance.

No criterion may be marked `PASS` solely because a page, endpoint, or database table exists. Its required observable behavior and validation evidence must both be present.
