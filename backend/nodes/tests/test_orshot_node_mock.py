"""Orshot HTTP boundary regressions; fixtures are official documented responses.

No live provider requests or credentials are used.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import orshot_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import _rows_from_operation, _identity_label

KEY = "orshot-synthetic-test-key"
EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/orshot/documented_responses.json").read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(
        node_id="orshot-test",
        node_type="automation-orshot",
        node_data={
            "config": config,
            "credentials": credential
            or {"credential_type": "orshot_api_key", "api_key": KEY},
        },
    )


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    real_client = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
async def test_render_url_format_modifications_and_async_mode(monkeypatch):
    payload = EXAMPLES["POST /studio/render"]["body"]
    requests = transport(monkeypatch, payload)
    result = await node(
        {
            "operation": "render_template",
            "templateId": 123,
            "modifications": {"title": "Custom Title", "page2@title": "Second"},
            "response": {"format": "png", "mode": "async"},
        }
    ).execute({})
    assert result["data"] == payload
    assert len(requests) == 1
    request = requests[0]
    assert (
        request.method == "POST" and str(request.url) == native.BASE + "/studio/render"
    )
    assert request.headers["authorization"] == "Bearer " + KEY
    assert json.loads(request.content) == {
        "templateId": 123,
        "modifications": {"title": "Custom Title", "page2@title": "Second"},
        "response": {"format": "png", "mode": "async", "type": "url"},
    }


@pytest.mark.asyncio
async def test_single_page_preserves_provider_pagination_and_filters(monkeypatch):
    payload = EXAMPLES["GET /studio/templates/all"]["body"]
    requests = transport(monkeypatch, payload)
    result = await node(
        {
            "operation": "list_templates",
            "page": 2,
            "limit": 10,
            "search": "banner + café",
            "tags": "social,marketing",
        }
    ).execute({})
    assert result["data"] == payload and len(requests) == 1
    assert dict(requests[0].url.params) == {
        "page": "2",
        "limit": "10",
        "search": "banner + café",
        "tags": "social,marketing",
    }
    assert _rows_from_operation(result) == payload["data"]


@pytest.mark.asyncio
async def test_workspace_identity_names_connected_workspace(monkeypatch):
    payload = EXAMPLES["GET /workspace"]["body"]
    transport(monkeypatch, payload)
    result = await node({"operation": "get_workspace"}).execute({})
    assert (
        _identity_label(
            result["data"], native.OrshotNode.connection_evidence.identity_keys
        )
        == "My Workspace"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,method,path,body",
    [
        (
            {"operation": "cancel_render_job", "id": "1208"},
            "POST",
            "/studio/render-jobs/1208/cancel",
            {},
        ),
        (
            {"operation": "delete_template", "templateId": 123},
            "DELETE",
            "/studio/templates/123/delete",
            None,
        ),
        (
            {"operation": "delete_folder", "folderId": 11},
            "DELETE",
            "/studio/folders/11",
            None,
        ),
        (
            {"operation": "rename_folder", "folderId": 11, "name": "Social Posts"},
            "PATCH",
            "/studio/folders/11",
            {"name": "Social Posts"},
        ),
        (
            {
                "operation": "move_template_to_folder",
                "templateId": 123,
                "folder_id": 11,
            },
            "PATCH",
            "/studio/templates/123/folder",
            {"folder_id": 11},
        ),
        (
            {"operation": "update_image_tags", "id": 123, "tags": []},
            "PATCH",
            "/brand-assets/images/update/123",
            {"tags": []},
        ),
        (
            {"operation": "delete_image", "id": 123},
            "DELETE",
            "/brand-assets/images/delete/123",
            None,
        ),
        (
            {"operation": "delete_color", "id": 123},
            "DELETE",
            "/brand-assets/colors/delete/123",
            None,
        ),
    ],
)
async def test_mutation_route_body_and_one_request(
    monkeypatch, config, method, path, body
):
    requests = transport(monkeypatch, {"success": True})
    await node(config).execute({})
    assert len(requests) == 1
    assert requests[0].method == method and requests[0].url.path == "/v1" + path
    assert (json.loads(requests[0].content) if requests[0].content else None) == body


@pytest.mark.asyncio
async def test_logs_cursor_and_timestamp_wire_names(monkeypatch):
    requests = transport(monkeypatch, {"data": [], "pagination": {"next_cursor": 100}})
    result = await node(
        {
            "operation": "list_workspace_logs",
            "cursor": 123,
            "from_time": "2026-01-01T00:00:00Z",
            "to_time": "2026-02-01T00:00:00Z",
        }
    ).execute({})
    assert dict(requests[0].url.params) == {
        "limit": "50",
        "cursor": "123",
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-02-01T00:00:00Z",
    }
    assert result["data"]["pagination"]["next_cursor"] == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 409, 429, 500])
async def test_provider_errors_redact_key_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Provider refused " + KEY}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_workspace"}).execute({})
    assert KEY not in str(exc.value) and "Provider refused" in str(exc.value)
    assert str(status) in str(exc.value) and len(requests) == 1


@pytest.mark.parametrize(
    "key", ["https://orshot.com/workspace", "<token>", "Bearer abc", "abc\nxyz", "abcé"]
)
def test_invalid_credentials_fail_before_http(key):
    with pytest.raises(ValidationError):
        native.OrshotAPIKeyCredential(api_key=key)


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_template", "templateId": "../workspace"},
        {"operation": "list_templates", "limit": 41},
        {"operation": "list_render_jobs", "status": "invalid"},
        {
            "operation": "render_template",
            "templateId": 123,
            "response": {"type": "base64"},
        },
    ],
)
def test_rejects_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)
