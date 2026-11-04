"""Application settings.

Variable names match the root `.env.example` exactly (see CLAUDE.md rule 2).
The backend refuses to start against anything other than the PayPal sandbox.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
SANDBOX_HOST = "api-m.sandbox.paypal.com"
DEFAULT_SQLITE_URL = f"sqlite:///{(ROOT_DIR / 'backend' / 'staycovered.db').as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # PayPal (sandbox only)
    PAYPAL_ENVIRONMENT: str = "sandbox"
    PAYPAL_BASE_URL: str = f"https://{SANDBOX_HOST}"
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_WEBHOOK_ID: str = ""

    # AI (used from Feature 2)
    AI_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = ""
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = ""
    AI_CONFIDENCE_THRESHOLD: float = 0.7

    # App
    PUBLIC_BASE_URL: str = ""
    FRONTEND_ORIGIN: str = "http://localhost:3000"
    DATABASE_URL: str = ""
    FILE_STORAGE_PATH: str = "./uploads"
    SIGNATURE_THRESHOLD_USD: float = 750.0
    AUTO_SUBMIT_EVIDENCE: bool = False

    @field_validator("AI_CONFIDENCE_THRESHOLD", "SIGNATURE_THRESHOLD_USD", mode="before")
    @classmethod
    def _blank_float(cls, v: object, info):  # empty string in .env -> default
        if v == "" or v is None:
            return cls.model_fields[info.field_name].default
        return v

    @field_validator("AUTO_SUBMIT_EVIDENCE", mode="before")
    @classmethod
    def _blank_bool(cls, v: object):
        return False if v in ("", None) else v

    @property
    def database_url(self) -> str:
        """Normalised SQLAlchemy URL. Empty -> local SQLite file (dev only)."""
        url = self.DATABASE_URL.strip()
        if not url:
            return DEFAULT_SQLITE_URL
        # Render/Heroku style URLs -> psycopg 3 driver
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    @property
    def paypal_configured(self) -> bool:
        return bool(self.PAYPAL_CLIENT_ID and self.PAYPAL_CLIENT_SECRET)


class ConfigError(RuntimeError):
    pass


def assert_sandbox(settings: Settings) -> None:
    """Startup guard (AC1.4): refuse anything that is not the PayPal sandbox."""
    if settings.PAYPAL_ENVIRONMENT.strip().lower() != "sandbox":
        raise ConfigError(
            f"PAYPAL_ENVIRONMENT must be 'sandbox' (got {settings.PAYPAL_ENVIRONMENT!r}). "
            "StayCovered only runs against the PayPal sandbox."
        )
    parsed = urlparse(settings.PAYPAL_BASE_URL.strip())
    if parsed.scheme != "https" or parsed.hostname != SANDBOX_HOST:
        raise ConfigError(
            f"PAYPAL_BASE_URL must be https://{SANDBOX_HOST} (got host {parsed.hostname!r})."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
