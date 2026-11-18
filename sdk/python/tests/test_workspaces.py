"""Workspaces: a workspace's members, its channels (several users, each posting as
themselves), its subscriptions into several channels, archive and delete."""

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing

CHANNEL = {"object": "channel", "id": "ch_1", "name": "billing", "mode": "mentions", "status": "open", "members": []}
WORKSPACE = {
    "object": "workspace", "id": "ws_1", "name": "Acme", "logo_url": None, "user_id": None, "status": "active",
    "budget_usd_per_month": 200, "spent_usd": 12.5, "channel_count": 2, "created_at": "2026-10-01T10:00:00Z",
    "members": [
        {"id": "wm_1", "type": "agent", "agent_id": "ag_1", "user_id": None, "name": "planner"},
        {"id": "wm_2", "type": "user", "agent_id": None, "user_id": "ana", "name": "Ana"},
    ],
}


def subscription(**extra):
    return {"object": "subscription", "id": "sub_1", "channel_id": None, "workspace_id": "ws_1", "channels": "all",
            "source": {"kind": "webhook", "name": "deploys"}, "wake": None, "filters": None,
            "status": "active", "error": None, "url": "https://wh.test/x", "last_event_at": None,
            "created_at": "2026-10-01T10:00:00Z", **extra}


# --- workspace channels ----------------------------------------------------------------------

def test_a_channel_in_a_workspace_holds_several_users(api, client):
    api.get("/v1/workspaces/ws_1").respond(json=WORKSPACE)
    create = api.post("/v1/channels").respond(json={**CHANNEL, "workspace_id": "ws_1"})
    ws = nc.Workspace.get("ws_1")
    room = nc.Channel.create("billing", workspace=ws, members=[nc.Agent.from_id("ag_1"), nc.User.from_id("ana"),
                                                               nc.User.from_id("bo")])
    assert body(create.calls.last.request) == {
        "name": "billing", "members": [{"agent_id": "ag_1"}, {"user_id": "ana"}, {"user_id": "bo"}],
        "workspace_id": "ws_1",
    }
    # The workspace is the account's, so the channel is too: no user header.
    assert "NoClick-User" not in create.calls.last.request.headers
    assert room.workspace_id == "ws_1"


def test_workspace_channel_members_and_posts_name_the_user(api, client):
    api.get("/v1/channels/ch_1").respond(json={**CHANNEL, "workspace_id": "ws_1"})
    add = api.post("/v1/channels/ch_1/members").respond(json={"id": "mem_9", "type": "user", "user_id": "carla"})
    post = api.post("/v1/channels/ch_1/messages").respond(json={"id": "msg_1", "text": "hi", "author": {}})
    room = nc.Channel.from_id("ch_1")
    room.add(nc.User.from_id("carla"))
    assert body(add.calls.last.request) == {"user_id": "carla"}
    room.post("@planner where are we?", as_=nc.User.from_id("carla"))
    assert body(post.calls.last.request) == {"text": "@planner where are we?", "as": {"user_id": "carla"}}


def test_a_workspace_object_carries_its_scope_so_user_is_refused(api, client):
    api.get("/v1/workspaces/ws_1").respond(json=WORKSPACE)
    ws = nc.Workspace.get("ws_1")
    with pytest.raises(TypeError, match="lives where the workspace does"):
        nc.Channel.create("billing", workspace=ws, user="user_42")
    with pytest.raises(TypeError, match="lives where the workspace does"):
        nc.Channel.from_name("billing", workspace=ws, user="user_42")
    # By id, user= still says where the workspace is.
    create = api.post("/v1/channels").respond(json={**CHANNEL, "workspace_id": "ws_1"})
    nc.Channel.create("billing", workspace="ws_1", user="user_42")
    assert create.calls.last.request.headers["NoClick-User"] == "user_42"


def test_a_channel_outside_a_workspace_keeps_its_one_user(api, client):
    api.get("/v1/channels/ch_2").respond(json={**CHANNEL, "id": "ch_2"})
    add = api.post("/v1/channels/ch_2/members").respond(json={"id": "mem_9", "type": "user"})
    nc.Channel.from_id("ch_2").add(nc.User.from_id(USER_ID))
    assert body(add.calls.last.request) == {"user": True}


def test_channel_list_and_from_name_look_in_a_workspace(api, client):
    rows = api.get("/v1/channels").mock(side_effect=[
        httpx.Response(200, json=listing({**CHANNEL, "workspace_id": "ws_1"})),
        httpx.Response(200, json=listing({**CHANNEL, "workspace_id": None})),  # same name, outside the workspace
    ])
    create = api.post("/v1/channels").respond(json={**CHANNEL, "id": "ch_3", "workspace_id": "ws_1"})
    nc.Channel.list(workspace="ws_1", status="open")
    assert rows.calls.last.request.url.params["workspace_id"] == "ws_1"
    room = nc.Channel.from_name("billing", workspace="ws_1", create_if_missing=True,
                                members=[nc.Agent.from_id("ag_1"), nc.User.from_id("ana")])
    assert room.id == "ch_3"  # the one outside the workspace isn't it
    assert rows.calls.last.request.url.params["workspace_id"] == "ws_1"
    assert body(create.calls.last.request) == {
        "name": "billing", "workspace_id": "ws_1", "members": [{"agent_id": "ag_1"}, {"user_id": "ana"}],
    }


def test_from_name_in_a_workspace_converges_its_users_too(api, client):
    api.get("/v1/channels").respond(json=listing({**CHANNEL, "workspace_id": "ws_1", "members": [
        {"id": "mem_1", "type": "agent", "agent_id": "ag_1"},
        {"id": "mem_2", "type": "user", "user_id": "bo"},
    ]}))
    removed = api.delete("/v1/channels/ch_1/members/mem_2").respond(204)
    added = api.post("/v1/channels/ch_1/members").respond(json={"id": "mem_3", "type": "user", "user_id": "ana"})
    api.get("/v1/channels/ch_1").respond(json={**CHANNEL, "workspace_id": "ws_1"})
    nc.Channel.from_name("billing", workspace="ws_1", create_if_missing=True,
                         members=[nc.Agent.from_id("ag_1"), nc.User.from_id("ana")]).hydrate()
    assert removed.called
    assert body(added.calls.last.request) == {"user_id": "ana"}


# --- workspaces -----------------------------------------------------------------------------

def test_workspace_create_in_a_scope(api, client):
    create = api.post("/v1/workspaces").respond(json={**WORKSPACE, "user_id": USER_ID})
    with nc.as_user(USER_ID):
        ws = nc.Workspace.create("Home", members=[nc.Agent.from_id("ag_u")], budget_usd_per_month=20,
                                 logo_url="https://cdn.test/home.png")
    assert body(create.calls.last.request) == {
        "name": "Home", "members": [{"agent_id": "ag_u"}], "budget_usd_per_month": 20, "logo_url": "https://cdn.test/home.png",
    }
    assert create.calls.last.request.headers["NoClick-User"] == USER_ID
    assert [(m.type, m.agent_id, m.user_id) for m in ws.members] == [("agent", "ag_1", None), ("user", None, "ana")]
    assert isinstance(ws.members[0], nc.WorkspaceMember) and ws.spent_usd == 12.5
    with pytest.raises(TypeError, match="Agent or a noclick.User"):
        nc.Workspace.create("Bad", members=["ag_1"])


def test_workspace_from_name_creates_then_converges(api, client):
    lookup = api.get("/v1/workspaces").mock(side_effect=[
        httpx.Response(200, json=listing()),
        httpx.Response(200, json=listing(WORKSPACE)),
    ])
    create = api.post("/v1/workspaces").respond(json=WORKSPACE)
    patch = api.patch("/v1/workspaces/ws_1").respond(json={**WORKSPACE, "logo_url": None, "budget_usd_per_month": 300})
    removed = api.delete("/v1/workspaces/ws_1/members/wm_2").respond(204)
    added = api.post("/v1/workspaces/ws_1/members").respond(json={"id": "wm_3", "type": "user", "user_id": "bo"})
    api.get("/v1/workspaces/ws_1").respond(json=WORKSPACE)
    members = [nc.Agent.from_id("ag_1"), nc.User.from_id("ana")]
    nc.Workspace.from_name("Acme", create_if_missing=True, members=members, budget_usd_per_month=200).hydrate()
    assert lookup.calls[0].request.url.params["status"] == "active"
    assert body(create.calls.last.request) == {
        "name": "Acme", "budget_usd_per_month": 200, "members": [{"agent_id": "ag_1"}, {"user_id": "ana"}],
    }
    nc.Workspace.from_name("Acme", create_if_missing=True, members=[nc.Agent.from_id("ag_1"), nc.User.from_id("bo")],
                           budget_usd_per_month=300, logo_url=None).hydrate()
    assert body(patch.calls.last.request) == {"budget_usd_per_month": 300}  # the logo is already none
    assert removed.called and body(added.calls.last.request) == {"user_id": "bo"}


def test_workspace_from_name_without_create_is_a_lookup(api, client):
    api.get("/v1/workspaces").respond(json=listing({**WORKSPACE, "name": "Acme Labs"}))
    with pytest.raises(nc.NotFound):
        nc.Workspace.from_name("Acme").hydrate()


def test_workspace_list_update_archive_delete(api, client):
    rows = api.get("/v1/workspaces").respond(json=listing(WORKSPACE))
    patch = api.patch("/v1/workspaces/ws_1").respond(json={**WORKSPACE, "budget_usd_per_month": None})
    archive = api.post("/v1/workspaces/ws_1/archive").respond(json={**WORKSPACE, "status": "archived"})
    trash = {"object": "trash_item", "id": "tr_1", "kind": "workspace", "resource_id": "ws_1", "name": "Acme",
             "user_id": None, "trashed_at": "2026-11-11T10:00:00Z", "purge_after": "2026-12-11T10:00:00Z"}
    delete = api.delete("/v1/workspaces/ws_1").respond(json={"object": "workspace", "id": "ws_1", "deleted": True,
                                                             "trash": trash, "operation_id": "op_1"})
    unarchive = api.post("/v1/workspaces/ws_1/unarchive").respond(json={**WORKSPACE, "status": "active"})
    [ws] = nc.Workspace.list(status="active", user_filter=nc.ALL_USERS)
    assert rows.calls.last.request.url.params["user_id"] == "all"
    assert ws.update(budget_usd_per_month=None, name="Acme Inc").budget_usd_per_month is None
    assert body(patch.calls.last.request) == {"name": "Acme Inc", "budget_usd_per_month": None}
    assert ws.archive().status == "archived" and archive.called
    assert ws.unarchive().status == "active" and unarchive.called
    item = ws.delete()
    assert delete.called and item.id == "tr_1" and item.kind == "workspace"
    page = nc.Workspace.list_page(limit=5)
    assert page.data[0].name == "Acme"
    nc.Workspace.list(agent=nc.Agent.from_id("ag_1"))
    assert rows.calls.last.request.url.params["agent_id"] == "ag_1"
    rooms = api.get("/v1/channels").respond(json=listing())
    nc.Channel.list(agent="ag_1")
    assert rooms.calls.last.request.url.params["agent_id"] == "ag_1"
    with pytest.raises(ValueError, match="status"):
        nc.Workspace.list(status="closed")


def test_workspace_channels_and_members(api, client):
    api.get("/v1/workspaces/ws_1").respond(json=WORKSPACE)
    rows = api.get("/v1/channels").respond(json=listing({**CHANNEL, "workspace_id": "ws_1"}))
    add = api.post("/v1/workspaces/ws_1/members").respond(json={"id": "wm_3", "type": "agent", "agent_id": "ag_9"})
    drop = api.delete("/v1/workspaces/ws_1/members/wm_2").respond(204)
    ws = nc.Workspace.from_id("ws_1")
    [room] = ws.channels(status="open")
    assert rows.calls.last.request.url.params["workspace_id"] == "ws_1" and room.name == "billing"
    member = ws.add(nc.Agent.from_id("ag_9"))
    assert body(add.calls.last.request) == {"agent_id": "ag_9"} and member.id == "wm_3"
    ws.remove(nc.User.from_id("ana"))
    assert drop.called
    with pytest.raises(ValueError, match="not a member"):
        ws.remove(nc.User.from_id("zed"))


def test_workspace_subscriptions_post_in_several_channels(api, client):
    api.get("/v1/workspaces/ws_1").respond(json=WORKSPACE)
    sub = api.post("/v1/workspaces/ws_1/subscriptions").respond(json=subscription(
        id="sub_w", channel_id=None, workspace_id="ws_1", channels="all"))
    api.get("/v1/workspaces/ws_1/subscriptions").respond(json=listing(subscription(
        id="sub_w", channel_id=None, workspace_id="ws_1", channels=["ch_1", "ch_2"])))
    gone = api.delete("/v1/workspaces/ws_1/subscriptions/sub_w").respond(204)
    ws = nc.Workspace.from_id("ws_1")
    made = ws.subscribe(nc.OnWebhook(name="deploys"), channels="all", filters={"status": "failed"})
    assert body(sub.calls.last.request) == {
        "source": {"kind": "webhook", "name": "deploys"}, "wake": None, "filters": {"status": "failed"},
        "channels": "all",
    }
    assert (made.channels, made.workspace_id, made.channel_id) == ("all", "ws_1", None)
    ws.subscribe(nc.OnEvent("stripe", "invoice_payment_failed"), channels=[nc.Channel.from_id("ch_1"), "ch_2"],
                 wake=[nc.Agent.from_id("ag_1")])
    sent = body(sub.calls.last.request)
    assert (sent["channels"], sent["wake"], sent["source"]["event"]) == (["ch_1", "ch_2"], ["ag_1"],
                                                                         "invoice_payment_failed")
    with pytest.raises(TypeError, match="channels="):
        ws.subscribe(nc.OnWebhook(name="deploys"), channels="billing")
    [listed] = ws.subscriptions()
    assert listed.channels == ["ch_1", "ch_2"]
    # A workspace's subscription reloads and stops under its workspace.
    api.get("/v1/workspaces/ws_1/subscriptions/sub_w").respond(json=subscription(id="sub_w", status="error",
                                                                                 error="The workspace is archived."))
    assert listed.refresh().status == "error"
    listed.unsubscribe()
    assert gone.called


def test_an_agents_files_are_its_agent_workspace(api, client):
    files = nc.Agent.from_id("ag_1").workspace()
    assert isinstance(files, nc.AgentWorkspace) and not isinstance(files, nc.Workspace)
    assert repr(files) == "AgentWorkspace(conversation=None)"
    api.get("/v1/agents/ag_1").respond(json=agent_row(id="ag_1"))
    listed = api.get("/v1/agents/ag_1/workspace").respond(json={"object": "list", "data": [], "next_cursor": None})
    assert files.files() == [] and "conversation" not in listed.calls.last.request.url.params
    # An old caller's conversation still goes; the server ignores it.
    nc.Agent.from_id("ag_1").workspace("ticket-1841").files()
    assert listed.calls.last.request.url.params["conversation"] == "ticket-1841"


def test_what_was_said_across_a_workspaces_channels_since_a_time(api, client):
    """One read for a catch-up: every channel's timeline since a time, oldest first, each message naming its
    channel; paged on from the last message."""
    from datetime import datetime, timezone

    said = {"object": "channel_message", "id": "m_2", "channel_id": "ch_2", "channel_name": "front-of-house",
            "author": {"type": "account", "id": None, "name": "Olu"}, "text": "Oven repair on Thursday.",
            "mentions": [], "created_at": "2026-11-10T09:00:00Z", "reply_count": 0}
    read = api.get("/v1/workspaces/ws_1/messages").respond(json={**listing(said), "next_cursor": "m_2"})
    ws = nc.Workspace.from_id("ws_1")
    since = datetime(2026, 11, 10, tzinfo=timezone.utc)
    [message] = ws.messages(since=since, limit=30)
    assert (message.channel_name, message.channel_id, message.text, message.author.name) == (
        "front-of-house", "ch_2", "Oven repair on Thursday.", "Olu")
    assert dict(read.calls.last.request.url.params) == {"since": "2026-11-10T00:00:00+00:00", "limit": "30"}
    ws.messages(after=message)
    assert dict(read.calls.last.request.url.params) == {"cursor": "m_2"}
    # A channel's own read names no channel.
    assert nc.ChannelMessage._from({"id": "m_1", "text": "hi"}).channel_name is None
