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


def company_trigger(perpage=100):
    config = polygon.PolygonFullConfig.model_validate({
        "config": {"operation": "on_new_or_updated_company", "perpage": perpage},
        "credentials": AUTH,
    })
    return polygon.PolygonNode(node_id="polygon-trigger", node_type="automation-polygon",
                               node_data={}, config=config)


@pytest.mark.asyncio
async def test_polygon_company_poll_baselines_deduplicates_and_delivers_agent_event(transport):
    # Synthetic regression values for Company properties in the pinned contract;
    # these are not represented as provider-authored response examples.
    old = {"symbol": "AAPL", "name": "Apple", "updated": "2026-11-09T12:00:00Z"}
    changed = {**old, "updated": "2026-11-10T12:00:00Z", "marketcap": 1234.5}
    added = {"symbol": "MSFT", "name": "Microsoft", "updated": "2026-11-10T12:00:00Z"}
    trigger = company_trigger(10)
    state = {}

    async def update(mutator, **kwargs):
        next_state, result = mutator(dict(state))
        if next_state is not None:
            state.clear()
            state.update(next_state)
        return result

    trigger._update_node_state = update
    transport[1].append((200, [old]))
    baseline = await trigger.execute({})
    assert baseline["data"]["companies"] == []
    assert trigger.trigger_produced_no_event(baseline)
    assert trigger.resolve_agent_event(baseline) is None
    transport[1].append((200, [changed, added]))
    result = await trigger.execute({})
    assert result["data"]["companies"] == [changed, added]
    assert result["data"]["new_or_updated_company_count"] == 2
    assert trigger.trigger_emitted_event(result)
    event = trigger.resolve_agent_event(result)
    for value in ("Apple", "AAPL", "Microsoft", "MSFT", changed["updated"], "1234.5"):
        assert value in event["text"]
    transport[1].append((200, [changed, added]))
    assert (await trigger.execute({}))["data"]["companies"] == []
    for request in transport[0]:
        assert request.url.path == "/v1/companies"
        assert dict(request.url.params) == {
            "sort": "-updated", "perpage": "10", "page": "1", "apiKey": AUTH["api_key"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[{}], [{"symbol": "AAPL"}], ["AAPL"]])
async def test_polygon_poll_rejects_records_without_identity_without_consuming_state(transport, body):
    trigger = company_trigger()
    trigger._filter_unseen = AsyncMock()
    transport[1].append((200, body))
    with pytest.raises(ValueError, match="symbol and updated"):
        await trigger.execute({})
    trigger._filter_unseen.assert_not_awaited()


def test_polygon_poll_scope_ignores_schedule_and_builder_metadata():
    from nodes.core.poll_trigger import poll_scope
    cfg = {"operation": "on_new_or_updated_company", "perpage": 100}
    scope = poll_scope(polygon.PolygonNode, cfg)
    assert scope
    # Use the parsed operation's declared fields; UI metadata is stripped by parse_config.
    assert scope == poll_scope(polygon.PolygonNode, {**cfg, "goal": "Watch companies", "label": "Stocks"})
    assert scope != poll_scope(polygon.PolygonNode, {**cfg, "perpage": 200})
