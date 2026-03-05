from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from docker.errors import NotFound

from backends.docker import DockerBackend


class FakeContainer:
    def __init__(self, container_id: str) -> None:
        self.id = container_id


class FakeContainerManager:
    def __init__(self) -> None:
        self._containers: dict[str, FakeContainer] = {}

    def add(self, container: FakeContainer) -> None:
        self._containers[container.id] = container

    def get(self, container_id: str) -> FakeContainer:
        return self._containers[container_id]


class FakeClient:
    def __init__(self, manager: FakeContainerManager) -> None:
        self.containers = manager


class FakeDownloadContainer:
    def get_archive(self, _path: str) -> tuple[bytes, dict[str, Any]]:
        raise NotFound("file not found in container")


class FakeExecContainer:
    def __init__(self, output: str = "ok", exit_code: int = 0) -> None:
        self._output = output
        self._exit_code = exit_code
        self.last_environment: dict[str, str] | None = None
        self.last_cmd: list[str] | None = None

    def exec_run(
        self, cmd: list[str], workdir: str, environment: dict[str, str]
    ) -> Any:
        self.last_cmd = cmd
        self.last_environment = environment
        return SimpleNamespace(
            output=self._output.encode("utf-8"),
            exit_code=self._exit_code,
        )


class FakeRuntime:
    def __init__(
        self,
        *,
        state: dict[str, Any],
        config: dict[str, Any],
        store: Any = None,
    ) -> None:
        self.state = state
        self.config = config
        self.store = store


class FakeStoreItem:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value


class FakeStore:
    def __init__(self) -> None:
        self._data: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}

    def put(self, namespace: tuple[str, ...], key: str, value: dict[str, Any]) -> None:
        self._data[(namespace, key)] = value

    def get(self, namespace: tuple[str, ...], key: str) -> FakeStoreItem | None:
        value = self._data.get((namespace, key))
        if value is None:
            return None
        return FakeStoreItem(value)


def test_container_uses_state_container_id_and_writes_store_mapping() -> None:
    store = FakeStore()
    manager = FakeContainerManager()
    container = FakeContainer("cid-1")
    manager.add(container)
    runtime = FakeRuntime(
        state={"container_id": "cid-1"},
        config={"configurable": {"thread_id": "thread-1"}},
        store=store,
    )
    backend = DockerBackend(runtime)
    backend._client = FakeClient(manager)

    resolved = backend.container

    assert resolved.id == "cid-1"
    stored = store.get(("docker_backend", "thread_container"), "thread-1")
    assert stored is not None
    assert stored.value["container_id"] == "cid-1"


def test_container_falls_back_to_store_when_state_missing_container_id() -> None:
    store = FakeStore()
    store.put(
        ("docker_backend", "thread_container"), "thread-1", {"container_id": "cid-1"}
    )
    manager = FakeContainerManager()
    manager.add(FakeContainer("cid-1"))
    runtime = FakeRuntime(
        state={},
        config={"configurable": {"thread_id": "thread-1"}},
        store=store,
    )
    backend = DockerBackend(runtime)
    backend._client = FakeClient(manager)

    resolved = backend.container

    assert resolved.id == "cid-1"


def test_container_raises_when_state_and_store_both_missing() -> None:
    manager = FakeContainerManager()
    runtime = FakeRuntime(
        state={},
        config={"configurable": {"thread_id": "thread-unknown"}},
    )
    backend = DockerBackend(runtime)
    backend._client = FakeClient(manager)

    with pytest.raises(RuntimeError, match="未找到 Docker 容器 ID"):
        _ = backend.container


def test_download_files_maps_docker_not_found_to_file_not_found() -> None:
    runtime = FakeRuntime(state={}, config={})
    backend = DockerBackend(runtime)
    backend._container = FakeDownloadContainer()  # type: ignore[assignment]

    responses = backend.download_files(
        ["/workspace/packages/components/examples/table-optimization.md"]
    )

    assert len(responses) == 1
    assert responses[0].path.endswith("table-optimization.md")
    assert responses[0].content is None
    assert responses[0].error == "file_not_found"


def test_build_execution_environment_injects_git_identity_and_token() -> None:
    runtime = FakeRuntime(
        state={
            "repo_auth_context": {
                "user_id": "u-1",
                "provider": "github",
                "repo": "owner/repo",
            },
            "repo_git_identity": {
                "name": "Alice",
                "email": "alice@example.com",
            },
        },
        config={},
    )
    backend = DockerBackend(runtime)
    backend._resolve_repo_access_token_from_context = lambda _ctx: "token-abc"  # type: ignore[method-assign]

    env, token = backend._build_execution_environment()

    assert token == "token-abc"
    assert env["GIT_AUTHOR_NAME"] == "Alice"
    assert env["GIT_AUTHOR_EMAIL"] == "alice@example.com"
    assert env["GH_TOKEN"] == "token-abc"
    assert env["GITHUB_TOKEN"] == "token-abc"


def test_execute_uses_injected_environment_and_sanitizes_token_output() -> None:
    runtime = FakeRuntime(state={}, config={})
    backend = DockerBackend(runtime)
    fake_container = FakeExecContainer(output="push failed with token-abc")
    backend._container = fake_container  # type: ignore[assignment]
    backend._build_execution_environment = lambda: (  # type: ignore[method-assign]
        {"PATH": "/bin", "GH_TOKEN": "token-abc"},
        "token-abc",
    )

    response = backend.execute("git push origin feature/test")

    assert response.exit_code == 0
    assert "token-abc" not in response.output
    assert "***" in response.output
    assert fake_container.last_environment is not None
    assert fake_container.last_environment["GH_TOKEN"] == "token-abc"
