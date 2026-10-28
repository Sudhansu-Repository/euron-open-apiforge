"""Every bundled spec generates a project that installs and passes its own gates.

This is the proof behind acceptance criteria 1 (it runs), 2 (it serves its spec), 3 (it
validates), 4 (a mock on day one), 7 (clean code), 11 (auth) and 12 (persistence): each
generated project's test suite checks those, so the suite passing is the claim holding.
Slow (each project is installed and tested): ``pytest -m corpus``.

With ``CORPUS_DATABASE_URL`` set to a Postgres database whose name ends in ``_test``
(``make test-corpus`` sets it), every ``--db`` project runs its tests a second time against
Postgres, so the generated persistence is proven on the database production uses, not only
on SQLite.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest

from apiforge.generator import generate
from apiforge.options import GenerateOptions
from apiforge.verify import verify
from apiforge.writer import write
from tests.conftest import CORPUS, large_spec, spec_bytes
from tests.test_hostile import hostile_spec

POSTGRES = os.environ.get("CORPUS_DATABASE_URL", "")
SPECS = sorted(p.name for p in CORPUS.iterdir() if p.suffix in (".yaml", ".json"))
CASES = [(name, db) for name in SPECS for db in (False, True)]

pytestmark = [
    pytest.mark.corpus,
    pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to install the projects"),
]


def _check(project: Path) -> None:
    result = verify(project)
    failed = [s for s in result.steps if not s.ok]
    assert not failed, f"{failed[0].name} failed:\n{failed[0].output}"


@pytest.mark.parametrize(("name", "db"), CASES, ids=[f"{n}{'-db' if d else ''}" for n, d in CASES])
def test_corpus_spec_generates_a_working_project(name: str, db: bool, tmp_path: Path) -> None:
    spec = CORPUS / name
    gen = generate(spec.read_bytes(), name, accept_report=True, options=GenerateOptions(db=db))
    write(gen, tmp_path / "project")
    _check(tmp_path / "project")
    if db and POSTGRES:
        _check_on_postgres(tmp_path / "project")


def _check_on_postgres(project: Path) -> None:
    name = urlparse(POSTGRES).path.lstrip("/")
    assert name.endswith("_test"), f"refusing to drop tables in {name!r}: use a *_test database"
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH")}
    env["DATABASE_URL"] = POSTGRES
    result = subprocess.run(
        ["uv", "run", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, f"tests failed on Postgres:\n{result.stdout[-4000:]}"


def test_a_hostile_spec_generates_a_project_that_passes_its_gates(tmp_path: Path) -> None:
    gen = generate(spec_bytes(hostile_spec()), "evil.yaml", accept_report=True)
    write(gen, tmp_path / "project")
    _check(tmp_path / "project")


def test_a_240_operation_spec_generates_a_project_that_passes_its_gates(tmp_path: Path) -> None:
    gen = generate(spec_bytes(large_spec(120)), "large.yaml")
    assert len(gen.api.operations) == 240
    write(gen, tmp_path / "project")
    _check(tmp_path / "project")
