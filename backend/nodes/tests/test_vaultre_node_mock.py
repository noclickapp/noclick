"""Wire-level contract tests with authored account data; no live credentials."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

import nodes.vaultre_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/vaultre/operations.json").read_text())["cases"]
CREDENTIAL = {"credential_type": "vaultre_api_key", "api_key": "integrator-secret-key", "access_token": "account-secret-token"}


def node(config):
    return NodeFactory.create_node(node_id="vaultre-test", node_type="automation-vaultre", node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, respond):
    requests = []
    def handler(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["http2"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_each_operation_has_exactly_one_published_request(monkeypatch, case):
    config = {"operation": case["operation"], **case["config"]}
    paged = case["operation"].startswith("list_") or case["operation"] == "search_contacts"
    body = {"items": [{"id": 123, "displayName": "Jane Doe"}], "totalItems": 25, "totalPages": 3, "urls": {"next": "https://foreign.test/steal"}} if paged else {"id": 123, "name": "My agency"}
    if case["operation"] in {"complete_task", "uncomplete_task"}:
        body = {"success": True, "msg": "Task updated"}
    requests = transport(monkeypatch, lambda _: httpx.Response(case["status"], json=body) if case["status"] != 204 else httpx.Response(204))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"]
    assert req.url.host == "ap-southeast-2.api.vaultre.com.au"
    assert req.url.path == "/api/v1.3" + case["path"]
    assert dict(req.url.params) == case["query"]
    assert req.headers["X-Api-Key"] == CREDENTIAL["api_key"]
    assert req.headers["Authorization"] == "Bearer " + CREDENTIAL["access_token"]
    assert (json.loads(req.content) if req.content else None) == case["body"]
    if case["body"] is not None:
        assert req.headers["Content-Type"] == "application/json"
    if paged:
        assert result["has_more"] is True
        assert result["next_page"] == config.get("page", 1) + 1
    if case["status"] == 204:
        assert result["deleted"] is True


@pytest.mark.asyncio
async def test_filters_preserve_false_values_and_documented_names(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"items": [], "totalPages": 1, "totalItems": 0}))
    result = await node({"operation": "list_tasks", "user_id": 7, "completed": False, "starting_after": "2026-11-10T00:00:00Z"}).execute({})
    assert dict(requests[0].url.params) == {"page": "1", "pagesize": "50", "userid": "7", "completed": "false", "startingAfter": "2026-11-10T00:00:00Z"}
    assert result["has_more"] is False and result["next_page"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_provider_failure_is_not_success_and_does_not_leak_secrets(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={"msg": "Rejected " + CREDENTIAL["access_token"] + " " + CREDENTIAL["api_key"]}, headers={"Location": "https://foreign.test/"}))
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert len(requests) == 1
    assert all(secret not in str(result) for secret in (CREDENTIAL["api_key"], CREDENTIAL["access_token"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"success": False, "msg": "Permission denied"}, [], {"items": "wrong"}, {"items": ["wrong"]}])
async def test_error_envelopes_and_malformed_lists_fail(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    assert (await node({"operation": "list_contacts"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_missing_pagination_metadata_remains_unknown(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={"items": []}))
    result = await node({"operation": "list_contacts"}).execute({})
    assert result["has_more"] is None and result["next_page"] is None


@pytest.mark.asyncio
async def test_transport_failure_never_claims_write_completion(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("private diagnostic " + CREDENTIAL["api_key"], request=request)
    requests = transport(monkeypatch, timeout)
    result = await node({"operation": "delete_contact", "contact_id": 123}).execute({})
    assert result["status"] == "error" and "deleted" not in result
    assert len(requests) == 1 and CREDENTIAL["api_key"] not in str(result)


def test_manual_credential_defaults_and_required_fields():
    model = native.VaultREAPIKeyCredential
    value = model.model_validate({"api_key": CREDENTIAL["api_key"], "access_token": CREDENTIAL["access_token"]})
    assert value.credential_type == "vaultre_api_key"
    schema = model.model_json_schema()
    assert set(schema["required"]) == {"api_key", "access_token"}
    assert all(schema["properties"][field]["ui:widget"] == "password" for field in schema["required"])
    for secret in ["https://bad.example", "Bearer bad token", "secret\r\nInjected: value"]:
        with pytest.raises(ValidationError):
            model.model_validate({**CREDENTIAL, "api_key": secret})


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../other"},
    {"operation": "get_task", "task_id": 0},
    {"operation": "create_contact"},
    {"operation": "update_task", "task_id": 1},
    {"operation": "create_task", "subject": "Call", "start": "2026-11-10", "user_id": 1},
    {"operation": "search_contacts", "name": "ab"},
    {"operation": "create_contact", "emails": ["not-an-email"]},
])
def test_invalid_inputs_fail_before_any_request(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)
