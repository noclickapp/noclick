// People in a workspace: invites (links and emails), joining as yourself, the workspaces you see, a session in a
// joined one, roles, DMs between people, and who wrote a message to an agent.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, setup } from "./helpers.ts";

const WS = {
  object: "workspace", id: "ws_1", name: "Acme", logo_url: null, user_id: null, status: "active", role: "admin",
  people_count: 1, people_limit: 3, channel_count: 1, created_at: "2026-11-10T09:00:00Z",
  members: [
    {
      id: "wm_1", type: "user", agent_id: null, user_id: "login-ana", name: "Ana", role: "admin", person: true,
      email: "ana@people.test", last_seen_at: "2026-11-10T08:00:00Z", created_at: "2026-11-09T09:00:00Z",
      joined_at: "2026-11-09T09:00:00Z",
    },
  ],
};
const LINK = {
  object: "workspace_invite", id: "inv_1", workspace_id: "ws_1", type: "link", role: "member", email: null,
  url: "https://noclick.test/invite/nkinv_x", uses: 0, max_uses: 5, uses_left: 5, invited_by: "Olu", status: "active",
  expires_at: "2026-12-10T09:00:00Z", sent_at: null, created_at: "2026-11-10T09:00:00Z",
};
const MINE = {
  object: "my_workspace", id: "ws_1", name: "Acme", logo_url: null, own: false, role: "member", status: "active",
  account_name: "Olu Owner", user_id: "login-ana", member_id: "wm_1", joined_at: "2026-11-10T09:00:00Z",
};

test("a workspace's people: roles, the plan's limit and when each was last active", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workspaces/ws_1", json(WS));
  const ws = await nc.Workspace.get("ws_1");
  assert.deepEqual([ws.role, ws.peopleCount, ws.peopleLimit], ["admin", 1, 3]);
  const [ana] = ws.members;
  assert.deepEqual([ana.role, ana.person, ana.email, ana.lastSeenAt?.toISOString()],
    ["admin", true, "ana@people.test", "2026-11-10T08:00:00.000Z"]);
  const patch = api.on("PATCH", "/v1/workspaces/ws_1/members/wm_1", json({ ...WS.members[0], role: "guest" }));
  assert.equal((await ws.setRole(ana, "guest")).role, "guest");
  assert.deepEqual(patch.last.body, { role: "guest" });
  const add = api.on("POST", "/v1/workspaces/ws_1/members", json({ id: "wm_2", type: "user", user_id: "bo", role: "guest" }));
  await ws.add(nc.User.fromId("bo"), { role: "guest" });
  assert.deepEqual(add.last.body, { user_id: "bo", role: "guest" });
  await assert.rejects(ws.add(nc.Agent.fromId("ag_1"), { role: "admin" }), TypeError);
});

test("invites: a link, an email, the list, and turning one off, sending again or rotating", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workspaces/ws_1", json(WS));
  const ws = await nc.Workspace.get("ws_1");
  const made = api.on("POST", "/v1/workspaces/ws_1/invite_links", json(LINK, { status: 201 }));
  const link = await ws.inviteLink({ role: "member", maxUses: 5, expiresInDays: 14 });
  assert.deepEqual(made.last.body, { role: "member", max_uses: 5, expires_in_days: 14 });
  assert.deepEqual([link.type, link.url, link.usesLeft, link.status], ["link", LINK.url, 5, "active"]);
  const emailed = api.on("POST", "/v1/workspaces/ws_1/invites", json({ ...LINK, id: "inv_2", type: "email", email: "bo@x.test" }));
  await ws.invite("bo@x.test", { role: "guest" });
  assert.deepEqual(emailed.last.body, { email: "bo@x.test", role: "guest" });
  const listed = api.on("GET", "/v1/workspaces/ws_1/invites", json(listing([LINK])));
  assert.deepEqual((await ws.invites({ status: "active" })).map((i) => i.id), ["inv_1"]);
  assert.equal(listed.last.query.get("status"), "active");
  api.on("DELETE", "/v1/workspaces/ws_1/invites/inv_1", json({ ...LINK, status: "revoked", url: null }));
  assert.equal((await link.revoke()).status, "revoked");
  api.on("POST", "/v1/workspaces/ws_1/invites/inv_1/rotate", json({ ...LINK, id: "inv_3" }));
  assert.equal((await link.rotate()).id, "inv_3");
  const resent = api.on("POST", "/v1/workspaces/ws_1/invites/inv_2/resend", json({ ...LINK, id: "inv_2", type: "email" }));
  await new nc.WorkspaceInvite({ ...LINK, id: "inv_2", type: "email" }).resend();
  assert.equal(resent.calls.length, 1);
});

test("the signed-in person: what an invite is for, joining, their workspaces, a session in one, leaving", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/invites/nkinv_x", json({
    object: "invite_preview", workspace: { id: "ws_1", name: "Acme", logo_url: null }, account_name: "Olu Owner",
    invited_by: "Olu", role: "member", type: "link", email: null, status: "active", already_member: false,
    expires_at: "2026-12-10T09:00:00Z",
  }));
  const preview = await nc.Workspace.invitation("nkinv_x");
  assert.deepEqual([preview.workspace.name, preview.invitedBy, preview.alreadyMember], ["Acme", "Olu", false]);
  assert.equal(read.last.headers.get("NoClick-User"), null);
  api.on("POST", "/v1/invites/nkinv_x/accept", json(MINE));
  const joined = await nc.Workspace.acceptInvite("nkinv_x");
  assert.deepEqual([joined.own, joined.role, joined.accountName, joined.userId], [false, "member", "Olu Owner", "login-ana"]);
  api.on("GET", "/v1/me/workspaces", json(listing([{ ...MINE, id: "ws_0", own: true, role: "owner", user_id: null }, MINE])));
  assert.deepEqual((await nc.Workspace.mine()).map((w) => [w.id, w.role]), [["ws_0", "owner"], ["ws_1", "member"]]);
  const minted = api.on("POST", "/v1/me/workspaces/ws_1/sessions", json({
    object: "session", id: "s_1", token: "nk_sess_abc", user_id: "login-ana", scopes: ["agents", "channels"],
    expires_at: "2026-11-10T10:00:00Z", workspace_id: "ws_1",
  }, { status: 201 }));
  const session = await nc.Workspace.session(joined, { ttlS: 600 });
  assert.deepEqual(minted.last.body, { ttl_s: 600 });
  assert.deepEqual([session.token, session.userId], ["nk_sess_abc", "login-ana"]);
  assert.equal(session.client().apiKey, "nk_sess_abc");
  const left = api.on("DELETE", "/v1/me/workspaces/ws_1", json({ object: "my_workspace", id: "ws_1", deleted: true }));
  await nc.Workspace.leave("ws_1");
  assert.equal(left.calls.length, 1);
});

test("a DM opens with one other person, and a channel says its kind and newest message", async () => {
  const { api } = setup();
  const dm = {
    object: "channel", id: "ch_dm", name: "dm-1", kind: "dm", status: "open", mode: "mentions", members: [],
    user_id: null, workspace_id: "ws_1", unread_count: 1,
    last_message: { id: "m_1", text: "psst", author: { type: "user", id: "login-bo", name: "Bo" }, created_at: "2026-11-10T09:00:00Z" },
  };
  const open = api.on("POST", "/v1/channels", json(dm, { status: 201 }));
  const channel = await nc.Channel.dm("login-bo", { workspace: "ws_1" });
  assert.deepEqual(open.last.body, { kind: "dm", workspace_id: "ws_1", members: [{ user_id: "login-bo" }] });
  assert.deepEqual([channel.kind, channel.unreadCount, channel.lastMessage?.text, channel.lastMessage?.author.id],
    ["dm", 1, "psst", "login-bo"]);
  await nc.Channel.dm("account", { workspace: "ws_1" });
  assert.deepEqual(open.last.body.members, [{ account: true }]);
  const list = api.on("GET", "/v1/channels", json(listing([dm])));
  await nc.Channel.list({ workspace: "ws_1", kind: "dm" });
  assert.deepEqual([list.last.query.get("workspace_id"), list.last.query.get("kind")], ["ws_1", "dm"]);
});

test("a message to an agent names who sent it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json({ object: "agent", id: "ag_1", name: "support", workflow_id: "wf_1" }));
  api.on("GET", "/v1/agents/ag_1/conversations/c", json({
    object: "conversation", id: "c", agent_id: "ag_1", next_cursor: null,
    messages: [
      { role: "user", text: "help", created_at: "2026-11-10T09:00:00Z", author: { type: "user", id: "login-ana", name: "Ana" } },
      { role: "assistant", text: "on it", created_at: "2026-11-10T09:00:01Z" },
    ],
  }));
  const [asked, answered] = await nc.Agent.fromId("ag_1").history("c");
  assert.deepEqual(asked.author, { type: "user", id: "login-ana", name: "Ana" });
  assert.equal(answered.author, null);
});

test("a channel's turn keeps the posts it delivered beside the text its agent read", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json({ object: "agent", id: "ag_1", name: "scout", workflow_id: "wf_1" }));
  const delivered = {
    id: "ch_1", name: "launch", space: { id: "ws_1", name: "Bakery" }, thread: null,
    posts: [{ id: "m_1", author: { type: "user", id: "login-ana", name: "Ana" }, text: "@scout did it ship?",
              created_at: "2026-11-24T10:00:00Z", thread_id: null, files: [{ name: "log.txt", mime_type: "text/plain" }] }],
  };
  api.on("GET", "/v1/agents/ag_1/conversations/c", json({
    object: "conversation", id: "c", agent_id: "ag_1", next_cursor: null,
    messages: [
      { role: "user", text: "You are @scout in the channel…", created_at: "2026-11-24T10:00:01Z", chat: "channel:ch_1", channel: delivered },
      { role: "assistant", text: "Yes.", created_at: "2026-11-24T10:00:05Z" },
    ],
  }));
  const [asked, answered] = await nc.Agent.fromId("ag_1").history("c");
  assert.equal(asked.text, "You are @scout in the channel…");
  assert.deepEqual(asked.channel?.space, { id: "ws_1", name: "Bakery" });
  const [post] = asked.channel?.posts ?? [];
  assert.deepEqual([post.author.name, post.text, post.createdAt?.toISOString(), post.files],
    ["Ana", "@scout did it ship?", "2026-11-24T10:00:00.000Z", [{ name: "log.txt", mimeType: "text/plain" }]]);
  assert.equal(answered.channel, null);
});

test("a resource shared with a workspace, its levels, and the space's Resources tab", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workspaces/ws_1", json(WS));
  const ws = await nc.Workspace.get("ws_1");
  const SHARED = {
    object: "workspace_resource", id: "wr_1", workspace_id: "ws_1", kind: "database", ref: "db_1", name: "orders",
    members_level: "read", guests_level: "none", levels: ["none", "agents", "read", "write"], level: "write",
    added_at: "2026-11-10T09:00:00Z",
  };
  const made = api.on("POST", "/v1/workspaces/ws_1/resources", json(SHARED, { status: 201 }));
  const shared = await ws.share("database", "db_1", { membersLevel: "read" });
  assert.deepEqual(made.last.body, { kind: "database", ref: "db_1", members_level: "read" });
  assert.deepEqual([shared.kind, shared.name, shared.membersLevel, shared.levels.at(-1)], ["database", "orders", "read", "write"]);
  const listed = api.on("GET", "/v1/workspaces/ws_1/resources", json(listing([SHARED])));
  assert.deepEqual((await ws.resources({ kind: "database" })).map((r) => r.ref), ["db_1"]);
  assert.equal(listed.last.query.get("kind"), "database");
  const patched = api.on("PATCH", "/v1/workspaces/ws_1/resources/wr_1", json({ ...SHARED, members_level: "write" }));
  assert.equal((await shared.update({ membersLevel: "write" })).membersLevel, "write");
  assert.deepEqual(patched.last.body, { members_level: "write" });
  const removed = api.on("DELETE", "/v1/workspaces/ws_1/resources/wr_1", json({ id: "wr_1", deleted: true }));
  await shared.remove();
  assert.equal(removed.calls.length, 1);
  api.on("GET", "/v1/workspaces/ws_1/summary", json({
    object: "workspace_summary", workspace_id: "ws_1",
    kinds: { agents: { count: 1, working: 1, waiting: 0, idle: 0, items: [{ id: "ag_1" }] } },
  }));
  assert.equal((await ws.summary()).kinds.agents.working, 1);
});

test("the questions your NoClick asked a space, each with its answer once it came", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workspaces/ws_1/questions", json(listing([
    { object: "space_question", id: "op_2", workspace_id: "ws_1", question: "Who?", status: "waiting", answer: null,
      asked_at: "2026-11-11T10:05:00Z", answered_at: null },
    { object: "space_question", id: "op_1", workspace_id: "ws_1", question: "When is launch?", status: "answered",
      answer: "The 20th.", asked_at: "2026-11-11T10:00:00Z", answered_at: "2026-11-11T10:01:00Z" },
  ])));
  const asked = await nc.Workspace.questions("ws_1");
  assert.deepEqual(asked.map((q) => [q.question, q.status, q.answer]), [["Who?", "waiting", null], ["When is launch?", "answered", "The 20th."]]);
  assert.equal(asked[1].answeredAt?.toISOString(), "2026-11-11T10:01:00.000Z");
});
