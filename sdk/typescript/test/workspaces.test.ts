// Workspaces: a workspace's members, its channels (several users, each posting as themselves),
// its subscriptions into several channels, archive and delete.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, listing, setup } from "./helpers.ts";

function noContent(): Response {
  return new Response(null, { status: 204 });
}

const CHANNEL = { object: "channel", id: "ch_1", name: "billing", status: "open", mode: "mentions", members: [], user_id: null, workspace_id: null };
const SUB = {
  object: "subscription", id: "sub_1", channel_id: null, workspace_id: "ws_1", channels: "all",
  source: { kind: "webhook", name: "deploys" }, wake: null, filters: {},
  status: "active", error: null, url: "https://wh.test/x", last_event_at: null, created_at: "2026-10-01T09:00:00Z",
};

// --- workspaces -------------------------------------------------------------------------

const WS = {
  object: "workspace", id: "ws_1", name: "Acme", logo_url: null, user_id: null, status: "active", budget_usd_per_month: 200,
  spent_usd: 12.5, channel_count: 2, created_at: "2026-10-01T09:00:00Z",
  members: [
    { id: "wm_1", type: "agent", agent_id: "ag_1", user_id: null, name: "planner", created_at: "2026-10-01T09:00:00Z" },
    { id: "wm_2", type: "user", agent_id: null, user_id: "ana", name: "Ana", created_at: "2026-10-01T09:00:00Z" },
  ],
};

test("Workspace.create sends its members, cap and logo; its fields read back", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/workspaces", json(WS, { status: 201 }));
  const ws = await nc.Workspace.create("Acme", {
    members: [nc.Agent.fromId("ag_1"), nc.User.fromId("ana")], budgetUsdPerMonth: 200, logoUrl: "https://acme.test/logo.png",
  });
  assert.deepEqual(create.last.body, {
    name: "Acme", members: [{ agent_id: "ag_1" }, { user_id: "ana" }], budget_usd_per_month: 200, logo_url: "https://acme.test/logo.png",
  });
  assert.deepEqual([ws.id, ws.status, ws.budgetUsdPerMonth, ws.spentUsd, ws.channelCount], ["ws_1", "active", 200, 12.5, 2]);
  assert.deepEqual(ws.members.map((m) => [m.type, m.agentId ?? m.userId]), [["agent", "ag_1"], ["user", "ana"]]);
  await nc.asUser(USER_ID, () => nc.Workspace.create("Mine"));
  assert.equal(create.last.headers.get("NoClick-User"), USER_ID);
});

test("Workspace.fromName makes one, or converges members, cap and logo on the one there", async () => {
  const { api } = setup();
  const find = api.on("GET", "/v1/workspaces", json(listing([])));
  const create = api.on("POST", "/v1/workspaces", json(WS));
  await nc.Workspace.fromName("Acme", { createIfMissing: true, members: [nc.Agent.fromId("ag_1")], budgetUsdPerMonth: 200 }).hydrate();
  assert.deepEqual([find.last.query.get("name"), find.last.query.get("status")], ["Acme", "active"]);
  assert.deepEqual(create.last.body, { name: "Acme", members: [{ agent_id: "ag_1" }], budget_usd_per_month: 200 });

  api.on("GET", "/v1/workspaces", json(listing([WS])));
  const patch = api.on("PATCH", "/v1/workspaces/ws_1", json({ ...WS, logo_url: null, budget_usd_per_month: 300 }));
  const removed = api.on("DELETE", "/v1/workspaces/ws_1/members/wm_2", noContent());
  const added = api.on("POST", "/v1/workspaces/ws_1/members", json({ id: "wm_3", type: "user", user_id: "bo" }));
  const reread = api.on("GET", "/v1/workspaces/ws_1", json(WS));
  await nc.Workspace.fromName("Acme", {
    createIfMissing: true, members: [nc.Agent.fromId("ag_1"), nc.User.fromId("bo")], budgetUsdPerMonth: 300, logoUrl: null,
  }).hydrate();
  assert.deepEqual(patch.last.body, { budget_usd_per_month: 300 });
  assert.deepEqual([removed.count, added.last.body, reread.count], [1, { user_id: "bo" }, 1]);
  await assert.rejects(nc.Workspace.fromName("Nope").hydrate(), nc.NotFound);
});

test("a workspace updates, archives, deletes, lists its channels and manages its members", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workspaces/ws_1", json(WS));
  const patch = api.on("PATCH", "/v1/workspaces/ws_1", json({ ...WS, name: "Acme Inc", logo_url: null }));
  const archive = api.on("POST", "/v1/workspaces/ws_1/archive", json({ ...WS, status: "archived" }));
  const trash = { object: "trash_item", id: "tr_1", kind: "workspace", resource_id: "ws_1", name: "Acme", user_id: null,
    trashed_at: "2026-11-11T10:00:00Z", purge_after: "2026-12-11T10:00:00Z" };
  const del = api.on("DELETE", "/v1/workspaces/ws_1", json({ object: "workspace", id: "ws_1", deleted: true, trash, operation_id: "op_1" }));
  const unarchive = api.on("POST", "/v1/workspaces/ws_1/unarchive", json({ ...WS, status: "active" }));
  const channels = api.on("GET", "/v1/channels", json(listing([{ ...CHANNEL, workspace_id: "ws_1" }])));
  const add = api.on("POST", "/v1/workspaces/ws_1/members", json({ id: "wm_4", type: "agent", agent_id: "ag_9", name: "writer" }));
  const removed = api.on("DELETE", "/v1/workspaces/ws_1/members/wm_2", noContent());
  const list = api.on("GET", "/v1/workspaces", json(listing([WS])));

  const ws = await nc.Workspace.get("ws_1");
  await ws.update({ name: "Acme Inc", logoUrl: null });
  assert.deepEqual(patch.last.body, { name: "Acme Inc", logo_url: null });
  const [room] = await ws.channels({ status: "open" });
  assert.deepEqual([channels.last.query.get("workspace_id"), channels.last.query.get("status"), room.workspaceId], ["ws_1", "open", "ws_1"]);
  assert.equal((await ws.add(nc.Agent.fromId("ag_9"))).name, "writer");
  assert.deepEqual(add.last.body, { agent_id: "ag_9" });
  await ws.remove(nc.User.fromId("ana"));
  assert.equal(removed.count, 1);
  assert.equal((await ws.archive()).status, "archived");
  assert.equal(archive.count, 1);
  assert.equal((await ws.unarchive()).status, "active");
  assert.equal(unarchive.count, 1);
  const item = await ws.delete();
  assert.deepEqual([del.count, item.id, item.kind], [1, "tr_1", "workspace"]);

  await nc.Workspace.list({ status: "archived", userFilter: nc.ALL_USERS });
  assert.deepEqual([list.last.query.get("status"), list.last.query.get("user_id")], ["archived", "all"]);
  await nc.Workspace.listPage({ agent: nc.Agent.fromId("ag_1") });
  assert.equal(list.last.query.get("agent_id"), "ag_1");
  const rooms = api.on("GET", "/v1/channels", json({ object: "list", data: [], next_cursor: null }));
  await nc.Channel.list({ agent: "ag_1", workspace: "ws_1" });
  assert.deepEqual([rooms.last.query.get("agent_id"), rooms.last.query.get("workspace_id")], ["ag_1", "ws_1"]);
});

test("a workspace subscribes several channels at once; channels are required", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workspaces/ws_1", json(WS));
  const sub = api.on("POST", "/v1/workspaces/ws_1/subscriptions", json({ ...SUB, channel_id: null, workspace_id: "ws_1", channels: "all" }));
  const ws = nc.Workspace.fromId("ws_1");
  const subscription = await ws.subscribe(new nc.OnWebhook("deploys"), { channels: "all", wake: "all", filters: { status: "failed" } });
  assert.deepEqual(sub.last.body, { source: { kind: "webhook", name: "deploys" }, wake: "all", filters: { status: "failed" }, channels: "all" });
  assert.deepEqual([subscription.workspaceId, subscription.channelId, subscription.channels], ["ws_1", null, "all"]);
  await ws.subscribe(new nc.OnEvent("stripe", "invoice_payment_failed"), { channels: [nc.Channel.fromId("ch_1"), "ch_2"] });
  assert.deepEqual((sub.last.body as { channels: unknown }).channels, ["ch_1", "ch_2"]);
  await assert.rejects(ws.subscribe(new nc.OnWebhook("deploys"), {} as { channels: "all" }), /needs channels/);

  api.on("GET", "/v1/workspaces/ws_1/subscriptions", json(listing([{ ...SUB, channel_id: null, workspace_id: "ws_1", channels: ["ch_1"] }])));
  const del = api.on("DELETE", "/v1/workspaces/ws_1/subscriptions/sub_1", noContent());
  const [mine] = await ws.subscriptions();
  await mine.unsubscribe();
  assert.equal(del.count, 1);

  // A subscription reloads itself from its own route, under its channel or its workspace.
  const own = api.on("GET", "/v1/workspaces/ws_1/subscriptions/sub_1", json({ ...SUB, channel_id: null, workspace_id: "ws_1", status: "error", error: "Disconnected." }));
  assert.deepEqual([(await mine.refresh()).status, mine.error, own.count], ["error", "Disconnected.", 1]);
  const channelRow = { ...SUB, channel_id: "ch_1", workspace_id: null, channels: null };
  api.on("POST", "/v1/channels/ch_1/subscriptions", json(channelRow));
  const ownChannel = api.on("GET", "/v1/channels/ch_1/subscriptions/sub_1", json({ ...channelRow, last_event_at: "2026-10-01T12:00:00Z" }));
  const channelSub = await nc.Channel.fromId("ch_1").subscribe(new nc.OnWebhook("deploys"));
  assert.equal((await channelSub.refresh()).lastEventAt?.toISOString(), "2026-10-01T12:00:00.000Z");
  assert.equal(ownChannel.count, 1);
});

test("a workspace channel takes the workspace's scope and names each user it holds", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/channels", json({ ...CHANNEL, workspace_id: "ws_u" }));
  const ws = nc.Workspace.fromId("ws_u", { user: USER_ID });
  const room = await nc.Channel.create("escalations", { workspace: ws, members: [nc.Agent.fromId("ag_1"), nc.User.fromId("ana"), nc.User.fromId("bo")] });
  assert.deepEqual(create.last.body, {
    name: "escalations", workspace_id: "ws_u", members: [{ agent_id: "ag_1" }, { user_id: "ana" }, { user_id: "bo" }],
  });
  assert.equal(create.last.headers.get("NoClick-User"), USER_ID);
  assert.equal(room.workspaceId, "ws_u");

  const find = api.on("GET", "/v1/channels", json(listing([])));
  await nc.Channel.fromName("escalations", { workspace: "ws_u", createIfMissing: true, members: [nc.User.fromId("ana")] }).hydrate();
  assert.deepEqual([find.last.query.get("name"), find.last.query.get("workspace_id")], ["escalations", "ws_u"]);
  assert.deepEqual(create.last.body, { name: "escalations", workspace_id: "ws_u", members: [{ user_id: "ana" }] });
  // A Workspace object carries its scope, so a user beside it is refused; an id leaves user to say where.
  await assert.rejects(nc.Channel.create("x", { workspace: ws, user: "bo" }), /lives in the workspace's scope/);
  await assert.rejects(nc.Channel.create("x", { workspace: ws, user: null }), /lives in the workspace's scope/);
  assert.throws(() => nc.Channel.fromName("x", { workspace: ws, user: "bo" }), /lives in the workspace's scope/);
  await nc.Channel.create("by-id", { workspace: "ws_u", user: "bo" });
  assert.equal(create.last.headers.get("NoClick-User"), "bo");
  assert.equal(create.count, 3);
  // Outside a workspace a channel still has one user.
  await assert.rejects(nc.Channel.create("x", { members: [nc.User.fromId("ana"), nc.User.fromId("bo")] }), /one user/);
});

// --- the agent's files are its AgentWorkspace -------------------------------------------------

test("agent.workspace() is an AgentWorkspace, apart from a Workspace, and an old caller's conversation still goes", () => {
  const files = nc.Agent.fromId("ag_1").workspace();
  assert.ok(files instanceof nc.AgentWorkspace);
  assert.ok(!(files instanceof nc.Workspace));
  assert.equal(files.conversation, undefined);
  assert.equal(nc.Agent.fromId("ag_1").workspace("ticket-1841").conversation, "ticket-1841");
});

test("in a workspace's channel a User is named by id, as a member and as an author", async () => {
  const { api } = setup();
  api.on("GET", "/v1/channels/ch_w", json({ ...CHANNEL, id: "ch_w", workspace_id: "ws_1" }));
  const add = api.on("POST", "/v1/channels/ch_w/members", json({ id: "mem_9", type: "user", user_id: "carla" }));
  const post = api.on("POST", "/v1/channels/ch_w/messages", json({ id: "msg_1", channel_id: "ch_w", text: "hi", author: { type: "user", id: "carla" } }));
  const room = nc.Channel.fromId("ch_w");
  assert.equal((await room.addMember(nc.User.fromId("carla"))).userId, "carla");
  assert.deepEqual(add.last.body, { user_id: "carla" });
  await room.post("@planner where are we?", { as: nc.User.fromId("carla") });
  assert.deepEqual(post.last.body, { text: "@planner where are we?", as: { user_id: "carla" } });

  // Outside a workspace the user is the channel's own.
  api.on("GET", "/v1/channels/ch_1", json(CHANNEL));
  const addOwn = api.on("POST", "/v1/channels/ch_1/members", json({ id: "mem_1", type: "user", user_id: USER_ID }));
  const postOwn = api.on("POST", "/v1/channels/ch_1/messages", json({ id: "msg_2", channel_id: "ch_1", text: "hi", author: {} }));
  await nc.Channel.fromId("ch_1").addMember(nc.User.fromId(USER_ID));
  await nc.Channel.fromId("ch_1").post("hi", { as: nc.User.fromId(USER_ID) });
  assert.deepEqual([addOwn.last.body, (postOwn.last.body as { as: unknown }).as], [{ user: true }, { user: true }]);
});

test("Workspace.messages reads what was said across its channels since a time, each naming its channel", async () => {
  const { api } = setup();
  const said = {
    object: "channel_message", id: "m_2", channel_id: "ch_2", channel_name: "front-of-house",
    author: { type: "account", id: null, name: "Olu" }, text: "Oven repair on Thursday.", mentions: [],
    created_at: "2026-11-10T09:00:00Z", reply_count: 0,
  };
  const read = api.on("GET", "/v1/workspaces/ws_1/messages", json(listing([said], "m_2")));
  const ws = nc.Workspace.fromId("ws_1");
  const [message] = await ws.messages({ since: new Date("2026-11-10T00:00:00Z"), limit: 30 });
  assert.deepEqual([message.channelName, message.channelId, message.text, message.author.name], [
    "front-of-house", "ch_2", "Oven repair on Thursday.", "Olu",
  ]);
  assert.deepEqual(Object.fromEntries(read.last.query), { since: "2026-11-10T00:00:00.000Z", limit: "30" });
  await ws.messages({ after: message });
  assert.deepEqual(Object.fromEntries(read.last.query), { cursor: "m_2" });
});
