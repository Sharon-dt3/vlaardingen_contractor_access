"""Administrator settings for how long access lasts at each site."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import UserAccount
from app.security import get_current_user, require_permissions
from app.services.site_settings import (
    MAX_ENTRY_DELAY_MINUTES,
    MAX_PASS_HOURS,
    MAX_QR_MAX_HOURS,
    MAX_VISIT_HOURS,
    get_site_settings,
    update_site_settings,
)
from app.services.workflows import WorkflowError
from app.services.walk_up import active_sites, site_for_key, site_key

router = APIRouter(prefix="/api/site-settings", tags=["Site settings"])


class SiteSettingsResponse(BaseModel):
    """Current validity settings for one site."""

    model_config = ConfigDict(extra="forbid")

    site_id: uuid.UUID
    site_key: str
    site_name: str
    visit_default_hours: int
    walk_up_pass_hours: int
    access_qr_max_hours: int
    walk_up_entry_delay_minutes: int
    updated_at: datetime | None = None


class SiteSettingsUpdate(BaseModel):
    """New validity settings."""

    model_config = ConfigDict(extra="forbid")

    visit_default_hours: int = Field(ge=1, le=MAX_VISIT_HOURS)
    walk_up_pass_hours: int = Field(ge=1, le=MAX_PASS_HOURS)
    access_qr_max_hours: int = Field(default=24, ge=1, le=MAX_QR_MAX_HOURS)
    walk_up_entry_delay_minutes: int = Field(default=0, ge=0, le=MAX_ENTRY_DELAY_MINUTES)


def _find_site(database: Session, site_key_value: str):
    try:
        return site_for_key(database, site_key_value)
    except WorkflowError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _response(site, row) -> SiteSettingsResponse:
    return SiteSettingsResponse(
        site_id=site.id,
        site_key=site_key(site),
        site_name=site.name,
        visit_default_hours=row.visit_default_hours,
        walk_up_pass_hours=row.walk_up_pass_hours,
        access_qr_max_hours=row.access_qr_max_hours,
        walk_up_entry_delay_minutes=row.walk_up_entry_delay_minutes,
        updated_at=row.updated_at,
    )


# PUBLIC_INTERFACE
@router.get(
    "",
    response_model=list[SiteSettingsResponse],
    operation_id="list_site_settings",
    summary="How long access lasts at every active site",
    description="Any signed-in staff member can read it; the invitation form uses the default visit length.",
)
def list_settings(
    _: Annotated[UserAccount, Depends(get_current_user)],
    database: Annotated[Session, Depends(get_db)],
) -> list[SiteSettingsResponse]:
    """Return every active site with its settings, or the defaults."""

    return [_response(site, get_site_settings(database, site)) for site in active_sites(database)]


# PUBLIC_INTERFACE
@router.get(
    "/{site_key_value}",
    response_model=SiteSettingsResponse,
    operation_id="get_site_settings",
    summary="How long access lasts at a site",
    description="Any signed-in staff member can read it; the invitation form uses the default visit length.",
)
def read_settings(
    site_key_value: str,
    _: Annotated[UserAccount, Depends(get_current_user)],
    database: Annotated[Session, Depends(get_db)],
) -> SiteSettingsResponse:
    """Return the settings, or the defaults when none were saved."""

    site = _find_site(database, site_key_value)
    return _response(site, get_site_settings(database, site))


# PUBLIC_INTERFACE
@router.put(
    "/{site_key_value}",
    response_model=SiteSettingsResponse,
    operation_id="update_site_settings",
    summary="Change how long access lasts at a site",
    description="Administrators only. New invitations and QR codes use the new values; issued ones keep theirs.",
)
def write_settings(
    site_key_value: str,
    payload: SiteSettingsUpdate,
    actor: Annotated[UserAccount, Depends(require_permissions("*"))],
    database: Annotated[Session, Depends(get_db)],
) -> SiteSettingsResponse:
    """Save and audit the new values."""

    site = _find_site(database, site_key_value)
    row = update_site_settings(
        database,
        actor=actor,
        site=site,
        visit_default_hours=payload.visit_default_hours,
        walk_up_pass_hours=payload.walk_up_pass_hours,
        access_qr_max_hours=payload.access_qr_max_hours,
        walk_up_entry_delay_minutes=payload.walk_up_entry_delay_minutes,
    )
    database.commit()
    return _response(site, row)
