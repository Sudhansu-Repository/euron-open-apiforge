"""The public contract of generations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from apiforge_server.core.schemas import ApiModel
from apiforge_server.projects.schemas import GenerationOptions


class GenerationIn(ApiModel):
    spec_number: int | None = Field(
        None, ge=1, description="Spec version to generate from; default: the latest"
    )
    options: GenerationOptions | None = Field(
        None, description="Default: the project's default options"
    )
    accept_report: bool = Field(
        False,
        description="Generate even when the lint report has errors (those parts are left out)",
    )


class GeneratedFileOut(ApiModel):
    path: str
    owner: Literal["generated", "user"]
    bytes: int


class GenerationOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_slug: str
    number: int
    spec_number: int
    spec_title: str
    options: GenerationOptions
    accept_report: bool
    status: Literal["queued", "running", "succeeded", "failed"]
    attempts: int
    error_code: str | None
    error: str | None
    archive_sha256: str | None
    archive_bytes: int | None
    file_count: int | None
    duration_ms: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_by_email: str | None = None


class GenerationDetail(GenerationOut):
    files: list[GeneratedFileOut]
    resources: list[str] = Field(
        default_factory=list, description="Collection resources implemented with --db"
    )


class FileContent(ApiModel):
    path: str
    owner: Literal["generated", "user"]
    content: str
    language: str
