"""Batch 5 presence commands and operational dashboard projections."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import column, select
from sqlalchemy.orm import Session

from app.models import (
    Evidence,
    EvidenceStatus,
    EvidenceType,
    GateDecision,
    GateEvent,
    Person,
    Population,
    PresenceEvent,
    PresenceEventType,
    Site,
    UserAccount,
    Visit,
    VisitStatus,
)
from app.services.audit import append_audit_event
from app.services.batch6 import get_effective_time
from app.services.workflows import WorkflowError

_DEFAULT_ACTIVITY_HOURS = 24
_MAX_ACTIVITY_HOURS = 168
_DEFAULT_RECENT_LIMIT = 20
_MAX_RECENT_LIMIT = 100
_DRIVER_POPULATIONS = frozenset({
    Population.RENEWI_DRIVER,
    Population.TEMPORARY_DRIVER,
    Population.EXTERNAL_DRIVER,
})


def _utc_timestamp(value: datetime | None) -> datetime:
    """Normalize an optional observation timestamp to timezone-aware UTC."""

    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _validate_activity_options(
    *,
    activity_hours: int,
    recent_limit: int,
) -> None:
    """Validate bounded dashboard query options before querying persistence."""

    if not 1 <= activity_hours <= _MAX_ACTIVITY_HOURS:
        raise WorkflowError(
            422,
            f"activity_hours must be between 1 and {_MAX_ACTIVITY_HOURS}.",
        )
    if not 1 <= recent_limit <= _MAX_RECENT_LIMIT:
        raise WorkflowError(
            422,
            f"recent_limit must be between 1 and {_MAX_RECENT_LIMIT}.",
        )


def _person_name(person: Person | None) -> str | None:
    """Return the safe display name for an optional synthetic person."""

    if person is None:
        return None
    return f"{person.first_name} {person.last_name}"


def _presence_row(
    *,
    event: GateEvent,
    visit: Visit,
    person: Person,
    site: Site,
    presence_event: PresenceEvent | None,
) -> dict[str, Any]:
    """Project an active persisted entry into a safe current-presence row."""

    return {
        "gate_event_id": event.id,
        "presence_event_id": presence_event.id if presence_event else None,
        "person_id": person.id,
        "person_name": _person_name(person),
        "population": person.population.value,
        "visit_id": visit.id,
        "site_id": site.id,
        "site_name": site.name,
        "entered_at": (
            presence_event.occurred_at if presence_event else event.occurred_at
        ),
        "visit_ends_at": visit.ends_at,
        "decision": event.decision.value,
    }


def _current_presence_rows(
    database: Session,
    *,
    observed_at: datetime,
    site_id: uuid.UUID | None = None,
    ended_only: bool = False,
) -> list[dict[str, Any]]:
    """Return eligible visits whose latest recorded occupancy event is an entry.

    With ``ended_only`` it returns the opposite window: visits whose time has run out
    but whose person was never recorded as leaving, so the dashboard can flag them.
    """

    statement = (
        select(GateEvent, Visit, Person, Site)
        .join(Visit, GateEvent.visit_id == Visit.id)
        .join(Person, Visit.person_id == Person.id)
        .join(Site, Visit.site_id == Site.id)
        .where(
            GateEvent.decision == GateDecision.GRANT,
            # Gate events use live UTC; the saved demo clock only determines
            # whether the visit window is eligible for this projection.
            # Registration leaves a visit PLANNED; a grant records its entry
            # without changing that status. Blocked or closed visits stay out.
            Visit.status.in_((VisitStatus.PLANNED, VisitStatus.ACTIVE)),
            Visit.starts_at <= observed_at,
            (Visit.ends_at <= observed_at) if ended_only else (Visit.ends_at > observed_at),
        )
        .order_by(GateEvent.occurred_at.desc(), GateEvent.id.desc())
    )
    if site_id is not None:
        statement = statement.where(Visit.site_id == site_id)

    grant_rows_by_visit: dict[uuid.UUID, tuple[GateEvent, Visit, Person, Site]] = {}
    for event, visit, person, site in database.execute(statement):
        grant_rows_by_visit.setdefault(visit.id, (event, visit, person, site))

    if not grant_rows_by_visit:
        return []

    event_statement = (
        select(PresenceEvent)
        # PostgreSQL's insertion marker reflects recording order even when
        # historical demo and live occurred_at clocks disagree. Keep this
        # order aligned with Record Exit eligibility below.
        .where(PresenceEvent.visit_id.in_(set(grant_rows_by_visit)))
        .order_by(column("ctid").desc())
    )
    latest_presence_events: dict[uuid.UUID, PresenceEvent] = {}
    for event in database.scalars(event_statement):
        latest_presence_events.setdefault(event.visit_id, event)

    rows: list[dict[str, Any]] = []
    for visit_id, (gate_event, visit, person, site) in grant_rows_by_visit.items():
        presence_event = latest_presence_events.get(visit_id)
        if presence_event is not None:
            if presence_event.event_type is PresenceEventType.EXIT:
                continue
            if presence_event.gate_event_id != gate_event.id:
                linked_event = database.get(GateEvent, presence_event.gate_event_id)
                if linked_event is None or linked_event.decision is not GateDecision.GRANT:
                    continue
                gate_event = linked_event

        rows.append(
            _presence_row(
                event=gate_event,
                visit=visit,
                person=person,
                site=site,
                presence_event=presence_event,
            )
        )

    # Only reviewed identity evidence is authoritative. A proposed renewal
    # must not replace the displayed date until a reviewer verifies it.
    identity_types = {
        row["person_id"]: (
            EvidenceType.DRIVING_LICENCE
            if grant_rows_by_visit[row["visit_id"]][2].population in _DRIVER_POPULATIONS
            else EvidenceType.ID_CARD
        )
        for row in rows
    }
    latest_identity: dict[tuple[uuid.UUID, EvidenceType], date | None] = {}
    if identity_types:
        evidence_rows = database.scalars(
            select(Evidence)
            .where(
                Evidence.person_id.in_(set(identity_types)),
                Evidence.evidence_type.in_(
                    (EvidenceType.ID_CARD, EvidenceType.DRIVING_LICENCE)
                ),
                Evidence.status == EvidenceStatus.VERIFIED,
            )
            .order_by(Evidence.updated_at.desc(), Evidence.id.desc())
        )
        for evidence in evidence_rows:
            latest_identity.setdefault(
                (evidence.person_id, evidence.evidence_type), evidence.expiry_date
            )
    for row in rows:
        row["id_expiry_date"] = latest_identity.get(
            (row["person_id"], identity_types[row["person_id"]])
        )

    return sorted(rows, key=lambda row: (row["site_name"], row["person_name"]))


def _latest_presence_event(
    database: Session,
    *,
    visit_id: uuid.UUID,
) -> PresenceEvent | None:
    """Return the most recent explicit occupancy event for one visit."""

    return database.scalar(
        select(PresenceEvent)
        .where(PresenceEvent.visit_id == visit_id)
        .order_by(column("ctid").desc())
        .limit(1)
    )


# PUBLIC_INTERFACE
def record_gate_entry(
    database: Session,
    *,
    actor: UserAccount,
    gate_event: GateEvent,
) -> PresenceEvent:
    """Persist an entry event after a backend-authoritative granted gate decision.

    Args:
        database: Active SQLAlchemy transaction shared with gate evaluation.
        actor: Authorized gate operator who completed the evaluation.
        gate_event: Newly persisted grant associated with a visit and person.

    Returns:
        The immutable entry occupancy event linked to the gate decision.

    Raises:
        ValueError: If the gate event is not a complete granted access decision.
    """

    if (
        gate_event.decision is not GateDecision.GRANT
        or gate_event.visit_id is None
        or gate_event.person_id is None
    ):
        raise ValueError("Only a complete granted gate event can create presence.")

    entry = PresenceEvent(
        id=uuid.uuid4(),
        visit_id=gate_event.visit_id,
        person_id=gate_event.person_id,
        site_id=gate_event.requested_site_id,
        gate_event_id=gate_event.id,
        recorded_by_id=actor.id,
        event_type=PresenceEventType.ENTRY,
        occurred_at=gate_event.occurred_at,
    )
    database.add(entry)
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="presence.entered",
        entity_type="presence_event",
        entity_id=str(entry.id),
        reason="A backend-authoritative gate grant recorded site entry.",
        details={
            "gate_event_id": str(gate_event.id),
            "visit_id": str(entry.visit_id),
            "person_id": str(entry.person_id),
            "site_id": str(entry.site_id),
            "synthetic": True,
        },
    )
    return entry


# PUBLIC_INTERFACE
def record_visit_exit(
    database: Session,
    *,
    actor: UserAccount,
    visit_id: uuid.UUID,
    occurred_at: datetime | None = None,
) -> PresenceEvent:
    """Record an authorized site exit for a visit with an outstanding entry.

    Args:
        database: Active SQLAlchemy transaction used for the append-only event.
        actor: Authorized gate operator recording the physical departure.
        visit_id: Visit whose most recent occupancy state is entered.
        occurred_at: Optional deterministic event instant for trusted callers.

    Returns:
        The immutable exit event that closes the latest recorded entry.

    Raises:
        WorkflowError: If the visit does not exist or has no outstanding entry.
    """

    visit = database.get(Visit, visit_id)
    if visit is None:
        raise WorkflowError(404, "The requested visit does not exist.")

    latest_event = _latest_presence_event(database, visit_id=visit_id)
    if latest_event is None or latest_event.event_type is PresenceEventType.EXIT:
        raise WorkflowError(
            409,
            "This visit has no current recorded entry to close.",
        )

    exit_event = PresenceEvent(
        id=uuid.uuid4(),
        visit_id=visit.id,
        person_id=visit.person_id,
        site_id=visit.site_id,
        gate_event_id=None,
        recorded_by_id=actor.id,
        event_type=PresenceEventType.EXIT,
        occurred_at=_utc_timestamp(occurred_at),
    )
    database.add(exit_event)
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="presence.exited",
        entity_type="presence_event",
        entity_id=str(exit_event.id),
        reason="A gate operator recorded the person's site exit.",
        details={
            "visit_id": str(exit_event.visit_id),
            "person_id": str(exit_event.person_id),
            "site_id": str(exit_event.site_id),
            "synthetic": True,
        },
    )
    return exit_event


# PUBLIC_INTERFACE
def list_current_presence(
    database: Session,
    *,
    site_id: uuid.UUID | None = None,
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """List people currently inferred to be present at one or all sites.

    Presence is a read-only projection of the latest immutable entry or exit
    event for visits eligible at the effective demo time. A grant records entry
    in the same transaction, while an authorized exit appends a separate event
    without changing gate history.

    Args:
        database: Request-scoped SQLAlchemy session used only for reads.
        site_id: Optional site UUID that narrows the projection.
        observed_at: Optional UTC observation instant for deterministic callers.

    Returns:
        Sanitized, deterministically ordered active-presence rows.
    """

    return _current_presence_rows(
        database,
        observed_at=_utc_timestamp(
            observed_at if observed_at is not None else get_effective_time(database)
        ),
        site_id=site_id,
    )


# PUBLIC_INTERFACE
def get_dashboard_snapshot(
    database: Session,
    *,
    observed_at: datetime | None = None,
    activity_hours: int = _DEFAULT_ACTIVITY_HOURS,
    recent_limit: int = _DEFAULT_RECENT_LIMIT,
) -> dict[str, Any]:
    """Build a backend-derived site-access dashboard snapshot.

    The snapshot combines active visit windows, current presence, immutable gate
    decisions, and explicit entry and exit records. It never exposes token
    values, token hashes, identity presentation references, or provider payloads.

    Args:
        database: Request-scoped SQLAlchemy session used only for reads.
        observed_at: Optional UTC observation instant for deterministic callers.
        activity_hours: Lookback window for operational activity.
        recent_limit: Maximum number of sanitized gate decisions to return.

    Returns:
        Aggregate totals, site counters, active presence, and recent decisions.
    """

    _validate_activity_options(
        activity_hours=activity_hours,
        recent_limit=recent_limit,
    )
    as_of = _utc_timestamp(
        observed_at if observed_at is not None else get_effective_time(database)
    )
    window_started_at = as_of - timedelta(hours=activity_hours)
    presence = _current_presence_rows(database, observed_at=as_of)

    sites = list(database.scalars(select(Site).order_by(Site.name, Site.id)).all())
    active_visits = list(
        database.scalars(
            select(Visit).where(
                Visit.status.in_((VisitStatus.PLANNED, VisitStatus.ACTIVE)),
                Visit.starts_at <= as_of,
                Visit.ends_at > as_of,
            )
        ).all()
    )
    recent_events = list(
        database.scalars(
            select(GateEvent)
            .where(
                GateEvent.occurred_at >= window_started_at,
                GateEvent.occurred_at <= as_of,
            )
            .order_by(GateEvent.occurred_at.desc(), GateEvent.id.desc())
        ).all()
    )
    recent_presence_events = list(
        database.scalars(
            select(PresenceEvent)
            .where(
                PresenceEvent.occurred_at >= window_started_at,
                PresenceEvent.occurred_at <= as_of,
            )
            .order_by(PresenceEvent.occurred_at.desc(), PresenceEvent.id.desc())
        ).all()
    )

    person_ids = {
        event.person_id for event in recent_events if event.person_id is not None
    }
    people_by_id = {
        person.id: person
        for person in database.scalars(
            select(Person).where(Person.id.in_(person_ids))
        ).all()
    }
    site_by_id = {site.id: site for site in sites}
    active_visit_counts = {site.id: 0 for site in sites}
    present_counts = {site.id: 0 for site in sites}
    grant_counts = {site.id: 0 for site in sites}
    denial_counts = {site.id: 0 for site in sites}
    entry_counts = {site.id: 0 for site in sites}
    exit_counts = {site.id: 0 for site in sites}

    entered_visit_ids = {row["visit_id"] for row in presence}
    for visit in active_visits:
        if visit.status is VisitStatus.PLANNED and visit.id not in entered_visit_ids:
            continue
        if visit.site_id in active_visit_counts:
            active_visit_counts[visit.site_id] += 1
    for row in presence:
        present_counts[row["site_id"]] = present_counts.get(row["site_id"], 0) + 1
    for event in recent_events:
        if event.requested_site_id not in site_by_id:
            continue
        if event.decision is GateDecision.GRANT:
            grant_counts[event.requested_site_id] += 1
        else:
            denial_counts[event.requested_site_id] += 1
    for event in recent_presence_events:
        if event.site_id not in site_by_id:
            continue
        if event.event_type is PresenceEventType.ENTRY:
            entry_counts[event.site_id] += 1
        else:
            exit_counts[event.site_id] += 1

    site_summaries = [
        {
            "site_id": site.id,
            "site_name": site.name,
            "country_code": site.country_code,
            "active_visit_count": active_visit_counts[site.id],
            "present_count": present_counts[site.id],
            "grant_count": grant_counts[site.id],
            "denial_count": denial_counts[site.id],
            "entry_count": entry_counts[site.id],
            "exit_count": exit_counts[site.id],
        }
        for site in sites
    ]

    recent_decisions = [
        {
            "gate_event_id": event.id,
            "occurred_at": event.occurred_at,
            "site_id": event.requested_site_id,
            "site_name": (
                site_by_id[event.requested_site_id].name
                if event.requested_site_id in site_by_id
                else None
            ),
            "visit_id": event.visit_id,
            "person_id": event.person_id,
            "person_name": _person_name(people_by_id.get(event.person_id)),
            "decision": event.decision.value,
            "reason_codes": event.reason_codes,
        }
        for event in recent_events[:recent_limit]
    ]

    return {
        "as_of": as_of,
        "activity_window_started_at": window_started_at,
        "activity_hours": activity_hours,
        "totals": {
            "site_count": len(sites),
            "active_visit_count": sum(active_visit_counts.values()),
            "present_count": len(presence),
            "grant_count": sum(grant_counts.values()),
            "denial_count": sum(denial_counts.values()),
            "entry_count": sum(entry_counts.values()),
            "exit_count": sum(exit_counts.values()),
        },
        "sites": site_summaries,
        "current_presence": presence,
        "recent_decisions": recent_decisions,
    }
