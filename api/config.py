"""Configuration. Everything secret comes from .env, nothing is hard-coded."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # database
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "aira"
    db_user: str = "aira_app"
    db_password: str = ""

    # auth
    jwt_secret: str = "dev-only"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    # sarvam
    sarvam_mode: str = "mock"
    sarvam_api_key: str = ""
    sarvam_max_live_calls: int = 30

    # gemini - the phrasing layer. It never decides a tier, and `mock` is the
    # default so that no code path can quietly start costing money.
    gemini_mode: str = "mock"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_max_calls: int = 400

    # documents
    max_upload_bytes: int = 5 * 1024 * 1024

    # app
    cors_origins: str = "http://localhost:5173"
    ruleset_dir: str = "rules"
    link_pin_ttl_minutes: int = 10
    link_pin_max_attempts: int = 3
    consent_default_days: int = 90

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
