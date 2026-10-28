"""Prove a generated project works: install it and run its own gates.

The project's tests already contain the proof APIForge promises (a contract test per
operation, validation and auth tests, and ``test_spec.py``, which compares the served
OpenAPI with the spec it came from), so verifying is running what its CI runs: ``uv sync``,
``ruff check``, ``ruff format --check``, ``mypy --strict`` and ``pytest``. Installing needs
the package index (or a warm uv cache); generating never does.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from apiforge.errors import ToolMissingError

STEPS: list[tuple[str, list[str]]] = [
    ("install", ["uv", "sync", "--quiet"]),
    ("lint", ["uv", "run", "--quiet", "ruff", "check", "."]),
    ("format", ["uv", "run", "--quiet", "ruff", "format", "--check", "."]),
    ("types", ["uv", "run", "--quiet", "mypy", "app", "tests"]),
    ("tests", ["uv", "run", "--quiet", "pytest", "-q", "-p", "no:cacheprovider"]),
]


@dataclass
class StepResult:
    name: str
    ok: bool
    seconds: float
    output: str  # the tail of stdout and stderr


@dataclass
class VerifyResult:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    def summary(self) -> str:
        return ", ".join(f"{s.name} {'ok' if s.ok else 'FAILED'}" for s in self.steps)


def verify(project: Path, *, timeout: float = 600, stop_on_failure: bool = True) -> VerifyResult:
    if shutil.which("uv") is None:
        raise ToolMissingError(
            "apiforge verify needs uv (https://docs.astral.sh/uv/) to install the project."
        )
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH")}
    env["UV_NO_PROGRESS"] = "1"
    result = VerifyResult()
    for name, cmd in STEPS:
        start = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S603 fixed commands in the project folder
                cmd,
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            ok = proc.returncode == 0
            output = (proc.stdout + proc.stderr).strip()
        except subprocess.TimeoutExpired:
            ok, output = False, f"timed out after {timeout:.0f} s"
        result.steps.append(
            StepResult(name, ok, round(time.monotonic() - start, 2), output[-4000:])
        )
        if not ok and stop_on_failure:
            break
    return result
