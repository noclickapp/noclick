"""Check all Vast.ai requests against independent wire fixtures without signing in.

Regression cases cover pagination, connection proof, provider failures and secret
handling so a successful HTTP call alone cannot masquerade as an account.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import vast_ai_node as native
from nodes.core.registry import NodeFactory

TOKEN = "vast-synthetic-api-key-for-tests"
CASES = json.loads((Path(__file__).parent / "fixtures/vast-ai/wire_cases.json").read_text())["cases"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(
        node_id="vast-ai-test", node_type="automation-vast-ai",
        node_data={"config": config, "credentials": credentials or {"credential_type": "vast_ai_api_key", "api_key": TOKEN}},
    )


def transport(monkeypatch, body, status=200, raw=None, error=None):
    seen = []
    original = httpx.AsyncClient

    def reply(request):
        seen.append(request)
        if error:
            raise error(TOKEN, request=request)
        return httpx.Response(status, content=raw) if raw is not None else httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[row["config"]["operation"] for row in CASES])
async def test_vast_ai_wire_contract(monkeypatch, case):
    seen = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "action": case["config"]["operation"], "data": case["response"]}
    assert len(seen) == 1
    req = seen[0]
    assert req.method == case["method"]
    assert req.url.host == "console.vast.ai" and req.url.path == case["path"]
    assert dict(req.url.params) == case["query"]
    assert (json.loads(req.content) if req.content else None) == case["body"]
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_vast_ai_error_preserves_message_and_redacts_key(monkeypatch, status):
    seen = transport(monkeypatch, {"success": False, "msg": "Rejected " + TOKEN}, status)
    with pytest.raises(ValueError, match=f"Vast.ai HTTP {status}: Rejected \\[redacted\\]"):
        await node({"operation": "get_current_user"}).execute({})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_vast_ai_http_200_error_is_failure(monkeypatch):
    transport(monkeypatch, {"success": False, "error": "Invalid date range"})
    with pytest.raises(ValueError, match="Invalid date range"):
        await node({"operation": "list_charges", "start_time": 1, "end_time": 2}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"id": True, "email": "user@example.com"}, {"id": 123}])
async def test_vast_ai_malformed_identity_cannot_prove_connection(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="recognisable account"):
        await node({"operation": "get_current_user"}).execute({})


@pytest.mark.asyncio
async def test_vast_ai_non_json_error_does_not_echo_body(monkeypatch):
    transport(monkeypatch, None, raw=("<html>" + TOKEN).encode())
    with pytest.raises(ValueError, match="without a JSON response") as exc:
        await node({"operation": "get_current_user"}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_vast_ai_write_timeout_is_never_retried(monkeypatch):
    seen = transport(monkeypatch, None, error=httpx.ReadTimeout)
    with pytest.raises(ValueError, match="inspect the provider before retrying") as exc:
        await node({"operation": "destroy_instance", "instance_id": 1234}).execute({})
    assert len(seen) == 1 and TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_vast_ai_cursor_is_preserved_without_fetching_more(monkeypatch):
    transport(monkeypatch, {"success": True, "instances": [], "next_token": "opaque-next"})
    result = await node({"operation": "list_instances"}).execute({})
    assert result["data"]["next_token"] == "opaque-next"


@pytest.mark.parametrize("value", ["Bearer key", "https://cloud.vast.ai", "<token>", "key\r\nInjected:yes", "ke\u200by"])
def test_vast_ai_manual_credential_rejects_bad_pastes(value):
    with pytest.raises(ValueError):
        native.VastAiAPIKeyCredential(api_key=value)


@pytest.mark.parametrize("config", [
    {"operation": "manage_instance", "instance_id": 1234},
    {"operation": "get_instance", "instance_id": "../other"},
    {"operation": "get_instance", "instance_id": 0},
    {"operation": "change_bid", "instance_id": 1234, "price": 33},
    {"operation": "list_charges", "start_time": 2, "end_time": 1},
    {"operation": "create_ssh_key", "ssh_key": "-----BEGIN PRIVATE KEY-----"},
])
def test_vast_ai_invalid_configuration(config):
    with pytest.raises(ValueError):
        node(config)


def test_vast_ai_manual_default_and_operation_coverage():
    assert native.VastAiAPIKeyCredential(api_key="  " + TOKEN + "\n").credential_type == "vast_ai_api_key"
    assert {row["config"]["operation"] for row in CASES} == set(native.ROUTES)
    assert native.VastAiNode.connection_evidence.identity_operation == "get_current_user"
