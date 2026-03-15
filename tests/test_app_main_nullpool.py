from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.pool import NullPool

from app import main as app_main


class FakeEngine:
    def __init__(self, pool: object) -> None:
        self.sync_engine = SimpleNamespace(pool=pool)
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@pytest.mark.asyncio
async def test_rebind_sqlalchemy_engine_to_nullpool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_engine = FakeEngine(pool=object())
    replacement_engine = FakeEngine(pool=NullPool(None))  # type: ignore[arg-type]

    monkeypatch.setattr(app_main.db_manager, "engine", original_engine)
    monkeypatch.setattr(app_main.aegra_orm, "async_session_maker", object())
    monkeypatch.setattr(
        app_main,
        "create_async_engine",
        lambda *args, **kwargs: replacement_engine,
    )

    await app_main._rebind_sqlalchemy_engine_to_nullpool()

    assert app_main.db_manager.engine is replacement_engine
    assert app_main.aegra_orm.async_session_maker is None
    assert original_engine.disposed is True


@pytest.mark.asyncio
async def test_rebind_sqlalchemy_engine_to_nullpool_skips_when_already_nullpool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_engine = FakeEngine(pool=NullPool(None))  # type: ignore[arg-type]

    monkeypatch.setattr(app_main.db_manager, "engine", current_engine)
    monkeypatch.setattr(app_main.aegra_orm, "async_session_maker", object())

    await app_main._rebind_sqlalchemy_engine_to_nullpool()

    assert app_main.db_manager.engine is current_engine
    assert app_main.aegra_orm.async_session_maker is None
    assert current_engine.disposed is False
