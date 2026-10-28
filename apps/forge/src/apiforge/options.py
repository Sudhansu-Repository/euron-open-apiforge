"""Generation options: everything that changes the output, recorded in ``apiforge.lock``."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from apiforge.naming import words


@dataclass(frozen=True)
class GenerateOptions:
    project_name: str | None = None  # default: derived from the spec title
    db: bool = False  # SQLAlchemy models, Alembic and CRUD handlers for collection resources
    docker: bool = True
    ci: bool = True

    def slug(self, title: str) -> str:
        return "-".join(words(self.project_name or title)) or "api"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerateOptions:
        known = {k: data[k] for k in ("project_name", "db", "docker", "ci") if k in data}
        return cls(**known)
