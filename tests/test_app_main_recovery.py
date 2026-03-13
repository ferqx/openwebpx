from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app import main as app_main


def test_recover_thread_metadata_after_restart_marks_bootstrap_error() -> None:
    metadata = {
        "graph_id": "build_app_agent_v3",
        "sandbox_bootstrap": {
            "status": "running",
            "run_status": "running",
            "event_seq": 3,
            "steps": [
                {"key": "container", "title": "容器创建", "status": "success"},
                {"key": "bootstrap", "title": "下载依赖并启动", "status": "running"},
            ],
            "logs": [],
            "events": [],
        },
    }

    recovered, changed = app_main._recover_thread_metadata_after_restart(
        metadata,
        now_iso="2026-03-13T01:02:03Z",
    )

    assert changed is True
    bootstrap = recovered["sandbox_bootstrap"]
    assert bootstrap["status"] == "error"
    assert bootstrap["run_status"] == "interrupted"
    assert bootstrap["finished_at"] == "2026-03-13T01:02:03Z"
    assert bootstrap["steps"][1]["status"] == "error"
    assert bootstrap["steps"][1]["detail"] == "服务重启中断"
    assert bootstrap["event_seq"] == 4
    assert (
        bootstrap["logs"][-1]["message"]
        == "后台初始化任务因服务重启中断，状态已自动回收。"
    )
    assert bootstrap["events"][-1]["seq"] == 4


@pytest.mark.asyncio
async def test_recover_interrupted_runtime_state_recovers_pending_runs_and_busy_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 3, 13, tzinfo=UTC)
    run = SimpleNamespace(
        run_id="run-1",
        status="running",
        updated_at=None,
        error_message=None,
    )
    thread = SimpleNamespace(
        thread_id="thread-1",
        status="busy",
        updated_at=None,
        metadata_json={
            "sandbox_bootstrap": {
                "status": "running",
                "event_seq": 0,
                "logs": [],
                "events": [],
                "steps": [
                    {"key": "bootstrap", "title": "下载依赖并启动", "status": "running"}
                ],
            }
        },
    )

    class FakeRows:
        def __init__(self, rows: list[Any]) -> None:
            self._rows = rows

        def all(self) -> list[Any]:
            return self._rows

    class FakeSession:
        def __init__(self) -> None:
            self.scalars_calls = 0
            self.committed = False

        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        async def scalars(self, stmt: Any) -> FakeRows:  # noqa: ARG002
            self.scalars_calls += 1
            if self.scalars_calls == 1:
                return FakeRows([run])
            if self.scalars_calls == 2:
                return FakeRows([thread])
            raise AssertionError("unexpected scalars call")

        async def commit(self) -> None:
            self.committed = True

    fake_session = FakeSession()

    def fake_session_maker() -> FakeSession:
        return fake_session

    monkeypatch.setattr(
        app_main.aegra_orm, "_get_session_maker", lambda: fake_session_maker
    )
    monkeypatch.setattr(
        app_main,
        "datetime",
        SimpleNamespace(
            now=lambda tz=None: now,
        ),
    )

    await app_main._recover_interrupted_runtime_state()

    assert fake_session.committed is True
    assert run.status == "interrupted"
    assert "service restarted" in run.error_message
    assert thread.status == "idle"
    assert thread.metadata_json["sandbox_bootstrap"]["status"] == "error"
