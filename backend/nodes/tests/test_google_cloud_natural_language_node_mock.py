"""Request-wire checks and parsing of Google's published sentiment example."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.google_cloud_natural_language_node import (
    GoogleCloudNaturalLanguageNode, GoogleCloudNaturalLanguageNodeConfig,
    GoogleCloudNaturalLanguageAPIKeyCredential, ROUTES,
)

KEY = "unit-test-gcnl-key"
RESPONSE = json.loads((Path(__file__).parent / "fixtures/google-cloud-natural-language/sentiment.json").read_text())


def node(config):
    parsed = GoogleCloudNaturalLanguageNodeConfig.model_validate({
        "config": config, "credentials": {"api_key": KEY}})
    return GoogleCloudNaturalLanguageNode("test", "automation-google-cloud-natural-language", {}, config=parsed)


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize("action,route", list(ROUTES.items()))
@pytest.mark.parametrize("storage", [False, True])
async def test_google_cloud_natural_language_document_wire(monkeypatch, action, route, storage):
    operation = action + ("_from_storage" if storage else "")
    config = {"operation": operation, "document_type": "HTML", "language": "en"}
    config.update({"gcs_content_uri": "gs://cloud-samples-data/language/sentiment-positive.txt"}
        if storage else {"content": "Enjoy your vacation!"})
    def handler(request):
        assert request.method == "POST"
        assert str(request.url) == "https://language.googleapis.com/v1/documents:" + route
        assert request.headers["x-goog-api-key"] == KEY
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["document"] == {"type": "HTML", "language": "en",
            **({"gcsContentUri": config["gcs_content_uri"]} if storage else {"content": config["content"]})}
        if action in {"moderate_text", "classify_text"}:
            assert "encodingType" not in body
        else:
            assert body["encodingType"] == "UTF8"
        if action == "classify_text":
            assert body["classificationModelOptions"] == {"v2Model": {}}
        if action == "annotate_text":
            assert body["features"] == {"extractDocumentSentiment": True, "extractEntities": True,
                "extractSyntax": True, "extractEntitySentiment": False, "classifyText": False, "moderateText": False}
        return httpx.Response(200, json=RESPONSE)
    transport(monkeypatch, handler)
    result = await node(config).execute({})
    assert result == {"status": "success", "operation": operation, "data": RESPONSE}


@pytest.mark.asyncio
async def test_google_cloud_natural_language_connection_probe(monkeypatch):
    def handler(request):
        assert request.url.path == "/v1/documents:analyzeSentiment"
        assert json.loads(request.content) == {"document": {"type": "PLAIN_TEXT", "content": "Hello, world!"}}
        return httpx.Response(200, json=RESPONSE)
    transport(monkeypatch, handler)
    result = await node({"operation": "check_connection"}).execute({})
    assert result["status"] == "success"
    assert GoogleCloudNaturalLanguageNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
async def test_google_cloud_natural_language_features_and_classification(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["features"]["classificationModelOptions"] == {"v1Model": {}}
        assert body["features"]["classifyText"] is True
        assert body["features"]["moderateText"] is True
        return httpx.Response(200, json={"categories": []})
    transport(monkeypatch, handler)
    result = await node({"operation": "annotate_text", "content": "Enjoy your vacation!",
        "classify_text": True, "moderate_text": True, "classification_model": "v1"}).execute({})
    assert result["data"] == {"categories": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(403, {"error": {"message": "API key rejected: " + KEY}}),
    (429, {"error": {"message": "Quota exceeded"}}), (200, []), (200, {"error": {"message": "Failure"}}), (302, {})])
async def test_google_cloud_natural_language_errors(monkeypatch, status, payload):
    transport(monkeypatch, lambda request: httpx.Response(status, json=payload))
    result = await node({"operation": "check_connection"}).execute({})
    assert result["status"] == "error"
    assert KEY not in json.dumps(result)
    if status == 429:
        assert result["error"] == "Quota exceeded"


@pytest.mark.asyncio
async def test_google_cloud_natural_language_network_error_hides_key(monkeypatch):
    def handler(request):
        raise httpx.ConnectError(KEY, request=request)
    transport(monkeypatch, handler)
    result = await node({"operation": "check_connection"}).execute({})
    assert result["status"] == "error"
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize("config", [
    {"operation": "analyze_sentiment", "content": ""},
    {"operation": "analyze_sentiment", "content": "hello", "gcs_content_uri": "gs://bucket/file"},
    {"operation": "analyze_sentiment_from_storage", "gcs_content_uri": "https://example.com"},
    {"operation": "analyze_sentiment_from_storage", "gcs_content_uri": "gs://bucket/file#version"},
    {"operation": "annotate_text", "content": "hello", "extract_document_sentiment": False,
        "extract_entities": False, "extract_syntax": False},
])
def test_google_cloud_natural_language_rejects_invalid_document(config):
    with pytest.raises(ValidationError):
        node(config)


def test_google_cloud_natural_language_manual_key():
    credential = GoogleCloudNaturalLanguageAPIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == "google_cloud_natural_language_api_key"
    assert credential.api_key == KEY
    with pytest.raises(ValidationError):
        GoogleCloudNaturalLanguageAPIKeyCredential(api_key="https://console.cloud.google.com")


@pytest.mark.parametrize("key", ["not a key", "token–typo", "https://console.cloud.google.com"])
def test_google_cloud_natural_language_bad_key_paste(key):
    with pytest.raises(ValidationError):
        GoogleCloudNaturalLanguageAPIKeyCredential(api_key=key)
