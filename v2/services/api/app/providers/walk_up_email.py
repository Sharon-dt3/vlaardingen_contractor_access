"""SMTP delivery of the walk-up email check code."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import Settings


# PUBLIC_INTERFACE
class WalkUpEmailError(Exception):
    """The code could not be handed to the configured SMTP server."""


# PUBLIC_INTERFACE
def send_walk_up_code_email(
    settings: Settings, *, to: str, code: str, site_name: str, valid_minutes: int
) -> None:
    """Email the six-digit code to the exact address the person entered.

    Args:
        settings: Server-only SMTP configuration.
        to: The address typed into the registration form.
        code: The six-digit code. It is never logged.
        site_name: The site the person is registering at.
        valid_minutes: How long the code works.
    Raises:
        WalkUpEmailError: If SMTP handoff fails.
    """

    message = EmailMessage()
    message["Subject"] = f"Your {site_name} registration code: {code}"
    message["From"] = settings.smtp_from_address or settings.smtp_username
    message["To"] = to
    message["X-Auto-Response-Suppress"] = "All"
    message.set_content(
        f"Your code to register at {site_name} is:\n\n    {code}\n\n"
        f"Enter it on the registration page within {valid_minutes} minutes. "
        "If you did not start a registration, ignore this email: nothing is stored until "
        "the code is entered.\n"
    )
    try:
        # Encrypted submission only, matching the invitation emails.
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise WalkUpEmailError("The code email could not be sent.") from error
