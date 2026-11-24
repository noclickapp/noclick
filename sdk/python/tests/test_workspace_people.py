"""People in a workspace: invites (links and emails), joining as yourself, the workspaces you see, a session in a
joined one, roles, DMs between people, and who wrote a message to an agent."""

import pytest

import noclick as nc
from platform_helpers import body, listing

WORKSPACE = {
    "object": "workspace", "id": "ws_1", "name": "Acme", "logo_url": None, "user_id": None, "status": "active",
    "role": "admin", "people_count": 1, "people_limit": 3, "channel_count": 1, "created_at": "2026-11-10T09:00:00Z",
    "members": [{
        "id": "wm_1", "type": "user", "agent_id": None, "user_id": "login-ana", "name": "Ana", "role": "admin",
        "person": True, "email": "ana@people.test", "last_seen_at": "2026-11-10T08:00:00Z",
        "created_at": "2026-11-09T09:00:00Z",
    }],
}
LINK = {
    "object": "workspace_invite", "id": "inv_1", "workspace_id": "ws_1", "type": "link", "role": "member",
    "email": None, "url": "https://noclick.test/invite/nkinv_x", "uses": 0, "max_uses": 5, "uses_left": 5,
    "invited_by": "Olu", "status": "active", "expires_at": "2026-12-10T09:00:00Z", "sent_at": None,
    "created_at": "2026-11-10T09:00:00Z",
}
MINE = {
    "object": "my_workspace", "id": "ws_1", "name": "Acme", "logo_url": None, "own": False, "role": "member",
    "status": "active", "account_name": "Olu Owner", "user_id": "login-ana", "member_id": "wm_1",
    "joined_at": "2026-11-10T09:00:00Z",
}


def test_a_workspaces_people_their_roles_and_the_plans_limit(api, client):
    api.get("/v1/workspaces/ws_1").respond(json=WORKSPACE)
    ws = nc.Workspace.get("ws_1")
    assert (ws.role, ws.people_count, ws.people_limit) == ("admin", 1, 3)
    [ana] = ws.members
    assert (ana.role, ana.person, ana.email, ana.last_seen_at.hour) == ("admin", True, "ana@people.test", 8)
    patch = api.patch("/v1/workspaces/ws_1/members/wm_1").respond(json={**WORKSPACE["members"][0], "role": "guest"})
    assert ws.set_role(ana, "guest").role == "guest"
    assert body(patch.calls.last.request) == {"role": "guest"}
    add = api.post("/v1/workspaces/ws_1/members").respond(json={"id": "wm_2", "type": "user", "user_id": "bo"})
    ws.add(nc.User.from_id("bo"), role="guest")
    assert body(add.calls.last.request) == {"user_id": "bo", "role": "guest"}
    with pytest.raises(ValueError):
        ws.add(nc.Agent.from_id("ag_1"), role="admin")
    with pytest.raises(ValueError):
        ws.set_role(ana, "owner")


def test_invites_a_link_an_email_the_list_and_turning_one_off(api, client):
    api.get("/v1/workspaces/ws_1").respond(json=WORKSPACE)
    ws = nc.Workspace.get("ws_1")
    made = api.post("/v1/workspaces/ws_1/invite_links").respond(json=LINK)
    link = ws.invite_link(role="member", max_uses=5, expires_in_days=14)
    assert body(made.calls.last.request) == {"role": "member", "max_uses": 5, "expires_in_days": 14}
    assert (link.type, link.url, link.uses_left, link.status) == ("link", LINK["url"], 5, "active")
    emailed = api.post("/v1/workspaces/ws_1/invites").respond(json={**LINK, "id": "inv_2", "type": "email",
                                                                      "email": "bo@x.test"})
    ws.invite("bo@x.test", role="guest")
    assert body(emailed.calls.last.request) == {"email": "bo@x.test", "role": "guest"}
    listed = api.get("/v1/workspaces/ws_1/invites").respond(json=listing(LINK))
    assert [i.id for i in ws.invites(status="active")] == ["inv_1"]
    assert listed.calls.last.request.url.params["status"] == "active"
    api.delete("/v1/workspaces/ws_1/invites/inv_1").respond(json={**LINK, "status": "revoked", "url": None})
    assert link.revoke().status == "revoked"
    api.post("/v1/workspaces/ws_1/invites/inv_1/rotate").respond(json={**LINK, "id": "inv_3"})
    assert link.rotate().id == "inv_3"


def test_the_signed_in_person_reads_an_invite_joins_and_acts_in_the_space(api, client):
    read = api.get("/v1/invites/nkinv_x").respond(json={
        "object": "invite_preview", "workspace": {"id": "ws_1", "name": "Acme", "logo_url": None},
        "account_name": "Olu Owner", "invited_by": "Olu", "role": "member", "type": "link", "email": None,
        "status": "active", "already_member": False})
    assert nc.Workspace.invitation("nkinv_x")["workspace"]["name"] == "Acme"
    assert "NoClick-User" not in read.calls.last.request.headers
    api.post("/v1/invites/nkinv_x/accept").respond(json=MINE)
    joined = nc.Workspace.accept_invite("nkinv_x")
    assert (joined.own, joined.role, joined.account_name, joined.user_id) == (False, "member", "Olu Owner", "login-ana")
    api.get("/v1/me/workspaces").respond(json=listing({**MINE, "id": "ws_0", "own": True, "role": "owner"}, MINE))
    assert [(w.id, w.role) for w in nc.Workspace.mine()] == [("ws_0", "owner"), ("ws_1", "member")]
    minted = api.post("/v1/me/workspaces/ws_1/sessions").respond(json={
        "object": "session", "id": "s_1", "token": "nk_sess_abc", "user_id": "login-ana",
        "scopes": ["agents", "channels"], "expires_at": "2026-11-10T10:00:00Z", "workspace_id": "ws_1"})
    session = nc.Workspace.session(joined, ttl_s=600)
    assert body(minted.calls.last.request) == {"ttl_s": 600}
    assert (session.token, session.user_id) == ("nk_sess_abc", "login-ana")
    left = api.delete("/v1/me/workspaces/ws_1").respond(json={"object": "my_workspace", "id": "ws_1", "deleted": True})
    nc.Workspace.leave("ws_1")
    assert left.called


def test_a_dm_opens_with_one_other_person(api, client):
    dm = {"object": "channel", "id": "ch_dm", "name": "dm-1", "kind": "dm", "status": "open", "members": [],
          "workspace_id": "ws_1", "unread_count": 1,
          "last_message": {"id": "m_1", "text": "psst", "author": {"type": "user", "id": "login-bo", "name": "Bo"},
                           "created_at": "2026-11-10T09:00:00Z"}}
    opened = api.post("/v1/channels").respond(json=dm)
    room = nc.Channel.dm("login-bo", workspace="ws_1")
    assert body(opened.calls.last.request) == {"kind": "dm", "workspace_id": "ws_1",
                                               "members": [{"user_id": "login-bo"}]}
    assert (room.kind, room.unread_count, room.last_message["text"]) == ("dm", 1, "psst")
    nc.Channel.dm("account", workspace="ws_1")
    assert body(opened.calls.last.request)["members"] == [{"account": True}]
    listed = api.get("/v1/channels").respond(json=listing(dm))
    nc.Channel.list(workspace="ws_1", kind="dm")
    assert listed.calls.last.request.url.params["kind"] == "dm"
    with pytest.raises(ValueError):
        nc.Channel.list(kind="thread")


def test_a_message_to_an_agent_names_who_sent_it(api, client):
    api.get("/v1/agents/ag_1").respond(json={"object": "agent", "id": "ag_1", "name": "support"})
    api.get("/v1/agents/ag_1/conversations/c").respond(json={
        "object": "conversation", "id": "c", "agent_id": "ag_1", "next_cursor": None,
        "messages": [
            {"role": "user", "text": "help", "created_at": "2026-11-10T09:00:00Z",
             "author": {"type": "user", "id": "login-ana", "name": "Ana"}},
            {"role": "assistant", "text": "on it", "created_at": "2026-11-10T09:00:01Z"},
        ]})
    asked, answered = nc.Agent.from_id("ag_1").history("c")
    assert asked.author == {"type": "user", "id": "login-ana", "name": "Ana"} and answered.author is None


def test_a_channel_turn_keeps_the_posts_it_delivered_beside_the_text_its_agent_read(api, client):
    api.get("/v1/agents/ag_1").respond(json={"object": "agent", "id": "ag_1", "name": "scout"})
    delivered = {"id": "ch_1", "name": "launch", "space": {"id": "ws_1", "name": "Bakery"}, "thread": None,
                 "posts": [{"id": "m_1", "author": {"type": "user", "id": "login-ana", "name": "Ana"},
                            "text": "@scout did it ship?", "created_at": "2026-11-24T10:00:00Z", "thread_id": None,
                            "files": []}]}
    api.get("/v1/agents/ag_1/conversations/c").respond(json={
        "object": "conversation", "id": "c", "agent_id": "ag_1", "next_cursor": None,
        "messages": [
            {"role": "user", "text": "You are @scout in the channel…", "created_at": "2026-11-24T10:00:01Z",
             "chat": "channel:ch_1", "channel": delivered},
            {"role": "assistant", "text": "Yes.", "created_at": "2026-11-24T10:00:05Z"},
        ]})
    asked, answered = nc.Agent.from_id("ag_1").history("c")
    assert asked.channel == delivered and asked.text.startswith("You are @scout")
    assert answered.channel is None


SHARED = {"object": "workspace_resource", "id": "wr_1", "workspace_id": "ws_1", "kind": "database", "ref": "db_1",
          "name": "orders", "members_level": "read", "guests_level": "none",
          "levels": ["none", "agents", "read", "write"], "level": "write", "added_at": "2026-11-10T09:00:00Z"}


def test_a_resource_shared_with_a_workspace_and_its_resources_tab(api, client):
    api.get("/v1/workspaces/ws_1").respond(json=WORKSPACE)
    ws = nc.Workspace.get("ws_1")
    made = api.post("/v1/workspaces/ws_1/resources").respond(json=SHARED)
    shared = ws.share("database", "db_1", members_level="read")
    assert body(made.calls.last.request) == {"kind": "database", "ref": "db_1", "members_level": "read"}
    assert (shared.kind, shared.name, shared.members_level, shared.levels[-1]) == ("database", "orders", "read",
                                                                                   "write")
    with pytest.raises(ValueError):
        ws.share("spaceship", "x")
    listed = api.get("/v1/workspaces/ws_1/resources").respond(json=listing(SHARED))
    assert [r.ref for r in ws.resources(kind="database")] == ["db_1"]
    assert listed.calls.last.request.url.params["kind"] == "database"
    patched = api.patch("/v1/workspaces/ws_1/resources/wr_1").respond(json={**SHARED, "members_level": "write"})
    assert shared.update(members_level="write").members_level == "write"
    assert body(patched.calls.last.request) == {"members_level": "write"}
    removed = api.delete("/v1/workspaces/ws_1/resources/wr_1").respond(json={"id": "wr_1", "deleted": True})
    shared.remove()
    assert removed.called
    api.get("/v1/workspaces/ws_1/summary").respond(json={
        "object": "workspace_summary", "workspace_id": "ws_1",
        "kinds": {"agents": {"count": 1, "working": 1, "waiting": 0, "idle": 0, "items": [{"id": "ag_1"}]}}})
    assert ws.summary()["kinds"]["agents"]["working"] == 1


def test_the_questions_your_noclick_asked_a_space_each_with_its_answer(api, client):
    route = api.get("/v1/workspaces/ws_1/questions").respond(json=listing(
        {"object": "space_question", "id": "op_2", "workspace_id": "ws_1", "question": "Who?", "status": "waiting",
         "answer": None, "asked_at": "2026-11-11T10:05:00Z", "answered_at": None},
        {"object": "space_question", "id": "op_1", "workspace_id": "ws_1", "question": "When is launch?",
         "status": "answered", "answer": "The 20th.", "asked_at": "2026-11-11T10:00:00Z",
         "answered_at": "2026-11-11T10:01:00Z"},
    ))
    asked = nc.Workspace.questions("ws_1")
    assert [(q.question, q.status, q.answer) for q in asked] == [
        ("Who?", "waiting", None), ("When is launch?", "answered", "The 20th.")]
    assert asked[1].answered_at.minute == 1 and asked[0].answered_at is None
    assert "noclick-user" not in route.calls.last.request.headers
