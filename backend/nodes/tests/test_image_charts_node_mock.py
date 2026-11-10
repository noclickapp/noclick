"""Factory execution, signing, documented image and failure boundaries."""
import hashlib
import hmac
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import image_charts_node as ic
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "image_charts_api_key", "account_id": "test-account", "secret_key": "fixture-signing-key"}
PNG = (Path(__file__).parent / "fixtures/image-charts/hello-world.png").read_bytes()


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "image-charts.com"
        assert AUTH["secret_key"] not in str(request.url)
        raw, signature = request.url.query.decode().rsplit("&ichm=", 1)
        assert signature == hmac.new(AUTH["secret_key"].encode(), raw.encode(), hashlib.sha256).hexdigest()
        assert request.url.params["icac"] == AUTH["account_id"]
        return replies.pop(0)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(ic, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, credentials=AUTH):
    node = NodeFactory.create_node(node_id="image-charts-test", node_type="automation-image-charts",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": credentials})
    return await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,chart_type", list(ic.CHART_TYPES.items()) + [("render_chartjs", None), ("check_connection", "qr")])
async def test_image_charts_every_action_one_signed_get(wire, operation, chart_type):
    # Numeric data is copied from the provider's bar-chart example; the QR
    # payload/image is the provider's documented Hello world example.
    args = {"c": "{type:'bar',data:{datasets:[{data:[10,20,30,40]}]}}"} if chart_type is None else {"chl": "Hello world"} if operation == "render_qr" else {} if operation == "check_connection" else {"chd": "t:5,5,5|10,10,10|15,15,15"}
    wire[1].append(httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"}))
    result = await run(operation, args)
    assert len(wire[0]) == 1 and not wire[1]
    request = wire[0][0]
    assert request.method == "GET" and not request.content
    assert request.url.path == ("/chart.js/2.8.0" if chart_type is None else "/chart")
    assert "operation" not in request.url.params
    if chart_type:
        assert request.url.params["cht"] == chart_type
        assert request.url.params["chs"] == ("150x150" if operation == "check_connection" else "500x300")
    for key, value in args.items():
        assert request.url.params[key] == value
    if operation == "check_connection":
        assert result == {"status": "success", "signed_render_accepted": True, "identity_verified": False}
    else:
        assert isinstance(result["file"], BinaryOutput)
        assert result["file"].data == PNG
        assert result["file"].content_type == "image/png"


def test_image_charts_signing_preserves_special_characters():
    credential = ic.ImageChartsAPIKey(**AUTH)
    query = ic.signed_query({"cht": "qr", "chl": "A&B + 50% / हिन्दी"}, credential)
    raw, signature = query.rsplit("&ichm=", 1)
    assert "chl=A%26B+%2B+50%25+%2F+" in raw
    assert signature == hmac.new(AUTH["secret_key"].encode(), raw.encode(), hashlib.sha256).hexdigest()
    assert dict(httpx.QueryParams(query))["chl"] == "A&B + 50% / हिन्दी"


@pytest.mark.asyncio
@pytest.mark.parametrize("media,body,extension", [("application/png", PNG, "png"), ("image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"/>', "svg"), ("application/gif", b"GIF89a", "gif")])
async def test_image_charts_binary_formats(wire, media, body, extension):
    wire[1].append(httpx.Response(200, content=body, headers={"Content-Type": media}))
    result = await run("render_qr", {"chl": "Hello world"})
    assert result["file"].filename.endswith("." + extension)
    assert result["file"].data == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status,headers", [(401, {"x-ic-error-code": "IC_INVALID_SIGNATURE"}), (403, {"x-ic-error-code": "IC_ACCOUNT_ID_NOT_FOUND"}), (400, {"x-ic-error-code": "IS_VALIDATION_ERROR", "x-ic-error-validation": '["bad data"]'}), (429, {}), (502, {}), (302, {"Location": "https://example.com"}), (200, {"x-ic-error-code": "IC_INVALID_SIGNATURE"})])
async def test_image_charts_provider_rejections(wire, status, headers):
    wire[1].append(httpx.Response(status, content=b"error", headers=headers))
    with pytest.raises(ValueError, match=headers.get("x-ic-error-code", "Image-Charts HTTP")):
        await run("check_connection")
    assert len(wire[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("media,body", [("text/html", b"<html/>"), ("image/png", b"")])
async def test_image_charts_unexpected_response(wire, media, body):
    wire[1].append(httpx.Response(200, content=body, headers={"Content-Type": media}))
    with pytest.raises(ValueError, match="unexpected image"):
        await run("check_connection")


@pytest.mark.asyncio
async def test_image_charts_connection_evidence(wire):
    wire[1].append(httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"}))
    result = await collect_evidence(node_type="automation-image-charts", credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert result.reachable is True
    assert ic.ImageChartsNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
async def test_image_charts_missing_credential(wire):
    with pytest.raises(ValueError, match="Connect an Image-Charts"):
        await run("check_connection", credentials=None)
    assert wire[0] == []


@pytest.mark.parametrize("credential", [{**AUTH, "credential_type": "another_key"}, {**AUTH, "secret_key": "https://example.com"}, {**AUTH, "account_id": "a\nb"}])
def test_image_charts_manual_credential_validation(credential):
    with pytest.raises(ValueError):
        ic.ImageChartsAPIKey.model_validate(credential)


@pytest.mark.parametrize("config", [{"operation": "render_bar", "chd": "bad data"}, {"operation": "render_qr", "chl": "Hello", "width": 1000}, {"operation": "render_chartjs", "c": "{}", "extra_params": {"ichm": "override"}}])
def test_image_charts_invalid_config(config):
    assert not ic.ImageChartsNode.validate_config({"config": config})["valid"]
