"""Exercise native Zigpoll requests against published v1 examples, without accounts."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import zigpoll_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NodeFactory

TOKEN = "fixture-zigpoll-private-key"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/zigpoll/contract_examples.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {"credential_type": "zigpoll_api_key", "api_key": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="zigpoll-fixture", node_type="automation-zigpoll",
        node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_published_contract_request_and_response(monkeypatch, operation):
    example = EXAMPLES[operation]
    requests = transport(monkeypatch, example["response"])
    config = {"operation": operation, **example["request"]}
    result = await node(config).execute({})
    assert result["data"] == example["response"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example["method"]
    assert request.url.scheme == "https" and request.url.host == "v1.zigpoll.com"
    assert request.url.path == example["path"]
    assert request.headers["Authorization"] == TOKEN
    if request.method == "GET":
        assert dict(request.url.params) == example["request"]
        assert not request.content
    else:
        assert json.loads(request.content) == example["request"]
        assert not request.url.query


@pytest.mark.asyncio
async def test_cursor_and_multi_answer_components_are_preserved(monkeypatch):
    payload = {"data": [{"response": "Red, Blue", "answers": [{"handle": "red"}, {"handle": "blue"}],
        "files": ["https://uploads.example.test/file"]}], "hasNextPage": True, "endCursor": "cursor-next"}
    requests = transport(monkeypatch, payload)
    result = await node({"operation": "list_responses", "pollId": "poll-1", "startCursor": "cursor-old",
        "createdAfter": "1700000000000", "filter": "fixed-choice", "order": "oldest", "limit": 25}).execute({})
    assert result == {"data": payload}
    assert dict(requests[0].url.params) == {"pollId": "poll-1", "startCursor": "cursor-old", "limit": "25",
        "createdAfter": "1700000000000", "filter": "fixed-choice", "order": "oldest"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 422, 429, 500])
async def test_provider_failure_is_not_retried_and_redacts_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"error": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "send_email", "pollId": "poll-1", "recipients": ["person@acme.test"]}).execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_error_is_redacted_before_truncation(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(401, text="a" * 1990 + TOKEN))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_me"}).execute({})
    assert TOKEN[:10] not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"error": "Rejected"}, {"success": False}, 42])
async def test_error_envelope_and_invalid_response_shape(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "get_me"}).execute({})


@pytest.mark.asyncio
async def test_non_json_success_and_timeout_do_not_retry_write(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "create_poll", "accountId": "account-1", "title": "Feedback"}).execute({})
    assert len(requests) == 1
    def timeout(request):
        raise httpx.ReadTimeout(TOKEN, request=request)
    requests = transport(monkeypatch, timeout)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "create_poll", "accountId": "account-1", "title": "Feedback"}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_read_evidence_names_the_accounts(monkeypatch):
    requests = transport(monkeypatch, [{"_id": "account-1", "title": "Acme Store"}])
    result = await collect_evidence(node_type="automation-zigpoll", user_id="fixture-user", credential_data=credential())
    assert result.reachable is True
    assert "Acme Store" in str(result)
    assert requests[0].method == "GET" and requests[0].url.path == "/accounts"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,reachable", [
    (200, {}, None),
    (401, {"error": "Private key rejected"}, False),
    (500, {"error": "Temporarily unavailable"}, None),
])
async def test_evidence_refuses_rejection_and_unexpected_shape(monkeypatch, status, body, reachable):
    transport(monkeypatch, lambda r: httpx.Response(status, json=body))
    result = await collect_evidence(node_type="automation-zigpoll", user_id="fixture-user", credential_data=credential())
    assert result.reachable is reachable


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,payload", [
    ("get_me", []), ("get_me", {}), ("list_accounts", ["bad-row"]),
    ("list_responses", {"data": "bad", "hasNextPage": False}),
])
async def test_operation_specific_response_shape(monkeypatch, operation, payload):
    transport(monkeypatch, payload)
    config = {"operation": operation, **({"pollId": "poll-1"} if operation == "list_responses" else {})}
    with pytest.raises(ValueError):
        await node(config).execute({})


@pytest.mark.parametrize("key", ["", "https://www.zigpoll.com", "<token>", "Bearer secret", "abc\nsecret", "nonasciié"])
def test_invalid_credentials(key):
    with pytest.raises(ValidationError):
        native.ZigpollAPIKeyCredential(api_key=key)


def test_only_supplied_update_fields_are_sent():
    config = node({"operation": "update_poll", "pollId": "poll-1", "isVisible": False, "pageRules": []}).config.config
    assert config.model_dump(exclude_none=True, exclude={"operation"}) == {"pollId": "poll-1", "isVisible": False, "pageRules": []}
    with pytest.raises(ConfigValidationError, match="less than or equal to 5000"):
        node({"operation": "list_responses", "pollId": "poll-1", "limit": 5001})
    with pytest.raises(ConfigValidationError, match="pollId"):
        node({"operation": "get_poll"})
