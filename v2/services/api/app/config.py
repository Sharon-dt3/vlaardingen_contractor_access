"""Validated runtime configuration for the API service."""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server-only settings loaded from the process environment."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        extra="ignore",
    )

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    backend_port: int = Field(default=8000, validation_alias="BACKEND_PORT")
    web_origin: str = Field(
        default="http://localhost:3000",
        validation_alias="WEB_ORIGIN",
    )
    database_url: str = Field(
        default="postgresql+psycopg://renewi@postgres:5432/renewi_access",
        validation_alias="DATABASE_URL",
    )
    redis_url: str = Field(
        default="redis://redis:6379/0",
        validation_alias="REDIS_URL",
    )
    demo_mode: bool = Field(default=True, validation_alias="DEMO_MODE")
    demo_timezone: str = Field(
        default="Europe/Amsterdam",
        validation_alias="DEMO_TIMEZONE",
    )
    session_cookie_secure: bool = Field(
        default=False,
        validation_alias="SESSION_COOKIE_SECURE",
    )
    session_cookie_name: str = Field(
        default="renewi_session",
        validation_alias="SESSION_COOKIE_NAME",
    )
    session_ttl_seconds: int = Field(
        default=28_800,
        ge=300,
        le=86_400,
        validation_alias="SESSION_TTL_SECONDS",
    )

    storage_provider: str = Field(default="local", validation_alias="STORAGE_PROVIDER")
    storage_local_path: str = Field(
        default="/var/lib/renewi/evidence",
        validation_alias="STORAGE_LOCAL_PATH",
    )
    ocr_provider: str = Field(default="anthropic", validation_alias="OCR_PROVIDER")
    identity_verifier_provider: str = Field(
        default="mock",
        validation_alias="IDENTITY_VERIFIER_PROVIDER",
    )
    notification_provider: str = Field(default="mock", validation_alias="NOTIFICATION_PROVIDER")
    auth_provider: str = Field(default="demo", validation_alias="AUTH_PROVIDER")

    app_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias="APP_SECRET_KEY",
    )
    demo_seed_password: SecretStr | None = Field(
        default=SecretStr("renewi-demo-access"),
        validation_alias="DEMO_SEED_PASSWORD",
    )
    e2e_baseline_token: SecretStr | None = Field(
        default=None,
        validation_alias="E2E_BASELINE_TOKEN",
    )

    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
    )
    anthropic_model: str = Field(
        default="claude-sonnet-5-5",
        validation_alias="ANTHROPIC_MODEL",
    )
    bedrock_access_key_id: SecretStr | None = Field(
        default=None,
        validation_alias="BEDROCK_ACCESS_KEY_ID",
    )
    bedrock_secret_access_key: SecretStr | None = Field(
        default=None,
        validation_alias="BEDROCK_SECRET_ACCESS_KEY",
    )
    bedrock_region: str = Field(default="eu-central-1", validation_alias="BEDROCK_REGION")
    bedrock_model_id: str = Field(default="", validation_alias="BEDROCK_MODEL_ID")
    s3_endpoint_url: str = Field(default="", validation_alias="S3_ENDPOINT_URL")
    s3_region: str = Field(default="", validation_alias="S3_REGION")
    s3_bucket: str = Field(default="", validation_alias="S3_BUCKET")
    s3_access_key_id: SecretStr | None = Field(
        default=None,
        validation_alias="S3_ACCESS_KEY_ID",
    )
    s3_secret_access_key: SecretStr | None = Field(
        default=None,
        validation_alias="S3_SECRET_ACCESS_KEY",
    )
    identity_provider_api_url: str = Field(
        default="",
        validation_alias="IDENTITY_PROVIDER_API_URL",
    )
    identity_provider_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="IDENTITY_PROVIDER_API_KEY",
    )
    # "on": walk-up people must enter a code emailed to them before they are registered.
    # "off": no email check (for setups without a mail server).
    walk_up_email_check: str = Field(default="on", validation_alias="WALK_UP_EMAIL_CHECK")
    smtp_host: str = Field(default="smtp.gmail.com", validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=587, ge=1, le=65535, validation_alias="SMTP_PORT")
    smtp_username: str = Field(default="", validation_alias="SMTP_USERNAME")
    smtp_password: SecretStr | None = Field(
        default=None,
        validation_alias="SMTP_PASSWORD",
    )
    smtp_from_address: str = Field(
        default="",
        validation_alias="SMTP_FROM_ADDRESS",
    )

    # PUBLIC_INTERFACE
    def prepare_local_runtime(self) -> list[str]:
        """Generate local-only values and select safe provider fallbacks.

        Returns:
            Sanitized notices describing fallbacks without exposing configuration
            values or secrets.
        """

        notices: list[str] = []

        if not self.app_secret_key or not self.app_secret_key.get_secret_value():
            self.app_secret_key = SecretStr(secrets.token_urlsafe(32))
            notices.append("Generated an in-memory local application signing key.")

        if (
            not self.demo_seed_password
            or not self.demo_seed_password.get_secret_value()
        ):
            self.demo_seed_password = SecretStr("renewi-demo-access")
            notices.append("Selected the deterministic local demo seed password.")

        if self.ocr_provider == "bedrock":
            bedrock_configured = bool(
                self._secret_is_set(self.bedrock_access_key_id)
                and self._secret_is_set(self.bedrock_secret_access_key)
                and self.bedrock_region
                and self.bedrock_model_id
            )
        else:
            bedrock_configured = False
        if self.ocr_provider != "mock" and not (
            bedrock_configured
            or (
                self.ocr_provider == "anthropic"
                and self._secret_is_set(self.anthropic_api_key)
            )
        ):
            self.ocr_provider = "mock"
            notices.append(
                "Document extraction integration is incomplete; selected the deterministic mock provider."
            )

        s3_configured = all(
            (
                self.s3_endpoint_url,
                self.s3_region,
                self.s3_bucket,
                self._secret_is_set(self.s3_access_key_id),
                self._secret_is_set(self.s3_secret_access_key),
            )
        )
        if self.storage_provider != "local" and s3_configured:
            self.storage_provider = "s3"
        elif self.storage_provider != "local":
            self.storage_provider = "local"
            notices.append(
                "Object storage integration is incomplete; selected private local storage."
            )

        identity_configured = bool(
            self.identity_provider_api_url
            and self._secret_is_set(self.identity_provider_api_key)
        )
        if self.identity_verifier_provider != "mock" and not identity_configured:
            self.identity_verifier_provider = "mock"
            notices.append(
                "Identity integration is incomplete; selected the deterministic mock provider."
            )

        smtp_configured = bool(
            self.smtp_host
            and self.smtp_port
            and self.smtp_username
            and self._secret_is_set(self.smtp_password)
        )
        if smtp_configured:
            self.notification_provider = "smtp"
        else:
            self.notification_provider = "mock"
            notices.append("SMTP credentials are unavailable; invitations remain local-only.")

        if self.auth_provider != "demo":
            self.auth_provider = "demo"
            notices.append(
                "External authentication is unavailable; selected the local demo provider."
            )

        return notices

    # PUBLIC_INTERFACE
    def provider_modes(self) -> dict[str, Literal["DEMO", "LOCAL", "EXTERNAL"]]:
        """Return sanitized provider modes suitable for health responses."""

        return {
            "authentication": (
                "DEMO" if self.auth_provider == "demo" else "EXTERNAL"
            ),
            "document_extraction": (
                "DEMO" if self.ocr_provider == "mock" else "EXTERNAL"
            ),
            "identity_verification": (
                "DEMO"
                if self.identity_verifier_provider == "mock"
                else "EXTERNAL"
            ),
            "notifications": (
                "DEMO"
                if self.notification_provider == "mock"
                else "EXTERNAL"
            ),
            "storage": (
                "LOCAL" if self.storage_provider == "local" else "EXTERNAL"
            ),
        }

    @staticmethod
    def _secret_is_set(value: SecretStr | None) -> bool:
        return bool(value and value.get_secret_value())


# PUBLIC_INTERFACE
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""

    return Settings()
