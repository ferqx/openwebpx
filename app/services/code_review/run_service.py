from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_review import (
    RepositoryIntegration,
    RepositoryMembership,
    ReviewFinding,
    ReviewFixRequest,
    ReviewRun,
    ReviewRunStatus,
)
from app.services.code_review.timeline_service import (
    CodeReviewTimelineService,
    code_review_timeline_service,
)


def _resolve_user_identity(current_user: Any) -> str:
    if isinstance(current_user, str) and current_user.strip():
        return current_user.strip()
    for attr_name in ("identity", "id", "user_id"):
        attr_value = getattr(current_user, attr_name, None)
        if isinstance(attr_value, str) and attr_value.strip():
            return attr_value.strip()
    if isinstance(current_user, dict):
        for key in ("identity", "id", "user_id"):
            value = current_user.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise HTTPException(400, "无法识别当前用户")


class CodeReviewRunService:
    def __init__(
        self,
        *,
        timeline_service: CodeReviewTimelineService = code_review_timeline_service,
    ) -> None:
        self.timeline_service = timeline_service

    async def list_runs(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
    ) -> list[dict[str, Any]]:
        visible_integration_ids = await self._visible_integration_ids(
            session=session,
            current_user=current_user,
        )

        # 使用聚合查询一次性获取 Run 及其统计信息
        result = await session.execute(
            select(ReviewRun)
            .where(ReviewRun.repository_integration_id.in_(visible_integration_ids))
            .order_by(desc(ReviewRun.created_at), desc(ReviewRun.id))
        )
        runs = result.scalars().all()

        if not runs:
            return []

        # 批量获取 findings count
        findings_count_result = await session.execute(
            select(ReviewFinding.review_run_id, func.count(ReviewFinding.id))
            .where(ReviewFinding.review_run_id.in_([r.id for r in runs]))
            .group_by(ReviewFinding.review_run_id)
        )
        findings_counts = dict(findings_count_result.all())

        # 批量获取待审批修复请求
        pending_fix_result = await session.execute(
            select(ReviewFixRequest.review_run_id)
            .where(
                ReviewFixRequest.review_run_id.in_([r.id for r in runs]),
                ReviewFixRequest.status == "pending_approval",
            )
            .distinct()
        )
        pending_fix_run_ids = {r[0] for r in pending_fix_result.all()}

        return [
            self._serialize_summary(
                run,
                findings_count=findings_counts.get(run.id, 0),
                has_pending_approval=(run.id in pending_fix_run_ids),
            )
            for run in runs
        ]

    async def get_run(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        run_id: int,
    ) -> dict[str, Any]:
        run = await self._get_visible_run(
            session=session,
            current_user=current_user,
            run_id=run_id,
        )
        events = await self.timeline_service.list_events(
            session=session,
            review_run_id=run.id,
        )
        findings = await self._list_findings(session=session, review_run_id=run.id)
        fix_requests = await self._list_fix_requests(
            session=session,
            review_run_id=run.id,
        )
        integration = await self._get_integration(
            session=session, integration_id=run.repository_integration_id
        )
        return self._serialize_detail(run, integration, findings, fix_requests, events)

    async def enqueue_run(
        self,
        *,
        session: AsyncSession,
        run_id: int,
    ) -> dict[str, Any]:
        run = await self._get_run_by_id(session=session, run_id=run_id)
        transitioned_to_analyzing = False
        if run.status == ReviewRunStatus.QUEUED:
            run.status = ReviewRunStatus.ANALYZING
            run.updated_at = datetime.now(UTC)
            await self.timeline_service.append_event(
                session=session,
                review_run=run,
                event_type="analysis_started",
                dedupe_key=f"{run.id}:analysis_started",
                payload={"status": ReviewRunStatus.ANALYZING.value},
            )
            await session.commit()
            await session.refresh(run)
            transitioned_to_analyzing = True
        serialized = await self._serialize_run_with_events(session=session, run=run)
        serialized["transitioned_to_analyzing"] = transitioned_to_analyzing
        return serialized

    async def complete_run(
        self,
        *,
        session: AsyncSession,
        run_id: int,
        result_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._finish_run(
            session=session,
            run_id=run_id,
            status=ReviewRunStatus.COMPLETED,
            event_type="analysis_completed",
            payload=result_payload,
        )

    async def fail_run(
        self,
        *,
        session: AsyncSession,
        run_id: int,
        error_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._finish_run(
            session=session,
            run_id=run_id,
            status=ReviewRunStatus.FAILED,
            event_type="analysis_failed",
            payload=error_payload,
        )

    async def _finish_run(
        self,
        *,
        session: AsyncSession,
        run_id: int,
        status: ReviewRunStatus,
        event_type: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        run = await self._get_run_by_id(session=session, run_id=run_id)
        if run.status != status:
            run.status = status
            run.updated_at = datetime.now(UTC)
            await self.timeline_service.append_event(
                session=session,
                review_run=run,
                event_type=event_type,
                dedupe_key=f"{run.id}:{event_type}",
                payload=payload or {"status": status.value},
            )
            await session.commit()
            await session.refresh(run)
        return await self._serialize_run_with_events(session=session, run=run)

    async def _visible_integration_ids(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
    ) -> set[int]:
        user_id = _resolve_user_identity(current_user)
        result = await session.scalars(select(RepositoryMembership))
        return {
            membership.repository_integration_id
            for membership in result.all()
            if membership.user_id == user_id
            and membership.repository_integration_id is not None
        }

    async def _load_runs(self, session: AsyncSession) -> list[ReviewRun]:
        result = await session.scalars(select(ReviewRun))
        return list(result.all())

    async def _get_run_by_id(
        self,
        *,
        session: AsyncSession,
        run_id: int,
    ) -> ReviewRun:
        runs = await self._load_runs(session)
        for run in runs:
            if run.id == run_id:
                return run
        raise HTTPException(404, "Review run not found")

    async def _get_visible_run(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        run_id: int,
    ) -> ReviewRun:
        run = await self._get_run_by_id(session=session, run_id=run_id)
        visible_integration_ids = await self._visible_integration_ids(
            session=session,
            current_user=current_user,
        )
        if run.repository_integration_id not in visible_integration_ids:
            raise HTTPException(404, "Review run not found")
        return run

    async def _get_integration(
        self,
        *,
        session: AsyncSession,
        integration_id: int | None,
    ) -> RepositoryIntegration | None:
        if integration_id is None:
            return None
        result = await session.scalars(select(RepositoryIntegration))
        for integration in result.all():
            if integration.id == integration_id:
                return integration
        return None

    def _serialize_summary(
        self,
        run: ReviewRun,
        findings_count: int | None = None,
        has_pending_approval: bool | None = None,
    ) -> dict[str, Any]:
        return {
            "id": run.id,
            "repository_integration_id": run.repository_integration_id,
            "provider": run.provider,
            "event_type": run.event_type,
            "status": self._status_value(run.status),
            "idempotency_key": run.idempotency_key,
            "thread_id": run.thread_id,
            "external_pr_or_mr_id": run.external_pr_or_mr_id,
            "head_commit_id": run.head_commit_id,
            "findings_count": findings_count,
            "has_pending_approval": has_pending_approval,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

    async def _serialize_run_with_events(
        self,
        *,
        session: AsyncSession,
        run: ReviewRun,
    ) -> dict[str, Any]:
        integration = await self._get_integration(
            session=session,
            integration_id=run.repository_integration_id,
        )
        events = await self.timeline_service.list_events(
            session=session,
            review_run_id=run.id,
        )
        findings = await self._list_findings(session=session, review_run_id=run.id)
        fix_requests = await self._list_fix_requests(
            session=session,
            review_run_id=run.id,
        )
        return self._serialize_detail(run, integration, findings, fix_requests, events)

    async def _list_findings(
        self,
        *,
        session: AsyncSession,
        review_run_id: int,
    ) -> list[ReviewFinding]:
        result = await session.scalars(select(ReviewFinding))
        findings = [
            finding
            for finding in result.all()
            if finding.review_run_id == review_run_id
        ]
        findings.sort(key=lambda finding: (finding.id or 0))
        return findings

    async def _list_fix_requests(
        self,
        *,
        session: AsyncSession,
        review_run_id: int,
    ) -> list[ReviewFixRequest]:
        result = await session.scalars(select(ReviewFixRequest))
        fix_requests = [
            fix_request
            for fix_request in result.all()
            if fix_request.review_run_id == review_run_id
        ]
        fix_requests.sort(key=lambda fix_request: (fix_request.id or 0))
        return fix_requests

    def _serialize_detail(
        self,
        run: ReviewRun,
        integration: RepositoryIntegration | None,
        findings: list[ReviewFinding],
        fix_requests: list[ReviewFixRequest],
        events: list[Any],
    ) -> dict[str, Any]:
        return {
            **self._serialize_summary(run),
            "repository": None
            if integration is None
            else {
                "id": integration.id,
                "provider": integration.provider,
                "external_repo_id": integration.external_repo_id,
                "repository_identity_key": integration.repository_identity_key,
                "full_name": integration.full_name,
                "gitlab_base_url": integration.gitlab_base_url,
            },
            "findings": [
                {
                    "id": finding.id,
                    "severity": finding.severity,
                    "category": finding.category,
                    "file_path": finding.file_path,
                    "line_start": finding.line_start,
                    "line_end": finding.line_end,
                    "title": finding.title,
                    "body": finding.body,
                    "rule_id": finding.rule_id,
                    "can_auto_fix": finding.can_auto_fix,
                    "metadata": finding.metadata_,
                    "created_at": finding.created_at,
                }
                for finding in findings
            ],
            "fix_requests": [
                {
                    "id": fix_request.id,
                    "review_run_id": fix_request.review_run_id,
                    "review_finding_id": fix_request.review_finding_id,
                    "source": self._status_value(fix_request.source),
                    "status": self._status_value(fix_request.status),
                    "approval_required": fix_request.approval_required,
                    "approved_by": fix_request.approved_by,
                    "approved_at": fix_request.approved_at,
                    "rejected_by": fix_request.rejected_by,
                    "rejected_at": fix_request.rejected_at,
                    "runner_job_id": fix_request.runner_job_id,
                    "result_payload": fix_request.result_payload,
                    "updated_at": fix_request.updated_at,
                }
                for fix_request in fix_requests
            ],
            "timeline_events": [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "dedupe_key": event.dedupe_key,
                    "payload": event.payload,
                    "created_at": event.created_at,
                }
                for event in events
            ],
        }

    @staticmethod
    def _status_value(status: Any) -> str:
        return status.value if hasattr(status, "value") else str(status)


code_review_run_service = CodeReviewRunService()
