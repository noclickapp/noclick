"""Unit tests for Facebook OAuth helper used by Instagram node."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nodes.oauth.facebook_oauth import exchange_code_for_tokens


def _mock_response(status_code: int, payload: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=payload)
    return resp


@pytest.mark.asyncio
async def test_exchange_discovers_instagram_via_page_token_fallback(monkeypatch):
    """Fallback path should discover IG account when nested page field is missing."""
    monkeypatch.setenv("FACEBOOK_APP_ID", "app-id")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "app-secret")

    # 1) code -> short lived
    # 2) short -> long lived
    # 3) me/accounts (without instagram_business_account)
    # 4) page lookup via page access token (has instagram_business_account)
    # 5) me?fields=email
    responses = [
        _mock_response(200, {"access_token": "short"}),
        _mock_response(200, {"access_token": "long", "expires_in": 5184000, "token_type": "Bearer"}),
        _mock_response(200, {"data": [{"id": "page_1", "name": "My Page", "access_token": "page_token_1"}]}),
        _mock_response(200, {"id": "page_1", "name": "My Page", "instagram_business_account": {"id": "ig_1", "username": "ig_user"}}),
        _mock_response(200, {"email": "user@example.com"}),
    ]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=responses)
    async_client_mock = MagicMock()
    async_client_mock.return_value.__aenter__.return_value = mock_client

    with patch("nodes.oauth.facebook_oauth.httpx.AsyncClient", async_client_mock):
        tokens, info = await exchange_code_for_tokens("code123", "https://example.com/callback")

    assert tokens.access_token == "long"
    assert info.instagram_user_id == "ig_1"
    assert info.instagram_username == "ig_user"
    assert info.facebook_page_id == "page_1"
    assert info.email == "user@example.com"


@pytest.mark.asyncio
async def test_exchange_error_includes_granted_scopes_when_no_account(monkeypatch):
    """No-account error should include granted scopes to aid debugging."""
    monkeypatch.setenv("FACEBOOK_APP_ID", "app-id")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "app-secret")

    responses = [
        _mock_response(200, {"access_token": "short"}),
        _mock_response(200, {"access_token": "long", "expires_in": 5184000, "token_type": "Bearer"}),
        _mock_response(200, {"data": [{"id": "page_1", "name": "My Page", "access_token": "page_token_1"}]}),
        _mock_response(200, {"id": "page_1", "name": "My Page"}),  # page fallback still no IG account
        _mock_response(200, {"data": {"scopes": ["pages_show_list"]}}),  # debug_token
    ]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=responses)
    async_client_mock = MagicMock()
    async_client_mock.return_value.__aenter__.return_value = mock_client

    with patch("nodes.oauth.facebook_oauth.httpx.AsyncClient", async_client_mock):
        with pytest.raises(ValueError) as exc:
            await exchange_code_for_tokens("code123", "https://example.com/callback")

    message = str(exc.value)
    assert "No Instagram Business account found" in message
    assert "instagram_basic" in message
    assert "Granted scopes on this token" in message


@pytest.mark.asyncio
async def test_exchange_supports_connected_instagram_account_field(monkeypatch):
    """Support Meta page payloads that expose connected_instagram_account."""
    monkeypatch.setenv("FACEBOOK_APP_ID", "app-id")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "app-secret")

    responses = [
        _mock_response(200, {"access_token": "short"}),
        _mock_response(200, {"access_token": "long", "expires_in": 5184000, "token_type": "Bearer"}),
        _mock_response(200, {"data": [{
            "id": "page_1",
            "name": "My Page",
            "access_token": "page_token_1",
            "connected_instagram_account": {"id": "ig_2", "username": "connected_ig"},
        }]}),
        _mock_response(200, {"email": "user@example.com"}),
    ]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=responses)
    async_client_mock = MagicMock()
    async_client_mock.return_value.__aenter__.return_value = mock_client

    with patch("nodes.oauth.facebook_oauth.httpx.AsyncClient", async_client_mock):
        _, info = await exchange_code_for_tokens("code123", "https://example.com/callback")

    assert info.instagram_user_id == "ig_2"
    assert info.instagram_username == "connected_ig"
