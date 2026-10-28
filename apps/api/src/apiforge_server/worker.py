"""Background worker: runs queued generations.

Stateless and safe to run as several replicas: generations are claimed with ``FOR UPDATE
SKIP LOCKED`` and held by a lease, so two workers never run the same one, and a job whose
worker died is claimed again once its lease expires. SIGTERM finishes the jobs in hand, then
exits. Prometheus metrics are served on WORKER_METRICS_PORT.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from prometheus_client import start_http_server

from apiforge_server.core.config import get_settings
from apiforge_server.core.container import Container
from apiforge_server.core.db import import_all_models
from apiforge_server.core.logs import configure_logging
from apiforge_server.generations import service as generations
from apiforge_server.observability import metrics

log = logging.getLogger("apiforge_server.worker")


@dataclass
class Job:
    name: str
    every_s: float
    run: Callable[[Container], Awaitable[Any]]
    last: float = field(default=0.0)
    # The last run did work (returned a positive count), so more may be waiting: run again
    # at once instead of after the interval, until a pass finds nothing.
    busy: bool = field(default=False)


def jobs(container: Container) -> list[Job]:
    return [Job("generations", container.settings.worker_poll_s, generations.process)]


async def run_due(container: Container, schedule: list[Job], now: float | None = None) -> int:
    """Run every job whose interval elapsed or that found work last time. A failing job is
    logged and retried next time; it never stops the others."""
    now = now if now is not None else time.monotonic()
    ran = 0
    for job in schedule:
        if not job.busy and now - job.last < job.every_s:
            continue
        job.last = now
        job.busy = False
        started = time.perf_counter()
        try:
            done = await job.run(container)
            job.busy = isinstance(done, int) and done > 0
        except Exception:
            metrics.JOB_FAILURES.labels(job.name).inc()
            log.exception("job failed", extra={"job": job.name})
        finally:
            metrics.JOB_SECONDS.labels(job.name).observe(time.perf_counter() - started)
        ran += 1
    return ran


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    import_all_models()
    if settings.worker_metrics_port:
        start_http_server(settings.worker_metrics_port)
    container = Container.build(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    schedule = jobs(container)
    log.info(
        "worker started",
        extra={"cache": container.kv.backend, "concurrency": settings.worker_concurrency},
    )
    try:
        while not stop.is_set():
            await run_due(container, schedule)
            if any(job.busy for job in schedule):
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_s)
    finally:
        await container.close()
        log.info("worker stopped")
