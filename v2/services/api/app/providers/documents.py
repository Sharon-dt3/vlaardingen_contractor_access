"""Document-extraction provider boundary for private evidence."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.models import EvidenceType
from app.providers.storage import StorageProvider

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_LOGGER = logging.getLogger(__name__)
_SUPPORTED_IDENTITY_TYPES = frozenset(
    {EvidenceType.ID_CARD, EvidenceType.DRIVING_LICENCE}
)
_SUPPORTED_MEDIA_TYPES = frozenset(
    {"application/pdf", "image/jpeg", "image/png"}
)
_SYNTHETIC_MARKERS = (b"DEMO", b"NOT A REAL CREDENTIAL")


# PUBLIC_INTERFACE
class DocumentExtractionError(RuntimeError):
    """Safe provider failure that must not expose credentials or document contents."""


# PUBLIC_INTERFACE
@dataclass(frozen=True)
class ExtractionResult:
    """Structured fields and confidence returned by a document provider."""

    fields: dict[str, Any]
    field_confidence: dict[str, float]
    provider_mode: str
    processing_metadata: dict[str, Any]


# PUBLIC_INTERFACE
class DocumentExtractionProvider(Protocol):
    """Provider contract that extracts fields without making compliance decisions."""

    # PUBLIC_INTERFACE
    def extract(
        self,
        *,
        storage_reference: str,
        evidence_type: EvidenceType,
        media_type: str | None = None,
        expected_fields: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Extract structured data from an authorized private document reference."""


_DEFAULT_FIELDS: dict[EvidenceType, dict[str, Any]] = {
    EvidenceType.ID_CARD: {
        "holder_name": "Demo Participant",
        "document_number": "DEMO-ID-0001",
        "nationality": "NL",
        "issue_date": "2026-01-01",
        "expiry_date": "2031-01-01",
    },
    EvidenceType.DRIVING_LICENCE: {
        "holder_name": "Demo Participant",
        "document_number": "DEMO-DL-0001",
        "categories": ["B", "C", "CE"],
        "code_95": True,
        "issue_date": "2025-06-01",
        "expiry_date": "2030-06-01",
    },
    EvidenceType.VCA_CERTIFICATE: {
        "holder_name": "Demo Participant",
        "certificate_number": "DEMO-VCA-0001",
        "provider": "Demo Safety Institute",
        "issue_date": "2026-01-15",
        "expiry_date": "2029-01-15",
    },
    EvidenceType.INSURANCE_CERTIFICATE: {
        "company_name": "Demo Contractor B.V.",
        "policy_number": "DEMO-POLICY-0001",
        "insurer": "Demo Mutual Insurance",
        "issue_date": "2026-01-01",
        "expiry_date": "2027-01-01",
    },
}


# PUBLIC_INTERFACE
class MockDocumentParser:
    """Credential-free parser returning stable fields for synthetic evidence."""

    # PUBLIC_INTERFACE
    def extract(
        self,
        *,
        storage_reference: str,
        evidence_type: EvidenceType,
        media_type: str | None = None,
        expected_fields: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Return expected asset fields or deterministic type defaults."""

        del media_type
        fields = dict(expected_fields or _DEFAULT_FIELDS[evidence_type])
        confidence = {key: 0.99 for key in fields}
        return ExtractionResult(
            fields=fields,
            field_confidence=confidence,
            provider_mode="DEMO",
            processing_metadata={
                "parser": "MockDocumentParser",
                "document_reference": storage_reference,
                "synthetic": True,
            },
        )


# PUBLIC_INTERFACE
class AnthropicDocumentParser:
    """Server-side Anthropic Vision extractor for Dutch identity documents."""

    # PUBLIC_INTERFACE
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        storage: StorageProvider,
    ) -> None:
        """Initialize the provider with a server-only credential and private storage."""

        self._api_key = api_key
        self._model = model
        self._storage = storage

    # PUBLIC_INTERFACE
    def extract(
        self,
        *,
        storage_reference: str,
        evidence_type: EvidenceType,
        media_type: str | None = None,
        expected_fields: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Extract reviewable fields from a Netherlands ID card or driving licence.

        The provider never makes an access decision. It reads bytes from private
        storage, sends them directly from the API server to Anthropic, and
        returns only structured fields for the existing human-review workflow.
        """

        del expected_fields
        if evidence_type not in _SUPPORTED_IDENTITY_TYPES:
            raise DocumentExtractionError(
                "Anthropic extraction only supports identity cards and driving licences."
            )
        if media_type not in _SUPPORTED_MEDIA_TYPES:
            raise DocumentExtractionError(
                "Identity documents must be a PDF, JPEG, or PNG image."
            )

        try:
            content = self._storage.get(storage_reference)
        except (FileNotFoundError, ValueError) as error:
            raise DocumentExtractionError(
                "Private identity-document content is unavailable."
            ) from error

        # The local demo accepts visibly synthetic files. Extract them with the
        # deterministic backend parser so transient external-provider failures
        # cannot block the demonstration workflow or generate fictional claims.
        if any(marker in content[:65536].upper() for marker in _SYNTHETIC_MARKERS):
            return MockDocumentParser().extract(
                storage_reference=storage_reference,
                evidence_type=evidence_type,
                media_type=media_type,
            )

        response = self._request_extraction(content=content, media_type=media_type)
        fields = self._validated_fields(response, evidence_type)
        return ExtractionResult(
            fields=fields,
            field_confidence={key: 0.9 for key in fields},
            provider_mode="EXTERNAL",
            processing_metadata={
                "provider": "anthropic",
                "model": self._model,
                "document_type": response["document_type"],
            },
        )

    def _request_extraction(
        self,
        *,
        content: bytes,
        media_type: str,
    ) -> dict[str, Any]:
        """Send a constrained extraction request without logging sensitive data."""

        encoded_content = base64.b64encode(content).decode("ascii")
        source_type = "document" if media_type == "application/pdf" else "image"
        prompt = (
            "Extract fields from this Netherlands identity document. It must be "
            "a Netherlands identity card or Netherlands driving licence. Return "
            "only valid JSON with this exact shape: "
            '{"document_type":"netherlands_identity_card|netherlands_driving_licence|unsupported",'
            '"holder_name":"string|null","document_number":"string|null",'
            '"nationality":"string|null","issue_date":"YYYY-MM-DD|null",'
            '"expiry_date":"YYYY-MM-DD|null","categories":["string"],'
            '"code_95":true|false|null}. Do not infer missing values. '
            "This is extraction only, not a verification or access decision."
        )
        payload = {
            "model": self._model,
            "max_tokens": 700,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": source_type,
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": encoded_content,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        request = Request(
            _ANTHROPIC_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as http_response:
                response = json.loads(http_response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code in {401, 403}:
                # Log only the upstream status: credentials, request headers, and
                # private document contents must never enter application logs.
                _LOGGER.warning(
                    "Anthropic document extraction authentication was rejected (HTTP %s).",
                    error.code,
                )
                raise DocumentExtractionError(
                    "The document extraction provider rejected its server-side "
                    "credentials. Contact an administrator to update the configured "
                    "provider credential."
                ) from error
            raise DocumentExtractionError(
                "The document extraction provider is temporarily unavailable."
            ) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise DocumentExtractionError(
                "The document extraction provider is temporarily unavailable."
            ) from error

        content_blocks = response.get("content", [])
        text = next(
            (
                block.get("text")
                for block in content_blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ),
            None,
        )
        if not isinstance(text, str):
            raise DocumentExtractionError(
                "The document extraction provider returned an invalid response."
            )
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            extracted = json.loads(text)
        except json.JSONDecodeError as error:
            raise DocumentExtractionError(
                "The document extraction provider returned an invalid response."
            ) from error
        if not isinstance(extracted, dict):
            raise DocumentExtractionError(
                "The document extraction provider returned an invalid response."
            )
        return extracted

    @staticmethod
    def _validated_fields(
        response: dict[str, Any],
        evidence_type: EvidenceType,
    ) -> dict[str, Any]:
        """Validate the constrained provider response before persistence."""

        expected_document_type = {
            EvidenceType.ID_CARD: "netherlands_identity_card",
            EvidenceType.DRIVING_LICENCE: "netherlands_driving_licence",
        }[evidence_type]
        if response.get("document_type") != expected_document_type:
            raise DocumentExtractionError(
                "The upload is not the selected Netherlands identity-document type."
            )

        fields: dict[str, Any] = {}
        for key in (
            "holder_name",
            "document_number",
            "nationality",
            "issue_date",
            "expiry_date",
        ):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                fields[key] = value.strip()

        categories = response.get("categories")
        if evidence_type is EvidenceType.DRIVING_LICENCE and isinstance(
            categories, list
        ):
            fields["categories"] = [
                category.strip()
                for category in categories
                if isinstance(category, str) and category.strip()
            ]
        code_95 = response.get("code_95")
        if evidence_type is EvidenceType.DRIVING_LICENCE and isinstance(
            code_95, bool
        ):
            fields["code_95"] = code_95

        if not fields.get("holder_name") or not fields.get("document_number"):
            raise DocumentExtractionError(
                "The document extraction result is incomplete; request a clearer upload."
            )
        return fields
