"""Application configuration with strict Pydantic settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    codex_bin: str = Field(default="codex", alias="CODEX_BIN")
    codex_model: str = Field(default="gpt-5.3-codex", alias="CODEX_MODEL")
    codex_cwd: str | None = Field(default=None, alias="CODEX_CWD")
    codex_client_name: str = Field(default="codex_whatsapp_agent", alias="CODEX_CLIENT_NAME")

    sidecar_url: str = Field(default="http://127.0.0.1:3001", alias="SIDECAR_URL")
    sidecar_shared_secret: str | None = Field(default=None, alias="SIDECAR_SHARED_SECRET")

    whatsapp_access_mode: str = Field(default="self_chat", alias="WHATSAPP_ACCESS_MODE")
    whatsapp_approved_numbers: str | list[str] | None = Field(
        default=None,
        alias="WHATSAPP_APPROVED_NUMBERS",
    )

    database_path: Path = Field(default=Path("data/state.db"), alias="DATABASE_PATH")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
