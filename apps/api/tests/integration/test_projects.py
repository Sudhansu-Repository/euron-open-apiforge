"""Projects, spec uploads, versions, diffs, the playground and the bundled examples."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
import yaml

from tests.integration.conftest import Api, corpus

pytestmark = pytest.mark.integration


async def test_project_lifecycle_and_unique_addresses(api: Api) -> None:
    a = await api.ok(
        "POST", "/api/v1/projects", {"name": "Payments API", "description": "Card payments"}
    )
    b = await api.ok("POST", "/api/v1/projects", {"name": "Payments API"})
    assert (a["slug"], b["slug"]) == ("payments-api", "payments-api-2")
    assert a["default_options"] == {"project_name": None, "db": False, "docker": True, "ci": True}
    patched = await api.ok(
        "PATCH",
        "/api/v1/projects/payments-api",
        {"name": "Payments", "default_options": {"db": True}},
    )
    assert patched["name"] == "Payments" and patched["default_options"]["db"] is True
    assert patched["slug"] == "payments-api"  # the address never changes
    listed = await api.ok("GET", "/api/v1/projects")
    assert next(p["slug"] for p in listed) == "payments-api"
    await api.ok("DELETE", "/api/v1/projects/payments-api-2", status=204)
    missing = await api.client.get("/api/v1/projects/payments-api-2")
    assert missing.status_code == 404 and "No project" in missing.json()["error"]["message"]


async def test_upload_lints_stores_and_numbers_versions(api: Api) -> None:
    slug = await api.project()
    resp = await api.upload(slug, corpus("petstore.yaml"), "petstore.yaml", note="first")
    assert resp.status_code == 201 and resp.json()["created"] is True
    v1 = resp.json()["spec"]
    assert (v1["number"], v1["title"], v1["api_version"], v1["openapi_version"]) == (
        1,
        "Pet Store",
        "1.0.0",
        "3.0.3",
    )
    assert v1["operations"] == 4 and v1["errors"] == 0 and v1["note"] == "first"
    assert {o["function"] for o in v1["operation_list"]} == {
        "list_pets",
        "create_pet",
        "get_pet",
        "delete_pet",
    }
    assert v1["schemes"] == [{"name": "bearerAuth", "kind": "bearer"}]
    assert v1["changes"]["first"] is True and len(v1["changes"]["added"]) == 4

    again = await api.upload(slug, corpus("petstore.yaml"), "petstore.yaml")
    assert again.status_code == 200 and again.json()["created"] is False
    assert again.json()["spec"]["number"] == 1  # the same bytes are the same version

    doc = yaml.safe_load(corpus("petstore.yaml"))
    del doc["paths"]["/pets/{petId}"]["delete"]
    doc["paths"]["/pets"]["get"]["parameters"][0]["schema"]["maximum"] = 500
    doc["paths"]["/owners"] = {"get": {"responses": {"200": {"description": "ok"}}}}
    v2 = await api.spec(slug, yaml.safe_dump(doc).encode())
    assert v2["number"] == 2
    assert v2["changes"] == {
        "first": False,
        "added": ["GET /owners"],
        "removed": ["DELETE /pets/{petId}"],
        "changed": [{"operation": "GET /pets", "parts": ["parameters"]}],
    }
    versions = await api.ok("GET", f"/api/v1/projects/{slug}/specs")
    assert [v["number"] for v in versions] == [2, 1]
    diff = await api.ok("GET", f"/api/v1/projects/{slug}/diff?base=1&head=2")
    assert diff["changes"]["removed"] == ["DELETE /pets/{petId}"]
    content = await api.ok("GET", f"/api/v1/projects/{slug}/specs/1/content")
    assert content["content"] == corpus("petstore.yaml").decode()
    project = await api.ok("GET", f"/api/v1/projects/{slug}")
    assert project["spec_count"] == 2 and project["latest_spec"]["number"] == 2


async def test_report_findings_point_into_the_spec(api: Api) -> None:
    slug = await api.project("Edge Cases")
    spec = await api.spec(slug, corpus("edge-cases.yaml"), "edge-cases.yaml")
    assert spec["errors"] == 0 and spec["warnings"] >= 10
    pointers = {f["pointer"] for f in spec["report"]}
    assert "/paths/~1search/get/parameters/0" in pointers
    assert all(f["severity"] in ("error", "warning", "info") for f in spec["report"])


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("swagger: '2.0'\ninfo: {title: x, version: '1'}\npaths: {}\n", "spec_version_unsupported"),
        ("openapi: 3.0.3\ninfo: {title: x}\npaths: {}\n", "spec_invalid"),
        ("{not json", "spec_unreadable"),
        (
            "openapi: 3.0.3\ninfo: {title: x, version: '1'}\npaths:\n  /a:\n    get:\n      responses:\n"
            "        '200': {description: ok, content: {application/json: {schema: {$ref: '#/nope'}}}}\n",
            "spec_ref_unresolved",
        ),
    ],
)
async def test_unusable_specs_are_refused_with_a_reason(api: Api, content: str, code: str) -> None:
    slug = await api.project()
    resp = await api.upload(slug, content.encode())
    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == code and error["message"]
    assert await api.ok("GET", f"/api/v1/projects/{slug}/specs") == []  # nothing stored


async def test_zip_bundles_with_relative_refs(api: Api) -> None:
    slug = await api.project()
    root = yaml.safe_load(corpus("petstore.yaml"))
    schemas = root["components"].pop("schemas")
    text = json.dumps(root).replace('"#/components/schemas/', '"schemas.yaml#/')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("api/openapi.json", text)
        inner = yaml.safe_dump(schemas).replace("#/components/schemas/", "#/")
        zf.writestr("api/schemas.yaml", inner)
    spec = await api.spec(slug, buf.getvalue(), "petstore.zip")
    assert spec["bundle"] is True and spec["operations"] == 4
    content = await api.ok("GET", f"/api/v1/projects/{slug}/specs/1/content")
    assert content["files"] == ["openapi.json", "schemas.yaml"]
    gen = await api.generate(slug)
    assert gen["status"] == "succeeded", gen


async def test_specs_over_the_limit_are_refused(api: Api) -> None:
    api.container.settings.max_spec_bytes = 2048
    try:
        slug = await api.project()
        resp = await api.upload(slug, corpus("petstore.yaml"))
        assert resp.status_code == 413 and resp.json()["error"]["code"] == "spec_too_large"
        assert "MAX_SPEC_BYTES" in resp.json()["error"]["message"]
        text = corpus("petstore.yaml").decode()
        for url in ("/api/v1/lint", f"/api/v1/projects/{slug}/specs/text"):
            r = await api.client.post(url, json={"content": text})
            assert r.status_code == 413, url
    finally:
        api.container.settings.max_spec_bytes = 5 * 1024 * 1024


async def test_playground_lints_without_storing(api: Api) -> None:
    result = await api.ok("POST", "/api/v1/lint", {"content": corpus("bookstore.yaml").decode()})
    assert result["title"] == "Bookstore" and result["openapi_version"] == "3.1.0"
    assert len(result["operations"]) == 11 and result["counts"]["error"] == 0
    assert await api.ok("GET", "/api/v1/projects") == []


async def test_examples_list_and_create_a_project(api: Api) -> None:
    examples = await api.ok("GET", "/api/v1/examples")
    names = {e["name"] for e in examples}
    assert {
        "petstore.yaml",
        "bookstore.yaml",
        "inventory.yaml",
        "secure-notes.yaml",
        "edge-cases.yaml",
    } <= names
    spec = await api.ok("GET", "/api/v1/examples/inventory.yaml")
    assert spec["content"].startswith("openapi:")
    assert (await api.client.get("/api/v1/examples/..%2Fpyproject.toml")).status_code == 404
    project = await api.ok("POST", "/api/v1/projects/from-example", {"example": "inventory.yaml"})
    assert project["name"] == "Warehouse Inventory" and project["latest_spec"]["operations"] == 11
    missing = await api.client.post(
        "/api/v1/projects/from-example", json={"example": "../../etc/passwd"}
    )
    assert missing.status_code == 404
