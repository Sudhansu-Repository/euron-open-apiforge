"""The FastAPI target: from the IR to the project's file set.

Signatures, decorators and imports are computed here, in Python, so the templates only lay
out blocks. Two kinds of files come out:

- ``generated`` (``app/generated/``, ``tests/generated/``): rewritten on every generation.
- ``user`` (``app/handlers/``, ``app/main.py``, ``app/config.py``, ``app/auth.py``, the
  project files): created once; regeneration never rewrites them (new operations get new
  stubs appended to the handler module, see ``writer.py``).
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from apiforge import __version__
from apiforge.ir import ApiDef, OperationDef, ParamDef, ResponseDef, SecuritySchemeDef
from apiforge.naming import Namer, docstring, pascal, py_literal, snake
from apiforge.options import GenerateOptions
from apiforge.render import GeneratedFile, environment, render
from apiforge.schemas import kwargs

TEMPLATES = Path(__file__).parent / "templates"

STD_IMPORTS: dict[str, str] = {
    "Annotated": "typing",
    "Any": "typing",
    "Literal": "typing",
    "datetime": "datetime",
    "date": "datetime",
    "time": "datetime",
    "UUID": "uuid",
    "EmailStr": "pydantic",
    "Field": "pydantic",
    "UploadFile": "fastapi",
}
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Path parameter names Starlette can route on; others are renamed in the route and mapped
# back in the served OpenAPI document (see app.py's PATH_RENAMES).
ROUTABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Python string literals as repr() writes them, so names inside strings are not imports.
_STRING = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
HANDLER_PREFIX = "app/handlers/"
PAGE_NAMES = {"limit", "offset", "page", "page_size", "per_page", "size"}
# The WWW-Authenticate challenge a 401 names for each kind of scheme.
CHALLENGES = {
    "bearer": "Bearer",
    "oauth2": "Bearer",
    "openid": "Bearer",
    "basic": "Basic",
    "apikey": "APIKey",
}
AUTH_HEADER = {"bearer", "basic", "oauth2", "openid"}  # kinds read from Authorization


def tokens(*exprs: str) -> set[str]:
    out: set[str] = set()
    for e in exprs:
        out |= set(_TOKEN.findall(_STRING.sub("''", e)))
    return out


_LITERAL = re.compile(r"Literal\[((?:[^\[\]'\"]|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")*)\]")


def wire_literals(expr: str) -> str:
    """``Literal[1, 2]`` -> ``Annotated[Literal[1, 2], wire_literal(1, 2)]`` for parameters.

    Parameter values arrive as text, and Pydantic never matches the text "2" to the member
    2; ``wire_literal`` (app/generated/wire.py) converts it first. String-only literals are
    left alone.
    """

    def wrap(m: re.Match[str]) -> str:
        members = ast.literal_eval(f"({m.group(1)},)")
        if all(isinstance(v, str) for v in members):
            return m.group(0)
        return f"Annotated[{m.group(0)}, wire_literal({m.group(1)})]"

    return _LITERAL.sub(wrap, expr)


def import_lines(names: set[str], models: set[str]) -> list[str]:
    by_module: dict[str, set[str]] = {}
    for n in names:
        if n in STD_IMPORTS:
            by_module.setdefault(STD_IMPORTS[n], set()).add(n)
    lines = [f"from {m} import {', '.join(sorted(ns))}" for m, ns in sorted(by_module.items())]
    if "re" in names:
        lines.insert(0, "import re")
    if "wire_literal" in names:
        lines.append("from app.generated.wire import wire_literal")
    used_models = sorted(names & models)
    if used_models:
        lines.append(f"from app.generated.models import {', '.join(used_models)}")
    return lines


def qualify(expr: str, models: set[str]) -> str:
    """``list[Pet] | None`` -> ``list[models.Pet] | None`` (handler modules import ``models``)."""
    return _TOKEN.sub(
        lambda m: f"models.{m.group(0)}" if m.group(0) in models else m.group(0), expr
    )


@dataclass
class OpView:
    """Everything a template needs for one operation."""

    op: OperationDef
    decorator: list[str] = field(default_factory=list)
    router_params: list[str] = field(default_factory=list)
    call_args: list[str] = field(default_factory=list)
    handler_params: list[str] = field(default_factory=list)
    return_expr: str = "None"
    handler_return: str = "None"
    result_mode: str = "model"  # model | empty | raw | plain
    status_code: int = 200
    media_type: str | None = None
    security_args: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    principal_expr: str = "principal"  # what the route passes the handler as principal
    require: str | None = None  # the security.require(...) call, when the route has one
    test_schemes: list[str] = field(default_factory=list)  # one alternative, for the tests
    auth_label: str = "none"  # for the README
    mock_body: str = "None"
    mock_type: str = "None"
    doc: str = ""
    test: dict[str, Any] = field(default_factory=dict)
    crud_body: list[str] = field(default_factory=list)  # handler body lines for --db
    error_mocks: list[tuple[str, str, str]] = field(default_factory=list)  # (func, type, body)
    route_path: str = ""  # the path FastAPI routes on (renamed parameters, see ROUTABLE)
    renames: dict[str, str] = field(default_factory=dict)  # Python name -> wire name


@dataclass
class ResourceView:
    """One collection resource implemented by ``--db``."""

    name: str  # snake, e.g. "pet"
    row: str  # ORM class, e.g. "PetRow"
    table: str
    model: str
    id_field: str
    id_type: str
    id_alias: str = "id"
    columns: list[dict[str, Any]] = field(default_factory=list)
    ops: dict[str, OpView] = field(default_factory=dict)


class FastApiTarget:
    def __init__(self, api: ApiDef, options: GenerateOptions, spec: dict[str, Any]) -> None:
        self.api = api
        self.options = options
        self.spec = spec
        self.env = environment(TEMPLATES)
        self.model_names = {m.name for m in api.models}
        self.slug = options.slug(api.title)
        self.views = [self._view(op) for op in api.operations]
        self.resources = self._resources() if options.db else []

    # ── operations ────────────────────────────────────────────────────────────

    def _view(self, op: OperationDef) -> OpView:
        v = OpView(op=op)
        names = Namer({p.name for p in op.params} | {"principal", "body", "request", "result"})
        required: list[str] = []
        optional: list[str] = []
        h_required: list[str] = []
        h_optional: list[str] = []

        v.route_path = op.path
        for p in op.params:
            if p.location == "path" and not ROUTABLE.match(p.wire):
                v.route_path = v.route_path.replace("{" + p.wire + "}", "{" + p.name + "}")
                v.renames[p.name] = p.wire
        for p in op.params:
            marker = {"path": "Path", "query": "Query", "header": "Header", "cookie": "Cookie"}[
                p.location
            ]
            kw = {} if p.name in v.renames else {"alias": py_literal(p.wire)}
            kw.update(p.type.constraints)
            if "pattern" in kw:
                # A compiled pattern makes FastAPI validate with Python's re, like the
                # models (regex_engine="python-re"): the default engine has no look-around,
                # and a spec's "^(?!admin)" would stop the app from starting.
                kw["pattern"] = f"re.compile({kw['pattern']})"
            if p.description:
                kw["description"] = py_literal(p.description)
            if p.deprecated:
                kw["deprecated"] = "True"
            ann = f"Annotated[{wire_literals(self._param_type(p))}, {marker}({kwargs(kw)})]"
            h_type = qualify(self._param_type(p), self.model_names)
            if p.required:
                required.append(f"{p.name}: {ann}")
                h_required.append(f"{p.name}: {h_type}")
            else:
                optional.append(f"{p.name}: {ann} = {p.default}")
                h_optional.append(f"{p.name}: {h_type} = {p.default}")
            v.call_args.append(f"{p.name}={p.name}")

        body = op.body
        if body is not None:
            if body.kind in ("json", "form") and body.type is not None:
                marker = "Body" if body.kind == "json" else "Form"
                expr = body.type.expr
                kw = {}
                if body.description:
                    kw["description"] = py_literal(body.description)
                if body.kind == "json" and body.media_type != "application/json":
                    kw["media_type"] = py_literal(body.media_type)
                if body.required:
                    required.append(f"body: Annotated[{expr}, {marker}({kwargs(kw)})]")
                    h_required.append(f"body: {qualify(expr, self.model_names)}")
                else:
                    t = expr if expr.endswith("| None") else f"{expr} | None"
                    optional.append(f"body: Annotated[{t}, {marker}({kwargs(kw)})] = None")
                    h_optional.append(f"body: {qualify(t, self.model_names)} = None")
                v.call_args.append("body=body")
            elif body.kind == "multipart":
                for f in body.form_fields:
                    marker = "File" if f.type.is_file else "Form"
                    kw = {"alias": py_literal(f.wire)}
                    kw.update(f.type.constraints)
                    t = f.type.expr
                    ann_t = t if f.required else (t if t.endswith("| None") else f"{t} | None")
                    ann = f"Annotated[{ann_t}, {marker}({kwargs(kw)})]"
                    if f.required:
                        required.append(f"{f.name}: {ann}")
                        h_required.append(f"{f.name}: {qualify(ann_t, self.model_names)}")
                    else:
                        optional.append(f"{f.name}: {ann} = None")
                        h_optional.append(f"{f.name}: {qualify(ann_t, self.model_names)} = None")
                    v.call_args.append(f"{f.name}={f.name}")
            else:  # binary or text: read the raw body
                required.insert(0, "request: Request")
                h_required.append("body: bytes" if body.kind == "binary" else "body: str")
                v.call_args.append(
                    "body=await request.body()"
                    if body.kind == "binary"
                    else "body=(await request.body()).decode()"
                )

        if op.security:
            self._security(op, v, names, required)
            h_required.append("principal: Principal")
            v.call_args.append(f"principal={v.principal_expr}")

        v.router_params = required + optional
        v.handler_params = h_required + h_optional

        # decorator
        success = op.success
        dec = [py_literal(v.route_path), f"operation_id={py_literal(op.operation_id)}"]
        dec.append(f"tags={py_literal(self._tags_of(op))}")
        if op.summary:
            dec.append(f"summary={py_literal(op.summary)}")
        if op.description:
            dec.append(f"description={py_literal(op.description)}")
        if op.deprecated:
            dec.append("deprecated=True")
        responses: dict[str, list[str]] = {}
        if success is not None:
            v.status_code = success.code or 200
            dec.append(f"status_code={v.status_code}")
            dec.append(
                f"response_description={py_literal(success.description or 'Successful Response')}"
            )
            if success.type is not None and success.is_json:
                dec.append(f"response_model={success.type.expr}")
                v.return_expr = success.type.expr
                v.handler_return = qualify(success.type.expr, self.model_names)
                v.result_mode = "model"
                v.mock_type = success.type.expr
                v.mock_body = py_literal(success.example)
            elif success.media_type is not None:
                dec.append("response_class=Response")
                v.result_mode = "raw"
                v.media_type = success.media_type
                v.return_expr = "Response"
                v.handler_return = "bytes"
                v.mock_type = "bytes"
                v.mock_body = "b''" if not success.media_type.startswith("text/") else "b'example'"
                responses[str(v.status_code)] = [self._content_entry(success)]
            else:
                dec.append("response_class=Response")
                v.result_mode = "empty"
                v.return_expr = "Response"
                v.handler_return = "None"
            if success.status == "default":
                # Keep the spec's default in the served document; FastAPI adds the 200.
                entry = [f'"description": {py_literal(success.description or "default")}']
                if success.type is not None and success.is_json:
                    entry.insert(0, f'"model": {success.type.expr}')
                elif success.media_type is not None:
                    entry.append(self._content_entry(success))
                responses["default"] = entry
            if success.raw.get("headers"):
                responses.setdefault(str(v.status_code), []).append(
                    f'"headers": {py_literal(self._clean_headers(success.raw["headers"]))}'
                )
        else:
            v.result_mode = "plain"
            v.return_expr = "Response"
            v.handler_return = "None"
            dec.append("response_class=Response")
        for r in op.errors:
            entry = [f'"description": {py_literal(r.description or r.status)}']
            if r.type is not None and r.is_json:
                entry.insert(0, f'"model": {r.type.expr}')
            elif r.media_type is not None:
                entry.append(self._content_entry(r))
            if r.raw.get("headers"):
                entry.append(f'"headers": {py_literal(self._clean_headers(r.raw["headers"]))}')
            responses[r.status] = entry
        if responses:
            items = []
            for status, entry in responses.items():
                key = status if status.isdigit() else py_literal(status)
                items.append(f"{key}: {{{', '.join(entry)}}}")
            dec.append("responses={" + ", ".join(items) + "}")
        if body is not None and body.kind in ("binary", "text"):
            dec.append(f"openapi_extra={py_literal({'requestBody': self._raw_body(body.raw)})}")
        v.decorator = dec
        v.doc = self._handler_doc(op, success)
        for r in op.errors:
            if r.type is not None and r.is_json:
                suffix = r.status.lower()
                v.error_mocks.append((f"{op.func}_{suffix}", r.type.expr, py_literal(r.example)))
        if op.crud is not None and self.options.db:
            v.crud_body = self._crud_body(op, v)
        v.test = self._test_case(op, v)
        return v

    def _security(self, op: OperationDef, v: OpView, names: Namer, required: list[str]) -> None:
        """Route arguments and the ``security.require`` call for the operation's requirement.

        Alternatives are OR, the schemes inside one are AND. One argument per scheme and
        scope set, shared between alternatives; ``require`` decides, so a missing scope on
        one alternative does not refuse a request another alternative accepts. An
        alternative that needs a scheme APIForge cannot check never accepts; when no
        alternative is left, the route always answers 401.
        """
        assert op.security
        usable = [alt for alt in op.security if all(self._scheme(u.scheme) for u in alt)]
        if not usable:
            arg = names.take("auth_unsupported")
            required.append(f"{arg}: Annotated[Principal, Depends(security.unsupported)]")
            v.principal_expr = arg
            v.auth_label = "refused (unsupported scheme)"
            return
        args: dict[tuple[str, tuple[str, ...]], str] = {}
        groups: list[str] = []
        challenges: list[str] = []
        for alt in usable:
            items: list[str] = []
            for use in alt:
                scheme = self._scheme(use.scheme)
                assert scheme is not None
                scopes = sorted(set(use.scopes)) if scheme.kind in ("oauth2", "openid") else []
                key = (scheme.name, tuple(scopes))
                if key not in args:
                    arg = names.take(f"auth_{scheme.name}")
                    args[key] = arg
                    dep = f"security.{scheme.name}"
                    extra = f", scopes={py_literal(scopes)}" if scopes else ""
                    required.append(f"{arg}: Annotated[Principal | None, Security({dep}{extra})]")
                    v.security_args.append(arg)
                items.append(f"({args[key]}, {py_literal(scopes)})")
                v.scopes = sorted(set(v.scopes) | set(scopes))
                challenge = CHALLENGES[scheme.kind]
                if challenge not in challenges:
                    challenges.append(challenge)
            groups.append("[" + ", ".join(items) + "]")
        v.principal_expr = "principal"
        v.require = (
            f"security.require({', '.join(groups)}, challenge={py_literal(', '.join(challenges))})"
        )
        # The generated tests send the credentials of one alternative: the first that does
        # not need the Authorization header twice (bearer and basic together, say).
        kind = {s.wire: s.kind for s in self.api.schemes}
        pick = next(
            (alt for alt in usable if sum(kind[u.scheme] in AUTH_HEADER for u in alt) <= 1),
            usable[0],
        )
        v.test_schemes = [u.scheme for u in pick]
        v.auth_label = " or ".join(" + ".join(u.scheme for u in alt) for alt in usable)

    def _crud_body(self, op: OperationDef, v: OpView) -> list[str]:
        c = op.crud
        assert c is not None
        repo = f"crud.{c.resource}"
        id_arg = next(
            (p.name for p in op.params if p.location == "path" and p.wire == c.id_param), None
        )
        not_found = next((m[0] for m in v.error_mocks if m[0].endswith("_404")), None)
        missing = f"mock.{not_found}()" if not_found else '{"detail": "Not found"}'
        if c.action == "list":
            names = {p.name: p for p in op.params if p.location == "query"}
            args: list[str] = []
            if "limit" in names:
                args.append("limit=limit")
            if "offset" in names:
                args.append("offset=offset")
            size = next((n for n in ("page_size", "per_page", "size") if n in names), None)
            if "page" in names:
                args.append("page=page")
            if size:
                args.append(f"page_size={size}")
            # A query parameter filters the column of the field with the same name on the
            # wire (``status`` filters ``status`` even though the argument is ``status_``).
            # JSON columns cannot be compared portably, so they are not offered as filters.
            from apiforge.crud import column_type

            model = next((m for m in self.api.models if m.name == c.model), None)
            enums = {m.name for m in self.api.models if m.kind == "enum"}
            by_alias = {
                alias: name
                for name, alias, type_expr, _ in (self._all_fields(model) if model else [])
                if not column_type(type_expr, enums)[1]
            }
            filters = [
                (by_alias[p.wire], p.name)
                for p in names.values()
                if p.wire in by_alias and p.name not in PAGE_NAMES
            ]
            if filters:
                args.append(
                    "filters={" + ", ".join(f"{py_literal(f)}: {a}" for f, a in filters) + "}"
                )
            return [f"return await {repo}.list({', '.join(args)})"]
        if c.action == "create":
            return [f"return await {repo}.create(body)"]
        if id_arg is None:
            return []
        if c.action == "read":
            call = f"await {repo}.get({id_arg})"
        elif c.action in ("replace", "update"):
            call = f"await {repo}.{c.action}({id_arg}, body)"
        else:
            return [
                f"if not await {repo}.delete({id_arg}):",
                f"    raise ApiError(404, {missing})",
                "return None",
            ]
        return [
            f"item = {call}",
            "if item is None:",
            f"    raise ApiError(404, {missing})",
            "return item",
        ]

    def _content_entry(self, r: ResponseDef) -> str:
        """``"content": {media: {"schema": ...}}`` for a non-JSON response."""
        schema = py_literal(self._clean(r.type.schema if r.type else {}))
        return f'"content": {{{py_literal(r.media_type)}: {{"schema": {schema}}}}}'

    def _param_type(self, p: ParamDef) -> str:
        t = p.type.expr
        if not p.required and p.default == "None" and not t.endswith("| None"):
            t = f"{t} | None"
        return t

    def _tags_of(self, op: OperationDef) -> list[str]:
        raw = self._raw_op(op)
        tags = raw.get("tags") if isinstance(raw, dict) else None
        return [str(t) for t in tags] if tags else [op.tag]

    def _raw_op(self, op: OperationDef) -> dict[str, Any]:
        item = (self.spec.get("paths") or {}).get(op.path) or {}
        if isinstance(item, dict):
            got = item.get(op.method)
            if isinstance(got, dict):
                return got
        return {}

    def _scheme(self, wire: str) -> SecuritySchemeDef | None:
        return next((s for s in self.api.schemes if s.wire == wire), None)

    def _handler_doc(self, op: OperationDef, success: ResponseDef | None) -> str:
        head = f"{op.method.upper()} {op.path}"
        if op.summary:
            head += f": {op.summary}"
        lines = [docstring(head)]
        if success is not None and success.code:
            lines.append("")
            if op.crud is not None and self.options.db:
                lines.append(f"Return the {success.code} response, kept in the database through")
                lines.append(f"crud.{op.crud.resource}. Change it as you need.")
            else:
                lines.append(
                    f"Return the {success.code} response. It returns example data until you "
                    "write this function."
                )
        errs = [r for r in op.errors if r.code and r.code >= 400]
        if errs:
            codes = ", ".join(r.status for r in errs)
            lines.append(f"Documented errors ({codes}): raise ApiError(status, body).")
        return "\n".join(f"    {line}" if line else "" for line in lines).lstrip()

    @staticmethod
    def _clean(schema: Any) -> Any:
        """A schema safe to embed in openapi_extra: no internal keys, no unresolved refs."""
        if isinstance(schema, dict):
            return {
                k: FastApiTarget._clean(v)
                for k, v in schema.items()
                if not k.startswith("__") and not k.startswith("x-apiforge") and k != "$ref"
            }
        if isinstance(schema, list):
            return [FastApiTarget._clean(v) for v in schema]
        return schema

    def _clean_headers(self, headers: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, h in headers.items():
            if isinstance(h, dict) and "$ref" not in h:
                out[str(name)] = self._clean(h)
        return out

    def _raw_body(self, body: dict[str, Any]) -> dict[str, Any]:
        content = {}
        for media, m in (body.get("content") or {}).items():
            schema = m.get("schema") if isinstance(m, dict) else None
            content[media] = {
                "schema": self._clean(schema or {"type": "string", "format": "binary"})
            }
        out: dict[str, Any] = {"content": content}
        if body.get("required"):
            out["required"] = True
        if body.get("description"):
            out["description"] = body["description"]
        return out

    # ── tests ─────────────────────────────────────────────────────────────────

    def _test_case(self, op: OperationDef, v: OpView) -> dict[str, Any]:
        path = op.path
        for p in op.params:
            if p.location == "path":
                path = path.replace("{" + p.wire + "}", quote(_wire_str(p.example), safe=""))
        query = {
            p.wire: _wire_value(p.example)
            for p in op.params
            if p.location == "query" and p.required
        }
        headers = {
            p.wire: _wire_str(p.example) for p in op.params if p.location == "header" and p.required
        }
        cookies = {
            p.wire: _wire_str(p.example) for p in op.params if p.location == "cookie" and p.required
        }
        case: dict[str, Any] = {
            "name": op.func,
            "method": op.method.upper(),
            "url": path,
            "query": py_literal(query) if query else None,
            "headers": py_literal(headers) if headers else None,
            "cookies": py_literal(cookies) if cookies else None,
            "json": None,
            "data": None,
            "files": None,
            "content": None,
            "secured": bool(op.security),
            "refused": bool(op.security) and v.require is None,
            "statuses": self._statuses(op),
            "check_type": None,
            "invalid": None,
        }
        body = op.body
        if body is not None:
            if body.kind == "json":
                case["json"] = py_literal(body.example)
            elif body.kind == "form":
                ex = body.example if isinstance(body.example, dict) else {}
                case["data"] = py_literal(
                    {k: _wire_str(v) for k, v in ex.items() if not isinstance(v, dict | list)}
                )
            elif body.kind == "multipart":
                data = {
                    f.wire: _wire_str(f.example) for f in body.form_fields if not f.type.is_file
                }
                files = [f.wire for f in body.form_fields if f.type.is_file]
                case["data"] = py_literal(data) if data else None
                case["files"] = (
                    "{"
                    + ", ".join(
                        f"{py_literal(w)}: ('example.txt', b'example', 'text/plain')" for w in files
                    )
                    + "}"
                    if files
                    else None
                )
            else:
                case["content"] = "b'example'"
        success = op.success
        if success is not None and success.type is not None and success.is_json:
            case["check_type"] = success.type.expr
        # A refused route answers 401 before it validates anything.
        case["invalid"] = None if case["refused"] else self._invalid_case(op, case)
        return case

    def _statuses(self, op: OperationDef) -> str | None:
        codes = []
        if (
            op.crud is not None
            and self.options.db
            and op.crud.action in ("read", "replace", "update", "delete")
        ):
            codes.append("404")
        for r in op.responses:
            if r.status == "default":
                return None
            if r.code is not None:
                codes.append(str(r.code))
            elif r.status.endswith("XX"):
                base = int(r.status[0]) * 100
                codes.extend(str(c) for c in range(base, base + 100))
        if not codes:
            return None
        return "{" + ", ".join(sorted(set(codes), key=int)) + "}"

    def _invalid_case(self, op: OperationDef, case: dict[str, Any]) -> dict[str, Any] | None:
        for p in op.params:
            if p.location == "path" and p.type.expr in ("int", "float", "UUID", "date", "datetime"):
                url = op.path
                for q in op.params:
                    if q.location == "path":
                        value = "not-a-valid-value" if q is p else _wire_str(q.example)
                        url = url.replace("{" + q.wire + "}", quote(value, safe=""))
                return {**case, "url": url, "why": f"{p.wire} must be {p.type.expr}"}
        for p in op.params:
            if p.location == "query" and p.required and p.type.expr in ("int", "float"):
                q = json.loads(json.dumps(dict(_parse(case["query"]))))
                q[p.wire] = "not-a-number"
                return {**case, "query": py_literal(q), "why": f"{p.wire} must be a number"}
        body = op.body
        if body is not None and body.kind == "json" and body.type is not None:
            required = (body.type.schema or {}).get("required") or []
            if required or self._model_has_required(body.type.expr):
                return {**case, "json": "{}", "why": "the body is missing required fields"}
        return None

    def _model_has_required(self, expr: str) -> bool:
        model = next((m for m in self.api.models if m.name == expr), None)
        if model is None or model.kind != "object":
            return False
        if any(f.required for f in model.fields):
            return True
        return any(self._model_has_required(b) for b in model.bases)

    # ── files ─────────────────────────────────────────────────────────────────

    def files(self) -> list[GeneratedFile]:
        api = self.api
        ctx: dict[str, Any] = {
            "api": api,
            "views": self.views,
            "options": self.options,
            "slug": self.slug,
            "version": __version__,
            "schemes": api.used_schemes,
            "has_security": bool(api.used_schemes),
            "has_bearer": any(s.kind in ("bearer", "oauth2", "openid") for s in api.used_schemes),
            "has_apikey": any(s.kind == "apikey" for s in api.used_schemes),
            "has_basic": any(s.kind == "basic" for s in api.used_schemes),
            "spec_has_health": any(
                op.path == "/health" and op.method == "get" for op in api.operations
            ),
            "resources": self.resources,
            "accepted": sorted(
                set(api.accepted)
                | {
                    (f"{op.method.upper()} {op.path}", part)
                    for op in api.operations
                    for part in op.accepted
                }
            ),
            "has_db": bool(self.resources),
            "py": py_literal,
            "kwargs": kwargs,
            "field_decl": field_decl,
            "py_version": pep440(api.version),
            "enum_imports": sorted(
                {
                    "StrEnum"
                    if m.enum_base == "str"
                    else "IntEnum"
                    if m.enum_base == "int"
                    else "Enum"
                    for m in api.models
                    if m.kind == "enum"
                }
            ),
        }
        out: list[GeneratedFile] = []

        def gen(path: str, template: str, owner: str = "generated", **extra: Any) -> None:
            content = render(self.env, template, **ctx, **extra)
            out.append(GeneratedFile(path, content, owner))  # type: ignore[arg-type]

        # generated
        gen("app/generated/__init__.py", "generated_init.py.j2")
        model_exprs = [f.type_expr for m in api.models for f in m.fields]
        model_exprs += [m.alias_type or "" for m in api.models] + [
            m.extra_type or "" for m in api.models
        ]
        model_exprs += [kwargs(f.constraints) for m in api.models for f in m.fields]
        gen(
            "app/generated/models.py",
            "models.py.j2",
            std_imports=import_lines(tokens(*model_exprs) - self.model_names, set()),
            uses_field=True,
        )
        gen("app/generated/errors.py", "errors.py.j2")
        gen("app/generated/principal.py", "principal.py.j2")
        gen("app/generated/security.py", "security.py.j2")
        gen("app/generated/middleware.py", "middleware.py.j2")
        gen("app/generated/wire.py", "wire.py.j2")
        mock_exprs = [v.mock_type for v in self.views] + [
            t for v in self.views for _, t, _ in v.error_mocks
        ]
        gen(
            "app/generated/mock.py",
            "mock.py.j2",
            imports=import_lines(tokens(*mock_exprs), self.model_names),
        )
        for tag in api.tags:
            views = [v for v in self.views if v.op.tag == tag.wire]
            exprs = [p for v in views for p in v.router_params] + [v.return_expr for v in views]
            exprs += [d for v in views for d in v.decorator]
            names = tokens(*exprs)
            fastapi_names = sorted(
                n
                for n in (
                    "Body",
                    "Cookie",
                    "File",
                    "Form",
                    "Header",
                    "Path",
                    "Query",
                    "Depends",
                    "Request",
                    "Response",
                    "Security",
                    "UploadFile",
                )
                if n in names
            )
            gen(
                f"app/generated/routers/{tag.module}.py",
                "router.py.j2",
                tag=tag,
                tag_views=views,
                imports=import_lines(
                    names - set(fastapi_names) | ({"Annotated"} if "Annotated" in names else set()),
                    self.model_names,
                ),
                fastapi_names=fastapi_names,
                uses_principal="Principal" in names,
            )
        gen("app/generated/routers/__init__.py", "routers_init.py.j2")
        renames = {v.route_path: (v.op.path, v.renames) for v in self.views if v.renames}
        gen("app/generated/app.py", "app.py.j2", spec_meta=self._app_meta(), renames=renames)
        out.append(
            GeneratedFile(
                "app/generated/openapi.json",
                json.dumps(self.spec, indent=2, ensure_ascii=False) + "\n",
                "generated",
            )
        )
        gen("tests/generated/__init__.py", "empty.py.j2")
        gen("tests/generated/conftest.py", "tests_conftest.py.j2")
        for tag in api.tags:
            views = [v for v in self.views if v.op.tag == tag.wire]
            check_types = [v.test["check_type"] for v in views if v.test["check_type"]]
            gen(
                f"tests/generated/test_{tag.module}.py",
                "test_module.py.j2",
                tag=tag,
                tag_views=views,
                imports=import_lines(tokens(*check_types), self.model_names),
            )
        gen("tests/generated/test_spec.py", "test_spec.py.j2")
        if self.resources:
            gen("app/generated/db_models.py", "db_models.py.j2")
            gen("app/generated/crud.py", "crud.py.j2")
            for res in self.resources:
                refused = any(o.test["refused"] for o in res.ops.values())
                if {"create", "read"} <= set(res.ops) and not refused:
                    gen(f"tests/generated/test_crud_{res.name}.py", "test_crud.py.j2", res=res)
            gen("app/db.py", "db.py.j2", owner="user")
            gen("alembic.ini", "alembic.ini.j2", owner="user")
            gen("migrations/env.py", "migrations_env.py.j2", owner="user")
            gen("migrations/script.py.mako", "script.py.mako.j2", owner="user")
            gen("migrations/versions/0001_initial.py", "migration_initial.py.j2", owner="user")
        out.append(GeneratedFile("tests/generated/fidelity.py", _fidelity_source(), "generated"))

        # user-owned (created once)
        gen("app/__init__.py", "empty.py.j2", owner="user")
        gen("app/main.py", "main.py.j2", owner="user")
        gen("app/config.py", "config.py.j2", owner="user")
        gen("app/auth.py", "auth.py.j2", owner="user")
        gen("app/handlers/__init__.py", "empty.py.j2", owner="user")
        for tag in api.tags:
            views = [v for v in self.views if v.op.tag == tag.wire]
            gen(
                f"{HANDLER_PREFIX}{tag.module}.py",
                "handlers.py.j2",
                owner="user",
                tag=tag,
                tag_views=views,
                tag_has_crud=any(v.crud_body for v in views),
            )
        gen("tests/__init__.py", "empty.py.j2", owner="user")
        gen("pyproject.toml", "pyproject.toml.j2", owner="user")
        gen("README.md", "README.md.j2", owner="user")
        gen(".env.example", "env.example.j2", owner="user")
        gen(".gitignore", "gitignore.j2", owner="user")
        gen("Makefile", "Makefile.j2", owner="user")
        if self.options.docker:
            gen("Dockerfile", "Dockerfile.j2", owner="user")
            gen(".dockerignore", "dockerignore.j2", owner="user")
            gen("compose.yaml", "compose.yaml.j2", owner="user")
        if self.options.ci:
            gen(".github/workflows/ci.yml", "ci.yml.j2", owner="user")
        return out

    def _resources(self) -> list[ResourceView]:
        from apiforge.crud import column_type

        enum_names = {m.name for m in self.api.models if m.kind == "enum"}
        by_name: dict[str, ResourceView] = {}
        for v in self.views:
            c = v.op.crud
            if c is None:
                continue
            res = by_name.get(c.resource)
            if res is None:
                model = next(m for m in self.api.models if m.name == c.model)
                fields = self._all_fields(model)
                columns: list[dict[str, Any]] = []
                used = Namer()
                for name, alias, type_expr, required in fields:
                    sa_type, is_json = column_type(type_expr, enum_names)
                    base = type_expr.replace(" | None", "").strip()
                    py_type = {
                        "String": "str",
                        "Integer": "int",
                        "Float": "float",
                        "Boolean": "bool",
                        "Date": "date",
                        "DateTime(timezone=True)": "datetime",
                        "Time": "time",
                        "Uuid": "UUID",
                    }.get(sa_type, "Any")
                    is_id = name == c.id_field
                    columns.append(
                        {
                            "attr": name,
                            "column": used.take(snake(alias, "field", frozenset())),
                            "sa_type": sa_type,
                            "py_type": py_type,
                            "is_json": is_json,
                            "is_enum": base in enum_names,
                            "nullable": not required and not is_id,
                            "is_id": is_id,
                        }
                    )
                columns.sort(key=lambda col: not col["is_id"])
                res = ResourceView(
                    name=c.resource,
                    row=pascal(c.resource) + "Row",
                    table=_plural(c.resource),
                    model=c.model,
                    id_field=c.id_field,
                    id_type=c.id_type,
                    id_alias=next((a for n, a, _, _ in fields if n == c.id_field), c.id_field),
                    columns=columns,
                )
                by_name[c.resource] = res
            res.ops.setdefault(c.action, v)
        return [by_name[k] for k in sorted(by_name)]

    def _all_fields(self, model: Any) -> list[tuple[str, str, str, bool]]:
        out: list[tuple[str, str, str, bool]] = []
        for base in model.bases:
            parent = next((m for m in self.api.models if m.name == base), None)
            if parent is not None:
                out.extend(self._all_fields(parent))
        seen = {f[0] for f in out}
        out = [f for f in out if f[0] not in {g.name for g in model.fields}]
        out.extend((f.name, f.alias, f.type_expr, f.required) for f in model.fields)
        _ = seen
        return out

    def handler_stub(self, view: OpView) -> str:
        """The source appended to a handler module for an operation added to the spec."""
        return render(self.env, "handler_stub.py.j2", v=view)

    def _app_meta(self) -> dict[str, str]:
        info = self.api.info
        meta: dict[str, str] = {
            "title": py_literal(self.api.title),
            "version": py_literal(self.api.version),
        }
        if self.api.description:
            meta["description"] = py_literal(self.api.description)
        if info.get("termsOfService"):
            meta["terms_of_service"] = py_literal(str(info["termsOfService"]))
        if isinstance(info.get("contact"), dict):
            meta["contact"] = py_literal(info["contact"])
        if isinstance(info.get("license"), dict):
            meta["license_info"] = py_literal(info["license"])
        if self.api.servers:
            meta["servers"] = py_literal(self.api.servers)
        tags = [
            {
                "name": t.get("name"),
                **({"description": t["description"]} if t.get("description") else {}),
            }
            for t in self.spec.get("tags") or []
            if isinstance(t, dict) and t.get("name")
        ]
        if tags:
            meta["openapi_tags"] = py_literal(tags)
        return meta


def field_decl(f: Any) -> str:
    """One model attribute: ``name: Type = Field(...)``, with the default first."""
    kw: dict[str, str] = {}
    if not f.required:
        kw["default"] = f.default or "None"
    if f.alias != f.name:
        kw["alias"] = py_literal(f.alias)
    if f.description:
        kw["description"] = py_literal(f.description)
    if f.deprecated:
        kw["deprecated"] = "True"
    if f.examples:
        kw["examples"] = py_literal(f.examples)
    kw.update(f.constraints)
    if not kw:
        return f"{f.name}: {f.type_expr}"
    if list(kw) == ["default"]:
        return f"{f.name}: {f.type_expr} = {kw['default']}"
    ordered = (["default"] if "default" in kw else []) + sorted(k for k in kw if k != "default")
    return f"{f.name}: {f.type_expr} = Field({', '.join(f'{k}={kw[k]}' for k in ordered)})"


def pep440(version: str) -> str:
    return version if re.fullmatch(r"\d+(\.\d+){0,3}", version) else "0.1.0"


def _plural(name: str) -> str:
    if name.endswith("y") and not name.endswith(("ay", "ey", "oy", "uy")):
        return name[:-1] + "ies"
    if name.endswith(("s", "x", "z", "ch", "sh")):
        return name + "es"
    return name + "s"


def _wire_str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value)
    return str(value)


def _wire_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_wire_str(v) for v in value]
    return _wire_str(value)


def _parse(literal: str | None) -> dict[str, Any]:
    if not literal:
        return {}
    import ast

    value = ast.literal_eval(literal)
    return value if isinstance(value, dict) else {}


def _fidelity_source() -> str:
    from apiforge import fidelity

    source = Path(fidelity.__file__).read_text()
    header = (
        "# Generated by APIForge: a copy of apiforge/fidelity.py, so this project's own tests\n"
        "# check that the app still serves the API its spec describes. Do not edit.\n"
    )
    return header + source
