"""Focused automated coverage for the Batch 6 expiry and re-validation lifecycle."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.models import (
    BlacklistEntry,
    ComplianceRequirement,
    ComplianceRequirementKind,
    DemoClock,
    Evidence,
    EvidenceStatus,
    EvidenceType,
    ExpiryAlert,
    ExpirySubjectKind,
    RevalidationTask,
    RevalidationTaskStatus,
)
from app.services import WorkflowError
from app.services import batch3, batch6


UTC = timezone.utc
EFFECTIVE_AT = datetime(2026, 9, 22, 12, tzinfo=UTC)


class _ScalarList:
    """Small SQLAlchemy scalar-result substitute used by isolated service tests."""

    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        """Return the configured scalar values."""

        return self._values


class _ExpiryProcessingSession:
    """In-memory persistence seam for expiry alert and task idempotency tests."""

    def __init__(self) -> None:
        self.alerts: list[ExpiryAlert] = []
        self.tasks: list[RevalidationTask] = []

    def scalar(self, statement: Any) -> ExpiryAlert | RevalidationTask | None:
        """Return the sole existing alert or task for the selected model."""

        entity = statement.column_descriptions[0]["entity"]
        if entity is ExpiryAlert:
            return self.alerts[0] if self.alerts else None
        if entity is RevalidationTask:
            return self.tasks[0] if self.tasks else None
        raise AssertionError(f"Unexpected scalar query for {entity!r}.")

    def add(self, entity: Any) -> None:
        """Persist newly created domain state in the matching collection."""

        if isinstance(entity, ExpiryAlert):
            self.alerts.append(entity)
        elif isinstance(entity, RevalidationTask):
            self.tasks.append(entity)

    def flush(self) -> None:
        """Match the SQLAlchemy unit-of-work flush interface."""

        return None


class _ComplianceSession:
    """Minimal query-backed session for exercising Batch 3's real evaluator."""

    def __init__(
        self,
        *,
        visit: Any,
        person: Any,
        requirement: Any,
        evidence: Any,
    ) -> None:
        self._visit = visit
        self._person = person
        self._requirement = requirement
        self.evidence = evidence

    def get(self, model: type[Any], _: Any) -> Any:
        """Return the configured visit or person required by compliance evaluation."""

        if model.__name__ == "Visit":
            return self._visit
        if model.__name__ == "Person":
            return self._person
        raise AssertionError(f"Unexpected get query for {model!r}.")

    def scalar(self, statement: Any) -> Any:
        """Answer the evaluator's blacklist and verified-evidence queries."""

        entity = statement.column_descriptions[0]["entity"]
        if entity is BlacklistEntry:
            return None
        if entity is Evidence:
            return self.evidence
        raise AssertionError(f"Unexpected scalar query for {entity!r}.")

    def scalars(self, statement: Any) -> _ScalarList:
        """Answer the evaluator's active-requirements query."""

        entity = statement.column_descriptions[0]["entity"]
        if entity is ComplianceRequirement:
            return _ScalarList([self._requirement])
        raise AssertionError(f"Unexpected scalars query for {entity!r}.")


class _TaskCompletionSession:
    """Minimal persistence seam for task completion and live compliance recording."""

    def __init__(self, *, task: Any, requirement: Any, visit: Any) -> None:
        self.task = task
        self.requirement = requirement
        self.visit = visit

    def get(self, model: type[Any], _: Any) -> Any:
        """Return the task and its configured requirement."""

        if model is DemoClock:
            return None
        if model is RevalidationTask:
            return self.task
        if model is ComplianceRequirement:
            return self.requirement
        raise AssertionError(f"Unexpected get query for {model!r}.")

    def scalars(self, _: Any) -> _ScalarList:
        """Return the active visit whose eligibility must be recalculated."""

        return _ScalarList([self.visit])


def _expired_evidence_fixture() -> tuple[Any, Any, Any, Any]:
    """Create the minimum real-domain shape for one evidence requirement."""

    site_id = "site-1"
    person_id = "person-1"
    visit = SimpleNamespace(id="visit-1", site_id=site_id, person_id=person_id)
    person = SimpleNamespace(
        id=person_id,
        company_id=None,
        population="maintenance_contractor",
    )
    requirement = SimpleNamespace(
        id="requirement-1",
        site_id=site_id,
        code="ID_CARD",
        label="Verified ID card",
        requirement_kind=ComplianceRequirementKind.EVIDENCE,
        evidence_type=EvidenceType.ID_CARD,
        is_active=True,
        is_blocking=True,
    )
    evidence = SimpleNamespace(
        id="expired-evidence",
        person_id=person_id,
        evidence_type=EvidenceType.ID_CARD,
        status=EvidenceStatus.VERIFIED,
        expiry_date=date(2026, 9, 21),
        updated_at=EFFECTIVE_AT,
    )
    return visit, person, requirement, evidence


def test_expired_verified_evidence_blocks_and_verified_renewal_restores_compliance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch 3 evaluates Batch 6 effective time instead of frontend eligibility."""

    visit, person, requirement, evidence = _expired_evidence_fixture()
    session = _ComplianceSession(
        visit=visit,
        person=person,
        requirement=requirement,
        evidence=evidence,
    )
    monkeypatch.setattr(batch3, "current_demo_time", lambda _: EFFECTIVE_AT)

    expired = batch3.evaluate_visit_compliance(session, visit_id=visit.id)

    assert expired["eligible"] is False
    assert expired["checks"] == [
        {
            "code": "ID_CARD",
            "label": "Verified ID card",
            "kind": "evidence",
            "status": "expired",
            "blocking": True,
            "detail": "The required verified evidence has expired.",
            "requirement_id": "requirement-1",
        }
    ]

    session.evidence = SimpleNamespace(
        id="renewed-evidence",
        person_id=person.id,
        evidence_type=EvidenceType.ID_CARD,
        status=EvidenceStatus.VERIFIED,
        expiry_date=date(2027, 9, 22),
        updated_at=EFFECTIVE_AT,
    )

    restored = batch3.evaluate_visit_compliance(session, visit_id=visit.id)

    assert restored["eligible"] is True
    assert restored["checks"][0]["status"] == "passed"
    assert restored["checks"][0]["blocking"] is False


def test_token_issuance_records_live_time_but_validates_expiry_at_demo_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A future demo clock must not become the token's issuance audit timestamp."""

    from app.models import AccessToken, Approval

    live_at = datetime(2026, 9, 29, 12, tzinfo=UTC)
    demo_at = live_at + timedelta(days=3)
    visit = SimpleNamespace(
        id="visit-1", starts_at=demo_at - timedelta(hours=1), ends_at=demo_at + timedelta(hours=2)
    )
    actor = SimpleNamespace(id="manager-1")

    class _TokenSession:
        """Capture the issued token behind the service's persistence seam."""

        def __init__(self) -> None:
            self.token: AccessToken | None = None

        def get(self, model: type[Any], _: Any) -> Any:
            """Return the visit requested by the issuance command."""

            assert model.__name__ == "Visit"
            return visit

        def scalar(self, statement: Any) -> Any:
            """Provide an approval and no existing active token."""

            entity = statement.column_descriptions[0]["entity"]
            if entity is Approval:
                return SimpleNamespace(id="approval-1")
            assert entity is AccessToken
            return None

        def add(self, entity: Any) -> None:
            """Capture the token without altering any persistent records."""

            assert isinstance(entity, AccessToken)
            self.token = entity

        def flush(self) -> None:
            """Match the SQLAlchemy session flush boundary."""

            return None

    session = _TokenSession()
    monkeypatch.setattr(batch3, "evaluate_visit_compliance", lambda *_args, **_kwargs: {"eligible": True})
    monkeypatch.setattr(batch3, "current_demo_time", lambda _: demo_at)
    monkeypatch.setattr(batch3, "_now", lambda: live_at)
    monkeypatch.setattr(batch3, "append_audit_event", lambda *_args, **_kwargs: None)

    with pytest.raises(WorkflowError, match="Token expiry must be in the future"):
        batch3.issue_access_token(
            session,
            actor=actor,
            visit_id=visit.id,
            requested_expiry=live_at + timedelta(hours=1),
        )
    assert session.token is None

    token, reference = batch3.issue_access_token(
        session,
        actor=actor,
        visit_id=visit.id,
        requested_expiry=None,
    )

    assert token is session.token
    assert token.issued_at == live_at
    assert token.expires_at == visit.ends_at
    assert reference.startswith("renewi-access:")


def test_process_expiry_persists_failed_delivery_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry state remains durable when local notification delivery fails."""

    _, person, requirement, evidence = _expired_evidence_fixture()
    session = _ExpiryProcessingSession()
    actor = SimpleNamespace(id="manager-1")
    audit_actions: list[str] = []
    live_at = EFFECTIVE_AT - timedelta(days=2)

    class _FailingProvider:
        """Notification boundary that simulates an optional delivery outage."""

        def deliver(self, **_: Any) -> None:
            """Raise after the alert has been persisted."""

            raise RuntimeError("notification transport unavailable")

    monkeypatch.setattr(batch6, "get_effective_time", lambda _: EFFECTIVE_AT)
    monkeypatch.setattr(batch6, "_utc_now", lambda: live_at)
    monkeypatch.setattr(
        batch6,
        "_requirement_subjects",
        lambda _, **_kwargs: [(requirement, person)],
    )
    monkeypatch.setattr(
        batch6,
        "_source_for_requirement",
        lambda *_args, **_kwargs: (
            ExpirySubjectKind.EVIDENCE,
            evidence.id,
            datetime(2026, 9, 22, tzinfo=UTC),
        ),
    )
    monkeypatch.setattr(batch6, "get_notification_provider", _FailingProvider)
    monkeypatch.setattr(
        batch6,
        "append_audit_event",
        lambda _db, **event: audit_actions.append(event["action"]),
    )

    first_pass = batch6.process_expiry(session, actor=actor)
    second_pass = batch6.process_expiry(session, actor=actor)

    assert first_pass == {
        "processed_at": EFFECTIVE_AT,
        "created_alert_count": 1,
        "created_task_count": 1,
        "existing_alert_count": 0,
        "existing_task_count": 0,
    }
    assert second_pass == {
        "processed_at": EFFECTIVE_AT,
        "created_alert_count": 0,
        "created_task_count": 0,
        "existing_alert_count": 1,
        "existing_task_count": 1,
    }
    assert len(session.alerts) == 1
    assert session.alerts[0].alert_code == "EXPIRED"
    assert session.alerts[0].created_at == live_at
    assert session.alerts[0].delivery_status == "FAILED"
    assert len(session.tasks) == 1
    assert session.tasks[0].created_at == live_at
    assert session.tasks[0].status is RevalidationTaskStatus.OPEN
    assert audit_actions == ["expiry.alert_created", "revalidation.task_created"]


def test_complete_revalidation_rejects_task_without_verified_current_renewal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completion cannot be used as a frontend override for expired compliance."""

    task = SimpleNamespace(
        id="task-1",
        status=RevalidationTaskStatus.OPEN,
        requirement_id="requirement-1",
        person_id="person-1",
        site_id="site-1",
    )
    session = _TaskCompletionSession(
        task=task,
        requirement=SimpleNamespace(id="requirement-1"),
        visit=SimpleNamespace(id="visit-1"),
    )

    monkeypatch.setattr(batch6, "_task_renewed", lambda *_args, **_kwargs: False)

    with pytest.raises(
        WorkflowError,
        match="verified current renewal is required",
    ) as error:
        batch6.complete_revalidation_task(
            session,
            actor=SimpleNamespace(id="manager-1"),
            task_id=task.id,
        )

    assert error.value.status_code == 409
    assert task.status is RevalidationTaskStatus.OPEN


def test_complete_revalidation_records_live_authoritative_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task completion recalculates backend compliance after a verified renewal."""

    task = SimpleNamespace(
        id="task-1",
        status=RevalidationTaskStatus.OPEN,
        requirement_id="requirement-1",
        person_id="person-1",
        site_id="site-1",
        completed_at=None,
        completed_by_id=None,
    )
    visit = SimpleNamespace(id="visit-1")
    session = _TaskCompletionSession(
        task=task,
        requirement=SimpleNamespace(id="requirement-1"),
        visit=visit,
    )
    audit_events: list[dict[str, Any]] = []
    evaluated_visit_ids: list[str] = []
    live_at = EFFECTIVE_AT - timedelta(days=2)

    def _evaluate_live_compliance(_: Any, *, visit_id: str) -> dict[str, bool]:
        """Represent Batch 3's protected live compliance evaluation boundary."""

        evaluated_visit_ids.append(visit_id)
        return {"eligible": True}

    monkeypatch.setattr(batch6, "_task_renewed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(batch6, "get_effective_time", lambda _: EFFECTIVE_AT)
    monkeypatch.setattr(batch6, "_utc_now", lambda: live_at)
    from app.services import batch5

    monkeypatch.setattr(
        batch5,
        "list_current_presence",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(batch3, "evaluate_visit_compliance", _evaluate_live_compliance)
    monkeypatch.setattr(
        batch6,
        "append_audit_event",
        lambda _db, **event: audit_events.append(event),
    )

    completed = batch6.complete_revalidation_task(
        session,
        actor=SimpleNamespace(id="manager-1"),
        task_id=task.id,
    )

    assert completed is task
    assert task.status is RevalidationTaskStatus.COMPLETED
    assert task.completed_at == live_at
    assert task.completed_by_id == "manager-1"
    assert evaluated_visit_ids == ["visit-1"]
    assert audit_events[0]["action"] == "revalidation.task_completed"
    assert audit_events[0]["details"]["eligibility_by_visit"] == {"visit-1": True}
