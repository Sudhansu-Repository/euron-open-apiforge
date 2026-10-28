"""Write a generation to disk without losing anyone's code (the generation gap).

Rules, applied file by file:

- **Generated files** (``app/generated/``, ``tests/generated/``, ``apiforge.lock``) are
  rewritten. Before that, each one on disk is hashed and compared with the hash recorded
  in the previous ``apiforge.lock``: a mismatch means someone edited a generated file, and
  nothing is written unless ``force`` is set (``ConflictError`` lists the files).
- **Your files** (handlers, ``main.py``, ``config.py``, ``auth.py``, project files) are
  created when missing and otherwise never touched, with one exception: an operation that is
  new in the spec gets its stub appended to the end of its handler module (nothing already
  in the file changes).
- An operation that disappeared from the spec keeps its handler; it is reported so you can
  delete it when you are ready. A generated file that is no longer produced (a tag that
  went away) is deleted if it was not edited.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apiforge.errors import ConflictError
from apiforge.generator import LOCK_FILE, Generation, sha256
from apiforge.targets.fastapi.plan import HANDLER_PREFIX


@dataclass
class WriteResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # yours, left alone
    deleted: list[str] = field(default_factory=list)
    appended: dict[str, list[str]] = field(default_factory=dict)  # handler module -> functions
    removed_operations: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "kept": self.kept,
            "deleted": self.deleted,
            "appended": self.appended,
            "removed_operations": self.removed_operations,
            "conflicts": self.conflicts,
        }


def read_lock(root: Path) -> dict[str, Any] | None:
    path = root / LOCK_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


GENERATED_DIRS = ("app/generated/", "tests/generated/")


def _generated_path(root: Path, path: str) -> bool:
    """A relative path under one of the generated folders, that stays inside ``root``."""
    if "\\" in path or path.startswith("/") or not path.startswith(GENERATED_DIRS):
        return False
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return False
    base = root.resolve()
    return (base / path).resolve().is_relative_to(base)


def plan_write(gen: Generation, root: Path, *, force: bool = False) -> WriteResult:
    """What ``write`` would do, without writing anything."""
    result = WriteResult()
    old = read_lock(root) or {}
    # The lock file is input from disk (a cloned repo, a pull request): only its entries for
    # generated files inside this project are trusted, so it can never point a delete or a
    # comparison at a path outside the generated folders.
    files = old.get("files")
    raw_hashes: dict[Any, Any] = files if isinstance(files, dict) else {}
    old_hashes: dict[str, str] = {
        p: h
        for p, h in raw_hashes.items()
        if isinstance(p, str) and isinstance(h, str) and _generated_path(root, p)
    }
    raw_ops = old.get("operations")
    old_ops: dict[str, Any] = raw_ops if isinstance(raw_ops, dict) else {}
    new_paths = {f.path for f in gen.files}

    for f in gen.files:
        target = root / f.path
        exists = target.exists()
        if f.owner == "generated":
            if not exists:
                result.created.append(f.path)
                continue
            current = target.read_text()
            if f.path != LOCK_FILE:
                recorded = old_hashes.get(f.path)
                edited = (recorded is not None and sha256(current) != recorded) or (
                    recorded is None and current != f.content
                )
                if edited and not force:
                    result.conflicts.append(f.path)
                    continue
            if current == f.content:
                result.unchanged.append(f.path)
            else:
                result.updated.append(f.path)
        else:
            if not exists:
                result.created.append(f.path)
            else:
                result.kept.append(f.path)

    for path, recorded in old_hashes.items():
        if path in new_paths:
            continue
        target = root / path
        if target.exists() and (force or sha256(target.read_text()) == recorded):
            result.deleted.append(path)

    for func, meta in old_ops.items():
        if not isinstance(meta, dict):
            continue
        if not any(op.func == func for op in gen.api.operations):
            result.removed_operations.append(
                f"{meta.get('method', '').upper()} {meta.get('path', '')} "
                f"(app/handlers/{meta.get('module', '')}.py: {func})"
            )

    for view in gen.target.views:
        module_path = f"{HANDLER_PREFIX}{view.op.module}.py"
        target = root / module_path
        if not target.exists():
            continue  # created whole, with every stub
        source = target.read_text()
        if re.search(rf"^async def {re.escape(view.op.func)}\(", source, re.MULTILINE):
            continue
        result.appended.setdefault(module_path, []).append(view.op.func)
    return result


def write(gen: Generation, root: Path, *, force: bool = False) -> WriteResult:
    """Apply a generation to ``root`` (created if needed). Raises ``ConflictError`` when a
    generated file was edited by hand and ``force`` is not set; nothing is written then."""
    result = plan_write(gen, root, force=force)
    if result.conflicts:
        raise ConflictError(result.conflicts)
    root.mkdir(parents=True, exist_ok=True)
    by_path = {f.path: f for f in gen.files}
    for path in result.created + result.updated:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(by_path[path].content)
    for path in result.deleted:
        (root / path).unlink(missing_ok=True)
    views = {v.op.func: v for v in gen.target.views}
    for module_path, funcs in result.appended.items():
        target = root / module_path
        source = target.read_text().rstrip("\n") + "\n"
        for func in funcs:
            source += gen.target.handler_stub(views[func]).rstrip("\n") + "\n"
        target.write_text(source)
    return result
