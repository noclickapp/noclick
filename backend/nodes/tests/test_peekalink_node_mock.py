"""Offline request and response evidence for the single Peekalink operation."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import peekalink_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

EXAMPLE = json.loads((Path(__file__).parent / "fixtures/peekalink/preview.json").read_text())["body"]
CREDENTIAL = {"credential_type": "peekalink_api_key", "api_key": "synthetic-peekalink-key"}
LINK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def node(**config):
    return NodeFactory.create_node(node_id="peekalink-test", node_type="automation-peekalink", node_data={
        "config": {"operation": "get_link_preview", "link": LINK, **config}, "credentials": CREDENTIAL,
    })


def transport(monkeypatch, *, status=200, body=EXAMPLE, raw=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if raw is None else httpx.Response(status, content=raw)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_preview_exact_contract_request_and_published_response(monkeypatch):
    requests = transport(monkeypatch)
    assert await node().execute({}) == {"status": "success", "data": EXAMPLE}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.peekalink.io/"
    assert request.headers["Authorization"] == "Bearer synthetic-peekalink-key"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {"link": LINK, "source": "API"}
    assert "accept-language" not in request.headers


@pytest.mark.asyncio
async def test_optional_fields_keep_contract_names_and_string_boolean_types(monkeypatch):
    requests = transport(monkeypatch)
    await node(accept_language="en-US,en;q=0.9", source="WEB", forceNewSnapshot="false", forceNewSnapshotRecursive="true").execute({})
    assert requests[0].headers["Accept-Language"] == "en-US,en;q=0.9"
    assert json.loads(requests[0].content) == {
        "link": LINK, "source": "WEB", "forceNewSnapshot": "false", "forceNewSnapshotRecursive": "true",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 400, 401, 403, 429, 500, 503])
async def test_http_failure_keeps_provider_message_and_is_never_retried(monkeypatch, code):
    requests = transport(monkeypatch, status=code, body={"ok": False, "status": code, "message": "The API key is invalid or expired."})
    with pytest.raises(httpx.HTTPStatusError, match="The API key is invalid or expired"):
        await node().execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_http_and_json_error_messages_do_not_echo_key(monkeypatch):
    error = {"ok": False, "status": 401, "message": "Rejected " + CREDENTIAL["api_key"]}
    transport(monkeypatch, status=401, body=error)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        await node().execute({})
    assert CREDENTIAL["api_key"] not in str(caught.value)
    transport(monkeypatch, body=error)
    result = await node().execute({})
    assert result["status"] == "error" and result["success"] is False
    assert CREDENTIAL["api_key"] not in result["error"]


@pytest.mark.asyncio
async def test_unavailable_link_metadata_is_preserved(monkeypatch):
    body = {**EXAMPLE, "ok": False, "status": 404}
    body.pop("title", None)
    body.pop("description", None)
    transport(monkeypatch, body=body)
    assert (await node().execute({}))["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], "unexpected", {}, {"ok": "true"}])
async def test_malformed_json_shape_is_not_success(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError, match="unexpected preview response"):
        await node().execute({})


@pytest.mark.asyncio
async def test_html_and_transport_failures_are_not_success(monkeypatch):
    transport(monkeypatch, raw=b"<html>Sign in</html>")
    with pytest.raises(ValueError):
        await node().execute({})
    def failed(**kwargs):
        def timeout(request):
            raise httpx.ReadTimeout("Timed out", request=request)
        return httpx.AsyncClient(transport=httpx.MockTransport(timeout), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", failed)
    with pytest.raises(httpx.ReadTimeout):
        await node().execute({})


@pytest.mark.parametrize("config", [
    {"link": "not a URL"}, {"link": "file:///tmp/test"},
    {"link": "https://user:password@example.com"}, {"link": "https://example.com/\n"},
    {"accept_language": "en\r\nAuthorization: bad"}, {"source": "OTHER"},
    {"forceNewSnapshot": True}, {"forceNewSnapshotRecursive": "yes"},
])
def test_invalid_config_is_rejected(config):
    with pytest.raises(ValueError):
        node(**config)


@pytest.mark.parametrize("key", ["", "Bearer token", "https://example.com", "key\r\nheader", "<token>"])
def test_invalid_credential_is_rejected(key):
    with pytest.raises(ValueError):
        native.PeekalinkAPIKeyCredential(api_key=key)


def test_native_registration_manual_connect_and_evidence():
    assert NODE_REGISTRY["automation-peekalink"] is native.PeekalinkNode
    credential = native.PeekalinkAPIKeyCredential(api_key="  synthetic-peekalink-key  ")
    assert credential.credential_type == "peekalink_api_key"
    assert credential.api_key == "synthetic-peekalink-key"
    assert set(native.PeekalinkAPIKeyCredential.model_json_schema()["required"]) == {"api_key"}
    evidence = native.PeekalinkNode.connection_evidence
    assert evidence.operation == "get_link_preview" and evidence.proves == "reachability"
    assert native.PeekalinkGetLinkPreviewConfig(**evidence.operation_arguments).link == LINK
