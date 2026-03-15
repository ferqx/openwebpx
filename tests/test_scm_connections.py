"""Tests for SCM connections endpoint."""

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_scm_connections_deduplication():
    """Test that list_scm_connections deduplicates by connection_key, keeping the most recent."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import scm

    # Create a test app with SCM router
    app = FastAPI()
    app.include_router(scm.router)

    # Mock the database query to return duplicate GitHub connections with different cache_keys
    mock_rows = [
        {
            "cache_key": "user123:github:oauth",  # Older legacy record
            "provider": "github",
            "gitlab_base_url": None,
            "github_auth_mode": "oauth",  # Legacy value
            "token_encrypted": '{"token": "old_token"}',
            "updated_at": 1000.0,
        },
        {
            "cache_key": "user123:github:github_app",  # Newer record
            "provider": "github",
            "gitlab_base_url": None,
            "github_auth_mode": "github_app",
            "token_encrypted": '{"token": "new_token"}',
            "updated_at": 2000.0,  # More recent
        },
    ]

    async def mock_list_rows(user_id: str):
        return mock_rows

    # Mock the delete function to track which keys were deleted
    deleted_keys = []

    async def mock_delete(cache_key: str):
        deleted_keys.append(cache_key)

    with (
        patch.object(scm, "_list_scm_token_rows_for_user", side_effect=mock_list_rows),
        patch.object(scm, "_delete_scm_token_payload", side_effect=mock_delete),
        patch.object(scm, "_resolve_request_user_identity", return_value="user123"),
        patch.object(scm, "_decrypt_scm_token_payload", return_value={"token": "test"}),
    ):
        client = TestClient(app)
        response = client.get("/integrations/scm/connections")

        # Verify response status
        assert response.status_code == 200

        data = response.json()
        connections = data.get("connections", [])

        # Should have only 1 GitHub connection (deduplicated)
        github_connections = [c for c in connections if c["provider"] == "github"]
        assert len(github_connections) == 1, (
            f"Expected 1 GitHub connection, got {len(github_connections)}"
        )

        # The remaining connection should be the newer one
        github_conn = github_connections[0]
        assert github_conn["connection_key"] == "github", (
            "Connection key should be 'github'"
        )
        assert github_conn["github_auth_mode"] == "github_app", (
            "Should have the newer github_app auth mode"
        )
        assert github_conn["updated_at"] == 2000.0, "Should have the newer timestamp"

        # The old cache_key should be marked for deletion
        assert "user123:github:oauth" in deleted_keys, (
            f"Older cache_key should be deleted, deleted_keys={deleted_keys}"
        )


@pytest.mark.asyncio
async def test_scm_connections_multiple_providers():
    """Test that deduplication only affects connections with the same connection_key."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import scm

    app = FastAPI()
    app.include_router(scm.router)

    mock_rows = [
        {
            "cache_key": "user123:github:github_app",
            "provider": "github",
            "gitlab_base_url": None,
            "github_auth_mode": "github_app",
            "token_encrypted": '{"token": "gh_token"}',
            "updated_at": 2000.0,
        },
        {
            "cache_key": "user123:gitlab:https://gitlab.com",
            "provider": "gitlab",
            "gitlab_base_url": "https://gitlab.com",
            "github_auth_mode": None,
            "token_encrypted": '{"token": "gl_token"}',
            "updated_at": 1500.0,
        },
    ]

    async def mock_list_rows(user_id: str):
        return mock_rows

    async def mock_delete(cache_key: str):
        pass

    with (
        patch.object(scm, "_list_scm_token_rows_for_user", side_effect=mock_list_rows),
        patch.object(scm, "_delete_scm_token_payload", side_effect=mock_delete),
        patch.object(scm, "_resolve_request_user_identity", return_value="user123"),
        patch.object(scm, "_decrypt_scm_token_payload", return_value={"token": "test"}),
    ):
        client = TestClient(app)
        response = client.get("/integrations/scm/connections")

        assert response.status_code == 200
        data = response.json()
        connections = data.get("connections", [])

        # Should have 2 connections (one GitHub, one GitLab)
        assert len(connections) == 2, f"Expected 2 connections, got {len(connections)}"

        providers = {c["provider"] for c in connections}
        assert providers == {
            "github",
            "gitlab",
        }, f"Expected both providers, got {providers}"


@pytest.mark.asyncio
async def test_scm_connections_route_tolerates_legacy_github_auth_mode():
    """
    Test that /integrations/scm/connections tolerates legacy github_auth_mode values.

    This addresses the issue where historical data may contain github_auth_mode="oauth"
    which is no longer supported by _normalize_github_auth_mode(). The endpoint should:
    1. Not fail when reading such legacy values
    2. Coerce them to "github_app" via _coerce_github_auth_mode()
    3. Deduplicate multiple GitHub connections, keeping the most recent
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import scm

    app = FastAPI()
    app.include_router(scm.router)

    # Simulate the historical data condition: multiple GitHub connections
    # with different (old) auth_mode values stored in DB
    mock_rows = [
        {
            "cache_key": "user123:github:oauth",  # Very old legacy record with unsupported value
            "provider": "github",
            "gitlab_base_url": None,
            "github_auth_mode": "oauth",  # This would fail if passed to _normalize_github_auth_mode
            "token_encrypted": "encrypted_token_1",
            "updated_at": 900.0,
        },
        {
            "cache_key": "user123:github:github_app",  # Current supported mode
            "provider": "github",
            "gitlab_base_url": None,
            "github_auth_mode": "github_app",
            "token_encrypted": "encrypted_token_2",
            "updated_at": 2000.0,
        },
    ]

    deleted_keys = []

    async def mock_list_rows(user_id: str):
        return mock_rows

    async def mock_delete(cache_key: str):
        deleted_keys.append(cache_key)

    # Mock decrypt to return a valid token payload
    def mock_decrypt(encrypted: str):
        return {"token": "test_token", "refresh_token": "test_refresh"}

    with (
        patch.object(scm, "_list_scm_token_rows_for_user", side_effect=mock_list_rows),
        patch.object(scm, "_delete_scm_token_payload", side_effect=mock_delete),
        patch.object(scm, "_resolve_request_user_identity", return_value="user123"),
        patch.object(scm, "_decrypt_scm_token_payload", side_effect=mock_decrypt),
    ):
        client = TestClient(app)
        response = client.get("/integrations/scm/connections")

        # Should succeed (200), not fail with 400 about unsupported auth_mode
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )

        data = response.json()
        connections = data.get("connections", [])

        # Should have exactly 1 GitHub connection (the duplicate with legacy mode was cleaned up)
        github_connections = [c for c in connections if c["provider"] == "github"]
        assert len(github_connections) == 1, (
            f"Expected 1 GitHub connection after dedup, got {len(github_connections)}"
        )

        # The remaining connection should be the newer one
        conn = github_connections[0]
        assert conn["github_auth_mode"] == "github_app", (
            "Should use github_app (new record)"
        )
        assert conn["updated_at"] == 2000.0, "Should have the newer timestamp"

        # The legacy cache_key should be marked for deletion
        assert "user123:github:oauth" in deleted_keys, (
            f"Legacy oauth cache_key should be deleted, deleted_keys={deleted_keys}"
        )
