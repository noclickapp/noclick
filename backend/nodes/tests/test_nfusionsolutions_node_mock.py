"""Requests, errors, manual credentials and stateful interval polling against v1 schemas."""
import copy
import json
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.nfusionsolutions_node import NFusionSolutionsNode, NFusionTokenCredential
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

CASES = json.loads(
    (
        Path(__file__).parent / "fixtures/nfusionsolutions/contract_cases.json"
    ).read_text()
)["cases"]
TOKEN = "fixture-nfusion-secret"


def node(config):
    return NodeFactory.create_node(
        node_id="nfusion-test",
        node_type="automation-nfusionsolutions",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "nfusionsolutions_token",
                "token": TOKEN,
            },
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c["config"]["operation"] for c in CASES])
async def test_contract_requests_and_responses(case):
    with respx.mock as router:
        route = router.request(
            case["method"], "https://api.nfusionsolutions.biz" + case["path"]
        ).mock(return_value=httpx.Response(200, json=case["response"]))
        result = await node(case["config"]).execute({})
    assert result == {"status": "success", "data": case["response"]}
    assert route.call_count == 1
    request = route.calls[0].request
    assert request.url.params["token"] == TOKEN
    assert request.headers["accept"] == "application/json"
    for key, value in case["config"].items():
        if key in {"operation", "items_json"}:
            continue
        assert request.url.params[key] == (
            str(value).lower() if isinstance(value, bool) else value
        )
    if case["method"] == "POST":
        assert json.loads(request.content) == {
            "token": TOKEN,
            "items": json.loads(case["config"]["items_json"]),
        }
        assert request.headers["content-type"] == "application/json"
    elif "adjustments" not in case["path"]:
        assert request.url.params["format"] == "json"


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_spot_history", "metals": "gold", "start": "not-a-date"},
        {"operation": "get_currency_rates"},
        {"operation": "get_spot_summary", "metals": "gold", "unitofmeasure": "ounce"},
        {
            "operation": "update_metal_adjustments",
            "items_json": '[{"adjustments": []}]',
        },
        {
            "operation": "update_currency_adjustments",
            "items_json": '[{"enabled":true,"adjustments":[{"ask":3}]}]',
        },
        {
            "operation": "update_currency_adjustments",
            "items_json": '[{"enabled":true,"unknown":1}]',
        },
    ],
)
def test_invalid_inputs_fail_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_credential_default_and_reachability():
    credential = NFusionTokenCredential(token=TOKEN)
    assert credential.credential_type == "nfusionsolutions_token"
    evidence = NFusionSolutionsNode.connection_evidence
    assert (
        evidence.operation == "get_metal_adjustments"
        and evidence.proves == "reachability"
    )
    with pytest.raises(ValueError):
        NFusionTokenCredential(token="https://example.com/token")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body",
    [
        (401, {"error": "Unauthorized"}),
        (302, {"url": "https://example.com"}),
        (500, {"error": TOKEN}),
    ],
)
async def test_http_errors_redact_query_secret(status, body):
    with respx.mock as router:
        router.get("https://api.nfusionsolutions.biz/api/v1/Metals/adjustments").mock(
            return_value=httpx.Response(status, json=body)
        )
        with pytest.raises(ValueError) as error:
            await node({"operation": "get_metal_adjustments"}).execute({})
    assert TOKEN not in str(error.value)
    assert str(status) in str(error.value)


@pytest.mark.asyncio
async def test_error_envelope_and_non_json_do_not_look_successful():
    with respx.mock as router:
        route = router.get(
            "https://api.nfusionsolutions.biz/api/v1/Metals/spot/summary"
        )
        route.mock(
            return_value=httpx.Response(
                200, json=[{"success": False, "error": "Symbol not supported"}]
            )
        )
        with pytest.raises(ValueError, match="Symbol not supported"):
            await node({"operation": "get_spot_summary", "metals": "unknown"}).execute(
                {}
            )
        route.mock(return_value=httpx.Response(200, text="<html>Login</html>"))
        with pytest.raises(ValueError, match="non-JSON"):
            await node({"operation": "get_spot_summary", "metals": "gold"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,trigger",
    [
        ("get_spot_history", "on_new_or_updated_spot_interval"),
        ("get_currency_history", "on_new_or_updated_currency_interval"),
    ],
)
async def test_poll_baseline_new_and_updated_interval_and_agent_event(source, trigger):
    case = next(c for c in CASES if c["config"]["operation"] == source)
    config = {**case["config"], "operation": trigger}
    watcher = node(config)
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(copy.deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    watcher._update_node_state = update
    body = copy.deepcopy(case["response"])
    with respx.mock as router:
        route = router.get("https://api.nfusionsolutions.biz" + case["path"])
        route.mock(return_value=httpx.Response(200, json=body))
        first = await watcher.execute({})
        assert first["interval_count"] == 0
        assert NFusionSolutionsNode.resolve_agent_event(first) is None
        body[0]["data"]["intervals"][0]["last"] = 2060.0
        route.mock(return_value=httpx.Response(200, json=body))
        changed = await watcher.execute({})
        assert changed["interval_count"] == 1
        assert NFusionSolutionsNode.should_propagate_output(changed, config)
        event = NFusionSolutionsNode.resolve_agent_event(changed)
        assert body[0]["data"]["symbol"] in event["text"] and "2060" in event["text"]
        assert (await watcher.execute({}))["interval_count"] == 0
        next_interval = {
            **body[0]["data"]["intervals"][0],
            "start": "2026-01-02T00:00:00Z",
            "end": "2026-01-03T00:00:00Z",
        }
        body[0]["data"]["intervals"].append(next_interval)
        route.mock(return_value=httpx.Response(200, json=body))
        assert (await watcher.execute({}))["interval_count"] == 1
    assert poll_scope(NFusionSolutionsNode, config) == poll_scope(
        NFusionSolutionsNode, {**config, "label": "Renamed", "goal": "Price alerts"}
    )
    assert poll_scope(NFusionSolutionsNode, config) != poll_scope(
        NFusionSolutionsNode, {**config, "interval": "1h"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,path",
    [
        ("update_metal_adjustments", "/api/v1/Metals/adjustments"),
        ("update_currency_adjustments", "/api/v1/Currencies/adjustments"),
    ],
)
async def test_adjustment_writes_preserve_explicit_null_and_zero(operation, path):
    items = [
        {
            "enabled": False,
            "expiresOn": None,
            "adjustments": [{"symbol": "gold", "ask": None, "bidAdjustment": 0}],
        }
    ]
    with respx.mock as router:
        route = router.post("https://api.nfusionsolutions.biz" + path).mock(
            return_value=httpx.Response(200, json={"enabled": False})
        )
        await node({"operation": operation, "items_json": json.dumps(items)}).execute(
            {}
        )
    assert json.loads(route.calls[0].request.content) == {
        "token": TOKEN,
        "items": items,
    }
