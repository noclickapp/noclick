"""Cling transport and webhook tests against the published contract/examples."""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from nodes.cling_node import ClingAPIKeyCredential, ClingNode, ClingNodeConfig, CONFIG_MODELS, OPERATIONS

KEY = "test-cling-private-key"
EVENT = json.loads((Path(__file__).parent / "fixtures/cling/document_accepted.json").read_text())


def node(config):
    return ClingNode(node_id="test", node_type="automation-cling", node_data={"config": config},
        config=ClingNodeConfig.model_validate({"config": config, "credentials": {"api_key": KEY}}), sio=Mock())


@pytest.fixture
def http(monkeypatch):
    requests = []
    responses = []
    original = httpx.AsyncClient
    def handler(request):
        requests.append(request)
        assert request.url.host == "api.cling.se"
        assert request.headers["apiKey"] == KEY
        if responses:
            status, body = responses.pop(0)
            return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
        return httpx.Response(200, json={"id": 5})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    return requests, responses


@pytest.mark.asyncio
@pytest.mark.parametrize("name", OPERATIONS)
async def test_every_operation_has_one_expected_route(name, http):
    method, path, fields, _ = OPERATIONS[name]
    config = {"operation": name}
    for key, (_, field) in fields.items():
        if field.is_required():
            config[key] = 3 if key in {"customer_id", "project_id"} else "abc123" if key.endswith("_id") else "draft" if key == "status" else "Document name"
    result = await node(config).execute({})
    requests, _ = http
    assert len(requests) == 1
    expected = path
    for key, value in config.items():
        expected = expected.replace("{" + key + "}", str(value))
    assert requests[0].method == method
    assert requests[0].url.path == expected
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_create_document_body_and_send_no_body(http):
    requests, responses = http
    responses.extend([(201, {"id": "doc123"}), (204, None)])
    await node({"operation": "create_document", "template_id": "5e53a9421b78eab96f0348a3", "customer_id": 3, "name": "Byte WC", "language": "sv", "currency": "SEK"}).execute({})
    body = json.loads(requests[0].content)
    assert body == {"templateId": "5e53a9421b78eab96f0348a3", "data": {"name": "Byte WC"}, "clients": [{"endCustomerId": 3, "documentRole": "signee", "deliveryTypes": ["email"], "answerMethod": {"accept": "button", "deny": "button"}}], "language": "sv", "currency": "SEK"}
    result = await node({"operation": "send_document", "document_id": "doc123"}).execute({})
    assert requests[1].content == b""
    assert result["data"] is None


@pytest.mark.asyncio
async def test_range_query_and_nonempty_customer_body(http):
    requests, _ = http
    await node({"operation": "list_customers", "start": 20, "end": 40, "sort": "updatedAt", "order": "DESC", "where": "name*=Kent"}).execute({})
    assert dict(requests[0].url.params) == {"_start": "20", "_end": "40", "_sort": "updatedAt", "_order": "DESC", "_where": "name*=Kent"}
    await node({"operation": "create_customer", "name": "Kent Andersson", "email": "kent.andersson@yourdomain.com"}).execute({})
    assert json.loads(requests[1].content) == {"customerType": "individual", "name": "Kent Andersson", "email": "kent.andersson@yourdomain.com"}
    with pytest.raises(ValueError, match="End must exceed"):
        await node({"operation": "list_projects", "start": 20, "end": 10}).execute({})
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_http_failures_and_empty_response(http):
    _, responses = http
    responses.extend([(401, {"message": "invalid " + KEY}), (204, None), (302, None)])
    with pytest.raises(ValueError, match="401") as exc:
        await node({"operation": "list_documents"}).execute({})
    assert KEY not in str(exc.value)
    assert (await node({"operation": "delete_document", "document_id": "abc"}).execute({}))["data"] is None
    with pytest.raises(ValueError, match="302"):
        await node({"operation": "list_documents"}).execute({})


@pytest.mark.asyncio
async def test_webhook_lifecycle_and_documented_event(http):
    requests, responses = http
    responses.extend([(200, {"id": 5}), (204, None)])
    state = await ClingNode._register_external_webhook(webhook_url="https://test.hooks.example.test/webhook/test", credential={"api_key": KEY}, config={"operation": "on_document_accepted"}, node_id="test")
    body = json.loads(requests[0].content)
    assert body == {"type": "document.accepted", "isActive": True, "url": "https://test.hooks.example.test/webhook/test", "includePaths": ["id", "status", "companyId", "data.name"]}
    assert state == {"external_webhook_id": "5"}
    await ClingNode._unregister_external_webhook(credential={"api_key": KEY}, config=state, node_id="test")
    assert requests[1].method == "DELETE" and requests[1].url.path == "/webhookSubscription/5"
    assert ClingNode.verify_webhook_signature(json.dumps(EVENT).encode(), {}, {})
    assert ClingNode.filter_trigger_payload(EVENT, {})
    assert not ClingNode.filter_trigger_payload({**EVENT, "type": "document.sent"}, {})
    result = ClingNode.resolve_agent_event(ClingNode.resolve_trigger_payload(EVENT, {}))
    assert result["conversation_key"] == EVENT["typeId"]
    assert all(v in result["text"] for v in ["Document name", "accepted", "25", EVENT["typeId"]])


def test_manual_credential_and_path_validation():
    assert ClingAPIKeyCredential(api_key=KEY).credential_type == "cling_api_key"
    for bad in ["https://example.com/key", "<token>", "bad\nkey"]:
        with pytest.raises(ValueError):
            ClingAPIKeyCredential(api_key=bad)
    with pytest.raises(ValueError):
        CONFIG_MODELS["get_document"](document_id="../companyApiKey")
    with pytest.raises(ValueError):
        CONFIG_MODELS["get_customer"](customer_id=0)


@pytest.mark.asyncio
async def test_plain_provider_refusal_is_preserved(monkeypatch):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(403, text="This company user cannot manage documents"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
    with pytest.raises(ValueError, match="This company user cannot manage documents"):
        await node({"operation": "list_documents"}).execute({})


@pytest.mark.asyncio
async def test_manual_trigger_run_has_no_live_event(http):
    output = await node({"operation": "on_document_accepted"}).execute({"type": "document.accepted", "data": EVENT})
    assert output["status"] == "no_event"
    assert not http[0]
