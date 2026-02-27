from __future__ import annotations

from typing import Any

import pytest

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
