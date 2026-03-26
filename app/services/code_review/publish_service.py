from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_review import ReviewFinding, ReviewRunStatus
from app.services.code_review.run_service import (
    CodeReviewRunService,
    code_review_run_service,
)
from app.services.code_review.timeline_service import (
    CodeReviewTimelineService,
    code_review_timeline_service,
)
from app.services.scm.repository import scm_repository_service


class CodeReviewPublishService:
    AI_SUMMARY_HEADER = "### 🤖 AI Code Review Summary"

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

        # 1. 获取所有 Findings
        result = await session.execute(
            select(ReviewFinding).where(ReviewFinding.review_run_id == run.id)
        )
        findings = result.scalars().all()

        if not findings:
            return {"published": False, "message": "No findings to publish"}

        # 2. 构造评论内容
        comment_body = f"{self.AI_SUMMARY_HEADER}\n\n"
        comment_body += f"I have analyzed the changes in this MR. Found **{len(findings)}** potential issues.\n\n"
        comment_body += (
            f"*Last Updated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC*\n\n"
        )

        for i, f in enumerate(findings, 1):
            severity_emoji = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(
                f.severity, "⚪"
            )
            comment_body += f"{i}. {severity_emoji} **{f.title}**\n"
            comment_body += f"   - **File**: `{f.file_path}` (Line {f.line_start})\n"
            comment_body += f"   - **Category**: {f.category}\n"
            comment_body += f"   - **Suggestion**: {f.body}\n\n"

        # 3. 发布或更新到 SCM
        token = os.getenv("TEST_GITLAB_TOKEN")
        if not token:
            raise ValueError("No SCM token available for publishing")

        published_info = {}
        if run.provider == "gitlab":
            # 3.1 尝试寻找已有的 AI 汇总评论
            existing_notes = await scm_repository_service.list_gitlab_mr_comments(
                repository=run.repository_integration.full_name,
                mr_iid=int(run.external_pr_or_mr_id),
                access_token=token,
                gitlab_base_url=run.repository_integration.gitlab_base_url,
            )

            existing_note_id = None
            for note in existing_notes:
                if str(note.get("body", "")).startswith(self.AI_SUMMARY_HEADER):
                    existing_note_id = note.get("id")
                    break

            if existing_note_id:
                # 3.2 更新已有评论
                published_info = await scm_repository_service.update_gitlab_mr_comment(
                    repository=run.repository_integration.full_name,
                    mr_iid=int(run.external_pr_or_mr_id),
                    note_id=existing_note_id,
                    body=comment_body,
                    access_token=token,
                    gitlab_base_url=run.repository_integration.gitlab_base_url,
                )
            else:
                # 3.3 创建新评论
                published_info = await scm_repository_service.post_gitlab_mr_comment(
                    repository=run.repository_integration.full_name,
                    mr_iid=int(run.external_pr_or_mr_id),
                    body=comment_body,
                    access_token=token,
                    gitlab_base_url=run.repository_integration.gitlab_base_url,
                )

        now = datetime.now(UTC)
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
                "mode": "update" if existing_note_id else "create",
                "scm_note_id": published_info.get("id"),
            },
        )

        await session.commit()
        return {
            "published": True,
            "run_id": run.id,
            "status": run.status.value,
            "published_at": now,
            "scm_note_id": published_info.get("id"),
            "mode": "updated" if existing_note_id else "created",
        }


code_review_publish_service = CodeReviewPublishService()
