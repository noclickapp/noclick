"""ESI wire, connect and polling tests against the provider's published schema.

The harness additionally validates every operation and full response schema.
"""
import json
from unittest.mock import Mock
import httpx
import pytest
import respx
from pydantic import ValidationError
from nodes.evetech_node import CONFIG_MODELS, EvetechNode, EvetechNodeConfig, EvetechOAuthCredential, EvetechOnNewMailConfig
from nodes.oauth.evetech_oauth import OAUTH_PROVIDER

CHARACTER = "2112625428"
BASE = "https://esi.evetech.net"


def node(operation, **values):
    config = EvetechOnNewMailConfig(**values) if operation == "on_new_mail" else CONFIG_MODELS[operation](**values)
    return EvetechNode(node_id="eve", node_type="automation-evetech", node_data={},
        config=EvetechNodeConfig(config=config, credentials=EvetechOAuthCredential(
            character_id=CHARACTER, access_token="test-access")),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,method,path,query,body", [
    ("list_market_orders", {"region_id":10000002,"type_id":34,"page":2}, "GET", "/markets/10000002/orders", {"order_type":"all","type_id":"34","page":"2"}, None),
    ("get_wallet", {}, "GET", f"/characters/{CHARACTER}/wallet", {}, None),
    ("get_mail", {"mail_id":7}, "GET", f"/characters/{CHARACTER}/mail/7", {}, None),
    ("list_mail", {"last_mail_id":7}, "GET", f"/characters/{CHARACTER}/mail", {"last_mail_id":"7"}, None),
    ("send_mail", {"subject":"Fleet","body":"Meet in Jita","recipients":[{"recipient_id":90000001,"recipient_type":"character"}]}, "POST", f"/characters/{CHARACTER}/mail", {}, {"subject":"Fleet","body":"Meet in Jita","approved_cost":0,"recipients":[{"recipient_id":90000001,"recipient_type":"character"}]}),
    ("update_mail", {"mail_id":7,"read":False,"labels":[]}, "PUT", f"/characters/{CHARACTER}/mail/7", {}, {"read":False,"labels":[]}),
    ("delete_mail", {"mail_id":7}, "DELETE", f"/characters/{CHARACTER}/mail/7", {}, None),
    ("respond_calendar", {"event_id":8,"response":"accepted"}, "PUT", f"/characters/{CHARACTER}/calendar/8", {}, {"response":"accepted"}),
    ("set_waypoint", {"destination_id":30000142}, "POST", "/ui/autopilot/waypoint", {"destination_id":"30000142","add_to_beginning":"false","clear_other_waypoints":"false"}, None),
])
async def test_wire(operation, values, method, path, query, body):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, BASE + path).mock(return_value=httpx.Response(204) if method in {"PUT","DELETE"} else httpx.Response(200,json=42))
        await node(operation, **values).execute({})
        request = route.calls[0].request
    assert dict(request.url.params) == query
    assert request.headers["X-Compatibility-Date"] == "2020-01-01"
    assert request.headers["Authorization"] == "Bearer test-access"
    assert json.loads(request.content) == body if body is not None else not request.content


def test_manual_connect_defaults_and_rejects_path_injection():
    credential = EvetechOAuthCredential(character_id=CHARACTER, access_token="token")
    assert credential.credential_type == "evetech_oauth"
    with pytest.raises(ValidationError):
        EvetechOAuthCredential(character_id="123/../../foo",access_token="token")
    with pytest.raises(ValidationError):
        CONFIG_MODELS["update_mail"](mail_id=7)
    with pytest.raises(ValidationError):
        CONFIG_MODELS["send_mail"](subject="s",body="b",recipients=[])


@pytest.mark.asyncio
async def test_provider_error_is_not_success_or_secret_leak():
    with respx.mock:
        respx.get(BASE + f"/characters/{CHARACTER}/wallet").mock(return_value=httpx.Response(403,json={"error":"denied test-access"}))
        with pytest.raises(ValueError, match="403: denied \\[redacted\\]"):
            await node("get_wallet").execute({})


@pytest.mark.asyncio
async def test_poll_baselines_deduplicates_and_describes_schema_fields():
    # Schema-shaped test data, not attributed as a provider example:
    # https://esi.evetech.net/meta/openapi.json#/components/schemas/CharactersCharacterIdMailGet
    mail = {"mail_id":7,"from":90000001,"subject":"Fleet", "timestamp":"2026-11-10T12:00:00Z","recipients":[{"recipient_id":int(CHARACTER),"recipient_type":"character"}],"is_read":False,"labels":[1]}
    instance = node("on_new_mail")
    state = {}
    async def update(mutator, skip_result):
        nonlocal state
        replacement, result = mutator(state)
        if replacement is not None:
            state = replacement
        return result
    instance._update_node_state = update
    with respx.mock:
        route = respx.get(BASE+f"/characters/{CHARACTER}/mail").mock(return_value=httpx.Response(200,json=[mail]))
        baseline = await instance.execute({})
        assert baseline["mails"] == []
        route.mock(return_value=httpx.Response(200,json=[{**mail,"mail_id":8},mail]))
        fresh = await instance.execute({})
        assert [m["mail_id"] for m in fresh["mails"]] == [8]
        assert instance.trigger_emitted_event(fresh)
        event = instance.resolve_agent_event(fresh)
        assert "Fleet" in event["text"] and "90000001" in event["text"] and "mail 8" in event["text"]
        assert (await instance.execute({}))["new_mail_count"] == 0
        assert instance.trigger_produced_no_event({})


@pytest.mark.asyncio
async def test_oauth_exchange_identity_and_rotating_refresh(monkeypatch):
    monkeypatch.setenv("EVETECH_CLIENT_ID","client")
    monkeypatch.setenv("EVETECH_CLIENT_SECRET","secret")
    context = {"character_id":CHARACTER}
    with respx.mock:
        route = respx.post("https://login.eveonline.com/v2/oauth/token").mock(side_effect=[
            httpx.Response(200,json={"access_token":"one","refresh_token":"r1","expires_in":1200,"scope":" ".join(OAUTH_PROVIDER.scope_registry.declared_scopes())}),
            httpx.Response(200,json={"access_token":"two","refresh_token":"r2","expires_in":1200}),
        ])
        respx.get("https://login.eveonline.com/v2/oauth/verify").mock(return_value=httpx.Response(200,json={"CharacterName":"Example Pilot","CharacterID":int(CHARACTER)}))
        tokens, name = await OAUTH_PROVIDER.exchange("code","https://noclick.com/api/auth/oauth/evetech/callback",context=context)
        refreshed = await OAUTH_PROVIDER.bind_refresh(context)(tokens.refresh_token)
    assert name == "Example Pilot"
    assert tokens.character_id == CHARACTER and refreshed.character_id == CHARACTER
    assert refreshed.refresh_token == "r2"
    assert route.calls[0].request.headers["Authorization"].startswith("Basic ")
    assert "grant_type=refresh_token" in route.calls[1].request.content.decode()
