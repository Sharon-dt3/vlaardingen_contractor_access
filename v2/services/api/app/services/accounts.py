"""Staff accounts: inviting people, setting passwords, and keeping sign-in safe."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AccountToken, Role, UserAccount
from app.security import hash_password
from app.services.audit import append_audit_event
from app.services.workflows import WorkflowError

INVITE_VALID_HOURS = 48
RESET_VALID_HOURS = 1
MAX_RESETS_PER_HOUR = 3
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
# The only two roles staff are invited as for now.
INVITABLE_ROLES = {"system_admin": Role.SYSTEM_ADMIN, "gate_operator": Role.GATE_OPERATOR}
ROLE_LABELS = {Role.SYSTEM_ADMIN: "Administrator", Role.GATE_OPERATOR: "Gate operator"}
_COMMON = frozenset(
    {
        "password1234", "password12345", "123456789012", "qwertyuiop12", "welcome12345",
        "letmein12345", "administrator", "renewi-demo-access", "changeme1234",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(secret: str) -> str:
    """The stored form of a link's secret."""

    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


# PUBLIC_INTERFACE
def password_problem(password: str, *, email: str = "") -> str | None:
    """Why a password is not acceptable, or ``None`` when it is."""

    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Use at most {MAX_PASSWORD_LENGTH} characters."
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) < 5:
        return "That password is too easy to guess. Choose something less predictable."
    local = email.split("@", 1)[0].lower()
    if email and (lowered == email.lower() or (len(local) >= 4 and local in lowered)):
        return "Do not use your email address in your password."
    if not any(character.isalpha() for character in password) or not any(
        character.isdigit() or not character.isalnum() for character in password
    ):
        return "Mix letters with numbers or symbols."
    return None


# PUBLIC_INTERFACE
def status_of(account: UserAccount) -> str:
    """invited, active, locked or deactivated."""

    if not account.is_active:
        return "invited" if account.password_changed_at is None and account.email else "deactivated"
    if account.locked_until is not None and account.locked_until > _now():
        return "locked"
    return "active"


def _new_token(database: Session, *, account: UserAccount, kind: str, actor: UserAccount | None, hours: int) -> str:
    secret = secrets.token_urlsafe(32)
    database.add(
        AccountToken(
            id=uuid.uuid4(),
            account_id=account.id,
            kind=kind,
            token_hash=hash_token(secret),
            expires_at=_now() + timedelta(hours=hours),
            created_at=_now(),
            created_by_id=actor.id if actor else None,
        )
    )
    return secret


def _spend_open_tokens(database: Session, account_id: uuid.UUID, kind: str) -> None:
    for token in database.scalars(
        select(AccountToken).where(
            AccountToken.account_id == account_id, AccountToken.kind == kind, AccountToken.used_at.is_(None)
        )
    ).all():
        token.used_at = _now()


# PUBLIC_INTERFACE
def list_accounts(database: Session) -> list[UserAccount]:
    """Every staff account, administrators first."""

    return list(
        database.scalars(select(UserAccount).order_by(UserAccount.role, func.lower(UserAccount.display_name))).all()
    )


# PUBLIC_INTERFACE
def invite_staff(
    database: Session, *, actor: UserAccount, name: str, email: str, role_key: str
) -> tuple[UserAccount, str]:
    """Create an inactive account and return it with the invitation secret (never stored)."""

    role = INVITABLE_ROLES.get(role_key)
    if role is None:
        raise WorkflowError(422, "Choose Administrator or Gate operator.")
    email_key = email.strip().lower()
    if len(email_key) > 64:
        raise WorkflowError(422, "That email address is too long to use as a sign-in name (64 characters at most).")
    taken = database.scalar(
        select(UserAccount).where(
            (func.lower(UserAccount.email) == email_key) | (UserAccount.handle == email_key)
        )
    )
    if taken is not None:
        raise WorkflowError(
            409,
            "That email address already has an account. Use Resend invitation if they have not set a password yet.",
        )
    account = UserAccount(
        id=uuid.uuid4(),
        handle=email_key,
        email=email_key,
        display_name=" ".join(name.split()),
        # Not a valid hash, so nothing can sign in until the person sets a password.
        password_hash="!invited",
        role=role,
        is_active=False,
        failed_attempts=0,
        created_by_id=actor.id,
    )
    database.add(account)
    database.flush()
    secret = _new_token(database, account=account, kind="invite", actor=actor, hours=INVITE_VALID_HOURS)
    append_audit_event(
        database,
        actor=actor,
        action="user.invited",
        entity_type="user_account",
        entity_id=str(account.id),
        reason="An administrator invited a new staff member.",
        details={"email": email_key, "role": role.value},
    )
    return account, secret


# PUBLIC_INTERFACE
def resend_invitation(database: Session, *, actor: UserAccount, account_id: uuid.UUID) -> tuple[UserAccount, str]:
    """Replace the open invitation with a fresh one for someone who has not set a password."""

    account = database.get(UserAccount, account_id)
    if account is None or status_of(account) != "invited":
        raise WorkflowError(409, "Only people who have not set a password yet can be sent a new invitation.")
    _spend_open_tokens(database, account.id, "invite")
    secret = _new_token(database, account=account, kind="invite", actor=actor, hours=INVITE_VALID_HOURS)
    append_audit_event(
        database,
        actor=actor,
        action="user.invitation_resent",
        entity_type="user_account",
        entity_id=str(account.id),
        reason="An administrator sent a new invitation.",
        details={"email": account.email},
    )
    return account, secret


def _usable_token(database: Session, secret: str, kind: str) -> AccountToken | None:
    token = database.scalar(
        select(AccountToken).where(AccountToken.token_hash == hash_token(secret.strip())).with_for_update()
    )
    if token is None or token.kind != kind or token.used_at is not None or token.expires_at <= _now():
        return None
    return token


# PUBLIC_INTERFACE
def look_up_invitation(database: Session, secret: str) -> UserAccount:
    """The account an unused, unexpired invitation belongs to."""

    token = _usable_token(database, secret, "invite")
    account = database.get(UserAccount, token.account_id) if token else None
    if account is None or status_of(account) != "invited":
        raise WorkflowError(404, "This link has expired or was already used. Ask an administrator for a new invitation.")
    return account


# PUBLIC_INTERFACE
def accept_invitation(database: Session, *, secret: str, password: str) -> UserAccount:
    """Spend the invitation: set the person's own password and activate the account."""

    token = _usable_token(database, secret, "invite")
    account = database.get(UserAccount, token.account_id) if token else None
    if token is None or account is None or status_of(account) != "invited":
        raise WorkflowError(404, "This link has expired or was already used. Ask an administrator for a new invitation.")
    problem = password_problem(password, email=account.email or "")
    if problem:
        raise WorkflowError(422, problem)
    account.password_hash = hash_password(password)
    account.password_changed_at = _now()
    account.is_active = True
    account.failed_attempts = 0
    account.locked_until = None
    token.used_at = _now()
    append_audit_event(
        database,
        actor=None,
        action="user.activated",
        entity_type="user_account",
        entity_id=str(account.id),
        reason="The invited person set their own password and activated the account.",
        details={"email": account.email, "role": account.role.value},
    )
    return account


def _active_admin_count(database: Session) -> int:
    return database.scalar(
        select(func.count()).select_from(UserAccount).where(
            UserAccount.role == Role.SYSTEM_ADMIN, UserAccount.is_active.is_(True)
        )
    ) or 0


# PUBLIC_INTERFACE
def set_active(database: Session, *, actor: UserAccount, account_id: uuid.UUID, active: bool) -> UserAccount:
    """Deactivate (sessions end at once) or reactivate an account that has a password."""

    account = database.get(UserAccount, account_id)
    if account is None:
        raise WorkflowError(404, "That account does not exist.")
    if status_of(account) == "invited":
        raise WorkflowError(409, "They have not set a password yet. Resend the invitation, or ask them to use it.")
    if account.id == actor.id and not active:
        raise WorkflowError(409, "You cannot deactivate your own account.")
    if not active and account.role == Role.SYSTEM_ADMIN and account.is_active and _active_admin_count(database) <= 1:
        raise WorkflowError(409, "This is the only active administrator. Add another before deactivating it.")
    account.is_active = active
    if active:
        account.failed_attempts = 0
        account.locked_until = None
    append_audit_event(
        database,
        actor=actor,
        action="user.reactivated" if active else "user.deactivated",
        entity_type="user_account",
        entity_id=str(account.id),
        reason="An administrator reactivated the account." if active else "An administrator deactivated the account.",
        details={"email": account.email, "handle": account.handle},
    )
    return account


# PUBLIC_INTERFACE
def check_sign_in(database: Session, *, handle: str, password: str, verify) -> tuple[UserAccount | None, str]:
    """Check a password and keep the failure counters.

    Returns the account on success, otherwise ``None`` and the reason for the audit
    trail. Callers never tell the person why, so nobody can learn which emails exist.
    """

    account = database.scalar(select(UserAccount).where(UserAccount.handle == handle))
    now = _now()
    if account is None:
        verify(password, "pbkdf2_sha256$1$AAAA$AAAA")  # keep the time similar
        return None, "unknown_account"
    if account.locked_until is not None and account.locked_until > now:
        return None, "locked"
    if not account.is_active:
        verify(password, "pbkdf2_sha256$1$AAAA$AAAA")
        return None, "inactive"
    if not verify(password, account.password_hash):
        account.failed_attempts += 1
        if account.failed_attempts >= MAX_FAILED_ATTEMPTS:
            account.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            account.failed_attempts = 0
            return None, "locked_now"
        return None, "wrong_password"
    account.failed_attempts = 0
    account.locked_until = None
    account.last_login_at = now
    return account, "ok"


# PUBLIC_INTERFACE
def request_reset(
    database: Session, *, email: str, actor: UserAccount | None = None, force: bool = False
) -> tuple[UserAccount, str] | None:
    """Make a one-hour reset link for an active account that has an email.

    Returns ``None`` (and does nothing) for any other address, and when three links were already
    made for the account in the last hour. The caller must reply the same way either way, so
    nobody can find out which emails belong to staff. ``force`` skips the hourly limit for an
    administrator pressing the button.
    """

    account = database.scalar(select(UserAccount).where(func.lower(UserAccount.email) == email.strip().lower()))
    if account is None or status_of(account) not in ("active", "locked"):
        return None
    if not force:
        recent = database.scalar(
            select(func.count()).select_from(AccountToken).where(
                AccountToken.account_id == account.id,
                AccountToken.kind == "reset",
                AccountToken.created_at >= _now() - timedelta(hours=1),
            )
        )
        if (recent or 0) >= MAX_RESETS_PER_HOUR:
            return None
    _spend_open_tokens(database, account.id, "reset")
    secret = _new_token(database, account=account, kind="reset", actor=actor, hours=RESET_VALID_HOURS)
    append_audit_event(
        database,
        actor=actor,
        action="user.reset_sent" if actor else "auth.reset_requested",
        entity_type="user_account",
        entity_id=str(account.id),
        reason="An administrator sent a password reset link." if actor else "A password reset link was requested.",
        details={"email": account.email},
    )
    return account, secret


# PUBLIC_INTERFACE
def look_up_reset(database: Session, secret: str) -> UserAccount:
    """The account an unused, unexpired reset link belongs to."""

    token = _usable_token(database, secret, "reset")
    account = database.get(UserAccount, token.account_id) if token else None
    if account is None or status_of(account) not in ("active", "locked"):
        raise WorkflowError(404, "This link has expired or was already used. Ask for a new one.")
    return account


def _set_new_password(account: UserAccount, password: str) -> None:
    account.password_hash = hash_password(password)
    account.password_changed_at = _now()
    account.failed_attempts = 0
    account.locked_until = None


# PUBLIC_INTERFACE
def complete_reset(database: Session, *, secret: str, password: str) -> UserAccount:
    """Spend the reset link and set the new password. Every open session of the account ends."""

    token = _usable_token(database, secret, "reset")
    account = database.get(UserAccount, token.account_id) if token else None
    if token is None or account is None or status_of(account) not in ("active", "locked"):
        raise WorkflowError(404, "This link has expired or was already used. Ask for a new one.")
    problem = password_problem(password, email=account.email or "")
    if problem:
        raise WorkflowError(422, problem)
    _set_new_password(account, password)
    token.used_at = _now()
    append_audit_event(
        database,
        actor=None,
        action="auth.password_reset",
        entity_type="user_account",
        entity_id=str(account.id),
        reason="The person chose a new password from a reset link.",
        details={"email": account.email},
    )
    return account


# PUBLIC_INTERFACE
def change_password(
    database: Session, *, account: UserAccount, current: str, new: str, verify
) -> UserAccount:
    """A signed-in person changes their own password. Other open sessions end."""

    if not verify(current, account.password_hash):
        raise WorkflowError(422, "Your current password is not right.")
    problem = password_problem(new, email=account.email or "")
    if problem:
        raise WorkflowError(422, problem)
    if verify(new, account.password_hash):
        raise WorkflowError(422, "Choose a password you have not used just now.")
    _set_new_password(account, new)
    _spend_open_tokens(database, account.id, "reset")
    append_audit_event(
        database,
        actor=account,
        action="auth.password_changed",
        entity_type="user_account",
        entity_id=str(account.id),
        reason="The person changed their own password.",
        details={"email": account.email},
    )
    return account
