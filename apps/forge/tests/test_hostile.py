"""A spec written to inject code generates code that compiles and runs none of it.

Every name, description, example, pattern, enum value and default below tries to close a
string, a docstring, a comment or a call. The generated modules must compile, and the
spec's text must appear only as string constants: no import, call or name the templates
did not write themselves.
"""

from __future__ import annotations

import ast
import string

from hypothesis import given, settings
from hypothesis import strategies as st

from apiforge.generator import generate
from apiforge.naming import docstring, pascal, py_literal, snake
from tests.conftest import minimal, spec_bytes

PAYLOADS = [
    "__import__('os').system('touch /tmp/pwned')",
    '"""; import os; os.system("id"); """',
    "'''; import os; '''",
    'x"); import os #',
    '\\""" \\\n import os',
    "a\nimport os\nb",
    "${{ secrets }} {% raw %} {{ 7*7 }}",
    " import os ",
    "class X: pass",
    "eval(open('/etc/passwd').read())",
]

ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "typing",
    "datetime",
    "uuid",
    "enum",
    "collections",
    "contextlib",
    "functools",
    "json",
    "pathlib",
    "os",
    "tempfile",
    "hmac",
    "time",
    "base64",
    "fastapi",
    "pydantic",
    "pydantic_core",
    "pydantic_settings",
    "httpx",
    "pytest",
    "jwt",
    "sqlalchemy",
    "app",
    "tests",
    "asyncio",
    "logging",
    "alembic",
    "starlette",
}
FORBIDDEN_CALLS = {"system", "eval", "exec", "__import__", "popen", "compile", "open"}


def hostile_spec() -> dict[str, object]:
    props = {p: {"type": "string", "description": p, "example": p, "default": p} for p in PAYLOADS}
    props["enumish"] = {"type": "string", "enum": PAYLOADS}
    props["patterned"] = {"type": "string", "pattern": "^'''\"\"\"$"}
    model = {"type": "object", "description": PAYLOADS[1], "properties": props}
    paths = {
        "/things/{" + PAYLOADS[3].replace("/", "") + "}": {
            "get": {
                "operationId": PAYLOADS[0],
                "summary": PAYLOADS[1],
                "description": PAYLOADS[5],
                "tags": [PAYLOADS[2]],
                "parameters": [
                    {
                        "name": PAYLOADS[3].replace("/", ""),
                        "in": "path",
                        "required": True,
                        "description": PAYLOADS[4],
                        "schema": {"type": "string"},
                    },
                    {
                        "name": PAYLOADS[6],
                        "in": "query",
                        "schema": {"type": "string", "default": PAYLOADS[7]},
                    },
                    {"name": PAYLOADS[8], "in": "header", "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {
                        "description": PAYLOADS[9],
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Evil"}}
                        },
                    }
                },
            }
        }
    }
    doc = minimal(
        paths,
        schemas={
            "Evil": model,
            PAYLOADS[8].replace(" ", "_").replace(":", "_"): {"type": "string"},
        },
    )
    doc["info"] = {"title": PAYLOADS[1], "version": PAYLOADS[2], "description": PAYLOADS[0]}
    doc["tags"] = [{"name": PAYLOADS[2], "description": PAYLOADS[6]}]
    return doc


def test_a_hostile_spec_generates_inert_code() -> None:
    gen = generate(spec_bytes(hostile_spec()), "evil.yaml", accept_report=True)
    py_files = [
        f for f in gen.files if f.path.endswith(".py") and not f.path.endswith("fidelity.py")
    ]
    assert py_files
    for f in py_files:
        tree = ast.parse(f.content, filename=f.path)  # it compiles
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                root = (module or "").split(".")[0]
                if isinstance(node, ast.ImportFrom) and node.level:
                    continue
                assert root in ALLOWED_IMPORT_ROOTS, f"{f.path}: unexpected import {module}"
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", "")
                )
                assert name not in FORBIDDEN_CALLS, f"{f.path}: call to {name}"
            if isinstance(node, ast.Name):
                assert node.id not in {"os", "eval", "exec", "__import__"} or f.path.startswith(
                    "tests/"
                ), f"{f.path}: name {node.id}"
        # The payloads only ever appear inside string constants (or comments).
        constants = " ".join(
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        )
        code_without_strings = ast.unparse(_strip_strings(tree))
        assert "touch /tmp/pwned" not in code_without_strings
        assert "/etc/passwd" not in code_without_strings
        _ = constants


def _strip_strings(tree: ast.AST) -> ast.AST:
    class Strip(ast.NodeTransformer):
        def visit_Constant(self, node: ast.Constant) -> ast.Constant:
            return ast.Constant("") if isinstance(node.value, str) else node

    return Strip().visit(tree)


@given(st.text())
@settings(max_examples=300, deadline=None)
def test_any_text_is_a_safe_literal(text: str) -> None:
    source = py_literal(text)
    tree = ast.parse(source, mode="eval")
    assert isinstance(tree.body, ast.Constant)
    assert tree.body.value == text


@given(st.text())
@settings(max_examples=300, deadline=None)
def test_any_text_is_safe_in_a_docstring(text: str) -> None:
    source = f'def f() -> None:\n    """{docstring(text)}"""\n'
    tree = ast.parse(source)
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef) and len(func.body) == 1
    assert isinstance(func.body[0], ast.Expr) and isinstance(func.body[0].value, ast.Constant)


@given(st.text())
@settings(max_examples=300, deadline=None)
def test_any_text_becomes_a_valid_identifier(text: str) -> None:
    for name in (snake(text), pascal(text)):
        assert name.isidentifier()
        assert set(name) <= set(string.ascii_letters + string.digits + "_")
        ast.parse(f"{name} = 1")


def _zip_with(member: bytes, *, compress_type: int = 0, flag_bits: int = 0) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("openapi.json")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, member)
    data = bytearray(buf.getvalue())
    # Patch the local and central headers after writing, the way a hostile tool would.
    for sig in (b"PK\x03\x04", b"PK\x01\x02"):
        at = data.find(sig)
        flag_at, method_at = (at + 6, at + 8) if sig == b"PK\x03\x04" else (at + 8, at + 10)
        data[flag_at : flag_at + 2] = flag_bits.to_bytes(2, "little")
        data[method_at : method_at + 2] = compress_type.to_bytes(2, "little")
    return bytes(data)


def test_unreadable_zip_members_are_refused_with_a_reason() -> None:
    import pytest

    from apiforge.bundles import read_zip
    from apiforge.errors import SpecLoadError

    body = spec_bytes(minimal())
    for data in (_zip_with(body, compress_type=99), _zip_with(body, flag_bits=1)):
        with pytest.raises(SpecLoadError):
            read_zip(data)
    corrupt = bytearray(_zip_with(body))
    corrupt[corrupt.find(b"PK\x03\x04") : corrupt.find(b"PK\x03\x04") + 4] = b"XXXX"
    with pytest.raises(SpecLoadError):
        read_zip(bytes(corrupt))


def test_a_pointer_with_a_unicode_digit_is_a_ref_error_not_a_crash() -> None:
    import pytest

    from apiforge.errors import ForgeError
    from apiforge.generator import lint

    spec = minimal(
        {
            "/a": {
                "get": {
                    "operationId": "a",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": {"$ref": "#/x/²"}}},
                        }
                    },
                }
            }
        },
    )
    spec["x"] = [{"type": "string"}]
    with pytest.raises(ForgeError):
        lint(spec_bytes(spec), "openapi.yaml")


def test_an_unpaired_surrogate_is_refused_at_load() -> None:
    import pytest

    from apiforge.errors import SpecLoadError
    from apiforge.generator import lint

    data = b'{"openapi": "3.0.3", "info": {"title": "X\\ud800", "version": "1"}, "paths": {}}'
    with pytest.raises(SpecLoadError, match="surrogate"):
        lint(data, "openapi.json")


def test_control_characters_in_the_title_keep_pyproject_valid_toml() -> None:
    import tomllib

    spec = minimal()
    spec["info"] = {"title": "X\u007fY\u0001Z", "version": "1"}
    gen = generate(spec_bytes(spec), "openapi.yaml")
    pyproject = next(f.content for f in gen.files if f.path == "pyproject.toml")
    assert "X\u007fY\u0001Z" in tomllib.loads(pyproject)["project"]["description"]
