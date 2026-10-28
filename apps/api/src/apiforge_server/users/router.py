from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter

from apiforge_server.auth.dependencies import Admin, Owner
from apiforge_server.auth.schemas import UserOut
from apiforge_server.core.deps import SessionDep
from apiforge_server.users import service
from apiforge_server.users.models import User
from apiforge_server.users.schemas import UserCreate, UserUpdate

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserOut], summary="List dashboard users")
async def list_users(_: Admin, session: SessionDep) -> Sequence[User]:
    return await service.list_users(session)


@router.post("", response_model=UserOut, status_code=201, summary="Invite a dashboard user")
async def create_user(body: UserCreate, actor: Owner, session: SessionDep) -> User:
    return await service.create_user(session, body, actor)


@router.patch("/{user_id}", response_model=UserOut, summary="Update a user's name, role or access")
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, actor: Owner, session: SessionDep
) -> User:
    return await service.update_user(session, user_id, body, actor)
