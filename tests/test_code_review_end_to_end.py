from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import database as database_module
from app.core.auth import authenticated_user
from app.core.database import get_db
from app.main import app
from app.models.code_review import (
    RepositoryIntegration,
    RepositoryMembership,
    RepositoryReviewConfig,
    ReviewFinding,
    ReviewFixRequest,
    ReviewFixRequestSource,
    ReviewFixRequestStatus,
    ReviewRun,
    ReviewRunStatus,
    ReviewTimelineEvent,
)
from app.services.code_review.dispatcher import code_review_run_dispatcher


class _FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class _FakeEndToEndSession:
    def __init__(self) -> None:
        self.integrations: list[RepositoryIntegration] = []
        self.memberships: list[RepositoryMembership] = []
        self.configs: list[RepositoryReviewConfig] = []
        self.runs: list[ReviewRun] = []
        self.findings: list[ReviewFinding] = []
        self.fix_requests: list[ReviewFixRequest] = []
        self.timeline_events: list[ReviewTimelineEvent] = []
        self._pending: list[Any] = []
        self._next_ids = {
            RepositoryIntegration: 1,
            RepositoryMembership: 1,
            RepositoryReviewConfig: 1,
            ReviewRun: 1,
            ReviewFinding: 1,
            ReviewFixRequest: 1,
            ReviewTimelineEvent: 1,
        }

    async def scalars(self, stmt: Any) -> _FakeScalarResult:  # noqa: ARG002
        entity = stmt.column_descriptions[0]["entity"]
        if entity is RepositoryIntegration:
            return _FakeScalarResult(self.integrations)
        if entity is RepositoryMembership:
            return _FakeScalarResult(self.memberships)
        if entity is RepositoryReviewConfig:
            return _FakeScalarResult(self.configs)
        if entity is ReviewRun:
            return _FakeScalarResult(self.runs)
        if entity is ReviewFinding:
            return _FakeScalarResult(self.findings)
        if entity is ReviewFixRequest:
            return _FakeScalarResult(self.fix_requests)
        if entity is ReviewTimelineEvent:
            return _FakeScalarResult(self.timeline_events)
        return _FakeScalarResult([])

    def add(self, obj: Any) -> None:
        self._prepare_object(obj)
        self._pending.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self._pending.extend(objs)

    async def commit(self) -> None:
        self._materialize_pending()
        self._pending.clear()

    async def rollback(self) -> None:
        self._pending.clear()

    async def refresh(self, obj: Any) -> None:  # noqa: ARG002
        return None

    def _prepare_object(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_ids[type(obj)]
            self._next_ids[type(obj)] += 1
        if (
            isinstance(obj, RepositoryMembership)
            and obj.repository_integration is not None
        ):
            obj.repository_integration_id = obj.repository_integration.id
        if (
            isinstance(obj, RepositoryReviewConfig)
            and obj.repository_integration is not None
        ):
            obj.repository_integration_id = obj.repository_integration.id
        if isinstance(obj, ReviewRun) and obj.repository_integration is not None:
            obj.repository_integration_id = obj.repository_integration.id
        if isinstance(obj, ReviewFinding) and obj.review_run is not None:
            obj.review_run_id = obj.review_run.id
        if isinstance(obj, ReviewFixRequest):
            if obj.review_run is not None:
                obj.review_run_id = obj.review_run.id
            if obj.review_finding is not None:
                obj.review_finding_id = obj.review_finding.id
        if isinstance(obj, ReviewTimelineEvent) and obj.review_run is not None:
            obj.review_run_id = obj.review_run.id

    def _materialize_pending(self) -> None:
        for obj in self._pending:
            self._prepare_object(obj)
            collection = self._collection_for(obj)
            if obj not in collection:
                collection.append(obj)

    def _collection_for(self, obj: Any) -> list[Any]:
        if isinstance(obj, RepositoryIntegration):
            return self.integrations
        if isinstance(obj, RepositoryMembership):
            return self.memberships
        if isinstance(obj, RepositoryReviewConfig):
            return self.configs
        if isinstance(obj, ReviewRun):
            return self.runs
        if isinstance(obj, ReviewFinding):
            return self.findings
        if isinstance(obj, ReviewFixRequest):
            return self.fix_requests
        if isinstance(obj, ReviewTimelineEvent):
            return self.timeline_events
        raise AssertionError(f"unexpected object {type(obj)!r}")


def _seed_integration(
    session: _FakeEndToEndSession,
    *,
    integration_id: int,
    provider: str = "github",
    external_repo_id: str = "123",
    repository_identity_key: str = "",
) -> RepositoryIntegration:
    integration = RepositoryIntegration(
        id=integration_id,
        provider=provider,
        external_repo_id=external_repo_id,
        repository_identity_key=repository_identity_key,
        full_name="acme/project",
        default_branch="main",
        gitlab_base_url=repository_identity_key if repository_identity_key else None,
        webhook_status=None,
        webhook_management_mode=None,
        created_at=None,
        updated_at=None,
    )
    session.integrations.append(integration)
    return integration


def _seed_membership(
    session: _FakeEndToEndSession,
    *,
    membership_id: int,
    repository_integration_id: int,
    user_id: str,
    can_approve_fixes: bool = True,
) -> RepositoryMembership:
    membership = RepositoryMembership(
        id=membership_id,
        repository_integration_id=repository_integration_id,
        user_id=user_id,
        role=None,
        can_approve_fixes=can_approve_fixes,
        created_at=None,
        updated_at=None,
    )
    session.memberships.append(membership)
    return membership


def _seed_config(
    session: _FakeEndToEndSession,
    *,
    config_id: int,
    repository_integration_id: int,
    auto_fix_enabled: bool = True,
    auto_fix_severities: dict[str, Any] | None = None,
    auto_fix_requires_approval: bool = True,
) -> RepositoryReviewConfig:
    config = RepositoryReviewConfig(
        id=config_id,
        repository_integration_id=repository_integration_id,
        review_enabled=True,
        review_triggers=None,
        auto_fix_enabled=auto_fix_enabled,
        auto_fix_severities=auto_fix_severities,
        auto_fix_requires_approval=auto_fix_requires_approval,
        auto_publish_enabled=False,
        updated_by=None,
        updated_at=None,
    )
    session.configs.append(config)
    return config


def _seed_github_payload() -> dict[str, Any]:
    return {
        "action": "opened",
        "repository": {"id": 123, "full_name": "acme/project"},
        "pull_request": {
            "id": 9001,
            "number": 17,
            "head": {"sha": "head-abc", "ref": "feature"},
            "base": {"sha": "base-def", "ref": "main"},
        },
    }


def _github_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _override_db(session: _FakeEndToEndSession):
    async def override_db() -> Any:
        yield session

    return override_db


def _override_user(identity: str):
    async def override_user() -> SimpleNamespace:
        return SimpleNamespace(identity=identity)

    return override_user


@pytest.mark.asyncio
async def test_code_review_happy_path_webhook_analysis_fix_and_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeEndToEndSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=integration.id or 1,
        user_id="approver",
        can_approve_fixes=True,
    )
    _seed_config(
        session,
        config_id=1,
        repository_integration_id=integration.id or 1,
        auto_fix_enabled=True,
        auto_fix_severities={"allowed_severities": ["medium"]},
        auto_fix_requires_approval=True,
    )

    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "github-secret")
    monkeypatch.setenv("SANDBOX_AGENT_CODE_REVIEW_WEBHOOK_SECRET", "shared-secret")
    monkeypatch.setenv("SANDBOX_AGENT_CODE_REVIEW_FIX_RUNNER_SECRET", "runner-secret")
    scheduled_run_ids: list[int] = []

    def fake_schedule_background_analysis(*, run_id: int) -> None:
        scheduled_run_ids.append(run_id)

    monkeypatch.setattr(database_module, "get_async_session_maker", lambda: None)
    monkeypatch.setattr(
        code_review_run_dispatcher,
        "_schedule_background_analysis",
        fake_schedule_background_analysis,
    )

    body = json.dumps(
        _seed_github_payload(), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    app.dependency_overrides[authenticated_user] = _override_user("approver")
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
            webhook_response = client.post(
                "/api/code-review/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": _github_signature("github-secret", body),
                },
            )
            assert webhook_response.status_code == 202
            webhook_payload = webhook_response.json()
            assert webhook_payload["ok"] is True
            assert webhook_payload["queued"] is True
            assert webhook_payload["review_run_id"] == 1
            assert session.runs[0].status == ReviewRunStatus.ANALYZING
            assert scheduled_run_ids == [1]
            assert [event.event_type for event in session.timeline_events] == [
                "review_requested",
                "queued",
                "analysis_started",
            ]

            analyzed = await code_review_run_dispatcher.analyze_run(
                session=session, run_id=1
            )
            assert analyzed["status"] == ReviewRunStatus.COMPLETED.value
            assert len(session.findings) == 1
            assert session.findings[0].can_auto_fix is True
            assert len(session.fix_requests) == 1
            fix_request = session.fix_requests[0]
            assert fix_request.status == ReviewFixRequestStatus.PENDING_APPROVAL
            assert fix_request.source == ReviewFixRequestSource.AUTO_POLICY
            assert [event.event_type for event in session.timeline_events] == [
                "review_requested",
                "queued",
                "analysis_started",
                "fix_request_created",
                "analysis_completed",
            ]

            approve_response = client.post("/api/code-review/fix-requests/1/approve")
            assert approve_response.status_code == 200
            approve_payload = approve_response.json()
            assert approve_payload["status"] == ReviewFixRequestStatus.RUNNING.value
            assert approve_payload["runner_job_id"] == "fix-request-1"
            assert fix_request.status == ReviewFixRequestStatus.RUNNING
            assert fix_request.runner_job_id == "fix-request-1"
            assert [event.event_type for event in session.timeline_events] == [
                "review_requested",
                "queued",
                "analysis_started",
                "fix_request_created",
                "analysis_completed",
                "fix_request_approved",
                "fix_request_running",
            ]

            callback_response = client.post(
                "/api/code-review/fix-runner/callback",
                json={
                    "runner_job_id": "fix-request-1",
                    "status": "completed",
                    "result_payload": {"summary": "ok"},
                },
                headers={"X-Sandbox-Agent-Fix-Runner-Secret": "runner-secret"},
            )
            assert callback_response.status_code == 200
            callback_payload = callback_response.json()
            assert callback_payload["status"] == ReviewFixRequestStatus.COMPLETED.value
            assert fix_request.status == ReviewFixRequestStatus.COMPLETED
            assert fix_request.result_payload == {"summary": "ok"}
            assert [event.event_type for event in session.timeline_events] == [
                "review_requested",
                "queued",
                "analysis_started",
                "fix_request_created",
                "analysis_completed",
                "fix_request_approved",
                "fix_request_running",
                "fix_request_completed",
            ]

            duplicate_callback = client.post(
                "/api/code-review/fix-runner/callback",
                json={
                    "runner_job_id": "fix-request-1",
                    "status": "completed",
                    "result_payload": {"summary": "ok"},
                },
                headers={"X-Sandbox-Agent-Fix-Runner-Secret": "runner-secret"},
            )
            assert duplicate_callback.status_code == 200
            assert (
                duplicate_callback.json()["status"]
                == ReviewFixRequestStatus.COMPLETED.value
            )
            assert [event.event_type for event in session.timeline_events] == [
                "review_requested",
                "queued",
                "analysis_started",
                "fix_request_created",
                "analysis_completed",
                "fix_request_approved",
                "fix_request_running",
                "fix_request_completed",
            ]
    finally:
        app.dependency_overrides.clear()


def test_code_review_fix_runner_callback_rejects_bad_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeEndToEndSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=integration.id or 1,
        user_id="approver",
        can_approve_fixes=True,
    )
    _seed_config(session, config_id=1, repository_integration_id=integration.id or 1)
    run = ReviewRun(
        id=1,
        repository_integration_id=integration.id or 1,
        provider="github",
        event_type="pull_request",
        external_event_id=None,
        external_pr_or_mr_id="17",
        head_commit_id="head-abc",
        base_commit_id="base-def",
        base_branch="main",
        head_branch="feature",
        status=ReviewRunStatus.COMPLETED,
        idempotency_key="github::123:pull_request:17:head-abc",
        created_by_event_at=None,
        created_at=datetime(2026, 3, 22, 10, 30, tzinfo=UTC),
        updated_at=datetime(2026, 3, 22, 10, 30, tzinfo=UTC),
    )
    session.runs.append(run)
    finding = ReviewFinding(
        id=1,
        review_run=run,
        review_run_id=run.id,
        severity="medium",
        category="correctness",
        file_path="src/app.py",
        line_start=10,
        line_end=10,
        title="Use safer pattern",
        body="Potential issue",
        rule_id="R001",
        can_auto_fix=True,
        metadata_={"auto_fixable": True},
        created_at=run.created_at,
    )
    session.findings.append(finding)
    fix_request = ReviewFixRequest(
        id=1,
        review_run=run,
        review_run_id=run.id,
        review_finding=finding,
        review_finding_id=finding.id,
        source=ReviewFixRequestSource.AUTO_POLICY,
        status=ReviewFixRequestStatus.RUNNING,
        approval_required=True,
        approved_by="approver",
        approved_at=run.created_at,
        rejected_by=None,
        rejected_at=None,
        runner_job_id="fix-request-1",
        result_payload=None,
        created_at=run.created_at,
        updated_at=run.created_at,
    )
    session.fix_requests.append(fix_request)

    monkeypatch.setenv("SANDBOX_AGENT_CODE_REVIEW_FIX_RUNNER_SECRET", "runner-secret")
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/code-review/fix-runner/callback",
                json={
                    "runner_job_id": "fix-request-1",
                    "status": "completed",
                    "result_payload": {"summary": "ok"},
                },
                headers={"X-Sandbox-Agent-Fix-Runner-Secret": "wrong-secret"},
            )
            assert response.status_code == 401
            assert fix_request.status == ReviewFixRequestStatus.RUNNING
            assert session.timeline_events == []
    finally:
        app.dependency_overrides.clear()
