"""Execute the factory against provider-authored v2 response examples.

Fixtures: https://raw.githubusercontent.com/NanoNets/api-docs/HEAD/nanonets_openapi_3.1.0.yaml
Version 2.0.0, sha256 aa540ed32c547b7c56319da70e848f43e657ad08d48f22543366a63c107a4e7f.
"""
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import nanonets_ocr_node as native
from nodes.core.registry import NodeFactory

MODEL = "00000000-0000-0000-0000-000000000000"
KEY = "synthetic-nanonets-key"
URL = "https://nanonets.s3-us-west-2.amazonaws.com/test-images/test1.jpg"
IMAGE = "data:image/png;base64,iVBORw0KGgo="
RESPONSES = json.loads((Path(__file__).parent / "fixtures/nanonets-ocr/responses.json").read_text())
CASES = [
    ("get_model", "GET", "/OCR/Model/{model_id}", {}),
    ("upload_training_urls", "POST", "/OCR/Model/{model_id}/UploadUrls", {"urls": [URL]}),
    ("upload_training_file", "POST", "/OCR/Model/{model_id}/UploadFile", {"file_reference": IMAGE}),
    ("train_model", "POST", "/OCR/Model/{model_id}/Train", {}),
    ("list_prediction_files", "GET", "/Inferences/Model/{model_id}/ImageLevelInferences", {"start_day_interval": 30, "current_batch_day": 1}),
    ("get_prediction_file", "GET", "/Inferences/Model/{model_id}/ImageLevelInferences/{id}", {"file_id": MODEL}),
    ("predict_urls", "POST", "/OCR/Model/{model_id}/LabelUrls", {"urls": [URL, URL + "?page=2"]}),
    ("predict_urls_async", "POST", "/OCR/Model/{model_id}/LabelUrls/", {"urls": [URL]}),
    ("predict_file", "POST", "/OCR/Model/{model_id}/LabelFile", {"file_reference": IMAGE}),
    ("predict_file_async", "POST", "/OCR/Model/{model_id}/LabelFile/", {"file_reference": IMAGE}),
    ("list_classification_models", "GET", "/ImageCategorization/Models", {}),
    ("get_classification_model", "GET", "/ImageCategorization/Model", {}),
    ("upload_classification_training_urls", "POST", "/ImageCategorization/UploadUrls", {"urls": [URL], "category": "category1"}),
    ("upload_classification_training_file", "POST", "/ImageCategorization/UploadFile", {"file_reference": IMAGE, "category": "category1"}),
    ("train_classification_model", "POST", "/ImageCategorization/Train", {}),
    ("classify_urls", "POST", "/ImageCategorization/LabelUrls", {"urls": [URL]}),
    ("classify_file", "POST", "/ImageCategorization/LabelFile", {"file_reference": IMAGE}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, fields=None):
    config = {"operation": operation, **({"model_id": MODEL} if operation != "list_classification_models" else {}), **(fields or {})}
    return NodeFactory.create_node(node_id="nanonets-test", node_type="automation-nanonets-ocr", node_data={
        "config": config, "credentials": {"credential_type": "nanonets_ocr_api_key", "api_key": KEY},
    })


def install(monkeypatch, response):
    calls = []
    def handle(request):
        calls.append(request)
        return response(request)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,route,fields", CASES)
async def test_published_operations(monkeypatch, operation, method, route, fields):
    example = RESPONSES[method + " " + route]
    calls = install(monkeypatch, lambda request: httpx.Response(200, json=example))
    result = await node(operation, fields).execute({})
    assert result["data"] == example and result["http_status"] == 200
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert str(request.url).split("?")[0] == native.BASE_URL + route.format(model_id=MODEL, id=MODEL)
    assert request.headers["authorization"] == "Basic " + base64.b64encode((KEY + ":").encode()).decode()
    query = dict(request.url.params)
    expected = {"async": "true"} if operation.endswith("_async") else {}
    if operation == "get_classification_model":
        expected = {"id": MODEL}
    if operation == "train_classification_model":
        expected = {"modelId": MODEL}
    if operation == "list_prediction_files":
        expected = {"start_day_interval": "30", "current_batch_day": "1"}
    assert query == expected
    if "urls" in fields:
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        body = parse_qs(request.content.decode())
        assert body["urls"] == fields["urls"]
        if route.startswith("/ImageCategorization"):
            assert body["modelId"] == [MODEL]
        if "category" in fields:
            assert body["category"] == ["category1"]
    elif "file_reference" in fields:
        from email import policy
        from email.parser import BytesParser
        message = BytesParser(policy=policy.default).parsebytes(
            ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode() + request.content)
        parts = {p.get_param("name", header="content-disposition"): p for p in message.iter_parts()}
        assert parts["file"].get_payload(decode=True) == b"\x89PNG\r\n\x1a\n"
        assert parts["file"].get_content_type() == "image/png"
        if operation == "upload_training_file":
            assert json.loads(parts["data"].get_content()) == [{"filename": parts["file"].get_filename()}]
        if route.startswith("/ImageCategorization"):
            assert parts["modelId"].get_content().strip() == MODEL
        if "category" in fields:
            assert parts["category"].get_content().strip() == "category1"
    else:
        assert request.content == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {"message": "Invalid API key"}), (429, {"message": "Too many requests"}), (500, {"message": "Server error"}), (302, {})])
async def test_rejections_are_not_retried(monkeypatch, status, payload):
    calls = install(monkeypatch, lambda request: httpx.Response(status, json=payload))
    with pytest.raises(ValueError, match=f"Nanonets HTTP {status}"):
        await node("get_model").execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"error": "invalid model"}, {"status": "failed"}])
async def test_bad_envelopes(monkeypatch, payload):
    install(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await node("get_model").execute({})


@pytest.mark.asyncio
async def test_non_json_and_secret_redaction(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(401, text="Invalid key: " + KEY))
    with pytest.raises(ValueError) as error:
        await node("get_model").execute({})
    assert KEY not in str(error.value)
    install(monkeypatch, lambda request: httpx.Response(200, text="<html>Unavailable</html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        await node("get_model").execute({})


@pytest.mark.parametrize("model_id", ["../other", "x/y", "x?query", "https://example.com"])
def test_model_path_injection(model_id):
    with pytest.raises(ValidationError):
        native.GetModel(model_id=model_id)


@pytest.mark.parametrize("key", ["https://example.com/key", "Basic abc", "abc:def", "<token>"])
def test_key_validation(key):
    with pytest.raises(ValidationError):
        native.NanonetsOcrAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
async def test_evidence_uses_account_read_only(monkeypatch):
    calls = install(monkeypatch, lambda request: httpx.Response(200, json=RESPONSES["GET /ImageCategorization/Models"]))
    assert native.NanonetsOcrNode.connection_evidence.operation == "list_classification_models"
    result = await node("list_classification_models").execute({})
    from nodes.core.connection_evidence import _rows_from_operation
    assert _rows_from_operation(result)[0]["model_id"] == MODEL
    assert calls[0].method == "GET" and not calls[0].url.query


@pytest.mark.asyncio
async def test_inline_pdf_bytes_and_training_filename(monkeypatch):
    calls = install(monkeypatch, lambda request: httpx.Response(200, json={"message": "Success"}))
    pdf = b"%PDF-1.4\n%%EOF"
    await node("upload_training_file", {"file_base64": base64.b64encode(pdf).decode(), "filename": "invoice.pdf"}).execute({})
    assert pdf in calls[0].content
    assert b'filename="invoice.pdf"' in calls[0].content
    assert b'[{"filename": "invoice.pdf"}]' in calls[0].content


def test_exactly_one_file_source():
    for fields in ({}, {"file_reference": IMAGE, "file_base64": "YWJj"}):
        with pytest.raises(ValidationError, match="exactly one"):
            native.PredictFile(model_id=MODEL, **fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["upload_training_urls", "predict_urls"])
async def test_documented_partial_url_response(monkeypatch, operation):
    calls = install(monkeypatch, lambda request: httpx.Response(202))
    result = await node(operation, {"urls": [URL]}).execute({})
    assert result["http_status"] == 202 and result["partial"] is True
    assert result["data"] is None and len(calls) == 1
