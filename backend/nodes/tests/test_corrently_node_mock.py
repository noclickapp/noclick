"""Offline request and response checks for the pinned Corrently v2 contract."""
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import corrently_node as mod
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "corrently_meter_secret", "account": "0xfixture", "secret": "existing-meter-password"}

@pytest.fixture
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="corrently-test", node_type="automation-corrently", node_data={"config": config, "credentials": AUTH})

@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(mod.ROUTES))
async def test_corrently_contract_routes(operation, monkeypatch):
    client = AsyncMock()
    client.request.return_value = httpx.Response(200, json={"reading": 42})
    @asynccontextmanager
    async def connect(**kwargs):
        assert kwargs["follow_redirects"] is False
        yield client
    monkeypatch.setattr(mod, "guarded_async_client", connect)
    config = {"operation": operation}
    if operation == "post_meter_reading":
        config.update(energy=12345, zip="69256")
    elif operation == "get_best_hour":
        config.update(zip="69256", hours=2, timeframe=24)
    result = await node(config).execute({})
    assert result == {"status": "success", "data": {"reading": 42}}
    args, kwargs = client.request.call_args
    method, path = mod.ROUTES[operation]
    assert args == (method, mod.BASE + path)
    assert AUTH["secret"] not in args[1]
    if operation == "post_meter_reading":
        assert kwargs["json"] == {"account": AUTH["account"], "secret": AUTH["secret"], "energy": 12345, "zip": "69256"}
        assert kwargs["params"] == {}
    else:
        assert kwargs["json"] is None
        assert AUTH["secret"] not in json.dumps(kwargs)
        if operation in {"get_balances", "get_meter_reading"}:
            assert kwargs["params"] == {"account": AUTH["account"]}
        if operation == "get_best_hour":
            assert kwargs["params"] == {"zip": "69256", "hours": 2, "timeframe": 24}

@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(401, json={"secret": AUTH["secret"]}), httpx.Response(200, text="not json"), httpx.Response(200, json={"error": "denied"})])
async def test_corrently_failures_do_not_claim_success(response, monkeypatch):
    client = AsyncMock()
    client.request.return_value = response
    @asynccontextmanager
    async def connect(**kwargs):
        yield client
    monkeypatch.setattr(mod, "guarded_async_client", connect)
    result = await node({"operation": "get_balances"}).execute({})
    assert result["status"] == "error"
    assert AUTH["secret"] not in json.dumps(result)

@pytest.mark.asyncio
async def test_corrently_redacts_echoed_secret(monkeypatch):
    client = AsyncMock()
    client.request.return_value = httpx.Response(200, json={"secret": AUTH["secret"], "nested": [AUTH["secret"]]})
    @asynccontextmanager
    async def connect(**kwargs):
        yield client
    monkeypatch.setattr(mod, "guarded_async_client", connect)
    result = await node({"operation": "get_balances"}).execute({})
    assert result["data"] == {"nested": ["[redacted]"]}


def test_corrently_manual_credential_has_default_type():
    credential = mod.CorrentlyMeterCredential.model_validate({k:v for k,v in AUTH.items() if k != "credential_type"})
    assert credential.credential_type == "corrently_meter_secret"
