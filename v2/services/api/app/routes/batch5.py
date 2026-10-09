"""Authorized APIs for Batch 5 operational presence and dashboard workflows."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import PresenceEvent, UserAccount
from app.schemas.batch5 import (
    CurrentPresenceResponse,
    DashboardSnapshotResponse,
    PresenceEventResponse,
    PresenceExitCreate,
)
from app.security import require_permissions
from app.services import (
    WorkflowError,
    get_dashboard_snapshot,
    list_current_presence,
    record_visit_exit,
)

router = APIRouter(prefix="/api", tags=["Presence and dashboard"])


def _raise_api_error(error: WorkflowError) -> None:
    """Translate a domain-service error to its documented HTTP response."""

    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


# PUBLIC_INTERFACE
@router.get(
    "/presence",
    response_model=list[CurrentPresenceResponse],
    operation_id="list_current_presence",
    summary="List people currently present at sites",
    description=(
        "Derives current presence from immutable authorized entry and exit events "
        "and active visit windows. It never exposes scanned token references or "
        "identity-provider payloads."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account lacks presence:read."},
    },
)
def get_current_presence(
    _: Annotated[UserAccount, Depends(require_permissions("presence:read"))],
    database: Annotated[Session, Depends(get_db)],
    site_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional site identifier that narrows the projection."),
    ] = None,
) -> list[CurrentPresenceResponse]:
    """Return safely projected people currently present at authorized sites.

    Args:
        _: Authorized account with operational presence-read permission.
        database: Request-scoped SQLAlchemy session.
        site_id: Optional site filter.

    Returns:
        Deterministically ordered current-presence records.
    """

    return [
        CurrentPresenceResponse.model_validate(row)
        for row in list_current_presence(database, site_id=site_id)
    ]


# PUBLIC_INTERFACE
@router.post(
    "/presence/exits",
    response_model=PresenceEventResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="record_visit_exit",
    summary="Record a person's exit from a site",
    description=(
        "Appends an immutable exit event for a visit with a current recorded "
        "entry. The command does not alter the historical gate decision."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account cannot record site exits."},
        404: {"description": "The requested visit does not exist."},
        409: {"description": "The visit has no current recorded entry to close."},
    },
)
def post_presence_exit(
    payload: PresenceExitCreate,
    actor: Annotated[UserAccount, Depends(require_permissions("presence:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> PresenceEventResponse:
    """Append and return a site-exit event for one entered visit.

    Args:
        payload: Visit identifier for the physical departure.
        actor: Authorized gate operator or privileged account.
        database: Request-scoped SQLAlchemy session.

    Returns:
        The immutable persisted exit event.
    """

    try:
        event = record_visit_exit(
            database,
            actor=actor,
            visit_id=payload.visit_id,
        )
        database.commit()
        database.refresh(event)
        return PresenceEventResponse.model_validate(event)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.get(
    "/dashboard",
    response_model=DashboardSnapshotResponse,
    operation_id="get_dashboard_snapshot",
    summary="Get the backend-derived operational site-access dashboard",
    description=(
        "Returns bounded, sanitized site counters, current presence, and recent "
        "backend-authoritative gate decisions. Token values, hashes, and identity "
        "presentation data are never returned."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account lacks dashboard:read."},
        422: {"description": "Dashboard query options are outside safe bounds."},
    },
)
def get_dashboard(
    _: Annotated[UserAccount, Depends(require_permissions("dashboard:read"))],
    database: Annotated[Session, Depends(get_db)],
    activity_hours: Annotated[
        int,
        Query(
            ge=1,
            le=168,
            description="Recent operational lookback period in hours.",
        ),
    ] = 24,
    recent_limit: Annotated[
        int,
        Query(
            ge=1,
            le=100,
            description="Maximum number of recent decisions to return.",
        ),
    ] = 20,
) -> DashboardSnapshotResponse:
    """Return the bounded backend-authoritative operational dashboard.

    Args:
        _: Authorized account with dashboard-read permission.
        database: Request-scoped SQLAlchemy session.
        activity_hours: Lookback period for operational counts.
        recent_limit: Maximum number of recent decision rows.

    Returns:
        Aggregate counters, per-site operations, presence, and recent decisions.
    """

    try:
        return DashboardSnapshotResponse.model_validate(
            get_dashboard_snapshot(
                database,
                activity_hours=activity_hours,
                recent_limit=recent_limit,
            )
        )
    except WorkflowError as error:
        _raise_api_error(error)
