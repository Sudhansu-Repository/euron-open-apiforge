"""Schema-valid example values, deterministic, for mocks and generated tests.

``expand`` turns a schema with ``$ref``s into a self-contained one (recursion cut at a
depth), which is also what the fidelity check compares. ``example_for`` builds a value from
it: the spec's own ``example``/``examples``/``default`` when they validate, otherwise one
synthesized from the type, format, enum and constraints (a value matching ``pattern`` is
built by walking the regular expression). The same input always gives the same value.
"""

from __future__ import annotations

import re

# The regular expression parser (private, stable since Python 3.11; 3.12 is the minimum).
import re._constants as sre_constants  # type: ignore[import-not-found]
import re._parser as sre_parse  # type: ignore[import-not-found]
from typing import Any, Literal

from apiforge.errors import SpecTooComplexError
from apiforge.loader import Bundle
from apiforge.report import Report

Context = Literal["response", "request"]
MAX_DEPTH = 6
# Nodes all ``expand`` calls for one spec may produce. The bundled 240-operation spec needs
# about 12,000; a schema whose 16 properties each reference it again would need 16 ** 6.
MAX_EXPANDED_NODES = 500_000

STRING_FORMATS: dict[str, str] = {
    "date-time": "2026-01-15T09:30:00Z",
    "date": "2026-01-15",
    "time": "09:30:00",
    "duration": "P3D",
    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "email": "ada@example.com",
    "idn-email": "ada@example.com",
    "uri": "https://example.com/resource",
    "url": "https://example.com/resource",
    "uri-reference": "/resource",
    "iri": "https://example.com/resource",
    "hostname": "api.example.com",
    "ipv4": "192.0.2.10",
    "ipv6": "2001:db8::10",
    "byte": "ZXhhbXBsZQ==",
    "password": "correct-horse-battery",
    "binary": "",
}


def expand(bundle: Bundle, schema: Any, file: str, depth: int = 0) -> Any:
    """Inline every ``$ref``; at ``MAX_DEPTH`` a recursive reference becomes ``{}``."""
    bundle.expanded += 1
    if bundle.expanded > MAX_EXPANDED_NODES:
        raise SpecTooComplexError(
            f"Inlining the spec's $refs would produce more than {MAX_EXPANDED_NODES:,} schema "
            "nodes: schemas that reference each other many times over. Reduce the fan-out "
            "(fewer properties pointing back at the same schema), or split the spec."
        )
    if isinstance(schema, list):
        return [expand(bundle, s, file, depth) for s in schema]
    if not isinstance(schema, dict):
        return schema
    file = schema.get("__file__", file)
    if "$ref" in schema:
        if depth >= MAX_DEPTH:
            return {}
        tfile, tptr, target = bundle.resolve(schema["$ref"], file)
        merged = expand(bundle, target, tfile, depth + 1)
        parts = tptr.split("/")
        if (
            isinstance(merged, dict)
            and len(parts) == 4
            and parts[1:3] == ["components", "schemas"]
            and "x-apiforge-component" not in merged
        ):
            merged = {
                **merged,
                "x-apiforge-component": parts[3].replace("~1", "/").replace("~0", "~"),
            }
        siblings = {k: v for k, v in schema.items() if k not in ("$ref", "__file__")}
        if siblings and isinstance(merged, dict):
            merged = {**merged, **expand(bundle, siblings, file, depth)}
        return merged
    return {
        k: expand(bundle, v, file, depth)
        if k not in ("example", "examples", "default", "enum", "const")
        else v
        for k, v in schema.items()
        if k != "__file__"
    }


class ExampleBuilder:
    def __init__(self, report: Report | None = None) -> None:
        self.report = report

    def value(
        self, schema: Any, context: Context = "response", depth: int = 0, key: str = ""
    ) -> Any:
        if not isinstance(schema, dict) or depth > MAX_DEPTH:
            return None
        for k in ("example",):
            if k in schema and _fits(schema[k], schema):
                return schema[k]
        if isinstance(schema.get("examples"), list) and schema["examples"]:
            first = schema["examples"][0]
            if _fits(first, schema):
                return first
        if (
            "default" in schema
            and schema["default"] is not None
            and _fits(schema["default"], schema)
        ):
            return schema["default"]
        if "const" in schema:
            return schema["const"]
        if "enum" in schema:
            values = [v for v in schema["enum"] if v is not None]
            return values[0] if values else None
        for comb in ("oneOf", "anyOf"):
            if comb in schema:
                options = [
                    o for o in schema[comb] if isinstance(o, dict) and o.get("type") != "null"
                ]
                if not options:
                    return None
                chosen = options[0]
                result = self.value(chosen, context, depth + 1, key)
                disc = schema.get("discriminator")
                if isinstance(disc, dict) and isinstance(result, dict) and disc.get("propertyName"):
                    prop = disc["propertyName"]
                    mapping = disc.get("mapping") or {}
                    comp = chosen.get("x-apiforge-component")
                    value = (
                        next(
                            (k for k, v in mapping.items() if str(v).rsplit("/", 1)[-1] == comp),
                            None,
                        )
                        or comp
                    )
                    if value is not None:
                        result[prop] = value
                return result
        if "allOf" in schema:
            merged: dict[str, Any] = {}
            for member in schema["allOf"]:
                part = self.value(member, context, depth + 1, key)
                if isinstance(part, dict):
                    merged.update(part)
            own = {k: v for k, v in schema.items() if k != "allOf"}
            if own.get("properties"):
                part = self.value(own, context, depth + 1, key)
                if isinstance(part, dict):
                    merged.update(part)
            return merged
        t = schema.get("type")
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), None)
        if t is None:
            t = "object" if "properties" in schema else "array" if "items" in schema else None
        if t == "object":
            return self._object(schema, context, depth)
        if t == "array":
            item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
            count = max(1, int(schema.get("minItems", 1)))
            if "maxItems" in schema:
                count = min(count, int(schema["maxItems"]))
            items = [self.value(item_schema, context, depth + 1, key) for _ in range(count)]
            if schema.get("uniqueItems") and count > 1:
                items = [_variant(v, i) for i, v in enumerate(items)]
            return items
        if t == "string":
            return self._string(schema, key)
        if t == "integer":
            return int(_number(schema, integer=True))
        if t == "number":
            return _number(schema, integer=False)
        if t == "boolean":
            return True
        if t == "null":
            return None
        return {} if schema.get("properties") else "value"

    def _object(self, schema: dict[str, Any], context: Context, depth: int) -> dict[str, Any]:
        out: dict[str, Any] = {}
        required = set(schema.get("required") or [])
        for prop, sub in (schema.get("properties") or {}).items():
            if not isinstance(sub, dict):
                continue
            if context == "request" and sub.get("readOnly"):
                continue
            if context == "response" and sub.get("writeOnly"):
                continue
            if depth >= MAX_DEPTH - 2 and prop not in required:
                continue
            out[prop] = self.value(sub, context, depth + 1, prop)
        extra = schema.get("additionalProperties")
        if not out and isinstance(extra, dict) and extra:
            out["key"] = self.value(extra, context, depth + 1, "key")
        return out

    def _string(self, schema: dict[str, Any], key: str) -> str:
        fmt = schema.get("format")
        if fmt in STRING_FORMATS:
            return STRING_FORMATS[fmt]
        pattern = schema.get("pattern")
        min_len = int(schema.get("minLength", 0))
        max_len = int(schema.get("maxLength", 64))
        if pattern:
            sampled = sample_pattern(str(pattern))
            if sampled is not None and min_len <= len(sampled) <= max_len:
                return sampled
            return sampled if sampled is not None else "a" * max(min_len, 1)
        base = _word_for(key)
        if len(base) < min_len:
            base = base + "x" * (min_len - len(base))
        return base[:max_len] if max_len >= min_len else base


def _number(schema: dict[str, Any], *, integer: bool) -> float:
    lo = schema.get("minimum")
    hi = schema.get("maximum")
    ex_lo = schema.get("exclusiveMinimum")
    ex_hi = schema.get("exclusiveMaximum")
    step = 1 if integer else 0.5
    if isinstance(ex_lo, bool):
        ex_lo = lo if ex_lo else None
    if isinstance(ex_hi, bool):
        ex_hi = hi if ex_hi else None
    low = None
    if lo is not None:
        low = lo
    if ex_lo is not None:
        low = ex_lo + step if low is None or ex_lo >= low else low
    high = None
    if hi is not None:
        high = hi
    if ex_hi is not None:
        high = ex_hi - step if high is None or ex_hi <= high else high
    value: float = low if low is not None else (1 if integer else 1.5)
    if high is not None and value > high:
        value = high
    multiple = schema.get("multipleOf")
    if multiple:
        m = float(multiple)
        k = -(-value // m)  # ceil
        value = k * m
        if high is not None and value > high:
            value = (high // m) * m
        if integer:
            value = round(value)
    if integer:
        return int(value)
    return float(value)


_WORDS = {
    "name": "Ada Lovelace",
    "title": "Getting started",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "username": "ada",
    "city": "London",
    "country": "GB",
    "description": "An example description",
    "status": "active",
    "id": "item-1",
    "slug": "getting-started",
    "phone": "+15550100",
    "currency": "USD",
    "message": "Hello",
    "code": "E100",
    "token": "example-token",
    "url": "https://example.com",
    "tag": "example",
}


def _word_for(key: str) -> str:
    k = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
    return _WORDS.get(k, "example")


def _variant(value: Any, i: int) -> Any:
    if isinstance(value, str):
        return f"{value}{i}" if i else value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value + i
    return value


def _fits(value: Any, schema: dict[str, Any]) -> bool:
    """A cheap type check: spec examples that clearly contradict their schema are skipped."""
    t = schema.get("type")
    types = t if isinstance(t, list) else [t] if t else []
    if value is None:
        return bool(schema.get("nullable")) or "null" in types
    if not types:
        return True
    checks = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
        "null": value is None,
    }
    if not any(checks.get(x, True) for x in types):
        return False
    if isinstance(value, str):
        if "enum" in schema and value not in schema["enum"]:
            return False
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            return False
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            return False
        if "pattern" in schema:
            try:
                if re.search(str(schema["pattern"]), value) is None:
                    return False
            except re.error:
                return False
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
    if isinstance(value, dict):
        required = schema.get("required") or []
        if any(r not in value for r in required):
            return False
    return True


# ── a minimal regular expression sampler ─────────────────────────────────────


class _UnsampleableError(Exception):
    pass


def sample_pattern(pattern: str) -> str | None:
    """A short string matching ``pattern`` (search semantics), or None when unsure."""
    try:
        parsed = sre_parse.parse(pattern)
        out = _emit(parsed)
    except (re.error, _UnsampleableError, RecursionError, OverflowError):
        return None
    try:
        if re.search(pattern, out) is None:
            return None
    except re.error:
        return None
    return out


def _emit(parsed: Any) -> str:
    out: list[str] = []
    for op, av in parsed:
        out.append(_emit_one(op, av))
    return "".join(out)


def _emit_one(op: Any, av: Any) -> str:
    c = sre_constants
    if op is c.LITERAL:
        return chr(av)
    if op is c.NOT_LITERAL:
        return "a" if chr(av) != "a" else "b"
    if op is c.ANY:
        return "a"
    if op is c.IN:
        return _emit_class(av)
    if op in (c.MAX_REPEAT, c.MIN_REPEAT, getattr(c, "POSSESSIVE_REPEAT", object())):
        lo, _hi, sub = av
        count = max(lo, 0)
        return "".join(_emit(sub) for _ in range(min(count, 64)))
    if op is c.SUBPATTERN:
        sub = av[-1]
        return _emit(sub)
    if op is getattr(c, "ATOMIC_GROUP", object()):
        return _emit(av)
    if op is c.BRANCH:
        return _emit(av[1][0])
    if op is c.AT:
        return ""
    if op is c.GROUPREF:
        raise _UnsampleableError
    if op in (c.ASSERT, c.ASSERT_NOT):
        raise _UnsampleableError
    if op is c.CATEGORY:
        return _category(av)
    raise _UnsampleableError


def _emit_class(items: Any) -> str:
    c = sre_constants
    negate = any(op is c.NEGATE for op, _ in items)
    if negate:
        excluded: set[str] = set()
        for op, av in items:
            if op is c.LITERAL:
                excluded.add(chr(av))
            elif op is c.RANGE:
                excluded |= {chr(x) for x in range(av[0], min(av[1], av[0] + 300) + 1)}
        for candidate in "aZ0_x":
            if candidate not in excluded:
                return candidate
        raise _UnsampleableError
    for op, av in items:
        if op is c.LITERAL:
            return chr(av)
        if op is c.RANGE:
            return chr(av[0])
        if op is c.CATEGORY:
            return _category(av)
    raise _UnsampleableError


def _category(av: Any) -> str:
    c = sre_constants
    table = {
        c.CATEGORY_DIGIT: "1",
        c.CATEGORY_NOT_DIGIT: "a",
        c.CATEGORY_SPACE: " ",
        c.CATEGORY_NOT_SPACE: "a",
        c.CATEGORY_WORD: "a",
        c.CATEGORY_NOT_WORD: "-",
    }
    if av in table:
        return table[av]
    raise _UnsampleableError
