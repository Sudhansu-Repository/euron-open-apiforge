"""Prometheus metrics for APIForge itself: specs, lint, generations, downloads, the worker."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

_S_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)

SPECS_UPLOADED = Counter(
    "apiforge_specs_uploaded_total", "Spec versions stored, by outcome", ["outcome"]
)
LINT_SECONDS = Histogram(
    "apiforge_lint_seconds", "Time to load, validate and normalize a spec", buckets=_S_BUCKETS
)
LINT_CACHE = Counter("apiforge_lint_cache_total", "Lint results served from cache", ["result"])
GENERATIONS = Counter("apiforge_generations_total", "Generations finished, by status", ["status"])
GENERATION_SECONDS = Histogram(
    "apiforge_generation_seconds",
    "Time for the worker to generate and store one project",
    buckets=_S_BUCKETS,
)
GENERATION_QUEUE = Gauge("apiforge_generation_queue", "Generations waiting for a worker")
ARCHIVE_DOWNLOADS = Counter("apiforge_archive_downloads_total", "Archives downloaded")
JOB_SECONDS = Histogram("apiforge_job_seconds", "Worker job run time", ["job"], buckets=_S_BUCKETS)
JOB_FAILURES = Counter("apiforge_job_failures_total", "Worker job failures", ["job"])
DEPENDENCY_ERRORS = Counter(
    "apiforge_dependency_errors_total",
    "Optional dependency failures that were absorbed",
    ["dependency", "operation"],
)
