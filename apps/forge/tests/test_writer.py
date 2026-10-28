"""Regeneration keeps your code (acceptance criterion 5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from apiforge.errors import ConflictError
from apiforge.generator import generate, sha256
from apiforge.writer import write
from tests.conftest import CORPUS, minimal, spec_bytes


def spec_with_changes() -> bytes:
    doc = yaml.safe_load((CORPUS / "petstore.yaml").read_text())
    item = doc["paths"]["/pets/{petId}"]
    del item["delete"]
    item["patch"] = {
        "tags": ["pets"],
        "operationId": "renamePet",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object", "properties": {"name": {"type": "string"}}}
                }
            },
        },
        "responses": {
            "200": {
                "description": "Renamed",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}},
            }
        },
    }
    doc["components"]["schemas"]["Pet"]["properties"]["nickname"] = {"type": "string"}
    doc["paths"]["/owners"] = {
        "get": {
            "tags": ["owners"],
            "operationId": "listOwners",
            "responses": {"200": {"description": "Owners"}},
        }
    }
    return yaml.safe_dump(doc, sort_keys=False).encode()


def test_regenerating_after_spec_changes_keeps_every_line_you_wrote(tmp_path: Path) -> None:
    write(generate((CORPUS / "petstore.yaml").read_bytes(), "petstore.yaml"), tmp_path)
    handler = tmp_path / "app/handlers/pets.py"
    mine = handler.read_text().replace(
        "    return mock.get_pet()", "    # my logic\n    return mock.get_pet()"
    )
    handler.write_text(mine)
    (tmp_path / "app/main.py").write_text(
        (tmp_path / "app/main.py").read_text() + "\n# my middleware\n"
    )

    result = write(generate(spec_with_changes(), "petstore.yaml"), tmp_path)

    after = handler.read_text()
    assert after.startswith(mine.rstrip("\n"))  # nothing you wrote moved or changed
    assert "async def rename_pet(" in after and result.appended == {
        "app/handlers/pets.py": ["rename_pet"]
    }
    assert "async def delete_pet(" in after  # kept, and reported
    assert any("delete_pet" in r for r in result.removed_operations)
    assert "nickname" in (tmp_path / "app/generated/models.py").read_text()
    assert (tmp_path / "app/handlers/owners.py").exists()  # a new tag gets its module
    assert "# my middleware" in (tmp_path / "app/main.py").read_text()
    assert "app/main.py" in result.kept


def test_a_hand_edited_generated_file_is_never_overwritten_silently(tmp_path: Path) -> None:
    gen = generate((CORPUS / "petstore.yaml").read_bytes(), "petstore.yaml")
    write(gen, tmp_path)
    models = tmp_path / "app/generated/models.py"
    models.write_text(models.read_text() + "\n# edited by hand\n")
    with pytest.raises(ConflictError) as exc:
        write(generate(spec_with_changes(), "petstore.yaml"), tmp_path)
    assert exc.value.paths == ["app/generated/models.py"]
    assert "edited by hand" in models.read_text()  # nothing was written
    write(generate(spec_with_changes(), "petstore.yaml"), tmp_path, force=True)
    assert "edited by hand" not in models.read_text()


def test_a_generated_file_that_is_no_longer_produced_is_removed(tmp_path: Path) -> None:
    write(generate(spec_with_changes(), "petstore.yaml"), tmp_path)
    assert (tmp_path / "app/generated/routers/owners.py").exists()
    result = write(generate((CORPUS / "petstore.yaml").read_bytes(), "petstore.yaml"), tmp_path)
    assert "app/generated/routers/owners.py" in result.deleted
    assert not (tmp_path / "app/generated/routers/owners.py").exists()
    assert (tmp_path / "app/handlers/owners.py").exists()  # yours stays


@pytest.mark.parametrize("force", [False, True])
def test_a_hostile_lock_file_cannot_delete_outside_the_generated_folders(
    tmp_path: Path, force: bool
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    handler = tmp_path / "project" / "app" / "handlers" / "mine.py"
    handler.parent.mkdir(parents=True)
    handler.write_text("# mine")
    lock = {
        "files": {
            "../victim.txt": sha256("keep me"),
            str(victim): sha256("keep me"),
            "app/handlers/mine.py": sha256("# mine"),
            "app/generated/../../../victim.txt": sha256("keep me"),
        },
        "operations": {"x": "not a dict"},
    }
    (tmp_path / "project" / "apiforge.lock").write_text(json.dumps(lock))
    gen = generate(spec_bytes(minimal()), "openapi.yaml")
    write(gen, tmp_path / "project", force=force)
    assert victim.read_text() == "keep me"
    assert handler.read_text() == "# mine"
