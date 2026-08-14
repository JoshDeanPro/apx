"""Environment-driven configuration for the OpenPower API.

All values come from environment variables (optionally loaded from a local
.env file for development). See .env.example at the repo root for the
authoritative list of what's required and why. Nothing here should ever
contain a real secret literal.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = Field(..., alias="DATABASE_URL")

    # Supabase / JWT verification
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_jwks_url: str = Field(default="", alias="SUPABASE_JWKS_URL")
    supabase_jwt_algorithms: str = Field(default="ES256,RS256", alias="SUPABASE_JWT_ALGORITHMS")
    supabase_jwt_audience: str = Field(default="authenticated", alias="SUPABASE_JWT_AUDIENCE")
    supabase_jwt_legacy_hs256_secret: str = Field(default="", alias="SUPABASE_JWT_LEGACY_HS256_SECRET")

    # Service
    openpower_api_host: str = Field(default="127.0.0.1", alias="OPENPOWER_API_HOST")
    openpower_api_port: int = Field(default=8100, alias="OPENPOWER_API_PORT")
    openpower_env: str = Field(default="production", alias="OPENPOWER_ENV")

    # Rate limiting
    rate_limit_max: int = Field(default=10, alias="OPENPOWER_RATE_LIMIT_MAX")
    rate_limit_window_seconds: int = Field(default=60, alias="OPENPOWER_RATE_LIMIT_WINDOW_SECONDS")

    # AXP identity linking (see openpower_axp.py). A symmetric secret shared with
    # every AXP instance that links to this OpenPower account -- HS256, matching
    # AXP's own stdlib-only auth_openpower.py verifier. Empty until configured;
    # the token-issuing endpoint 503s rather than minting with an empty secret.
    openpower_axp_shared_secret: str = Field(default="", alias="OPENPOWER_AXP_SHARED_SECRET")
    openpower_axp_token_ttl_days: int = Field(default=365, alias="OPENPOWER_AXP_TOKEN_TTL_DAYS")

    @field_validator("supabase_jwt_algorithms")
    @classmethod
    def _non_empty_algorithms(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("SUPABASE_JWT_ALGORITHMS must not be empty")
        return v

    @property
    def jwt_algorithms(self) -> list[str]:
        return [a.strip() for a in self.supabase_jwt_algorithms.split(",") if a.strip()]

    @property
    def jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if self.supabase_url:
            return self.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        return ""

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
