"""Regression coverage for invitation registration identity associations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database.base import Base
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
    Visit,
    VisitStatus,
)
from app.schemas.workflows import RegistrationCreate
from app.services.workflows import register_invitation


def _registration_context(
    database: Session,
) -> tuple[UserAccount, Invitation, Person]:
    """Create isolated records for a pre-existing recipient and new invitation."""

    company = Company(
        id=uuid.uuid4(),
        seed_key="registration_identity_company",
        name="Demo Supplies",
        company_type="contractor",
        country_code="NL",
        is_active=True,
    )
    site = Site(
        id=uuid.uuid4(),
        seed_key="registration_identity_site",
        name="Demo Site",
        country_code="NL",
        timezone="Europe/Amsterdam",
        gate_mode="standard",
        is_active=True,
    )
    actor = UserAccount(
        id=uuid.uuid4(),
        handle="registration_identity_actor",
        display_name="Demo Host",
        password_hash="unused",
        role=Role.SYSTEM_ADMIN,
        person_id=None,
        is_active=True,
    )
    person = Person(
        id=uuid.uuid4(),
        seed_key="registration_identity_person",
        company_id=company.id,
        first_name="Alex",
        last_name="Shaw",
        email="recipient@example.com",
        population=Population.VISITOR,
        standing=PersonStanding.ACTIVE,
        source_metadata={"synthetic": True},
    )
    now = datetime.now(timezone.utc)
    invitation = Invitation(
        id=uuid.uuid4(),
        seed_key="registration_identity_invitation",
        site_id=site.id,
        requested_by_id=actor.id,
        invitee_email=person.email,
        population=Population.VISITOR,
        company_name=company.name,
        purpose="Drop supplies",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=2),
        status=InvitationStatus.INVITED,
        response_status="accepted",
        responded_at=now,
        registration_completed_at=now,
        delivery_status="local_only",
        company_id=None,
        person_id=None,
        visit_id=None,
        created_at=now,
        updated_at=now,
    )
    database.add_all([company, site, actor, person, invitation])
    database.flush()
    return actor, invitation, person


@pytest.fixture
def registration_database() -> Session:
    """Use an isolated in-memory database; never connect to deployed records."""

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as database:
            yield database
    finally:
        engine.dispose()


def test_email_match_with_different_name_creates_separate_person_and_visit(
    registration_database: Session,
) -> None:
    """Keep the entered name even when another person has the same email."""

    database = registration_database
    actor, invitation, alex = _registration_context(database)
    payload = RegistrationCreate(
        company_id=alex.company_id,
        first_name="Aditya",
        last_name="Raj",
        email=alex.email,
    )

    result, _, person, visit, _, person_created = register_invitation(
        database,
        actor=actor,
        invitation_id=invitation.id,
        payload=payload,
    )

    assert person_created is True
    assert person.id != alex.id
    assert (person.first_name, person.last_name, person.email) == (
        "Aditya",
        "Raj",
        alex.email,
    )
    assert result.person_id == person.id == visit.person_id
    assert result.visit_id == visit.id
    assert visit.purpose == "Drop supplies"
    assert (alex.first_name, alex.last_name) == ("Alex", "Shaw")
    assert len(database.scalars(select(Person)).all()) == 2


def test_matching_company_email_and_name_links_existing_person_to_visit(
    registration_database: Session,
) -> None:
    """Reuse an existing person only when their name and company also match."""

    database = registration_database
    actor, invitation, alex = _registration_context(database)
    payload = RegistrationCreate(
        company_id=alex.company_id,
        first_name=" alex ",
        last_name="SHAW",
        email=alex.email,
    )

    result, _, linked_person, visit, _, person_created = register_invitation(
        database,
        actor=actor,
        invitation_id=invitation.id,
        payload=payload,
    )

    assert result.person_id == alex.id == linked_person.id == visit.person_id
    assert result.visit_id == visit.id
    assert visit.purpose == "Drop supplies"
    assert person_created is False


def test_new_registration_does_not_change_an_existing_invitation(
    registration_database: Session,
) -> None:
    """Leave a previously registered invitation and its visit untouched."""

    database = registration_database
    actor, earlier_invitation, alex = _registration_context(database)
    earlier_visit = Visit(
        id=uuid.uuid4(),
        seed_key="registration_identity_earlier_visit",
        person_id=alex.id,
        site_id=earlier_invitation.site_id,
        host_person_id=None,
        purpose="Earlier delivery",
        status=VisitStatus.PLANNED,
        starts_at=earlier_invitation.starts_at,
        ends_at=earlier_invitation.ends_at,
    )
    earlier_invitation.person_id = alex.id
    earlier_invitation.company_id = alex.company_id
    earlier_invitation.visit_id = earlier_visit.id
    earlier_invitation.status = InvitationStatus.PRE_REGISTERED
    database.add(earlier_visit)
    database.flush()

    new_invitation = Invitation(
        id=uuid.uuid4(),
        seed_key="registration_identity_new_invitation",
        site_id=earlier_invitation.site_id,
        requested_by_id=actor.id,
        invitee_email=alex.email,
        population=Population.VISITOR,
        company_name=earlier_invitation.company_name,
        purpose="Drop supplies",
        starts_at=earlier_invitation.starts_at,
        ends_at=earlier_invitation.ends_at,
        status=InvitationStatus.INVITED,
        response_status="accepted",
        responded_at=earlier_invitation.responded_at,
        registration_completed_at=earlier_invitation.registration_completed_at,
        delivery_status="local_only",
        company_id=None,
        person_id=None,
        visit_id=None,
        created_at=earlier_invitation.created_at,
        updated_at=earlier_invitation.updated_at,
    )
    database.add(new_invitation)
    database.flush()

    result, _, person, visit, _, person_created = register_invitation(
        database,
        actor=actor,
        invitation_id=new_invitation.id,
        payload=RegistrationCreate(
            company_id=alex.company_id,
            first_name="Aditya",
            last_name="Raj",
            email=alex.email,
        ),
    )

    assert person_created is True
    assert result.person_id == visit.person_id == person.id != alex.id
    assert earlier_invitation.person_id == earlier_visit.person_id == alex.id
    assert earlier_invitation.visit_id == earlier_visit.id
    assert earlier_visit.purpose == "Earlier delivery"


def test_same_email_at_another_company_does_not_claim_that_person(
    registration_database: Session,
) -> None:
    """A contact address may be shared across companies without a person link."""

    database = registration_database
    actor, invitation, alex = _registration_context(database)
    other_company = Company(
        id=uuid.uuid4(),
        seed_key="registration_identity_other_company",
        name="Other Demo Company",
        company_type="contractor",
        country_code="NL",
        is_active=True,
    )
    database.add(other_company)
    database.flush()

    result, company, person, visit, _, person_created = register_invitation(
        database,
        actor=actor,
        invitation_id=invitation.id,
        payload=RegistrationCreate(
            company_id=other_company.id,
            first_name="Aditya",
            last_name="Raj",
            email=alex.email,
        ),
    )

    assert person_created is True
    assert company.id == person.company_id == other_company.id
    assert person.id == result.person_id == visit.person_id != alex.id
    assert (alex.first_name, alex.last_name) == ("Alex", "Shaw")
