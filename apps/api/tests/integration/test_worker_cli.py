"""The worker loop, the command line and the demo seed, run for real."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from apiforge_server import cli, worker
from apiforge_server.generations.models import Generation
from apiforge_server.projects.models import Project
from apiforge_server.users.models import User
from tests.integration.conftest import Api, corpus

pytestmark = pytest.mark.integration


async def test_the_worker_schedule_runs_queued_generations(api: Api) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.ok("POST", f"/api/v1/projects/{slug}/generations", {}, status=202)
    schedule = worker.jobs(api.container)
    assert [j.name for j in schedule] == ["generations"]
    assert await worker.run_due(api.container, schedule, now=1_000_000.0) == 1
    # It found work, so it runs again at once, finds the queue empty and goes idle.
    assert schedule[0].busy
    assert await worker.run_due(api.container, schedule, now=1_000_000.1) == 1
    assert not schedule[0].busy
    assert await worker.run_due(api.container, schedule, now=1_000_000.2) == 0  # not due yet
    gen = await api.ok("GET", f"/api/v1/projects/{slug}/generations/1")
    assert gen["status"] == "succeeded"


async def test_a_failing_job_is_logged_and_the_others_keep_running(api: Api) -> None:
    calls: list[str] = []

    async def broken(container: object) -> None:
        calls.append("broken")
        raise RuntimeError("boom")

    async def fine(container: object) -> None:
        calls.append("fine")

    schedule = [worker.Job("broken", 1, broken), worker.Job("fine", 1, fine)]
    assert await worker.run_due(api.container, schedule, now=10.0) == 2
    assert calls == ["broken", "fine"]


def test_cli_prints_the_openapi_document(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["openapi"])
    out = capsys.readouterr().out
    assert out.startswith("openapi:") and "/api/v1/projects/{slug}/generations" in out


async def test_cli_creates_and_resets_an_owner(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", api.container.settings.database_url)
    monkeypatch.setenv("APIFORGE_OWNER_PASSWORD", "Fresh-Owner-Pass-1")
    from apiforge_server.core.config import get_settings

    get_settings.cache_clear()
    try:
        await cli._create_owner(
            "second@example.test", "Second", cli._checked_hash("Fresh-Owner-Pass-1")
        )
        await cli._create_owner(
            "second@example.test", "Second", cli._checked_hash("Fresh-Owner-Pass-2")
        )
    finally:
        get_settings.cache_clear()
    async with api.container.db.sessionmaker() as session:
        owners = (await session.scalars(select(User).where(User.role == "owner"))).all()
    assert {u.email for u in owners} == {"owner@example.test", "second@example.test"}


def test_hash_password_prints_an_argon2id_hash_that_verifies(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from apiforge_server.core.security import verify_password

    monkeypatch.setenv("APIFORGE_OWNER_PASSWORD", "Cloud-Owner-Pass-9")
    cli.main(["hash-password"])
    printed = capsys.readouterr().out.strip()
    assert printed.startswith("$argon2id$") and "Cloud-Owner-Pass-9" not in printed
    assert verify_password("Cloud-Owner-Pass-9", printed)


def test_create_owner_refuses_a_hash_that_is_not_argon2id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIFORGE_OWNER_PASSWORD_HASH", "plaintext-password")
    with pytest.raises(SystemExit, match="argon2id"):
        cli.main(["create-owner", "--email", "x@example.test"])


async def test_the_demo_seed_fills_every_screen_and_is_idempotent(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apiforge_server.core.config import get_settings
    from apiforge_server.demo import seed

    s = api.container.settings
    for key, value in {
        "DATABASE_URL": s.database_url,
        "REDIS_URL": s.redis_url,
        "LOCAL_STORAGE_DIR": s.local_storage_dir,
        "STORAGE": s.storage,
        "ARTIFACTS_BUCKET": s.artifacts_bucket,
        "AWS_ENDPOINT_URL": s.aws_endpoint_url or "",
        "S3_FORCE_PATH_STYLE": "true",
        "DEMO_PASSWORD": "Demo-Pass-1234",
    }.items():
        if value:
            monkeypatch.setenv(key, value)
    if not s.aws_endpoint_url:
        monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    get_settings.cache_clear()
    try:
        await seed.run()
        await seed.run()  # the second run changes nothing
    finally:
        get_settings.cache_clear()
    async with api.container.db.sessionmaker() as session:
        projects = await session.scalar(select(func.count()).select_from(Project))
        statuses = (await session.scalars(select(Generation.status))).all()
    assert projects == 5
    assert statuses and set(statuses) == {"succeeded"}
    overview = await api.ok("GET", "/api/v1/overview")
    assert overview["spec_versions"] == 8 and overview["generations"] == 7


async def test_api_keys_can_be_edited(api: Api) -> None:
    created = await api.ok("POST", "/api/v1/keys", {"name": "ci"})
    updated = await api.ok(
        "PATCH", f"/api/v1/keys/{created['id']}", {"name": "ci-downloads", "rpm_limit": 30}
    )
    assert updated["name"] == "ci-downloads" and updated["rpm_limit"] == 30
    listed = await api.ok("GET", "/api/v1/keys")
    assert [k["name"] for k in listed] == ["ci-downloads"]


def test_the_demo_seed_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from apiforge_server.core.config import get_settings

    monkeypatch.setattr(
        cli, "get_settings", lambda: get_settings().model_copy(update={"environment": "production"})
    )
    with pytest.raises(SystemExit, match="refuses ENVIRONMENT=production"):
        cli.main(["seed-demo"])
