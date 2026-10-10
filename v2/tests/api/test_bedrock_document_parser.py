"""Claude-on-Bedrock identity-document reader, exercised with a fake AWS client."""

from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError

from app.config import Settings
from app.models import EvidenceType
from app.providers.documents import (
    BedrockDocumentParser,
    DocumentExtractionError,
    MockDocumentParser,
)
from app.providers.storage import S3Storage

REFERENCE = "objects/ab/" + "a" * 64
GOOD_REPLY = {
    "document_type": "netherlands_identity_card",
    "holder_name": "Jan de Vries",
    "document_number": "SPEC12345",
    "nationality": "Nederlandse",
    "issue_date": "2022-03-01",
    "expiry_date": "2032-03-01",
}


class _Storage:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def get(self, reference: str) -> bytes:
        return self.content


class _FakeBedrock:
    def __init__(self, text: str | None = None, error: str | None = None) -> None:
        self.text, self.error, self.calls = text, error, []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise ClientError({"Error": {"Code": self.error}}, "Converse")
        return {"output": {"message": {"content": [{"text": self.text}]}}}


def _parser(content: bytes, client: _FakeBedrock) -> BedrockDocumentParser:
    parser = BedrockDocumentParser(
        access_key_id="k", secret_access_key="s", region="us-east-2",
        model_id="test-model", storage=_Storage(content),
    )
    parser._client = client
    return parser


def _extract(parser, media_type="image/png"):
    return parser.extract(
        storage_reference=REFERENCE,
        evidence_type=EvidenceType.ID_CARD,
        media_type=media_type,
    )


def test_real_document_is_read_through_converse():
    client = _FakeBedrock(json.dumps(GOOD_REPLY))
    result = _extract(_parser(b"\x89PNG real card bytes", client))
    assert result.fields["holder_name"] == "Jan de Vries"
    assert result.fields["expiry_date"] == "2032-03-01"
    assert result.provider_mode == "EXTERNAL"
    assert result.processing_metadata["provider"] == "bedrock"
    call = client.calls[0]
    assert call["modelId"] == "test-model"
    attachment = call["messages"][0]["content"][0]
    assert attachment["image"]["format"] == "png"
    assert attachment["image"]["source"]["bytes"] == b"\x89PNG real card bytes"


def test_pdf_is_sent_as_a_document_and_fenced_json_is_accepted():
    client = _FakeBedrock("```json\n" + json.dumps(GOOD_REPLY) + "\n```")
    result = _extract(_parser(b"%PDF-1.4", client), media_type="application/pdf")
    assert result.fields["document_number"] == "SPEC12345"
    assert client.calls[0]["messages"][0]["content"][0]["document"]["format"] == "pdf"


def test_demo_marked_file_never_reaches_aws():
    client = _FakeBedrock(json.dumps(GOOD_REPLY))
    result = _extract(_parser(b"...DEMO - NOT A REAL CREDENTIAL...", client))
    assert client.calls == []
    assert result.provider_mode == "DEMO"


def test_wrong_document_type_is_rejected():
    reply = dict(GOOD_REPLY, document_type="unsupported")
    with pytest.raises(DocumentExtractionError, match="Netherlands"):
        _extract(_parser(b"real", _FakeBedrock(json.dumps(reply))))


def test_non_json_reply_is_a_safe_error():
    with pytest.raises(DocumentExtractionError, match="invalid response"):
        _extract(_parser(b"real", _FakeBedrock("I cannot read this.")))


@pytest.mark.parametrize("code", ["AccessDeniedException", "UnrecognizedClientException"])
def test_credential_failures_do_not_leak_details(code):
    with pytest.raises(DocumentExtractionError) as raised:
        _extract(_parser(b"real", _FakeBedrock(error=code)))
    assert "credentials" in str(raised.value)
    assert "AKIA" not in str(raised.value)


def test_throttling_is_reported_as_temporary():
    with pytest.raises(DocumentExtractionError, match="temporarily unavailable"):
        _extract(_parser(b"real", _FakeBedrock(error="ThrottlingException")))


def test_only_real_parsers_may_accept_unmarked_documents():
    assert MockDocumentParser.reads_real_documents is False
    assert BedrockDocumentParser.reads_real_documents is True


def _settings(**overrides) -> Settings:
    values = {
        "OCR_PROVIDER": "bedrock",
        "BEDROCK_ACCESS_KEY_ID": "k",
        "BEDROCK_SECRET_ACCESS_KEY": "s",
        "BEDROCK_REGION": "us-east-2",
        "BEDROCK_MODEL_ID": "test-model",
    }
    values.update(overrides)
    return Settings(**values)


def test_complete_bedrock_settings_keep_bedrock():
    settings = _settings()
    settings.prepare_local_runtime()
    assert settings.ocr_provider == "bedrock"


def test_missing_model_id_falls_back_to_mock():
    settings = _settings(BEDROCK_MODEL_ID="")
    notices = settings.prepare_local_runtime()
    assert settings.ocr_provider == "mock"
    assert any("Document extraction" in n for n in notices)
