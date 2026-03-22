from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import authenticated_user
from app.core.database import get_db
from app.services.code_review import code_review_repository_service

router = APIRouter(prefix="/api/code-review", tags=["code-review"])


class RepositorySyncRequest(BaseModel):
    provider: Literal["github", "gitlab"]
    gitlab_base_url: str | None = None
    github_auth_mode: str | None = None


class RepositoryConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_enabled: bool | None = None
    review_triggers: dict[str, Any] | None = None
    auto_fix_enabled: bool | None = None
    auto_fix_severities: dict[str, Any] | None = None
    auto_fix_requires_approval: bool | None = None
    auto_publish_enabled: bool | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


@router.post("/repositories/sync")
async def sync_repositories(
    payload: RepositorySyncRequest,
    current_user: Any = Depends(authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repositories = await code_review_repository_service.sync_repositories(
        session=db,
        current_user=current_user,
        provider=payload.provider,
        gitlab_base_url=payload.gitlab_base_url,
        github_auth_mode=payload.github_auth_mode,
    )
    return {"repositories": repositories}


@router.get("/repositories")
async def list_repositories(
    current_user: Any = Depends(authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repositories = await code_review_repository_service.list_repositories(
        session=db,
        current_user=current_user,
    )
    return {"repositories": repositories}


@router.get("/repositories/{id}/config")
async def get_repository_config(
    id: int,
    current_user: Any = Depends(authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await code_review_repository_service.get_repository_config(
        session=db,
        current_user=current_user,
        repository_id=id,
    )


@router.put("/repositories/{id}/config")
async def update_repository_config(
    id: int,
    payload: RepositoryConfigUpdateRequest,
    current_user: Any = Depends(authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await code_review_repository_service.update_repository_config(
        session=db,
        current_user=current_user,
        repository_id=id,
        payload=payload.to_payload(),
    )
