from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.auth import authenticated_user
from app.core.database import get_db
from app.main import app, create_app
from app.models.code_review import (
    RepositoryIntegration,
    RepositoryMembership,
    RepositoryReviewConfig,
)
from app.routers.code_review_repositories import (
    list_repositories as list_repositories_route,
)
from app.services.code_review.repository_service import CodeReviewRepositoryService


class _FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any | None:
        return self._items[0] if self._items else None

    def one_or_none(self) -> Any | None:
        return self.first()


def _make_test_app():
    return create_app(include_lifespan=False)


class _FakeSession:
    def __init__(self, *, fail_commit_once: bool = False) -> None:
        self.integrations: list[RepositoryIntegration] = []
        self.memberships: list[RepositoryMembership] = []
        self.configs: list[RepositoryReviewConfig] = []
        self._pending: list[Any] = []
        self._pending_deletes: list[Any] = []
        self._fail_commit_once = fail_commit_once
        self._commit_calls = 0
        self._next_ids = {
            RepositoryIntegration: 1,
            RepositoryMembership: 1,
            RepositoryReviewConfig: 1,
        }

    async def scalars(self, stmt: Any) -> _FakeScalarResult:  # noqa: ARG002
        entity = stmt.column_descriptions[0]["entity"]
        if entity is RepositoryIntegration:
            return _FakeScalarResult(self.integrations)
        if entity is RepositoryMembership:
            return _FakeScalarResult(self.memberships)
        if entity is RepositoryReviewConfig:
            return _FakeScalarResult(self.configs)
        return _FakeScalarResult([])

    def add(self, obj: Any) -> None:
        self._pending.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self._pending.extend(objs)

    async def delete(self, obj: Any) -> None:
        self._pending_deletes.append(obj)

    async def commit(self) -> None:
        self._commit_calls += 1
        if self._fail_commit_once and self._commit_calls == 1:
            self._materialize_pending()
            self._apply_deletes()
            self._pending.clear()
            self._pending_deletes.clear()
            raise IntegrityError("insert", {}, Exception("unique violation"))
        self._materialize_pending()
        self._apply_deletes()
        self._pending.clear()
        self._pending_deletes.clear()

    def _materialize_pending(self) -> None:
        for obj in self._pending:
            cls = type(obj)
            if getattr(obj, "id", None) is None:
                obj.id = self._next_ids[cls]
                self._next_ids[cls] += 1
            if (
                isinstance(obj, RepositoryMembership)
                and obj.repository_integration_id is None
                and obj.repository_integration is not None
                and obj.repository_integration.id is not None
            ):
                obj.repository_integration_id = obj.repository_integration.id
            if (
                isinstance(obj, RepositoryReviewConfig)
                and obj.repository_integration_id is None
                and obj.repository_integration is not None
                and obj.repository_integration.id is not None
            ):
                obj.repository_integration_id = obj.repository_integration.id

            collection = self._collection_for(obj)
            if obj not in collection:
                collection.append(obj)

    def _apply_deletes(self) -> None:
        for obj in self._pending_deletes:
            collection = self._collection_for(obj)
            if obj in collection:
                collection.remove(obj)

    async def refresh(self, obj: Any) -> None:
        return None

    async def rollback(self) -> None:
        self._pending.clear()
        self._pending_deletes.clear()

    def _collection_for(self, obj: Any) -> list[Any]:
        if isinstance(obj, RepositoryIntegration):
            return self.integrations
        if isinstance(obj, RepositoryMembership):
            return self.memberships
        if isinstance(obj, RepositoryReviewConfig):
            return self.configs
        raise AssertionError(f"unexpected object {type(obj)!r}")


class _FakeTokenStore:
    def __init__(self) -> None:
        self._payloads: dict[
            tuple[str, str, str | None, str | None], dict[str, Any]
        ] = {}

    def set_payload(
        self,
        *,
        user_id: str,
        provider: str,
        access_token: str,
        gitlab_base_url: str | None = None,
        github_auth_mode: str | None = None,
    ) -> None:
        if provider == "github" and github_auth_mode is None:
            github_auth_mode = "github_app"
        self._payloads[(user_id, provider, gitlab_base_url, github_auth_mode)] = {
            "provider": provider,
            "access_token": access_token,
            "gitlab_base_url": gitlab_base_url,
            "github_auth_mode": github_auth_mode,
            "github_token_source": "user_token",
        }

    async def resolve_token_payload(
        self,
        *,
        user_id: str,
        provider: str,
        gitlab_base_url: str | None,
        github_auth_mode: str | None = None,
    ) -> dict[str, Any]:
        return self._payloads[(user_id, provider, gitlab_base_url, github_auth_mode)]


class _FakeScmRepositoryService:
    def __init__(self) -> None:
        self.github_by_token: dict[str, list[dict[str, Any]]] = {}
        self.gitlab_by_token_and_base: dict[
            tuple[str, str | None], list[dict[str, Any]]
        ] = {}

    async def list_github_repositories(
        self,
        *,
        access_token: str,
        token_payload: dict[str, Any],  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        return list(self.github_by_token.get(access_token, []))

    async def list_gitlab_repositories(
        self,
        *,
        access_token: str,
        gitlab_base_url: str | None,
    ) -> list[dict[str, Any]]:
        return list(
            self.gitlab_by_token_and_base.get((access_token, gitlab_base_url), [])
        )


def _user(identity: str) -> SimpleNamespace:
    return SimpleNamespace(identity=identity)


def _seed_integration(
    session: _FakeSession,
    *,
    integration_id: int,
    provider: str,
    external_repo_id: str,
    gitlab_base_url: str | None = None,
) -> RepositoryIntegration:
    integration = RepositoryIntegration(
        id=integration_id,
        provider=provider,
        external_repo_id=external_repo_id,
        repository_identity_key=gitlab_base_url if provider == "gitlab" else "",
        full_name=f"{provider}/{external_repo_id}",
        default_branch="main",
        gitlab_base_url=gitlab_base_url,
        webhook_status=None,
        webhook_management_mode=None,
        created_at=None,
        updated_at=None,
    )
    session.integrations.append(integration)
    return integration


def _seed_membership(
    session: _FakeSession,
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


def _seed_config(
    session: _FakeSession,
    *,
    config_id: int,
    repository_integration_id: int,
) -> RepositoryReviewConfig:
    config = RepositoryReviewConfig(
        id=config_id,
        repository_integration_id=repository_integration_id,
        review_enabled=True,
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


@pytest.mark.asyncio
async def test_empty_sync_returns_no_rows_and_does_not_leak_existing_integrations() -> (
    None
):
    session = _FakeSession()
    token_store = _FakeTokenStore()
    scm_repository_service = _FakeScmRepositoryService()
    service = CodeReviewRepositoryService(
        token_store=token_store,
        scm_repository_service=scm_repository_service,
    )

    token_store.set_payload(
        user_id="user-empty", provider="github", access_token="token-empty"
    )
    _seed_integration(
        session,
        integration_id=99,
        provider="github",
        external_repo_id="leaked",
    )
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=99,
        user_id="user-empty",
    )

    result = await service.sync_repositories(
        session=session,
        current_user=_user("user-empty"),
        provider="github",
    )

    assert result == []
    assert [item.external_repo_id for item in session.integrations] == ["leaked"]
    assert session.memberships == []


@pytest.mark.asyncio
async def test_sync_reuses_integrations_and_keeps_memberships_per_user() -> None:
    session = _FakeSession()
    token_store = _FakeTokenStore()
    scm_repository_service = _FakeScmRepositoryService()
    service = CodeReviewRepositoryService(
        token_store=token_store,
        scm_repository_service=scm_repository_service,
    )

    token_store.set_payload(user_id="user-a", provider="github", access_token="token-a")
    token_store.set_payload(user_id="user-b", provider="github", access_token="token-b")
    scm_repository_service.github_by_token["token-a"] = [
        {
            "id": 101,
            "name": "shared",
            "full_name": "acme/shared",
            "default_branch": "main",
        }
    ]
    scm_repository_service.github_by_token["token-b"] = [
        {
            "id": 101,
            "name": "shared",
            "full_name": "acme/shared",
            "default_branch": "main",
        },
        {
            "id": 202,
            "name": "private",
            "full_name": "acme/private",
            "default_branch": "develop",
        },
    ]

    first_sync = await service.sync_repositories(
        session=session,
        current_user=_user("user-a"),
        provider="github",
    )
    second_sync = await service.sync_repositories(
        session=session,
        current_user=_user("user-b"),
        provider="github",
    )

    assert first_sync == [
        {
            "id": 1,
            "provider": "github",
            "external_repo_id": "101",
            "repository_identity_key": "",
            "full_name": "acme/shared",
            "default_branch": "main",
            "gitlab_base_url": None,
            "review_enabled": False,
        }
    ]
    assert second_sync == [
        {
            "id": 1,
            "provider": "github",
            "external_repo_id": "101",
            "repository_identity_key": "",
            "full_name": "acme/shared",
            "default_branch": "main",
            "gitlab_base_url": None,
            "review_enabled": False,
        },
        {
            "id": 2,
            "provider": "github",
            "external_repo_id": "202",
            "repository_identity_key": "",
            "full_name": "acme/private",
            "default_branch": "develop",
            "gitlab_base_url": None,
            "review_enabled": False,
        },
    ]

    assert len(session.integrations) == 2
    shared_integration = next(
        item for item in session.integrations if item.external_repo_id == "101"
    )
    private_integration = next(
        item for item in session.integrations if item.external_repo_id == "202"
    )
    assert shared_integration.repository_identity_key == ""
    assert private_integration.repository_identity_key == ""
    assert shared_integration.full_name == "acme/shared"
    assert shared_integration.default_branch == "main"
    assert private_integration.full_name == "acme/private"

    assert len(session.memberships) == 3
    shared_memberships = [
        item
        for item in session.memberships
        if item.repository_integration_id == shared_integration.id
    ]
    assert {item.user_id for item in shared_memberships} == {"user-a", "user-b"}

    assert len(session.configs) == 2
    for config in session.configs:
        assert config.review_enabled is False
        assert config.auto_fix_enabled is False
        assert config.auto_fix_requires_approval is True
        assert config.auto_publish_enabled is False

    visible_user_a = await service.list_repositories(
        session=session, current_user=_user("user-a")
    )
    visible_user_b = await service.list_repositories(
        session=session, current_user=_user("user-b")
    )

    assert [item["external_repo_id"] for item in visible_user_a] == ["101", "202"]
    assert [item["external_repo_id"] for item in visible_user_b] == ["101", "202"]
    assert visible_user_a[0]["full_name"] == "acme/shared"
    assert visible_user_a[0]["default_branch"] == "main"
    assert visible_user_a[0]["review_enabled"] is False
    assert visible_user_b[1]["full_name"] == "acme/private"


@pytest.mark.asyncio
async def test_gitlab_instance_identity_keeps_same_project_ids_distinct() -> None:
    session = _FakeSession()
    token_store = _FakeTokenStore()
    scm_repository_service = _FakeScmRepositoryService()
    service = CodeReviewRepositoryService(
        token_store=token_store,
        scm_repository_service=scm_repository_service,
    )

    token_store.set_payload(
        user_id="user-gitlab",
        provider="gitlab",
        access_token="gitlab-token-1",
        gitlab_base_url="https://gitlab.one",
    )
    token_store.set_payload(
        user_id="user-gitlab",
        provider="gitlab",
        access_token="gitlab-token-2",
        gitlab_base_url="https://gitlab.two",
    )
    scm_repository_service.gitlab_by_token_and_base[
        (
            "gitlab-token-1",
            "https://gitlab.one",
        )
    ] = [
        {
            "id": 777,
            "name": "project",
            "path_with_namespace": "group/project",
            "default_branch": "main",
        }
    ]
    scm_repository_service.gitlab_by_token_and_base[
        (
            "gitlab-token-2",
            "https://gitlab.two",
        )
    ] = [
        {
            "id": 777,
            "name": "project",
            "path_with_namespace": "group/project",
            "default_branch": "main",
        }
    ]

    await service.sync_repositories(
        session=session,
        current_user=_user("user-gitlab"),
        provider="gitlab",
        gitlab_base_url="https://gitlab.one",
    )
    await service.sync_repositories(
        session=session,
        current_user=_user("user-gitlab"),
        provider="gitlab",
        gitlab_base_url="https://gitlab.two",
    )

    assert len(session.integrations) == 2
    assert {item.gitlab_base_url for item in session.integrations} == {
        "https://gitlab.one",
        "https://gitlab.two",
    }
    assert {item.repository_identity_key for item in session.integrations} == {
        "https://gitlab.one",
        "https://gitlab.two",
    }


@pytest.mark.asyncio
async def test_sync_removes_stale_memberships_even_if_integrations_remain_listed() -> (
    None
):
    session = _FakeSession()
    token_store = _FakeTokenStore()
    scm_repository_service = _FakeScmRepositoryService()
    service = CodeReviewRepositoryService(
        token_store=token_store,
        scm_repository_service=scm_repository_service,
    )

    token_store.set_payload(
        user_id="user-stale", provider="github", access_token="token-stale"
    )
    scm_repository_service.github_by_token["token-stale"] = [
        {
            "id": 501,
            "name": "keep",
            "full_name": "acme/keep",
            "default_branch": "main",
        },
        {
            "id": 502,
            "name": "drop",
            "full_name": "acme/drop",
            "default_branch": "main",
        },
    ]
    await service.sync_repositories(
        session=session,
        current_user=_user("user-stale"),
        provider="github",
    )

    scm_repository_service.github_by_token["token-stale"] = [
        {
            "id": 501,
            "name": "keep",
            "full_name": "acme/keep",
            "default_branch": "main",
        }
    ]
    await service.sync_repositories(
        session=session,
        current_user=_user("user-stale"),
        provider="github",
    )

    visible = await service.list_repositories(
        session=session,
        current_user=_user("user-stale"),
    )
    assert [item["external_repo_id"] for item in visible] == ["501", "502"]
    assert [item.user_id for item in session.memberships] == ["user-stale"]
    assert [item.repository_integration_id for item in session.memberships] == [1]


@pytest.mark.asyncio
async def test_sync_handles_uniqueness_conflict_by_reloading_existing_rows() -> None:
    session = _FakeSession(fail_commit_once=True)
    token_store = _FakeTokenStore()
    scm_repository_service = _FakeScmRepositoryService()
    service = CodeReviewRepositoryService(
        token_store=token_store,
        scm_repository_service=scm_repository_service,
    )

    token_store.set_payload(
        user_id="user-race", provider="github", access_token="token-race"
    )
    scm_repository_service.github_by_token["token-race"] = [
        {
            "id": 404,
            "name": "race",
            "full_name": "acme/race",
            "default_branch": "main",
        }
    ]

    result = await service.sync_repositories(
        session=session,
        current_user=_user("user-race"),
        provider="github",
    )

    assert result == [
        {
            "id": 1,
            "provider": "github",
            "external_repo_id": "404",
            "repository_identity_key": "",
            "full_name": "acme/race",
            "default_branch": "main",
            "gitlab_base_url": None,
            "review_enabled": False,
        }
    ]
    assert len(session.integrations) == 1
    assert len(session.memberships) == 1
    assert len(session.configs) == 1
    assert session._commit_calls >= 2


@pytest.mark.asyncio
async def test_gitlab_sync_preserves_gitlab_base_url() -> None:
    session = _FakeSession()
    token_store = _FakeTokenStore()
    scm_repository_service = _FakeScmRepositoryService()
    service = CodeReviewRepositoryService(
        token_store=token_store,
        scm_repository_service=scm_repository_service,
    )

    token_store.set_payload(
        user_id="user-gitlab",
        provider="gitlab",
        access_token="gitlab-token",
        gitlab_base_url="https://gitlab.example.com",
    )
    scm_repository_service.gitlab_by_token_and_base[
        (
            "gitlab-token",
            "https://gitlab.example.com",
        )
    ] = [
        {
            "id": 303,
            "name": "project",
            "path_with_namespace": "group/project",
            "default_branch": "main",
        }
    ]

    await service.sync_repositories(
        session=session,
        current_user=_user("user-gitlab"),
        provider="gitlab",
        gitlab_base_url="https://gitlab.example.com",
    )

    assert len(session.integrations) == 1
    integration = session.integrations[0]
    assert integration.provider == "gitlab"
    assert integration.external_repo_id == "303"
    assert integration.gitlab_base_url == "https://gitlab.example.com"


@pytest.mark.asyncio
async def test_gitlab_identity_canonicalizes_mixed_case_base_urls() -> None:
    session = _FakeSession()
    token_store = _FakeTokenStore()
    scm_repository_service = _FakeScmRepositoryService()
    service = CodeReviewRepositoryService(
        token_store=token_store,
        scm_repository_service=scm_repository_service,
    )

    token_store.set_payload(
        user_id="user-gitlab-case",
        provider="gitlab",
        access_token="gitlab-token-upper",
        gitlab_base_url="https://GitLab.One",
    )
    token_store.set_payload(
        user_id="user-gitlab-case",
        provider="gitlab",
        access_token="gitlab-token-lower",
        gitlab_base_url="https://gitlab.one",
    )
    scm_repository_service.gitlab_by_token_and_base[
        (
            "gitlab-token-upper",
            "https://GitLab.One",
        )
    ] = [
        {
            "id": 909,
            "name": "project",
            "path_with_namespace": "group/project",
            "default_branch": "main",
        }
    ]
    scm_repository_service.gitlab_by_token_and_base[
        (
            "gitlab-token-lower",
            "https://gitlab.one",
        )
    ] = [
        {
            "id": 909,
            "name": "project",
            "path_with_namespace": "group/project",
            "default_branch": "main",
        }
    ]

    await service.sync_repositories(
        session=session,
        current_user=_user("user-gitlab-case"),
        provider="gitlab",
        gitlab_base_url="https://GitLab.One",
    )
    await service.sync_repositories(
        session=session,
        current_user=_user("user-gitlab-case"),
        provider="gitlab",
        gitlab_base_url="https://gitlab.one",
    )

    assert len(session.integrations) == 1
    integration = session.integrations[0]
    assert integration.external_repo_id == "909"
    assert integration.repository_identity_key == "https://gitlab.one"


def test_code_review_config_routes_work_through_the_app() -> None:
    session = _FakeSession()
    integration = _seed_integration(
        session,
        integration_id=1,
        provider="github",
        external_repo_id="101",
    )
    _seed_membership(
        session,
        membership_id=1,
        repository_integration_id=integration.id or 1,
        user_id="route-user",
    )

    async def override_user() -> SimpleNamespace:
        return _user("route-user")

    async def override_db() -> Any:
        yield session

    test_app = _make_test_app()
    test_app.dependency_overrides[authenticated_user] = override_user
    test_app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(test_app) as client:
            get_response = client.get("/api/code-review/repositories/1/config")
            assert get_response.status_code == 200
            get_payload = get_response.json()
            assert get_payload["review_enabled"] is False
            assert get_payload["auto_fix_enabled"] is False
            assert get_payload["repository_integration_id"] == 1

            put_response = client.put(
                "/api/code-review/repositories/1/config",
                json={"review_enabled": False, "auto_publish_enabled": True},
            )
            assert put_response.status_code == 200
            put_payload = put_response.json()
            assert put_payload["review_enabled"] is False
            assert put_payload["auto_publish_enabled"] is True
    finally:
        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_code_review_repository_list_route_returns_all_integrations() -> None:
    session = _FakeSession()
    _seed_integration(
        session,
        integration_id=1,
        provider="github",
        external_repo_id="101",
    )
    _seed_integration(
        session,
        integration_id=2,
        provider="gitlab",
        external_repo_id="202",
        gitlab_base_url="https://gitlab.example.com",
    )

    payload = await list_repositories_route(
        current_user=_user("route-user"),
        db=session,
    )

    assert [repository["id"] for repository in payload["repositories"]] == [1, 2]


@pytest.mark.asyncio
async def test_list_repositories_returns_all_integrations_without_membership_filter() -> (
    None
):
    session = _FakeSession()
    service = CodeReviewRepositoryService()
    first = _seed_integration(
        session,
        integration_id=1,
        provider="github",
        external_repo_id="101",
    )
    second = _seed_integration(
        session,
        integration_id=2,
        provider="gitlab",
        external_repo_id="202",
        gitlab_base_url="https://gitlab.example.com",
    )

    repositories = await service.list_repositories(
        session=session,
        current_user=_user("list-user"),
    )

    assert [repository["id"] for repository in repositories] == [
        first.id,
        second.id,
    ]


def test_code_review_routes_are_registered_on_main_app() -> None:
    route_paths = {getattr(route, "path", None) for route in app.routes}

    assert "/api/code-review/repositories/sync" in route_paths
    assert "/api/code-review/repositories" in route_paths
    assert "/api/code-review/repositories/{id}/config" in route_paths
