"""Append-only audit persistence shared by business commands."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, UserAccount


# PUBLIC_INTERFACE
def append_audit_event(
    database: Session,
    *,
    actor: UserAccount | None,
    action: str,
    entity_type: str,
    entity_id: str,
    reason: str,
    details: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> AuditEvent:
    """Append immutable audit evidence within the caller's transaction.

    Args:
        database: SQLAlchemy unit of work owned by the business command.
        actor: Authenticated account responsible for the event, when applicable.
        action: Stable business action identifier.
        entity_type: Type of affected entity.
        entity_id: Stable or opaque affected entity identifier.
        reason: Human-readable business reason.
        details: Synthetic, non-secret structured context.
        occurred_at: Optional deterministic timestamp for seed operations.

    Returns:
        The newly appended audit event. The caller controls commit or rollback.
    """

    event = AuditEvent(
        id=uuid.uuid4(),
        actor_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        details=details or {},
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )
    database.add(event)
    database.flush()
    return event
