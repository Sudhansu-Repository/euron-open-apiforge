"""Does the running app serve the API its spec describes? (standard library only)

``compare(spec, served)`` reduces both OpenAPI documents to a canonical form (refs inlined,
``allOf`` merged, 3.0 ``nullable`` and 3.1 ``null`` types unified, unions order-free) and
lists every difference that changes behaviour: a missing or extra operation, a parameter
with another location, requiredness or schema, a request body or response whose media type
or schema differs, different security. It ignores what does not change behaviour: titles,
descriptions, examples, the 422 response FastAPI adds for validation errors, integer and
number format hints, and ``null`` on properties and parameters that are optional anyway.

This module is copied into every generated project (``tests/generated/fidelity.py``), so
keep it free of third-party imports.
"""

from __future__ import annotations

import json
from typing import Any

METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")
MAX_DEPTH = 24
STRING_FORMATS_COMPARED = {
    "date-time",
    "date",
    "time",
    "uuid",
    "email",
    "binary",
    "byte",
    "uri",
    "hostname",
    "ipv4",
    "ipv6",
    "password",
    "duration",
}


def compare(
    spec: dict[str, Any],
    served: dict[str, Any],
    accepted: list[tuple[str, str]] | tuple[tuple[str, str], ...] = (),
) -> list[str]:
    """Differences between the input spec and the served OpenAPI document; [] means equal.

    ``accepted`` lists differences APIForge reported when it generated the project, as
    (operation, part of the message) pairs; "*" matches every operation.
    """
    a = _operations(spec)
    b = _operations(served)
    problems: list[str] = []
    for key in sorted(set(a) - set(b)):
        problems.append(f"{key}: in the spec but not served")
    for key in sorted(set(b) - set(a)):
        problems.append(f"{key}: served but not in the spec")
    for key in sorted(set(a) & set(b)):
        problems.extend(f"{key}: {d}" for d in _diff(a[key], b[key]))
    return [
        p
        for p in problems
        if not any((op == "*" or p.startswith(f"{op}:")) and part in p for op, part in accepted)
    ]


# ── canonical operations ─────────────────────────────────────────────────────


def canonical_operations(doc: dict[str, Any]) -> dict[str, Any]:
    """Every operation of ``doc`` in canonical form, keyed by ``"METHOD /path"``."""
    return _operations(doc)


def _operations(doc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    global_security = doc.get("security")
    discriminators = _discriminator_props(doc)
    for path, item in (doc.get("paths") or {}).items():
        item = _deref(doc, item)
        if not isinstance(item, dict):
            continue
        shared = item.get("parameters") or []
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            params: dict[str, Any] = {}
            for raw in list(shared) + list(op.get("parameters") or []):
                p = _deref(doc, raw)
                if not isinstance(p, dict):
                    continue
                loc, name = str(p.get("in")), str(p.get("name"))
                if loc == "header" and name.lower() in ("accept", "content-type", "authorization"):
                    continue
                required = bool(p.get("required")) or loc == "path"
                schema = p.get("schema") or {}
                params[f"parameter {name} ({loc})"] = {
                    "required": required,
                    "schema": _canon(
                        doc, schema, "request", 0, optional=not required, disc=discriminators
                    ),
                }
            body: Any = None
            raw_body = _deref(doc, op.get("requestBody"))
            if isinstance(raw_body, dict) and raw_body.get("content"):
                media = _main_media(raw_body["content"])
                schema = (raw_body["content"].get(media) or {}).get("schema") or {}
                body = {
                    "required": bool(raw_body.get("required")),
                    "media": _media_family(media),
                    "schema": _canon(doc, schema, "request", 0, disc=discriminators),
                }
            responses: dict[str, Any] = {}
            for status, raw in (op.get("responses") or {}).items():
                r = _deref(doc, raw)
                if not isinstance(r, dict):
                    continue
                content = r.get("content") or {}
                entry: dict[str, Any] = {"media": None, "schema": None}
                if content:
                    media = _main_media(content)
                    schema = (content.get(media) or {}).get("schema")
                    entry = {
                        "media": _media_family(media),
                        "schema": _canon(doc, schema, "response", 0, disc=discriminators)
                        if isinstance(schema, dict)
                        else None,
                    }
                responses[str(status).upper()] = entry
            security = op.get("security", global_security)
            schemes: list[str] = []
            if security:
                if any(isinstance(s, dict) and not s for s in security):
                    schemes = []  # optional authentication
                else:
                    for alt in security:
                        if isinstance(alt, dict):
                            schemes.extend(f"{k}{sorted(v or [])}" for k, v in alt.items())
            out[f"{method.upper()} {path}"] = {
                "parameters": params,
                "request body": body,
                "responses": responses,
                "security": sorted(set(schemes)),
            }
    return out


def _main_media(content: dict[str, Any]) -> str:
    for media in content:
        base = media.split(";")[0].strip().lower()
        if base == "application/json" or base.endswith("+json"):
            return media
    return next(iter(content))


def _media_family(media: str) -> str:
    base = media.split(";")[0].strip().lower()
    if base == "application/json" or base.endswith("+json"):
        return "json"
    return base


def _discriminator_props(doc: dict[str, Any]) -> set[str]:
    props: set[str] = set()
    stack: list[Any] = [doc]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            disc = node.get("discriminator")
            if isinstance(disc, dict) and disc.get("propertyName"):
                props.add(str(disc["propertyName"]))
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return props


# ── canonical schemas ────────────────────────────────────────────────────────


def _deref(doc: dict[str, Any], node: Any, depth: int = 0) -> Any:
    while isinstance(node, dict) and "$ref" in node and depth < 32:
        ref = str(node["$ref"])
        if not ref.startswith("#"):
            return {}
        target: Any = doc
        for part in ref[1:].lstrip("/").split("/"):
            if not part:
                continue
            part = part.replace("~1", "/").replace("~0", "~")
            target = target.get(part) if isinstance(target, dict) else None
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        node = {**target, **siblings} if isinstance(target, dict) and siblings else target
        depth += 1
    return node


def _canon(
    doc: dict[str, Any],
    schema: Any,
    side: str,
    depth: int,
    *,
    optional: bool = False,
    disc: set[str] | None = None,
    stack: tuple[str, ...] = (),
) -> Any:
    disc = disc or set()
    if isinstance(schema, dict) and isinstance(schema.get("$ref"), str):
        # A component already on the path is recursion: mark it by name, in both documents.
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name in stack:
            return {"recursive": name}
        stack = (*stack, name)
    schema = _deref(doc, schema)
    if not isinstance(schema, dict) or depth > MAX_DEPTH:
        return {}
    nullable = bool(schema.get("nullable"))
    types = schema.get("type")
    type_list = (
        [t for t in types if isinstance(t, str)]
        if isinstance(types, list)
        else ([types] if isinstance(types, str) else [])
    )
    if "null" in type_list:
        nullable = True
        type_list = [t for t in type_list if t != "null"]

    for comb in ("anyOf", "oneOf"):
        options = schema.get(comb)
        if isinstance(options, list):
            real = []
            for o in options:
                o2 = _deref(doc, o)
                if isinstance(o2, dict) and (o2.get("type") == "null" or o2.get("enum") == [None]):
                    nullable = True
                    continue
                real.append(o)
            if len(real) == 1:
                inner = _canon(doc, real[0], side, depth + 1, disc=disc, stack=stack)
                if isinstance(inner, dict):
                    inner = dict(inner)
                    if nullable and not optional:
                        inner["nullable"] = True
                    inner.pop("nullable", None) if optional else None
                return inner
            parts = sorted(
                json.dumps(_canon(doc, o, side, depth + 1, disc=disc, stack=stack), sort_keys=True)
                for o in real
            )
            out: dict[str, Any] = {"union": parts}
            if nullable and not optional:
                out["nullable"] = True
            return out

    if "allOf" in schema:
        merged: dict[str, Any] = {k: v for k, v in schema.items() if k != "allOf"}
        props: dict[str, Any] = dict(merged.get("properties") or {})
        required: list[str] = list(merged.get("required") or [])
        single: Any = None
        members = [m for m in schema["allOf"] if isinstance(m, dict)]
        for m in members:
            m = _deref(doc, m)
            if not isinstance(m, dict):
                continue
            if "allOf" in m:
                m = _flatten_allof(doc, m)
            if m.get("properties") or m.get("required"):
                props.update(m.get("properties") or {})
                required.extend(m.get("required") or [])
            elif (
                m.get("type") or m.get("items") or m.get("enum") or m.get("anyOf") or m.get("oneOf")
            ):
                single = m
            if m.get("nullable"):
                nullable = True
        if not props and single is not None:
            inner = _canon(doc, single, side, depth + 1, disc=disc, stack=stack)
            if isinstance(inner, dict) and nullable and not optional:
                inner = {**inner, "nullable": True}
            return inner
        merged["properties"] = props
        merged["required"] = required
        merged["type"] = "object"
        if nullable:
            merged["nullable"] = True
        return _canon(doc, merged, side, depth, optional=optional, disc=disc, stack=stack)

    out = {}
    if "const" in schema:
        out["enum"] = [schema["const"]]
    elif "enum" in schema:
        values = [v for v in schema["enum"] if v is not None]
        if None in schema["enum"]:
            nullable = True
        out["enum"] = sorted(values, key=lambda v: json.dumps(v))
    t = type_list[0] if len(type_list) == 1 else None
    if len(type_list) > 1:
        out["type"] = sorted(type_list)
    if t is None and schema.get("properties"):
        t = "object"
    if t is None and "items" in schema:
        t = "array"
    if t:
        out["type"] = t
    if t == "string":
        fmt = schema.get("format")
        if fmt in STRING_FORMATS_COMPARED:
            out["format"] = fmt
        if schema.get("contentMediaType") == "application/octet-stream" and "format" not in out:
            out["format"] = "binary"
        for k in ("minLength", "maxLength", "pattern"):
            if k in schema:
                out[k] = schema[k]
    if t in ("integer", "number"):
        lo, hi = schema.get("minimum"), schema.get("maximum")
        ex_lo, ex_hi = schema.get("exclusiveMinimum"), schema.get("exclusiveMaximum")
        if ex_lo is True:
            ex_lo, lo = lo, None
        if ex_hi is True:
            ex_hi, hi = hi, None
        for k, v in (
            ("minimum", lo),
            ("maximum", hi),
            ("exclusiveMinimum", ex_lo),
            ("exclusiveMaximum", ex_hi),
            ("multipleOf", schema.get("multipleOf")),
        ):
            if isinstance(v, int | float) and not isinstance(v, bool):
                out[k] = float(v)
    if t == "array":
        out["items"] = _canon(
            doc, schema.get("items") or {}, side, depth + 1, disc=disc, stack=stack
        )
        for k in ("minItems", "maxItems"):
            if k in schema:
                out[k] = schema[k]
        if schema.get("uniqueItems"):
            out["uniqueItems"] = True
    if t == "object":
        required_set = set(schema.get("required") or [])
        props_out: dict[str, Any] = {}
        for name, sub in (schema.get("properties") or {}).items():
            sub_d = _deref(doc, sub)
            if isinstance(sub_d, dict):
                if side == "request" and sub_d.get("readOnly"):
                    continue
                if side == "response" and sub_d.get("writeOnly"):
                    continue
            c = _canon(
                doc, sub, side, depth + 1, optional=name not in required_set, disc=disc, stack=stack
            )
            if name in disc and isinstance(c, dict):
                c = {k: v for k, v in c.items() if k != "enum"}
            props_out[name] = c
        out["properties"] = props_out
        out["required"] = sorted(n for n in required_set if n in props_out)
        extra = schema.get("additionalProperties")
        if extra is False:
            out["additionalProperties"] = False
        elif isinstance(extra, dict) and extra:
            out["additionalProperties"] = _canon(
                doc, extra, side, depth + 1, disc=disc, stack=stack
            )
    if "default" in schema and schema["default"] is not None:
        out["default"] = schema["default"]
    if nullable and not optional:
        out["nullable"] = True
    return out


def _flatten_allof(doc: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = dict(schema.get("properties") or {})
    required: list[str] = list(schema.get("required") or [])
    for m in schema.get("allOf") or []:
        m = _deref(doc, m)
        if isinstance(m, dict):
            if "allOf" in m:
                m = _flatten_allof(doc, m)
            props.update(m.get("properties") or {})
            required.extend(m.get("required") or [])
    return {"type": "object", "properties": props, "required": required}


# ── diff ─────────────────────────────────────────────────────────────────────


def _diff(a: Any, b: Any, where: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        keys = set(a) | set(b)
        for k in sorted(keys, key=str):
            label = f"{where} {k}".strip() if where else str(k)
            if k == "responses":
                ra, rb = a.get(k) or {}, b.get(k) or {}
                rb = {s: v for s, v in rb.items() if not (s == "422" and s not in ra)}
                out.extend(_diff(ra, rb, label))
                continue
            if k not in a:
                if b[k] in (None, {}, [], False):
                    continue
                out.append(f"{label}: served has {_short(b[k])}, the spec does not")
            elif k not in b:
                if a[k] in (None, {}, [], False):
                    continue
                out.append(f"{label}: the spec has {_short(a[k])}, served does not")
            else:
                out.extend(_diff(a[k], b[k], label))
        return out
    if a != b:
        return [f"{where}: the spec says {_short(a)}, served says {_short(b)}"]
    return []


def _short(value: Any) -> str:
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= 120 else text[:117] + "..."
