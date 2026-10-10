"""SMTP delivery of the walk-up email check code."""

from __future__ import annotations

import smtplib
from datetime import datetime
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


# PUBLIC_INTERFACE
def send_walk_up_pass_email(
    settings: Settings,
    *,
    to: str,
    first_name: str,
    site_name: str,
    reference: str,
    valid_until: datetime,
    qr_png: bytes,
) -> None:
    """Email the person their entry QR, so it is not lost if they close the page.

    Args:
        settings: Server-only SMTP configuration.
        to: The address that was just verified with a code.
        first_name: Used in the greeting only.
        site_name: The site they registered at.
        reference: The short code that stands in for the QR.
        valid_until: When the entry QR stops working.
        qr_png: The QR image, attached as a PNG.
    Raises:
        WalkUpEmailError: If SMTP handoff fails.
    """

    message = EmailMessage()
    message["Subject"] = f"Your {site_name} entry QR"
    message["From"] = settings.smtp_from_address or settings.smtp_username
    message["To"] = to
    message["X-Auto-Response-Suppress"] = "All"
    message.set_content(
        f"Hello {first_name},\n\n"
        f"You are registered at {site_name}. Show the attached QR code to the gate officer "
        "when you arrive, or read out your reference.\n\n"
        f"    Reference: {reference}\n"
        f"    Valid until: {valid_until.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "Keep this email private: anyone who has the QR can use it until it expires.\n"
    )
    message.add_attachment(
        qr_png, maintype="image", subtype="png", filename=f"entry-qr-{reference}.png"
    )
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise WalkUpEmailError("The entry QR email could not be sent.") from error
