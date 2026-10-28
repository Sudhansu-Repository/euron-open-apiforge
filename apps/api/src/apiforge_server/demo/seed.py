"""``apiforge-server seed-demo``: a team that has been using APIForge for a while.

Users with each role, a read-only API key, and one project per example spec that ships
with the generator. Two projects get a spec history: their earlier versions are the same
example with some operations and fields taken out, so the version list, the diffs and the
regeneration story have something real to show. Every generation is queued through the
service and run by the same code the worker runs, so each archive is a real generation.
Running it twice changes nothing.
"""

from __future__ import annotations

import asyncio
import copy
import os
from typing import Any

import yaml
from apiforge.cli import CORPUS
from sqlalchemy import func, select

from apiforge_server.audit.service import Actor
from apiforge_server.core.config import get_settings
from apiforge_server.core.container import Container
from apiforge_server.core.security import hash_password
from apiforge_server.generations import service as generations
from apiforge_server.generations.schemas import GenerationIn
from apiforge_server.keys import service as key_service
from apiforge_server.keys.schemas import KeyIn
from apiforge_server.projects import service as projects
from apiforge_server.projects.models import Project
from apiforge_server.projects.schemas import GenerationOptions, ProjectIn
from apiforge_server.users.models import User

OWNER_EMAIL = "owner@apiforge.local"
USERS = (
    (OWNER_EMAIL, "Priya Raman", "owner"),
    ("admin@apiforge.local", "Marco Silva", "admin"),
    ("viewer@apiforge.local", "Dana Okafor", "viewer"),
)


def _load(name: str) -> dict[str, Any]:
    doc = yaml.safe_load((CORPUS / name).read_text())
    assert isinstance(doc, dict)
    return doc


def _dump(doc: dict[str, Any]) -> bytes:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).encode()


def _petstore_history() -> list[tuple[bytes, str]]:
    final = _load("petstore.yaml")
    v1 = copy.deepcopy(final)
    v1["info"]["version"] = "0.9.0"
    del v1["paths"]["/pets/{petId}"]["delete"]
    del v1["components"]["schemas"]["Pet"]["properties"]["birthday"]
    del v1["paths"]["/pets"]["get"]["parameters"][2]  # the tags filter
    v2 = copy.deepcopy(final)
    v2["info"]["version"] = "0.9.5"
    del v2["paths"]["/pets/{petId}"]["delete"]
    return [
        (_dump(v1), "First draft: list, create and read"),
        (_dump(v2), "Birthdays and the tag filter"),
        (_dump(final), "Pets can be removed"),
    ]


def _bookstore_history() -> list[tuple[bytes, str]]:
    final = _load("bookstore.yaml")
    v1 = copy.deepcopy(final)
    v1["info"]["version"] = "2.2.0"
    for path in ("/orders", "/orders/{orderId}", "/orders/{orderId}/invoice"):
        del v1["paths"][path]
    v1["tags"] = [t for t in v1["tags"] if t["name"] != "orders"]
    return [(_dump(v1), "Catalog and accounts"), (_dump(final), "Orders and invoices")]


PROJECTS: list[dict[str, Any]] = [
    {
        "name": "Pet Store",
        "description": "The pet shop's inventory API: the first spec most teams try.",
        "history": _petstore_history,
        "options": GenerationOptions(db=True),
        "generate": [(1, GenerationOptions()), (3, GenerationOptions(db=True))],
    },
    {
        "name": "Bookstore",
        "description": "Online bookstore: printed books, ebooks and audiobooks, accounts and orders.",
        "history": _bookstore_history,
        "options": GenerationOptions(),
        "generate": [(1, GenerationOptions()), (2, GenerationOptions())],
    },
    {
        "name": "Warehouse Inventory",
        "description": "Stock items and suppliers, persisted with SQLAlchemy (--db).",
        "file": "inventory.yaml",
        "options": GenerationOptions(db=True),
        "generate": [(1, GenerationOptions(db=True))],
    },
    {
        "name": "Secure Notes",
        "description": "Every kind of credential OpenAPI describes, mapped to FastAPI security.",
        "file": "secure-notes.yaml",
        "options": GenerationOptions(),
        "generate": [(1, GenerationOptions())],
    },
    {
        "name": "Edge Cases",
        "description": "Constructs APIForge approximates, each one listed in the lint report.",
        "file": "edge-cases.yaml",
        "options": GenerationOptions(docker=False, ci=False),
        "generate": [(1, GenerationOptions(docker=False, ci=False))],
    },
]


async def _users(container: Container, password: str) -> Actor:
    async with container.db.sessionmaker() as session:
        for email, name, role in USERS:
            user = await session.scalar(select(User).where(func.lower(User.email) == email))
            if user is None:
                session.add(
                    User(
                        email=email,
                        name=name,
                        role=role,
                        password_hash=await asyncio.to_thread(hash_password, password),
                    )
                )
        await session.commit()
        owner = await session.scalar(select(User).where(User.email == OWNER_EMAIL))
        admin = await session.scalar(select(User).where(User.email == "admin@apiforge.local"))
        assert owner is not None
        assert admin is not None
        return Actor(admin.id, admin.email, admin.role, None)


async def _key(container: Container) -> str | None:
    async with container.db.sessionmaker() as session:
        actor_row = await session.scalar(select(User).where(User.email == OWNER_EMAIL))
        assert actor_row is not None
        actor = Actor(actor_row.id, actor_row.email, actor_row.role, None)
        existing = await key_service.list_keys(session, include_revoked=False)
        if any(k.name == "CI download (read only)" for k in existing):
            return None
        created = await key_service.create_key(
            session, KeyIn(name="CI download (read only)"), container.settings.api_key_pepper, actor
        )
        return created.key


async def _project(container: Container, actor: Actor, spec: dict[str, Any]) -> None:
    async with container.db.sessionmaker() as session:
        if await session.scalar(select(Project.id).where(Project.name == spec["name"])):
            return
        project = await projects.create_project(
            session,
            ProjectIn(
                name=spec["name"], description=spec["description"], default_options=spec["options"]
            ),
            actor,
        )
        versions = (
            spec["history"]()
            if "history" in spec
            else [((CORPUS / spec["file"]).read_bytes(), "From the example spec")]
        )
        filename = spec.get("file", f"{project.slug}.yaml")
        for data, note in versions:
            await projects.upload_spec(
                session, container, project.slug, data, filename, note, actor
            )
        for number, options in spec["generate"]:
            await generations.create_generation(
                session, project.slug, GenerationIn(spec_number=number, options=options), actor
            )
    while await generations.process(container):  # the worker's own code path
        pass


async def run() -> None:
    settings = get_settings()
    password = os.environ.get("DEMO_PASSWORD") or os.environ.get("AF_DEMO_PASSWORD")
    if not password:
        raise SystemExit("Set DEMO_PASSWORD (make demo passes the one from deploy/compose/.env).")
    container = Container.build(settings)
    try:
        actor = await _users(container, password)
        key = await _key(container)
        for spec in PROJECTS:
            await _project(container, actor, spec)
    finally:
        await container.close()
    print("Demo data ready.")
    print(
        "  Sign in at the web app as owner@apiforge.local, admin@apiforge.local or viewer@apiforge.local"
    )
    if key:
        print(f"  Read-only API key (shown once): {key}")
