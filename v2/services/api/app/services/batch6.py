"""Authoritative Batch 6 demo-time, expiry, and re-validation commands."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    ComplianceRequirement,
    ComplianceRequirementKind,
    DemoClock,
    Evidence,
    EvidenceStatus,
    EvidenceType,
    ExpiryAlert,
    ExpirySubjectKind,
    Invitation,
    Person,
    Population,
    PresenceEvent,
    PresenceEventType,
    RevalidationTask,
    RevalidationTaskStatus,
    TrainingOutcome,
    TrainingResult,
    UserAccount,
    Visit,
    VisitStatus,
)
from app.providers import get_notification_provider
from app.providers.storage import lock_private_reference
from app.schemas.batch6 import OnSiteIdRenewalSubmission, OnSiteRenewalSubmission
from app.services.audit import append_audit_event
from app.services.workflows import WorkflowError

_RENEWAL_WINDOWS = frozenset({30, 14, 7})
_DRIVER_POPULATIONS = frozenset({
    Population.RENEWI_DRIVER,
    Population.TEMPORARY_DRIVER,
    Population.EXTERNAL_DRIVER,
})


def _utc_now() -> datetime:
    """Return the host UTC instant used when no persisted demo clock exists."""

    return datetime.now(timezone.utc)


def _normalise_utc(value: datetime) -> datetime:
    """Normalize a persisted timezone-aware instant to UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _source_for_requirement(
    database: Session,
    *,
    requirement: ComplianceRequirement,
    person_id: uuid.UUID,
) -> tuple[ExpirySubjectKind, uuid.UUID, datetime] | None:
    """Return the latest monitored expiring source for one applicable requirement."""

    if requirement.requirement_kind is ComplianceRequirementKind.EVIDENCE:
        assert requirement.evidence_type is not None
        evidence = database.scalar(
            select(Evidence)
            .where(
                Evidence.person_id == person_id,
                Evidence.evidence_type == requirement.evidence_type,
                Evidence.status == EvidenceStatus.VERIFIED,
            )
            .order_by(Evidence.updated_at.desc(), Evidence.id.desc())
            .limit(1)
        )
        if evidence is None or evidence.expiry_date is None:
            return None
        expires_at = datetime.combine(
            evidence.expiry_date + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        return (ExpirySubjectKind.EVIDENCE, evidence.id, expires_at)

    if requirement.requirement_kind is ComplianceRequirementKind.LIFE_SAVING_RULES:
        # A confirmation does not expire on a date; it is replaced when new rules are published.
        return None

    assert requirement.training_module_id is not None
    result = database.scalar(
        select(TrainingResult)
        .where(
            TrainingResult.person_id == person_id,
            TrainingResult.training_module_id == requirement.training_module_id,
        )
        .order_by(
            TrainingResult.completed_at.desc(),
            TrainingResult.attempt_number.desc(),
        )
        .limit(1)
    )
    if result is None or result.expires_at is None:
        return None
    return (
        ExpirySubjectKind.TRAINING,
        result.id,
        _normalise_utc(result.expires_at),
    )


def _alert_code(
    *,
    source_kind: ExpirySubjectKind,
    expires_at: datetime,
    effective_at: datetime,
) -> str | None:
    """Return the applicable warning or expiry code for one expiring source."""

    if source_kind is ExpirySubjectKind.EVIDENCE:
        expires_on: date = (expires_at - timedelta(days=1)).date()
        days_until_expiry = (expires_on - effective_at.date()).days
        expired = days_until_expiry < 0
    else:
        days_until_expiry = (expires_at.date() - effective_at.date()).days
        expired = expires_at <= effective_at

    if expired:
        return "EXPIRED"
    if days_until_expiry in _RENEWAL_WINDOWS:
        return f"DUE_{days_until_expiry}D"
    return None


def _requirement_subjects(
    database: Session,
    *,
    effective_at: datetime,
) -> list[tuple[ComplianceRequirement, Person]]:
    """Return requirements for active visits and entered, current planned visits."""

    # Presence is determined by the same backend projection used by the dashboard.
    # A gate grant records entry without changing the visit's PLANNED status.
    from app.services.batch5 import list_current_presence

    entered_visit_ids = {
        row["visit_id"]
        for row in list_current_presence(database, observed_at=effective_at)
    }

    rows = database.execute(
        select(ComplianceRequirement, Person)
        .join(Visit, Visit.site_id == ComplianceRequirement.site_id)
        .join(Person, Person.id == Visit.person_id)
        .where(
            ComplianceRequirement.is_active.is_(True),
            # VCA is no longer required; retain existing records for audit.
            or_(
                ComplianceRequirement.evidence_type.is_(None),
                ComplianceRequirement.evidence_type != EvidenceType.VCA_CERTIFICATE,
            ),
            or_(
                Visit.status == VisitStatus.ACTIVE,
                Visit.id.in_(entered_visit_ids),
            ),
            or_(
                ComplianceRequirement.population.is_(None),
                ComplianceRequirement.population == Person.population,
            ),
        )
        .order_by(ComplianceRequirement.id, Person.id)
    ).all()
    subjects: dict[tuple[uuid.UUID, uuid.UUID], tuple[ComplianceRequirement, Person]] = {}
    for requirement, person in rows:
        subjects.setdefault((requirement.id, person.id), (requirement, person))
    return list(subjects.values())


def _task_renewed(
    database: Session,
    *,
    task: RevalidationTask,
    effective_at: datetime,
) -> bool:
    """Return whether the task's configured requirement has a current renewal."""

    requirement = database.get(ComplianceRequirement, task.requirement_id)
    if requirement is None:
        return False
    if requirement.evidence_type is EvidenceType.VCA_CERTIFICATE:
        return False
    source = _source_for_requirement(
        database,
        requirement=requirement,
        person_id=task.person_id,
    )
    if source is None:
        return False

    source_kind, source_id, expires_at = source
    if source_id == task.source_id:
        return False
    if source_kind is ExpirySubjectKind.EVIDENCE:
        return (expires_at - timedelta(days=1)).date() >= effective_at.date()
    return expires_at > effective_at


# PUBLIC_INTERFACE
def current_demo_time(database: Session) -> datetime | None:
    """Return the persisted effective demo time, or None before clock initialization."""

    clock = database.get(DemoClock, 1)
    return _normalise_utc(clock.effective_at) if clock is not None else None


# PUBLIC_INTERFACE
def get_effective_time(database: Session) -> datetime:
    """Return the persisted effective time or current UTC before the first clock command."""

    return current_demo_time(database) or _utc_now()


# PUBLIC_INTERFACE
def advance_demo_clock(
    database: Session,
    *,
    actor: UserAccount,
    days: int,
) -> DemoClock:
    """Advance the singleton demo clock by an approved deterministic interval.

    Args:
        database: Active SQLAlchemy transaction.
        actor: Privileged account operating the deterministic demo timeline.
        days: One of the documented advancement intervals: 7, 14, or 30.

    Returns:
        The persisted singleton clock after advancement.

    Raises:
        WorkflowError: If the requested interval is not an approved demo interval.
    """

    if days not in _RENEWAL_WINDOWS:
        raise WorkflowError(422, "Demo clock advancement must be 7, 14, or 30 days.")

    now = _utc_now()
    clock = database.get(DemoClock, 1)
    if clock is None:
        clock = DemoClock(
            id=1,
            effective_at=now + timedelta(days=days),
            updated_at=now,
            updated_by_id=actor.id,
        )
        database.add(clock)
    else:
        clock.effective_at = _normalise_utc(clock.effective_at) + timedelta(days=days)
        clock.updated_at = now
        clock.updated_by_id = actor.id

    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="demo_clock.advanced",
        entity_type="demo_clock",
        entity_id="1",
        reason=f"Advanced the persisted demo clock by {days} days.",
        details={
            "days": days,
            "effective_at": _normalise_utc(clock.effective_at).isoformat(),
            "synthetic": True,
        },
    )
    return clock


# PUBLIC_INTERFACE
def process_expiry(
    database: Session,
    *,
    actor: UserAccount,
) -> dict[str, Any]:
    """Create idempotent expiry alerts and re-validation tasks for active visits.

    Durable alerts and tasks are created before optional notification delivery.
    The local notification result is recorded on the alert, but delivery failures
    never block expiry state, compliance evaluation, or later renewal.

    Args:
        database: Active SQLAlchemy transaction.
        actor: Privileged account or deterministic processor invoking the pass.

    Returns:
        Counts showing newly created and already-existing alert/task records.
    """

    effective_at = get_effective_time(database)
    created_alert_count = 0
    created_task_count = 0
    existing_alert_count = 0
    existing_task_count = 0

    for requirement, person in _requirement_subjects(database, effective_at=effective_at):
        source = _source_for_requirement(
            database,
            requirement=requirement,
            person_id=person.id,
        )
        if source is None:
            continue

        source_kind, source_id, expires_at = source
        alert_code = _alert_code(
            source_kind=source_kind,
            expires_at=expires_at,
            effective_at=effective_at,
        )
        if alert_code is None:
            continue

        alert = database.scalar(
            select(ExpiryAlert).where(
                ExpiryAlert.source_kind == source_kind,
                ExpiryAlert.source_id == source_id,
                ExpiryAlert.alert_code == alert_code,
            )
        )
        if alert is None:
            alert = ExpiryAlert(
                id=uuid.uuid4(),
                person_id=person.id,
                site_id=requirement.site_id,
                requirement_id=requirement.id,
                source_kind=source_kind,
                source_id=source_id,
                alert_code=alert_code,
                expires_at=expires_at,
                delivery_mode="IN_APP",
                delivery_status="PENDING",
                provider_reference=None,
                created_at=_utc_now(),
                created_by_id=actor.id,
            )
            database.add(alert)
            database.flush()
            created_alert_count += 1

            try:
                delivery = get_notification_provider().deliver(
                    template_key=f"expiry.{alert_code.lower()}",
                    recipient_reference=str(person.id),
                    payload={
                        "alert_id": str(alert.id),
                        "person_id": str(person.id),
                        "requirement_code": requirement.code,
                        "expires_at": expires_at.isoformat(),
                    },
                    idempotency_key=str(alert.id),
                )
                alert.delivery_mode = delivery.mode
                alert.delivery_status = delivery.status
                alert.provider_reference = delivery.provider_reference
            except Exception:
                alert.delivery_status = "FAILED"

            append_audit_event(
                database,
                actor=actor,
                action="expiry.alert_created",
                entity_type="expiry_alert",
                entity_id=str(alert.id),
                reason=(
                    f"{requirement.label} is {alert_code.lower().replace('_', ' ')} "
                    "for an active visit participant."
                ),
                details={
                    "person_id": str(person.id),
                    "requirement_id": str(requirement.id),
                    "source_kind": source_kind.value,
                    "source_id": str(source_id),
                    "alert_code": alert_code,
                    "synthetic": True,
                },
            )
        else:
            existing_alert_count += 1

        if alert_code != "EXPIRED":
            continue

        task = database.scalar(
            select(RevalidationTask).where(
                RevalidationTask.person_id == person.id,
                RevalidationTask.requirement_id == requirement.id,
                RevalidationTask.source_kind == source_kind,
                RevalidationTask.source_id == source_id,
            )
        )
        if task is not None:
            existing_task_count += 1
            continue

        task = RevalidationTask(
            id=uuid.uuid4(),
            person_id=person.id,
            site_id=requirement.site_id,
            requirement_id=requirement.id,
            source_kind=source_kind,
            source_id=source_id,
            status=RevalidationTaskStatus.OPEN,
            created_at=_utc_now(),
            completed_at=None,
            completed_by_id=None,
        )
        database.add(task)
        database.flush()
        created_task_count += 1
        append_audit_event(
            database,
            actor=actor,
            action="revalidation.task_created",
            entity_type="revalidation_task",
            entity_id=str(task.id),
            reason="Expired required evidence or training requires re-validation.",
            details={
                "person_id": str(person.id),
                "requirement_id": str(requirement.id),
                "source_kind": source_kind.value,
                "source_id": str(source_id),
                "synthetic": True,
            },
        )

    return {
        "processed_at": effective_at,
        "created_alert_count": created_alert_count,
        "created_task_count": created_task_count,
        "existing_alert_count": existing_alert_count,
        "existing_task_count": existing_task_count,
    }


# PUBLIC_INTERFACE
def list_expiry_alerts(
    database: Session,
    *,
    person_id: uuid.UUID | None = None,
) -> list[ExpiryAlert]:
    """List persisted expiry alerts newest first, optionally for one person."""

    statement = select(ExpiryAlert).order_by(
        ExpiryAlert.created_at.desc(),
        ExpiryAlert.id.desc(),
    )
    if person_id is not None:
        statement = statement.where(ExpiryAlert.person_id == person_id)
    return list(database.scalars(statement).all())


# PUBLIC_INTERFACE
def list_revalidation_tasks(
    database: Session,
    *,
    person_id: uuid.UUID | None = None,
    status: RevalidationTaskStatus | None = None,
) -> list[RevalidationTask]:
    """List persisted re-validation tasks in stable actionable order."""

    statement = select(RevalidationTask).order_by(
        RevalidationTask.status.asc(),
        RevalidationTask.created_at.desc(),
        RevalidationTask.id.desc(),
    )
    if person_id is not None:
        statement = statement.where(RevalidationTask.person_id == person_id)
    if status is not None:
        statement = statement.where(RevalidationTask.status == status)
    return list(database.scalars(statement).all())


# PUBLIC_INTERFACE
def submit_on_site_renewal(
    database: Session,
    *,
    actor: UserAccount,
    task_id: uuid.UUID,
    payload: OnSiteRenewalSubmission,
) -> Evidence:
    """Submit proposed evidence expiry for an on-site person, pending human review.

    Args:
        database: Request-scoped transaction.
        actor: Account authorized to write expiry workflows.
        task_id: Open evidence re-validation task identifier.
        payload: Selected person, expired source, and proposed expiry date.

    Returns:
        New, unverified evidence metadata referencing the previous source.

    Raises:
        WorkflowError: If the task, source, presence, or expiry is invalid.
    """

    # Lock the task to prevent two concurrent submissions against the same
    # expired source from creating competing pending renewals.
    task = database.scalar(
        select(RevalidationTask)
        .where(RevalidationTask.id == task_id)
        .with_for_update()
    )
    if task is None:
        raise WorkflowError(404, "Re-validation task not found.")
    if task.status is not RevalidationTaskStatus.OPEN:
        raise WorkflowError(409, "Only an open re-validation task can receive a renewal.")
    if task.person_id != payload.person_id or task.source_id != payload.source_id:
        raise WorkflowError(409, "The selected person or expired source does not match this task.")
    if task.source_kind is not ExpirySubjectKind.EVIDENCE:
        raise WorkflowError(422, "Training renewal must use the scored training workflow.")

    requirement = database.get(ComplianceRequirement, task.requirement_id)
    previous = database.get(Evidence, task.source_id)
    if (
        requirement is None
        or not requirement.is_active
        or requirement.requirement_kind is not ComplianceRequirementKind.EVIDENCE
        or requirement.site_id != task.site_id
        or requirement.evidence_type is None
        or requirement.evidence_type is EvidenceType.VCA_CERTIFICATE
        or previous is None
        or previous.person_id != task.person_id
        or previous.evidence_type is not requirement.evidence_type
        or previous.status is not EvidenceStatus.VERIFIED
    ):
        raise WorkflowError(409, "This task no longer has a renewable evidence source.")

    effective_at = get_effective_time(database)
    if payload.expiry_date <= effective_at.date():
        raise WorkflowError(422, "Choose an expiry date after the effective current date.")

    from app.services.batch5 import list_current_presence

    if not any(
        row["person_id"] == task.person_id and row["site_id"] == task.site_id
        for row in list_current_presence(database, site_id=task.site_id, observed_at=effective_at)
    ):
        raise WorkflowError(409, "The selected person is no longer on site.")

    # Do not manufacture a document or claim that an old document acquired a
    # new expiry. The reviewable submission has its own record, retains the
    # private prior document reference, and explicitly identifies its origin.
    if not previous.storage_reference or not previous.content_sha256:
        raise WorkflowError(409, "The previous evidence has no private document to review.")
    if database.scalar(
        select(Evidence.id)
        .where(
            Evidence.person_id == task.person_id,
            Evidence.supersedes_id == previous.id,
            Evidence.status.in_((EvidenceStatus.UPLOADED, EvidenceStatus.EXTRACTED)),
        )
        .limit(1)
    ) is not None:
        raise WorkflowError(409, "A renewal for this source is already awaiting review.")

    # Reused bytes still need the same transaction lock as fresh uploads.
    lock_private_reference(database, previous.storage_reference)
    now = _utc_now()
    evidence = Evidence(
        id=uuid.uuid4(),
        person_id=task.person_id,
        invitation_id=previous.invitation_id,
        asset_id=None,
        evidence_type=previous.evidence_type,
        status=EvidenceStatus.UPLOADED,
        filename=previous.filename,
        media_type=previous.media_type,
        size_bytes=previous.size_bytes,
        content_sha256=previous.content_sha256,
        storage_reference=previous.storage_reference,
        storage_mode=previous.storage_mode,
        provider_mode="PENDING",
        extracted_fields={},
        field_confidence={},
        validity_assessment={
            "source": "on_site_renewal_request",
            "document_reused": True,
            "expiry_unverified": True,
        },
        issue_date=None,
        expiry_date=payload.expiry_date,
        review_notes="Proposed expiry; the referenced document and date require authorized review.",
        supersedes_id=previous.id,
        uploaded_by_id=actor.id,
        reviewed_by_id=None,
        created_at=now,
        updated_at=now,
    )
    database.add(evidence)
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="revalidation.renewal_submitted",
        entity_type="evidence",
        entity_id=str(evidence.id),
        reason="An on-site evidence renewal was submitted for authorized review.",
        details={
            "task_id": str(task.id),
            "person_id": str(task.person_id),
            "site_id": str(task.site_id),
            "source_id": str(previous.id),
            "proposed_expiry_date": payload.expiry_date.isoformat(),
            "status": evidence.status.value,
        },
    )
    return evidence


# PUBLIC_INTERFACE
def submit_on_site_id_renewal(
    database: Session,
    *,
    actor: UserAccount,
    payload: OnSiteIdRenewalSubmission,
) -> Evidence:
    """Submit an on-site non-driver ID date for review without altering eligibility.

    Args:
        database: Request-scoped transaction.
        actor: Account authorized for expiry submissions.
        payload: Selected on-site person, current verified ID, and proposed date.

    Returns:
        New uploaded evidence awaiting independent authorized verification.

    Raises:
        WorkflowError: If presence, population, source, or proposed date is invalid.
    """

    person = database.get(Person, payload.person_id)
    if person is None:
        raise WorkflowError(404, "Selected person not found.")
    if person.population in _DRIVER_POPULATIONS:
        raise WorkflowError(422, "Driver identity documents cannot be renewed here.")

    from app.services.batch5 import list_current_presence

    effective_at = get_effective_time(database)
    if not any(
        row["person_id"] == person.id
        for row in list_current_presence(database, observed_at=effective_at)
    ):
        raise WorkflowError(409, "The selected person is no longer on site.")

    # Lock the source so concurrent submissions cannot race the source check.
    previous = database.scalar(
        select(Evidence)
        .where(Evidence.id == payload.source_id)
        .with_for_update()
    )
    if (
        previous is None
        or previous.person_id != person.id
        or previous.evidence_type is not EvidenceType.ID_CARD
        or previous.status is not EvidenceStatus.VERIFIED
    ):
        raise WorkflowError(409, "The selected ID is not verified for this person.")
    latest = database.scalar(
        select(Evidence)
        .where(
            Evidence.person_id == person.id,
            Evidence.evidence_type == EvidenceType.ID_CARD,
            Evidence.status == EvidenceStatus.VERIFIED,
        )
        .order_by(Evidence.updated_at.desc(), Evidence.id.desc())
        .limit(1)
    )
    if latest is None or latest.id != previous.id:
        raise WorkflowError(409, "The selected ID is no longer the current verified ID.")
    if (
        payload.expiry_date <= effective_at.date()
        or (previous.expiry_date is not None and payload.expiry_date <= previous.expiry_date)
    ):
        raise WorkflowError(422, "Choose a future expiry later than the current ID expiry.")
    if not previous.storage_reference or not previous.content_sha256:
        raise WorkflowError(409, "The previous ID has no private document to review.")
    if database.scalar(
        select(Evidence.id)
        .where(
            Evidence.person_id == person.id,
            Evidence.supersedes_id == previous.id,
            Evidence.status.in_((EvidenceStatus.UPLOADED, EvidenceStatus.EXTRACTED)),
        )
        .limit(1)
    ) is not None:
        raise WorkflowError(409, "This ID already has a renewal awaiting review.")

    # Reuse only the private reference: the reviewer must inspect it and verify
    # the claimed new date. Neither the old nor the proposed date is changed.
    lock_private_reference(database, previous.storage_reference)
    now = _utc_now()
    evidence = Evidence(
        id=uuid.uuid4(),
        person_id=person.id,
        invitation_id=previous.invitation_id,
        asset_id=None,
        evidence_type=EvidenceType.ID_CARD,
        status=EvidenceStatus.UPLOADED,
        filename=previous.filename,
        media_type=previous.media_type,
        size_bytes=previous.size_bytes,
        content_sha256=previous.content_sha256,
        storage_reference=previous.storage_reference,
        storage_mode=previous.storage_mode,
        provider_mode="PENDING",
        extracted_fields={},
        field_confidence={},
        validity_assessment={
            "source": "on_site_id_renewal_request",
            "document_reused": True,
            "expiry_unverified": True,
        },
        issue_date=None,
        expiry_date=payload.expiry_date,
        review_notes="Proposed ID expiry; reviewer must verify the private document and date.",
        supersedes_id=previous.id,
        uploaded_by_id=actor.id,
        reviewed_by_id=None,
        created_at=now,
        updated_at=now,
    )
    database.add(evidence)
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="identity.renewal_submitted",
        entity_type="evidence",
        entity_id=str(evidence.id),
        reason="An on-site non-driver ID expiry was proposed for independent review.",
        details={
            "person_id": str(person.id),
            "source_id": str(previous.id),
            "proposed_expiry_date": payload.expiry_date.isoformat(),
            "status": evidence.status.value,
        },
    )
    return evidence


# PUBLIC_INTERFACE
def complete_revalidation_task(
    database: Session,
    *,
    actor: UserAccount,
    task_id: uuid.UUID,
) -> RevalidationTask:
    """Complete a task only after verified renewal restores its current requirement.

    Completion reuses the existing evidence/training state and compliance
    calculation rather than accepting a frontend assertion that the person is
    eligible. Existing approved visits remain subject to those live checks, so a
    verified renewal can restore an otherwise current visit at the gate.

    Args:
        database: Active SQLAlchemy transaction.
        actor: Privileged compliance reviewer completing the task.
        task_id: Identifier of the open re-validation task.

    Returns:
        The completed durable re-validation task.

    Raises:
        WorkflowError: If the task is missing, already complete, or lacks renewal.
    """

    task = database.get(RevalidationTask, task_id)
    if task is None:
        raise WorkflowError(404, "Re-validation task not found.")
    if task.status is not RevalidationTaskStatus.OPEN:
        raise WorkflowError(409, "Only an open re-validation task can be completed.")

    effective_at = get_effective_time(database)
    if not _task_renewed(database, task=task, effective_at=effective_at):
        raise WorkflowError(
            409,
            "A verified current renewal is required before completing this task.",
        )

    task.status = RevalidationTaskStatus.COMPLETED
    task.completed_at = _utc_now()
    task.completed_by_id = actor.id

    from app.services.batch3 import evaluate_visit_compliance

    from app.services.batch5 import list_current_presence

    entered_visit_ids = {
        row["visit_id"]
        for row in list_current_presence(database, observed_at=effective_at)
        if row["person_id"] == task.person_id and row["site_id"] == task.site_id
    }
    relevant_visits = list(
        database.scalars(
            select(Visit).where(
                Visit.person_id == task.person_id,
                Visit.site_id == task.site_id,
                or_(
                    Visit.status == VisitStatus.ACTIVE,
                    Visit.id.in_(entered_visit_ids),
                ),
            )
        ).all()
    )
    eligibility_by_visit = {
        str(visit.id): evaluate_visit_compliance(database, visit_id=visit.id)["eligible"]
        for visit in relevant_visits
    }
    append_audit_event(
        database,
        actor=actor,
        action="revalidation.task_completed",
        entity_type="revalidation_task",
        entity_id=str(task.id),
        reason=(
            "A verified renewal restored the task's current requirement and "
            "recalculated active visit compliance."
        ),
        details={
            "person_id": str(task.person_id),
            "requirement_id": str(task.requirement_id),
            "eligibility_by_visit": eligibility_by_visit,
            "synthetic": True,
        },
    )
    return task
