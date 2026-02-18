"""E2E tests for sandbox runtime/debug custom routes.

These tests hit a running Aegra server (settings.app.SERVER_URL).
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest

from src.agent_server.settings import settings
from tests.e2e._utils import elog


def get_server_url() -> str:
    return settings.app.SERVER_URL


def _ensure_server_available() -> None:
    """服务不可达时直接 skip，避免在 CI/本地未启动服务时误报失败。"""
    try:
        httpx.get(f"{get_server_url()}/health", timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Server is not reachable at {get_server_url()}: {exc}")


def _get_auth_headers_from_env() -> dict[str, str] | None:
    """从环境变量读取 E2E token，未提供时返回 None。"""
    token = os.getenv("E2E_AUTH_TOKEN")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.e2e
def test_openapi_includes_sandbox_runtime_and_debug_routes() -> None:
    _ensure_server_available()
    response = httpx.get(f"{get_server_url()}/openapi.json", timeout=10.0)

    # 某些部署场景下 OpenAPI 可能被网关临时返回 5xx，这里 skip 避免误报。
    if response.status_code >= 500:
        pytest.skip(
            f"/openapi.json is temporarily unavailable (status={response.status_code})"
        )
    assert response.status_code == 200
    paths = response.json().get("paths", {})
    assert "/custom/sandbox/threads/{thread_id}/runtime" in paths
    assert "/custom/sandbox/threads/{thread_id}/debug" in paths

    elog(
        "Sandbox routes in OpenAPI",
        {
            "runtime_route": "/custom/sandbox/threads/{thread_id}/runtime" in paths,
            "debug_route": "/custom/sandbox/threads/{thread_id}/debug" in paths,
        },
    )


@pytest.mark.e2e
def test_sandbox_routes_exist_without_auth_not_404() -> None:
    _ensure_server_available()
    thread_id = "e2e-probe-thread"

    runtime_resp = httpx.get(
        f"{get_server_url()}/custom/sandbox/threads/{thread_id}/runtime", timeout=10.0
    )
    debug_resp = httpx.get(
        f"{get_server_url()}/custom/sandbox/threads/{thread_id}/debug", timeout=10.0
    )

    # 关键验证：即使未认证，也应该是鉴权失败而不是路由不存在。
    assert runtime_resp.status_code != 404
    assert debug_resp.status_code != 404

    elog(
        "Sandbox routes existence check",
        {
            "runtime_status": runtime_resp.status_code,
            "debug_status": debug_resp.status_code,
        },
    )


@pytest.mark.e2e
def test_sandbox_runtime_and_debug_bundle_with_auth_token() -> None:
    _ensure_server_available()
    headers = _get_auth_headers_from_env()
    if headers is None:
        pytest.skip("Set E2E_AUTH_TOKEN to run authenticated sandbox debug e2e.")

    thread_id = f"e2e-sandbox-debug-{uuid4()}"

    # 先创建线程，确保后续 runtime/debug 接口有合法 thread 可查询。
    create_resp = httpx.post(
        f"{get_server_url()}/threads",
        headers=headers,
        json={"thread_id": thread_id, "metadata": {"purpose": "sandbox-debug-e2e"}},
        timeout=15.0,
    )
    assert create_resp.status_code == 200, create_resp.text

    runtime_resp = httpx.get(
        f"{get_server_url()}/custom/sandbox/threads/{thread_id}/runtime",
        headers=headers,
        params={
            "log_lines": 40,
            "errors_only": False,
            "include_container_details": False,
        },
        timeout=20.0,
    )
    assert runtime_resp.status_code == 200, runtime_resp.text
    runtime_data = runtime_resp.json()
    assert runtime_data["thread_id"] == thread_id
    assert "service_status" in runtime_data
    assert "runtime_excerpt" in runtime_data

    debug_resp = httpx.get(
        f"{get_server_url()}/custom/sandbox/threads/{thread_id}/debug",
        headers=headers,
        params={
            "runs_limit": 3,
            "events_limit": 8,
            "log_lines": 40,
            "errors_only": True,
            "include_container_details": False,
        },
        timeout=20.0,
    )
    assert debug_resp.status_code == 200, debug_resp.text
    debug_data = debug_resp.json()

    assert "thread" in debug_data
    assert "runtime" in debug_data
    assert "runs" in debug_data
    assert "summary" in debug_data
    assert debug_data["thread"]["thread_id"] == thread_id
    assert isinstance(debug_data["runs"], list)
    assert isinstance(debug_data["summary"].get("run_count"), int)

    elog(
        "Sandbox runtime/debug bundle",
        {
            "thread_id": thread_id,
            "runtime_status": runtime_data.get("status"),
            "run_count": debug_data["summary"].get("run_count"),
            "error_run_count": debug_data["summary"].get("error_run_count"),
            "has_runtime_diagnostic": debug_data["summary"].get(
                "has_runtime_diagnostic"
            ),
        },
    )
