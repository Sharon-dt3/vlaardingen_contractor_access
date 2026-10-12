"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.logging import configure_logging
from app.routes.audit import router as audit_router
from app.routes.auth import router as auth_router
from app.routes.health import router as health_router
from app.routes.life_saving import router as life_saving_router
from app.routes.site_settings import router as site_settings_router
from app.routes.users import router as users_router
from app.routes.walk_up import router as walk_up_router
from app.routes.records import router as records_router
from app.routes.batch3 import router as batch3_router
from app.routes.batch4 import router as batch4_router
from app.routes.batch5 import router as batch5_router
from app.routes.batch6 import router as batch6_router
from app.routes.workflows import router as workflows_router

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

OPENAPI_TAGS = [
    {
        "name": "Health",
        "description": "Credential-free API and PostgreSQL readiness checks.",
    },
    {
        "name": "Authentication",
        "description": "Seeded local login, logout, and signed-session inspection.",
    },
    {
        "name": "Core records",
        "description": "Permission-protected site, company, person, and visit reads.",
    },
    {
        "name": "Audit",
        "description": "Chronological reads and append-only business evidence.",
    },
    {
        "name": "Invitations and evidence",
        "description": (
            "Workflow Steps 1-3: invitation, create-or-link registration, "
            "private evidence, configured server-side document extraction, "
            "and authorized human review."
        ),
    },
    {
        "name": "Training, compliance, approvals, and tokens",
        "description": (
            "Workflow Steps 4-6: scored training, configurable compliance, "
            "blacklist controls, auditable approvals, and opaque QR tokens."
        ),
    },
    {
        "name": "Identity and gate decisions",
        "description": (
            "Workflow Steps 7-8: presentation identity checks, reviewer-"
            "verified identity evidence, and backend-authoritative gate "
            "grants or denials."
        ),
    },
    {
        "name": "Presence and dashboard",
        "description": (
            "Workflow Step 9: immutable entry and exit events, current site "
            "presence, and backend-derived operational dashboard projections."
        ),
    },
    {
        "name": "Expiry and re-validation",
        "description": (
            "Workflow Step 10: persisted demo time, idempotent expiry alerts, "
            "re-validation tasks, verified renewals, and restored eligibility."
        ),
    },
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Prepare local security values and provider fallbacks for this process."""

    for notice in settings.prepare_local_runtime():
        logger.warning(notice)

    logger.info(
        "API startup complete environment=%s demo_mode=%s",
        settings.app_env,
        settings.demo_mode,
    )
    yield
    logger.info("API shutdown complete")


# PUBLIC_INTERFACE
def create_app() -> FastAPI:
    """Create and configure the Renewi site-access API application.

    Returns:
        A FastAPI application with OpenAPI metadata, CORS, lifecycle handling,
        and registered Batch 0 through Batch 6 backend routes.
    """

    application = FastAPI(
        title="Renewi Contractor and Visitor Site Access API",
        description=(
            "Manager-demo API for the contractor and visitor site-access "
            "lifecycle. It exposes credential-free readiness, seeded local "
            "authentication, API-enforced roles, invitation and registration "
            "workflows, private synthetic evidence, scored training, "
            "authoritative compliance, approvals, opaque access tokens, and "
            "audit history, immutable site-presence events, and operational "
            "dashboard projections, persisted demo-time expiry processing, "
            "and re-validation restoration."
        ),
        version="0.4.0",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(records_router)
    application.include_router(audit_router)
    application.include_router(workflows_router)
    application.include_router(batch3_router)
    application.include_router(batch4_router)
    application.include_router(batch5_router)
    application.include_router(batch6_router)
    application.include_router(life_saving_router)
    application.include_router(walk_up_router)
    application.include_router(site_settings_router)
    application.include_router(users_router)
    return application


app = create_app()
