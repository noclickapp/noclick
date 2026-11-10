"""ezeep wire behavior and lifecycle checks; no live account or writes."""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.core.registry import NodeFactory
from nodes.ezeep_printing_node import EzeepPrintingNode, EzeepPrintingOAuthCredential
from nodes.oauth.ezeep_printing_oauth import OAUTH_PROVIDER

IDENTIFIER = "62b3dcb2-8a96-45d6-8863-7817ae4aa9a3"
ENDPOINT = "af47f7ec-0299-4267-b61b-736e887d6531"
CREDENTIAL = {"credential_type": "ezeep_printing_oauth", "access_token": "recorded-test-access-918273", "refresh_token": "recorded-test-refresh-918273", "expires_at": "2099-01-01T00:00:00Z"}
FIXTURE = Path(__file__).parent / "fixtures/ezeep-printing/printjob_succeeded.json"


@pytest.fixture(autouse=True)
async def ensure_native_db_pool():
    # This node has no database work. Override the shared Docker pool fixture.
    yield


@pytest.fixture
def wire(monkeypatch):
    original = httpx.AsyncClient
    calls, replies = [], []
    def respond(request):
        calls.append(request)
        return replies.pop(0) if replies else httpx.Response(200, json={"count": 0, "results": []})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    return calls, replies


def node(config):
    return NodeFactory.create_node(node_id="ezeep-test", node_type="automation-ezeep-printing",
        node_data={"config": config, "credentials": dict(CREDENTIAL)})


@pytest.mark.asyncio
async def test_factory_account_probe_and_page_filters(wire):
    calls, replies = wire
    replies.append(httpx.Response(200, json={"count": 1, "next": "https://api2.ezeep.com/printing/v1/printers/?offset=1", "results": [{"id": IDENTIFIER, "name": "Office"}]}))
    result = await node({"operation": "list_printers", "limit": 1, "offset": 0, "location": "Office + café", "status": "ON"}).execute({})
    assert result["data"]["results"][0]["name"] == "Office"
    assert result["data"]["next"].endswith("offset=1")
    assert calls[0].url.host == "api2.ezeep.com" and calls[0].url.path == "/printing/v1/printers/"
    assert dict(calls[0].url.params) == {"limit": "1", "offset": "0", "location": "Office + café", "status": "ON"}
    assert calls[0].headers["authorization"] == "Bearer " + CREDENTIAL["access_token"]
    assert CREDENTIAL["access_token"] not in str(result)
    assert EzeepPrintingNode.connection_evidence.operation == "list_printers"


@pytest.mark.asyncio
async def test_patch_is_sparse_and_keeps_false(wire):
    calls, _ = wire
    await node({"operation": "update_group", "id": IDENTIFIER, "description": "Updated office", "myprinters_enabled": False}).execute({})
    assert calls[0].method == "PATCH" and calls[0].url.path == f"/printing/v1/groups/{IDENTIFIER}/"
    assert json.loads(calls[0].content) == {"description": "Updated office", "myprinters_enabled": False}


@pytest.mark.asyncio
async def test_create_profile_uses_documented_enum_and_uuid_array(wire):
    calls, _ = wire
    await node({"operation": "create_printer_profile", "name": "Office", "color": "MONOCHROME", "duplex": "DUPLEX_VERTICAL", "selected_printers": [IDENTIFIER]}).execute({})
    assert calls[0].method == "POST" and calls[0].url.path == "/printing/v1/printer_profiles/"
    assert json.loads(calls[0].content) == {"name": "Office", "color": "MONOCHROME", "duplex": "DUPLEX_VERTICAL", "selected_printers": [IDENTIFIER]}


@pytest.mark.asyncio
async def test_delete_ack_and_provider_error_are_not_success(wire):
    calls, replies = wire
    replies.append(httpx.Response(204))
    assert (await node({"operation": "delete_print_job", "id": IDENTIFIER}).execute({}))["data"] == {}
    assert calls[0].method == "DELETE"
    replies.append(httpx.Response(401, json={"detail": "Invalid token"}))
    with pytest.raises(ValueError, match="401.*Invalid token"):
        await node({"operation": "get_current_user"}).execute({})
    replies.append(httpx.Response(302, headers={"location": "https://other.example"}))
    with pytest.raises(ValueError, match="302"):
        await node({"operation": "get_current_user"}).execute({})
    assert len(calls) == 3


@pytest.mark.parametrize("config", [
    {"operation": "update_group", "id": IDENTIFIER},
    {"operation": "get_printer", "id": "../../users/me"},
    {"operation": "list_printers", "status": "ONLINE"},
    {"operation": "create_printer_profile", "name": "Office", "color": "blue"},
])
def test_invalid_inputs_are_rejected(config):
    with pytest.raises(ValueError):
        EzeepPrintingNode.parse_config({"config": config, "credentials": CREDENTIAL})


def test_manual_credential_default_and_oauth_declaration():
    assert EzeepPrintingOAuthCredential(access_token=CREDENTIAL["access_token"], refresh_token=CREDENTIAL["refresh_token"]).credential_type == "ezeep_printing_oauth"
    assert set(OAUTH_PROVIDER.scope_registry.declared_scopes()) == {"printing", "webhooks"}
    assert OAUTH_PROVIDER.identity_url == "https://api2.ezeep.com/printing/v1/users/me/"
    assert OAUTH_PROVIDER.rotates_refresh_tokens and OAUTH_PROVIDER.token_auth == "basic"


@pytest.mark.asyncio
async def test_webhook_basic_auth_registration_delivery_and_unregistration(wire):
    calls, replies = wire
    replies.append(httpx.Response(201, json=json.loads(FIXTURE.with_name("webhook_registration.json").read_text())))
    state = await EzeepPrintingNode._register_external_webhook(webhook_url="https://test.hooks.example.test/hooks/job", credential=CREDENTIAL, config={}, node_id="job")
    body = json.loads(calls[0].content)
    assert calls[0].url.path == "/webhooks/endpoints"
    assert body["topics"] == ["printjob_succeeded"]
    assert body["authentication_scheme"] == "basic" and body["basic_username"] == "noclick"
    assert body["basic_password"] == state["signing_secret"] and len(state["signing_secret"]) >= 32
    payload = json.loads(FIXTURE.read_text())
    raw = json.dumps(payload).encode()
    auth = "Basic " + base64.b64encode(("noclick:" + state["signing_secret"]).encode()).decode()
    assert EzeepPrintingNode.verify_webhook_signature(raw, {"Authorization": auth}, state)
    assert EzeepPrintingNode.verify_webhook_signature(raw, {"authorization": auth.replace("Basic", "basic")}, state)
    assert not EzeepPrintingNode.verify_webhook_signature(raw, {}, state)
    assert not EzeepPrintingNode.verify_webhook_signature(raw, {"authorization": auth + "x"}, state)
    assert not EzeepPrintingNode.verify_webhook_signature(raw, {"authorization": auth}, {})
    assert not EzeepPrintingNode.verify_webhook_signature(raw, {"authorization": "Basic !!!"}, state)
    event = EzeepPrintingNode.resolve_agent_event(EzeepPrintingNode.resolve_trigger_payload(payload, {}))
    assert "Webhook test user" in event["text"] and "Webhook test printer" in event["text"]
    assert payload["content"]["printjob"]["printjob_id"] in event["text"]
    assert event["conversation_key"] == payload["content"]["printjob"]["printjob_id"]
    assert EzeepPrintingNode.filter_trigger_payload(payload, {})
    assert not EzeepPrintingNode.filter_trigger_payload({"topic": "printjob_failed"}, {})
    replies.append(httpx.Response(204))
    await EzeepPrintingNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id="job")
    assert calls[-1].method == "DELETE" and calls[-1].url.path == "/webhooks/endpoints/" + ENDPOINT


@pytest.mark.asyncio
async def test_refresh_uses_shared_choke_point(monkeypatch):
    import nodes.core.oauth_refresh as refresh
    freshen = AsyncMock(return_value=CREDENTIAL)
    monkeypatch.setattr(refresh, "freshen_oauth_credential", freshen)
    await EzeepPrintingNode.freshen_credential(CREDENTIAL, user_id="user", credential_id="cred")
    assert freshen.call_args.kwargs["provider"] == "ezeep-printing"
    assert freshen.call_args.kwargs["refresh"] == OAUTH_PROVIDER.refresh
