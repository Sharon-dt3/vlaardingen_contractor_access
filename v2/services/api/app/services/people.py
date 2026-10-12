"""Administrator-only deletion of one person's complete relational data."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.providers.storage import StorageProvider, lock_private_reference
from app.models import (
    AccessToken,
    Approval,
    AuditEvent,
    BlacklistEntry,
    Evidence,
    EvidenceAsset,
    ExpiryAlert,
    GateEvent,
    GateIdentityScan,
    IdentityVerification,
    Invitation,
    LifeSavingRulesAcknowledgement,
    WalkUpPending,
    WalkUpRegistration,
    Person,
    PresenceEvent,
    PrivateErasureJob,
    RevalidationTask,
    Role,
    TrainingResult,
    UserAccount,
    Visit,
)
from app.schemas.domain import PersonDeletionConfirmation
from app.services.workflows import WorkflowError


def _private_object_references(
    database: Session,
    person_id: uuid.UUID,
    invitation_ids: list[uuid.UUID],
) -> tuple[set[str], int]:
    """Find selected-person objects and count those shared outside that scope."""

    evidence_references = set(
        database.scalars(
            select(Evidence.storage_reference).where(Evidence.person_id == person_id)
        ).all()
    )
    identity_references = set(
        database.scalars(
            select(Invitation.identity_document_storage_reference).where(
                Invitation.id.in_(invitation_ids),
                Invitation.identity_document_storage_reference.is_not(None),
            )
        ).all()
    )
    walk_up_references = set(
        database.scalars(
            select(WalkUpRegistration.id_storage_reference).where(
                WalkUpRegistration.person_id == person_id,
                WalkUpRegistration.id_storage_reference.is_not(None),
            )
        ).all()
    )
    references = evidence_references | identity_references | walk_up_references
    if not references:
        return set(), 0

    # The local provider deduplicates by content hash. Never remove bytes
    # referenced by another person, an unrelated invitation, or a seed asset.
    shared = set(
        database.scalars(
            select(Evidence.storage_reference).where(
                Evidence.storage_reference.in_(references),
                Evidence.person_id != person_id,
            )
        ).all()
    )
    shared.update(
        database.scalars(
            select(Invitation.identity_document_storage_reference).where(
                Invitation.identity_document_storage_reference.in_(references),
                Invitation.id.not_in(invitation_ids),
            )
        ).all()
    )
    shared.update(
        database.scalars(
            select(WalkUpRegistration.id_storage_reference).where(
                WalkUpRegistration.id_storage_reference.in_(references),
                WalkUpRegistration.person_id != person_id,
            )
        ).all()
    )
    shared.update(
        database.scalars(
            select(WalkUpPending.id_storage_reference).where(
                WalkUpPending.id_storage_reference.in_(references)
            )
        ).all()
    )
    shared.update(
        database.scalars(
            select(EvidenceAsset.storage_reference).where(
                EvidenceAsset.storage_reference.in_(references)
            )
        ).all()
    )
    return references - shared, len(shared)


def _reference_is_used(database: Session, reference: str) -> bool:
    """Recheck every live source of a content-addressed private reference."""

    return any(
        database.scalar(statement) is not None
        for statement in (
            select(Evidence.id).where(Evidence.storage_reference == reference).limit(1),
            select(Invitation.id).where(
                Invitation.identity_document_storage_reference == reference
            ).limit(1),
            select(EvidenceAsset.id).where(
                EvidenceAsset.storage_reference == reference
            ).limit(1),
            select(WalkUpRegistration.id).where(
                WalkUpRegistration.id_storage_reference == reference
            ).limit(1),
            select(WalkUpPending.id).where(
                WalkUpPending.id_storage_reference == reference
            ).limit(1),
        )
    )


# PUBLIC_INTERFACE
def delete_person_data(
    database: Session,
    *,
    actor: UserAccount,
    person_id: uuid.UUID,
    confirmation: PersonDeletionConfirmation,
) -> tuple[set[str], int]:
    """Erase one person's dependent records within the caller's transaction.

    Args:
        database: SQLAlchemy session whose caller commits or rolls back.
        actor: Authenticated administrator requesting deletion.
        person_id: Exact person UUID; names and email addresses are not keys.
        confirmation: Explicit acknowledgement bound to the same UUID.

    Returns:
        Queued references eligible for erasure after commit, and the count
        of shared objects retained. The caller must commit before erasing.

    Raises:
        WorkflowError: If authorization, confirmation, or the target is invalid.
    """

    if actor.role is not Role.SYSTEM_ADMIN:
        raise WorkflowError(403, "Only a system administrator can delete a person.")
    if confirmation.person_id != person_id or confirmation.confirmation != "DELETE PERSON":
        raise WorkflowError(
            422,
            "Confirm the selected person's UUID and enter DELETE PERSON exactly.",
        )

    # Lock the selected row while collecting its associations. No global reset
    # or name/email matching is used: other people can share these attributes.
    person = database.scalar(
        select(Person).where(Person.id == person_id).with_for_update()
    )
    if person is None:
        raise WorkflowError(404, "The selected person does not exist.")

    invitation_id_list = list(
        database.scalars(
            select(Invitation.id).where(
                (Invitation.person_id == person_id)
                | (
                    Invitation.visit_id.in_(
                        select(Visit.id).where(Visit.person_id == person_id)
                    )
                )
            )
        ).all()
    )
    objects_to_erase, shared_count = _private_object_references(
        database, person_id, invitation_id_list
    )
    # Persist work before removing its source rows. A failed commit rolls back
    # both the deletion and the work; filesystem erasure remains post-commit.
    for reference in sorted(objects_to_erase):
        database.add(
            PrivateErasureJob(
                id=uuid.uuid4(),
                person_id=person_id,
                storage_reference=reference,
                status="pending",
                attempts=0,
            )
        )
    database.flush()

    visit_ids = select(Visit.id).where(Visit.person_id == person_id)
    invitation_ids = select(Invitation.id).where(
        (Invitation.person_id == person_id) | (Invitation.visit_id.in_(visit_ids))
    )
    evidence_ids = select(Evidence.id).where(
        (Evidence.person_id == person_id) | (Evidence.invitation_id.in_(invitation_ids))
    )
    token_ids = select(AccessToken.id).where(AccessToken.visit_id.in_(visit_ids))
    gate_ids = select(GateEvent.id).where(
        (GateEvent.person_id == person_id)
        | (GateEvent.visit_id.in_(visit_ids))
        | (GateEvent.token_id.in_(token_ids))
    )
    presence_ids = select(PresenceEvent.id).where(
        (PresenceEvent.person_id == person_id)
        | (PresenceEvent.visit_id.in_(visit_ids))
        | (PresenceEvent.gate_event_id.in_(gate_ids))
    )
    approval_ids = select(Approval.id).where(Approval.visit_id.in_(visit_ids))
    training_ids = select(TrainingResult.id).where(
        TrainingResult.person_id == person_id
    )
    blacklist_ids = select(BlacklistEntry.id).where(
        BlacklistEntry.person_id == person_id
    )
    alert_ids = select(ExpiryAlert.id).where(ExpiryAlert.person_id == person_id)
    task_ids = select(RevalidationTask.id).where(
        RevalidationTask.person_id == person_id
    )
    identity_ids = select(IdentityVerification.id).where(
        (IdentityVerification.person_id == person_id)
        | (IdentityVerification.gate_event_id.in_(gate_ids))
    )
    scan_ids = select(GateIdentityScan.id).where(
        GateIdentityScan.invitation_id.in_(invitation_ids)
    )
    acknowledgement_ids = select(LifeSavingRulesAcknowledgement.id).where(
        LifeSavingRulesAcknowledgement.person_id == person_id
    )
    walk_up_ids = select(WalkUpRegistration.id).where(
        WalkUpRegistration.person_id == person_id
    )

    # Audit rows store identifiers as text and may also contain a person UUID
    # inside structured details. Remove those rows before deleting their
    # subjects; retain unrelated audit events and do not log personal details.
    audit_subjects = (
        ("person", select(Person.id).where(Person.id == person_id)),
        ("visit", visit_ids),
        ("invitation", invitation_ids),
        ("evidence", evidence_ids),
        ("access_token", token_ids),
        ("gate_event", gate_ids),
        ("presence_event", presence_ids),
        ("approval", approval_ids),
        ("training_result", training_ids),
        ("blacklist_entry", blacklist_ids),
        ("expiry_alert", alert_ids),
        ("revalidation_task", task_ids),
        ("identity_verification", identity_ids),
        ("gate_identity_scan", scan_ids),
        ("life_saving_rules_acknowledgement", acknowledgement_ids),
        ("walk_up_registration", walk_up_ids),
    )
    audit_predicates = [
        (AuditEvent.entity_type == kind)
        & (AuditEvent.entity_id.in_(select(ids.c.id.cast(AuditEvent.entity_id.type))))
        for kind, statement in audit_subjects
        for ids in (statement.subquery(),)
    ]

    # Include audit events whose JSON details identify the selected person,
    # including events whose primary entity is a site or another shared object.
    database.execute(
        delete(AuditEvent).where(
            or_(
                *audit_predicates,
                AuditEvent.details["person_id"].as_string() == str(person_id),
            )
        )
    )

    # These references are to accounts or other people's visits, not records
    # owned by this person. Unlink them instead of deleting their owners.
    database.execute(
        update(UserAccount)
        .where(UserAccount.person_id == person_id)
        .values(person_id=None)
    )
    database.execute(
        update(Visit)
        .where(Visit.host_person_id == person_id, Visit.person_id != person_id)
        .values(host_person_id=None)
    )

    database.execute(delete(RevalidationTask).where(RevalidationTask.person_id == person_id))
    database.execute(delete(ExpiryAlert).where(ExpiryAlert.person_id == person_id))
    database.execute(delete(PresenceEvent).where(PresenceEvent.person_id == person_id))
    database.execute(
        delete(IdentityVerification).where(
            (IdentityVerification.person_id == person_id)
            | (IdentityVerification.gate_event_id.in_(gate_ids))
        )
    )
    database.execute(
        delete(GateEvent).where(
            (GateEvent.person_id == person_id)
            | (GateEvent.visit_id.in_(visit_ids))
            | (GateEvent.token_id.in_(token_ids))
        )
    )
    database.execute(delete(AccessToken).where(AccessToken.visit_id.in_(visit_ids)))
    database.execute(delete(Approval).where(Approval.visit_id.in_(visit_ids)))
    database.execute(delete(TrainingResult).where(TrainingResult.person_id == person_id))
    database.execute(delete(BlacklistEntry).where(BlacklistEntry.person_id == person_id))
    database.execute(
        delete(WalkUpRegistration).where(WalkUpRegistration.person_id == person_id)
    )
    database.execute(
        delete(LifeSavingRulesAcknowledgement).where(
            LifeSavingRulesAcknowledgement.person_id == person_id
        )
    )
    database.execute(delete(GateIdentityScan).where(GateIdentityScan.invitation_id.in_(invitation_ids)))

    # Self-referential supersession links must be cleared before evidence rows
    # are removed. Other people's evidence is never deleted.
    database.execute(
        update(Evidence)
        .where(Evidence.supersedes_id.in_(evidence_ids), Evidence.person_id != person_id)
        .values(supersedes_id=None)
    )
    database.execute(
        update(Evidence)
        .where(Evidence.invitation_id.in_(invitation_ids), Evidence.person_id != person_id)
        .values(invitation_id=None)
    )
    database.execute(delete(Evidence).where(Evidence.person_id == person_id))
    database.execute(delete(Invitation).where(Invitation.id.in_(invitation_ids)))
    database.execute(delete(Visit).where(Visit.person_id == person_id))
    database.execute(delete(Person).where(Person.id == person_id))
    return objects_to_erase, shared_count


# PUBLIC_INTERFACE
def retry_private_erasure(
    database: Session,
    *,
    actor: UserAccount,
    person_id: uuid.UUID,
    storage: StorageProvider,
) -> tuple[int, int, int]:
    """Attempt queued erasure for one deleted person and return erased, pending, retained counts.

    Args:
        database: Session used to lock and persist each queue outcome.
        actor: Authenticated administrator.
        person_id: Exact UUID originally selected for deletion.
        storage: Configured private storage provider.

    Returns:
        Counts of erased, failed/pending, and newly shared objects.

    Raises:
        WorkflowError: If the actor is not an administrator or the person still exists.
    """

    if actor.role is not Role.SYSTEM_ADMIN:
        raise WorkflowError(403, "Only a system administrator can retry erasure.")
    if database.get(Person, person_id) is not None:
        raise WorkflowError(409, "The selected person has not been deleted.")

    erased = pending = retained = 0
    job_ids = database.scalars(
        select(PrivateErasureJob.id)
        .where(
            PrivateErasureJob.person_id == person_id,
            PrivateErasureJob.status.in_(("pending", "failed", "retained")),
        )
        .order_by(PrivateErasureJob.storage_reference)
    ).all()
    database.rollback()
    for job_id in job_ids:
        try:
            # Lock and process one row per transaction. PostgreSQL serializes
            # concurrent retries of that reference until its outcome commits.
            job = database.scalar(
                select(PrivateErasureJob)
                .where(PrivateErasureJob.id == job_id)
                .with_for_update()
            )
            if job is None or job.status not in ("pending", "failed", "retained"):
                database.rollback()
                continue
            if database.get(Person, person_id) is not None:
                raise WorkflowError(409, "The selected person has not been deleted.")
            # Writers lock the same content reference before put and through
            # commit. Recheck only after any in-flight writer has committed.
            lock_private_reference(database, job.storage_reference)
            job.attempts += 1
            job.updated_at = datetime.now(timezone.utc)
            if _reference_is_used(database, job.storage_reference):
                job.status = "retained"
                retained += 1
            else:
                try:
                    # An absent file is already erased by LocalStorage.delete.
                    storage.delete(job.storage_reference)
                except (OSError, ValueError):
                    job.status = "failed"
                    pending += 1
                else:
                    job.status = "erased"
                    erased += 1
            database.commit()
        except Exception:
            database.rollback()
            raise
    return erased, pending, retained
