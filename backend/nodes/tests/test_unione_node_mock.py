"""Offline UniOne wire, credential, pagination and failure regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import unione_node as native
from nodes.core.registry import NodeFactory, NODE_REGISTRY

KEY = "unione-offline-key-9384756"
CASES = json.loads((Path(__file__).parent / "fixtures/unione/requests.json").read_text())


def node(config, credential=None):
    return NodeFactory.create_node(node_id="unione-offline", node_type="automation-unione",
        node_data={"config": config, "credentials": credential or {"credential_type": "unione_api_key", "api_key": KEY}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_factory_operation_makes_one_documented_post(monkeypatch, case):
    requests = transport(monkeypatch, {"status": "success"})
    result = await node(case["config"]).execute({})
    assert result == {"status": "success"}
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "POST"
    assert str(req.url) == native.BASE_URL + case["path"]
    assert req.headers["X-API-KEY"] == KEY
    assert req.headers["Content-Type"] == "application/json"
    assert req.headers["Accept"] == "application/json"
    assert json.loads(req.content) == case["body"]
    assert KEY not in req.content.decode()


@pytest.mark.asyncio
async def test_send_preserves_partial_acceptance_without_claiming_delivery(monkeypatch):
    reply = {"status":"success", "job_id":"1ZymBc-00041N-9X", "emails":[],
             "failed_emails":{"email@example.com":"unsubscribed"}}
    transport(monkeypatch, reply)
    assert await node(CASES[0]["config"]).execute({}) == reply


@pytest.mark.asyncio
async def test_template_update_nests_id_and_omits_absent_content(monkeypatch):
    reqs = transport(monkeypatch, {"status":"success"})
    await node({"operation":"set_template", "id":"00000000-0000-0000-0000-000000000000",
                "name":"Updated", "from_email":"email@example.com"}).execute({})
    assert json.loads(reqs[0].content) == {"template":{"id":"00000000-0000-0000-0000-000000000000", "name":"Updated", "from_email":"email@example.com"}}


@pytest.mark.asyncio
async def test_suppression_cursor_is_preserved_with_single_page(monkeypatch):
    reply = {"status":"success", "suppressions":[], "cursor":"provider-next-cursor"}
    requests = transport(monkeypatch, reply)
    assert await node({"operation":"list_suppressions", "cursor":"previous-cursor"}).execute({}) == reply
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {"cursor":"previous-cursor", "limit":50}


@pytest.mark.asyncio
async def test_account_identity_and_secret_redaction(monkeypatch):
    transport(monkeypatch, {"status":"success", "user_id":12345, "email":"email@example.com",
        "project_api_key":KEY, "nested":{"api_key":KEY, "message":"echo " + KEY}})
    result = await node({"operation":"get_account_info"}).execute({})
    assert result["email"] == "email@example.com" and result["user_id"] == 12345
    assert KEY not in str(result) and "project_api_key" not in result
    assert native.UnioneNode.connection_evidence.identity_operation == "get_account_info"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 401, 403, 404, 429, 500, 302])
async def test_error_envelopes_and_redirects_are_never_success(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status,
        json={"status":"error", "message":"API key is wrong", "code":1000},
        headers={"Location":"https://example.net/"}))
    result = await node({"operation":"get_account_info"}).execute({})
    assert result["status"] == "error" and result["message"] == "API key is wrong"
    assert result["http_status"] == status and result["code"] == 1000
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_ambiguous_write_timeout_never_retries(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)
    requests = transport(monkeypatch, timeout)
    result = await node(CASES[0]["config"]).execute({})
    assert result["status"] == "error" and result["outcome"] == "unknown"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [[], {"user_id":123}, {"status":"pending"}])
async def test_malformed_success_is_rejected(monkeypatch, reply):
    transport(monkeypatch, reply)
    try:
        result = await node({"operation":"ping"}).execute({})
    except ValueError:
        return
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_html_response_is_not_a_success(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, text="<html>Login</html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation":"get_account_info"}).execute({})


def test_manual_credential_and_catalog():
    assert NODE_REGISTRY["automation-unione"] is native.UnioneNode
    c = native.UnioneAPIKeyCredential.model_validate({"api_key":"  " + KEY + "  "})
    assert c.credential_type == "unione_api_key" and c.api_key == KEY
    assert set(native.ROUTES) == {c["operation"] for c in CASES}
    assert len(native.ROUTES) == 25 and len(set(native.ROUTES.values())) == 25
    for key in ["", "https://example.com/key", "<token>", "Bearer wrong key", "bad\r\nheader"]:
        with pytest.raises((ValueError, ValidationError)):
            native.UnioneAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("config", [
    {"operation":"delete_template", "id":"../other"},
    {"operation":"get_suppression", "email":"invalid"},
    {"operation":"list_domains", "limit":0},
    {"operation":"set_webhook", "url":"file:///etc/passwd"},
    {"operation":"set_webhook", "url":"https://example.com/", "max_parallel":101},
    {"operation":"get_account_info", "api_key":"overridden"},
])
def test_invalid_configs_fail_before_http(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.asyncio
async def test_export_dates_are_validated_before_http(monkeypatch):
    requests = transport(monkeypatch, {"status":"success"})
    for start, end in [("2026-02-30 00:00:00",None), ("2026-01-02 00:00:00","2026-01-01 00:00:00")]:
        with pytest.raises(ValueError):
            await node({"operation":"create_event_dump", "start_time":start, "end_time":end}).execute({})
    assert requests == []


DOCUMENTED = json.loads((Path(__file__).parent / "fixtures/unione/documented_responses.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [c for c in CASES if "POST " + c["path"] in DOCUMENTED], ids=lambda c: c["operation"])
async def test_provider_published_response_is_preserved(monkeypatch, case):
    published = DOCUMENTED["POST " + case["path"]]["body"]
    transport(monkeypatch, published)
    assert await node(case["config"]).execute({}) == published


@pytest.mark.asyncio
async def test_json_editor_text_and_tool_objects_produce_same_request(monkeypatch):
    requests = transport(monkeypatch, {"status":"success"})
    for events in [{"email_status":["delivered"]}, '{"email_status":["delivered"]}']:
        await node({"operation":"set_webhook", "url":"https://example.com/webhook", "events":events}).execute({})
    assert json.loads(requests[0].content) == json.loads(requests[1].content)
    send = {**CASES[0]["config"], "tags":'["receipt"]', "global_substitutions":'{"CustomerId":"12452"}'}
    await node(send).execute({})
    message = json.loads(requests[-1].content)["message"]
    assert message["tags"] == ["receipt"] and message["global_substitutions"] == {"CustomerId":"12452"}
    for bad in ["[bad", "1", '{"email_status":["invented"]}']:
        with pytest.raises((ValueError, ValidationError)):
            node({"operation":"set_webhook", "url":"https://example.com/webhook", "events":bad})
