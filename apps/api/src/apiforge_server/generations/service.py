"""Generations: queued by the API, run by the worker, browsed and downloaded afterwards.

The worker claims queued rows with ``FOR UPDATE SKIP LOCKED`` and a lease, so several
workers never run the same generation and a crashed worker's job is picked up again when
its lease runs out (up to ``GENERATION_MAX_ATTEMPTS``). Archives are deterministic and
immutable: their SHA-256 is the ETag, and files inside them are cached in process by it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import logging
import time
import uuid
import zipfile
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

from apiforge.archive import build_zip
from apiforge.errors import ForgeError
from apiforge.generator import generate
from apiforge.options import GenerateOptions
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apiforge_server.audit.service import Actor, audit
from apiforge_server.core.container import Container
from apiforge_server.core.errors import AppError, ConflictError, NotFoundError
from apiforge_server.generations.models import Generation
from apiforge_server.generations.schemas import (
    FileContent,
    GeneratedFileOut,
    GenerationDetail,
    GenerationIn,
    GenerationOut,
)
from apiforge_server.observability import metrics
from apiforge_server.projects.analysis import spec_inputs
from apiforge_server.projects.models import Project, SpecVersion
from apiforge_server.projects.schemas import GenerationOptions
from apiforge_server.projects.service import get_project
from apiforge_server.users.models import User

log = logging.getLogger("apiforge_server.generations")
LANGUAGES = {
    ".py": "python",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".ini": "ini",
    ".mako": "python",
    ".lock": "json",
}
FILENAME_LANGUAGES = {"Dockerfile": "dockerfile", "Makefile": "makefile"}


class ReportHasErrorsError(AppError):
    status_code = 422
    code = "report_has_errors"


# ── queueing ─────────────────────────────────────────────────────────────────


async def create_generation(
    session: AsyncSession, slug: str, data: GenerationIn, actor: Actor
) -> GenerationOut:
    project = await get_project(session, slug)
    query = select(SpecVersion).where(SpecVersion.project_id == project.id)
    if data.spec_number is not None:
        query = query.where(SpecVersion.number == data.spec_number)
    spec = await session.scalar(query.order_by(SpecVersion.number.desc()).limit(1))
    if spec is None:
        raise NotFoundError(
            f"{slug} has no spec version {data.spec_number}."
            if data.spec_number
            else f"{slug} has no spec yet: upload one first."
        )
    if spec.errors and not data.accept_report:
        raise ReportHasErrorsError(
            f"Spec version {spec.number} has {spec.errors} "
            f"problem{'s' if spec.errors != 1 else ''} "
            "APIForge cannot generate faithfully. Fix the spec, or accept the report to generate "
            "without those parts.",
            details={
                "errors": [f for f in (spec.report or []) if f.get("severity") == "error"][:10]
            },
        )
    options = data.options or GenerationOptions.model_validate(project.default_options or {})
    for _ in range(3):
        number = (
            await session.scalar(
                select(func.coalesce(func.max(Generation.number), 0)).where(
                    Generation.project_id == project.id
                )
            )
            or 0
        ) + 1
        gen = Generation(
            project_id=project.id,
            spec_version_id=spec.id,
            number=number,
            options=options.model_dump(),
            accept_report=data.accept_report,
            created_by=actor.id,
        )
        session.add(gen)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            project = await get_project(session, slug)
            continue
        audit(
            session,
            actor,
            "generation.queued",
            "generation",
            gen.id,
            project=project.slug,
            number=number,
            spec=spec.number,
            options=gen.options,
        )
        await session.commit()
        await session.refresh(gen)
        return _out(gen, project, spec, actor.email)
    raise ConflictError("Several generations were requested at once; send it again.")


def _out(g: Generation, project: Project, spec: SpecVersion, email: str | None) -> GenerationOut:
    return GenerationOut(
        id=g.id,
        project_id=g.project_id,
        project_slug=project.slug,
        number=g.number,
        spec_number=spec.number,
        spec_title=spec.title,
        options=GenerationOptions.model_validate(g.options or {}),
        accept_report=g.accept_report,
        status=g.status,
        attempts=g.attempts,
        error_code=g.error_code,
        error=g.error,
        archive_sha256=g.archive_sha256,
        archive_bytes=g.archive_bytes,
        file_count=g.file_count,
        duration_ms=g.duration_ms,
        created_at=g.created_at,
        started_at=g.started_at,
        finished_at=g.finished_at,
        created_by_email=email,
    )


async def list_generations(
    session: AsyncSession, slug: str, limit: int = 50
) -> list[GenerationOut]:
    project = await get_project(session, slug)
    rows = (
        await session.execute(
            select(Generation, SpecVersion, User.email)
            .join(SpecVersion, SpecVersion.id == Generation.spec_version_id)
            .outerjoin(User, User.id == Generation.created_by)
            .where(Generation.project_id == project.id)
            .order_by(Generation.number.desc())
            .limit(limit)
        )
    ).all()
    return [_out(g, project, s, email) for g, s, email in rows]


async def recent_generations(session: AsyncSession, limit: int = 10) -> list[GenerationOut]:
    rows = (
        await session.execute(
            select(Generation, Project, SpecVersion, User.email)
            .join(Project, Project.id == Generation.project_id)
            .join(SpecVersion, SpecVersion.id == Generation.spec_version_id)
            .outerjoin(User, User.id == Generation.created_by)
            .order_by(Generation.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [_out(g, p, s, email) for g, p, s, email in rows]


async def _load(
    session: AsyncSession, slug: str, number: int
) -> tuple[Generation, Project, SpecVersion]:
    project = await get_project(session, slug)
    row = (
        await session.execute(
            select(Generation, SpecVersion)
            .join(SpecVersion, SpecVersion.id == Generation.spec_version_id)
            .where(Generation.project_id == project.id, Generation.number == number)
        )
    ).first()
    if row is None:
        raise NotFoundError(f"{slug} has no generation {number}.")
    return row[0], project, row[1]


async def get_generation(session: AsyncSession, slug: str, number: int) -> GenerationDetail:
    g, project, spec = await _load(session, slug, number)
    email = (
        await session.scalar(select(User.email).where(User.id == g.created_by))
        if g.created_by
        else None
    )
    base = _out(g, project, spec, email)
    return GenerationDetail(
        **base.model_dump(),
        files=[GeneratedFileOut.model_validate(f) for f in g.files or []],
        resources=(g.summary or {}).get("resources", []),
    )


# ── archives and files ───────────────────────────────────────────────────────


class _ArchiveCache:
    """Archives are immutable, so their unpacked files are cached by SHA-256, bounded by
    count and by total bytes (least recently used goes first)."""

    def __init__(self, max_archives: int = 16, max_bytes: int = 64 * 1024 * 1024) -> None:
        self._items: OrderedDict[str, dict[str, bytes]] = OrderedDict()
        self._max = max_archives
        self._max_bytes = max_bytes
        self._bytes = 0

    def get(self, sha: str) -> dict[str, bytes] | None:
        item = self._items.get(sha)
        if item is not None:
            self._items.move_to_end(sha)
        return item

    def put(self, sha: str, files: dict[str, bytes]) -> None:
        if sha in self._items:
            self._items.move_to_end(sha)
            return
        self._items[sha] = files
        self._bytes += _size(files)
        while len(self._items) > 1 and (
            len(self._items) > self._max or self._bytes > self._max_bytes
        ):
            _, dropped = self._items.popitem(last=False)
            self._bytes -= _size(dropped)


def _size(files: dict[str, bytes]) -> int:
    return sum(len(v) for v in files.values())


def etag(sha: str, path: str | None = None) -> str:
    """The ETag of an archive, or of one file in it: both are immutable."""
    return f'"{sha}:{path}"' if path else f'"{sha}"'


ARCHIVES = _ArchiveCache()


async def archive(
    session: AsyncSession,
    container: Container,
    slug: str,
    number: int,
    if_none_match: str | None = None,
) -> tuple[bytes | None, str, str]:
    """(zip bytes, sha256, download filename) of a finished generation. The bytes are None
    when ``if_none_match`` already names this archive: storage is not read at all."""
    g, project, _ = await _load(session, slug, number)
    if g.status != "succeeded" or not g.archive_key or not g.archive_sha256:
        raise ConflictError(
            f"Generation {number} is {g.status}; its archive is ready once it has succeeded."
        )
    filename = f"{project.slug}-{number}.zip"
    if if_none_match == etag(g.archive_sha256):
        return None, g.archive_sha256, filename
    data = await container.storage.get(g.archive_key)
    metrics.ARCHIVE_DOWNLOADS.inc()
    return data, g.archive_sha256, filename


async def file_content(
    session: AsyncSession,
    container: Container,
    slug: str,
    number: int,
    path: str,
    if_none_match: str | None = None,
) -> tuple[FileContent | None, str]:
    """One file of a finished generation, or None when ``if_none_match`` names it."""
    g, _, _ = await _load(session, slug, number)
    entry = next((f for f in g.files or [] if f.get("path") == path), None)
    if entry is None:
        raise NotFoundError(f"Generation {number} has no file {path!r}.")
    if not g.archive_sha256 or not g.archive_key:
        raise ConflictError("The archive is not ready yet.")
    if if_none_match == etag(g.archive_sha256, path):
        return None, g.archive_sha256
    files = ARCHIVES.get(g.archive_sha256)
    if files is None:
        data = await container.storage.get(g.archive_key)
        files = await asyncio.to_thread(_unpack, data)
        ARCHIVES.put(g.archive_sha256, files)
    content = files.get(path)
    if content is None:
        raise NotFoundError(f"{path!r} is not in the archive.")
    name = path.rsplit("/", 1)[-1]
    suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    language = FILENAME_LANGUAGES.get(name) or LANGUAGES.get(suffix, "text")
    return FileContent(
        path=path,
        owner=entry["owner"],
        content=content.decode("utf-8", "replace"),
        language=language,
    ), g.archive_sha256


def _unpack(data: bytes) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            _, _, inner = info.filename.partition("/")  # drop the project folder
            out[inner or info.filename] = zf.read(info)
    return out


# ── the worker side ──────────────────────────────────────────────────────────


async def claim(container: Container, limit: int) -> list[uuid.UUID]:
    """Take up to ``limit`` queued generations (or ones whose lease ran out)."""
    now = datetime.now(UTC)
    lease = now + timedelta(seconds=container.settings.generation_timeout_s + 30)
    async with container.db.sessionmaker() as session:
        rows = (
            await session.scalars(
                select(Generation)
                .where(
                    (Generation.status == "queued")
                    | ((Generation.status == "running") & (Generation.lease_until < now))
                )
                .order_by(Generation.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        claimed = []
        for g in rows:
            if g.attempts >= container.settings.generation_max_attempts:
                g.status = "failed"
                g.error_code = "worker_lost"
                g.error = (
                    f"The worker stopped {g.attempts} times while generating this. "
                    "Request a new generation; if it happens again, report it with the spec."
                )
                g.finished_at = now
                metrics.GENERATIONS.labels("failed").inc()
                _log_failure(g)
                continue
            g.status = "running"
            g.attempts += 1
            g.lease_until = lease
            g.started_at = now
            claimed.append(g.id)
        await session.commit()
        queued = await session.scalar(select(func.count()).where(Generation.status == "queued"))
        metrics.GENERATION_QUEUE.set(queued or 0)
    return claimed


def _log_failure(g: Generation) -> None:
    """One line per failed generation, whatever the cause: the GenerationFailures alarm
    counts these."""
    log.warning(
        "generation failed",
        extra={"generation_id": str(g.id), "error_code": g.error_code, "attempts": g.attempts},
    )


def _run_generator(
    data: bytes, filename: str, options: dict[str, Any], accept: bool
) -> tuple[bytes, Any]:
    root, name, files = spec_inputs(data, filename)
    gen = generate(
        root, name, files=files, options=GenerateOptions.from_dict(options), accept_report=accept
    )
    return build_zip(gen), gen


async def run(container: Container, generation_id: uuid.UUID) -> None:
    """Generate one claimed generation and record the result (never raises).

    The result is recorded only while this worker still owns the row: in a new transaction
    the row is locked and its ``attempts`` compared with the value this claim set. A worker
    whose lease expired (another worker claimed the job again) or whose project was deleted
    meanwhile records nothing; in the second case the archive it stored is removed again.
    """
    started = time.perf_counter()
    async with container.db.sessionmaker() as session:
        row = (
            await session.execute(
                select(Generation, SpecVersion)
                .join(SpecVersion, SpecVersion.id == Generation.spec_version_id)
                .where(Generation.id == generation_id)
            )
        ).first()
        if row is None:
            return
        g, spec = row
        mine = g.attempts
        storage_key, filename = spec.storage_key, spec.filename
        options, accept = dict(g.options or {}), g.accept_report
        key = f"archives/{g.project_id}/{g.id}.zip"
        await session.rollback()  # no transaction stays open while the generator runs

    outcome: dict[str, Any] = {}
    stored = False
    try:
        data = await container.storage.get(storage_key)
        zipped, gen = await asyncio.wait_for(
            asyncio.to_thread(_run_generator, data, filename, options, accept),
            timeout=container.settings.generation_timeout_s,
        )
        await container.storage.put(key, zipped, "application/zip")
        stored = True
        files = [
            {"path": f.path, "owner": f.owner, "bytes": len(f.content.encode())}
            for f in sorted(gen.files, key=lambda f: f.path)
        ]
        outcome = {
            "status": "succeeded",
            "error_code": None,
            "error": None,
            "archive_key": key,
            "archive_sha256": hashlib.sha256(zipped).hexdigest(),
            "archive_bytes": len(zipped),
            "files": files,
            "file_count": len(files),
            "summary": {
                "resources": gen.api.crud_resources if gen.target.options.db else [],
                "operations": len(gen.api.operations),
                "models": len(gen.api.models),
            },
        }
    except ForgeError as exc:
        outcome = {"status": "failed", "error_code": exc.code, "error": exc.message}
    except TimeoutError:
        outcome = {
            "status": "failed",
            "error_code": "generation_timeout",
            "error": (
                f"Generating took longer than {container.settings.generation_timeout_s} s. "
                "The spec may be very large; raise GENERATION_TIMEOUT_S or split the spec."
            ),
        }
    except Exception as exc:  # a bug: record it for the user, keep the worker alive
        log.exception("generation raised", extra={"generation_id": str(generation_id)})
        outcome = {
            "status": "failed",
            "error_code": "internal_error",
            "error": (
                f"APIForge hit an unexpected error ({type(exc).__name__}). "
                "Please report it with the spec."
            ),
        }

    async with container.db.sessionmaker() as session:
        current = await session.scalar(
            select(Generation).where(Generation.id == generation_id).with_for_update()
        )
        if current is None:  # the project was deleted while this ran
            await session.rollback()
            if stored:
                with contextlib.suppress(Exception):
                    await container.storage.delete(key)
            log.info(
                "generation deleted while running", extra={"generation_id": str(generation_id)}
            )
            return
        if current.status != "running" or current.attempts != mine:
            await session.rollback()  # another worker owns it now; its result stands
            log.warning(
                "generation lease lost",
                extra={"generation_id": str(generation_id), "attempts": mine},
            )
            return
        for name, value in outcome.items():
            setattr(current, name, value)
        current.lease_until = None
        current.finished_at = datetime.now(UTC)
        current.duration_ms = int((time.perf_counter() - started) * 1000)
        await session.commit()
        g = current
    if g.status == "failed":
        _log_failure(g)
    metrics.GENERATIONS.labels(g.status).inc()
    metrics.GENERATION_SECONDS.observe(time.perf_counter() - started)


async def process(container: Container) -> int:
    """One worker pass: claim and run as many generations as the concurrency allows."""
    ids = await claim(container, container.settings.worker_concurrency)
    if ids:
        await asyncio.gather(*(run(container, i) for i in ids))
    return len(ids)


async def requeue_stuck(session: AsyncSession) -> int:
    """For tests and operations: put running generations without a lease back in the queue."""
    result = await session.execute(
        update(Generation)
        .where(Generation.status == "running", Generation.lease_until.is_(None))
        .values(status="queued")
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
