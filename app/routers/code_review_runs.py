from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import authenticated_user
from app.core.database import get_db
from app.services.code_review.publish_service import code_review_publish_service
from app.services.code_review.run_service import code_review_run_service

router = APIRouter(prefix="/api/code-review", tags=["code-review"])


@router.get("/runs")
async def list_runs(
    current_user: Any = Depends(authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    runs = await code_review_run_service.list_runs(
        session=db,
        current_user=current_user,
    )
    return {"runs": runs}


@router.get("/runs/{id}")
async def get_run(
    id: int,
    current_user: Any = Depends(authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await code_review_run_service.get_run(
        session=db,
        current_user=current_user,
        run_id=id,
    )


@router.post("/runs/{id}/publish")
async def publish_run(
    id: int,
    current_user: Any = Depends(authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await code_review_publish_service.publish_run(
        session=db,
        current_user=current_user,
        run_id=id,
    )
