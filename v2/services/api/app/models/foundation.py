"""Batch 0 persistence model used to verify database lifecycle commands."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class FoundationState(Base):
    """Deterministic marker for the successfully seeded demo foundation."""

    __tablename__ = "foundation_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    seed_version: Mapped[str] = mapped_column(String(32), nullable=False)
    seeded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
