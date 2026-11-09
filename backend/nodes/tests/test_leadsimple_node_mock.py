"""Exercise LeadSimple's native factory against a local HTTP transport.

These regressions verify form encoding, one-page semantics, manual credentials
and rejection handling without a provider account or real writes.
"""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError
from nodes import leadsimple_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-leadsimple-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="leadsimple-test", node_type="automation-leadsimple",
        node_data={"config": config, "credentials": credential or {"api_token": TOKEN}})


def transport(monkeypatch, payload=None, status=200, callback=None):
    requests = []
    def respond(request):
        requests.append(request)
        return callback(request) if callback else httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_bearer_account_identity_and_manual_default(monkeypatch):
    requests = transport(monkeypatch, {"uid": "acct_123", "name": "Example Management"})
    result = await node({"operation": "get_account"}).run({})
    assert result["data"]["name"] == "Example Management"
    assert str(requests[0].url) == "https://api.leadsimple.com/rest/info/account"
    assert requests[0].headers["authorization"] == "Bearer " + TOKEN
    assert native.LeadSimpleTokenCredential(api_token=TOKEN).credential_type == "leadsimple_api_token"
    assert native.LeadSimpleNode.connection_evidence.identity_operation == "get_account"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,form,status", [
    ({"operation": "create_contact", "first_name": "François + Ada", "email_addresses": ["a@example.test", "b@example.test"]},
     "POST", "/contacts", {"first_name": ["François + Ada"], "email_addresses[]": ["a@example.test", "b@example.test"]}, 201),
    ({"operation": "create_deal", "deal_pipeline_id": "pipe_123", "deal_stage_id": "stage_123", "contact_full_name": "Ada Example", "deal_accept_duplicates": False},
     "POST", "/deals", {"deal[pipeline_id]": ["pipe_123"], "deal[stage_id]": ["stage_123"], "contact[full_name]": ["Ada Example"], "deal[accept_duplicates]": ["false"]}, 201),
    ({"operation": "update_deal", "deal_id": "deal_123", "pipeline_id": "pipe_123", "tags": ["won"], "remove_tags": False},
     "PUT", "/deals/deal_123", {"pipeline_id": ["pipe_123"], "tags[]": ["won"], "remove_tags": ["false"]}, 200),
    ({"operation": "create_process", "process_process_type_id": "type_123", "process_stage_id": "stage_123", "property_ids": ["prop_1", "prop_2"]},
     "POST", "/processes", {"process[process_type_id]": ["type_123"], "process[stage_id]": ["stage_123"], "property_ids[]": ["prop_1", "prop_2"]}, 201),
    ({"operation": "create_note", "parent_id": "process_123", "parent_type": "Process", "description": "Follow up"},
     "POST", "/notes", {"parent_id": ["process_123"], "parent_type": ["Process"], "description": ["Follow up"]}, 201),
])
async def test_documented_form_encodings(monkeypatch, config, method, path, form, status):
    requests = transport(monkeypatch, {"id": "owned_123"}, status)
    assert (await node(config).run({}))["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == "/rest" + path
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(req.content.decode()) == form


@pytest.mark.asyncio
async def test_list_single_page_and_filters(monkeypatch):
    body = [{"id": "contact_123", "emails": ["ada@example.test"], "custom_fields": None}]
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_contacts", "page": 2, "per_page": 100,
        "search": "Ada + Example", "include_custom_fields": True, "updated_since": 1700000000}).run({})
    assert result["data"] == body and result["pagination"] == {"page": 2, "per_page": 100, "complete": False}
    assert dict(requests[0].url.params) == {"page": "2", "per_page": "100", "search": "Ada + Example",
        "include_custom_fields": "true", "updated_since": "1700000000"}
    assert len(requests) == 1


CASES = json.loads((Path(__file__).parent / "fixtures/leadsimple/contract.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_all_fixed_operations(monkeypatch, case):
    schema = native.LeadSimpleFullConfig.model_json_schema()
    member = next(v for v in schema["$defs"].values() if
        v.get("properties", {}).get("operation", {}).get("const") == case["operation"])
    config = {"operation": case["operation"]}
    for key in member.get("required", []):
        config[key] = member["properties"][key].get("enum", ["owned_123"])[0]
    for op, key in {"create_contact": "first_name", "update_contact": "first_name",
                    "update_process": "name", "update_property": "address_city"}.items():
        if case["operation"] == op:
            config[key] = "Example"
    requests = transport(monkeypatch, {"id": "owned_123", "name": "Example"}, case["status"])
    assert (await node(config).run({}))["status"] == "success"
    assert len(requests) == 1 and requests[0].method == case["method"]
    path = case["path"]
    for field in case["path_fields"]:
        path = path.replace("{" + field + "}", config[field])
    assert requests[0].url.path == "/rest" + path


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 422, 429, 500])
async def test_provider_rejections_and_secret_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "get_account"}).run({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected [redacted]"}
    assert len(requests) == 1 and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"errors": ["Invalid token"]}, {"error": "Not allowed"}, "not an account"])
async def test_unexpected_or_error_json(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "get_account"}).run({}))["status"] == "error"


@pytest.mark.asyncio
async def test_invalid_json_and_timeout(monkeypatch):
    transport(monkeypatch, callback=lambda r: httpx.Response(200, text="<html>sign in</html>"))
    assert (await node({"operation": "get_account"}).run({}))["status"] == "error"
    def timeout(request):
        raise httpx.ReadTimeout("Contains " + TOKEN, request=request)
    transport(monkeypatch, callback=timeout)
    result = await node({"operation": "get_account"}).run({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.parametrize("config", [
    {"operation": "get_deal", "deal_id": "../foreign"},
    {"operation": "get_property", "property_id": "x?api_key=secret"},
    {"operation": "list_contacts", "page": 0}, {"operation": "list_contacts", "per_page": 201},
    {"operation": "list_deals", "include_custom_fields": True, "per_page": 101},
    {"operation": "create_deal"}, {"operation": "update_deal", "deal_id": "owned_123"},
    {"operation": "create_process", "process_process_type_id": "owned_123"},
    {"operation": "create_note", "parent_type": "Account", "parent_id": "owned_123", "description": "hello"},
    {"operation": "custom_request", "url": "https://foreign.test"},
])
def test_invalid_inputs_fail_before_http(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


@pytest.mark.parametrize("value", ["https://api.leadsimple.com", "Bearer secret", "<token>", "  "])
def test_invalid_credentials(value):
    with pytest.raises((ValidationError, ValueError)):
        native.LeadSimpleTokenCredential(api_token=value)


def test_foreign_credential_type_is_not_adopted():
    with pytest.raises((ValidationError, ValueError)):
        node({"operation": "get_account"}, {"credential_type": "another_api_key", "api_token": TOKEN})
    result = native.LeadSimpleNode.validate_config({"config": {"operation": "get_account"},
        "credentials": {"credential_type": "another_api_key", "api_token": TOKEN}})
    assert result["valid"] is False
