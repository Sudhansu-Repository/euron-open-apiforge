"""Validate a loaded spec and build the intermediate representation."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from apiforge.errors import RefError, SpecInvalidError, UnsupportedVersionError
from apiforge.examples import ExampleBuilder, expand
from apiforge.ir import (
    ApiDef,
    BodyDef,
    OperationDef,
    ParamDef,
    ResponseDef,
    SecuritySchemeDef,
    SecurityUse,
    TagDef,
    TypeInfo,
)
from apiforge.loader import Bundle
from apiforge.naming import Namer, pascal, snake
from apiforge.report import Report, pointer
from apiforge.schemas import SchemaCompiler

METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")
IGNORED_HEADERS = {"accept", "content-type", "authorization"}
MAX_ERRORS = 20


def detect_version(doc: dict[str, Any]) -> str:
    if "swagger" in doc:
        raise UnsupportedVersionError(
            f"This is a Swagger {doc.get('swagger')} document. APIForge reads OpenAPI 3.0 and "
            "3.1: convert it first (for example with swagger2openapi or the Swagger Editor's "
            "'Convert to OpenAPI 3' action)."
        )
    version = str(doc.get("openapi", ""))
    if not (version.startswith("3.0") or version.startswith("3.1")):
        raise UnsupportedVersionError(
            f"openapi: {version or '(missing)'} is not supported. APIForge reads OpenAPI 3.0.x "
            "and 3.1.x documents."
        )
    return version


def _all_refs(node: Any) -> list[str]:
    refs: list[str] = []
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            ref = cur.get("$ref")
            if isinstance(ref, str):
                refs.append(ref)
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return refs


def validate(bundle: Bundle) -> str:
    """Structural validation with openapi-spec-validator; returns the OpenAPI version.

    Every ``$ref`` is checked to be local before the validator sees the document, and the
    bundle is written to a private temporary folder so relative file refs resolve there:
    the validator never reaches the network.
    """
    from openapi_spec_validator import OpenAPIV30SpecValidator, OpenAPIV31SpecValidator

    version = detect_version(bundle.root)
    for name, doc in bundle.documents.items():
        for ref in _all_refs(doc):
            bundle.resolve(ref, name)  # raises RefError for URLs and missing targets
    validator_cls = (
        OpenAPIV31SpecValidator if version.startswith("3.1") else OpenAPIV30SpecValidator
    )
    with tempfile.TemporaryDirectory(prefix="apiforge-") as tmp:
        import json

        root_path = Path(tmp) / bundle.root_name
        for name, doc in bundle.documents.items():
            target = Path(tmp) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(doc))
        try:
            validator = validator_cls(bundle.root, base_uri=root_path.as_uri())
            errors = []
            for err in validator.iter_errors():
                where = "/" + "/".join(str(p) for p in getattr(err, "absolute_path", []) or [])
                errors.append(f"{where if where != '/' else '(root)'}: {err.message}")
                if len(errors) >= MAX_ERRORS:
                    break
        except RefError:
            raise
        except Exception as exc:  # the validator's own resolution errors
            raise SpecInvalidError(f"The spec could not be validated: {exc}") from exc
    if errors:
        raise SpecInvalidError(
            f"The spec is not a valid OpenAPI {version} document ({len(errors)} problem"
            f"{'s' if len(errors) != 1 else ''}; the first: {errors[0]}).",
            errors=errors,
        )
    return version


class Normalizer:
    def __init__(self, bundle: Bundle, report: Report, version: str) -> None:
        self.bundle = bundle
        self.report = report
        self.version = version
        self.root = bundle.root
        self.compiler = SchemaCompiler(bundle, report, version)
        self.examples = ExampleBuilder(report)
        self._funcs = Namer({"router"})
        self._op_ids: set[str] = set()
        self._dropped_security = False
        self._accepted: list[tuple[str, str]] = []

    def build(self) -> ApiDef:
        info = self.root.get("info") or {}
        components = self.root.get("components") or {}
        for name in sorted((components.get("schemas") or {}).keys()):
            self.compiler.component(name)
        schemes = self._schemes(components.get("securitySchemes") or {})
        tag_docs = {
            t.get("name"): t.get("description")
            for t in self.root.get("tags") or []
            if isinstance(t, dict) and t.get("name")
        }
        operations: list[OperationDef] = []
        paths = self.root.get("paths") or {}
        if not paths:
            self.report.warning(
                "no_paths", "The spec has no paths: the project will only have /health."
            )
        seen_routes: dict[tuple[str, str], str] = {}
        for raw_path, item in paths.items():
            item_ptr = pointer("paths", raw_path)
            file = self.bundle.root_name
            if isinstance(item, dict) and "$ref" in item:
                file, _, item = self.bundle.resolve(item["$ref"], file)
            if not isinstance(item, dict):
                continue
            shared = item.get("parameters") or []
            for method in METHODS:
                op = item.get(method)
                if not isinstance(op, dict):
                    continue
                op_ptr = f"{item_ptr}/{method}"
                route = (method, _route_shape(raw_path))
                if route in seen_routes:
                    self._accepted.append(
                        (f"{method.upper()} {raw_path}", "in the spec but not served")
                    )
                    self.report.error(
                        "duplicate_route",
                        f"{method.upper()} {raw_path} has the same shape as "
                        f"{seen_routes[route]}; only the first is generated.",
                        op_ptr,
                    )
                    continue
                seen_routes[route] = f"{method.upper()} {raw_path}"
                operations.append(
                    self._operation(raw_path, method, op, shared, file, op_ptr, schemes)
                )
        for key in ("callbacks", "links"):
            if components.get(key):
                self.report.warning(
                    f"{key}_not_generated",
                    f"components.{key} are documentation only in this release; no code is "
                    "generated for them.",
                    pointer("components", key),
                )
        if self.root.get("webhooks"):
            self.report.warning(
                "webhooks_not_generated",
                "Top-level webhooks describe requests your API sends; no code is generated "
                "for them.",
                "/webhooks",
            )
        tags: list[TagDef] = []
        modules = Namer({"generated", "handlers", "main", "config", "auth", "db", "tests"})
        for op in operations:
            if not any(t.wire == op.tag for t in tags):
                tags.append(
                    TagDef(op.tag, modules.take(snake(op.tag, "default")), tag_docs.get(op.tag))
                )
        for op in operations:
            op.module = next(t.module for t in tags if t.wire == op.tag)
        models = self.compiler.finish()
        if any(f.code == "unique_items_not_enforced" for f in self.report.findings):
            self._accepted.append(("*", "uniqueItems"))
        return ApiDef(
            title=str(info.get("title") or "API"),
            version=str(info.get("version") or "0.1.0"),
            description=info.get("description"),
            openapi=self.version,
            info=info,
            servers=[s for s in self.root.get("servers") or [] if isinstance(s, dict)],
            tags=tags,
            operations=operations,
            models=models,
            schemes=schemes,
            accepted=self._accepted,
        )

    # ── operations ────────────────────────────────────────────────────────────

    def _operation(
        self,
        path: str,
        method: str,
        op: dict[str, Any],
        shared: list[Any],
        file: str,
        ptr: str,
        schemes: list[SecuritySchemeDef],
    ) -> OperationDef:
        op_id = op.get("operationId")
        if not op_id:
            op_id = snake(f"{method} {path.replace('{', ' by ').replace('}', ' ')}", "operation")
            self.report.info(
                "operation_id_derived",
                f"{method.upper()} {path} has no operationId; it is named {op_id!r}.",
                ptr,
            )
        elif op_id in self._op_ids:
            self.report.error(
                "duplicate_operation_id", f"operationId {op_id!r} is used twice.", ptr
            )
        self._op_ids.add(str(op_id))
        func = self._funcs.take(snake(str(op_id), "operation"))
        tags = op.get("tags") or []
        tag = str(tags[0]) if tags else "default"
        if len(tags) > 1:
            self.report.info(
                "extra_tags",
                f"{func} has {len(tags)} tags; it is generated under the first, {tag!r}, and "
                "documented under all of them.",
                ptr,
            )
        params = self._params(shared, op.get("parameters") or [], file, ptr, func, path)
        body = self._body(op.get("requestBody"), file, f"{ptr}/requestBody", func)
        responses = self._responses(op.get("responses") or {}, file, f"{ptr}/responses", func)
        accepted: list[str] = []
        if not any((r.code or 0) // 100 == 2 or r.status == "2XX" for r in responses):
            if any(r.status == "default" for r in responses):
                outcome = "200 with the default response's body"
                # The served document lists that 200 next to the spec's default.
                accepted.append("responses 200: served has")
            else:
                outcome = "200 with no body"
            self.report.warning(
                "no_success_response",
                f"{method.upper()} {path} documents no 2xx response; the handler returns "
                f"{outcome}.",
                f"{ptr}/responses",
            )
        security = self._security(op, ptr, schemes)
        for p in params:
            if p.approximate:
                accepted.append(f"parameter {p.wire} ({p.location}) schema")
        if body is not None and any(f.approximate for f in body.form_fields):
            accepted.extend(
                f"request body schema properties {f.wire}"
                for f in body.form_fields
                if f.approximate
            )
        if (
            body is not None
            and body.kind == "binary"
            and body.media_type.startswith("application/x-www-form-urlencoded")
        ):
            accepted.append("request body")
        if self._dropped_security:
            accepted.append("security")
            self._dropped_security = False
        if op.get("callbacks"):
            self.report.warning(
                "callbacks_not_generated",
                "Callbacks are documentation only in this release.",
                f"{ptr}/callbacks",
            )
        if op.get("servers"):
            self.report.info(
                "operation_servers",
                "Operation-level servers are documented but do not change routing.",
                f"{ptr}/servers",
            )
        return OperationDef(
            operation_id=str(op_id),
            func=func,
            method=method,
            path=path,
            tag=tag,
            module="",
            summary=op.get("summary"),
            description=op.get("description"),
            deprecated=bool(op.get("deprecated")),
            params=params,
            body=body,
            responses=responses,
            security=security,
            pointer=ptr,
            accepted=accepted,
        )

    def _params(
        self,
        shared: list[Any],
        own: list[Any],
        file: str,
        ptr: str,
        func: str,
        path: str,
    ) -> list[ParamDef]:
        merged: dict[tuple[str, str], tuple[dict[str, Any], str, str]] = {}
        for i, raw in enumerate(shared):
            p, pfile = self._deref(raw, file)
            if isinstance(p, dict):
                merged[(str(p.get("name")), str(p.get("in")))] = (
                    p,
                    pfile,
                    f"{ptr.rsplit('/', 1)[0]}/parameters/{i}",
                )
        for i, raw in enumerate(own):
            p, pfile = self._deref(raw, file)
            if isinstance(p, dict):
                merged[(str(p.get("name")), str(p.get("in")))] = (p, pfile, f"{ptr}/parameters/{i}")
        names = Namer({"principal", "body", "request", "file", "files"})
        out: list[ParamDef] = []
        for (wire, loc), (p, pfile, pptr) in merged.items():
            if loc == "header" and wire.lower() in IGNORED_HEADERS:
                self.report.info(
                    "header_param_ignored",
                    f"Header parameter {wire!r} is ignored (OpenAPI reserves it; FastAPI sets it).",
                    pptr,
                )
                continue
            if loc not in ("path", "query", "header", "cookie"):
                continue
            approximate = False
            schema = p.get("schema")
            if schema is None and "content" in p:
                self.report.warning(
                    "param_content_as_string",
                    f"Parameter {wire!r} uses 'content'; it is received as a string.",
                    pptr,
                )
                schema = {"type": "string"}
                approximate = True
            info = self.compiler.type_of(
                schema or {},
                file=pfile,
                pointer=f"{pptr}/schema",
                hint=func + pascal(wire),
                context="request",
            )
            style = p.get("style")
            explode = p.get("explode")
            if style == "deepObject" or (
                info.expr.startswith("dict") or _is_model(info, self.compiler)
            ):
                self.report.warning(
                    "param_object_as_string",
                    f"Object parameter {wire!r} ({style or 'form'} style) is received as a string.",
                    pptr,
                )
                info = TypeInfo("str", {"type": "string"})
                approximate = True
            if info.is_array and loc == "query" and explode is False:
                self.report.warning(
                    "param_explode_false",
                    f"Array parameter {wire!r} has explode: false (a,b,c); it is received as "
                    "repeated parameters (?x=a&x=b).",
                    pptr,
                )
            if style in ("spaceDelimited", "pipeDelimited", "matrix", "label"):
                self.report.warning(
                    "param_style",
                    f"Parameter {wire!r} uses style {style!r}; it is read as the default style.",
                    pptr,
                )
            required = bool(p.get("required")) or loc == "path"
            schema_dict = schema if isinstance(schema, dict) else {}
            default = None
            if not required:
                d = schema_dict.get("default")
                from apiforge.naming import py_literal

                default = py_literal(d) if d is not None else "None"
            expanded = expand(self.bundle, schema_dict, pfile)
            example = p.get("example")
            has_example = "example" in p
            if not has_example and isinstance(p.get("examples"), dict) and p["examples"]:
                first = next(iter(p["examples"].values()))
                if isinstance(first, dict) and "value" in first:
                    example, has_example = first["value"], True
            if not has_example:
                example = self.examples.value(expanded, "request", key=wire)
            out.append(
                ParamDef(
                    name=names.take(snake(wire, "param")),
                    wire=wire,
                    location=loc,  # type: ignore[arg-type]
                    type=info,
                    required=required,
                    default=default,
                    description=p.get("description"),
                    deprecated=bool(p.get("deprecated")),
                    example=example,
                    has_example=True,
                    approximate=approximate,
                )
            )
        for name in _path_names(path):
            if not any(pp.location == "path" and pp.wire == name for pp in out):
                self.report.error(
                    "path_param_undeclared",
                    f"Path parameter {{{name}}} in {path} is not declared; it is added as a "
                    "string.",
                    ptr,
                )
                out.append(
                    ParamDef(
                        names.take(snake(name, "param")),
                        name,
                        "path",
                        TypeInfo("str", {"type": "string"}),
                        True,
                        example="value",
                        has_example=True,
                    )
                )
        order = {"path": 0, "query": 1, "header": 2, "cookie": 3}
        out.sort(key=lambda x: (order[x.location], not x.required))
        return out

    def _body(self, raw: Any, file: str, ptr: str, func: str) -> BodyDef | None:
        if raw is None:
            return None
        body, bfile = self._deref(raw, file)
        if not isinstance(body, dict):
            return None
        content = body.get("content") or {}
        if not content:
            return None
        chosen = None
        for kind, test in (
            ("json", _is_json),
            ("form", lambda m: m.startswith("application/x-www-form-urlencoded")),
            ("multipart", lambda m: m.startswith("multipart/form-data")),
            ("text", lambda m: m.startswith("text/")),
            ("binary", lambda m: True),
        ):
            for media in content:
                if test(media.lower()):
                    chosen = (kind, media)
                    break
            if chosen:
                break
        assert chosen is not None
        kind, media = chosen
        others = [m for m in content if m != media]
        if others:
            self.report.warning(
                "body_media_types_dropped",
                f"Only {media} is generated for this request body; {', '.join(others)} "
                "are accepted by the spec but not by the generated route.",
                ptr,
            )
        mobj = content[media] if isinstance(content[media], dict) else {}
        schema = mobj.get("schema") or {}
        required = bool(body.get("required"))
        mptr = f"{ptr}/content/{media.replace('/', '~1')}/schema"
        expanded = expand(self.bundle, schema, bfile)
        example = mobj.get("example")
        if example is None and isinstance(mobj.get("examples"), dict) and mobj["examples"]:
            first = next(iter(mobj["examples"].values()))
            if isinstance(first, dict):
                example = first.get("value")
        if example is None:
            example = self.examples.value(expanded, "request")
        if kind in ("json", "form"):
            info = self.compiler.type_of(
                schema, file=bfile, pointer=mptr, hint=pascal(func) + "Request", context="request"
            )
            if kind == "form" and not _is_model(info, self.compiler):
                self.report.warning(
                    "form_not_object",
                    "A form body that is not an object is received as raw bytes.",
                    ptr,
                )
                return BodyDef(
                    "binary", media, None, required, body.get("description"), raw=body, example=None
                )
            return BodyDef(
                kind,  # type: ignore[arg-type]
                media,
                info,
                required,
                body.get("description"),
                raw=body,
                example=example,
            )
        if kind == "multipart":
            props = expanded.get("properties") or {}
            req = set(expanded.get("required") or [])
            names = Namer({"principal", "body", "request"})
            fields: list[ParamDef] = []
            for prop, sub in props.items():
                sub = sub if isinstance(sub, dict) else {}
                is_file = sub.get("format") == "binary" or (
                    sub.get("type") == "array"
                    and isinstance(sub.get("items"), dict)
                    and sub["items"].get("format") == "binary"
                )
                if is_file:
                    many = sub.get("type") == "array"
                    tinfo = TypeInfo(
                        "list[UploadFile]" if many else "UploadFile",
                        sub,
                        is_file=True,
                        is_array=many,
                    )
                else:
                    tinfo = self.compiler.type_of(
                        sub,
                        file=bfile,
                        pointer=f"{mptr}/properties/{prop}",
                        hint=pascal(func) + pascal(prop),
                        context="request",
                    )
                    if _is_model(tinfo, self.compiler) or tinfo.expr.startswith("dict"):
                        self.report.warning(
                            "multipart_object_part",
                            f"Multipart part {prop!r} is an object; it is received as a JSON "
                            "string.",
                            f"{mptr}/properties/{prop}",
                        )
                        tinfo = TypeInfo("str", {"type": "string"})
                        fields.append(
                            ParamDef(
                                names.take(snake(prop, "part")),
                                prop,
                                "query",
                                tinfo,
                                prop in req,
                                default=None if prop in req else "None",
                                description=sub.get("description"),
                                example="{}",
                                has_example=True,
                                approximate=True,
                            )
                        )
                        continue
                fields.append(
                    ParamDef(
                        names.take(snake(prop, "part")),
                        prop,
                        "query",
                        tinfo,
                        prop in req,
                        default=None if prop in req else "None",
                        description=sub.get("description"),
                        example=self.examples.value(sub, "request", key=prop),
                        has_example=True,
                    )
                )
            return BodyDef(
                "multipart", media, None, required, body.get("description"), fields, raw=body
            )
        return BodyDef(kind, media, None, required, body.get("description"), raw=body)  # type: ignore[arg-type]

    def _responses(self, raw: dict[str, Any], file: str, ptr: str, func: str) -> list[ResponseDef]:
        out: list[ResponseDef] = []
        for status, value in raw.items():
            status = str(status).upper() if str(status).upper().endswith("XX") else str(status)
            resp, rfile = self._deref(value, file)
            if not isinstance(resp, dict):
                continue
            rptr = f"{ptr}/{status}"
            content = resp.get("content") or {}
            media = None
            for candidate in content:
                if _is_json(candidate.lower()):
                    media = candidate
                    break
            if media is None and content:
                media = next(iter(content))
            others = [m for m in content if m != media]
            if others:
                self.report.warning(
                    "response_media_types_dropped",
                    f"Response {status}: only {media} is generated; {', '.join(others)} are "
                    "documented but not produced.",
                    rptr,
                )
            info = None
            example = None
            if media is not None:
                mobj = content[media] if isinstance(content[media], dict) else {}
                schema = mobj.get("schema")
                if isinstance(schema, dict) and _is_json(media.lower()):
                    info = self.compiler.type_of(
                        schema,
                        file=rfile,
                        pointer=f"{rptr}/content/{media.replace('/', '~1')}/schema",
                        hint=f"{pascal(func)}{status.title()}Response",
                        context="response",
                    )
                    expanded = expand(self.bundle, schema, rfile)
                    example = mobj.get("example")
                    if (
                        example is None
                        and isinstance(mobj.get("examples"), dict)
                        and mobj["examples"]
                    ):
                        first = next(iter(mobj["examples"].values()))
                        if isinstance(first, dict):
                            example = first.get("value")
                    if example is None:
                        example = self.examples.value(expanded, "response")
                elif isinstance(schema, dict):
                    info = TypeInfo("bytes", schema, is_file=True)
            out.append(
                ResponseDef(
                    status=status,
                    description=str(resp.get("description") or ""),
                    media_type=media,
                    type=info,
                    raw={k: v for k, v in resp.items() if k in ("headers", "links")},
                    example=example,
                )
            )
        return out

    # ── security ──────────────────────────────────────────────────────────────

    def _schemes(self, raw: dict[str, Any]) -> list[SecuritySchemeDef]:
        names = Namer()
        out: list[SecuritySchemeDef] = []
        for wire, value in raw.items():
            s, _ = self._deref(value, self.bundle.root_name)
            if not isinstance(s, dict):
                continue
            sptr = pointer("components", "securitySchemes", wire)
            t = s.get("type")
            name = names.take(snake(wire, "scheme"))
            if t == "http" and str(s.get("scheme", "")).lower() == "bearer":
                out.append(
                    SecuritySchemeDef(
                        wire,
                        name,
                        "bearer",
                        s.get("description"),
                        bearer_format=s.get("bearerFormat"),
                    )
                )
            elif t == "http" and str(s.get("scheme", "")).lower() == "basic":
                out.append(SecuritySchemeDef(wire, name, "basic", s.get("description")))
            elif t == "apiKey" and s.get("in") in ("header", "query", "cookie"):
                out.append(
                    SecuritySchemeDef(
                        wire,
                        name,
                        "apikey",
                        s.get("description"),
                        location=s["in"],
                        param_name=str(s.get("name")),
                    )
                )
            elif t == "oauth2":
                out.append(
                    SecuritySchemeDef(
                        wire, name, "oauth2", s.get("description"), flows=s.get("flows") or {}
                    )
                )
            elif t == "openIdConnect":
                out.append(
                    SecuritySchemeDef(
                        wire,
                        name,
                        "openid",
                        s.get("description"),
                        openid_url=s.get("openIdConnectUrl"),
                    )
                )
            else:
                self.report.error(
                    "security_scheme_unsupported",
                    f"Security scheme {wire!r} ({t} {s.get('scheme', '')}) is not supported; "
                    "a requirement that needs it never accepts a request (401).",
                    sptr,
                )
        return out

    def _security(
        self, op: dict[str, Any], ptr: str, schemes: list[SecuritySchemeDef]
    ) -> list[list[SecurityUse]] | None:
        requirement = op.get("security", self.root.get("security"))
        if requirement is None:
            return None
        if requirement == []:
            return []
        known = {s.wire for s in schemes}
        # Each requirement object is one alternative (OR); the schemes inside it are all
        # needed (AND). A scheme APIForge cannot check stays in its alternative, so the
        # target can refuse that alternative instead of dropping the requirement.
        alternatives: list[list[SecurityUse]] = []
        for alt in requirement:
            if not isinstance(alt, dict):
                continue
            if not alt:
                self.report.info(
                    "optional_auth",
                    "Authentication is optional for this operation; requests without "
                    "credentials are allowed and the handler receives no principal.",
                    ptr,
                )
                return None
            uses = [SecurityUse(str(name), list(scopes or [])) for name, scopes in alt.items()]
            if any(u.scheme not in known for u in uses):
                self._dropped_security = True
            key = sorted((u.scheme, sorted(u.scopes)) for u in uses)
            if not any(
                sorted((u.scheme, sorted(u.scopes)) for u in a) == key for a in alternatives
            ):
                alternatives.append(uses)
        return alternatives or None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _deref(self, value: Any, file: str) -> tuple[Any, str]:
        seen = 0
        while isinstance(value, dict) and "$ref" in value:
            file, _, value = self.bundle.resolve(value["$ref"], file)
            seen += 1
            if seen > 32:
                raise RefError("A $ref chain loops.")
        return value, file


def _requirement_key(uses: list[SecurityUse]) -> list[tuple[str, list[str]]]:
    return sorted((u.scheme, sorted(u.scopes)) for u in uses)


def _is_json(media: str) -> bool:
    base = media.split(";")[0].strip()
    return base == "application/json" or base.endswith("+json")


def _is_model(info: TypeInfo, compiler: SchemaCompiler) -> bool:
    name = info.expr.removesuffix(" | None")
    model = compiler.models.get(name)
    return model is not None and model.kind == "object"


def _path_names(path: str) -> list[str]:
    import re

    return re.findall(r"\{([^}/]+)\}", path)


def _route_shape(path: str) -> str:
    import re

    return re.sub(r"\{[^}/]+\}", "{}", path.rstrip("/") or "/")


def normalize(bundle: Bundle, report: Report | None = None) -> tuple[ApiDef, Report]:
    report = report or Report()
    version = validate(bundle)
    api = Normalizer(bundle, report, version).build()
    return api, report
