from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.code_review import (
    RepositoryMembership,
    ReviewFixRequest,
    ReviewFixRequestStatus,
    ReviewRun,
)
from app.services.code_review.fix_runner import (
    CodeReviewFixRunner,
    code_review_fix_runner,
)
from app.services.code_review.run_service import _resolve_user_identity
from app.services.code_review.timeline_service import (
    CodeReviewTimelineService,
    code_review_timeline_service,
)


class CodeReviewFixService:
    def __init__(
        self,
        *,
        fix_runner: CodeReviewFixRunner = code_review_fix_runner,
        timeline_service: CodeReviewTimelineService = code_review_timeline_service,
    ) -> None:
        self.fix_runner = fix_runner
        self.timeline_service = timeline_service

    async def approve_fix_request(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        fix_request_id: int,
    ) -> dict[str, Any]:
        fix_request = await self._get_fix_request(
            session=session, fix_request_id=fix_request_id
        )
        await self._ensure_approval_permission(
            session=session,
            current_user=current_user,
            repository_integration_id=fix_request.review_run.repository_integration_id,
        )
        if fix_request.status != ReviewFixRequestStatus.PENDING_APPROVAL:
            raise HTTPException(409, "Fix request is not pending approval")

        now = datetime.now(UTC)
        fix_request.status = ReviewFixRequestStatus.APPROVED
        fix_request.approved_by = _resolve_user_identity(current_user)
        fix_request.approved_at = now
        fix_request.updated_at = now

        await self.timeline_service.append_event(
            session=session,
            review_run=fix_request.review_run,
            event_type="fix_request_approved",
            dedupe_key=f"{fix_request.id}:fix_request_approved",
            payload={
                "fix_request_id": fix_request.id,
                "review_finding_id": fix_request.review_finding_id,
                "approved_by": fix_request.approved_by,
            },
        )

        # 启动 Runner
        runner_job_id = await self.fix_runner.start_fix(
            session=session, fix_request=fix_request
        )

        fix_request.runner_job_id = runner_job_id
        fix_request.status = ReviewFixRequestStatus.RUNNING
        fix_request.updated_at = datetime.now(UTC)

        await self.timeline_service.append_event(
            session=session,
            review_run=fix_request.review_run,
            event_type="fix_request_running",
            dedupe_key=f"{fix_request.id}:fix_request_running",
            payload={
                "fix_request_id": fix_request.id,
                "runner_job_id": runner_job_id,
            },
        )
        await session.commit()
        await session.refresh(fix_request)
        return self._serialize_fix_request(fix_request)

    async def reject_fix_request(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        fix_request_id: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        fix_request = await self._get_fix_request(
            session=session, fix_request_id=fix_request_id
        )
        await self._ensure_approval_permission(
            session=session,
            current_user=current_user,
            repository_integration_id=fix_request.review_run.repository_integration_id,
        )
        if fix_request.status == ReviewFixRequestStatus.REJECTED:
            return self._serialize_fix_request(fix_request)
        if fix_request.status != ReviewFixRequestStatus.PENDING_APPROVAL:
            raise HTTPException(409, "Fix request is not pending approval")

        now = datetime.now(UTC)
        fix_request.status = ReviewFixRequestStatus.REJECTED
        fix_request.rejected_by = _resolve_user_identity(current_user)
        fix_request.rejected_at = now
        fix_request.updated_at = now
        await self.timeline_service.append_event(
            session=session,
            review_run=fix_request.review_run,
            event_type="fix_request_rejected",
            dedupe_key=f"{fix_request.id}:fix_request_rejected",
            payload={
                "fix_request_id": fix_request.id,
                "review_finding_id": fix_request.review_finding_id,
                "rejected_by": fix_request.rejected_by,
                "reason": reason,
            },
        )
        await session.commit()
        await session.refresh(fix_request)
        return self._serialize_fix_request(fix_request)

    async def handle_runner_callback(
        self,
        *,
        session: AsyncSession,
        payload: dict[str, Any],
        callback_secret: str | None,
    ) -> dict[str, Any]:
        self._ensure_runner_callback_secret(callback_secret=callback_secret)
        runner_job_id = str(payload.get("runner_job_id") or "").strip()
        if not runner_job_id:
            raise HTTPException(400, "runner_job_id is required")
        status_text = str(payload.get("status") or "").strip().lower()
        if status_text not in {"completed", "failed"}:
            raise HTTPException(400, "status must be completed or failed")

        fix_request = await self._get_fix_request_by_runner_job_id(
            session=session,
            runner_job_id=runner_job_id,
        )
        if fix_request is None:
            raise HTTPException(404, "Fix request not found")
        if fix_request.status in {
            ReviewFixRequestStatus.COMPLETED,
            ReviewFixRequestStatus.FAILED,
        }:
            return self._serialize_fix_request(fix_request)

        now = datetime.now(UTC)
        terminal_status = (
            ReviewFixRequestStatus.COMPLETED
            if status_text == "completed"
            else ReviewFixRequestStatus.FAILED
        )
        fix_request.status = terminal_status
        fix_request.result_payload = payload.get("result_payload")
        fix_request.updated_at = now
        await self.timeline_service.append_event(
            session=session,
            review_run=fix_request.review_run,
            event_type=f"fix_request_{terminal_status.value}",
            dedupe_key=f"{fix_request.id}:fix_request_{terminal_status.value}",
            payload={
                "fix_request_id": fix_request.id,
                "runner_job_id": runner_job_id,
                "result_payload": fix_request.result_payload,
            },
        )
        await session.commit()
        await session.refresh(fix_request)
        return self._serialize_fix_request(fix_request)

    def _ensure_runner_callback_secret(self, *, callback_secret: str | None) -> None:
        expected_secret = (
            os.getenv("OPENWEBPX_CODE_REVIEW_FIX_RUNNER_SECRET")
            or os.getenv("CODE_REVIEW_FIX_RUNNER_SECRET")
            or ""
        ).strip()
        provided_secret = (callback_secret or "").strip()
        if not expected_secret or provided_secret != expected_secret:
            raise HTTPException(401, "Fix runner callback secret invalid")

    async def _get_fix_request(
        self,
        *,
        session: AsyncSession,
        fix_request_id: int,
    ) -> ReviewFixRequest:
        result = await session.execute(
            select(ReviewFixRequest)
            .options(
                joinedload(ReviewFixRequest.review_run).joinedload(
                    ReviewRun.repository_integration
                ),
                joinedload(ReviewFixRequest.review_finding),
            )
            .where(ReviewFixRequest.id == fix_request_id)
        )
        fix_request = result.scalar_one_or_none()
        if not fix_request:
            raise HTTPException(404, "Fix request not found")
        return fix_request

    async def _get_fix_request_by_runner_job_id(
        self,
        *,
        session: AsyncSession,
        runner_job_id: str,
    ) -> ReviewFixRequest | None:
        result = await session.execute(
            select(ReviewFixRequest)
            .options(
                joinedload(ReviewFixRequest.review_run).joinedload(
                    ReviewRun.repository_integration
                )
            )
            .where(ReviewFixRequest.runner_job_id == runner_job_id)
        )
        return result.scalar_one_or_none()

    async def _ensure_approval_permission(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        repository_integration_id: int | None,
    ) -> None:
        if repository_integration_id is None:
            raise HTTPException(404, "Fix request not found")
        user_id = _resolve_user_identity(current_user)
        result = await session.execute(
            select(RepositoryMembership).where(
                RepositoryMembership.repository_integration_id
                == repository_integration_id,
                RepositoryMembership.user_id == user_id,
            )
        )
        membership = result.scalar_one_or_none()
        if membership and membership.can_approve_fixes:
            return
        raise HTTPException(403, "Current user cannot approve fix requests")

    def _serialize_fix_request(self, fix_request: ReviewFixRequest) -> dict[str, Any]:
        return {
            "id": fix_request.id,
            "review_run_id": fix_request.review_run_id,
            "review_finding_id": fix_request.review_finding_id,
            "source": fix_request.source.value
            if hasattr(fix_request.source, "value")
            else str(fix_request.source),
            "status": fix_request.status.value
            if hasattr(fix_request.status, "value")
            else str(fix_request.status),
            "approval_required": fix_request.approval_required,
            "approved_by": fix_request.approved_by,
            "approved_at": fix_request.approved_at,
            "rejected_by": fix_request.rejected_by,
            "rejected_at": fix_request.rejected_at,
            "runner_job_id": fix_request.runner_job_id,
            "result_payload": fix_request.result_payload,
            "updated_at": fix_request.updated_at,
        }


code_review_fix_service = CodeReviewFixService()
