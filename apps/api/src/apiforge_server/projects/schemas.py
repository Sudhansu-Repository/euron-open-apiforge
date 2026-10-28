"""The public contract of projects, spec versions and the lint playground."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from apiforge_server.core.schemas import ApiModel

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Severity = Literal["error", "warning", "info"]


class GenerationOptions(ApiModel):
    """What changes the generated project (recorded in its apiforge.lock)."""

    project_name: Annotated[str, StringConstraints(max_length=80)] | None = Field(
        None, description="Package name; default: from the spec title"
    )
    db: bool = Field(
        False, description="SQLAlchemy models, Alembic and CRUD for collection resources"
    )
    docker: bool = Field(True, description="Dockerfile and compose.yaml")
    ci: bool = Field(True, description="GitHub Actions workflow")


class Finding(ApiModel):
    severity: Severity
    code: str
    message: str
    pointer: str


class OperationSummary(ApiModel):
    method: str
    path: str
    operation_id: str
    function: str
    tag: str
    summary: str
    deprecated: bool
    secured: bool
    schemes: list[str]
    responses: list[str]


class TagSummary(ApiModel):
    name: str
    description: str
    operations: int


class SchemeSummary(ApiModel):
    name: str
    kind: str


class SpecChanges(ApiModel):
    first: bool = Field(description="The project's first version: everything is new")
    added: list[str]
    removed: list[str]
    changed: list[dict[str, Any]] = Field(
        description=(
            "[{operation, parts}]: parts is any of parameters, request body, responses, security"
        )
    )


class ProjectIn(ApiModel):
    name: Name
    description: Annotated[str, StringConstraints(max_length=2000)] = ""
    default_options: GenerationOptions = Field(default_factory=GenerationOptions)


class ProjectPatch(ApiModel):
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    default_options: GenerationOptions | None = None


class LatestSpec(ApiModel):
    id: uuid.UUID
    number: int
    title: str
    api_version: str
    operations: int
    errors: int
    warnings: int
    created_at: datetime


class LatestGeneration(ApiModel):
    id: uuid.UUID
    number: int
    status: str
    created_at: datetime
    finished_at: datetime | None


class ProjectOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    default_options: GenerationOptions
    created_at: datetime
    updated_at: datetime
    spec_count: int = 0
    generation_count: int = 0
    latest_spec: LatestSpec | None = None
    latest_generation: LatestGeneration | None = None


class SpecVersionOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    number: int
    filename: str
    bundle: bool
    sha256: str
    size_bytes: int
    title: str
    api_version: str
    openapi_version: str
    operations: int
    models: int
    errors: int
    warnings: int
    note: str
    changes: SpecChanges
    created_at: datetime
    created_by_email: str | None = None


class SpecVersionDetail(SpecVersionOut):
    report: list[Finding]
    operation_list: list[OperationSummary]
    tags: list[TagSummary]
    schemes: list[SchemeSummary]
    model_names: list[str]


class SpecUploaded(ApiModel):
    created: bool = Field(
        description="False when this exact spec was already the latest or an earlier version"
    )
    spec: SpecVersionDetail


class SpecContent(ApiModel):
    filename: str
    content: str
    files: list[str] = Field(default_factory=list, description="Every file of a zip bundle")


class SpecDiff(ApiModel):
    base: int
    head: int
    changes: SpecChanges


class LintIn(ApiModel):
    # Bounded by MAX_SPEC_BYTES in the service (and MAX_BODY_BYTES before parsing), so the
    # limit follows the configuration instead of being fixed here.
    content: Annotated[str, StringConstraints(min_length=1)]
    filename: Annotated[str, StringConstraints(max_length=255)] = "openapi.yaml"


class LintOut(ApiModel):
    title: str
    api_version: str
    openapi_version: str
    sha256: str
    counts: dict[str, int]
    report: list[Finding]
    operations: list[OperationSummary]
    tags: list[TagSummary]
    schemes: list[SchemeSummary]
    models: list[str]


class ExampleOut(ApiModel):
    name: str
    title: str
    description: str
    operations: int
    features: list[str]


class ExampleSpecOut(ApiModel):
    name: str
    content: str


class FromExampleIn(ApiModel):
    example: Annotated[str, StringConstraints(max_length=80)]
    name: Name | None = None
