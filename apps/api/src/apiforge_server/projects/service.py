"""Projects and spec versions: the business rules.

A spec upload is linted before anything is stored, so a version always has a report; the
same bytes uploaded again return the existing version instead of a duplicate (uploads are
idempotent, which matters for CI that pushes the spec on every commit). Spec bodies live in
object storage under ``specs/<project>/<version>/``; rows keep the key and the analysis.
"""

from __future__ import annotations

import io
import re
import unicodedata
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apiforge.cli import CORPUS
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apiforge_server.audit.service import Actor, audit
from apiforge_server.core.container import Container
from apiforge_server.core.errors import AppError, ConflictError, NotFoundError
from apiforge_server.generations.models import Generation
from apiforge_server.observability import metrics
from apiforge_server.projects.analysis import Analysis, analyze, changes_between
from apiforge_server.projects.models import Project, SpecVersion
from apiforge_server.projects.schemas import (
    ExampleOut,
    GenerationOptions,
    LatestGeneration,
    LatestSpec,
    LintOut,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    SpecChanges,
    SpecContent,
    SpecDiff,
    SpecVersionDetail,
    SpecVersionOut,
)
from apiforge_server.users.models import User

SPEC_SUFFIXES = (".yaml", ".yml", ".json", ".zip")
_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")

EXAMPLE_FEATURES = {
    "petstore.yaml": ["CRUD", "bearer auth", "enums", "patterns", "readOnly fields"],
    "bookstore.yaml": [
        "OpenAPI 3.1",
        "discriminated unions",
        "file upload",
        "forms",
        "OAuth2 scopes",
    ],
    "inventory.yaml": ["CRUD with --db", "UUID ids", "PATCH", "paging and filters"],
    "secure-notes.yaml": ["every security scheme", "optional auth", "scopes", "API key in cookie"],
    "edge-cases.yaml": ["the lint report", "deepObject", "callbacks", "webhooks", "XML alternates"],
}


class SpecTooLargeError(AppError):
    status_code = 413
    code = "spec_too_large"


# ── projects ─────────────────────────────────────────────────────────────────


def _slugify(name: str) -> str:
    """A project's address: the name in lower case, words joined by dashes. Unlike code
    identifiers, a name is not split on case changes ("E2E Tests" is ``e2e-tests``)."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:60].strip("-") or "project"


async def _unique_slug(session: AsyncSession, name: str) -> str:
    base = _slugify(name)
    taken = set(
        (await session.scalars(select(Project.slug).where(Project.slug.like(f"{base}%")))).all()
    )
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


async def get_project(session: AsyncSession, slug: str) -> Project:
    project = await session.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        raise NotFoundError(f"No project {slug!r}. Check the address, or create it first.")
    return project


async def project_out(session: AsyncSession, project: Project) -> ProjectOut:
    return (await _projects_out(session, [project]))[0]


async def _projects_out(session: AsyncSession, projects: list[Project]) -> list[ProjectOut]:
    """Projects with counts and their latest spec and generation: four queries in total."""
    if not projects:
        return []
    ids = [p.id for p in projects]
    spec_counts = dict(
        (
            await session.execute(
                select(SpecVersion.project_id, func.count())
                .where(SpecVersion.project_id.in_(ids))
                .group_by(SpecVersion.project_id)
            )
        ).all()
    )
    gen_counts = dict(
        (
            await session.execute(
                select(Generation.project_id, func.count())
                .where(Generation.project_id.in_(ids))
                .group_by(Generation.project_id)
            )
        ).all()
    )
    latest_spec_ids = (
        select(func.max(SpecVersion.number).label("n"), SpecVersion.project_id)
        .where(SpecVersion.project_id.in_(ids))
        .group_by(SpecVersion.project_id)
        .subquery()
    )
    specs = {
        s.project_id: s
        for s in (
            await session.scalars(
                select(SpecVersion).join(
                    latest_spec_ids,
                    (SpecVersion.project_id == latest_spec_ids.c.project_id)
                    & (SpecVersion.number == latest_spec_ids.c.n),
                )
            )
        ).all()
    }
    latest_gen_ids = (
        select(func.max(Generation.number).label("n"), Generation.project_id)
        .where(Generation.project_id.in_(ids))
        .group_by(Generation.project_id)
        .subquery()
    )
    gens = {
        g.project_id: g
        for g in (
            await session.scalars(
                select(Generation).join(
                    latest_gen_ids,
                    (Generation.project_id == latest_gen_ids.c.project_id)
                    & (Generation.number == latest_gen_ids.c.n),
                )
            )
        ).all()
    }
    out = []
    for p in projects:
        spec = specs.get(p.id)
        gen = gens.get(p.id)
        out.append(
            ProjectOut(
                id=p.id,
                slug=p.slug,
                name=p.name,
                description=p.description,
                default_options=GenerationOptions.model_validate(p.default_options or {}),
                created_at=p.created_at,
                updated_at=p.updated_at,
                spec_count=spec_counts.get(p.id, 0),
                generation_count=gen_counts.get(p.id, 0),
                latest_spec=LatestSpec.model_validate(spec) if spec else None,
                latest_generation=LatestGeneration.model_validate(gen) if gen else None,
            )
        )
    return out


async def list_projects(session: AsyncSession) -> list[ProjectOut]:
    projects = list(
        (await session.scalars(select(Project).order_by(Project.updated_at.desc()))).all()
    )
    return await _projects_out(session, projects)


async def create_project(session: AsyncSession, data: ProjectIn, actor: Actor) -> ProjectOut:
    for _ in range(3):  # two people creating "Payments" at once both get a slug
        project = Project(
            slug=await _unique_slug(session, data.name),
            name=data.name,
            description=data.description,
            default_options=data.default_options.model_dump(),
            created_by=actor.id,
        )
        session.add(project)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue
        audit(session, actor, "project.created", "project", project.id, name=project.name)
        await session.commit()
        await session.refresh(project)
        return await project_out(session, project)
    raise ConflictError("Could not pick a unique project address; try another name.")


async def update_project(
    session: AsyncSession, slug: str, data: ProjectPatch, actor: Actor
) -> ProjectOut:
    project = await get_project(session, slug)
    changed: dict[str, Any] = {}
    if data.name is not None and data.name != project.name:
        project.name = data.name
        changed["name"] = data.name
    if data.description is not None:
        project.description = data.description
        changed["description"] = True
    if data.default_options is not None:
        project.default_options = data.default_options.model_dump()
        changed["default_options"] = project.default_options
    if changed:
        audit(session, actor, "project.updated", "project", project.id, **changed)
        await session.commit()
        await session.refresh(project)
    return await project_out(session, project)


async def delete_project(
    session: AsyncSession, container: Container, slug: str, actor: Actor
) -> None:
    project = await get_project(session, slug)
    keys = list(
        (
            await session.scalars(
                select(SpecVersion.storage_key).where(SpecVersion.project_id == project.id)
            )
        ).all()
    )
    keys += [
        k
        for k in (
            await session.scalars(
                select(Generation.archive_key).where(Generation.project_id == project.id)
            )
        ).all()
        if k
    ]
    audit(
        session,
        actor,
        "project.deleted",
        "project",
        project.id,
        name=project.name,
        slug=project.slug,
    )
    await session.delete(project)
    await session.commit()
    for key in keys:  # best effort after the commit: the rows are gone either way
        try:
            await container.storage.delete(key)
        except Exception:
            metrics.DEPENDENCY_ERRORS.labels("storage", "delete").inc()


# ── spec versions ────────────────────────────────────────────────────────────


def _safe_filename(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name or "openapi.yaml"
    name = _FILENAME.sub("-", name)[:120]
    if not name.lower().endswith(SPEC_SUFFIXES):
        name += ".yaml"
    return name


async def _emails(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.email).where(User.id.in_(ids)))
    return dict(rows.all())


def _version_out(v: SpecVersion, email: str | None) -> SpecVersionOut:
    return SpecVersionOut(
        id=v.id,
        project_id=v.project_id,
        number=v.number,
        filename=v.filename,
        bundle=v.bundle,
        sha256=v.sha256,
        size_bytes=v.size_bytes,
        title=v.title,
        api_version=v.api_version,
        openapi_version=v.openapi_version,
        operations=v.operations,
        models=v.models,
        errors=v.errors,
        warnings=v.warnings,
        note=v.note,
        changes=SpecChanges.model_validate(
            v.changes or {"first": True, "added": [], "removed": [], "changed": []}
        ),
        created_at=v.created_at,
        created_by_email=email,
    )


def version_detail(v: SpecVersion, email: str | None) -> SpecVersionDetail:
    base = _version_out(v, email)
    summary = v.summary or {}
    return SpecVersionDetail(
        **base.model_dump(),
        report=v.report or [],
        operation_list=summary.get("operations", []),
        tags=summary.get("tags", []),
        schemes=summary.get("schemes", []),
        model_names=summary.get("models", []),
    )


async def upload_spec(
    session: AsyncSession,
    container: Container,
    slug: str,
    data: bytes,
    filename: str,
    note: str,
    actor: Actor,
) -> tuple[bool, SpecVersionDetail]:
    """Lint and store a spec; (created, version). The same bytes return the existing version."""
    project = await get_project(session, slug)
    project_id = project.id  # read once: a rollback below expires the instance
    _check_size(container, data)
    filename = _safe_filename(filename)
    try:
        analysis = await analyze(container.kv, data, filename)
    except AppError:
        metrics.SPECS_UPLOADED.labels("rejected").inc()
        raise
    existing = await session.scalar(
        select(SpecVersion).where(
            SpecVersion.project_id == project.id, SpecVersion.sha256 == analysis.sha256
        )
    )
    if existing is not None:
        metrics.SPECS_UPLOADED.labels("unchanged").inc()
        emails = await _emails(session, {existing.created_by} if existing.created_by else set())
        return False, version_detail(
            existing, emails.get(existing.created_by) if existing.created_by else None
        )
    previous = await session.scalar(
        select(SpecVersion)
        .where(SpecVersion.project_id == project.id)
        .order_by(SpecVersion.number.desc())
        .limit(1)
    )
    number = (previous.number + 1) if previous else 1
    version_id = uuid.uuid4()
    key = f"specs/{project.id}/{version_id}/{filename}"
    content_type = (
        "application/zip" if filename.lower().endswith(".zip") else "text/plain; charset=utf-8"
    )
    await container.storage.put(key, data, content_type)
    version = _new_version(
        project, version_id, number, filename, key, data, analysis, previous, note, actor
    )
    session.add(version)
    project.updated_at = datetime.now(UTC)
    try:
        await session.flush()
    except IntegrityError as exc:
        # A concurrent upload won the race. Same bytes: that version is ours too (uploads
        # are idempotent). Otherwise it took this number: the client sends it again.
        await session.rollback()
        try:
            await container.storage.delete(key)
        except Exception:
            metrics.DEPENDENCY_ERRORS.labels("storage", "delete").inc()
        winner = await session.scalar(
            select(SpecVersion).where(
                SpecVersion.project_id == project_id, SpecVersion.sha256 == analysis.sha256
            )
        )
        if winner is not None:
            metrics.SPECS_UPLOADED.labels("unchanged").inc()
            return False, version_detail(winner, None)
        raise ConflictError(
            "Another version was uploaded at the same moment; send it again."
        ) from exc
    audit(
        session,
        actor,
        "spec.uploaded",
        "spec_version",
        version.id,
        project=project.slug,
        number=number,
        title=analysis.title,
        operations=len(analysis.operations),
    )
    await session.commit()
    await session.refresh(version)
    metrics.SPECS_UPLOADED.labels("stored").inc()
    return True, version_detail(version, actor.email)


def _new_version(
    project: Project,
    version_id: uuid.UUID,
    number: int,
    filename: str,
    key: str,
    data: bytes,
    analysis: Analysis,
    previous: SpecVersion | None,
    note: str,
    actor: Actor,
) -> SpecVersion:
    return SpecVersion(
        id=version_id,
        project_id=project.id,
        number=number,
        filename=filename,
        bundle=filename.lower().endswith(".zip"),
        storage_key=key,
        sha256=analysis.sha256,
        size_bytes=len(data),
        title=analysis.title[:300],
        api_version=analysis.api_version[:100],
        openapi_version=analysis.openapi_version[:20],
        operations=len(analysis.operations),
        models=len(analysis.models),
        errors=analysis.counts.get("error", 0),
        warnings=analysis.counts.get("warning", 0),
        report=analysis.report,
        summary=analysis.summary,
        changes=changes_between(previous.summary if previous else None, analysis),
        note=note[:500],
        created_by=actor.id,
    )


async def list_specs(session: AsyncSession, slug: str) -> list[SpecVersionOut]:
    project = await get_project(session, slug)
    versions = list(
        (
            await session.scalars(
                select(SpecVersion)
                .where(SpecVersion.project_id == project.id)
                .order_by(SpecVersion.number.desc())
            )
        ).all()
    )
    emails = await _emails(session, {v.created_by for v in versions if v.created_by})
    return [_version_out(v, emails.get(v.created_by) if v.created_by else None) for v in versions]


async def get_version(session: AsyncSession, slug: str, number: int) -> SpecVersion:
    project = await get_project(session, slug)
    version = await session.scalar(
        select(SpecVersion).where(
            SpecVersion.project_id == project.id, SpecVersion.number == number
        )
    )
    if version is None:
        raise NotFoundError(f"{slug} has no spec version {number}.")
    return version


async def spec_detail(session: AsyncSession, slug: str, number: int) -> SpecVersionDetail:
    v = await get_version(session, slug, number)
    emails = await _emails(session, {v.created_by} if v.created_by else set())
    return version_detail(v, emails.get(v.created_by) if v.created_by else None)


async def spec_content(
    session: AsyncSession, container: Container, slug: str, number: int
) -> SpecContent:
    v = await get_version(session, slug, number)
    data = await container.storage.get(v.storage_key)
    if not v.bundle:
        return SpecContent(filename=v.filename, content=data.decode("utf-8", "replace"))
    from apiforge.bundles import read_zip

    root, name, files = read_zip(data)
    return SpecContent(filename=name, content=root.decode("utf-8", "replace"), files=sorted(files))


async def spec_diff(session: AsyncSession, slug: str, base: int, head: int) -> SpecDiff:
    a = await get_version(session, slug, base)
    b = await get_version(session, slug, head)
    fingerprints_a = (a.summary or {}).get("fingerprints") or {}
    fingerprints_b = (b.summary or {}).get("fingerprints") or {}
    changed = []
    for key in sorted(set(fingerprints_a) & set(fingerprints_b)):
        parts = [
            p for p in fingerprints_b[key] if fingerprints_a[key].get(p) != fingerprints_b[key][p]
        ]
        if parts:
            changed.append({"operation": key, "parts": parts})
    return SpecDiff(
        base=base,
        head=head,
        changes=SpecChanges(
            first=False,
            added=sorted(set(fingerprints_b) - set(fingerprints_a)),
            removed=sorted(set(fingerprints_a) - set(fingerprints_b)),
            changed=changed,
        ),
    )


def _check_size(container: Container, data: bytes) -> None:
    limit = container.settings.max_spec_bytes
    if len(data) > limit:
        raise SpecTooLargeError(
            f"The spec is {len(data) // 1024} KiB; the limit is {limit // 1024} KiB "
            "(MAX_SPEC_BYTES). Split it into files with relative $refs and upload a zip."
        )


# ── playground and examples ──────────────────────────────────────────────────


async def lint_text(container: Container, content: str, filename: str) -> LintOut:
    data = content.encode("utf-8")
    _check_size(container, data)
    a = await analyze(container.kv, data, _safe_filename(filename))
    return LintOut(
        title=a.title,
        api_version=a.api_version,
        openapi_version=a.openapi_version,
        sha256=a.sha256,
        counts=a.counts,
        report=a.report,
        operations=a.operations,
        tags=a.tags,
        schemes=a.schemes,
        models=a.models,
    )


def _examples() -> list[Path]:
    return sorted(p for p in CORPUS.iterdir() if p.suffix in (".yaml", ".json"))


async def list_examples(container: Container) -> list[ExampleOut]:
    out = []
    for path in _examples():
        a = await analyze(container.kv, path.read_bytes(), path.name)
        out.append(
            ExampleOut(
                name=path.name,
                title=a.title,
                description=(a_description(path) or "")[:300],
                operations=len(a.operations),
                features=EXAMPLE_FEATURES.get(path.name, []),
            )
        )
    return out


def a_description(path: Path) -> str:
    import yaml

    doc = yaml.safe_load(path.read_text())
    info = doc.get("info") if isinstance(doc, dict) else None
    return " ".join(str((info or {}).get("description") or "").split())


def example_bytes(name: str) -> bytes:
    for path in _examples():
        if path.name == name:
            return path.read_bytes()
    raise NotFoundError(f"There is no example {name!r}. GET /api/v1/examples lists them.")


def zip_of(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    return buf.getvalue()
