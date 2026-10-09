# Environment Contract

## Purpose

This document defines development, manager-demo, and optional-integration configuration. The complete local workflow must run without third-party credentials. Missing external credentials must never prevent infrastructure startup or the eleven-step journey.

STEP-03 implements the root `.env.example` and `docker-compose.yml`. STEP-04 implements the profile-gated FastAPI service, SQLAlchemy connectivity, Alembic migrations, database lifecycle commands, and readiness reporting. The E2E definition remains profile-gated for its owning implementation step.

## Environment Profiles

### Development

The default Compose profile starts PostgreSQL, Redis, and the Next.js web shell. PostgreSQL and Redis bind only to host loopback addresses. The web shell remains usable while the API is unavailable.

The complete application profile starts with:

```powershell
docker compose --profile application up --build
```

Development uses synthetic records, deterministic providers, private evidence storage, and developer-oriented sanitized logs.

### Manager Demo

The manager-demo profile uses the same service contracts as development, starts from deterministic seed data, uses stable scenario dates relative to the persisted demo clock, and displays `DEMO MODE` for simulated extraction and identity verification.

The walkthrough must not require internet access after images and dependencies have been built.

### Optional Integration

Optional integrations may enable external OCR, S3-compatible storage, SMTP, or an identity provider. They exercise adapter compatibility and do not redefine domain behavior.

Incomplete optional configuration must retain the matching deterministic local provider. Real identity documents or biometric data are prohibited.

## REQUIRED FOR LOCAL DEMO

| Group | Variables and defaults |
| --- | --- |
| Runtime | `APP_ENV=development`, `LOG_LEVEL=INFO`, `FRONTEND_PORT=3000`, `BACKEND_PORT=8000` |
| Browser/API origins | `WEB_ORIGIN=http://localhost:3000`, `API_BASE_URL=http://localhost:8000`, `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` |
| Database | `POSTGRES_DB=renewi_access`, `POSTGRES_USER=renewi`, `POSTGRES_PORT=5432`, `DATABASE_URL=postgresql+psycopg://renewi@postgres:5432/renewi_access` |
| Redis | `REDIS_PORT=6379`, `REDIS_URL=redis://redis:6379/0` |
| Demo operation | `DEMO_MODE=true`, `DEMO_TIMEZONE=Europe/Amsterdam` |
| Storage | `STORAGE_PROVIDER=local`, `STORAGE_LOCAL_PATH=/var/lib/renewi/evidence` |
| Provider selection | `OCR_PROVIDER=mock`, `IDENTITY_VERIFIER_PROVIDER=mock`, `NOTIFICATION_PROVIDER=mock`, `AUTH_PROVIDER=demo` |
| Authentication | `DEMO_SEED_PASSWORD=renewi-demo-access` for synthetic local accounts only |
| Cookie behavior | `SESSION_COOKIE_NAME=renewi_session`, `SESSION_TTL_SECONDS=28800`, `SESSION_COOKIE_SECURE=false` for local HTTP only |

A local `.env` file is optional. Compose supplies these defaults itself, so routine local startup requires no manual configuration.

`POSTGRES_PASSWORD` is intentionally empty and unused. PostgreSQL uses `POSTGRES_HOST_AUTH_METHOD=trust` only inside the local demo stack. Host access is bound to `127.0.0.1`.

## OPTIONAL INTEGRATION

The tracked template exposes empty overrides for:

- `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`
- `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, and `S3_SECRET_ACCESS_KEY`
- `IDENTITY_PROVIDER_API_URL` and `IDENTITY_PROVIDER_API_KEY`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_ADDRESS`

`APP_SECRET_KEY` remains an empty override and the API generates a process-local
signing value when it is absent. `DEMO_SEED_PASSWORD` has the explicitly
non-production fallback `renewi-demo-access` so all seeded roles can sign in
after a deterministic reset without manual configuration. Shared or hosted
environments must override both values. Startup logs never print either value.

## DEMO FALLBACK

| Capability | Default implementation | External credentials required | Visible mode |
| --- | --- | --- | --- |
| Document extraction | Deterministic mock parser | No | `DEMO MODE` |
| Identity verification | Deterministic mock verifier | No | `DEMO MODE` |
| File storage | Local private named volume | No | `LOCAL` |
| Notifications | Deterministic mock adapter | No | `DEMO MODE` |
| Authentication | Seeded demo provider | No | `DEMO MODE` |
| Database | Local PostgreSQL | No | `LOCAL` |
| Coordination | Local Redis | No | `LOCAL` |

Provider mode must be included in relevant API results so the web application can display it without inferring server configuration.

## Compose Services

### PostgreSQL

The `postgres` service uses PostgreSQL 17, database `renewi_access`, role `renewi`, and development-only trust authentication. Data persists in the `postgres_data` named volume.

Its health check runs `pg_isready` against the configured role and database.

### Redis

The `redis` service uses Redis 7.4 with append-only persistence in the `redis_data` named volume. Its health check requires `redis-cli ping` to return `PONG`.

### Web

The `web` service builds the existing standalone Next.js application through `apps/web/Dockerfile`, binds to `127.0.0.1:3000` by default, and checks the root route. It does not depend on API health, preserving the backend-independent shell behavior established in STEP-02.

### API

The `api` definition is gated by the `application` and `e2e` profiles. It receives the credential-free database and Redis URLs, deterministic provider selectors, demo settings, and the private `private_storage` volume.

PostgreSQL and Redis must be healthy before the API starts. The container applies Alembic migrations before starting its non-root, single-worker Uvicorn process. `/health` executes a PostgreSQL query and reports HTTP 503 if database readiness is degraded.

### E2E

The `e2e` definition is gated by the `e2e` profile until the browser-test package exists. It targets the Compose-internal web and API addresses.

## Storage and Privacy

The database, Redis, and private evidence paths use named volumes:

- `postgres_data`
- `redis_data`
- `private_storage`

Evidence storage is mounted only into the API service and is never exposed through the web public directory.

Every profile uses fictional identities and documents. Files remain private, constrained, and referenced by opaque identifiers.

## Startup, Health, and Cleanup

Credential-free infrastructure startup:

```powershell
docker compose up -d --wait postgres redis
docker compose ps
docker compose exec -T postgres psql -U renewi -d renewi_access -c "SELECT current_database(), current_user;"
docker compose exec -T redis redis-cli ping
```

Complete application startup and deterministic database lifecycle:

```powershell
docker compose --profile application up -d --build --wait
docker compose --profile application exec -T api python -m app.commands migrate
docker compose --profile application exec -T api python -m app.commands seed
docker compose --profile application exec -T api python -m app.commands reset
docker compose --profile application exec -T api python -m app.commands seed
Invoke-RestMethod -Uri "http://localhost:8000/health"
```

`migrate` is idempotent. `seed` reconciles deterministic records, and `reset` truncates application tables while preserving `alembic_version`. Reset is destructive to application data and is intended only for deliberate demo-state restoration.

Clean shutdown and volume removal for an intentionally disposable Batch 0 environment:

```powershell
docker compose down -v --remove-orphans
```

Do not remove volumes containing useful demo state during normal development. Use the migration, seed, and reset commands for a clean deterministic demo state.

## Validation Evidence

On 2026-09-22, Docker Compose v5.3.1 accepted the full service model. A clean validation project pulled PostgreSQL 17 and Redis 7.4, created named persistence volumes, and reported both containers healthy.

An in-container PostgreSQL query returned database `renewi_access` and role `renewi`. A separate container connected over the Compose network without a password and successfully ran `SELECT 1`. Redis returned `PONG`.

STEP-04 built the FastAPI image and started API, PostgreSQL, and Redis in the isolated `renewi-step04-validation` project. All three services became healthy. Startup applied Alembic revision `20260922_0001`, and a second migration invocation completed successfully.

The initial seed created one `demo-foundation` marker with version `batch-0-v1` and fixed timestamp `2026-01-01 00:00:00+00`. Reset reduced the marker count to zero, and the second seed restored exactly one marker with the same version.

`GET /health` returned HTTP 200 with API and database status `ready`, demo mode enabled, mock capabilities reported as `DEMO`, and storage reported as `LOCAL`. `/openapi.json` exposed the documented `get_health` operation. Startup generated local security values without printing them. Final teardown removed all isolated validation containers, network, and named volumes.
