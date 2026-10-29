"""The generated app is safe to put in front of users: proven by running one.

The code checks below run on every test run. The slow test generates the team-tasks corpus
spec with ``--db``, adds the runtime checks in ``RUNTIME_TESTS`` to the project's own test
suite and runs its gates (on Postgres too when ``CORPUS_DATABASE_URL`` is set), so each
fix is shown working in a real app, not only present in the source.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from apiforge.generator import generate, lint
from apiforge.loader import load
from apiforge.normalize import normalize
from apiforge.options import GenerateOptions
from apiforge.verify import verify
from apiforge.writer import write
from tests.conftest import CORPUS, minimal, spec_bytes

TASKS = (CORPUS / "team-tasks.yaml").read_bytes()


def _files(spec: bytes = TASKS, db: bool = True) -> dict[str, str]:
    gen = generate(spec, "team-tasks.yaml", accept_report=True, options=GenerateOptions(db=db))
    return gen.file_map()


def test_and_requirements_keep_every_scheme_and_or_alternatives_stay_separate() -> None:
    api, _ = normalize(load(TASKS, "team-tasks.yaml"))
    ops = {op.func: op for op in api.operations}
    assert [[u.scheme for u in alt] for alt in ops["list_tasks"].security or []] == [
        ["apiKey", "bearerAuth"]
    ]
    assert [[u.scheme for u in alt] for alt in ops["replace_task"].security or []] == [
        ["oauth2"],
        ["apiKey"],
    ]
    router = _files()["app/generated/routers/tasks.py"]
    assert "[(auth_api_key, []), (auth_bearer_auth, [])]" in router
    assert '[(auth_oauth2, ["tasks:admin"])], [(auth_api_key, [])]' in router


def test_an_unsupported_scheme_fails_closed_and_stays_in_the_report() -> None:
    _, report = lint(TASKS, "team-tasks.yaml")
    assert "security_scheme_unsupported" in {f.code for f in report.findings}
    router = _files()["app/generated/routers/tasks.py"]
    audit = router[router.index("async def get_task_audit") :]
    assert "Depends(security.unsupported)" in audit.split("\n\n")[0]
    security = _files()["app/generated/security.py"]
    assert "async def unsupported() -> Principal:" in security
    assert "HTTP_401_UNAUTHORIZED" in security


def test_an_unsupported_alternative_does_not_open_the_route() -> None:
    doc = minimal(
        {
            "/a": {
                "get": {
                    "operationId": "a",
                    "security": [{"digest": []}, {"key": []}],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        securitySchemes={
            "digest": {"type": "http", "scheme": "digest"},
            "key": {"type": "apiKey", "in": "header", "name": "X-Key"},
        },
    )
    router = _files(spec_bytes(doc), db=False)["app/generated/routers/default.py"]
    assert 'security.require([(auth_key, [])], challenge="APIKey")' in router


def test_scope_checks_moved_out_of_the_scheme_dependencies() -> None:
    security = _files()["app/generated/security.py"]
    assert "SecurityScopes" not in security
    assert "HTTP_403_FORBIDDEN" in security.split("async def unsupported")[0]
    assert "class _LenientBasic(HTTPBasic)" in security


def test_list_paging_accepts_missing_values_and_bounds_offset() -> None:
    crud = _files()["app/generated/crud.py"]
    assert "limit: int | None = None" in crud and "offset: int | None = None" in crud
    assert "MAX_OFFSET" in crud
    handlers = _files()["app/handlers/tasks.py"]
    assert "crud.task.list(limit=limit, offset=offset, filters=" in handlers


def test_replace_no_longer_clears_columns_outside_the_input_model() -> None:
    crud = _files()["app/generated/crud.py"]
    assert "values[key] = None" not in crud


def test_integer_enum_parameters_accept_their_text() -> None:
    router = _files()["app/generated/routers/reports.py"]
    assert 'Annotated[Literal[1, 2, 3, "all"], wire_literal(1, 2, 3, "all")]' in router
    assert "from app.generated.wire import wire_literal" in router


def test_a_default_only_operation_answers_with_the_default_body() -> None:
    router = _files()["app/generated/routers/reports.py"]
    assert "response_model=GetSummaryDefaultResponse" in router
    assert '"default": {"model": GetSummaryDefaultResponse' in router


def test_the_dockerfile_and_ci_use_the_lockfile_when_there_is_one() -> None:
    files = _files()
    assert "COPY pyproject.toml uv.lock* ./" in files["Dockerfile"]
    assert "uv sync --locked --no-dev --no-install-project" in files["Dockerfile"]
    assert "uv sync --locked" in files[".github/workflows/ci.yml"]


def test_user_owned_settings_carry_the_production_guards() -> None:
    files = _files()
    config = files["app/config.py"]
    assert "DATABASE_URL must be set" in config
    assert 'jwt_algorithm: Literal["HS256", "HS384", "HS512"]' in config
    assert "jwt_issuer" in config and "jwt_leeway_seconds" in config
    assert "DatabaseSettings" in files["migrations/env.py"]
    assert "get_settings" not in files["migrations/env.py"]
    assert "server_settings" in files["app/db.py"]
    assert 'claims.get("scp")' in files["app/auth.py"]
    assert "not JWKS" in files["README.md"] or "(JWKS)" in files["README.md"]


# Added to the generated project's tests/generated by the slow test below, to run with the
# project's own fixtures (tests/generated/conftest.py).
RUNTIME_TESTS = '''\
"""Runtime checks for the production fixes (added by APIForge's own test suite)."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator

import httpx
import jwt
import pytest
from sqlalchemy import update

from app.config import Settings, get_settings
from app.db import session_scope
from app.generated.db_models import TaskRow
from app.main import create_app
from tests.generated.conftest import bearer_token

KEY = {"X-API-Key": "test-only-api-key-0123456789"}
NEW = {"title": "Write the report", "level": 2}


def _bearer(scopes: list[str] | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {bearer_token(scopes)}"}


async def _create(client: httpx.AsyncClient) -> int:
    resp = await client.post("/tasks", json=NEW, headers={**KEY, **_bearer()})
    assert resp.status_code == 201, resp.text
    return int(resp.json()["id"])


async def test_an_unsupported_scheme_refuses_every_request(client: httpx.AsyncClient) -> None:
    resp = await client.get("/tasks/1/audit", headers={**KEY, **_bearer()})
    assert resp.status_code == 401
    assert "does not support" in resp.json()["detail"]


async def test_every_scheme_of_an_and_requirement_is_needed(client: httpx.AsyncClient) -> None:
    for headers in ({}, KEY, _bearer()):
        resp = await client.get("/tasks", headers=headers)
        assert resp.status_code == 401, headers
        assert resp.headers["www-authenticate"] == "APIKey, Bearer"
    assert (await client.get("/tasks", headers={**KEY, **_bearer()})).status_code == 200


async def test_a_missing_scope_does_not_refuse_another_alternative(
    client: httpx.AsyncClient,
) -> None:
    task = await _create(client)
    body = {"title": "Replaced", "level": 1}
    resp = await client.put(f"/tasks/{task}", json=body, headers={**KEY, **_bearer()})
    assert resp.status_code == 200, resp.text
    resp = await client.put(f"/tasks/{task}", json=body, headers=_bearer())
    assert resp.status_code == 403 and "tasks:admin" in resp.json()["detail"]
    assert (await client.put(f"/tasks/{task}", json=body)).status_code == 401
    admin = _bearer(["tasks:admin"])
    assert (await client.put(f"/tasks/{task}", json=body, headers=admin)).status_code == 200


async def test_basic_routes_challenge_basic_and_malformed_basic_is_no_credential(
    client: httpx.AsyncClient,
) -> None:
    for headers in ({}, {"Authorization": "Basic !!!not-base64"}):
        resp = await client.delete("/tasks/1", headers=headers)
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Basic"
        assert resp.json() == {"detail": "Missing or invalid credentials"}


async def test_paging_without_defaults_and_huge_offsets(client: httpx.AsyncClient) -> None:
    await _create(client)
    auth = {**KEY, **_bearer()}
    assert len((await client.get("/tasks", headers=auth)).json()) == 1
    resp = await client.get("/tasks", params={"offset": "99999999999999999999"}, headers=auth)
    assert resp.status_code == 200 and resp.json() == []
    resp = await client.get("/tasks", params={"limit": 1, "offset": 0}, headers=auth)
    assert resp.status_code == 200 and len(resp.json()) == 1


async def test_integer_enum_query_values_match(client: httpx.AsyncClient) -> None:
    await _create(client)
    auth = {**KEY, **_bearer()}
    assert len((await client.get("/tasks", params={"level": "2"}, headers=auth)).json()) == 1
    assert (await client.get("/tasks", params={"level": "1"}, headers=auth)).json() == []
    assert (await client.get("/tasks", params={"level": "7"}, headers=auth)).status_code == 422
    for group in ("2", "all"):
        resp = await client.get("/summary", params={"group": group})
        assert resp.status_code == 200 and "total" in resp.json(), resp.text


async def test_replace_keeps_read_only_server_fields(client: httpx.AsyncClient) -> None:
    task = await _create(client)
    async with session_scope() as session:
        await session.execute(update(TaskRow).where(TaskRow.id == task).values(owner_id="ana"))
    body = {"title": "Replaced", "level": 3}
    resp = await client.put(f"/tasks/{task}", json=body, headers=KEY)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ownerId"] == "ana" and resp.json()["title"] == "Replaced"
    assert resp.json()["done"] is False  # a replace writes the input's defaults


async def test_a_database_conflict_is_a_409_without_sql(client: httpx.AsyncClient) -> None:
    task = await _create(client)
    resp = await client.patch(f"/tasks/{task}", json={"title": None}, headers=_bearer())
    assert resp.status_code == 409, resp.text
    text = resp.text.lower()
    assert "detail" in resp.json() and "insert" not in text and "update " not in text
    assert "null" not in text and "tasks" not in text


async def test_validation_errors_do_not_echo_the_input(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/tasks", json={"title": "x", "level": "hunter2"}, headers={**KEY, **_bearer()}
    )
    assert resp.status_code == 422
    assert "hunter2" not in resp.text
    error = resp.json()["detail"][0]
    assert set(error) <= {"loc", "msg", "type", "ctx"} and error["loc"] == ["body", "level"]


async def test_unhandled_errors_are_a_bare_json_500(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.handlers import reports

    async def broken(**kwargs: object) -> None:
        raise RuntimeError("secret internals")

    monkeypatch.setattr(reports, "get_summary", broken)
    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/summary")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}


async def test_example_data_is_refused_in_production(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "production")
    resp = await client.get("/summary")
    assert resp.status_code == 501 and resp.json() == {"detail": "Not implemented"}
    resp = await client.get("/tasks", headers={**KEY, **_bearer()})
    assert resp.status_code == 200  # implemented (database) handlers are unaffected


def test_production_needs_a_real_database() -> None:
    secrets = {
        "app_env": "production",
        "jwt_secret": "s" * 40,
        "api_keys": ["k" * 30],
        "basic_users": {"admin": "p" * 20},
    }
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(**secrets, database_url="sqlite+aiosqlite:///./app.db")  # type: ignore[arg-type]
    url = "postgresql+asyncpg://u:p@db/app"
    assert Settings(**secrets, database_url=url).database_url == url  # type: ignore[arg-type]


async def test_docs_can_be_turned_off_and_headers_are_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://t"
    ) as c:
        assert (await c.get("/openapi.json")).status_code == 200
        health = await c.get("/health")
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    assert health.headers["referrer-policy"] == "no-referrer"
    monkeypatch.setattr(get_settings(), "docs_enabled", False)
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await c.get(path)).status_code == 404
    assert "/tasks" in app.openapi()["paths"]  # the spec test still reads it


async def test_large_bodies_are_refused_even_when_chunked(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_body_bytes", 64)
    big = b'{"title": "' + b"x" * 200 + b'", "level": 1}'
    auth = {**KEY, **_bearer(), "Content-Type": "application/json"}

    async def chunks() -> AsyncIterator[bytes]:
        for i in range(0, len(big), 16):
            yield big[i : i + 16]

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.post("/tasks", content=big, headers=auth)
        assert resp.status_code == 413, resp.text
        resp = await c.post("/tasks", content=chunks(), headers=auth)
        assert resp.status_code == 413, resp.text
        assert resp.json() == {"detail": "Request body too large"}


async def test_jwt_scp_claims_issuer_and_leeway(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = await _create(client)
    secret = os.environ["JWT_SECRET"]

    def token(**claims: object) -> dict[str, str]:
        base = {"sub": "u", "exp": int(time.time()) + 600, **claims}
        return {"Authorization": "Bearer " + jwt.encode(base, secret, algorithm="HS256")}

    body = {"title": "Replaced", "level": 1}
    url = f"/tasks/{task}"
    assert (await client.put(url, json=body, headers=token(scp=["tasks:admin"]))).status_code == 200
    expired = token(scp="tasks:admin", exp=int(time.time()) - 10)
    assert (await client.put(url, json=body, headers=expired)).status_code == 200  # leeway
    monkeypatch.setattr(get_settings(), "jwt_issuer", "https://issuer.test")
    no_iss = token(scp="tasks:admin")
    assert (await client.put(url, json=body, headers=no_iss)).status_code == 401
    good = token(scp="tasks:admin", iss="https://issuer.test")
    assert (await client.put(url, json=body, headers=good)).status_code == 200
'''


@pytest.mark.corpus
@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to install the project")
def test_the_fixes_hold_in_a_running_app(tmp_path: Path) -> None:
    from tests.test_corpus import POSTGRES, _check_on_postgres

    gen = generate(TASKS, "team-tasks.yaml", accept_report=True, options=GenerateOptions(db=True))
    project = tmp_path / "project"
    write(gen, project)
    (project / "tests" / "generated" / "test_production_fixes.py").write_text(RUNTIME_TESTS)
    result = verify(project)
    failed = [s for s in result.steps if not s.ok]
    assert not failed, f"{failed[0].name} failed:\n{failed[0].output}"
    if POSTGRES:
        _check_on_postgres(project)
