"""Exercise all ten Polygon requests through the real operation runner."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import polygon_node as polygon
from nodes.core.connection_evidence import collect_evidence
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "polygon_api_key", "api_key": "polygon-test-secret-12345"}
CASES = json.loads((Path(__file__).parent / "fixtures/polygon/synthetic_cases.json").read_text())["cases"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        calls.append(request)
        response = replies.pop(0)
        if isinstance(response, Exception):
            raise response
        status, body = response
        return httpx.Response(status, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(polygon, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return calls, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(node_type="automation-polygon", operation=operation,
        arguments=arguments or {}, credential_data=auth, user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path,body", CASES)
async def test_polygon_exact_requests_and_lossless_results(transport, operation, config, path, body):
    calls, replies = transport
    replies.append((200, body))
    result = await run(operation, config)
    assert result == {"status": "success", "data": body}
    assert len(calls) == 1 and not replies
    req = calls[0]
    assert req.method == "GET" and req.url.host == "api.polygon.io"
    assert req.url.path == path and req.content == b""
    expected = {"apiKey": AUTH["api_key"]}
    if operation == "list_companies":
        expected.update({"sort": "-marketcap", "perpage": "10", "page": "2"})
    elif "historic" in operation:
        expected["limit"] = str(config.get("limit", 100))
        if "offset" in config:
            expected["offset"] = str(config["offset"])
    assert dict(req.url.params) == expected
    assert AUTH["api_key"] not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Unknown API Key"}), (403, {"message": "Not entitled"}), (429, {"message": "Rate limit exceeded"}), (200, {"status": "ERROR", "error": "Invalid API key"}), (302, {})])
async def test_polygon_rejections_are_not_success(transport, status, body):
    transport[1].append((status, body))
    with pytest.raises(ValueError):
        await run("list_currencies")
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_polygon_errors_redact_query_key(transport):
    transport[1].append((401, {"message": "Rejected " + AUTH["api_key"]}))
    with pytest.raises(ValueError) as err:
        await run("list_currencies")
    assert AUTH["api_key"] not in str(err.value)
    transport[1].append(httpx.ConnectError("https://api.polygon.io?apiKey=" + AUTH["api_key"]))
    with pytest.raises(ValueError) as err:
        await run("list_currencies")
    assert AUTH["api_key"] not in str(err.value)


@pytest.mark.asyncio
async def test_polygon_connect_proves_reachability(transport):
    transport[1].append((200, ["USD", "JPY"]))
    result = await collect_evidence(node_type="automation-polygon", user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert result.reachable is True
    assert polygon.PolygonNode.connection_evidence.proves == "reachability"
    transport[1].append((401, {"message": "Unknown API Key"}))
    result = await collect_evidence(node_type="automation-polygon", user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert result.reachable is False and "Unknown API Key" in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [
    {"symbol": "AAPL", "date": "2026-02-30"},
    {"symbol": "../bad", "date": "2017-06-22"},
    {"symbol": "AAPL", "date": "2017-06-22", "limit": 10001},
    {"symbol": "AAPL", "date": "2017-06-22", "offset": -1},
])
async def test_polygon_invalid_inputs_stop_before_http(transport, config):
    with pytest.raises(ValueError):
        await run("get_historic_trades", config)
    assert not transport[0]


def test_polygon_manual_credential_defaults():
    parsed = polygon.PolygonAPIKeyCredential(api_key=AUTH["api_key"])
    assert parsed.credential_type == "polygon_api_key"
    assert not polygon.PolygonAPIKeyCredential.model_fields["credential_type"].is_required()
