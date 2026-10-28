"""The round-trip comparison finds real differences and ignores cosmetic ones."""

from __future__ import annotations

import copy
from typing import Any

from apiforge.fidelity import compare

SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "paths": {
        "/pets/{petId}": {
            "get": {
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer", "minimum": 1},
                    },
                    {"name": "q", "in": "query", "schema": {"type": "string", "nullable": True}},
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                        },
                    }
                },
                "security": [{"bearer": []}],
            }
        }
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "maxLength": 10},
                    "kids": {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}},
                },
            }
        }
    },
}


def served() -> dict[str, Any]:
    """What FastAPI serves for SPEC: 3.1, titles, anyOf null for optionals, an extra 422."""
    doc = copy.deepcopy(SPEC)
    doc["openapi"] = "3.1.0"
    op = doc["paths"]["/pets/{petId}"]["get"]
    op["parameters"][0]["schema"]["title"] = "Petid"
    op["parameters"][1]["schema"] = {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Q"}
    op["responses"]["422"] = {"description": "Validation Error"}
    pet = doc["components"]["schemas"]["Pet"]
    pet["title"] = "Pet"
    pet["properties"]["kids"] = {
        "anyOf": [
            {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}},
            {"type": "null"},
        ]
    }
    return doc


def test_cosmetic_differences_are_ignored() -> None:
    assert compare(SPEC, served()) == []


def test_a_changed_constraint_is_found() -> None:
    doc = served()
    doc["components"]["schemas"]["Pet"]["properties"]["name"]["maxLength"] = 11
    assert any("maxLength" in d for d in compare(SPEC, doc))


def test_missing_and_extra_operations_are_found() -> None:
    doc = served()
    doc["paths"]["/extra"] = {"post": {"responses": {"200": {"description": "x"}}}}
    del doc["paths"]["/pets/{petId}"]["get"]
    problems = compare(SPEC, doc)
    assert "POST /extra: served but not in the spec" in problems
    assert "GET /pets/{petId}: in the spec but not served" in problems


def test_parameter_location_requiredness_and_security_are_compared() -> None:
    doc = served()
    op = doc["paths"]["/pets/{petId}"]["get"]
    op["parameters"][1]["in"] = "header"
    op["security"] = []
    problems = compare(SPEC, doc)
    assert any("parameter q (query)" in p for p in problems)
    assert any("security" in p for p in problems)


def test_accepted_differences_are_filtered_precisely() -> None:
    doc = served()
    doc["components"]["schemas"]["Pet"]["properties"]["name"]["maxLength"] = 11
    assert compare(SPEC, doc, [("GET /pets/{petId}", "maxLength")]) == []
    assert compare(SPEC, doc, [("GET /other", "maxLength")]) != []
