"""QR walk-up registration: arrive without an invitation, register, confirm the rules.

These tests run against a migrated and seeded PostgreSQL database and roll back
everything they do. They are skipped when the database cannot be reached.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.commands import _demo_id
from app.database.session import get_db
from app.models import (
    AuditEvent,
    SiteAccessSettings,
    Company,
    LifeSavingRulesAcknowledgement,
    LifeSavingRulesVersion,
    Person,
    WalkUpPending,
    WalkUpRegistration,
)
from app.routes import walk_up as walk_up_routes
from app.security import get_current_user
from app.services.life_saving import get_current_rules, status_for_people
from app.services.walk_up import (
    PASS_VALID_HOURS,
    MAX_CODE_ATTEMPTS,
    MAX_CODE_SENDS,
    MAX_CODES_PER_EMAIL_PER_HOUR,
    admit_at_gate,
    email_hint,
    refuse_at_gate,
    list_on_site,
    lookup_for_gate,
    record_exit,
    register_walk_up,
    resend_email_code,
    site_key,
    start_email_check,
    verify_email_code,
)
from app.services.workflows import WorkflowError


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
        session.scalar(select(func.count()).select_from(WalkUpRegistration))
        # An administrator may have changed the validity in the demo; tests assume the defaults.
        session.execute(delete(SiteAccessSettings))
    except Exception:  # pragma: no cover - tables missing
        pytest.skip("The database is not migrated and seeded.")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _details(database: Session, **overrides):
    rules = get_current_rules(database)
    values = dict(
        site_key_value="vlaardingen",
        first_name="Piet",
        last_name="Jansen",
        company_name="Walk Up Test B.V.",
        email="piet.jansen@example.com",
        population="maintenance_contractor",
        rules_version_id=rules.id,
        language="en",
        confirmed=True,
    )
    values.update(overrides)
    return values


def test_arrival_creates_person_confirmation_and_audit(database: Session) -> None:
    registration, site, rules, ack, _secret = register_walk_up(database, **_details(database))
    person = database.get(Person, registration.person_id)
    assert person.source_metadata == {"source": "walk_up_qr"}
    assert (person.first_name, person.last_name, person.email) == ("Piet", "Jansen", "piet.jansen@example.com")
    assert database.get(Company, person.company_id).name == "Walk Up Test B.V."
    assert ack.method == "walk_up_qr" and ack.invitation_id is None
    assert ack.statement_text and len(ack.content_sha256) == 64
    assert registration.site_id == site.id and registration.acknowledgement_id == ack.id
    # The people list and the gate's compliance check see the person as confirmed.
    assert status_for_people(database, [person.id])[person.id]["status"] == "confirmed"
    actions = set(
        database.scalars(
            select(AuditEvent.action).where(AuditEvent.details["person_id"].as_string() == str(person.id))
        )
    )
    assert actions == {"life_saving_rules.acknowledged", "walk_up.registered"}


def test_the_tick_is_required_and_nothing_is_stored_without_it(database: Session) -> None:
    before = database.scalar(select(func.count()).select_from(Person))
    with pytest.raises(WorkflowError) as raised:
        register_walk_up(database, **_details(database, confirmed=False))
    assert raised.value.status_code == 422
    assert database.scalar(select(func.count()).select_from(Person)) == before


def test_unknown_site_and_outdated_rules_are_refused(database: Session) -> None:
    with pytest.raises(WorkflowError) as unknown:
        register_walk_up(database, **_details(database, site_key_value="nowhere"))
    assert unknown.value.status_code == 404

    current = get_current_rules(database)
    current.is_current = False
    database.add(
        LifeSavingRulesVersion(
            id=uuid.uuid4(), version=current.version + 1, content=current.content,
            is_current=True, published_at=datetime.now(timezone.utc),
        )
    )
    database.flush()
    with pytest.raises(WorkflowError) as outdated:
        register_walk_up(database, **_details(database, rules_version_id=current.id))
    assert outdated.value.status_code == 409


def test_arriving_again_reuses_the_person_and_the_confirmation(database: Session) -> None:
    first, *_ = register_walk_up(database, **_details(database))
    second, *_ = register_walk_up(database, **_details(database, first_name="PIET", email="Piet.Jansen@Example.com"))
    assert first.person_id == second.person_id
    assert first.acknowledgement_id == second.acknowledgement_id
    assert first.id != second.id
    assert database.scalar(
        select(func.count()).select_from(LifeSavingRulesAcknowledgement).where(
            LifeSavingRulesAcknowledgement.person_id == first.person_id
        )
    ) == 1


def test_a_new_rules_version_needs_a_new_confirmation_on_the_next_arrival(database: Session) -> None:
    first, *_ = register_walk_up(database, **_details(database))
    current = get_current_rules(database)
    current.is_current = False
    newer = LifeSavingRulesVersion(
        id=uuid.uuid4(), version=current.version + 1, content=current.content,
        is_current=True, published_at=datetime.now(timezone.utc),
    )
    database.add(newer)
    database.flush()
    assert status_for_people(database, [first.person_id])[first.person_id]["status"] == "outdated"
    second, *_ = register_walk_up(database, **_details(database, rules_version_id=newer.id))
    assert second.acknowledgement_id != first.acknowledgement_id
    assert status_for_people(database, [first.person_id])[first.person_id]["status"] == "confirmed"


def test_a_walk_up_never_attaches_to_an_invited_or_seeded_person(database: Session) -> None:
    alex = database.get(Person, _demo_id("person_alex"))
    registration, *_ = register_walk_up(
        database,
        **_details(database, first_name=alex.first_name, last_name=alex.last_name, email=alex.email),
    )
    assert registration.person_id != alex.id


def test_a_walk_up_person_can_be_erased_completely(database: Session) -> None:
    from app.models import UserAccount
    from app.schemas.domain import PersonDeletionConfirmation
    from app.services.people import delete_person_data

    registration, *_ = register_walk_up(database, **_details(database))
    person_id = registration.person_id
    admin = database.scalar(select(UserAccount).where(UserAccount.handle == "admin.demo"))
    lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code=registration.id.hex[:8])
    refuse_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id, reason="not_expected")
    admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    record_exit(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    delete_person_data(
        database, actor=admin, person_id=person_id,
        confirmation=PersonDeletionConfirmation(person_id=person_id, confirmation="DELETE PERSON"),
    )
    database.flush()
    assert database.get(Person, person_id) is None
    for model in (WalkUpRegistration, LifeSavingRulesAcknowledgement):
        assert database.scalar(select(func.count()).select_from(model).where(model.person_id == person_id)) == 0
    assert database.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.details["person_id"].as_string() == str(person_id))
    ) == 0


# --- the public API -----------------------------------------------------------


@pytest.fixture()
def client(database: Session, monkeypatch):
    """The API with the email check off, so registrations complete in one step."""

    app = FastAPI()
    app.include_router(walk_up_routes.router)
    app.dependency_overrides[get_db] = lambda: database
    walk_up_routes._registration_limiter.reset()
    walk_up_routes._verify_limiter.reset()
    monkeypatch.setattr(walk_up_routes, "email_check_enabled", lambda: False)
    return TestClient(app)


def _body(database: Session, **overrides):
    rules = get_current_rules(database)
    body = {
        "site_key": "vlaardingen", "first_name": "Anna", "last_name": "de Boer",
        "company_name": "Walk Up Test B.V.", "email": "anna.deboer@example.com",
        "population": "visitor", "rules_version_id": str(rules.id), "language": "en", "confirmed": True,
    }
    body.update(overrides)
    return body


def test_api_site_lookup_and_qr_image(client: TestClient) -> None:
    ok = client.get("/api/walk-up/sites/vlaardingen")
    assert ok.status_code == 200 and ok.json() == {"site_key": "vlaardingen", "site_name": "Vlaardingen"}
    assert client.get("/api/walk-up/sites/nowhere").status_code == 404
    image = client.get("/api/walk-up/qr.png", params={"site": "vlaardingen"})
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/api/walk-up/qr.png", params={"site": "nowhere"}).status_code == 404


def test_api_registration_round_trip_and_error_codes(client: TestClient, database: Session) -> None:
    ok = client.post("/api/walk-up/registrations", json=_body(database))
    assert ok.status_code == 201
    receipt = ok.json()
    assert set(receipt) == {
        "reference", "site_name", "registered_at", "rules_version", "language", "pass_qr", "pass_valid_until",
        "pass_valid_from", "site_timezone", "emailed_to",
    }
    assert len(receipt["reference"]) == 8 and ok.headers["cache-control"] == "no-store"
    database.commit()  # the route rolls back rejected requests; keep the setup

    assert client.post("/api/walk-up/registrations", json=_body(database, confirmed=False)).status_code == 422
    assert client.post("/api/walk-up/registrations", json=_body(database, email="not-an-email")).status_code == 422
    assert client.post("/api/walk-up/registrations", json=_body(database, population="astronaut")).status_code == 422
    assert client.post("/api/walk-up/registrations", json=_body(database, website="http://spam")).status_code == 422
    assert client.post("/api/walk-up/registrations", json=_body(database, unexpected="x")).status_code == 422
    assert client.post("/api/walk-up/registrations", json=_body(database, site_key="nowhere")).status_code == 404
    assert client.post("/api/walk-up/registrations", json=_body(database, first_name="   ")).status_code == 422
    assert client.post(
        "/api/walk-up/registrations", json=_body(database, rules_version_id=str(uuid.uuid4()))
    ).status_code == 404


def test_api_registration_is_rate_limited(client: TestClient, database: Session) -> None:
    walk_up_routes._registration_limiter = walk_up_routes.RateLimiter(limit=2, window_seconds=60)
    codes = [
        client.post("/api/walk-up/registrations", json=_body(database, confirmed=False)).status_code
        for _ in range(3)
    ]
    assert codes == [422, 422, 429]
    walk_up_routes._registration_limiter = walk_up_routes.RateLimiter(limit=30, window_seconds=600)


def test_staff_endpoints_need_a_signed_in_user(client: TestClient) -> None:
    assert client.get("/api/walk-up/registrations").status_code == 401
    assert client.get("/api/walk-up/sites").status_code == 401


def test_staff_see_arrivals_with_the_confirmed_wording(client: TestClient, database: Session) -> None:
    from app.models import UserAccount

    client.post("/api/walk-up/registrations", json=_body(database))
    admin = database.scalar(select(UserAccount).where(UserAccount.handle == "admin.demo"))
    client.app.dependency_overrides[get_current_user] = lambda: admin
    rows = client.get("/api/walk-up/registrations").json()
    mine = [row for row in rows if row["email"] == "anna.deboer@example.com"]
    assert len(mine) == 1
    row = mine[0]
    assert (row["first_name"], row["last_name"], row["company_name"]) == ("Anna", "de Boer", "Walk Up Test B.V.")
    assert row["site_name"] == "Vlaardingen" and row["rules_version"] == 1 and row["statement_text"]
    sites = client.get("/api/walk-up/sites").json()
    assert sites[0]["site_key"] == "vlaardingen" and sites[0]["arrival_url"].endswith("/arrive/vlaardingen")


def test_site_key_is_a_readable_slug(database: Session) -> None:
    from app.models import Site

    names = {site_key(site) for site in database.scalars(select(Site)).all()}
    assert "vlaardingen" in names


# --- the kiosk: scan or type, then let in ------------------------------------


def _admin(database: Session):
    from app.models import UserAccount

    return database.scalar(select(UserAccount).where(UserAccount.handle == "admin.demo"))


def test_the_pass_is_stored_only_as_a_hash_and_expires(database: Session) -> None:
    import hashlib

    registration, _site, _rules, _ack, secret = register_walk_up(database, **_details(database))
    assert registration.pass_hash == hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in (registration.pass_hash or "")
    remaining = registration.pass_expires_at - registration.registered_at
    assert remaining == timedelta(hours=PASS_VALID_HOURS)


def test_the_kiosk_finds_an_arrival_by_qr_or_by_typed_reference(database: Session) -> None:
    registration, _site, _rules, _ack, secret = register_walk_up(database, **_details(database))
    reference = registration.id.hex[:8].upper()
    for code in (
        secret,
        "renewi-walkup:" + secret,  # earlier QR codes
        f"renewi-walkup:{reference}:{secret}",  # current QR codes
        reference,
        reference.lower(),
        f"  {reference} ",
    ):
        found = lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=code)
        assert found["registration_id"] == registration.id
        assert (found["first_name"], found["company_name"]) == ("Piet", "Walk Up Test B.V.")
        assert found["eligible"] is True and found["reasons"] == []
        assert found["rules_version"] == 1 and found["admitted_at"] is None


def test_unknown_expired_and_wrong_site_codes_are_refused(database: Session) -> None:
    registration, _site, _rules, _ack, secret = register_walk_up(database, **_details(database))
    for code in ("not-a-real-code-at-all", "DEADBEEF"):
        with pytest.raises(WorkflowError) as unknown:
            lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=code)
        assert unknown.value.status_code == 404
    with pytest.raises(WorkflowError) as wrong_site:
        lookup_for_gate(database, actor=_admin(database), site_key_value="nowhere", code=secret)
    assert wrong_site.value.status_code == 404
    registration.registered_at = datetime.now(timezone.utc) - timedelta(hours=PASS_VALID_HOURS + 1)
    registration.pass_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    database.flush()
    with pytest.raises(WorkflowError) as expired:
        lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=secret)
    assert expired.value.status_code == 404


def test_the_operator_lets_a_person_in_once_and_it_is_audited(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    admin = _admin(database)
    first = admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    assert first["admitted_at"] is not None and first["admitted_by"] == admin.display_name
    again = admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    assert again["admitted_at"] == first["admitted_at"]
    events = database.scalars(
        select(AuditEvent).where(AuditEvent.action == "walk_up.admitted", AuditEvent.entity_id == str(registration.id))
    ).all()
    assert len(events) == 1 and events[0].actor_id == admin.id
    assert events[0].details["person_id"] == str(registration.person_id)


def test_entry_is_refused_when_the_rules_changed_after_they_confirmed(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    current = get_current_rules(database)
    current.is_current = False
    database.add(
        LifeSavingRulesVersion(
            id=uuid.uuid4(), version=current.version + 1, content=current.content,
            is_current=True, published_at=datetime.now(timezone.utc),
        )
    )
    database.flush()
    state = lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert state["eligible"] is False
    assert [r["code"] for r in state["reasons"]] == ["LIFE_SAVING_RULES_OUTDATED"]
    with pytest.raises(WorkflowError) as refused:
        admit_at_gate(database, actor=_admin(database), site_key_value="vlaardingen", registration_id=registration.id)
    assert refused.value.status_code == 409
    assert database.get(WalkUpRegistration, registration.id).admitted_at is None


def test_a_blocked_or_blacklisted_person_is_not_let_in(database: Session) -> None:
    from app.models import BlacklistEntry, BlacklistSubjectType, PersonStanding

    registration, *_ = register_walk_up(database, **_details(database))
    person = database.get(Person, registration.person_id)
    person.standing = PersonStanding.BLOCKED
    database.flush()
    state = lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert [r["code"] for r in state["reasons"]] == ["PERSON_NOT_ACTIVE"]

    person.standing = PersonStanding.ACTIVE
    admin = _admin(database)
    database.add(
        BlacklistEntry(
            id=uuid.uuid4(), subject_type=BlacklistSubjectType.PERSON, person_id=person.id,
            reason="test", is_active=True, starts_at=datetime.now(timezone.utc) - timedelta(days=1),
            ends_at=None, created_by_id=admin.id,
        )
    )
    database.flush()
    state = lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert [r["code"] for r in state["reasons"]] == ["BLACKLISTED"]
    with pytest.raises(WorkflowError):
        admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)


def test_the_qr_carries_the_reference_and_the_secret(database: Session) -> None:
    from app.services.walk_up import PASS_PREFIX, pass_qr_data_url, reference_for

    registration, _site, _rules, _ack, secret = register_walk_up(database, **_details(database))
    reference = reference_for(registration.id)
    url = pass_qr_data_url(secret, reference)
    assert url.startswith("data:image/png;base64,")
    # A wrong reference in front of the right secret still finds the right person: the secret decides.
    found = lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=f"{PASS_PREFIX}ZZZZZZZZ:{secret}")
    assert found["registration_id"] == registration.id
    with pytest.raises(WorkflowError):
        lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=f"{PASS_PREFIX}{reference}:not-the-secret")


def test_api_receipt_carries_a_qr_image_and_validity(client: TestClient, database: Session) -> None:
    receipt = client.post("/api/walk-up/registrations", json=_body(database)).json()
    assert receipt["pass_qr"].startswith("data:image/png;base64,") and len(receipt["pass_qr"]) > 500
    assert receipt["pass_valid_until"] > receipt["registered_at"]


def test_api_kiosk_needs_gate_permission_and_round_trips(client: TestClient, database: Session) -> None:
    from app.models import Role, UserAccount

    receipt = client.post("/api/walk-up/registrations", json=_body(database)).json()
    database.commit()
    body = {"site_key": "vlaardingen", "code": receipt["reference"]}
    assert client.post("/api/walk-up/gate/lookup", json=body).status_code == 401

    host = UserAccount(
        id=uuid.uuid4(), handle=f"host-{uuid.uuid4().hex[:6]}", display_name="Host", password_hash="x",
        role=Role.HOST, is_active=True,
    )
    database.add(host)
    database.flush()
    client.app.dependency_overrides[get_current_user] = lambda: host
    assert client.post("/api/walk-up/gate/lookup", json=body).status_code == 403

    client.app.dependency_overrides[get_current_user] = lambda: _admin(database)
    found = client.post("/api/walk-up/gate/lookup", json=body)
    assert found.status_code == 200 and found.headers["cache-control"] == "no-store"
    assert found.json()["eligible"] is True and found.json()["admitted_at"] is None
    admit = {"site_key": "vlaardingen", "registration_id": found.json()["registration_id"]}
    done = client.post("/api/walk-up/gate/admit", json=admit)
    assert done.status_code == 200 and done.json()["admitted_at"] is not None
    assert client.post("/api/walk-up/gate/lookup", json={**body, "code": "nope-nope"}).status_code == 404
    assert client.post("/api/walk-up/gate/admit", json={**admit, "site_key": "nowhere"}).status_code == 404
    assert client.post("/api/walk-up/gate/lookup", json={**body, "extra": 1}).status_code == 422


# --- the email check ----------------------------------------------------------


def _start(database: Session, **overrides):
    values = _details(database)
    values.pop("email_verified_at", None)
    values.update(overrides)
    return start_email_check(database, **values)


def test_starting_the_check_stores_no_person_and_no_plain_code(database: Session) -> None:
    people_before = database.scalar(select(func.count()).select_from(Person))
    acks_before = database.scalar(select(func.count()).select_from(LifeSavingRulesAcknowledgement))
    pending, code, site = _start(database)
    assert len(code) == 6 and code.isdigit() and site.name == "Vlaardingen"
    assert code not in pending.code_hash and len(pending.code_hash) == 64
    assert database.scalar(select(func.count()).select_from(Person)) == people_before
    assert database.scalar(select(func.count()).select_from(LifeSavingRulesAcknowledgement)) == acks_before
    registrations_before = database.scalar(select(func.count()).select_from(WalkUpRegistration))
    assert registrations_before == database.scalar(select(func.count()).select_from(WalkUpRegistration))
    assert database.get(WalkUpPending, pending.id) is not None


def test_the_right_code_completes_the_registration_and_marks_the_email_verified(database: Session) -> None:
    pending, code, _site = _start(database)
    registration, _s, _r, ack, secret = verify_email_code(database, pending_id=pending.id, code=code)
    assert registration.email_verified_at is not None and secret
    assert ack.method == "walk_up_qr"
    assert database.get(WalkUpPending, pending.id) is None
    state = lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert state["email_verified"] is True and state["eligible"] is True


def test_wrong_codes_are_counted_even_though_the_request_fails_and_then_locked(database: Session) -> None:
    pending, code, _site = _start(database)
    wrong = "000000" if code != "000000" else "111111"
    for expected_left in range(MAX_CODE_ATTEMPTS - 1, 0, -1):
        with pytest.raises(WorkflowError) as raised:
            verify_email_code(database, pending_id=pending.id, code=wrong)
        assert raised.value.status_code == 422 and str(expected_left) in raised.value.detail
        assert database.get(WalkUpPending, pending.id).attempts == MAX_CODE_ATTEMPTS - expected_left
    with pytest.raises(WorkflowError) as locked:
        verify_email_code(database, pending_id=pending.id, code=wrong)
    assert locked.value.status_code == 429
    # Even the right code no longer works: the registration has to start again.
    with pytest.raises(WorkflowError) as gone:
        verify_email_code(database, pending_id=pending.id, code=code)
    assert gone.value.status_code == 404


def test_an_expired_code_is_refused_and_removed(database: Session) -> None:
    pending, code, _site = _start(database)
    pending.code_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    database.flush()
    with pytest.raises(WorkflowError) as raised:
        verify_email_code(database, pending_id=pending.id, code=code)
    assert raised.value.status_code == 410
    assert database.get(WalkUpPending, pending.id) is None


def test_resending_replaces_the_code_and_is_limited(database: Session) -> None:
    pending, first_code, _site = _start(database)
    with pytest.raises(WorkflowError) as too_soon:
        resend_email_code(database, pending_id=pending.id)
    assert too_soon.value.status_code == 429
    for _ in range(MAX_CODE_SENDS - 1):
        pending.last_sent_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        database.flush()
        _p, new_code, _s = resend_email_code(database, pending_id=pending.id)
    assert pending.sends == MAX_CODE_SENDS
    pending.last_sent_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    database.flush()
    with pytest.raises(WorkflowError) as capped:
        resend_email_code(database, pending_id=pending.id)
    assert capped.value.status_code == 429
    if new_code != first_code:
        with pytest.raises(WorkflowError):
            verify_email_code(database, pending_id=pending.id, code=first_code)
    assert verify_email_code(database, pending_id=pending.id, code=new_code)[0].email_verified_at is not None


def test_one_email_address_cannot_be_flooded_with_codes(database: Session) -> None:
    for _ in range(MAX_CODES_PER_EMAIL_PER_HOUR):
        _start(database)
    with pytest.raises(WorkflowError) as raised:
        _start(database)
    assert raised.value.status_code == 429


def test_the_check_refuses_what_a_registration_would_refuse(database: Session) -> None:
    with pytest.raises(WorkflowError) as unticked:
        _start(database, confirmed=False)
    assert unticked.value.status_code == 422
    with pytest.raises(WorkflowError) as unknown:
        _start(database, site_key_value="nowhere")
    assert unknown.value.status_code == 404


def test_rules_changing_while_the_code_is_pending_sends_them_back_to_the_start(database: Session) -> None:
    pending, code, _site = _start(database)
    current = get_current_rules(database)
    current.is_current = False
    database.add(
        LifeSavingRulesVersion(
            id=uuid.uuid4(), version=current.version + 1, content=current.content,
            is_current=True, published_at=datetime.now(timezone.utc),
        )
    )
    database.flush()
    with pytest.raises(WorkflowError) as raised:
        verify_email_code(database, pending_id=pending.id, code=code)
    assert raised.value.status_code == 409


def test_email_hint_shows_little() -> None:
    assert email_hint("dana.driver@example.com") == "d***@example.com"


# --- who is on site -----------------------------------------------------------


def test_exit_needs_an_entry_is_idempotent_audited_and_stops_re_entry(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    admin = _admin(database)
    with pytest.raises(WorkflowError) as never_in:
        record_exit(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    assert never_in.value.status_code == 409

    admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    left = record_exit(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    again = record_exit(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    assert left["exited_at"] is not None and again["exited_at"] == left["exited_at"]
    events = database.scalars(
        select(AuditEvent).where(AuditEvent.action == "walk_up.exited", AuditEvent.entity_id == str(registration.id))
    ).all()
    assert len(events) == 1 and events[0].actor_id == admin.id

    state = lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert state["eligible"] is False and [r["code"] for r in state["reasons"]] == ["ALREADY_LEFT"]
    with pytest.raises(WorkflowError) as back_in:
        admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    assert back_in.value.status_code == 409


def test_the_on_site_list_shows_only_people_let_in_who_have_not_left(database: Session) -> None:
    admin = _admin(database)
    inside, *_ = register_walk_up(database, **_details(database, first_name="Inside", email="in@example.com"))
    gone, *_ = register_walk_up(database, **_details(database, first_name="Gone", email="gone@example.com"))
    waiting, *_ = register_walk_up(database, **_details(database, first_name="Waiting", email="wait@example.com"))
    for registration in (inside, gone):
        admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    record_exit(database, actor=admin, site_key_value="vlaardingen", registration_id=gone.id)
    names = [row["first_name"] for row in list_on_site(database)]
    assert "Inside" in names and "Gone" not in names and "Waiting" not in names
    row = next(r for r in list_on_site(database) if r["first_name"] == "Inside")
    assert row["overdue"] is False and row["overdue_minutes"] is None and row["admitted_by"] == admin.display_name
    # Past the QR's exit time they stay on the list, flagged as overdue, however long they have been inside.
    inside.pass_expires_at = datetime.now(timezone.utc) - timedelta(minutes=90)
    inside.admitted_at = datetime.now(timezone.utc) - timedelta(hours=40)
    database.flush()
    late = next(r for r in list_on_site(database) if r["first_name"] == "Inside")
    assert late["overdue"] is True and 89 <= late["overdue_minutes"] <= 91


# --- the email check and the on-site list through the API ---------------------


@pytest.fixture()
def checked_client(database: Session, monkeypatch):
    """The API with the email check on and a fake mailer that keeps the codes it was asked to send."""

    from types import SimpleNamespace

    app = FastAPI()
    app.include_router(walk_up_routes.router)
    app.dependency_overrides[get_db] = lambda: database
    walk_up_routes._registration_limiter.reset()
    walk_up_routes._verify_limiter.reset()
    sent: list[dict] = []
    passes: list[dict] = []
    monkeypatch.setattr(walk_up_routes, "email_check_enabled", lambda: True)
    monkeypatch.setattr(walk_up_routes, "send_walk_up_pass_email", lambda settings, **kw: passes.append(kw))
    monkeypatch.setattr(
        walk_up_routes, "get_settings", lambda: SimpleNamespace(notification_provider="smtp", web_origin="http://x")
    )
    monkeypatch.setattr(walk_up_routes, "send_walk_up_code_email", lambda settings, **kw: sent.append(kw))
    client = TestClient(app)
    client.sent = sent  # type: ignore[attr-defined]
    client.passes = passes  # type: ignore[attr-defined]
    return client


def test_api_email_check_round_trip(checked_client: TestClient, database: Session) -> None:
    started = checked_client.post("/api/walk-up/registrations", json=_body(database))
    assert started.status_code == 202
    body = started.json()
    assert body["verification_required"] is True and body["email_hint"] == "a***@example.com"
    assert "pass_qr" not in body and "reference" not in body
    assert len(checked_client.sent) == 1 and checked_client.sent[0]["to"] == "anna.deboer@example.com"
    code = checked_client.sent[0]["code"]
    database.commit()

    bad_format = checked_client.post(
        "/api/walk-up/registrations/verify", json={"pending_id": body["pending_id"], "code": "12ab56"}
    )
    assert bad_format.status_code == 422
    wrong = checked_client.post(
        "/api/walk-up/registrations/verify",
        json={"pending_id": body["pending_id"], "code": "000000" if code != "000000" else "111111"},
    )
    assert wrong.status_code == 422 and "tries left" in wrong.json()["detail"]
    ok = checked_client.post(
        "/api/walk-up/registrations/verify", json={"pending_id": body["pending_id"], "code": code}
    )
    assert ok.status_code == 201
    assert ok.json()["pass_qr"].startswith("data:image/png;base64,") and len(ok.json()["reference"]) == 8
    again = checked_client.post(
        "/api/walk-up/registrations/verify", json={"pending_id": body["pending_id"], "code": code}
    )
    assert again.status_code == 404
    unknown = checked_client.post(
        "/api/walk-up/registrations/verify", json={"pending_id": str(uuid.uuid4()), "code": "123456"}
    )
    assert unknown.status_code == 404


def test_api_resend_is_throttled(checked_client: TestClient, database: Session) -> None:
    started = checked_client.post("/api/walk-up/registrations", json=_body(database)).json()
    database.commit()
    too_soon = checked_client.post("/api/walk-up/registrations/resend", json={"pending_id": started["pending_id"]})
    assert too_soon.status_code == 429 and len(checked_client.sent) == 1


def test_api_email_check_needs_a_mail_server(checked_client: TestClient, database: Session, monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(walk_up_routes, "get_settings", lambda: SimpleNamespace(notification_provider="mock"))
    refused = checked_client.post("/api/walk-up/registrations", json=_body(database))
    assert refused.status_code == 503 and "mail server" in refused.json()["detail"]


def test_api_a_failed_email_leaves_nothing_behind(checked_client: TestClient, database: Session, monkeypatch) -> None:
    from app.providers.walk_up_email import WalkUpEmailError

    def boom(settings, **kw):
        raise WalkUpEmailError("down")

    monkeypatch.setattr(walk_up_routes, "send_walk_up_code_email", boom)
    before = database.scalar(select(func.count()).select_from(WalkUpPending))
    failed = checked_client.post("/api/walk-up/registrations", json=_body(database))
    assert failed.status_code == 503
    assert database.scalar(select(func.count()).select_from(WalkUpPending)) == before


def test_api_exit_and_on_site_list(client: TestClient, database: Session) -> None:
    from app.models import Role, UserAccount

    receipt = client.post("/api/walk-up/registrations", json=_body(database)).json()
    database.commit()
    assert client.get("/api/walk-up/on-site").status_code == 401

    host = UserAccount(
        id=uuid.uuid4(), handle=f"host-{uuid.uuid4().hex[:6]}", display_name="Host", password_hash="x",
        role=Role.HOST, is_active=True,
    )
    database.add(host)
    database.flush()
    client.app.dependency_overrides[get_current_user] = lambda: host
    assert client.get("/api/walk-up/on-site").status_code == 403

    client.app.dependency_overrides[get_current_user] = lambda: _admin(database)
    found = client.post("/api/walk-up/gate/lookup", json={"site_key": "vlaardingen", "code": receipt["reference"]}).json()
    assert found["email_verified"] is False  # the check was off for this registration
    admit = {"site_key": "vlaardingen", "registration_id": found["registration_id"]}
    assert client.post("/api/walk-up/gate/admit", json=admit).status_code == 200
    on_site = client.get("/api/walk-up/on-site").json()
    assert [r["reference"] for r in on_site if r["reference"] == receipt["reference"]] == [receipt["reference"]]
    left = client.post("/api/walk-up/gate/exit", json=admit)
    assert left.status_code == 200 and left.json()["exited_at"] is not None
    assert all(r["reference"] != receipt["reference"] for r in client.get("/api/walk-up/on-site").json())
    assert client.post("/api/walk-up/gate/exit", json={**admit, "site_key": "nowhere"}).status_code == 404


@pytest.mark.parametrize(
    "population",
    ["renewi_driver", "temporary_driver", "external_driver", "maintenance_contractor", "permanent_contractor", "visitor"],
)
def test_every_invitation_category_can_register_as_a_walk_up(client: TestClient, database: Session, population: str) -> None:
    ok = client.post(
        "/api/walk-up/registrations",
        json=_body(database, population=population, email=f"{population}@example.com"),
    )
    assert ok.status_code == 201, ok.text
    stored = database.scalar(select(Person).where(Person.email == f"{population}@example.com"))
    assert stored.population.value == population


# --- refusals are recorded ----------------------------------------------------


def _refusals(database: Session, registration_id: uuid.UUID) -> list[AuditEvent]:
    return list(
        database.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "walk_up.refused", AuditEvent.entity_id == str(registration_id))
            .order_by(AuditEvent.occurred_at)
        ).all()
    )


def _make_rules_outdated(database: Session) -> None:
    current = get_current_rules(database)
    current.is_current = False
    database.add(
        LifeSavingRulesVersion(
            id=uuid.uuid4(), version=current.version + 1, content=current.content,
            is_current=True, published_at=datetime.now(timezone.utc),
        )
    )
    database.flush()


def test_a_system_refusal_is_recorded_with_its_reasons_and_not_repeated_within_a_minute(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    _make_rules_outdated(database)
    admin = _admin(database)
    state = lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert state["eligible"] is False and state["refusal_count"] == 1 and state["last_refused_at"] is not None
    events = _refusals(database, registration.id)
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == admin.id
    assert event.details["source"] == "system"
    assert event.details["reasons"] == ["LIFE_SAVING_RULES_OUTDATED"]
    assert event.details["person_id"] == str(registration.person_id)

    lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert len(_refusals(database, registration.id)) == 1  # a repeated Check is not a new refusal

    event.occurred_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    database.flush()
    lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert len(_refusals(database, registration.id)) == 2


def test_someone_who_may_enter_is_not_recorded_as_refused(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    state = lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert state["eligible"] is True and state["refusal_count"] == 0
    assert _refusals(database, registration.id) == []


def test_a_code_that_matches_nobody_is_recorded_without_storing_the_code(database: Session) -> None:
    import json

    admin = _admin(database)
    for typed, kind in (("not-a-real-code-at-all", "qr"), ("DEADBEEF", "reference")):
        with pytest.raises(WorkflowError) as raised:
            lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code=typed)
        assert raised.value.status_code == 404
        event = database.scalars(
            select(AuditEvent).where(AuditEvent.action == "walk_up.lookup_failed").order_by(AuditEvent.occurred_at.desc())
        ).first()
        assert event.actor_id == admin.id and event.details["code_kind"] == kind
        assert typed not in json.dumps(event.details) and typed not in event.reason


def test_a_refused_admit_is_recorded_even_though_it_raises(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    _make_rules_outdated(database)
    with pytest.raises(WorkflowError) as raised:
        admit_at_gate(database, actor=_admin(database), site_key_value="vlaardingen", registration_id=registration.id)
    assert raised.value.status_code == 409
    events = _refusals(database, registration.id)
    assert len(events) == 1 and events[0].details["reasons"] == ["LIFE_SAVING_RULES_OUTDATED"]


def test_admitting_someone_who_already_left_is_a_recorded_refusal(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    admin = _admin(database)
    admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    record_exit(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    with pytest.raises(WorkflowError):
        admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    assert [e.details["reasons"] for e in _refusals(database, registration.id)] == [["ALREADY_LEFT"]]


def test_an_officer_can_turn_away_someone_the_records_allow_and_say_why(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    admin = _admin(database)
    state = refuse_at_gate(
        database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id,
        reason="identity_mismatch", note="  Face does   not match the ID  ",
    )
    assert state["refusal_count"] == 1 and state["eligible"] is True  # a refusal does not lock the person out
    event = _refusals(database, registration.id)[0]
    assert event.actor_id == admin.id
    assert event.details["source"] == "officer" and event.details["reasons"] == ["identity_mismatch"]
    assert event.details["note"] == "Face does not match the ID"

    with pytest.raises(WorkflowError) as bad_reason:
        refuse_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id, reason="because")
    assert bad_reason.value.status_code == 422
    with pytest.raises(WorkflowError) as needs_note:
        refuse_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id, reason="other")
    assert needs_note.value.status_code == 422

    admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    with pytest.raises(WorkflowError) as already_in:
        refuse_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id, reason="not_expected")
    assert already_in.value.status_code == 409


def test_refusals_show_up_in_the_staff_list(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database, first_name="Refused", email="refused@example.com"))
    refuse_at_gate(database, actor=_admin(database), site_key_value="vlaardingen", registration_id=registration.id, reason="not_expected")
    from app.services.walk_up import list_registrations

    row = next(r for r in list_registrations(database, since_hours=24, limit=500) if r["id"] == registration.id)
    assert row["refusal_count"] == 1 and row["last_refused_at"] is not None


def test_api_refuse_endpoint_permissions_and_validation(client: TestClient, database: Session) -> None:
    from app.models import Role, UserAccount

    receipt = client.post("/api/walk-up/registrations", json=_body(database)).json()
    database.commit()
    found_id = database.scalar(select(WalkUpRegistration.id).order_by(WalkUpRegistration.registered_at.desc()))
    body = {"site_key": "vlaardingen", "registration_id": str(found_id), "reason": "identity_mismatch", "note": "ID photo differs"}
    assert client.post("/api/walk-up/gate/refuse", json=body).status_code == 401

    host = UserAccount(
        id=uuid.uuid4(), handle=f"host-{uuid.uuid4().hex[:6]}", display_name="Host", password_hash="x",
        role=Role.HOST, is_active=True,
    )
    database.add(host)
    database.flush()
    client.app.dependency_overrides[get_current_user] = lambda: host
    assert client.post("/api/walk-up/gate/refuse", json=body).status_code == 403

    client.app.dependency_overrides[get_current_user] = lambda: _admin(database)
    assert client.post("/api/walk-up/gate/refuse", json={**body, "reason": "because"}).status_code == 422
    assert client.post("/api/walk-up/gate/refuse", json={**body, "reason": "other", "note": ""}).status_code == 422
    done = client.post("/api/walk-up/gate/refuse", json=body)
    assert done.status_code == 200 and done.json()["refusal_count"] == 1
    assert len(_refusals(database, found_id)) == 1
    assert receipt["reference"]


# --- merged into the main dashboard -------------------------------------------


def _snapshot(database: Session):
    from app.services.batch5 import get_dashboard_snapshot
    from app.services.walk_up import merge_walk_ups_into_dashboard

    snapshot = get_dashboard_snapshot(database, observed_at=datetime.now(timezone.utc) + timedelta(minutes=1))
    return merge_walk_ups_into_dashboard(database, snapshot, recent_limit=20)


def _vlaardingen(snapshot: dict) -> dict:
    return next(site for site in snapshot["sites"] if site["site_name"] == "Vlaardingen")


def test_walk_ups_are_counted_in_the_main_dashboard_numbers(database: Session) -> None:
    before = _snapshot(database)
    registration, *_ = register_walk_up(database, **_details(database))
    admin = _admin(database)
    assert _vlaardingen(_snapshot(database))["present_count"] == _vlaardingen(before)["present_count"]  # registering is not entering

    admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    entered = _snapshot(database)
    for key in ("present_count", "grant_count", "entry_count"):
        assert _vlaardingen(entered)[key] == _vlaardingen(before)[key] + 1, key
        assert entered["totals"][key] == before["totals"][key] + 1, key
    assert _vlaardingen(entered)["active_visit_count"] == _vlaardingen(before)["active_visit_count"]  # no visit
    assert _vlaardingen(entered)["denial_count"] == _vlaardingen(before)["denial_count"]

    # An admitted person cannot be refused, so refuse another person.
    other, *_ = register_walk_up(database, **_details(database, first_name="Other", email="other@example.com"))
    refuse_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=other.id, reason="not_expected")
    refused = _snapshot(database)
    assert _vlaardingen(refused)["denial_count"] == _vlaardingen(entered)["denial_count"] + 1
    assert _vlaardingen(refused)["present_count"] == _vlaardingen(entered)["present_count"]

    record_exit(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    left = _snapshot(database)
    assert _vlaardingen(left)["present_count"] == _vlaardingen(before)["present_count"]
    assert _vlaardingen(left)["exit_count"] == _vlaardingen(before)["exit_count"] + 1


def test_the_dashboard_splits_planned_and_unexpected_arrivals(database: Session) -> None:
    before = _snapshot(database)
    site_before = _vlaardingen(before)["by_path"]
    registration, *_ = register_walk_up(database, **_details(database, first_name="Split", email="split@example.com"))
    admin = _admin(database)

    admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    entered = _snapshot(database)
    site = _vlaardingen(entered)["by_path"]
    assert site["walk_up"]["present_count"] == site_before["walk_up"]["present_count"] + 1
    assert site["walk_up"]["entry_count"] == site_before["walk_up"]["entry_count"] + 1
    assert site["planned"] == site_before["planned"]  # an unexpected arrival never changes the planned counts
    for key in ("present_count", "entry_count", "exit_count"):
        # planned plus unexpected always equals the figure shown in the main tiles
        assert site["planned"][key] + site["walk_up"][key] == _vlaardingen(entered)[key]
        assert entered["totals"]["by_path"]["planned"][key] + entered["totals"]["by_path"]["walk_up"][key] == entered["totals"][key]

    record_exit(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    left = _vlaardingen(_snapshot(database))["by_path"]
    assert left["walk_up"]["present_count"] == site_before["walk_up"]["present_count"]
    assert left["walk_up"]["exit_count"] == site_before["walk_up"]["exit_count"] + 1
    assert left["planned"] == site_before["planned"]


def test_walk_ups_appear_in_the_roster_and_the_recent_decisions(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database, first_name="Roster", email="roster@example.com"))
    admin = _admin(database)
    admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    other, *_ = register_walk_up(database, **_details(database, first_name="Turned", email="turned@example.com"))
    refuse_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=other.id, reason="identity_mismatch")
    snapshot = _snapshot(database)

    rows = [r for r in snapshot["current_presence"] if r.get("source") == "walk_up"]
    mine = next(r for r in rows if r["walk_up_registration_id"] == registration.id)
    assert mine["visit_id"] is None and mine["gate_event_id"] is None and mine["visit_ends_at"] is None
    assert mine["person_name"] == "Roster Jansen" and mine["decision"] == "GRANT" and mine["site_key"] == "vlaardingen"

    decisions = [d for d in snapshot["recent_decisions"] if d.get("source") == "walk_up"]
    by_name = {d["person_name"]: d for d in decisions}
    assert by_name["Roster Jansen"]["decision"] == "GRANT" and by_name["Roster Jansen"]["visit_id"] is None
    assert by_name["Turned Jansen"]["decision"] == "DENY" and by_name["Turned Jansen"]["reason_codes"] == ["identity_mismatch"]
    times = [d["occurred_at"] for d in snapshot["recent_decisions"]]
    assert times == sorted(times, reverse=True)


def test_the_presence_list_used_by_expiry_features_never_includes_walk_ups(database: Session) -> None:
    from app.services.batch5 import list_current_presence

    registration, *_ = register_walk_up(database, **_details(database, first_name="Hidden", email="hidden@example.com"))
    admit_at_gate(database, actor=_admin(database), site_key_value="vlaardingen", registration_id=registration.id)
    assert all(row["visit_id"] is not None for row in list_current_presence(database))


def test_the_presence_and_dashboard_apis_return_walk_ups(database: Session) -> None:
    from app.routes import batch5 as batch5_routes

    registration, *_ = register_walk_up(database, **_details(database, first_name="Api", email="api@example.com"))
    admit_at_gate(database, actor=_admin(database), site_key_value="vlaardingen", registration_id=registration.id)
    database.commit()
    app = FastAPI()
    app.include_router(batch5_routes.router)
    app.dependency_overrides[get_db] = lambda: database
    app.dependency_overrides[get_current_user] = lambda: _admin(database)
    api = TestClient(app)
    presence = api.get("/api/presence")
    assert presence.status_code == 200
    mine = [r for r in presence.json() if r["walk_up_registration_id"] == str(registration.id)]
    assert len(mine) == 1 and mine[0]["source"] == "walk_up" and mine[0]["visit_id"] is None
    assert all(r["source"] in ("walk_up", "invitation") for r in presence.json())
    dashboard = api.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert any(r["walk_up_registration_id"] == str(registration.id) for r in dashboard.json()["current_presence"])
    assert dashboard.json()["totals"]["present_count"] == len(dashboard.json()["current_presence"])


# --- every check at the kiosk is logged -----------------------------------------


def _lookups(database: Session, registration_id: uuid.UUID) -> list[AuditEvent]:
    return list(
        database.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "walk_up.looked_up", AuditEvent.entity_id == str(registration_id))
            .order_by(AuditEvent.occurred_at)
        ).all()
    )


def test_checking_someone_who_may_enter_is_logged_without_the_code(database: Session) -> None:
    import json

    registration, _site, _rules, _ack, secret = register_walk_up(database, **_details(database))
    admin = _admin(database)
    state = lookup_for_gate(
        database, actor=admin, site_key_value="vlaardingen",
        code=f"renewi-walkup:{registration.id.hex[:8].upper()}:{secret}",
    )
    assert state["eligible"] is True
    events = _lookups(database, registration.id)
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == admin.id
    assert event.details["method"] == "qr" and event.details["result"] == "may_enter"
    assert event.details["already_admitted"] is False
    assert event.details["person_id"] == str(registration.person_id)
    assert secret not in json.dumps(event.details) and secret not in event.reason
    assert _refusals(database, registration.id) == []  # a lookup is not a refusal


def test_a_typed_reference_is_logged_as_a_reference_and_repeats_are_not_logged_again(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    admin = _admin(database)
    code = registration.id.hex[:8]
    lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code=code)
    lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code=code.upper())
    events = _lookups(database, registration.id)
    assert len(events) == 1 and events[0].details["method"] == "reference"

    events[0].occurred_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    database.flush()
    lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code=code)
    assert len(_lookups(database, registration.id)) == 2


def test_a_check_after_entry_records_that_the_person_was_already_in(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    admin = _admin(database)
    admit_at_gate(database, actor=admin, site_key_value="vlaardingen", registration_id=registration.id)
    lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert [e.details["already_admitted"] for e in _lookups(database, registration.id)] == [True]


def test_two_officers_checking_the_same_person_are_both_logged(database: Session) -> None:
    from app.models import Role, UserAccount

    registration, *_ = register_walk_up(database, **_details(database))
    second = UserAccount(
        id=uuid.uuid4(), handle=f"gate-{uuid.uuid4().hex[:6]}", display_name="Second officer",
        password_hash="x", role=Role.GATE_OPERATOR, is_active=True,
    )
    database.add(second)
    database.flush()
    for officer in (_admin(database), second):
        lookup_for_gate(database, actor=officer, site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert {e.actor_id for e in _lookups(database, registration.id)} == {_admin(database).id, second.id}


def test_refused_and_unknown_checks_are_logged_as_those_not_as_lookups(database: Session) -> None:
    registration, *_ = register_walk_up(database, **_details(database))
    _make_rules_outdated(database)
    admin = _admin(database)
    lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code=registration.id.hex[:8])
    assert _lookups(database, registration.id) == [] and len(_refusals(database, registration.id)) == 1
    with pytest.raises(WorkflowError):
        lookup_for_gate(database, actor=admin, site_key_value="vlaardingen", code="no-such-code-anywhere")
    assert database.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "walk_up.looked_up", AuditEvent.entity_id == str(registration.id))
    ) == 0


def test_the_kiosk_endpoint_writes_the_lookup_event(client: TestClient, database: Session) -> None:
    receipt = client.post("/api/walk-up/registrations", json=_body(database)).json()
    database.commit()
    client.app.dependency_overrides[get_current_user] = lambda: _admin(database)
    found = client.post("/api/walk-up/gate/lookup", json={"site_key": "vlaardingen", "code": receipt["reference"]}).json()
    assert len(_lookups(database, uuid.UUID(found["registration_id"]))) == 1


# --- the entry QR is also emailed ---------------------------------------------


def test_the_entry_qr_is_emailed_to_the_verified_address(checked_client: TestClient, database: Session) -> None:
    import base64

    started = checked_client.post("/api/walk-up/registrations", json=_body(database)).json()
    code = checked_client.sent[0]["code"]
    database.commit()
    assert checked_client.passes == []  # nothing is sent until the code is right

    ok = checked_client.post(
        "/api/walk-up/registrations/verify", json={"pending_id": started["pending_id"], "code": code}
    )
    assert ok.status_code == 201
    receipt = ok.json()
    assert receipt["emailed_to"] == "a***@example.com"
    assert len(checked_client.passes) == 1
    mail = checked_client.passes[0]
    assert mail["to"] == "anna.deboer@example.com" and mail["reference"] == receipt["reference"]
    assert mail["site_name"] == "Vlaardingen" and mail["first_name"] == "Anna"
    assert mail["qr_png"][:8] == b"\x89PNG\r\n\x1a\n"
    # The emailed image is the one shown on the page.
    assert mail["qr_png"] == base64.b64decode(receipt["pass_qr"].split(",", 1)[1])


def test_a_failed_qr_email_does_not_undo_the_registration(checked_client: TestClient, database: Session, monkeypatch) -> None:
    from app.providers.walk_up_email import WalkUpEmailError

    def boom(settings, **kw):
        raise WalkUpEmailError("down")

    monkeypatch.setattr(walk_up_routes, "send_walk_up_pass_email", boom)
    started = checked_client.post("/api/walk-up/registrations", json=_body(database)).json()
    code = checked_client.sent[0]["code"]
    database.commit()
    ok = checked_client.post(
        "/api/walk-up/registrations/verify", json={"pending_id": started["pending_id"], "code": code}
    )
    assert ok.status_code == 201 and ok.json()["pass_qr"].startswith("data:image/png")
    assert database.scalar(select(func.count()).select_from(WalkUpRegistration)) >= 1


def test_without_the_email_check_the_qr_is_not_emailed(client: TestClient, database: Session, monkeypatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(walk_up_routes, "send_walk_up_pass_email", lambda settings, **kw: sent.append(kw))
    ok = client.post("/api/walk-up/registrations", json=_body(database))
    assert ok.status_code == 201 and ok.json()["emailed_to"] is None
    assert sent == []  # the address was never verified, so nothing is sent to it


def test_people_still_inside_after_their_exit_time_are_flagged_overdue_and_counted(database: Session) -> None:
    before = _snapshot(database)
    registration, *_ = register_walk_up(database, **_details(database, first_name="Late", email="late@example.com"))
    admit_at_gate(database, actor=_admin(database), site_key_value="vlaardingen", registration_id=registration.id)
    inside = _snapshot(database)
    assert _vlaardingen(inside)["overdue_count"] == _vlaardingen(before)["overdue_count"]

    registration.pass_expires_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    database.flush()
    late = _snapshot(database)
    site = _vlaardingen(late)
    assert site["overdue_count"] == _vlaardingen(before)["overdue_count"] + 1
    assert site["by_path"]["walk_up"]["overdue_count"] == _vlaardingen(before)["by_path"]["walk_up"]["overdue_count"] + 1
    assert late["totals"]["overdue_count"] == before["totals"]["overdue_count"] + 1
    assert site["present_count"] == _vlaardingen(inside)["present_count"]  # still counted as on site
    row = next(r for r in late["current_presence"] if r.get("walk_up_registration_id") == registration.id)
    assert row["overdue"] is True and row["overdue_minutes"] >= 29

    record_exit(database, actor=_admin(database), site_key_value="vlaardingen", registration_id=registration.id)
    assert _vlaardingen(_snapshot(database))["overdue_count"] == _vlaardingen(before)["overdue_count"]


def test_an_invited_person_still_inside_after_their_visit_ended_is_not_lost(database: Session) -> None:
    """The invitation projection drops them at the visit end; the dashboard keeps and flags them."""

    from app.models import GateEvent, PresenceEvent, Visit
    from app.services.batch5 import _current_presence_rows

    snapshot = _snapshot(database)
    as_of = snapshot["as_of"]
    ended = _current_presence_rows(database, observed_at=as_of, ended_only=True)
    live = {row["visit_id"] for row in _current_presence_rows(database, observed_at=as_of)}
    assert not {row["visit_id"] for row in ended} & live  # never both lists
    flagged = [row for row in snapshot["current_presence"] if row.get("visit_id") in {r["visit_id"] for r in ended}]
    assert len(flagged) == len(ended) and all(row["overdue"] for row in flagged)
