from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.auth import authenticated_user
from app.core.database import get_db
from app.main import app
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


def _set_fix_runner_secret(
    monkeypatch: pytest.MonkeyPatch, secret: str = "runner-secret"
) -> None:
    monkeypatch.setenv("OPENWEBPX_CODE_REVIEW_FIX_RUNNER_SECRET", secret)


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
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(session, fix_request_id=1, review_run=run, review_finding=finding)

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    app.dependency_overrides[authenticated_user] = override_user
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
            response = client.post("/api/code-review/fix-requests/1/approve")
            assert response.status_code == 403
            assert (
                session.fix_requests[0].status
                == ReviewFixRequestStatus.PENDING_APPROVAL
            )
            assert session.timeline_events == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_transitions_request_and_starts_runner() -> None:
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
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(session, fix_request_id=1, review_run=run, review_finding=finding)

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    app.dependency_overrides[authenticated_user] = override_user
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
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
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_rejects_non_pending_fix_request() -> None:
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

    app.dependency_overrides[authenticated_user] = override_user
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
            response = client.post("/api/code-review/fix-requests/1/approve")
            assert response.status_code == 409
            assert session.timeline_events == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reject_transitions_request_to_rejected() -> None:
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
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(session, fix_request_id=1, review_run=run, review_finding=finding)

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    app.dependency_overrides[authenticated_user] = override_user
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
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
        app.dependency_overrides.clear()


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
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(session, fix_request_id=1, review_run=run, review_finding=finding)

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    app.dependency_overrides[authenticated_user] = override_user
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
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
                headers={"X-OpenWebPX-Fix-Runner-Secret": "runner-secret"},
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
                headers={"X-OpenWebPX-Fix-Runner-Secret": "runner-secret"},
            )
            assert second_response.status_code == 200
            assert second_response.json()["status"] == terminal_status
            assert [event.event_type for event in session.timeline_events] == [
                "fix_request_approved",
                "fix_request_running",
                f"fix_request_{terminal_status}",
            ]
    finally:
        app.dependency_overrides.clear()


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
    finding = _seed_finding(session, finding_id=1, review_run=run)
    _seed_fix_request(session, fix_request_id=1, review_run=run, review_finding=finding)

    async def override_user() -> SimpleNamespace:
        return _user("approver")

    app.dependency_overrides[authenticated_user] = override_user
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        with TestClient(app) as client:
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
        app.dependency_overrides.clear()


def test_fix_routes_are_registered_on_main_app() -> None:
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/code-review/fix-requests/{id}/approve" in route_paths
    assert "/api/code-review/fix-requests/{id}/reject" in route_paths
    assert "/api/code-review/fix-runner/callback" in route_paths
