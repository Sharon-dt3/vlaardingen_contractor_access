# Integration and Provider Contract

## Purpose

This document defines the external-capability boundaries for document extraction, identity verification, storage, and notifications. These interfaces are **DEMO DESIGN** choices derived from the requirement that the application work without external credentials.

No provider named here is asserted to be part of Renewi's production estate. Enterprise HR, agency, freight-exchange, LMS, gate hardware, and identity-system integrations remain outside the demo and require later discovery.

## Architectural Rule

Domain services depend on provider interfaces rather than concrete SDKs. Provider selection occurs in API configuration and dependency composition. Route handlers and React components must not instantiate provider clients, inspect provider credentials, or reproduce provider-selection logic.

Every provider result includes a mode or provider identifier so that simulated results can be displayed honestly. The default manager-demo path is deterministic and must remain available when the machine is offline after dependencies have been installed.

## Document Extraction

### Interface

`DocumentExtractionProvider` accepts a private document reference and declared evidence type and returns structured fields, field-level confidence where available, provider mode, and processing metadata. It must not determine whether evidence is compliant or verified.

`EvidenceService` owns the extraction lifecycle, reviewer edits, verification state, issue and expiry dates, and audit events. A compliance reviewer may correct extracted values before verification.

### Implementations

| Implementation | Mode | Credential | Behavior |
| --- | --- | --- | --- |
| `MockDocumentParser` | `DEMO` | None | Returns deterministic fields from a synthetic asset identifier and evidence type. |
| `AnthropicVisionDocumentParser` | `EXTERNAL` | `ANTHROPIC_API_KEY` | Optionally extracts structured fields from a synthetic image using the configured provider. |

The mock output for a synthetic driving licence includes a fictional holder name, document number, categories, Code 95 flag, issue date, and expiry date. It must be stable across resets.

Missing Anthropic configuration selects `MockDocumentParser`. A failed external extraction must preserve the evidence record, report a readable processing error, and allow retry or an explicit return to demo mode.

## Identity Verification

### Interface

`IdentityVerificationProvider` accepts an opaque person reference and a synthetic presentation reference. It returns `match`, `confidence`, `mode`, a provider reference suitable for audit, and an evaluation timestamp.

The provider does not grant or deny access. `GateService` combines the identity result with token, standing, blacklist, evidence, training, and approval checks.

### Implementations

| Implementation | Mode | Credential | Behavior |
| --- | --- | --- | --- |
| `MockIdentityVerifier` | `DEMO` | None | Returns the deterministic match or mismatch assigned to the selected seeded scenario. |
| Future CV provider adapter | `EXTERNAL` | `IDENTITY_PROVIDER_API_KEY` and provider URL | Optional boundary for a later synthetic integration exercise. |

The demo must not collect or process real biometric information. The gate screen must display `DEMO MODE` for mock results.

If an explicitly selected external verifier is unavailable during a gate evaluation, the API must return a typed provider-unavailable check rather than silently treating the person as matched. An operator may retry or deliberately select a deterministic demo scenario.

## File Storage

### Interface

`StorageProvider` creates a private object from validated content, retrieves authorized content, and returns an opaque storage reference. Domain records store the reference rather than a public filesystem path or provider credential.

The API owns upload size, extension, MIME-type, path, and authorization checks before a storage call.

### Implementations

| Implementation | Mode | Credential | Behavior |
| --- | --- | --- | --- |
| `LocalStorage` | `LOCAL` | None | Stores synthetic files in a private Docker volume outside the web public directory. |
| `S3Storage` | `EXTERNAL` | S3-compatible settings and credentials | Optionally stores synthetic files in a private bucket. |

Missing S3 credentials select `LocalStorage`. Neither implementation may return a permanent unauthenticated public URL. Preview access must pass through an authorized API response or a short-lived provider mechanism.

## Notifications

### Interface

`NotificationProvider` receives a template key, recipient reference, structured payload, and idempotency key. It returns delivery mode, status, and a provider reference. Domain services create business alerts and audit events independently of delivery success.

### Implementations

| Implementation | Mode | Credential | Behavior |
| --- | --- | --- | --- |
| `InAppNotification` | `IN_APP` | None | Persists a visible local invitation, correction, expiry, or re-validation notification. |
| `SmtpNotification` | `SMTP` | Optional SMTP configuration | Optionally sends synthetic-address email or routes mail to a local catcher. |

Missing SMTP credentials select `InAppNotification`. No demo flow may require an email to be delivered before the workflow can continue.

## Planned Service Integration

| Domain service | Provider dependency | Domain-owned behavior |
| --- | --- | --- |
| `EvidenceService` | `DocumentExtractionProvider`, `StorageProvider` | Evidence lifecycle, editable review, verification, rejection, and re-upload request |
| `GateService` | `IdentityVerificationProvider` | Ordered compliance checks, final grant or denial, reasons, and corrective actions |
| Invitation and re-validation services | `NotificationProvider` | Business state, task creation, and audit events |
| Upload and evidence routes | `StorageProvider` through `EvidenceService` | Authorization and validated file handling |

`ComplianceService`, `ApprovalService`, `TokenService`, `PresenceService`, `DashboardService`, and `AuditService` have no direct dependency on an external provider.

## Provider Selection and Observability

Provider selectors and credential names are documented in `requirements/CREDENTIALS.md`. The API must expose only sanitized provider mode and health information.

Startup logs may state that an optional provider was unavailable and that a local provider was selected. They must not print API keys, passwords, tokens, connection strings, uploaded content, or sensitive provider responses.

Relevant API responses must include enough provider-mode information for the web application to show `DEMO MODE`, `LOCAL`, `IN APP`, or `EXTERNAL`. The web application must render the returned mode rather than infer it from environment variables.

## Future Integration Boundaries

The following integrations are intentionally not implemented in the manager demo:

| Future integration | Required discovery before implementation |
| --- | --- |
| Authoritative person or HR source | Ownership, identity key, update direction, retention, and access controls |
| Company or supplier source | Authoritative supplier status, duplicate rules, and compliance ownership |
| Agency or freight-exchange feed | Notice timing, payload, consent, failure handling, and manual fallback |
| Enterprise LMS | Module ownership, completion API, score semantics, and expiry rules |
| Physical gate or barrier | Hardware protocol, network conditions, offline mode, safety fallback, and operator ownership |
| Production identity matching | Legal basis, DPIA, accuracy thresholds, provider selection, retention, and appeal path |

## Validation Obligations

VAL-01 requires inspection showing that every optional integration has a deterministic local fallback. VAL-06 must prove that the backend, rather than the provider or frontend, owns the final gate decision. VAL-10 and VAL-12 must confirm that provider modes are visible, secrets are absent, uploads remain private, and simulated identity behavior is not represented as production biometric processing.
