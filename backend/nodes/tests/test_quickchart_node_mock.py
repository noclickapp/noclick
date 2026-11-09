"""Native factory tests; every provider request stays on a mock transport."""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import quickchart_node as qc
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence
from utils import ssrf

AUTH = {"credential_type": "quickchart_api_key", "api_key": "fixture-quickchart-key"}
CHART = {"type": "bar", "data": {"labels": ["Hello", "World"], "datasets": [{"label": "Foo", "data": [1, 2]}]}}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "quickchart.io"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, payload, headers = replies.pop(0)
        kwargs = {"json": payload} if isinstance(payload, dict) else {"content": payload}
        return httpx.Response(status, headers=headers, **kwargs)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(qc, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    node = NodeFactory.create_node(node_id="quickchart-test", node_type="automation-quickchart",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": AUTH})
    return await node.execute({})


CASES = [
    ("check_connection", {}, "GET", "/qr", b"png", {"Content-Type": "image/png", "X-quickchart-verified-key": "1"}),
    ("render_chart", {"chart": CHART}, "POST", "/chart", b"png", {"Content-Type": "image/png"}),
    ("create_chart_url", {"chart": CHART}, "POST", "/chart/create", {"success": True, "url": "https://quickchart.io/chart/render/id"}, {}),
    ("validate_chart", {"chart": CHART}, "POST", "/api/validate-chart", {"success": True, "errors": [], "warnings": [], "normalized": {}}, {}),
    ("render_word_cloud", {"text": "To be or not to be"}, "POST", "/wordcloud", b"png", {"Content-Type": "image/png"}),
    ("render_table", {"data": {"columns": [{"title": "Column 1", "dataIndex": "col1"}], "dataSource": [{"col1": "Foo"}]}}, "POST", "/v1/table", b"png", {"Content-Type": "image/png"}),
    ("watermark_image", {"mainImageUrl": "https://example.com/a.png", "markImageUrl": "https://example.com/b.png"}, "POST", "/watermark", b"png", {"Content-Type": "image/png"}),
    ("render_diagram", {"graph": "graph{a--b}"}, "POST", "/graphviz", b"png", {"Content-Type": "image/png"}),
    ("render_qr", {"text": "Hello world"}, "POST", "/qr", b"png", {"Content-Type": "image/png"}),
    ("validate_qr", {"text": "Hello world"}, "POST", "/api/validate-qr", {"success": True, "errors": [], "warnings": [], "normalized": {}}, {}),
    ("build_qr_url", {"text": "Hello world"}, "POST", "/qr-url", {"url": "https://quickchart.io/qr?text=Hello%20world"}, {}),
    ("build_qr_urls", {"qrCodes": [{"text": "Hello world"}]}, "POST", "/qr-urls", {"urls": ["https://quickchart.io/qr?text=Hello%20world"]}, {}),
    ("batch_qr", {"qrCodes": [{"text": "Hello world", "filename": "hello.png"}]}, "POST", "/qr/batch", b"PK\x03\x04", {"Content-Type": "application/zip"}),
    ("render_barcode", {"type": "code128", "text": "12345"}, "POST", "/barcode", b"png", {"Content-Type": "image/png"}),
    ("read_qr", {"url": "https://example.com/qr.png"}, "GET", "/qr-read", {"result": "Hello world"}, {}),
    ("generate_chart_config", {"description": "A bar chart"}, "POST", "/natural/config", {"success": True, "chart": "{}", "chartUrl": "https://quickchart.io/chart/render/id"}, {}),
]


@pytest.mark.parametrize("operation,arguments,method,path,payload,headers", CASES)
@pytest.mark.asyncio
async def test_every_operation_exact_request(wire, operation, arguments, method, path, payload, headers):
    requests, replies = wire
    replies.append((200, payload, headers))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert (request.method, request.url.path) == (method, path)
    if method == "POST":
        body = json.loads(request.content)
        assert "operation" not in body
        assert body.get("key") == (AUTH["api_key"] if operation == "create_chart_url" else None)
        for key, value in arguments.items():
            if key == "qrCodes":
                for actual, expected in zip(body[key], value):
                    assert all(actual[k] == v for k, v in expected.items())
            else:
                assert body[key] == value
    else:
        assert request.url.params["text" if operation == "check_connection" else "url"] == ("Hello world" if operation == "check_connection" else arguments["url"])
    if "base64" in result:
        assert base64.b64decode(result["base64"]) == payload
    if isinstance(payload, dict):
        assert result["data"] == payload


@pytest.mark.parametrize("media,payload", [("image/svg+xml", b"<svg/>"), ("application/pdf", b"%PDF-1.7"), ("image/webp", b"RIFF"), ("text/plain", b"aGVsbG8=")])
@pytest.mark.asyncio
async def test_render_media_and_base64_are_preserved(wire, media, payload):
    wire[1].append((200, payload, {"Content-Type": media}))
    result = await run("render_chart", {"chart": CHART})
    assert result["base64"] == (payload.decode() if media == "text/plain" else base64.b64encode(payload).decode())


@pytest.mark.parametrize("headers", [{}, {"X-quickchart-verified-key": "0"}])
@pytest.mark.asyncio
async def test_free_render_does_not_verify_key(wire, headers):
    wire[1].append((200, b"png", {"Content-Type": "image/png", **headers}))
    with pytest.raises(ValueError, match="recognition is unverified"):
        await run("check_connection")


@pytest.mark.asyncio
async def test_actual_connection_evidence_recognizes_only_verified_key(wire):
    wire[1].append((200, b"png", {"Content-Type": "image/png", "X-quickchart-verified-key": "1"}))
    result = await collect_evidence(node_type="automation-quickchart", credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert result.reachable is True
    assert qc.QuickChartNode.connection_evidence.proves == "reachability"


@pytest.mark.parametrize("status,payload,headers,match", [
    (400, b"png", {"Content-Type": "image/png", "X-quickchart-error": "Invalid chart"}, "Invalid chart"),
    (403, {"error": "Forbidden"}, {}, "Forbidden"),
    (429, b"Too many requests", {"Content-Type": "text/plain"}, "Too many requests"),
    (302, b"", {"Location": "https://other.example/"}, "HTTP 302"),
])
@pytest.mark.asyncio
async def test_errors_are_not_render_success(wire, status, payload, headers, match):
    wire[1].append((status, payload, headers))
    with pytest.raises(ValueError, match=match):
        await run("render_chart", {"chart": CHART})
    assert len(wire[0]) == 1


@pytest.mark.asyncio
async def test_json_error_envelope_and_redaction(wire):
    wire[1].append((200, {"success": False, "error": "Bad " + AUTH["api_key"]}, {}))
    with pytest.raises(ValueError) as exc:
        await run("create_chart_url", {"chart": CHART})
    assert AUTH["api_key"] not in str(exc.value)


def test_manual_credential_default_and_required_fields():
    credential = qc.QuickChartAPIKey.model_validate({"api_key": AUTH["api_key"]})
    assert credential.credential_type == "quickchart_api_key"
    assert {k for k, f in qc.QuickChartAPIKey.model_fields.items() if f.is_required()} == {"api_key"}


@pytest.mark.parametrize("key", ["", "Bearer abc", "abc\n123", "https://example.com", "<token>"])
def test_invalid_key_shape(key):
    with pytest.raises(ValueError):
        qc.QuickChartAPIKey(api_key=key)


EXAMPLES = json.loads((Path(__file__).parent / "fixtures/quickchart/published_examples.json").read_text())


@pytest.mark.parametrize("operation", ["create_chart_url", "validate_chart", "build_qr_url", "build_qr_urls", "read_qr"])
@pytest.mark.asyncio
async def test_provider_published_examples(wire, operation):
    method, path = qc.ROUTES[operation]
    payload = EXAMPLES["responses"][method + " " + path]["body"]
    wire[1].append((200, payload, {}))
    result = await run(operation, EXAMPLES["inputs"][operation]["config"])
    assert result["data"] == payload


@pytest.mark.asyncio
async def test_validation_failure_is_usable_structured_output(wire):
    payload = {"success": False, "errors": ["Chart error: Invalid input"], "warnings": [], "normalized": {}}
    wire[1].append((200, payload, {}))
    result = await run("validate_chart", {"chart": CHART})
    assert result == {"status": "success", "data": payload}
