"""Private Compose-only deterministic baseline runner for E2E acceptance tests."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status

from app.commands import reset_database, seed_database
from app.config import get_settings

BASELINE_TOKEN_HEADER = "X-E2E-Baseline-Token"


def _require_baseline_token(
    supplied_token: Annotated[str | None, Header(alias=BASELINE_TOKEN_HEADER)] = None,
) -> None:
    """Reject requests that do not hold the isolated Compose capability token."""

    configured_token = get_settings().e2e_baseline_token
    expected_token = (
        configured_token.get_secret_value() if configured_token is not None else ""
    )

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The isolated E2E baseline runner is not configured.",
        )

    if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The E2E baseline capability is invalid.",
        )


# PUBLIC_INTERFACE
def create_baseline_app() -> FastAPI:
    """Create the private E2E baseline service.

    Returns:
        A Compose-internal FastAPI application with only a capability-gated
        restore operation. This service is never published on a host port and
        is not included in the production application API.
    """

    application = FastAPI(
        title="Renewi E2E Baseline Runner",
        description=(
            "Private Compose-only reset-and-seed runner for isolated acceptance "
            "tests. It is not part of the public application API."
        ),
        version="1.0.0",
        openapi_tags=[
            {
                "name": "E2E baseline",
                "description": "Private isolated test-baseline restoration.",
            }
        ],
    )

    # PUBLIC_INTERFACE
    @application.get(
        "/health",
        summary="Check baseline runner readiness",
        description=(
            "Returns runner readiness inside the private Compose network. "
            "This endpoint does not expose database state or credentials."
        ),
        tags=["E2E baseline"],
    )
    def baseline_health() -> dict[str, str]:
        """Return readiness for the private Compose health check."""

        return {"status": "ready"}

    # PUBLIC_INTERFACE
    @application.post(
        "/restore",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Restore the deterministic E2E baseline",
        description=(
            "Requires the private Compose capability token and invokes the "
            "existing CLI-equivalent reset and deterministic seed operations. "
            "The sidecar has no host port and is available only in the E2E profile."
        ),
        tags=["E2E baseline"],
    )
    def restore_baseline(_: None = Depends(_require_baseline_token)) -> Response:
        """Reset and seed the disposable isolated E2E database."""

        reset_database()
        seed_database()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return application


app = create_baseline_app()
