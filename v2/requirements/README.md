# Renewi Contractor and Visitor Site Access Demo Requirements

## Document Purpose

This directory is the requirements source of truth for the manager-facing Renewi Contractor and Visitor Site Access demo. It translates the supplied product requirements and build instructions into an executable demonstration contract without claiming that the proposed workflow is Renewi's verified current process.

The supplied DigitalT3 material identifies the business context, six relevant populations, the Netherlands and Belgium scope, a candidate Vlaardingen pilot, population-specific checks, and an eleven-step journey. The detailed application architecture, provider choices, demo rules, seeded identities, role permissions, and implementation conventions documented here are demo design decisions that remain subject to production discovery.

At completion of STEP-01, the repository remains greenfield apart from documentation. The commands, containers, URLs, environment template, database schema, application code, and tests described below are obligations for subsequent implementation steps rather than currently available runtime behavior.

## Classification Convention

Requirements in this directory use three classifications.

**SOURCE FACT** identifies information explicitly supported by the supplied DigitalT3 discovery material or PRD.

**DEMO DESIGN** identifies a concrete choice made so that the manager-facing demonstration can be built and tested consistently.

**OPEN QUESTION** identifies a production concern that requires confirmation from Renewi and must not block the local demo.

## Project Purpose

**SOURCE FACT:** The concept is a centralized digital site-access and compliance platform intended to help ensure that only qualified and authorized people enter a site. The controlling demonstration journey is Invite or request, Pre-register, Collect evidence, Train and test, Approve, Issue token, Arrive at gate, Grant or deny, On-site record, Dashboard, and Expiry or re-validation.

**DEMO DESIGN:** The application will connect all eleven stages through persisted state and an append-only audit history. A manager must be able to demonstrate a successful gate decision, several meaningful denials, presence and dashboard updates, expiry, renewal, and restored access without editing the database manually.

**OPEN QUESTION:** The actual Renewi current-state process, system ownership, exception handling, site infrastructure, volumes, and production compliance rules remain unverified.

## Scope and Boundaries

The demo includes a Vlaardingen site record, multi-site-ready information structures, all six source populations, seven seeded application roles, synthetic evidence, configurable compliance requirements, scored training, approval, opaque QR access tokens, a simulated identity check, gate decisions, presence, site-and-day dashboard reporting, expiry, re-validation, audit history, and deterministic reset controls.

The demo excludes physical barrier hardware, production biometrics, enterprise IAM, HR and agency integrations, freight-exchange integration, an enterprise LMS, real personal data, production legal compliance, France and Portugal, high-availability engineering, disaster recovery, and production monitoring. Identity matching must remain visibly marked as simulated `DEMO MODE`.

## Proposed Architecture

The selected architecture is a containerized monorepo containing a Next.js web application, a FastAPI API, and PostgreSQL. The API domain layer will own workflow transitions, compliance evaluation, token eligibility, gate decisions, presence, expiry, and audit creation. The web application will render typed results and must not duplicate gate or compliance rules.

The initial architecture contract is documented in `docs/ARCHITECTURE.md`. Integration boundaries and deterministic fallback behavior are documented in `requirements/INTEGRATIONS.md`.

## Proposed Technology Stack

| Layer | Demo design |
| --- | --- |
| Web application | Next.js App Router with TypeScript |
| UI | Tailwind CSS and shadcn/ui |
| Forms and validation | React Hook Form and Zod |
| Client data management | TanStack Query |
| API | FastAPI and Pydantic |
| Domain persistence | PostgreSQL with SQLAlchemy |
| Migrations | Alembic |
| Local storage | Private filesystem storage behind a storage interface |
| Background processing | APScheduler inside the single demo API process |
| API and service tests | Pytest |
| Browser acceptance tests | Playwright |
| Packaging | Docker Compose |
| API documentation | FastAPI OpenAPI and Swagger UI |

## Local Setup Contract

Subsequent Batch 0 implementation must make the following workflow executable from PowerShell on a machine with Docker Compose v2:

1. Build and start the `web`, `api`, and `postgres` services from clean volumes.
2. Wait for PostgreSQL and API health checks.
3. Apply all Alembic migrations.
4. load the deterministic seed manifest.
5. Open the web application and API documentation.
6. Reset all mutable demo state and recreate the same scenarios.
7. Stop the services and remove their local volumes safely.

The exact tested commands must be added during Batch 0 and finalized in STEP-29. Until those steps complete, documentation must not imply that a command has been implemented or verified.

## Proposed Application URLs

| Surface | Proposed local URL | Status at STEP-01 |
| --- | --- | --- |
| Web application | `http://localhost:3000` | Contract only; not implemented |
| API | `http://localhost:8000` | Contract only; not implemented |
| API health | `http://localhost:8000/health` | Contract only; not implemented |
| OpenAPI documentation | `http://localhost:8000/docs` | Contract only; not implemented |

These ports are demo design defaults. If implementation evidence requires a change, this document and the environment contract must be updated together.

## Demo Accounts

Seven seeded account identities are required: System Admin, Compliance or SHEQ, Site Manager, Gate Operator, Requester or Host, Contractor or Driver or Visitor, and Read-only Viewer. Their proposed account handles and permissions are defined in `requirements/DEMO_DATA.md`.

No password or signing secret is fixed in this document. Seeded account passwords must be supplied through local demo configuration, must never be reused outside this repository, and must be clearly identified as non-production credentials.

## Database, Seed, and Reset Obligations

PostgreSQL is the authoritative store for people, companies, sites, visits, invitations, evidence metadata, training attempts, approvals, blacklist entries, access tokens, gate events, presence, re-validation tasks, audit events, scenarios, demo-clock state, and role accounts.

Migrations must create a clean database repeatably. Seed and reset must be manifest-driven and idempotent. Reset must remove mutable scenario outcomes, recreate the six mandatory personas and supporting data, restore predictable relative dates, reset the demo clock, and preserve no real personal information.

Normal business commands must not delete evidence, approvals, access tokens, gate events, or audit history. They must use verified, rejected, superseded, revoked, expired, or closed states.

## External Integrations

The demo must function without third-party credentials. Document extraction, identity verification, file storage, and notifications must be accessed through provider interfaces with deterministic local implementations selected by default.

Missing optional credentials must select the local provider and produce a visible `DEMO MODE` label. Provider behavior, configuration, and failure boundaries are specified in `requirements/INTEGRATIONS.md`; environment-variable names are inventoried in `requirements/CREDENTIALS.md`.

## Demo Scenarios

The deterministic seed must provide the following connected scenarios:

| Persona | Scenario | Expected gate outcome |
| --- | --- | --- |
| Alex van Dijk | Complete happy path | `GRANT` |
| Sofia Janssen | Expired VCA evidence | `DENY` |
| Milan de Boer | Site-rules training failure | `DENY` |
| Noah Peters | Active blacklist entry | `DENY` |
| Emma Visser | Simulated identity mismatch | `DENY` |
| Lucas Smit | Expiry followed by successful re-validation | `DENY`, then `GRANT` after renewal |

The full record contract, fictional companies, synthetic asset identifiers, role accounts, and reset states are defined in `requirements/DEMO_DATA.md`.

## Testing and Acceptance

Acceptance criteria AC-01 through AC-24 are defined in `requirements/ACCEPTANCE_CRITERIA.md`. They require unit, API, authorization, upload-safety, aggregate, expiry, audit, responsive, accessibility, and Playwright evidence.

The final end-to-end test must cover invitation, registration, evidence, training, approval, token issue, gate grant, entry, dashboard update, expiry, renewal, re-validation, and a second gate evaluation. At least four deterministic denial cases must also be tested.

## Security and Demo Safety

Only fictional identities, companies, documents, contact details, and images may be committed. QR payloads may contain only an opaque, non-guessable reference; raw personal data must be resolved server-side. Uploads must be constrained by type and size and stored outside the web application's public assets.

Authorization must be enforced by API dependencies rather than navigation alone. Optional provider secrets, database credentials, session-signing material, and SMTP credentials must never be committed. The simulated identity provider must not process real biometric data.

## Known Limitations

The proposed workflow is a DigitalT3 reconstruction for demonstration and discovery, not a verified statement of Renewi's current operations. Vlaardingen is the seeded demo site but is not confirmed as a production pilot. Demo compliance profiles, validity periods, training questions, scores, companies, identities, denial wording, and provider outputs are synthetic design choices.

The demo does not establish legal basis, retention, DPIA compliance, enterprise security accreditation, offline gate behavior, integration ownership, or production operating procedures. These topics remain in `requirements/OPEN_QUESTIONS.md`.
