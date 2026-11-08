"""One-request operation mappings and failures at the real HTTP client seam."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import e2b_node as e2b

AUTH = {"credential_type": "e2b_api_key", "api_key": "e2b_fixture_key_never_live"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/e2b/contract.json").read_text())
CONFIGS = {
    "create_sandbox": {"template_id": "base", "env_vars": {"HELLO": "world"}},
    "create_webhook": {"name": "Sandbox events", "url": "https://example.com/events", "events": ["sandbox.lifecycle.created"], "signature_secret": "fixture_signing_secret"},
    "update_webhook": {"enabled": False},
    "update_template": {"public": False},
    "set_sandbox_timeout": {"timeout": 600},
}


def config(operation):
    data = {"operation": operation, **CONFIGS.get(operation, {})}
    path = FIXTURE["operations"][operation]["path"]
    for key, wire in [("sandbox_id", "sandboxID"), ("template_id", "templateID"), ("build_id", "buildID"), ("webhook_id", "webhookID")]:
        if "{" + wire + "}" in path:
            data[key] = "00000000-0000-4000-8000-000000000001" if key == "webhook_id" else "fixture-" + key
    return data


async def run(monkeypatch, data, reply):
    calls = []
    real = httpx.AsyncClient
    async def send(request):
        calls.append(request)
        return reply(request)
    monkeypatch.setattr(e2b.httpx, "AsyncClient", lambda **kw: real(**kw, transport=httpx.MockTransport(send)))
    node = e2b.E2BNode(node_id="fixture", node_type="automation-e2b", node_data={}, config=e2b.E2BNode.parse_config({"config": data, "credentials": AUTH}))
    node.emit = AsyncMock()
    output = await node.execute({})
    node.emit.assert_awaited_once_with(output)
    return output, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(FIXTURE["operations"]))
async def test_every_operation_method_route_auth_and_completed_response(monkeypatch, operation):
    case = FIXTURE["operations"][operation]
    code, shape = next(iter(case["responses"].items()))
    payload = [] if shape == "array" else {"templateID": "base"}
    def reply(request):
        if shape is None:
            return httpx.Response(int(code))
        return httpx.Response(int(code), json=payload, headers={"X-Next-Token": "next-page"})
    output, calls = await run(monkeypatch, config(operation), reply)
    assert output["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    path = case["path"]
    for key, value in config(operation).items():
        wire = {"sandbox_id": "sandboxID", "template_id": "templateID", "build_id": "buildID", "webhook_id": "webhookID"}.get(key, key)
        path = path.replace("{" + wire + "}", str(value))
    assert str(request.url).split("?")[0] == e2b.API_ROOT + path
    assert request.headers["X-API-Key"] == AUTH["api_key"]
    assert AUTH["api_key"] not in str(request.url)
    if shape:
        assert output["data"] == payload and output["next_page_token"] == "next-page"
    if operation == "create_sandbox":
        body = json.loads(request.content)
        assert body["templateID"] == "base" and body["envVars"] == {"HELLO": "world"}
        assert "template_id" not in body
    if operation == "update_template":
        assert json.loads(request.content) == {"public": False}
    if operation == "set_sandbox_timeout":
        assert json.loads(request.content) == {"timeout": 600}
    if operation == "update_webhook":
        assert json.loads(request.content) == {"enabled": False}


@pytest.mark.asyncio
async def test_query_arrays_booleans_cursors_and_no_false_completeness(monkeypatch):
    output, calls = await run(monkeypatch, {"operation": "list_sandboxes", "state": ["running", "paused"], "next_token": "opaque+/=", "limit": 2}, lambda r: httpx.Response(200, json=[], headers={"X-Next-Token": "more"}))
    assert calls[0].url.params["state"] == "running,paused"
    assert calls[0].url.params["nextToken"] == "opaque+/="
    assert output["has_more"] is True


@pytest.mark.asyncio
async def test_event_filter_explode_and_boolean_false(monkeypatch):
    output, calls = await run(monkeypatch, {"operation": "list_team_events", "types": ["created", "paused"], "order_asc": False}, lambda r: httpx.Response(200, json=[]))
    assert calls[0].url.params.get_list("types") == ["created", "paused"]
    assert calls[0].url.params["orderAsc"] == "false"
    assert output["has_more"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 429, 500, 503])
async def test_provider_failures_no_redirects_and_secret_redaction(monkeypatch, code):
    output, calls = await run(monkeypatch, {"operation": "list_templates"}, lambda r: httpx.Response(code, json={"message": "Rejected " + AUTH["api_key"]}, headers={"Location": "https://elsewhere.example"}))
    assert len(calls) == 1 and output["status"] == "error" and output["http_status"] == code
    assert AUTH["api_key"] not in str(output)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"error": "bad"}, [], None])
async def test_malformed_or_error_response_not_success(monkeypatch, payload):
    output, _ = await run(monkeypatch, config("get_sandbox"), lambda r: httpx.Response(200, json=payload))
    assert output["status"] == "error"


def test_manual_credential_default_and_schema_secrets():
    cred = e2b.E2BAPIKeyCredential(api_key=AUTH["api_key"])
    assert cred.credential_type == "e2b_api_key"
    assert e2b.E2BAPIKeyCredential.model_json_schema()["properties"]["api_key"]["ui:widget"] == "password"
    for operation, arguments in [("set_sandbox_timeout", {"sandbox_id": "abc", "timeout": -1}), ("list_sandboxes", {"limit": 101}), ("get_webhook", {"webhook_id": "not-uuid"})]:
        with pytest.raises(ValidationError):
            e2b.E2BNode.parse_config({"config": {"operation": operation, **arguments}, "credentials": AUTH})
