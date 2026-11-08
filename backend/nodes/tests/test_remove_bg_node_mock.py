"""remove.bg v1 request mapping, binary results and connection evidence."""
import base64
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from nodes import remove_bg_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-remove-bg-key"
IMAGE = "https://www.remove.bg/example-hd.jpg"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="remove-bg-test", node_type="automation-remove-bg",
        node_data={"config": config, "credentials": credentials or {
            "credential_type": "remove_bg_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def handler(request):
        requests.append(request)
        return response(request) if callable(response) else response
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,expected", [
    ("remove_background", {}, {}),
    ("remove_background_base64", {"image_file_b64": base64.b64encode(b"synthetic-image").decode()}, {}),
    ("create_alpha_mask", {}, {"channels": "alpha", "format": "png"}),
    ("replace_background_color", {"bg_color": "81d4fa"}, {"bg_color": "81d4fa"}),
    ("replace_background_image", {"bg_image_url": IMAGE}, {"bg_image_url": IMAGE}),
    ("crop_to_subject", {"crop_margin": "10%"}, {"crop": True, "crop_margin": "10%"}),
    ("resize_subject", {"scale": "50%", "position": "center"}, {"scale": "50%", "position": "center"}),
    ("add_shadow", {"shadow_type": "drop", "shadow_opacity": "50"}, {"shadow_type": "drop", "shadow_opacity": "50"}),
])
async def test_remove_bg_each_image_action_is_one_contract_request(monkeypatch, operation, extra, expected):
    requests = transport(monkeypatch, httpx.Response(200, content=b"image-bytes", headers={
        "content-type": "image/png", "X-Credits-Charged": "0.25", "X-Width": "625"}))
    config = {"operation": operation, **({} if "base64" in operation else {"image_url": IMAGE}), **extra}
    result = await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST" and str(request.url) == native.BASE + "/removebg"
    assert request.headers["X-API-Key"] == TOKEN
    assert request.headers["content-type"] == "application/json"
    body = json.loads(request.content)
    assert "operation" not in body and "agree_to_conditions" not in body
    assert not ({"image_url", "image_file_b64"} <= body.keys())
    assert body.items() >= expected.items()
    assert body["semitransparency"] is True
    assert result["status"] == "success" and isinstance(result["file"], BinaryOutput)
    assert result["file"].data == b"image-bytes" and result["credits_charged"] == "0.25"


@pytest.mark.asyncio
async def test_remove_bg_account_evidence_read(monkeypatch):
    attrs = {"credits": {"total": 200.0, "subscription": 150.0, "payg": 50.0, "enterprise": 0.0},
        "api": {"free_calls": 50, "sizes": "all"}}
    requests = transport(monkeypatch, httpx.Response(200, json={"data": {"attributes": attrs}}))
    assert "automation-remove-bg" in NODE_REGISTRY
    evidence = native.RemoveBgNode.connection_evidence
    assert evidence.operation == "get_account" and evidence.proves == "reachability"
    assert await node({"operation": evidence.operation}).execute({}) == {"status": "success", "data": attrs}
    assert requests[0].method == "GET" and requests[0].url.path == "/v1.0/account"
    assert not requests[0].content and not requests[0].url.query


@pytest.mark.asyncio
async def test_remove_bg_improvement_conditions_are_required_and_not_sent(monkeypatch):
    with pytest.raises(ValidationError):
        native.SubmitImprovement(image_url=IMAGE)
    with pytest.raises(ValidationError):
        native.SubmitImprovement(image_url=IMAGE, agree_to_conditions=False)
    requests = transport(monkeypatch, httpx.Response(200, json={"id": "fe09820b-be79-4511-8836-679583529882"}))
    result = await node({"operation": "submit_improvement", "image_url": IMAGE,
        "image_filename": "car.jpg", "tag": "batch_1_2020", "agree_to_conditions": True}).execute({})
    assert result["status"] == "success"
    assert requests[0].url.path == "/v1.0/improve"
    assert json.loads(requests[0].content) == {"image_url": IMAGE, "image_filename": "car.jpg", "tag": "batch_1_2020"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 402, 403, 429, 500])
async def test_remove_bg_provider_rejection_is_an_error_without_retry(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={"errors": [{"title": "Missing API Key " + TOKEN}]}))
    result = await node({"operation": "get_account"}).execute({})
    assert len(requests) == 1 and result["status"] == "error" and result["status_code"] == status
    assert "Missing API Key" in result["error"] and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,response", [
    ("get_account", httpx.Response(200, json={"data": {}})),
    ("get_account", httpx.Response(200, json={"errors": []})),
    ("get_account", httpx.Response(200, text="<html>sign in</html>")),
    ("remove_background", httpx.Response(200, json={"errors": []})),
    ("remove_background", httpx.Response(200, content=b"", headers={"content-type": "image/png"})),
])
async def test_remove_bg_malformed_success_is_not_connection_proof(monkeypatch, operation, response):
    transport(monkeypatch, response)
    config = {"operation": operation, **({"image_url": IMAGE} if operation == "remove_background" else {})}
    assert (await node(config).execute({}))["status"] == "error"


@pytest.mark.parametrize("key", ["https://example.com/key", "Bearer something", "key\r\nheader", ""])
def test_remove_bg_credentials_refuse_urls_headers_and_blanks(key):
    with pytest.raises((ValidationError, ValueError)):
        native.RemoveBgAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("image", ["file:///tmp/x.png", "https://user:pass@example.com/x", "no-url"])
def test_remove_bg_invalid_source_refused(image):
    with pytest.raises(ValidationError):
        native.RemoveBackground(image_url=image)
