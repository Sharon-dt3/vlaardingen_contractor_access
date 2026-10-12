"""SMTP delivery of staff invitation emails."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import Settings


# PUBLIC_INTERFACE
class StaffEmailError(Exception):
    """An email could not be handed to the configured SMTP server."""


# PUBLIC_INTERFACE
def send_staff_invitation_email(
    settings: Settings,
    *,
    to: str,
    name: str,
    role_label: str,
    invited_by: str,
    link: str,
    valid_hours: int,
) -> None:
    """Email a new staff member the one-time link to set their own password.

    Raises:
        StaffEmailError: If SMTP handoff fails.
    """

    message = EmailMessage()
    message["Subject"] = "Your Renewi Access account"
    message["From"] = settings.smtp_from_address or settings.smtp_username
    message["To"] = to
    message["X-Auto-Response-Suppress"] = "All"
    message.set_content(
        f"Hello {name},\n\n"
        f"{invited_by} has set up a {role_label.lower()} account for you in Renewi Access.\n\n"
        "Open this link to choose your own password and finish setting up:\n\n"
        f"    {link}\n\n"
        f"The link works once and expires in {valid_hours} hours. If it has expired, ask {invited_by} to send a new one.\n\n"
        "If you were not expecting this email, you can ignore it. Nothing happens until the link is used.\n"
    )
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException, AttributeError) as error:
        raise StaffEmailError("The invitation email could not be sent.") from error
