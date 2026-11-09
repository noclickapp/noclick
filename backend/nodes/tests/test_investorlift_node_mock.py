"""Offline request and parser checks using the provider's published examples."""
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from nodes import investorlift_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads(
    (Path(__file__).parent / "fixtures/investorlift/contract.json").read_text()
)["cases"]
TOKEN = "synthetic-investorlift-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="investorlift-fixture",
        node_type="automation-investorlift",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "investorlift_api_key",
                "api_key": TOKEN,
            },
        },
    )


def mock(monkeypatch, reply):
    requests = []

    def handler(request):
        requests.append(request)
        return (
            reply(request)
            if callable(reply)
            else httpx.Response(200, json=reply, headers={"trace-id": "fixture-trace"})
        )

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_published_contract_requests_and_documented_responses(monkeypatch, case):
    requests = mock(monkeypatch, case["response"])
    result = await node(case["config"]).run({})
    assert result["status"] == "success", result
    assert result["data"] == case["response"]
    assert result["trace_id"] == "fixture-trace"
    assert len(requests) == 1
    request = requests[0]
    assert (
        request.url.host == "api.investorliftdata.com"
        and request.method == case["method"]
    )
    path = case["path"]
    for key, value in case["config"].items():
        if "{" + key + "}" in path:
            path = path.replace("{" + key + "}", quote(value, safe=""))
    assert request.url.raw_path.split(b"?")[0].decode() == path
    assert request.headers["authorization"] == "Bearer " + TOKEN
    if case["method"] == "POST":
        assert json.loads(request.content) == {
            k: v for k, v in case["config"].items() if k != "operation"
        }
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_repeated_zip_false_cursor_and_idempotency_not_body(monkeypatch):
    requests = mock(
        monkeypatch,
        {"data": [], "page": {"next_cursor": "next+token", "limit": 2, "returned": 0}},
    )
    result = await node(
        {
            "operation": "list_listings",
            "zip": ["85008", "85009"],
            "on_market": False,
            "limit": 2,
            "cursor": "prior+token",
        }
    ).run({})
    assert requests[0].url.params.get_list("zip") == ["85008", "85009"]
    assert requests[0].url.params["on_market"] == "false"
    assert requests[0].url.params["cursor"] == "prior+token"
    assert result["data"]["page"]["next_cursor"] == "next+token" and len(requests) == 1
    requests = mock(monkeypatch, {"valid": True})
    await node(
        {
            "operation": "predict",
            "address": "1026 N Beckley Ave, Dallas, TX 75203",
            "idempotency_key": "owned-call-1",
        }
    ).run({})
    assert requests[0].headers["Idempotency-Key"] == "owned-call-1"
    assert "idempotency_key" not in json.loads(requests[0].content)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 402, 403, 409, 422, 429, 503])
async def test_errors_never_retry_and_redact_provider_details(monkeypatch, status):
    requests = mock(
        monkeypatch,
        lambda r: httpx.Response(
            status,
            json={
                "type": "https://docs.investorliftdata.com/errors/invalid-key",
                "detail": "Rejected " + TOKEN,
            },
            headers={
                "content-type": "application/problem+json",
                "trace-id": "failed-trace",
                "retry-after": "60",
                "location": "https://example.test/",
            },
        ),
    )
    result = await node({"operation": "get_coverage"}).run({})
    assert (
        result["status"] == "error"
        and result["http_status"] == status
        and len(requests) == 1
    )
    assert result["trace_id"] == "failed-trace" and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [[], None, {"error": "unavailable"}, {"type": "problem"}]
)
async def test_malformed_or_error_success_envelopes_fail(monkeypatch, body):
    requests = mock(monkeypatch, body)
    result = await node({"operation": "get_coverage"}).run({})
    assert result["status"] == "error" and len(requests) == 1


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "predict"},
        {"operation": "predict", "address": "x", "property_id": "a" * 32},
        {"operation": "predict", "address": "x", "overrides": {}},
        {"operation": "predict", "address": "x", "overrides": {"bathrooms": None}},
        {"operation": "predict_batch", "properties": []},
        {"operation": "get_property", "property_id": "../evil"},
        {"operation": "list_listings", "zip": ["bad"]},
        {"operation": "list_listings", "lat": 33.4},
        {"operation": "list_listings", "zip": ["85008"], "bbox": "x"},
        {"operation": "list_listings", "zip": ["85008"], "limit": True},
    ],
)
def test_invalid_inputs_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_key_defaults_and_reachability_evidence():
    assert (
        native.InvestorLiftAPIKeyCredential(api_key=TOKEN).credential_type
        == "investorlift_api_key"
    )
    assert native.InvestorLiftNode.connection_evidence.proves == "reachability"
    for key in ["Bearer " + TOKEN, "https://example.test/key", "<token>", "x\ny"]:
        with pytest.raises(ValueError):
            native.InvestorLiftAPIKeyCredential(api_key=key)
