# Credential Inventory

## Purpose

This inventory defines the credential boundary for the manager-facing demo. It records configuration names and intended use without supplying secret values.

The governing **SOURCE FACT** is that no external API key may block development or the manager walkthrough. Every third-party capability has a deterministic local substitute, and simulated behavior is identified as `DEMO MODE`.

## Handling Rules

Real secret values must never be committed to source control, documentation, synthetic assets, logs, screenshots, QR payloads, or browser-visible configuration.

The API reads secret-bearing values only on the server. The web application must not receive database credentials, signing material, provider API keys, storage secrets, or SMTP passwords.

The tracked `.env.example` contains only non-secret defaults and empty optional overrides. A local `.env` is not required because Compose supplies credential-free defaults. If an operator creates one, it remains ignored by source control.

## REQUIRED FOR LOCAL DEMO

| Variable | Purpose | Implemented value or behavior | Credential? |
| --- | --- | --- | --- |
| `POSTGRES_DB` | Name the local database. | `renewi_access` | No |
| `POSTGRES_USER` | Name the local database role. | `renewi` | No |
| `POSTGRES_PORT` | Bind PostgreSQL to the host loopback interface. | `5432` | No |
| `POSTGRES_PASSWORD` | Reserved for non-demo PostgreSQL authentication. | Empty and unused by the local trust-authenticated container | No local value required |
| `DATABASE_URL` | Connect the API, migrations, seed, and reset commands. | `postgresql+psycopg://renewi@postgres:5432/renewi_access` | No password |
| `REDIS_URL` | Connect API background coordination and caching to Redis. | `redis://redis:6379/0` | No password |
| `FRONTEND_PORT` | Bind the web shell to localhost. | `3000` | No |
| `BACKEND_PORT` | Bind the API to localhost. | `8000` | No |
| `STORAGE_PROVIDER` | Select evidence storage. | `local` | No |
| `STORAGE_LOCAL_PATH` | Locate private evidence inside the API volume. | `/var/lib/renewi/evidence` | No |
| `OCR_PROVIDER` | Select document extraction. | `mock` | No |
| `IDENTITY_VERIFIER_PROVIDER` | Select identity verification. | `mock` | No |
| `NOTIFICATION_PROVIDER` | Select notifications. | `mock` | No |
| `AUTH_PROVIDER` | Select authentication. | `demo` | No |

PostgreSQL trust authentication is a deliberate development-only choice. The database and Redis host ports bind to `127.0.0.1`; this configuration must not be used for a shared or production deployment.

## Local Application Security Overrides

| Variable | Purpose | Local behavior when empty |
| --- | --- | --- |
| `APP_SECRET_KEY` | Sign local session or token data. | The API generates an in-memory local-only value without requiring manual setup. |
| `DEMO_SEED_PASSWORD` | Initialize seeded role accounts. | Compose uses the explicitly non-production `renewi-demo-access` fallback so the credential-free manager demo is repeatable. |
| `SESSION_COOKIE_SECURE` | Control secure-cookie enforcement. | `false` for the HTTP localhost demo; hosted environments must override it. |
| `SESSION_COOKIE_NAME` | Name the signed HttpOnly browser session. | `renewi_session`. |
| `SESSION_TTL_SECONDS` | Limit signed-session lifetime. | `28800` seconds (eight hours). |

These values are internal demo configuration, not third-party credentials. The
committed seed password is safe only for this synthetic local demonstration and
must be overridden for any shared or hosted environment. Empty overrides must
not block initial Compose infrastructure startup.

## OPTIONAL INTEGRATION

### Document extraction

| Variable | Purpose | Requirement |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Authorize optional Anthropic extraction. | Optional secret |
| `ANTHROPIC_MODEL` | Select an optional Anthropic model. | Optional non-secret setting |

### Object storage

| Variable | Purpose | Requirement |
| --- | --- | --- |
| `S3_ENDPOINT_URL` | Identify an optional S3-compatible endpoint. | Optional |
| `S3_REGION` | Identify an optional storage region. | Optional |
| `S3_BUCKET` | Identify the private upload bucket. | Optional |
| `S3_ACCESS_KEY_ID` | Authenticate the optional storage client. | Optional secret |
| `S3_SECRET_ACCESS_KEY` | Authenticate the optional storage client. | Optional secret |

### Identity verification

| Variable | Purpose | Requirement |
| --- | --- | --- |
| `IDENTITY_PROVIDER_API_URL` | Locate an optional verification service. | Optional |
| `IDENTITY_PROVIDER_API_KEY` | Authorize an optional verification service. | Optional secret |

### Notifications

| Variable | Purpose | Requirement |
| --- | --- | --- |
| `SMTP_HOST` | Locate an optional notification relay. | Optional |
| `SMTP_PORT` | Select the optional relay port. | Optional |
| `SMTP_USERNAME` | Authenticate to an optional relay. | Optional secret |
| `SMTP_PASSWORD` | Authenticate to an optional relay. | Optional secret |
| `SMTP_FROM_ADDRESS` | Set an optional sender address. | Optional |

## DEMO FALLBACK

| Capability | Selector | Default | Fallback implementation |
| --- | --- | --- | --- |
| Document extraction | `OCR_PROVIDER` | `mock` | Deterministic mock document parser |
| Identity verification | `IDENTITY_VERIFIER_PROVIDER` | `mock` | Deterministic mock identity verifier |
| Storage | `STORAGE_PROVIDER` | `local` | Private `private_storage` named volume |
| Notifications | `NOTIFICATION_PROVIDER` | `mock` | Deterministic local notification adapter |
| Authentication | `AUTH_PROVIDER` | `demo` | Seeded local demo authentication |
| Database | `DATABASE_URL` | Local Compose URL | Trust-authenticated local PostgreSQL |
| Coordination | `REDIS_URL` | Local Compose URL | Local Redis with no external credential |

If an optional provider is selected without its required configuration, API startup emits a sanitized warning, selects the deterministic local adapter, and exposes the resulting `DEMO` or `LOCAL` mode through health metadata. Logs and responses never contain supplied or missing credential values.

## Verification Obligations

STEP-03 provides the environment template and credential-free infrastructure defaults. STEP-04 validates provider selection at API startup and implements generated in-memory local application-security values. Its clean Compose validation showed only sanitized generation notices and selected provider modes; no generated value was logged or returned by `/health`. VAL-01, VAL-10, and VAL-12 must continue to confirm that no tracked file, rendered QR code, synthetic asset, browser response, or ordinary log contains a secret value.
