"""Exercise Jinko's wire boundary, money and asynchronous response semantics."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

import nodes.jinko_node as module
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/jinko/servicing.json").read_text())
KEY = "jnk_t_test_secret"


def node(config):
    return NodeFactory.create_node("jinko-test", "automation-jinko", {
        "config": config, "credentials": {"credential_type": "jinko_api_key", "api_key": KEY}})


@pytest.fixture
def transport(monkeypatch):
    calls = []
    result = {"status": 200, "body": {"result": "ok"}, "headers": {}}

    def handle(request):
        calls.append(request)
        return httpx.Response(result["status"], json=result["body"], headers=result["headers"])

    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as session:
            yield session

    monkeypatch.setattr(module, "guarded_async_client", client)
    return calls, result


@pytest.mark.asyncio
async def test_jinko_cancel_copies_acknowledged_minor_units_once(transport):
    calls, result = transport
    result["body"] = {"state": "pending", "operation": "svc_example"}
    out = await node({"operation": "commit_hotel_cancel", **FIXTURE["hotel_cancel"]}).execute({})
    assert len(calls) == 1
    request = calls[0]
    assert (request.method, str(request.url)) == ("POST", "https://api.gojinko.com/v1/hotel_cancel_commit")
    assert request.headers["X-API-Key"] == KEY
    assert json.loads(request.content) == FIXTURE["hotel_cancel"]
    assert out["data"]["state"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [
    ("status_hotel_cancel", "hotel_cancel_status"), ("status_flight_refund", "flight_refund_status")])
async def test_jinko_service_handle_is_not_the_node_discriminator(transport, operation, path):
    calls, _ = transport
    await node({"operation": operation, "booking_ref": "JNK-H1ZK90", "service_operation": "svc_example"}).execute({})
    assert calls[0].url.path == "/v1/" + path
    assert json.loads(calls[0].content) == {"booking_ref": "JNK-H1ZK90", "operation": "svc_example"}


@pytest.mark.asyncio
async def test_jinko_car_search_uses_published_body(transport):
    calls, _ = transport
    await node({"operation": "search_cars", **FIXTURE["car_search"]}).execute({})
    assert calls[0].url.path == "/v1/car_search"
    assert json.loads(calls[0].content) == FIXTURE["car_search"]


@pytest.mark.asyncio
async def test_jinko_task_pending_retains_polling_hint(transport):
    calls, result = transport
    result.update(status=202, body={"status": "running", "task_id": "atk_example"}, headers={"Retry-After": "3"})
    out = await node({"operation": "search_hotels_ai", "text": "A hotel in Paris", "timezone": "Europe/Paris"}).execute({})
    assert len(calls) == 1
    assert out["http_status"] == 202 and out["retry_after"] == "3"
    assert out["data"]["status"] == "running"


@pytest.mark.asyncio
async def test_jinko_hotel_reviews_preserves_page_and_opaque_identifier(transport):
    calls, result = transport
    result["body"] = {"reviews": [], "total": 12}
    out = await node({"operation": "get_hotel_reviews", "hotel_id": "opaque/id", "offset": 10, "limit": 2}).execute({})
    assert calls[0].url.raw_path == b"/v1/hotel_reviews/opaque%2Fid?limit=2&offset=10"
    assert out["data"] == result["body"]


@pytest.mark.asyncio
async def test_jinko_evidence_reads_authenticated_demand(transport):
    calls, _ = transport
    await node({"operation": "list_destinations"}).execute({})
    assert calls[0].method == "GET"
    assert calls[0].url.params["origin"] == "global"
    assert module.JinkoNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 409, 429, 503])
async def test_jinko_error_envelopes_are_not_success_and_never_retry(transport, status):
    calls, result = transport
    result.update(status=status, body={"error": {"code": "FORBIDDEN", "message": "Refused " + KEY}})
    out = await node({"operation": "checkout_trip", "trip_id": "trip_1048576"}).execute({})
    assert out["status"] == "error" and out["http_status"] == status
    assert KEY not in json.dumps(out)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_jinko_empty_trip_write_refused_without_request(transport):
    with pytest.raises(ValueError, match="Provide a trip item"):
        await node({"operation": "manage_trip"}).execute({})
    assert not transport[0]


def test_jinko_manual_credential_default_and_hidden_secret():
    cred = module.JinkoAPIKeyCredential(api_key=KEY)
    assert cred.credential_type == "jinko_api_key"
    assert KEY not in repr(cred)
    with pytest.raises(ValidationError):
        module.JinkoAPIKeyCredential(api_key="https://example.com/key")
