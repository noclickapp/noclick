"""Designed agent features against the mocked API: schedules (``Cron`` triggers
and their convergence from a definition; webhooks and app events are built, see
``test_triggers.py``), pause and resume, memory, workspace files, the share link,
streamed turns, rehearsals, hosted MCP servers and simulated toolkits."""

import asyncio

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, operation, user_row

AGENT = agent_row(id="ag_1", name="support")


def _trigger(trigger_id, kind, spec, **extra):
    return {"object": "agent_trigger", "id": trigger_id, "kind": kind, "spec": spec, "status": "active",
            "url": None, "next_run": None, "last_fired_at": None, "error": None,
            "created_at": "2026-09-25T10:00:00Z", **extra}


CRON = _trigger("tr_1", "cron", {"cron": "0 8 * * 1-5", "tz": "Europe/London", "message": "Old summary"},
                next_run="2026-09-28T07:00:00Z")
WEBHOOK = _trigger("tr_2", "webhook", {"name": "orders"}, url="https://hooks.noclick.app/t/wh_secret")
EMAIL = _trigger("tr_3", "email", {"inbox_id": "inb_1", "address": "help@acme.test"})


# --- definitions -------------------------------------------------------------------

def test_create_sends_triggers_browser_profile_and_card(api, client):
    api.get("/v1/connections/slack").respond(json={"object": "connection", "id": "cn_1", "name": "slack",
                                                   "integration": "slack", "status": "connected"})
    api.get("/v1/cards/card_9").respond(json={"object": "card", "id": "card_9", "name": "Software"})
    create = api.post("/v1/agents").respond(json={**AGENT, "trigger_kinds": ["cron", "webhook", "event"],
                                                  "browser_profile_id": "bp_1", "card_id": "card_9", "paused": False})
    slack = nc.Connection.from_name("slack")
    agent = nc.Agent.create(
        "support", instructions="Answer #support.",
        triggers=[nc.Cron("0 8 * * 1-5", tz="Europe/London", message="Post the summary"),
                  nc.OnWebhook(name="orders"),
                  nc.OnEvent(slack, "message", channel="#support", message="Answer it")],
        browser_profile="bp_1", card=nc.Card.from_id("card_9"),
    )
    assert body(create.calls.last.request) == {
        "name": "support", "instructions": "Answer #support.",
        "triggers": [
            {"kind": "cron", "cron": "0 8 * * 1-5", "tz": "Europe/London", "message": "Post the summary"},
            {"kind": "webhook", "name": "orders"},
            {"kind": "event", "connection": "slack", "event": "message", "filters": {"channel": "#support"},
             "message": "Answer it"},
        ],
        "browser_profile_id": "bp_1", "card_id": "card_9",
    }
    assert (agent.trigger_kinds, agent.browser_profile_id, agent.card_id, agent.paused) == (
        ["cron", "webhook", "event"], "bp_1", "card_9", False)




def test_from_name_converges_triggers_and_keeps_mail_and_webhooks(api, client):
    api.get("/v1/agents").respond(json=listing({**AGENT, "trigger_kinds": ["cron", "webhook", "email"]}))
    api.get("/v1/agents/ag_1/triggers").respond(json=listing(CRON, WEBHOOK, EMAIL))
    removed = api.delete("/v1/agents/ag_1/triggers/tr_1").respond(204)
    added = api.post("/v1/agents/ag_1/triggers").respond(json=_trigger("tr_4", "cron", {}))
    reread = api.get("/v1/agents/ag_1").respond(json={**AGENT, "trigger_kinds": ["cron", "webhook", "email"]})
    patch = api.patch("/v1/agents/ag_1").respond(json=AGENT)

    agent = nc.Agent.from_name(
        "support", create_if_missing=True, instructions="hi",
        triggers=[nc.Cron("0 8 * * 1-5", tz="Europe/London", message="New summary"), nc.OnWebhook(name="orders")],
    )
    assert agent.id == "ag_1"
    assert patch.call_count == 0  # nothing else differs
    assert removed.call_count == 1  # the old schedule, not the webhook (its URL stays) nor the inbox's email
    assert body(added.calls.last.request) == {
        "kind": "cron", "cron": "0 8 * * 1-5", "tz": "Europe/London", "message": "New summary"}
    assert reread.call_count == 1




def test_from_name_finds_an_agent_by_the_name_it_had_before_a_rename(api, client):
    renamed = {**AGENT, "name": "Billing desk", "former_names": ["support"]}
    api.get("/v1/agents").respond(json={**listing(renamed), "notes": ["'support' is now 'Billing desk': it was renamed, "
                                                                      "so use the new name."]})
    patch = api.patch("/v1/agents/ag_1").respond(json=renamed)
    create = api.post("/v1/agents").respond(json=AGENT)
    agent = nc.Agent.from_name("support", create_if_missing=True, instructions="hi")
    assert (agent.id, agent.name, agent.former_names) == ("ag_1", "Billing desk", ["support"])
    # Its name now is kept: from_name never renames it back, nor makes another under the old name.
    assert patch.call_count == 0 and create.call_count == 0


def test_browser_profile_and_card_converge_by_id(api, client):
    api.get("/v1/agents").respond(json=listing({**AGENT, "browser_profile_id": None, "card_id": "card_1"}))
    patch = api.patch("/v1/agents/ag_1").respond(json={**AGENT, "browser_profile_id": "bp_1", "card_id": "card_1"})
    agent = nc.Agent.from_name("support", create_if_missing=True, instructions="hi", browser_profile="bp_1", card="card_1")
    assert agent.browser_profile_id == "bp_1"
    assert body(patch.calls.last.request) == {"browser_profile_id": "bp_1"}


def test_update_signs_its_browser_in_with_a_profile_and_out(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/browser_profiles/bp_2").respond(json={"object": "browser_profile", "id": "bp_2", "name": "ana-work"})
    patch = api.patch("/v1/agents/ag_1").respond(json={**AGENT, "browser_profile_id": "bp_2"})
    agent = nc.Agent.from_id("ag_1")
    agent.update(browser_profile=nc.BrowserProfile.from_id("bp_2"))
    assert body(patch.calls.last.request) == {"browser_profile_id": "bp_2"} and agent.browser_profile_id == "bp_2"
    agent.update(browser_profile=None)
    assert body(patch.calls.last.request) == {"browser_profile_id": None}


def test_update_gives_a_card_and_takes_it_back(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    patch = api.patch("/v1/agents/ag_1").respond(json={**AGENT, "card_id": "card_1"})
    agent = nc.Agent.from_id("ag_1")
    agent.update(card="card_1")
    assert body(patch.calls.last.request) == {"card_id": "card_1"} and agent.card_id == "card_1"
    agent.update(card=None)
    assert body(patch.calls.last.request) == {"card_id": None}


# --- triggers, pause and resume ----------------------------------------------------------

def test_triggers_add_and_remove(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    listed = api.get("/v1/agents/ag_1/triggers").respond(json=listing(CRON, WEBHOOK, EMAIL))
    add = api.post("/v1/agents/ag_1/triggers").respond(json=WEBHOOK)
    delete = api.delete(path__regex=r"/v1/agents/ag_1/triggers/tr_\d").respond(204)

    agent = nc.Agent.from_id("ag_1")
    cron, webhook, email = agent.triggers()
    assert (cron.kind, cron.spec["tz"], cron.next_run.hour, cron.defined) == ("cron", "Europe/London", 7, True)
    assert (webhook.url, email.defined, email.spec["address"]) == ("https://hooks.noclick.app/t/wh_secret", False, "help@acme.test")

    added = agent.add_trigger(nc.OnWebhook(name="orders", message="A new order"))
    assert body(add.calls.last.request) == {"kind": "webhook", "name": "orders", "message": "A new order"}
    assert added.url == WEBHOOK["url"]

    agent.remove_trigger(cron)
    agent.remove_trigger("tr_2")
    assert [c.request.url.path for c in delete.calls] == ["/v1/agents/ag_1/triggers/tr_1", "/v1/agents/ag_1/triggers/tr_2"]
    # A definition is matched against what the agent has.
    agent.remove_trigger(nc.Cron("0 8 * * 1-5", tz="Europe/London", message="Old summary"))
    assert delete.calls.last.request.url.path == "/v1/agents/ag_1/triggers/tr_1"
    assert listed.call_count == 2
    with pytest.raises(nc.NotFound):
        agent.remove_trigger(nc.OnWebhook(name="refunds"))


def test_pause_and_resume(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    pause = api.post("/v1/agents/ag_1/pause").respond(json={**AGENT, "paused": True})
    resume = api.post("/v1/agents/ag_1/resume").respond(json={**AGENT, "paused": False})
    agent = nc.Agent.from_id("ag_1")
    assert agent.pause().paused is True
    assert agent.resume().paused is False
    assert pause.call_count == resume.call_count == 1


# --- memory ---------------------------------------------------------------------------

ENTRY = {"object": "memory_entry", "name": "refunds", "description": "Our refund rules",
         "content": "Refund within 30 days.", "version": 3, "updated_at": "2026-09-25T10:00:00Z",
         "updated_by": "agent", "user_id": None}


def test_memory_reads_and_writes_one_layer(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    checkpoint = {**ENTRY, "name": "context.3f9a0c1d2e4b5a6f", "content": None, "conversation": "desk"}
    reads = api.get("/v1/agents/ag_1/memory").respond(json=listing({**ENTRY, "content": None}, checkpoint))
    one = api.get("/v1/agents/ag_1/memory/refunds").respond(json=ENTRY)
    save = api.put("/v1/agents/ag_1/memory/refunds").respond(json={**ENTRY, "version": 4, "updated_by": "api"})
    forget = api.delete("/v1/agents/ag_1/memory/old%20pricing").respond(204)

    memory = nc.Agent.from_id("ag_1").memory
    listed, folded = memory.list()
    assert (listed.name, listed.content, listed.version, listed.conversation) == ("refunds", None, 3, None)
    assert folded.conversation == "desk"  # a conversation's checkpoint
    assert "NoClick-User" not in reads.calls.last.request.headers  # the account's layer

    memory.search("refund policy", limit=5, user="user_42")
    params = reads.calls.last.request.url.params
    assert (params["q"], params["limit"]) == ("refund policy", "5")
    assert reads.calls.last.request.headers["NoClick-User"] == "user_42"

    entry = memory.read("refunds")
    assert (entry.content, entry.updated_by, entry.updated_at.day) == ("Refund within 30 days.", "agent", 25)
    saved = memory.save("refunds", "Refund within 14 days.", version=entry.version)
    assert body(save.calls.last.request) == {"content": "Refund within 14 days.", "version": 3}
    assert (saved.version, saved.updated_by) == (4, "api")
    memory.save("refunds", "x", description="Our refund rules")
    assert body(save.calls.last.request) == {"content": "x", "description": "Our refund rules"}

    memory.delete("old pricing", version=2)
    assert forget.calls.last.request.url.params["version"] == "2"
    assert one.call_count == 1


def test_an_entry_lists_reads_and_restores_its_versions(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    version = {"object": "memory_entry_version", "name": "refunds", "version": 3, "current": True,
               "description": "Our refund rules", "content": None, "user_id": None, "saved_at": "2026-09-25T10:00:00Z",
               "written_by": {"type": "agent", "agent_id": "ag_1", "agent_name": "support", "conversation": "desk"}}
    listed = api.get("/v1/agents/ag_1/memory/refunds/versions").respond(json=listing(
        version, {**version, "version": 2, "current": False, "written_by": {"type": "api"}}))
    api.get("/v1/agents/ag_1/memory/refunds/versions/2").respond(json={
        **version, "version": 2, "current": False, "content": "Refund within 30 days."})
    restore = api.post("/v1/agents/ag_1/memory/refunds/versions/2/restore").respond(201, json={
        **ENTRY, "version": 4, "updated_by": "api"})

    memory = nc.Agent.from_id("ag_1").memory
    newest, older = memory.versions("refunds", user="user_42")
    assert (newest.version, newest.current, newest.content, newest.written_by.conversation) == (3, True, None, "desk")
    assert (older.version, older.current, older.written_by.type, newest.saved_at.day) == (2, False, "api", 25)
    assert listed.calls.last.request.headers["NoClick-User"] == "user_42"
    assert memory.get_version("refunds", 2).content == "Refund within 30 days."
    restored = memory.restore("refunds", 2)
    assert (restored.version, restored.content) == (4, "Refund within 30 days.")
    assert restore.call_count == 1


def test_a_user_agent_keeps_its_memory_with_its_user(api, client):
    api.get("/v1/agents/ag_2").respond(json={**AGENT, "id": "ag_2", "user_id": USER_ID})
    route = api.get("/v1/agents/ag_2/memory").respond(json=listing())
    nc.Agent.from_id("ag_2").memory.list(user="someone_else")
    assert route.calls.last.request.headers["NoClick-User"] == USER_ID


def test_a_changed_entry_is_a_conflict(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.put("/v1/agents/ag_1/memory/refunds").respond(409, json={"error": {
        "type": "conflict", "message": "refunds is at version 5.", "current_version": 5}})
    with pytest.raises(nc.Conflict) as exc:
        nc.Agent.from_id("ag_1").memory.save("refunds", "x", version=3)
    assert exc.value.details["current_version"] == 5


# --- workspace -----------------------------------------------------------------------

def test_workspace_lists_reads_writes_links_and_deletes_files(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    files = api.get("/v1/agents/ag_1/workspace").respond(json=listing(
        {"path": "report.csv", "size_bytes": 2048, "modified_at": "2026-09-25T10:00:00Z", "url": "https://files.test/r"}))
    read = api.get("/v1/agents/ag_1/workspace/files").respond(content=b"region,total\n")
    write = api.put("/v1/agents/ag_1/workspace/files").respond(json={"path": "notes.md", "size_bytes": 5})
    link = api.get("/v1/agents/ag_1/workspace/url").respond(json={"url": "https://files.test/n", "expires_at": "x"})
    removed = api.delete("/v1/agents/ag_1/workspace/files").respond(json={"path": "notes.md", "deleted": True})

    with nc.as_user("user_42"):
        workspace = nc.Agent.from_id("ag_1").workspace(conversation="ticket-1841")
    [report] = workspace.files()
    assert (report.path, report.size_bytes, report.url) == ("report.csv", 2048, "https://files.test/r")
    request = files.calls.last.request
    assert request.url.params["conversation"] == "ticket-1841"
    assert request.headers["NoClick-User"] == "user_42"  # captured where the workspace was made

    assert workspace.read("report.csv") == b"region,total\n"
    assert read.calls.last.request.url.params["path"] == "report.csv"
    written = workspace.write("notes.md", "hello")
    assert (write.calls.last.request.content, written.path) == (b"hello", "notes.md")
    assert write.calls.last.request.url.params["conversation"] == "ticket-1841"
    assert workspace.url("notes.md", expires_in_s=600) == "https://files.test/n"
    assert link.calls.last.request.url.params["expires_in_s"] == "600"
    assert workspace.delete("notes.md") is None
    assert removed.calls.last.request.url.params["path"] == "notes.md"
    assert removed.calls.last.request.headers["NoClick-User"] == "user_42"


# --- share link ------------------------------------------------------------------------

def test_share_disable_and_rotate(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    link_row = {"object": "share_link", "agent_id": "ag_1", "url": "https://noclick.com/a/lk_1", "enabled": True,
                "created_at": "2026-09-25T10:00:00Z", "rotated_at": None}
    share = api.post("/v1/agents/ag_1/share").respond(json=link_row)
    disable = api.patch("/v1/agents/ag_1/share").respond(json={**link_row, "enabled": False})
    rotate = api.post("/v1/agents/ag_1/share/rotate").respond(
        json={**link_row, "url": "https://noclick.com/a/lk_2", "rotated_at": "2026-09-26T10:00:00Z"})

    read = api.get("/v1/agents/ag_1/share").mock(side_effect=[
        httpx.Response(404, json={"error": {"type": "not_found", "message": "Never shared."}}),
        httpx.Response(200, json={**link_row, "enabled": False}),
    ])
    agent = nc.Agent.from_id("ag_1")
    assert agent.share_link() is None  # reading never turns it on
    assert agent.share_link().enabled is False and share.call_count == 0

    link = agent.share()
    assert (link.url, link.enabled, link.agent_id) == ("https://noclick.com/a/lk_1", True, "ag_1")
    assert link.disable().enabled is False
    assert body(disable.calls.last.request) == {"enabled": False}
    assert link.rotate().url == "https://noclick.com/a/lk_2" and link.rotated_at.day == 26
    assert share.call_count == rotate.call_count == 1 and read.call_count == 2


# --- streaming ---------------------------------------------------------------------------

SSE = (
    ": keep-alive\n\n"
    "event: text\ndata: {\"text\": \"Let me \"}\n\n"
    "event: tool_call\ndata: {\"tool\": \"stripe__list_refunds\", \"arguments\": {\"order\": \"1841\"}}\n\n"
    "event: tool_result\ndata: {\"tool\": \"stripe__list_refunds\", \"result\": [], \"is_error\": false}\n\n"
    "event: text\ndata: {\"text\": \"check.\"}\n\n"
    "event: done\ndata: {\"text\": \"Let me check.\", \"conversation\": \"ticket-1841\", "
    "\"tool_calls\": [{\"tool\": \"stripe__list_refunds\"}], \"operation_id\": \"op_9\"}\n\n"
)


def test_stream_yields_each_moment_then_the_reply(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    route = api.post("/v1/agents/ag_1/messages").respond(
        200, content=SSE.encode(), headers={"content-type": "text/event-stream"})
    events = list(nc.Agent.from_id("ag_1").stream("Where's my refund?", conversation="ticket-1841", user="user_42"))
    assert [e.type for e in events] == ["text", "tool_call", "tool_result", "text", "done"]
    assert events[1].tool == "stripe__list_refunds" and events[1].arguments == {"order": "1841"}
    assert events[2].result == [] and events[2].is_error is False
    done = events[-1]
    assert isinstance(done.reply, nc.AgentReply)
    assert (done.reply.text, done.reply.conversation, done.reply.operation_id) == ("Let me check.", "ticket-1841", "op_9")
    request = route.calls.last.request
    assert request.url.params["stream"] == "1"
    assert request.headers["Accept"] == "text/event-stream"
    assert request.headers["NoClick-User"] == "user_42"
    assert request.headers["Authorization"] == "Bearer nk_live_test"
    assert body(request) == {"text": "Where's my refund?", "conversation": "ticket-1841"}


def test_stream_aio_and_a_failed_turn(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    failing = ("event: text\ndata: {\"text\": \"Hm\"}\n\n"
               "event: error\ndata: {\"error\": {\"type\": \"spend_cap_exceeded\", \"message\": \"Over its budget.\"}}\n\n")
    api.post("/v1/agents/ag_1/messages").respond(200, content=failing.encode())

    async def collect():
        seen = []
        async for event in nc.Agent.from_id("ag_1").stream.aio("hi"):
            seen.append(event.text)
        return seen

    with pytest.raises(nc.SpendCapExceeded, match="Over its budget"):
        asyncio.run(collect())


def test_stream_refused_up_front_raises_its_error(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.post("/v1/agents/ag_1/messages").respond(409, json={"error": {"type": "conflict", "message": "Mid-turn."}})
    with pytest.raises(nc.Conflict, match="Mid-turn"):
        list(nc.Agent.from_id("ag_1").stream("hi", conversation="c"))


# --- rehearsals --------------------------------------------------------------------------

def test_rehearse_waits_for_a_rehearsal(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    result = {"reply": "I've refunded order 1841.", "scenario": "It arrived broken.", "cost_usd": 0.04,
              "tool_calls": [{"tool": "stripe__create_refund", "arguments": {"order": "1841"}, "result": {"id": "re_1"}}],
              "transcript": [{"role": "tool", "tool": "stripe__create_refund"}, {"role": "assistant", "text": "Done"}]}
    start = api.post("/v1/agents/ag_1/rehearsals").respond(json=operation("op_r", "agent.rehearse", "running"))
    api.get("/v1/operations/op_r/wait").respond(json=operation("op_r", "agent.rehearse", "succeeded", result=result))

    op = nc.Agent.from_id("ag_1").rehearse("Refund order 1841", scenario="It arrived broken.", user="user_42")
    assert body(start.calls.last.request) == {"message": "Refund order 1841", "scenario": "It arrived broken."}
    assert start.calls.last.request.headers["NoClick-User"] == "user_42"
    run = op.wait()
    assert isinstance(run, nc.Rehearsal)
    assert (run.reply, run.cost_usd, run.operation_id) == ("I've refunded order 1841.", 0.04, "op_r")
    assert run.tool_calls[0]["result"] == {"id": "re_1"} and len(run.transcript) == 2
    # Resumed anywhere, the kind still reads as a Rehearsal.
    assert isinstance(nc.Operation.from_id("op_r").wait(), nc.Rehearsal)


# --- hosted MCP servers -------------------------------------------------------------------

SERVER = {"object": "mcp_server", "id": "mcp_1", "name": "crm-tools", "url": "https://mcp.noclick.app/s/k3y",
          "tools": ["hubspot", "search"], "tool_count": 31, "user_id": USER_ID,
          "created_at": "2026-09-25T10:00:00Z", "last_client_at": None}


def test_mcp_server_create_list_and_manage(api, client):
    create = api.post("/v1/mcp_servers").respond(json=SERVER)
    listed = api.get("/v1/mcp_servers").respond(json=listing(SERVER))
    patch = api.patch("/v1/mcp_servers/mcp_1").respond(json={**SERVER, "tools": ["hubspot", "search", "fetch"]})
    rotate = api.post("/v1/mcp_servers/mcp_1/rotate").respond(json={**SERVER, "url": "https://mcp.noclick.app/s/n3w"})
    clients = api.get("/v1/mcp_servers/mcp_1/clients").respond(json=listing(
        {"name": "Claude", "version": "1.4.2", "first_seen_at": "2026-09-25T10:00:00Z",
         "last_seen_at": "2026-09-26T09:00:00Z", "tool_count": 31}))
    delete = api.delete("/v1/mcp_servers/mcp_1").respond(204)

    server = nc.McpServer.create("crm-tools", tools=["hubspot", "search"], user="acme")
    assert body(create.calls.last.request) == {"name": "crm-tools", "tools": ["hubspot", "search"]}
    assert create.calls.last.request.headers["NoClick-User"] == "acme"
    assert (server.url, server.tool_count, server.last_client_at) == ("https://mcp.noclick.app/s/k3y", 31, None)

    [row] = nc.McpServer.list(user_filter=nc.ALL_USERS)
    assert listed.calls.last.request.url.params["user_id"] == "all" and row == server
    server.update(tools=["hubspot", "search", "fetch"])
    assert body(patch.calls.last.request) == {"tools": ["hubspot", "search", "fetch"]}
    assert server.rotate().url == "https://mcp.noclick.app/s/n3w"
    [claude] = server.clients()
    assert (claude.name, claude.version, claude.tool_count, claude.last_seen_at.hour) == ("Claude", "1.4.2", 31, 9)
    server.delete()
    assert rotate.call_count == clients.call_count == delete.call_count == 1
    assert delete.calls.last.request.headers["NoClick-User"] == USER_ID


def test_mcp_server_from_name_creates_or_converges(api, client):
    listed = api.get("/v1/mcp_servers").respond(json=listing())
    create = api.post("/v1/mcp_servers").respond(json=SERVER)
    server = nc.McpServer.from_name("crm-tools", tools=["hubspot", "search"], create_if_missing=True)
    assert listed.call_count == 0  # lazy
    assert server.url == SERVER["url"]
    assert listed.calls.last.request.url.params["name"] == "crm-tools"
    assert create.call_count == 1

    api.get("/v1/mcp_servers").respond(json=listing(SERVER))
    patch = api.patch("/v1/mcp_servers/mcp_1").respond(json={**SERVER, "tools": ["hubspot"]})
    assert nc.McpServer.from_name("crm-tools", tools=["hubspot"], create_if_missing=True).tools == ["hubspot"]
    assert body(patch.calls.last.request) == {"tools": ["hubspot"]}
    with pytest.raises(ValueError):
        nc.McpServer.from_name("crm-tools", create_if_missing=True)
    api.get("/v1/mcp_servers").respond(json=listing())
    with pytest.raises(nc.NotFound):
        nc.McpServer.from_name("nope").hydrate()


# --- toolkits -----------------------------------------------------------------------------

def test_a_simulated_toolkit_is_one_world(api, client):
    calls = api.post("/v1/toolkits/call").mock(side_effect=lambda request: httpx.Response(200, json={
        "object": "tool_result", "name": body(request)["name"], "content": "two open invoices", "is_error": False,
        "simulated": True}))
    toolkit = nc.Toolkit(["stripe"], simulated=True, scenario="Ana has two unpaid invoices")
    toolkit.call("stripe__list_invoices", {"status": "open"})
    toolkit.call("stripe__create_refund", {"invoice": "in_1"})
    first, second = (body(c.request)["simulated"] for c in calls.calls)
    assert first == second and first["scenario"] == "Ana has two unpaid invoices" and first["world"].startswith("world_")
    assert body(calls.calls[0].request) == {"name": "stripe__list_invoices", "arguments": {"status": "open"}, "simulated": first}
    assert nc.Toolkit(["stripe"], simulated=True)._world != toolkit._world  # each toolkit its own world
    nc.Toolkit(["stripe"]).call("stripe__list_invoices")
    assert "simulated" not in body(calls.calls.last.request)
    with pytest.raises(ValueError):
        nc.Toolkit(["stripe"], scenario="no world")


def test_toolkit_mcp_server_serves_its_tools(api, client):
    api.get("/v1/connections/hubspot").respond(json={"object": "connection", "id": "cn_1", "name": "hubspot",
                                                     "integration": "hubspot", "status": "connected"})
    api.get("/v1/mcp_servers").respond(json=listing())
    create = api.post("/v1/mcp_servers").respond(json=SERVER)
    toolkit = nc.Toolkit([nc.Connection.from_name("hubspot", user="acme"), "search"], user="acme")
    server = toolkit.mcp_server("crm-tools")
    assert isinstance(server, nc.McpServer) and not server.is_hydrated
    server.hydrate()
    assert body(create.calls.last.request) == {"name": "crm-tools", "tools": ["hubspot", "search"]}
    assert create.calls.last.request.headers["NoClick-User"] == "acme"
    with pytest.raises(ValueError):
        nc.Toolkit(["hubspot"], simulated=True).mcp_server("x")


def _connection(connection_id, name, user_id):
    return {"object": "connection", "id": connection_id, "name": name, "integration": name, "status": "connected",
            "user_id": user_id}


def test_a_connection_from_another_scope_stays_that_connection(api, client):
    api.get("/v1/connections/slack").respond(json=_connection("cn_acme", "slack", "acme"))
    api.get("/v1/connections/gmail").respond(json=_connection("cn_ours", "gmail", None))
    api.get("/v1/connections/calendar").respond(json=_connection("cn_ana", "calendar", USER_ID))
    users = api.route(path__startswith="/v1/users").respond(json=user_row())
    create = api.post("/v1/agents").respond(json=agent_row(id="ag_2", name="assistant", user_id=USER_ID))

    acme_slack = nc.Connection.from_name("slack", user="acme")
    our_gmail = nc.Connection.from_name("gmail")   # the account's
    with nc.as_user("user_42"):
        calendar = nc.Connection.from_name("calendar")
        nc.Agent.create("assistant", instructions="hi",
                        tools=[acme_slack, our_gmail.only("send_email_message"), calendar, "search"])
    # Another user's and the account's go by id; Ana's own and plain names stay names.
    assert body(create.calls.last.request)["tools"] == [
        "connection:cn_acme", "connection:cn_ours.send_email_message", "calendar", "search",
    ]

    # One reached through a User object is still Ana's own for a toolkit acting as "user_42".
    ana = nc.Toolkit([acme_slack, nc.Connection.from_name("calendar", user=nc.User.from_id(USER_ID))], user="user_42")
    call = api.post("/v1/toolkits/call").respond(json={"name": "slack__send_message_to_channel", "content": "sent"})
    ana.call("slack__send_message_to_channel", {"channel": "#ops", "text": "hi"})
    assert body(call.calls.last.request)["tools"] == ["connection:cn_acme", "calendar"]
    assert users.call_count == 0  # your ids need no lookup

    # A toolkit of names alone sends none: each name resolves among the acting user's.
    nc.Toolkit(["slack"]).call("slack__send_message_to_channel", {"channel": "#ops"}, user="user_42")
    assert "tools" not in body(call.calls.last.request)

