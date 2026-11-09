"""Exercise the discovered node with the provider's documented wire examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import slicktext_node as native
from nodes.core.registry import NodeFactory

TOKEN = "slicktext-test-secret-key"
CASES = json.loads((Path(__file__).parent / "fixtures/slicktext/documented.json").read_text())["cases"]


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="slicktext-test", node_type="automation-slicktext", node_data={
        "config": config, "credentials": credentials or {"credential_type": "slicktext_api_key", "api_key": TOKEN}})


def transport(monkeypatch, payload, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_documented_operations_through_factory(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == case["response"]
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"] and req.url.path == case["path"]
    assert req.url.host == "dev.slicktext.com"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert req.headers["Content-Type"] == "application/json"
    assert dict(req.url.params) == case["query"]
    assert (json.loads(req.content) if req.content else None) == case["request"]
    assert TOKEN not in str(result)
    if case["operation"] in {"create_campaign", "update_campaign"}:
        assert result["delivery_verified"] is False


@pytest.mark.asyncio
async def test_paging_reports_next_offset_without_fetching_again(monkeypatch):
    requests = transport(monkeypatch, {"data": [{"contact_id": 123}], "pagingData": {"hasMore": True}})
    result = await node({"operation": "list_contacts", "brand_id": 1, "limit": 1, "offset": 20}).execute({})
    assert result["next_offset"] == 21 and result["complete"] is False
    assert len(requests) == 1
    transport(monkeypatch, {"data": [], "pagingData": {"hasMore": False}})
    result = await node({"operation": "list_contacts", "brand_id": 1}).execute({})
    assert result["complete"] is True and result["next_offset"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": []}, {"data": [], "pagingData": {"hasMore": True}}, {"data": [], "pagingData": {"hasMore": "false"}}])
async def test_invalid_collections_cannot_claim_success(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "list_contacts", "brand_id": 1}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(403, {"message": "denied " + TOKEN}), (429, {"message": "rate limited"}), (500, {}), (200, {"errors": [TOKEN]})])
async def test_rejections_are_redacted_and_never_retried(monkeypatch, status, payload):
    requests = transport(monkeypatch, payload, status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "create_list", "brand_id": 1, "name": "Join"}).execute({})
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_uncertain_write_is_not_retried(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout(TOKEN))
    with pytest.raises(ValueError, match="write outcome is unknown") as error:
        await node({"operation": "delete_contact", "brand_id": 1, "contact_id": 2}).execute({})
    assert len(requests) == 1 and TOKEN not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"name": "SlickText"}, {"brand_id": 1, "name": ""}])
async def test_connection_requires_brand_identity(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError, match="identity"):
        await node({"operation": "get_brand"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "create_contact", "brand_id": 1, "mobile_number": "123"},
    {"operation": "get_contact", "brand_id": 1, "contact_id": "../brands"},
    {"operation": "list_contacts", "brand_id": 1, "limit": 251},
    {"operation": "update_list", "brand_id": 1, "list_id": 2},
    {"operation": "update_contact", "brand_id": 1, "contact_id": 2, "custom_fields": {}},
    {"operation": "update_list", "brand_id": 1, "list_id": 2, "name": None},
    {"operation": "create_campaign", "brand_id": 1, "name": "test", "body": "test", "audience": {}, "status": "scheduled"},
    {"operation": "create_contact", "brand_id": 1, "mobile_number": "+16155553338", "custom_fields": {"operation": "delete_contact"}},
])
def test_bad_inputs_fail_before_network(config):
    assert native.SlickTextNode.validate_config({"config": config})["valid"] is False


def test_manual_credential_default_and_token_validation():
    assert native.SlickTextAPIKeyCredential(api_key=TOKEN).credential_type == "slicktext_api_key"
    for value in ("Bearer " + TOKEN, "https://example.com/key"):
        with pytest.raises(ValidationError):
            native.SlickTextAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_campaign_update_can_clear_media(monkeypatch):
    requests = transport(monkeypatch, {"campaign_id": 3333, "media_url": None})
    await node({"operation": "update_campaign", "brand_id": 1, "campaign_id": 3333, "media_url": None}).execute({})
    assert json.loads(requests[0].content) == {"media_url": None}
