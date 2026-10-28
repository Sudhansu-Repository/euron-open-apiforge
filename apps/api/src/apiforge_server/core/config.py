"""Runtime configuration, validated once at boot.

Every setting comes from the environment. Security-relevant settings are checked by
``Settings.guard`` so a misconfigured production deployment refuses to start instead of
running with demo secrets.

Redis is optional: leave ``REDIS_URL`` empty and rate limits, the lint cache and config
invalidation run in process (correct for one single-process replica; use Redis for
several replicas or WEB_CONCURRENCY above 1).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_SECRETS = {"", "change-me", "replace-with-output-of-make-env", "dev", "secret"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "production"] = "development"
    cloud: Literal["local", "floci", "aws"] = Field("local", alias="APIFORGE_CLOUD")
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://apiforge:apiforge@localhost:4642/apiforge"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Empty: no Redis. Rate limits, the lint cache and config invalidation run in process.
    redis_url: str = ""

    session_secret: str = "dev-session-secret-not-for-production"  # noqa: S105 dev default, refused in production by guard()
    api_key_pepper: str = "dev-api-key-pepper-not-for-production"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:4610"]
    )

    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None
    s3_force_path_style: bool = False
    # Uploaded specs (specs/) and generated archives (archives/). Rows keep only the key.
    artifacts_bucket: str = "apiforge-local-artifacts"
    storage: Literal["local", "s3"] = "local"
    local_storage_dir: str = "./.data/artifacts"

    max_body_bytes: int = 25_000_000
    default_rpm_limit: int = 600
    # Spec uploads: one file, or a zip with relative $refs (see apiforge.loader limits).
    max_spec_bytes: int = Field(5 * 1024 * 1024, ge=1024)

    # Generations run in the worker. A job whose worker died is retried after its lease.
    worker_concurrency: int = Field(2, ge=1, le=32)
    worker_poll_s: float = Field(1.0, gt=0)
    generation_timeout_s: int = Field(120, ge=10)
    generation_max_attempts: int = Field(3, ge=1, le=10)
    # When set, /metrics needs "Authorization: Bearer <token>".
    metrics_token: str | None = None
    # The worker serves its own /metrics here; 0 turns it off.
    worker_metrics_port: int = Field(9464, ge=0, le=65535)

    otel_enabled: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def cache_backend(self) -> Literal["redis", "memory"]:
        return "redis" if self.redis_url else "memory"

    def guard(self) -> None:
        """Refuse to boot in production with demo secrets or unsafe options."""
        if self.environment != "production":
            return
        problems: list[str] = []
        for name in ("session_secret", "api_key_pepper"):
            value = getattr(self, name)
            if value in INSECURE_SECRETS or "not-for-production" in value or len(value) < 32:
                problems.append(f"{name.upper()} must be a random value of at least 32 chars")
        if self.session_secret == self.api_key_pepper:
            problems.append("SESSION_SECRET and API_KEY_PEPPER must differ")
        if self.cloud == "aws" and self.aws_endpoint_url:
            problems.append("AWS_ENDPOINT_URL must be unset when APIFORGE_CLOUD=aws")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if self.storage == "local":
            problems.append("STORAGE must be s3 in production (local disk is per container)")
        if problems:
            raise RuntimeError("unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.guard()
    return settings
