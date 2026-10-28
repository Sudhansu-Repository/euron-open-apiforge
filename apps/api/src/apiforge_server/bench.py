"""``make bench``: latency and throughput against the running stack, plus the generator.

Over HTTP, against the API and worker started by ``make up``: lint (uncached and from the
cache), spec upload, generation end to end through the worker (queued to succeeded), and
the archive and file-view reads. In process: how long the generator itself takes for each
bundled example. Creates a project named "bench" and deletes it afterwards.

    API_URL=http://localhost:4630 DEMO_PASSWORD=... uv run python -m apiforge_server.bench
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from apiforge.archive import build_zip
from apiforge.cli import CORPUS
from apiforge.generator import generate
from apiforge.options import GenerateOptions

API = os.environ.get("API_URL", "http://localhost:4630")
EMAIL = os.environ.get("BENCH_EMAIL", "admin@apiforge.local")
PASSWORD = os.environ.get("DEMO_PASSWORD", "")
GENERATIONS = int(os.environ.get("BENCH_GENERATIONS", "20"))
# A per-run marker in every spec text, so a rerun within the lint cache's TTL still
# measures uncached lints and creates new spec versions.
NONCE = int(time.time())


def _report(name: str, ms: list[float]) -> None:
    ms = sorted(ms)
    p95 = ms[max(0, round(len(ms) * 0.95) - 1)]
    print(
        f"  {name:<44} p50 {statistics.median(ms):7.1f} ms   p95 {p95:7.1f} ms   ({len(ms)} runs)"
    )


async def _timed(n: int, call: Callable[[int], Awaitable[object]]) -> list[float]:
    out = []
    for i in range(n):
        start = time.perf_counter()
        await call(i)
        out.append((time.perf_counter() - start) * 1000)
    return out


def generator_timings() -> None:
    print("\nGenerator, in process (load, validate, normalize, render, format, zip):")
    for spec in sorted(p for p in Path(CORPUS).iterdir() if p.suffix == ".yaml"):
        data = spec.read_bytes()
        for db in (False, True):
            runs = []
            for _ in range(5):
                start = time.perf_counter()
                gen = generate(data, spec.name, accept_report=True, options=GenerateOptions(db=db))
                build_zip(gen)
                runs.append((time.perf_counter() - start) * 1000)
            flag = " --db" if db else ""
            label = f"{spec.name}{flag} ({len(gen.api.operations)} ops, {len(gen.files)} files)"
            _report(label, runs)


async def main() -> None:
    if not PASSWORD:
        raise SystemExit("Set DEMO_PASSWORD (make bench passes it from deploy/compose/.env).")
    petstore = (Path(CORPUS) / "petstore.yaml").read_text()
    bookstore = (Path(CORPUS) / "bookstore.yaml").read_text()
    async with httpx.AsyncClient(base_url=API, timeout=60) as c:
        token = (
            await c.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        ).json()
        c.headers["authorization"] = f"Bearer {token['session_token']}"
        print(f"APIForge bench against {API}")

        async def lint_uncached(i: int) -> None:
            text = bookstore.replace("version: 2.3.0", f"version: 2.3.{NONCE}{i:03d}")
            (await c.post("/api/v1/lint", json={"content": text})).raise_for_status()

        async def lint_cached(i: int) -> None:
            (await c.post("/api/v1/lint", json={"content": bookstore})).raise_for_status()

        _report("lint, bookstore (11 ops), not cached", await _timed(30, lint_uncached))
        _report("lint, bookstore, cached by content", await _timed(30, lint_cached))

        project = (await c.post("/api/v1/projects", json={"name": "bench"})).json()
        slug = project["slug"]
        try:

            async def upload(i: int) -> None:
                text = petstore.replace("version: 1.0.0", f"version: 1.0.{NONCE}{i:03d}")
                r = await c.post(f"/api/v1/projects/{slug}/specs/text", json={"content": text})
                r.raise_for_status()

            _report("upload a spec version (lint, store, diff)", await _timed(20, upload))

            start = time.perf_counter()
            queued = [
                (await c.post(f"/api/v1/projects/{slug}/generations", json={})).json()["number"]
                for _ in range(GENERATIONS)
            ]
            durations: list[float] = []
            pending = set(queued)
            while pending:
                await asyncio.sleep(0.2)
                for gen in (await c.get(f"/api/v1/projects/{slug}/generations?limit=200")).json():
                    if gen["number"] in pending and gen["status"] in ("succeeded", "failed"):
                        pending.discard(gen["number"])
                        if gen["status"] == "succeeded":
                            durations.append(float(gen["duration_ms"]))
            elapsed = time.perf_counter() - start
            _report("generation in the worker (claimed to stored)", durations)
            print(
                f"  {GENERATIONS} generations queued at once: all finished in {elapsed:.1f} s "
                f"({GENERATIONS / elapsed:.1f} per second)"
            )

            number = queued[-1]

            async def download(i: int) -> None:
                r = await c.get(f"/api/v1/projects/{slug}/generations/{number}/archive")
                r.raise_for_status()

            async def view(i: int) -> None:
                r = await c.get(
                    f"/api/v1/projects/{slug}/generations/{number}/file",
                    params={"path": "app/generated/models.py"},
                )
                r.raise_for_status()

            _report("download an archive", await _timed(30, download))
            _report("view a generated file (cached archive)", await _timed(30, view))
            _report("list projects", await _timed(30, lambda i: c.get("/api/v1/projects")))
            _report("overview", await _timed(30, lambda i: c.get("/api/v1/overview")))
        finally:
            await c.delete(f"/api/v1/projects/{slug}")
    generator_timings()


if __name__ == "__main__":
    asyncio.run(main())
