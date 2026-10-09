"""Authorized append and chronological read routes for audit evidence."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import AuditEvent, UserAccount
from app.schemas.domain import AuditEventCreate, AuditEventResponse
from app.security import require_permissions
from app.services import append_audit_event

router = APIRouter(prefix="/api/audit", tags=["Audit"])


# PUBLIC_INTERFACE
@router.get(
    "/events",
    response_model=list[AuditEventResponse],
    operation_id="list_audit_events",
    summary="List chronological audit evidence",
    description=(
        "Returns append-only lifecycle evidence in oldest-to-newest order to "
        "roles with audit:read."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account lacks audit:read."},
    },
)
def list_audit_events(
    _: Annotated[UserAccount, Depends(require_permissions("audit:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[AuditEvent]:
    """Return audit events in deterministic chronological order.

    Args:
        _: Authorized current account.
        database: Request-scoped SQLAlchemy session.

    Returns:
        Audit events ordered by occurrence time and identifier.
    """

    statement = select(AuditEvent).order_by(
        AuditEvent.occurred_at,
        AuditEvent.id,
    )
    return list(database.scalars(statement).all())


# PUBLIC_INTERFACE
@router.post(
    "/events",
    response_model=AuditEventResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="append_audit_event",
    summary="Append authorized business evidence",
    description=(
        "Appends an immutable audit event. Viewer, gate, host, participant, and "
        "anonymous callers are rejected by API dependencies."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account lacks audit:write."},
        422: {"description": "The event payload is invalid."},
    },
)
def create_audit_event(
    payload: AuditEventCreate,
    actor: Annotated[UserAccount, Depends(require_permissions("audit:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> AuditEvent:
    """Append business evidence under the authenticated actor.

    Args:
        payload: Validated non-secret event details.
        actor: Authorized current account.
        database: Request-scoped SQLAlchemy session.

    Returns:
        The persisted immutable audit event.
    """

    event = append_audit_event(
        database,
        actor=actor,
        action=payload.action,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        reason=payload.reason,
        details=payload.details,
    )
    database.commit()
    database.refresh(event)
    return event
