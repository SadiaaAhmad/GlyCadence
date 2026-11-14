from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or root .env."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="GlyCadence API")
    app_version: str = Field(default="0.1.0")
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: str | None = Field(default=None)
    jwt_secret_key: str = Field(default="dev-only-insecure-fallback-change-in-env")
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=20)
    jwt_refresh_token_expire_days: int = Field(default=7)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def validate_jwt_secret_for_env(self) -> "Settings":
        env = self.app_env.strip().lower()
        if env not in {"development", "dev", "test"} and (
            not self.jwt_secret_key
            or self.jwt_secret_key == "dev-only-insecure-fallback-change-in-env"
            or len(self.jwt_secret_key) < 32
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be set to a strong secret (>=32 chars) outside development/test"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
