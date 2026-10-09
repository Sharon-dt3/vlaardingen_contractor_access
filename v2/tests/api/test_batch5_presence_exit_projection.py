"""Regression coverage for occupancy events and saved demo-time projections."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.models import Evidence, GateDecision, GateEvent, Person, Population, PresenceEvent, PresenceEventType, Site, Visit, VisitStatus
from app.services import batch5
from app.services.workflows import WorkflowError


DEMO_TIME = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
LIVE_TIME = DEMO_TIME - timedelta(hours=1)
EXIT_TIME = DEMO_TIME + timedelta(days=3)


class ScalarResult(list):
    """Model the scalar query result's iteration and all() interfaces."""

    def all(self) -> list:
        return list(self)


class PresenceDatabase:
    """Retain immutable events while answering the projection's ORM selects."""

    def __init__(self) -> None:
        self.site = SimpleNamespace(id=uuid.uuid4(), name="Test site", country_code="NL")
        self.person = SimpleNamespace(
            id=uuid.uuid4(), first_name="Test", last_name="Visitor", population=Population.VISITOR
        )
        self.visit = SimpleNamespace(
            id=uuid.uuid4(),
            person_id=self.person.id,
            site_id=self.site.id,
            starts_at=DEMO_TIME - timedelta(hours=2),
            ends_at=DEMO_TIME + timedelta(hours=2),
            status=VisitStatus.PLANNED,
        )
        self.grant = GateEvent(
            id=uuid.uuid4(),
            visit_id=self.visit.id,
            person_id=self.person.id,
            requested_site_id=self.site.id,
            decision=GateDecision.GRANT,
            occurred_at=LIVE_TIME,
        )
        self.events: list[PresenceEvent] = [
            PresenceEvent(
                id=uuid.uuid4(),
                visit_id=self.visit.id,
                person_id=self.person.id,
                site_id=self.site.id,
                gate_event_id=self.grant.id,
                recorded_by_id=uuid.uuid4(),
                event_type=PresenceEventType.ENTRY,
                occurred_at=LIVE_TIME,
            )
        ]

    def execute(self, statement: Any) -> Any:
        """Return eligible grant rows for the real ORM selection."""
        assert statement.column_descriptions[0]["entity"] is GateEvent
        return [(self.grant, self.visit, self.person, self.site)]

    def scalars(self, statement: Any) -> Any:
        """Apply SQL predicates to an in-memory SQLite-free event fixture."""
        entity = statement.column_descriptions[0]["entity"]
        if entity is Evidence:
            return ScalarResult()
        if entity is PresenceEvent:
            # The query must select all occupancy events for the eligible visit,
            # not just events occurring before the saved effective demo time.
            # PostgreSQL insertion order, not mixed event timestamps, selects
            # the latest recorded occupancy state.
            if "presence_events.visit_id IN" in str(statement):
                assert "presence_events.occurred_at <=" not in str(statement)
                assert "ctid DESC" in str(statement)
            return ScalarResult(reversed(self.events))
        if entity is Site:
            return SimpleNamespace(all=lambda: [self.site])
        if entity is Visit:
            return SimpleNamespace(all=lambda: [self.visit])
        if entity is GateEvent:
            return SimpleNamespace(all=lambda: [])
        if entity is Person:
            return SimpleNamespace(all=lambda: [])
        raise AssertionError(f"Unexpected projection query: {entity!r}")

    def get(self, entity: Any, record_id: uuid.UUID) -> Any:
        """Look up the visit or referenced gate decision."""
        if entity is Visit and record_id == self.visit.id:
            return self.visit
        if entity is GateEvent and record_id == self.grant.id:
            return self.grant
        return None

    def scalar(self, statement: Any) -> Any:
        """Resolve the latest occupancy event for the exit command."""
        assert statement.column_descriptions[0]["entity"] is PresenceEvent
        assert "ctid DESC" in str(statement)
        return self.events[-1] if self.events else None

    def add(self, event: PresenceEvent) -> None:
        """Append, rather than overwrite, the exit event."""
        self.events.append(event)

    def flush(self) -> None:
        """Accept the service's event flush without changing historical state."""


def test_exit_after_saved_demo_clock_removes_person_from_roster_and_dashboard(monkeypatch: Any) -> None:
    """A current physical exit closes presence without changing demo-time eligibility."""
    database = PresenceDatabase()
    actor = SimpleNamespace(id=uuid.uuid4())
    monkeypatch.setattr(batch5, "append_audit_event", lambda *_args, **_kwargs: None)

    assert len(batch5.list_current_presence(database, observed_at=DEMO_TIME)) == 1

    exit_event = batch5.record_visit_exit(
        database, actor=actor, visit_id=database.visit.id, occurred_at=EXIT_TIME
    )

    assert exit_event.event_type is PresenceEventType.EXIT
    assert exit_event.occurred_at == EXIT_TIME
    assert database.events[0].event_type is PresenceEventType.ENTRY
    assert database.grant.decision is GateDecision.GRANT
    assert database.visit.status is VisitStatus.PLANNED
    assert batch5.list_current_presence(database, observed_at=DEMO_TIME) == []

    snapshot = batch5.get_dashboard_snapshot(database, observed_at=DEMO_TIME)
    assert snapshot["current_presence"] == []
    assert snapshot["totals"]["present_count"] == 0
    assert snapshot["sites"][0]["present_count"] == 0


def test_future_dated_historical_entry_is_closed_by_later_recorded_exit(monkeypatch: Any) -> None:
    """Recording an exit closes even an entry dated later than the exit."""
    database = PresenceDatabase()
    actor = SimpleNamespace(id=uuid.uuid4())
    monkeypatch.setattr(batch5, "append_audit_event", lambda *_args, **_kwargs: None)
    database.events[0].occurred_at = EXIT_TIME + timedelta(days=1)

    assert len(batch5.list_current_presence(database, observed_at=DEMO_TIME)) == 1
    exit_event = batch5.record_visit_exit(
        database, actor=actor, visit_id=database.visit.id, occurred_at=EXIT_TIME
    )

    assert exit_event.occurred_at < database.events[0].occurred_at
    assert database.events == [database.events[0], exit_event]
    assert batch5.list_current_presence(database, observed_at=DEMO_TIME) == []
    snapshot = batch5.get_dashboard_snapshot(database, observed_at=DEMO_TIME)
    assert snapshot["current_presence"] == []
    assert snapshot["totals"]["present_count"] == 0
    assert snapshot["sites"][0]["present_count"] == 0
    with pytest.raises(WorkflowError) as error:
        batch5.record_visit_exit(database, actor=actor, visit_id=database.visit.id)
    assert error.value.status_code == 409
    assert len(database.events) == 2


def test_genuine_later_reentry_restores_presence_and_exit_eligibility(monkeypatch: Any) -> None:
    """A newly recorded entry reopens presence after an earlier recorded exit."""
    database = PresenceDatabase()
    actor = SimpleNamespace(id=uuid.uuid4())
    monkeypatch.setattr(batch5, "append_audit_event", lambda *_args, **_kwargs: None)
    database.events[0].occurred_at = EXIT_TIME + timedelta(days=1)
    batch5.record_visit_exit(
        database, actor=actor, visit_id=database.visit.id, occurred_at=EXIT_TIME
    )

    reentry_gate = GateEvent(
        id=uuid.uuid4(),
        visit_id=database.visit.id,
        person_id=database.person.id,
        requested_site_id=database.site.id,
        decision=GateDecision.GRANT,
        occurred_at=EXIT_TIME - timedelta(hours=1),
    )
    database.grant = reentry_gate
    reentry = batch5.record_gate_entry(
        database, actor=actor, gate_event=reentry_gate
    )

    assert reentry.event_type is PresenceEventType.ENTRY
    assert reentry.occurred_at < database.events[1].occurred_at
    rows = batch5.list_current_presence(database, observed_at=DEMO_TIME)
    assert len(rows) == 1
    assert rows[0]["presence_event_id"] == reentry.id
    assert rows[0]["gate_event_id"] == reentry_gate.id
    assert batch5.get_dashboard_snapshot(database, observed_at=DEMO_TIME)["totals"]["present_count"] == 1

    second_exit = batch5.record_visit_exit(
        database, actor=actor, visit_id=database.visit.id, occurred_at=EXIT_TIME
    )
    assert second_exit.event_type is PresenceEventType.EXIT
    assert batch5.list_current_presence(database, observed_at=DEMO_TIME) == []
