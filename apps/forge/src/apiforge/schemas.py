"""JSON Schema (OpenAPI 3.0 and 3.1 dialects) to Pydantic v2 types and models.

Rules, in the order a reader of the generated code will meet them:

- A schema under ``#/components/schemas`` becomes a named class: an ``Enum`` for string or
  integer enums, a model for objects (``allOf`` members that are objects become base
  classes), or a module-level alias for everything else (arrays, unions, primitives).
- Inline objects get a name from where they appear (``PetOwner`` for ``Pet.owner``).
- ``nullable: true`` (3.0) and ``type: [..., "null"]`` (3.1) become ``T | None``.
- ``oneOf``/``anyOf`` become unions; with a ``discriminator`` whose variants are object
  components, a discriminated union, and each variant's discriminator field is narrowed to
  a ``Literal`` of its value(s).
- Constraints become ``Field`` arguments (``min_length``, ``pattern``, ``ge``, ...); on
  array items and dict values they are nested with ``Annotated``.
- A model whose properties (directly or through referenced models) are ``readOnly`` or
  ``writeOnly`` gets an ``<Name>Input`` variant for request bodies: read-only properties are
  left out of input, write-only properties out of output.
- Anything without a faithful Pydantic equivalent (``not``, ``if``/``then``,
  ``patternProperties``, ``prefixItems``...) is approximated and reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from apiforge.ir import FieldDef, ModelDef, TypeInfo
from apiforge.loader import Bundle
from apiforge.naming import MODEL_RESERVED, Namer, constant, pascal, py_literal, snake
from apiforge.report import Report

Context = Literal["response", "request"]

# Formats Pydantic validates and documents itself.
NATIVE_FORMATS = {
    "date-time": "datetime",
    "date": "date",
    "time": "time",
    "uuid": "UUID",
    "email": "EmailStr",
}
UNSUPPORTED_KEYWORDS = {
    "not": "is not enforced",
    "if": "(if/then/else) is not enforced",
    "patternProperties": "is not enforced; extra properties are accepted as-is",
    "dependentSchemas": "is not enforced",
    "dependentRequired": "is not enforced",
    "dependencies": "is not enforced",
    "unevaluatedProperties": "is not enforced",
    "contains": "is not enforced",
    "propertyNames": "is not enforced",
}


@dataclass
class _Key:
    file: str
    pointer: str
    context: Context

    def __hash__(self) -> int:
        return hash((self.file, self.pointer, self.context))


@dataclass
class _DiscriminatorUse:
    prop: str  # wire property name
    values: set[str] = field(default_factory=set)


class SchemaCompiler:
    """Compiles schemas on demand; ``models`` collects every class to generate."""

    def __init__(self, bundle: Bundle, report: Report, version: str) -> None:
        self.bundle = bundle
        self.report = report
        self.v31 = version.startswith("3.1")
        self.models: dict[str, ModelDef] = {}
        self._names = Namer({"ApiModel"})
        self._by_key: dict[_Key, str] = {}
        self._in_progress: set[_Key] = set()
        self._differs_memo: dict[tuple[str, str], bool] = {}
        self._discriminators: dict[str, _DiscriminatorUse] = {}  # model name -> use

    # ── public ────────────────────────────────────────────────────────────────

    def type_of(
        self,
        schema: Any,
        *,
        file: str,
        pointer: str,
        hint: str,
        context: Context = "response",
    ) -> TypeInfo:
        """The annotation for ``schema`` (constraints returned separately for the caller)."""
        if not isinstance(schema, dict):
            return TypeInfo("Any", {})
        if "$ref" in schema:
            return self._ref(schema, file=file, pointer=pointer, hint=hint, context=context)
        return self._inline(schema, file=file, pointer=pointer, hint=hint, context=context)

    def component(self, name: str) -> str:
        """Compile ``#/components/schemas/<name>`` (response shape); returns the class name."""
        ptr = "/components/schemas/" + name.replace("~", "~0").replace("/", "~1")
        info = self.type_of({"$ref": "#" + ptr}, file=self.bundle.root_name, pointer=ptr, hint=name)
        return info.expr

    def finish(self) -> list[ModelDef]:
        """Apply discriminator narrowing; return models in a stable, dependency-friendly order."""
        for model_name, use in self._discriminators.items():
            model = self.models.get(model_name)
            if model is None:
                continue
            literal = "Literal[" + ", ".join(py_literal(v) for v in sorted(use.values)) + "]"
            own = next((f for f in model.fields if f.alias == use.prop), None)
            if own is not None:
                own.type_expr = literal
                own.required = True
                own.default = None
                continue
            inherited = self._inherited_field(model, use.prop)
            model.fields.append(
                FieldDef(
                    name=inherited.name if inherited else snake(use.prop, "kind", MODEL_RESERVED),
                    alias=use.prop,
                    type_expr=literal,
                    required=True,
                    description=inherited.description if inherited else None,
                )
            )
        return self._ordered()

    # ── references ────────────────────────────────────────────────────────────

    def _ref(
        self, schema: dict[str, Any], *, file: str, pointer: str, hint: str, context: Context
    ) -> TypeInfo:
        ref = schema["$ref"]
        target_file, target_ptr, target = self.bundle.resolve(ref, file)
        nullable = bool(schema.get("nullable")) and not self.v31
        if self.v31 and isinstance(schema.get("type"), list) and "null" in schema["type"]:
            nullable = True
        if not isinstance(target, dict):
            self.report.warning(
                "schema_not_object", f"$ref {ref!r} does not point to a schema.", pointer
            )
            return TypeInfo("Any", {})
        if "$ref" in target and len(target) == 1:  # a chain of refs: follow it
            info = self._ref(
                target, file=target_file, pointer=target_ptr, hint=hint, context=context
            )
        elif self._is_component(target_ptr) and self._named_kind(target) is not None:
            name = self._named(target_file, target_ptr, target, context)
            info = TypeInfo(name, self._resolved(target, target_file))
        else:
            info = self._inline(
                target, file=target_file, pointer=target_ptr, hint=hint, context=context
            )
        if nullable and not info.nullable:
            info = TypeInfo(
                f"{info.expr} | None", info.schema, info.constraints, True, info.is_file
            )
        return info

    @staticmethod
    def _is_component(ptr: str) -> bool:
        parts = ptr.split("/")
        return len(parts) == 4 and parts[1] == "components" and parts[2] == "schemas"

    def _named_kind(self, schema: dict[str, Any]) -> str | None:
        if "enum" in schema and self._enum_base(schema) is not None:
            return "enum"
        if self._is_object(schema):
            return "object"
        return "alias"

    def _named(self, file: str, ptr: str, schema: dict[str, Any], context: Context) -> str:
        if context == "request" and not self._differs(file, ptr):
            context = "response"
        key = _Key(file, ptr, context)
        if key in self._by_key:
            return self._by_key[key]
        component = ptr.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
        base = pascal(component)
        name = self._names.take(base + ("Input" if context == "request" else ""))
        self._by_key[key] = name
        self._in_progress.add(key)
        try:
            kind = self._named_kind(schema)
            if kind == "enum":
                self.models[name] = self._enum_model(name, schema, ptr)
            elif kind == "object":
                self.models[name] = self._object_model(name, schema, file, ptr, context)
            else:
                info = self._inline(schema, file=file, pointer=ptr, hint=base, context=context)
                expr = info.expr
                if info.constraints:
                    expr = f"Annotated[{expr}, Field({_kwargs(info.constraints)})]"
                self.models[name] = ModelDef(
                    name=name,
                    kind="alias",
                    pointer=ptr,
                    description=schema.get("description"),
                    alias_type=expr,
                    depends_on=self._deps(expr),
                    schema=self._resolved(schema, file),
                )
        finally:
            self._in_progress.discard(key)
        return name

    # ── read-only and write-only variants ─────────────────────────────────────

    def _differs(self, file: str, ptr: str) -> bool:
        """True when the component's shape is different in requests and responses."""
        key = (file, ptr)
        if key in self._differs_memo:
            return self._differs_memo[key]
        self._differs_memo[key] = False  # cycle guard
        _, _, schema = self.bundle.resolve("#" + ptr, file)
        result = self._schema_differs(schema, file, depth=0)
        self._differs_memo[key] = result
        return result

    def _schema_differs(self, schema: Any, file: str, depth: int) -> bool:
        if not isinstance(schema, dict) or depth > 32:
            return False
        if "$ref" in schema:
            tfile, tptr, target = self.bundle.resolve(schema["$ref"], file)
            if self._is_component(tptr):
                return self._differs(tfile, tptr)
            return self._schema_differs(target, tfile, depth + 1)
        for prop in (schema.get("properties") or {}).values():
            if isinstance(prop, dict) and (prop.get("readOnly") or prop.get("writeOnly")):
                return True
            if self._schema_differs(prop, file, depth + 1):
                return True
        children = [schema.get("items"), schema.get("additionalProperties")]
        for key in ("allOf", "oneOf", "anyOf"):
            children.extend(schema.get(key) or [])
        return any(self._schema_differs(c, file, depth + 1) for c in children)

    # ── classes ───────────────────────────────────────────────────────────────

    def _enum_base(self, schema: dict[str, Any]) -> Literal["str", "int", "float"] | None:
        values = [v for v in schema.get("enum", []) if v is not None]
        if not values:
            return None
        if all(isinstance(v, str) for v in values):
            return "str"
        if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            return "int"
        if all(isinstance(v, int | float) and not isinstance(v, bool) for v in values):
            return "float"
        return None

    def _enum_model(self, name: str, schema: dict[str, Any], ptr: str) -> ModelDef:
        base = self._enum_base(schema) or "str"
        members: list[tuple[str, str]] = []
        names = Namer({"name", "value"})
        for value in schema["enum"]:
            if value is None:
                continue
            label = constant(str(value), "VALUE")
            if base != "str":
                label = constant(f"v_{value}".replace("-", "minus_").replace(".", "_"), "V")
            members.append((names.take(label), py_literal(value)))
        return ModelDef(
            name=name,
            kind="enum",
            pointer=ptr,
            description=schema.get("description"),
            enum_base=base,
            enum_members=members,
            schema=dict(schema),
        )

    def _is_object(self, schema: dict[str, Any]) -> bool:
        """An object with declared properties (directly or through allOf) becomes a model;
        a free-form object (no properties) becomes ``dict``."""
        if schema.get("properties"):
            return True
        if "allOf" in schema and not any(k in schema for k in ("oneOf", "anyOf")):
            members = schema["allOf"]
            return any(
                isinstance(m, dict) and ("$ref" in m or m.get("properties")) for m in members
            )
        return False

    def _object_model(
        self, name: str, schema: dict[str, Any], file: str, ptr: str, context: Context
    ) -> ModelDef:
        model = ModelDef(
            name=name,
            kind="object",
            pointer=ptr,
            description=schema.get("description"),
            schema=self._resolved(schema, file),
        )
        self._check_unsupported(schema, ptr)
        props: dict[str, Any] = {}
        required: set[str] = set(schema.get("required") or [])
        for i, member in enumerate(schema.get("allOf") or []):
            mptr = f"{ptr}/allOf/{i}"
            if not isinstance(member, dict):
                continue
            if "$ref" in member:
                tfile, tptr, target = self.bundle.resolve(member["$ref"], file)
                if self._is_component(tptr) and self._named_kind(target) == "object":
                    base = self._named(tfile, tptr, target, context)
                    model.bases.append(base)
                    model.depends_on.add(base)
                    continue
                member = target
            if member.get("properties") or member.get("required"):
                self._check_unsupported(member, mptr)
                props.update(member.get("properties") or {})
                required |= set(member.get("required") or [])
            elif member.get("allOf") or member.get("oneOf") or member.get("anyOf"):
                self.report.warning(
                    "allof_nested_composition",
                    "A nested composition inside allOf is flattened only one level; its "
                    "alternatives are not enforced.",
                    mptr,
                )
        props.update(schema.get("properties") or {})
        fields = Namer({"model_config", "model_fields"})
        for prop, sub in props.items():
            if not isinstance(sub, dict):
                continue
            read_only = bool(sub.get("readOnly"))
            write_only = bool(sub.get("writeOnly"))
            if context == "request" and read_only:
                continue
            if context == "response" and write_only:
                continue
            sub_ptr = f"{ptr}/properties/{_esc(prop)}"
            info = self.type_of(
                sub, file=file, pointer=sub_ptr, hint=name + pascal(prop, "Field"), context=context
            )
            is_required = prop in required
            default = None
            if not is_required:
                if "default" in sub and sub["default"] is not None:
                    default = py_literal(sub["default"])
                else:
                    default = "None"
            type_expr = info.expr
            if not is_required and default == "None" and not info.nullable:
                type_expr = f"{type_expr} | None"
            model.fields.append(
                FieldDef(
                    name=fields.take(snake(prop, "field", MODEL_RESERVED)),
                    alias=prop,
                    type_expr=type_expr,
                    required=is_required,
                    default=default,
                    constraints=info.constraints,
                    description=sub.get("description"),
                    read_only=read_only,
                    write_only=write_only,
                    deprecated=bool(sub.get("deprecated")),
                    examples=_examples_of(sub),
                )
            )
            model.depends_on |= self._deps(type_expr)
        extra = schema.get("additionalProperties")
        if extra is True or (isinstance(extra, dict) and not extra):
            model.extra = "allow"
        elif extra is False:
            model.extra = "forbid"
        elif isinstance(extra, dict):
            model.extra = "allow"
            info = self.type_of(
                extra,
                file=file,
                pointer=f"{ptr}/additionalProperties",
                hint=name + "Value",
                context=context,
            )
            model.extra_type = info.expr
            model.depends_on |= self._deps(info.expr)
        for key in ("minProperties", "maxProperties"):
            if key in schema:
                self.report.warning(
                    "object_size_not_enforced", f"{key} on an object is not enforced.", ptr
                )
        return model

    def _inherited_field(self, model: ModelDef, alias: str) -> FieldDef | None:
        for base in model.bases:
            parent = self.models.get(base)
            if parent is None:
                continue
            for f in parent.fields:
                if f.alias == alias:
                    return f
            found = self._inherited_field(parent, alias)
            if found:
                return found
        return None

    # ── inline schemas ────────────────────────────────────────────────────────

    def _inline(
        self, schema: dict[str, Any], *, file: str, pointer: str, hint: str, context: Context
    ) -> TypeInfo:
        self._check_unsupported(schema, pointer)
        resolved = self._resolved(schema, file)
        types = schema.get("type")
        type_list: list[str] = (
            [t for t in types if isinstance(t, str)]
            if isinstance(types, list)
            else [types]
            if isinstance(types, str)
            else []
        )
        nullable = bool(schema.get("nullable")) or "null" in type_list
        non_null = [t for t in type_list if t != "null"]
        constraints: dict[str, str] = {}

        if "const" in schema:
            return self._wrap(f"Literal[{py_literal(schema['const'])}]", resolved, {}, nullable)

        if "enum" in schema:
            values = [v for v in schema["enum"] if v is not None]
            if None in schema["enum"]:
                nullable = True
            if values and all(isinstance(v, str | int | float | bool) for v in values):
                expr = "Literal[" + ", ".join(py_literal(v) for v in values) + "]"
                return self._wrap(expr, resolved, {}, nullable)

        for comb in ("oneOf", "anyOf"):
            if comb in schema:
                return self._union(
                    schema,
                    comb,
                    file=file,
                    pointer=pointer,
                    hint=hint,
                    context=context,
                    nullable=nullable,
                )

        if "allOf" in schema:
            members = [m for m in schema["allOf"] if isinstance(m, dict)]
            significant = [
                m
                for m in members
                if "$ref" in m
                or m.get("properties")
                or m.get("type")
                or m.get("allOf")
                or m.get("oneOf")
                or m.get("anyOf")
                or m.get("items")
            ]
            if len(significant) == 1 and not schema.get("properties"):
                only = significant[0]
                info = self.type_of(
                    only, file=file, pointer=f"{pointer}/allOf/0", hint=hint, context=context
                )
                extra_nullable = nullable or any(m.get("nullable") for m in members)
                return self._wrap(
                    info.expr,
                    info.schema,
                    info.constraints,
                    extra_nullable and not info.nullable,
                    info.is_file,
                )
            if self._is_object(schema):
                name = self._inline_model(schema, file, pointer, hint, context)
                return self._wrap(name, resolved, {}, nullable)

        if len(non_null) > 1:
            parts = [
                self._inline(
                    {**schema, "type": t, "nullable": False},
                    file=file,
                    pointer=pointer,
                    hint=hint + pascal(t),
                    context=context,
                ).expr
                for t in non_null
            ]
            return self._wrap(" | ".join(dict.fromkeys(parts)), resolved, {}, nullable)

        t = non_null[0] if non_null else None
        if t is None and schema.get("properties"):
            t = "object"
        if t is None and "items" in schema:
            t = "array"

        if t == "object":
            props = schema.get("properties")
            extra = schema.get("additionalProperties")
            if not props and isinstance(extra, dict) and extra:
                value = self.type_of(
                    extra,
                    file=file,
                    pointer=f"{pointer}/additionalProperties",
                    hint=hint + "Value",
                    context=context,
                )
                return self._wrap(f"dict[str, {_annotated(value)}]", resolved, {}, nullable)
            if not props and "allOf" not in schema:
                return self._wrap("dict[str, Any]", resolved, {}, nullable)
            name = self._inline_model(schema, file, pointer, hint, context)
            return self._wrap(name, resolved, {}, nullable)

        if t == "array":
            items = schema.get("items")
            if "prefixItems" in schema:
                self.report.warning(
                    "tuple_not_enforced",
                    "prefixItems (a tuple) is accepted as a list of any items.",
                    pointer,
                )
            item = (
                self.type_of(
                    items,
                    file=file,
                    pointer=f"{pointer}/items",
                    hint=hint + "Item",
                    context=context,
                )
                if isinstance(items, dict)
                else TypeInfo("Any", {})
            )
            if "minItems" in schema:
                constraints["min_length"] = py_literal(int(schema["minItems"]))
            if "maxItems" in schema:
                constraints["max_length"] = py_literal(int(schema["maxItems"]))
            container = "list"
            if schema.get("uniqueItems"):
                scalar = item.expr in {"str", "int", "float", "bool", "UUID", "date", "datetime"}
                if scalar and not item.constraints:
                    container = "set"
                else:
                    self.report.warning(
                        "unique_items_not_enforced",
                        "uniqueItems is enforced only for arrays of plain scalars.",
                        pointer,
                    )
            info = self._wrap(f"{container}[{_annotated(item)}]", resolved, constraints, nullable)
            info.is_array = True
            return info

        if t == "string":
            fmt = schema.get("format")
            expr = "str"
            if fmt in NATIVE_FORMATS:
                expr = NATIVE_FORMATS[fmt]
            elif fmt == "binary":
                return self._wrap("bytes", resolved, {}, nullable, is_file=True)
            elif fmt:
                constraints["json_schema_extra"] = py_literal({"format": fmt})
            if expr == "str":
                if "minLength" in schema:
                    constraints["min_length"] = py_literal(int(schema["minLength"]))
                if "maxLength" in schema:
                    constraints["max_length"] = py_literal(int(schema["maxLength"]))
                if "pattern" in schema:
                    constraints["pattern"] = py_literal(str(schema["pattern"]))
            return self._wrap(expr, resolved, constraints, nullable)

        if t in ("integer", "number"):
            expr = "int" if t == "integer" else "float"
            self._numeric(schema, constraints)
            if (
                schema.get("format")
                and t == "number"
                and schema["format"] not in ("float", "double")
            ):
                constraints["json_schema_extra"] = py_literal({"format": schema["format"]})
            return self._wrap(expr, resolved, constraints, nullable)

        if t == "boolean":
            return self._wrap("bool", resolved, {}, nullable)
        if t == "null":
            return TypeInfo("None", resolved, nullable=True)
        return self._wrap("Any", resolved, {}, False)

    def _numeric(self, schema: dict[str, Any], out: dict[str, str]) -> None:
        def num(v: Any) -> str:
            return py_literal(v if not isinstance(v, bool) else int(v))

        if "minimum" in schema:
            key = "gt" if schema.get("exclusiveMinimum") is True else "ge"
            out[key] = num(schema["minimum"])
        if "maximum" in schema:
            key = "lt" if schema.get("exclusiveMaximum") is True else "le"
            out[key] = num(schema["maximum"])
        for key, kw in (("exclusiveMinimum", "gt"), ("exclusiveMaximum", "lt")):
            value = schema.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                out[kw] = num(value)
        if "multipleOf" in schema:
            out["multiple_of"] = num(schema["multipleOf"])

    def _union(
        self,
        schema: dict[str, Any],
        comb: str,
        *,
        file: str,
        pointer: str,
        hint: str,
        context: Context,
        nullable: bool,
    ) -> TypeInfo:
        options = [o for o in schema[comb] if isinstance(o, dict)]
        non_null = [o for o in options if o.get("type") != "null"]
        if len(non_null) < len(options):
            nullable = True
        resolved = self._resolved(schema, file)
        if len(non_null) == 1:
            info = self.type_of(
                non_null[0], file=file, pointer=f"{pointer}/{comb}/0", hint=hint, context=context
            )
            return self._wrap(
                info.expr,
                info.schema,
                info.constraints,
                nullable and not info.nullable,
                info.is_file,
            )
        disc = schema.get("discriminator")
        parts: list[str] = []
        variants: list[tuple[str, str]] = []  # (class name, component name)
        for i, option in enumerate(non_null):
            info = self.type_of(
                option,
                file=file,
                pointer=f"{pointer}/{comb}/{i}",
                hint=f"{hint}Option{i + 1}",
                context=context,
            )
            parts.append(_annotated(info))
            if "$ref" in option:
                comp = option["$ref"].rsplit("/", 1)[-1]
                variants.append((info.expr, comp))
        expr = " | ".join(dict.fromkeys(parts))
        if isinstance(disc, dict) and disc.get("propertyName"):
            prop = str(disc["propertyName"])
            if len(variants) == len(non_null) and all(
                self.models.get(cls) is not None and self.models[cls].kind == "object"
                for cls, _ in variants
            ):
                mapping = disc.get("mapping") or {}
                values_for: dict[str, set[str]] = {cls: set() for cls, _ in variants}
                for value, target in mapping.items():
                    comp = str(target).rsplit("/", 1)[-1]
                    for cls, c in variants:
                        if c == comp:
                            values_for[cls].add(str(value))
                for cls, comp in variants:
                    if not values_for[cls]:
                        values_for[cls].add(comp)
                    use = self._discriminators.setdefault(cls, _DiscriminatorUse(prop))
                    use.values |= values_for[cls]
                attr = self._discriminator_attr(variants[0][0], prop)
                expr = f"Annotated[{expr}, Field(discriminator={py_literal(attr)})]"
            else:
                self.report.info(
                    "discriminator_ignored",
                    "The discriminator is used only when every alternative is an object "
                    "component; this union is validated by trying each alternative.",
                    pointer,
                )
        if comb == "anyOf" and len(parts) > 1 and not disc:
            self.report.info(
                "anyof_as_union",
                "anyOf is validated as 'one of these shapes': a value matching several is "
                "kept as the first that fits.",
                pointer,
            )
        return self._wrap(expr, resolved, {}, nullable)

    def _discriminator_attr(self, cls: str, prop: str) -> str:
        model = self.models.get(cls)
        if model is not None:
            for f in model.fields:
                if f.alias == prop:
                    return f.name
            inherited = self._inherited_field(model, prop)
            if inherited:
                return inherited.name
        return snake(prop, "kind", MODEL_RESERVED)

    def _inline_model(
        self, schema: dict[str, Any], file: str, pointer: str, hint: str, context: Context
    ) -> str:
        key = _Key(file, pointer, context)
        if key in self._by_key:
            return self._by_key[key]
        name = self._names.take(pascal(hint, "Model"))
        self._by_key[key] = name
        self.models[name] = self._object_model(name, schema, file, pointer, context)
        return name

    # ── helpers ───────────────────────────────────────────────────────────────

    def _wrap(
        self,
        expr: str,
        schema: dict[str, Any],
        constraints: dict[str, str],
        nullable: bool,
        is_file: bool = False,
    ) -> TypeInfo:
        if nullable and expr not in ("Any", "None"):
            expr = f"{expr} | None"
        return TypeInfo(expr, schema, constraints, nullable, is_file)

    def _resolved(self, schema: dict[str, Any], file: str) -> dict[str, Any]:
        """The schema with refs left as is but tagged with their file, for later expansion."""
        return {"__file__": file, **schema}

    def _check_unsupported(self, schema: dict[str, Any], pointer: str) -> None:
        for key, why in UNSUPPORTED_KEYWORDS.items():
            if key in schema:
                self.report.warning("keyword_not_enforced", f"{key} {why}.", pointer)
        if "then" in schema and "if" not in schema:
            self.report.warning("keyword_not_enforced", "then without if is ignored.", pointer)

    def _deps(self, expr: str) -> set[str]:
        import re

        return {tok for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr) if tok in self.models}

    def _ordered(self) -> list[ModelDef]:
        """Enums first, then classes in dependency order (cycles kept as written), then aliases."""
        enums = [m for m in self.models.values() if m.kind == "enum"]
        classes = [m for m in self.models.values() if m.kind == "object"]
        aliases = [m for m in self.models.values() if m.kind == "alias"]
        ordered: list[ModelDef] = []
        seen: set[str] = set()
        visiting: set[str] = set()

        def visit(m: ModelDef) -> None:
            if m.name in seen or m.name in visiting:
                return
            visiting.add(m.name)
            for dep in sorted(m.bases):
                parent = self.models.get(dep)
                if parent is not None and parent.kind == "object":
                    visit(parent)
            visiting.discard(m.name)
            seen.add(m.name)
            ordered.append(m)

        for m in sorted(classes, key=lambda x: x.name):
            visit(m)
        alias_order: list[ModelDef] = []
        done: set[str] = set()

        def visit_alias(m: ModelDef, stack: set[str]) -> None:
            if m.name in done or m.name in stack:
                return
            stack.add(m.name)
            for dep in sorted(m.depends_on):
                target = self.models.get(dep)
                if target is not None and target.kind == "alias":
                    visit_alias(target, stack)
            stack.discard(m.name)
            done.add(m.name)
            alias_order.append(m)

        for m in sorted(aliases, key=lambda x: x.name):
            visit_alias(m, set())
        return sorted(enums, key=lambda x: x.name) + ordered + alias_order


def _annotated(info: TypeInfo) -> str:
    """A nested annotation carrying its own constraints (array items, dict values)."""
    if not info.constraints:
        return info.expr
    return f"Annotated[{info.expr}, Field({_kwargs(info.constraints)})]"


def _kwargs(constraints: dict[str, str]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(constraints.items()))


def kwargs(constraints: dict[str, str]) -> str:
    return _kwargs(constraints)


def _examples_of(schema: dict[str, Any]) -> list[Any]:
    if "example" in schema:
        return [schema["example"]]
    ex = schema.get("examples")
    if isinstance(ex, list):
        return ex
    return []


def _esc(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")
