"""Prepared primary REST contract tests. Not run while campaign CI is paused."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nodes.granola_node import GranolaNode, GranolaNodeConfig, GranolaApiKeyCredential, _request

CASES = [({'operation': 'list_notes', 'page_size': 10}, 'GET', '/v1/notes', {'page_size': 10}, None), ({'operation': 'get_note', 'note_id': 'not_1d3tmYTlCICgjy'}, 'GET', '/v1/notes/not_1d3tmYTlCICgjy', {}, None), ({'operation': 'get_transcript', 'note_id': 'not_1d3tmYTlCICgjy', 'page_size': 50}, 'GET', '/v1/notes/not_1d3tmYTlCICgjy/transcript', {'page_size': 50}, None), ({'operation': 'list_folders', 'page_size': 10}, 'GET', '/v1/folders', {'page_size': 10}, None), ({'operation': 'list_spaces', 'page_size': 10}, 'GET', '/v1/spaces', {'page_size': 10}, None), ({'operation': 'list_audit_events', 'page_size': 10}, 'GET', '/v1/audit', {'page_size': 10}, None), ({'operation': 'create_webhook_endpoint', 'url': 'https://example.com/granola-webhooks', 'scopes': ['personal', 'public'], 'events': ['note.access_granted', 'note.edited', 'note.generated']}, 'POST', '/v1/webhook-endpoints', {}, {'url': 'https://example.com/granola-webhooks', 'scopes': ['personal', 'public'], 'events': ['note.access_granted', 'note.edited', 'note.generated']}), ({'operation': 'list_webhook_endpoints'}, 'GET', '/v1/webhook-endpoints', {}, None), ({'operation': 'update_webhook_endpoint', 'webhook_endpoint_id': 'whe_2mKr8fQxLp7Ta3'}, 'PATCH', '/v1/webhook-endpoints/whe_2mKr8fQxLp7Ta3', {}, None), ({'operation': 'delete_webhook_endpoint', 'webhook_endpoint_id': 'whe_2mKr8fQxLp7Ta3'}, 'DELETE', '/v1/webhook-endpoints/whe_2mKr8fQxLp7Ta3', {}, None), ({'operation': 'create_legal_hold', 'name': 'X v. Y', 'covers_entire_workspace': False}, 'POST', '/v1/legal-holds', {}, {'name': 'X v. Y', 'covers_entire_workspace': False}), ({'operation': 'list_legal_holds', 'page_size': 10}, 'GET', '/v1/legal-holds', {'page_size': 10}, None), ({'operation': 'get_legal_hold', 'hold_id': 'lgh_Abc123XyZ456De'}, 'GET', '/v1/legal-holds/lgh_Abc123XyZ456De', {}, None), ({'operation': 'update_legal_hold', 'hold_id': 'lgh_Abc123XyZ456De'}, 'PATCH', '/v1/legal-holds/lgh_Abc123XyZ456De', {}, None), ({'operation': 'release_legal_hold', 'hold_id': 'lgh_Abc123XyZ456De'}, 'DELETE', '/v1/legal-holds/lgh_Abc123XyZ456De', {}, None), ({'operation': 'add_legal_hold_custodians', 'hold_id': 'lgh_Abc123XyZ456De', 'custodians': [{'email': 'person@example.test'}]}, 'POST', '/v1/legal-holds/lgh_Abc123XyZ456De/custodians', {}, {'custodians': [{'email': 'person@example.test'}]}), ({'operation': 'list_legal_hold_custodians', 'hold_id': 'lgh_Abc123XyZ456De', 'page_size': 10}, 'GET', '/v1/legal-holds/lgh_Abc123XyZ456De/custodians', {'page_size': 10}, None), ({'operation': 'remove_legal_hold_custodian', 'hold_id': 'lgh_Abc123XyZ456De', 'custodian_id': 'lhc_7Yt3nBv8Wq2Lms'}, 'DELETE', '/v1/legal-holds/lgh_Abc123XyZ456De/custodians/lhc_7Yt3nBv8Wq2Lms', {}, None)]

@pytest.mark.asyncio
@pytest.mark.parametrize("args,method,path,params,body", CASES)
async def test_documented_http_contract(args, method, path, params, body):
    credential = GranolaApiKeyCredential(api_key="test-key")
    config = GranolaNodeConfig(config=args, credentials=credential)
    node = GranolaNode("test", "automation-granola", {}, config=config)
    client = AsyncMock()
    client.request.return_value = httpx.Response(200, json={"items": [{"id": "resource"}]})
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    with patch("nodes.granola_node.httpx.AsyncClient", return_value=context):
        result = await node.execute({})
    assert result["status"] == "success"
    positional, kwargs = client.request.call_args
    assert positional == (method, 'https://public-api.granola.ai' + path)
    assert kwargs["headers"]["Authorization"] == 'Bearer test-key'
    if args["operation"] == "upload_file":
        assert kwargs["files"] == {"file": ("sample.txt", b"hello", "text/plain")}
        assert "json" not in kwargs
    else:
        assert kwargs["params"] == params
        assert kwargs.get("json") == body
    assert result["data"] == {"items": [{"id": "resource"}]}
    assert "total" in result["timing_ms"]

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_provider_errors_are_not_retried_or_echoed(status):
    client = AsyncMock()
    client.request.return_value = httpx.Response(status, json={"error": "test-key"}, headers={"Retry-After": "60"})
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    with patch("nodes.granola_node.httpx.AsyncClient", return_value=context) as constructor:
        result = await _request({"api_key": "test-key"}, "GET", '/v1/notes', action="probe")
    assert result["status"] == "error"
    assert result["status_code"] == status
    assert "test-key" not in json.dumps(result)
    client.request.assert_awaited_once()
    assert constructor.call_args.kwargs["follow_redirects"] is False

@pytest.mark.asyncio
async def test_timeout_is_not_retried():
    client = AsyncMock()
    client.request.side_effect = httpx.ReadTimeout("sensitive request details")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    with patch("nodes.granola_node.httpx.AsyncClient", return_value=context):
        result = await _request({"api_key": "test-key"}, "GET", '/v1/notes', action="probe")
    assert result["status"] == "error"
    assert "sensitive" not in json.dumps(result)
    client.request.assert_awaited_once()

def test_explicit_null_clears_legal_hold_description():
    from nodes.granola_node import GranolaUpdateLegalHoldConfig, _request_parts
    op = GranolaUpdateLegalHoldConfig(hold_id="lgh_Abc123XyZ456De", description=None)
    assert _request_parts(op)[3] == {"description": None}
    assert _request_parts(GranolaUpdateLegalHoldConfig(hold_id="lgh_Abc123XyZ456De"))[3] is None

def test_custodian_needs_an_identity():
    from nodes.granola_node import GranolaLegalHoldCustodianInput
    with pytest.raises(ValueError):
        GranolaLegalHoldCustodianInput()
