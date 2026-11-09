"""Native execution against documented fixtures, with all HTTP intercepted."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import teltel_node as native
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "teltel_api_key", "api_key": "teltel-fixture-secret-938472"}
CASES = json.loads((Path(__file__).parent / "fixtures/teltel/contract_examples.json").read_text())["cases"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.teltel.io"
        assert request.url.params["apikey"] == AUTH["api_key"]
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)
    real_client = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: real_client(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


def node(config):
    return NodeFactory.create_node(node_id="teltel-test", node_type="automation-teltel", node_data={"config": config, "credentials": AUTH})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_teltel_documented_requests_and_responses(case, transport):
    requests, replies = transport
    replies.append((200, case["response"]))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"] and req.url.path == "/v2" + case["path"]
    cfg = {k: v for k, v in case["config"].items() if k not in {"operation", "id"}}
    if case["method"] in {"POST", "PATCH"}:
        if "sender" in cfg: cfg["from"] = cfg.pop("sender")
        assert json.loads(req.content) == {"data": cfg}
    if case["method"] == "DELETE": assert not req.content
    assert AUTH["api_key"] not in str(result)
    if case["config"]["operation"] == "list_users":
        assert "api_key" not in str(result)
        assert result["data"][0]["display_name"] == "John Doe"


@pytest.mark.asyncio
async def test_teltel_pagination_filters_and_patch_omission(transport):
    requests, replies = transport
    replies.extend([(200, {"data": []}), (200, {"meta": {"updated": True}})])
    await node({"operation": "list_contacts", "limit": 25, "offset": 50, "filter": "group_id=5"}).execute({})
    assert dict(requests[0].url.params) == {"apikey": AUTH["api_key"], "limit": "25", "offset": "50", "filter": "group_id=5"}
    await node({"operation": "update_contact", "id": 13, "param_2": "changed"}).execute({})
    assert json.loads(requests[1].content) == {"data": {"param_2": "changed"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_teltel_errors_no_redirect_or_secret_leak(status, transport):
    requests, replies = transport
    replies.append((status, {"message": "Rejected " + AUTH["api_key"]}))
    result = await node({"operation": "list_users"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert AUTH["api_key"] not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_teltel_rejects_unexpected_success_payload(transport):
    _, replies = transport
    replies.append((200, {"errors": ["invalid key"]}))
    with pytest.raises(ValueError, match="unexpected response"):
        await node({"operation": "list_users"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "id": 0},
    {"operation": "get_contact", "id": "../users"},
    {"operation": "list_contacts", "offset": 101},
    {"operation": "update_contact", "id": 13},
    {"operation": "create_contact", "phone": "371212345678"},
    {"operation": "send_sms", "sender": "test", "to": "37126118198", "message": "界" * 71},
])
def test_teltel_required_fields_and_bounds(config):
    with pytest.raises((ValueError, ValidationError)):
        native.TeltelNode.parse_config({"config": config, "credentials": AUTH})


def test_teltel_manual_credential_default_and_secret_cleaning():
    assert native.TeltelAPIKeyCredential(api_key="  " + AUTH["api_key"] + "  ").credential_type == "teltel_api_key"
    for key in ["https://example.com/key", "Bearer token", "<token>"]:
        with pytest.raises(ValueError): native.TeltelAPIKeyCredential(api_key=key)
