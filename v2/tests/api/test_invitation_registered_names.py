"""Regression coverage for names in authorized invitation responses."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.session import get_db
from app.models import (
    Company,
    Invitation,
    InvitationStatus,
    Person,
    PersonStanding,
    Population,
    Role,
    Site,
    UserAccount,
)
from app.routes import workflows as workflow_routes
from app.security import get_current_user


@pytest.fixture
def invitation_database():
    """Keep invitation response checks separate from deployed data."""

    # TestClient runs requests on another thread; share one in-memory connection.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as database:
            yield database
    finally:
        engine.dispose()


def _account(database: Session, role: Role, handle: str) -> UserAccount:
    """Persist a distinct authenticated actor."""

    account = UserAccount(
        id=uuid.uuid4(),
        handle=handle,
        display_name=handle,
        password_hash="unused",
        role=role,
        person_id=None,
        is_active=True,
    )
    database.add(account)
    database.flush()
    return account


def _invitation(
    database: Session,
    *,
    population: Population,
    requester: UserAccount,
    registered: bool,
) -> Invitation:
    """Create one invitation with an optional linked person."""

    suffix = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    company = Company(
        id=uuid.uuid4(),
        seed_key=f"company_{suffix}",
        name=f"Demo Company {suffix}",
        company_type="contractor",
        country_code="NL",
        is_active=True,
    )
    site = Site(
        id=uuid.uuid4(),
        seed_key=f"site_{suffix}",
        name=f"Demo Site {suffix}",
        country_code="NL",
        timezone="Europe/Amsterdam",
        gate_mode="standard",
        is_active=True,
    )
    database.add_all([company, site])
    database.flush()

    person = None
    if registered:
        person = Person(
            id=uuid.uuid4(),
            seed_key=f"person_{suffix}",
            company_id=company.id,
            first_name="Submitted",
            last_name="Name",
            email=f"{suffix}@example.test",
            population=population,
            standing=PersonStanding.ACTIVE,
            source_metadata={"source": "accepted_invitation_registration"},
        )
        database.add(person)
        database.flush()

    invitation = Invitation(
        id=uuid.uuid4(),
        seed_key=f"invitation_{suffix}",
        site_id=site.id,
        requested_by_id=requester.id,
        invitee_email=f"{suffix}@example.test",
        population=population,
        company_name=company.name,
        purpose="Scheduled visit",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=2),
        status=(
            InvitationStatus.PRE_REGISTERED
            if registered
            else InvitationStatus.INVITED
        ),
        company_id=company.id if registered else None,
        person_id=person.id if person else None,
        visit_id=None,
        response_status="accepted" if registered else "pending",
        responded_at=now if registered else None,
        registration_completed_at=now if registered else None,
        delivery_status="local_only",
        created_at=now,
        updated_at=now,
    )
    database.add(invitation)
    database.flush()
    return invitation


def _client(database: Session, actor: UserAccount) -> TestClient:
    """Exercise the real permission and object-scope checks for one actor."""

    application = FastAPI()
    application.include_router(workflow_routes.router)
    application.dependency_overrides[get_db] = lambda: database
    application.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(application)


@pytest.mark.parametrize("population", list(Population))
def test_authorized_invitation_list_and_detail_include_linked_name(
    invitation_database: Session, population: Population
) -> None:
    """Every population uses the same linked-person name in both responses."""

    database = invitation_database
    actor = _account(database, Role.SYSTEM_ADMIN, f"admin_{uuid.uuid4().hex}")
    invitation = _invitation(
        database, population=population, requester=actor, registered=True
    )
    pending = _invitation(
        database, population=population, requester=actor, registered=False
    )

    with _client(database, actor) as client:
        listed = client.get("/api/invitations")
        detail = client.get(f"/api/invitations/{invitation.id}")
        pending_detail = client.get(f"/api/invitations/{pending.id}")

    assert listed.status_code == 200
    names = {item["id"]: item["registered_name"] for item in listed.json()}
    assert names[str(invitation.id)] == "Submitted Name"
    assert names[str(pending.id)] is None
    assert detail.status_code == 200
    assert detail.json()["registered_name"] == "Submitted Name"
    assert pending_detail.status_code == 200
    assert pending_detail.json()["registered_name"] is None


def test_invitation_names_remain_inside_object_and_permission_scope(
    invitation_database: Session,
) -> None:
    """A host cannot see another requester's name; a viewer cannot read invitations."""

    database = invitation_database
    owner = _account(database, Role.HOST, "invitation_owner")
    other_host = _account(database, Role.HOST, "unrelated_host")
    viewer = _account(database, Role.VIEWER, "invitation_viewer")
    invitation = _invitation(
        database,
        population=Population.VISITOR,
        requester=owner,
        registered=True,
    )

    with _client(database, other_host) as client:
        listed = client.get("/api/invitations")
        detail = client.get(f"/api/invitations/{invitation.id}")
    assert listed.status_code == 200
    assert listed.json() == []
    assert detail.status_code == 403

    with _client(database, viewer) as client:
        listed = client.get("/api/invitations")
        detail = client.get(f"/api/invitations/{invitation.id}")
    assert listed.status_code == 403
    assert detail.status_code == 403


def test_public_registration_status_does_not_include_name(
    invitation_database: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registration-link holder receives only the minimal form status."""

    database = invitation_database
    actor = _account(database, Role.SYSTEM_ADMIN, "registration_requester")
    invitation = _invitation(
        database,
        population=Population.TEMPORARY_DRIVER,
        requester=actor,
        registered=True,
    )
    monkeypatch.setattr(
        workflow_routes,
        "get_invitee_registration",
        lambda _database, *, token: invitation,
    )
    application = FastAPI()
    application.include_router(workflow_routes.router)
    application.dependency_overrides[get_db] = lambda: database

    with TestClient(application) as client:
        response = client.get(
            "/api/invitations/registration", params={"token": "test-capability"}
        )

    assert response.status_code == 200
    assert response.json() == {
        "company_name": invitation.company_name,
        "population": "temporary_driver",
        "registration_completed": True,
        "evidence_uploaded": True,
        # The link holder may also learn whether they have confirmed the life-saving
        # rules. Nothing else about them, and nothing about anyone else, is returned.
        "life_saving_rules_confirmed": False,
        "life_saving_rules_confirmed_at": None,
    }
    assert "registered_name" not in response.text
