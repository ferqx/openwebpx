from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from aegra_api.core.auth_deps import get_current_user
from aegra_api.core.orm import get_session
from fastapi.testclient import TestClient

from app.main import app
from app.routers import sandbox as sandbox_router
from app.routers import scm as scm_router


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_hello_route_smoke(client: TestClient) -> None:
    response = client.get("/hello")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello from custom route!"}


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
