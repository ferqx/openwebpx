from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.code_review import (
    RepositoryReviewConfig,
    ReviewFinding,
    ReviewFixRequest,
    ReviewFixRequestSource,
    ReviewFixRequestStatus,
    ReviewRun,
    ReviewRunStatus,
)
from app.services.code_review.agent_adapter import (
    CodeReviewAgentAdapter,
    code_review_agent_adapter,
)
from app.services.code_review.run_service import (
    CodeReviewRunService,
    code_review_run_service,
)
from app.services.code_review.timeline_service import (
    CodeReviewTimelineService,
    code_review_timeline_service,
)
from app.services.scm.repository import scm_repository_service

logger = logging.getLogger(__name__)


def _as_lower_text(value: Any) -> str:
    return str(value).strip().lower()


def _extract_allowed_severities(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = _as_lower_text(value)
        return {normalized} if normalized else None
    if isinstance(value, Mapping):
        for key in ("allowed_severities", "severities", "levels", "values"):
            if key in value:
                return _extract_allowed_severities(value[key])
        return {
            _as_lower_text(item)
            for item in value.values()
            if isinstance(item, (str, int, float)) and _as_lower_text(item)
        } or None
    if isinstance(value, (set, frozenset, list, tuple)):
        severities = {
            _as_lower_text(item)
            for item in value
            if isinstance(item, (str, int, float)) and _as_lower_text(item)
        }
        return severities or None
    normalized = _as_lower_text(value)
    return {normalized} if normalized else None


class CodeReviewAnalyzerService:
    def __init__(
        self,
        *,
        run_service: CodeReviewRunService = code_review_run_service,
        timeline_service: CodeReviewTimelineService = code_review_timeline_service,
        agent_adapter: CodeReviewAgentAdapter = code_review_agent_adapter,
    ) -> None:
        self.run_service = run_service
        self.timeline_service = timeline_service
        self.agent_adapter = agent_adapter

    async def analyze_run(
        self,
        *,
        session: AsyncSession,
        run_id: int,
        analysis_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            run = await self._load_run(session=session, run_id=run_id)
            if run.status == ReviewRunStatus.QUEUED:
                await self.run_service.enqueue_run(session=session, run_id=run_id)
                run = await self._load_run(session=session, run_id=run_id)

            if run.status in {ReviewRunStatus.COMPLETED, ReviewRunStatus.FAILED}:
                return await self.run_service._serialize_run_with_events(  # noqa: SLF001
                    session=session,
                    run=run,
                )

            # 如果没有传入外部分析结果，则启动真实的 AI 分析
            if analysis_result is None:
                analysis_result = await self._perform_ai_analysis(
                    session=session,
                    run=run,
                )

            if (
                analysis_result is not None
                and _as_lower_text(analysis_result.get("status")) == "failed"
            ):
                return await self.run_service.fail_run(
                    session=session,
                    run_id=run_id,
                    error_payload={
                        "error": analysis_result.get("error")
                        or analysis_result.get("message")
                        or "analysis failed",
                        "analysis_result": analysis_result,
                    },
                )

            normalized_event = await self._load_normalized_event(
                session=session, run=run
            )
            config = await self._load_repository_config(
                session=session,
                repository_integration_id=run.repository_integration_id,
            )
            finding_specs = self._build_finding_specs(
                analysis_result=analysis_result,
                normalized_event=normalized_event,
            )

            findings: list[ReviewFinding] = []
            fix_requests: list[ReviewFixRequest] = []
            for finding_spec in finding_specs:
                finding = ReviewFinding(
                    review_run=run,
                    severity=finding_spec["severity"],
                    category=finding_spec["category"],
                    file_path=finding_spec["file_path"],
                    line_start=finding_spec["line_start"],
                    line_end=finding_spec["line_end"],
                    title=finding_spec["title"],
                    body=finding_spec["body"],
                    rule_id=finding_spec["rule_id"],
                    can_auto_fix=self._can_auto_fix(
                        config=config,
                        severity=finding_spec["severity"],
                        metadata=finding_spec["metadata"],
                    ),
                    metadata_=finding_spec["metadata"],
                    created_at=run.created_at,
                )
                findings.append(finding)
                if (
                    config is not None
                    and config.auto_fix_enabled
                    and finding.can_auto_fix
                ):
                    fix_requests.append(
                        ReviewFixRequest(
                            review_run=run,
                            review_finding=finding,
                            source=ReviewFixRequestSource.AUTO_POLICY,
                            status=ReviewFixRequestStatus.PENDING_APPROVAL,
                            approval_required=config.auto_fix_requires_approval,
                            approved_by=None,
                            approved_at=None,
                            rejected_by=None,
                            rejected_at=None,
                            runner_job_id=None,
                            result_payload=None,
                            created_at=run.created_at,
                            updated_at=run.created_at,
                        )
                    )

            session.add_all(findings)
            session.add_all(fix_requests)

            # 更新 thread_id (如果由适配器生成)
            if analysis_result.get("thread_id"):
                run.thread_id = analysis_result["thread_id"]

            for finding in findings:
                if (
                    config is not None
                    and config.auto_fix_enabled
                    and finding.can_auto_fix
                ):
                    await self.timeline_service.append_event(
                        session=session,
                        review_run=run,
                        event_type="fix_request_created",
                        dedupe_key=(
                            f"{run.id}:fix_request_created:{finding.rule_id}:{finding.file_path}:"
                            f"{finding.line_start}"
                        ),
                        payload={
                            "title": finding.title,
                            "severity": finding.severity,
                            "file_path": finding.file_path,
                        },
                    )

            return await self.run_service.complete_run(
                session=session,
                run_id=run_id,
                result_payload={
                    "analysis_mode": analysis_result.get("analysis_mode", "ai_agent"),
                    "findings_count": len(findings),
                    "auto_fix_request_count": len(fix_requests),
                    "thread_id": run.thread_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"Review analysis failed for run {run_id}")
            await session.rollback()
            return await self.run_service.fail_run(
                session=session,
                run_id=run_id,
                error_payload={
                    "error": "analysis execution failed",
                    "detail": str(exc),
                },
            )

    async def _perform_ai_analysis(
        self,
        *,
        session: AsyncSession,
        run: ReviewRun,
    ) -> dict[str, Any]:
        """核心 AI 分析流程：获取 Diff -> 调用 Agent Adapter -> 返回 Findings."""
        normalized_event = await self._load_normalized_event(session=session, run=run)

        # 1. 获取 SCM 凭证 (Token)
        # 优先级：环境变量 (测试用) > 数据库 (正式用)
        token = os.getenv("TEST_GITLAB_TOKEN")
        user_id = "test-user"  # 默认测试用户

        if not token:
            # 尝试从数据库获取 Token
            try:
                # 这里假设我们使用第一个关联的用户 Token
                from aegra_api.core.crypto import decrypt_payload

                from app.models.scm_token import ScmToken

                result = await session.execute(
                    select(ScmToken).where(ScmToken.provider == run.provider).limit(1)
                )
                scm_token_record = result.scalar_one_or_none()
                if scm_token_record:
                    decrypted = decrypt_payload(
                        scm_token_record.encrypted_token_payload
                    )
                    token = decrypted.get("access_token")
                    user_id = scm_token_record.user_id
            except Exception as e:
                logger.warning(f"Failed to fetch token from store: {e}")

        # 终极 Fallback：如果还是没有（常发生在 Webhook 异步 worker 中）
        if not token:
            # 此时应抛出错误，引导用户配置环境变量或数据库记录
            raise ValueError("No SCM token available for analysis (checked env and DB)")

        # 2. 获取 Diff 内容
        diff = ""
        repo_name = normalized_event.get("repository_full_name")
        mr_iid = normalized_event.get("external_pr_or_mr_id")

        if not repo_name or not mr_iid:
            logger.warning(f"Missing repo metadata in event: {normalized_event}")
            return {"status": "success", "findings": [], "analysis_mode": "no_context"}

        if run.provider == "gitlab":
            diff = await scm_repository_service.get_gitlab_mr_diff(
                repository=repo_name,
                mr_iid=int(mr_iid),
                access_token=token,
                gitlab_base_url=run.repository_integration.gitlab_base_url,
            )
        elif run.provider == "github":
            diff = await scm_repository_service.get_github_pr_diff(
                repository=repo_name,
                pr_number=int(mr_iid),
                access_token=token,
            )

        if not diff.strip():
            logger.info(f"No diff found for MR {mr_iid} in {repo_name}")
            return {"status": "success", "findings": [], "analysis_mode": "empty_diff"}

        logger.info(f"Analyzing diff (length: {len(diff)} characters)")
        # 3. 调用 Agent 适配器
        findings, thread_id = await self.agent_adapter.run_analysis(
            session=session,
            diff=diff,
            user_id=user_id,
            run_id=run.id,
            thread_id=run.thread_id,
        )

        return {
            "status": "success",
            "findings": findings,
            "thread_id": thread_id,
            "analysis_mode": "ai_agent",
        }

    async def _load_run(self, *, session: AsyncSession, run_id: int) -> ReviewRun:
        result = await session.execute(
            select(ReviewRun)
            .options(joinedload(ReviewRun.repository_integration))
            .where(ReviewRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise ValueError(f"review run {run_id} not found")
        return run

    async def _load_repository_config(
        self,
        *,
        session: AsyncSession,
        repository_integration_id: int | None,
    ) -> RepositoryReviewConfig | None:
        if repository_integration_id is None:
            return None
        result = await session.execute(
            select(RepositoryReviewConfig).where(
                RepositoryReviewConfig.repository_integration_id
                == repository_integration_id
            )
        )
        return result.scalar_one_or_none()

    async def _load_normalized_event(
        self,
        *,
        session: AsyncSession,
        run: ReviewRun,
    ) -> dict[str, Any]:
        events = await self.timeline_service.list_events(
            session=session,
            review_run_id=run.id,
        )
        for event in events:
            if event.event_type == "review_requested" and isinstance(
                event.payload, dict
            ):
                normalized_event = event.payload.get("normalized_event")
                if isinstance(normalized_event, dict):
                    return normalized_event
        return {
            "provider": run.provider,
            "provider_event_type": run.event_type,
            "repository_external_id": None,
            "repository_identity_key": None,
            "raw_payload": None,
        }

    def _build_finding_specs(
        self,
        *,
        analysis_result: dict[str, Any] | None,
        normalized_event: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if analysis_result is not None:
            findings = analysis_result.get("findings")
            if isinstance(findings, list) and findings:
                return [
                    self._normalize_finding_spec(item, normalized_event)
                    for item in findings
                ]

        return []

    def _normalize_finding_spec(
        self,
        value: Any,
        normalized_event: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError("analysis_result.findings must contain objects")
        severity = _as_lower_text(value.get("severity") or "medium")
        category = (
            str(value.get("category") or "maintainability").strip() or "maintainability"
        )
        file_path = str(value.get("file_path") or "src/app.py").strip() or "src/app.py"
        line_start = value.get("line_start")
        line_end = value.get("line_end")
        title = (
            str(value.get("title") or "Code review finding").strip()
            or "Code review finding"
        )
        body = value.get("body")
        body_text = str(body).strip() if body is not None else None
        rule_id = (
            str(value.get("rule_id") or "ai.review.rule").strip() or "ai.review.rule"
        )
        metadata = value.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata = {
            **metadata,
            "provider": normalized_event.get("provider"),
            "provider_event_type": normalized_event.get("provider_event_type"),
            "repository_identity_key": normalized_event.get("repository_identity_key"),
        }
        return {
            "severity": severity,
            "category": category,
            "file_path": file_path,
            "line_start": line_start if isinstance(line_start, int) else 1,
            "line_end": line_end if isinstance(line_end, int) else 1,
            "title": title,
            "body": body_text or "AI generated finding",
            "rule_id": rule_id,
            "metadata": metadata,
        }

    def _can_auto_fix(
        self,
        *,
        config: RepositoryReviewConfig | None,
        severity: str,
        metadata: dict[str, Any],
    ) -> bool:
        if config is None or not config.auto_fix_enabled:
            return False
        if not bool(metadata.get("auto_fixable", False)):
            return False
        allowed_severities = _extract_allowed_severities(config.auto_fix_severities)
        if allowed_severities is None:
            return True
        return _as_lower_text(severity) in allowed_severities


code_review_analyzer_service = CodeReviewAnalyzerService()
