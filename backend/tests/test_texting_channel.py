"""The engine's rule for a text to the assistant's number (coder/coordinator/texting/channel.py), against real Postgres:
a link code drafted on the web binds the number, a bound number's text is a coordinator turn in that account's
conversation answered on the app it came on, and anyone else gets one short notice a day and never an account. Also
how the assistant reaches its owner's phone without a platform's sender."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from agents.models.interface import Model
from openai.types.responses import Response, ResponseCompletedEvent, ResponseOutputMessage, ResponseOutputText

from coder.coordinator import agent as coordinator
from coder.coordinator.texting import channel, imessage, owner_message, whatsapp
from coder.coordinator.texting.whatsapp import InboundMessage
from coder.openai_agent import Agent
from repositories.phones import PhoneRepo
from utils import capabilities
from utils.phone_identity import LinkCodes, PhoneIdentity

pytestmark = pytest.mark.asyncio

USER = "00000000-0000-0000-0000-000000000001"  # seeded with test@example.com
OWNER_PHONE = "+14155550161"
STRANGER = "+14155550162"


class FakeRedis:
    """The commands texting uses, with Redis's own semantics for them (NX, expiry, GETDEL)."""

    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None, px=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value.encode() if isinstance(value, str) else value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def getdel(self, key):
        return self.data.pop(key, None)

    async def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)

    async def exists(self, key):
        return int(key in self.data)

    async def pttl(self, key):
        return 600_000 if key in self.data else -2


class ScriptedModel(Model):
    """Answers every turn with one line, recording what it was given."""

    def __init__(self, seen):
        self.seen = seen

    async def get_response(self, *a, **kw):
        raise AssertionError("Expected streaming")

    async def stream_response(self, system_instructions, input, *a, **kw):
        self.seen.append((system_instructions, input))
        output = [ResponseOutputMessage(id="m1", type="message", role="assistant", status="completed",
                                        content=[ResponseOutputText(type="output_text", text="You have **no** workflows yet.",
                                                                    annotations=[])])]
        yield ResponseCompletedEvent(type="response.completed", sequence_number=0, response=Response.model_construct(
            id="r1", created_at=0, model="test", object="response", output=output, status="completed", usage=None))


@pytest.fixture
async def texting(postgres_db, postgres_container, monkeypatch):
    """The engine's own rule (no platform's), a real pool, Redis, and a WhatsApp line whose sends are recorded."""
    from billing.usage_tracker import registered_usage_tracker
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=5, init=setup_asyncpg_codecs,
    )
    for name in (capabilities.PHONE_TEXT, capabilities.OWNER_MESSAGE, capabilities.COORDINATOR_PLATFORM_TOOLS):
        monkeypatch.delitem(capabilities._providers, name, raising=False)
    monkeypatch.setattr(type(registered_usage_tracker()), "spend_cap_refusal", AsyncMock(return_value=None))
    redis = FakeRedis()
    for target in ("utils.redis_client.get_shared_redis", "utils.phone_identity.get_shared_redis"):
        monkeypatch.setattr(target, lambda: redis)
    monkeypatch.setattr(channel, "get_shared_redis", lambda: redis)
    for target in ("utils.database_pool.get_native_pool", "utils.phone_identity.get_native_pool"):
        monkeypatch.setattr(target, lambda: pool)
    monkeypatch.setattr(channel, "get_native_pool", lambda: pool)
    monkeypatch.setattr(coordinator, "get_native_pool", lambda: pool)
    monkeypatch.setattr(channel, "get_sio", lambda: None)
    monkeypatch.setattr(channel, "missing_brain_key", lambda model: None)
    monkeypatch.setattr(channel, "plan_allows_turn", AsyncMock(return_value=(True, None)))
    seen = []
    original = Agent.create

    async def create(**kw):
        agent = await original(**kw)
        agent._sdk_agent.model = ScriptedModel(seen)
        agent._billing_hooks = None
        return agent

    monkeypatch.setattr(Agent, "create", create)
    api = MagicMock(send_text=AsyncMock(return_value="wamid.out"), mark_read=AsyncMock())
    try:
        yield pool, api, seen, redis
    finally:
        await pool.execute("DELETE FROM user_phones WHERE phone_e164 = ANY($1::text[])", [OWNER_PHONE, STRANGER])
        await pool.execute("DELETE FROM conversations WHERE conversation_id = $1", f"coordinator:{USER}")
        await pool.close()


def _text(body, wamid, sender=OWNER_PHONE):
    return InboundMessage(wamid=wamid, sender=sender, sender_name="Ada", kind="text", text=body)


async def _replies(api):
    await asyncio.sleep(0)
    return [call.args[1] for call in api.send_text.await_args_list]


async def test_a_stranger_gets_one_notice_a_day_and_never_an_account(texting):
    pool, api, seen, _ = texting
    accounts = await pool.fetchval("SELECT count(*) FROM auth.users")
    await whatsapp.handle_inbound(_text("hi, who is this?", "wamid.s1", sender=STRANGER), api)
    await whatsapp.handle_inbound(_text("hello??", "wamid.s2", sender=STRANGER), api)
    assert await _replies(api) == [channel.UNBOUND_NOTICE]
    assert await pool.fetchval("SELECT count(*) FROM auth.users") == accounts
    assert await PhoneRepo(pool).get_user_by_phone(STRANGER) is None
    assert seen == []  # no turn ran


async def test_the_drafted_link_code_binds_the_number_and_its_texts_reach_the_coordinator(texting):
    pool, api, seen, redis = texting
    code = (await PhoneIdentity(PhoneRepo(pool), None, codes=LinkCodes(redis)).channel_link_code(USER))["code"]
    await whatsapp.handle_inbound(_text(f"Link my NoClick account: {code}", "wamid.l1"), api)
    [linked] = await _replies(api)
    assert linked.startswith("Linked.") and "(t•••@example.com)" in linked
    binding = await PhoneRepo(pool).get_user_by_phone(OWNER_PHONE)
    assert str(binding["user_id"]) == USER and binding["source"] == "whatsapp"
    assert seen == []  # the draft is not a request

    await whatsapp.handle_inbound(_text("What do I have?", "wamid.l2"), api)
    # The coordinator answered in WhatsApp's own markup, told it's a WhatsApp text.
    assert (await _replies(api))[1] == "You have *no* workflows yet."
    instructions, _ = seen[0]
    assert whatsapp.PROMPTS.TEXT_STYLE in instructions
    events = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id = $1", f"coordinator:{USER}")
    asked = next(e for e in events if e.get("role") == "user")
    assert asked["message"] == "What do I have?" and asked["channel"] == "whatsapp_text" and asked["wamid"] == "wamid.l2"
    assert await PhoneRepo(pool).last_seen_app(USER) == "whatsapp"
    # A redelivery is answered once.
    await whatsapp.handle_inbound(_text("What do I have?", "wamid.l2"), api)
    assert len(seen) == 1 and len(await _replies(api)) == 2


async def test_without_redis_only_a_link_code_is_answered_saying_what_is_missing(texting, monkeypatch):
    pool, api, seen, _ = texting
    monkeypatch.setattr(channel, "get_shared_redis", lambda: None)
    monkeypatch.setattr("utils.phone_identity.get_shared_redis", lambda: None)
    await whatsapp.handle_inbound(_text("Link my NoClick account: NC-7K4Q-9PXA", "wamid.r1"), api)
    [refused] = await _replies(api)
    assert "REDIS_URL" in refused
    await whatsapp.handle_inbound(_text("hello", "wamid.r2", sender=STRANGER), api)
    assert len(await _replies(api)) == 1 and seen == []


async def _bound(pool):
    async with PhoneRepo(pool).claiming(OWNER_PHONE) as conn:
        await PhoneRepo(pool).bind_channel(conn, user_id=USER, phone_e164=OWNER_PHONE, source="verify")


async def test_a_bound_number_with_no_model_key_is_told_where_to_add_it(texting, monkeypatch):
    pool, api, seen, _ = texting
    await _bound(pool)
    monkeypatch.setattr(channel, "missing_brain_key", lambda model: ("OPENROUTER_API_KEY", "openrouter"))
    await whatsapp.handle_inbound(_text("hi", "wamid.k1"), api)
    assert await _replies(api) == [channel.NO_MODEL_KEY_REPLY.format(env_var="OPENROUTER_API_KEY")]
    assert seen == []


async def test_a_file_that_cannot_be_read_reaches_the_turn_as_the_packs_note(texting):
    pool, api, seen, _ = texting
    await _bound(pool)
    from utils.whatsapp_cloud_api import WhatsAppSendError

    api.get_media = AsyncMock(side_effect=WhatsAppSendError("expired"))
    await whatsapp.handle_inbound(InboundMessage(wamid="wamid.f1", sender=OWNER_PHONE, sender_name="Ada",
                                                 kind="document", media_id="gone", text="the menu"), api)
    _, given = seen[0]
    assert given[-1]["content"] == f"the menu\n\n{whatsapp.PROMPTS.unreadable_attachment('document')}"
    assert "expired" not in str(given)


async def test_a_platforms_rule_takes_every_text(texting, monkeypatch):
    _, api, seen, _ = texting
    rule = AsyncMock()
    monkeypatch.setitem(capabilities._providers, capabilities.PHONE_TEXT, rule)
    await whatsapp.handle_inbound(_text("hi", "wamid.p1", sender=STRANGER), api)
    transport, message = rule.await_args.args
    assert (transport.source, message.text, message.raw) == ("whatsapp", "hi", {})
    assert await _replies(api) == [] and seen == []


async def test_an_imessage_text_from_a_bound_number_is_answered_in_plain_text(texting):
    pool, _, seen, _ = texting
    await _bound(pool)
    line = MagicMock(send=AsyncMock(return_value="h1"), share_profile=AsyncMock(), mark_read=AsyncMock(),
                     typing=AsyncMock())
    await imessage.handle_inbound(imessage.InboundMessage(handle="msg-1", sender=OWNER_PHONE, text="What do I have?"), line)
    line.send.assert_awaited_once_with(OWNER_PHONE, content="You have no workflows yet.")
    assert imessage.PROMPTS.IMESSAGE_STYLE in seen[0][0]
    assert await PhoneRepo(pool).last_seen_app(USER) == "imessage"


# ── reaching the owner's phone without a platform's sender ───────────────────

async def test_the_instances_own_lines_decide_what_can_text_the_owner(monkeypatch):
    for name in ("WHATSAPP_DISPLAY_NUMBER", "SENDBLUE_NUMBER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delitem(capabilities._providers, capabilities.OWNER_MESSAGE, raising=False)
    assert owner_message.phone_sender() is None and owner_message.phone_sender("imessage") is None
    monkeypatch.setenv("SENDBLUE_NUMBER", "+14155550123")
    assert owner_message.phone_sender("imessage") is owner_message.send_owner_message
    assert owner_message.phone_sender() is owner_message.send_owner_message
    assert owner_message.phone_sender("whatsapp") is None
    registered = AsyncMock()
    monkeypatch.setitem(capabilities._providers, capabilities.OWNER_MESSAGE, registered)
    assert owner_message.phone_sender("whatsapp") is registered


async def test_the_owner_is_texted_on_the_app_they_last_used_else_the_line_there_is(monkeypatch):
    sent = []
    monkeypatch.setattr("coder.coordinator.texting.imessage.send_owner_imessage",
                        AsyncMock(side_effect=lambda *a, **k: sent.append("imessage") or {"success": True}))
    monkeypatch.setattr("coder.coordinator.texting.whatsapp.send_owner_whatsapp",
                        AsyncMock(side_effect=lambda *a, **k: sent.append("whatsapp") or {"success": True}))
    last = AsyncMock(return_value="whatsapp")
    monkeypatch.setattr(owner_message, "last_phone_app", last)
    monkeypatch.delenv("WHATSAPP_DISPLAY_NUMBER", raising=False)
    monkeypatch.setenv("SENDBLUE_NUMBER", "+14155550123")
    await owner_message.send_owner_message("pool", USER, "done")
    last.return_value = None  # never texted: the instance's one line
    await owner_message.send_owner_message("pool", USER, "done")
    await owner_message.send_owner_message("pool", USER, "done", channel="whatsapp")  # a named app wins
    assert sent == ["whatsapp", "imessage", "whatsapp"]


async def test_message_owner_offers_each_app_the_instance_has_a_line_for(monkeypatch):
    from coder.coordinator.tools import CoordinatorTools

    for name in (capabilities.OWNER_MESSAGE, capabilities.COORDINATOR_PLATFORM_TOOLS):
        monkeypatch.delitem(capabilities._providers, name, raising=False)
    monkeypatch.delenv("WHATSAPP_DISPLAY_NUMBER", raising=False)
    monkeypatch.setenv("SENDBLUE_NUMBER", "+14155550123")
    tools = CoordinatorTools(pool=MagicMock(), sio=None, user_id=USER, organization_id=None,
                             conversation_id=f"coordinator:{USER}", email="test@example.com")

    def reach():
        tool = next(p for p in tools.tool_params() if p["function"]["name"] == "message_owner")
        return tool["function"]["parameters"]["properties"]["channel"]["enum"]

    assert reach() == ["auto", "email", "web", "imessage"]
    monkeypatch.setenv("WHATSAPP_DISPLAY_NUMBER", "+15550100000")
    assert reach() == ["auto", "email", "web", "whatsapp", "imessage"]
    monkeypatch.delenv("SENDBLUE_NUMBER")
    monkeypatch.delenv("WHATSAPP_DISPLAY_NUMBER")
    assert reach() == ["auto", "email", "web"] and not tools.can_text
