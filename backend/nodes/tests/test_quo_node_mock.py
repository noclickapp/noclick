"""Offline Quo tests using verbatim rendered provider responses.

Fixtures retain source URLs from https://www.quo.com/docs/mdx/api-reference/.
Example requests use the values on those same pages. No provider account needed.
"""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.quo_node import QuoNode, QuoNodeConfig

FIXTURES = Path(__file__).parent / "fixtures/quo"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
INPUTS = json.loads((FIXTURES / "inputs.json").read_text())
KEY = "quo-test-secret-key"
CASES = [
    ("send_message", "POST", "/v1/messages", 202),
    ("list_messages", "GET", "/v1/messages", 200),
    ("get_message", "GET", "/v1/messages/AC123abc", 200),
    ("list_contacts", "GET", "/v1/contacts", 200),
    ("get_contact", "GET", "/v1/contacts/66d0d87e8dc1211467372303", 200),
    ("create_contact", "POST", "/v1/contacts", 201),
    ("update_contact", "PATCH", "/v1/contacts/66d0d87e8dc1211467372303", 200),
    ("delete_contact", "DELETE", "/v1/contacts/66d0d87e8dc1211467372303", 204),
    ("list_contact_custom_fields", "GET", "/v1/contact-custom-fields", 200),
    ("list_calls", "GET", "/v1/calls", 200),
    ("get_call", "GET", "/v1/calls/AC3700e624eca547eb9f749a06f2eb1", 200),
    (
        "get_call_recordings",
        "GET",
        "/v1/call-recordings/AC3700e624eca547eb9f749a06f",
        200,
    ),
    (
        "get_call_transcript",
        "GET",
        "/v1/call-transcripts/AC3700e624eca547eb9f749a06f2eb1",
        200,
    ),
    ("get_call_summary", "GET", "/v1/call-summaries/AC3700e624eca547eb9f749a06f", 200),
    (
        "get_call_voicemail",
        "GET",
        "/v1/call-voicemails/AC3700e624eca547eb9f749a06f",
        200,
    ),
    ("list_conversations", "GET", "/v1/conversations", 200),
    ("list_phone_numbers", "GET", "/v1/phone-numbers", 200),
    ("get_phone_number", "GET", "/v1/phone-numbers/PNlja6rrtI", 200),
    ("list_users", "GET", "/v1/users", 200),
]


def node(config):
    return QuoNode(
        node_id="quo-test",
        node_type="automation-quo",
        node_data={},
        config=QuoNodeConfig(config=config, credentials={"api_key": KEY}),
        sio=Mock(),
        sid="test",
        workflow_id="test",
    )


async def run(monkeypatch, config, body, status=200):
    requests = []
    original = httpx.AsyncClient

    def transport(request):
        requests.append(request)
        return (
            httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
        )

    monkeypatch.setattr(
        "nodes.quo_node.httpx.AsyncClient",
        lambda *a, **kw: original(transport=httpx.MockTransport(transport)),
    )
    result = await node(config).execute({})
    return result, requests


def documented_response(operation):
    # The per-operation source page includes these exact JSON response bodies.
    slug = INPUTS[operation]["source"]
    return next(
        entry["body"] for entry in RESPONSES.values() if entry["source"] == slug
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,method,path,status", CASES, ids=[c[0] for c in CASES]
)
async def test_documented_operation(monkeypatch, operation, method, path, status):
    body = None if status == 204 else documented_response(operation)
    result, requests = await run(monkeypatch, INPUTS[operation]["config"], body, status)
    (request,) = requests
    assert (request.method, request.url.host, request.url.path) == (
        method,
        "api.quo.com",
        path,
    )
    assert (
        request.headers["Authorization"] == KEY
    )  # Quo explicitly forbids adding Bearer.
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["status_code"] == status
    assert result["data"] == ({"deleted": True} if status == 204 else body["data"])
    assert result["timing_ms"]["api_request"] >= 0
    if body:
        for key in ("totalItems", "nextPageToken"):
            if key in body:
                assert result[key] == body[key]
    if operation in ("list_calls", "list_messages"):
        assert dict(request.url.params) == {
            "phoneNumberId": "PN123abc",
            "participants": "+15555555555",
            "maxResults": "10",
        }
    if operation == "send_message":
        assert json.loads(request.content) == {
            "content": "Hello, world!",
            "from": "+15555555555",
            "to": ["+15555555555"],
            "userId": "US123abc",
            "setInboxStatus": "done",
        }
    if operation == "create_contact":
        assert json.loads(request.content) == {
            "defaultFields": {
                "firstName": "John",
                "lastName": "Doe",
                "company": "Quo",
                "emails": [{"name": "company email", "value": "abc@example.com"}],
                "phoneNumbers": [{"name": "company phone", "value": "+12345678901"}],
            },
            "externalId": "664d0db69fcac7cf2e6ec",
            "source": "public-api",
        }
    if operation == "update_contact":
        assert json.loads(request.content) == {
            "defaultFields": {
                "firstName": "John",
                "lastName": "Doe",
                "company": "Quo",
                "emails": [
                    {
                        "name": "company email",
                        "value": "info@openphone.com",
                        "id": "acb123",
                    }
                ],
                "phoneNumbers": [
                    {"name": "company phone", "value": "+15555555555", "id": "acb123"}
                ],
            },
            "externalId": "664d0db69fcac7cf2e6ec",
            "source": "public-api",
            "customFields": [{"key": "inbound-lead", "value": "123 Main St"}],
        }


@pytest.mark.asyncio
async def test_repeated_query_keys_and_pagination(monkeypatch):
    config = {
        **INPUTS["list_messages"]["config"],
        "participants": "+15555555555, +15555555556",
        "page_token": "next-page",
        "max_results": 25,
    }
    body = {**documented_response("list_messages"), "nextPageToken": "following-page"}
    result, requests = await run(monkeypatch, config, body)
    assert requests[0].url.params.get_list("participants") == [
        "+15555555555",
        "+15555555556",
    ]
    assert requests[0].url.params["pageToken"] == "next-page"
    assert requests[0].url.params["maxResults"] == "25"
    assert "participants[]" not in requests[0].url.params
    assert result["nextPageToken"] == "following-page"


@pytest.mark.asyncio
async def test_contact_crm_filters(monkeypatch):
    _, requests = await run(
        monkeypatch,
        {
            "operation": "list_contacts",
            "external_ids": "crm-1, crm-2",
            "sources": "public-api",
            "page_token": "next-page",
        },
        documented_response("list_contacts"),
    )
    assert requests[0].url.params.get_list("externalIds") == ["crm-1", "crm-2"]
    assert requests[0].url.params.get_list("sources") == ["public-api"]


@pytest.mark.asyncio
async def test_conversation_filters_preserve_false(monkeypatch):
    _, requests = await run(
        monkeypatch,
        {
            "operation": "list_conversations",
            "phone_numbers": "PN123abc,+15555555555",
            "exclude_inactive": False,
            "updated_after": "2022-01-01T00:00:00Z",
        },
        documented_response("list_conversations"),
    )
    assert requests[0].url.params.get_list("phoneNumbers") == [
        "PN123abc",
        "+15555555555",
    ]
    assert requests[0].url.params["excludeInactive"] == "false"
    assert requests[0].url.params["updatedAfter"] == "2022-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_contact_clear_lists_and_null_values(monkeypatch):
    _, requests = await run(
        monkeypatch,
        {
            "operation": "update_contact",
            "contact_id": "contact",
            "emails_json": "[]",
            "phone_numbers_json": '[{"name":"work","value":null}]',
            "custom_fields_json": '[{"key":"inbound-lead","value":false}]',
        },
        documented_response("update_contact"),
    )
    assert json.loads(requests[0].content) == {
        "defaultFields": {
            "emails": [],
            "phoneNumbers": [{"name": "work", "value": None}],
        },
        "customFields": [{"key": "inbound-lead", "value": False}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body",
    [
        (401, {"error": {"message": "Invalid API key", "key": "Unauthorized"}}),
        (429, {"message": "Rate limit exceeded"}),
        (403, {"message": f"Rejected {KEY}"}),
    ],
)
async def test_provider_rejection_no_retries_or_secret_leak(monkeypatch, status, body):
    result, requests = await run(
        monkeypatch, {"operation": "list_phone_numbers"}, body, status
    )
    assert len(requests) == 1
    assert result["status"] == "error"
    assert result["status_code"] == status
    assert KEY not in json.dumps(result)
    if status == 401:
        assert result["error"] == "Invalid API key"


@pytest.mark.asyncio
async def test_processing_voicemail_retains_nulls(monkeypatch):
    result, _ = await run(
        monkeypatch, INPUTS["get_call_voicemail"]["config"], {"data": None}
    )
    assert result["status"] == "success" and result["data"] is None


@pytest.mark.asyncio
async def test_missing_envelope_is_not_success(monkeypatch):
    result, _ = await run(monkeypatch, {"operation": "list_phone_numbers"}, {})
    assert result["status"] == "error"


@pytest.mark.parametrize(
    "field,value",
    [
        ("emails_json", "{}"),
        ("phone_numbers_json", '[{"value":"123"}]'),
        ("custom_fields_json", "not json"),
    ],
)
def test_invalid_contact_json_rejected(field, value):
    with pytest.raises(ValidationError):
        node({"operation": "create_contact", "first_name": "John", field: value})


@pytest.mark.asyncio
async def test_calls_refuse_multiple_participants(monkeypatch):
    with pytest.raises(ValueError, match="between 1 and 1"):
        await run(
            monkeypatch,
            {
                **INPUTS["list_calls"]["config"],
                "participants": "+15555555555,+15555555556",
            },
            {},
        )


def test_fixture_coverage_matches_all_schema_operations():
    schema = QuoNode.get_config_schema()
    configs = [
        d for d in schema["$defs"].values() if "operation" in d.get("properties", {})
    ]
    assert (
        {d["properties"]["operation"]["const"] for d in configs}
        == set(INPUTS)
        == {c[0] for c in CASES}
    )
    assert QuoNode.connection_evidence.operation == "list_phone_numbers"


@pytest.mark.asyncio
async def test_empty_participants_never_issue_a_request(monkeypatch):
    with pytest.raises(ValueError, match="nonempty"):
        await run(
            monkeypatch,
            {**INPUTS["list_messages"]["config"], "participants": " , "},
            {},
        )


@pytest.mark.asyncio
async def test_timeout_and_missing_credentials(monkeypatch):
    original = httpx.AsyncClient

    def timeout(request):
        raise httpx.ReadTimeout("sensitive details", request=request)

    monkeypatch.setattr(
        "nodes.quo_node.httpx.AsyncClient",
        lambda *a, **kw: original(transport=httpx.MockTransport(timeout)),
    )
    result = await node({"operation": "list_phone_numbers"}).execute({})
    assert result["status"] == "error" and result["status_code"] == 408
    assert "sensitive" not in json.dumps(result)
    disconnected = node({"operation": "list_phone_numbers"})
    disconnected.config.credentials = None
    with pytest.raises(ValueError, match="Connect a Quo API key"):
        await disconnected.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401])
async def test_connect_evidence_executes_the_registered_read(monkeypatch, status):
    from nodes.core.connection_evidence import collect_evidence

    original = httpx.AsyncClient
    requests = []
    body = (
        documented_response("list_phone_numbers")
        if status == 200
        else {"error": {"message": "Invalid API key", "key": "Unauthorized"}}
    )

    def transport(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        "nodes.quo_node.httpx.AsyncClient",
        lambda *a, **kw: original(transport=httpx.MockTransport(transport)),
    )
    result = await collect_evidence(
        node_type="automation-quo",
        user_id="test",
        credential_data={"credential_type": "quo_api_key", "api_key": KEY},
    )
    assert len(requests) == 1 and requests[0].url.path == "/v1/phone-numbers"
    assert requests[0].method == "GET"
    assert result.reachable is (status == 200)
    if status == 200:
        assert result.samples
        assert result.samples[0].label == body["data"][0]["name"]
    else:
        assert not result.samples
