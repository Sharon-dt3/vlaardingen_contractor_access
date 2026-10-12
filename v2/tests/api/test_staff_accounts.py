"""Adding staff by invitation, setting a password, and signing in safely."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import AccountToken, AuditEvent, LifeSavingRulesVersion, Role, UserAccount
from app.routes import auth as auth_routes
from app.routes import users as users_routes
from app.security import get_current_user, hash_password, verify_password
from app.services.accounts import (
    MAX_FAILED_ATTEMPTS,
    accept_invitation,
    hash_token,
    invite_staff,
    look_up_invitation,
    password_problem,
    resend_invitation,
    set_active,
    status_of,
)
from app.services.workflows import WorkflowError

GOOD = "Correct-horse-9battery"


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
        session.scalar(select(func.count()).select_from(AccountToken))
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


def _email() -> str:
    return f"staff.{uuid.uuid4().hex[:8]}@example.com"


def _invite(database: Session, role: str = "gate_operator", email: str | None = None):
    return invite_staff(database, actor=_admin(database), name="Gina Gate", email=email or _email(), role_key=role)


def test_the_password_rules() -> None:
    assert password_problem(GOOD, email="a@example.com") is None
    assert "at least 12" in password_problem("Short1!")
    assert password_problem("aaaaaaaaaaaaaaaa1")  # too repetitive
    assert password_problem("password12345")  # common
    assert password_problem("onlyletterslonglong")  # no number or symbol
    assert "email" in password_problem("piet.jansen-2026!", email="piet.jansen@example.com")
    assert password_problem("x" * 200 + "1")


def test_an_invitation_creates_an_inactive_account_and_stores_only_a_hash(database: Session) -> None:
    account, secret = _invite(database, role="system_admin")
    assert account.is_active is False and status_of(account) == "invited"
    assert account.handle == account.email and account.role == Role.SYSTEM_ADMIN
    assert account.password_hash == "!invited" and not verify_password("!invited", account.password_hash)
    token = database.scalar(select(AccountToken).where(AccountToken.account_id == account.id))
    assert token.token_hash == hash_token(secret) and secret not in token.token_hash
    assert timedelta(hours=47) < token.expires_at - datetime.now(timezone.utc) <= timedelta(hours=48)
    event = database.scalar(select(AuditEvent).where(AuditEvent.action == "user.invited", AuditEvent.entity_id == str(account.id)))
    assert event.details["role"] == "system_admin" and event.actor_id == _admin(database).id


def test_only_two_roles_and_no_duplicates(database: Session) -> None:
    with pytest.raises(WorkflowError) as bad_role:
        _invite(database, role="viewer")
    assert bad_role.value.status_code == 422
    email = _email()
    _invite(database, email=email)
    with pytest.raises(WorkflowError) as duplicate:
        _invite(database, email=email.upper())
    assert duplicate.value.status_code == 409
    with pytest.raises(WorkflowError) as long_email:
        _invite(database, email="a" * 60 + "@example.com")
    assert long_email.value.status_code == 422


def test_the_person_sets_their_own_password_once(database: Session) -> None:
    account, secret = _invite(database)
    assert look_up_invitation(database, secret).id == account.id
    with pytest.raises(WorkflowError) as weak:
        accept_invitation(database, secret=secret, password="short")
    assert weak.value.status_code == 422 and status_of(account) == "invited"  # a weak password does not spend the link

    activated = accept_invitation(database, secret=secret, password=GOOD)
    assert activated.is_active and status_of(activated) == "active"
    assert verify_password(GOOD, activated.password_hash)
    with pytest.raises(WorkflowError) as again:
        accept_invitation(database, secret=secret, password=GOOD + "x")
    assert again.value.status_code == 404
    with pytest.raises(WorkflowError):
        look_up_invitation(database, secret)
    assert database.scalar(select(AuditEvent).where(AuditEvent.action == "user.activated", AuditEvent.entity_id == str(account.id)))


def test_an_expired_or_replaced_link_does_not_work(database: Session) -> None:
    account, secret = _invite(database)
    token = database.scalar(select(AccountToken).where(AccountToken.account_id == account.id))
    token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    database.flush()
    with pytest.raises(WorkflowError):
        accept_invitation(database, secret=secret, password=GOOD)

    account2, old = _invite(database)
    _acc, new = resend_invitation(database, actor=_admin(database), account_id=account2.id)
    assert new != old
    with pytest.raises(WorkflowError):
        accept_invitation(database, secret=old, password=GOOD)  # the earlier link stopped working
    assert accept_invitation(database, secret=new, password=GOOD).is_active
    with pytest.raises(WorkflowError):
        resend_invitation(database, actor=_admin(database), account_id=account2.id)  # already active


@pytest.fixture()
def client(database: Session):
    app = FastAPI()
    app.include_router(auth_routes.router)
    app.include_router(users_routes.router)
    app.dependency_overrides[get_db] = lambda: database
    auth_routes._login_limiter.reset()
    users_routes._link_limiter.reset()
    return TestClient(app)


def _activate(database: Session, role: str = "gate_operator") -> tuple[UserAccount, str]:
    account, secret = _invite(database, role=role)
    accept_invitation(database, secret=secret, password=GOOD)
    database.flush()
    return account, GOOD


def test_sign_in_works_and_every_outcome_is_audited(client: TestClient, database: Session) -> None:
    account, password = _activate(database)
    ok = client.post("/auth/login", json={"handle": account.email.upper(), "password": password})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "gate_operator"
    assert "session" in ok.headers["set-cookie"].lower() or "httponly" in ok.headers["set-cookie"].lower()
    assert database.scalar(select(UserAccount).where(UserAccount.id == account.id)).last_login_at is not None
    assert database.scalar(select(AuditEvent).where(AuditEvent.action == "auth.login", AuditEvent.entity_id == str(account.id)))


def test_five_wrong_passwords_lock_the_account_and_the_answer_never_says_why(client: TestClient, database: Session) -> None:
    account, password = _activate(database)
    unknown = client.post("/auth/login", json={"handle": "nobody@example.com", "password": "Whatever-123456"})
    wrong = client.post("/auth/login", json={"handle": account.email, "password": "Wrong-password-1"})
    assert unknown.status_code == wrong.status_code == 401 and unknown.json() == wrong.json()
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        assert client.post("/auth/login", json={"handle": account.email, "password": "Wrong-password-1"}).status_code == 401
    locked_now = database.get(UserAccount, account.id)
    assert locked_now.locked_until is not None and status_of(locked_now) == "locked"
    # Even the right password is refused during the lock, with the same words.
    refused = client.post("/auth/login", json={"handle": account.email, "password": password})
    assert refused.status_code == 401 and refused.json() == wrong.json()
    assert database.scalar(select(AuditEvent).where(AuditEvent.action == "auth.locked", AuditEvent.entity_id == str(account.id)))
    # After the lock passes, the right password works again.
    locked_now.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    database.flush()
    assert client.post("/auth/login", json={"handle": account.email, "password": password}).status_code == 200


def test_an_invited_or_deactivated_account_cannot_sign_in(client: TestClient, database: Session) -> None:
    waiting, _secret = _invite(database)
    assert client.post("/auth/login", json={"handle": waiting.email, "password": GOOD}).status_code == 401
    account, password = _activate(database)
    set_active(database, actor=_admin(database), account_id=account.id, active=False)
    assert client.post("/auth/login", json={"handle": account.email, "password": password}).status_code == 401
    set_active(database, actor=_admin(database), account_id=account.id, active=True)
    assert client.post("/auth/login", json={"handle": account.email, "password": password}).status_code == 200


def test_deactivation_rules(database: Session) -> None:
    admin = _admin(database)
    with pytest.raises(WorkflowError) as own:
        set_active(database, actor=admin, account_id=admin.id, active=False)
    assert own.value.status_code == 409
    other, _ = _activate(database, role="system_admin")
    # With two active administrators the second can be deactivated; the last cannot.
    others = database.scalars(select(UserAccount).where(UserAccount.role == Role.SYSTEM_ADMIN, UserAccount.is_active.is_(True))).all()
    for extra in others:
        if extra.id not in (admin.id, other.id):
            extra.is_active = False
    database.flush()
    set_active(database, actor=other, account_id=admin.id, active=False)
    with pytest.raises(WorkflowError) as last:
        set_active(database, actor=admin, account_id=other.id, active=False)
    assert last.value.status_code == 409 and "only active administrator" in last.value.detail
    waiting, _secret = _invite(database)
    with pytest.raises(WorkflowError):
        set_active(database, actor=other, account_id=waiting.id, active=False)


def test_the_users_api_is_for_administrators_only(client: TestClient, database: Session, monkeypatch) -> None:
    operator, _ = _activate(database)
    client.app.dependency_overrides[get_current_user] = lambda: operator
    body = {"name": "New Person", "email": _email(), "role": "gate_operator"}
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json=body).status_code == 403
    assert client.post(f"/api/users/{operator.id}/deactivate").status_code == 403

    monkeypatch.setattr(users_routes, "_send_invitation", lambda *args: True)
    client.app.dependency_overrides[get_current_user] = lambda: _admin(database)
    created = client.post("/api/users", json=body)
    assert created.status_code == 201 and created.json()["user"]["status"] == "invited" and created.json()["email_sent"] is True
    assert "token" not in created.text and "link" not in created.text.lower()  # the administrator never sees the link
    rows = client.get("/api/users").json()
    assert any(row["email"] == body["email"] and row["status"] == "invited" for row in rows)
    assert any(row["is_you"] and row["handle"] == "admin.demo" for row in rows)
    assert client.post("/api/users", json=body).status_code == 409
    assert client.post("/api/users", json={**body, "email": _email(), "role": "viewer"}).status_code == 422


def test_the_public_link_pages(client: TestClient, database: Session) -> None:
    account, secret = _invite(database)
    database.commit()  # the routes roll back a failed request, so the invitation must be saved first
    found = client.post("/auth/invitation", json={"token": secret})
    assert found.status_code == 200 and found.json()["email"] == account.email
    assert found.json()["role_label"] == "Gate operator" and found.headers["cache-control"] == "no-store"
    assert client.post("/auth/invitation", json={"token": "x" * 40}).status_code == 404
    weak = client.post("/auth/set-password", json={"token": secret, "password": "short"})
    assert weak.status_code == 422
    done = client.post("/auth/set-password", json={"token": secret, "password": GOOD})
    assert done.status_code == 204
    assert client.post("/auth/set-password", json={"token": secret, "password": GOOD}).status_code == 404


# --- forgot password, reset and change -----------------------------------------

import time
from contextlib import contextmanager
from types import SimpleNamespace

from app.config import get_settings
from app.services.accounts import (
    MAX_RESETS_PER_HOUR,
    change_password,
    complete_reset,
    look_up_reset,
    request_reset,
)

NEW = "Another-strong-pass-77"


def test_a_reset_link_is_made_only_for_a_real_active_account_and_is_limited(database: Session) -> None:
    account, _ = _activate(database)
    assert request_reset(database, email="nobody@example.com") is None
    waiting, _secret = _invite(database)
    assert request_reset(database, email=waiting.email) is None  # invited people use their invitation

    first = request_reset(database, email=account.email.upper())
    assert first is not None and first[0].id == account.id
    token = database.scalar(select(AccountToken).where(AccountToken.token_hash == hash_token(first[1])))
    assert token.kind == "reset" and token.expires_at - datetime.now(timezone.utc) <= timedelta(hours=1)
    second = request_reset(database, email=account.email)
    with pytest.raises(WorkflowError):
        look_up_reset(database, first[1])  # a newer link replaced it
    assert look_up_reset(database, second[1]).id == account.id
    for _ in range(MAX_RESETS_PER_HOUR):
        request_reset(database, email=account.email)
    assert request_reset(database, email=account.email) is None  # the hourly limit
    assert request_reset(database, email=account.email, actor=_admin(database), force=True) is not None


def test_a_reset_sets_the_password_once_and_ends_older_sessions(client: TestClient, database: Session) -> None:
    account, old_password = _activate(database)
    account.failed_attempts = 3
    database.flush()
    _acc, secret = request_reset(database, email=account.email)
    weak = None
    with pytest.raises(WorkflowError) as weak:
        complete_reset(database, secret=secret, password="short")
    assert weak.value.status_code == 422 and look_up_reset(database, secret)  # a weak password keeps the link

    logged_in = client.post("/auth/login", json={"handle": account.email, "password": old_password})
    cookie = client.cookies.get(get_settings().session_cookie_name)
    assert logged_in.status_code == 200 and client.get("/auth/me").status_code == 200
    time.sleep(1.1)
    complete_reset(database, secret=secret, password=NEW)
    database.commit()
    assert verify_password(NEW, account.password_hash) and account.failed_attempts == 0
    with pytest.raises(WorkflowError):
        complete_reset(database, secret=secret, password=NEW + "x")  # single use
    client.cookies.set(get_settings().session_cookie_name, cookie)
    assert client.get("/auth/me").status_code == 401  # the earlier session ended
    assert client.post("/auth/login", json={"handle": account.email, "password": old_password}).status_code == 401
    assert client.post("/auth/login", json={"handle": account.email, "password": NEW}).status_code == 200
    assert database.scalar(select(AuditEvent).where(AuditEvent.action == "auth.password_reset", AuditEvent.entity_id == str(account.id)))


def test_changing_your_own_password(client: TestClient, database: Session, monkeypatch) -> None:
    account, password = _activate(database)
    database.commit()
    sent = []
    monkeypatch.setattr(users_routes, "_send_changed_notice", lambda email, name: sent.append(email))
    client.post("/auth/login", json={"handle": account.email, "password": password})
    other_browser = client.cookies.get(get_settings().session_cookie_name)
    time.sleep(1.1)

    wrong = client.post("/auth/change-password", json={"current_password": "Not-my-password-1", "new_password": NEW})
    assert wrong.status_code == 422 and "current password" in wrong.json()["detail"]
    same = client.post("/auth/change-password", json={"current_password": password, "new_password": password})
    assert same.status_code == 422
    assert client.post("/auth/change-password", json={"current_password": password, "new_password": "weak"}).status_code == 422
    done = client.post("/auth/change-password", json={"current_password": password, "new_password": NEW})
    assert done.status_code == 204 and sent == [account.email]
    assert client.get("/auth/me").status_code == 200  # this browser stays signed in
    fresh = client.cookies.get(get_settings().session_cookie_name)
    client.cookies.set(get_settings().session_cookie_name, other_browser)
    assert client.get("/auth/me").status_code == 401  # any other browser is signed out
    client.cookies.set(get_settings().session_cookie_name, fresh)
    assert client.get("/auth/me").status_code == 200
    assert database.scalar(select(AuditEvent).where(AuditEvent.action == "auth.password_changed", AuditEvent.entity_id == str(account.id)))


def test_forgot_password_always_answers_the_same(client: TestClient, database: Session, monkeypatch) -> None:
    account, _ = _activate(database)
    database.commit()

    @contextmanager
    def _same_session():
        yield database

    monkeypatch.setattr("app.database.session.SessionLocal", _same_session)
    sent = []
    monkeypatch.setattr(users_routes, "_send_reset", lambda email, name, secret, admin: sent.append((email, admin)) or True)
    known = client.post("/auth/forgot-password", json={"email": account.email})
    unknown = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert sent == [(account.email, False)]  # only the real account got a link
    assert client.post("/auth/forgot-password", json={"email": "not an email"}).status_code == 422


def test_an_administrator_can_send_a_reset_but_never_sees_it(client: TestClient, database: Session, monkeypatch) -> None:
    account, _ = _activate(database)
    database.commit()
    monkeypatch.setattr(users_routes, "_send_reset", lambda email, name, secret, admin: admin is True)
    client.app.dependency_overrides[get_current_user] = lambda: account
    assert client.post(f"/api/users/{account.id}/send-reset").status_code == 403
    client.app.dependency_overrides[get_current_user] = lambda: _admin(database)
    sent = client.post(f"/api/users/{account.id}/send-reset")
    assert sent.status_code == 202 and sent.json() == {"email_sent": True}
    assert database.scalar(select(AuditEvent).where(AuditEvent.action == "user.reset_sent", AuditEvent.entity_id == str(account.id)))
    waiting, _secret = _invite(database)
    database.commit()
    assert client.post(f"/api/users/{waiting.id}/send-reset").status_code == 409
    assert client.post(f"/api/users/{_admin(database).id}/send-reset").status_code == 404  # the demo account has no email


def test_the_reset_link_pages(client: TestClient, database: Session) -> None:
    account, _ = _activate(database)
    _acc, secret = request_reset(database, email=account.email)
    database.commit()
    found = client.post("/auth/reset", json={"token": secret})
    assert found.status_code == 200 and found.json()["email"] == account.email
    assert client.post("/auth/reset", json={"token": "y" * 40}).status_code == 404
    assert client.post("/auth/reset-password", json={"token": secret, "password": "weak"}).status_code == 422
    assert client.post("/auth/reset-password", json={"token": secret, "password": NEW}).status_code == 204
    assert client.post("/auth/reset-password", json={"token": secret, "password": NEW}).status_code == 404
