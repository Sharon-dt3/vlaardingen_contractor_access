"""Isolated transaction and private-storage regression coverage for person deletion."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.database.base import Base
from app.models import (
    Company,
    Evidence,
    EvidenceAsset,
    EvidenceStatus,
    EvidenceType,
    Invitation,
    InvitationStatus,
    Person,
    PersonStanding,
    Population,
    PrivateErasureJob,
    Role,
    Site,
    UserAccount,
    Visit,
    VisitStatus,
)
from app.providers.storage import LocalStorage
from app.routes.records import delete_person, retry_person_private_erasure
from app.schemas.domain import PersonDeletionConfirmation
from app.services.people import delete_person_data
from app.services.workflows import upload_evidence, upload_invitation_identity_document


class FailingCommitSession(Session):
    """Simulate a database commit failure after the service prepares deletion."""

    def commit(self) -> None:
        """Reject the commit without making the pending deletion durable."""
        raise RuntimeError("Synthetic commit failure")


class FailingStorage:
    """Wrap local storage while simulating one post-commit erasure failure."""

    def __init__(self, storage: LocalStorage) -> None:
        """Keep the isolated storage backend and record deletion attempts."""
        self.storage = storage
        self.attempts: list[str] = []

    def delete(self, reference: str) -> None:
        """Fail one requested erasure without changing the stored bytes."""
        self.attempts.append(reference)
        raise OSError("Synthetic storage failure")


@pytest.fixture
def deletion_case(tmp_path):
    """Create synthetic people, cross-person links, and private/shared files."""
    engine = create_engine(f"sqlite:///{tmp_path / 'people.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _connection_record):
        """Make isolated SQLite enforce the relational deletion boundaries."""
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    storage = LocalStorage(str(tmp_path / "private"))
    private = storage.put(b"DEMO private person evidence")
    identity = storage.put(b"DEMO private invitation ID")
    shared = storage.put(b"DEMO shared evidence")
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    company_id, site_id = uuid.uuid4(), uuid.uuid4()
    selected_id, other_id = uuid.uuid4(), uuid.uuid4()
    actor_id = uuid.uuid4()
    selected_visit_id, other_visit_id = uuid.uuid4(), uuid.uuid4()
    selected_invitation_id, other_invitation_id = uuid.uuid4(), uuid.uuid4()

    with Session(engine) as database:
        database.add_all(
            [
                Company(
                    id=company_id, seed_key="deletion_company", name="Synthetic company",
                    company_type="contractor", country_code="NL", is_active=True,
                ),
                Site(
                    id=site_id, seed_key="deletion_site", name="Synthetic site",
                    country_code="NL", timezone="UTC", gate_mode="local", is_active=True,
                ),
                Person(
                    id=selected_id, seed_key="deletion_selected", company_id=company_id,
                    first_name="Selected", last_name="Person", email="selected@example.test",
                    population=Population.VISITOR, standing=PersonStanding.ACTIVE,
                    source_metadata={},
                ),
                Person(
                    id=other_id, seed_key="deletion_other", company_id=company_id,
                    first_name="Other", last_name="Person", email="other@example.test",
                    population=Population.VISITOR, standing=PersonStanding.ACTIVE,
                    source_metadata={},
                ),
                UserAccount(
                    id=actor_id, handle="synthetic_admin", display_name="Synthetic admin",
                    password_hash="synthetic", role=Role.SYSTEM_ADMIN, person_id=None,
                    is_active=True,
                ),
                Visit(
                    id=selected_visit_id, seed_key="deletion_selected_visit",
                    person_id=selected_id, site_id=site_id, host_person_id=None,
                    purpose="Synthetic visit", status=VisitStatus.PLANNED,
                    starts_at=now, ends_at=now + timedelta(hours=1),
                ),
                Visit(
                    id=other_visit_id, seed_key="deletion_other_visit",
                    person_id=other_id, site_id=site_id, host_person_id=selected_id,
                    purpose="Synthetic visit", status=VisitStatus.PLANNED,
                    starts_at=now, ends_at=now + timedelta(hours=1),
                ),
                EvidenceAsset(
                    id=uuid.uuid4(), asset_key="deletion_shared_asset",
                    evidence_type=EvidenceType.ID_CARD, display_name="Synthetic asset",
                    filename="shared.txt", media_type="text/plain",
                    size_bytes=len(b"DEMO shared evidence"),
                    content_sha256=shared.sha256, storage_reference=shared.reference,
                    expected_fields={}, issue_date=None, expiry_date=None, is_active=True,
                ),
            ]
        )
        database.flush()
        database.add_all(
            [
                Invitation(
                    id=selected_invitation_id, seed_key="deletion_selected_invitation",
                    site_id=site_id, requested_by_id=actor_id,
                    invitee_email="selected@example.test", population=Population.VISITOR,
                    company_name="Synthetic company", purpose="Synthetic visit",
                    starts_at=now, ends_at=now + timedelta(hours=1),
                    status=InvitationStatus.PRE_REGISTERED,
                    company_id=company_id, person_id=selected_id,
                    visit_id=selected_visit_id, response_status="accepted",
                    delivery_status="local_only",
                    identity_document_sha256=identity.sha256,
                    identity_document_storage_reference=identity.reference,
                    created_at=now, updated_at=now,
                ),
                Invitation(
                    id=other_invitation_id, seed_key="deletion_other_invitation",
                    site_id=site_id, requested_by_id=actor_id,
                    invitee_email="other@example.test", population=Population.VISITOR,
                    company_name="Synthetic company", purpose="Synthetic visit",
                    starts_at=now, ends_at=now + timedelta(hours=1),
                    status=InvitationStatus.PRE_REGISTERED,
                    company_id=company_id, person_id=other_id, visit_id=other_visit_id,
                    response_status="accepted", delivery_status="local_only",
                    registration_completed_at=now,
                    created_at=now, updated_at=now,
                ),
            ]
        )
        database.flush()
        for owner, invitation, stored in (
            (selected_id, selected_invitation_id, private),
            (selected_id, selected_invitation_id, shared),
            # An unrelated person's evidence links to this invitation. Deletion
            # must unlink that reference, not delete the person's evidence.
            (other_id, selected_invitation_id, shared),
        ):
            database.add(
                Evidence(
                    id=uuid.uuid4(), person_id=owner, invitation_id=invitation,
                    asset_id=None, evidence_type=EvidenceType.ID_CARD,
                    status=EvidenceStatus.UPLOADED, filename="demo.txt",
                    media_type="text/plain", size_bytes=stored.size_bytes,
                    content_sha256=stored.sha256, storage_reference=stored.reference,
                    storage_mode="LOCAL", provider_mode="DEMO",
                    extracted_fields={}, field_confidence={}, validity_assessment={},
                    uploaded_by_id=actor_id, created_at=now, updated_at=now,
                )
            )
        database.commit()

    yield {
        "engine": engine,
        "storage": storage,
        "selected_id": selected_id,
        "other_id": other_id,
        "actor_id": actor_id,
        "selected_invitation_id": selected_invitation_id,
        "other_invitation_id": other_invitation_id,
        "private": private,
        "identity": identity,
        "shared": shared,
    }
    engine.dispose()


def confirmation(person_id: uuid.UUID) -> PersonDeletionConfirmation:
    """Build the exact synthetic confirmation required by the service."""
    return PersonDeletionConfirmation(person_id=person_id, confirmation="DELETE PERSON")


def actor_for(database: Session, case: dict):
    """Load the synthetic administrator in the given isolated session."""
    return database.get(UserAccount, case["actor_id"])


def test_rolled_back_service_deletion_keeps_private_files(deletion_case):
    """Discarding uncommitted SQL changes must never erase private bytes."""
    case = deletion_case
    with Session(case["engine"]) as database:
        references, shared_count = delete_person_data(
            database, actor=actor_for(database, case),
            person_id=case["selected_id"], confirmation=confirmation(case["selected_id"]),
        )
        assert references == {case["private"].reference, case["identity"].reference}
        assert shared_count == 1
        database.rollback()

    with Session(case["engine"]) as database:
        assert database.get(Person, case["selected_id"]) is not None
        assert database.get(Invitation, case["selected_invitation_id"]) is not None
        assert database.scalars(select(PrivateErasureJob)).all() == []
    for stored in (case["private"], case["identity"], case["shared"]):
        assert case["storage"].get(stored.reference)


def test_failed_commit_keeps_person_and_private_files(deletion_case):
    """A failed route commit must roll back without attempting file erasure."""
    case = deletion_case
    with FailingCommitSession(case["engine"]) as database:
        with pytest.raises(RuntimeError, match="Synthetic commit failure"):
            delete_person(
                person_id=case["selected_id"],
                payload=confirmation(case["selected_id"]),
                actor=actor_for(database, case),
                database=database,
                storage=case["storage"],
            )

    with Session(case["engine"]) as database:
        assert database.get(Person, case["selected_id"]) is not None
        assert database.get(Invitation, case["selected_invitation_id"]) is not None
        assert database.scalars(select(PrivateErasureJob)).all() == []
    assert case["storage"].get(case["private"].reference)
    assert case["storage"].get(case["identity"].reference)


def test_success_erases_only_unshared_files_and_unlinks_other_people(deletion_case):
    """Committed deletion erases private bytes but retains unrelated records."""
    case = deletion_case
    with Session(case["engine"]) as database:
        result = delete_person(
            person_id=case["selected_id"],
            payload=confirmation(case["selected_id"]),
            actor=actor_for(database, case),
            database=database,
            storage=case["storage"],
        )
    assert result.shared_objects_retained == 1
    assert result.storage_objects_not_erased == 0
    with Session(case["engine"]) as database:
        assert database.get(Person, case["selected_id"]) is None
        assert database.get(Invitation, case["selected_invitation_id"]) is None
        assert {
            job.status for job in database.scalars(select(PrivateErasureJob))
        } == {"erased"}
        assert database.get(Person, case["other_id"]) is not None
        assert database.get(Invitation, case["other_invitation_id"]) is not None
        other_visit = database.scalar(
            select(Visit).where(Visit.person_id == case["other_id"])
        )
        assert other_visit.host_person_id is None
        other_evidence = database.scalar(
            select(Evidence).where(Evidence.person_id == case["other_id"])
        )
        assert other_evidence.invitation_id is None
    for stored in (case["private"], case["identity"]):
        with pytest.raises(FileNotFoundError):
            case["storage"].get(stored.reference)
    assert case["storage"].get(case["shared"].reference)


def test_post_commit_storage_failure_is_reported(deletion_case):
    """A file error after commit is reported, not disguised as SQL rollback."""
    case = deletion_case
    failing_storage = FailingStorage(case["storage"])
    with Session(case["engine"]) as database:
        result = delete_person(
            person_id=case["selected_id"],
            payload=confirmation(case["selected_id"]),
            actor=actor_for(database, case),
            database=database,
            storage=failing_storage,
        )
    assert set(failing_storage.attempts) == {
        case["private"].reference, case["identity"].reference
    }
    assert result.storage_objects_not_erased == 2
    with Session(case["engine"]) as database:
        assert database.get(Person, case["selected_id"]) is None
        jobs = database.scalars(select(PrivateErasureJob)).all()
        assert {job.storage_reference for job in jobs} == set(failing_storage.attempts)
        assert {job.status for job in jobs} == {"failed"}
    assert case["storage"].get(case["private"].reference)
    assert case["storage"].get(case["identity"].reference)
    assert case["storage"].get(case["shared"].reference)


def test_admin_retry_recovers_failed_erasure(deletion_case):
    """Failed work persists across sessions and a retry removes only private files."""

    case = deletion_case
    with Session(case["engine"]) as database:
        delete_person(
            person_id=case["selected_id"],
            payload=confirmation(case["selected_id"]),
            actor=actor_for(database, case),
            database=database,
            storage=FailingStorage(case["storage"]),
        )
    with Session(case["engine"]) as database:
        result = retry_person_private_erasure(
            person_id=case["selected_id"],
            actor=actor_for(database, case),
            database=database,
            storage=case["storage"],
        )
        assert result.storage_objects_erased == 2
        assert result.storage_objects_not_erased == 0
        assert result.shared_objects_retained == 0
    with Session(case["engine"]) as database:
        assert {job.status for job in database.scalars(select(PrivateErasureJob))} == {
            "erased"
        }
    for stored in (case["private"], case["identity"]):
        with pytest.raises(FileNotFoundError):
            case["storage"].get(stored.reference)
    assert case["storage"].get(case["shared"].reference)


def test_retry_rechecks_new_reference_and_rejects_non_admin(deletion_case):
    """A newly shared queued object is retained and a non-admin cannot retry."""

    from fastapi import HTTPException

    case = deletion_case
    with Session(case["engine"]) as database:
        delete_person(
            person_id=case["selected_id"],
            payload=confirmation(case["selected_id"]),
            actor=actor_for(database, case),
            database=database,
            storage=FailingStorage(case["storage"]),
        )
    with Session(case["engine"]) as database:
        database.add(
            EvidenceAsset(
                id=uuid.uuid4(), asset_key="newly_shared_private",
                evidence_type=EvidenceType.ID_CARD, display_name="Shared later",
                filename="shared-later.txt", media_type="text/plain",
                size_bytes=case["private"].size_bytes,
                content_sha256=case["private"].sha256,
                storage_reference=case["private"].reference,
                expected_fields={}, is_active=True,
            )
        )
        database.commit()
        non_admin = UserAccount(role=Role.COMPLIANCE)
        with pytest.raises(HTTPException) as denied:
            retry_person_private_erasure(
                person_id=case["selected_id"], actor=non_admin,
                database=database, storage=case["storage"],
            )
        assert denied.value.status_code == 403
        result = retry_person_private_erasure(
            person_id=case["selected_id"],
            actor=actor_for(database, case),
            database=database,
            storage=case["storage"],
        )
        assert result.shared_objects_retained == 1
        assert result.storage_objects_erased == 1
    assert case["storage"].get(case["private"].reference)
    with pytest.raises(FileNotFoundError):
        case["storage"].get(case["identity"].reference)


@pytest.mark.parametrize("reference_kind", ("evidence", "invitation"))
def test_retry_interleaving_preserves_committed_new_reference(
    deletion_case, monkeypatch, reference_kind
):
    """A newly committed reference at erasure time retains its private bytes."""

    case = deletion_case
    with Session(case["engine"]) as database:
        delete_person(
            person_id=case["selected_id"],
            payload=confirmation(case["selected_id"]),
            actor=actor_for(database, case),
            database=database,
            storage=FailingStorage(case["storage"]),
        )

    stored = case["private"] if reference_kind == "evidence" else case["identity"]
    content = case["storage"].get(stored.reference)
    original_lock = __import__(
        "app.services.people", fromlist=["lock_private_reference"]
    ).lock_private_reference
    inserted = False

    def interleave_before_recheck(database, reference):
        nonlocal inserted
        original_lock(database, reference)
        if reference != stored.reference or inserted:
            return
        inserted = True
        # A distinct committed transaction represents a concurrent writer
        # arriving immediately before erasure's final reference check.
        with Session(case["engine"]) as writer:
            actor = actor_for(writer, case)
            if reference_kind == "evidence":
                upload_evidence(
                    writer,
                    actor=actor,
                    invitation_id=case["other_invitation_id"],
                    evidence_type=EvidenceType.ID_CARD,
                    filename="shared-later.txt",
                    media_type="text/plain",
                    content=content,
                    storage=case["storage"],
                    allow_real_identity_document=False,
                )
            else:
                upload_invitation_identity_document(
                    writer,
                    actor=actor,
                    invitation_id=case["other_invitation_id"],
                    filename="shared-later.txt",
                    media_type="text/plain",
                    content=content,
                    storage=case["storage"],
                )
            writer.commit()

    monkeypatch.setattr(
        "app.services.people.lock_private_reference", interleave_before_recheck
    )
    with Session(case["engine"]) as database:
        result = retry_person_private_erasure(
            person_id=case["selected_id"],
            actor=actor_for(database, case),
            database=database,
            storage=case["storage"],
        )
        assert result.shared_objects_retained == 1
    assert inserted
    assert case["storage"].get(stored.reference) == content
    with Session(case["engine"]) as database:
        job = database.scalar(
            select(PrivateErasureJob).where(
                PrivateErasureJob.storage_reference == stored.reference
            )
        )
        assert job.status == "retained"
        if reference_kind == "evidence":
            assert database.scalar(
                select(Evidence.id).where(
                    Evidence.person_id == case["other_id"],
                    Evidence.storage_reference == stored.reference,
                )
            ) is not None
        else:
            invitation = database.get(Invitation, case["other_invitation_id"])
            assert invitation.identity_document_storage_reference == stored.reference
