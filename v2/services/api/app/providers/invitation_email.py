"""SMTP delivery of invitation action links."""

from __future__ import annotations

import smtplib
from io import BytesIO
from email.message import EmailMessage

import qrcode

from app.config import Settings
from app.models import AccessToken, Invitation, Site


# PUBLIC_INTERFACE
class InvitationEmailError(Exception):
    """An invitation could not be handed to the configured SMTP server."""


# PUBLIC_INTERFACE
def send_invitation_email(
    settings: Settings,
    invitation: Invitation,
    site: Site,
    accept_url: str,
    decline_url: str,
) -> None:
    """Send invitation details and both action links to the exact invitee address.

    Args:
        settings: Server-only SMTP configuration.
        invitation: Persisted invitation and recipient.
        site: Site identified in the invitation.
        accept_url: Opaque acceptance link on the public API origin.
        decline_url: Opaque declination link on the public API origin.
    Returns:
        None after the SMTP server accepts the message.
    Raises:
        InvitationEmailError: If SMTP handoff fails.
    """

    message = EmailMessage()
    message["Subject"] = "Site access invitation"
    message["From"] = settings.smtp_from_address or settings.smtp_username
    message["To"] = invitation.invitee_email
    message["X-Auto-Response-Suppress"] = "All"
    message.set_content(
        f"You have been invited to {site.name}.\n\n"
        f"Company: {invitation.company_name}\n"
        f"Purpose: {invitation.purpose}\n"
        f"Visit starts: {invitation.starts_at.isoformat()}\n"
        f"Visit ends: {invitation.ends_at.isoformat()}\n\n"
        "Open a link and confirm your choice on the page:\n"
        f"Accept Invitation: {accept_url}\n"
        f"Decline Invitation: {decline_url}\n\n"
        "After accepting, you will be taken to a private registration form. "
        "Enter your name and upload the requested ID card or driving licence. "
        "The form cannot be opened before you accept. Each link expires and "
        "can only be used for this invitation. An administrator must verify "
        "your name and evidence before training, approval, or site access.\n"
    )
    try:
        # Gmail submission uses STARTTLS; do not fall back to plaintext delivery.
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(
                settings.smtp_username,
                settings.smtp_password.get_secret_value(),
            )
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise InvitationEmailError("Invitation SMTP handoff failed.") from error


# PUBLIC_INTERFACE
def send_access_token_email(
    settings: Settings,
    invitation: Invitation,
    site: Site,
    token: AccessToken,
    qr_payload: str,
) -> None:
    """Email the invitee a downloadable, gate-readable PNG for a newly issued token.

    Args:
        settings: Server-only SMTP configuration.
        invitation: Accepted invitation containing the intended recipient address.
        site: Site associated with the visit.
        token: Newly issued access token, used only for expiry and attachment naming.
        qr_payload: One-time opaque reference; never persist it or log it.
    Returns:
        None after SMTP accepts the message.
    Raises:
        InvitationEmailError: When QR generation or SMTP delivery fails.
    """

    try:
        # The gate decodes an uploaded image and hashes its raw QR text. Encode
        # the original reference, not the token ID or its stored digest.
        image = qrcode.make(qr_payload, error_correction=qrcode.constants.ERROR_CORRECT_M)
        output = BytesIO()
        image.save(output, format="PNG")
        message = EmailMessage()
        message["Subject"] = "Your site access QR token"
        message["From"] = settings.smtp_from_address or settings.smtp_username
        message["To"] = invitation.invitee_email
        message["X-Auto-Response-Suppress"] = "All"
        message.set_content(
            f"Your access QR for {site.name} is attached as a PNG image.\n"
            "Download the image and bring it with you for verification at the gate.\n"
            f"The token expires at {token.expires_at.isoformat()}.\n"
            "An issued token does not guarantee admission: the gate checks the "
            "current visit, identity, approval, and compliance requirements.\n"
            "Keep the image private and do not forward this email.\n"
        )
        message.add_attachment(
            output.getvalue(),
            maintype="image",
            subtype="png",
            filename=f"renewi-access-qr-{token.id}.png",
        )
        # Match invitation delivery: encrypted SMTP submission only.
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(
                settings.smtp_username,
                settings.smtp_password.get_secret_value(),
            )
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError, RuntimeError) as error:
        raise InvitationEmailError("Access-token SMTP handoff failed.") from error
