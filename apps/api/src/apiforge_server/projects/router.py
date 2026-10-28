"""Projects, spec versions, the lint playground and the bundled examples."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile

from apiforge_server.auth.dependencies import Admin, Viewer
from apiforge_server.core.deps import ContainerDep, SessionDep
from apiforge_server.projects import service
from apiforge_server.projects.schemas import (
    ExampleOut,
    ExampleSpecOut,
    FromExampleIn,
    LintIn,
    LintOut,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    SpecContent,
    SpecDiff,
    SpecUploaded,
    SpecVersionDetail,
    SpecVersionOut,
)

router = APIRouter(prefix="/api/v1", tags=["projects"])


@router.get("/projects", response_model=list[ProjectOut], summary="Every project, latest first")
async def list_projects(_: Viewer, session: SessionDep) -> list[ProjectOut]:
    return await service.list_projects(session)


@router.post("/projects", response_model=ProjectOut, status_code=201, summary="Create a project")
async def create_project(data: ProjectIn, actor: Admin, session: SessionDep) -> ProjectOut:
    return await service.create_project(session, data, actor)


@router.get("/projects/{slug}", response_model=ProjectOut, summary="A project")
async def get_project(slug: str, _: Viewer, session: SessionDep) -> ProjectOut:
    return await service.project_out(session, await service.get_project(session, slug))


@router.patch(
    "/projects/{slug}", response_model=ProjectOut, summary="Rename a project or change its defaults"
)
async def update_project(
    slug: str, data: ProjectPatch, actor: Admin, session: SessionDep
) -> ProjectOut:
    return await service.update_project(session, slug, data, actor)


@router.delete(
    "/projects/{slug}", status_code=204, summary="Delete a project, its specs and archives"
)
async def delete_project(
    slug: str, actor: Admin, session: SessionDep, container: ContainerDep
) -> Response:
    await service.delete_project(session, container, slug, actor)
    return Response(status_code=204)


@router.post(
    "/projects/{slug}/specs",
    response_model=SpecUploaded,
    responses={200: {"description": "This exact spec is already a version of the project"}},
    status_code=201,
    summary="Upload a spec version (a .yaml or .json file, or a zip with relative $refs)",
)
async def upload_spec(
    slug: str,
    actor: Admin,
    session: SessionDep,
    container: ContainerDep,
    response: Response,
    file: Annotated[UploadFile, File(description="openapi.yaml, openapi.json or a zip")],
    note: Annotated[str, Form(max_length=500)] = "",
) -> SpecUploaded:
    data = await file.read(container.settings.max_spec_bytes + 1)
    created, spec = await service.upload_spec(
        session, container, slug, data, file.filename or "openapi.yaml", note, actor
    )
    if not created:
        response.status_code = 200
    return SpecUploaded(created=created, spec=spec)


@router.post(
    "/projects/{slug}/specs/text",
    response_model=SpecUploaded,
    status_code=201,
    summary="Upload a spec version as text (what the web app's editor sends)",
)
async def upload_spec_text(
    slug: str,
    data: LintIn,
    actor: Admin,
    session: SessionDep,
    container: ContainerDep,
    response: Response,
) -> SpecUploaded:
    created, spec = await service.upload_spec(
        session, container, slug, data.content.encode(), data.filename, "", actor
    )
    if not created:
        response.status_code = 200
    return SpecUploaded(created=created, spec=spec)


@router.get(
    "/projects/{slug}/specs",
    response_model=list[SpecVersionOut],
    summary="Spec versions, newest first",
)
async def list_specs(slug: str, _: Viewer, session: SessionDep) -> list[SpecVersionOut]:
    return await service.list_specs(session, slug)


@router.get(
    "/projects/{slug}/specs/{number}",
    response_model=SpecVersionDetail,
    summary="A spec version: its report, operations, tags and security schemes",
)
async def get_spec(slug: str, number: int, _: Viewer, session: SessionDep) -> SpecVersionDetail:
    return await service.spec_detail(session, slug, number)


@router.get(
    "/projects/{slug}/specs/{number}/content", response_model=SpecContent, summary="The spec's text"
)
async def spec_content(
    slug: str,
    number: int,
    _: Viewer,
    session: SessionDep,
    container: ContainerDep,
    request: Request,
) -> SpecContent:
    return await service.spec_content(session, container, slug, number)


@router.get(
    "/projects/{slug}/diff",
    response_model=SpecDiff,
    summary="What changed between two spec versions",
)
async def spec_diff(
    slug: str,
    _: Viewer,
    session: SessionDep,
    base: Annotated[int, Query(ge=1)],
    head: Annotated[int, Query(ge=1)],
) -> SpecDiff:
    return await service.spec_diff(session, slug, base, head)


@router.post(
    "/lint", response_model=LintOut, summary="Lint a spec without saving it (the playground)"
)
async def lint(data: LintIn, _: Viewer, container: ContainerDep) -> LintOut:
    return await service.lint_text(container, data.content, data.filename)


@router.get(
    "/examples",
    response_model=list[ExampleOut],
    summary="The example specs that ship with APIForge",
)
async def list_examples(_: Viewer, container: ContainerDep) -> list[ExampleOut]:
    return await service.list_examples(container)


@router.get(
    "/examples/{name}",
    response_model=ExampleSpecOut,
    summary="One bundled example spec, with its text",
)
async def get_example(name: str, _: Viewer) -> ExampleSpecOut:
    return ExampleSpecOut(name=name, content=service.example_bytes(name).decode())


@router.post(
    "/projects/from-example",
    response_model=ProjectOut,
    status_code=201,
    summary="Create a project from a bundled example, with its spec as version 1",
)
async def from_example(
    data: FromExampleIn, actor: Admin, session: SessionDep, container: ContainerDep
) -> ProjectOut:
    raw = service.example_bytes(data.example)
    analysis_title = (await service.lint_text(container, raw.decode(), data.example)).title
    project = await service.create_project(
        session, ProjectIn(name=data.name or analysis_title), actor
    )
    await service.upload_spec(
        session, container, project.slug, raw, data.example, "From the bundled example", actor
    )
    return await service.project_out(session, await service.get_project(session, project.slug))
