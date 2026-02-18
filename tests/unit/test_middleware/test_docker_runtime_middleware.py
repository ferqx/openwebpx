from __future__ import annotations

from typing import Any

from middleware.docker import DockerMiddleware


class _FakeContainers:
    def __init__(self, container: Any) -> None:
        self._container = container

    def get(self, _container_id: str) -> Any:
        return self._container


class _FakeClient:
    def __init__(self, container: Any) -> None:
        self.containers = _FakeContainers(container)


class _FakeContainer:
    id = "container-1"


def test_before_model_injects_diagnostic_once() -> None:
    middleware = DockerMiddleware(image="node:20-bookworm")
    middleware._client = _FakeClient(_FakeContainer())  # type: ignore[assignment]
    middleware._ensure_container = lambda state: "container-1"  # type: ignore[method-assign]
    middleware._build_runtime_status = lambda state, container: {  # type: ignore[method-assign]
        "app_detected": True,
        "startup_attempted": False,
    }
    middleware._build_diagnostic_message = lambda status: "runtime error"  # type: ignore[method-assign]

    state: dict[str, Any] = {}
    first = middleware.before_model(state, runtime=None)
    assert first is not None
    assert "messages" in first
    assert first["last_diagnostic_fingerprint"]

    state.update(first)
    second = middleware.before_model(state, runtime=None)
    assert second is not None
    assert "messages" not in second


def test_before_model_clears_fingerprint_when_healthy() -> None:
    middleware = DockerMiddleware(image="node:20-bookworm")
    middleware._client = _FakeClient(_FakeContainer())  # type: ignore[assignment]
    middleware._ensure_container = lambda state: "container-1"  # type: ignore[method-assign]
    middleware._build_runtime_status = lambda state, container: {  # type: ignore[method-assign]
        "app_detected": True,
        "startup_attempted": False,
    }
    middleware._build_diagnostic_message = lambda status: None  # type: ignore[method-assign]

    state: dict[str, Any] = {"last_diagnostic_fingerprint": "abcd"}
    update = middleware.before_model(state, runtime=None)

    assert update is not None
    assert update["last_diagnostic_fingerprint"] is None
    assert "messages" not in update


def test_resolve_start_script_priority() -> None:
    middleware = DockerMiddleware(image="node:20-bookworm")

    assert (
        middleware._resolve_start_script(
            {"scripts": {"preview": "vite preview", "start": "node server.js"}}
        )
        == "start"
    )
    assert middleware._resolve_start_script({"scripts": {"dev": "vite"}}) == "dev"
    assert middleware._resolve_start_script({"scripts": {}}) is None


def test_build_preview_urls_from_bindings() -> None:
    middleware = DockerMiddleware(image="node:20-bookworm", healthcheck_path="/health")

    urls = middleware._build_preview_urls(
        {
            "5173/tcp": [49123],
            "3000/tcp": [49124, 49125],
        }
    )

    assert "http://127.0.0.1:49123/health" in urls
    assert "http://127.0.0.1:49124/health" in urls
    assert "http://127.0.0.1:49125/health" in urls


def test_detect_framework_and_start_command() -> None:
    middleware = DockerMiddleware(image="node:20-bookworm")

    vite_framework = middleware._detect_framework(
        {"dependencies": {"react": "^18", "vite": "^5"}}
    )
    next_framework = middleware._detect_framework(
        {"dependencies": {"next": "15.0.0", "react": "^18"}}
    )
    unknown_framework = middleware._detect_framework({"dependencies": {"react": "^18"}})

    assert vite_framework == "vite"
    assert next_framework == "next"
    assert unknown_framework == "unknown"

    next_cmd = middleware._build_start_command(
        package_manager="npm",
        start_script="dev",
        framework="next",
        port=5173,
    )
    vite_cmd = middleware._build_start_command(
        package_manager="pnpm",
        start_script="dev",
        framework="vite",
        port=3000,
    )

    assert "--hostname 0.0.0.0" in next_cmd
    assert "--host 0.0.0.0" in vite_cmd
