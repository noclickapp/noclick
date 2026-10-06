"""The real picker uses authoritative row types before native provider guards.

Storage, encryption, session and provider boundaries use synthetic fixtures;
the handler, shared loader, freshening and native credential parsing run as-is.
"""

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import ValidationError


@pytest.fixture
def ensure_native_db_pool():
    """The local storage boundary never needs the suite's native database pool."""
    yield


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.fixture
def picker(monkeypatch):
    from nodes import elasticsearch_node as elastic
    from utils import encryption
    from wss.handlers import workflow_handler as module
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest

    # This suite isolates row/type preparation. Admission is covered through
    # its real repository in test_stored_picker_admission.py.
    monkeypatch.setattr(
        "repositories.credential_approvals.CredentialApprovalRepo.admit",
        AsyncMock(return_value=None),
    )

    row = {
        "credential": b"encrypted-fixture", "credential_type": "elasticsearch_api_key",
        "revoked_at": None, "token_version": 7,
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    blob = {"url": "https://search.example.test", "api_key": "fixture-key"}
    conn = SimpleNamespace(fetchrow=AsyncMock(return_value=row))
    pool = _Pool(conn)
    crypto = MagicMock()
    crypto.decrypt_credential.side_effect = lambda value: deepcopy(blob)
    monkeypatch.setattr(encryption, "get_encryption", lambda: crypto)
    monkeypatch.setattr(module, "get_encryption", lambda: crypto)
    org = AsyncMock(return_value=None)
    monkeypatch.setattr(module, "get_user_org_context", org)
    send = AsyncMock()
    monkeypatch.setattr(module, "send_event", send)
    handler = module.WorkflowHandler.__new__(module.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": "fixture-user"}))
    handler.get_pool = AsyncMock(return_value=pool)

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=httpx.Response(200, json={
        "indices": [{"name": "fixture-index"}],
    }))
    provider = MagicMock(return_value=client)
    monkeypatch.setattr(elastic, "guarded_async_client", provider)
    freshen = AsyncMock(wraps=elastic.ElasticsearchNode.freshen_credential)
    options = AsyncMock(wraps=elastic.ElasticsearchNode.load_field_options)
    monkeypatch.setattr(elastic.ElasticsearchNode, "freshen_credential", freshen)
    monkeypatch.setattr(elastic.ElasticsearchNode, "load_field_options", options)

    async def load(**kwargs):
        request = WorkflowNodeLoadOptionsRequest(**{
            "request_id": "fixture-picker", "node_type": "automation-elasticsearch",
            "field_name": "index", "credential_id": "fixture-credential", **kwargs,
        })
        await handler.load_node_options("fixture-sid", request)
        send.assert_awaited_once()
        event = send.call_args.args[2]
        assert event.request_id == "fixture-picker" and event.error is None
        return event.data

    return SimpleNamespace(
        row=row, blob=blob, conn=conn, pool=pool, crypto=crypto, org=org,
        handler=handler, client=client, provider=provider, freshen=freshen,
        options=options, load=load,
    )


@pytest.mark.parametrize("blob_type", [None, "elasticsearch_api_key"])
@pytest.mark.parametrize("row_type", ["slack_oauth", "api_key"])
async def test_foreign_row_is_rejected_by_native_picker_before_provider(picker, blob_type, row_type):
    from nodes.elasticsearch_node import ElasticsearchCredential

    picker.row["credential_type"] = row_type
    if blob_type is not None:
        picker.blob["credential_type"] = blob_type
    result = await picker.load()

    # Elasticsearch's existing native guard returns an empty list on rejection.
    assert result["success"] is True and result["options"] == []
    loaded = picker.options.call_args.kwargs["credential_data"]
    assert loaded["credential_type"] == row_type
    assert picker.freshen.call_args.args[0]["credential_type"] == row_type
    with pytest.raises(ValidationError) as error:
        ElasticsearchCredential.model_validate(loaded)
    assert error.value.errors()[0]["loc"] == ("credential_type",)
    picker.provider.assert_not_called()
    picker.client.get.assert_not_awaited()


@pytest.mark.parametrize("blob_type", [None, "slack_oauth", "elasticsearch_api_key"])
@pytest.mark.parametrize("org_id", [None, "fixture-org"])
async def test_native_row_wins_before_freshening_and_options(picker, blob_type, org_id):
    from repositories.credentials import credential_access_predicate

    picker.org.return_value = org_id
    if blob_type is not None:
        picker.blob["credential_type"] = blob_type
    result = await picker.load(
        context={"_user_id": "caller-supplied-user", "folder": "fixture-folder"},
        page_token="fixture-cursor", search=" fixture ",
    )

    assert result["success"] is True
    assert result["options"] == [{"value": "fixture-index", "label": "fixture-index", "metadata": None}]
    loaded = picker.freshen.call_args.args[0]
    assert loaded["credential_type"] == "elasticsearch_api_key"
    assert loaded["token_version"] == 7
    assert loaded["updated_at"] == picker.row["updated_at"].isoformat()
    assert picker.options.call_args.kwargs["credential_data"] == loaded
    assert picker.options.call_args.kwargs["context"] == {
        "_user_id": "fixture-user", "folder": "fixture-folder",
    }
    assert picker.options.call_args.kwargs["search"] == "fixture"
    assert picker.options.call_args.kwargs["page_token"] == "fixture-cursor"
    picker.provider.assert_called_once()
    picker.client.get.assert_awaited_once()
    assert picker.client.get.call_args.args[0] == "https://search.example.test/_resolve/index/*"
    assert picker.client.get.call_args.kwargs["headers"]["Authorization"] == "ApiKey fixture-key"
    sql, credential_id, user_id, query_org = picker.conn.fetchrow.call_args.args
    assert credential_access_predicate() in sql
    assert (credential_id, user_id, query_org) == ("fixture-credential", "fixture-user", org_id)


@pytest.mark.parametrize("row_type", [None, "missing"])
@pytest.mark.parametrize("blob_type", [None, "elasticsearch_api_key"])
async def test_absent_row_type_preserves_legacy_blob_discriminator(picker, row_type, blob_type):
    if blob_type is not None:
        picker.blob["credential_type"] = blob_type
    if row_type == "missing":
        del picker.row["credential_type"]
    else:
        picker.row["credential_type"] = None
    result = await picker.load()

    assert result["options"][0]["value"] == "fixture-index"
    assert picker.freshen.call_args.args[0].get("credential_type") == blob_type
    picker.client.get.assert_awaited_once()


@pytest.mark.parametrize("unavailable", ["missing_or_inaccessible", "revoked"])
async def test_unavailable_row_never_decrypts_or_reaches_native_provider(picker, unavailable):
    if unavailable == "revoked":
        picker.row["revoked_at"] = datetime(2026, 1, 1, tzinfo=timezone.utc)
    else:
        picker.conn.fetchrow.return_value = None
    result = await picker.load()

    assert result["success"] is False
    assert result["message"] == "Credential not found or access denied"
    picker.crypto.decrypt_credential.assert_not_called()
    picker.freshen.assert_not_awaited()
    picker.options.assert_not_awaited()
    picker.provider.assert_not_called()


@pytest.mark.parametrize("failure", ["fetch", "decrypt"])
async def test_credential_loading_error_returns_typed_failure(picker, failure):
    if failure == "fetch":
        picker.conn.fetchrow.side_effect = RuntimeError("fixture storage failure")
    else:
        picker.crypto.decrypt_credential.side_effect = ValueError("fixture decryption failure")
    result = await picker.load()

    assert result["success"] is False and result["message"] == "Failed to load credential"
    picker.freshen.assert_not_awaited()
    picker.options.assert_not_awaited()
    picker.provider.assert_not_called()


async def test_service_account_row_selects_native_preparation(picker, monkeypatch):
    from nodes import bigquery_node as bigquery
    from nodes.core import oauth_refresh

    picker.row["credential_type"] = "bigquery_service_account"
    picker.blob.clear()
    picker.blob.update(service_account_json="synthetic service-account fixture", credential_type="bigquery_oauth")
    mint = AsyncMock(return_value="fixture-minted-token")
    request = AsyncMock(return_value={
        "status": "success", "data": {"projects": [{"id": "fixture-project", "friendlyName": "Fixture"}]},
    })
    oauth = AsyncMock(side_effect=AssertionError("service accounts must not take the OAuth branch"))
    monkeypatch.setattr(bigquery, "_mint_service_account_access_token", mint)
    monkeypatch.setattr(bigquery, "_bigquery_request", request)
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", oauth)
    result = await picker.load(node_type="automation-bigquery", field_name="project_id")

    assert result["success"] is True
    assert result["options"] == [{"value": "fixture-project", "label": "Fixture", "metadata": None}]
    mint.assert_awaited_once_with("synthetic service-account fixture")
    request.assert_awaited_once_with("fixture-minted-token", "GET", "/projects", action_name="list_projects")
    oauth.assert_not_awaited()


async def test_credential_less_picker_keeps_context_search_and_pagination(picker, monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    seen = {}

    class Node:
        @classmethod
        async def freshen_credential(cls, *args, **kwargs):
            raise AssertionError("credential-less picker must not freshen")

        @classmethod
        async def load_field_options(cls, **kwargs):
            seen.update(kwargs)
            return {"options": [{"value": "fixture-option", "label": "Fixture"}], "next_page_token": "fixture-next"}

    monkeypatch.setitem(NODE_REGISTRY, "fixture-credential-less", Node)
    result = await picker.load(
        node_type="fixture-credential-less", credential_id=None,
        context={"folder": "fixture-folder"}, page_token="fixture-cursor", search="  ",
    )

    assert result["success"] is True and result["next_page_token"] == "fixture-next"
    assert seen == {
        "field_name": "index", "credential_data": {},
        "context": {"folder": "fixture-folder", "_user_id": "fixture-user"},
        "page_token": "fixture-cursor", "search": None,
    }
    picker.handler.get_pool.assert_not_awaited()
    picker.crypto.decrypt_credential.assert_not_called()
    picker.provider.assert_not_called()
