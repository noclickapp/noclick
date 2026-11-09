"""Exercise Coassemble's real node factory against an intercepted HTTP transport.

These tests pin routes, query/body placement, pasted-key authentication and
response handling without a provider account or live writes.
"""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from nodes import coassemble_node as native
from nodes.core.registry import NodeFactory

KEY = "COASSEMBLE:123:synthetic-secret-456"
CREDENTIAL = {"credential_type": "coassemble_api_key", "api_key": KEY}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="coassemble-fixture", node_type="automation-coassemble",
        node_data={"config": config, "credentials": CREDENTIAL if credential is None else credential})


def transport(monkeypatch, payload, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        assert request.headers["Authorization"] == KEY
        assert request.url.host == "api.coassemble.com"
        return httpx.Response(status, json=payload)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs) as session:
            yield session

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "list_clients", "page": 2, "length": 10}, "GET", "/clients", {"page": "2", "length": "10"}, None, []),
    ({"operation": "get_client", "identifier": "client /+?é"}, "GET", "/client/client%20%2F%2B%3F%C3%A9", {}, None, {"clientIdentifier": "client /+?é"}),
    ({"operation": "update_client", "identifier": "customer-1", "metadata": {"department": "Sales"}}, "PUT", "/client/customer-1", {}, {"metadata": {"department": "Sales"}}, {"clientIdentifier": "customer-1"}),
    ({"operation": "list_users", "client_identifier": "customer-1"}, "GET", "/users", {"page": "0", "length": "100", "clientIdentifier": "customer-1"}, None, []),
    ({"operation": "get_user", "identifier": "learner-1"}, "GET", "/user/learner-1", {}, None, {"identifier": "learner-1"}),
    ({"operation": "update_user", "identifier": "learner-1", "name": "Alex", "metadata": {"role": "learner"}}, "PUT", "/user/learner-1", {}, {"name": "Alex", "metadata": {"role": "learner"}}, {"identifier": "learner-1", "name": "Alex"}),
    ({"operation": "list_courses", "title": "Safety + First", "deleted": True}, "GET", "/courses", {"page": "0", "length": "100", "title": "Safety + First", "deleted": "true"}, None, [{"id": 42, "title": "Safety + First"}]),
    ({"operation": "get_course", "course_id": 42, "client_identifier": "customer-1"}, "GET", "/courses/42", {"clientIdentifier": "customer-1"}, None, {"id": 42, "sections": []}),
    ({"operation": "delete_course", "course_id": 42}, "DELETE", "/course/42", {}, None, True),
    ({"operation": "restore_course", "course_id": 42}, "POST", "/course/42/restore", {}, None, True),
    ({"operation": "publish_course", "course_id": 42}, "POST", "/course/42/publish", {}, None, {"id": 42}),
    ({"operation": "duplicate_course", "course_id": 42, "identifier": "owner-1", "client_identifier": "customer-1"}, "POST", "/course/42/duplicate", {}, {"identifier": "owner-1", "clientIdentifier": "customer-1"}, {"id": 43}),
    ({"operation": "list_collections"}, "GET", "/collections", {"page": "0", "length": "100", "deleted": "false"}, None, [{"id": 7, "courses": []}]),
    ({"operation": "get_collection", "collection_id": 7}, "GET", "/collections/7", {}, None, {"id": 7, "courses": []}),
    ({"operation": "create_collection", "title": "Onboarding", "course_ids": [42, 43], "theme_id": 3, "private": True, "emails": ["learner@example.com"]}, "POST", "/collection", {}, {"title": "Onboarding", "courseIds": [42, 43], "themeId": 3, "private": True, "emails": ["learner@example.com"]}, {"id": 7, "courses": [{"id": 42}, {"id": 43}]}),
    ({"operation": "update_collection", "collection_id": 7, "title": "New title", "private": False, "domains": []}, "PUT", "/collection/7", {}, {"title": "New title", "private": False, "domains": []}, {"id": 7, "title": "New title", "courses": []}),
    ({"operation": "delete_collection", "collection_id": 7}, "DELETE", "/collection/7", {}, None, True),
    ({"operation": "restore_collection", "collection_id": 7}, "POST", "/collection/7/restore", {}, None, True),
    ({"operation": "list_trackings", "course_id": 42, "identifier": "learner-1", "start": "2026-01-01", "end": "2026-02-01"}, "GET", "/trackings", {"id": "42", "length": "100", "page": "0", "identifier": "learner-1", "start": "2026-01-01", "end": "2026-02-01"}, None, [{"id": 9, "progress_percent": 50, "total_time": 120}]),
    ({"operation": "get_tracking", "tracking_id": 9}, "GET", "/tracking/9", {}, None, {"id": 9, "progressPercent": 50}),
    ({"operation": "list_themes", "length": 10}, "GET", "/themes", {"length": "10"}, None, [{"id": 3, "name": "Brand"}]),
    ({"operation": "get_theme", "theme_id": 3}, "GET", "/themes/3", {}, None, {"id": 3, "name": "Brand"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body,payload", CASES)
async def test_every_operation_uses_one_pinned_endpoint(monkeypatch, config, method, path, params, body, payload):
    requests = transport(monkeypatch, payload)
    result = await node(config).execute({})
    assert result["success"] is True
    assert result["data"] == payload
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.raw_path.decode().split("?")[0] == "/api/v1/headless" + path
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body
    if method != "GET":
        assert result["acknowledged"] is True
        assert "readback_verified" not in result
    assert KEY not in str(result)


@pytest.mark.asyncio
async def test_full_page_is_a_continuation_hint_and_empty_page_ends(monkeypatch):
    transport(monkeypatch, [{"id": 42}])
    result = await node({"operation": "list_courses", "page": 2, "length": 1}).execute({})
    assert result["pagination"] == {"page": 2, "length": 1, "page_full": True, "next_page": 3}
    transport(monkeypatch, [])
    result = await node({"operation": "list_courses", "page": 3, "length": 1}).execute({})
    assert result["pagination"]["next_page"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_error_envelope_preserves_rejection_and_redacts_key(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Denied key " + KEY}, status)
    result = await node({"operation": "list_courses"}).execute({})
    assert result["success"] is False and result["http_status"] == status
    assert result["error"] == "Denied key [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"courses": []}, None, "invalid"])
async def test_malformed_list_does_not_prove_connection(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError, match="invalid list"):
        await node({"operation": "list_courses"}).execute({})


@pytest.mark.asyncio
async def test_output_redacts_reflected_key_recursively(monkeypatch):
    transport(monkeypatch, [{"id": 42, "metadata": {"key": KEY}}])
    result = await node({"operation": "list_courses"}).execute({})
    assert KEY not in str(result)
    assert result["data"][0]["metadata"]["key"] == "[redacted]"


def test_credential_is_manually_fillable_without_type_tag():
    parsed = native.CoassembleAPIKeyCredential(api_key="  " + KEY + "  ")
    assert parsed.credential_type == "coassemble_api_key" and parsed.api_key == KEY
    with pytest.raises(ValidationError):
        native.CoassembleAPIKeyCredential(api_key="https://example.com/key")


@pytest.mark.parametrize("config", [
    {"operation": "get_course", "course_id": -1},
    {"operation": "get_client", "identifier": ".."},
    {"operation": "list_courses", "length": 101},
    {"operation": "list_courses", "page": -1},
    {"operation": "update_user", "identifier": "learner-1"},
    {"operation": "update_collection", "collection_id": 7},
    {"operation": "create_collection"},
])
def test_invalid_config_is_refused_before_transport(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,field", [
    ("delete_course", "course_id"), ("restore_course", "course_id"),
    ("delete_collection", "collection_id"), ("restore_collection", "collection_id"),
])
@pytest.mark.parametrize("acknowledged", [True, False])
async def test_documented_boolean_write_response(monkeypatch, operation, field, acknowledged):
    transport(monkeypatch, acknowledged)
    result = await node({"operation": operation, field: 42}).execute({})
    assert result["data"] is acknowledged
    assert result["acknowledged"] is acknowledged
    assert result["success"] is acknowledged
    assert result["status"] == ("success" if acknowledged else "unconfirmed")
