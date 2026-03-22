from __future__ import annotations

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
from app.services.code_review.timeline_service import code_review_timeline_service


class _FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class _FakeRunSession:
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
        collection = self._collection_for(obj)
        if obj not in collection:
            collection.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self._pending.extend(objs)

    async def commit(self) -> None:
        self._materialize_pending()
        self._pending.clear()

    def _materialize_pending(self) -> None:
        for obj in self._pending:
            self._prepare_object(obj)

            collection = self._collection_for(obj)
            if obj not in collection:
                collection.append(obj)

    def _prepare_object(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_ids[type(obj)]
            self._next_ids[type(obj)] += 1
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

    async def rollback(self) -> None:
        self._pending.clear()

    async def refresh(self, obj: Any) -> None:
        return None


def _user(identity: str) -> SimpleNamespace:
    return SimpleNamespace(identity=identity)


def _seed_integration(
    session: _FakeRunSession,
    *,
    integration_id: int,
    provider: str = "github",
    external_repo_id: str = "123",
) -> RepositoryIntegration:
    integration = RepositoryIntegration(
        id=integration_id,
        provider=provider,
        external_repo_id=external_repo_id,
        repository_identity_key="",
        full_name="acme/project",
        default_branch="main",
        gitlab_base_url=None,
        webhook_status=None,
        webhook_management_mode=None,
        created_at=None,
        updated_at=None,
    )
    session.integrations.append(integration)
    return integration


def _seed_membership(
    session: _FakeRunSession,
    *,
    membership_id: int,
    repository_integration_id: int,
    user_id: str,
) -> RepositoryMembership:
    membership = RepositoryMembership(
        id=membership_id,
        repository_integration_id=repository_integration_id,
        user_id=user_id,
        role=None,
        can_approve_fixes=False,
        created_at=None,
        updated_at=None,
    )
    session.memberships.append(membership)
    return membership


def _seed_run(
    session: _FakeRunSession,
    *,
    run_id: int,
    repository_integration_id: int,
    status: ReviewRunStatus = ReviewRunStatus.QUEUED,
    created_at: datetime | None = None,
) -> ReviewRun:
    run = ReviewRun(
        id=run_id,
        repository_integration_id=repository_integration_id,
        provider="github",
        event_type="pull_request",
        external_event_id=None,
        external_pr_or_mr_id="17",
        head_commit_id="head-abc",
        base_commit_id="base-def",
        base_branch="main",
        head_branch="feature",
        status=status,
        idempotency_key=f"github::{repository_integration_id}:pull_request:17:head-abc",
        created_by_event_at=None,
        created_at=created_at,
        updated_at=created_at,
    )
    session.runs.append(run)
    return run


def _seed_event(
    session: _FakeRunSession,
    *,
    event_id: int,
    review_run: ReviewRun,
    event_type: str,
    dedupe_key: str,
) -> ReviewTimelineEvent:
    event = ReviewTimelineEvent(
        id=event_id,
        review_run=review_run,
        review_run_id=review_run.id,
        event_type=event_type,
        dedupe_key=dedupe_key,
        payload={"event_type": event_type},
        created_at=review_run.created_at,
    )
    session.timeline_events.append(event)
    return event


def _seed_finding(
    session: _FakeRunSession,
    *,
    finding_id: int,
    review_run: ReviewRun,
    title: str = "Use safer pattern",
    severity: str = "medium",
    can_auto_fix: bool = False,
) -> ReviewFinding:
    finding = ReviewFinding(
        id=finding_id,
        review_run=review_run,
        review_run_id=review_run.id,
        severity=severity,
        category="correctness",
        file_path="src/example.py",
        line_start=12,
        line_end=12,
        title=title,
        body="Potential issue",
        rule_id="R001",
        can_auto_fix=can_auto_fix,
        metadata_={"source": "test", "auto_fixable": can_auto_fix},
        created_at=review_run.created_at,
    )
    session.findings.append(finding)
    return finding


def _seed_fix_request(
    session: _FakeRunSession,
    *,
    fix_request_id: int,
    review_run: ReviewRun,
    review_finding: ReviewFinding,
) -> ReviewFixRequest:
    fix_request = ReviewFixRequest(
        id=fix_request_id,
        review_run=review_run,
        review_run_id=review_run.id,
        review_finding=review_finding,
        review_finding_id=review_finding.id,
        source=ReviewFixRequestSource.AUTO_POLICY,
        status=ReviewFixRequestStatus.PENDING_APPROVAL,
        approval_required=True,
        approved_by=None,
        approved_at=None,
        rejected_by=None,
        rejected_at=None,
        runner_job_id=None,
        result_payload=None,
        created_at=review_run.created_at,
        updated_at=review_run.created_at,
    )
    session.fix_requests.append(fix_request)
    return fix_request


def _seed_config(
    session: _FakeRunSession,
    *,
    config_id: int,
    repository_integration_id: int,
    review_enabled: bool = True,
    auto_fix_enabled: bool = False,
    auto_fix_severities: dict[str, Any] | None = None,
    auto_fix_requires_approval: bool = True,
) -> RepositoryReviewConfig:
    config = RepositoryReviewConfig(
        id=config_id,
        repository_integration_id=repository_integration_id,
        review_enabled=review_enabled,
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


def _override_db(session: _FakeRunSession):
    async def override_db() -> Any:
        yield session

    return override_db


@pytest.mark.asyncio
async def test_timeline_service_records_initial_review_lifecycle_events_once() -> None:
    session = _FakeRunSession()
    integration = _seed_integration(session, integration_id=1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    normalized_event = {
        "raw_payload": {"repository": {"id": 123}},
    }

    first_events = await code_review_timeline_service.record_initial_run_events(
        session=session,
        review_run=run,
        normalized_event=normalized_event,
    )
    second_events = await code_review_timeline_service.record_initial_run_events(
        session=session,
        review_run=run,
        normalized_event=normalized_event,
    )

    assert [event.event_type for event in first_events] == [
        "review_requested",
        "queued",
    ]
    assert [event.event_type for event in second_events] == [
        "review_requested",
        "queued",
    ]
    assert [event.event_type for event in session.timeline_events] == [
        "review_requested",
        "queued",
    ]


@pytest.mark.asyncio
async def test_analyzer_persists_findings_and_auto_fix_requests_and_completes_run() -> (
    None
):
    session = _FakeRunSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_config(
        session,
        config_id=1,
        repository_integration_id=integration.id or 1,
        auto_fix_enabled=True,
        auto_fix_severities={"allowed_severities": ["medium"]},
        auto_fix_requires_approval=True,
    )
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    _seed_event(
        session,
        event_id=1,
        review_run=run,
        event_type="review_requested",
        dedupe_key=run.idempotency_key,
    )
    _seed_event(
        session,
        event_id=2,
        review_run=run,
        event_type="queued",
        dedupe_key=run.idempotency_key,
    )

    analyzed = await code_review_run_dispatcher.analyze_run(session=session, run_id=1)

    assert analyzed["status"] == ReviewRunStatus.COMPLETED.value
    assert run.status == ReviewRunStatus.COMPLETED
    assert [finding.severity for finding in session.findings] == ["medium"]
    assert session.findings[0].can_auto_fix is True
    assert len(session.fix_requests) == 1
    assert session.fix_requests[0].source == ReviewFixRequestSource.AUTO_POLICY
    assert session.fix_requests[0].status == ReviewFixRequestStatus.PENDING_APPROVAL
    assert session.fix_requests[0].approval_required is True
    assert [event.event_type for event in session.timeline_events] == [
        "review_requested",
        "queued",
        "analysis_started",
        "fix_request_created",
        "analysis_completed",
    ]


@pytest.mark.asyncio
async def test_analyzer_failure_marks_run_failed_and_records_timeline() -> None:
    session = _FakeRunSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_config(session, config_id=1, repository_integration_id=integration.id or 1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    _seed_event(
        session,
        event_id=1,
        review_run=run,
        event_type="review_requested",
        dedupe_key=run.idempotency_key,
    )
    _seed_event(
        session,
        event_id=2,
        review_run=run,
        event_type="queued",
        dedupe_key=run.idempotency_key,
    )

    analyzed = await code_review_run_dispatcher.analyze_run(
        session=session,
        run_id=1,
        analysis_result={"status": "failed", "error": "boom"},
    )

    assert analyzed["status"] == ReviewRunStatus.FAILED.value
    assert run.status == ReviewRunStatus.FAILED
    assert session.findings == []
    assert session.fix_requests == []
    assert [event.event_type for event in session.timeline_events] == [
        "review_requested",
        "queued",
        "analysis_started",
        "analysis_failed",
    ]


@pytest.mark.asyncio
async def test_analyzer_invalid_finding_payload_marks_run_failed() -> None:
    session = _FakeRunSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_config(session, config_id=1, repository_integration_id=integration.id or 1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    _seed_event(
        session,
        event_id=1,
        review_run=run,
        event_type="review_requested",
        dedupe_key=run.idempotency_key,
    )
    _seed_event(
        session,
        event_id=2,
        review_run=run,
        event_type="queued",
        dedupe_key=run.idempotency_key,
    )

    analyzed = await code_review_run_dispatcher.analyze_run(
        session=session,
        run_id=1,
        analysis_result={"findings": ["bad"]},
    )

    assert analyzed["status"] == ReviewRunStatus.FAILED.value
    assert run.status == ReviewRunStatus.FAILED
    assert session.findings == []
    assert session.fix_requests == []
    assert [event.event_type for event in session.timeline_events] == [
        "review_requested",
        "queued",
        "analysis_started",
        "analysis_failed",
    ]


@pytest.mark.asyncio
async def test_dispatcher_enqueue_schedules_background_analysis_when_session_maker_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled_run_ids: list[int] = []

    class _FakeContextSessionManager:
        async def __aenter__(self) -> _FakeRunSession:
            return _FakeRunSession()

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

    class _FakeSessionMaker:
        def __call__(self) -> _FakeContextSessionManager:
            return _FakeContextSessionManager()

    def fake_get_async_session_maker() -> _FakeSessionMaker:
        return _FakeSessionMaker()

    class _FakeTask:
        def cancel(self) -> bool:
            return True

    def fake_create_task(coro: Any) -> _FakeTask:
        scheduled_run_ids.append(coro.cr_frame.f_locals["run_id"])
        coro.close()
        return _FakeTask()

    monkeypatch.setattr(
        database_module, "get_async_session_maker", fake_get_async_session_maker
    )
    monkeypatch.setattr(
        "app.services.code_review.dispatcher.get_async_session_maker",
        fake_get_async_session_maker,
    )
    monkeypatch.setattr(
        "asyncio.get_running_loop",
        lambda: SimpleNamespace(create_task=fake_create_task),
    )

    session = _FakeRunSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)

    enqueued = await code_review_run_dispatcher.enqueue_run(session=session, run_id=1)

    assert enqueued["status"] == ReviewRunStatus.ANALYZING.value
    assert enqueued["transitioned_to_analyzing"] is True
    assert scheduled_run_ids == [1]


@pytest.mark.asyncio
async def test_dispatcher_enqueue_does_not_reschedule_when_run_already_analyzing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled_run_ids: list[int] = []

    class _FakeTask:
        def cancel(self) -> bool:
            return True

    def fake_create_task(coro: Any) -> _FakeTask:
        scheduled_run_ids.append(coro.cr_frame.f_locals["run_id"])
        coro.close()
        return _FakeTask()

    monkeypatch.setattr(
        "asyncio.get_running_loop",
        lambda: SimpleNamespace(create_task=fake_create_task),
    )
    monkeypatch.setattr(
        "app.services.code_review.dispatcher.get_async_session_maker",
        lambda: SimpleNamespace(__call__=lambda self: None),
    )

    session = _FakeRunSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_run(
        session,
        run_id=1,
        repository_integration_id=integration.id or 1,
        status=ReviewRunStatus.ANALYZING,
    )

    enqueued = await code_review_run_dispatcher.enqueue_run(session=session, run_id=1)

    assert enqueued["status"] == ReviewRunStatus.ANALYZING.value
    assert enqueued["transitioned_to_analyzing"] is False
    assert scheduled_run_ids == []


@pytest.mark.asyncio
async def test_run_dispatcher_transitions_to_analyzing_and_completes() -> None:
    session = _FakeRunSession()
    integration = _seed_integration(session, integration_id=1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)

    analyzing = await code_review_run_dispatcher.enqueue_run(session=session, run_id=1)
    analyzing_again = await code_review_run_dispatcher.enqueue_run(
        session=session, run_id=1
    )
    completed = await code_review_run_dispatcher.complete_run(
        session=session,
        run_id=1,
        result_payload={"summary": "ok"},
    )

    assert analyzing["status"] == ReviewRunStatus.ANALYZING.value
    assert analyzing_again["status"] == ReviewRunStatus.ANALYZING.value
    assert completed["status"] == ReviewRunStatus.COMPLETED.value
    assert run.status == ReviewRunStatus.COMPLETED
    assert [event.event_type for event in session.timeline_events] == [
        "analysis_started",
        "analysis_completed",
    ]


@pytest.mark.asyncio
async def test_run_dispatcher_can_fail_runs() -> None:
    session = _FakeRunSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)

    failed = await code_review_run_dispatcher.fail_run(
        session=session,
        run_id=1,
        error_payload={"error": "boom"},
    )

    assert failed["status"] == ReviewRunStatus.FAILED.value
    assert [event.event_type for event in session.timeline_events] == [
        "analysis_failed"
    ]


def test_run_routes_list_and_detail_scope_results_to_visible_memberships() -> None:
    session = _FakeRunSession()
    visible_integration = _seed_integration(session, integration_id=1)
    hidden_integration = _seed_integration(session, integration_id=2)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=visible_integration.id or 1,
        user_id="run-user",
    )
    visible_run = _seed_run(
        session,
        run_id=11,
        repository_integration_id=visible_integration.id or 1,
        created_at=datetime(2026, 3, 22, 10, 30, tzinfo=UTC),
    )
    hidden_run = _seed_run(
        session,
        run_id=22,
        repository_integration_id=hidden_integration.id or 2,
        created_at=datetime(2026, 3, 22, 10, 31, tzinfo=UTC),
    )
    _seed_event(
        session,
        event_id=101,
        review_run=visible_run,
        event_type="review_requested",
        dedupe_key="visible",
    )
    _seed_event(
        session,
        event_id=102,
        review_run=visible_run,
        event_type="queued",
        dedupe_key="visible",
    )
    _seed_event(
        session,
        event_id=201,
        review_run=hidden_run,
        event_type="review_requested",
        dedupe_key="hidden",
    )

    async def override_user() -> SimpleNamespace:
        return _user("run-user")

    app.dependency_overrides[authenticated_user] = override_user
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
            list_response = client.get("/api/code-review/runs")
            assert list_response.status_code == 200
            list_payload = list_response.json()
            assert [item["id"] for item in list_payload["runs"]] == [11]
            assert list_payload["runs"][0]["status"] == ReviewRunStatus.QUEUED.value

            detail_response = client.get("/api/code-review/runs/11")
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["id"] == 11
            assert detail_payload["repository"]["id"] == 1
            assert detail_payload["findings"] == []
            assert [
                event["event_type"] for event in detail_payload["timeline_events"]
            ] == [
                "review_requested",
                "queued",
            ]

            hidden_response = client.get("/api/code-review/runs/22")
            assert hidden_response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_code_review_run_routes_are_registered_on_main_app() -> None:
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/code-review/runs" in route_paths
    assert "/api/code-review/runs/{id}" in route_paths


def test_run_detail_includes_findings() -> None:
    session = _FakeRunSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=integration.id or 1,
        user_id="run-user",
    )
    run = _seed_run(
        session,
        run_id=11,
        repository_integration_id=integration.id or 1,
        created_at=datetime(2026, 3, 22, 10, 30, tzinfo=UTC),
    )
    finding = _seed_finding(session, finding_id=501, review_run=run)
    _seed_fix_request(
        session,
        fix_request_id=601,
        review_run=run,
        review_finding=finding,
    )

    async def override_user() -> SimpleNamespace:
        return _user("run-user")

    app.dependency_overrides[authenticated_user] = override_user
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
            detail_response = client.get("/api/code-review/runs/11")
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert [finding["id"] for finding in detail_payload["findings"]] == [501]
            assert detail_payload["findings"][0]["title"] == "Use safer pattern"
            assert detail_payload["fix_requests"] == [
                {
                    "id": 601,
                    "review_run_id": 11,
                    "review_finding_id": 501,
                    "source": "auto_policy",
                    "status": "pending_approval",
                    "approval_required": True,
                    "approved_by": None,
                    "approved_at": None,
                    "rejected_by": None,
                    "rejected_at": None,
                    "runner_job_id": None,
                    "result_payload": None,
                    "updated_at": "2026-03-22T10:30:00Z",
                }
            ]
    finally:
        app.dependency_overrides.clear()


def test_publish_run_requires_visibility_and_completed_status() -> None:
    session = _FakeRunSession()
    visible_integration = _seed_integration(session, integration_id=1)
    hidden_integration = _seed_integration(session, integration_id=2)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=visible_integration.id or 1,
        user_id="run-user",
    )
    _seed_run(
        session,
        run_id=11,
        repository_integration_id=visible_integration.id or 1,
        status=ReviewRunStatus.COMPLETED,
        created_at=datetime(2026, 3, 22, 10, 30, tzinfo=UTC),
    )
    _seed_run(
        session,
        run_id=22,
        repository_integration_id=hidden_integration.id or 2,
        status=ReviewRunStatus.COMPLETED,
        created_at=datetime(2026, 3, 22, 10, 31, tzinfo=UTC),
    )
    _seed_run(
        session,
        run_id=33,
        repository_integration_id=visible_integration.id or 1,
        status=ReviewRunStatus.ANALYZING,
        created_at=datetime(2026, 3, 22, 10, 32, tzinfo=UTC),
    )

    async def override_user() -> SimpleNamespace:
        return _user("run-user")

    app.dependency_overrides[authenticated_user] = override_user
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
            publish_response = client.post("/api/code-review/runs/11/publish")
            assert publish_response.status_code == 200
            publish_payload = publish_response.json()
            assert publish_payload["published"] is True
            assert publish_payload["run_id"] == 11
            assert publish_payload["status"] == ReviewRunStatus.COMPLETED.value
            assert [event.event_type for event in session.timeline_events] == [
                "publish_requested",
                "publish_completed",
            ]

            second_response = client.post("/api/code-review/runs/11/publish")
            assert second_response.status_code == 200
            assert second_response.json()["published"] is True
            assert [event.event_type for event in session.timeline_events] == [
                "publish_requested",
                "publish_completed",
            ]

            hidden_response = client.post("/api/code-review/runs/22/publish")
            assert hidden_response.status_code == 404

            analyzing_response = client.post("/api/code-review/runs/33/publish")
            assert analyzing_response.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_code_review_publish_route_is_registered_on_main_app() -> None:
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/code-review/runs/{id}/publish" in route_paths
