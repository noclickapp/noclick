"""Exercise the real LibreTranslate node against documented response shapes.

Requests are intercepted with HTTPX; no account, translation charge or network is used.
"""
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError
from nodes import libretranslate_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-libretranslate-key-42"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/libretranslate/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="libretranslate-test", node_type="automation-libretranslate",
        node_data={"config": config, "credentials": credentials or {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}})


def transport(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["translate_text", "translate_html", "translate_auto_text", "translate_auto_html",
    "translate_batch_text", "translate_batch_html", "translate_alternatives"])
async def test_translation_variants_preserve_json_arrays_and_documented_output(monkeypatch, operation):
    batch = "batch" in operation
    html = operation.endswith("html")
    auto = "auto" in operation
    payload = {"translatedText": ["¡Hola!"]} if batch else FIXTURES["auto" if auto else "html" if html else "alternatives" if operation.endswith("alternatives") else "text"]
    requests = transport(monkeypatch, payload)
    result = await node({"operation": operation, "q": ["Hello!"] if batch else "Hello!", "target": "es"}).execute({})
    req = requests[0]
    assert len(requests) == 1 and req.method == "POST" and str(req.url) == native.BASE_URL + "/translate"
    body = json.loads(req.content)
    assert body == {"q": ["Hello!"] if batch else "Hello!", "source": "auto" if auto else "en", "target": "es",
        "format": "html" if html else "text", "alternatives": 3 if operation.endswith("alternatives") else 0, "api_key": TOKEN}
    assert result["data"] == payload and result["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,payload,config", [
    ("detect_language", "/detect", FIXTURES["detect"], {"q": "Bonjour!"}),
    ("check_connection", "/detect", FIXTURES["detect"], {}),
    ("list_languages", "/languages", [], {}),
    ("get_frontend_settings", "/frontend/settings", {"keyRequired": True, "supportedFilesFormat": ["txt"]}, {}),
    ("get_health", "/health", {"status": "ok"}, {}),
    ("suggest_translation", "/suggest", {"success": True}, {"q": "Hello world!", "s": "¡Hola mundo!", "source": "en", "target": "es"}),
])
async def test_other_contract_routes(monkeypatch, operation, path, payload, config):
    requests = transport(monkeypatch, payload)
    result = await node({"operation": operation, **config}).execute({})
    assert len(requests) == 1 and requests[0].url.path == path
    assert result["data"] == payload and result["identity_verified"] is False
    if path == "/detect":
        assert parse_qs(requests[0].content.decode()) == {"q": [config.get("q", "What language is this?")], "api_key": [TOKEN]}
    elif path == "/suggest":
        assert parse_qs(requests[0].content.decode()) == {k: [v] for k,v in config.items()}
        assert TOKEN not in requests[0].content.decode()
    else:
        assert requests[0].method == "GET" and not requests[0].url.query
        assert TOKEN not in str(requests[0].headers)


@pytest.mark.asyncio
async def test_file_upload_is_multipart_and_never_fetches_returned_url(monkeypatch):
    payload = {"translatedFileUrl": "https://libretranslate.com/translated/123/document_es.txt"}
    requests = transport(monkeypatch, payload)
    result = await node({"operation": "translate_file", "file_base64": base64.b64encode(b"Hello!").decode(), "file_name": "document.txt", "target": "es"}).execute({})
    assert len(requests) == 1 and requests[0].url.path == "/translate_file"
    assert requests[0].headers["content-type"].startswith("multipart/form-data;")
    for text in ['name="file"; filename="document.txt"', 'name="source"', 'name="target"', 'name="api_key"', 'Hello!', TOKEN]:
        assert text in requests[0].content.decode()
    assert result["data"] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 403, 429, 500, 302])
async def test_errors_are_reported_and_secret_redacted_without_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Invalid API key " + TOKEN}, status)
    result = await node({"operation": "check_connection"}).execute({})
    assert len(requests) == 1 and result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_200_error_envelope_is_not_success(monkeypatch):
    transport(monkeypatch, {"error": "Invalid API key"})
    result = await node({"operation": "check_connection"}).execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_malformed_translation_does_not_report_success(monkeypatch):
    transport(monkeypatch, {"translatedText": 42})
    with pytest.raises(ValueError, match="unexpected response"):
        await node({"operation": "translate_text", "q": "Hello!", "target": "es"}).execute({})


def test_manual_credential_default_and_secret_shaping():
    credential = native.LibreTranslateAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == native.CREDENTIAL_TYPE and credential.api_key == TOKEN
    with pytest.raises(ValidationError):
        native.LibreTranslateAPIKeyCredential(api_key="https://example.com/key")


@pytest.mark.parametrize("content", ["%%%", ""])
def test_invalid_inline_file_refused(content):
    with pytest.raises(ValidationError):
        native.TranslateFile(file_base64=content, target="es")
