"""Export the OpenAPI document. ``apiforge-server openapi > docs/api/openapi.yaml``."""

from __future__ import annotations

from typing import Any

from apiforge_server.core.config import Settings


def spec() -> dict[str, Any]:
    from apiforge_server.main import create_app

    app = create_app(Settings())
    document: dict[str, Any] = app.openapi()
    document["servers"] = [{"url": "http://localhost:4630", "description": "Local (make up)"}]
    return document


def to_yaml(document: dict[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)
