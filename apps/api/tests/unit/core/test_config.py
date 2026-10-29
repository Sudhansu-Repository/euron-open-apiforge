import pytest

from apiforge_server.core.config import Settings

STRONG = "x" * 40


def prod(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "session_secret": STRONG,
        "api_key_pepper": "y" * 40,
        "cookie_secure": True,
        "storage": "s3",
        "cors_origins": "https://apiforge.example.com",
        "database_url": "postgresql+asyncpg://app:secret@db.internal:5432/apiforge",
        "metrics_token": "z" * 40,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_development_defaults_boot() -> None:
    Settings().guard()


def test_production_with_strong_secrets_boots() -> None:
    prod().guard()


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"session_secret": "dev-session-secret-not-for-production"}, "SESSION_SECRET"),
        ({"api_key_pepper": "short"}, "API_KEY_PEPPER"),
        ({"api_key_pepper": STRONG}, "must differ"),
        (
            {"APIFORGE_CLOUD": "aws", "aws_endpoint_url": "http://floci:4566"},
            "AWS_ENDPOINT_URL",
        ),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"storage": "local"}, "STORAGE"),
        ({"cors_origins": "*"}, "CORS_ORIGINS"),
        ({"cors_origins": "http://apiforge.example.com"}, "CORS_ORIGINS"),
        (
            {"database_url": "postgresql+asyncpg://apiforge:apiforge@localhost:4642/apiforge"},
            "DATABASE_URL",
        ),
        ({"metrics_token": None}, "METRICS_TOKEN"),
    ],
)
def test_production_guards(overrides: dict[str, object], fragment: str) -> None:
    with pytest.raises(RuntimeError, match=fragment):
        prod(**overrides).guard()


def test_cors_origins_accept_comma_string() -> None:
    s = Settings(cors_origins="http://a.test, http://b.test")  # type: ignore[arg-type]
    assert s.cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:4610,http://127.0.0.1:4610")
    assert Settings().cors_origins == ["http://localhost:4610", "http://127.0.0.1:4610"]


def test_tracing_is_a_no_op_until_enabled() -> None:
    from opentelemetry import trace

    from apiforge_server.core import tracing

    # Checked by identity, not by span recording: another test in the same process may
    # have installed an SDK provider, which this must neither need nor replace.
    before = trace.get_tracer_provider()
    tracing.configure_tracing(Settings())
    assert tracing._configured is False
    assert trace.get_tracer_provider() is before


def test_redis_is_optional() -> None:
    assert Settings().cache_backend == "memory"
    assert Settings(redis_url="redis://localhost:4679/0").cache_backend == "redis"


def test_defaults_send_nothing_anywhere() -> None:
    s = Settings()
    assert s.aws_endpoint_url is None and s.otel_enabled is False
    assert s.metrics_token is None and s.storage == "local"


def test_worker_bounds_are_validated() -> None:
    with pytest.raises(ValueError, match="worker_concurrency"):
        Settings(worker_concurrency=0)
    with pytest.raises(ValueError, match="generation_timeout_s"):
        Settings(generation_timeout_s=1)
