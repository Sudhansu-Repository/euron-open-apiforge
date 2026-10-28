"""What a spec describes and what APIForge thinks of it: the bridge to the generator.

Linting is CPU work (YAML parsing, validation, normalization), so it runs in a worker
thread; results are cached in the KV store by the spec's SHA-256 for an hour, because the
same bytes always lint the same way (a re-upload, the playground, a generation request).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from apiforge import __version__ as forge_version
from apiforge.bundles import read_zip
from apiforge.errors import ForgeError, SpecInvalidError
from apiforge.fidelity import canonical_operations
from apiforge.generator import bundled_document
from apiforge.loader import load
from apiforge.normalize import normalize

from apiforge_server.core.errors import AppError
from apiforge_server.core.kv import KV
from apiforge_server.observability import metrics

log = logging.getLogger("apiforge_server.analysis")
CACHE_TTL_S = 3600
# Bump when the cached analysis changes shape. The generator version is part of the key
# too, so an upgrade that changes lint results never serves the old ones.
CACHE_VERSION = "1"


class SpecRejectedError(AppError):
    """The upload is not a spec APIForge can read (unreadable, invalid, unsupported)."""

    # Always raised with the generator's own code (spec_unreadable, spec_invalid,
    # spec_version_unsupported, spec_ref_unresolved, spec_too_complex), so clients can act
    # on the reason; this class only fixes the status.
    status_code = 422


@dataclass
class Analysis:
    sha256: str
    title: str
    api_version: str
    openapi_version: str
    operations: list[dict[str, Any]] = field(default_factory=list)
    tags: list[dict[str, Any]] = field(default_factory=list)
    schemes: list[dict[str, str]] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    report: list[dict[str, str]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    # (METHOD path) -> fingerprint of the operation's canonical form, for version diffs.
    fingerprints: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "operations": self.operations,
            "tags": self.tags,
            "schemes": self.schemes,
            "models": self.models,
            "fingerprints": self.fingerprints,
        }


def spec_inputs(data: bytes, filename: str) -> tuple[bytes, str, dict[str, bytes] | None]:
    """(root bytes, root name, sibling files) for a single document or a zip bundle."""
    if filename.lower().endswith(".zip"):
        return read_zip(data)
    return data, filename, None


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _analyze(data: bytes, filename: str, sha: str) -> Analysis:
    root, name, files = spec_inputs(data, filename)
    bundle = load(root, name, files=files)
    api, report = normalize(bundle)
    canonical = canonical_operations(bundled_document(bundle))
    fingerprints = {
        key: {
            part: _fingerprint(op[part])
            for part in ("parameters", "request body", "responses", "security")
        }
        for key, op in canonical.items()
    }
    operations = [
        {
            "method": op.method.upper(),
            "path": op.path,
            "operation_id": op.operation_id,
            "function": op.func,
            "tag": op.tag,
            "summary": op.summary or "",
            "deprecated": op.deprecated,
            "secured": bool(op.security),
            "schemes": sorted({u.scheme for alt in (op.security or []) for u in alt}),
            "responses": [r.status for r in op.responses],
        }
        for op in api.operations
    ]
    return Analysis(
        sha256=sha,
        title=api.title,
        api_version=api.version,
        openapi_version=api.openapi,
        operations=operations,
        tags=[
            {"name": t.wire, "description": t.description or "", "operations": len(api.tag_ops(t))}
            for t in api.tags
        ],
        schemes=[{"name": s.wire, "kind": s.kind} for s in api.schemes],
        models=[m.name for m in api.models],
        report=report.as_list(),
        counts=report.counts(),
        fingerprints=fingerprints,
    )


async def analyze(kv: KV, data: bytes, filename: str) -> Analysis:
    """Lint ``data`` (cached by content); raises ``SpecRejectedError`` with a reason."""
    sha = hashlib.sha256(data).hexdigest()
    key = f"af:lint:{CACHE_VERSION}:{forge_version}:{sha}:{filename.lower().endswith('.zip')}"
    try:
        cached = await kv.get(key)
    except Exception:  # Redis down: lint anyway, uncached
        metrics.DEPENDENCY_ERRORS.labels("kv", "lint_cache_get").inc()
        cached = None
    if cached is not None:
        metrics.LINT_CACHE.labels("hit").inc()
        return Analysis(**json.loads(cached))
    metrics.LINT_CACHE.labels("miss").inc()
    started = time.perf_counter()
    try:
        result = await asyncio.to_thread(_analyze, data, filename, sha)
    except SpecInvalidError as exc:
        raise SpecRejectedError(
            exc.message, code=exc.code, details={"errors": exc.errors[:20]}
        ) from exc
    except ForgeError as exc:
        details = {"pointer": exc.pointer} if exc.pointer else {}
        raise SpecRejectedError(exc.message, code=exc.code, details=details) from exc
    finally:
        metrics.LINT_SECONDS.observe(time.perf_counter() - started)
    try:
        await kv.set(key, json.dumps(asdict(result)).encode(), CACHE_TTL_S)
    except Exception:
        metrics.DEPENDENCY_ERRORS.labels("kv", "lint_cache_set").inc()
    return result


def changes_between(old: dict[str, Any] | None, new: Analysis) -> dict[str, Any]:
    """Operations added, removed and changed (and which part changed) between versions."""
    if not old:
        return {
            "added": [o["method"] + " " + o["path"] for o in new.operations],
            "removed": [],
            "changed": [],
            "first": True,
        }
    before: dict[str, dict[str, str]] = old.get("fingerprints") or {}
    after = new.fingerprints
    changed = []
    for key in sorted(set(before) & set(after)):
        parts = [p for p in after[key] if before[key].get(p) != after[key][p]]
        if parts:
            changed.append({"operation": key, "parts": parts})
    return {
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "changed": changed,
        "first": False,
    }
