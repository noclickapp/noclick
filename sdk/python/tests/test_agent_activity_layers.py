"""What the agent pages read beyond a conversation's messages: its activity, a thread or memory layer read as the account
naming whose (``user_filter``), a conversation read by the agent's ref without loading it, a WhatsApp chat's profiles,
an integration's events by name, one human request, a space's NoClick, the personal space and one session's edits."""

import noclick as nc
from platform_helpers import body, listing

AGENT = {"object": "agent", "id": "ag_1", "name": "support", "user_id": None}
ITEM = {
    "chat": {"key": "wa-1", "name": "Ana", "kind": "direct", "number": "+14155550101", "avatar": None,
             "node_type": "automation-whatsapp"},
    "inbound": {"sender_name": "Ana", "text": "Is it open?", "media": {"kind": "voice", "transcript": "Is it open?"},
                "at": "2026-11-25T10:00:00Z", "message_id": "m1"},
    "also_inbound": [{"text": "Today?", "at": "2026-11-25T10:00:05Z"}],
    "did": [{"kind": "reply", "text": "Yes, till 6.", "tool": "whatsapp__send_message", "edited": True}],
    "turn": {"id": "op_t", "conversation_id": "wa-1", "status": "done", "started_at": "2026-11-25T10:00:01Z",
             "worked_s": 8, "started_by": {"kind": "on_event", "id": "tr_1"}, "steps": []},
}


def test_activity_is_typed_and_a_thread_read_as_the_account_names_whose_with_its_session(api):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    activity = api.get("/v1/agents/ag_1/conversations/wa-1/activity").respond(json=listing(ITEM))
    thread = api.get("/v1/agents/ag_1/conversations/chat-1").respond(
        json={"messages": [], "next_cursor": None, "session": "s_7"})
    agent = nc.Agent.from_id("ag_1")
    [item] = agent.activity("wa-1", limit=20)
    assert activity.calls.last.request.url.params["limit"] == "20"
    assert (item.chat.node_type, item.inbound.text, item.also_inbound[0].text, item.did[0].edited,
            item.turn.worked_s) == ("automation-whatsapp", "Is it open?", "Today?", True, 8)
    page = agent.history_page("chat-1", limit=1, user_filter=nc.NO_USER)
    assert page.session == "s_7"
    request = thread.calls.last.request
    assert request.url.params["user_id"] == "none" and "noclick-user" not in request.headers


def test_an_agent_named_by_its_ref_reads_its_conversations_without_loading_it(api):
    loaded = api.get("/v1/agents/agent%3Acoordinator").respond(json=AGENT)
    api.get("/v1/agents/agent%3Acoordinator/conversations").respond(
        json=listing({"conversation": "s_1", "active": True}))
    api.get("/v1/agents/agent%3Acoordinator/conversations/s_1").respond(json={"messages": [{"role": "user", "text": "hi"}]})
    agent = nc.Agent.from_id("agent:coordinator", user=None)
    assert agent.conversations_page(user=None).data[0].conversation == "s_1"
    assert [m.text for m in agent.history("s_1", user=None)] == ["hi"]
    assert loaded.call_count == 0


def test_a_memory_layer_is_read_and_written_as_the_account_naming_whose(api):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    listed = api.get("/v1/agents/ag_1/memory").respond(json=listing({"name": "refunds", "description": "d", "version": 2}))
    saved = api.put("/v1/agents/ag_1/memory/refunds").respond(
        json={"name": "refunds", "description": "d", "version": 3, "content": "30 days"})
    agent = nc.Agent.from_id("ag_1")
    assert agent.memory.list(user_filter="user_42")[0].name == "refunds"
    assert listed.calls.last.request.url.params["user_id"] == "user_42"
    assert "noclick-user" not in listed.calls.last.request.headers
    agent.memory.save("refunds", "30 days", version=2, user_filter=nc.NO_USER)
    assert saved.calls.last.request.url.params["user_id"] == "none"
    assert body(saved.calls.last.request) == {"content": "30 days", "version": 2}


def test_a_whatsapp_chats_profiles_and_an_integrations_events_by_name(api):
    profiles = api.get("/v1/connections/conn_1/chat_profiles").respond(
        json=listing({"jid": "1@c.us", "name": None, "avatar_url": "https://x.test/a.jpg"}))
    api.get("/v1/integrations/slack/events").respond(
        json=listing({"name": "channel_message", "description": "d", "filters": {"channel": "Required."}}))
    [chat] = nc.Connection.from_id("conn_1").chat_profiles(["1@c.us", "2@g.us"])
    assert (chat.jid, chat.avatar_url) == ("1@c.us", "https://x.test/a.jpg")
    assert profiles.calls.last.request.url.params.get_list("jid") == ["1@c.us", "2@g.us"]
    [event] = nc.Connection.integration_events("slack")
    assert (event.name, event.filters) == ("channel_message", {"channel": "Required."})


def test_a_human_request_is_retrieved_by_its_id_and_answered_through_it(api):
    view = {"id": "hr_1", "operation_id": "op_h", "kind": "approve", "status": "pending", "message": "Refund $40?"}
    api.get("/v1/humans/requests/hr_1").respond(json=view)
    answered = api.post("/v1/humans/requests/hr_1/answer").respond(json={**view, "status": "answered"})
    request = nc.HumanRequest.retrieve("hr_1", user=None)
    assert (request.request_id, request.request_status) == ("hr_1", "pending")
    request.approve(note="Go ahead")
    assert body(answered.calls.last.request) == {"approved": True, "note": "Go ahead"}
    assert request.request_status == "answered"


def test_a_spaces_noclick_the_personal_space_and_one_sessions_edits(api):
    api.get("/v1/workspaces/ws_1/noclick").respond(json={
        "object": "workspace_noclick", "workspace_id": "ws_1", "agent_id": "ag_9", "name": "noclick-ws1",
        "label": "NoClick · Support"})
    api.post("/v1/me/personal_space").respond(json={"id": "ws_p", "name": "Ana", "role": "owner", "own": True,
                                                    "personal": True})
    api.get("/v1/projects").respond(json=listing({"object": "project", "id": "prj_1", "name": "larkspur"}))
    edits = api.get("/v1/projects/prj_1/live/edits").respond(json={
        "object": "list", "data": [{"seq": 4, "files": ["a.js"], "outcome": "hot"}], "last_seq": 4})
    assert nc.Workspace.from_id("ws_1").noclick_agent().agent_id == "ag_9"
    assert nc.Workspace.personal_space().id == "ws_p"
    read = nc.Project.from_name("larkspur").live.edits(session_id="ls_2", after=3)
    params = edits.calls.last.request.url.params
    assert (read.last_seq, params["session_id"], params["after"]) == (4, "ls_2", "3")
