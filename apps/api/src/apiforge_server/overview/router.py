"""The dashboard's first screen: what exists and what happened lately."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from apiforge_server.auth.dependencies import Viewer
from apiforge_server.core.deps import SessionDep
from apiforge_server.core.schemas import ApiModel
from apiforge_server.generations import service as generations
from apiforge_server.generations.models import Generation
from apiforge_server.generations.schemas import GenerationOut
from apiforge_server.projects.models import Project, SpecVersion

router = APIRouter(prefix="/api/v1", tags=["overview"])


class SpecChange(ApiModel):
    project_slug: str
    project_name: str
    number: int
    title: str
    api_version: str
    added: int
    removed: int
    changed: int
    errors: int
    warnings: int
    created_at: datetime


class Overview(ApiModel):
    projects: int
    spec_versions: int
    operations: int
    generations: int
    generations_7d: int
    succeeded_7d: int
    failed_7d: int
    queued: int
    median_duration_ms: int | None
    recent_generations: list[GenerationOut]
    recent_specs: list[SpecChange]


@router.get("/overview", response_model=Overview, summary="Counts and recent activity")
async def overview(_: Viewer, session: SessionDep) -> Overview:
    week = datetime.now(UTC) - timedelta(days=7)
    projects = await session.scalar(select(func.count()).select_from(Project)) or 0
    specs = await session.scalar(select(func.count()).select_from(SpecVersion)) or 0
    latest = (
        select(func.max(SpecVersion.number).label("n"), SpecVersion.project_id)
        .group_by(SpecVersion.project_id)
        .subquery()
    )
    operations = (
        await session.scalar(
            select(func.coalesce(func.sum(SpecVersion.operations), 0)).join(
                latest,
                (SpecVersion.project_id == latest.c.project_id)
                & (SpecVersion.number == latest.c.n),
            )
        )
        or 0
    )
    total = await session.scalar(select(func.count()).select_from(Generation)) or 0
    week_rows = (
        await session.execute(
            select(Generation.status, func.count())
            .where(Generation.created_at >= week)
            .group_by(Generation.status)
        )
    ).all()
    by_status = dict(week_rows)
    queued = await session.scalar(select(func.count()).where(Generation.status == "queued")) or 0
    median = await session.scalar(
        select(func.percentile_cont(0.5).within_group(Generation.duration_ms)).where(
            Generation.status == "succeeded", Generation.created_at >= week
        )
    )
    spec_rows = (
        await session.execute(
            select(SpecVersion, Project)
            .join(Project, Project.id == SpecVersion.project_id)
            .order_by(SpecVersion.created_at.desc())
            .limit(8)
        )
    ).all()
    return Overview(
        projects=projects,
        spec_versions=specs,
        operations=int(operations),
        generations=total,
        generations_7d=sum(by_status.values()),
        succeeded_7d=by_status.get("succeeded", 0),
        failed_7d=by_status.get("failed", 0),
        queued=queued,
        median_duration_ms=int(median) if median is not None else None,
        recent_generations=await generations.recent_generations(session, 8),
        recent_specs=[
            SpecChange(
                project_slug=p.slug,
                project_name=p.name,
                number=v.number,
                title=v.title,
                api_version=v.api_version,
                added=len((v.changes or {}).get("added", [])),
                removed=len((v.changes or {}).get("removed", [])),
                changed=len((v.changes or {}).get("changed", [])),
                errors=v.errors,
                warnings=v.warnings,
                created_at=v.created_at,
            )
            for v, p in spec_rows
        ],
    )
