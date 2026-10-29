"""Abuse and race cases: hostile input, forged headers, parallel requests, evicted caches.

Each test pins one production-readiness guarantee: bounded work per request, no 500s on odd
but valid JSON, a spec that cannot make the server reach anywhere or write anywhere, and
state that stays correct under concurrency.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select

from apiforge_server.audit.models import AuditLog
from apiforge_server.users.models import User
from tests.integration.conftest import OWNER, Api, corpus, login

pytestmark = pytest.mark.integration


async def test_lone_surrogate_is_a_422_not_a_500(api: Api) -> None:
    raw = b'{"name": "bad \\ud800 name"}'
    r = await api.client.post(
        "/api/v1/projects", content=raw, headers={"content-type": "application/json"}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_json"


async def test_chunked_bodies_obey_the_body_limit(api: Api) -> None:
    settings = api.container.settings
    settings.max_body_bytes = 2000

    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"content": "'
        for _ in range(20):
            yield b"x" * 500
        yield b'"}'

    try:
        r = await api.client.post(
            "/api/v1/lint", content=chunks(), headers={"content-type": "application/json"}
        )
        assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    finally:
        settings.max_body_bytes = 8 * 1024 * 1024


async def test_routes_other_than_spec_uploads_take_only_small_bodies(api: Api) -> None:
    # 200 KB is fine for a spec upload but refused, unparsed, on sign-in and the rest.
    big = b'{"email": "a@example.test", "password": "' + b"x" * 200_000 + b'"}'
    async with api.anonymous() as c:
        r = await c.post(
            "/api/v1/auth/login", content=big, headers={"content-type": "application/json"}
        )
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    r = await api.client.post(
        "/api/v1/projects", content=big, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
    text = '{"content": "' + "x" * 200_000 + '"}'
    r = await api.client.post(
        "/api/v1/lint", content=text, headers={"content-type": "application/json"}
    )
    assert r.status_code != 413  # a spec route: parsed, and refused for its content instead


async def test_a_spec_with_url_refs_never_makes_the_server_fetch(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    real = socket.socket

    def guarded(*args: object, **kwargs: object) -> socket.socket:
        family = args[0] if args else kwargs.get("family", socket.AF_INET)
        if family in (socket.AF_INET, socket.AF_INET6):
            sock = real(*args, **kwargs)  # type: ignore[arg-type]
            original = sock.connect

            def connect(address: object) -> None:
                host = address[0] if isinstance(address, tuple) else address
                if host not in ("127.0.0.1", "::1", "localhost"):
                    raise AssertionError(f"the server tried to connect to {address}")
                original(address)  # type: ignore[arg-type]

            sock.connect = connect  # type: ignore[method-assign]
            return sock
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "socket", guarded)
    spec = (
        b"openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths:\n  /a:\n    get:\n"
        b"      responses:\n        '200':\n          description: ok\n          content:\n"
        b"            application/json:\n              schema:\n"
        b"                $ref: 'http://169.254.169.254/latest/meta-data'\n"
    )
    r = await api.client.post("/api/v1/lint", json={"content": spec.decode()})
    assert r.status_code == 422 and r.json()["error"]["code"] == "spec_ref_unresolved"
    assert "never fetches" in r.json()["error"]["message"]


async def test_uploaded_file_names_cannot_escape_the_storage_folder(api: Api) -> None:
    slug = await api.project()
    resp = await api.upload(slug, corpus("petstore.yaml"), filename="../../../etc/passwd.yaml")
    assert resp.status_code == 201, resp.text
    spec = resp.json()["spec"]
    assert spec["filename"] == "passwd.yaml"
    from apiforge_server.projects.models import SpecVersion

    async with api.container.db.sessionmaker() as session:
        key = await session.scalar(select(SpecVersion.storage_key))
    assert key is not None and ".." not in key and key.endswith("/passwd.yaml")


async def test_zip_bombs_and_yaml_bombs_are_refused_before_doing_the_work(api: Api) -> None:
    import io
    import zipfile

    slug = await api.project()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("openapi.yaml", corpus("petstore.yaml"))
        zf.writestr("huge.yaml", b"a: " + b"0" * (21 * 1024 * 1024))
    r = await api.upload(slug, buf.getvalue(), filename="spec.zip")
    assert r.status_code == 422 and "expand" in r.json()["error"]["message"]
    # Each level refers to the previous one nine times: 9**10 values once expanded.
    lines = ["l0: &l0 [x, x, x, x, x, x, x, x, x]"]
    lines += [f"l{i}: &l{i} [{', '.join([f'*l{i - 1}'] * 9)}]" for i in range(1, 11)]
    r = await api.client.post("/api/v1/lint", json={"content": "\n".join(lines)})
    assert r.status_code == 422 and "aliases" in r.json()["error"]["message"]


async def test_parallel_uploads_of_one_spec_store_one_version(api: Api) -> None:
    slug = await api.project()
    results = await asyncio.gather(
        *(api.upload(slug, corpus("petstore.yaml")) for _ in range(4)), return_exceptions=True
    )
    codes = sorted(r.status_code for r in results if not isinstance(r, BaseException))
    assert codes == [200, 200, 200, 201], codes  # one stored, the others get that version
    versions = await api.ok("GET", f"/api/v1/projects/{slug}/specs")
    assert len(versions) == 1


async def test_forwarded_for_cannot_dodge_the_login_throttle(api: Api) -> None:
    async with api.anonymous() as c:
        codes = []
        for i in range(22):
            r = await c.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.test", "password": "wrong-password"},
                headers={"x-forwarded-for": f"203.0.113.{i}"},
            )
            codes.append(r.status_code)
    assert codes[-1] == 429


async def test_parallel_wrong_passwords_still_lock_the_account(api: Api) -> None:
    async with api.anonymous() as c:
        await asyncio.gather(
            *(
                c.post("/api/v1/auth/login", json={"email": OWNER["email"], "password": "nope"})
                for _ in range(8)
            )
        )
        locked = await c.post("/api/v1/auth/login", json=OWNER)
    assert locked.json()["error"]["code"] == "account_locked"
    async with api.container.db.sessionmaker() as s:
        failures = await s.scalar(
            select(func.count()).where(AuditLog.action == "auth.login_failed")
        )
    assert failures == 8


async def test_logout_ends_the_session_server_side(api: Api) -> None:
    client = await login(api.app)
    try:
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        assert (await client.post("/api/v1/auth/logout")).status_code == 200
        again = await client.get("/api/v1/auth/me")
        assert again.status_code == 401 and again.json()["error"]["code"] == "session_expired"
    finally:
        await client.aclose()
    assert (await api.client.get("/api/v1/auth/me")).status_code == 200


async def test_signed_out_session_survives_cache_eviction(api: Api) -> None:
    client = await login(api.app)
    try:
        await client.post("/api/v1/auth/logout")
        kv = api.container.kv
        for i in range(3000):
            await kv.set(f"filler:{i}", b"x" * 100, 60)
        if hasattr(kv, "redis"):
            await kv.redis.flushdb()
        assert (await client.get("/api/v1/auth/me")).status_code == 401
    finally:
        await client.aclose()


async def test_login_response_is_not_cached(api: Api) -> None:
    async with api.anonymous() as c:
        resp = await c.post("/api/v1/auth/login", json=OWNER)
    assert resp.headers["cache-control"] == "no-store"


async def test_two_owners_demoting_each_other_keep_an_owner(api: Api) -> None:
    other = {"email": "second-owner@example.test", "password": "Second-Owner-123"}
    created = await api.ok(
        "POST", "/api/v1/users", {"name": "Second", "role": "owner", **other}, status=201
    )
    me = await api.ok("GET", "/api/v1/auth/me")
    second = await login(api.app, other)
    try:
        results = await asyncio.gather(
            api.client.patch(f"/api/v1/users/{created['id']}", json={"role": "viewer"}),
            second.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"}),
        )
    finally:
        await second.aclose()
    assert sorted(r.status_code for r in results)[0] == 200
    async with api.container.db.sessionmaker() as s:
        owners = await s.scalar(
            select(func.count()).where(User.role == "owner", User.disabled.is_(False))
        )
    assert owners == 1


async def test_racing_user_creates_conflict_without_leaking_hashes(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    body = {
        "email": "race@example.test",
        "name": "Race",
        "role": "viewer",
        "password": "Race-Pass-12345",
    }
    results = await asyncio.gather(*(api.client.post("/api/v1/users", json=body) for _ in range(4)))
    codes = sorted(r.status_code for r in results)
    assert codes[0] == 201 and set(codes[1:]) <= {409}
    assert "argon2" not in caplog.text


async def test_security_headers_on_every_response(api: Api) -> None:
    async with api.anonymous() as c:
        r = await c.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in r.headers
