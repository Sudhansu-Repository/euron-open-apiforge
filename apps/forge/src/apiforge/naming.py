"""Names and literals: the only way text from a spec reaches generated code.

Every identifier is rebuilt from ASCII letters, digits and underscores (so a name can never
close a string, open a call or reach another statement), and every other piece of spec text
(descriptions, examples, patterns, defaults) is emitted as a Python literal with ``repr``,
inside a docstring with every quote and backslash escaped, or in a single-line comment. The
templates never place raw spec text anywhere else; ``tests/test_hostile.py`` checks that
with specs built to break out.
"""

from __future__ import annotations

import keyword
import re
import unicodedata
from typing import Any

# Names the generated modules use themselves; a spec field or parameter with one of these
# names gets a suffix instead of shadowing it.
RESERVED = frozenset(
    {
        "self",
        "cls",
        "request",
        "response",
        "handlers",
        "models",
        "mock",
        "security",
        "settings",
        "app",
        "router",
        "status",
        "body",
        "annotated",
        "field",
        "basemodel",
        "query",
        "path",
        "header",
        "cookie",
        "file",
        "form",
        "depends",
        "uploadfile",
        "json",
        "typing",
        "datetime",
        "date",
        "uuid",
        "decimal",
        "any",
        "literal",
        "enum",
        "rootmodel",
        "configdict",
        "session",
        "db",
        "credentials",
        "principal",
    }
)
_PY_RESERVED = (
    frozenset(keyword.kwlist)
    | frozenset(keyword.softkwlist)
    | {
        "None",
        "True",
        "False",
        "print",
        "type",
        "id",
        "list",
        "dict",
        "set",
        "str",
        "int",
        "float",
        "bool",
        "bytes",
        "object",
        "format",
        "input",
        "filter",
        "map",
        "max",
        "min",
        "next",
        "range",
        "hash",
        "iter",
        "len",
        "open",
        "vars",
        "dir",
        "help",
        "all",
    }
)

_CAMEL_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_2 = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD = re.compile(r"[^0-9a-zA-Z]+")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def words(text: str) -> list[str]:
    """Split ``getPetById``, ``pet-id``, ``PET_ID`` and ``pet id`` into lower-case words."""
    text = _CAMEL_2.sub(r"\1 \2", _CAMEL_1.sub(r"\1 \2", _ascii(text)))
    return [w.lower() for w in _NON_WORD.split(text) if w]


# Model attributes: Python keywords plus what BaseModel itself defines. A field may shadow
# a builtin (``id``, ``type``); it is an attribute, not a variable.
MODEL_RESERVED = frozenset(
    {
        "model_config",
        "model_fields",
        "model_computed_fields",
        "schema",
        "json",
        "dict",
        "copy",
        "validate",
        "construct",
        "fields",
        "parse_obj",
        "parse_raw",
        "update_forward_refs",
    }
)


def snake(text: str, fallback: str = "value", reserved: frozenset[str] | None = None) -> str:
    """A safe snake_case identifier (never a keyword, never empty, never starts with a digit).

    ``reserved`` defaults to the names a generated function body uses (``RESERVED``) and the
    builtins it may call; pass ``MODEL_RESERVED`` for model attributes.
    """
    name = "_".join(words(text)) or fallback
    if name[0].isdigit():
        name = f"{fallback}_{name}"
    blocked = (_PY_RESERVED | RESERVED) if reserved is None else reserved
    if keyword.iskeyword(name) or keyword.issoftkeyword(name) or name in blocked:
        name = f"{name}_"
    return name


def pascal(text: str, fallback: str = "Model") -> str:
    """A safe PascalCase class name."""
    name = "".join(w[:1].upper() + w[1:] for w in words(text)) or fallback
    if name[0].isdigit():
        name = f"{fallback}{name}"
    if name in _PY_RESERVED or keyword.iskeyword(name):
        name = f"{name}Model"
    return name


def constant(text: str, fallback: str = "VALUE") -> str:
    """A safe UPPER_CASE name (enum members)."""
    name = "_".join(words(text)).upper() or fallback
    if name[0].isdigit():
        name = f"{fallback}_{name}"
    if keyword.iskeyword(name.lower()) and name.lower() == name:
        name = f"{name}_"
    return name


class Namer:
    """Hands out unique names in one scope: a module, a class or a function signature."""

    def __init__(self, taken: set[str] | None = None) -> None:
        self._taken: set[str] = set(taken or ())

    def take(self, base: str) -> str:
        name = base
        n = 2
        while name in self._taken:
            name = f"{base}_{n}" if base[-1:].islower() or base.endswith("_") else f"{base}{n}"
            n += 1
        self._taken.add(name)
        return name

    def __contains__(self, name: object) -> bool:
        return name in self._taken


def py_literal(value: Any) -> str:
    """A Python literal for a JSON value: ``repr`` escapes every quote and control character."""
    if isinstance(value, bool) or value is None:
        return repr(value)
    if isinstance(value, int | float):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return "None"
        return repr(value)
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(py_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(f"{py_literal(str(k))}: {py_literal(v)}" for k, v in value.items())
            + "}"
        )
    return repr(str(value))


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f  ]")


def docstring(text: str | None, limit: int = 2000) -> str:
    """Text safe inside a triple-double-quoted docstring (no closing quotes, no escapes)."""
    if not text:
        return ""
    text = _CONTROL.sub(" ", text.strip())[:limit]
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return text


def comment(text: str | None, limit: int = 200) -> str:
    """Text safe in a single-line ``#`` comment."""
    if not text:
        return ""
    return " ".join(_CONTROL.sub(" ", text).split())[:limit]


def first_line(text: str | None, limit: int = 120) -> str:
    if not text:
        return ""
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line[:limit]
