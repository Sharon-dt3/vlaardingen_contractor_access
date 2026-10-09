---
artifact_type: implementation_plan
plan_id: renewi-access-batch-8-final-acceptance-supplement
title: Batch 8 Final Acceptance and Remaining Dependent Work
status: in_progress
revision: 1
approved_revision: 1
approval:
  state: approved
execution:
  state: in_progress
  executing_revision: 1
risk_level: high
plan_depth: large
source_specs:
  - requirements/ACCEPTANCE_CRITERIA.md
  - requirements/README.md
primary_references:
  - "User request: Start Batch 8 feature-development workflow and create an implementation-ready plan from accessible metadata."
  - requirements/ACCEPTANCE_CRITERIA.md
other_references:
  - requirements/ENVIRONMENT.md
  - requirements/INTEGRATIONS.md
  - requirements/DEMO_DATA.md
  - requirements/OPEN_QUESTIONS.md
  - docker-compose.yml
  - pytest.ini
  - apps/web/package.json
  - services/api/app/main.py
  - tests/api/test_step15_gate_decision.py
  - tests/api/test_batch6_expiry_revalidation.py
  - tests/browser/test_step11_evidence_ready.py
  - tests/browser/test_step14_training_to_qr.py
  - tests/browser/test_batch6_expiry_revalidation.py
  - tests/browser/test_batch7_ui_hardening.py
dependencies:
  - "Completed workflow implementation through STEP-16 remains outside this plan unless validation exposes a direct regression."
  - "The protected existing plan at kavia-docs/CodeWiki/Artifacts/Plans/renewi-contractor-visitor-site-access-implementation-plan.md is explicitly excluded from inspection, reconstruction, modification, and replacement."
open_questions:
  - id: OQ-B8-01
    text: "Accessible metadata defines Batch 8 as the final named batch. No Batch 9 or later scope is available, so this plan closes Batch 8 and records no successor batch."
  - id: OQ-B8-02
    text: "The exact CI runner and browser-image provisioning contract are not established in accessible metadata. The implementation must make the existing Compose e2e service executable rather than assuming a hosted CI platform."
acceptance_criteria:
  - id: B8-AC-01
    text: "An automated browser suite proves the connected synthetic lifecycle from invitation through evidence, training, approval, QR token issue, gate grant, presence, expiry, verified renewal, re-validation, and a later gate grant."
  - id: B8-AC-02
    text: "The automated suite proves four seeded denials for expired evidence, failed training, active blacklist, and identity mismatch, while retaining backend-authoritative reasons and corrective actions."
  - id: B8-AC-03
    text: "A clean local Compose cycle can build, migrate, seed, reset, reseed, and health-check the credential-free application twice without externally configured providers."
  - id: B8-AC-04
    text: "The final acceptance matrix maps AC-01 through AC-24 to executable validation or recorded inspection evidence, with no criterion marked passed merely because an endpoint or screen exists."
  - id: B8-AC-05
    text: "Final operator documentation states the verified local commands, synthetic-data and demo-mode limitations, and recovery behavior without exposing secrets or claiming unverified production behavior."
validation_strategy:
  - id: B8-VAL-01
    validates: [B8-AC-01, B8-AC-02]
    method: "Run the new tests/e2e Playwright suite through docker compose --profile e2e run --rm e2e and retain trace, screenshot, and report artifacts for failures."
  - id: B8-VAL-02
    validates: [B8-AC-01, B8-AC-02, B8-AC-04]
    method: "Run python -m pytest tests/api and the existing focused Selenium workflows for Steps 11, 14, Batch 6, and Batch 7 against a healthy local application."
  - id: B8-VAL-03
    validates: [B8-AC-03]
    method: "Perform two clean cycles using docker compose down -v --remove-orphans, docker compose --profile application up -d --build --wait, migrate, seed, reset, seed, and GET /health."
  - id: B8-VAL-04
    validates: [B8-AC-04, B8-AC-05]
    method: "Run npm --prefix apps/web run lint, npm --prefix apps/web run typecheck, review provider modes and opaque QR behavior, scan tracked documentation for secret values, and inspect updated acceptance and operator documentation."
steps:
  - id: STEP-B8-01
    title: Establish a runnable Compose-hosted Playwright test package
    agent: TestCodeWritingAgent
    container: all
    depends_on: []
    acceptance: [B8-AC-01, B8-AC-02, B8-AC-03]
    validation: [B8-VAL-01, B8-VAL-03]
    recovery: "If the e2e package or browser container fails, preserve test reports, run docker compose down -v --remove-orphans, and restore the deterministic baseline before retrying."
    status: in_progress
  - id: STEP-B8-02
    title: Add connected lifecycle and deterministic-denial Playwright coverage
    agent: TestCodeWritingAgent
    container: all
    depends_on: [STEP-B8-01]
    acceptance: [B8-AC-01, B8-AC-02]
    validation: [B8-VAL-01]
    recovery: "Each test must reset and reseed before scenario execution and restore the seed baseline in cleanup; retain failure diagnostics rather than rerunning against mutated state."
    status: in_progress
  - id: STEP-B8-03
    title: Complete acceptance regression coverage around existing API and rendered UI boundaries
    agent: TestCodeWritingAgent
    container: all
    depends_on: [STEP-B8-01]
    acceptance: [B8-AC-02, B8-AC-04]
    validation: [B8-VAL-02, B8-VAL-04]
    recovery: "Keep completed implementation behavior unchanged; if a direct regression is found, isolate it with a failing test and route the minimal fix to the owning container before repeating the affected suite."
    status: in_progress
  - id: STEP-B8-04
    title: Execute clean-room and full acceptance validation
    agent: TestExecutionAgent
    container: all
    depends_on: [STEP-B8-02, STEP-B8-03]
    acceptance: [B8-AC-01, B8-AC-02, B8-AC-03, B8-AC-04]
    validation: [B8-VAL-01, B8-VAL-02, B8-VAL-03, B8-VAL-04]
    recovery: "On failure, preserve artifacts under artifacts/batch8, identify the first failing command or scenario, reset the disposable Compose state, and rerun only after the applicable regression has a bounded fix."
    status: in_progress
  - id: STEP-B8-05
    title: Publish verified final acceptance and operator documentation
    agent: DocumentationAgent
    container: all
    depends_on: [STEP-B8-04]
    acceptance: [B8-AC-04, B8-AC-05]
    validation: [B8-VAL-04]
    recovery: "Update documentation only from recorded validation evidence; if an acceptance item remains failed or unverified, preserve that status and document the exact safe next action instead of asserting completion."
    status: to_do
revision_history: []
---

[CodeWiki](../../index.md) / [Artifacts](../index.md) / [Plans](index.md)

# Batch 8 Final Acceptance and Remaining Dependent Work

## Outcome and boundaries

Batch 8 closes the accessible delivery scope with reproducible automated coverage, clean-room acceptance evidence, and final operator documentation for the credential-free Renewi manager demo. It must prove the complete persisted workflow and deterministic denial scenarios without reimplementing completed business capabilities or moving authorization, compliance, token eligibility, or gate-decision logic into the frontend or test code.

This supplemental plan is intentionally separate from `renewi-contractor-visitor-site-access-implementation-plan.md`. That existing plan is inaccessible through the available documentation tooling and is not read, reconstructed, overwritten, or modified by this work. Completed work through STEP-16 is also out of scope unless final validation demonstrates a direct regression. Accessible metadata identifies Batch 8 as the final named batch; no Batch 9 or later batch is planned here.

## Current architecture

The application is a Compose-orchestrated monorepo with a Next.js web application in `apps/web/`, a FastAPI application in `services/api/`, PostgreSQL and Redis services, Alembic migrations in `database/migrations/`, and Python-based browser validation under `tests/browser/`. `services/api/app/main.py` registers the Batch 3 through Batch 6 workflow routers, including the persisted expiry and re-validation endpoints in `services/api/app/routes/batch6.py`. Domain services remain the authority for compliance, expiry processing, gate decisions, presence, audit events, and provider selection.

The test posture is uneven but provides reusable evidence seams. `tests/api/test_step15_gate_decision.py` covers server-side gate precedence and typed response fields. `tests/api/test_batch6_expiry_revalidation.py` covers expiry idempotency and backend restoration of compliance. The focused Selenium workflows in `tests/browser/` exercise invitation and evidence readiness, training through QR issuance, expiry and re-validation, and Batch 7 accessibility hardening. Each workflow uses authenticated browser interactions and retains artifacts. Conversely, `docker-compose.yml` already declares an `e2e` service that runs `npm --prefix tests/e2e test`, but the accessible repository inventory contains no `tests/e2e/` package. Batch 8 must fill that defined-but-unimplemented integration seam rather than replace the existing focused workflows.

## Proposed change overview

The selected approach is to add a small Playwright package at `tests/e2e/` that runs inside the existing Compose `e2e` service and exercises the web and API through their Compose-internal addresses. It will be the consolidated, repeatable acceptance suite for the full lifecycle, four seeded denial scenarios, role checks, and reset smoke coverage. Existing Selenium workflows remain focused regression and diagnostic evidence; they are not rewritten or discarded.

Batch 8 then adds any missing API and rendered-UI regression cases needed to map every requirement acceptance criterion to executable evidence. A clean-room run performs two disposable Compose cycles, executes unit, focused browser, and Playwright suites, and retains only sanitized diagnostics. Final documentation is written from that evidence: it will update acceptance status, explain the verified commands and recovery sequence, and preserve the project's explicit synthetic-data, `DEMO MODE`, and non-production limitations.

## Decisions and invariants

| ID | Decision | Rationale and implementation effect |
| --- | --- | --- |
| DEC-B8-01 | Keep domain services and API authorization authoritative. | Test fixtures may drive public UI and API contracts, but may not add frontend rules or test-only bypasses for compliance, approval, token, gate, presence, or expiry decisions. |
| DEC-B8-02 | Use Playwright in `tests/e2e/` for the consolidated final acceptance suite. | `docker-compose.yml` already owns an `e2e` service whose command targets `tests/e2e`; this is the lowest-risk path to making the existing Compose contract executable. |
| DEC-B8-03 | Preserve the existing Selenium workflows as targeted regression checks. | Their reset behavior, diagnostics, and rendered assertions provide valuable evidence for Steps 11 and 14 and Batches 6 and 7. Batch 8 supplements rather than rewrites them. |
| DEC-B8-04 | Treat reset and seed as mandatory isolation boundaries for mutating acceptance scenarios. | The deterministic seed contract requires repeatable persona states. Tests must never rely on an earlier test's mutable state. |
| DEC-B8-05 | Publish final documentation only from recorded validation evidence. | `AC-01` through `AC-24` may be marked passed only when their specified observable behavior and validation evidence exist. |
| INV-B8-01 | Completed work through STEP-16 remains unchanged unless a direct final-validation regression requires a minimal fix. | This constrains Batch 8 to coverage, acceptance, documentation, and bounded corrective changes. |
| INV-B8-02 | No real credentials, personal data, biometric data, public uploads, or raw QR identity data may appear in tests, artifacts, or documentation. | This preserves the documented demo safety boundary and AC-24. |
| INV-B8-03 | Batch 8 has no accessible successor batch. | Closeout evidence and a precise unresolved-work statement are required if any validation remains incomplete. |

## Execution steps

### STEP-B8-01 — Establish a runnable Compose-hosted Playwright test package

**Owner:** TestCodeWritingAgent  
**Container:** all  
**Status:** 🔄 `in_progress`  
**Depends on:** None  
**Acceptance:** B8-AC-01 — complete lifecycle automation; B8-AC-02 — deterministic denials; B8-AC-03 — credential-free clean execution  
**Validation:** B8-VAL-01 — Compose e2e suite; B8-VAL-03 — clean application cycle  
**Definition of done:** The existing `e2e` Compose service can install and execute a version-pinned Playwright package against the healthy Compose-internal web and API endpoints, producing sanitized failure artifacts.

**Technical approach:** Implement DEC-B8-02 — use the pre-existing `docker-compose.yml` `e2e` service rather than adding an alternate test runner. Create an npm package under `tests/e2e/` with a Playwright configuration that uses `WEB_BASE_URL=http://web:3000` and `API_BASE_URL=http://api:8000`, matching the current Compose environment. The test runtime must use stable `data-testid`, role, label, and accessible-name selectors where current UI identifiers are unavailable, and it must not scrape opaque QR payloads or add a privileged test-only route.

| File/component and symbol | Concrete change or resulting code shape | Integration and compatibility impact | Acceptance and validation |
| --- | --- | --- | --- |
| `tests/e2e/package.json` | Add the isolated npm package, pinned Playwright dependency, non-interactive `test` script, and report script required by the Compose `e2e` command. | Makes the already-declared `npm --prefix tests/e2e test` command executable without changing application dependencies. | B8-AC-01, B8-AC-02 through B8-VAL-01. |
| `tests/e2e/playwright.config.ts` | Configure Compose-internal base URLs, deterministic reporter output, screenshots and traces on failure, bounded retries, and artifact output below `artifacts/batch8/`. | Keeps test artifacts outside production containers and supports failure diagnosis. | B8-AC-03 through B8-VAL-01 and B8-VAL-03. |
| `tests/e2e/support/auth.ts` and `tests/e2e/support/reset.ts` | Provide browser login helpers for seeded roles and API/Compose reset-seed-health helpers that do not expose credentials in reports. | Reuses seeded local accounts and the documented reset contract; does not bypass API authorization. | B8-AC-01 through B8-VAL-01. |
| `docker-compose.yml` `e2e` service | Make only the bounded changes needed to install dependencies deterministically and persist failure diagnostics from the Playwright package. | Retains the existing `web` and `api` health dependencies and e2e profile boundary. | B8-AC-03 through B8-VAL-03. |

#### Implementation Tracker

- [x] Create `tests/e2e/package.json` and lockfile with the Playwright test command expected by the existing `e2e` service.
- [x] Create `tests/e2e/playwright.config.ts` with Compose-internal base URLs and failure-only screenshot, trace, and report retention under `artifacts/batch8/`.
- [x] Add authenticated seeded-role and deterministic reset helpers in `tests/e2e/support/` without logging passwords, opaque QR payloads, or private identifiers.
- [x] Update the bounded `docker-compose.yml` `e2e` runtime only as necessary for deterministic dependency installation and artifact capture.
- [ ] Verify `docker compose --profile e2e run --rm e2e` starts only after the web and API health checks pass.

### STEP-B8-02 — Add connected lifecycle and deterministic-denial Playwright coverage

**Owner:** TestCodeWritingAgent  
**Container:** all  
**Status:** 🔄 `in_progress`  
**Depends on:** STEP-B8-01  
**Acceptance:** B8-AC-01 — complete lifecycle automation; B8-AC-02 — deterministic denials  
**Validation:** B8-VAL-01 — Compose e2e suite  
**Definition of done:** The Playwright suite verifies one complete manager-visible lifecycle, four seeded denials, re-validation recovery, role restrictions, and a reset smoke check from deterministic baseline state.

**Technical approach:** Implement DEC-B8-01 — exercise browser-visible behavior and public API responses while treating `GateService`, compliance evaluation, and re-validation service results as authoritative. The end-to-end happy path must use the synthetic data contract: invitation, registration, evidence handling, scored training, approval, opaque-token issuance, gate grant, entry, dashboard or presence update, expiry, verified renewal, task completion, and a second grant. The denial matrix must cover Sofia's expired VCA, Milan's failed site rules, Noah's blacklist, and Emma's identity mismatch. Where existing screens do not expose a required action, tests may use a documented authenticated API contract only to continue the workflow, and must still assert the relevant rendered state and server-owned outcome.

| File/component and symbol | Concrete change or resulting code shape | Integration and compatibility impact | Acceptance and validation |
| --- | --- | --- | --- |
| `tests/e2e/specs/full-lifecycle.spec.ts` | Add the connected happy-path and re-validation scenario with baseline restoration and ordered audit assertions. | Consolidates evidence currently separated between Steps 11, 14, and Batch 6 without replacing them. | B8-AC-01 through B8-VAL-01. |
| `tests/e2e/specs/gate-denials.spec.ts` | Add seeded tests for expired evidence, failed training, blacklist, and identity mismatch, asserting typed server reasons and corrective actions. | Verifies deterministic demo personas and preserves backend decision authority. | B8-AC-02 through B8-VAL-01. |
| `tests/e2e/specs/roles-and-reset.spec.ts` | Add role-navigation and forbidden-operation checks for all seven roles, plus a reset/reseed smoke scenario. | Extends AC-21 and AC-22 evidence without weakening server authorization. | B8-AC-03 and B8-AC-04 through B8-VAL-01. |

#### Implementation Tracker

- [x] Add `test_full_lifecycle.spec.ts` that connects the seeded renewal invitation, expiry, verified renewal, task completion, rendered workspace, ordered audit evidence, and second gate grant without logging opaque token content.
- [x] Add `test_gate_denials.spec.ts` for Sofia, Milan, Noah, and Emma using the seeded scenario states defined in `requirements/DEMO_DATA.md`.
- [x] Assert decision, primary reason code, reason, corrective action, provider mode, and absence of presence for denied gate scenarios.
- [x] Add `test_roles_and_reset.spec.ts` for seven-role navigation and API-forbidden behavior plus repeated deterministic reset/reseed evidence.
- [x] Ensure every mutating Playwright test restores a valid seed baseline in `afterEach`, including when a scenario fails, when `E2E_BASELINE_COMMAND` is supplied.

### STEP-B8-03 — Complete acceptance regression coverage around existing API and rendered UI boundaries

**Owner:** TestCodeWritingAgent  
**Container:** all  
**Status:** 🔄 `in_progress`  
**Depends on:** STEP-B8-01  
**Acceptance:** B8-AC-02 — deterministic denials; B8-AC-04 — complete acceptance mapping  
**Validation:** B8-VAL-02 — API and focused browser suites; B8-VAL-04 — quality checks  
**Definition of done:** Unit, route, focused browser, and quality checks collectively cover each AC-01 through AC-24 behavior not already proven by the Playwright suite, with a stable acceptance-to-test mapping.

**Technical approach:** Implement DEC-B8-03 — retain the existing focused test files as their owning workflow evidence. Add narrow tests only for uncovered acceptance behavior and direct regressions found during the mapping. Do not refactor completed Batch 1 through Batch 7 implementation to make tests easier; any code change must be a minimal direct-regression fix with its own failing test and validation evidence. The regression matrix must explicitly distinguish executable tests from manual manager-walkthrough or safety inspection evidence.

| File/component and symbol | Concrete change or resulting code shape | Integration and compatibility impact | Acceptance and validation |
| --- | --- | --- | --- |
| `tests/api/test_batch8_acceptance_matrix.py` | Add API-level assertions for uncovered authorization, provider fallback, upload privacy, audit chronology, and aggregate behavior using public service and route contracts. | Supplements existing focused tests; does not duplicate or change domain rules. | B8-AC-04 through B8-VAL-02 and B8-VAL-04. |
| `tests/browser/test_batch7_ui_hardening.py` | Extend only if a documented AC-23 responsive or accessible state lacks final regression coverage. | Preserves existing keyboard, permission-feedback, and gate-recovery tests. | B8-AC-04 through B8-VAL-02. |
| `tests/browser/test_step11_evidence_ready.py`, `tests/browser/test_step14_training_to_qr.py`, and `tests/browser/test_batch6_expiry_revalidation.py` | Add only direct regression assertions required to close an identified acceptance gap. | Existing artifact and reset conventions remain authoritative for focused browser diagnostics. | B8-AC-01, B8-AC-04 through B8-VAL-02. |
| `requirements/ACCEPTANCE_CRITERIA.md` working matrix inputs | Prepare a one-to-one source list of AC and VAL identifiers for the final documentation step; do not mark statuses until clean-room evidence exists. | Maintains stable acceptance identifiers and prevents premature pass claims. | B8-AC-04 through B8-VAL-04. |

#### Implementation Tracker

- [x] Create a requirement-to-test inventory for AC-01 through AC-24 before adding any new regression test.
- [x] Add `tests/api/test_batch8_acceptance_matrix.py` only for acceptance cases not already proven by the current API test suite.
- [x] Review targeted browser regression assertions; none were added because existing lifecycle, denial, role/reset, Step 11, Step 14, Batch 6, and Batch 7 workflows already prove the demonstrated rendered UI boundaries.
- [ ] Run `python -m pytest tests/api` and preserve the failure output or passing summary as validation evidence.
- [ ] Run `npm --prefix apps/web run lint` and `npm --prefix apps/web run typecheck`, resolving only direct validation regressions.

### STEP-B8-04 — Execute clean-room and full acceptance validation

**Owner:** TestExecutionAgent  
**Container:** all  
**Status:** 🔄 `in_progress`  
**Depends on:** STEP-B8-02, STEP-B8-03  
**Acceptance:** B8-AC-01 — complete lifecycle automation; B8-AC-02 — deterministic denials; B8-AC-03 — credential-free clean execution; B8-AC-04 — complete acceptance mapping  
**Validation:** B8-VAL-01, B8-VAL-02, B8-VAL-03, B8-VAL-04  
**Definition of done:** Two clean disposable Compose cycles and all required automated suites have recorded pass or fail evidence, with a deterministic reset baseline restored after validation.

**Technical approach:** Implement DEC-B8-04. Run all validation from a deliberately disposable local state. Each clean cycle must remove containers and volumes, build the application profile, apply migrations, seed, reset, reseed, and check `/health`. The complete suite then runs API tests, frontend lint and typecheck, focused Selenium browser workflows, and the Compose-hosted Playwright suite. Retain sanitized reports under `artifacts/batch8/`; do not commit private evidence storage, opaque token values, session cookies, or credential values.

| File/component and symbol | Concrete change or resulting code shape | Integration and compatibility impact | Acceptance and validation |
| --- | --- | --- | --- |
| `artifacts/batch8/` validation output | Retain timestamped command logs, suite summaries, Playwright reports, and failure diagnostics generated by the validation runners. | Evidence-only output; no application source behavior changes. | B8-AC-01 through B8-VAL-01 to B8-VAL-04. |
| `docker-compose.yml` application and e2e profiles | Execute the existing profile contracts without manually mutating state in PostgreSQL or private volumes. | Proves the documented Compose topology and deterministic provider defaults. | B8-AC-03 through B8-VAL-03. |

#### Implementation Tracker

- [x] Correct the API-test collection blocker in `tests/api/test_batch8_acceptance_matrix.py` by replacing the invalid non-ASCII bytes literal with equivalent ASCII synthetic data.
- [ ] Run two clean cycles of `docker compose down -v --remove-orphans` followed by `docker compose --profile application up -d --build --wait`.
- [ ] Run `docker compose --profile application exec -T api python -m app.commands migrate`, `reset`, `seed`, and a `/health` check in each cycle.
- [ ] Run `python -m pytest tests/api`, frontend lint, frontend typecheck, and all focused Selenium workflow scripts against the clean application.
- [ ] Run `docker compose --profile e2e run --rm e2e` and retain Playwright artifacts for any failure.
- [ ] Record every AC-01 through AC-24 as passed, failed, or unverified with a link or path to its evidence; restore the seeded baseline after the final run.

### STEP-B8-05 — Publish verified final acceptance and operator documentation

**Owner:** DocumentationAgent  
**Container:** all  
**Status:** ⏳ `to_do`  
**Depends on:** STEP-B8-04  
**Acceptance:** B8-AC-04 — complete acceptance mapping; B8-AC-05 — verified operator documentation  
**Validation:** B8-VAL-04 — documentation and safety inspection  
**Definition of done:** The repository documentation reflects recorded final validation, provides safe local demonstration and recovery instructions, and preserves every documented synthetic-data and non-production limitation.

**Technical approach:** Implement DEC-B8-05. Update only current documentation that is affected by recorded validation results. `requirements/ACCEPTANCE_CRITERIA.md` must become the authoritative outcome matrix for AC-01 through AC-24 and must retain failed or unverified statuses when evidence is incomplete. `requirements/ENVIRONMENT.md` must show only tested Compose and test-run commands. `docs/ARCHITECTURE.md` must be corrected where its STEP-01 greenfield language no longer reflects observed implementation, without making production claims. Add a manager-oriented runbook describing the validated normal startup, reset, test, artifact, and cleanup paths.

| File/component and symbol | Concrete change or resulting code shape | Integration and compatibility impact | Acceptance and validation |
| --- | --- | --- | --- |
| `requirements/ACCEPTANCE_CRITERIA.md` | Update each acceptance status and its evidence reference from STEP-B8-04 records; retain stable AC and VAL IDs. | Gives stakeholders a source-backed final readiness view. | B8-AC-04 through B8-VAL-04. |
| `requirements/ENVIRONMENT.md` | Correct the documented commands and profiles only when they were successfully executed in clean-room validation. | Aligns setup and recovery instructions with actual Compose behavior. | B8-AC-03 and B8-AC-05 through B8-VAL-04. |
| `docs/ARCHITECTURE.md` | Correct outdated greenfield descriptions with verified current-state boundaries while retaining demo-design and production-limit disclaimers. | Keeps architectural documentation synchronized without inventing production behavior. | B8-AC-05 through B8-VAL-04. |
| `docs/DEMO_RUNBOOK.md` | Create a concise manager-demo runbook with startup, sign-in roles, reset, acceptance suite, artifact location, cleanup, and failure recovery instructions. | Creates a discoverable operator-facing entry point with no secret values or raw QR references. | B8-AC-05 through B8-VAL-04. |

#### Implementation Tracker

- [ ] Update `requirements/ACCEPTANCE_CRITERIA.md` from recorded evidence, preserving non-passing outcomes rather than inferring success.
- [ ] Update `requirements/ENVIRONMENT.md` with only clean-room-tested commands and recovery steps.
- [ ] Correct `docs/ARCHITECTURE.md` where implementation evidence supersedes its STEP-01 greenfield statements.
- [ ] Create `docs/DEMO_RUNBOOK.md` with synthetic-demo safety boundaries, tested startup and reset commands, and artifact locations.
- [ ] Inspect updated documentation and generated artifacts for secrets, real personal data, private paths, raw QR payloads, and unsupported production claims.

## Acceptance and verification matrix

| Acceptance ID | Observable result | Validation ID | Method or command | Expected evidence |
| --- | --- | --- | --- | --- |
| B8-AC-01 | The full persisted lifecycle completes from invitation to second gate grant after renewal. | B8-VAL-01 | `docker compose --profile e2e run --rm e2e` | Playwright result, trace on failure, and explicit lifecycle assertions. |
| B8-AC-02 | Sofia, Milan, Noah, and Emma receive the documented deterministic denials and corrective actions. | B8-VAL-01 | `docker compose --profile e2e run --rm e2e` | Denial-suite report with server-owned decision and reason assertions. |
| B8-AC-03 | The credential-free application completes two clean build, migration, seed, reset, reseed, and health cycles. | B8-VAL-03 | `docker compose down -v --remove-orphans`; `docker compose --profile application up -d --build --wait`; API lifecycle commands; `Invoke-RestMethod http://localhost:8000/health` | Timestamped clean-cycle logs and sanitized health responses. |
| B8-AC-04 | AC-01 through AC-24 have executable test evidence or an explicit inspection record and status. | B8-VAL-02 | `python -m pytest tests/api`; focused browser workflows; test-to-acceptance inventory | Passing suite summaries or preserved failure artifacts, plus the final acceptance matrix. |
| B8-AC-05 | Operator documentation contains tested commands and retains demo safety limitations. | B8-VAL-04 | `npm --prefix apps/web run lint`; `npm --prefix apps/web run typecheck`; documentation and secret-safety review | Command results and reviewed documentation with no sensitive values. |

## Risks and open decisions

| Risk ID | Concrete failure mode | Mitigation or recovery | Affected steps |
| --- | --- | --- | --- |
| RISK-B8-01 | The declared Compose `e2e` service cannot run because `tests/e2e/` is absent. | Create the isolated package in STEP-B8-01 and prove it through the Compose command before adding broad scenarios. | STEP-B8-01, STEP-B8-02 |
| RISK-B8-02 | Tests mutate deterministic state and cause order-dependent failures. | Reset and reseed before mutable scenarios and restore baseline in `finally` or equivalent cleanup. | STEP-B8-02, STEP-B8-04 |
| RISK-B8-03 | Browser tests expose or persist opaque token values, credentials, or private identifiers in artifacts. | Assert QR presence and server behavior without logging payloads; sanitize artifact writers and review outputs in B8-VAL-04. | STEP-B8-01 through STEP-B8-05 |
| RISK-B8-04 | Existing architecture documentation still describes the STEP-01 greenfield state after the application exists. | Correct only with recorded current-state evidence in STEP-B8-05; preserve explicitly future or production-unknown boundaries. | STEP-B8-05 |
| RISK-B8-05 | A validation regression prompts unnecessary rework of completed workflow scope. | Require a minimal failing test and route only direct regressions to the owning container. Keep broader changes out of Batch 8. | STEP-B8-03, STEP-B8-04 |

| Open decision | Owner | Impact if unresolved | Required before |
| --- | --- | --- | --- |
| OQ-B8-01 — No Batch 9 metadata is accessible. | Workflow owner | No successor-batch schedule can be safely invented. | Batch 8 closeout; record remaining failures as explicit future work. |
| OQ-B8-02 — Hosted CI/browser provisioning is not defined. | Test infrastructure owner | Validation remains executable locally through Compose but cannot claim a hosted pipeline. | Any CI implementation beyond the existing local Compose contract. |

## Execution record

| Record | Current state |
| --- | --- |
| Progress | 2026-09-23: STEP-B8-01 package metadata, deterministic lockfile, Playwright configuration, support helpers, Compose smoke coverage, and the bounded Compose runner update are staged. The exact remaining work is materialization followed by the required Compose e2e execution. |
| Progress | 2026-09-23: STEP-B8-02 coverage is staged in `tests/e2e/test_full_lifecycle.spec.ts`, `tests/e2e/test_gate_denials.spec.ts`, and `tests/e2e/test_roles_and_reset.spec.ts`. The tests cover Sofia's seeded renewal-to-second-grant lifecycle, four deterministic server denials, seven rendered role-navigation states, direct API permission denials, and repeated reset/reseed smoke behavior. Execution is intentionally deferred to STEP-B8-04. |
| Discoveries/deviations | Reset and seed are documented API-container CLI operations, not privileged HTTP routes. The reset helper therefore requires a caller-provided command runner for future mutating scenarios and itself performs only the public API readiness check. Docker bind mounts also do not expose approval-staged files to the runner before materialization. |
| Discoveries/deviations | STEP-B8-02 adds the test-only `E2E_BASELINE_COMMAND` contract because the Compose-hosted Playwright container has neither a privileged reset HTTP endpoint nor a Docker socket/API-container CLI runner. Mutating tests are skipped rather than allowed to run against stale state unless this command restores the documented reset-and-seed baseline before and after each scenario; no authorization bypass or test-only backend route was added. |
| Validation evidence | `docker compose --profile e2e config --quiet` succeeded. The required `docker compose --profile e2e run --rm e2e` started PostgreSQL, Redis, API, and web; all reported healthy before the e2e container failed with `ENOENT` for `/workspace/tests/e2e/package.json`, because the Docker bind mount used the pre-approval workspace. Exact registry integrity metadata for Playwright 1.49.1 dependencies was verified. |
| Validation evidence | No STEP-B8-02 tests were executed, per the requested consolidated-validation sequence. Static inspection confirmed that test assertions use only public API contracts and rendered UI, that opaque token values are submitted but neither asserted nor emitted to messages, and that each mutating test invokes external baseline restoration in `beforeEach` and `afterEach`. |
| Progress | 2026-09-23: STEP-B8-03 stages `tests/api/test_batch8_acceptance_matrix.py` for the remaining demonstrated API-boundary gaps: credential-free provider selection and private local storage, evidence metadata redaction, chronological audit reads, and dashboard response redaction. Existing lifecycle, denial, role/reset, Step 11, Step 14, Batch 6, and Batch 7 browser coverage was inspected; no additional observable rendered-UI gap was demonstrated, so no browser test was changed. |
| Validation evidence | STEP-B8-03 execution is intentionally deferred to STEP-B8-04 at the user's request. No API tests, lint, typecheck, focused-browser workflows, or e2e suite were run while changes remain approval-staged. |
| Discoveries/deviations | 2026-09-23: API-test collection identified an invalid non-ASCII em dash in the bytes literal in `tests/api/test_batch8_acceptance_matrix.py`. The fixture now uses equivalent ASCII-only synthetic bytes (`SYNTHETIC - NOT A REAL CREDENTIAL`), preserving private-local-storage semantics without changing application behavior. |
| Progress | 2026-09-23: STEP-B8-04 is in progress. The bounded collection blocker is corrected; no remaining validation suite was run before this correction because collection could not proceed. |
| Outcomes | STEP-B8-01 and STEP-B8-02 remain in progress. Their definitions of done require materialization and a passing Compose-hosted Playwright run. The unconfigured CLI runner prevents mutating coverage from executing in the current isolated e2e container; non-mutating role coverage remains executable once the package is materialized. |
| Next safe resume | Materialize all staged Batch 8 files, then rerun `python -m pytest tests/api` as the first consolidated validation command to verify collection and preserve its evidence. If it passes, configure `E2E_BASELINE_COMMAND` to run the documented API-container `reset` followed by `seed` lifecycle and continue the STEP-B8-04 sequence: frontend lint and typecheck, focused browser workflows, clean Compose cycles, and `docker compose --profile e2e run --rm e2e`. Retain sanitized artifacts and mark implementation steps complete only after required validation passes. |
