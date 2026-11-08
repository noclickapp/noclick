"""HTTP boundary tests for Raisely's published request and response envelopes."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import raisely_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/raisely/requests.json").read_text())["cases"]
SECRET = "synthetic-raisely-api-key-1234"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="raisely-test", node_type="automation-raisely", node_data={
        "config": config, "credentials": {"credential_type": "raisely_api_key", "api_key": SECRET},
    })


def transport(monkeypatch, respond):
    requests = []
    def handler(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_contract_request(monkeypatch, case):
    operation = case["config"]["operation"]
    many = operation.startswith("list_") or operation in {"add_tag_record", "remove_tag_record"}
    record = {"uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "fullName": "Leila Norma de Lima", "accessToken": "never-output-this"}
    payload = {"data": [record] if many else record}
    if operation.startswith("list_"):
        payload["pagination"] = {"total": 1, "limit": 50, "offset": 0, "nextUrl": False}
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    result = await node(case["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.raisely.com"
    assert request.url.path == "/v3" + case["path"]
    assert dict(request.url.params) == case["params"]
    assert request.headers["Authorization"] == "Bearer " + SECRET
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert result["data"] == ([{"uuid": record["uuid"], "fullName": record["fullName"]}] if many else {"uuid": record["uuid"], "fullName": record["fullName"]})
    assert "never-output-this" not in json.dumps(result)


def test_every_operation_has_a_contract_case():
    assert {c["config"]["operation"] for c in CASES} == set(native.OPERATIONS)


@pytest.mark.asyncio
async def test_pagination_never_follows_provider_url(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"data": [], "pagination": {
        "nextUrl": "https://untrusted.example/steal", "total": 200, "offset": 100, "limit": 25,
    }}))
    result = await node({"operation": "list_users", "offset": 100, "limit": 25}).execute({})
    assert result["next_offset"] == 125
    assert result["has_more"] is True
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {}, "errors": ["bad"]}, {"data": []}])
async def test_bad_envelope_fails(monkeypatch, payload):
    transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await node({"operation": "check_connection"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_http_failure_retains_provider_rejection_without_secret(monkeypatch, status):
    transport(monkeypatch, lambda r: httpx.Response(status, text="Token rejected: " + SECRET))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "check_connection"}).execute({})
    assert "Token rejected" in str(exc.value)
    assert SECRET not in str(exc.value)


@pytest.mark.parametrize("config", [
    {"operation": "get_user", "user_id": "../users"},
    {"operation": "get_profile", "profile_path": "bobd?private=true"},
    {"operation": "list_profiles"}, {"operation": "list_users", "limit": 0},
    {"operation": "list_users", "offset": -1}, {"operation": "create_user"},
    {"operation": "list_users", "arbitrary": "injected"},
])
def test_invalid_configuration(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


@pytest.mark.asyncio
async def test_empty_update_does_not_send_a_request(monkeypatch):
    requests = transport(monkeypatch, lambda r: pytest.fail("unexpected request"))
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_user", "user_id": "valid-user"}).execute({})
    assert requests == []


def test_credential_shaping_and_family():
    assert native.RaiselyAPIKeyCredential(api_key="  " + SECRET + "  ").api_key == SECRET
    for key in ("https://example.com", "Bearer " + SECRET):
        with pytest.raises(ValidationError):
            native.RaiselyAPIKeyCredential(api_key=key)
    with pytest.raises(ValidationError):
        native.RaiselyAPIKeyCredential(api_key=SECRET, credential_type="other_api_key")
