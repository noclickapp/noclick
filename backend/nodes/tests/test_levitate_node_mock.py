"""Synthetic contract-shaped executions through the real node factory."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import levitate_node as native
from nodes.core.registry import NodeFactory

KEY = "levitate-synthetic-test-key"
CASES = json.loads((Path(__file__).parent / "fixtures/levitate/contract_cases.json").read_text())["operations"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="levitate-test", node_type="automation-levitate", node_data={
        "config": config, "credentials": {"credential_type": "levitate_api_key", "api_key": KEY}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_endpoint_contract(monkeypatch, operation):
    case = CASES[operation]
    requests = transport(monkeypatch, case["response"], case["status"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url).split("?")[0] == native.BASE + case["path"]
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert dict(request.url.params) == {k: str(v) for k, v in case["query"].items()}
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert result.get("write_acknowledged", False) == (case["method"] != "GET" and operation != "search_contacts")
    if operation.startswith("list_") or operation == "search_contacts":
        assert result["next_page_token"] == "next-page"
        assert result["items"] == case["response"]["value"]["values"]
    elif case["method"] != "DELETE":
        assert result["data"] == case["response"]["value"]


@pytest.mark.asyncio
async def test_repeatable_tags_cursor_and_empty_page(monkeypatch):
    requests = transport(monkeypatch, {"success": True, "value": {"values": [], "pageToken": None}})
    result = await node({"operation": "list_contacts", "tags": ["Customer", "Gold"], "limit": 10, "pageToken": "previous"}).execute({})
    assert requests[0].url.params.get_list("tags") == ["Customer", "Gold"]
    assert requests[0].url.params["pageToken"] == "previous"
    assert result["items"] == [] and not result["has_more"]


@pytest.mark.asyncio
async def test_update_omission_and_array_replacement(monkeypatch):
    requests = transport(monkeypatch, {"success": True, "value": {"id": "contact-1"}})
    await node({"operation": "update_contact", "contact_id": "contact-1", "tags": [], "customFields": {}}).execute({})
    assert json.loads(requests[0].content) == {"tags": [], "customFields": {}}
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_contact", "contact_id": "contact-1"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 409, 429, 500])
async def test_provider_rejection_redacts_secret_without_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"success": False, "systemMessage": "Rejected " + KEY}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_contacts"}).execute({})
    assert "Rejected [redacted]" in str(exc.value) and KEY not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{}, {"success": False}, {"success": True}, {"success": True, "value": []}])
async def test_error_or_malformed_envelopes(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "get_contact", "contact_id": "contact-1"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [42, "", "previous"])
async def test_invalid_or_repeated_cursor(monkeypatch, token):
    transport(monkeypatch, {"success": True, "value": {"values": [], "pageToken": token}})
    with pytest.raises(ValueError, match="cursor"):
        await node({"operation": "list_contacts", "pageToken": "previous"}).execute({})


@pytest.mark.parametrize("key", ["https://example.com", "<token>", "Bearer secret", "bad\nheader", "nonascii-ä"])
def test_invalid_keys(key):
    with pytest.raises(ValidationError):
        native.LevitateAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("config", [
    {"operation": "create_contact"},
    {"operation": "create_company", "name": ""},
    {"operation": "create_note", "body": "hello", "references": []},
    {"operation": "add_contact_key_fact", "contact_id": "contact-1", "type": "Birthday"},
    {"operation": "add_contact_key_fact", "contact_id": "contact-1", "type": "Birthday", "date": {"month": 2, "day": 30}},
    {"operation": "search_contacts", "filter": {"field": "name", "operator": "equals", "value": "Ada"}},
    {"operation": "get_company", "company_id": "../../contacts"},
    {"operation": "update_contact", "contact_id": "contact-1", "company": "company-1"},
])
def test_invalid_write_or_path_shapes(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_type_default():
    assert native.LevitateAPIKeyCredential(api_key=KEY).credential_type == "levitate_api_key"


@pytest.mark.asyncio
async def test_success_output_redacts_secret(monkeypatch):
    transport(monkeypatch, {"success": True, "value": {"id": "note-1", "body": KEY}})
    result = await node({"operation": "get_note", "note_id": "note-1"}).execute({})
    assert KEY not in json.dumps(result)
