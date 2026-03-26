from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_review import (
    RepositoryIntegration,
    RepositoryReviewConfig,
    ReviewRun,
    ReviewRunStatus,
)
from app.services.code_review.dispatcher import (
    CodeReviewRunDispatcher,
    code_review_run_dispatcher,
)
from app.services.code_review.provider_github import (
    normalize_github_webhook_payload,
    verify_github_webhook_signature,
)
from app.services.code_review.provider_gitlab import (
    normalize_gitlab_webhook_payload,
    verify_gitlab_webhook_token,
)
from app.services.code_review.timeline_service import (
    CodeReviewTimelineService,
    code_review_timeline_service,
)


def _load_env_secret(*keys: str) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value and value.strip():
            return value.strip()
    return None


class CodeReviewWebhookService:
    def __init__(
        self,
        *,
        timeline_service: CodeReviewTimelineService = code_review_timeline_service,
        run_dispatcher: CodeReviewRunDispatcher = code_review_run_dispatcher,
    ) -> None:
        self.timeline_service = timeline_service
        self.run_dispatcher = run_dispatcher

    async def handle_github_webhook(
        self,
        *,
        session: AsyncSession,
        headers: Mapping[str, str],
        body: bytes,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        secret = _load_env_secret(
            "GITHUB_WEBHOOK_SECRET",
            "OPENWEBPX_CODE_REVIEW_WEBHOOK_SECRET",
        )
        signature_header = headers.get("X-Hub-Signature-256")
        if not verify_github_webhook_signature(
            secret=secret,
            body=body,
            signature_header=signature_header,
        ):
            raise HTTPException(401, "GitHub webhook signature invalid")

        try:
            normalized_event = normalize_github_webhook_payload(
                payload,
                event_type=headers.get("X-GitHub-Event"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if normalized_event is None:
            return {"ok": True, "queued": False}
        return await self._process_event(
            session=session, normalized_event=normalized_event
        )

    async def handle_gitlab_webhook(
        self,
        *,
        session: AsyncSession,
        headers: Mapping[str, str],
        body: bytes,  # noqa: ARG002
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        secret = _load_env_secret(
            "GITLAB_WEBHOOK_SECRET",
            "OPENWEBPX_CODE_REVIEW_WEBHOOK_SECRET",
        )
        token_header = headers.get("X-Gitlab-Token")

        # 只有在配置了密钥的情况下才进行验证
        if secret and not verify_gitlab_webhook_token(
            secret=secret, token_header=token_header
        ):
            raise HTTPException(401, "GitLab webhook token invalid")

        gitlab_base_url = headers.get("X-Gitlab-Instance")
        try:
            normalized_event = normalize_gitlab_webhook_payload(
                payload,
                gitlab_base_url=gitlab_base_url,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if normalized_event is None:
            return {"ok": True, "queued": False}
        return await self._process_event(
            session=session, normalized_event=normalized_event
        )

    async def _process_event(
        self,
        *,
        session: AsyncSession,
        normalized_event: dict[str, Any],
    ) -> dict[str, Any]:
        # 防止死循环：如果提交信息中包含 [AI Fix] 标记，则跳过评审
        commit_message = normalized_event.get("head_commit_message") or ""
        if "[AI Fix]" in commit_message:
            return {"ok": True, "skipped": True, "reason": "AI fix commit detected"}

        integration = await self._find_repository_integration(
            session=session,
            provider=str(normalized_event["provider"]),
            external_repo_id=str(normalized_event["repository_external_id"]),
            repository_identity_key=str(normalized_event["repository_identity_key"]),
        )
        if integration is None:
            return {"ok": True, "queued": False}

        config = await self._find_repository_config(
            session=session,
            repository_integration_id=integration.id,
        )
        if config is None or not config.review_enabled:
            return {"ok": True, "queued": False}

        idempotency_key = self._build_idempotency_key(
            provider=str(normalized_event["provider"]),
            repository_identity_key=str(normalized_event["repository_identity_key"]),
            external_repo_id=str(normalized_event["repository_external_id"]),
            event_type=str(normalized_event["provider_event_type"]),
            external_pr_or_mr_id=normalized_event.get("external_pr_or_mr_id"),
            head_commit_id=normalized_event.get("head_commit_id"),
        )

        existing_run = await self._find_review_run(
            session=session,
            idempotency_key=idempotency_key,
        )
        if existing_run is not None:
            return self._serialize_run(existing_run, queued=False)

        now = datetime.now(UTC)

        # 预先创建一个 Aegra Thread
        from aegra_api.core.orm import Thread as ThreadORM

        new_thread = ThreadORM()
        session.add(new_thread)
        await session.flush()

        run = ReviewRun(
            repository_integration_id=integration.id,
            provider=str(normalized_event["provider"]),
            event_type=str(normalized_event["provider_event_type"]),
            external_event_id=normalized_event.get("external_event_id"),
            external_pr_or_mr_id=normalized_event.get("external_pr_or_mr_id"),
            head_commit_id=normalized_event.get("head_commit_id"),
            base_commit_id=normalized_event.get("base_commit_id"),
            base_branch=normalized_event.get("base_branch"),
            head_branch=normalized_event.get("head_branch"),
            status=ReviewRunStatus.QUEUED,
            idempotency_key=idempotency_key,
            thread_id=str(new_thread.thread_id),  # 关联 Thread ID
            created_by_event_at=now,
            created_at=now,
            updated_at=now,
        )
        await self.timeline_service.record_initial_run_events(
            session=session,
            review_run=run,
            normalized_event=normalized_event,
        )
        session.add(run)

        try:
            await session.commit()
            await session.refresh(run)
            response_payload = self._serialize_run(run, queued=True)
            try:
                await self.run_dispatcher.enqueue_run(session=session, run_id=run.id)
            except (HTTPException, SQLAlchemyError):
                await session.rollback()
            return response_payload
        except IntegrityError:
            await session.rollback()
            existing_run = await self._find_review_run(
                session=session,
                idempotency_key=idempotency_key,
            )
            if existing_run is not None:
                return self._serialize_run(existing_run, queued=False)
            raise HTTPException(
                500, "创建代码评审运行失败：幂等冲突后未找到已存在记录"
            ) from None
        except SQLAlchemyError as exc:
            await session.rollback()
            raise HTTPException(500, f"创建代码评审运行失败: {exc}") from exc

    async def _find_repository_integration(
        self,
        *,
        session: AsyncSession,
        provider: str,
        external_repo_id: str,
        repository_identity_key: str,
    ) -> RepositoryIntegration | None:
        result = await session.scalars(select(RepositoryIntegration))
        for integration in result.all():
            if (
                integration.provider == provider
                and integration.external_repo_id == external_repo_id
                and integration.repository_identity_key == repository_identity_key
            ):
                return integration
        return None

    async def _find_repository_config(
        self,
        *,
        session: AsyncSession,
        repository_integration_id: int | None,
    ) -> RepositoryReviewConfig | None:
        if repository_integration_id is None:
            return None
        result = await session.scalars(select(RepositoryReviewConfig))
        for config in result.all():
            if config.repository_integration_id == repository_integration_id:
                return config
        return None

    async def _find_review_run(
        self,
        *,
        session: AsyncSession,
        idempotency_key: str,
    ) -> ReviewRun | None:
        result = await session.scalars(select(ReviewRun))
        for run in result.all():
            if run.idempotency_key == idempotency_key:
                return run
        return None

    def _build_idempotency_key(
        self,
        *,
        provider: str,
        repository_identity_key: str,
        external_repo_id: str,
        event_type: str,
        external_pr_or_mr_id: Any,
        head_commit_id: Any,
    ) -> str:
        identity_segment = repository_identity_key.strip()
        pr_segment = (
            "" if external_pr_or_mr_id is None else str(external_pr_or_mr_id).strip()
        )
        head_segment = "" if head_commit_id is None else str(head_commit_id).strip()
        return (
            f"{provider}:{identity_segment}:{external_repo_id}:{event_type}:"
            f"{pr_segment}:{head_segment}"
        )

    def _serialize_run(
        self,
        run: ReviewRun,
        *,
        queued: bool,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "queued": queued,
            "repository_integration_id": run.repository_integration_id,
            "review_run_id": run.id,
            "idempotency_key": run.idempotency_key,
            "provider": run.provider,
            "event_type": run.event_type,
        }


code_review_webhook_service = CodeReviewWebhookService()
