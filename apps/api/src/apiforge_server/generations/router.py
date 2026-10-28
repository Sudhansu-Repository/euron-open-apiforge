"""Generations: request one, follow it, browse its files, download the archive."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from apiforge_server.auth.dependencies import Admin, Viewer
from apiforge_server.core.deps import ContainerDep, SessionDep
from apiforge_server.generations import service
from apiforge_server.generations.schemas import (
    FileContent,
    GenerationDetail,
    GenerationIn,
    GenerationOut,
)

router = APIRouter(prefix="/api/v1", tags=["generations"])
# An archive never changes, but its URL (slug and number) can be reused after a project is
# deleted and another takes its slug, so caches revalidate every time: a matching ETag gets
# a 304 without reading storage, which is what makes revalidating cheap.
REVALIDATE = "private, no-cache"


@router.post(
    "/projects/{slug}/generations",
    response_model=GenerationOut,
    status_code=202,
    summary="Generate a project from a spec version (queued for the worker)",
)
async def create_generation(
    slug: str, data: GenerationIn, actor: Admin, session: SessionDep
) -> GenerationOut:
    return await service.create_generation(session, slug, data, actor)


@router.get(
    "/projects/{slug}/generations",
    response_model=list[GenerationOut],
    summary="Generations, newest first",
)
async def list_generations(
    slug: str, _: Viewer, session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[GenerationOut]:
    return await service.list_generations(session, slug, limit)


@router.get(
    "/projects/{slug}/generations/{number}",
    response_model=GenerationDetail,
    summary="A generation and its files",
)
async def get_generation(
    slug: str, number: int, _: Viewer, session: SessionDep
) -> GenerationDetail:
    return await service.get_generation(session, slug, number)


@router.get(
    "/projects/{slug}/generations/{number}/archive",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}, "description": "The generated project"}},
    summary="Download the generated project as a zip",
)
async def download(
    slug: str,
    number: int,
    _: Viewer,
    session: SessionDep,
    container: ContainerDep,
    request: Request,
) -> Response:
    data, sha, filename = await service.archive(
        session, container, slug, number, request.headers.get("if-none-match")
    )
    headers = {"etag": service.etag(sha), "cache-control": REVALIDATE}
    if data is None:
        return Response(status_code=304, headers=headers)
    headers["content-disposition"] = f'attachment; filename="{filename}"'
    return Response(content=data, media_type="application/zip", headers=headers)


@router.get(
    "/projects/{slug}/generations/{number}/file",
    response_model=FileContent,
    summary="One file of a generated project",
)
async def get_file(
    slug: str,
    number: int,
    _: Viewer,
    session: SessionDep,
    container: ContainerDep,
    request: Request,
    path: Annotated[str, Query(min_length=1, max_length=500)],
) -> FileContent | Response:
    content, sha = await service.file_content(
        session, container, slug, number, path, request.headers.get("if-none-match")
    )
    headers = {"etag": service.etag(sha, path), "cache-control": REVALIDATE}
    if content is None:
        return Response(status_code=304, headers=headers)
    return JSONResponse(content.model_dump(mode="json"), headers=headers)
