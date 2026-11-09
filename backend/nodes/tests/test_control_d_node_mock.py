"""Exercise Control D requests through the real node factory and HTTP transport.

Fixtures preserve the pinned provider examples where available; unmodelled
responses are explicitly marked synthetic, never claimed as provider evidence.
"""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import control_d_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence

TOKEN = "synthetic-control-d-token-42"
CASES = json.loads((Path(__file__).parent / "fixtures/control-d/contract_examples.json").read_text())["operations"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="control-d-test", node_type="automation-control-d",
        node_data={"config": config, "credentials": {"credential_type": native.CREDENTIAL_TYPE, "api_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(CASES))
async def test_control_d_contract_requests_and_response_examples(monkeypatch, operation):
    case = CASES[operation]
    requests = transport(monkeypatch, case["response"])
    result = await node({"operation": operation, **case["config"]}).execute({})
    assert result["status"] == "success"
    assert result["data"] == case["response"]["body"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.scheme == "https" and request.url.host == "api.controld.com"
    assert request.url.path == case["path"] and not request.url.query
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    form = parse_qs(request.content.decode(), keep_blank_values=True)
    expected = {k: [str(x) for x in (v if isinstance(v, list) else [v])] for k,v in case["form"].items()}
    assert form == (expected if request.method in {"POST", "PUT"} else {})


@pytest.mark.asyncio
async def test_control_d_repeated_hostnames_zero_and_empty_comment(monkeypatch):
    requests = transport(monkeypatch, {"success": True, "body": []})
    await node({"operation": "update_rules", "profile_id": "abcd123", "do": 0, "status": 0,
        "hostnames[]": ["domain1.com", "domain2.com"], "clear_comment": True, "group": 0}).execute({})
    assert parse_qs(requests[0].content.decode(), keep_blank_values=True) == {
        "do": ["0"], "status": ["0"], "hostnames[]": ["domain1.com", "domain2.com"], "comment": [""], "group": ["0"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {"message": "Token rejected"}),
    (403, {"message": "Write access required"}), (302, {"message": "Moved"}),
    (200, {"success": False, "message": "Profile is locked"})])
async def test_control_d_rejection_is_error_without_follow_or_retry(monkeypatch, status, payload):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json=payload))
    result = await node({"operation": "list_profiles"}).execute({})
    assert result["status"] == "error" and payload["message"] in result["error"]
    assert len(requests) == 1 and "data" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"success": "true", "body": []}, {"success": True}, []])
async def test_control_d_malformed_envelopes_fail(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError, match="Control D"):
        await node({"operation": "list_profiles"}).execute({})


@pytest.mark.parametrize("value", ["https://controld.com", "Bearer abc", "bad\r\nheader", "<token>", "héllo"])
def test_control_d_manual_token_refuses_bad_pastes(value):
    with pytest.raises(ValidationError):
        native.ControlDAPITokenCredential(api_token=value)


def test_control_d_manual_token_has_default_type_and_normalizes_paste():
    c = native.ControlDAPITokenCredential(api_token="  " + TOKEN + "\n")
    assert c.credential_type == native.CREDENTIAL_TYPE and c.api_token == TOKEN


@pytest.mark.asyncio
async def test_control_d_path_value_cannot_change_origin(monkeypatch):
    requests = transport(monkeypatch, {"success": True, "body": []})
    await node({"operation": "delete_profile", "profile_id": "id/../../users?x=1#fragment"}).execute({})
    assert requests[0].url.host == "api.controld.com" and not requests[0].url.query
    assert requests[0].url.raw_path == b"/profiles/id%2F..%2F..%2Fusers%3Fx%3D1%23fragment"
    for value in [".", ".."]:
        with pytest.raises(ValueError):
            await node({"operation": "delete_profile", "profile_id": value}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "update_profile", "profile_id": "abc"},
    {"operation": "update_device", "device_id": "abc"},
    {"operation": "create_rules", "profile_id": "abc", "do": 0, "status": 1, "hostnames[]": []},
    {"operation": "update_default_rule", "profile_id": "abc", "do": 3, "status": 1},
])
def test_control_d_incomplete_writes_fail_before_network(config):
    with pytest.raises(ValidationError):
        native.ControlDFullConfig(config=config)


@pytest.mark.asyncio
async def test_control_d_connect_uses_account_profiles_and_identity(monkeypatch):
    from nodes.core import run_op
    async def run_operation(**kwargs):
        return await node({"operation": kwargs["operation"]}).execute({})
    # Exercise the evidence collector without saved credentials or a database.
    monkeypatch.setattr(run_op, "run_node_operation", run_operation)
    requests = transport(monkeypatch, CASES["list_profiles"]["response"])
    result = await collect_evidence(node_type="automation-control-d", user_id="test-user", credential_data={"credential_type": native.CREDENTIAL_TYPE, "api_token": TOKEN})
    assert result.reachable is True and result.samples
    assert [r.url.path for r in requests] == ["/profiles"]


@pytest.mark.asyncio
async def test_control_d_empty_account_uses_identity_and_rejection_never_connects(monkeypatch):
    from nodes.core import run_op
    async def run_operation(**kwargs):
        return await node({"operation": kwargs["operation"]}).execute({})
    monkeypatch.setattr(run_op, "run_node_operation", run_operation)
    def reply(request):
        return httpx.Response(200, json={"success": True, "body": {"profiles": []}} if request.url.path == "/profiles" else CASES["get_user"]["response"])
    requests = transport(monkeypatch, reply)
    result = await collect_evidence(node_type="automation-control-d", user_id="test-user",
        credential_data={"credential_type": native.CREDENTIAL_TYPE, "api_token": TOKEN})
    assert result.reachable is True and result.account_label == "username@email.com"
    assert [r.url.path for r in requests] == ["/profiles", "/users"]
    requests = transport(monkeypatch, lambda r: httpx.Response(401, json={"message": "Invalid token"}))
    result = await collect_evidence(node_type="automation-control-d", user_id="test-user",
        credential_data={"credential_type": native.CREDENTIAL_TYPE, "api_token": TOKEN})
    assert result.reachable is False and "Invalid token" in result.error
    assert len(requests) == 1
