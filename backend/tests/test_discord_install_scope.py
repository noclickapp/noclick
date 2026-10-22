"""A bot-install credential acts only in the server it was installed into. NoClick's one bot (the platform token)
is in every customer's server, so every id an operation or a picker names is judged against the install's server
before the request is sent: guild ids directly; a channel, thread, webhook or invite through Discord (remembered);
a DM by its recipients' membership. A customer's own bot token is theirs and is never restricted. Discord's HTTP
API is faked at the boundary (respx); operations run through the node-operation seam agents and the platform use,
and events through the receiver's fan-out."""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from nodes.core.run_op import run_node_operation
from nodes.discord_node import DISCORD_API_BASE, DiscordNode
from utils import app_webhooks

pytestmark = pytest.mark.asyncio

API = DISCORD_API_BASE
HOME, ELSEWHERE = "111", "999"
INSTALL = {"credential_type": "discord_bot_install", "guild_id": HOME, "guild_name": "Acme HQ",
           "access_token": "user-token", "refresh_token": "r", "expires_at": "2099-01-01T00:00:00Z"}
OWN_BOT = {"credential_type": "discord_bot_token", "bot_token": "their-own-bot"}


@pytest.fixture(autouse=True)
def platform_bot():
    DiscordNode._GUILD_OF.clear()
    DiscordNode._MEMBERS.clear()
    with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "platform-bot"}):
        yield


async def run(operation, credential=INSTALL, **arguments):
    return await run_node_operation(node_type="automation-discord", operation=operation, arguments=arguments,
                                    user_id=str(uuid.uuid4()), credential_data=credential)


def channel(channel_id, guild_id):
    return httpx.Response(200, json={"id": channel_id, "type": 0, "guild_id": guild_id})


def methods(router):
    return [call.request.method for call in router.calls]


async def test_a_message_to_another_servers_channel_is_refused_before_anything_is_sent():
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/channels/c-else").mock(return_value=channel("c-else", ELSEWHERE))
        post = router.post(f"{API}/channels/c-else/messages").mock(return_value=httpx.Response(200, json={"id": "m"}))
        with pytest.raises(ValueError, match="installed into"):
            await run("send_message_to_channel", channel_id="c-else", content="hi")
        assert methods(router) == ["GET"] and not post.called


async def test_its_own_servers_channel_works_and_is_looked_up_once():
    with respx.mock(assert_all_called=True) as router:
        lookup = router.get(f"{API}/channels/c-home").mock(return_value=channel("c-home", HOME))
        post = router.post(f"{API}/channels/c-home/messages").mock(
            return_value=httpx.Response(200, json={"id": "m1", "timestamp": "t"}))
        for _ in range(2):
            out = await run("send_message_to_channel", channel_id="c-home", content="hi")
            assert out["message_id"] == "m1"
        assert lookup.call_count == 1 and post.call_count == 2
        assert post.calls[0].request.headers["Authorization"] == "Bot platform-bot"


async def test_a_users_own_bot_token_is_not_restricted():
    with respx.mock(assert_all_called=True) as router:
        post = router.post(f"{API}/channels/c-else/messages").mock(
            return_value=httpx.Response(200, json={"id": "m2", "timestamp": "t"}))
        router.get(f"{API}/guilds/{ELSEWHERE}").mock(return_value=httpx.Response(200, json={"id": ELSEWHERE}))
        await run("send_message_to_channel", credential=OWN_BOT, channel_id="c-else", content="hi")
        await run("get_guild_info", credential=OWN_BOT, guild_id=ELSEWHERE)
        assert methods(router) == ["POST", "GET"]  # nothing looked up first
        assert post.calls[0].request.headers["Authorization"] == "Bot their-own-bot"


async def test_another_servers_guild_id_is_refused_without_a_request():
    with respx.mock(assert_all_called=False) as router:
        with pytest.raises(ValueError, match="installed into"):
            await run("kick_member_from_guild", guild_id=ELSEWHERE, user_id="u1")
        with pytest.raises(ValueError, match="installed into"):
            await run("get_guild_info", guild_id=ELSEWHERE)
        assert methods(router) == []


async def test_its_own_guild_works():
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{API}/guilds/{HOME}").mock(return_value=httpx.Response(200, json={"id": HOME, "name": "Acme"}))
        out = await run("get_guild_info", guild_id=HOME)
    assert out["guild"]["name"] == "Acme"


async def test_a_thread_webhook_or_invite_elsewhere_is_refused():
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/channels/t-else").mock(return_value=channel("t-else", ELSEWHERE))
        router.get(f"{API}/webhooks/w-else").mock(
            return_value=httpx.Response(200, json={"id": "w-else", "guild_id": ELSEWHERE, "channel_id": "c"}))
        router.get(f"{API}/invites/abc").mock(
            return_value=httpx.Response(200, json={"code": "abc", "guild": {"id": ELSEWHERE}}))
        for operation, arguments in (("add_member_to_thread", {"thread_id": "t-else", "user_id": "u1"}),
                                     ("delete_webhook", {"webhook_id": "w-else"}),
                                     ("delete_invite", {"invite_code": "abc"})):
            with pytest.raises(ValueError, match="installed into"):
                await run(operation, **arguments)
        assert methods(router) == ["GET", "GET", "GET"]


async def test_an_id_that_climbs_out_of_its_path_is_refused():
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/channels/c-home").mock(return_value=channel("c-home", HOME))
        for sneaky in (f"c-home/../../guilds/{ELSEWHERE}", f"c-home/%2e%2e/%2e%2e/guilds/{ELSEWHERE}"):
            with pytest.raises(ValueError, match="installed into"):
                await run("get_channel_info", channel_id=sneaky)
        assert not [call for call in router.calls if ELSEWHERE in str(call.request.url)]


async def test_noclicks_own_application_is_not_a_customers_to_change():
    with respx.mock(assert_all_called=False) as router:
        with pytest.raises(ValueError, match="installed into"):
            await run("create_global_application_command", application_id="noclick-app", name="hi", description="d")
        router.get(f"{API}/applications/noclick-app/guilds/{HOME}/commands").mock(
            return_value=httpx.Response(200, json=[]))
        await run("list_guild_application_commands", application_id="noclick-app", guild_id=HOME)
        assert methods(router) == ["GET"]


async def test_listing_the_bots_servers_names_only_its_own():
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{API}/users/@me/guilds").mock(return_value=httpx.Response(200, json=[
            {"id": HOME, "name": "Acme"}, {"id": ELSEWHERE, "name": "Someone else's"}]))
        out = await run("list_user_guilds")
    assert [guild["id"] for guild in out["guilds"]] == [HOME] and out["count"] == 1


async def test_a_dm_goes_only_to_a_member_of_its_server():
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/guilds/{HOME}/members/404").mock(
            return_value=httpx.Response(404, json={"message": "Unknown Member"}))
        router.get(f"{API}/guilds/{HOME}/members/200").mock(
            return_value=httpx.Response(200, json={"user": {"id": "200"}}))
        open_dm = router.post(f"{API}/users/@me/channels").mock(
            return_value=httpx.Response(200, json={"id": "dm1", "type": 1}))
        router.get(f"{API}/channels/dm-stranger").mock(return_value=httpx.Response(200, json={
            "id": "dm-stranger", "type": 1, "recipients": [{"id": "404"}]}))
        send = router.post(f"{API}/channels/dm-stranger/messages").mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(ValueError, match="installed into"):
            await run("create_direct_message_channel", recipient_id="404")
        assert not open_dm.called
        await run("create_direct_message_channel", recipient_id="200")
        assert open_dm.call_count == 1
        with pytest.raises(ValueError, match="installed into"):
            await run("send_message_to_channel", channel_id="dm-stranger", content="hi")
        assert not send.called


async def test_a_soundboard_sound_from_another_server_is_refused():
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/channels/c-home").mock(return_value=channel("c-home", HOME))
        play = router.post(f"{API}/channels/c-home/send-soundboard-sound").mock(return_value=httpx.Response(204))
        with pytest.raises(ValueError, match="installed into"):
            await run("play_soundboard_sound_in_voice_channel", channel_id="c-home", sound_id="s1",
                      source_guild_id=ELSEWHERE)
        assert not play.called


async def test_pickers_list_only_its_own_server():
    with respx.mock(assert_all_called=False) as router:
        roles = router.get(f"{API}/guilds/{HOME}/roles").mock(return_value=httpx.Response(200, json=[
            {"id": "r1", "name": "Mods"}]))
        with pytest.raises(ValueError, match="installed into"):
            await DiscordNode.load_field_options("channel_id", INSTALL, context={"guild_id": ELSEWHERE})
        with pytest.raises(ValueError, match="installed into"):
            await DiscordNode.load_field_options("user_id", INSTALL, context={"guild_id": ELSEWHERE})
        # With no server picked, the install's own is the one.
        out = await DiscordNode.load_field_options("role_id", INSTALL, context={})
        assert out["options"] == [{"value": "r1", "label": "Mods"}] and roles.call_count == 1
        assert [call.request.url.path for call in router.calls] == [f"/api/v10/guilds/{HOME}/roles"]


# ── what fires: events NoClick's shared application receives ─────────────────

def _pool(ctype, guild):
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"credential_type": ctype, "metadata": {"guild_id": guild}})
    return pool


def _app_event(event_type, data):
    return {"type": 1, "application_id": "noclick-app", "event": {"type": event_type, "data": data}}


async def test_noclicks_application_events_reach_only_the_server_they_happened_in():
    app_webhooks._credential_scope_cache.clear()
    sub = {"credential_id": str(uuid.uuid4()), "user_id": "u1"}
    pool = _pool("discord_bot_install", HOME)
    scope = app_webhooks._discord_scope_filter
    assert await scope(pool, sub, _app_event("APPLICATION_AUTHORIZED", {"guild": {"id": HOME}})) is None
    assert await scope(pool, sub, _app_event("APPLICATION_AUTHORIZED", {"guild": {"id": ELSEWHERE}}))
    assert await scope(pool, sub, _app_event("ENTITLEMENT_CREATE", {"guild_id": ELSEWHERE}))
    # Naming no server, it's no install's.
    assert await scope(pool, sub, _app_event("APPLICATION_DEAUTHORIZED", {"user": {"id": "u9"}}))


async def test_a_customers_own_application_hears_all_its_events():
    app_webhooks._credential_scope_cache.clear()
    sub = {"credential_id": str(uuid.uuid4()), "user_id": "u1"}
    pool = _pool("discord_bot_token", None)
    assert await app_webhooks._discord_scope_filter(
        pool, sub, _app_event("APPLICATION_DEAUTHORIZED", {"user": {"id": "u9"}})) is None


async def test_a_message_in_another_server_fires_none_of_this_servers_triggers():
    from tests.test_discord_gateway_bridge import _envelope
    from utils import webhook_routes

    rows = {("discord", HOME, "MESSAGE_CREATE"): [{"provider": "discord", "workflow_id": str(uuid.uuid4()),
                                                   "node_id": "n1", "user_id": "u1"}]}
    fired = []

    async def find(pool, provider, tenant, event_type):
        return rows.get((provider, tenant, event_type), [])

    async def fire(tasks, sub, payload, channel_id):
        fired.append(sub["node_id"])
        return True

    with patch("utils.webhook_routes.get_native_pool", return_value=MagicMock()), \
         patch("nodes.core.webhook_subscriptions.find_subscriptions", new=find), \
         patch("utils.app_event_dedup.was_delivered", new=AsyncMock(return_value=False)), \
         patch("utils.app_event_dedup.mark_delivered", new=AsyncMock()), \
         patch("utils.webhook_routes._fire_subscription", new=fire):
        elsewhere = json.dumps(_envelope(guild_id=ELSEWHERE, id="m-else")).encode()
        assert await webhook_routes.dispatch_app_events("discord", elsewhere) == 0
        home = json.dumps(_envelope(guild_id=HOME, id="m-home", mentions=[])).encode()
        assert await webhook_routes.dispatch_app_events("discord", home) == 1
    assert fired == ["n1"]
