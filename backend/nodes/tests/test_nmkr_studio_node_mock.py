"""Offline NMKR Studio wire, parser, connect and mutation regressions."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import nmkr_studio_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence

KEY = "synthetic-nmkr-key-42"
CREDENTIAL = {"credential_type": native.CREDENTIAL_TYPE, "api_key": KEY}
CASES = json.loads((Path(__file__).parent / "fixtures/nmkr-studio/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    # These tests have no database access.
    yield


def node(config):
    return NodeFactory.create_node(node_id="nmkr-test", node_type="automation-nmkr-studio",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, reply):
    requests = []
    def handle(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_nmkr_studio_wire_contract(monkeypatch, case):
    requests = transport(monkeypatch, lambda req: httpx.Response(200) if case["response"] is None else httpx.Response(200, json=case["response"]))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and KEY not in str(result)
    assert len(requests) == 1  # Including mutating GETs and mints: never retry.
    req = requests[0]
    assert req.method == case["method"]
    assert req.url.host == "studio-api.nmkr.io" and req.url.scheme == "https"
    assert req.url.path == case["path"]
    assert req.headers["Authorization"] == "Bearer " + KEY
    if case["body"] is not None:
        assert req.headers["Content-Type"] == "application/json"
        assert json.loads(req.content) == case["body"]
    else:
        assert req.content == b""


@pytest.mark.asyncio
async def test_nmkr_studio_query_and_page_continuation(monkeypatch):
    requests = transport(monkeypatch, [{"projectname": "Example", "uid": "owned"}] * 2)
    result = await node({"operation": "list_projects", "count": 2, "page": 3, "optionalSortOrder": "name_desc"}).execute({})
    assert requests[0].url.path == "/v2/ListProjects/2/3"
    assert dict(requests[0].url.params) == {"optionalSortOrder": "name_desc"}
    assert result["next_page"] == 4 and result["page"] == 3
    requests = transport(monkeypatch, [])
    result = await node({"operation": "list_nfts", "projectuid": "owned", "state": "sold", "orderby": "id"}).execute({})
    assert requests[0].url.path == "/v2/GetNfts/owned/sold/50/1"
    assert dict(requests[0].url.params) == {"orderby": "id"}
    assert result["next_page"] is None
    requests = transport(monkeypatch, [])
    await node({"operation": "get_pricelist", "projectuid": "owned", "returnAllPrices": True}).execute({})
    assert dict(requests[0].url.params) == {"returnAllPrices": "true"}
    requests = transport(monkeypatch, [])
    await node({"operation": "list_project_transactions", "projectuid": "owned", "fromdate": "2026-10-01T00:00:00Z", "todate": "2026-10-02T00:00:00Z"}).execute({})
    assert dict(requests[0].url.params) == {"fromdate": "2026-10-01T00:00:00+00:00", "todate": "2026-10-02T00:00:00+00:00"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["replace_pricelist", "replace_discounts", "replace_notifications", "replace_sale_conditions"])
async def test_nmkr_studio_clear_lists_sends_empty_array(monkeypatch, operation):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=[]) if operation == "replace_notifications" else httpx.Response(200))
    result = await node({"operation": operation, "projectuid": "owned", "entries": []}).execute({})
    assert result["status"] == "success" and json.loads(requests[0].content) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 406, 429, 500])
async def test_nmkr_studio_http_failure_is_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={"errorMessage": "Rejected " + KEY}, headers={"Location": "https://other.test/"}))
    result = await node({"operation": "mint_and_send_random", "projectuid": "owned", "countnft": 1, "receiveraddress": "addr_receiver"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert KEY not in str(result) and "Rejected" in result["error"] and len(requests) == 1


@pytest.mark.asyncio
async def test_nmkr_studio_error_envelope_and_secret_redaction(monkeypatch):
    transport(monkeypatch, {"resultState": "Error", "errorCode": 5, "errorMessage": "Metadata invalid"})
    result = await node({"operation": "check_metadata", "nftuid": "owned"}).execute({})
    assert result["status"] == "error" and result["error"] == "Metadata invalid"
    transport(monkeypatch, [{"projectname": "Project " + KEY, "uid": "one"}])
    result = await node({"operation": "list_projects"}).execute({})
    assert KEY not in str(result) and "[redacted]" in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, None, "text"])
async def test_nmkr_studio_wrong_response_shape_fails(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_projects"}).execute({})


@pytest.mark.asyncio
async def test_nmkr_studio_connection_evidence(monkeypatch):
    requests = transport(monkeypatch, [{"projectname": "My collection", "uid": "owned"}])
    result = await collect_evidence(node_type="automation-nmkr-studio", credential_data=CREDENTIAL, user_id="nmkr-test")
    assert result.reachable is True and "My collection" in str(result)
    assert len(requests) == 1 and requests[0].url.path.startswith("/v2/ListProjects/")


def test_nmkr_studio_manual_credential_default_and_schema():
    credential = native.NmkrStudioAPIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == native.CREDENTIAL_TYPE and credential.api_key == KEY
    assert KEY not in repr(credential) and len(native.ROUTES) == 24
    schema = native.NmkrStudioConfig.model_json_schema()
    assert schema["$defs"]["NmkrStudioAPIKeyCredential"]["properties"]["api_key"]["ui:widget"] == "password"
    for value in ["Bearer abc", "https://studio.nmkr.io/key", "<token>", "key\nheader"]:
        with pytest.raises((ValueError, ValidationError)):
            native.NmkrStudioAPIKeyCredential(api_key=value)


@pytest.mark.parametrize("config", [
    {"operation": "get_project", "projectuid": "../other"},
    {"operation": "get_nft", "nftuid": "nft?other"},
    {"operation": "list_nfts", "projectuid": "one", "count": 101},
    {"operation": "list_projects", "page": 0},
    {"operation": "set_nft_blocked", "nftuid": "one", "blockNft": "yes"},
    {"operation": "replace_notifications", "projectuid": "one", "entries": [{"notificationType": "sms"}]},
    {"operation": "replace_pricelist", "projectuid": "one", "entries": [{"currency": None}]},
    {"operation": "get_project", "projectuid": "one", "extra_params": {"admin": True}},
])
def test_nmkr_studio_invalid_configs(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)
