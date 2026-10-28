"""Templates to files: a strict Jinja environment, escaping filters and ruff formatting."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from apiforge.naming import comment, docstring, first_line, py_literal

Owner = Literal["generated", "user"]


@dataclass
class GeneratedFile:
    path: str  # posix path inside the project
    content: str
    owner: Owner  # generated: rewritten every time; user: created once, then yours

    @property
    def is_python(self) -> bool:
        return self.path.endswith(".py")


def environment(template_dir: Path) -> SandboxedEnvironment:
    """Sandboxed (templates cannot reach Python internals) and strict (a missing variable
    is an error, never an empty string)."""
    from jinja2 import FileSystemLoader

    env = SandboxedEnvironment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        autoescape=False,  # the output is Python and YAML, not HTML
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        extensions=["jinja2.ext.do"],
    )
    env.filters["lit"] = py_literal
    env.filters["doc"] = docstring
    env.filters["comment"] = comment
    env.filters["first_line"] = first_line
    env.filters["json"] = lambda v: json.dumps(v, indent=2, sort_keys=False, ensure_ascii=False)
    # A JSON string is a valid TOML basic string and YAML double-quoted string, except that
    # TOML forbids a raw DEL (json.dumps leaves it as is): escape it the way both accept.
    env.filters["yaml_str"] = lambda v: json.dumps(str(v), ensure_ascii=False).replace(
        "\x7f", "\\u007f"
    )
    return env


def ruff_binary() -> str:
    from ruff.__main__ import find_ruff_bin  # type: ignore[import-untyped]

    return os.fsdecode(find_ruff_bin())


def format_python(files: list[GeneratedFile], line_length: int = 100) -> None:
    """Sort imports and format every Python file in place, with a pinned configuration so
    the output does not depend on the machine's ruff settings."""
    py = [f for f in files if f.is_python]
    if not py:
        return
    ruff = ruff_binary()
    with tempfile.TemporaryDirectory(prefix="apiforge-fmt-") as tmp:
        root = Path(tmp)
        (root / "ruff.toml").write_text(
            f'line-length = {line_length}\ntarget-version = "py312"\n'
            '[lint]\nselect = ["I", "F401"]\n[lint.isort]\nknown-first-party = ["app", "tests"]\n'
        )
        for f in py:
            target = root / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content)
        env = {**os.environ, "RUFF_NO_CACHE": "true"}
        base = [ruff, "--config", str(root / "ruff.toml")]
        # Import sorting only (F401 is reported for the project's own check, not fixed here,
        # so the handler modules keep their convenience imports).
        subprocess.run(  # noqa: S603 the pinned ruff binary on files we just wrote
            [
                *base[:1],
                "check",
                "--config",
                str(root / "ruff.toml"),
                "--select",
                "I",
                "--fix",
                "--quiet",
                "--exit-zero",
                str(root),
            ],
            check=True,
            env=env,
            capture_output=True,
            cwd=tmp,
        )
        # Unused imports are removed only from the generated folders: which names a
        # generated module needs depends on the spec (no models, no Field), while a handler
        # module keeps its convenience imports for the code you will write.
        generated = [str(root / d) for d in ("app/generated", "tests/generated")]
        generated = [d for d in generated if Path(d).is_dir()]
        if generated:
            subprocess.run(  # noqa: S603 the pinned ruff binary on files we just wrote
                [
                    *base[:1],
                    "check",
                    "--config",
                    str(root / "ruff.toml"),
                    "--select",
                    "F401",
                    "--fix",
                    "--quiet",
                    "--exit-zero",
                    *generated,
                ],
                check=True,
                env=env,
                capture_output=True,
                cwd=tmp,
            )
        result = subprocess.run(  # noqa: S603
            [*base[:1], "format", "--config", str(root / "ruff.toml"), str(root)],
            env=env,
            capture_output=True,
            text=True,
            cwd=tmp,
        )
        if result.returncode != 0:
            output = (result.stderr + result.stdout)[:2000]
            raise RuntimeError(
                "Formatting the generated code failed, which means APIForge produced invalid "
                f"Python. Please report it with your spec.\n{output}"
            )
        for f in py:
            f.content = (root / f.path).read_text()


def render(env: SandboxedEnvironment, template: str, **context: Any) -> str:
    return env.get_template(template).render(**context)
