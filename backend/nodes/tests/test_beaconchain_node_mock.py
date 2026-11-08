"""Pinned Beaconchain routes, body encoding, failures and manual credentials."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import beaconchain_node as native
from nodes.core.registry import NodeFactory

TOKEN = "beaconchain-test-token-42"
ADDRESS = "0x" + "a" * 40
METRICS = {"operation": "submit_system_metrics", "machine": "validator-1", "timestamp": 1760076662,
    "exporter_version": "1.0", "cpu_cores": 4, "cpu_threads": 8, "memory_node_bytes_total": 100,
    "memory_node_bytes_free": 50, "disk_node_bytes_total": 200, "disk_node_bytes_free": 10}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="beaconchain-test", node_type="automation-beaconchain",
        node_data={"config": config, "credentials": {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}})


def mock(monkeypatch, reply):
    requests = []
    def handle(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", json.loads((Path(__file__).parent / "fixtures/beaconchain/routes.json").read_text()))
async def test_beaconchain_every_read_uses_pinned_route(monkeypatch, case):
    body = {"code": 200, "data": {"rapid": 141086566}} if case["config"]["operation"] == "get_gas_prices" else {"status": "OK", "data": []}
    requests = mock(monkeypatch, body)
    result = await node(case["config"]).execute({})
    assert result["success"] and result["data"] == body["data"]
    assert result["account_identity_verified"] is False
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.host == "beaconcha.in" and requests[0].url.path == case["path"]
    assert requests[0].headers["apikey"] == TOKEN and TOKEN not in str(requests[0].url)
    assert dict(requests[0].url.params) == case["params"]


@pytest.mark.asyncio
async def test_beaconchain_metric_write_exact_body_one_request_no_readback_claim(monkeypatch):
    requests = mock(monkeypatch, {"status": "OK"})
    result = await node(METRICS).run({})
    assert result["submission_acknowledged"] and result["readback_verified"] is False
    assert len(requests) == 1 and requests[0].method == "POST"
    assert requests[0].url.path == "/api/v1/client/metrics"
    assert dict(requests[0].url.params) == {"apikey": TOKEN, "machine": "validator-1"}
    assert json.loads(requests[0].content) == {"version": 2, "process": "system", **{k:v for k,v in METRICS.items() if k not in {"operation", "machine"}}}
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(200, {"status": "ERROR: " + TOKEN}), (200, {}), (200, []), (302, {"status": "OK"}), (401, {"status": "ERROR: key rejected"}), (403, {}), (429, {}), (500, {})])
async def test_beaconchain_failed_responses_never_claim_success_or_leak_key(monkeypatch, status, body):
    requests = mock(monkeypatch, lambda _: httpx.Response(status, json=body, headers={"Location": "https://example.test"}))
    result = await node({"operation": "get_latest_state"}).execute({})
    assert not result["success"] and result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1
    if status == 401:
        assert result["message"] == "ERROR: key rejected"


@pytest.mark.asyncio
async def test_beaconchain_write_timeout_is_unknown_without_retry(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("secret=" + TOKEN, request=request)
    requests = mock(monkeypatch, timeout)
    result = await node(METRICS).execute({})
    assert not result["success"] and result["write_outcome"] == "unknown"
    assert len(requests) == 1 and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_beaconchain_malformed_json_and_redaction(monkeypatch):
    mock(monkeypatch, lambda _: httpx.Response(200, text="not JSON " + TOKEN))
    assert not (await node({"operation": "get_latest_state"}).execute({}))["success"]
    mock(monkeypatch, {"status": "OK", "data": {"nested": [TOKEN]}})
    assert TOKEN not in str(await node({"operation": "get_latest_state"}).execute({}))


@pytest.mark.parametrize("config", [
    {"operation": "get_validators", "validators": "../user"},
    {"operation": "get_validators", "validators": ",".join(["1"]*101)},
    {"operation": "get_epoch", "epoch": "../latestState"},
    {"operation": "get_slot", "slot": "-1"},
    {"operation": "list_address_tokens", "address": ADDRESS, "limit": 201},
    {"operation": "list_balance_history", "validators": "1", "latest_epoch": 1, "offset": 2},
    {"operation": "resolve_ens", "domain": "https://example.test"},
    {"operation": "get_latest_state", "url": "https://example.test"},
    {**METRICS, "memory_node_bytes_free": 101},
    {**METRICS, "timestamp": True},
])
def test_beaconchain_invalid_inputs_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        native.BeaconchainNode.parse_config({"config": config})


def test_beaconchain_manual_connect_default_and_evidence():
    credential = native.BeaconchainAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "beaconchain_api_key"
    assert native.BeaconchainNode.connection_evidence.proves == "reachability"
    assert native.BeaconchainNode.connection_evidence.operation == "get_latest_state"
