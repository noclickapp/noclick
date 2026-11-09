"""Salesmsg v2.3 requests and failures. All account values are synthetic.

Contract: https://app.salesmessage.com/api/docs/salesmessage-public-api-v2.3.json
"""
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import salesmsg_node as native
from nodes.core.registry import NodeFactory
from nodes.core.base import ConfigValidationError

TOKEN = "salesmsg-synthetic-personal-token-12345"
CREDENTIAL = {"credential_type": native.CREDENTIAL_TYPE, "access_token": TOKEN}
CASES = [
    ({"operation": "get_current_user"}, "GET", "/users/me", {}),
    ({"operation": "list_contacts", "search": "Ada"}, "GET", "/contacts", {"search": "Ada", "length": "10", "page": "1"}),
    ({"operation": "get_contact", "contact_id": 123}, "GET", "/contacts/123", {}),
    ({"operation": "create_contact", "number": "+12025550018", "first_name": "Ada"}, "POST", "/contacts", {"number": "+12025550018", "first_name": "Ada"}),
    ({"operation": "update_contact", "contact_id": 123, "first_name": "Grace"}, "PUT", "/contacts/123", {"first_name": "Grace"}),
    ({"operation": "delete_contact", "contact_id": 123}, "DELETE", "/contacts/123", {}),
    ({"operation": "search_contacts", "term": "Ada"}, "GET", "/contacts/search", {"term": "Ada", "limit": "50"}),
    ({"operation": "create_contact_note", "contact_id": 123, "text": "Follow up tomorrow"}, "POST", "/contacts/note/123/create", {"text": "Follow up tomorrow"}),
    ({"operation": "list_tags", "page": 2}, "GET", "/tags", {"page": "2", "length": "10"}),
    ({"operation": "get_tag", "tag_id": 7}, "GET", "/tags/7", {}),
    ({"operation": "create_tag", "label": "New lead"}, "POST", "/tags", {"label": "New lead"}),
    ({"operation": "update_tag", "tag_id": 7, "label": "Qualified"}, "PUT", "/tags/7", {"label": "Qualified"}),
    ({"operation": "add_contact_tag", "contact_id": 123, "tag_id": 7}, "PUT", "/tags/contact/123/7", {}),
    ({"operation": "remove_contact_tag", "contact_id": 123, "tag_id": 7}, "DELETE", "/tags/contact/123/7", {}),
    ({"operation": "list_inboxes", "has_membership": False}, "GET", "/teams", {"limit": "50", "has_membership": "false"}),
    ({"operation": "get_inbox", "team_id": 5}, "GET", "/teams/5", {}),
    ({"operation": "list_conversations", "offset": 20}, "GET", "/conversations", {"filter": "open", "limit": "10", "offset": "20"}),
    ({"operation": "get_conversation", "conversation_id": 456}, "GET", "/conversations/456", {}),
    ({"operation": "close_conversation", "conversation_id": 456}, "PUT", "/conversations/456/close", {}),
    ({"operation": "open_conversation", "conversation_id": 456}, "PUT", "/conversations/456/open", {}),
    ({"operation": "list_messages", "conversation_id": 456, "page": 3, "only_scheduled": False}, "GET", "/messages/456/paginated", {"per_page": "15", "page": "3", "only_scheduled": "false"}),
    ({"operation": "send_sms", "number": "+12025550018", "team_id": 5, "message": "Hello + welcome & thanks"}, "POST", "/messages", {"number": "+12025550018", "team_id": "5", "message": "Hello + welcome & thanks"}),
    ({"operation": "send_conversation_sms", "conversation_id": 456, "message": "Hello", "enable_quiet_hours": True}, "POST", "/messages/456", {"message": "Hello", "enable_quiet_hours": "true"}),
]

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="salesmsg-test", node_type="automation-salesmsg",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,payload", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_salesmsg_exact_request_and_response(monkeypatch, config, method, path, payload):
    body = {"id": 123, "status": "queued", "new_provider_field": {"preserved": True}}
    requests = transport(monkeypatch, body)
    assert await node(config).execute({}) == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.salesmessage.com"
    assert request.url.path == "/pub/v2.3" + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if config["operation"] == "update_contact":
        assert json.loads(request.content) == payload
        assert not request.url.query
    else:
        assert dict(request.url.params) == payload
        assert request.content == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], [{"id": 1}], {"data": [{"id": 1}], "meta": {"current_page": 3, "last_page": 4, "total": 50}}])
async def test_salesmsg_list_preserves_records_and_pagination(monkeypatch, body):
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_messages", "conversation_id": 456, "page": 3}).execute({})
    assert result == (body if isinstance(body, dict) else {"data": body})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_salesmsg_connection_evidence(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, {"data": [{"id": 7, "label": "Qualified"}]})
    result = await collect_evidence(node_type="automation-salesmsg", user_id="salesmsg-test", credential_data=CREDENTIAL)
    assert result.reachable is True
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == "/pub/v2.3/tags"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 404, 422, 429, 500])
async def test_salesmsg_rejection_no_retry_and_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "send_sms", "number": "+12025550018", "team_id": 1, "message": "Hello"}).execute({})
    assert TOKEN not in str(exc.value) and str(status) in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": "Invalid token"}, {"errors": {"number": ["Invalid"]}}, {"success": False, "message": "Failed"}, "not a resource"])
async def test_salesmsg_rejects_error_envelopes_and_bad_shapes(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_tags"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../contacts"},
    {"operation": "get_inbox", "team_id": 0},
    {"operation": "send_sms", "team_id": 1, "number": "+12025550018"},
    {"operation": "create_tag", "label": "x" * 51},
    {"operation": "list_tags", "length": 101},
])
def test_salesmsg_invalid_config(config):
    with pytest.raises(ConfigValidationError):
        node(config)


def test_salesmsg_manual_credential_defaults_and_secret_shaping():
    credential = native.SalesmsgPersonalAccessToken(access_token="  " + TOKEN + "  ")
    assert credential.credential_type == native.CREDENTIAL_TYPE and credential.access_token == TOKEN
    assert TOKEN not in repr(credential)
    with pytest.raises(ValidationError):
        native.SalesmsgPersonalAccessToken(access_token="Bearer " + TOKEN)
