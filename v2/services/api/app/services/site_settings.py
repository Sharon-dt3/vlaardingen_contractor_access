"""Per-site access validity: default visit length (Path A) and walk-up QR validity (Path B)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Site, SiteAccessSettings, UserAccount, Visit
from app.services.workflows import WorkflowError
from app.services.audit import append_audit_event

DEFAULT_VISIT_HOURS = 8
DEFAULT_PASS_HOURS = 12
DEFAULT_QR_MAX_HOURS = 24
DEFAULT_ENTRY_DELAY_MINUTES = 0
MAX_VISIT_HOURS = 168
MAX_PASS_HOURS = 72
MAX_QR_MAX_HOURS = 168
MAX_ENTRY_DELAY_MINUTES = 240


# PUBLIC_INTERFACE
def get_site_settings(database: Session, site: Site) -> SiteAccessSettings:
    """The site's settings; a site that was never configured gets the defaults.

    The defaults are not written here, so reading never changes the database.
    """

    row = database.get(SiteAccessSettings, site.id)
    if row is not None:
        return row
    return SiteAccessSettings(
        site_id=site.id,
        visit_default_hours=DEFAULT_VISIT_HOURS,
        walk_up_pass_hours=DEFAULT_PASS_HOURS,
        access_qr_max_hours=DEFAULT_QR_MAX_HOURS,
        walk_up_entry_delay_minutes=DEFAULT_ENTRY_DELAY_MINUTES,
    )


# PUBLIC_INTERFACE
def pass_hours_for(database: Session, site: Site) -> int:
    """How many hours a new walk-up entry QR is valid at this site."""

    return get_site_settings(database, site).walk_up_pass_hours


# PUBLIC_INTERFACE
def update_site_settings(
    database: Session,
    *,
    actor: UserAccount,
    site: Site,
    visit_default_hours: int,
    walk_up_pass_hours: int,
    access_qr_max_hours: int = DEFAULT_QR_MAX_HOURS,
    walk_up_entry_delay_minutes: int = DEFAULT_ENTRY_DELAY_MINUTES,
) -> SiteAccessSettings:
    """Save new values and record who changed what. Issued QR codes keep their expiry."""

    row = database.get(SiteAccessSettings, site.id)
    before = {
        "visit_default_hours": row.visit_default_hours if row else DEFAULT_VISIT_HOURS,
        "walk_up_pass_hours": row.walk_up_pass_hours if row else DEFAULT_PASS_HOURS,
        "access_qr_max_hours": row.access_qr_max_hours if row else DEFAULT_QR_MAX_HOURS,
        "walk_up_entry_delay_minutes": (
            row.walk_up_entry_delay_minutes if row else DEFAULT_ENTRY_DELAY_MINUTES
        ),
    }
    now = datetime.now(timezone.utc)
    if row is None:
        row = SiteAccessSettings(site_id=site.id)
        database.add(row)
    row.visit_default_hours = visit_default_hours
    row.walk_up_pass_hours = walk_up_pass_hours
    row.access_qr_max_hours = access_qr_max_hours
    row.walk_up_entry_delay_minutes = walk_up_entry_delay_minutes
    row.updated_at = now
    row.updated_by_id = actor.id
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="site_settings.updated",
        entity_type="site",
        entity_id=str(site.id),
        reason="An administrator changed how long access lasts at this site.",
        details={
            "before": before,
            "after": {
                "visit_default_hours": visit_default_hours,
                "walk_up_pass_hours": walk_up_pass_hours,
                "access_qr_max_hours": access_qr_max_hours,
                "walk_up_entry_delay_minutes": walk_up_entry_delay_minutes,
            },
        },
    )
    return row


# PUBLIC_INTERFACE
def access_qr_window(
    database: Session,
    *,
    visit: Visit,
    requested_start: datetime | None,
    requested_expiry: datetime | None,
    now: datetime,
) -> tuple[datetime | None, datetime | None]:
    """Apply the site's longest-QR rule to the window staff asked for.

    Returns the entry and exit time to issue with. When staff gave no exit time, it is
    the visit end or the longest allowed from the entry time, whichever is sooner. When
    they gave one that is longer than allowed, the request is refused so nobody is
    surprised by a shorter QR than they chose.
    """

    site = database.get(Site, visit.site_id)
    longest = timedelta(hours=get_site_settings(database, site).access_qr_max_hours)
    start = requested_start or visit.starts_at
    if requested_expiry is None:
        base = max(start, now)
        return requested_start, min(visit.ends_at, base + longest)
    if requested_expiry - start > longest:
        hours = int(longest.total_seconds() // 3600)
        raise WorkflowError(
            422,
            f"An access QR can be valid for at most {hours} hours at this site. Choose a shorter window.",
        )
    return requested_start, requested_expiry
