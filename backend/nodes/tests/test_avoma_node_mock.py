"""Offline request regressions for Avoma's published API contract."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import avoma_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-avoma-key:synthetic-secret"
ID = "f04490d0-4d46-4f4a-aa53-2b94a137a27a"
DATES = {"from_date": "2026-10-01T00:00:00Z", "to_date": "2026-10-02T00:00:00Z"}


def node(config):
    return NodeFactory.create_node(node_type="automation-avoma", node_id="avoma-test",
        node_data={"config": config, "credentials": {"credential_type": "avoma_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_account_evidence_preserves_users_and_pasted_full_key(monkeypatch):
    users = json.loads((Path(__file__).parent / "fixtures/avoma/users.json").read_text())
    requests = transport(monkeypatch, users)
    result = await node({"operation": "list_users"}).run({})
    assert result["data"] == users and result["http_status"] == 200
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert str(requests[0].url) == "https://api.avoma.com/v1/users/"
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,extra", [
    ("list_meetings", "/v1/meetings/", DATES),
    ("get_meeting", "/v1/meetings/" + ID + "/", {"uuid": ID}),
    ("get_meeting_insights", "/v1/meetings/" + ID + "/insights/", {"meeting_uuid": ID}),
    ("list_notes", "/v1/notes/", DATES),
    ("get_recording", "/v1/recordings/", {"meeting_uuid": ID}),
    ("list_transcriptions", "/v1/transcriptions/", {**DATES, "page": 3}),
    ("get_transcription", "/v1/transcriptions/" + ID + "/", {"uuid": ID}),
    ("get_user", "/v1/users/" + ID + "/", {"uuid": ID}),
    ("list_smart_categories", "/v1/smart_categories/", {}),
    ("get_smart_category", "/v1/smart_categories/" + ID + "/", {"uuid": ID}),
    ("list_templates", "/v1/template/", {}),
    ("get_template", "/v1/template/" + ID + "/", {"uuid": ID}),
])
async def test_read_paths_query_and_no_secondary_requests(monkeypatch, operation, path, extra):
    body = {"results": [], "count": 1, "next": "https://untrusted.example/next", "previous": None}
    requests = transport(monkeypatch, body)
    result = await node({"operation": operation, **extra}).execute({})
    assert result["data"] == body and len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.path == path
    assert not request.content and "operation" not in request.url.params and "uuid" not in request.url.params
    if operation == "get_recording": assert request.url.params["meeting_uuid"] == ID
    if operation == "list_transcriptions": assert request.url.params["page"] == "3"
    if operation == "list_meetings": assert request.url.params["include_crm_associations"] == "false"


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["meeting_type", "meeting_outcome"])
@pytest.mark.parametrize("verb,method", [("list", "GET"), ("get", "GET"), ("create", "POST"), ("update", "PATCH"), ("delete", "DELETE")])
async def test_classification_crud_exact_route_body_and_empty_delete(monkeypatch, resource, verb, method):
    values = {"uuid": ID} if verb in {"get", "update", "delete"} else {}
    if verb in {"create", "update"}: values.update(label="Discovery", description="First call")
    status = 204 if verb == "delete" else 201 if verb == "create" else 200
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"uuid": ID, "label": "Discovery", "description": "First call"}) if status != 204 else httpx.Response(204))
    result = await node({"operation": verb + "_" + resource + ("s" if verb == "list" else ""), **values}).execute({})
    assert result["http_status"] == status
    assert len(requests) == 1 and requests[0].method == method
    assert requests[0].url.path == "/v1/" + resource + "/" + (ID + "/" if "uuid" in values else "")
    if method in {"POST", "PATCH"}: assert json.loads(requests[0].content) == {"label": "Discovery", "description": "First call"}
    else: assert not requests[0].content
    if status == 204: assert result["data"] is None


@pytest.mark.asyncio
async def test_partial_update_omits_absent_fields(monkeypatch):
    requests = transport(monkeypatch, {"uuid": ID, "label": "Updated", "description": "Existing"})
    await node({"operation": "update_meeting_type", "uuid": ID, "label": "Updated"}).execute({})
    assert json.loads(requests[0].content) == {"label": "Updated"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_rejection_redacts_key_and_never_retries(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"detail": "Denied " + TOKEN}))
    result = await node({"operation": "list_users"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and result["error"].startswith("Denied") and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, "bad", 12, {"error": "bad"}, {"detail": "bad"}])
async def test_invalid_success_body_is_not_success(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError): await node({"operation": "list_users"}).execute({})



@pytest.mark.asyncio
async def test_processing_recording_and_no_content_notes_preserve_http_state(monkeypatch):
    body = {"uuid": ID, "meeting_uuid": ID, "message": "Recording is processing"}
    requests = transport(monkeypatch, lambda r: httpx.Response(202, json=body))
    result = await node({"operation": "get_recording", "meeting_uuid": ID}).execute({})
    assert result["http_status"] == 202 and result["data"] == body and len(requests) == 1
    transport(monkeypatch, lambda r: httpx.Response(204))
    result = await node({"operation": "list_notes", **DATES}).execute({})
    assert result["http_status"] == 204 and result["data"] is None


@pytest.mark.asyncio
async def test_user_evidence_names_people_and_refuses_non_user_envelopes(monkeypatch):
    transport(monkeypatch, [{"uuid": ID, "user": {"first_name": "Alex", "last_name": "Example"}}])
    result = await node({"operation": "list_users"}).execute({})
    assert result["items"][0]["label"] == "Alex Example"
    transport(monkeypatch, [{"uuid": ID}])
    with pytest.raises(ValueError): await node({"operation": "list_users"}).execute({})


def test_required_fields_closed_config_dates_ids_and_secret_validation():
    assert len(native.ROUTES) == 23
    for cfg in [
        {"operation": "get_meeting", "uuid": "../other"},
        {"operation": "list_meetings"},
        {"operation": "list_notes", **DATES, "page_size": 21},
        {"operation": "list_transcriptions", **DATES, "page": 0},
        {"operation": "list_meetings", **DATES, "to_date": "2025-01-01T00:00:00Z"},
        {"operation": "list_meetings", **DATES, "from_date": "2026-10-01T00:00:00"},
        {"operation": "update_meeting_type", "uuid": ID},
        {"operation": "create_meeting_outcome", "label": "Qualified"},
        {"operation": "list_users", "url": "https://untrusted.example"},
    ]:
        with pytest.raises((ValueError, ValidationError)): node(cfg)
    with pytest.raises(ValueError): native.AvomaAPIKey(api_key="Bearer " + TOKEN)
