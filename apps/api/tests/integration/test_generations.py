"""Generations: queue, worker, archives, files, the report gate, leases and concurrency."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from apiforge.archive import build_zip
from apiforge.generator import generate
from apiforge.options import GenerateOptions
from sqlalchemy import select, update

from apiforge_server.generations import service
from apiforge_server.generations.models import Generation
from tests.integration.conftest import Api, corpus

pytestmark = pytest.mark.integration


async def test_a_generation_runs_in_the_worker_and_its_archive_is_the_cli_output(api: Api) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"), "petstore.yaml")
    queued = await api.ok("POST", f"/api/v1/projects/{slug}/generations", {}, status=202)
    assert queued["status"] == "queued" and queued["number"] == 1 and queued["spec_number"] == 1
    assert await api.work() == 1
    gen = await api.ok("GET", f"/api/v1/projects/{slug}/generations/1")
    assert gen["status"] == "succeeded" and gen["attempts"] == 1 and gen["duration_ms"] is not None
    paths = {f["path"]: f["owner"] for f in gen["files"]}
    assert (
        paths["app/handlers/pets.py"] == "user" and paths["app/generated/models.py"] == "generated"
    )

    resp = await api.client.get(f"/api/v1/projects/{slug}/generations/1/archive")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/zip"
    assert resp.headers["content-disposition"] == f'attachment; filename="{slug}-1.zip"'
    # Acceptance 6: the web app's archive is byte for byte what the CLI produces.
    cli = build_zip(generate(corpus("petstore.yaml"), "petstore.yaml", options=GenerateOptions()))
    assert (
        hashlib.sha256(resp.content).hexdigest()
        == hashlib.sha256(cli).hexdigest()
        == gen["archive_sha256"]
    )
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert "pet-store/app/main.py" in names

    etag = resp.headers["etag"]

    async def no_storage(key: str) -> bytes:
        raise AssertionError("a 304 must not read the archive from storage")

    api.container.storage.get = no_storage  # type: ignore[method-assign]
    cached = await api.client.get(
        f"/api/v1/projects/{slug}/generations/1/archive", headers={"if-none-match": etag}
    )
    assert cached.status_code == 304 and not cached.content
    assert cached.headers["etag"] == etag


async def test_files_can_be_browsed_one_by_one(api: Api) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.generate(slug)
    f = await api.ok("GET", f"/api/v1/projects/{slug}/generations/1/file?path=app/handlers/pets.py")
    assert (
        f["owner"] == "user" and f["language"] == "python" and "async def get_pet(" in f["content"]
    )
    url = f"/api/v1/projects/{slug}/generations/1/file?path=app/handlers/pets.py"
    first = await api.client.get(url)
    assert first.headers["cache-control"] == "private, no-cache"
    again = await api.client.get(url, headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304 and not again.content
    dockerfile = await api.ok("GET", f"/api/v1/projects/{slug}/generations/1/file?path=Dockerfile")
    assert dockerfile["language"] == "dockerfile"
    missing = await api.client.get(
        f"/api/v1/projects/{slug}/generations/1/file?path=../../etc/passwd"
    )
    assert missing.status_code == 404


async def test_options_default_from_the_project_and_change_the_output(api: Api) -> None:
    slug = await api.project("Inventory", db=True)
    await api.spec(slug, corpus("inventory.yaml"))
    with_db = await api.generate(slug)
    assert with_db["options"]["db"] is True and set(with_db["resources"]) == {"item", "supplier"}
    assert any(f["path"] == "app/generated/crud.py" for f in with_db["files"])
    plain = await api.generate(slug, options={"db": False, "docker": False})
    assert not any(f["path"] in ("app/generated/crud.py", "Dockerfile") for f in plain["files"])
    assert plain["archive_sha256"] != with_db["archive_sha256"]


async def test_errors_in_the_report_block_generation_until_accepted(api: Api) -> None:
    slug = await api.project()
    spec = (
        "openapi: 3.0.3\ninfo: {title: Dup, version: '1'}\npaths:\n"
        "  /a/{x}:\n    get:\n      parameters: [{name: x, in: path, required: true, schema: {type: string}}]\n"
        "      responses: {'200': {description: ok}}\n"
        "  /a/{y}:\n    get:\n      parameters: [{name: y, in: path, required: true, schema: {type: string}}]\n"
        "      responses: {'200': {description: ok}}\n"
    )
    v = await api.spec(slug, spec.encode())
    assert v["errors"] == 1
    blocked = await api.client.post(f"/api/v1/projects/{slug}/generations", json={})
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "report_has_errors"
    assert blocked.json()["error"]["details"]["errors"][0]["code"] == "duplicate_route"
    gen = await api.generate(slug, accept_report=True)
    assert gen["status"] == "succeeded" and gen["accept_report"] is True


async def test_generating_without_a_spec_explains_what_to_do(api: Api) -> None:
    slug = await api.project()
    resp = await api.client.post(f"/api/v1/projects/{slug}/generations", json={})
    assert resp.status_code == 404 and "upload one first" in resp.json()["error"]["message"]
    missing = await api.client.get(f"/api/v1/projects/{slug}/generations/9/archive")
    assert missing.status_code == 404


async def test_an_unfinished_generation_has_no_archive_yet(api: Api) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.ok("POST", f"/api/v1/projects/{slug}/generations", {}, status=202)
    resp = await api.client.get(f"/api/v1/projects/{slug}/generations/1/archive")
    assert resp.status_code == 409 and "queued" in resp.json()["error"]["message"]


async def test_a_crashed_workers_job_is_retried_then_failed_with_a_reason(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.ok("POST", f"/api/v1/projects/{slug}/generations", {}, status=202)
    assert await service.claim(api.container, 5)  # a worker takes it, then dies
    async with api.container.db.sessionmaker() as session:
        await session.execute(
            update(Generation).values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert await api.work() == 1  # picked up again after the lease ran out
    gen = await api.ok("GET", f"/api/v1/projects/{slug}/generations/1")
    assert gen["status"] == "succeeded" and gen["attempts"] == 2

    await api.ok("POST", f"/api/v1/projects/{slug}/generations", {}, status=202)
    for _ in range(api.container.settings.generation_max_attempts):
        await service.claim(api.container, 5)
        async with api.container.db.sessionmaker() as session:
            await session.execute(
                update(Generation)
                .where(Generation.number == 2)
                .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()
    with caplog.at_level(logging.WARNING, logger="apiforge_server"):
        await service.claim(api.container, 5)
    failed = await api.ok("GET", f"/api/v1/projects/{slug}/generations/2")
    assert failed["status"] == "failed" and failed["error_code"] == "worker_lost"
    # Every failure, not only crashes, writes the line the GenerationFailures alarm counts.
    lines = [r for r in caplog.records if r.getMessage() == "generation failed"]
    assert [getattr(r, "error_code", None) for r in lines] == ["worker_lost"]
    assert "Request a new generation" in failed["error"]


async def test_concurrent_workers_never_run_the_same_generation(api: Api) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    for _ in range(6):
        await api.ok("POST", f"/api/v1/projects/{slug}/generations", {}, status=202)
    claimed = await asyncio.gather(*(service.claim(api.container, 2) for _ in range(5)))
    flat = [i for batch in claimed for i in batch]
    assert len(flat) == len(set(flat)) == 6
    await asyncio.gather(*(service.run(api.container, i) for i in flat))
    async with api.container.db.sessionmaker() as session:
        statuses = (await session.scalars(select(Generation.status))).all()
    assert statuses and set(statuses) == {"succeeded"}
    hashes = {
        g["archive_sha256"] for g in await api.ok("GET", f"/api/v1/projects/{slug}/generations")
    }
    assert len(hashes) == 1  # the same spec and options: the same archive, every time


async def test_a_failure_inside_the_generator_is_recorded_not_raised(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("simulated bug")

    monkeypatch.setattr(service, "_run_generator", boom)
    with caplog.at_level(logging.WARNING, logger="apiforge_server"):
        gen = await api.generate(slug)
    assert gen["status"] == "failed" and gen["error_code"] == "internal_error"
    failures = [r for r in caplog.records if r.getMessage() == "generation failed"]
    assert len(failures) == 1 and getattr(failures[0], "error_code", None) == "internal_error"
    assert "report it" in gen["error"]


async def test_overview_counts_and_recent_activity(api: Api) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.generate(slug)
    overview = await api.ok("GET", "/api/v1/overview")
    assert (overview["projects"], overview["spec_versions"], overview["operations"]) == (1, 1, 4)
    assert overview["generations_7d"] == overview["succeeded_7d"] == 1 and overview["queued"] == 0
    assert overview["recent_generations"][0]["project_slug"] == slug
    assert overview["recent_specs"][0]["added"] == 4


async def test_a_worker_that_lost_its_lease_records_nothing(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.ok("POST", f"/api/v1/projects/{slug}/generations", {}, status=202)
    [claimed] = await service.claim(api.container, 1)
    real_put = api.container.storage.put

    async def reclaimed_meanwhile(key: str, data: bytes, content_type: str) -> None:
        # While this worker was busy its lease expired and another worker claimed the job.
        async with api.container.db.sessionmaker() as session:
            await session.execute(
                update(Generation).where(Generation.id == claimed).values(attempts=2)
            )
            await session.commit()
        await real_put(key, data, content_type)

    monkeypatch.setattr(api.container.storage, "put", reclaimed_meanwhile)
    await service.run(api.container, claimed)
    gen = await api.ok("GET", f"/api/v1/projects/{slug}/generations/1")
    # Still running, owned by the second claim: the first worker's result was not written.
    assert gen["status"] == "running" and gen["attempts"] == 2 and gen["archive_sha256"] is None


async def test_a_project_deleted_mid_generation_leaves_no_archive_behind(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.ok("POST", f"/api/v1/projects/{slug}/generations", {}, status=202)
    [claimed] = await service.claim(api.container, 1)
    real_put = api.container.storage.put
    stored: list[str] = []

    async def deleted_meanwhile(key: str, data: bytes, content_type: str) -> None:
        await real_put(key, data, content_type)
        stored.append(key)
        assert (await api.client.delete(f"/api/v1/projects/{slug}")).status_code == 204

    monkeypatch.setattr(api.container.storage, "put", deleted_meanwhile)
    await service.run(api.container, claimed)  # must not raise
    assert stored
    with pytest.raises(Exception):  # noqa: B017 the backend's own not-found error
        await api.container.storage.get(stored[0])
