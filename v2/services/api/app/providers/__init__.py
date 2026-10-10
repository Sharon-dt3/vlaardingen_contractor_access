"""Configured provider composition for API domain services."""

from functools import lru_cache

from app.config import get_settings
from app.providers.documents import (
    AnthropicDocumentParser,
    BedrockDocumentParser,
    DocumentExtractionError,
    DocumentExtractionProvider,
    ExtractionResult,
    MockDocumentParser,
)
from app.providers.identity import (
    IdentityVerificationProvider,
    IdentityVerificationResult,
    MockIdentityVerifier,
)
from app.providers.notifications import (
    InAppNotificationProvider,
    NotificationDeliveryResult,
    NotificationProvider,
)
from app.providers.storage import LocalStorage, S3Storage, StorageProvider, StoredObject


# PUBLIC_INTERFACE
def get_document_extraction_provider() -> DocumentExtractionProvider:
    """Return the configured server-side document extraction provider."""

    settings = get_settings()
    if settings.ocr_provider == "mock":
        return MockDocumentParser()
    if settings.ocr_provider == "anthropic" and settings.anthropic_api_key:
        api_key = settings.anthropic_api_key.get_secret_value()
        if api_key:
            return AnthropicDocumentParser(
                api_key=api_key,
                model=settings.anthropic_model,
                storage=get_storage_provider(),
            )
    if (
        settings.ocr_provider == "bedrock"
        and settings.bedrock_access_key_id
        and settings.bedrock_secret_access_key
    ):
        access_key_id = settings.bedrock_access_key_id.get_secret_value()
        secret_access_key = settings.bedrock_secret_access_key.get_secret_value()
        if access_key_id and secret_access_key:
            return BedrockDocumentParser(
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                region=settings.bedrock_region,
                model_id=settings.bedrock_model_id,
                storage=get_storage_provider(),
            )
    raise RuntimeError("The configured document extraction adapter is unavailable.")


# PUBLIC_INTERFACE
def get_storage_provider() -> StorageProvider:
    """Return private local or S3-compatible storage selected by validated settings."""

    settings = get_settings()
    if settings.storage_provider == "local":
        return LocalStorage(settings.storage_local_path)
    if settings.storage_provider == "s3":
        return _s3_storage(
            settings.s3_endpoint_url,
            settings.s3_region,
            settings.s3_bucket,
            settings.s3_access_key_id.get_secret_value(),
            settings.s3_secret_access_key.get_secret_value(),
        )
    raise RuntimeError("The configured external storage adapter is unavailable.")


@lru_cache(maxsize=1)
def _s3_storage(
    endpoint_url: str, region: str, bucket: str, access_key_id: str, secret_access_key: str
) -> S3Storage:
    """Build one reusable S3 client; boto3 clients are thread-safe."""

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )
    return S3Storage(client, bucket)


# PUBLIC_INTERFACE
def get_identity_verification_provider() -> IdentityVerificationProvider:
    """Return the deterministic identity adapter selected for the local demo."""

    settings = get_settings()
    if settings.identity_verifier_provider != "mock":
        raise RuntimeError(
            "The configured external identity adapter is not available in this demo."
        )
    return MockIdentityVerifier()


# PUBLIC_INTERFACE
def get_notification_provider() -> NotificationProvider:
    """Return the local in-app notification adapter for credential-free workflows."""

    return InAppNotificationProvider()


__all__ = [
    "DocumentExtractionProvider",
    "DocumentExtractionError",
    "ExtractionResult",
    "IdentityVerificationProvider",
    "IdentityVerificationResult",
    "InAppNotificationProvider",
    "LocalStorage",
    "S3Storage",
    "AnthropicDocumentParser",
    "BedrockDocumentParser",
    "MockDocumentParser",
    "MockIdentityVerifier",
    "NotificationDeliveryResult",
    "NotificationProvider",
    "StorageProvider",
    "StoredObject",
    "get_document_extraction_provider",
    "get_identity_verification_provider",
    "get_notification_provider",
    "get_storage_provider",
]
