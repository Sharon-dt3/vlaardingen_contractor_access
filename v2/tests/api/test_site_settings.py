"""Administrators set how long access lasts at a site; new QR codes follow it, issued ones do not."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import AuditEvent, LifeSavingRulesVersion, Role, Site, SiteAccessSettings, UserAccount
from app.routes import site_settings as settings_routes
from app.security import get_current_user
from app.services.life_saving import get_current_rules
from app.services.site_settings import DEFAULT_PASS_HOURS, DEFAULT_VISIT_HOURS, get_site_settings
from app.services.walk_up import lookup_for_gate, register_walk_up, site_for_key


@pytest.fixture()
def database():
    from app.database.session import engine

    try:
        connection = engine.connect()
    except Exception:  # pragma: no cover
        pytest.skip("PostgreSQL is not reachable.")
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        if not session.scalar(select(func.count()).select_from(LifeSavingRulesVersion)):
            pytest.skip("The database is not migrated and seeded.")
        session.scalar(select(func.count()).select_from(SiteAccessSettings))
        # An administrator may have changed the validity in the demo; tests assume the defaults.
        session.execute(delete(SiteAccessSettings))
    except Exception:  # pragma: no cover
        pytest.skip("The database is not migrated and seeded.")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _admin(database: Session) -> UserAccount:
    return database.scalar(select(UserAccount).where(UserAccount.handle == "admin.demo"))


def _register(database: Session):
    rules = get_current_rules(database)
    return register_walk_up(
        database,
        site_key_value="vlaardingen",
        first_name="Piet",
        last_name="Jansen",
        company_name="Settings Test B.V.",
        email=f"piet.{uuid.uuid4().hex[:6]}@example.com",
        population="maintenance_contractor",
        rules_version_id=rules.id,
        language="en",
        confirmed=True,
    )


@pytest.fixture()
def client(database: Session):
    app = FastAPI()
    app.include_router(settings_routes.router)
    app.dependency_overrides[get_db] = lambda: database
    app.dependency_overrides[get_current_user] = lambda: _admin(database)
    return TestClient(app)


def test_an_unconfigured_site_gets_the_defaults_and_reading_writes_nothing(database: Session) -> None:
    site = site_for_key(database, "vlaardingen")
    values = get_site_settings(database, site)
    assert (values.visit_default_hours, values.walk_up_pass_hours) == (DEFAULT_VISIT_HOURS, DEFAULT_PASS_HOURS)
    assert database.get(SiteAccessSettings, site.id) is None


def test_a_new_walk_up_qr_uses_the_configured_validity(database: Session, client: TestClient) -> None:
    default_registration, *_ = _register(database)
    assert default_registration.pass_expires_at - default_registration.registered_at == timedelta(hours=12)

    done = client.put("/api/site-settings/vlaardingen", json={"visit_default_hours": 6, "walk_up_pass_hours": 4})
    assert done.status_code == 200 and done.json()["walk_up_pass_hours"] == 4

    shorter, *_ = _register(database)
    assert shorter.pass_expires_at - shorter.registered_at == timedelta(hours=4)
    # The QR issued before the change keeps its 12 hours.
    assert default_registration.pass_expires_at - default_registration.registered_at == timedelta(hours=12)


def test_the_kiosk_follows_each_qrs_own_expiry(database: Session) -> None:
    registration, _site, _rules, _ack, secret = _register(database)
    registration.pass_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    database.flush()
    found = lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=secret)
    assert found["registration_id"] == registration.id
    registration.pass_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    database.flush()
    from app.services.workflows import WorkflowError

    with pytest.raises(WorkflowError) as expired:
        lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=secret)
    assert expired.value.status_code == 404


def test_the_list_and_update_round_trip_and_are_audited(database: Session, client: TestClient) -> None:
    listed = client.get("/api/site-settings").json()
    row = next(item for item in listed if item["site_key"] == "vlaardingen")
    assert row["visit_default_hours"] == 8 and row["walk_up_pass_hours"] == 12 and row["site_name"] == "Vlaardingen"
    assert client.get("/api/site-settings/vlaardingen").json()["site_id"] == row["site_id"]

    assert client.put(
        "/api/site-settings/vlaardingen", json={"visit_default_hours": 10, "walk_up_pass_hours": 24}
    ).status_code == 200
    assert client.get("/api/site-settings/vlaardingen").json()["visit_default_hours"] == 10
    event = database.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "site_settings.updated")
        .order_by(AuditEvent.occurred_at.desc())
    )
    assert event is not None
    assert event.details["before"] == {
        "visit_default_hours": 8, "walk_up_pass_hours": 12, "access_qr_max_hours": 24, "walk_up_entry_delay_minutes": 0,
    }
    assert event.details["after"] == {
        "visit_default_hours": 10, "walk_up_pass_hours": 24, "access_qr_max_hours": 24, "walk_up_entry_delay_minutes": 0,
    }


@pytest.mark.parametrize(
    "body",
    [
        {"visit_default_hours": 0, "walk_up_pass_hours": 12},
        {"visit_default_hours": 169, "walk_up_pass_hours": 12},
        {"visit_default_hours": 8, "walk_up_pass_hours": 0},
        {"visit_default_hours": 8, "walk_up_pass_hours": 73},
        {"visit_default_hours": "eight", "walk_up_pass_hours": 12},
        {"visit_default_hours": 8},
        {"visit_default_hours": 8, "walk_up_pass_hours": 12, "extra": 1},
    ],
)
def test_out_of_range_or_malformed_values_are_rejected(client: TestClient, body: dict) -> None:
    assert client.put("/api/site-settings/vlaardingen", json=body).status_code == 422


def test_only_an_administrator_can_change_it_and_unknown_sites_are_404(database: Session, client: TestClient) -> None:
    host = UserAccount(
        id=uuid.uuid4(), handle=f"host-{uuid.uuid4().hex[:6]}", display_name="Host", password_hash="x",
        role=Role.HOST, is_active=True,
    )
    database.add(host)
    database.flush()
    client.app.dependency_overrides[get_current_user] = lambda: host
    body = {"visit_default_hours": 8, "walk_up_pass_hours": 12}
    assert client.put("/api/site-settings/vlaardingen", json=body).status_code == 403
    assert client.get("/api/site-settings/vlaardingen").status_code == 200  # staff may read
    client.app.dependency_overrides[get_current_user] = lambda: _admin(database)
    assert client.put("/api/site-settings/nowhere", json=body).status_code == 404


# --- entry and exit times shown to the person --------------------------------


def test_the_entry_and_exit_times_are_written_in_the_sites_time_zone() -> None:
    from app.providers.time_format import entry_exit_lines

    start = datetime(2026, 10, 12, 11, 30, tzinfo=timezone.utc)  # 13:30 in Amsterdam (summer time)
    end = datetime(2026, 10, 12, 17, 45, tzinfo=timezone.utc)
    text = entry_exit_lines(start, end, "Europe/Amsterdam")
    assert "Entry from: Mon 12 Oct 2026, 13:30 (Europe/Amsterdam)" in text
    assert "Exit by: Mon 12 Oct 2026, 19:45 (Europe/Amsterdam)" in text
    assert "Entry from" not in entry_exit_lines(None, end, "Europe/Amsterdam")
    assert "(UTC)" in entry_exit_lines(start, end, "Not/AZone")


def _sent_text(monkeypatch, sender, **kwargs) -> str:
    import smtplib

    from pydantic import SecretStr

    from app.config import Settings

    captured = {}

    class FakeSMTP:
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): ...
        def starttls(self): ...
        def login(self, *a): ...
        def send_message(self, message):
            body = message.get_body(preferencelist=("plain",))
            captured["text"] = body.get_content()

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = Settings.model_construct(
        smtp_host="h", smtp_port=587, smtp_username="u", smtp_password=SecretStr("p"), smtp_from_address="a@example.com"
    )
    sender(settings, **kwargs)
    return captured["text"]


def test_the_walk_up_email_states_when_entry_opens_and_when_the_qr_stops(monkeypatch) -> None:
    from app.providers.walk_up_email import send_walk_up_pass_email

    start = datetime(2026, 10, 12, 11, 30, tzinfo=timezone.utc)
    text = _sent_text(
        monkeypatch,
        send_walk_up_pass_email,
        to="p@example.com", first_name="Piet", site_name="Vlaardingen", reference="ABCD1234",
        valid_until=start + timedelta(hours=4), valid_from=start, timezone_name="Europe/Amsterdam",
        qr_png=b"\x89PNG",
    )
    assert "Entry from: Mon 12 Oct 2026, 13:30 (Europe/Amsterdam)" in text
    assert "Exit by: Mon 12 Oct 2026, 17:30 (Europe/Amsterdam)" in text


def test_the_walk_up_receipt_carries_the_site_time_zone(database: Session) -> None:
    from app.routes import walk_up as walk_up_routes

    app = FastAPI()
    app.include_router(walk_up_routes.router)
    app.dependency_overrides[get_db] = lambda: database
    walk_up_routes._registration_limiter.reset()
    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as patch:
        patch.setattr(walk_up_routes, "email_check_enabled", lambda: False)
        rules = get_current_rules(database)
        receipt = TestClient(app).post(
            "/api/walk-up/registrations",
            json={
                "site_key": "vlaardingen", "first_name": "Piet", "last_name": "Jansen",
                "company_name": "Receipt Test B.V.", "email": f"r.{uuid.uuid4().hex[:6]}@example.com",
                "population": "visitor", "rules_version_id": str(rules.id), "language": "en", "confirmed": True,
            },
        )
    assert receipt.status_code == 201
    assert receipt.json()["site_timezone"] == "Europe/Amsterdam"


def test_the_access_qr_email_states_the_visit_window(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.providers.invitation_email import send_access_token_email

    start = datetime(2026, 10, 12, 11, 30, tzinfo=timezone.utc)
    token = SimpleNamespace(id=uuid.uuid4(), expires_at=start + timedelta(hours=6))
    text = _sent_text(
        monkeypatch,
        lambda settings, **kw: send_access_token_email(
            settings, SimpleNamespace(invitee_email="p@example.com"),
            SimpleNamespace(name="Vlaardingen", timezone="Europe/Amsterdam"), token, "payload", **kw,
        ),
        valid_from=start,
    )
    assert "Entry from: Mon 12 Oct 2026, 13:30 (Europe/Amsterdam)" in text
    assert "Exit by: Mon 12 Oct 2026, 19:30 (Europe/Amsterdam)" in text


# --- longest access QR, and the walk-up entry time -----------------------------


def _visit_window(starts: datetime, ends: datetime):
    from types import SimpleNamespace

    return SimpleNamespace(site_id=None, starts_at=starts, ends_at=ends)


def test_the_longest_access_qr_caps_the_default_and_refuses_a_longer_choice(database: Session) -> None:
    from app.services.site_settings import access_qr_window, update_site_settings
    from app.services.workflows import WorkflowError

    site = site_for_key(database, "vlaardingen")
    update_site_settings(
        database, actor=_admin(database), site=site, visit_default_hours=8, walk_up_pass_hours=12,
        access_qr_max_hours=6, walk_up_entry_delay_minutes=0,
    )
    now = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
    visit = _visit_window(now, now + timedelta(hours=10))
    visit.site_id = site.id

    # No exit chosen: the QR runs to the longest allowed, not to the end of a 10 hour visit.
    _start, expiry = access_qr_window(database, visit=visit, requested_start=None, requested_expiry=None, now=now)
    assert expiry == now + timedelta(hours=6)
    # An exit inside the limit is kept exactly.
    chosen = now + timedelta(hours=3)
    assert access_qr_window(database, visit=visit, requested_start=None, requested_expiry=chosen, now=now)[1] == chosen
    # An exit beyond the limit is refused, so nobody gets a shorter QR than they asked for.
    with pytest.raises(WorkflowError) as refused:
        access_qr_window(database, visit=visit, requested_start=None, requested_expiry=now + timedelta(hours=7), now=now)
    assert refused.value.status_code == 422 and "at most 6 hours" in refused.value.detail
    # A short visit is never stretched.
    short = _visit_window(now, now + timedelta(hours=2))
    short.site_id = site.id
    assert access_qr_window(database, visit=short, requested_start=None, requested_expiry=None, now=now)[1] == now + timedelta(hours=2)


def test_a_walk_up_qr_opens_after_the_configured_delay_and_the_kiosk_waits(database: Session, client: TestClient) -> None:
    assert client.put(
        "/api/site-settings/vlaardingen",
        json={"visit_default_hours": 8, "walk_up_pass_hours": 3, "access_qr_max_hours": 24, "walk_up_entry_delay_minutes": 30},
    ).status_code == 200
    registration, _site, _rules, _ack, secret = _register(database)
    assert registration.pass_valid_from - registration.registered_at == timedelta(minutes=30)
    # The exit is counted from when the QR opens.
    assert registration.pass_expires_at - registration.pass_valid_from == timedelta(hours=3)

    early = lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=secret)
    assert early["eligible"] is False and [r["code"] for r in early["reasons"]] == ["PASS_NOT_YET_VALID"]
    assert early["pass_valid_from"] == registration.pass_valid_from
    assert early["pass_valid_until"] == registration.pass_expires_at and early["site_timezone"] == "Europe/Amsterdam"

    from app.services.walk_up import admit_at_gate
    from app.services.workflows import WorkflowError

    with pytest.raises(WorkflowError) as refused:
        admit_at_gate(database, actor=_admin(database), site_key_value="vlaardingen", registration_id=registration.id)
    assert refused.value.status_code == 409 and "not valid yet" in refused.value.detail

    # Once the entry time has passed, the same QR works.
    registration.pass_valid_from = datetime.now(timezone.utc) - timedelta(minutes=1)
    database.flush()
    assert lookup_for_gate(database, actor=_admin(database), site_key_value="vlaardingen", code=secret)["eligible"] is True


def test_the_new_settings_are_validated(client: TestClient) -> None:
    base = {"visit_default_hours": 8, "walk_up_pass_hours": 12}
    for bad in ({"access_qr_max_hours": 0}, {"access_qr_max_hours": 169}, {"walk_up_entry_delay_minutes": -1}, {"walk_up_entry_delay_minutes": 241}):
        assert client.put("/api/site-settings/vlaardingen", json={**base, **bad}).status_code == 422
