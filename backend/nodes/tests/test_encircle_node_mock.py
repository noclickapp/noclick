"""Encircle wire-contract regressions through the production node factory.

Fixtures are synthetic account data; no live token or account is needed.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import encircle_node as encircle
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-encircle-token"
ORG = "f81d4fae-7dec-11d0-a765-00a0c91e6bf6"
CASES = json.loads((Path(__file__).parent / "fixtures/encircle/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="encircle-test", node_type="automation-encircle", node_data={
        "config": config, "credentials": credential or {"credential_type": "encircle_token", "api_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []

    def handle(request):
        requests.append(request)
        return response(request)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(encircle, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_documented_routes_fields_and_response_shapes(monkeypatch, case):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=case["response"]))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url).split("?")[0] == "https://api.encircleapp.com" + case["path"]
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["X-Encircle-Attribution"] == "NoClick"
    assert TOKEN not in str(result)
    if "list" in case["response"]:
        assert result["items"] == case["response"]["list"]
        assert result["next_after"] == case["response"].get("cursor", {}).get("after")
    else:
        assert result["data"] == case["response"]


@pytest.mark.asyncio
async def test_cursor_and_filters_are_returned_without_following_urls(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={
        "list": [{"id": 42, "policyholder_name": "A + B"}],
        "cursor": {"after": "opaque+/=", "limit": 2, "order": "oldest"}}))
    result = await node({"operation": "list_claims", "limit": 2, "order": "oldest", "after": "previous+/=",
                         "policyholder_name": "A + B"}).execute({})
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {"limit": "2", "order": "oldest", "after": "previous+/=", "policyholder_name": "A + B"}
    assert result["next_after"] == "opaque+/="


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_rejections_are_not_successful_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={"message": "Token refused"},
                                                               headers={"Location": "https://example.test/"}))
    with pytest.raises(ValueError, match=f"{status}.*Token refused"):
        await node({"operation": "list_organizations"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200), httpx.Response(200, text="<html>Login</html>"),
    httpx.Response(200, json={"error": "Rejected"}), httpx.Response(200, json={"list": {}}),
    httpx.Response(200, json={"list": [], "cursor": "wrong"})])
async def test_malformed_evidence_is_never_success(monkeypatch, response):
    transport(monkeypatch, lambda _: response)
    with pytest.raises(ValueError):
        await node({"operation": "list_organizations"}).execute({})


@pytest.mark.asyncio
async def test_account_evidence_can_be_empty(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={"list": []}))
    result = await node({"operation": "list_organizations"}).execute({})
    assert result["items"] == []
    assert encircle.EncircleNode.connection_evidence.operation == "list_organizations"


@pytest.mark.parametrize("config", [
    {"operation": "create_claim", "organization_id": ORG},
    {"operation": "get_claim", "property_claim_id": "../42"},
    {"operation": "list_claims", "limit": 101},
    {"operation": "create_claim", "organization_id": ORG, "brand_id": 1, "default_depreciation": 2},
    {"operation": "create_claim", "organization_id": ORG, "brand_id": 1, "date_of_loss": "2999-01-01"},
    {"operation": "update_claim", "property_claim_id": 42},
    {"operation": "update_claim_note", "property_claim_id": 42, "note_id": 5},
    {"operation": "assign_user", "property_claim_id": 42},
    {"operation": "create_room_note", "property_claim_id": 42, "structure_id": 2, "room_id": 3},
    {"operation": "list_organizations", "api_url": "https://example.test"},
])
def test_invalid_config_refused_before_request(config):
    with pytest.raises(ConfigValidationError):
        node(config)


@pytest.mark.parametrize("token", ["", "Bearer abc", "abc\r\nInjected: yes", "https://example.test", "<token>", "nonascii-é"])
def test_bad_manual_tokens_refused(token):
    with pytest.raises(ValidationError):
        encircle.EncircleTokenCredential(api_token=token)


def test_manual_credential_type_has_default():
    credential = encircle.EncircleTokenCredential(api_token="  " + TOKEN + "\n")
    assert credential.credential_type == "encircle_token"
    assert credential.api_token == TOKEN
