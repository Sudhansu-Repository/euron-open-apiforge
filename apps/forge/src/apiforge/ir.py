"""The intermediate representation: one normalized description of the API.

Everything after ``normalize`` reads only these dataclasses (never the raw spec), so the
FastAPI target, the example builder, the tests generator and the lint report agree on one
interpretation. Names here are already safe Python identifiers; ``wire`` names are what the
HTTP API uses. Text fields are raw (unescaped) and are escaped only by the template filters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Location = Literal["path", "query", "header", "cookie"]
BodyKind = Literal["json", "form", "multipart", "binary", "text"]
SchemeKind = Literal["bearer", "basic", "apikey", "oauth2", "openid"]


@dataclass
class FieldDef:
    name: str  # Python attribute
    alias: str  # JSON property name
    type_expr: str  # annotation, e.g. "list[Pet] | None"
    required: bool
    default: str | None = None  # Python literal, when not required
    constraints: dict[str, str] = field(default_factory=dict)  # Field() keyword -> literal
    description: str | None = None
    read_only: bool = False
    write_only: bool = False
    deprecated: bool = False
    examples: list[Any] = field(default_factory=list)


@dataclass
class ModelDef:
    """A generated class: a Pydantic model, an Enum, or a RootModel alias."""

    name: str
    kind: Literal["object", "enum", "alias"]
    pointer: str
    description: str | None = None
    fields: list[FieldDef] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)  # other ModelDefs (allOf)
    extra: Literal["ignore", "allow", "forbid"] = "ignore"
    extra_type: str | None = None  # additionalProperties schema type, when typed
    enum_base: Literal["str", "int", "float"] = "str"
    enum_members: list[tuple[str, str]] = field(default_factory=list)  # (NAME, literal)
    alias_type: str | None = None  # for kind == "alias"
    depends_on: set[str] = field(default_factory=set)
    schema: dict[str, Any] = field(default_factory=dict)  # resolved JSON schema, for examples


@dataclass
class TypeInfo:
    """A schema compiled to an annotation plus what it needs."""

    expr: str
    schema: dict[str, Any]  # resolved schema (refs followed), for examples and tests
    constraints: dict[str, str] = field(default_factory=dict)
    nullable: bool = False
    is_file: bool = False
    is_array: bool = False


@dataclass
class ParamDef:
    name: str  # Python argument
    wire: str  # name on the wire
    location: Location
    type: TypeInfo
    required: bool
    default: str | None = None
    description: str | None = None
    deprecated: bool = False
    example: Any = None
    has_example: bool = False
    approximate: bool = False  # received differently than the spec says (reported)


@dataclass
class BodyDef:
    kind: BodyKind
    media_type: str
    type: TypeInfo | None  # json and form: the model; binary and text: None
    required: bool
    description: str | None = None
    form_fields: list[ParamDef] = field(default_factory=list)  # multipart parts
    raw: dict[str, Any] = field(default_factory=dict)  # the requestBody object, for docs
    example: Any = None


@dataclass
class ResponseDef:
    status: str  # "200", "4XX", "default"
    description: str
    media_type: str | None
    type: TypeInfo | None
    raw: dict[str, Any] = field(default_factory=dict)  # the response object (headers, links)
    example: Any = None

    @property
    def code(self) -> int | None:
        return int(self.status) if self.status.isdigit() else None

    @property
    def is_json(self) -> bool:
        return self.media_type is not None and _is_json(self.media_type)


@dataclass
class SecurityUse:
    scheme: str  # wire name in components.securitySchemes
    scopes: list[str] = field(default_factory=list)


@dataclass
class SecuritySchemeDef:
    wire: str
    name: str  # Python identifier
    kind: SchemeKind
    description: str | None = None
    location: Literal["header", "query", "cookie"] | None = None  # apikey
    param_name: str | None = None  # apikey
    bearer_format: str | None = None
    flows: dict[str, Any] = field(default_factory=dict)  # oauth2
    openid_url: str | None = None


@dataclass
class CrudInfo:
    """A collection resource that ``--db`` implements: /things and /things/{id}."""

    resource: str  # snake name, e.g. "pet"
    model: str  # response model (component) name
    create_model: str | None
    id_param: str  # wire name of the id path parameter
    id_field: str  # model attribute holding the id
    id_type: str  # "int" or "str"
    action: Literal["list", "create", "read", "replace", "update", "delete"]


@dataclass
class OperationDef:
    operation_id: str  # wire
    func: str  # Python function name, unique across the API
    method: str  # lower case
    path: str  # wire path
    tag: str  # wire tag (first tag, or "default")
    module: str  # Python module for the tag
    summary: str | None
    description: str | None
    deprecated: bool
    params: list[ParamDef]
    body: BodyDef | None
    responses: list[ResponseDef]
    security: list[list[SecurityUse]] | None  # None: no requirement; []: explicitly open
    pointer: str
    crud: CrudInfo | None = None
    # Differences from the spec APIForge reported and accepted, as fidelity message parts.
    accepted: list[str] = field(default_factory=list)

    @property
    def success(self) -> ResponseDef | None:
        for r in self.responses:
            if r.code is not None and 200 <= r.code < 300:
                return r
        for r in self.responses:
            if r.status == "2XX":
                return r
        return None

    @property
    def errors(self) -> list[ResponseDef]:
        primary = self.success
        return [r for r in self.responses if r is not primary]

    @property
    def secured(self) -> bool:
        return bool(self.security)


@dataclass
class TagDef:
    wire: str
    module: str
    description: str | None = None


@dataclass
class ApiDef:
    title: str
    version: str
    description: str | None
    openapi: str  # the input's version, "3.0.3" or "3.1.0"
    info: dict[str, Any]
    servers: list[dict[str, Any]]
    tags: list[TagDef]
    operations: list[OperationDef]
    models: list[ModelDef]
    schemes: list[SecuritySchemeDef]
    package: str = "app"
    # (operation key or "*", message part): reported differences the fidelity test accepts.
    accepted: list[tuple[str, str]] = field(default_factory=list)

    def tag_ops(self, tag: TagDef) -> list[OperationDef]:
        return [op for op in self.operations if op.tag == tag.wire]

    @property
    def used_schemes(self) -> list[SecuritySchemeDef]:
        used = {u.scheme for op in self.operations for alt in (op.security or []) for u in alt}
        return [s for s in self.schemes if s.wire in used]

    @property
    def crud_resources(self) -> list[str]:
        return sorted({op.crud.resource for op in self.operations if op.crud})


def _is_json(media_type: str) -> bool:
    base = media_type.split(";")[0].strip().lower()
    return base == "application/json" or base.endswith("+json")
