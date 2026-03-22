from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import authenticated_user
from app.core.database import get_db
from app.services.code_review.fix_service import code_review_fix_service

router = APIRouter(prefix="/api/code-review", tags=["code-review"])


class FixRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class FixRunnerCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runner_job_id: str
    status: str
    result_payload: dict[str, Any] | None = None


@router.post("/fix-requests/{id}/approve")
async def approve_fix_request(
    id: int,
    current_user: Any = Depends(authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await code_review_fix_service.approve_fix_request(
        session=db,
        current_user=current_user,
        fix_request_id=id,
    )


@router.post("/fix-requests/{id}/reject")
async def reject_fix_request(
    id: int,
    payload: FixRejectRequest,
    current_user: Any = Depends(authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await code_review_fix_service.reject_fix_request(
        session=db,
        current_user=current_user,
        fix_request_id=id,
        reason=payload.reason,
    )


@router.post("/fix-runner/callback")
async def fix_runner_callback(
    payload: FixRunnerCallbackRequest,
    x_openwebpx_fix_runner_secret: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await code_review_fix_service.handle_runner_callback(
        session=db,
        payload=payload.model_dump(),
        callback_secret=x_openwebpx_fix_runner_secret,
    )
