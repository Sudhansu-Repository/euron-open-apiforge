"""Synthesized examples always validate against their schema."""

from __future__ import annotations

import re

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apiforge.examples import ExampleBuilder, sample_pattern

SCHEMAS = [
    {"type": "string", "format": "date-time"},
    {"type": "string", "format": "uuid"},
    {"type": "string", "minLength": 12, "maxLength": 20},
    {"type": "string", "pattern": "^[A-Z]{3}-[0-9]{4}$"},
    {"type": "string", "pattern": "^97[89][0-9]{10}$"},
    {"type": "string", "pattern": r"^[a-z0-9]+(?:-[a-z0-9]+)*$"},
    {"type": "integer", "minimum": 10, "maximum": 20, "multipleOf": 3},
    {"type": "integer", "exclusiveMinimum": 0},
    {"type": "number", "minimum": 0.5, "maximum": 0.7},
    {"type": "array", "minItems": 3, "uniqueItems": True, "items": {"type": "integer"}},
    {
        "type": "object",
        "required": ["a"],
        "properties": {"a": {"type": "boolean"}, "b": {"enum": ["x", "y"]}},
    },
    {"type": "object", "additionalProperties": {"type": "integer", "minimum": 5}},
    {"oneOf": [{"type": "string", "maxLength": 3}, {"type": "integer"}]},
    {
        "allOf": [
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"properties": {"b": {"type": "integer"}}},
        ]
    },
    {"type": ["string", "null"], "maxLength": 4},
    {"const": "fixed"},
]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_examples_validate(schema: dict[str, object]) -> None:
    value = ExampleBuilder().value(schema)
    jsonschema.validate(value, schema)


def test_the_same_schema_always_gives_the_same_example() -> None:
    builder = ExampleBuilder()
    assert [builder.value(s) for s in SCHEMAS] == [ExampleBuilder().value(s) for s in SCHEMAS]


def test_spec_examples_win_when_they_fit_and_lose_when_they_do_not() -> None:
    assert ExampleBuilder().value({"type": "string", "example": "Rex"}) == "Rex"
    assert ExampleBuilder().value({"type": "integer", "example": "not a number", "minimum": 3}) == 3


def test_read_only_and_write_only_respect_the_direction() -> None:
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "readOnly": True},
            "password": {"type": "string", "writeOnly": True},
        },
    }
    assert set(ExampleBuilder().value(schema, "request")) == {"password"}
    assert set(ExampleBuilder().value(schema, "response")) == {"id"}


@given(st.from_regex(r"\^[a-z]{1,3}(\[0-9\]\{[1-4]\}|\\d\+|-)[A-Z]?\$", fullmatch=True))
@settings(max_examples=200, deadline=None)
def test_sampled_strings_match_their_pattern(pattern: str) -> None:
    sample = sample_pattern(pattern)
    assert sample is not None and re.search(pattern, sample)


def test_patterns_the_sampler_cannot_handle_return_none() -> None:
    assert sample_pattern(r"^(?=.*\d)(?=.*[a-z]).{8,}$") is None
    assert sample_pattern(r"(a)\1") is None
