# Source Facts, Demo Assumptions, and Open Questions

## Purpose

The supplied discovery material describes the eleven-step journey as a DigitalT3 reconstruction and hypothesis rather than a verified Renewi current-state map. This register prevents concrete demo choices from being presented as confirmed production policy.

Open questions do not block the manager-facing demo. They become prerequisites only for the production activity identified in the relevant row.

## Source Facts

| ID | Supported statement | Demo consequence |
| --- | --- | --- |
| SF-01 | The concept covers six populations: Renewi drivers, temporary or agency drivers, external drivers, maintenance contractors, permanent contractors, and visitors. | The population reference data and configurable profiles include all six values. |
| SF-02 | The Netherlands and Belgium are in geographic scope; France and Portugal are out of scope for this work. | The model is multi-site-ready for NL and BE, while the seed uses one Netherlands site. |
| SF-03 | Vlaardingen is proposed as the initial pilot or lighthouse framing. | Vlaardingen is the deterministic demo site but is not described as a confirmed production pilot. |
| SF-04 | The supplied workflow has eleven stages from invitation through expiry and re-validation. | The complete connected workflow is the acceptance backbone. |
| SF-05 | Population checks include corporate compliance, identity, driving licence, VCA, safety training, site rules, access approval or token, and blacklist. | Applicability is stored as configuration rather than hard-coded in React. |
| SF-06 | A daily, per-site management view and visibility of who is on site are desired. | Presence and dashboard values are derived from persisted backend state. |
| SF-07 | Privacy, estate variety, barrier adoption, duplication, unknown baselines, short-notice populations, and language are source concerns. | The demo uses synthetic data, adapter boundaries, site configuration, explicit denial actions, and language metadata. |
| SF-08 | Current systems, detailed process ownership, failure handling, legal basis, exact compliance definitions, and site realities remain open. | Documentation and UI copy must not claim production certainty. |

## Demo Assumptions

| ID | Committed demo assumption | Rationale and boundary |
| --- | --- | --- |
| DA-01 | The proposed stack is Next.js, FastAPI, PostgreSQL, SQLAlchemy, Alembic, and Docker Compose. | It supports a legible local demonstration; it is not a Renewi technology decision. |
| DA-02 | The API domain layer owns workflow transitions, compliance, token eligibility, gate decisions, presence, expiry, and audit. | This prevents duplicated or inconsistent frontend rules. |
| DA-03 | Vlaardingen uses `Europe/Amsterdam` and a software-kiosk gate mode. | This makes visit windows and site-day reporting deterministic. |
| DA-04 | Six mandatory fictional personas demonstrate one grant, four denial causes, and re-validation restoration. | This gives the manager walkthrough stable, meaningful outcomes. |
| DA-05 | Document extraction and identity verification use deterministic mock providers by default. | No external credential or real biometric processing is required. |
| DA-06 | Evidence is stored privately on a local filesystem volume by default. | It provides a credential-free path while retaining an S3-compatible boundary. |
| DA-07 | Notifications are persisted in an in-app center by default. | Invitation and expiry flows do not depend on email delivery. |
| DA-08 | Access tokens use opaque, non-guessable references and store a hash server-side. | QR codes contain no raw personal information. |
| DA-09 | APScheduler runs inside one API process and expiry processing is also manually triggerable and idempotent. | The demo avoids a separate worker while preserving a service boundary. |
| DA-10 | A persisted demo-clock offset supports 7-, 14-, and 30-day advancement. | Step 11 can be demonstrated without changing the host clock. |
| DA-11 | Normal commands preserve historical records through status, supersede, revoke, expire, and close semantics. | Audit history remains explainable throughout the walkthrough. |
| DA-12 | Seed and reset are manifest-driven and idempotent. | Every demonstration can return to a known logical state. |
| DA-13 | Site compliance profiles control population applicability, blocking severity, validity, and renewal lead time. | Demo rules remain configurable and are not embedded in presentation code. |
| DA-14 | Seeded sessions use locally signed, short-lived cookies and server-enforced roles. | This provides practical demo authentication without enterprise IAM. |
| DA-15 | The manager demo uses synthetic companies, identities, documents, training content, scores, and dates. | The repository must not contain real personal or supplier data. |

## Open Questions

| ID | Open production question | Suggested owner | Demo handling | Required before |
| --- | --- | --- | --- | --- |
| OQ-01 | Is Vlaardingen confirmed as the production pilot? | Renewi product owner | Continue using Vlaardingen as a labeled demo site. | Pilot commitment |
| OQ-02 | What is the authoritative person record? | Enterprise architecture and HR | Use deterministic local person records. | Person-system integration |
| OQ-03 | What is the authoritative company and supplier record? | Procurement and enterprise architecture | Use fictional local company records. | Supplier integration |
| OQ-04 | Does Renewi already operate contractor-management or site-access capabilities, especially at Seveso sites? | Site operations and enterprise architecture | Preserve modular boundaries and make no replacement claim. | Production solution design |
| OQ-05 | What happens operationally when a person fails a gate check? | Site operations and SHEQ | Show reason, corrective action, person-record link, and manual-review option without frontend override. | Pilot operating procedure |
| OQ-06 | Who owns compliance decisions, approvals, blacklist changes, exceptions, and appeals? | SHEQ, site operations, and legal | Use seeded role permissions and append audit events. | Production authorization model |
| OQ-07 | Where do SHEQ training, site rules, and test results live today? | SHEQ and learning owners | Use local demo modules and scored attempts. | LMS integration |
| OQ-08 | What are actual volumes by site, population, day, season, and repeat-visit rate? | Operations and data owners | Use small synthetic datasets and make no capacity claim. | Sizing and performance design |
| OQ-09 | What is the legal basis for identity capture and live matching? | Privacy and legal | Use no real biometric data and label the verifier as simulated. | Real identity processing |
| OQ-10 | Is a DPIA required, and what retention, access, deletion, and appeal rules apply? | Data protection officer and legal | Treat demo data as disposable synthetic data. | Production privacy approval |
| OQ-11 | What gate hardware, network connectivity, offline behavior, and safety constraints exist at each site? | Site operations and infrastructure | Use a software kiosk and no physical barrier integration. | Site integration design |
| OQ-12 | Which enterprise hosting, IAM, logging, security, accessibility, and support standards apply? | Enterprise architecture and security | Use local containers and documented demo safeguards. | Production platform selection |
| OQ-13 | What exact population-specific rules, validity periods, renewal windows, and evidence sources are authoritative? | SHEQ and compliance owners | Use configurable demo profiles with clearly synthetic values. | Production compliance configuration |
| OQ-14 | Which languages and translated training content are required at each site? | Operations and SHEQ | Store language metadata and seed a limited demo language set. | Multi-site rollout |
| OQ-15 | Should gate decisions support an override, and if so under what authority and audit controls? | Site operations, SHEQ, legal, and security | Provide manual review but no unaudited frontend override. | Exception workflow design |
| OQ-16 | Which notifications must be delivered by email, messaging, or another enterprise channel? | Product owner and enterprise architecture | Use the in-app notification provider. | Notification integration |
| OQ-17 | What are the production availability, recovery, monitoring, and support objectives? | Platform operations | Explicitly exclude HA, DR, and production monitoring from the demo. | Production readiness planning |

## Decision Rule

A new production claim must not be added to requirements, UI copy, seed data, or architecture documentation unless it is supported by an authoritative source. Until an open question is resolved, implementation must preserve the documented demo assumption and label it accordingly.

If new evidence changes scope, interfaces, acceptance, security, privacy, or recovery behavior, the active implementation plan must be revised and reapproved before dependent implementation continues.
