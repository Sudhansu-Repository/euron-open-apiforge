"""Shared helpers for the generator's tests."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

CORPUS = Path(__file__).resolve().parents[1] / "src" / "apiforge" / "corpus"


def spec_bytes(doc: dict[str, object]) -> bytes:
    return yaml.safe_dump(doc, sort_keys=False).encode()


def minimal(paths: dict[str, object] | None = None, **components: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1.0.0"},
        "paths": paths or {},
    }
    if components:
        doc["components"] = components
    return doc


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Any attempt to open a socket fails the test."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("APIForge tried to open a network connection")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield


def large_spec(resources: int = 120) -> dict[str, object]:
    """A synthesized API: ``resources`` collections, each listed and created, with nested and
    recursive models; 2 operations and 4 models per resource. Used for scale checks."""
    schemas: dict[str, object] = {}
    paths: dict[str, object] = {}
    for i in range(resources):
        name = f"Resource{i}"
        parent: dict[str, object] = (
            {"$ref": f"#/components/schemas/Resource{(i + 1) % resources}"}
            if i % 5 == 0
            else {"type": "string", "format": "date-time"}
        )
        schemas[name] = {
            "type": "object",
            "required": ["name"],
            "properties": {
                "id": {"type": "integer", "readOnly": True},
                "name": {"type": "string", "maxLength": 80},
                "status": {"type": "string", "enum": ["active", "archived"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "parent": parent,
                "owner": {
                    "type": "object",
                    "properties": {"email": {"type": "string", "format": "email"}},
                },
            },
        }
        ref = {"$ref": f"#/components/schemas/{name}"}
        paths[f"/r{i}"] = {
            "get": {
                "tags": [f"group{i % 12}"],
                "operationId": f"list{name}",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer", "minimum": 1, "maximum": 100},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {"schema": {"type": "array", "items": ref}}
                        },
                    }
                },
            },
            "post": {
                "tags": [f"group{i % 12}"],
                "operationId": f"create{name}",
                "requestBody": {"required": True, "content": {"application/json": {"schema": ref}}},
                "responses": {
                    "201": {"description": "ok", "content": {"application/json": {"schema": ref}}}
                },
            },
        }
    return {
        "openapi": "3.0.3",
        "info": {"title": "Large API", "version": "1.0.0"},
        "paths": paths,
        "components": {"schemas": schemas},
    }
