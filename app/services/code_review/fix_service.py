from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

from aegra_api.core.orm import (
    Run as AegraRunORM,
)
from aegra_api.core.orm import (
    Thread as AegraThreadORM,
)
from aegra_api.core.orm import (
    _get_session_maker,
)
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
        queue_poll_interval_seconds: float = 1.0,
    ) -> None:
        self.fix_runner = fix_runner
        self.timeline_service = timeline_service
        self.queue_poll_interval_seconds = queue_poll_interval_seconds
        self._thread_worker_tasks: dict[str, asyncio.Task[None]] = {}
        self._thread_worker_lock = asyncio.Lock()

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
        thread_id = self._require_review_thread_id(fix_request.review_run)
        await self._load_thread(session=session, thread_id=thread_id)

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
        await session.commit()
        await self.process_thread_queue_once(session=session, thread_id=thread_id)
        await self.ensure_background_worker(thread_id=thread_id)
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
        try:
            await self.process_thread_queue_once(
                session=session,
                thread_id=self._require_review_thread_id(fix_request.review_run),
            )
        finally:
            await self.ensure_background_worker(
                thread_id=self._require_review_thread_id(fix_request.review_run)
            )
        return self._serialize_fix_request(fix_request)

    async def process_thread_queue_once(
        self,
        *,
        session: AsyncSession,
        thread_id: str,
    ) -> bool:
        progressed = False
        while True:
            thread = await self._load_thread(session=session, thread_id=thread_id)
            running_fix = await self._get_running_fix_request(
                session=session,
                thread_id=thread_id,
            )
            if running_fix is not None:
                aegra_run = await self._get_aegra_run(
                    session=session,
                    run_id=str(running_fix.runner_job_id or "").strip(),
                )
                if aegra_run is None:
                    return progressed
                aegra_status = str(aegra_run.status or "").strip().lower()
                if aegra_status not in {"success", "error", "timeout", "interrupted"}:
                    return progressed
                await self._finalize_running_fix_request(
                    session=session,
                    fix_request=running_fix,
                    aegra_run=aegra_run,
                )
                progressed = True
                continue

            if str(thread.status or "").strip().lower() != "idle":
                return progressed

            next_fix = await self._get_next_approved_fix_request(
                session=session,
                thread_id=thread_id,
            )
            if next_fix is None:
                return progressed

            instruction = self._build_fix_instruction(next_fix)
            runner_metadata = await self.fix_runner.start_fix(
                session=session,
                fix_request=next_fix,
                thread=thread,
                instruction=instruction,
            )
            runner_job_id = str(runner_metadata.get("runner_job_id") or "").strip()
            if not runner_job_id:
                raise HTTPException(500, "Fix runner did not return runner_job_id")

            next_fix.runner_job_id = runner_job_id
            next_fix.status = ReviewFixRequestStatus.RUNNING
            next_fix.updated_at = datetime.now(UTC)
            await self.timeline_service.append_event(
                session=session,
                review_run=next_fix.review_run,
                event_type="fix_request_running",
                dedupe_key=f"{next_fix.id}:fix_request_running",
                payload={
                    "fix_request_id": next_fix.id,
                    "runner_job_id": runner_job_id,
                    "thread_id": thread_id,
                },
            )
            await session.commit()
            progressed = True
            return progressed

    async def ensure_background_worker(self, *, thread_id: str) -> None:
        async with self._thread_worker_lock:
            task = self._thread_worker_tasks.get(thread_id)
            if task is not None and not task.done():
                return
            self._thread_worker_tasks[thread_id] = asyncio.create_task(
                self._thread_queue_worker(thread_id=thread_id)
            )

    async def _thread_queue_worker(self, *, thread_id: str) -> None:
        session_maker = _get_session_maker()
        try:
            while True:
                async with session_maker() as session:
                    try:
                        await self.process_thread_queue_once(
                            session=session,
                            thread_id=thread_id,
                        )
                        has_work = await self._thread_has_queue_work(
                            session=session,
                            thread_id=thread_id,
                        )
                    except HTTPException:
                        return
                if not has_work:
                    return
                await asyncio.sleep(self.queue_poll_interval_seconds)
        finally:
            async with self._thread_worker_lock:
                task = self._thread_worker_tasks.get(thread_id)
                if task is not None and task.done():
                    self._thread_worker_tasks.pop(thread_id, None)

    async def _thread_has_queue_work(
        self,
        *,
        session: AsyncSession,
        thread_id: str,
    ) -> bool:
        approved = await self._get_next_approved_fix_request(
            session=session,
            thread_id=thread_id,
        )
        running = await self._get_running_fix_request(
            session=session,
            thread_id=thread_id,
        )
        if approved is not None or running is not None:
            return True
        thread = await self._load_thread(session=session, thread_id=thread_id)
        return str(thread.status or "").strip().lower() != "idle"

    def _ensure_runner_callback_secret(self, *, callback_secret: str | None) -> None:
        expected_secret = (
            os.getenv("SANDBOX_AGENT_CODE_REVIEW_FIX_RUNNER_SECRET")
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

    async def _load_thread(
        self,
        *,
        session: AsyncSession,
        thread_id: str,
    ) -> AegraThreadORM:
        result = await session.execute(
            select(AegraThreadORM).where(AegraThreadORM.thread_id == thread_id)
        )
        thread = result.scalar_one_or_none()
        if thread is None:
            raise HTTPException(404, f"Thread '{thread_id}' not found")
        return thread

    async def _get_running_fix_request(
        self,
        *,
        session: AsyncSession,
        thread_id: str,
    ) -> ReviewFixRequest | None:
        result = await session.execute(
            select(ReviewFixRequest)
            .options(
                joinedload(ReviewFixRequest.review_run).joinedload(
                    ReviewRun.repository_integration
                ),
                joinedload(ReviewFixRequest.review_finding),
            )
            .join(ReviewRun, ReviewFixRequest.review_run_id == ReviewRun.id)
            .where(
                ReviewRun.thread_id == thread_id,
                ReviewFixRequest.status == ReviewFixRequestStatus.RUNNING,
            )
            .order_by(ReviewFixRequest.updated_at.desc(), ReviewFixRequest.id.desc())
        )
        return result.scalar_one_or_none()

    async def _get_next_approved_fix_request(
        self,
        *,
        session: AsyncSession,
        thread_id: str,
    ) -> ReviewFixRequest | None:
        result = await session.execute(
            select(ReviewFixRequest)
            .options(
                joinedload(ReviewFixRequest.review_run).joinedload(
                    ReviewRun.repository_integration
                ),
                joinedload(ReviewFixRequest.review_finding),
            )
            .join(ReviewRun, ReviewFixRequest.review_run_id == ReviewRun.id)
            .where(
                ReviewRun.thread_id == thread_id,
                ReviewFixRequest.status == ReviewFixRequestStatus.APPROVED,
            )
            .order_by(
                ReviewFixRequest.approved_at.asc().nulls_last(),
                ReviewFixRequest.created_at.asc(),
                ReviewFixRequest.id.asc(),
            )
        )
        return result.scalar_one_or_none()

    async def _get_aegra_run(
        self,
        *,
        session: AsyncSession,
        run_id: str,
    ) -> AegraRunORM | None:
        if not run_id:
            return None
        result = await session.execute(
            select(AegraRunORM).where(AegraRunORM.run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def _finalize_running_fix_request(
        self,
        *,
        session: AsyncSession,
        fix_request: ReviewFixRequest,
        aegra_run: AegraRunORM,
    ) -> None:
        aegra_status = str(aegra_run.status or "").strip().lower()
        terminal_status = (
            ReviewFixRequestStatus.COMPLETED
            if aegra_status == "success"
            else ReviewFixRequestStatus.FAILED
        )
        fix_request.status = terminal_status
        fix_request.result_payload = {
            "aegra_run_status": aegra_status,
            "aegra_run_output": aegra_run.output,
        }
        fix_request.updated_at = datetime.now(UTC)
        await self.timeline_service.append_event(
            session=session,
            review_run=fix_request.review_run,
            event_type=f"fix_request_{terminal_status.value}",
            dedupe_key=f"{fix_request.id}:fix_request_{terminal_status.value}",
            payload={
                "fix_request_id": fix_request.id,
                "runner_job_id": fix_request.runner_job_id,
                "result_payload": fix_request.result_payload,
            },
        )
        await session.commit()

    def _build_fix_instruction(self, fix_request: ReviewFixRequest) -> str:
        finding = fix_request.review_finding
        lines = [
            f"Fix request #{fix_request.id} for review run #{fix_request.review_run_id}.",
        ]
        if finding is not None:
            location = finding.file_path or "unknown file"
            if finding.line_start is not None:
                location = f"{location}:{finding.line_start}"
                if (
                    finding.line_end is not None
                    and finding.line_end != finding.line_start
                ):
                    location = f"{location}-{finding.line_end}"
            lines.append(f"Finding: {finding.title}")
            lines.append(f"Location: {location}")
            if finding.body:
                lines.append(f"Detail: {finding.body}")
        lines.append(
            "Continue in the same task thread and make the minimal correct fix."
        )
        return "\n".join(lines)

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

    def _require_review_thread_id(self, review_run: ReviewRun) -> str:
        thread_id = str(review_run.thread_id or "").strip()
        if thread_id:
            return thread_id
        raise HTTPException(409, "Review run has no bound thread_id for fix approval")

    def _serialize_fix_request(self, fix_request: ReviewFixRequest) -> dict[str, Any]:
        runner_job_id = fix_request.runner_job_id
        thread_id = str(
            getattr(getattr(fix_request, "review_run", None), "thread_id", "") or ""
        ).strip()
        runner_payload = None
        if thread_id and fix_request.status in {
            ReviewFixRequestStatus.APPROVED,
            ReviewFixRequestStatus.RUNNING,
        }:
            runner_payload = {
                "thread_id": thread_id,
                "status": (
                    "running"
                    if fix_request.status == ReviewFixRequestStatus.RUNNING
                    else "queued"
                ),
                "queue_scope": "thread",
            }
            if runner_job_id:
                runner_payload["runner_job_id"] = runner_job_id
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
            "runner_job_id": runner_job_id,
            "runner": runner_payload,
            "result_payload": fix_request.result_payload,
            "updated_at": fix_request.updated_at,
        }


code_review_fix_service = CodeReviewFixService()
