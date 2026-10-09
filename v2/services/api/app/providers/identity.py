"""Deterministic identity-verification provider for the credential-free demo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import Person


@dataclass(frozen=True)
class IdentityVerificationResult:
    """A sanitized identity-provider result safe to persist in a gate snapshot."""

    is_match: bool
    confidence: float
    mode: str
    provider_reference: str
    evaluated_at: datetime


class IdentityVerificationProvider:
    """Protocol-like base class for identity-verification provider adapters."""

    def verify(
        self,
        *,
        person: Person,
        presentation_reference: str,
    ) -> IdentityVerificationResult:
        """Evaluate one synthetic presentation against a registered person."""

        raise NotImplementedError


class MockIdentityVerifier(IdentityVerificationProvider):
    """Return deterministic scenario-specific identity results in DEMO mode."""

    def verify(
        self,
        *,
        person: Person,
        presentation_reference: str,
    ) -> IdentityVerificationResult:
        """Return the configured synthetic match or mismatch for one person."""

        scenario = str(person.source_metadata.get("scenario", ""))
        is_match = scenario != "identity_mismatch"
        confidence = 0.96 if is_match else 0.18
        return IdentityVerificationResult(
            is_match=is_match,
            confidence=confidence,
            mode="DEMO",
            provider_reference=(
                f"mock-identity:{person.seed_key}:"
                f"{'match' if is_match else 'mismatch'}"
            ),
            evaluated_at=datetime.now(timezone.utc),
        )
