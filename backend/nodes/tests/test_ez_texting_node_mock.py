"""Exercise EZ Texting through the native runner with offline HTTP fixtures.

The cases pin routes, Basic authentication, JSON bodies, pagination and the
unusual query-array membership writes from the provider's v1 contract.
"""
import json
import httpx
import pytest

from nodes import ez_texting_node as ez
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "ez_texting_basic", "username": "fixture@example.test", "password": "fixture-secret-value"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    seen, replies = [], []
    real_client = httpx.AsyncClient

    async def respond(request):
        seen.append(request)
        assert request.url.scheme == "https" and request.url.host == "a.eztexting.com"
        assert not request.url.userinfo
        assert request.headers["Authorization"] == httpx.BasicAuth(AUTH["username"], AUTH["password"])._auth_header
        code, data = replies.pop(0)
        return httpx.Response(code, content=b"" if data is None else json.dumps(data).encode(), headers={"Content-Type": "application/json"})

    monkeypatch.setattr(ez.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    return seen, replies


CASES = [
    ("list_contacts", {}, "GET", "/v1/contacts", {"content": [{"phoneNumber": "15551234567", "firstName": "Ada"}], "number": 0, "size": 20, "totalPages": 2}),
    ("get_contact", {"phoneNumber": "+15551234567"}, "GET", "/v1/contacts/+15551234567", {"phoneNumber": "+15551234567"}),
    ("upsert_contact", {"phoneNumber": "15551234567", "firstName": "Ada", "groupIdsAdd": ["group-1"]}, "POST", "/v1/contacts", {"id": "15551234567"}),
    ("delete_contact", {"phoneNumber": "15551234567"}, "DELETE", "/v1/contacts/15551234567", None),
    ("list_groups", {}, "GET", "/v1/contact-groups", {"content": []}),
    ("create_group", {"name": "Customers"}, "POST", "/v1/contact-groups", {"id": "group-1"}),
    ("get_group", {"resource_id": "group-1"}, "GET", "/v1/contact-groups/group-1", {"id": "group-1", "name": "Customers"}),
    ("update_group", {"resource_id": "group-1", "name": "Leads"}, "PUT", "/v1/contact-groups/group-1", None),
    ("delete_group", {"resource_id": "group-1"}, "DELETE", "/v1/contact-groups/group-1", None),
    ("add_group_contacts", {"resource_id": "group-1", "phoneNumbers": ["15551234567", "15557654321"]}, "POST", "/v1/contact-groups/group-1/contacts", ["15551234567"]),
    ("remove_group_contacts", {"resource_id": "group-1", "phoneNumbers": ["15551234567"]}, "DELETE", "/v1/contact-groups/group-1/contacts", ["15551234567"]),
    ("list_messages", {}, "GET", "/v1/messages", {"content": []}),
    ("send_message", {"message": "Hello", "toNumbers": ["15551234567"], "sendAt": "2030-12-03T10:15:30+00:00"}, "POST", "/v1/messages", {"id": "message-1"}),
    ("delete_messages", {"ids": [123]}, "DELETE", "/v1/messages", None),
    ("get_message_details", {"resource_id": "message-1"}, "GET", "/v1/message-details/message-1", {"id": "message-1"}),
    ("get_message_report", {"resource_id": "message-1"}, "GET", "/v1/message-reports/message-1", {"total": 1}),
    ("list_templates", {}, "GET", "/v1/message-templates", {"content": []}),
    ("create_template", {"name": "Greeting", "message": "Hello"}, "POST", "/v1/message-templates", {"id": "template-1"}),
    ("get_template", {"resource_id": "template-1"}, "GET", "/v1/message-templates/template-1", {"id": "template-1", "name": "Greeting", "message": "Hello"}),
    ("update_template", {"resource_id": "template-1", "name": "Greeting", "message": "Hi"}, "PUT", "/v1/message-templates/template-1", None),
    ("delete_template", {"resource_id": "template-1"}, "DELETE", "/v1/message-templates/template-1", None),
    ("get_credit_balance", {}, "GET", "/v1/credits", {"totalCredits": 100}),
    ("list_contact_fields", {}, "GET", "/v1/contact-fields", {"content": []}),
    ("block_numbers", {"phoneNumbers": ["15551234567"]}, "POST", "/v1/blocks", None),
]


async def run(operation, config):
    return await run_node_operation(node_type="automation-ez-texting", operation=operation, arguments=config, user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,payload", CASES)
async def test_ez_texting_operations(transport, operation, config, method, path, payload):
    seen, replies = transport
    replies.append((201 if operation in {"send_message", "create_group", "create_template"} else 200, payload))
    out = await run(operation, config)
    assert out["success"] is True
    assert len(seen) == 1 and seen[0].method == method and seen[0].url.path == path
    request = seen[0]
    if operation.startswith("list_"):
        assert request.url.params["page"] == "0" and request.url.params["size"] == "20"
    if operation in {"add_group_contacts", "remove_group_contacts"}:
        assert request.url.params.get_list("phoneNumbers") == config["phoneNumbers"]
        assert not request.content
    elif method != "GET" and config and operation not in {"delete_contact", "delete_group", "delete_template"}:
        body = json.loads(request.content)
        for key, value in config.items():
            if key != "resource_id":
                assert body[key] == value
        assert "operation" not in body and "resource_id" not in body
    if operation == "send_message":
        assert out["delivery_verified"] is False
        assert json.loads(request.content)["strictValidation"] is True
    if operation == "list_contacts":
        assert out["next_page"] == 1 and out["data"][0]["firstName"] == "Ada"


@pytest.mark.asyncio
async def test_ez_texting_filters_and_page(transport):
    seen, replies = transport
    replies.append((200, {"content": [], "number": 3, "totalPages": 4}))
    out = await run("list_contacts", {"page": 3, "size": "50", "opt_out": False, "email": "person@example.test"})
    assert out["next_page"] is None
    assert dict(seen[0].url.params) == {"page": "3", "size": "50", "filters[optOut][eq]": "false", "filters[email][like]": "person@example.test"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_ez_texting_failures_and_redaction(transport, status):
    seen, replies = transport
    replies.append((status, {"errors": [{"message": "Rejected " + AUTH["password"]}]}))
    out = await run("get_credit_balance", {})
    assert out["success"] is False and out["http_status"] == status
    assert AUTH["password"] not in json.dumps(out)
    assert len(seen) == 1


@pytest.mark.parametrize("model,data", [
    (ez.SendMessage, {"message": "Hello"}),
    (ez.SendMessage, {"toNumbers": ["15551234567"]}),
    (ez.SendMessage, {"message": "Hello", "toNumbers": ["15551234567"], "sendAt": "2030-12-01"}),
    (ez.CreateGroup, {"name": "a" * 26}),
    (ez.UpsertContact, {"phoneNumber": "15551234567", "firstName": "a" * 21}),
    (ez.GetContact, {"phoneNumber": ".."}),
    (ez.GetGroup, {"resource_id": ".."}),
    (ez.AddGroupContacts, {"resource_id": "g1", "phoneNumbers": []}),
])
def test_ez_texting_invalid_inputs(model, data):
    with pytest.raises(ValueError):
        model.model_validate(data)


@pytest.mark.asyncio
async def test_ez_texting_invalid_page_is_not_success(transport):
    _, replies = transport
    replies.append((200, {"unexpected": []}))
    with pytest.raises(ValueError, match="page envelope"):
        await run("list_contacts", {})


def test_ez_texting_credential_can_be_entered_by_hand():
    shaped = ez.EZTextingCredential.model_validate({"username": AUTH["username"], "password": AUTH["password"]})
    assert shaped.credential_type == "ez_texting_basic"
