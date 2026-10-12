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


def _send(settings: Settings, message: EmailMessage) -> None:
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException, AttributeError) as error:
        raise StaffEmailError("The email could not be sent.") from error


def _message(settings: Settings, to: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_address or settings.smtp_username
    message["To"] = to
    message["X-Auto-Response-Suppress"] = "All"
    message.set_content(body)
    return message


# PUBLIC_INTERFACE
def send_staff_reset_email(
    settings: Settings, *, to: str, name: str, link: str, valid_minutes: int, sent_by_admin: bool
) -> None:
    """Email the one-time link for choosing a new password."""

    why = "An administrator sent you this link" if sent_by_admin else "Someone asked to reset your password"
    _send(
        settings,
        _message(
            settings,
            to,
            "Reset your Renewi Access password",
            f"Hello {name},\n\n{why}. Open this link to choose a new password:\n\n    {link}\n\n"
            f"The link works once and expires in {valid_minutes} minutes.\n\n"
            "If you did not expect this, ignore this email. Your password stays as it is.\n",
        ),
    )


# PUBLIC_INTERFACE
def send_password_changed_email(settings: Settings, *, to: str, name: str) -> None:
    """Tell the person their password was changed, so a stranger doing it would be noticed."""

    _send(
        settings,
        _message(
            settings,
            to,
            "Your Renewi Access password was changed",
            f"Hello {name},\n\nYour Renewi Access password was just changed, and every other browser "
            "where you were signed in has been signed out.\n\n"
            "If this was you, there is nothing to do. If it was not, ask an administrator to deactivate your account and "
            "reset it straight away.\n",
        ),
    )
