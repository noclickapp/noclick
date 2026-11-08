"""HTTP boundary regressions for the native Abyssale integration (no live key)."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import abyssale_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-abyssale-key-42"
ID = "64238d01-d402-474b-8c2d-fbc957e9d290"
PROJECT = "9d00e9fe-9bd5-4471-acad-baa702a867e9"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {"credential_type": "abyssale_api_key", "api_key": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="abyssale-fixture", node_type="automation-abyssale",
        node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, handler):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host == "api.abyssale.com"
        assert request.headers["x-api-key"] == TOKEN
        assert request.headers["content-type"] == "application/json"
        return handler(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_generation_sends_layer_objects_and_preserves_documented_asset_urls(monkeypatch):
    body = json.loads((Path(__file__).parent / "fixtures/abyssale/generate_image.json").read_text())
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    result = await node({"operation": "generate_image", "design_id": ID,
        "template_format_name": "facebook-post", "image_file_type": "png",
        "elements": {"title": {"payload": "Summer sale — 40% off"}}}).execute({})
    assert result["data"] == body
    assert result["data"]["version"] == 1  # visual version is numeric, not API version
    assert requests[0].method == "POST"
    assert requests[0].url.path == f"/banner-builder/{ID}/generate"
    assert json.loads(requests[0].content) == {"template_format_name": "facebook-post", "image_file_type": "png", "elements": {"title": {"payload": "Summer sale — 40% off"}}}


@pytest.mark.asyncio
async def test_async_acceptance_and_polling_do_not_claim_completion(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200 if r.method == "POST" else 202,
        json={"generation_request_id": ID} if r.method == "POST" else {"id": ID, "is_finalized": False, "banners": []}))
    queued = await node({"operation": "generate_media", "design_id": ID, "template_format_names": ["facebook-feed", "instagram-post"]}).execute({})
    assert queued["data"] == {"generation_request_id": ID}
    pending = await node({"operation": "get_generation_request", "generation_request_id": ID}).execute({})
    assert pending["http_status"] == 202 and pending["data"]["is_finalized"] is False
    assert len(requests) == 2
    assert requests[1].content == b""


@pytest.mark.asyncio
async def test_explicit_pagination_and_comma_separated_design_filters(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=[{"id": ID, "name": "Summer sale"}], headers={"X-Total-Count": "26"}))
    first = await node({"operation": "list_designs", "type": ["static", "animated"], "project_id": PROJECT}).execute({})
    assert first["has_more"] is True and first["next_page"] == 2
    assert dict(requests[0].url.params) == {"page": "1", "per_page": "25", "sort": "name", "type": "static,animated", "project_id": PROJECT}
    second = await node({"operation": "list_projects", "page": 2}).execute({})
    assert second["next_page"] is None and second["total"] == 26


@pytest.mark.asyncio
async def test_move_rename_and_delete_use_published_methods_and_bodies(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"id": ID, "name": "Summer sale"}))
    await node({"operation": "move_design", "design_id": ID, "project_id": PROJECT}).execute({})
    await node({"operation": "rename_design", "design_id": ID, "name": "Summer sale"}).execute({})
    deleted = await node({"operation": "delete_design", "design_id": ID}).execute({})
    assert [(r.method, r.url.path) for r in requests] == [("PUT", f"/designs/{ID}/project"), ("PUT", f"/designs/{ID}/name"), ("DELETE", f"/designs/{ID}")]
    assert json.loads(requests[0].content) == {"project_id": PROJECT}
    assert json.loads(requests[1].content) == {"name": "Summer sale"}
    assert requests[2].content == b"" and deleted["deletion_acknowledged"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 429, 500, 302])
async def test_provider_failures_remain_errors_and_never_retry_writes(monkeypatch, code):
    requests = transport(monkeypatch, lambda _: httpx.Response(code, json={"id": "unauthorized", "message": "Invalid key " + TOKEN}))
    result = await node({"operation": "create_project", "name": "Summer Campaign 2024"}).execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_invalid_json_and_error_envelopes_are_not_success(monkeypatch):
    for response in [httpx.Response(200, text="<html>Login</html>"), httpx.Response(200, json={"id": "bad", "message": "Rejected"}), httpx.Response(200, json={"projects": []})]:
        transport(monkeypatch, lambda _, r=response: r)
        with pytest.raises(ValueError):
            await node({"operation": "list_projects"}).execute({})


@pytest.mark.parametrize("value", ["https://example.com/key", "{{api_key}}", "Bearer secret key", "key\nheader"])
def test_bad_credential_values_rejected(value):
    with pytest.raises(ValidationError):
        native.AbyssaleApiKeyCredential(api_key=value)


def test_config_rejects_path_injection_and_bare_string_layer_values():
    with pytest.raises(ValidationError):
        native.GetDesign(design_id="../credits")
    with pytest.raises(ValidationError):
        native.GenerateImage(design_id=ID, elements={"title": "not-an-object"})
    with pytest.raises(ValidationError):
        native.CreateProject(name="x")


@pytest.mark.asyncio
async def test_connection_evidence_uses_the_workspace_project_read(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=[{"id": PROJECT, "name": "Summer Campaign 2024", "created_at_ts": 1749827107}]))
    evidence = await collect_evidence(node_type="automation-abyssale", credential_data=credential(), user_id="fixture-user")
    assert evidence.reachable is True
    assert requests[0].method == "GET" and requests[0].url.path == "/projects"
    assert "Summer Campaign 2024" in str(evidence)
