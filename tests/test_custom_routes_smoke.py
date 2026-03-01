from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aegra_api.core.auth_deps import get_current_user, require_auth
from aegra_api.core.orm import get_session
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.core import reset_auth_state_for_tests
from app.main import app
from app.routers import sandbox as sandbox_router
from app.routers import scm as scm_router


async def _override_require_auth() -> Any:
    return SimpleNamespace(
        identity="local-dev",
        display_name="Local Dev",
        is_authenticated=True,
        permissions=["developer", "developer:read", "developer:write"],
        role="developer",
        team_id="team_default",
        email="local-dev@example.com",
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "auth_users_test.json"))
    reset_auth_state_for_tests()
    scm_router.SCM_TOKENS.clear()
    app.dependency_overrides[require_auth] = _override_require_auth
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_hello_route_smoke(client: TestClient) -> None:
    response = client.get("/hello")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello from custom route!"}


def test_auth_register_and_login_smoke(client: TestClient) -> None:
    register_response = client.post(
        "/auth/register",
        json={
            "username": "new-user",
            "password": "secret123",
        },
    )

    assert register_response.status_code == 200
    register_payload = register_response.json()
    assert isinstance(register_payload["access_token"], str)
    assert register_payload["access_token"].count(".") == 2

    login_response = client.post(
        "/auth/login",
        json={
            "username": "new-user",
            "password": "secret123",
        },
    )

    assert login_response.status_code == 200
    assert login_response.json()["user"]["identity"] == "new_user"


def test_auth_register_conflict_smoke(client: TestClient) -> None:
    first = client.post(
        "/auth/register",
        json={
            "username": "repeat-user",
            "password": "secret123",
        },
    )
    second = client.post(
        "/auth/register",
        json={
            "username": "repeat-user",
            "password": "secret123",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_sandbox_runtime_route_smoke(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_thread = SimpleNamespace(
        metadata_json={"graph_id": "agent"},
        thread_id="th-1",
        status="ready",
        user_id="user-1",
        created_at=None,
        updated_at=None,
    )

    class FakeSession:
        async def scalar(self, stmt: Any) -> Any:  # noqa: ARG002
            return fake_thread

    class FakeSnapshot:
        values = {
            "container_id": "container-123",
            "service_bootstrapped": True,
            "service_restart_count": 0,
            "last_diagnostic_fingerprint": "diag-1",
            "service_status": {
                "service_running": True,
                "preview_urls": ["http://localhost:3000"],
                "preview_probes": {"http://localhost:3000": "200"},
                "error_lines": ["none"],
                "log_tail": "line1\nline2",
            },
        }
        config = {"configurable": {"checkpoint_id": "ckpt-1"}}

    class FakeAgent:
        def with_config(self, config: Any) -> FakeAgent:  # noqa: ARG002
            return self

        async def aget_state(
            self, config: Any, subgraphs: bool = False
        ) -> FakeSnapshot:  # noqa: ARG002
            return FakeSnapshot()

    class FakeGraphContext:
        async def __aenter__(self) -> FakeAgent:
            return FakeAgent()

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:  # noqa: ARG002
            return None

    class FakeLangGraphService:
        def get_graph(self, graph_id: str) -> FakeGraphContext:  # noqa: ARG002
            return FakeGraphContext()

    async def override_current_user() -> Any:
        return SimpleNamespace(identity="user-1")

    async def override_session() -> Any:
        return FakeSession()

    monkeypatch.setattr(
        sandbox_router,
        "create_thread_config",
        lambda thread_id, user, _: {"configurable": {"thread_id": thread_id}},
    )
    monkeypatch.setattr(
        sandbox_router,
        "get_langgraph_service",
        lambda: FakeLangGraphService(),
    )
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_session] = override_session

    response = client.get("/sandbox/threads/th-1/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread_id"] == "th-1"
    assert payload["graph_id"] == "agent"
    assert payload["status"] == "ok"
    assert payload["checkpoint_id"] == "ckpt-1"
    assert payload["container_id"] == "container-123"
    assert payload["runtime_excerpt"]["error_lines"] == ["none"]


def test_scm_repositories_route_smoke(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    scm_router.SCM_TOKENS.clear()
    cache_key = scm_router._scm_token_cache_key(  # noqa: SLF001
        user_id="local-dev",
        provider="github",
    )
    scm_router.SCM_TOKENS[cache_key] = {
        "provider": "github",
        "access_token": "test-token",
        "github_token_source": "user_token",
    }

    async def fake_fetch_github_user_repositories(
        *,
        http_client: Any,  # noqa: ARG001
        access_token: str,
    ) -> list[dict[str, Any]]:
        assert access_token == "test-token"
        return [
            {
                "id": 1,
                "name": "repo-a",
                "full_name": "owner/repo-a",
                "default_branch": "main",
            }
        ]

    monkeypatch.setattr(
        scm_router,
        "_fetch_github_user_repositories",
        fake_fetch_github_user_repositories,
    )

    response = client.get(
        "/integrations/scm/repositories",
        params={"provider": "github"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "repositories": [
            {
                "id": 1,
                "name": "repo-a",
                "full_name": "owner/repo-a",
                "default_branch": "main",
            }
        ]
    }


def test_sandbox_debug_route_smoke(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    fake_thread = SimpleNamespace(
        metadata_json={"graph_id": "agent"},
        thread_id="th-1",
        status="ready",
        user_id="user-1",
        created_at=now,
        updated_at=now,
    )
    fake_runs = [
        SimpleNamespace(
            run_id="run-1",
            assistant_id="asst-1",
            status="error",
            error_message="failed",
            created_at=now,
            updated_at=now,
        )
    ]

    class FakeScalarRows:
        def __init__(self, rows: list[Any]) -> None:
            self._rows = rows

        def all(self) -> list[Any]:
            return self._rows

    class FakeSession:
        async def scalar(self, stmt: Any) -> Any:  # noqa: ARG002
            return fake_thread

        async def scalars(self, stmt: Any) -> FakeScalarRows:  # noqa: ARG002
            return FakeScalarRows(fake_runs)

    async def override_current_user() -> Any:
        return SimpleNamespace(identity="user-1")

    async def override_session() -> Any:
        return FakeSession()

    async def fake_get_sandbox_runtime(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["thread_id"] == "th-1"
        return {
            "thread_id": "th-1",
            "status": "ok",
            "last_diagnostic_fingerprint": "diag-1",
            "service_status": {"service_running": True},
        }

    async def fake_fetch_recent_run_events(
        session: Any,  # noqa: ARG001
        *,
        run_id: str,
        events_limit: int,  # noqa: ARG001
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": "evt-1",
                "seq": 1,
                "event": "run.error",
                "created_at": now.isoformat(),
                "error_excerpt": f"{run_id}: failed",
            }
        ]

    monkeypatch.setattr(sandbox_router, "get_sandbox_runtime", fake_get_sandbox_runtime)
    monkeypatch.setattr(
        sandbox_router,
        "_fetch_recent_run_events",
        fake_fetch_recent_run_events,
    )
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_session] = override_session

    response = client.get("/sandbox/threads/th-1/debug")

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread"]["thread_id"] == "th-1"
    assert payload["runtime"]["status"] == "ok"
    assert payload["runs"][0]["run_id"] == "run-1"
    assert payload["runs"][0]["events"][0]["event"] == "run.error"
    assert payload["summary"]["run_count"] == 1
    assert payload["summary"]["error_run_count"] == 1
    assert payload["summary"]["has_runtime_diagnostic"] is True


def test_scm_branches_route_smoke(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    scm_router.SCM_TOKENS.clear()
    cache_key = scm_router._scm_token_cache_key(  # noqa: SLF001
        user_id="local-dev",
        provider="github",
    )
    scm_router.SCM_TOKENS[cache_key] = {
        "provider": "github",
        "access_token": "test-token",
        "github_token_source": "user_token",
    }

    class FakeResponse:
        status_code = 200
        text = ""
        content = b"ok"

        def json(self) -> list[dict[str, str]]:
            return [{"name": "main"}, {"name": "dev"}]

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
            return None

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:  # noqa: ARG002
            return None

        async def get(
            self,
            url: str,
            *,
            params: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeResponse:
            assert url == "https://api.github.com/repos/owner/repo-a/branches"
            assert params == {"per_page": 100}
            assert headers["Authorization"] == "Bearer test-token"
            return FakeResponse()

    monkeypatch.setattr(scm_router.httpx, "AsyncClient", FakeAsyncClient)

    response = client.get(
        "/integrations/scm/branches",
        params={"provider": "github", "repository": "owner/repo-a"},
    )

    assert response.status_code == 200
    assert response.json() == {"branches": [{"name": "main"}, {"name": "dev"}]}


def test_scm_token_persistence_smoke(client: TestClient) -> None:
    storage: dict[str, str] = {}

    class FakeResult:
        def __init__(
            self,
            *,
            rowcount: int = 0,
            row: dict[str, Any] | None = None,
        ) -> None:
            self.rowcount = rowcount
            self._row = row

        def mappings(self) -> FakeResult:
            return self

        def first(self) -> dict[str, Any] | None:
            return self._row

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(
            self,
            exc_type: Any,
            exc: Any,
            tb: Any,  # noqa: ARG002
        ) -> None:
            return None

        async def execute(self, stmt: Any, params: dict[str, Any]) -> FakeResult:
            sql = str(stmt).strip().lower()
            cache_key = str(params.get("cache_key", ""))
            if sql.startswith("update"):
                if cache_key not in storage:
                    return FakeResult(rowcount=0)
                storage[cache_key] = str(params["token_encrypted"])
                return FakeResult(rowcount=1)
            if sql.startswith("insert"):
                storage[cache_key] = str(params["token_encrypted"])
                return FakeResult(rowcount=1)
            if sql.startswith("select"):
                token_encrypted = storage.get(cache_key)
                if token_encrypted is None:
                    return FakeResult(row=None)
                return FakeResult(row={"token_encrypted": token_encrypted})
            if sql.startswith("delete"):
                storage.pop(cache_key, None)
                return FakeResult(rowcount=1)
            return FakeResult(rowcount=0)

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    class FakeSessionMaker:
        def __call__(self) -> FakeSession:
            return FakeSession()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            scm_router,
            "_get_session_maker",
            lambda: FakeSessionMaker(),
        )

        scm_router.SCM_TOKENS.clear()
        cache_key = scm_router._scm_token_cache_key(  # noqa: SLF001
            user_id="local-dev",
            provider="github",
        )
        asyncio.run(
            scm_router._set_scm_token_payload(  # noqa: SLF001
                cache_key,
                {
                    "provider": "github",
                    "access_token": "persisted-token",
                    "github_token_source": "user_token",
                },
            )
        )
        scm_router.SCM_TOKENS.clear()

        payload = asyncio.run(
            scm_router._resolve_scm_token_payload(  # noqa: SLF001
                user_id="local-dev",
                provider="github",
                gitlab_base_url=None,
                github_auth_mode=None,
            )
        )

        assert payload["access_token"] == "persisted-token"


def test_scm_repositories_revoked_token_clears_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    scm_router.SCM_TOKENS.clear()
    cache_key = scm_router._scm_token_cache_key(  # noqa: SLF001
        user_id="local-dev",
        provider="github",
    )
    scm_router.SCM_TOKENS[cache_key] = {
        "provider": "github",
        "access_token": "revoked-token",
        "github_token_source": "user_token",
    }

    async def fake_fetch_github_user_repositories(
        *,
        http_client: Any,  # noqa: ARG001
        access_token: str,  # noqa: ARG001
    ) -> list[dict[str, Any]]:
        raise HTTPException(401, "GitHub 仓库查询失败: Bad credentials")

    monkeypatch.setattr(
        scm_router,
        "_fetch_github_user_repositories",
        fake_fetch_github_user_repositories,
    )

    async def fake_delete_scm_token_payload(cache_key: str) -> None:
        scm_router.SCM_TOKENS.pop(cache_key, None)

    monkeypatch.setattr(
        scm_router,
        "_delete_scm_token_payload",
        fake_delete_scm_token_payload,
    )

    response = client.get(
        "/integrations/scm/repositories",
        params={"provider": "github"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "SCM 授权已失效或已被撤销，请重新授权"
    assert cache_key not in scm_router.SCM_TOKENS


def test_scm_connections_route_lists_multiple_sources(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    github_payload = scm_router._encrypt_scm_token_payload(  # noqa: SLF001
        {
            "provider": "github",
            "access_token": "gh-token",
            "refresh_token": "gh-refresh",
            "expires_at": time.time() + 3600,
        }
    )
    gitlab_payload = scm_router._encrypt_scm_token_payload(  # noqa: SLF001
        {
            "provider": "gitlab",
            "access_token": "gl-token",
            "gitlab_base_url": "https://gitlab.com",
            "expires_at": time.time() + 1800,
        }
    )

    async def fake_list_rows(user_id: str) -> list[dict[str, Any]]:
        assert user_id == "local-dev"
        return [
            {
                "cache_key": "local-dev:github:github_app",
                "provider": "github",
                "github_auth_mode": "github_app",
                "gitlab_base_url": None,
                "token_encrypted": github_payload,
                "updated_at": time.time(),
            },
            {
                "cache_key": "local-dev:gitlab:https://gitlab.com",
                "provider": "gitlab",
                "github_auth_mode": None,
                "gitlab_base_url": "https://gitlab.com",
                "token_encrypted": gitlab_payload,
                "updated_at": time.time(),
            },
        ]

    monkeypatch.setattr(scm_router, "_list_scm_token_rows_for_user", fake_list_rows)

    response = client.get("/integrations/scm/connections")

    assert response.status_code == 200
    payload = response.json()
    keys = {item["connection_key"] for item in payload["connections"]}
    assert "github" in keys
    assert "gitlab" in keys


def test_scm_connections_route_tolerates_legacy_github_auth_mode(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    github_payload = scm_router._encrypt_scm_token_payload(  # noqa: SLF001
        {
            "provider": "github",
            "access_token": "legacy-gh-token",
            "expires_at": time.time() + 3600,
        }
    )

    async def fake_list_rows(user_id: str) -> list[dict[str, Any]]:
        assert user_id == "local-dev"
        return [
            {
                "cache_key": "local-dev:github:oauth",
                "provider": "github",
                "github_auth_mode": "oauth",
                "gitlab_base_url": None,
                "token_encrypted": github_payload,
                "updated_at": time.time(),
            }
        ]

    monkeypatch.setattr(scm_router, "_list_scm_token_rows_for_user", fake_list_rows)

    response = client.get("/integrations/scm/connections")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["connections"]) == 1
    assert payload["connections"][0]["provider"] == "github"
    assert payload["connections"][0]["github_auth_mode"] == "github_app"


def test_scm_revoke_connection_route_smoke(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted_cache_keys: list[str] = []

    async def fake_delete(cache_key: str) -> None:
        deleted_cache_keys.append(cache_key)

    monkeypatch.setattr(scm_router, "_delete_scm_token_payload", fake_delete)

    response = client.delete(
        "/integrations/scm/connections",
        params={
            "provider": "gitlab",
            "gitlab_base_url": "https://gitlab.company.com",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["connection_key"] == "gitlab_enterprise:https://gitlab.company.com"
    assert deleted_cache_keys == ["local-dev:gitlab:https://gitlab.company.com"]


def test_scm_validate_connection_revoked_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    scm_router.SCM_TOKENS.clear()
    cache_key = scm_router._scm_token_cache_key(  # noqa: SLF001
        user_id="local-dev",
        provider="github",
    )
    scm_router.SCM_TOKENS[cache_key] = {
        "provider": "github",
        "access_token": "expired-token",
        "github_token_source": "github_app",
    }

    class FakeResponse:
        status_code = 401
        text = "Bad credentials"

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
            return None

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:  # noqa: ARG002
            return None

        async def get(self, url: str, *, headers: dict[str, str]) -> FakeResponse:
            assert url == "https://api.github.com/user"
            assert headers["Authorization"] == "Bearer expired-token"
            return FakeResponse()

    monkeypatch.setattr(scm_router.httpx, "AsyncClient", FakeAsyncClient)

    async def fake_delete(cache_key: str) -> None:
        scm_router.SCM_TOKENS.pop(cache_key, None)

    monkeypatch.setattr(scm_router, "_delete_scm_token_payload", fake_delete)

    response = client.get(
        "/integrations/scm/connections/validate",
        params={"provider": "github"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert payload["revoked"] is True
    assert cache_key not in scm_router.SCM_TOKENS


def test_scm_access_token_refresh_when_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    scm_router.SCM_TOKENS.clear()
    cache_key = scm_router._scm_token_cache_key(  # noqa: SLF001
        user_id="local-dev",
        provider="github",
    )
    scm_router.SCM_TOKENS[cache_key] = {
        "provider": "github",
        "access_token": "old-token",
        "refresh_token": "refresh-token",
        "expires_at": time.time() - 5,
        "github_auth_mode": "github_app",
    }

    async def fake_refresh(
        *,
        refresh_token: str,
        github_auth_mode: str | None = None,
    ) -> dict[str, Any]:
        assert refresh_token == "refresh-token"
        assert github_auth_mode == "github_app"
        return {
            "access_token": "new-token",
            "refresh_token": "refresh-token-next",
            "expires_in": 3600,
            "github_auth_mode": "github_app",
            "github_token_source": "github_app",
        }

    async def fake_set(cache_key: str, payload: dict[str, Any]) -> None:
        scm_router.SCM_TOKENS[cache_key] = payload

    monkeypatch.setattr(scm_router, "_refresh_github_oauth_token", fake_refresh)
    monkeypatch.setattr(scm_router, "_set_scm_token_payload", fake_set)

    token = asyncio.run(
        scm_router._resolve_scm_access_token(  # noqa: SLF001
            user_id="local-dev",
            provider="github",
            gitlab_base_url=None,
            github_auth_mode="github_app",
        )
    )

    assert token == "new-token"
    assert scm_router.SCM_TOKENS[cache_key]["access_token"] == "new-token"
    assert scm_router.SCM_TOKENS[cache_key]["refresh_token"] == "refresh-token-next"


def test_scm_oauth_callback_rejects_mismatched_redirect_uri(client: TestClient) -> None:
    state = scm_router._encode_scm_oauth_state_token(  # noqa: SLF001
        {
            "provider": "github",
            "user_id": "local-dev",
            "created_at": time.time(),
            "redirect_uri": "http://localhost:5173/oauth/scm/callback",
            "origin": "http://localhost:5173",
            "github_auth_mode": "github_app",
            "nonce": "nonce-1",
        }
    )

    response = client.post(
        "/integrations/scm/oauth/callback",
        json={
            "params": {"state": state, "code": "code-1"},
            "redirect_uri": "http://localhost:5173/another/callback",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "error": "OAuth redirect_uri 与授权请求不匹配",
    }
