"""Credential rows, not optional encrypted-blob tags, select provider models.

All values are synthetic. The consumer regressions exercise the real workflow
credential resolver and Instagram node with mocked storage, encryption and HTTP.
"""

from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import ValidationError

from utils.credentials import get_credential


class _Connection:
    def __init__(self, row):
        self.fetchrow = AsyncMock(return_value=row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Pool:
    def __init__(self, row):
        self.connection = _Connection(row)

    def acquire(self):
        return self.connection


def _fixture(monkeypatch, credential_type, blob, *, revoked_at=None):
    row = {
        "credential": b"synthetic-encrypted-fixture",
        "credential_type": credential_type,
        "revoked_at": revoked_at,
    }
    encryption = MagicMock()
    encryption.decrypt_credential.side_effect = lambda _value: deepcopy(blob)
    monkeypatch.setattr("utils.credentials.get_encryption", lambda: encryption)
    return _Pool(row), encryption


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_type", ["instagram_login", "instagram_oauth", "slack_oauth", "api_key"])
async def test_get_credential_includes_authoritative_row_type(monkeypatch, credential_type):
    blob = {"access_token": "synthetic-token-only", "custom": "preserved"}
    pool, encryption = _fixture(monkeypatch, credential_type, blob)

    actual = await get_credential("credential-fixture", "user-fixture", pool, "org-fixture")

    assert actual == {**blob, "credential_type": credential_type}
    encryption.decrypt_credential.assert_called_once_with(b"synthetic-encrypted-fixture")
    sql, credential_id, user_id, org_id = pool.connection.fetchrow.await_args.args
    assert "c.credential_type" in sql
    assert (credential_id, user_id, org_id) == ("credential-fixture", "user-fixture", "org-fixture")


@pytest.mark.asyncio
async def test_row_type_overrides_conflicting_blob_type(monkeypatch):
    pool, _ = _fixture(monkeypatch, "instagram_login", {
        "access_token": "synthetic-token-only", "credential_type": "instagram_oauth",
    })

    actual = await get_credential("credential-fixture", "user-fixture", pool)

    assert actual["credential_type"] == "instagram_login"


@pytest.mark.asyncio
@pytest.mark.parametrize("row_type", [None, "missing"])
async def test_absent_row_type_preserves_legacy_blob(monkeypatch, row_type):
    """Keep compatibility with legacy adapters/fixtures lacking the column."""
    blob = {"api_key": "synthetic-key-only", "credential_type": "api_key"}
    pool, _ = _fixture(monkeypatch, None, blob)
    if row_type == "missing":
        del pool.connection.fetchrow.return_value["credential_type"]

    assert await get_credential("credential-fixture", "user-fixture", pool) == blob


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["unauthorized", "revoked"])
async def test_unavailable_credentials_are_never_decrypted(monkeypatch, unavailable):
    pool, encryption = _fixture(monkeypatch, "instagram_login", {"access_token": "unused"})
    if unavailable == "unauthorized":
        pool.connection.fetchrow.return_value = None
    else:
        pool.connection.fetchrow.return_value["revoked_at"] = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert await get_credential("credential-fixture", "user-fixture", pool) is None
    encryption.decrypt_credential.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row_type,expected_class,expected_host",
    [
        ("instagram_login", "InstagramLoginCredential", "graph.instagram.com"),
        ("instagram_oauth", "InstagramOAuthCredential", "graph.facebook.com"),
        ("instagram_system_user_token", "InstagramSystemUserTokenCredential", "graph.facebook.com"),
        ("instagram_page_access_token", "InstagramPageAccessTokenCredential", "graph.facebook.com"),
    ],
)
async def test_workflow_resolver_preserves_instagram_auth_model_through_http(
    monkeypatch, row_type, expected_class, expected_host,
):
    from nodes.instagram_node import InstagramNode, InstagramNodeConfig
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

    # The direct Instagram OAuth handler stores exactly these fields in the
    # encrypted blob. Its discriminator exists only in credentials.credential_type.
    blob = {
        "access_token": "synthetic-provider-token-only",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "instagram_user_id": "17841400000000000",
        "instagram_username": "controlled_fixture",
    }
    pool, _ = _fixture(monkeypatch, row_type, blob)
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=pool)

    resolved = await handler._resolve_credentials(
        {"operation": "get_user_profile", "fields": "user_id,username", "credentialIds": {row_type: "credential-fixture"}},
        user_id="user-fixture", org_id="org-fixture",
    )
    config = InstagramNodeConfig.model_validate(resolved)
    requests = []

    async def fake_request(_client, method, url, *, params=None, json=None):
        requests.append((method, httpx.URL(url), params))
        return httpx.Response(200, json={"id": "17841400000000000", "username": "controlled_fixture"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    node = InstagramNode(
        "instagram-fixture", "automation-instagram", {}, config=config,
        workflow_id="workflow-fixture", user_id="user-fixture",
    )
    result = await node.run({})

    assert result["status"] == "success"
    assert len(requests) == 1
    method, url, params = requests[0]
    assert method == "GET"
    assert url.host == expected_host
    assert type(config.credentials).__name__ == expected_class
    assert config.credentials.credential_type == row_type
    assert params["access_token"] == blob["access_token"]


@pytest.mark.asyncio
async def test_foreign_row_type_cannot_fall_back_to_instagram_model(monkeypatch):
    from nodes.instagram_node import InstagramNodeConfig

    pool, _ = _fixture(monkeypatch, "slack_oauth", {
        "access_token": "synthetic-token-only",
        "instagram_user_id": "17841400000000000",
        "expires_at": "2099-01-01T00:00:00+00:00",
    })
    credential = await get_credential("credential-fixture", "user-fixture", pool)

    with pytest.raises(ValidationError):
        InstagramNodeConfig.model_validate({"config": {"operation": "get_user_profile"}, "credentials": credential})
