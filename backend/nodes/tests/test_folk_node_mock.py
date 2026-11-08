"""Real factory executions against the provider's published example responses."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import folk_node as native
from nodes.core.registry import NodeFactory

KEY = "folk-synthetic-test-api-key"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/folk/contract_examples.json").read_text())["operations"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="folk-fixture", node_type="automation-folk", node_data={
        "config": config, "credentials": {"credential_type": "folk_api_key", "api_key": KEY}})


def transport(monkeypatch, response, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_documented_operation_contract(monkeypatch, operation):
    case = EXAMPLES[operation]
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == case["response"]["data"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url).split("?")[0] == native.BASE + case["path"]
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert request.headers["X-API-Version"] == "2025-06-09"
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"limit": "20"}
        assert result["next_cursor"] == "eyJvZmZzZXQiOjIwfQ=="
        assert result["has_more"]
    assert result.get("write_acknowledged", False) == (case["method"] != "GET")


@pytest.mark.asyncio
async def test_filtered_page_and_terminal_page(monkeypatch):
    requests = transport(monkeypatch, {"data": {"items": [], "pagination": {}}})
    result = await node({"operation": "list_people", "limit": 10, "cursor": "previous", "name_query": "Alice"}).execute({})
    assert dict(requests[0].url.params) == {"limit": "10", "cursor": "previous", "filter[fullName][like]": "Alice"}
    assert result["items"] == [] and result["next_cursor"] is None and result["has_more"] is False


@pytest.mark.asyncio
async def test_association_replacements_note_entity_and_idempotency(monkeypatch):
    case = EXAMPLES["update_person"]
    requests = transport(monkeypatch, case["response"])
    group = "grp_5fa60242-0756-4e31-8cca-30c2c5ff1ac2"
    company = "com_92346499-30bf-4278-ae8e-4aa3ae2ace2c"
    await node({**case["config"], "group_ids": [group], "company_ids": [company], "emails": [], "idempotency_key": "same-write-key"}).execute({})
    assert json.loads(requests[0].content) == {**case["body"], "groups": [{"id": group}], "companies": [{"id": company}], "emails": []}
    assert requests[0].headers["Idempotency-Key"] == "same-write-key"
    case = EXAMPLES["create_note"]
    requests = transport(monkeypatch, case["response"])
    parent = "nte_14c18444-a0c7-459a-86b0-ccd70ebcd65c"
    await node({**case["config"], "parent_note_id": parent}).execute({})
    assert json.loads(requests[0].content) == {**case["body"], "parentNote": {"id": parent}}


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["https://evil.example/v1/people?cursor=next", "https://api.folk.app/v1/companies?cursor=next", "https://api.folk.app/v1/people?cursor=previous", "https://api.folk.app/v1/people?cursor=a&cursor=b"])
async def test_untrusted_or_nonadvancing_next_page_is_rejected(monkeypatch, link):
    requests = transport(monkeypatch, {"data": {"items": [], "pagination": {"nextLink": link}}})
    with pytest.raises(ValueError, match="next page|cursor"):
        await node({"operation": "list_people", "cursor": "previous"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_errors_preserved_secrets_redacted_no_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"error": {"message": "Rejected " + KEY}}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_current_user"}).execute({})
    assert "Rejected [redacted]" in str(exc.value) and KEY not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{}, {"data": []}, {"data": {}}, {"data": {"id": "wrong-id"}}])
async def test_invalid_or_mismatched_resource_fails(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node(EXAMPLES["get_person"]["config"]).execute({})


@pytest.mark.parametrize("key", ["https://example.com", "<token>", "Bearer secret", "bad\nheader", "nonascii-ä"])
def test_bad_keys_rejected(key):
    with pytest.raises(ValidationError):
        native.FolkAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("operation,field", [("get_person", "person_id"), ("get_company", "company_id"), ("get_note", "note_id")])
def test_unsafe_path_ids_rejected(operation, field):
    with pytest.raises(ValueError):
        node({"operation": operation, field: "../../users/me"})
