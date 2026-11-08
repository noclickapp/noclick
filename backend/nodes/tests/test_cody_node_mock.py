"""Exercise Cody's real factory, auth, request mapping and response handling."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import cody_node as cody
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / 'fixtures/cody/operations.json').read_text())
AUTH = {"credential_type": "cody_api_key", "api_key": "synthetic-cody-secret"}


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "getcody.ai"
        assert request.headers["Authorization"] == "Bearer synthetic-cody-secret"
        assert AUTH["api_key"] not in str(request.url)
        status, payload = replies.pop(0)
        return httpx.Response(status, content=b"" if payload is None else json.dumps(payload).encode(), headers={"Content-Type": "application/json"})

    native = ssrf.guarded_async_client
    monkeypatch.setattr(cody, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, credential=None):
    return await run_node_operation(node_type="automation-cody", operation=operation,
        arguments=arguments or {}, credential_data=AUTH if credential is None else credential,
        user_id="00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_every_operation_is_one_contract_request(wire, case):
    requests, replies = wire
    payload = {"data": [{"id": "bot1", "name": "Factual Bot"}], "meta": {"pagination": {"next_page": 2}}} if case["operation"].startswith("list_") else {"data": {"id": "example-id"}}
    replies.append((200, payload))
    assert await run(case["operation"], case["arguments"]) == payload
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == "/api/v1" + case["path"]
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else {}) == case["body"]


@pytest.mark.asyncio
async def test_filters_focus_and_includes_remain_in_their_contract_locations(wire):
    wire[1].extend([(200, {"data": []}), (200, {"data": {"id": "c1"}})])
    await run("list_conversations", {"keyword": "Planning", "bot_id": "bot1", "includes": "document_ids"})
    assert dict(wire[0][0].url.params) == {"keyword": "Planning", "bot_id": "bot1", "includes": "document_ids"}
    await run("update_conversation", {"conversation_id": "c1", "name": "Planning", "bot_id": "bot1", "document_ids": []})
    assert json.loads(wire[0][1].content) == {"name": "Planning", "bot_id": "bot1", "document_ids": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("delete_document", {"document_id": "doc1"}), ("delete_conversation", {"conversation_id": "c1"}), ("create_document_from_file", {"folder_id": "f1", "key": "uploaded-key"})])
async def test_empty_success_and_async_acceptance(wire, operation, args):
    wire[1].append((200, None))
    assert await run(operation, args) == {"success": True, "operation": operation, "http_status": 200}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 422, 429, 500, 302])
async def test_provider_refusal_is_not_a_success_or_redirect(wire, status):
    wire[1].append((status, {"message": "Provider refused synthetic-cody-secret"}))
    with pytest.raises(ValueError, match=f"HTTP {status}") as exc:
        await run("list_bots")
    assert AUTH["api_key"] not in str(exc.value)
    assert "Provider refused" in str(exc.value)
    assert len(wire[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["../other", ".", "a/b", "a?x=y", "a%2fb", "x\n"])
async def test_path_injection_fails_before_http(wire, identifier):
    with pytest.raises(ValueError):
        await run("get_document", {"document_id": identifier})
    assert not wire[0]


@pytest.mark.asyncio
async def test_byte_limit_enforced_for_unicode_document_content(wire):
    with pytest.raises(ValueError, match="768 KB"):
        await run("create_document", {"name": "Large", "folder_id": "f1", "content": "é" * 400000})
    assert not wire[0]


@pytest.mark.asyncio
async def test_required_conversation_fields_and_key_type_before_http(wire):
    with pytest.raises(ValueError):
        await run("create_conversation", {"name": "Missing bot"})
    with pytest.raises(ValueError):
        await run("list_bots", credential={**AUTH, "credential_type": "foreign_api_key"})
    assert not wire[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, {}, [], {"data": {"id": "not-a-list"}}])
async def test_bad_list_envelope_cannot_prove_a_connection(wire, payload):
    wire[1].append((200, payload))
    with pytest.raises(ValueError, match="Cody returned"):
        await run("list_bots")
