# Deterministic Demo Data Contract

## Purpose and Safety Boundary

This document defines the deterministic records required to tell the complete manager-facing story. The six populations and mandatory scenario themes are supported by the supplied source material. Names, companies, contact details, account handles, document identifiers, dates, scores, tokens, and provider outputs are **DEMO DESIGN** data.

Every record and asset must be visibly fictional. No real Renewi employee, supplier, visitor, credential, signature, portrait, contact detail, document number, or biometric sample may be copied into the repository.

## Pilot Site

The seed contains one active site named Vlaardingen in the Netherlands. `Europe/Amsterdam` is the proposed site timezone. The site supports software-kiosk gate mode and configurable compliance requirements.

Vlaardingen is a **SOURCE FACT** candidate for the demonstration but remains an **OPEN QUESTION** as a production pilot. The information model must support additional Netherlands and Belgium sites without creating additional production claims.

## Source Population Catalog

| Population | Source description | Default demo treatment |
| --- | --- | --- |
| Renewi driver | Known permanent or employed driver | Driver compliance profile |
| Temporary or agency driver | Driver supplied by an employment agency | Driver profile with external-source metadata |
| External driver | Freight-exchange or otherwise short-notice driver | Driver profile with manual enrollment support |
| Maintenance contractor | Ad hoc specialist contractor | Contractor compliance profile |
| Permanent contractor | Fixed-term contractor who can be onboarded earlier | Contractor profile with recurring re-validation |
| Visitor | Hosted visitor with a lighter check set | Visitor compliance profile |

All six values must exist in the seed reference data even though the six mandatory gate scenarios do not map one-to-one to the six population categories.

## Fictional Companies

| Seed key | Display name | Type | Purpose |
| --- | --- | --- | --- |
| `company_demo_logistics` | Delta Demo Logistics B.V. | Logistics supplier | External-driver scenarios |
| `company_demo_maintenance` | Northstar Demo Maintenance B.V. | Maintenance supplier | Contractor scenarios |
| `company_demo_agency` | Harbor Demo Staffing B.V. | Employment agency | Temporary-driver population coverage |
| `company_demo_permanent` | Circular Demo Services B.V. | Permanent contractor | Recurring contractor population coverage |
| `company_demo_visitors` | Independent Demo Visitors | Visitor placeholder | Hosted visitor scenarios |
| `company_demo_renewi` | Renewi Demo Operations | Internal demo organization | Requester, host, and Renewi-driver records |

The names above are fictional seed data and must not be interpreted as actual suppliers or legal entities.

## Mandatory Personas

### Alex van Dijk

Alex is a fictional external driver for Delta Demo Logistics B.V. at Vlaardingen. The baseline seed gives Alex verified synthetic ID and driving-licence evidence, valid corporate insurance, passed SHEQ Basics and Vlaardingen Site Rules training, no blacklist entry, an approved visit, and an active opaque access token.

The deterministic identity result is a match with confidence `0.96` and mode `DEMO`. Gate evaluation must return `GRANT` with the readable reason that all mandatory checks passed. Recording entry creates one active on-site record and recording exit closes it.

### Sofia Janssen

Sofia is a fictional maintenance contractor for Northstar Demo Maintenance B.V. at Vlaardingen. The baseline seed gives Sofia verified ID, passed training, no blacklist entry, a previously approved visit, and an active token. Her VCA certificate has since expired.

The token remains resolvable so that gate evaluation reaches the current compliance checks. The gate must return `DENY` with reason code `VCA_EXPIRED` and a corrective action to renew and verify the VCA evidence.

### Milan de Boer

Milan is a fictional visitor associated with Independent Demo Visitors and a seeded host at Vlaardingen. Milan has verified identity evidence and a token issued while eligible, but the current Vlaardingen Site Rules requirement is no longer satisfied because the required renewal test was failed.

The latest training attempt must record a score below the passing threshold and a failed result. Gate evaluation must return `DENY` with reason code `SITE_RULES_NOT_PASSED` and direct the operator to training remediation or site-manager review.

### Noah Peters

Noah is a fictional driver for Delta Demo Logistics B.V. Noah has otherwise valid evidence, training, approval, and an active token. An active person-level blacklist entry was added after token issue.

Gate evaluation must apply blacklist precedence and return `DENY` with reason code `PERSON_BLACKLISTED`. The operator may open the person record or contact the site manager but may not override the backend decision through frontend-only logic.

### Emma Visser

Emma is a fictional permanent contractor for Circular Demo Services B.V. Emma has valid evidence, training, approval, and an active token. The deterministic presented-identity scenario intentionally does not match the registered synthetic identity.

The identity adapter must return `match: false`, confidence `0.18`, and mode `DEMO`. Gate evaluation must return `DENY` with reason code `IDENTITY_MISMATCH` and offer manual review without creating presence.

### Lucas Smit

Lucas is a fictional external driver for Delta Demo Logistics B.V. The baseline scenario includes evidence that can be advanced across an expiry boundary with the persisted demo clock.

After expiry processing, Lucas receives one re-validation task, a dashboard alert, a blocked compliance result, and gate reason code `DRIVING_LICENCE_EXPIRED`. A synthetic replacement is then uploaded and verified, the task is completed, compliance is recalculated, and the next gate evaluation returns `GRANT`.

## Persona State Matrix

| Persona | Evidence | Training | Approval | Token | Initial gate result | Scenario |
| --- | --- | --- | --- | --- | --- | --- |
| Alex van Dijk | Required items verified and valid | Required modules passed | Approved | Active | `GRANT` | Happy path |
| Sofia Janssen | VCA expired; other required items valid | Passed | Previously approved; current compliance blocked | Active and resolvable | `DENY` | Expired evidence |
| Milan de Boer | Visitor ID valid | Site-rules renewal test failed | Current compliance blocked | Active and resolvable from earlier eligibility | `DENY` | Training failure |
| Noah Peters | Required items valid | Passed | Previously approved | Active and resolvable | `DENY` | Active blacklist |
| Emma Visser | Required items valid | Passed | Approved | Active | `DENY` | Identity mismatch |
| Lucas Smit | Valid at reset, then expires after time advance | Passed | Approved before expiry | Active and resolvable | `DENY`, then `GRANT` | Re-validation |

An active token does not guarantee entry. `GateService` must re-evaluate current standing, blacklist, evidence, training, approval, and identity on every attempt.

## Supporting Population Records

The deterministic seed must also include lightweight reference records for a Renewi driver and a temporary or agency driver so that all six source population values are visible and filterable. These supporting records do not replace the six mandatory personas and do not require additional gate scenarios.

## Synthetic Evidence Assets

| Asset key | Type | Required characteristics |
| --- | --- | --- |
| `demo_id_card_v1` | Fictional identity card | Clearly marked `DEMO`, synthetic portrait or illustration, fictional number |
| `demo_nl_driving_licence_v1` | Fictional Dutch-style driving licence | Clearly marked `NOT A REAL CREDENTIAL`, fictional number, categories and expiry |
| `demo_vca_certificate_v1` | Fictional VCA certificate | Fictional provider, certificate number, issue and expiry dates |
| `demo_insurance_certificate_v1` | Fictional company insurance certificate | Fictional insurer, policy number, issue and expiry dates |
| `demo_training_record_v1` | Synthetic training completion | Module, attempt, score, pass state, completion and expiry |
| `demo_registered_identity_v1` | Synthetic identity-verification reference | No real biometric data; deterministic scenario reference only |

Synthetic assets will be created during implementation. They must remain in private demo storage or an appropriate source asset directory and must never reproduce a real credential design closely enough to be mistaken for an authentic document.

## Training Seed

The seed includes `SHEQ Basics` and `Vlaardingen Site Rules`. Each module has a language, passing score, validity period, active state, and multiple-choice question set.

Training results must store attempt number, score, pass or fail, completion time, and expiry. The checkbox completion interaction does not replace the scored test record.

## Seeded Role Accounts

| Account handle | Role | Primary seeded permissions |
| --- | --- | --- |
| `admin.demo` | System Admin | All modules, settings, demo clock, and scenario reset |
| `sheq.demo` | Compliance or SHEQ | Evidence, training, compliance, approvals, and blacklist |
| `manager.demo` | Site Manager | Dashboard, roster, gate decisions, exceptions, and approvals |
| `gate.demo` | Gate Operator | Gate, limited person lookup, entry, exit, and on-site roster |
| `host.demo` | Requester or Host | Create invitations and view own requests |
| `participant.demo` | Contractor, Driver, or Visitor | Own registration, evidence, training, and token |
| `viewer.demo` | Read-only Viewer | Dashboard, audit, and high-level record reads |

Passwords are supplied through local seed configuration and are not recorded here. API authorization is authoritative; hidden navigation alone is not a permission control.

## Scenario Reset Contract

| Scenario key | Reset result |
| --- | --- |
| `happy_path` | Alex returns to approved, token-active, not-present state with a deterministic identity match. |
| `expired_evidence` | Sofia returns to expired-VCA state with no presence and no mutable gate result. |
| `training_failure` | Milan returns to the failed latest site-rules attempt and current blocked state. |
| `blacklist` | Noah returns to one active blacklist entry and otherwise valid state. |
| `identity_mismatch` | Emma returns to the deterministic mismatch input and no presence. |
| `revalidation` | Lucas returns to pre-expiry eligibility, no re-validation task, and zero demo-clock offset. |
| `full_demo` | All personas, roles, events, alerts, clock state, and mutable outcomes return to the complete deterministic baseline. |

Repeated reset must produce the same logical records and scenario outcomes without duplicate active tokens, blacklist entries, presence records, or re-validation tasks.

## Expected Audit Story

The seed may contain enough prior history to make each scenario understandable, but actions performed during the walkthrough must create new audit events. The complete story must support invitation, registration, evidence upload and verification, training result, approval, token issue, gate scan, identity result, grant or denial, entry, exit, expiry, re-validation start, renewal, re-validation completion, and restored gate eligibility.
