from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.code_review.webhook_service import code_review_webhook_service

router = APIRouter(prefix="/api/code-review/webhooks", tags=["code-review-webhooks"])


async def _read_json_payload(request: Request) -> tuple[bytes, dict[str, Any]]:
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Invalid webhook JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Webhook payload must be an object")
    return body, payload


@router.post("/github", status_code=202)
async def github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    body, payload = await _read_json_payload(request)
    return await code_review_webhook_service.handle_github_webhook(
        session=db,
        headers=request.headers,
        body=body,
        payload=payload,
    )


@router.post("/gitlab", status_code=202)
async def gitlab_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    body, payload = await _read_json_payload(request)
    return await code_review_webhook_service.handle_gitlab_webhook(
        session=db,
        headers=request.headers,
        body=body,
        payload=payload,
    )
