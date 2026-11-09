"""Kisi requests at the real factory/HTTP boundary; no live account is used."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import kisi_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-kisi-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="kisi-test", node_type="automation-kisi",
        node_data={"config": config, "credentials": {"api_key": TOKEN}})


def transport(monkeypatch, status=200, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.parametrize("resource", ["places", "locks", "groups", "members"])
async def test_list_and_get_use_fixed_account_routes(monkeypatch, resource):
    requests = transport(monkeypatch, body=[{"id": 17, "name": "Office"}])
    result = await node({"operation": "list_" + resource, "limit": 1, "offset": 2, "query": "Office"}).execute({})
    assert result["items"] == [{"id": 17, "name": "Office"}]
    assert result["next_offset"] == 3 and result["has_more"]
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET" and str(req.url).startswith("https://api.kisi.io/" + resource)
    assert dict(req.url.params) == {"limit": "1", "offset": "2", "query": "Office"}
    assert req.headers["Authorization"] == "KISI-LOGIN " + TOKEN
    assert req.headers["Accept"] == req.headers["Content-Type"] == "application/json"
    singular = resource[:-1]
    requests = transport(monkeypatch, body={"id": 17, "name": "Office"})
    result = await node({"operation": "get_" + singular, singular + "_id": 17}).execute({})
    assert result["data"]["id"] == 17
    assert requests[0].url.path == "/" + resource + "/17"


@pytest.mark.parametrize("resource,fields", [
    ("group", {"name": "Visitors", "place_id": 12}),
    ("member", {"email": "visitor@example.org", "name": "Visitor"}),
])
async def test_create_sends_only_documented_envelope_and_explicit_email_defaults(monkeypatch, resource, fields):
    requests = transport(monkeypatch, body={"id": 17})
    await node({"operation": "create_" + resource, **fields}).execute({})
    request = requests[0]
    assert len(requests) == 1 and request.method == "POST"
    assert request.url.path == "/" + resource + "s"
    body = json.loads(request.content)
    assert set(body) == {resource}
    assert fields.items() <= body[resource].items()
    if resource == "member":
        assert body[resource]["send_emails"] is False


@pytest.mark.parametrize("resource,fields", [
    ("group", {"description": None}),
    ("member", {"access_enabled": False, "notes": None}),
])
async def test_update_preserves_omissions_and_explicit_nulls(monkeypatch, resource, fields):
    requests = transport(monkeypatch, status=204)
    result = await node({"operation": "update_" + resource, resource + "_id": 17, **fields}).execute({})
    assert result["status"] == "success"
    request = requests[0]
    assert request.method == "PATCH" and request.url.path == "/" + resource + "s/17"
    assert json.loads(request.content) == {resource: fields}


@pytest.mark.parametrize("resource", ["group", "member"])
async def test_delete_has_no_body_and_accepts_204(monkeypatch, resource):
    requests = transport(monkeypatch, status=204)
    result = await node({"operation": "delete_" + resource, resource + "_id": 17}).execute({})
    assert result["success"] is True
    assert requests[0].method == "DELETE"
    assert requests[0].url.path == "/" + resource + "s/17"
    assert requests[0].content == b""


async def test_unlock_once_includes_required_nullable_proof(monkeypatch):
    requests = transport(monkeypatch, status=204)
    await node({"operation": "unlock_lock", "lock_id": 17}).execute({})
    assert len(requests) == 1
    assert requests[0].method == "POST" and requests[0].url.path == "/locks/17/unlock"
    assert json.loads(requests[0].content) == {"lock": {"proximity_proof": None}}


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_error_is_not_success_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={"message": "Access denied " + TOKEN})
    result = await node({"operation": "list_places"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Access denied [redacted]"
    assert TOKEN not in str(result) and len(requests) == 1


async def test_empty_page_ends_pagination_and_nested_secrets_are_redacted(monkeypatch):
    transport(monkeypatch, body=[])
    result = await node({"operation": "list_places"}).execute({})
    assert not result["has_more"] and result["next_offset"] is None
    transport(monkeypatch, body={"id": 17, "nested": {"value": TOKEN}})
    assert TOKEN not in str(await node({"operation": "get_place", "place_id": 17}).execute({}))


async def test_bad_response_does_not_claim_a_connection(monkeypatch):
    transport(monkeypatch, body={"error": "bad key"})
    with pytest.raises(ValueError, match="invalid list"):
        await node({"operation": "list_places"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_lock", "lock_id": "../user"},
    {"operation": "list_places", "limit": 101},
    {"operation": "list_places", "offset": 20001},
    {"operation": "create_member", "email": "invalid"},
    {"operation": "create_role_assignment", "applies_to_id": 1, "assignee_id": 1, "valid_until": "2026-01-01T00:00:00"},
])
def test_invalid_input_is_rejected_before_http(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_api_key_connects_by_hand_and_evidence_needs_no_extra_fields():
    credential = native.KisiAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "kisi_api_key"
    assert native.KisiNode.connection_evidence.operation == "list_places"
    assert native.KisiListPlacesConfig().operation == "list_places"
    for value in ["KISI-LOGIN " + TOKEN, "https://example.org/key", "<token>"]:
        with pytest.raises(ValueError):
            native.KisiAPIKeyCredential(api_key=value)


async def test_group_role_grant_uses_current_contract_fields(monkeypatch):
    # Published response: https://docs.kisi.io/api/how_to_guides/manage_access_rights/assign_access_rights/
    response = json.loads((Path(__file__).parent / "fixtures/kisi/role_assignment.json").read_text())
    requests = transport(monkeypatch, body=response)
    await node({"operation": "create_role_assignment", "assignee_id": 3, "applies_to_id": 4,
                "valid_from": "2023-05-24T14:15:22Z", "valid_until": "2023-05-25T14:15:22Z"}).execute({})
    body = json.loads(requests[0].content)["role_assignment"]
    assert requests[0].url.path == "/role_assignments"
    assert body["applies_to_type"] == "Group" and body["assignee_type"] == "User"
    assert body["role_id"] == "group_basic" and body["notify"] is False
    assert body["assignee_id"] == 3 and body["applies_to_id"] == 4
    assert body["valid_until"] == "2023-05-25T14:15:22Z"


async def test_group_door_grant_and_revoke(monkeypatch):
    requests = transport(monkeypatch, body={"id": 17})
    await node({"operation": "create_group_lock", "group_id": 2, "lock_id": 3}).execute({})
    assert requests[0].url.path == "/group_locks"
    assert json.loads(requests[0].content) == {"group_lock": {"group_id": 2, "lock_id": 3}}
    requests = transport(monkeypatch, status=204)
    await node({"operation": "delete_group_lock", "group_lock_id": 17}).execute({})
    assert requests[0].url.path == "/group_locks/17" and requests[0].method == "DELETE"


async def test_access_right_list_read_and_revoke(monkeypatch):
    requests = transport(monkeypatch, body=[])
    await node({"operation": "list_role_assignments", "assignee_type": "User", "assignee_id": 2}).execute({})
    assert requests[0].url.path == "/role_assignments"
    assert dict(requests[0].url.params)["assignee_id"] == "2"
    requests = transport(monkeypatch, body={"id": 17})
    await node({"operation": "get_role_assignment", "role_assignment_id": 17}).execute({})
    assert requests[0].url.path == "/role_assignments/17"
    requests = transport(monkeypatch, status=204)
    await node({"operation": "delete_role_assignment", "role_assignment_id": 17}).execute({})
    assert requests[0].method == "DELETE" and requests[0].url.path == "/role_assignments/17"
