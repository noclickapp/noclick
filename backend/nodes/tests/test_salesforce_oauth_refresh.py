from unittest.mock import AsyncMock

import pytest

from nodes.oauth.salesforce_oauth import refresh_access_token


class _Response:
    status_code = 200

    def json(self):
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "instance_url": "https://rotated.my.salesforce.com",
            "issued_at": "1779710400000",
            "token_type": "Bearer",
            "scope": "api refresh_token",
        }


class _Client:
    def __init__(self, *args, **kwargs):
        self.post = AsyncMock(return_value=_Response())

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_salesforce_refresh_preserves_rotated_refresh_token(monkeypatch):
    client = _Client()
    monkeypatch.setenv("SALESFORCE_CLIENT_ID", "client-id")
    monkeypatch.setenv("SALESFORCE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        "nodes.oauth.salesforce_oauth.httpx.AsyncClient",
        lambda *args, **kwargs: client,
    )

    tokens = await refresh_access_token(
        "old-refresh",
        "https://old.my.salesforce.com",
        is_sandbox=False,
    )

    assert tokens.access_token == "new-access"
    assert tokens.refresh_token == "new-refresh"
    assert tokens.instance_url == "https://rotated.my.salesforce.com"
    client.post.assert_awaited_once()
    assert client.post.await_args.kwargs["data"]["refresh_token"] == "old-refresh"
