"""Offline Recraft transport, provider response, and connect regressions."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import recraft_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-recraft-api-token"
ID = "0e6a1b8c-5b1f-4a8e-9f3a-2c7d4e8b9a10"
IMAGE = "https://example.com/input.png"
MASK = "https://example.com/mask.png"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/recraft/responses.json").read_text())
STYLE = {"id": ID, "style": "digital_illustration", "creation_time": "2026-11-09T00:00:00Z", "is_private": True}
# Expected requests are independent of the node's dispatch table.
CASES = [
    ("get_current_user", "GET", "/v1/users/me", {}, {"id": ID, "name": "Example account", "credits": 12}),
    ("list_styles", "GET", "/v1/styles", {}, {"styles": [STYLE]}),
    ("list_basic_styles", "GET", "/v1/styles/basic", {}, {"styles": [{"style_id": ID, "style": "realistic_image", "model": "recraftv3"}]}),
    ("get_style", "GET", f"/v1/styles/{ID}", {"style_id": ID}, STYLE),
    ("delete_style", "DELETE", f"/v1/styles/{ID}", {"style_id": ID}, {}),
    ("create_style", "POST", "/v1/styles", {"image_urls": [IMAGE], "style": "digital_illustration"}, {**STYLE, "credits": 5}),
    ("generate_image", "POST", "/v1/images/generations", {"prompt": "minimal fox logo, flat"}, FIXTURE["generated"]),
    ("generate_raster", "POST", "/v1/images/generations/raster", {"prompt": "minimal fox logo, flat"}, FIXTURE["generated"]),
    ("generate_vector", "POST", "/v1/images/generations/vector", {"prompt": "minimal fox logo, flat"}, FIXTURE["generated"]),
    ("image_to_image", "POST", "/v1/images/imageToImage", {"image_url": IMAGE, "prompt": "a green velvet armchair", "strength": 0.5}, FIXTURE["generated"]),
    ("inpaint", "POST", "/v1/images/inpaint", {"image_url": IMAGE, "mask_url": MASK, "prompt": "a green velvet armchair"}, FIXTURE["generated"]),
    ("generate_background", "POST", "/v1/images/generateBackground", {"image_url": IMAGE, "mask_url": MASK, "prompt": "a green velvet armchair"}, FIXTURE["generated"]),
    ("replace_background", "POST", "/v1/images/replaceBackground", {"image_url": IMAGE, "prompt": "a green velvet armchair"}, FIXTURE["generated"]),
    ("outpaint", "POST", "/v1/images/outpaint", {"image_url": IMAGE, "prompt": "a green velvet armchair", "expand_left": 256}, FIXTURE["generated"]),
    ("variate_image", "POST", "/v1/images/variateImage", {"image_url": IMAGE, "size": "1024x1024"}, FIXTURE["generated"]),
    ("remove_background", "POST", "/v1/images/removeBackground", {"image_url": IMAGE}, FIXTURE["processed"]),
    ("crisp_upscale", "POST", "/v1/images/crispUpscale", {"image_url": IMAGE}, FIXTURE["processed"]),
    ("creative_upscale", "POST", "/v1/images/creativeUpscale", {"image_url": IMAGE}, FIXTURE["processed"]),
    ("enhance_image", "POST", "/v1/images/enhance", {"image_url": IMAGE, "refinement": "subtle"}, FIXTURE["processed"]),
    ("erase_region", "POST", "/v1/images/eraseRegion", {"image_url": IMAGE, "mask_url": MASK}, FIXTURE["processed"]),
    ("vectorize_image", "POST", "/v1/images/vectorize", {"image_url": IMAGE, "shape_stacking": "cut_out"}, FIXTURE["processed"]),
]


def node(operation, **config):
    return NodeFactory.create_node(node_id="recraft-fixture", node_type="automation-recraft", node_data={
        "config": {"operation": operation, **config},
        "credentials": {"credential_type": native.CREDENTIAL_TYPE, "api_token": TOKEN},
    })


def transport(monkeypatch, payload, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,config,payload", CASES)
async def test_recraft_one_contract_request_and_response(monkeypatch, operation, method, path, config, payload):
    calls = transport(monkeypatch, payload)
    result = await node(operation, **config).execute({})
    assert result == {"status": "success", "data": payload}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert str(request.url) == native.BASE + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if method == "POST":
        expected = dict(config)
        if path.startswith("/v1/images/"):
            expected["response_format"] = "url"
        assert json.loads(request.content) == expected
        assert request.headers["content-type"] == "application/json"
    else:
        assert request.content == b""


@pytest.mark.asyncio
async def test_recraft_nested_controls_seed_style_and_zero_false_values(monkeypatch):
    calls = transport(monkeypatch, FIXTURE["generated"])
    config = {"prompt": "minimal fox logo, flat", "model": "recraftv4_1_vector", "size": "1:1", "random_seed": 0,
        "controls": {"no_text": False, "colors": [{"rgb": [255, 102, 0], "weight": 0.5}]}, "zdr": False, "n": 2}
    await node("generate_image", **config).execute({})
    assert json.loads(calls[0].content) == {**config, "response_format": "url"}


@pytest.mark.asyncio
async def test_recraft_base64_response_field_is_never_returned(monkeypatch):
    payload = copy.deepcopy(FIXTURE["generated"])
    payload["data"][0]["b64_json"] = "provider-base64-image-body"
    transport(monkeypatch, payload)
    assert await node("generate_image", prompt="fox").execute({}) == {"status": "success", "data": FIXTURE["generated"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_recraft_provider_errors_are_not_success_or_retried(monkeypatch, status):
    calls = transport(monkeypatch, {"message": "Invalid token " + TOKEN}, status)
    with pytest.raises(ValueError, match=f"Recraft API {status}") as error:
        await node("get_current_user").execute({})
    assert TOKEN not in str(error.value)
    assert "Invalid token" in str(error.value) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {}, {"data": []}, {"id": "invalid", "credits": 10}])
async def test_recraft_malformed_account_response_fails(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError, match="unexpected response shape"):
        await node("get_current_user").execute({})


def test_recraft_manual_credential_default_and_foreign_family():
    credential = native.RecraftAPITokenCredential(api_token="  " + TOKEN + "  ")
    assert credential.api_token == TOKEN and credential.credential_type == native.CREDENTIAL_TYPE
    for token in ["Bearer token", "https://example.com/key", "<token>", ""]:
        with pytest.raises((ValueError, ValidationError)):
            native.RecraftAPITokenCredential(api_token=token)
    result = native.RecraftNode.validate_config({"config": {"operation": "get_current_user"},
        "credentials": {"credential_type": "foreign_token", "api_token": TOKEN}})
    assert not result["valid"]


@pytest.mark.parametrize("config", [
    {"operation": "image_to_image", "image_url": IMAGE, "prompt": "fox"},
    {"operation": "inpaint", "image_url": IMAGE, "prompt": "fox"},
    {"operation": "create_style", "image_urls": []},
    {"operation": "get_style", "style_id": "../../me"},
    {"operation": "outpaint", "image_url": IMAGE, "prompt": "fox"},
    {"operation": "outpaint", "image_url": IMAGE, "prompt": "fox", "size": "1024x1024", "expand_left": 256},
])
def test_recraft_required_inputs_and_constraints(config):
    assert not native.RecraftNode.validate_config({"config": config})["valid"]


@pytest.mark.asyncio
async def test_recraft_connect_evidence_uses_current_account(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    calls = transport(monkeypatch, {"id": ID, "name": "Example account", "credits": 12})
    result = await collect_evidence(node_type="automation-recraft", user_id="fixture", pool=None,
        credential_data={"credential_type": native.CREDENTIAL_TYPE, "api_token": TOKEN})
    assert result.reachable is True and result.account_label == "Example account"
    assert len(calls) == 1 and calls[0].url.path == "/v1/users/me"
