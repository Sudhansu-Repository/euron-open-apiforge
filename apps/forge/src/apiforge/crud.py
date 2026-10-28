"""Collection resources for ``--db``: which operations get a working database handler.

A collection resource is a pair of paths ``/things`` and ``/things/{id}`` whose operations
return one object component (``Thing``) or a list of it:

| Operation | Becomes |
| --- | --- |
| ``GET /things`` returning ``Thing[]`` | list (paging and equality filters, see below) |
| ``POST /things`` with a ``Thing`` body | create |
| ``GET /things/{id}`` | read (404 when missing) |
| ``PUT /things/{id}`` | replace |
| ``PATCH /things/{id}`` | update the fields that were sent |
| ``DELETE /things/{id}`` | delete |

A list reads ``limit``/``offset`` (or ``page``/``pageSize``) and filters by equality on query
parameters named like a field. The id is the model field named like the path parameter
(``petId`` -> ``id`` or ``pet_id``).
Operations that do not fit (a list wrapped in a page object, a nested path) keep their
example-data stubs and are listed in the report.
"""

from __future__ import annotations

import re

from apiforge.ir import ApiDef, CrudInfo, ModelDef, OperationDef
from apiforge.naming import snake, words
from apiforge.report import Report

PAGE_PARAMS = {"limit", "offset", "page", "page_size", "per_page", "size"}
ID_TYPES = {"int": "int", "str": "str", "UUID": "UUID"}


def detect(api: ApiDef, report: Report) -> None:
    models = {m.name: m for m in api.models}
    by_path: dict[str, list[OperationDef]] = {}
    for op in api.operations:
        by_path.setdefault(op.path.rstrip("/") or "/", []).append(op)
    for collection, ops in sorted(by_path.items()):
        item_paths = [p for p in by_path if re.fullmatch(re.escape(collection) + r"/\{[^}/]+\}", p)]
        if not item_paths or collection == "/":
            continue
        item_path = item_paths[0]
        item_ops = by_path[item_path]
        param = item_path.rsplit("{", 1)[1].rstrip("}")
        model_name = _resource_model(ops + item_ops, models)
        if model_name is None:
            report.info(
                "crud_no_model",
                f"{collection} and {item_path} do not share one object model; their handlers "
                "keep example data.",
                item_ops[0].pointer,
            )
            continue
        model = models[model_name]
        id_field = _id_field(model, param, models)
        if id_field is None:
            report.info(
                "crud_no_id",
                f"{model_name} has no field matching {{{param}}} (or 'id'); {collection} keeps "
                "example data.",
                item_ops[0].pointer,
            )
            continue
        id_name, id_type = id_field
        resource = snake(" ".join(words(model_name)), "item")
        create_model = None
        for op in ops + item_ops:
            action = _action(op, collection, item_path, model_name)
            if action in ("create", "replace") and not _covers(op, model, id_name, models):
                report.info(
                    "crud_body_incomplete",
                    f"{op.method.upper()} {op.path}: the request body does not provide every "
                    f"required field of {model_name}, so it cannot be stored as one; it keeps "
                    "example data.",
                    op.pointer,
                )
                continue
            if action is None:
                if op.method in ("get", "post", "put", "patch", "delete"):
                    report.info(
                        "crud_operation_skipped",
                        f"{op.method.upper()} {op.path} does not fit the {resource} resource; it "
                        "keeps example data.",
                        op.pointer,
                    )
                continue
            if action == "create" and op.body and op.body.type:
                create_model = op.body.type.expr
            op.crud = CrudInfo(
                resource=resource,
                model=model_name,
                create_model=op.body.type.expr if op.body and op.body.type else None,
                id_param=param,
                id_field=id_name,
                id_type=id_type,
                action=action,  # type: ignore[arg-type]
            )
        if create_model is None:
            # Without a create operation nothing could ever fill the table: keep the examples.
            touched = [
                op for op in ops + item_ops if op.crud is not None and op.crud.resource == resource
            ]
            for op in touched:
                op.crud = None
            if touched:
                report.info(
                    "crud_no_create",
                    f"The {resource} resource has no create operation that stores a whole "
                    f"{model_name}, so its operations keep example data.",
                    touched[0].pointer,
                )


def _resource_model(ops: list[OperationDef], models: dict[str, ModelDef]) -> str | None:
    counts: dict[str, int] = {}
    for op in ops:
        s = op.success
        if s is None or s.type is None:
            continue
        expr = s.type.expr
        name = expr[5:-1] if expr.startswith("list[") and expr.endswith("]") else expr
        model = models.get(name)
        if model is not None and model.kind == "object":
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None
    return max(sorted(counts), key=lambda n: counts[n])


def _all_fields(model: ModelDef, models: dict[str, ModelDef]) -> list[tuple[str, str, str, bool]]:
    out: list[tuple[str, str, str, bool]] = []
    for base in model.bases:
        parent = models.get(base)
        if parent is not None:
            out.extend(_all_fields(parent, models))
    out.extend((f.name, f.alias, f.type_expr, f.required) for f in model.fields)
    return out


def _id_field(model: ModelDef, param: str, models: dict[str, ModelDef]) -> tuple[str, str] | None:
    candidates = {snake(param), param, "id"}
    tail = words(param)
    if tail and tail[-1] == "id":
        candidates.add("id")
    for name, alias, type_expr, _ in _all_fields(model, models):
        if name in candidates or alias in candidates:
            base = type_expr.replace(" | None", "")
            if base in ID_TYPES:
                return name, ID_TYPES[base]
    return None


def _covers(op: OperationDef, model: ModelDef, id_name: str, models: dict[str, ModelDef]) -> bool:
    """True when the body carries every required field of the resource (the id aside)."""
    if op.body is None or op.body.type is None:
        return False
    body_name = op.body.type.expr.replace(" | None", "")
    if body_name in (model.name, model.name + "Input"):
        return True
    body = models.get(body_name)
    if body is None or body.kind != "object":
        return False
    have = {name for name, _, _, _ in _all_fields(body, models)}
    need = {
        name for name, _, _, required in _all_fields(model, models) if required and name != id_name
    }
    return need <= have


def _action(op: OperationDef, collection: str, item_path: str, model: str) -> str | None:
    s = op.success
    returns = s.type.expr if s and s.type else None
    path = op.path.rstrip("/")
    if path == collection:
        if op.method == "get" and returns == f"list[{model}]":
            return "list"
        if op.method == "post" and returns == model and op.body and op.body.kind == "json":
            return "create"
        return None
    if path == item_path:
        if op.method == "get" and returns == model:
            return "read"
        if op.method == "put" and returns == model and op.body and op.body.kind == "json":
            return "replace"
        if op.method == "patch" and returns == model and op.body and op.body.kind == "json":
            return "update"
        if op.method == "delete" and (returns is None or returns == model):
            return "delete"
    return None


def column_type(type_expr: str, enum_names: set[str]) -> tuple[str, bool]:
    """(SQLAlchemy type, is_json) for a model field annotation."""
    base = type_expr.replace(" | None", "").strip()
    simple = {
        "str": "String",
        "int": "Integer",
        "float": "Float",
        "bool": "Boolean",
        "date": "Date",
        "datetime": "DateTime(timezone=True)",
        "time": "Time",
        "UUID": "Uuid",
        "EmailStr": "String",
    }
    if base in simple:
        return simple[base], False
    if base in enum_names or base.startswith("Literal["):
        return "String", False
    return "JSON", True
