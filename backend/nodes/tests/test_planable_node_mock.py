"""Synthetic transport tests; no live token, sign-in or provider writes."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import planable_node as native
from nodes.core.registry import NodeFactory

TOKEN = "pln_synthetic_testing_secret"
CREDENTIAL = {"credential_type": "planable_api_token", "api_token": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="planable-test", node_type="automation-planable",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, status=200, body=None):
    requests = []
    async def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_workspace_connection_evidence_is_a_read(monkeypatch):
    requests = transport(monkeypatch, body={"data": [{"id": "ws_123", "name": "My team"}]})
    result = await node({"operation": "list_workspaces"}).execute({})
    assert result["data"][0]["name"] == "My team"
    assert native.PlanableNode.connection_evidence.operation == "list_workspaces"
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url == "https://api.planable.io/api/v1/workspaces"
    assert requests[0].headers["authorization"] == "Bearer " + TOKEN
    assert not requests[0].content


@pytest.mark.asyncio
async def test_create_post_keeps_posts_envelope_and_safe_explicit_defaults(monkeypatch):
    requests = transport(monkeypatch, 201, {"posts": [{"id": "p1", "instagramTrialReelsError": "not eligible"}]})
    result = await node({"operation": "create_post", "workspaceId": "w1", "pageId": "page1", "text": "A link https://example.com"}).execute({})
    assert result["posts"][0]["instagramTrialReelsError"] == "not eligible"
    assert json.loads(requests[0].content) == {"workspaceId": "w1", "pageId": "page1", "text": "A link https://example.com", "notify": False, "publishAtScheduledDate": False}
    assert len(requests) == 1 and requests[0].method == "POST"


@pytest.mark.asyncio
async def test_patch_preserves_omission_false_empty_and_documented_null(monkeypatch):
    requests = transport(monkeypatch, body={"data": {"id": "p1"}, "declinedSuggestionsCount": 2})
    result = await node({"operation": "update_post", "id": "p1", "labels": [], "approved": False, "campaignId": None, "scheduledAt": None, "notify": False}).execute({})
    assert result["declinedSuggestionsCount"] == 2
    assert requests[0].url.path == "/api/v1/posts/p1"
    assert json.loads(requests[0].content) == {"labels": [], "approved": False, "campaignId": None, "scheduledAt": None, "notify": False}


@pytest.mark.asyncio
async def test_approval_uses_approvers_body_without_path_id(monkeypatch):
    requests = transport(monkeypatch, body={"data": {"requested": True}})
    await node({"operation": "request_approval", "id": "p1", "approverIds": ["member1"], "levelId": "level1", "note": "Please review"}).execute({})
    assert requests[0].url.path == "/api/v1/posts/p1/request-approval"
    assert json.loads(requests[0].content) == {"approverIds": ["member1"], "levelId": "level1", "note": "Please review"}


@pytest.mark.asyncio
async def test_empty_filtered_media_page_advances_by_limit(monkeypatch):
    requests = transport(monkeypatch, body={"data": [], "pagination": {"offset": 40, "limit": 20, "hasMore": True}})
    result = await node({"operation": "list_media", "workspaceId": "w1", "deletable": "true", "offset": 40}).execute({})
    assert result["next_offset"] == 60 and len(requests) == 1
    assert dict(requests[0].url.params) == {"workspaceId": "w1", "deletable": "true", "offset": "40", "limit": "20"}


@pytest.mark.asyncio
async def test_upload_acceptance_is_preserved_and_never_polled(monkeypatch):
    requests = transport(monkeypatch, 202, {"data": [{"id": "media1", "status": "processing"}]})
    result = await node({"operation": "upload_media", "workspaceId": "w1", "mediaUrls": ["https://example.com/photo.png"]}).execute({})
    assert result["http_status"] == 202 and result["data"][0]["status"] == "processing"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [("delete_post", "/posts/p1"), ("delete_campaign", "/campaigns/p1"), ("revoke_share_link", "/posts/p1/share")])
async def test_204_does_not_parse_json(monkeypatch, operation, path):
    requests = transport(monkeypatch, 204)
    result = await node({"operation": operation, "id": "p1"}).execute({})
    assert result == {"status": "success", "http_status": 204}
    assert requests[0].method == "DELETE" and requests[0].url.path == "/api/v1" + path


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_failures_never_follow_or_retry_and_redact_secret(monkeypatch, status):
    requests = transport(monkeypatch, status, {"error": {"message": "Rejected " + TOKEN}})
    result = await node({"operation": "list_workspaces"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_list_filters_and_dates_are_query_parameters(monkeypatch):
    requests = transport(monkeypatch, body={"data": [], "pagination": {"offset": 0, "limit": 20, "hasMore": False}})
    await node({"operation": "list_posts", "workspaceId": "w1", "campaignId": "no-campaign", "scheduledAfter": "2026-11-09T00:00:00Z"}).execute({})
    assert requests[0].url.params["scheduledAfter"] == "2026-11-09T00:00:00Z"
    assert requests[0].url.params["campaignId"] == "no-campaign"
    assert not requests[0].content


@pytest.mark.parametrize("config", [
    {"operation": "get_post", "id": "../posts"},
    {"operation": "list_posts"},
    {"operation": "update_post", "id": "p1", "notify": False},
    {"operation": "update_campaign", "id": "c1"},
    {"operation": "request_approval", "id": "p1", "approverIds": [""]},
    {"operation": "upload_media", "workspaceId": "w1", "mediaUrls": ["file:///private/photo.png"]},
    {"operation": "create_post", "workspaceId": "w1", "pageId": "pg1", "scheduledAt": "2026-11-09T00:00:00"},
])
def test_invalid_config_fails_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        native.PlanableNode.parse_config({"config": config, "credentials": CREDENTIAL})


def test_operation_catalog_and_manual_credential_default():
    operations = json.loads((Path(__file__).parent / "fixtures/planable/operations.json").read_text())
    assert len(operations) == 25 and len({(o["method"], o["path"]) for o in operations.values()}) == 25
    assert native.PlanableTokenCredential(api_token=TOKEN).credential_type == "planable_api_token"
    assert native.PlanableTokenCredential.model_fields["credential_type"].default == "planable_api_token"
