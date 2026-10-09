"""Life-saving rules: the contractor's own confirmation, and the checks that enforce it.

These tests run against a migrated and seeded PostgreSQL database
(``python -m app.commands migrate && python -m app.commands seed``). Every test
runs inside a transaction that is rolled back, so the seeded data is never changed.
They are skipped when the database cannot be reached or has not been seeded.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.commands import _demo_id
from app.database.session import get_db
from app.life_saving_content import SAMPLE_RULES_CONTENT
from app.models import (
    AuditEvent,
    ComplianceRequirement,
    ComplianceRequirementKind,
    Invitation,
    LifeSavingRulesAcknowledgement,
    LifeSavingRulesVersion,
    Person,
    Site,
)
from app.routes import life_saving as life_saving_routes
from app.services import batch3, batch4, batch6
from app.services.life_saving import (
    confirm_rules_by_invitee,
    content_sha256,
    get_current_rules,
    life_saving_check,
    pick_translation,
    status_for_people,
)
from app.services.workflows import WorkflowError

REGISTRATION_TOKEN = "registration-link-secret-used-only-in-tests-0123456789"


@pytest.fixture()
def database():
    """A session in a transaction that is always rolled back."""

    from app.database.session import engine

    try:
        connection = engine.connect()
    except Exception:  # pragma: no cover - depends on the environment
        pytest.skip("PostgreSQL is not reachable.")
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        if not session.scalar(select(func.count()).select_from(LifeSavingRulesVersion)):
            pytest.skip("The database is not migrated and seeded.")
    except Exception:  # pragma: no cover - tables missing
        pytest.skip("The database is not migrated and seeded.")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _person(database: Session, key: str) -> Person:
    person = database.get(Person, _demo_id(key))
    assert person is not None, f"{key} is not seeded"
    return person


def _requirement(database: Session) -> ComplianceRequirement:
    requirement = database.scalar(
        select(ComplianceRequirement).where(
            ComplianceRequirement.requirement_kind is not None,
            ComplianceRequirement.code == "LIFE_SAVING_RULES",
        )
    )
    assert requirement is not None
    return requirement


def _open_registration_link(database: Session, person_key: str) -> str:
    """Give a seeded person's invitation a live, completed registration link."""

    invitation = database.get(Invitation, _demo_id(f"invitation_{person_key}"))
    assert invitation is not None
    invitation.registration_token_hash = hashlib.sha256(
        REGISTRATION_TOKEN.encode("utf-8")
    ).hexdigest()
    invitation.registration_token_expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    invitation.registration_completed_at = datetime.now(timezone.utc)
    invitation.response_status = "accepted"
    database.flush()
    return REGISTRATION_TOKEN


def _publish_new_version(database: Session) -> LifeSavingRulesVersion:
    current = get_current_rules(database)
    current.is_current = False
    database.flush()
    newer = LifeSavingRulesVersion(
        id=uuid.uuid4(),
        version=current.version + 1,
        content=SAMPLE_RULES_CONTENT,
        is_current=True,
        published_at=datetime.now(timezone.utc),
    )
    database.add(newer)
    database.flush()
    return newer


# --- what counts as confirmed -------------------------------------------------


def test_seeded_baseline_has_exactly_one_person_without_a_confirmation(database: Session) -> None:
    people = list(database.scalars(select(Person)).all())
    statuses = status_for_people(database, [person.id for person in people])
    missing = [p.seed_key for p in people if statuses[p.id]["status"] == "not_confirmed"]
    assert missing == ["person_ruben"]


def test_confirmed_person_passes_and_stores_what_they_saw(database: Session) -> None:
    alex = _person(database, "person_alex")
    check = life_saving_check(database, person_id=alex.id, requirement=_requirement(database))
    assert check["status"] == "passed"
    assert check["blocking"] is False
    assert check["kind"] == "life_saving_rules"
    assert "rules version 1" in check["detail"]


def test_person_without_confirmation_is_blocked(database: Session) -> None:
    ruben = _person(database, "person_ruben")
    check = life_saving_check(database, person_id=ruben.id, requirement=_requirement(database))
    assert check["status"] == "missing"
    assert check["blocking"] is True


def test_a_new_version_requires_everyone_to_confirm_again(database: Session) -> None:
    alex = _person(database, "person_alex")
    _publish_new_version(database)
    summary = status_for_people(database, [alex.id])[alex.id]
    assert summary["status"] == "outdated"
    assert (summary["confirmed_rules_version"], summary["current_rules_version"]) == (1, 2)
    check = life_saving_check(database, person_id=alex.id, requirement=_requirement(database))
    assert check["status"] == "expired" and check["blocking"] is True


def test_fails_closed_when_no_rules_are_published(database: Session) -> None:
    get_current_rules(database).is_current = False
    database.flush()
    alex = _person(database, "person_alex")
    check = life_saving_check(database, person_id=alex.id, requirement=_requirement(database))
    assert check["status"] == "missing" and check["blocking"] is True


def test_a_non_blocking_requirement_reports_but_does_not_block(database: Session) -> None:
    requirement = _requirement(database)
    requirement.is_blocking = False
    ruben = _person(database, "person_ruben")
    check = life_saving_check(database, person_id=ruben.id, requirement=requirement)
    assert check["status"] == "missing" and check["blocking"] is False


# --- the contractor confirms for themselves ----------------------------------


def test_contractor_confirmation_is_recorded_audited_and_makes_them_compliant(database: Session) -> None:
    ruben = _person(database, "person_ruben")
    token = _open_registration_link(database, "person_ruben")
    rules = get_current_rules(database)

    acknowledgement = confirm_rules_by_invitee(
        database, token=token, rules_version_id=rules.id, language="nl", confirmed=True
    )

    english = SAMPLE_RULES_CONTENT["translations"]["nl"]
    assert acknowledgement.person_id == ruben.id
    assert acknowledgement.language == "nl"
    assert acknowledgement.statement_text == english["statement"]
    assert acknowledgement.content_sha256 == content_sha256(english)
    assert acknowledgement.method == "invitee_registration_link"
    assert status_for_people(database, [ruben.id])[ruben.id]["status"] == "confirmed"

    events = list(
        database.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "life_saving_rules.acknowledged",
                AuditEvent.entity_id == str(acknowledgement.id),
            )
        ).all()
    )
    assert len(events) == 1
    assert events[0].details["person_id"] == str(ruben.id)
    assert events[0].details["rules_version"] == rules.version


def test_confirming_the_same_version_twice_adds_nothing(database: Session) -> None:
    token = _open_registration_link(database, "person_ruben")
    rules = get_current_rules(database)
    first = confirm_rules_by_invitee(database, token=token, rules_version_id=rules.id, language="en", confirmed=True)
    second = confirm_rules_by_invitee(database, token=token, rules_version_id=rules.id, language="en", confirmed=True)
    assert first.id == second.id
    count = database.scalar(
        select(func.count()).select_from(LifeSavingRulesAcknowledgement).where(
            LifeSavingRulesAcknowledgement.person_id == first.person_id
        )
    )
    assert count == 1


def test_confirmation_needs_the_box_to_be_ticked(database: Session) -> None:
    token = _open_registration_link(database, "person_ruben")
    rules = get_current_rules(database)
    with pytest.raises(WorkflowError) as error:
        confirm_rules_by_invitee(database, token=token, rules_version_id=rules.id, language="en", confirmed=False)
    assert error.value.status_code == 422


def test_confirmation_needs_a_completed_registration(database: Session) -> None:
    token = _open_registration_link(database, "person_ruben")
    invitation = database.get(Invitation, _demo_id("invitation_person_ruben"))
    invitation.registration_completed_at = None
    database.flush()
    with pytest.raises(WorkflowError) as error:
        confirm_rules_by_invitee(
            database, token=token, rules_version_id=get_current_rules(database).id, language="en", confirmed=True
        )
    assert error.value.status_code == 409


def test_an_unknown_link_cannot_confirm(database: Session) -> None:
    with pytest.raises(WorkflowError) as error:
        confirm_rules_by_invitee(
            database,
            token="x" * 48,
            rules_version_id=get_current_rules(database).id,
            language="en",
            confirmed=True,
        )
    assert error.value.status_code == 404


def test_only_the_current_version_can_be_confirmed(database: Session) -> None:
    token = _open_registration_link(database, "person_ruben")
    old = get_current_rules(database)
    _publish_new_version(database)
    with pytest.raises(WorkflowError) as error:
        confirm_rules_by_invitee(database, token=token, rules_version_id=old.id, language="en", confirmed=True)
    assert error.value.status_code == 409


def test_unavailable_language_falls_back_to_english() -> None:
    rules = LifeSavingRulesVersion(id=uuid.uuid4(), version=9, content=SAMPLE_RULES_CONTENT, is_current=True, published_at=datetime.now(timezone.utc))
    assert pick_translation(rules, "pl")[0] == "en"
    assert pick_translation(rules, "nl-BE")[0] == "nl"
    assert pick_translation(rules, None)[0] == "en"


# --- the approval and the gate enforce it ------------------------------------


def test_approval_compliance_includes_the_check(database: Session) -> None:
    ruben = _person(database, "person_ruben")
    visit_id = _demo_id("visit_person_ruben")
    visit = database.get(batch3.Visit, visit_id)
    checks = batch3._requirement_checks(
        database, visit=visit, person=ruben, evaluated_at=datetime.now(timezone.utc)
    )
    life = [c for c in checks if c["code"] == "LIFE_SAVING_RULES"]
    assert len(life) == 1 and life[0]["blocking"] is True


def test_the_gate_explains_the_denial_and_the_next_step() -> None:
    code, action = batch4._requirement_reason({"code": "LIFE_SAVING_RULES", "status": "missing"})
    assert code == "LIFE_SAVING_RULES_NOT_CONFIRMED"
    assert "confirm the life-saving rules" in action
    code, _ = batch4._requirement_reason({"code": "LIFE_SAVING_RULES", "status": "expired"})
    assert code == "LIFE_SAVING_RULES_OUTDATED"


def test_a_confirmation_never_creates_an_expiry_task(database: Session) -> None:
    source = batch6._source_for_requirement(
        database, requirement=_requirement(database), person_id=_person(database, "person_alex").id
    )
    assert source is None


# --- database guarantees ------------------------------------------------------


def test_only_one_rules_version_can_be_current(database: Session) -> None:
    database.add(
        LifeSavingRulesVersion(
            id=uuid.uuid4(), version=99, content=SAMPLE_RULES_CONTENT, is_current=True,
            published_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        database.flush()


def test_a_life_saving_requirement_cannot_point_at_a_document(database: Session) -> None:
    from app.models import EvidenceType

    site = database.scalar(select(Site))
    database.add(
        ComplianceRequirement(
            id=uuid.uuid4(), site_id=site.id, population=None, code="BAD", label="Bad",
            requirement_kind=ComplianceRequirementKind.LIFE_SAVING_RULES,
            evidence_type=EvidenceType.ID_CARD, training_module_id=None,
            is_required=True, is_blocking=True, is_active=True,
        )
    )
    with pytest.raises(IntegrityError):
        database.flush()


def test_a_person_cannot_confirm_the_same_version_twice_at_the_database_level(database: Session) -> None:
    alex = _person(database, "person_alex")
    rules = get_current_rules(database)
    database.add(
        LifeSavingRulesAcknowledgement(
            id=uuid.uuid4(), person_id=alex.id, rules_version_id=rules.id, language="en",
            statement_text="x", content_sha256="0" * 64,
            acknowledged_at=datetime.now(timezone.utc), method="test", invitation_id=None,
        )
    )
    with pytest.raises(IntegrityError):
        database.flush()


# --- the public API -----------------------------------------------------------


@pytest.fixture()
def client(database: Session):
    app = FastAPI()
    app.include_router(life_saving_routes.router)
    app.dependency_overrides[get_db] = lambda: database
    return TestClient(app)


def test_api_serves_the_current_rules_in_the_requested_language(client: TestClient) -> None:
    english = client.get("/api/life-saving-rules/current", params={"language": "en"}).json()
    dutch = client.get("/api/life-saving-rules/current", params={"language": "nl"}).json()
    assert english["language"] == "en" and dutch["language"] == "nl"
    assert english["id"] == dutch["id"] and english["is_sample"] is True
    assert dutch["statement"] != english["statement"]
    assert len(english["rules"]) == len(dutch["rules"]) > 0
    assert client.get("/api/life-saving-rules/current", params={"language": "de"}).json()["language"] == "en"


def test_api_confirmation_round_trip_and_error_codes(client: TestClient, database: Session) -> None:
    token = _open_registration_link(database, "person_ruben")
    # The route rolls back after a rejected request, so make the setup survive that.
    database.commit()
    rules = client.get("/api/life-saving-rules/current").json()
    body = {"token": token, "rules_version_id": rules["id"], "language": "en", "confirmed": True}

    unticked = client.post("/api/invitations/registration/life-saving-confirmation", json={**body, "confirmed": False})
    assert unticked.status_code == 422

    bad_link = client.post("/api/invitations/registration/life-saving-confirmation", json={**body, "token": "y" * 48})
    assert bad_link.status_code == 404

    ok = client.post("/api/invitations/registration/life-saving-confirmation", json=body)
    assert ok.status_code == 201
    assert ok.json()["rules_version"] == 1 and ok.json()["language"] == "en"
    assert ok.headers["cache-control"] == "no-store"
    assert set(ok.json()) == {"rules_version", "language", "acknowledged_at"}  # nothing about anyone else
