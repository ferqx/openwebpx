from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.main import app
from app.models.code_review import (
    RepositoryIntegration,
    RepositoryReviewConfig,
    ReviewRun,
    ReviewRunStatus,
    ReviewTimelineEvent,
)
from app.services.code_review.provider_github import (
    normalize_github_webhook_payload,
    verify_github_webhook_signature,
)
from app.services.code_review.provider_gitlab import (
    normalize_gitlab_webhook_payload,
    verify_gitlab_webhook_token,
)


class _FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any | None:
        return self._items[0] if self._items else None

    def one_or_none(self) -> Any | None:
        return self.first()


class _FakeWebhookSession:
    def __init__(
        self,
        *,
        fail_commit_once: bool = False,
        conflict_run_on_rollback: ReviewRun | None = None,
        conflict_timeline_events_on_rollback: list[ReviewTimelineEvent] | None = None,
    ) -> None:
        self.integrations: list[RepositoryIntegration] = []
        self.configs: list[RepositoryReviewConfig] = []
        self.runs: list[ReviewRun] = []
        self.timeline_events: list[ReviewTimelineEvent] = []
        self._pending: list[Any] = []
        self._fail_commit_once = fail_commit_once
        self._conflict_run_on_rollback = conflict_run_on_rollback
        self._conflict_timeline_events_on_rollback = (
            conflict_timeline_events_on_rollback or []
        )
        self._conflict_run_injected = False
        self._conflict_events_injected = False
        self._commit_calls = 0
        self._next_ids = {
            RepositoryIntegration: 1,
            RepositoryReviewConfig: 1,
            ReviewRun: 1,
            ReviewTimelineEvent: 1,
        }

    async def scalars(self, stmt: Any) -> _FakeScalarResult:  # noqa: ARG002
        entity = stmt.column_descriptions[0]["entity"]
        if entity is RepositoryIntegration:
            return _FakeScalarResult(self.integrations)
        if entity is RepositoryReviewConfig:
            return _FakeScalarResult(self.configs)
        if entity is ReviewRun:
            return _FakeScalarResult(self.runs)
        if entity is ReviewTimelineEvent:
            return _FakeScalarResult(self.timeline_events)
        return _FakeScalarResult([])

    def add(self, obj: Any) -> None:
        self._pending.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self._pending.extend(objs)

    async def commit(self) -> None:
        self._commit_calls += 1
        if self._fail_commit_once and self._commit_calls == 1:
            self._pending.clear()
            raise IntegrityError("insert", {}, Exception("unique violation"))
        self._materialize_pending()
        self._pending.clear()

    def _materialize_pending(self) -> None:
        for obj in self._pending:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_ids[type(obj)]
                self._next_ids[type(obj)] += 1
            collection = self._collection_for(obj)
            if obj not in collection:
                collection.append(obj)
            if isinstance(obj, ReviewRun) and obj.repository_integration is not None:
                obj.repository_integration_id = obj.repository_integration.id
            if isinstance(obj, ReviewTimelineEvent) and obj.review_run is not None:
                obj.review_run_id = obj.review_run.id
            if (
                isinstance(obj, RepositoryReviewConfig)
                and obj.repository_integration is not None
            ):
                obj.repository_integration_id = obj.repository_integration.id

    def _collection_for(self, obj: Any) -> list[Any]:
        if isinstance(obj, RepositoryIntegration):
            return self.integrations
        if isinstance(obj, RepositoryReviewConfig):
            return self.configs
        if isinstance(obj, ReviewRun):
            return self.runs
        if isinstance(obj, ReviewTimelineEvent):
            return self.timeline_events
        raise AssertionError(f"unexpected object {type(obj)!r}")

    async def rollback(self) -> None:
        self._pending.clear()
        if (
            self._conflict_run_on_rollback is not None
            and not self._conflict_run_injected
        ):
            self._conflict_run_injected = True
            if self._conflict_run_on_rollback.id is None:
                self._conflict_run_on_rollback.id = self._next_ids[ReviewRun]
                self._next_ids[ReviewRun] += 1
            if self._conflict_run_on_rollback not in self.runs:
                self.runs.append(self._conflict_run_on_rollback)
        if (
            self._conflict_timeline_events_on_rollback
            and not self._conflict_events_injected
        ):
            self._conflict_events_injected = True
            for event in self._conflict_timeline_events_on_rollback:
                if event.id is None:
                    event.id = self._next_ids[ReviewTimelineEvent]
                    self._next_ids[ReviewTimelineEvent] += 1
                if event.review_run is not None and event.review_run.id is not None:
                    event.review_run_id = event.review_run.id
                if event not in self.timeline_events:
                    self.timeline_events.append(event)

    async def refresh(self, obj: Any) -> None:
        return None


def _seed_integration(
    session: _FakeWebhookSession,
    *,
    integration_id: int,
    provider: str,
    external_repo_id: str,
    repository_identity_key: str,
    gitlab_base_url: str | None = None,
) -> RepositoryIntegration:
    integration = RepositoryIntegration(
        id=integration_id,
        provider=provider,
        external_repo_id=external_repo_id,
        repository_identity_key=repository_identity_key,
        full_name="acme/project",
        default_branch="main",
        gitlab_base_url=gitlab_base_url,
        webhook_status=None,
        webhook_management_mode=None,
        created_at=None,
        updated_at=None,
    )
    session.integrations.append(integration)
    return integration


def _seed_config(
    session: _FakeWebhookSession,
    *,
    config_id: int,
    repository_integration_id: int,
    review_enabled: bool = True,
) -> RepositoryReviewConfig:
    config = RepositoryReviewConfig(
        id=config_id,
        repository_integration_id=repository_integration_id,
        review_enabled=review_enabled,
        review_triggers=None,
        auto_fix_enabled=False,
        auto_fix_severities=None,
        auto_fix_requires_approval=True,
        auto_publish_enabled=False,
        updated_by=None,
        updated_at=None,
    )
    session.configs.append(config)
    return config


def _seed_review_run(
    session: _FakeWebhookSession,
    *,
    run_id: int,
    repository_integration_id: int,
    provider: str,
    event_type: str,
    idempotency_key: str,
) -> ReviewRun:
    run = ReviewRun(
        id=run_id,
        repository_integration_id=repository_integration_id,
        provider=provider,
        event_type=event_type,
        external_event_id=None,
        external_pr_or_mr_id=None,
        head_commit_id=None,
        base_commit_id=None,
        base_branch=None,
        head_branch=None,
        status=ReviewRunStatus.QUEUED,
        idempotency_key=idempotency_key,
        created_by_event_at=None,
        created_at=None,
        updated_at=None,
    )
    session.runs.append(run)
    session._next_ids[ReviewRun] = max(session._next_ids[ReviewRun], run_id + 1)
    return run


def _seed_timeline_event(
    session: _FakeWebhookSession,
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
        payload={"seeded": True},
        created_at=None,
    )
    session.timeline_events.append(event)
    session._next_ids[ReviewTimelineEvent] = max(
        session._next_ids[ReviewTimelineEvent], event_id + 1
    )
    return event


def _github_payload(
    *,
    repo_id: int = 123,
    number: int = 17,
    head_sha: str = "head-abc",
    base_sha: str = "base-def",
) -> dict[str, Any]:
    return {
        "action": "opened",
        "repository": {
            "id": repo_id,
            "full_name": "acme/project",
        },
        "pull_request": {
            "id": 9001,
            "number": number,
            "head": {"sha": head_sha, "ref": "feature"},
            "base": {"sha": base_sha, "ref": "main"},
        },
    }


def _gitlab_payload(
    *,
    repo_id: int = 777,
    iid: int = 7,
    head_sha: str = "gitlab-head",
    base_sha: str = "gitlab-base",
    project_web_url: str = "https://GitLab.One/group/project",
) -> dict[str, Any]:
    return {
        "object_kind": "merge_request",
        "object_attributes": {
            "id": 8001,
            "iid": iid,
            "action": "open",
            "source_branch": "feature",
            "target_branch": "main",
            "last_commit": {"id": head_sha},
            "oldrev": base_sha,
        },
        "project": {
            "id": repo_id,
            "path_with_namespace": "group/project",
            "web_url": project_web_url,
        },
    }


def _github_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _override_db_factory(session: _FakeWebhookSession):
    async def override_db() -> Any:
        yield session

    return override_db


def _override_main_app_db(session: _FakeWebhookSession) -> None:
    app.dependency_overrides[get_db] = _override_db_factory(session)


def _set_webhook_secrets(
    monkeypatch: pytest.MonkeyPatch, *, github: str, gitlab: str
) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", github)
    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", gitlab)
    monkeypatch.setenv("OPENWEBPX_CODE_REVIEW_WEBHOOK_SECRET", "shared-secret")


@pytest.mark.asyncio
async def test_provider_payload_normalization_to_unified_review_event_fields() -> None:
    github_event = normalize_github_webhook_payload(
        _github_payload(),
        event_type="pull_request",
    )
    assert github_event["provider"] == "github"
    assert github_event["repository_external_id"] == "123"
    assert github_event["repository_identity_key"] == ""
    assert github_event["provider_event_type"] == "pull_request"
    assert github_event["external_pr_or_mr_id"] == "17"
    assert github_event["head_commit_id"] == "head-abc"
    assert github_event["base_commit_id"] == "base-def"
    assert github_event["head_branch"] == "feature"
    assert github_event["base_branch"] == "main"
    assert github_event["raw_payload"]["repository"]["id"] == 123

    gitlab_event = normalize_gitlab_webhook_payload(
        _gitlab_payload(),
        gitlab_base_url="https://GitLab.One",
    )
    assert gitlab_event["provider"] == "gitlab"
    assert gitlab_event["repository_external_id"] == "777"
    assert gitlab_event["repository_identity_key"] == "https://gitlab.one"
    assert gitlab_event["provider_event_type"] == "merge_request"
    assert gitlab_event["external_pr_or_mr_id"] == "7"
    assert gitlab_event["head_commit_id"] == "gitlab-head"
    assert gitlab_event["base_commit_id"] == "gitlab-base"
    assert gitlab_event["head_branch"] == "feature"
    assert gitlab_event["base_branch"] == "main"
    assert gitlab_event["raw_payload"]["project"]["id"] == 777
    assert (
        normalize_gitlab_webhook_payload(
            _gitlab_payload(),
            gitlab_base_url="https://GitLab.One/subpath",
        )["repository_identity_key"]
        == "https://gitlab.one/subpath"
    )
    assert (
        normalize_gitlab_webhook_payload(
            _gitlab_payload(project_web_url="https://GitLab.One/subpath/group/project"),
            gitlab_base_url=None,
        )["repository_identity_key"]
        == "https://gitlab.one/subpath"
    )
    assert (
        normalize_github_webhook_payload(_github_payload(), event_type="ping") is None
    )
    assert (
        normalize_gitlab_webhook_payload(
            {
                "object_kind": "push",
                "project": {"id": 777},
            },
            gitlab_base_url="https://GitLab.One",
        )
        is None
    )


def test_github_webhook_signature_validation() -> None:
    body = json.dumps(
        _github_payload(), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    secret = "github-secret"
    assert verify_github_webhook_signature(
        secret=secret,
        body=body,
        signature_header=_github_signature(secret, body),
    )
    assert not verify_github_webhook_signature(
        secret=secret,
        body=body,
        signature_header="sha256=deadbeef",
    )


def test_gitlab_webhook_token_validation() -> None:
    assert verify_gitlab_webhook_token(
        secret="gitlab-secret", token_header="gitlab-secret"
    )
    assert not verify_gitlab_webhook_token(
        secret="gitlab-secret",
        token_header="different",
    )


@pytest.mark.parametrize(
    "path, body_factory, headers_factory",
    [
        (
            "/api/code-review/webhooks/github",
            lambda: json.dumps(
                {"repository": {"id": 123}},
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8"),
            lambda body: {
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": _github_signature("github-secret", body),
            },
        ),
        (
            "/api/code-review/webhooks/gitlab",
            lambda: json.dumps(
                {"object_kind": "merge_request", "project": {"id": 777}},
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8"),
            lambda _body: {
                "Content-Type": "application/json",
                "X-Gitlab-Token": "gitlab-secret",
                "X-Gitlab-Instance": "https://GitLab.One",
            },
        ),
    ],
)
def test_authenticated_malformed_webhook_payload_returns_400(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    body_factory: Any,
    headers_factory: Any,
) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    session = _FakeWebhookSession()
    _seed_integration(
        session,
        integration_id=1,
        provider="github" if "github" in path else "gitlab",
        external_repo_id="123" if "github" in path else "777",
        repository_identity_key="" if "github" in path else "https://gitlab.one",
        gitlab_base_url=None if "github" in path else "https://gitlab.one",
    )
    _seed_config(session, config_id=1, repository_integration_id=1)

    body = body_factory()
    headers = headers_factory(body)

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(path, data=body, headers=headers)
            assert response.status_code == 400
            assert session.runs == []
            assert session.timeline_events == []
    finally:
        app.dependency_overrides.clear()


def test_github_webhook_rejects_invalid_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    session = _FakeWebhookSession()
    _seed_integration(
        session,
        integration_id=1,
        provider="github",
        external_repo_id="123",
        repository_identity_key="",
    )
    _seed_config(session, config_id=1, repository_integration_id=1)

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/code-review/webhooks/github",
                data=json.dumps(
                    _github_payload(), separators=(",", ":"), ensure_ascii=False
                ),
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": "sha256=deadbeef",
                },
            )
            assert response.status_code == 401
            assert session.runs == []
            assert session.timeline_events == []
    finally:
        app.dependency_overrides.clear()


def test_gitlab_webhook_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    session = _FakeWebhookSession()
    _seed_integration(
        session,
        integration_id=1,
        provider="gitlab",
        external_repo_id="777",
        repository_identity_key="https://gitlab.one",
        gitlab_base_url="https://gitlab.one",
    )
    _seed_config(session, config_id=1, repository_integration_id=1)

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/code-review/webhooks/gitlab",
                json=_gitlab_payload(),
                headers={
                    "Content-Type": "application/json",
                    "X-Gitlab-Token": "wrong-token",
                    "X-Gitlab-Instance": "https://GitLab.One",
                },
            )
            assert response.status_code == 401
            assert session.runs == []
            assert session.timeline_events == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "path, body, headers",
    [
        (
            "/api/code-review/webhooks/github",
            json.dumps(
                {"zen": "Approachable is better than simple."},
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8"),
            None,
        ),
        (
            "/api/code-review/webhooks/gitlab",
            json.dumps(
                {
                    "object_kind": "push",
                    "project": {"id": 777},
                },
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8"),
            {
                "Content-Type": "application/json",
                "X-Gitlab-Token": "gitlab-secret",
                "X-Gitlab-Instance": "https://GitLab.One",
            },
        ),
    ],
)
def test_supported_auth_but_unsupported_webhook_events_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    body: bytes,
    headers: dict[str, str] | None,
) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    session = _FakeWebhookSession()
    if "github" in path:
        headers = {
            "Content-Type": "application/json",
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _github_signature("github-secret", body),
        }

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(path, content=body, headers=headers)
            assert response.status_code == 202
            assert response.json() == {"ok": True, "queued": False}
            assert session.runs == []
            assert session.timeline_events == []
    finally:
        app.dependency_overrides.clear()


def test_github_webhook_creates_an_idempotent_review_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    session = _FakeWebhookSession()
    _seed_integration(
        session,
        integration_id=1,
        provider="github",
        external_repo_id="123",
        repository_identity_key="",
    )
    _seed_config(session, config_id=1, repository_integration_id=1)

    body = json.dumps(
        _github_payload(), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    secret = "github-secret"

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            first_response = client.post(
                "/api/code-review/webhooks/github",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": _github_signature(secret, body),
                },
            )
            assert first_response.status_code == 202
            first_payload = first_response.json()
            assert first_payload["ok"] is True
            assert first_payload["queued"] is True
            assert first_payload["repository_integration_id"] == 1
            assert first_payload["review_run_id"] == 1
            assert session.runs[0].status == ReviewRunStatus.ANALYZING
            assert (
                session.runs[0].idempotency_key
                == "github::123:pull_request:17:head-abc"
            )
            assert [event.event_type for event in session.timeline_events] == [
                "review_requested",
                "queued",
                "analysis_started",
            ]
            assert len(session.timeline_events) == 3

            second_response = client.post(
                "/api/code-review/webhooks/github",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": _github_signature(secret, body),
                },
            )
            assert second_response.status_code == 202
            second_payload = second_response.json()
            assert second_payload["ok"] is True
            assert second_payload["queued"] is False
            assert second_payload["review_run_id"] == 1
            assert len(session.runs) == 1
            assert [event.event_type for event in session.timeline_events] == [
                "review_requested",
                "queued",
                "analysis_started",
            ]
            assert len(session.timeline_events) == 3
    finally:
        app.dependency_overrides.clear()


def test_gitlab_webhook_creates_run_for_mixed_case_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    session = _FakeWebhookSession()
    _seed_integration(
        session,
        integration_id=1,
        provider="gitlab",
        external_repo_id="777",
        repository_identity_key="https://gitlab.one",
        gitlab_base_url="https://gitlab.one",
    )
    _seed_config(session, config_id=1, repository_integration_id=1)

    payload = _gitlab_payload()
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    token = "gitlab-secret"

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/code-review/webhooks/gitlab",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Gitlab-Token": token,
                    "X-Gitlab-Instance": "https://GitLab.One",
                },
            )
            assert response.status_code == 202
            payload_out = response.json()
            assert payload_out["ok"] is True
            assert payload_out["queued"] is True
            assert payload_out["repository_integration_id"] == 1
            assert payload_out["review_run_id"] == 1
            assert (
                session.runs[0].idempotency_key
                == "gitlab:https://gitlab.one:777:merge_request:7:gitlab-head"
            )
            assert [event.event_type for event in session.timeline_events] == [
                "review_requested",
                "queued",
                "analysis_started",
            ]
    finally:
        app.dependency_overrides.clear()


def test_gitlab_webhook_matches_subpath_instance_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    session = _FakeWebhookSession()
    _seed_integration(
        session,
        integration_id=1,
        provider="gitlab",
        external_repo_id="777",
        repository_identity_key="https://gitlab.one/subpath",
        gitlab_base_url="https://gitlab.one/subpath",
    )
    _seed_config(session, config_id=1, repository_integration_id=1)

    body = json.dumps(
        _gitlab_payload(project_web_url="https://GitLab.One/subpath/group/project"),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/code-review/webhooks/gitlab",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Gitlab-Token": "gitlab-secret",
                },
            )
            assert response.status_code == 202
            payload_out = response.json()
            assert payload_out["queued"] is True
            assert payload_out["repository_integration_id"] == 1
            assert session.runs[0].idempotency_key == (
                "gitlab:https://gitlab.one/subpath:777:merge_request:7:gitlab-head"
            )
            assert [event.event_type for event in session.timeline_events] == [
                "review_requested",
                "queued",
                "analysis_started",
            ]
    finally:
        app.dependency_overrides.clear()


def test_disabled_repository_config_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    session = _FakeWebhookSession()
    _seed_integration(
        session,
        integration_id=1,
        provider="github",
        external_repo_id="123",
        repository_identity_key="",
    )
    _seed_config(
        session,
        config_id=1,
        repository_integration_id=1,
        review_enabled=False,
    )

    body = json.dumps(
        _github_payload(), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    secret = "github-secret"

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/code-review/webhooks/github",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": _github_signature(secret, body),
                },
            )
            assert response.status_code == 202
            payload_out = response.json()
            assert payload_out["ok"] is True
            assert payload_out["queued"] is False
            assert session.runs == []
            assert session.timeline_events == []
    finally:
        app.dependency_overrides.clear()


def test_missing_repository_config_safely_declines_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    session = _FakeWebhookSession()
    _seed_integration(
        session,
        integration_id=1,
        provider="github",
        external_repo_id="123",
        repository_identity_key="",
    )

    body = json.dumps(
        _github_payload(), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/code-review/webhooks/github",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": _github_signature("github-secret", body),
                },
            )
            assert response.status_code == 202
            payload_out = response.json()
            assert payload_out["ok"] is True
            assert payload_out["queued"] is False
            assert session.runs == []
            assert session.timeline_events == []
    finally:
        app.dependency_overrides.clear()


def test_repository_config_for_another_integration_does_not_authorize_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    session = _FakeWebhookSession()
    _seed_integration(
        session,
        integration_id=1,
        provider="github",
        external_repo_id="123",
        repository_identity_key="",
    )
    _seed_integration(
        session,
        integration_id=2,
        provider="github",
        external_repo_id="999",
        repository_identity_key="",
    )
    _seed_config(session, config_id=1, repository_integration_id=2, review_enabled=True)

    body = json.dumps(
        _github_payload(), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/code-review/webhooks/github",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": _github_signature("github-secret", body),
                },
            )
            assert response.status_code == 202
            payload_out = response.json()
            assert payload_out["ok"] is True
            assert payload_out["queued"] is False
            assert session.runs == []
            assert session.timeline_events == []
    finally:
        app.dependency_overrides.clear()


def test_webhook_routes_are_registered_on_main_app() -> None:
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/code-review/webhooks/github" in route_paths
    assert "/api/code-review/webhooks/gitlab" in route_paths


def test_webhook_service_handles_commit_conflicts_without_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_webhook_secrets(monkeypatch, github="github-secret", gitlab="gitlab-secret")
    conflict_run = ReviewRun(
        id=1,
        repository_integration_id=1,
        provider="github",
        event_type="pull_request",
        external_event_id=None,
        external_pr_or_mr_id=None,
        head_commit_id=None,
        base_commit_id=None,
        base_branch=None,
        head_branch=None,
        status=ReviewRunStatus.QUEUED,
        idempotency_key="github::123:pull_request:17:head-abc",
        created_by_event_at=None,
        created_at=None,
        updated_at=None,
    )
    session = _FakeWebhookSession(
        fail_commit_once=True,
        conflict_run_on_rollback=conflict_run,
        conflict_timeline_events_on_rollback=[
            _seed_timeline_event(
                _FakeWebhookSession(),
                event_id=1,
                review_run=conflict_run,
                event_type="review_requested",
                dedupe_key="github::123:pull_request:17:head-abc",
            ),
            _seed_timeline_event(
                _FakeWebhookSession(),
                event_id=2,
                review_run=conflict_run,
                event_type="queued",
                dedupe_key="github::123:pull_request:17:head-abc",
            ),
        ],
    )
    _seed_integration(
        session,
        integration_id=1,
        provider="github",
        external_repo_id="123",
        repository_identity_key="",
    )
    _seed_config(session, config_id=1, repository_integration_id=1)

    body = json.dumps(
        _github_payload(), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    _override_main_app_db(session)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/code-review/webhooks/github",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": _github_signature("github-secret", body),
                },
            )
            assert response.status_code == 202
            assert response.json()["queued"] is False
            assert response.json()["review_run_id"] == 1
            assert len(session.runs) == 1
            assert [event.event_type for event in session.timeline_events] == [
                "review_requested",
                "queued",
            ]
    finally:
        app.dependency_overrides.clear()
