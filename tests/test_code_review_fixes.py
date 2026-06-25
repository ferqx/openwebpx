from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.auth import authenticated_user
from app.core.database import get_db
from app.main import app, create_app
from app.models.code_review import (
    RepositoryIntegration,
    RepositoryMembership,
    ReviewFinding,
    ReviewFixRequest,
    ReviewFixRequestSource,
    ReviewFixRequestStatus,
    ReviewRun,
    ReviewRunStatus,
    ReviewTimelineEvent,
)
from app.services.code_review.fix_service import (
    CodeReviewFixService,
    code_review_fix_service,
)


class _FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class _FakeFixSession:
    def __init__(self) -> None:
        self.integrations: list[RepositoryIntegration] = []
        self.memberships: list[RepositoryMembership] = []
        self.runs: list[ReviewRun] = []
        self.findings: list[ReviewFinding] = []
        self.fix_requests: list[ReviewFixRequest] = []
        self.timeline_events: list[ReviewTimelineEvent] = []
        self._pending: list[Any] = []
        self._next_ids = {
            RepositoryIntegration: 1,
            RepositoryMembership: 1,
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
        self._materialize_relationship_ids(obj)
        self._pending.append(obj)
        collection = self._collection_for(obj)
        if obj not in collection:
            collection.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        for obj in objs:
            self.add(obj)

    async def commit(self) -> None:
        self._pending.clear()

    async def rollback(self) -> None:
        self._pending.clear()

    async def refresh(self, obj: Any) -> None:  # noqa: ARG002
        return None

    def _materialize_relationship_ids(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_ids[type(obj)]
            self._next_ids[type(obj)] += 1
        if (
            isinstance(obj, RepositoryMembership)
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

    def _collection_for(self, obj: Any) -> list[Any]:
        if isinstance(obj, RepositoryIntegration):
            return self.integrations
        if isinstance(obj, RepositoryMembership):
            return self.memberships
        if isinstance(obj, ReviewRun):
            return self.runs
        if isinstance(obj, ReviewFinding):
            return self.findings
        if isinstance(obj, ReviewFixRequest):
            return self.fix_requests
        if isinstance(obj, ReviewTimelineEvent):
            return self.timeline_events
        raise AssertionError(f"unexpected object {type(obj)!r}")


def _user(identity: str) -> SimpleNamespace:
    return SimpleNamespace(identity=identity)


def _override_db(session: _FakeFixSession):
    async def override_db() -> Any:
        yield session

    return override_db


def _make_test_app():
    return create_app(include_lifespan=False)


def _set_fix_runner_secret(
    monkeypatch: pytest.MonkeyPatch, secret: str = "runner-secret"
) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_CODE_REVIEW_FIX_RUNNER_SECRET", secret)


def _seed_integration(
    session: _FakeFixSession,
    *,
    integration_id: int,
) -> RepositoryIntegration:
    integration = RepositoryIntegration(
        id=integration_id,
        provider="github",
        external_repo_id="123",
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
    session: _FakeFixSession,
    *,
    membership_id: int,
    repository_integration_id: int,
    user_id: str,
    can_approve_fixes: bool,
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


def _seed_run(
    session: _FakeFixSession,
    *,
    run_id: int,
    repository_integration_id: int,
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
        status=ReviewRunStatus.COMPLETED,
        idempotency_key=f"github::{repository_integration_id}:pull_request:17:head-abc",
        created_by_event_at=None,
        created_at=datetime(2026, 3, 22, 10, 30, tzinfo=UTC),
        updated_at=datetime(2026, 3, 22, 10, 30, tzinfo=UTC),
    )
    session.runs.append(run)
    return run


def _seed_finding(
    session: _FakeFixSession,
    *,
    finding_id: int,
    review_run: ReviewRun,
    can_auto_fix: bool = True,
) -> ReviewFinding:
    finding = ReviewFinding(
        id=finding_id,
        review_run=review_run,
        review_run_id=review_run.id,
        severity="medium",
        category="correctness",
        file_path="src/app.py",
        line_start=10,
        line_end=10,
        title="Use safer pattern",
        body="Potential issue",
        rule_id="R001",
        can_auto_fix=can_auto_fix,
        metadata_={"auto_fixable": can_auto_fix},
        created_at=review_run.created_at,
    )
    session.findings.append(finding)
    return finding


def _seed_fix_request(
    session: _FakeFixSession,
    *,
    fix_request_id: int,
    review_run: ReviewRun,
    review_finding: ReviewFinding,
    status: ReviewFixRequestStatus = ReviewFixRequestStatus.PENDING_APPROVAL,
    approval_required: bool = True,
) -> ReviewFixRequest:
    fix_request = ReviewFixRequest(
        id=fix_request_id,
        review_run=review_run,
        review_run_id=review_run.id,
        review_finding=review_finding,
        review_finding_id=review_finding.id,
        source=ReviewFixRequestSource.AUTO_POLICY,
        status=status,
        approval_required=approval_required,
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


class _RecordingTimelineService:
    def __init__(self) -> None:
        self.event_types: list[str] = []

    async def append_event(
        self,
        *,
        session: _FakeFixSession,
        review_run: ReviewRun,
        event_type: str,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        created_at: datetime | None = None,
    ) -> ReviewTimelineEvent:
        event = ReviewTimelineEvent(
            id=len(session.timeline_events) + 1,
            review_run=review_run,
            review_run_id=review_run.id,
            event_type=event_type,
            dedupe_key=dedupe_key,
            payload=payload,
            created_at=created_at or datetime.now(UTC),
        )
        session.timeline_events.append(event)
        self.event_types.append(event_type)
        return event


class _RecordingFixRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def start_fix(
        self,
        *,
        session: _FakeFixSession,
        fix_request: ReviewFixRequest,
        thread: Any,
        instruction: str,
    ) -> dict[str, Any]:
        metadata = {
            "runner_job_id": f"fix-request-{fix_request.id}",
            "thread_id": thread.thread_id,
            "status": "running",
            "queue_scope": "thread",
        }
        self.calls.append(
            {
                "session": session,
                "fix_request_id": fix_request.id,
                "thread_id": thread.thread_id,
                "instruction": instruction,
                "metadata": metadata,
            }
        )
        return metadata


def _make_fake_thread(
    *, thread_id: str, status: str = "idle", user_id: str = "author"
) -> SimpleNamespace:
    return SimpleNamespace(thread_id=thread_id, status=status, user_id=user_id)


def _patch_service_for_immediate_queue_dispatch(
    *,
    service: CodeReviewFixService,
    fix_request: ReviewFixRequest,
    fix_runner: _RecordingFixRunner,
    timeline_service: _RecordingTimelineService,
    thread_status: str = "idle",
) -> None:
    thread = _make_fake_thread(
        thread_id=str(fix_request.review_run.thread_id or ""),
        status=thread_status,
    )

    async def fake_load_thread(
        *, session: _FakeFixSession, thread_id: str
    ) -> SimpleNamespace:
        assert thread_id == thread.thread_id
        return thread

    async def fake_process_thread_queue_once(
        *, session: _FakeFixSession, thread_id: str
    ) -> bool:
        assert thread_id == thread.thread_id
        if thread.status != "idle":
            return False
        metadata = await fix_runner.start_fix(
            session=session,
            fix_request=fix_request,
            thread=thread,
            instruction=service._build_fix_instruction(fix_request),
        )
        fix_request.runner_job_id = metadata["runner_job_id"]
        fix_request.status = ReviewFixRequestStatus.RUNNING
        await timeline_service.append_event(
            session=session,
            review_run=fix_request.review_run,
            event_type="fix_request_running",
            dedupe_key=f"{fix_request.id}:fix_request_running",
            payload={
                "fix_request_id": fix_request.id,
                "runner_job_id": metadata["runner_job_id"],
                "thread_id": thread_id,
            },
        )
        return True

    async def fake_ensure_background_worker(*, thread_id: str) -> None:
        assert thread_id == thread.thread_id

    service._load_thread = fake_load_thread  # type: ignore[method-assign]
    service.process_thread_queue_once = fake_process_thread_queue_once  # type: ignore[method-assign]
    service.ensure_background_worker = fake_ensure_background_worker  # type: ignore[method-assign]


def _patch_route_service_for_immediate_queue_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session: _FakeFixSession,
) -> None:
    async def fake_get_fix_request(
        *, session: _FakeFixSession, fix_request_id: int
    ) -> ReviewFixRequest:
        for candidate in session.fix_requests:
            if candidate.id == fix_request_id:
                return candidate
        raise HTTPException(404, "Fix request not found")

    async def fake_ensure_approval_permission(
        *,
        session: _FakeFixSession,
        current_user: Any,
        repository_integration_id: int | None,
    ) -> None:
        user_id = getattr(current_user, "identity", None)
        membership = next(
            (
                candidate
                for candidate in session.memberships
                if candidate.repository_integration_id == repository_integration_id
                and candidate.user_id == user_id
            ),
            None,
        )
        if membership and membership.can_approve_fixes:
            return
        raise HTTPException(403, "Current user cannot approve fix requests")

    async def fake_load_thread(
        *, session: _FakeFixSession, thread_id: str
    ) -> SimpleNamespace:
        return _make_fake_thread(thread_id=thread_id)

    async def fake_process_thread_queue_once(
        *, session: _FakeFixSession, thread_id: str
    ) -> bool:
        fix_request = next(
            (
                candidate
                for candidate in session.fix_requests
                if candidate.status == ReviewFixRequestStatus.APPROVED
            ),
            None,
        )
        if fix_request is None:
            return False
        fix_request.runner_job_id = f"fix-request-{fix_request.id}"
        fix_request.status = ReviewFixRequestStatus.RUNNING
        await code_review_fix_service.timeline_service.append_event(
            session=session,
            review_run=fix_request.review_run,
            event_type="fix_request_running",
            dedupe_key=f"{fix_request.id}:fix_request_running",
            payload={
                "fix_request_id": fix_request.id,
                "runner_job_id": fix_request.runner_job_id,
                "thread_id": thread_id,
            },
        )
        return True

    async def fake_ensure_background_worker(*, thread_id: str) -> None:
        return None

    async def fake_get_fix_request_by_runner_job_id(
        *, session: _FakeFixSession, runner_job_id: str
    ) -> ReviewFixRequest | None:
        return next(
            (
                candidate
                for candidate in session.fix_requests
                if candidate.runner_job_id == runner_job_id
            ),
            None,
        )

    monkeypatch.setattr(code_review_fix_service, "_load_thread", fake_load_thread)
    monkeypatch.setattr(
        code_review_fix_service, "_get_fix_request", fake_get_fix_request
    )
    monkeypatch.setattr(
        code_review_fix_service,
        "_ensure_approval_permission",
        fake_ensure_approval_permission,
    )
    monkeypatch.setattr(
        code_review_fix_service,
        "process_thread_queue_once",
        fake_process_thread_queue_once,
    )
    monkeypatch.setattr(
        code_review_fix_service,
        "ensure_background_worker",
        fake_ensure_background_worker,
    )
    monkeypatch.setattr(
        code_review_fix_service,
        "_get_fix_request_by_runner_job_id",
        fake_get_fix_request_by_runner_job_id,
    )


@pytest.mark.asyncio
async def test_service_approve_transitions_request_and_starts_runner() -> None:
    session = _FakeFixSession()
    timeline_service = _RecordingTimelineService()
    fix_runner = _RecordingFixRunner()
    service = CodeReviewFixService(
        fix_runner=fix_runner,
        timeline_service=timeline_service,
    )
    integration = _seed_integration(session, integration_id=1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-existing-1"
    run.repository_integration = integration
    finding = _seed_finding(session, finding_id=1, review_run=run)
    fix_request = _seed_fix_request(
        session,
        fix_request_id=1,
        review_run=run,
        review_finding=finding,
    )

    async def fake_get_fix_request(
        *, session: _FakeFixSession, fix_request_id: int
    ) -> ReviewFixRequest:
        assert fix_request_id == 1
        return fix_request

    async def fake_ensure_approval_permission(
        *,
        session: _FakeFixSession,
        current_user: Any,
        repository_integration_id: int | None,
    ) -> None:
        assert repository_integration_id == integration.id
        assert getattr(current_user, "identity", None) == "approver"

    service._get_fix_request = fake_get_fix_request  # type: ignore[method-assign]
    service._ensure_approval_permission = fake_ensure_approval_permission  # type: ignore[method-assign]
    _patch_service_for_immediate_queue_dispatch(
        service=service,
        fix_request=fix_request,
        fix_runner=fix_runner,
        timeline_service=timeline_service,
    )

    payload = await service.approve_fix_request(
        session=session,
        current_user=_user("approver"),
        fix_request_id=1,
    )

    assert payload["status"] == ReviewFixRequestStatus.RUNNING.value
    assert payload["runner_job_id"] == "fix-request-1"
    assert payload["runner"] == {
        "runner_job_id": "fix-request-1",
        "thread_id": "thread-existing-1",
        "status": "running",
        "queue_scope": "thread",
    }
    assert fix_request.status == ReviewFixRequestStatus.RUNNING
    assert fix_request.runner_job_id == "fix-request-1"
    assert fix_runner.calls == [
        {
            "session": session,
            "fix_request_id": 1,
            "thread_id": "thread-existing-1",
            "instruction": (
                "Fix request #1 for review run #1.\n"
                "Finding: Use safer pattern\n"
                "Location: src/app.py:10\n"
                "Detail: Potential issue\n"
                "Continue in the same task thread and make the minimal correct fix."
            ),
            "metadata": {
                "runner_job_id": "fix-request-1",
                "thread_id": "thread-existing-1",
                "status": "running",
                "queue_scope": "thread",
            },
        }
    ]
    assert timeline_service.event_types == [
        "fix_request_approved",
        "fix_request_running",
    ]


@pytest.mark.asyncio
async def test_service_approve_uses_existing_review_run_thread_id() -> None:
    session = _FakeFixSession()
    timeline_service = _RecordingTimelineService()
    fix_runner = _RecordingFixRunner()
    service = CodeReviewFixService(
        fix_runner=fix_runner,
        timeline_service=timeline_service,
    )
    integration = _seed_integration(session, integration_id=1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-review-123"
    run.repository_integration = integration
    finding = _seed_finding(session, finding_id=1, review_run=run)
    fix_request = _seed_fix_request(
        session,
        fix_request_id=1,
        review_run=run,
        review_finding=finding,
    )

    async def fake_get_fix_request(
        *, session: _FakeFixSession, fix_request_id: int
    ) -> ReviewFixRequest:
        assert fix_request_id == 1
        return fix_request

    async def fake_ensure_approval_permission(
        *,
        session: _FakeFixSession,
        current_user: Any,
        repository_integration_id: int | None,
    ) -> None:
        assert repository_integration_id == integration.id
        assert getattr(current_user, "identity", None) == "approver"

    service._get_fix_request = fake_get_fix_request  # type: ignore[method-assign]
    service._ensure_approval_permission = fake_ensure_approval_permission  # type: ignore[method-assign]
    _patch_service_for_immediate_queue_dispatch(
        service=service,
        fix_request=fix_request,
        fix_runner=fix_runner,
        timeline_service=timeline_service,
    )

    payload = await service.approve_fix_request(
        session=session,
        current_user=_user("approver"),
        fix_request_id=1,
    )

    assert payload["runner"]["thread_id"] == "thread-review-123"
    assert fix_runner.calls[0]["thread_id"] == "thread-review-123"


@pytest.mark.asyncio
async def test_service_approve_fails_clearly_when_review_run_thread_id_missing() -> (
    None
):
    session = _FakeFixSession()
    timeline_service = _RecordingTimelineService()
    fix_runner = _RecordingFixRunner()
    service = CodeReviewFixService(
        fix_runner=fix_runner,
        timeline_service=timeline_service,
    )
    integration = _seed_integration(session, integration_id=1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = None
    run.repository_integration = integration
    finding = _seed_finding(session, finding_id=1, review_run=run)
    fix_request = _seed_fix_request(
        session,
        fix_request_id=1,
        review_run=run,
        review_finding=finding,
    )

    async def fake_get_fix_request(
        *, session: _FakeFixSession, fix_request_id: int
    ) -> ReviewFixRequest:
        assert fix_request_id == 1
        return fix_request

    async def fake_ensure_approval_permission(
        *,
        session: _FakeFixSession,
        current_user: Any,
        repository_integration_id: int | None,
    ) -> None:
        assert repository_integration_id == integration.id
        assert getattr(current_user, "identity", None) == "approver"

    service._get_fix_request = fake_get_fix_request  # type: ignore[method-assign]
    service._ensure_approval_permission = fake_ensure_approval_permission  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as exc_info:
        await service.approve_fix_request(
            session=session,
            current_user=_user("approver"),
            fix_request_id=1,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Review run has no bound thread_id for fix approval"
    assert fix_request.status == ReviewFixRequestStatus.PENDING_APPROVAL
    assert fix_request.runner_job_id is None
    assert fix_runner.calls == []
    assert timeline_service.event_types == []


@pytest.mark.asyncio
async def test_service_approve_does_not_create_or_return_new_thread_id() -> None:
    session = _FakeFixSession()
    timeline_service = _RecordingTimelineService()
    fix_runner = _RecordingFixRunner()
    service = CodeReviewFixService(
        fix_runner=fix_runner,
        timeline_service=timeline_service,
    )
    integration = _seed_integration(session, integration_id=1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-original-9"
    run.repository_integration = integration
    finding = _seed_finding(session, finding_id=1, review_run=run)
    fix_request = _seed_fix_request(
        session,
        fix_request_id=1,
        review_run=run,
        review_finding=finding,
    )

    async def fake_get_fix_request(
        *, session: _FakeFixSession, fix_request_id: int
    ) -> ReviewFixRequest:
        assert fix_request_id == 1
        return fix_request

    async def fake_ensure_approval_permission(
        *,
        session: _FakeFixSession,
        current_user: Any,
        repository_integration_id: int | None,
    ) -> None:
        assert repository_integration_id == integration.id
        assert getattr(current_user, "identity", None) == "approver"

    service._get_fix_request = fake_get_fix_request  # type: ignore[method-assign]
    service._ensure_approval_permission = fake_ensure_approval_permission  # type: ignore[method-assign]
    _patch_service_for_immediate_queue_dispatch(
        service=service,
        fix_request=fix_request,
        fix_runner=fix_runner,
        timeline_service=timeline_service,
    )

    payload = await service.approve_fix_request(
        session=session,
        current_user=_user("approver"),
        fix_request_id=1,
    )

    assert payload["runner"]["thread_id"] == "thread-original-9"
    assert "new_thread_id" not in payload
    assert "new_thread_id" not in payload["runner"]
    assert all(call["thread_id"] == "thread-original-9" for call in fix_runner.calls)


@pytest.mark.asyncio
async def test_serialize_fix_request_does_not_report_queued_runner_for_terminal_status() -> (
    None
):
    session = _FakeFixSession()
    integration = _seed_integration(session, integration_id=1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-terminal-1"
    run.repository_integration = integration
    finding = _seed_finding(session, finding_id=1, review_run=run)
    fix_request = _seed_fix_request(
        session,
        fix_request_id=1,
        review_run=run,
        review_finding=finding,
        status=ReviewFixRequestStatus.COMPLETED,
    )
    fix_request.runner_job_id = "fix-request-1"

    service = CodeReviewFixService()

    payload = service._serialize_fix_request(fix_request)

    assert payload["runner_job_id"] == "fix-request-1"
    assert payload["runner"] is None


@pytest.mark.asyncio
async def test_process_thread_queue_once_does_not_start_next_fix_while_thread_busy() -> (
    None
):
    session = _FakeFixSession()
    timeline_service = _RecordingTimelineService()
    fix_runner = _RecordingFixRunner()
    service = CodeReviewFixService(
        fix_runner=fix_runner,
        timeline_service=timeline_service,
    )
    integration = _seed_integration(session, integration_id=1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-busy-1"
    run.repository_integration = integration
    finding = _seed_finding(session, finding_id=1, review_run=run)
    fix_request = _seed_fix_request(
        session,
        fix_request_id=1,
        review_run=run,
        review_finding=finding,
        status=ReviewFixRequestStatus.APPROVED,
    )
    fix_request.approved_at = datetime(2026, 3, 26, 10, 0, tzinfo=UTC)
    thread = _make_fake_thread(thread_id="thread-busy-1", status="busy")

    async def fake_load_thread(
        *, session: _FakeFixSession, thread_id: str
    ) -> SimpleNamespace:
        assert thread_id == thread.thread_id
        return thread

    async def fake_get_running_fix_request(
        *, session: _FakeFixSession, thread_id: str
    ) -> ReviewFixRequest | None:
        return None

    async def fake_get_next_approved_fix_request(
        *, session: _FakeFixSession, thread_id: str
    ) -> ReviewFixRequest | None:
        return fix_request

    service._load_thread = fake_load_thread  # type: ignore[method-assign]
    service._get_running_fix_request = fake_get_running_fix_request  # type: ignore[method-assign]
    service._get_next_approved_fix_request = fake_get_next_approved_fix_request  # type: ignore[method-assign]

    progressed = await service.process_thread_queue_once(
        session=session,
        thread_id="thread-busy-1",
    )

    assert progressed is False
    assert fix_request.status == ReviewFixRequestStatus.APPROVED
    assert fix_request.runner_job_id is None
    assert fix_runner.calls == []
    assert timeline_service.event_types == []


@pytest.mark.asyncio
async def test_process_thread_queue_once_dispatches_fifo_after_running_fix_completes() -> (
    None
):
    session = _FakeFixSession()
    timeline_service = _RecordingTimelineService()
    fix_runner = _RecordingFixRunner()
    service = CodeReviewFixService(
        fix_runner=fix_runner,
        timeline_service=timeline_service,
    )
    integration = _seed_integration(session, integration_id=1)
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-fifo-1"
    run.repository_integration = integration
    finding_one = _seed_finding(session, finding_id=1, review_run=run)
    finding_two = _seed_finding(session, finding_id=2, review_run=run)
    first_fix = _seed_fix_request(
        session,
        fix_request_id=1,
        review_run=run,
        review_finding=finding_one,
        status=ReviewFixRequestStatus.RUNNING,
    )
    first_fix.approved_at = datetime(2026, 3, 26, 10, 0, tzinfo=UTC)
    first_fix.runner_job_id = "run-existing-1"
    second_fix = _seed_fix_request(
        session,
        fix_request_id=2,
        review_run=run,
        review_finding=finding_two,
        status=ReviewFixRequestStatus.APPROVED,
    )
    second_fix.approved_at = datetime(2026, 3, 26, 10, 5, tzinfo=UTC)
    thread = _make_fake_thread(thread_id="thread-fifo-1", status="idle")

    async def fake_load_thread(
        *, session: _FakeFixSession, thread_id: str
    ) -> SimpleNamespace:
        assert thread_id == thread.thread_id
        return thread

    async def fake_get_running_fix_request(
        *, session: _FakeFixSession, thread_id: str
    ) -> ReviewFixRequest | None:
        for candidate in session.fix_requests:
            if (
                candidate.review_run.thread_id == thread_id
                and candidate.status == ReviewFixRequestStatus.RUNNING
            ):
                return candidate
        return None

    async def fake_get_next_approved_fix_request(
        *, session: _FakeFixSession, thread_id: str
    ) -> ReviewFixRequest | None:
        approved = [
            candidate
            for candidate in session.fix_requests
            if (
                candidate.review_run.thread_id == thread_id
                and candidate.status == ReviewFixRequestStatus.APPROVED
            )
        ]
        approved.sort(
            key=lambda candidate: (
                candidate.approved_at or datetime.max.replace(tzinfo=UTC),
                candidate.created_at or datetime.max.replace(tzinfo=UTC),
                candidate.id or 0,
            )
        )
        return approved[0] if approved else None

    async def fake_get_aegra_run(
        *, session: _FakeFixSession, run_id: str
    ) -> SimpleNamespace | None:
        if run_id != "run-existing-1":
            return None
        return SimpleNamespace(status="success", output={"summary": "done"})

    service._load_thread = fake_load_thread  # type: ignore[method-assign]
    service._get_running_fix_request = fake_get_running_fix_request  # type: ignore[method-assign]
    service._get_next_approved_fix_request = fake_get_next_approved_fix_request  # type: ignore[method-assign]
    service._get_aegra_run = fake_get_aegra_run  # type: ignore[method-assign]

    progressed = await service.process_thread_queue_once(
        session=session,
        thread_id="thread-fifo-1",
    )

    assert progressed is True
    assert first_fix.status == ReviewFixRequestStatus.COMPLETED
    assert second_fix.status == ReviewFixRequestStatus.RUNNING
    assert second_fix.runner_job_id == "fix-request-2"
    assert [call["fix_request_id"] for call in fix_runner.calls] == [2]
    assert timeline_service.event_types == [
        "fix_request_completed",
        "fix_request_running",
    ]


@pytest.mark.asyncio
async def test_approve_requires_approval_rights() -> None:
    session = _FakeFixSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=integration.id or 1,
        user_id="approver",
        can_approve_fixes=False,
    )
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-route-forbidden-1"
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(session, fix_request_id=1, review_run=run, review_finding=finding)

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    test_app = _make_test_app()
    test_app.dependency_overrides[authenticated_user] = override_user
    test_app.dependency_overrides[get_db] = _override_db(session)
    monkeypatch = pytest.MonkeyPatch()
    _patch_route_service_for_immediate_queue_dispatch(monkeypatch, session=session)
    try:
        with TestClient(test_app) as client:
            response = client.post("/api/code-review/fix-requests/1/approve")
            assert response.status_code == 403
            assert (
                session.fix_requests[0].status
                == ReviewFixRequestStatus.PENDING_APPROVAL
            )
            assert session.timeline_events == []
    finally:
        monkeypatch.undo()
        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_transitions_request_and_starts_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeFixSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=integration.id or 1,
        user_id="approver",
        can_approve_fixes=True,
    )
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-route-1"
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(session, fix_request_id=1, review_run=run, review_finding=finding)
    _patch_route_service_for_immediate_queue_dispatch(monkeypatch, session=session)

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    test_app = _make_test_app()
    test_app.dependency_overrides[authenticated_user] = override_user
    test_app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(test_app) as client:
            response = client.post("/api/code-review/fix-requests/1/approve")
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == ReviewFixRequestStatus.RUNNING.value
            assert payload["runner_job_id"] == "fix-request-1"
            assert session.fix_requests[0].status == ReviewFixRequestStatus.RUNNING
            assert session.fix_requests[0].runner_job_id == "fix-request-1"
            assert [event.event_type for event in session.timeline_events] == [
                "fix_request_approved",
                "fix_request_running",
            ]
    finally:
        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_rejects_non_pending_fix_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeFixSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=integration.id or 1,
        user_id="approver",
        can_approve_fixes=True,
    )
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-route-conflict-1"
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(
        session,
        fix_request_id=1,
        review_run=run,
        review_finding=finding,
        status=ReviewFixRequestStatus.REJECTED,
    )

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    test_app = _make_test_app()
    test_app.dependency_overrides[authenticated_user] = override_user
    test_app.dependency_overrides[get_db] = _override_db(session)
    _patch_route_service_for_immediate_queue_dispatch(monkeypatch, session=session)
    try:
        with TestClient(test_app) as client:
            response = client.post("/api/code-review/fix-requests/1/approve")
            assert response.status_code == 409
            assert session.timeline_events == []
    finally:
        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reject_transitions_request_to_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeFixSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=integration.id or 1,
        user_id="approver",
        can_approve_fixes=True,
    )
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-route-reject-1"
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(session, fix_request_id=1, review_run=run, review_finding=finding)

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    test_app = _make_test_app()
    test_app.dependency_overrides[authenticated_user] = override_user
    test_app.dependency_overrides[get_db] = _override_db(session)
    _patch_route_service_for_immediate_queue_dispatch(monkeypatch, session=session)
    try:
        with TestClient(test_app) as client:
            response = client.post(
                "/api/code-review/fix-requests/1/reject",
                json={"reason": "not needed"},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == ReviewFixRequestStatus.REJECTED.value
            assert session.fix_requests[0].status == ReviewFixRequestStatus.REJECTED
            assert [event.event_type for event in session.timeline_events] == [
                "fix_request_rejected",
            ]
    finally:
        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
async def test_runner_callback_updates_terminal_state_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    terminal_status: str,
) -> None:
    _set_fix_runner_secret(monkeypatch)
    session = _FakeFixSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=integration.id or 1,
        user_id="approver",
        can_approve_fixes=True,
    )
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-callback-1"
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(session, fix_request_id=1, review_run=run, review_finding=finding)
    _patch_route_service_for_immediate_queue_dispatch(monkeypatch, session=session)

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    test_app = _make_test_app()
    test_app.dependency_overrides[authenticated_user] = override_user
    test_app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(test_app) as client:
            approve_response = client.post("/api/code-review/fix-requests/1/approve")
            assert approve_response.status_code == 200
            runner_job_id = approve_response.json()["runner_job_id"]
            assert runner_job_id == "fix-request-1"

            callback_payload = {
                "runner_job_id": runner_job_id,
                "status": terminal_status,
                "result_payload": {"detail": terminal_status},
            }
            first_response = client.post(
                "/api/code-review/fix-runner/callback",
                json=callback_payload,
                headers={"X-Sandbox-Agent-Fix-Runner-Secret": "runner-secret"},
            )
            assert first_response.status_code == 200
            first_payload = first_response.json()
            assert first_payload["status"] == terminal_status
            assert session.fix_requests[0].status == (
                ReviewFixRequestStatus.COMPLETED
                if terminal_status == "completed"
                else ReviewFixRequestStatus.FAILED
            )
            assert [event.event_type for event in session.timeline_events] == [
                "fix_request_approved",
                "fix_request_running",
                f"fix_request_{terminal_status}",
            ]

            second_response = client.post(
                "/api/code-review/fix-runner/callback",
                json=callback_payload,
                headers={"X-Sandbox-Agent-Fix-Runner-Secret": "runner-secret"},
            )
            assert second_response.status_code == 200
            assert second_response.json()["status"] == terminal_status
            assert [event.event_type for event in session.timeline_events] == [
                "fix_request_approved",
                "fix_request_running",
                f"fix_request_{terminal_status}",
            ]
    finally:
        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_runner_callback_requires_shared_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fix_runner_secret(monkeypatch)
    session = _FakeFixSession()
    integration = _seed_integration(session, integration_id=1)
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=integration.id or 1,
        user_id="approver",
        can_approve_fixes=True,
    )
    run = _seed_run(session, run_id=1, repository_integration_id=integration.id or 1)
    run.thread_id = "thread-callback-secret-1"
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(session, fix_request_id=1, review_run=run, review_finding=finding)
    _patch_route_service_for_immediate_queue_dispatch(monkeypatch, session=session)

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    test_app = _make_test_app()
    test_app.dependency_overrides[authenticated_user] = override_user
    test_app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(test_app) as client:
            approve_response = client.post("/api/code-review/fix-requests/1/approve")
            assert approve_response.status_code == 200

            callback_payload = {
                "runner_job_id": "fix-request-1",
                "status": "completed",
                "result_payload": {"detail": "completed"},
            }
            response = client.post(
                "/api/code-review/fix-runner/callback",
                json=callback_payload,
            )
            assert response.status_code == 401
            assert session.fix_requests[0].status == ReviewFixRequestStatus.RUNNING
            assert [event.event_type for event in session.timeline_events] == [
                "fix_request_approved",
                "fix_request_running",
            ]
    finally:
        test_app.dependency_overrides.clear()


def test_fix_routes_are_registered_on_main_app() -> None:
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/code-review/fix-requests/{id}/approve" in route_paths
    assert "/api/code-review/fix-requests/{id}/reject" in route_paths
    assert "/api/code-review/fix-runner/callback" in route_paths
