"""Exercise every operation through the actual factory and HTTP request boundary."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import databox_node as db
from nodes.core.registry import NodeFactory
from utils import ssrf

CASES = json.loads(
    (Path(__file__).parent / "fixtures/databox/requests.json").read_text()
)
AUTH = {"credential_type": "databox_api_key", "api_key": "databox-fixture-key"}


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        db,
        "guarded_async_client",
        lambda **kw: native(**kw, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(op, args=None):
    node = NodeFactory.create_node(
        node_id="databox-test",
        node_type="automation-databox",
        node_data={"config": {"operation": op, **(args or {})}, "credentials": AUTH},
    )
    return await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("op", CASES)
async def test_databox_contract_route_body_and_single_request(wire, op):
    requests, replies = wire
    args, method, path, body = CASES[op]
    data = {"id": 1234567, "name": "Transactions"}
    replies.append((200, {"status": "success", "data": data}))
    result = await run(op, args)
    assert result["status"] == "success" and result["data"] == data
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.raw_path.decode().split("?")[0] == path
    assert request.url.host == "api.databox.com"
    assert request.headers["x-api-key"] == AUTH["api_key"]
    assert AUTH["api_key"] not in str(request.url)
    assert (json.loads(request.content) if request.content else None) == body
    if "page" in request.url.params:
        assert request.url.params["page"] == "0"
    if op == "ingest_dataset_data":
        assert result["ingestion_completed"] is False


@pytest.mark.asyncio
async def test_databox_account_idempotency_and_filters(wire):
    requests, replies = wire
    replies.append((200, {"status": "success", "data": {}}))
    args = {
        **CASES["create_dataset"][0],
        "account_id": 123456,
        "idempotency_key": "repeat-safe",
    }
    await run("create_dataset", args)
    assert requests[0].headers["x-account-id"] == "123456"
    assert requests[0].headers["Idempotency-Key"] == "repeat-safe"
    assert not requests[0].url.query
    replies.append((200, {"status": "success", "data": {}}))
    await run(
        "list_metrics",
        {"page": 2, "page_size": 10, "source_id": 1234567, "search": "Sessions"},
    )
    assert dict(requests[-1].url.params) == {
        "page": "2",
        "pageSize": "10",
        "sourceId": "1234567",
        "search": "Sessions",
    }


@pytest.mark.asyncio
async def test_databox_page_and_partial_page_continuation(wire):
    requests, replies = wire
    for total, expected in [(1000, 1), (25, None), (0, None)]:
        replies.append(
            (
                200,
                {
                    "status": "success",
                    "data": {
                        "items": [],
                        "pagination": {"page": 0, "pageSize": 25, "totalItems": total},
                    },
                },
            )
        )
        assert (await run("list_datasets"))["next_page"] == expected
    assert len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,payload",
    [
        (401, {"status": "error", "message": "Invalid API key"}),
        (429, {"message": "Too many requests"}),
        (200, {"status": "error", "error": "Denied"}),
        (302, {}),
        (200, {"status": "success"}),
        (200, {"status": "success", "data": {"pagination": {}}}),
    ],
)
async def test_databox_errors_never_look_like_success(wire, code, payload):
    wire[1].append((code, payload))
    assert (await run("get_profile"))["status"] == "error"
    assert len(wire[0]) == 1


@pytest.mark.asyncio
async def test_databox_secret_echo_is_redacted(wire):
    wire[1].append((401, {"message": "Invalid " + AUTH["api_key"]}))
    result = await run("get_profile")
    assert AUTH["api_key"] not in json.dumps(result)
    assert result["error"] == "Invalid [redacted]"


@pytest.mark.parametrize("value", ["", "https://example.com/key", "<token>"])
def test_databox_invalid_credentials(value):
    with pytest.raises(ValidationError):
        db.DataboxAPIKey(api_key=value)


def test_databox_rejects_unsupported_granularity_and_backwards_dates():
    with pytest.raises(ValidationError):
        db.DateRange.model_validate(
            {"from": "2026-06-01", "to": "2026-06-30", "granularity": "hourly"}
        )
    with pytest.raises(ValidationError):
        db.DateRange.model_validate(
            {"from": "2026-06-30", "to": "2026-06-01", "granularity": "daily"}
        )


def test_databox_ingestion_id_requires_provider_uuid():
    with pytest.raises(ValidationError):
        db.DataboxGetDatasetIngestion(dataset_id=1234567, ingestion_id="1")


@pytest.mark.asyncio
async def test_databox_documented_error_array_keeps_provider_message(wire):
    wire[1].append(
        (
            401,
            {
                "status": "error",
                "errors": [
                    {
                        "code": "invalid_input",
                        "message": "The provided parameter is invalid.",
                        "field": "name",
                        "type": "validation",
                    }
                ],
            },
        )
    )
    result = await run("get_profile")
    assert result["status"] == "error"
    assert result["http_status"] == 401
    assert result["error"] == "The provided parameter is invalid."
