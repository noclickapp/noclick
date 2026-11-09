"""Exercise Responder through the platform factory with fixture-only HTTP.

These checks cover all operation routes plus explicit consent, query placement,
provider rejection, secret redaction and ambiguous write failures.
"""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import responder_node as responder
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / "fixtures/responder/cases.json").read_text())
TOKEN = "responder-fixture-account-access-token"
AUTH = {"credential_type": "responder_access_token", "access_token": TOKEN}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "graph.responder.live"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        code, payload = reply
        if isinstance(payload, bytes):
            return httpx.Response(code, content=payload)
        return httpx.Response(code, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(responder, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(
        node_type="automation-responder", operation=operation,
        arguments=deepcopy(arguments or {}), credential_data=deepcopy(auth), user_id=USER,
    )


@pytest.mark.parametrize("operation", CASES)
@pytest.mark.asyncio
async def test_one_contract_request_per_operation(transport, operation):
    case = CASES[operation]
    requests, replies = transport
    replies.append((200, case["response"]))
    result = await run(operation, case["config"])
    assert result["status"] == "success", result
    assert result["data"] == case["expected_data"]
    assert len(requests) == 1 and replies == []
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == "/v2" + case["path"]
    assert dict(request.url.params) == {k: str(v) for k, v in case["query"].items()}
    assert (json.loads(request.content) if request.content else {}) == case["body"]
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_search_defaults_are_required_query_parameters(transport):
    requests, replies = transport
    replies.append((200, {"status": True, "data": [], "total": 0}))
    await run("search_subscribers", {"listId": 1, "searchKey": "doe@example.com"})
    assert dict(requests[0].url.params) == {"listId": "1", "searchKey": "doe@example.com", "offset": "0", "size": "100"}
    assert requests[0].content == b""


@pytest.mark.asyncio
async def test_subscriber_identifier_cannot_inject_query_or_path(transport):
    requests, replies = transport
    replies.append((200, {"status": "true", "data": {}}))
    await run("get_subscriber", {"identifier": "user+tag@example.com/?expand=secret#fragment"})
    assert requests[0].url.query == b"" and requests[0].url.fragment == ""
    assert b"%2F%3Fexpand%3Dsecret%23fragment" in requests[0].url.raw_path


@pytest.mark.asyncio
async def test_account_and_subscriber_secrets_are_never_emitted(transport):
    _, replies = transport
    replies.append((200, {"status": True, "data": [{"name": "David", "password": "private", "mfa_secret": "private", "token": "private", "note": TOKEN}]}))
    result = await run("get_account")
    assert "private" not in json.dumps(result)
    assert TOKEN not in json.dumps(result)
    assert result["data"]["data"][0] == {"name": "David", "note": "[redacted]"}


@pytest.mark.parametrize("code,payload", [(401, {"message": "Token expired"}), (403, {"error": "Access denied"}), (200, {"status": False, "message": "Account disabled"}), (200, {"status": "false", "message": "Account disabled"})])
@pytest.mark.asyncio
async def test_provider_rejections_are_errors_with_provider_text(transport, code, payload):
    requests, replies = transport
    replies.append((code, payload))
    result = await run("list_lists")
    assert result["status"] == "error" and result["success"] is False
    assert (payload.get("message") or payload["error"]) in result["error"]
    assert len(requests) == 1


@pytest.mark.parametrize("reply", [httpx.ReadTimeout("timeout"), (500, {"message": "Unavailable"}), (200, b"not JSON"), (200, b""), (302, b"")])
@pytest.mark.asyncio
async def test_failed_writes_are_not_retried_and_outcome_is_unknown(transport, reply):
    requests, replies = transport
    replies.append(reply)
    result = await run("create_subscriber_tag", {"name": "My tag"})
    assert result["status"] == "error" and result["write_outcome"] == "unknown"
    assert len(requests) == 1 and not replies


@pytest.mark.parametrize("token", ["", "Bearer abc", "abc\nxyz", "https://example.com/key"])
def test_manual_credential_rejects_bad_tokens(token):
    with pytest.raises((ValidationError, ValueError)):
        responder.ResponderAccessTokenCredential(access_token=token)


def test_manual_credential_defaults_type_and_rejects_foreign_credentials():
    credential = responder.ResponderAccessTokenCredential(access_token=TOKEN)
    assert credential.credential_type == "responder_access_token"
    with pytest.raises(ValueError, match="Responder"):
        responder.ResponderNode.parse_config({"config": {"operation": "list_lists"}, "credentials": {"credential_type": "another_token", "access_token": TOKEN}})


@pytest.mark.parametrize("operation,arguments", [("create_subscriber", {"email": "doe@example.com", "list_ids": [1, 1]}), ("update_subscriber", {"subscriber_id": 1}), ("update_subscriber", {"subscriber_id": 1, "email": None}), ("update_list_subscriber", {"list_id": 1, "subscriber_id": 1})])
def test_invalid_or_empty_writes_fail_before_http(operation, arguments):
    with pytest.raises(ValidationError):
        responder.ResponderNodeConfig.model_validate({"config": {"operation": operation, **arguments}, "credentials": AUTH})
