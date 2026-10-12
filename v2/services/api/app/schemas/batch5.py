"""Pydantic contracts for Batch 5 presence and dashboard workflows."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import GateDecision, PresenceEventType


# PUBLIC_INTERFACE
class PresenceExitCreate(BaseModel):
    """An authorized command that records a person's physical site exit."""

    visit_id: uuid.UUID = Field(
        ...,
        description="Visit identifier for the person leaving the site.",
    )


# PUBLIC_INTERFACE
class PresenceEventResponse(BaseModel):
    """A safe immutable entry or exit event returned to gate operators."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Presence event identifier.")
    visit_id: uuid.UUID = Field(..., description="Associated visit identifier.")
    person_id: uuid.UUID = Field(..., description="Associated person identifier.")
    site_id: uuid.UUID = Field(..., description="Associated site identifier.")
    gate_event_id: uuid.UUID | None = Field(
        default=None,
        description="Grant decision that produced an entry, when applicable.",
    )
    event_type: PresenceEventType = Field(
        ...,
        description="Whether this immutable event records entry or exit.",
    )
    occurred_at: datetime = Field(
        ...,
        description="UTC instant at which the occupancy transition was recorded.",
    )


# PUBLIC_INTERFACE
class CurrentPresenceResponse(BaseModel):
    """A sanitized projection of one person currently present at a site."""

    gate_event_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Backend-authoritative grant that established entry. Null for a walk-up "
            "person, who has no gate event."
        ),
    )
    presence_event_id: uuid.UUID | None = Field(
        default=None,
        description="Explicit entry event identifier, when recorded after Batch 5.",
    )
    person_id: uuid.UUID = Field(..., description="Present person's identifier.")
    person_name: str = Field(..., description="Safe display name for the person.")
    population: str = Field(..., description="Configured person population.")
    id_expiry_date: date | None = Field(
        default=None,
        description=(
            "Expiry date of the latest verified population-appropriate identity "
            "document; null when no verified date is available. Pending renewal "
            "proposals are never displayed as verified dates."
        ),
    )
    visit_id: uuid.UUID | None = Field(
        default=None, description="Active visit identifier. Null for a walk-up person."
    )
    site_id: uuid.UUID = Field(..., description="Site where the person is present.")
    site_name: str = Field(..., description="Safe display name for the site.")
    entered_at: datetime = Field(
        ...,
        description="UTC instant of the active authorized entry.",
    )
    visit_ends_at: datetime | None = Field(
        default=None,
        description="UTC visit-window end after which presence expires. Null for a walk-up person.",
    )
    decision: str = Field(
        ...,
        description="Authoritative grant decision associated with the entry.",
    )
    source: str = Field(
        default="invitation",
        description="Where the person came from: an invitation, or a walk-up registration.",
    )
    walk_up_registration_id: uuid.UUID | None = Field(
        default=None, description="The walk-up registration, when source is walk_up."
    )
    site_key: str | None = Field(
        default=None, description="Short site key used to record a walk-up exit."
    )
    exit_due_at: datetime | None = Field(
        default=None,
        description="When this person should have left: the earlier of the visit end and their QR's exit time.",
    )
    overdue: bool = Field(default=False, description="Still on site after the exit time.")
    overdue_minutes: int | None = Field(default=None, description="How long past the exit time, in minutes.")


# PUBLIC_INTERFACE
class DashboardPathCounts(BaseModel):
    """People on site, entered and exited for one way of arriving."""

    present_count: int = Field(..., ge=0)
    entry_count: int = Field(..., ge=0)
    exit_count: int = Field(..., ge=0)
    overdue_count: int = Field(default=0, ge=0, description="Still on site after their exit time.")


# PUBLIC_INTERFACE
class DashboardByPath(BaseModel):
    """The same counts split into planned (invited) and unexpected (walk-up) arrivals."""

    planned: DashboardPathCounts
    walk_up: DashboardPathCounts


# PUBLIC_INTERFACE
class DashboardTotalsResponse(BaseModel):
    """Aggregate operational counts for the selected dashboard interval."""

    site_count: int = Field(..., ge=0)
    active_visit_count: int = Field(..., ge=0)
    present_count: int = Field(..., ge=0)
    grant_count: int = Field(..., ge=0)
    denial_count: int = Field(..., ge=0)
    entry_count: int = Field(..., ge=0)
    exit_count: int = Field(..., ge=0)
    overdue_count: int = Field(default=0, ge=0, description="Still on site after their exit time.")
    by_path: DashboardByPath | None = None


# PUBLIC_INTERFACE
class DashboardSiteResponse(BaseModel):
    """Operational counters for one site within the dashboard interval."""

    site_id: uuid.UUID
    site_name: str
    country_code: str
    active_visit_count: int = Field(..., ge=0)
    present_count: int = Field(..., ge=0)
    grant_count: int = Field(..., ge=0)
    denial_count: int = Field(..., ge=0)
    entry_count: int = Field(..., ge=0)
    exit_count: int = Field(..., ge=0)
    overdue_count: int = Field(default=0, ge=0, description="Still on site after their exit time.")
    by_path: DashboardByPath | None = None


# PUBLIC_INTERFACE
class DashboardDecisionResponse(BaseModel):
    """A safe recent gate decision included in the operational dashboard."""

    gate_event_id: uuid.UUID
    occurred_at: datetime
    site_id: uuid.UUID
    site_name: str | None
    visit_id: uuid.UUID | None
    person_id: uuid.UUID | None
    person_name: str | None
    decision: GateDecision
    reason_codes: list[str]
    source: str = "invitation"


# PUBLIC_INTERFACE
class DashboardSnapshotResponse(BaseModel):
    """Backend-derived operational dashboard data with no credential secrets."""

    as_of: datetime
    activity_window_started_at: datetime
    activity_hours: int = Field(..., ge=1, le=168)
    totals: DashboardTotalsResponse
    sites: list[DashboardSiteResponse]
    current_presence: list[CurrentPresenceResponse]
    recent_decisions: list[DashboardDecisionResponse]
