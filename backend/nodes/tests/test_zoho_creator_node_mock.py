"""Provider-published Zoho Creator fixtures through the factory and HTTP transport."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs
import httpx
import pytest
from pydantic import ValidationError
from nodes.core.credential_connect import shape_credential, typed_fields
from nodes.core.registry import NODE_REGISTRY
from nodes.core.run_op import run_node_operation
from nodes.oauth.zoho_creator_oauth import OAUTH_PROVIDER
from nodes.zoho_creator_node import OPS, OP_MODELS, ZohoCreatorNode, ZohoCreatorOAuthCredential
from utils import ssrf

FIXTURES = json.loads((Path(__file__).parent / "fixtures/zoho-creator/documented-requests.json").read_text())
AUTH = {"credential_type": "zoho_creator_oauth", "access_token": "fixture-access-token",
    "refresh_token": "fixture-refresh-token", "expires_at": "2099-01-01T00:00:00Z",
    "accounts_server": "https://accounts.zoho.eu", "api_domain": "https://www.zohoapis.eu"}
BASE = AUTH["api_domain"] + "/creator/v2.1"

@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "www.zohoapis.eu"
        assert request.headers["Authorization"] == "Bearer fixture-access-token"
        assert AUTH["access_token"] not in str(request.url)
        return responses.pop(0)
    native = ssrf.guarded_async_client
    monkeypatch.setattr("nodes.zoho_creator_node.guarded_async_client",
        lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, responses

async def run(operation, arguments=None, auth=None):
    return await run_node_operation(node_type="automation-zoho-creator", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(auth or AUTH),
        user_id="00000000-0000-0000-0000-000000000001")

@pytest.mark.parametrize("operation", FIXTURES)
async def test_zoho_creator_documented_examples(operation, transport):
    fixture = FIXTURES[operation]; requests, responses = transport
    responses.append(httpx.Response(200, json=fixture["response"]))
    result = await run(operation, fixture["config"])
    assert len(requests) == 1 and not responses
    request = requests[0]
    assert request.method == fixture["method"]
    assert str(request.url).split("?")[0] == BASE + fixture["path"]
    assert (json.loads(request.content) if request.content else None) == fixture["body"]
    assert result["data"] == fixture["response"] and result["operation"] == operation
    if operation in {"update_records", "delete_records"}:
        assert request.url.params["process_until_limit"] == "false"

async def test_zoho_creator_pagination_and_fields(transport):
    requests, responses = transport
    payload = FIXTURES["list_records"]["response"]
    responses.append(httpx.Response(200, json=payload, headers={"record_cursor": "next-cursor"}))
    result = await run("list_records", {**FIXTURES["list_records"]["config"],
        "criteria": 'Email == "jason@zylker.com"', "max_records": 1000,
        "record_cursor": "previous-cursor", "field_config": "custom", "fields": ["Email", "Name.first_name"]})
    assert result["record_cursor"] == "next-cursor"
    assert requests[0].headers["record_cursor"] == "previous-cursor"
    assert dict(requests[0].url.params) == {"max_records": "1000", "criteria": 'Email == "jason@zylker.com"',
        "field_config": "custom", "fields": "Email,Name.first_name"}
    assert len(requests) == 1

async def test_zoho_creator_partial_batch_result_preserved(transport):
    payload = {"code": 3000, "result": [{"code": 3000, "data": {"ID": "1"}},
        {"code": 3001, "error": ["Mandatory field missing"]}], "more_records": True}
    transport[1].append(httpx.Response(200, json=payload))
    result = await run("add_records", FIXTURES["add_records"]["config"])
    assert result["data"] == payload and "success" not in result

@pytest.mark.parametrize("response", [
    httpx.Response(401, json={"code": 1030, "message": "Authorization Failure"}),
    httpx.Response(200, json={"code": 2945, "message": "Invalid oauthscope"}),
    httpx.Response(429, json={"code": 2955, "message": "API call limit"}),
    httpx.Response(200, text="<html>login</html>"),
    httpx.Response(302, headers={"Location": "https://elsewhere.example"}),
    httpx.Response(200, json=[]), httpx.Response(200, json={}),
])
async def test_zoho_creator_failed_responses(transport, response):
    transport[1].append(response)
    with pytest.raises(ValueError): await run("list_applications")
    assert len(transport[0]) == 1

async def test_zoho_creator_rejection_redacts_tokens(transport):
    transport[1].append(httpx.Response(401, json={"code": 1030,
        "message": "Rejected " + AUTH["access_token"] + " " + AUTH["refresh_token"]}))
    with pytest.raises(ValueError) as error: await run("list_applications")
    assert "Rejected" in str(error.value)
    assert AUTH["access_token"] not in str(error.value) and AUTH["refresh_token"] not in str(error.value)

@pytest.mark.parametrize("bad", ["../data", ".", "..", "a/b", "a%2fb", "x?y", "a#b", "https://evil.example", "a\n"])
def test_zoho_creator_resource_injection(bad):
    with pytest.raises(ValidationError): OP_MODELS["get_record"](**{**FIXTURES["get_record"]["config"], "record_id": bad})

@pytest.mark.parametrize("field,bad", [
    ("api_domain", "https://www.zohoapis.com.evil.example"), ("api_domain", "https://www.zohoapis.eu/path"),
    ("api_domain", "http://www.zohoapis.eu"), ("api_domain", "https://user:pass@www.zohoapis.eu"),
    ("accounts_server", "https://evil.example"), ("accounts_server", "https://accounts.zoho.com:443"),
])
def test_zoho_creator_region_allowlist(field, bad):
    with pytest.raises(ValidationError): ZohoCreatorOAuthCredential(**{**AUTH, field: bad})

def test_zoho_creator_registration_scopes_and_manual_connect():
    assert NODE_REGISTRY["automation-zoho-creator"] is ZohoCreatorNode and len(OPS) == 17
    assert set(ZohoCreatorNode.scope_registry._requirements) == set(OPS)
    assert ZohoCreatorNode.connection_evidence.operation == "list_applications"
    schema = ZohoCreatorNode.get_config_schema()
    assert len(schema["properties"]["config"]["oneOf"]) == 17
    credential = schema["$defs"]["ZohoCreatorOAuthCredential"]
    assert set(credential["x-oauth-scopes"]) == set(ZohoCreatorNode.scope_registry.declared_scopes())
    assert credential["x-oauth-provider"] == OAUTH_PROVIDER.provider
    assert {f["name"] for f in typed_fields("zoho_creator_oauth")} == set(AUTH) - {"credential_type"}
    shaped, errors, _ = shape_credential("zoho_creator_oauth", {k:v for k,v in AUTH.items() if k != "credential_type"})
    assert not errors and shaped["api_domain"] == AUTH["api_domain"]
    assert ZohoCreatorOAuthCredential(**shaped).credential_type == "zoho_creator_oauth"

@pytest.mark.parametrize("operation", ["update_records", "delete_records"])
def test_zoho_creator_mutations_require_criteria(operation):
    values = dict(FIXTURES[operation]["config"]); values.pop("criteria")
    with pytest.raises(ValidationError): OP_MODELS[operation](**values)

def test_zoho_creator_required_update_and_custom_fields():
    with pytest.raises(ValidationError): OP_MODELS["update_record"](**{**FIXTURES["update_record"]["config"], "data": {}})
    with pytest.raises(ValidationError): OP_MODELS["list_records"](**FIXTURES["list_records"]["config"], field_config="custom")

async def test_zoho_creator_regional_identity_and_refresh(monkeypatch):
    from nodes.core import oauth_refresh
    monkeypatch.setenv("ZOHO_CREATOR_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("ZOHO_CREATOR_CLIENT_SECRET", "fixture-secret")
    def respond(request):
        assert request.url.host == "accounts.zoho.eu"
        if request.url.path == "/oauth/user/info":
            assert request.headers["Authorization"] == "Bearer fixture-access-token"
            return httpx.Response(200, json={"Email": "person@example.test"})
        assert request.url.path == "/oauth/v2/token"
        assert parse_qs(request.content.decode()) == {"grant_type": ["refresh_token"],
            "refresh_token": ["fixture-refresh-token"], "client_id": ["fixture-client"], "client_secret": ["fixture-secret"]}
        return httpx.Response(200, json={"access_token": "fresh-access", "expires_in": 3600,
            "api_domain": "https://www.zohoapis.eu"})
    native = httpx.AsyncClient
    monkeypatch.setattr("utils.ssrf.guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(respond)))
    assert await OAUTH_PROVIDER.account_name(AUTH["access_token"], context={k:AUTH[k] for k in ("accounts_server", "api_domain")}) == "person@example.test"
    result = await OAUTH_PROVIDER.bind_refresh(AUTH)(AUTH["refresh_token"])
    assert result.access_token == "fresh-access"
    captured = {}
    async def freshen(data, **kwargs): captured.update(kwargs); return data
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", freshen)
    await ZohoCreatorNode.freshen_credential(AUTH)
    assert captured["provider"] == "zoho_creator"
    assert set(captured["additional_token_fields"]) == {"accounts_server", "api_domain"}

async def test_zoho_creator_connection_evidence_shows_real_app_names(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport[1].append(httpx.Response(200, json=FIXTURES["list_applications"]["response"]))
    result = await collect_evidence(node_type="automation-zoho-creator", credential_data=AUTH,
        user_id="00000000-0000-0000-0000-000000000001")
    assert result.reachable is True
    assert result.samples[0].label == "Zylker Store"
    assert len(transport[0]) == 1
