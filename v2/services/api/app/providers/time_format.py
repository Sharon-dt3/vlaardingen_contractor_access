"""Plain-language entry and exit times for emails, shown in the site's own time zone."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _local(moment: datetime, timezone_name: str) -> tuple[datetime, str]:
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
        timezone_name = "UTC"
    return moment.astimezone(zone), timezone_name


# PUBLIC_INTERFACE
def format_moment(moment: datetime, timezone_name: str) -> str:
    """For example ``Mon 12 Oct 2026, 13:30 (Europe/Amsterdam)``."""

    local, name = _local(moment, timezone_name)
    return f"{local.strftime('%a %d %b %Y, %H:%M')} ({name})"


# PUBLIC_INTERFACE
def entry_exit_lines(valid_from: datetime | None, valid_until: datetime, timezone_name: str) -> str:
    """The two lines an email shows: when entry opens and when the QR stops working."""

    lines = ""
    if valid_from is not None:
        lines += f"    Entry from: {format_moment(valid_from, timezone_name)}\n"
    lines += f"    Exit by: {format_moment(valid_until, timezone_name)}\n"
    return lines
