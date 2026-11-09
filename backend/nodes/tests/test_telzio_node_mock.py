"""Native-factory tests: form encoding, paging, account evidence and failures.

Responses are synthetic shapes based on Telzio's published v3 contract.
No credentials or calls to the live service are used.
"""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import telzio_node as native
from nodes.core.connection_evidence import _rows_from_operation
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-telzio-token-92741"
CONTACT = "e6fd17d9-18dc-42d9-aea9-c2e5a97d26a2"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config, credentials=None):
    return NodeFactory.create_node(
        node_id="telzio-test", node_type="automation-telzio",
        node_data={"config": config, "credentials": credentials or {"credential_type": "telzio_token", "token": TOKEN}},
    )


def mock_api(monkeypatch, body=None, status=200, *, text=None, failure=False):
    requests = []

    def reply(request):
        requests.append(request)
        if failure:
            raise httpx.ReadTimeout("synthetic transport interruption", request=request)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_account_evidence_and_native_user_pagination(monkeypatch):
    payload = json.loads((Path(__file__).parent / "fixtures/telzio/users.json").read_text())
    requests = mock_api(monkeypatch, payload)
    result = await make_node({"operation": "list_users", "term": "Peter + Griffin", "limit": 20, "starting_page_id": "opaque/next+page="}).execute({})
    request = requests[0]
    assert request.method == "GET" and request.url.host == "api.telzio.com" and request.url.path == "/v3/users"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == {"limit": "20", "starting_page_id": "opaque/next+page=", "term": "Peter + Griffin"}
    assert result["data"] == payload
    rows = _rows_from_operation(result)
    assert rows[0]["username"] == "pgriffin"
    assert native.TelzioNode.connection_evidence.proves == "account"
    assert native.TelzioNode.connection_evidence.operation == "list_users"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path,expected", [
    ("create_sms_conversation", {"number_id": "num_rodkRqeyP2GW", "recipient": "+15551234567", "text": "Hi + café & friends"}, "/v3/conversations/sms/create-conversation", {"number_id": ["num_rodkRqeyP2GW"], "recipient": ["+15551234567"], "text": ["Hi + café & friends"]}),
    ("send_sms", {"conversation_id": "cnv_vaKDxpO1DB4G", "text": "Hello + again"}, "/v3/conversations/cnv_vaKDxpO1DB4G/sms", {"text": ["Hello + again"]}),
    ("create_contact", {"contact_name": "Customer & Co", "organization_id": CONTACT}, "/v3/phonebook/contacts", {"contact_name": ["Customer & Co"], "organization_id": [CONTACT]}),
    ("update_contact", {"contact_id": CONTACT, "contact_name": "Renamed contact"}, "/v3/phonebook/contacts/" + CONTACT, {"contact_name": ["Renamed contact"]}),
    ("create_comment", {"item_id": "vm_y2MkJJQnkBoW", "text": "Please follow up"}, "/v3/comments/vm_y2MkJJQnkBoW", {"text": ["Please follow up"]}),
    ("update_voicemail", {"voicemail_id": "vm_y2MkJJQnkBoW", "status": "listened"}, "/v3/voicemails/vm_y2MkJJQnkBoW", {"status": ["listened"]}),
    ("create_tag", {"name": "Follow up"}, "/v3/tags", {"name": ["Follow up"]}),
])
async def test_writes_are_single_form_encoded_contract_requests(monkeypatch, operation, config, path, expected):
    requests = mock_api(monkeypatch, {"acknowledged": True})
    result = await make_node({"operation": operation, **config}).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == "POST" and request.url.path == path
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert parse_qs(request.content.decode()) == expected
    assert not request.url.query


@pytest.mark.asyncio
async def test_delete_contact_accepts_documented_empty_200(monkeypatch):
    requests = mock_api(monkeypatch, text="")
    result = await make_node({"operation": "delete_contact", "contact_id": CONTACT}).execute({})
    assert result["status"] == "success"
    assert requests[0].method == "DELETE" and requests[0].content == b""
    assert result["data"]["deleted_contact_id"] == CONTACT


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,cursor", [("list_recent_calls", 45), ("list_conversations", 1234567890123), ("list_comments", "com_Q3Kkj9nePeqd"), ("list_recordings", "rec_JEbPBZn7PYrV"), ("list_voicemails", "vm_JEbPBVzKEPYr"), ("list_tags", "tag_rodkR9gnP2GW")])
async def test_one_page_preserves_more_and_never_follows_automatically(monkeypatch, operation, cursor):
    payload = {"data": [], "has_more": True}
    if operation == "list_conversations":
        payload["next_starting_after"] = 9999999999999
    requests = mock_api(monkeypatch, payload)
    result = await make_node({"operation": operation, "starting_after": cursor, **({"item_id": "vm_y2MkJJQnkBoW"} if operation == "list_comments" else {})}).execute({})
    assert result["data"] == payload and len(requests) == 1
    assert requests[0].url.params["starting_after"] == str(cursor)


@pytest.mark.asyncio
async def test_nullable_list_data_preserved(monkeypatch):
    mock_api(monkeypatch, {"data": None, "has_more": False})
    result = await make_node({"operation": "list_users"}).execute({})
    assert result["status"] == "success" and result["data"]["data"] is None


@pytest.mark.asyncio
async def test_user_query_is_encoded_as_one_path_segment(monkeypatch):
    requests = mock_api(monkeypatch, {"username": "a+b"})
    await make_node({"operation": "get_user", "query": "a+b"}).execute({})
    assert requests[0].url.raw_path == b"/v3/users/a%2Bb"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_provider_error_preserved_and_token_redacted_without_retry(monkeypatch, status):
    requests = mock_api(monkeypatch, status=status, text="Provider rejected: " + TOKEN)
    result = await make_node({"operation": "list_users"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["message"] == "Provider rejected: [redacted]" and len(requests) == 1
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], "html", {"errors": ["bad"]}, {"data": "unexpected list"}])
async def test_invalid_read_response_has_no_success(monkeypatch, body):
    mock_api(monkeypatch, body)
    assert (await make_node({"operation": "list_users"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_write_timeout_and_bad_json_do_not_claim_success_or_retry(monkeypatch):
    requests = mock_api(monkeypatch, failure=True)
    config = {"operation": "send_sms", "conversation_id": "cnv_vaKDxpO1DB4G", "text": "hello"}
    result = await make_node(config).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unknown" and len(requests) == 1
    requests = mock_api(monkeypatch, text="unexpected response")
    result = await make_node(config).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unknown" and len(requests) == 1


@pytest.mark.parametrize("token", ["Bearer abc", "https://example.test/key", "<token>", "has whitespace", "curly‘quote"])
def test_manual_token_rejects_invalid_pastes(token):
    with pytest.raises(ValidationError):
        native.TelzioTokenCredential(token=token)


def test_manual_credential_type_defaults_and_token_is_trimmed():
    parsed = native.TelzioTokenCredential(token="  " + TOKEN + "\n")
    assert parsed.credential_type == "telzio_token" and parsed.token == TOKEN


@pytest.mark.parametrize("operation,fields", [
    ("get_call", {"call_id": "../recent"}), ("get_call", {"call_id": "recent"}),
    ("get_user", {"query": "groups"}), ("get_user", {"query": "evil?x=y"}),
    ("get_contact", {"contact_id": "invalid-uuid"}),
    ("send_sms", {"conversation_id": "cnv_ok", "text": "x" * 2049}),
    ("list_users", {"limit": 501}),
])
def test_invalid_config_cannot_reach_transport(operation, fields):
    with pytest.raises(ValueError):
        make_node({"operation": operation, **fields})
