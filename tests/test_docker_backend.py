from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import suppress
from types import SimpleNamespace
from typing import Any

import docker
import pytest
from docker.errors import NotFound
from docker.models.containers import Container

from backends.docker import DockerBackend, _docker_unavailable_message


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


class FakeRuntimeWithoutState:
    def __init__(self, *, config: dict[str, Any], store: Any = None) -> None:
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


@pytest.fixture
def real_integration_container(
    request: pytest.FixtureRequest,
) -> tuple[docker.DockerClient, Container]:
    client = docker.from_env()
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Docker daemon unavailable: {exc}")

    container = client.containers.run(
        "sandbox-agent:latest",
        command=["tail", "-f", "/dev/null"],
        detach=True,
        working_dir="/workspace",
        environment={
            "SHELL": "/bin/bash",
            "BASH_ENV": "/etc/profile.d/openwebpx-scm.sh",
        },
        labels={
            "openwebpx.test": "docker-backend-integration",
            "openwebpx.cleanup": "true",
        },
        name=f"openwebpx-test-{uuid.uuid4().hex[:8]}",
    )

    def _cleanup() -> None:
        with suppress(Exception):
            container.remove(force=True)

    request.addfinalizer(_cleanup)
    return client, container


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


def test_build_execution_environment_tolerates_runtime_without_state_attribute() -> (
    None
):
    runtime = FakeRuntimeWithoutState(config={})
    backend = DockerBackend(runtime)  # type: ignore[arg-type]

    env, token = backend._build_execution_environment()

    assert token is None
    assert env["PATH"]
    assert "GH_TOKEN" not in env


def test_docker_unavailable_message_mentions_socket_mount_when_socket_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("backends.docker.Path.exists", lambda _self: False)

    message = _docker_unavailable_message(docker.errors.DockerException("boom"))

    assert "/var/run/docker.sock" in message
    assert "DOCKER_HOST=unix:///var/run/docker.sock" in message


def test_docker_unavailable_message_mentions_group_add_on_permission_denied() -> None:
    message = _docker_unavailable_message(
        docker.errors.DockerException("PermissionError(13, 'Permission denied')")
    )

    assert "group_add" in message
    assert "DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)" in message


def test_build_execution_environment_injects_gitlab_host_and_tokens() -> None:
    runtime = FakeRuntime(
        state={
            "repo_auth_context": {
                "user_id": "u-1",
                "provider": "gitlab",
                "repo": "group/repo",
                "gitlab_base_url": "https://gitlab.com",
            },
            "repo_git_identity": {
                "name": "Bob",
                "email": "bob@example.com",
            },
        },
        config={},
    )
    backend = DockerBackend(runtime)
    backend._resolve_repo_access_token_from_context = lambda _ctx: "token-gl"  # type: ignore[method-assign]

    env, token = backend._build_execution_environment()

    assert token == "token-gl"
    assert env["GLAB_HOST"] == "gitlab.com"
    assert env["GITLAB_HOST"] == "gitlab.com"
    assert env["GLAB_TOKEN"] == "token-gl"
    assert env["GITLAB_TOKEN"] == "token-gl"


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


def test_execute_blocks_glab_when_token_not_injected() -> None:
    runtime = FakeRuntime(state={}, config={})
    backend = DockerBackend(runtime)
    backend._build_execution_environment = lambda: ({"PATH": "/bin"}, None)  # type: ignore[method-assign]

    response = backend.execute("glab mr create --title t --description d")

    assert response.exit_code == 1
    assert "`glab mr create` is disabled in sandbox" in response.output
    assert "Authorization: Bearer $GITLAB_TOKEN" in response.output
    assert "numeric-id" in response.output


def test_execute_blocks_glab_mr_create_even_when_token_is_injected() -> None:
    runtime = FakeRuntime(state={}, config={})
    backend = DockerBackend(runtime)
    backend._build_execution_environment = lambda: (  # type: ignore[method-assign]
        {"PATH": "/bin", "GITLAB_TOKEN": "token-gl"},
        "token-gl",
    )

    response = backend.execute("glab mr create --title t --description d")

    assert response.exit_code == 1
    assert "`glab mr create` is disabled in sandbox" in response.output
    assert "Authorization: Bearer $GITLAB_TOKEN" in response.output
    assert "numeric-id" in response.output


def test_execute_blocks_gh_when_token_not_injected() -> None:
    runtime = FakeRuntime(state={}, config={})
    backend = DockerBackend(runtime)
    backend._build_execution_environment = lambda: ({"PATH": "/bin"}, None)  # type: ignore[method-assign]

    response = backend.execute("gh pr create --title t --body d")

    assert response.exit_code == 1
    assert "SCM authorization unavailable for GitHub CLI command" in response.output
    assert "do not run `gh auth login` in sandbox" in response.output


@pytest.mark.skipif(
    os.getenv("OPENWEBPX_RUN_DOCKER_INTEGRATION") != "1",
    reason="Set OPENWEBPX_RUN_DOCKER_INTEGRATION=1 to run real Docker integration checks.",
)
def test_execute_sees_refreshed_repo_runtime_env_in_real_container(
    real_integration_container: tuple[docker.DockerClient, Container],
) -> None:
    from middleware.docker import DockerMiddleware

    client, container = real_integration_container
    middleware = DockerMiddleware()
    middleware._client = client
    middleware._bootstrap_global_scm_env_in_container(container)
    init_result = container.exec_run(
        cmd=[
            "bash",
            "-lc",
            "mkdir -p /workspace && git init /workspace >/dev/null 2>&1",
        ],
        workdir="/workspace",
        environment={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        },
    )
    assert init_result.exit_code == 0

    binding = {
        "user_id": "u-1",
        "provider": "github",
        "repo": "owner/repo",
        "branch": "main",
        "git_name": "Alice",
        "git_email": "alice@example.com",
        "gitlab_base_url": "",
        "github_auth_mode": "github_app",
    }

    async def fake_aload_thread_repo_binding(_runtime: Any) -> dict[str, str]:
        return binding

    async def fake_resolve_token(**_kwargs: Any) -> str:
        return "token-abc"

    middleware._aload_thread_repo_binding = fake_aload_thread_repo_binding  # type: ignore[method-assign]
    middleware._resolve_thread_repo_access_token = fake_resolve_token  # type: ignore[method-assign]

    repo_update = asyncio.run(
        middleware._maybe_sync_thread_repository(
            state={
                "repo_sync_signature": (
                    f"{container.id}|github|owner/repo|main||github_app"
                ),
                "repo_sync_success": True,
            },
            runtime=object(),
            container_id=container.id,
        )
    )

    assert repo_update is not None

    runtime = FakeRuntime(
        state={
            "container_id": container.id,
            "repo_auth_context": repo_update["repo_auth_context"],
            "repo_git_identity": repo_update["repo_git_identity"],
        },
        config={},
    )
    backend = DockerBackend(runtime)
    backend._client = client
    backend._resolve_repo_access_token_from_context = lambda _ctx: "token-abc"  # type: ignore[method-assign]

    response = backend.execute(
        'printf "%s|%s|" "$(git config user.name)" "$(git config user.email)"; '
        'if [ -n "$GH_TOKEN" ] && [ "$GH_TOKEN" = "$GITHUB_TOKEN" ]; then '
        "echo token-present; "
        "else "
        "echo token-missing; "
        "fi"
    )

    assert response.exit_code == 0
    assert "Alice|alice@example.com|token-present" in response.output
