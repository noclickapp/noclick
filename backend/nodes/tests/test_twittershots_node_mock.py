"""HTTP-boundary coverage of the two published TwitterShots operations.

JSON fixtures are from https://twittershots.com/docs/api and
https://twittershots.com/docs/api/get-usage. All credentials are synthetic.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import twittershots_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures/twittershots"
TOKEN = "synthetic-twittershots-key"
TWEET = "1998506701201473808"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="twittershots-test", node_type="automation-twittershots",
        node_data={"config": config, "credentials": {"credential_type": "twittershots_api_key", "api_key": TOKEN}})


def mock_client(monkeypatch, respond):
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("format,mime,content", [
    ("svg", "image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
    ("png", "image/png", b"\x89PNG\r\n\x1a\n"),
    ("html", "text/html", b"<!doctype html><p>Tweet</p>"),
])
@pytest.mark.parametrize("theme", ["light", "dark"])
async def test_twittershots_file_wire_contract(format, mime, content, theme, monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.twittershots.com"
        assert request.url.path == "/api/v1/screenshot/" + TWEET
        assert dict(request.url.params) == {"format": format, "theme": theme, "returnType": "buffer"}
        assert request.headers["X-API-KEY"] == TOKEN
        assert TOKEN not in str(request.url) and not request.content
        return httpx.Response(200, content=content, headers={"Content-Type": mime,
            "X-Quota-Remaining": "295", "X-Quota-Limit": "300"})
    mock_client(monkeypatch, respond)
    result = await node({"operation": "get_tweet_screenshot", "tweet_id": TWEET,
                         "format": format, "theme": theme}).execute({})
    assert len(calls) == 1 and result["status"] == "success"
    assert isinstance(result["file"], BinaryOutput)
    assert result["file"].data == content and result["file"].content_type == mime
    assert result["file"].filename == f"tweet-{TWEET}.{format}"
    assert result["quota_remaining"] == 295 and result["quota_limit"] == 300


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fixture", [("get_api_usage", "usage"), ("get_tweet_screenshot", "screenshot")])
async def test_twittershots_documented_json(operation, fixture, monkeypatch):
    body = json.loads((FIXTURES / (fixture + ".json")).read_text())
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == "GET" and request.headers["X-API-KEY"] == TOKEN
        assert request.headers["Accept"] == "application/json"
        assert request.url.host == "api.twittershots.com" and not request.content
        if operation == "get_api_usage":
            assert request.url.path == "/api/v1/usage" and not request.url.query
        else:
            assert request.url.path == "/api/v1/screenshot/" + TWEET
            assert dict(request.url.params) == {"format": "svg", "theme": "light", "returnType": "url"}
        return httpx.Response(200, json=body)
    mock_client(monkeypatch, respond)
    config = {"operation": operation}
    if fixture == "screenshot":
        config.update(tweet_id=f"https://x.com/example/status/{TWEET}?s=20", return_type="url")
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == body and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_twittershots_rejection_no_retry_or_key_leak(status, monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"message": "Rejected " + TOKEN})
    mock_client(monkeypatch, respond)
    result = await node({"operation": "get_api_usage"}).execute({})
    assert result == {"status": "error", "http_status": status, "message": "Rejected [redacted]"}
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"remaining": True, "limit": 1}, {"remaining": 1}, {"error": "Rejected"}])
async def test_twittershots_evidence_requires_quota(body, monkeypatch):
    mock_client(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "get_api_usage"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("content,mime", [(b"<html>Sign in</html>", "text/html"), (b"invalid", "application/json")])
async def test_twittershots_invalid_json_response(content, mime, monkeypatch):
    mock_client(monkeypatch, lambda r: httpx.Response(200, content=content, headers={"content-type": mime}))
    with pytest.raises(ValueError):
        await node({"operation": "get_api_usage"}).execute({})


@pytest.mark.asyncio
async def test_twittershots_transport_failure_is_not_confirmation(monkeypatch):
    def respond(request):
        raise httpx.ReadTimeout(TOKEN, request=request)
    mock_client(monkeypatch, respond)
    with pytest.raises(ValueError, match="could not be confirmed") as exc:
        await node({"operation": "get_api_usage"}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize("value", ["", "https://twittershots.com/settings/keys", "a\nb", "your_api_key", "nonascii—key"])
def test_twittershots_bad_key(value):
    with pytest.raises(ValidationError):
        native.TwittershotsAPIKeyCredential(api_key=value)


def test_twittershots_manual_connect_default_and_evidence():
    shaped, errors, resolved = shape_credential("twittershots_api_key", {"api_key": "  " + TOKEN + "  "})
    assert not errors and shaped == {"api_key": TOKEN}
    assert resolved[1] is native.TwittershotsAPIKeyCredential
    assert native.TwittershotsAPIKeyCredential.model_validate(shaped).credential_type == "twittershots_api_key"
    assert native.TwittershotsNode.connection_evidence.operation == "get_api_usage"
    assert native.TwittershotsNode.connection_evidence.proves == "reachability"


@pytest.mark.parametrize("value", ["../usage", "1/../usage", "https://evil.example/status/123", "https://x.com.evil.example/a/status/123", "https://u@x.com/a/status/123", "https://x.com:443/a/status/123"])
def test_twittershots_rejects_other_paths_and_hosts(value):
    with pytest.raises(ValueError):
        node({"operation": "get_tweet_screenshot", "tweet_id": value})


@pytest.mark.parametrize("field,value", [("format", "jpeg"), ("theme", "auto"), ("return_type", "base64")])
def test_twittershots_only_contract_options(field, value):
    with pytest.raises(ValueError):
        node({"operation": "get_tweet_screenshot", "tweet_id": TWEET, field: value})
