"""API and database readiness endpoint."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.session import get_db
from app.schemas.health import ComponentHealth, HealthResponse

router = APIRouter(tags=["Health"])


# PUBLIC_INTERFACE
@router.get(
    "/health",
    response_model=HealthResponse,
    operation_id="get_health",
    summary="Check API and database readiness",
    description=(
        "Runs a lightweight PostgreSQL query and returns only sanitized runtime "
        "and provider readiness details. HTTP 503 indicates degraded readiness."
    ),
    responses={
        200: {"description": "The API and PostgreSQL are ready."},
        503: {"description": "The API is running but PostgreSQL is unavailable."},
    },
)
def get_health(
    response: Response,
    database: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Return API and PostgreSQL readiness.

    Args:
        response: FastAPI response used to signal degraded readiness.
        database: Request-scoped SQLAlchemy session.
        settings: Validated server settings.

    Returns:
        A sanitized readiness response with selected provider modes.
    """

    database_status = "ready"
    overall_status = "ready"

    try:
        database.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_status = "unavailable"
        overall_status = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall_status,
        api=ComponentHealth(status="ready"),
        database=ComponentHealth(status=database_status),
        environment=settings.app_env,
        demo_mode=settings.demo_mode,
        providers=settings.provider_modes(),
    )
