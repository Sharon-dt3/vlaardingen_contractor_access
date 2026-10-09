"""Demo authentication, signed sessions, and authoritative API permissions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.models import Role, UserAccount

PBKDF2_ITERATIONS = 310_000
ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.SYSTEM_ADMIN: frozenset({"*", "people:delete"}),
    Role.COMPLIANCE: frozenset(
        {
            "sites:read",
            "companies:read",
            "people:read",
            "visits:read",
            "audit:read",
            "audit:write",
            "invitations:read",
            "invitations:write",
            "invitations:register",
            "evidence:read",
            "evidence:write",
            "evidence:review",
            "training:read",
            "training:complete",
            "compliance:read",
            "approvals:read",
            "approvals:write",
            "blacklist:read",
            "blacklist:write",
            "tokens:read",
            "tokens:write",
            "presence:read",
            "dashboard:read",
        }
    ),
    Role.SITE_MANAGER: frozenset(
        {
            "sites:read",
            "companies:read",
            "people:read",
            "visits:read",
            "audit:read",
            "audit:write",
            "invitations:read",
            "invitations:write",
            "invitations:register",
            "evidence:read",
            "evidence:write",
            "evidence:review",
            "training:read",
            "training:complete",
            "compliance:read",
            "approvals:read",
            "approvals:write",
            "blacklist:read",
            "blacklist:write",
            "tokens:read",
            "tokens:write",
            "presence:read",
            "presence:write",
            "dashboard:read",
            "expiry:read",
            "expiry:write",
        }
    ),
    Role.GATE_OPERATOR: frozenset(
        {
            "sites:read",
            "people:read",
            "visits:read",
            "gate:evaluate",
            "presence:read",
            "presence:write",
            "dashboard:read",
        }
    ),
    Role.HOST: frozenset(
        {
            "sites:read",
            "invitations:read",
            "invitations:write",
            "invitations:register",
        }
    ),
    Role.PARTICIPANT: frozenset(
        {
            "invitations:read",
            "invitations:register",
            "evidence:read",
            "evidence:write",
            "training:read",
            "training:complete",
            "tokens:read",
        }
    ),
    Role.VIEWER: frozenset(
        {
            "sites:read",
            "companies:read",
            "people:read",
            "visits:read",
            "audit:read",
            "presence:read",
            "dashboard:read",
        }
    ),
}


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _signing_key() -> bytes:
    settings = get_settings()
    if not settings.app_secret_key or not settings.app_secret_key.get_secret_value():
        settings.prepare_local_runtime()
    if not settings.app_secret_key:
        raise RuntimeError("Application signing key is unavailable.")
    return settings.app_secret_key.get_secret_value().encode("utf-8")


# PUBLIC_INTERFACE
def deterministic_demo_salt(handle: str) -> bytes:
    """Derive a stable per-account salt for repeatable synthetic seed records."""

    return hashlib.sha256(f"renewi-demo:{handle}".encode("utf-8")).digest()[:16]


# PUBLIC_INTERFACE
def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Hash a password with PBKDF2-SHA256 and a random or supplied salt."""

    selected_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        selected_salt,
        PBKDF2_ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"
        f"{_urlsafe_encode(selected_salt)}${_urlsafe_encode(digest)}"
    )


# PUBLIC_INTERFACE
def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password against a PBKDF2 hash in constant time."""

    try:
        algorithm, iterations, encoded_salt, expected_digest = encoded_hash.split(
            "$",
            maxsplit=3,
        )
        if algorithm != "pbkdf2_sha256":
            return False
        salt = _urlsafe_decode(encoded_salt)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(_urlsafe_encode(digest), expected_digest)
    except (TypeError, ValueError):
        return False


# PUBLIC_INTERFACE
def create_session_token(account: UserAccount) -> str:
    """Create a short-lived HMAC-signed session token for a user account."""

    settings = get_settings()
    issued_at = int(time.time())
    payload = {
        "sub": str(account.id),
        "handle": account.handle,
        "iat": issued_at,
        "exp": issued_at + settings.session_ttl_seconds,
    }
    encoded_payload = _urlsafe_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        _signing_key(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_urlsafe_encode(signature)}"


# PUBLIC_INTERFACE
def verify_session_token(token: str) -> dict[str, Any] | None:
    """Validate a signed session token and return its payload when current."""

    try:
        encoded_payload, encoded_signature = token.split(".", maxsplit=1)
        expected_signature = hmac.new(
            _signing_key(),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        supplied_signature = _urlsafe_decode(encoded_signature)
        if not hmac.compare_digest(expected_signature, supplied_signature):
            return None
        payload = json.loads(_urlsafe_decode(encoded_payload))
        if not isinstance(payload, dict) or int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return payload
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


# PUBLIC_INTERFACE
def permissions_for_role(role: Role) -> list[str]:
    """Return a stable, sorted permission list suitable for API responses."""

    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))


# PUBLIC_INTERFACE
def get_current_user(
    request: Request,
    database: Annotated[Session, Depends(get_db)],
) -> UserAccount:
    """Resolve the active account represented by the signed HttpOnly cookie."""

    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    payload = verify_session_token(token) if token else None
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    account = database.scalar(
        select(UserAccount).where(
            UserAccount.id == payload.get("sub"),
            UserAccount.is_active.is_(True),
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session account is unavailable.",
        )
    return account


# PUBLIC_INTERFACE
def require_permissions(
    *required_permissions: str,
) -> Callable[..., UserAccount]:
    """Create a FastAPI dependency enforcing every requested permission."""

    def dependency(
        account: Annotated[UserAccount, Depends(get_current_user)],
    ) -> UserAccount:
        """Reject an authenticated account lacking a required API permission."""

        granted = ROLE_PERMISSIONS.get(account.role, frozenset())
        if "*" not in granted and not set(required_permissions).issubset(granted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return account

    return dependency
