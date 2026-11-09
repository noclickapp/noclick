"""Exercise real Tidio operations with HTTP-only stubs, never live accounts."""
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import tidio_node as tidio
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "tidio_api_key", "client_id": "ci_fixture", "client_secret": "cs_fixture"}
CONTACT = "a1b4ca4c-1108-4432-b256-1e4cf2bf6f9e"
OPERATOR = "b4c3717a-d45b-4c08-ab2a-f0d38bdc0caf"
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    async def send(request):
        requests.append(request)
        code, payload = replies.pop(0)
        return httpx.Response(code, **({"content": b""} if code == 204 else {"json": payload}))

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as session:
            yield session

    monkeypatch.setattr(tidio, "guarded_async_client", client)
    return requests, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type="automation-tidio", operation=operation, arguments=arguments,
                                    credential_data=AUTH, user_id=USER)


# Values follow the pinned provider examples. Every exposed route is covered.
CASES = [
    ("get_project", {}, "GET", "/project", None, 200, {"project_id": 123, "status": "online"}),
    ("list_contacts", {"email": "user@tidio.com", "cursor": "next=="}, "GET", "/contacts", None, 200, {"contacts": [], "meta": {"cursor": "next==", "limit": 1000}}),
    ("create_contact", {"distinct_id": "123456", "first_name": "John"}, "POST", "/contacts", {"distinct_id": "123456", "first_name": "John"}, 201, {"id": CONTACT}),
    ("get_contact", {"contact_id": CONTACT}, "GET", f"/contacts/{CONTACT}", None, 200, {"id": CONTACT, "first_name": "John"}),
    ("update_contact", {"contact_id": CONTACT, "properties": [{"name": "shoe_size", "value": None}]}, "PATCH", f"/contacts/{CONTACT}", {"properties": [{"name": "shoe_size", "value": None}]}, 204, None),
    ("delete_contact", {"contact_id": CONTACT}, "DELETE", f"/contacts/{CONTACT}", None, 204, None),
    ("list_viewed_pages", {"contact_id": CONTACT}, "GET", f"/contacts/{CONTACT}/viewed-pages", None, 200, {"viewed_pages": [], "meta": {"cursor": None}}),
    ("send_contact_message", {"contact_id": CONTACT, "message": "Hi, I need help with my order #2341."}, "POST", f"/contacts/{CONTACT}/messages", {"message": "Hi, I need help with my order #2341."}, 202, {"status": "accepted"}),
    ("list_contact_messages", {"contact_id": CONTACT}, "GET", f"/contacts/{CONTACT}/messages", None, 200, {"messages": [], "conversation_url": None, "meta": {"cursor": None}}),
    ("list_contact_properties", {}, "GET", "/contact-properties", None, 200, {"properties": [], "meta": {"cursor": None}}),
    ("list_operators", {}, "GET", "/operators", None, 200, {"operators": [], "meta": {"cursor": None}}),
    ("create_ticket", {"contact_email": "user@tidio.com", "subject": "Question about delivery", "message_content": "Is it possible to ship the product to the USA?", "tag_ids": [1, 2]}, "POST", "/tickets/as-contact", {"contact_email": "user@tidio.com", "subject": "Question about delivery", "message_content": "Is it possible to ship the product to the USA?", "tag_ids": [1, 2]}, 201, {"id": 10000}),
    ("list_tickets", {}, "GET", "/tickets", None, 200, {"tickets": [], "meta": {"cursor": None}}),
    ("list_ticket_tags", {}, "GET", "/tickets/tags", None, 200, [{"id": 1, "name": "billing"}]),
    ("list_ticket_custom_fields", {}, "GET", "/tickets/custom-fields", None, 200, [{"id": "01HF8N4A2B3C4D5E6F7G8H9J0K", "name": "Priority reason", "type": "text", "is_required": False}]),
    ("get_ticket", {"ticket_id": 10000}, "GET", "/tickets/10000", None, 200, {"id": 10000, "status": "open"}),
    ("update_ticket", {"ticket_id": 10000, "priority": "urgent", "tag_ids": [], "assigned": None, "custom_fields": [{"id": "01HF8N4A2B3C4D5E6F7G8H9J0K", "value": None}]}, "PATCH", "/tickets/10000", {"priority": "urgent", "tag_ids": [], "assigned": None, "custom_fields": [{"id": "01HF8N4A2B3C4D5E6F7G8H9J0K", "value": None}]}, 204, None),
    ("delete_ticket", {"ticket_id": 10000}, "DELETE", "/tickets/10000", None, 204, None),
    ("reply_ticket", {"ticket_id": 10000, "author_type": "operator", "content": "message from operator", "operator_id": OPERATOR, "message_type": "public"}, "POST", "/tickets/10000/reply", {"author_type": "operator", "content": "message from operator", "operator_id": OPERATOR, "message_type": "public"}, 201, {"id": "01H6XZJ88T5PMRRQC3C54WY1EJ"}),
    ("list_departments", {}, "GET", "/departments", None, 200, {"departments": []}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,method,path,body,code,payload", CASES)
async def test_tidio_contract_routes(transport, op, args, method, path, body, code, payload):
    requests, replies = transport
    replies.append((code, payload))
    result = await run(op, **args)
    assert result == {"status": "success", "status_code": code, "data": payload}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.tidio.com"
    assert request.headers["X-Tidio-Openapi-Client-Id"] == AUTH["client_id"]
    assert request.headers["X-Tidio-Openapi-Client-Secret"] == AUTH["client_secret"]
    assert request.headers["Accept"] == tidio.MEDIA_TYPE
    if body is not None:
        assert request.headers["Content-Type"] == tidio.MEDIA_TYPE
        assert json.loads(request.content) == body
    else:
        assert not request.content
    if op == "list_contacts":
        assert dict(request.url.params) == {"email": "user@tidio.com", "cursor": "next=="}
    assert AUTH["client_secret"] not in str(request.url) + json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_tidio_rejections_are_not_success_and_do_not_retry(transport, status):
    requests, replies = transport
    replies.append((status, {"errors": [{"message": "Key rejected cs_fixture"}]}))
    with pytest.raises(ValueError, match="Key rejected \\[redacted\\]"):
        await run("get_project")
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args", [
    ("get_contact", {"contact_id": "../operators"}),
    ("delete_ticket", {"ticket_id": 0}),
    ("create_contact", {"distinct_id": "123456"}),
    ("reply_ticket", {"ticket_id": 10000, "author_type": "operator", "content": "Hello"}),
    ("send_contact_message", {"contact_id": CONTACT, "message": "x" * 5001}),
    ("update_contact", {"contact_id": CONTACT}),
    ("update_ticket", {"ticket_id": 10000}),
])
async def test_tidio_invalid_inputs_never_send(transport, op, args):
    with pytest.raises((ValueError, ValidationError)):
        await run(op, **args)
    assert not transport[0]


def test_tidio_manual_credential_defaults():
    credential = tidio.TidioAPIKeyCredential(client_id="ci_fixture", client_secret="cs_fixture")
    assert credential.credential_type == "tidio_api_key"
    assert set(tidio.TidioAPIKeyCredential.model_json_schema()["required"]) == {"client_id", "client_secret"}


@pytest.mark.parametrize("value", ["https://api.tidio.com", "key\r\nheader", " key with spaces "])
def test_tidio_credential_rejects_url_and_header_injection(value):
    with pytest.raises(ValueError):
        tidio.TidioAPIKeyCredential(client_id=value, client_secret="cs_fixture")


@pytest.mark.asyncio
async def test_tidio_evidence_names_authenticated_project(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport[1].append((200, {"project_id": 123, "status": "online"}))
    evidence = await collect_evidence(node_type="automation-tidio", credential_data=AUTH, user_id=USER)
    assert evidence.reachable is True
    assert evidence.account_label == "123"
    assert transport[0][0].url.path == "/project"
