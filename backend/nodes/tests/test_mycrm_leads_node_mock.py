"""MyCRM wire checks; provider-published responses are pinned with source URLs."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import mycrm_leads_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-mycrm-bearer-token"
CREDENTIAL = {"credential_type": "mycrm_leads_access_token", "api_base_url": "https://api.mycrm.io", "access_token": TOKEN, "adviser_contact_id": "1001"}
FIXTURES = Path(__file__).parent / "fixtures" / "mycrm-leads"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="mycrm-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def documented(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())["body"]


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Content-Type": native.MEDIA})
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


READS = {"contacts": "contact-get", "contact-groups": "contact-group-get", "advisers": "adviser-get",
         "deals": "deal-get", "leads": "lead-get", "structured-leads": "structured-lead-get", "tasks": "task-get", "deal-notes": "deal-note-get"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [name for name, spec in native.OPERATIONS.items() if spec[0] == "GET"])
async def test_every_read_against_documented_resource(monkeypatch, operation):
    _, kind, _, _ = native.OPERATIONS[operation]
    body = documented(READS[kind])
    cfg = {"operation": operation}
    if operation.startswith("list_"):
        body["data"] = [body["data"]]
        cfg.update(page_number=2, page_size=10)
    else:
        cfg["resource_id"] = body["data"]["id"]
    requests = transport(monkeypatch, body)
    result = await node(cfg).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/jsonapi/" + kind + ("/" + cfg["resource_id"] if "resource_id" in cfg else "")
    assert request.headers["UserId"] == "1001" and request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Accept"] == native.MEDIA
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"page[number]": "2", "page[size]": "10"}
        assert not result["has_more"]


WRITES = [
    ({"operation": "create_lead", "attributes": {"firstName": "Alex", "lastName": "Morgan", "email": "alex@example.com", "mobile": "+61400000000"}}, {}),
    ({"operation": "create_structured_lead", "attributes": {"contacts": [{"firstName": "Alex", "lastName": "Morgan", "email": "alex@example.com"}]}}, {}),
    ({"operation": "create_contact", "attributes": {"firstName": "Alex", "lastName": "Morgan"}, "contact_group_id": "1001"}, {"contactGroup": {"data": {"type": "contact-groups", "id": "1001"}}}),
    ({"operation": "update_contact", "resource_id": "1001", "attributes": {"email": "alex@example.com", "hasMarketingConsent": False}}, {}),
    ({"operation": "update_deal", "resource_id": "1001", "attributes": {"name": "string"}}, {}),
    ({"operation": "create_task", "attributes": {"title": "string", "progress": "Completed"}, "assignee_id": "1001", "deal_id": "1001"}, {"assignee": {"data": {"type": "advisers", "id": "1001"}}, "residentialDeal": {"data": {"type": "deals", "id": "1001"}}}),
    ({"operation": "update_task", "resource_id": "1001", "attributes": {"progress": "Completed"}}, {}),
    ({"operation": "update_task", "resource_id": "1001", "attributes": {"title": "string", "progress": "Completed", "dueDate": "2026-01-15T09:00:00Z"}}, {}),
    ({"operation": "create_deal_note", "attributes": {"title": "Follow-up", "detail": "Client requested a call next week."}, "deal_id": "3001"}, {"deal": {"data": {"type": "deals", "id": "3001"}}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg,relationships", WRITES)
async def test_every_write_exact_jsonapi_body(monkeypatch, cfg, relationships):
    method, kind, _, _ = native.OPERATIONS[cfg["operation"]]
    requests = transport(monkeypatch, documented(READS[kind]), 201 if method == "POST" else 200)
    result = await node(cfg).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == method and request.headers["Content-Type"] == native.MEDIA
    assert request.url.path == "/jsonapi/" + kind + ("/" + cfg["resource_id"] if "resource_id" in cfg else "")
    expected = {"type": kind, "attributes": cfg["attributes"]}
    if method == "PATCH":
        expected["id"] = cfg["resource_id"]
    if relationships:
        expected["relationships"] = relationships
    assert json.loads(request.content) == {"data": expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 422, 429, 500])
async def test_errors_redact_provider_text_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"errors": [{"detail": "Access denied " + TOKEN}]}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_contacts"}).execute({})
    assert "Access denied [redacted]" in str(exc.value) and TOKEN not in str(exc.value)
    assert len(requests) == 1


def test_manual_credential_defaults_and_destination_boundary():
    value = {k: v for k, v in CREDENTIAL.items() if k != "credential_type"}
    assert native.MyCRMLeadsAccessToken(**value).credential_type == "mycrm_leads_access_token"
    for url in ["http://api.mycrm.io", "https://api.mycrm.io/jsonapi", "https://user:pass@api.mycrm.io", "https://api.mycrm.io?redirect=evil"]:
        with pytest.raises(ValidationError):
            native.MyCRMLeadsAccessToken(**{**CREDENTIAL, "api_base_url": url})
    for token in ["Bearer abc", "<token>", "https://example.com/token"]:
        with pytest.raises(ValidationError):
            native.MyCRMLeadsAccessToken(**{**CREDENTIAL, "access_token": token})
    assert NODE_REGISTRY[native.NODE_TYPE] is native.MyCRMLeadsNode


def test_write_field_allowlist_and_patch_path_reject_bad_inputs():
    for cfg in [
        {"operation": "update_task", "resource_id": "1001", "attributes": {"dueDate": "2026-01-15T09:00:00"}},
        {"operation": "get_contact", "resource_id": "2147483648"},
        {"operation": "update_contact", "resource_id": "../1001", "attributes": {"firstName": "Alex"}},
        {"operation": "update_contact", "resource_id": "1001", "attributes": {"created": "2026-01-15"}},
        {"operation": "update_contact", "resource_id": "1001", "attributes": {}},
    ]:
        assert not native.MyCRMLeadsNode.validate_config({"config": cfg})["valid"]
