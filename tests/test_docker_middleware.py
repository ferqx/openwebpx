from __future__ import annotations

from typing import Any

from docker.errors import NotFound

from middleware.docker import DockerMiddleware


class FakeContainer:
    def __init__(self, container_id: str, *, status: str = "running") -> None:
        self.id = container_id
        self.status = status
        self.started = False
        self.unpaused = False

    def reload(self) -> None:
        return None

    def start(self) -> None:
        self.started = True
        self.status = "running"

    def unpause(self) -> None:
        self.unpaused = True
        self.status = "running"


class FakeContainerManager:
    def __init__(
        self,
        *,
        existing: dict[str, FakeContainer] | None = None,
        run_result: FakeContainer | None = None,
        missing_ids: set[str] | None = None,
    ) -> None:
        self.existing = existing or {}
        self.run_result = run_result or FakeContainer("new-container")
        self.missing_ids = missing_ids or set()
        self.run_calls = 0

    def get(self, container_id: str) -> FakeContainer:
        if container_id in self.missing_ids:
            raise NotFound("container not found")
        return self.existing[container_id]

    def run(self, *args: Any, **kwargs: Any) -> FakeContainer:  # noqa: ARG002
        self.run_calls += 1
        return self.run_result


class FakeDockerClient:
    def __init__(self, manager: FakeContainerManager) -> None:
        self.containers = manager


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str, dict[str, Any]]] = []

    def put(self, namespace: tuple[str, ...], key: str, value: dict[str, Any]) -> None:
        self.calls.append((namespace, key, value))


class FakeRuntime:
    def __init__(self, *, thread_id: str | None = None, store: Any = None) -> None:
        configurable = {"thread_id": thread_id} if thread_id is not None else {}
        self.config = {"configurable": configurable}
        self.store = store


def test_ensure_container_auto_starts_stopped_container() -> None:
    stopped = FakeContainer("cid-1", status="exited")
    manager = FakeContainerManager(existing={"cid-1": stopped})
    middleware = DockerMiddleware()
    middleware._client = FakeDockerClient(manager)

    resolved = middleware._ensure_container({"container_id": "cid-1"})

    assert resolved == "cid-1"
    assert stopped.started is True
    assert stopped.status == "running"
    assert manager.run_calls == 0


def test_before_agent_jumps_to_end_when_thread_container_destroyed() -> None:
    manager = FakeContainerManager(missing_ids={"cid-missing"})
    middleware = DockerMiddleware()
    middleware._client = FakeDockerClient(manager)

    result = middleware.before_agent({"container_id": "cid-missing"}, runtime=None)

    assert result is not None
    assert result.get("jump_to") == "end"
    assert "容器已销毁" in result["messages"][0].content
    assert manager.run_calls == 0


def test_ensure_container_creates_new_container_for_new_thread() -> None:
    new_container = FakeContainer("cid-new", status="running")
    manager = FakeContainerManager(run_result=new_container)
    middleware = DockerMiddleware()
    middleware._client = FakeDockerClient(manager)

    resolved = middleware._ensure_container({})

    assert resolved == "cid-new"
    assert manager.run_calls == 1


def test_before_agent_persists_thread_container_mapping_to_store() -> None:
    manager = FakeContainerManager(existing={"cid-1": FakeContainer("cid-1")})
    middleware = DockerMiddleware()
    middleware._client = FakeDockerClient(manager)
    store = FakeStore()
    runtime = FakeRuntime(thread_id="thread-1", store=store)

    update = middleware.before_agent({"container_id": "cid-1"}, runtime=runtime)

    assert update is not None
    assert update.get("container_id") == "cid-1"
    assert store.calls == [
        (
            ("docker_backend", "thread_container"),
            "thread-1",
            {"container_id": "cid-1"},
        )
    ]


def test_install_dependencies_auto_provisions_pnpm_via_corepack() -> None:
    middleware = DockerMiddleware()
    state = {"pnpm_ready": False}

    def fake_exec(
        _container: Any,
        command: str,
        *,
        workdir: str | None = None,  # noqa: ARG001
        environment: dict[str, str] | None = None,  # noqa: ARG001
        user: str | None = None,  # noqa: ARG001
    ) -> tuple[int, str]:
        if command.startswith("command -v pnpm"):
            return (0, "") if state["pnpm_ready"] else (1, "")
        if command == "[ -d node_modules ]":
            return 1, ""
        return 0, ""

    def fake_exec_stream(
        _container: Any,
        command: str,
        *,
        workdir: str | None = None,  # noqa: ARG001
        environment: dict[str, str] | None = None,  # noqa: ARG001
        user: str | None = None,  # noqa: ARG001
        on_output_line: Any = None,  # noqa: ANN401, ARG001
    ) -> tuple[int, str]:
        if "corepack prepare" in command:
            state["pnpm_ready"] = True
            return 0, "prepared"
        if command == "pnpm install":
            return 0, "installed"
        return 1, "unexpected command"

    middleware._exec = fake_exec  # type: ignore[method-assign]
    middleware._exec_stream = fake_exec_stream  # type: ignore[method-assign]

    ok, err = middleware._install_dependencies(
        object(),
        "pnpm",
        package_json={"packageManager": "pnpm@9.0.0"},
    )

    assert ok is True
    assert err is None


def test_install_dependencies_reports_error_when_corepack_provision_fails() -> None:
    middleware = DockerMiddleware()

    def fake_exec(
        _container: Any,
        command: str,
        *,
        workdir: str | None = None,  # noqa: ARG001
        environment: dict[str, str] | None = None,  # noqa: ARG001
        user: str | None = None,  # noqa: ARG001
    ) -> tuple[int, str]:
        if command.startswith("command -v pnpm"):
            return 1, ""
        return 0, ""

    def fake_exec_stream(
        _container: Any,
        command: str,
        *,
        workdir: str | None = None,  # noqa: ARG001
        environment: dict[str, str] | None = None,  # noqa: ARG001
        user: str | None = None,  # noqa: ARG001
        on_output_line: Any = None,  # noqa: ANN401, ARG001
    ) -> tuple[int, str]:
        if "corepack prepare" in command:
            return 127, "corepack: command not found"
        return 1, "unexpected command"

    middleware._exec = fake_exec  # type: ignore[method-assign]
    middleware._exec_stream = fake_exec_stream  # type: ignore[method-assign]

    ok, err = middleware._install_dependencies(
        object(),
        "pnpm",
        package_json={"packageManager": "pnpm@9.0.0"},
    )

    assert ok is False
    assert isinstance(err, str)
    assert "auto-provision via corepack failed" in err


def test_resolve_runtime_package_manager_falls_back_to_npm() -> None:
    middleware = DockerMiddleware()

    def fake_ensure(
        _container: Any,
        _manager: str,
        *,
        package_json: dict[str, Any] | None = None,  # noqa: ARG001
        reporter: Any = None,  # noqa: ANN401, ARG001
    ) -> tuple[bool, str | None]:
        return False, "pnpm unavailable"

    def fake_exec(
        _container: Any,
        command: str,
        *,
        workdir: str | None = None,  # noqa: ARG001
        environment: dict[str, str] | None = None,  # noqa: ARG001
        user: str | None = None,  # noqa: ARG001
    ) -> tuple[int, str]:
        if command == "command -v npm >/dev/null 2>&1":
            return 0, ""
        return 1, ""

    middleware._ensure_package_manager_available = fake_ensure  # type: ignore[method-assign]
    middleware._exec = fake_exec  # type: ignore[method-assign]

    manager, err = middleware._resolve_runtime_package_manager(
        object(),
        detected_manager="pnpm",
    )

    assert manager == "npm"
    assert err is None


def test_resolve_runtime_package_manager_returns_error_without_fallback() -> None:
    middleware = DockerMiddleware()

    def fake_ensure(
        _container: Any,
        _manager: str,
        *,
        package_json: dict[str, Any] | None = None,  # noqa: ARG001
        reporter: Any = None,  # noqa: ANN401, ARG001
    ) -> tuple[bool, str | None]:
        return False, "pm unavailable"

    def fake_exec(
        _container: Any,
        command: str,
        *,
        workdir: str | None = None,  # noqa: ARG001
        environment: dict[str, str] | None = None,  # noqa: ARG001
        user: str | None = None,  # noqa: ARG001
    ) -> tuple[int, str]:
        if command == "command -v npm >/dev/null 2>&1":
            return 1, ""
        return 1, ""

    middleware._ensure_package_manager_available = fake_ensure  # type: ignore[method-assign]
    middleware._exec = fake_exec  # type: ignore[method-assign]

    manager, err = middleware._resolve_runtime_package_manager(
        object(),
        detected_manager="pnpm",
    )

    assert manager is None
    assert err == "pm unavailable"


def test_resolve_runtime_package_manager_does_not_fallback_when_workspace_protocol_present() -> (
    None
):
    middleware = DockerMiddleware()

    def fake_ensure(
        _container: Any,
        _manager: str,
        *,
        package_json: dict[str, Any] | None = None,  # noqa: ARG001
        reporter: Any = None,  # noqa: ANN401, ARG001
    ) -> tuple[bool, str | None]:
        return False, "pnpm unavailable"

    middleware._ensure_package_manager_available = fake_ensure  # type: ignore[method-assign]

    manager, err = middleware._resolve_runtime_package_manager(
        object(),
        detected_manager="pnpm",
        package_json={"dependencies": {"ui": "workspace:*"}},
    )

    assert manager is None
    assert isinstance(err, str)
    assert "refusing fallback to npm" in err


def test_detect_package_manager_prefers_package_manager_field() -> None:
    middleware = DockerMiddleware()

    def fake_exec(
        _container: Any,
        command: str,
        *,
        workdir: str | None = None,  # noqa: ARG001
        environment: dict[str, str] | None = None,  # noqa: ARG001
        user: str | None = None,  # noqa: ARG001
    ) -> tuple[int, str]:
        if command == "command -v pnpm >/dev/null 2>&1":
            return 0, ""
        return 1, ""

    middleware._exec = fake_exec  # type: ignore[method-assign]

    detected = middleware._detect_package_manager(
        object(),
        package_json={"packageManager": "pnpm@9.1.0"},
    )

    assert detected == "pnpm"
