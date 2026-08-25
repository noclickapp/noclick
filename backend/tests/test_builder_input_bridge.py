"""Builder input bridge: public capability links for answering a parked
agent-initiated builder run's <ask/> without a NoClick account (2026-07-19).

Repo SQL runs against the LOCAL postgres (skipped when unreachable); routes,
minting, and the finalize hooks are unit-tested with fakes.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.test_builder_decision_loop import LOCAL_DSN, local_pool  # noqa: F401 (fixture)


# ── repo SQL (real local DB) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bridge_link_lifecycle_roundtrip(local_pool):  # noqa: F811
    from repositories.builder_bridge import BuilderBridgeRepo

    async with local_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM auth.users LIMIT 1")
    if not row:
        pytest.skip("no local users to satisfy the FK")
    user_id = str(row["id"])
    repo = BuilderBridgeRepo(local_pool)
    link_id = None
    try:
        link_id = await repo.create_link(
            user_id=user_id,
            workflow_id=str(uuid.uuid4()),
            builder_conversation_id="agent-builder:wf:agent_1:abc",
            ask_id="ask-1",
            agent_conversation_id="ck:wf:agent_1:tg:123",
            agent_node_id="agent_1",
            inputs=[{"id": "ask_0", "label": "Which channel?", "type": "text", "required": True}],
            workflow_name="Slack Bot",
        )
        link = await repo.load_pending(link_id)
        assert link and link["ask_id"] == "ask-1"
        assert link["workflow_name"] == "Slack Bot"

        # Exactly-once consume: first submit wins, the second loses, and a
        # consumed link no longer resolves.
        assert await repo.mark_answered(link_id) is True
        assert await repo.mark_answered(link_id) is False
        assert await repo.load_pending(link_id) is None

        # Garbage ids resolve to None, never raise.
        assert await repo.load_pending("not-a-uuid") is None
        assert await repo.load_pending(str(uuid.uuid4())) is None
    finally:
        if link_id:
            async with local_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM builder_input_links WHERE id=$1::uuid", link_id
                )


# ── link minting ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_bridge_link_mints_credential_requests(monkeypatch):
    from utils import builder_bridge

    created = {}

    async def fake_create_link(self, **kw):
        created.update(kw)
        return "link-123"

    async def fake_upsert(self, **kw):
        return SimpleNamespace(id=uuid.uuid4(), token="tok-abc")

    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.create_link", fake_create_link
    )
    monkeypatch.setattr(
        "repositories.credentials.CredentialsRepo.upsert_credential_request", fake_upsert
    )
    monkeypatch.setattr(
        "mcp_adapter.auth.endpoints.get_frontend_url", lambda: "https://www.noclick.com"
    )

    result = await builder_bridge.create_bridge_link_for_ask(
        MagicMock(),
        user_id=str(uuid.uuid4()),
        workflow_id=str(uuid.uuid4()),
        builder_conversation_id="conv-1",
        ask_id="ask-1",
        inputs=[
            {"id": "ask_0", "label": "Which channel?", "type": "config",
             "nodeConfig": {"secret": "MUST_NOT_LEAK"}, "credentialIds": {"a": "b"}},
            {"id": "ask_1", "label": "Connect Slack", "type": "credential",
             "credentialType": "slack"},
        ],
        agent_conversation_id="ck:...",
        agent_node_id="agent_1",
        workflow_name="Slack Bot",
    )
    assert result and result["url"] == "https://www.noclick.com/b/link-123"
    assert result["questions"] == ["Which channel?", "Connect Slack"]
    stored = created["inputs"]
    # Sanitization: node configs / credential id maps never reach the row.
    assert "nodeConfig" not in stored[0] and "credentialIds" not in stored[0]
    # Credential input delegates to the EXISTING public provide flow.
    assert stored[1]["credential_provide_url"].endswith("/credential/provide/tok-abc")
    assert stored[1]["credential_request_id"]


def test_sanitize_input_carries_multiple_flag():
    """<ask multiple="true"> selection asks keep their flag through the public
    projection so the /b page renders checkboxes; absent stays absent."""
    from utils.builder_bridge import _sanitize_input

    multi = _sanitize_input({
        "id": "ask_0", "label": "Which alerts?", "type": "selection",
        "options": [{"id": "A", "label": "A"}], "multiple": True,
    })
    assert multi["multiple"] is True
    single = _sanitize_input({
        "id": "ask_1", "label": "Which tone?", "type": "selection",
        "options": [{"id": "A", "label": "A"}], "multiple": False,
    })
    assert "multiple" not in single


# ── public routes ────────────────────────────────────────────────────────────


def _link_row(inputs):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    return {
        "id": "link-1", "user_id": uuid.uuid4(), "workflow_id": uuid.uuid4(),
        "builder_conversation_id": "conv-1", "ask_id": "ask-1",
        "agent_conversation_id": "ck:...", "agent_node_id": "agent_1",
        "inputs": inputs, "workflow_name": "Slack Bot",
        "created_at": now, "expires_at": now + timedelta(days=7),
    }


@pytest.mark.asyncio
async def test_bridge_get_hides_credential_request_id(monkeypatch):
    from fastapi import HTTPException

    from utils import builder_bridge_routes as routes

    link = _link_row([
        {"id": "ask_0", "label": "Which channel?", "type": "text", "required": True},
        {"id": "ask_1", "label": "Connect Slack", "type": "credential",
         "credential_type": "slack", "credential_request_id": "req-1",
         "credential_provide_url": "https://x/credential/provide/tok"},
    ])
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.load_pending",
        AsyncMock(return_value=link),
    )
    monkeypatch.setattr(
        routes, "_credential_state",
        AsyncMock(return_value={"status": "fulfilled", "credential_id": uuid.uuid4()}),
    )
    monkeypatch.setattr("utils.builder_bridge_routes.get_native_pool", lambda: MagicMock())

    resp = await routes.get_bridge_link("link-1")
    assert resp["workflow_name"] == "Slack Bot"
    cred = resp["inputs"][1]
    assert "credential_request_id" not in cred
    assert cred["credential_fulfilled"] is True
    assert cred["credential_provide_url"].endswith("/tok")

    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.load_pending",
        AsyncMock(return_value=None),
    )
    with pytest.raises(HTTPException) as exc:
        await routes.get_bridge_link("link-1")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_bridge_submit_resolves_credentials_and_resumes_as_owner(monkeypatch):
    from utils import builder_bridge_routes as routes
    from utils.builder_bridge_routes import BridgeSubmitBody

    owner = uuid.uuid4()
    cred_id = uuid.uuid4()
    link = _link_row([
        {"id": "ask_0", "label": "Which channel?", "type": "text", "required": True},
        {"id": "ask_1", "label": "Connect Slack", "type": "credential",
         "credential_type": "slack", "credential_request_id": "req-1", "required": True},
    ])
    link["user_id"] = owner
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.load_pending",
        AsyncMock(return_value=link),
    )
    marked = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.mark_answered", marked
    )
    monkeypatch.setattr(
        routes, "_credential_state",
        AsyncMock(return_value={"status": "fulfilled", "credential_id": cred_id}),
    )
    monkeypatch.setattr("utils.builder_bridge_routes.get_native_pool", lambda: MagicMock())
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: MagicMock())
    resumed = {}

    class FakeHandler:
        def __init__(self, sio):
            pass

        async def handle_input_response(self, sid, data, caller_user_id=None):
            resumed.update({"sid": sid, "data": data, "caller_user_id": caller_user_id})

    monkeypatch.setattr(
        "wss.handlers.workflow_builder_handler.WorkflowBuilderHandler", FakeHandler
    )
    spawned = []
    monkeypatch.setattr(
        "utils.async_helpers.spawn",
        lambda coro, name=None: spawned.append(coro),
    )

    resp = await routes.submit_bridge_answers(
        "link-1", BridgeSubmitBody(values={"ask_0": "#alerts", "ignored": "x"})
    )
    assert resp == {"success": True}
    assert marked.await_count == 1
    # Run the spawned resume coroutine to observe the payload.
    assert spawned
    await spawned[0]
    assert resumed["sid"] == ""
    assert resumed["caller_user_id"] == str(owner)
    assert resumed["data"]["conversation_id"] == "conv-1"
    assert resumed["data"]["ask_id"] == "ask-1"
    # Text answer passes through; the credential resolves to the FULFILLED
    # request's credential id — the visitor never supplies one.
    assert resumed["data"]["values"] == {"ask_0": "#alerts", "ask_1": str(cred_id)}


@pytest.mark.asyncio
async def test_bridge_submit_skips_unconnected_credential_but_refuses_empty(monkeypatch):
    """Drawer partial-submit semantics: a skipped credential is OMITTED (the
    brain re-asks or proceeds) — but an entirely-empty submit is refused and
    the link is NOT consumed."""
    from fastapi import HTTPException

    from utils import builder_bridge_routes as routes
    from utils.builder_bridge_routes import BridgeSubmitBody

    link = _link_row([
        {"id": "ask_0", "label": "Which channel?", "type": "text", "required": True},
        {"id": "ask_1", "label": "Connect Slack", "type": "credential",
         "credential_type": "slack", "credential_request_id": "req-1", "required": True},
    ])
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.load_pending",
        AsyncMock(return_value=link),
    )
    monkeypatch.setattr(
        routes, "_credential_state",
        AsyncMock(return_value={"status": "pending", "credential_id": None}),
    )
    monkeypatch.setattr("utils.builder_bridge_routes.get_native_pool", lambda: MagicMock())
    mark = AsyncMock(return_value=True)
    monkeypatch.setattr("repositories.builder_bridge.BuilderBridgeRepo.mark_answered", mark)

    # Empty submit: refused, link untouched.
    with pytest.raises(HTTPException) as exc:
        await routes.submit_bridge_answers("link-1", BridgeSubmitBody(values={}))
    assert exc.value.status_code == 422
    assert mark.await_count == 0

    # Text answered, credential skipped: accepted — the credential is omitted.
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: MagicMock())
    resumed = {}

    class FakeHandler:
        def __init__(self, sio):
            pass

        async def handle_input_response(self, sid, data, caller_user_id=None):
            resumed.update(data)

    monkeypatch.setattr(
        "wss.handlers.workflow_builder_handler.WorkflowBuilderHandler", FakeHandler
    )
    spawned = []
    monkeypatch.setattr("utils.async_helpers.spawn", lambda coro, name=None: spawned.append(coro))
    resp = await routes.submit_bridge_answers("link-1", BridgeSubmitBody(values={"ask_0": "#alerts"}))
    assert resp == {"success": True}
    await spawned[0]
    assert resumed["values"] == {"ask_0": "#alerts"}


# ── finalize hooks ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_paused_finalizer_mints_link_and_notifies_agent(monkeypatch):
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    handler = WorkflowBuilderHandler(MagicMock())
    handler.get_pool = AsyncMock(return_value=MagicMock())
    minted = AsyncMock(return_value={
        "link_id": "l1", "url": "https://x/b/l1", "questions": ["Which channel?"],
    })
    appended = AsyncMock()
    monkeypatch.setattr("utils.builder_bridge.create_bridge_link_for_ask", minted)
    monkeypatch.setattr("utils.builder_bridge.append_agent_builder_event", appended)

    request = SimpleNamespace(
        conversation_id="agent-builder:wf:agent_1:abc",
        user_context={
            "source": "agent_prompt_builder", "workflow_id": "wf-1",
            "agent_conversation_id": "ck:wf:agent_1:tg:9", "agent_node_id": "agent_1",
        },
    )
    builder = SimpleNamespace(graph_state=SimpleNamespace(workflow_name="Slack Bot"))
    pending_ask = SimpleNamespace(to_dict=lambda: {
        "ask_id": "ask-1",
        "inputs": [{"id": "ask_0", "label": "Which channel?", "type": "text"}],
    })

    await handler._maybe_notify_agent_ask(
        request=request, user_id="owner-1", builder=builder, pending_ask=pending_ask,
    )
    assert minted.await_count == 1
    kw = appended.await_args.kwargs
    assert kw["kind"] == "builder_ask"
    assert kw["agent_conversation_id"] == "ck:wf:agent_1:tg:9"
    assert kw["payload"]["bridge_url"] == "https://x/b/l1"
    assert kw["payload"]["relay_id"] == "l1"

    # Non-agent runs (interactive sidebar) never mint links.
    minted.reset_mock(); appended.reset_mock()
    request.user_context = {"workflow_id": "wf-1"}
    await handler._maybe_notify_agent_ask(
        request=request, user_id="owner-1", builder=builder, pending_ask=pending_ask,
    )
    assert minted.await_count == 0 and appended.await_count == 0


@pytest.mark.asyncio
async def test_complete_finalizer_relays_result(monkeypatch):
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    handler = WorkflowBuilderHandler(MagicMock())
    handler.get_pool = AsyncMock(return_value=MagicMock())
    appended = AsyncMock()
    monkeypatch.setattr("utils.builder_bridge.append_agent_builder_event", appended)

    request = SimpleNamespace(
        conversation_id="agent-builder:wf:agent_1:abc",
        user_context={
            "source": "agent_prompt_builder", "workflow_id": "wf-1",
            "agent_conversation_id": "ck:wf:agent_1:tg:9", "agent_node_id": "agent_1",
        },
    )
    builder = SimpleNamespace(
        graph_state=SimpleNamespace(workflow_name="Slack Bot", summary="2 nodes"),
    )
    segments = [
        {"type": "text", "text": "Added a Slack provider"},
        {"type": "graph", "data": {}},
        {"type": "text", "text": "and wired it to your agent."},
    ]
    await handler._maybe_notify_agent_result(
        request=request, user_id="owner-1", builder=builder, segments=segments,
    )
    kw = appended.await_args.kwargs
    assert kw["kind"] == "builder_result"
    assert kw["payload"]["summary"] == "Added a Slack provider\nand wired it to your agent."
    assert kw["payload"]["relay_id"]


@pytest.mark.asyncio
async def test_load_origin_restores_agent_return_address(local_pool):  # noqa: F811
    """The resume path rebuilds user_context from scratch — the bridge link row
    is the durable agent-origin record it restores from. Without it, a
    bridge-answered run's completion never reaches the agent."""
    from repositories.builder_bridge import BuilderBridgeRepo

    async with local_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM auth.users LIMIT 1")
    if not row:
        pytest.skip("no local users to satisfy the FK")
    repo = BuilderBridgeRepo(local_pool)
    conv = f"agent-builder:wf:agent_1:{uuid.uuid4().hex[:8]}"
    link_id = await repo.create_link(
        user_id=str(row["id"]), workflow_id=str(uuid.uuid4()),
        builder_conversation_id=conv, ask_id="ask-1",
        agent_conversation_id="ck:wf:agent_1:tg:9", agent_node_id="agent_1",
        inputs=[], workflow_name=None,
    )
    try:
        origin = await repo.load_origin(conv)
        assert origin == {
            "agent_conversation_id": "ck:wf:agent_1:tg:9", "agent_node_id": "agent_1",
        }
        assert await repo.load_origin("agent-builder:no:such:conv") is None
    finally:
        async with local_pool.acquire() as conn:
            await conn.execute("DELETE FROM builder_input_links WHERE id=$1::uuid", link_id)


@pytest.mark.asyncio
async def test_share_ask_mints_idempotently_for_owner(monkeypatch):
    """The drawer's share button: user-scoped read, ask must still be pending,
    and re-clicks return the SAME link instead of minting duplicates."""
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler
    from wss.receiver.client_events import ShareBuilderAskRequest

    handler = WorkflowBuilderHandler(MagicMock())
    handler.sio.get_session = AsyncMock(return_value={"user_id": "u-1"})
    handler.get_pool = AsyncMock(return_value=MagicMock(acquire=MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=MagicMock(fetchval=AsyncMock(return_value="Slack Bot"))),
            __aexit__=AsyncMock(),
        ))))
    monkeypatch.setattr(
        WorkflowBuilderHandler, "_read_conversation_events",
        AsyncMock(return_value=[
            {"role": "user", "message": "build it"},
            {"role": "assistant", "message": "", "pending_ask": {
                "ask_id": "ask-1",
                "inputs": [{"id": "ask_0", "label": "Which channel?", "type": "text"}],
            }},
        ]),
    )
    monkeypatch.setattr(
        "repositories.conversation.ConversationRepo.get_workflow_id",
        AsyncMock(return_value=str(uuid.uuid4())),
    )
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.find_pending_for_ask",
        AsyncMock(return_value=None),
    )
    minted = AsyncMock(return_value={"link_id": "l9", "url": "https://x/b/l9", "questions": []})
    monkeypatch.setattr("utils.builder_bridge.create_bridge_link_for_ask", minted)
    sent = []
    monkeypatch.setattr(
        "wss.handlers.workflow_builder_handler.send_event",
        AsyncMock(side_effect=lambda sio, sid, ev, **kw: sent.append(ev)),
    )

    req = ShareBuilderAskRequest(request_id="r1", conversation_id="conv-1", ask_id="ask-1")
    await handler.handle_share_ask("sid-1", req)
    assert sent[-1].data == {"success": True, "url": "https://x/b/l9", "link_id": "l9"}
    assert minted.await_args.kwargs["agent_conversation_id"] is None  # manual share

    # Second click: existing pending link wins — no second mint.
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.find_pending_for_ask",
        AsyncMock(return_value="l9"),
    )
    monkeypatch.setattr(
        "utils.builder_bridge.bridge_url", lambda lid: f"https://x/b/{lid}",
    )
    minted.reset_mock()
    await handler.handle_share_ask("sid-1", req)
    assert sent[-1].data["url"] == "https://x/b/l9"
    assert minted.await_count == 0

    # A stale/answered ask can't be shared.
    monkeypatch.setattr(
        WorkflowBuilderHandler, "_read_conversation_events",
        AsyncMock(return_value=[{"role": "assistant", "message": "done"}]),
    )
    await handler.handle_share_ask("sid-1", req)
    assert sent[-1].data["success"] is False


@pytest.mark.asyncio
async def test_drawer_answer_voids_outstanding_links(local_pool):  # noqa: F811
    """Answering the ask anywhere (drawer or another link) must expire every
    still-pending link for it — a stale public page kept loading otherwise."""
    from repositories.builder_bridge import BuilderBridgeRepo

    async with local_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM auth.users LIMIT 1")
    if not row:
        pytest.skip("no local users to satisfy the FK")
    repo = BuilderBridgeRepo(local_pool)
    conv = f"agent-builder:void:{uuid.uuid4().hex[:8]}"
    link_id = await repo.create_link(
        user_id=str(row["id"]), workflow_id=str(uuid.uuid4()),
        builder_conversation_id=conv, ask_id="ask-1",
        agent_conversation_id=None, agent_node_id=None,
        inputs=[], workflow_name=None,
    )
    try:
        await repo.void_pending_links_for_ask(conv, "ask-1")
        assert await repo.load_pending(link_id) is None
        # Voided links also lose the exactly-once consume race cleanly.
        assert await repo.mark_answered(link_id) is False
    finally:
        async with local_pool.acquire() as conn:
            await conn.execute("DELETE FROM builder_input_links WHERE id=$1::uuid", link_id)


def test_derive_credential_type_covers_ungated_nodes():
    """The bridge keys credential_requests on the node schema's own type via
    the UNGATED def-scan — WhatsApp QR (not OAuth, not allowlisted) minted no
    provide link before (2026-07-19). Pin the general seam across gating
    classes: QR, OAuth, and plain-token nodes all derive non-empty."""
    from coder.workflow.operation_catalog import derive_credential_type

    assert derive_credential_type("automation-whatsapp") == "whatsapp_qr"
    assert derive_credential_type("automation-slack") == "slack_oauth"
    assert derive_credential_type("automation-telegram") == "telegram_bot_token"


@pytest.mark.asyncio
async def test_heal_link_inputs_repairs_legacy_snapshots(monkeypatch):
    """Links minted before the derivation/token fixes served dead credential
    steps forever (the share button re-hands out the same pending link). The
    GET/POST heal re-derives from the conversation's FULL pending_ask and
    mints the missing credential_request, persisting the repaired snapshot."""
    from utils import builder_bridge

    class FakePool:
        async def fetchrow(self, query, *args):
            if "pending_ask" in query:
                return {"pending_ask": {
                    "ask_id": "ask-1",
                    "inputs": [
                        {"id": "ask_3", "label": "Connect your WhatsApp account",
                         "type": "credential", "nodeType": "automation-whatsapp",
                         "nodeConfig": {}},
                    ],
                }}
            raise AssertionError(f"unexpected query: {query}")

    minted = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), token="tok-wa"))
    monkeypatch.setattr(
        "repositories.credentials.CredentialsRepo.upsert_credential_request", minted
    )
    persisted = AsyncMock()
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.update_inputs", persisted
    )
    monkeypatch.setattr(
        "coder.workflow.operation_catalog.derive_credential_type",
        lambda nt, op=None, cfg=None: "whatsapp_qr",
    )

    link = _link_row([
        # Empty-type era: no credential_type, no request, no token.
        {"id": "ask_3", "label": "Connect your WhatsApp account",
         "type": "credential", "required": True},
        # Healthy entry: untouched.
        {"id": "ask_4", "type": "credential", "credential_type": "slack_oauth",
         "credential_request_id": "req-9", "credential_provide_token": "tok-ok",
         "credential_provide_url": "https://x/credential/provide/tok-ok"},
    ])
    healed = await builder_bridge.heal_link_inputs(FakePool(), link)

    wa = healed[0]
    assert wa["credential_type"] == "whatsapp_qr"
    assert wa["credential_provide_token"] == "tok-wa"
    assert wa["credential_provide_url"].endswith("/credential/provide/tok-wa")
    assert minted.await_args.kwargs["credential_type"] == "whatsapp_qr"
    # Healthy entry untouched; repaired snapshot persisted once.
    assert healed[1]["credential_provide_token"] == "tok-ok"
    assert persisted.await_count == 1


@pytest.mark.asyncio
async def test_heal_backfills_token_without_rotating_existing_request(monkeypatch):
    """Pre-inline-token era: the request exists — read its token instead of
    re-minting (an upsert would rotate the token under a live provide tab)."""
    from utils import builder_bridge

    class FakePool:
        async def fetchrow(self, query, *args):
            assert "credential_requests" in query
            return {"token": "tok-existing", "credential_type": "slack_oauth"}

    minted = AsyncMock()
    monkeypatch.setattr(
        "repositories.credentials.CredentialsRepo.upsert_credential_request", minted
    )
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.update_inputs", AsyncMock()
    )

    link = _link_row([
        {"id": "ask_1", "type": "credential", "credential_type": "slack_oauth",
         "credential_request_id": str(uuid.uuid4()),
         "credential_provide_url": "https://x/credential/provide/tok-existing"},
    ])
    healed = await builder_bridge.heal_link_inputs(FakePool(), link)
    assert healed[0]["credential_provide_token"] == "tok-existing"
    assert minted.await_count == 0


@pytest.mark.asyncio
async def test_reconnect_reopens_credential_and_refreshes_snapshot(monkeypatch):
    """'Connected' is not an ending: reconnect re-upserts the request (rotates
    token, resets to pending — never touching the already-created credential)
    and refreshes the snapshot so the connect UI renders again."""
    from utils import builder_bridge_routes as routes
    from utils.builder_bridge_routes import BridgeReconnectBody

    link = _link_row([
        {"id": "ask_1", "type": "credential", "credential_type": "slack_oauth",
         "credential_request_id": "req-old", "credential_provide_token": "tok-old",
         "credential_provide_url": "https://x/credential/provide/tok-old", "required": True},
    ])
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.load_pending",
        AsyncMock(return_value=link),
    )
    new_id = uuid.uuid4()
    minted = AsyncMock(return_value=SimpleNamespace(id=new_id, token="tok-new"))
    monkeypatch.setattr(
        "repositories.credentials.CredentialsRepo.upsert_credential_request", minted
    )
    persisted = AsyncMock()
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.update_inputs", persisted
    )
    monkeypatch.setattr("utils.builder_bridge_routes.get_native_pool", lambda: MagicMock())

    resp = await routes.reconnect_bridge_credential(
        "link-1", BridgeReconnectBody(input_id="ask_1")
    )
    assert resp == {"success": True}
    assert minted.await_args.kwargs["credential_type"] == "slack_oauth"
    saved = persisted.await_args.args[1]
    assert saved[0]["credential_provide_token"] == "tok-new"
    assert saved[0]["credential_request_id"] == str(new_id)

    # Unknown input id → 404, nothing minted.
    from fastapi import HTTPException

    minted.reset_mock()
    with pytest.raises(HTTPException) as exc:
        await routes.reconnect_bridge_credential(
            "link-1", BridgeReconnectBody(input_id="nope")
        )
    assert exc.value.status_code == 404
    assert minted.await_count == 0


@pytest.mark.asyncio
async def test_wake_turn_fires_empty_message_run_as_owner(monkeypatch):
    """Builder events PUSH an immediate agent turn (empty user message — the
    pre-dispatch relay composes the pending events into it) instead of waiting
    for the next user message."""
    from utils.builder_bridge import fire_agent_wake_turn

    monkeypatch.setattr(
        "repositories.conversation.ConversationRepo.fetch_unrelayed_builder_events",
        AsyncMock(return_value=[{"kind": "builder_ask", "payload": {}}]),
    )
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

    await fire_agent_wake_turn(
        MagicMock(), user_id="owner", workflow_id="wf-1", node_id="agent_1",
        agent_conversation_id="ck:wf-1:agent_1:tg:99",
    )
    assert fired["sid"] == "" and fired["caller"] == "owner"
    req = fired["request"]
    assert req.trigger_source == "builder_event"
    assert req.start_node_id == "agent_1"
    override = req.config_overrides["agent_1"]
    # Sentinel, not "" — every agent config model requires min_length=1, so an
    # empty message crashed validation before the relay could compose events in.
    from utils.builder_bridge import WAKE_TURN_MESSAGE
    assert override["message"] == WAKE_TURN_MESSAGE
    # ck parsing keeps colons inside the key intact (tg:99).
    assert override["conversation_key"] == "tg:99"
    assert override["mockedOutput"] is None


@pytest.mark.asyncio
async def test_wake_turn_skips_when_nothing_undelivered_or_unkeyable(monkeypatch):
    from utils.builder_bridge import fire_agent_wake_turn

    monkeypatch.setattr(
        "repositories.conversation.ConversationRepo.fetch_unrelayed_builder_events",
        AsyncMock(return_value=[]),
    )
    fired = AsyncMock()

    class FakeExec:
        def __init__(self, sio):
            pass

        handle_execute = fired

    monkeypatch.setattr(
        "wss.handlers.workflow_execution_handler.WorkflowExecutionHandler", FakeExec
    )
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: MagicMock())

    # Nothing undelivered → no turn (a user turn consumed the events already).
    await fire_agent_wake_turn(
        MagicMock(), user_id="o", workflow_id="w", node_id="n",
        agent_conversation_id="ck:w:n:key",
    )
    # Non-ck conversation ids can't be re-keyed into a run → no turn.
    await fire_agent_wake_turn(
        MagicMock(), user_id="o", workflow_id="w", node_id="n",
        agent_conversation_id="some-legacy-id",
    )
    assert fired.await_count == 0


# ── Wake-turn message survives agent config validation ──────────────────────

def test_wake_turn_sentinel_passes_config_validation():
    """The 2026-07-31 crash class: every agent config model requires
    message min_length=1, and validation runs at node construction — BEFORE
    the pre-dispatch relay could replace an empty wake message. The sentinel
    must parse for the harness that crashed (claude-code) and the SDK default;
    the empty string must still be rejected (that contract is why the sentinel
    exists)."""
    from nodes.agent_node import AgentNode
    from nodes.core.base import ConfigValidationError
    from utils.builder_bridge import WAKE_TURN_MESSAGE

    for model in ("claude-code", "gpt-5.2"):
        parsed = AgentNode.parse_config(
            {"config": {"model": model, "message": WAKE_TURN_MESSAGE}}
        )
        assert parsed.config.message == WAKE_TURN_MESSAGE

        with pytest.raises(ConfigValidationError):
            AgentNode.parse_config({"config": {"model": model, "message": ""}})


def test_skipped_wake_output_does_not_propagate_downstream():
    from nodes.agent_node import AgentNode

    skipped = {"status": "success", "skipped": True, "message": "nothing to relay"}
    assert AgentNode.should_propagate_output(skipped, {}) is False
    assert AgentNode.should_propagate_output({"status": "success", "response": "hi"}, {}) is True
