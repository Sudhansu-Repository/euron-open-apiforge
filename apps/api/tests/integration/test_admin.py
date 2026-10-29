"""Dashboard platform: sign-in, sessions, roles, API keys, users, audit, system info."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text

from tests.integration.conftest import OWNER, Api, corpus, login

pytestmark = pytest.mark.integration


async def test_login_failures_and_lockout(api: Api) -> None:
    async with api.anonymous() as c:
        bad = await c.post(
            "/api/v1/auth/login", json={"email": OWNER["email"], "password": "wrong"}
        )
        assert bad.status_code == 401
        for _ in range(5):
            await c.post("/api/v1/auth/login", json={"email": OWNER["email"], "password": "wrong"})
        locked = await c.post("/api/v1/auth/login", json=OWNER)
        assert locked.status_code == 401 and locked.json()["error"]["code"] == "account_locked"
        assert (await c.get("/api/v1/auth/me")).status_code == 401


async def test_cookie_session_requires_csrf_header(api: Api) -> None:
    async with api.anonymous() as c:
        await c.post("/api/v1/auth/login", json=OWNER)
        assert (await c.get("/api/v1/auth/me")).status_code == 200
        resp = await c.post("/api/v1/keys", json={"name": "x"})
        assert resp.status_code == 403 and resp.json()["error"]["code"] == "csrf_required"
        ok = await c.post("/api/v1/keys", json={"name": "x"}, headers={"x-apiforge-csrf": "1"})
        assert ok.status_code == 201


async def test_roles_are_enforced(api: Api) -> None:
    await api.ok(
        "POST",
        "/api/v1/users",
        {
            "email": "viewer@example.test",
            "name": "V",
            "password": "Viewer-Pass-123",
            "role": "viewer",
        },
    )
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.generate(slug)
    viewer = await login(api.app, {"email": "viewer@example.test", "password": "Viewer-Pass-123"})
    try:
        for path in (
            "/api/v1/overview",
            "/api/v1/projects",
            f"/api/v1/projects/{slug}",
            f"/api/v1/projects/{slug}/specs/1",
            f"/api/v1/projects/{slug}/generations/1",
            f"/api/v1/projects/{slug}/generations/1/archive",
            "/api/v1/examples",
        ):
            assert (await viewer.get(path)).status_code == 200, path
        assert (
            await viewer.post("/api/v1/lint", json={"content": "openapi: 3.0.3"})
        ).status_code != 403
        for method, path, body in (
            ("POST", "/api/v1/keys", {"name": "x"}),
            ("POST", "/api/v1/projects", {"name": "x"}),
            ("PATCH", f"/api/v1/projects/{slug}", {"name": "x"}),
            ("DELETE", f"/api/v1/projects/{slug}", None),
            ("POST", f"/api/v1/projects/{slug}/generations", {}),
            ("POST", f"/api/v1/projects/{slug}/specs/text", {"content": "openapi: 3.0.3"}),
            ("POST", "/api/v1/projects/from-example", {"example": "petstore.yaml"}),
            ("GET", "/api/v1/audit", None),
        ):
            r = await viewer.request(method, path, json=body)
            assert r.status_code == 403, (method, path, r.text)
    finally:
        await viewer.aclose()


async def test_api_keys_read_but_never_write(api: Api) -> None:
    created = await api.ok("POST", "/api/v1/keys", {"name": "grafana"})
    assert created["key"].startswith("afk_") and created["display"].endswith("_****")
    headers = {"authorization": f"Bearer {created['key']}"}
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.generate(slug)
    async with api.anonymous() as c:
        assert (await c.get("/api/v1/projects", headers=headers)).status_code == 200
        # The CI use case: download the latest archive with a key.
        archive = await c.get(f"/api/v1/projects/{slug}/generations/1/archive", headers=headers)
        assert archive.status_code == 200 and archive.content[:2] == b"PK"
        r = await c.post(f"/api/v1/projects/{slug}/generations", json={}, headers=headers)
        assert r.status_code == 403 and r.json()["error"]["code"] == "read_only_key"
        assert (await c.get("/api/v1/audit", headers=headers)).status_code == 403  # admin only
    await api.ok("POST", f"/api/v1/keys/{created['id']}/revoke")
    async with api.anonymous() as c:
        r = await c.get("/api/v1/projects", headers=headers)
        assert r.status_code == 401 and r.json()["error"]["code"] == "revoked_api_key"
        bad = await c.get(
            "/api/v1/projects", headers={"authorization": "Bearer afk_000000000000_nope"}
        )
        assert bad.status_code == 401


async def test_api_key_rate_limit(api: Api) -> None:
    key = (await api.ok("POST", "/api/v1/keys", {"name": "tiny", "rpm_limit": 3}))["key"]
    async with api.anonymous() as c:
        codes = [
            (
                await c.get("/api/v1/projects", headers={"authorization": f"Bearer {key}"})
            ).status_code
            for _ in range(4)
        ]
    assert codes == [200, 200, 200, 429]


async def test_users_keep_an_owner(api: Api) -> None:
    me = await api.ok("GET", "/api/v1/auth/me")
    resp = await api.client.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"})
    assert resp.status_code == 403
    assert len(await api.ok("GET", "/api/v1/users")) == 1


async def test_password_change_ends_other_sessions(api: Api) -> None:
    other = await login(api.app)
    try:
        await api.ok(
            "POST",
            "/api/v1/auth/password",
            {"current_password": OWNER["password"], "new_password": "Changed-Pass-456"},
        )
        assert (await other.get("/api/v1/auth/me")).status_code == 401
    finally:
        await other.aclose()


async def test_audit_log_records_changes_and_is_append_only(api: Api) -> None:
    await api.ok("POST", "/api/v1/keys", {"name": "audited"})
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.ok("POST", f"/api/v1/projects/{slug}/generations", {}, status=202)
    actions = {e["action"] for e in (await api.ok("GET", "/api/v1/audit"))["items"]}
    assert {
        "auth.login",
        "api_key.created",
        "project.created",
        "spec.uploaded",
        "generation.queued",
    } <= actions
    async with api.container.db.engine.begin() as conn:
        with pytest.raises(Exception, match="append-only"):
            await conn.execute(text("UPDATE audit_log SET action = 'x'"))


async def test_system_info_health_and_metrics(api: Api) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"))
    await api.generate(slug)
    info = await api.ok("GET", "/api/v1/system")
    assert info["cache_backend"] in ("redis", "memory")
    assert info["generator_version"] == "0.1.0" and info["worker_concurrency"] == 2
    assert info["checks"]["postgres"]["ok"] and info["checks"]["postgres"]["ms"] >= 0
    async with api.anonymous() as c:
        assert (await c.get("/healthz")).json() == {"status": "ok"}
        assert (await c.get("/health")).status_code == 200
        ready = await c.get("/readyz")
        assert ready.status_code == 200 and ready.json()["status"] == "ready"
        metrics = (await c.get("/metrics")).text
        assert 'apiforge_generations_total{status="succeeded"}' in metrics
        assert "apiforge_lint_seconds_count" in metrics


async def test_metrics_token_protects_the_metrics(api: Api) -> None:
    api.container.settings.metrics_token = "scrape-secret-123"
    try:
        async with api.anonymous() as c:
            assert (await c.get("/metrics")).status_code == 401
            ok = await c.get("/metrics", headers={"authorization": "Bearer scrape-secret-123"})
            assert ok.status_code == 200
    finally:
        api.container.settings.metrics_token = None


async def test_failures_from_one_address_do_not_lock_the_account_for_others(api: Api) -> None:
    def client(ip: str) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=api.app, client=(ip, 50000))
        return httpx.AsyncClient(transport=transport, base_url="http://testserver")

    async with client("198.51.100.7") as attacker, client("203.0.113.9") as owner:
        for _ in range(6):
            await attacker.post(
                "/api/v1/auth/login", json={"email": OWNER["email"], "password": "wrong"}
            )
        locked = await attacker.post("/api/v1/auth/login", json=OWNER)
        assert locked.json()["error"]["code"] == "account_locked"
        # The real owner, elsewhere, still gets in.
        assert (await owner.post("/api/v1/auth/login", json=OWNER)).status_code == 200
