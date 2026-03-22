from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_review import ReviewRunStatus
from app.services.code_review.run_service import (
    CodeReviewRunService,
    code_review_run_service,
)
from app.services.code_review.timeline_service import (
    CodeReviewTimelineService,
    code_review_timeline_service,
)


class CodeReviewPublishService:
    def __init__(
        self,
        *,
        run_service: CodeReviewRunService = code_review_run_service,
        timeline_service: CodeReviewTimelineService = code_review_timeline_service,
    ) -> None:
        self.run_service = run_service
        self.timeline_service = timeline_service

    async def publish_run(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        run_id: int,
    ) -> dict[str, Any]:
        run = await self.run_service._get_visible_run(  # noqa: SLF001
            session=session,
            current_user=current_user,
            run_id=run_id,
        )
        if run.status != ReviewRunStatus.COMPLETED:
            raise HTTPException(409, "Review run must be completed before publish")

        now = datetime.now(UTC)
        await self.timeline_service.append_event(
            session=session,
            review_run=run,
            event_type="publish_requested",
            dedupe_key=f"{run.id}:publish_requested",
            payload={
                "run_id": run.id,
                "repository_integration_id": run.repository_integration_id,
                "status": run.status.value,
            },
        )
        await self.timeline_service.append_event(
            session=session,
            review_run=run,
            event_type="publish_completed",
            dedupe_key=f"{run.id}:publish_completed",
            payload={
                "run_id": run.id,
                "repository_integration_id": run.repository_integration_id,
                "published_at": now.isoformat(),
                "status": run.status.value,
                "stubbed": True,
            },
        )
        await session.commit()
        await session.refresh(run)
        return {
            "published": True,
            "run_id": run.id,
            "status": run.status.value,
            "published_at": now,
            "stubbed": True,
        }


code_review_publish_service = CodeReviewPublishService()
