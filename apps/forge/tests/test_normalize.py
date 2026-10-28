"""From a spec to the intermediate representation, and what the report says about it."""

from __future__ import annotations

import pytest

from apiforge.errors import SpecInvalidError, UnsupportedVersionError
from apiforge.loader import load
from apiforge.normalize import normalize
from tests.conftest import CORPUS, minimal, spec_bytes


def build(doc: dict[str, object]):  # type: ignore[no-untyped-def]
    return normalize(load(spec_bytes(doc), "openapi.yaml"))


def test_swagger_2_is_refused_with_a_way_forward() -> None:
    with pytest.raises(UnsupportedVersionError, match="convert"):
        build({"swagger": "2.0", "info": {"title": "x", "version": "1"}, "paths": {}})


def test_an_invalid_spec_lists_its_problems() -> None:
    with pytest.raises(SpecInvalidError) as exc:
        build(
            {
                "openapi": "3.0.3",
                "info": {"title": "x"},
                "paths": {"/a": {"get": {"responses": {}}}},
            }
        )
    assert exc.value.errors and "version" in str(exc.value.errors)


def test_petstore_maps_to_routes_models_and_security() -> None:
    api, report = normalize(load((CORPUS / "petstore.yaml").read_bytes(), "petstore.yaml"))
    ops = {op.func: op for op in api.operations}
    assert set(ops) == {"list_pets", "create_pet", "get_pet", "delete_pet"}
    get = ops["get_pet"]
    assert [(p.name, p.wire, p.location) for p in get.params] == [
        ("pet_id", "petId", "path"),
        ("x_request_id", "X-Request-ID", "header"),
    ]
    assert get.params[0].type.constraints == {"ge": "1"}
    assert ops["create_pet"].body is not None and ops["create_pet"].body.type is not None
    assert ops["create_pet"].body.type.expr == "PetInput"  # readOnly id left out of input
    assert ops["create_pet"].security and ops["create_pet"].security[0][0].scheme == "bearerAuth"
    assert ops["list_pets"].security is None
    models = {m.name: m for m in api.models}
    assert models["PetStatus"].kind == "enum"
    assert "id" not in {f.name for f in models["PetInput"].fields}
    assert report.errors == []


def test_discriminated_unions_narrow_each_variant() -> None:
    api, _ = normalize(load((CORPUS / "bookstore.yaml").read_bytes(), "bookstore.yaml"))
    models = {m.name: m for m in api.models}
    assert models["Book"].kind == "alias"
    assert "discriminator='format'" in (models["Book"].alias_type or "")
    fmt = next(f for f in models["Ebook"].fields if f.alias == "format")
    assert fmt.type_expr == "Literal['ebook']"
    assert models["PrintBook"].bases == ["BookBase"]


def test_nullable_constraints_and_defaults() -> None:
    doc = minimal(
        schemas={
            "T": {
                "type": "object",
                "required": ["n"],
                "properties": {
                    "n": {"type": "integer", "minimum": 1, "maximum": 10, "exclusiveMaximum": True},
                    "s": {"type": "string", "nullable": True, "maxLength": 5},
                    "flag": {"type": "boolean", "default": True},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 2},
                        "maxItems": 3,
                    },
                },
            }
        }
    )
    api, _ = build(doc)
    fields = {f.name: f for f in api.models[0].fields}
    assert fields["n"].constraints == {"ge": "1", "lt": "10"} and fields["n"].required
    assert fields["s"].type_expr == "str | None" and fields["s"].constraints == {"max_length": "5"}
    assert fields["flag"].default == "True"
    assert fields["tags"].type_expr.startswith("list[Annotated[str, Field(min_length=2)]]")


def test_derived_operation_ids_and_unsupported_parts_are_reported() -> None:
    api, report = normalize(load((CORPUS / "edge-cases.yaml").read_bytes(), "edge-cases.yaml"))
    codes = {f.code for f in report.findings}
    assert {
        "operation_id_derived",
        "param_object_as_string",
        "param_explode_false",
        "body_media_types_dropped",
        "response_media_types_dropped",
        "callbacks_not_generated",
        "webhooks_not_generated",
        "keyword_not_enforced",
        "tuple_not_enforced",
        "unique_items_not_enforced",
        "object_size_not_enforced",
        "header_param_ignored",
    } <= codes
    assert all(f.pointer for f in report.findings if f.code != "no_paths")
    assert ("*", "uniqueItems") in api.accepted


def test_duplicate_routes_are_an_error() -> None:
    doc = minimal(
        {
            "/a/{x}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                    "parameters": [
                        {"name": "x", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                }
            },
            "/a/{y}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                    "parameters": [
                        {"name": "y", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                }
            },
        }
    )
    api, report = build(doc)
    assert [f.code for f in report.errors] == ["duplicate_route"]
    assert len(api.operations) == 1


def test_optional_authentication_and_explicitly_open_operations() -> None:
    api, _ = normalize(load((CORPUS / "secure-notes.yaml").read_bytes(), "secure-notes.yaml"))
    ops = {op.func: op for op in api.operations}
    assert ops["get_status"].security == []
    assert ops["read_shared_note"].security is None
    assert [a[0].scheme for a in ops["get_note"].security or []] == [
        "bearerAuth",
        "apiKeyQuery",
        "openId",
    ]
