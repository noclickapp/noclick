"""Wire assertions use the provider's published 0.4.3 response examples."""
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.outscraper_ca1391_node import (
    BASE, FAMILY, MODELS, OPERATIONS, TRIGGERS, OutscraperAPIKeyCredential,
    OutscraperFullConfig, OutscraperNode, OutscraperError,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures/outscraper-ca1391/published_examples.json").read_text())
SECRET = "test-outscraper-private-key"
CREDENTIAL = {"credential_type": FAMILY, "api_key": SECRET}
CLIENT = httpx.AsyncClient


def setup_http(monkeypatch, handler):
    monkeypatch.setattr("nodes.outscraper_ca1391_node.httpx.AsyncClient",
        lambda **kwargs: CLIENT(transport=httpx.MockTransport(handler), **kwargs))


def config_for(name):
    fields = MODELS[name].model_fields
    raw = {"operation": name}
    if "query" in fields:
        raw["query"] = "Restaurants, Manhattan, NY, US" if fields["query"].annotation is str else ["outscraper.com"]
    if name == "list_tasks":
        raw["query"] = "restaurant +1"
    if "requestId" in fields:
        raw["requestId"] = "your-request-id"
    if "taskId" in fields:
        raw["taskId"] = "20211211132758c8e9"
    if name == "create_task":
        raw.update(service_name="google_maps_service_v2", queries=["restaurants ny usa"], tags=["restaurant +1"])
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize("name", OPERATIONS)
async def test_outscraper_ca1391_documented_wire(monkeypatch, name):
    spec = OPERATIONS[name]
    key = f"{spec.method} {spec.path} 200"
    body = FIXTURE["responses"][key]
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == spec.method
        expected = spec.path.replace("{requestId}", "your-request-id").replace("{taskId}", "20211211132758c8e9")
        assert str(request.url).split("?", 1)[0] == BASE + expected
        assert request.headers["x-api-key"] == SECRET
        assert "apiKey" not in request.url.params
        if spec.body:
            assert json.loads(request.content) == {"service_name": "google_maps_service_v2", "queries": ["restaurants ny usa"], "tags": ["restaurant +1"]}
        elif "async_request" in spec.fields:
            assert request.url.params["async"] == "true"
            if spec.fields["query"][0] == list[str]:
                assert request.url.params.get_list("query") == ["outscraper.com"]
        return httpx.Response(200, json=body)

    setup_http(monkeypatch, handle)
    cfg = OutscraperFullConfig.model_validate({"config": config_for(name), "credentials": CREDENTIAL})
    node = OutscraperNode(node_id="test", node_type=OutscraperNode.integration_type, node_data={}, config=cfg, sio=Mock())
    result = await node.execute({})
    assert result == {"status": "success", "operation": name, "data": body}
    assert len(calls) == 1  # No retries or hidden follow-up mutations.


@pytest.mark.asyncio
@pytest.mark.parametrize("name", TRIGGERS)
async def test_outscraper_ca1391_signed_completion_lifecycle(monkeypatch, name):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            assert request.url.path == OPERATIONS[TRIGGERS[name][1]].path
            assert request.url.params["webhook"] == "https://example.hooks.example.test/webhook/test"
            assert request.url.params["async"] == "true"
            return httpx.Response(202, json=FIXTURE["responses"]["GET /google-maps-search 202"])
        assert request.method == "DELETE"
        assert request.url.path == "/requests/your-request-id"
        return httpx.Response(200, json=FIXTURE["responses"]["DELETE /requests/{requestId} 200"])

    setup_http(monkeypatch, handle)
    config = {"operation": name, "query": "Restaurants, Manhattan, NY, US" if name == "on_google_maps_finished" else ["support@outscraper.com"]}
    state = await OutscraperNode._register_external_webhook(webhook_url="https://example.hooks.example.test/webhook/test", credential=CREDENTIAL, config=config, node_id="test")
    config.update(state)
    event = FIXTURE["completion_event"]
    raw = json.dumps(event).encode()
    signed = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert OutscraperNode.verify_webhook_signature(raw, {"X-Hub-Signature-256": signed}, config)
    assert not OutscraperNode.verify_webhook_signature(raw + b" ", {"X-Hub-Signature-256": signed}, config)
    assert not OutscraperNode.verify_webhook_signature(raw, {}, config)
    assert not OutscraperNode.verify_webhook_signature(raw, {"X-Hub-Signature-256": signed}, {})
    assert OutscraperNode.filter_trigger_payload(event, config)
    assert not OutscraperNode.filter_trigger_payload({**event, "id": "other-job"}, config)
    assert not OutscraperNode.filter_trigger_payload({**event, "api_task": False}, config)
    output = OutscraperNode.resolve_trigger_payload(event, config)
    turn = OutscraperNode.resolve_agent_event(output)
    assert turn["conversation_key"] == "your-request-id"
    assert "your-user-id" in turn["text"]
    assert "Google Maps Data: 1 units" in turn["text"]
    assert "get_request_results" in turn["text"]
    await OutscraperNode._unregister_external_webhook(credential=CREDENTIAL, config=config, node_id="test")
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_outscraper_ca1391_auth_failure_redacts_key(monkeypatch):
    setup_http(monkeypatch, lambda request: httpx.Response(401, text=f"Invalid API key {SECRET}"))
    with pytest.raises(OutscraperError) as caught:
        await OutscraperNode._request(CREDENTIAL, "GET", "/profile/balance")
    assert "401" in str(caught.value)
    assert "Invalid API key" in str(caught.value)
    assert SECRET not in str(caught.value)


@pytest.mark.asyncio
async def test_outscraper_ca1391_empty_and_failed_results_are_not_success(monkeypatch):
    setup_http(monkeypatch, lambda request: httpx.Response(204, json={"id": "your-request-id", "status": "Failure"}))
    with pytest.raises(OutscraperError, match="failed"):
        await OutscraperNode._perform(CREDENTIAL, "get_request_results", {"requestId": "your-request-id"})


@pytest.mark.asyncio
@pytest.mark.parametrize("resource_id", ["../profile/balance", "a?apiKey=bad", "a/b", "https://example.com"])
async def test_outscraper_ca1391_ids_cannot_change_route(resource_id):
    with pytest.raises(ValueError, match="resource ID"):
        await OutscraperNode._perform(CREDENTIAL, "terminate_request", {"requestId": resource_id})


def test_outscraper_ca1391_manual_key_default_and_bounds():
    assert OutscraperAPIKeyCredential(api_key=SECRET).credential_type == FAMILY
    for value in ["https://example.com/key", "<token>", "key\nheader"]:
        with pytest.raises(ValidationError):
            OutscraperAPIKeyCredential(api_key=value)
    with pytest.raises(ValidationError):
        MODELS["search_google_maps"](query="restaurants", limit=10001)


@pytest.mark.asyncio
async def test_outscraper_ca1391_trigger_manual_run_does_not_start_job(monkeypatch):
    def unexpected(request):
        pytest.fail("A manual trigger run must not submit another paid job")
    setup_http(monkeypatch, unexpected)
    cfg = OutscraperFullConfig.model_validate({"config": {"operation": "on_google_maps_finished", "query": "restaurants"}, "credentials": CREDENTIAL})
    node = OutscraperNode(node_id="test", node_type=OutscraperNode.integration_type, node_data={}, config=cfg, sio=Mock())
    assert node.trigger_produced_no_event(await node.execute({}))
