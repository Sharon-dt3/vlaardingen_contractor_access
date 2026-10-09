"""Local notification-provider boundary for credential-free expiry workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


# PUBLIC_INTERFACE
@dataclass(frozen=True)
class NotificationDeliveryResult:
    """The sanitized result of attempting one notification delivery."""

    mode: str
    status: str
    provider_reference: str


# PUBLIC_INTERFACE
class NotificationProvider(Protocol):
    """Boundary for optional notification delivery after durable business state exists."""

    def deliver(
        self,
        *,
        template_key: str,
        recipient_reference: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> NotificationDeliveryResult:
        """Deliver one idempotent notification and return only safe correlation metadata."""


# PUBLIC_INTERFACE
class InAppNotificationProvider:
    """Persist-compatible local provider represented by the durable expiry alert itself."""

    def deliver(
        self,
        *,
        template_key: str,
        recipient_reference: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> NotificationDeliveryResult:
        """Return a deterministic local-delivery result without external credentials."""

        del template_key, recipient_reference, payload
        return NotificationDeliveryResult(
            mode="IN_APP",
            status="PERSISTED",
            provider_reference=f"in-app:{idempotency_key}",
        )
