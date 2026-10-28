"""Spec to project: the one entry point the CLI and the web service both use.

``generate`` is deterministic: the same spec bytes and options give the same files, byte
for byte, on any machine (formatting is pinned, ordering is sorted, nothing reads the clock
or the environment).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from apiforge import __version__
from apiforge.errors import ForgeError
from apiforge.examples import expand
from apiforge.ir import ApiDef
from apiforge.loader import Bundle, load
from apiforge.normalize import normalize
from apiforge.options import GenerateOptions
from apiforge.render import GeneratedFile, format_python
from apiforge.report import Report
from apiforge.targets.fastapi.plan import FastApiTarget

LOCK_FILE = "apiforge.lock"


class ReportBlockedError(ForgeError):
    """The lint report has errors and the caller has not accepted them."""

    code = "report_has_errors"

    def __init__(self, report: Report) -> None:
        n = len(report.errors)
        super().__init__(
            f"The spec has {n} problem{'s' if n != 1 else ''} APIForge cannot generate "
            f"faithfully (the first: {report.errors[0].message}). Fix the spec, or accept the "
            "report to generate without them (--accept-report)."
        )
        self.report = report


@dataclass
class Generation:
    api: ApiDef
    report: Report
    files: list[GeneratedFile]
    lock: dict[str, Any]
    target: FastApiTarget
    spec_sha256: str

    @property
    def slug(self) -> str:
        return self.target.slug

    def file_map(self) -> dict[str, str]:
        return {f.path: f.content for f in self.files}


def sha256(text: str | bytes) -> str:
    data = text.encode() if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def lint(
    data: bytes, name: str = "openapi.yaml", *, files: Mapping[str, bytes] | None = None
) -> tuple[ApiDef, Report]:
    """Load, validate and normalize; the report lists everything APIForge noticed."""
    bundle = load(data, name, files=files)
    return normalize(bundle)


def bundled_document(bundle: Bundle) -> dict[str, Any]:
    """The root document with refs into other files inlined (refs inside it are kept)."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                file, _, target = bundle.resolve(ref, bundle.root_name)
                return expand(
                    bundle,
                    {"__file__": file, **target} if isinstance(target, dict) else target,
                    file,
                )
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(bundle.root)  # type: ignore[no-any-return]


def generate(
    data: bytes,
    name: str = "openapi.yaml",
    *,
    files: Mapping[str, bytes] | None = None,
    options: GenerateOptions | None = None,
    accept_report: bool = False,
) -> Generation:
    options = options or GenerateOptions()
    bundle = load(data, name, files=files)
    api, report = normalize(bundle)
    if report.errors and not accept_report:
        raise ReportBlockedError(report)
    if options.db:
        from apiforge.crud import detect

        detect(api, report)
    spec = bundled_document(bundle)
    target = FastApiTarget(api, options, spec)
    out = target.files()
    format_python(out)
    out.sort(key=lambda f: f.path)
    spec_sha = sha256(data + b"".join(files[k] for k in sorted(files)) if files else data)
    lock = {
        "generator": "euron-apiforge",
        "version": __version__,
        "target": "fastapi",
        "options": options.as_dict(),
        "spec": {"title": api.title, "version": api.version, "sha256": spec_sha},
        "operations": {
            op.func: {"module": op.module, "method": op.method, "path": op.path}
            for op in api.operations
        },
        "files": {f.path: sha256(f.content) for f in out if f.owner == "generated"},
    }
    out.append(
        GeneratedFile(LOCK_FILE, json.dumps(lock, indent=2, sort_keys=True) + "\n", "generated")
    )
    return Generation(api, report, out, lock, target, spec_sha)
