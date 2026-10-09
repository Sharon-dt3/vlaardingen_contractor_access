"""Private, single-use identity scan results for final gate evaluation."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


# PUBLIC_INTERFACE
class GateIdentityScan(Base):
    """A token-bound gate ID comparison, consumed by one final evaluation."""

    __tablename__ = "gate_identity_scans"
    __table_args__ = (
        Index(
            "ix_gate_identity_scans_operator_token",
            "operator_id",
            "token_reference_hash",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invitations.id", ondelete="CASCADE"),
        nullable=False,
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    token_reference_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    invitation_identity_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
