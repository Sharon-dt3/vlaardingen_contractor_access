"""Authentication routes for deterministic local demo accounts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.models import UserAccount
from app.schemas.auth import LoginRequest, SessionResponse, UserResponse
from app.security import (
    create_session_token,
    get_current_user,
    permissions_for_role,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _user_response(account: UserAccount) -> UserResponse:
    return UserResponse(
        id=str(account.id),
        handle=account.handle,
        display_name=account.display_name,
        role=account.role,
        permissions=permissions_for_role(account.role),
    )


# PUBLIC_INTERFACE
@router.post(
    "/login",
    response_model=SessionResponse,
    operation_id="login",
    summary="Sign in with a seeded demo account",
    description=(
        "Validates the configured local demo password and sets a short-lived, "
        "HMAC-signed HttpOnly SameSite cookie."
    ),
    responses={
        401: {"description": "The handle or password is invalid."},
        422: {"description": "The submitted credentials are malformed."},
    },
)
def login(
    credentials: LoginRequest,
    response: Response,
    database: Annotated[Session, Depends(get_db)],
) -> SessionResponse:
    """Authenticate a seeded handle and return its role and permissions.

    Args:
        credentials: Local demo handle and configured seed password.
        response: FastAPI response used to set the signed session cookie.
        database: Request-scoped SQLAlchemy session.

    Returns:
        The authenticated user and session lifetime.

    Raises:
        HTTPException: When credentials are invalid or the account is inactive.
    """

    account = database.scalar(
        select(UserAccount).where(
            UserAccount.handle == credentials.handle.strip().lower()
        )
    )
    if (
        account is None
        or not account.is_active
        or not verify_password(credentials.password, account.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid handle or password.",
        )

    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=create_session_token(account),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return SessionResponse(
        user=_user_response(account),
        expires_in_seconds=settings.session_ttl_seconds,
    )


# PUBLIC_INTERFACE
@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="logout",
    summary="Sign out the current browser session",
    description="Expires the local signed session cookie.",
    responses={204: {"description": "The browser session was cleared."}},
)
def logout(response: Response) -> Response:
    """Clear the signed session cookie and return no response body.

    Args:
        response: FastAPI response used to expire the cookie.

    Returns:
        The empty response with the session cookie expired.
    """

    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# PUBLIC_INTERFACE
@router.get(
    "/me",
    response_model=UserResponse,
    operation_id="get_current_user",
    summary="Get the current demo user",
    description="Returns role and permission data from the verified signed session.",
    responses={
        401: {"description": "No current valid session exists."},
    },
)
def current_user(
    account: Annotated[UserAccount, Depends(get_current_user)],
) -> UserResponse:
    """Return the account represented by the current signed cookie.

    Args:
        account: Active account resolved by the authentication dependency.

    Returns:
        Current user details and effective permissions.
    """

    return _user_response(account)
