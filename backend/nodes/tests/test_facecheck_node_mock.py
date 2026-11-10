"""Exercise the native node at its HTTP boundary; all account data is synthetic."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import facecheck_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-facecheck-token-42"
CREDENTIAL = {"credential_type": "facecheck_api_token", "api_token": TOKEN}
CONTRACT = json.loads((Path(__file__).parent / "fixtures/facecheck/openapi.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="facecheck-fixture", node_type="automation-facecheck",
        node_data={"config": config, "credentials": credentials or CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_facecheck_info_auth_and_connection_read(monkeypatch):
    body = {name: schema["example"] for name, schema in CONTRACT["components"]["schemas"]["InfoResponse"]["properties"].items()}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "get_info"}).execute({})
    assert result["data"] == body
    assert result["status"] == "success"
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "https://facecheck.id/api/info"
    assert requests[0].headers["Authorization"] == TOKEN
    assert requests[0].content == b""
    assert NODE_REGISTRY["automation-facecheck"] is native.FaceCheckNode
    assert native.FaceCheckNode.connection_evidence.operation == "get_info"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,expected", [
    ({"operation": "search", "demo": False, "shady_only": False},
     {"status_only": False, "with_progress": True, "demo": False, "shady_only": False}),
    ({"operation": "search", "with_progress": False},
     {"status_only": False, "with_progress": False, "demo": True}),
    ({"operation": "get_search_status"}, {"status_only": True, "with_progress": True}),
])
async def test_facecheck_search_modes_exact_body_preserves_result(monkeypatch, operation, expected):
    search_id = CONTRACT["components"]["schemas"]["SearchData"]["properties"]["id_search"]["example"]
    body = {"id_search": search_id, "progress": 100, "error": None,
            "output": {"items": [{"guid": "fixture", "url": {"value": "https://example.com/fixture"}, "score": 80}]}}
    requests = transport(monkeypatch, body)
    result = await node({**operation, "id_search": search_id}).execute({})
    assert result["data"] == body
    assert len(requests) == 1
    assert requests[0].url.path == "/api/search"
    assert json.loads(requests[0].content) == {"id_search": search_id, **expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [None, "existing-bundle"])
async def test_facecheck_upload_multipart_binary_and_bundle_controls(monkeypatch, existing):
    image = b"\x89PNG\r\n\x1a\nsynthetic-test-image"
    body = {"id_search": "fixture-bundle", "input": [{"id_pic": "fixture-image"}], "error": None}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "upload_image", "image_base64": base64.b64encode(image).decode(),
                         "filename": "fixture.png", "id_search": existing, "reset_prev_images": True}).execute({})
    assert result["data"] == body
    request = requests[0]
    assert request.url.path == "/api/upload_pic"
    assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="images"; filename="fixture.png"' in request.content
    assert b"Content-Type: image/png" in request.content
    assert image in request.content
    assert b'name="reset_prev_images"\r\nContent-Type: text/plain\r\n\r\ntrue' in request.content
    assert (b'name="id_search"' in request.content) is (existing is not None)
    if existing:
        assert existing.encode() in request.content


@pytest.mark.asyncio
async def test_facecheck_delete_uses_query_not_json(monkeypatch):
    requests = transport(monkeypatch, {"error": None, "input": []})
    await node({"operation": "delete_image", "id_search": "bundle + id", "id_pic": "image/id"}).execute({})
    assert requests[0].url.path == "/api/delete_pic"
    assert dict(requests[0].url.params) == {"id_search": "bundle + id", "id_pic": "image/id"}
    assert requests[0].content == b""


@pytest.mark.asyncio
async def test_facecheck_upload_leaves_optional_reset_unset_by_default(monkeypatch):
    requests = transport(monkeypatch, {"id_search": "fixture-bundle", "error": None})
    await node({"operation": "upload_image", "image_base64": "aW1hZ2U="}).execute({})
    assert b'name="reset_prev_images"' not in requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": "Token rejected"}), (302, {}),
    (200, {"error": "Insufficient credits"}), (200, []), (200, {"error": TOKEN})])
async def test_facecheck_errors_are_not_success_or_retried(monkeypatch, status, body):
    requests = transport(monkeypatch, body, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_info"}).execute({})
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1
    if status == 401:
        assert "401" in str(exc.value) and "Token rejected" in str(exc.value)


def test_facecheck_manual_credential_default_and_wrong_family():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential("facecheck_api_token", {"api_token": TOKEN})
    assert not errors and shaped["api_token"] == TOKEN
    assert resolved == ("automation-facecheck", native.FaceCheckAPITokenCredential)
    assert resolved[1].model_validate(shaped).credential_type == "facecheck_api_token"
    with pytest.raises(ValidationError):
        native.FaceCheckAPITokenCredential(credential_type="unrelated", api_token=TOKEN)


@pytest.mark.parametrize("value", ["Bearer abc", "bad\nheader", "https://example.com/key"])
def test_facecheck_rejects_bad_tokens(value):
    with pytest.raises(ValueError):
        native.FaceCheckAPITokenCredential(api_token=value)


@pytest.mark.parametrize("changes", [{"image_base64": "not-base64"}, {"filename": "../secret.png"}])
def test_facecheck_upload_validation(changes):
    with pytest.raises(ValueError):
        native.UploadImageConfig.model_validate({"image_base64": "aW1hZ2U=", **changes})


def test_facecheck_all_actions_use_published_routes():
    assert set(CONTRACT["paths"]) == {"/api/upload_pic", "/api/search", "/api/info", "/api/delete_pic", "/llms.txt"}
    assert all("post" in CONTRACT["paths"][path] for path in CONTRACT["paths"] if path.startswith("/api/"))
