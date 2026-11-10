"""Offline request and documented-response tests; no live account is used."""
import base64
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx
import pytest

from nodes import dreamstudio_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/dreamstudio/contract.json").read_text())
KEY = "test-dreamstudio-api-key"
# Small synthetic PNG input; response examples below are copied from the provider.
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture-image-bytes").decode()
PROMPTS = [{"text": "A lighthouse on a cliff", "weight": 1}, {"text": "land, ground, dirt, grass", "weight": -0.9}]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="dreamstudio-test", node_type="automation-dreamstudio",
        node_data={"config": config, "credentials": {"credential_type": native.CREDENTIAL, "api_key": KEY}})


def transport(monkeypatch, body, status=200):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


def multipart(request):
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
    return {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
        for part in message.iter_parts()}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,fixture,output", [
    ("get_account", "/v1/user/account", "account", "data"),
    ("get_balance", "/v1/user/balance", "balance", "credits"),
    ("list_engines", "/v1/engines/list", "engines", "engines"),
])
async def test_account_reads(monkeypatch, operation, path, fixture, output):
    requests = transport(monkeypatch, FIXTURE[fixture])
    result = await node({"operation": operation, **({"organization": "org-123456"} if operation != "get_account" else {})}).execute({})
    assert result["success"]
    assert result[output] == (FIXTURE[fixture]["credits"] if output == "credits" else FIXTURE[fixture])
    request, = requests
    assert request.method == "GET" and request.url.path == path
    assert request.url.host == "api.stability.ai" and request.headers["Authorization"] == "Bearer " + KEY
    assert ("Organization" in request.headers) == (operation != "get_account")
    assert not request.content and not request.url.query


@pytest.mark.asyncio
async def test_text_generation_json_and_provider_artifacts_envelope(monkeypatch):
    requests = transport(monkeypatch, {"artifacts": [FIXTURE["images"][0]]})
    result = await node({"operation": "text_to_image", "engine_id": "stable-diffusion-v1-5", "text_prompts": PROMPTS}).execute({})
    assert result["success"] and result["artifacts"] == [FIXTURE["images"][0]]
    request, = requests
    assert request.method == "POST" and request.url.path == "/v1/generation/stable-diffusion-v1-5/text-to-image"
    assert request.headers["Accept"] == "application/json"
    body = json.loads(request.content)
    assert body["text_prompts"] == PROMPTS and body["height"] == body["width"] == 512
    assert "engine_id" not in body and "operation" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("action,extra,field,value,suffix", [
    ("image_to_image_strength", {"init_image": PNG}, "init_image_mode", "IMAGE_STRENGTH", "image-to-image"),
    ("image_to_image_schedule", {"init_image": PNG, "step_schedule_end": 0.01}, "init_image_mode", "STEP_SCHEDULE", "image-to-image"),
    ("mask_alpha", {"init_image": PNG}, "mask_source", "INIT_IMAGE_ALPHA", "image-to-image/masking"),
    ("mask_white", {"init_image": PNG, "mask_image": PNG}, "mask_source", "MASK_IMAGE_WHITE", "image-to-image/masking"),
    ("mask_black", {"init_image": PNG, "mask_image": PNG}, "mask_source", "MASK_IMAGE_BLACK", "image-to-image/masking"),
])
async def test_multipart_modes_and_negative_prompts(monkeypatch, action, extra, field, value, suffix):
    requests = transport(monkeypatch, [FIXTURE["images"][0]])
    result = await node({"operation": action, "engine_id": "stable-diffusion-v1-5", "text_prompts": PROMPTS, **extra}).execute({})
    assert result["success"]
    request, = requests
    assert request.url.path == "/v1/generation/stable-diffusion-v1-5/" + suffix
    parts = multipart(request)
    assert parts[field] == value.encode()
    assert parts["init_image"] == base64.b64decode(PNG)
    assert parts["text_prompts[0][text]"] == PROMPTS[0]["text"].encode()
    assert parts["text_prompts[1][weight]"] == b"-0.9"
    if "mask_image" in extra:
        assert parts["mask_image"] == base64.b64decode(PNG)
    if action == "image_to_image_strength":
        assert parts["image_strength"] == b"0.35" and "step_schedule_start" not in parts
    if action == "image_to_image_schedule":
        assert parts["step_schedule_start"] == b"0.65" and "image_strength" not in parts


@pytest.mark.asyncio
async def test_upscale_is_only_image_and_one_dimension(monkeypatch):
    requests = transport(monkeypatch, [FIXTURE["images"][0]])
    assert (await node({"operation": "upscale_image", "engine_id": "esrgan-v1-x2plus", "image": PNG, "width": 1024}).execute({}))["success"]
    request, = requests
    assert request.url.path.endswith("/image-to-image/upscale")
    assert multipart(request) == {"image": base64.b64decode(PNG), "width": b"1024"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204, 302, 400, 401, 403, 429, 500])
async def test_provider_errors_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "rejected " + KEY}, status)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert KEY not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_billable_timeout_is_not_retried(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("secret " + KEY))
    result = await node({"operation": "text_to_image", "engine_id": "test", "text_prompts": PROMPTS}).execute({})
    assert not result["success"] and len(requests) == 1 and KEY not in str(result)


@pytest.mark.asyncio
async def test_content_filter_is_not_claimed_as_success(monkeypatch):
    transport(monkeypatch, {"artifacts": FIXTURE["images"]})
    result = await node({"operation": "text_to_image", "engine_id": "test", "text_prompts": PROMPTS}).execute({})
    assert not result["generation_success"] and result["artifacts"][1]["finishReason"] == "CONTENT_FILTERED"


@pytest.mark.parametrize("config", [
    {"operation": "text_to_image", "engine_id": "../escape", "text_prompts": PROMPTS},
    {"operation": "text_to_image", "engine_id": "test", "text_prompts": []},
    {"operation": "text_to_image", "engine_id": "test", "text_prompts": PROMPTS, "width": 513},
    {"operation": "text_to_image", "engine_id": "test", "text_prompts": PROMPTS, "width": 128, "height": 128},
    {"operation": "upscale_image", "engine_id": "test", "image": PNG, "width": 1024, "height": 1024},
    {"operation": "upscale_image", "engine_id": "test", "image": "https://private.test/image.png"},
    {"operation": "mask_white", "engine_id": "test", "init_image": PNG, "text_prompts": PROMPTS},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize("action,payload", [("get_account", {}), ("get_balance", {"credits": True}),
    ("list_engines", {}), ("text_to_image", {"artifacts": []}), ("text_to_image", {"message": "error"})])
def test_malformed_success_is_rejected(action, payload):
    with pytest.raises(ValueError):
        native.DreamstudioNode._result(action, payload)


def test_manual_credential_default_and_identity_evidence():
    assert native.DreamstudioAPIKey(api_key=KEY).credential_type == native.CREDENTIAL
    assert native.DreamstudioNode.connection_evidence.identity_operation == "get_account"
