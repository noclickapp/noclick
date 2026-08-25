"""The email_user channel (utils/agent_email.py + the inbound reply branch):
per-node unsubscribe scoping, reply-address lifecycle, the reply → agent-turn
fire, the outbound send's gates/charge/headers, and owner-presence steering.

Repo SQL runs against the LOCAL postgres (skipped when unreachable); the rest
is unit-tested with fakes.
"""
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

LOCAL_DSN = os.environ.get(
    "NC_TEST_POSTGRES_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


@pytest.fixture(autouse=True)
def relay_secret(monkeypatch):
    monkeypatch.setenv("EMAIL_RELAY_SECRET", "test-relay-secret")


@pytest.fixture
async def local_pool():
    import asyncpg

    from utils.database_pool import setup_asyncpg_codecs

    try:
        pool = await asyncpg.create_pool(
            LOCAL_DSN, min_size=1, max_size=2, timeout=5, init=setup_asyncpg_codecs,
        )
    except Exception:
        pytest.skip("local postgres unavailable")
    try:
        yield pool
    finally:
        await pool.close()


# ── unsubscribe signature + scope ────────────────────────────────────────────


class TestDisableSig:
    def test_roundtrip(self):
        from utils.agent_email import (
            mint_agent_updates_disable_sig,
            verify_agent_updates_disable_sig,
        )

        sig = mint_agent_updates_disable_sig("wf-1", "agent_1")
        assert verify_agent_updates_disable_sig("wf-1", "agent_1", sig)
        assert not verify_agent_updates_disable_sig("wf-1", "agent_2", sig)
        assert not verify_agent_updates_disable_sig("wf-2", "agent_1", sig)
        assert not verify_agent_updates_disable_sig("wf-1", "agent_1", "")

    def test_purpose_salted_against_send_email_disable_sig(self):
        # A send-email-node disable link for the SAME workflow/node must not
        # authorize flipping the agent's email flag (and vice versa).
        from utils.agent_email import verify_agent_updates_disable_sig
        from utils.email_unsubscribe import mint_disable_sig

        assert not verify_agent_updates_disable_sig(
            "wf-1", "agent_1", mint_disable_sig("wf-1", "agent_1")
        )

    def test_disable_url_targets_the_agent_route(self):
        from utils.agent_email import build_agent_updates_disable_url

        url = build_agent_updates_disable_url("wf-1", "agent_1")
        assert "/email/agent-updates/disable?" in url
        assert "wf=wf-1" in url and "node=agent_1" in url and "sig=" in url


@pytest.mark.asyncio
async def test_disable_flips_only_the_target_node(local_pool, monkeypatch):
    """The unsubscribe link's scope: enable_email_updates='false' on ONE node's
    saved config; sibling agents keep theirs."""
    from utils.agent_email import disable_agent_email_updates

    async with local_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM auth.users LIMIT 1")
    if not row:
        pytest.skip("no local users to satisfy the workflows FK")
    wf_id = str(uuid.uuid4())
    blob = {
        "nodes": [
            {"id": "agent_1", "type": "agent",
             "config": {"label": "Mailer", "enable_email_updates": "true"}},
            {"id": "agent_2", "type": "agent",
             "config": {"label": "Sibling", "enable_email_updates": "true"}},
        ],
        "edges": [],
    }
    await local_pool.execute(
        "INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1::uuid, $2, $3, $4)",
        wf_id, row["id"], "Email scope test", blob,
    )
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: local_pool)
    try:
        result = await disable_agent_email_updates(wf_id, "agent_1")
        assert result == {"workflow_name": "Email scope test", "node_label": "Mailer"}
        saved = await local_pool.fetchval(
            "SELECT workflow FROM workflows WHERE id = $1::uuid", wf_id
        )
        import json

        if isinstance(saved, str):
            saved = json.loads(saved)
        by_id = {n["id"]: n for n in saved["nodes"]}
        assert by_id["agent_1"]["config"]["enable_email_updates"] == "false"
        assert by_id["agent_2"]["config"]["enable_email_updates"] == "true"

        # Missing node / workflow → None (old link outlived its source).
        assert await disable_agent_email_updates(wf_id, "gone") is None
        assert await disable_agent_email_updates(str(uuid.uuid4()), "agent_1") is None
    finally:
        await local_pool.execute("DELETE FROM workflows WHERE id = $1::uuid", wf_id)


# ── reply-address lifecycle ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reply_address_mint_reuse_and_resolve(local_pool):
    from utils.agent_email import (
        AGENT_REPLY_PREFIX,
        mint_reply_address,
        resolve_reply_address,
    )

    async with local_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM auth.users LIMIT 1")
    if not row:
        pytest.skip("no local users to satisfy the FK")
    user_id = str(row["id"])
    wf_id = str(uuid.uuid4())
    try:
        addr = await mint_reply_address(
            local_pool, user_id=user_id, workflow_id=wf_id,
            node_id="agent_1", conversation_id="ck:wf:agent_1:tg:9",
        )
        assert addr.startswith(AGENT_REPLY_PREFIX) and "@" in addr
        # Same scope reuses the row — stable address keeps mail threads intact.
        again = await mint_reply_address(
            local_pool, user_id=user_id, workflow_id=wf_id,
            node_id="agent_1", conversation_id="ck:wf:agent_1:tg:9",
        )
        assert again == addr
        # A different conversation gets its own address.
        other = await mint_reply_address(
            local_pool, user_id=user_id, workflow_id=wf_id,
            node_id="agent_1", conversation_id=None,
        )
        assert other != addr

        ctx = await resolve_reply_address(local_pool, addr.split("@")[0])
        assert str(ctx["user_id"]) == user_id
        assert str(ctx["workflow_id"]) == wf_id
        assert ctx["node_id"] == "agent_1"
        assert ctx["conversation_id"] == "ck:wf:agent_1:tg:9"

        # Garbage local parts resolve to None, never raise.
        assert await resolve_reply_address(local_pool, f"{AGENT_REPLY_PREFIX}nope") is None
        assert await resolve_reply_address(
            local_pool, f"{AGENT_REPLY_PREFIX}{uuid.uuid4().hex}"
        ) is None
    finally:
        await local_pool.execute(
            "DELETE FROM agent_email_replies WHERE workflow_id = $1::uuid", wf_id
        )


# ── reply → agent turn ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reply_turn_carries_message_and_ck(monkeypatch):
    from utils.agent_email import fire_agent_email_reply_turn

    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: MagicMock())
    fired = {}

    class FakeExec:
        def __init__(self, sio):
            pass

        async def handle_execute(self, sid, request, caller_user_id=None):
            fired.update({"sid": sid, "caller": caller_user_id, "request": request})

    monkeypatch.setattr(
        "wss.handlers.workflow_execution_handler.WorkflowExecutionHandler", FakeExec
    )

    await fire_agent_email_reply_turn(
        MagicMock(), user_id="owner", workflow_id="wf-1", node_id="agent_1",
        conversation_id="ck:wf-1:agent_1:tg:99", sender="o@x.com",
        subject="Re: Need Slack", body="Use #alerts",
    )
    assert fired["sid"] == "" and fired["caller"] == "owner"
    req = fired["request"]
    assert req.trigger_source == "agent_email_reply"
    override = req.config_overrides["agent_1"]
    assert "Email reply from the user (o@x.com)" in override["message"]
    assert "Re: Need Slack" in override["message"]
    assert "Use #alerts" in override["message"]
    # Steers the answer back to email — the user is in their inbox, and a
    # chat-only reply is invisible to them (2026-07-19 live turn).
    assert "email_user tool" in override["message"]
    # ck parsing keeps colons inside the key intact.
    assert override["conversation_key"] == "tg:99"
    assert override["mockedOutput"] is None

    # Non-ck conversation ids fire without a key override (config's own key wins).
    await fire_agent_email_reply_turn(
        MagicMock(), user_id="owner", workflow_id="wf-1", node_id="agent_1",
        conversation_id=None, sender="o@x.com", subject="s", body="b",
    )
    assert "conversation_key" not in fired["request"].config_overrides["agent_1"]


# ── outbound send ────────────────────────────────────────────────────────────


def _send_pool(email="owner@x.com", name="My WF", label="Mailer", thread_row=None):
    pool = MagicMock()
    row = thread_row or {"id": uuid.uuid4(), "thread_subject": None, "last_message_id": None}
    steps = [
        {"name": name, "node_label": label},       # provenance lookup
    ]
    if thread_row:
        steps.append(row)                          # reply row exists
    else:
        steps += [None, row]                       # no row → insert returning
    pool.fetchrow = AsyncMock(side_effect=steps)
    pool.fetchval = AsyncMock(return_value=email)  # owner email (get_user_email)
    pool.execute = AsyncMock()                     # thread-state update
    return pool




@pytest.mark.asyncio
async def test_send_agent_email_threads_follow_ups(monkeypatch):
    """A conversation with prior mail is ONE thread: the send replies onto the
    last message (Re: thread subject + In-Reply-To/References) and skips the
    intro — re-introducing on every reply reads like a bot."""
    from billing.usage_tracker import usage_tracker
    from utils import agent_email

    monkeypatch.setattr(agent_email, "_execution_cap_hit", AsyncMock(return_value=False))
    monkeypatch.setattr(agent_email, "_daily_cap_hit", AsyncMock(return_value=False))
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", AsyncMock())
    monkeypatch.setattr(usage_tracker, "track_usage_event", AsyncMock())
    sent = {}

    async def fake_send(**kw):
        sent.update(kw)
        return {"message_id": "<m2@noclick.app>", "delivery_status": "delivered",
                "to": kw["to"], "from": kw["from_addr"]}

    monkeypatch.setattr("utils.email_sending.send_email", fake_send)

    pool = _send_pool(thread_row={
        "id": uuid.uuid4(),
        "thread_subject": "Need you to connect Slack",
        "last_message_id": "<user-reply@gmail.com>",
    })
    result = await agent_email.send_agent_email(
        pool,
        user_id=str(uuid.uuid4()), organization_id=None, workflow_id=str(uuid.uuid4()),
        node_id="agent_1", conversation_id="ck:wf:agent_1:k",
        subject="This subject is ignored mid-thread",
        body="Done — Slack is wired up now.",
    )
    assert result["success"] is True
    assert sent["subject"] == "Re: Need you to connect Slack"
    assert sent["extra_headers"]["In-Reply-To"] == "<user-reply@gmail.com>"
    assert sent["extra_headers"]["References"] == "<user-reply@gmail.com>"
    # The result tells the model this rode the existing thread (its cue not
    # to re-introduce itself).
    assert "reply in the existing email thread" in result["message"]
    # Footer (with Unsubscribe) still rides every email.
    assert "Unsubscribe" in sent["text"] and ">Unsubscribe</a>" in sent["html"]


@pytest.mark.asyncio
async def test_send_agent_email_gates(monkeypatch):
    from billing.exceptions import InsufficientBalanceError
    from utils import agent_email

    # Empty subject/body refused before any I/O.
    result = await agent_email.send_agent_email(
        MagicMock(), user_id="u", organization_id=None, workflow_id="wf",
        node_id="n", conversation_id=None, subject="", body="hi",
    )
    assert result["success"] is False

    # One send per execution — the fan-out backstop runs before the daily cap.
    monkeypatch.setattr(agent_email, "_execution_cap_hit", AsyncMock(return_value=True))
    daily = AsyncMock(return_value=False)
    monkeypatch.setattr(agent_email, "_daily_cap_hit", daily)
    result = await agent_email.send_agent_email(
        MagicMock(), user_id="u", organization_id=None, workflow_id="wf",
        node_id="n", conversation_id=None, subject="s", body="b",
        execution_id="exec-1",
    )
    assert result["success"] is False and "workflow execution" in result["error"]
    daily.assert_not_awaited()

    # Daily cap.
    monkeypatch.setattr(agent_email, "_execution_cap_hit", AsyncMock(return_value=False))
    monkeypatch.setattr(agent_email, "_daily_cap_hit", AsyncMock(return_value=True))
    result = await agent_email.send_agent_email(
        MagicMock(), user_id="u", organization_id=None, workflow_id="wf",
        node_id="n", conversation_id=None, subject="s", body="b",
    )
    assert result["success"] is False and "cap" in result["error"].lower()

    # Credit gate failure surfaces as a tool error, not an exception.
    monkeypatch.setattr(agent_email, "_daily_cap_hit", AsyncMock(return_value=False))
    from billing.usage_tracker import usage_tracker

    monkeypatch.setattr(
        usage_tracker, "enforce_credit_gate",
        AsyncMock(side_effect=InsufficientBalanceError("Insufficient credits")),
    )
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value="o@x.com")  # owner email (get_user_email)
    result = await agent_email.send_agent_email(
        pool, user_id="u", organization_id=None, workflow_id="wf",
        node_id="n", conversation_id=None, subject="s", body="b",
    )
    assert result["success"] is False and "credit" in result["error"].lower()


@pytest.mark.asyncio
async def test_execution_cap_is_shared_by_parallel_items(monkeypatch):
    from utils import agent_email

    redis = MagicMock()
    redis.incr = AsyncMock(side_effect=[1, 2])
    redis.expire = AsyncMock()
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: redis)

    first = await agent_email._execution_cap_hit("wf", "agent", "exec-1")
    second = await agent_email._execution_cap_hit("wf", "agent", "exec-1")

    assert first is False
    assert second is True
    assert redis.incr.await_args_list[0].args[0].endswith(":wf:agent:exec-1")
    redis.expire.assert_awaited_once()


# ── inbound branch ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inbound_reply_verifies_owner_and_fires(monkeypatch):
    from utils.email_routes import _receive_agent_reply

    ctx = {
        "id": uuid.uuid4(), "user_id": "u-1", "workflow_id": "wf-1",
        "node_id": "agent_1", "conversation_id": "ck:wf-1:agent_1:k",
    }
    monkeypatch.setattr(
        "utils.agent_email.resolve_reply_address", AsyncMock(return_value=ctx)
    )
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value="Owner@X.com")
    pool.execute = AsyncMock()
    monkeypatch.setattr("utils.email_routes.get_native_pool", lambda: pool)
    monkeypatch.setattr(
        "utils.email_routes._parse_mime", lambda raw: {"text": "yes do it"}
    )
    tasks = MagicMock()

    import base64

    payload = {
        "from": "owner@x.com", "subject": "Re: q",
        "headers": {"message-id": "<user-reply@gmail.com>"},
        "rawBase64": base64.b64encode(b"x").decode(),
    }
    resp = await _receive_agent_reply("agent-reply-abc", payload, tasks)
    assert resp.triggered is True
    args, kwargs = tasks.add_task.call_args
    assert kwargs["user_id"] == "u-1" and kwargs["node_id"] == "agent_1"
    assert kwargs["body"] == "yes do it"
    # The user's Message-ID becomes the thread anchor for the agent's next send.
    anchor = pool.execute.await_args.args
    assert anchor[1] == ctx["id"] and anchor[2] == "<user-reply@gmail.com>"

    # A stranger's mail is dropped quietly — no turn, no bounce detail.
    tasks.reset_mock()
    resp = await _receive_agent_reply(
        "agent-reply-abc", {**payload, "from": "evil@z.com"}, tasks
    )
    assert resp.triggered is False and tasks.add_task.call_count == 0

    # Unknown address: same quiet drop.
    monkeypatch.setattr(
        "utils.agent_email.resolve_reply_address", AsyncMock(return_value=None)
    )
    resp = await _receive_agent_reply("agent-reply-zzz", payload, tasks)
    assert resp.triggered is False


# ── presence ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_presence_describe_buckets(monkeypatch):
    from utils import user_presence

    async def age(val):
        monkeypatch.setattr(
            user_presence, "seconds_since_active", AsyncMock(return_value=val)
        )
        return await user_presence.describe_owner_presence("u")

    assert "ACTIVE" in await age(30)
    assert "minutes ago" in await age(20 * 60)
    assert "hours ago" in await age(5 * 3600)
    assert "days ago" in await age(3 * 86400)
    assert "no recent" in await age(None)


def test_presence_touch_throttles(monkeypatch):
    from utils import user_presence

    user_presence._last_stamped.clear()
    stamped = []
    redis = MagicMock()
    redis.set = AsyncMock(side_effect=lambda *a, **k: stamped.append(a))
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: redis)
    spawned = []
    monkeypatch.setattr(
        "utils.async_helpers.spawn",
        lambda coro, name=None: (spawned.append(coro), coro.close()),
    )

    user_presence.touch_user_presence("u-1")
    user_presence.touch_user_presence("u-1")  # throttled
    user_presence.touch_user_presence("u-2")
    assert len(spawned) == 2


@pytest.mark.asyncio
async def test_presence_touch_fails_open_and_allows_retry(monkeypatch):
    from utils import user_presence

    user_presence._last_stamped.clear()
    redis = MagicMock()
    redis.set = AsyncMock(side_effect=TimeoutError("redis unavailable"))
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: redis)
    spawned = []
    monkeypatch.setattr(
        "utils.async_helpers.spawn",
        lambda coro, name=None: spawned.append(coro),
    )

    user_presence.touch_user_presence("u-1")
    await spawned.pop()
    assert "u-1" not in user_presence._last_stamped

    user_presence.touch_user_presence("u-1")
    assert len(spawned) == 1
    await spawned.pop()
