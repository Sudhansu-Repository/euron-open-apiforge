"""Determinism, the lock file, the report gate and the CLI."""

from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from apiforge.archive import build_zip
from apiforge.cli import main
from apiforge.generator import ReportBlockedError, generate, lint
from apiforge.options import GenerateOptions
from tests.conftest import CORPUS, minimal, spec_bytes

PETSTORE = (CORPUS / "petstore.yaml").read_bytes()


def test_the_same_input_gives_the_same_bytes() -> None:
    a = build_zip(generate(PETSTORE, "petstore.yaml"))
    b = build_zip(generate(PETSTORE, "petstore.yaml"))
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()
    names = zipfile.ZipFile(BytesIO(a)).namelist()
    assert names == sorted(names) and all(n.startswith("pet-store/") for n in names)


def test_options_change_the_output_and_are_recorded() -> None:
    plain = generate(PETSTORE, "petstore.yaml")
    db = generate(PETSTORE, "petstore.yaml", options=GenerateOptions(db=True, docker=False))
    assert (
        "app/generated/crud.py" in db.file_map() and "app/generated/crud.py" not in plain.file_map()
    )
    assert "Dockerfile" not in db.file_map()
    lock = json.loads(db.file_map()["apiforge.lock"])
    assert lock["options"]["db"] is True and lock["spec"]["title"] == "Pet Store"
    assert set(lock["operations"]) == {"list_pets", "create_pet", "get_pet", "delete_pet"}
    assert all(path.startswith(("app/generated/", "tests/generated/")) for path in lock["files"])


def test_every_file_is_owned_and_handlers_are_yours() -> None:
    gen = generate(PETSTORE, "petstore.yaml")
    owners = {f.path: f.owner for f in gen.files}
    assert owners["app/handlers/pets.py"] == "user"
    assert owners["app/generated/models.py"] == "generated"
    assert owners["pyproject.toml"] == "user"


def test_errors_in_the_report_block_generation_until_accepted() -> None:
    doc = minimal(
        {
            "/a/{x}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                    "parameters": [
                        {"name": "x", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                }
            },
            "/a/{y}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                    "parameters": [
                        {"name": "y", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                }
            },
        }
    )
    with pytest.raises(ReportBlockedError, match="accept"):
        generate(spec_bytes(doc), "openapi.yaml")
    assert generate(spec_bytes(doc), "openapi.yaml", accept_report=True).files


def test_generating_needs_no_network(no_network: None) -> None:
    for spec in sorted(CORPUS.glob("*.yaml")):
        lint(spec.read_bytes(), spec.name)
        generate(spec.read_bytes(), spec.name, accept_report=True, options=GenerateOptions(db=True))


def test_cli_lint_generate_zip_diff_and_examples(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = CORPUS / "petstore.yaml"
    assert main(["lint", str(spec)]) == 0
    assert "4 operations" in capsys.readouterr().out
    out = tmp_path / "proj"
    assert main(["generate", "--spec", str(spec), "-o", str(out)]) == 0
    assert (out / "app/handlers/pets.py").exists()
    assert main(["diff", "--spec", str(spec), "-o", str(out)]) == 0
    assert "Nothing would change" in capsys.readouterr().out
    archive = tmp_path / "p.zip"
    assert main(["generate", "--spec", str(spec), "--zip", str(archive)]) == 0
    assert zipfile.ZipFile(archive).testzip() is None
    assert main(["examples", "--copy", str(tmp_path / "ex")]) == 0
    assert (tmp_path / "ex" / "bookstore.yaml").exists()
    assert main(["lint", str(tmp_path / "missing.yaml")]) == 1


def test_cli_reads_folders_and_zips_with_relative_refs(tmp_path: Path) -> None:
    folder = tmp_path / "spec"
    (folder / "schemas").mkdir(parents=True)
    root = minimal(
        {
            "/pets": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {"schema": {"$ref": "schemas/pet.yaml#/Pet"}}
                            },
                        }
                    }
                }
            }
        }
    )
    (folder / "openapi.yaml").write_bytes(spec_bytes(root))
    (folder / "schemas" / "pet.yaml").write_text(
        "Pet:\n  type: object\n  properties:\n    name: {type: string}\n"
    )
    assert main(["lint", str(folder)]) == 0
    archive = tmp_path / "spec.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(folder / "openapi.yaml", "openapi.yaml")
        zf.write(folder / "schemas" / "pet.yaml", "schemas/pet.yaml")
    assert main(["generate", "--spec", str(archive), "-o", str(tmp_path / "out")]) == 0
    spec_copy = json.loads((tmp_path / "out/app/generated/openapi.json").read_text())
    schema = spec_copy["paths"]["/pets"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert "$ref" not in schema and schema["properties"]["name"]["type"] == "string"


def test_verify_without_uv_is_an_error_message_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("apiforge.verify.shutil.which", lambda _: None)
    assert main(["verify", str(tmp_path)]) == 1
    assert "needs uv" in capsys.readouterr().err


def test_db_list_filters_use_the_wire_name_and_skip_json_columns() -> None:
    gen = generate(
        (CORPUS / "petstore.yaml").read_bytes(), "petstore.yaml", options=GenerateOptions(db=True)
    )
    handlers = next(f.content for f in gen.files if f.path == "app/handlers/pets.py")
    # ?status= arrives as status_ (a reserved name) but filters the status column; tags is
    # a JSON column, which cannot be compared portably, so it is not a filter.
    assert 'filters={"status": status_}' in handlers
    assert "kept in the database through" in handlers
    assert "already use the database" in handlers and "works as a mock" not in handlers


def test_a_look_around_pattern_on_a_parameter_is_enforced_with_python_re() -> None:
    spec = minimal(
        {
            "/users": {
                "get": {
                    "operationId": "findUser",
                    "parameters": [
                        {
                            "name": "name",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "pattern": "^(?!admin).*$"},
                        }
                    ],
                    "responses": {"204": {"description": "found"}},
                }
            }
        }
    )
    gen = generate(spec_bytes(spec), "openapi.yaml")
    router = next(f.content for f in gen.files if f.path.startswith("app/generated/routers/d"))
    assert "import re" in router and "pattern=re.compile(" in router
