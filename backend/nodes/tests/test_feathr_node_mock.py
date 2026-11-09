"""Contract-based Feathr request/response checks without a provider account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import feathr_node as native
from nodes.core.registry import NodeFactory

TOKEN = "fthr_synthetic_fixture_key"
CASES = json.loads((Path(__file__).parent / "fixtures/feathr/wire.json").read_text())["cases"]


def node(config):
    return NodeFactory.create_node(node_id="feathr-test", node_type="automation-feathr", node_data={
        "config": config, "credentials": {"credential_type": "feathr_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, status, body):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_all_contract_operations_wire_and_documented_shapes(monkeypatch, case):
    requests = transport(monkeypatch, case["status"], case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.feathr.co" and request.url.path == case["path"]
    assert dict(request.url.params) == {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in case["query"].items()}
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    for key, value in case["headers"].items():
        assert request.headers[key] == value
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["config"]["operation"].startswith("list_"):
        assert result["has_more"] is True and result["next_page"] == 2
    elif case["status"] == 204:
        assert result["completed"] is True
    else:
        assert result["data"] == case["response"]


@pytest.mark.asyncio
async def test_empty_last_page(monkeypatch):
    requests = transport(monkeypatch, 200, {"items": [], "page": 3, "size": 10, "total": 20})
    result = await node({"operation": "list_campaigns", "page": 3, "size": 10}).execute({})
    assert dict(requests[0].url.params) == {"page": "3", "size": "10"}
    assert result["items"] == [] and result["has_more"] is False and result["next_page"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_rejection_is_not_success_and_redacts_key(monkeypatch, status):
    requests = transport(monkeypatch, status, {"title": "Forbidden", "detail": "Rejected " + TOKEN})
    result = await node({"operation": "get_account"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"items": [], "page": 0, "size": 25, "total": 0}, {"status": 403, "detail": "Forbidden"}])
async def test_invalid_pages_and_error_envelopes_fail(monkeypatch, body):
    transport(monkeypatch, 200, body)
    assert (await node({"operation": "list_campaigns"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_connection_identity_and_response_token_redaction(monkeypatch):
    transport(monkeypatch, 200, {"account_id": "owned-account", "service_name": TOKEN, "rate_limit": {"enabled": False}})
    result = await node({"operation": "get_account"}).execute({})
    assert result["data"]["account_id"] == "owned-account" and TOKEN not in str(result)
    assert native.FeathrNode.connection_evidence.identity_operation == "get_account"


@pytest.mark.parametrize("config", [
    {"operation": "upsert_person", "first_name": "Ava"},
    {"operation": "create_tag", "name": "Members", "context": "invalid"},
    {"operation": "add_person_tags", "person_id": "person", "tag_ids": []},
    {"operation": "list_campaigns", "page": 0}, {"operation": "list_projects", "size": 101},
    {"operation": "update_custom_field", "field_id": "field", "data_type": "int"},
])
def test_invalid_config_rejected(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize("key", ["Bearer secret", "https://example.com/key", "key\nheader", "<token>"])
def test_manual_key_rejects_header_url_controls_and_placeholder(key):
    with pytest.raises(ValidationError):
        native.FeathrAPIKeyCredential(api_key=key)


def test_credential_default_is_hand_connectable():
    credential = native.FeathrAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "feathr_api_key"
    assert native.FeathrAPIKeyCredential.model_json_schema()["required"] == ["api_key"]
