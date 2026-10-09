"""Regression coverage for safe external document-provider authentication errors."""

from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError

import pytest

from app.models import EvidenceType
from app.providers import documents
from app.providers.documents import AnthropicDocumentParser, DocumentExtractionError


class _PrivateStorage:
    """Minimal private-storage substitute used without filesystem or network access."""

    def get(self, _reference: str) -> bytes:
        """Return non-synthetic bytes so the external request path is exercised."""

        return b"private driving licence image bytes"


def test_anthropic_rejected_credential_is_reported_without_secret_disclosure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Map upstream 401 responses to an actionable, credential-safe error."""

    def rejected_request(*_args: object, **_kwargs: object) -> None:
        """Simulate Anthropic rejecting the configured server-side credential."""

        raise HTTPError(
            url="https://api.anthropic.com/v1/messages",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=BytesIO(),
        )

    monkeypatch.setattr(documents, "urlopen", rejected_request)
    parser = AnthropicDocumentParser(
        api_key="server-only-test-key",
        model="claude-sonnet-4-20250514",
        storage=_PrivateStorage(),
    )

    with pytest.raises(DocumentExtractionError) as error:
        parser.extract(
            storage_reference="objects/aa/" + ("a" * 64),
            evidence_type=EvidenceType.DRIVING_LICENCE,
            media_type="image/jpeg",
        )

    message = str(error.value)
    assert "rejected its server-side credentials" in message
    assert "server-only-test-key" not in message
    assert "private driving licence image bytes" not in message
