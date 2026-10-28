"""Small specs that would expand into huge ones are refused quickly, not run out of memory."""

from __future__ import annotations

import time

import pytest

from apiforge.errors import SpecTooComplexError
from apiforge.generator import generate, lint
from tests.conftest import spec_bytes


def fan_out_spec(width: int) -> dict[str, object]:
    props = {f"p{i}": {"$ref": "#/components/schemas/A"} for i in range(width)}
    return {
        "openapi": "3.1.0",
        "info": {"title": "Fan out", "version": "1"},
        "paths": {
            "/a": {
                "get": {
                    "operationId": "getA",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/A"}}
                            },
                        }
                    },
                }
            }
        },
        "components": {"schemas": {"A": {"type": "object", "properties": props}}},
    }


def test_a_self_referencing_fan_out_is_refused_fast() -> None:
    start = time.perf_counter()
    with pytest.raises(SpecTooComplexError) as err:
        lint(spec_bytes(fan_out_spec(24)), "fan.yaml")
    assert err.value.code == "spec_too_complex"
    assert time.perf_counter() - start < 10


def test_a_modest_fan_out_still_generates() -> None:
    gen = generate(spec_bytes(fan_out_spec(3)), "fan.yaml")
    assert any(f.path == "app/generated/models.py" for f in gen.files)
