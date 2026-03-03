from __future__ import annotations

from typing import Any

import pytest

from app.auth import core as auth_core


@pytest.fixture(autouse=True)
def _reset_auth_state(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "auth_users_test.json"))
    auth_core.reset_auth_state_for_tests()


@pytest.mark.asyncio
async def test_register_user_writes_to_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_DB_ENABLED", "true")
    monkeypatch.setenv("AUTH_FILE_FALLBACK_ENABLED", "false")

    captured: dict[str, Any] = {}

    async def fake_insert_db_user(record: dict[str, Any]) -> None:
        captured.update(record)

    monkeypatch.setattr(auth_core, "_insert_db_user", fake_insert_db_user)

    user = await auth_core.register_user(
        username="new-user",
        password="secret123",
        role="developer",
        team_id="team-a",
    )

    assert captured["identity"] == "new_user"
    assert isinstance(captured["password_hash"], str)
    assert captured["auth_source"] == "local"
    assert user["identity"] == "new_user"
    assert user["team_id"] == "team_a"


@pytest.mark.asyncio
async def test_authenticate_user_supports_ldap_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_DB_ENABLED", "true")
    monkeypatch.setenv("AUTH_FILE_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("AUTH_LDAP_ENABLED", "true")

    async def fake_fetch_db_user(identity: str) -> dict[str, Any] | None:  # noqa: ARG001
        return None

    async def fake_authenticate_user_via_ldap(
        *, username: str, password: str
    ) -> dict[str, Any] | None:
        _ = (password,)
        return {
            "identity": auth_core.normalize_identity(username),
            "password_hash": None,
            "auth_source": "ldap",
            "role": "developer",
            "team_id": "ldap_team",
            "display_name": "LDAP User",
            "email": "ldap_user@example.com",
        }

    captured_upserts: list[dict[str, Any]] = []

    async def fake_upsert_db_user(record: dict[str, Any]) -> None:
        captured_upserts.append(record)

    monkeypatch.setattr(auth_core, "_fetch_db_user", fake_fetch_db_user)
    monkeypatch.setattr(
        auth_core,
        "_authenticate_user_via_ldap",
        fake_authenticate_user_via_ldap,
    )
    monkeypatch.setattr(auth_core, "_upsert_db_user", fake_upsert_db_user)

    user = await auth_core.authenticate_user(username="ldap-user", password="secret123")

    assert user["identity"] == "ldap_user"
    assert captured_upserts
    assert captured_upserts[0]["auth_source"] == "ldap"
