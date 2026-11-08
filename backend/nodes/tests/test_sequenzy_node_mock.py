"""Exercise Sequenzy's native factory with HTTP fixtures and no live account.

These regressions cover all endpoint mappings, consent defaults, pagination,
connection evidence, error handling and credential validation at the real seam.
"""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import sequenzy_node as native
from nodes.core.registry import NodeFactory

TOKEN = "seq_live_synthetic_fixture_key"
AUTH = {"credential_type": "sequenzy_api_key", "api_key": TOKEN}
EMAIL = "user+test@example.com"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id="sequenzy-fixture", node_type="automation-sequenzy",
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    def respond(request):
        requests.append(request)
        result = replies.pop(0)
        if isinstance(result, Exception):
            raise result
        status, body = result
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, replies


CASES = [
    ("get_account_info", {}, "GET", "/subscribers/me", {}),
    ("list_subscribers", {}, "GET", "/subscribers", {"limit": "20"}),
    ("get_subscriber", {"email": EMAIL}, "GET", "/subscribers/user%2Btest%40example.com", {}),
    ("create_subscriber", {"email": EMAIL, "first_name": "John", "lists": []}, "POST", "/subscribers", {"email": EMAIL, "firstName": "John", "lists": [], "duplicateStrategy": "skip", "optInMode": "default", "enrollInSequences": False}),
    ("update_subscriber", {"email": EMAIL, "custom_attributes": {"plan": "pro"}}, "PATCH", "/subscribers/user%2Btest%40example.com", {"customAttributes": {"plan": "pro"}, "customAttributesStrategy": "merge"}),
    ("delete_subscriber", {"email": EMAIL}, "DELETE", "/subscribers/user%2Btest%40example.com", {}),
    ("add_tag", {"email": EMAIL, "tag": "premium"}, "POST", "/subscribers/tags", {"email": EMAIL, "tag": "premium"}),
    ("remove_tag", {"email": EMAIL, "tag": "premium"}, "POST", "/subscribers/tags/remove", {"email": EMAIL, "tag": "premium"}),
    ("trigger_event", {"email": EMAIL, "event": "purchase.completed", "properties": {"amount": 9900}, "event_id": "inv_9182"}, "POST", "/subscribers/events", {"email": EMAIL, "event": "purchase.completed", "properties": {"amount": 9900}, "eventId": "inv_9182"}),
    ("list_tags", {}, "GET", "/tags", {}),
    ("create_tag", {"name": "premium", "color": "blue"}, "POST", "/tags", {"name": "premium", "color": "blue"}),
    ("list_lists", {}, "GET", "/lists", {}),
    ("create_list", {"name": "Newsletter"}, "POST", "/lists", {"name": "Newsletter", "isPrivate": False, "allowMemberUnsubscribe": False}),
    ("add_subscribers_to_list", {"list_id": "list_abc123", "emails": [EMAIL]}, "POST", "/lists/list_abc123/subscribers", {"emails": [EMAIL], "duplicateStrategy": "skip", "optInMode": "default", "enrollInSequences": False}),
    ("remove_subscribers_from_list", {"list_id": "list_abc123", "emails": [EMAIL]}, "POST", "/lists/list_abc123/subscribers/remove", {"emails": [EMAIL]}),
    ("list_sequences", {}, "GET", "/sequences", {"limit": "50", "offset": "0"}),
    ("get_sequence", {"sequence_id": "seq_abc123"}, "GET", "/sequences/seq_abc123", {}),
    ("enroll_subscribers", {"sequence_id": "seq_abc123", "emails": [EMAIL], "target_node_id": "node_1"}, "POST", "/sequences/seq_abc123/enroll", {"emails": [EMAIL], "targetNodeId": "node_1"}),
    ("list_campaigns", {}, "GET", "/campaigns", {"limit": "50", "offset": "0"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,payload", CASES)
async def test_all_operations_one_request_each(transport, operation, config, method, path, payload):
    requests, replies = transport
    body = {"success": True, "processed": 2, "failed": 1,
        "results": [{"email": EMAIL, "success": False, "error": "Suppressed"}]}
    replies.append((200, body))
    result = await node(operation, **config).execute({})
    assert result == {**body, "status": "success", "http_status": 200}
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "api.sequenzy.com"
    assert request.url.raw_path.decode().split("?")[0] == "/api/v1" + path
    assert request.method == method
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in str(result)
    if method == "GET":
        assert dict(request.url.params) == payload and request.content == b""
    elif method == "DELETE":
        assert request.content == b""
    else:
        assert json.loads(request.content) == payload


@pytest.mark.asyncio
async def test_cursor_metadata_and_filters_survive_without_page_conflict(transport):
    requests, replies = transport
    pagination = {"nextCursor": "opaque-next", "hasMore": True}
    replies.append((200, {"success": True, "subscribers": [], "pagination": pagination}))
    result = await node("list_subscribers", cursor="opaque-prev", tags="vip,premium", status="all", list_id="list_1").execute({})
    assert result["pagination"] == pagination
    assert dict(requests[0].url.params) == {"limit": "20", "cursor": "opaque-prev", "tags": "vip,premium", "status": "all", "listId": "list_1"}


@pytest.mark.parametrize("operation,config", [
    ("list_subscribers", {"cursor": "abc", "page": 1}),
    ("list_subscribers", {"limit": 1001}),
    ("get_sequence", {"sequence_id": "../subscribers"}),
    ("get_sequence", {"sequence_id": "a%2Fb"}),
    ("get_subscriber", {"email": "person@example.com/../me"}),
    ("enroll_subscribers", {"sequence_id": "seq_1", "emails": []}),
    ("enroll_subscribers", {"sequence_id": "seq_1", "emails": [EMAIL] * 501}),
    ("create_tag", {"name": "vip", "color": "invalid"}),
])
def test_bad_inputs_fail_before_transport(transport, operation, config):
    with pytest.raises(ValueError):
        node(operation, **config)
    assert transport[0] == []


@pytest.mark.parametrize("key", ["seq_user_some_account_key", "Bearer seq_live_fixture", "https://example.com/key", "bad\nkey"])
def test_credentials_reject_account_keys_headers_and_urls(key):
    with pytest.raises(ValueError):
        native.SequenzyAPIKeyCredential(api_key=key)


def test_credential_cleaning_and_foreign_type():
    assert native.SequenzyAPIKeyCredential(api_key="  seq_live_fixture_key  ").api_key == "seq_live_fixture_key"
    with pytest.raises(ValueError):
        native.SequenzyAPIKeyCredential(api_key=TOKEN, credential_type="other_api_key")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
async def test_error_envelopes_are_failures_with_redacted_provider_message(transport, status):
    requests, replies = transport
    replies.append((status, {"success": False, "error": "Rejected " + TOKEN}))
    result = await node("list_tags").execute({})
    assert result["status"] == "error" and result["success"] is False
    assert result["error"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,expected", [("list_tags", {}, "error"), ("create_tag", {"name": "vip"}, "unknown")])
async def test_transport_failure_does_not_retry_or_claim_write_success(transport, operation, config, expected):
    requests, replies = transport
    replies.append(httpx.ReadTimeout("private transport text " + TOKEN))
    result = await node(operation, **config).execute({})
    assert result["status"] == expected and result["success"] is False
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {}, {"success": "true"}])
async def test_unconfirmed_response_rejected(transport, body):
    transport[1].append((200, body))
    with pytest.raises(ValueError):
        await node("list_tags").execute({})


@pytest.mark.asyncio
async def test_connection_evidence_names_workspace_through_shared_operation(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport[1].append((200, {"success": True, "account": {"companyId": "company_abc123", "companyName": "Acme Inc", "apiKeyType": "company"}}))
    result = await collect_evidence(node_type="automation-sequenzy", credential_data=AUTH, user_id="fixture-user")
    assert result.reachable is True and result.account_label == "Acme Inc"
    assert transport[0][0].url.path == "/api/v1/subscribers/me"


@pytest.mark.asyncio
async def test_saved_credential_uses_shared_admission_and_loader(transport, monkeypatch):
    from nodes.core import run_op
    from utils import credential_approval
    loader = AsyncMock(return_value=AUTH)
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(run_op, "resolve_operation_credential", loader)
    monkeypatch.setattr(credential_approval, "admit_node", admission)
    transport[1].append((200, {"success": True, "tags": []}))
    result = await run_op.run_node_operation(node_type="automation-sequenzy", operation="list_tags", arguments={},
        credential_id="00000000-0000-4000-8000-000000000042", user_id="fixture-user")
    assert result["tags"] == []
    loader.assert_awaited_once()
    admission.assert_awaited_once()
