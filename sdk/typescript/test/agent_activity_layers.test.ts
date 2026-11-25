// What the agent pages read beyond a conversation's messages: its activity, a thread or memory layer read as the account
// naming whose (`userFilter`), a conversation read by the agent's ref without loading it, a WhatsApp chat's profiles,
// an integration's events by name, one human request, a space's NoClick, the personal space and one session's edits.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const AGENT = { object: "agent", id: "ag_1", name: "support", user_id: null };
const ITEM = {
  chat: { key: "wa-1", name: "Ana", kind: "direct", number: "+14155550101", avatar: null, node_type: "automation-whatsapp" },
  inbound: { sender_name: "Ana", sender_id: "1@c.us", text: "Is it open?", media: { kind: "voice", transcript: "Is it open?" }, at: "2026-11-25T10:00:00Z", message_id: "m1" },
  also_inbound: [{ text: "Today?", at: "2026-11-25T10:00:05Z" }],
  did: [{ kind: "reply", text: "Yes, till 6.", at: "2026-11-25T10:00:09Z", tool: "whatsapp__send_message", edited: true }],
  turn: { id: "op_t", conversation_id: "wa-1", status: "done", started_at: "2026-11-25T10:00:01Z", worked_s: 8, started_by: { kind: "on_event", id: "tr_1" }, steps: [{ tool: "whatsapp__send_message", at: "2026-11-25T10:00:09Z", error: null }] },
};

test("an agent's activity reads each turn typed, and a thread read as the account names whose with its session", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const activity = api.on("GET", "/v1/agents/ag_1/conversations/wa-1/activity", json({ object: "list", data: [ITEM] }));
  const thread = api.on("GET", "/v1/agents/ag_1/conversations/chat-1", json({ messages: [], next_cursor: null, session: "s_7" }));
  const agent = nc.Agent.fromId("ag_1");
  const [item] = await agent.activity("wa-1", { limit: 20 });
  assert.equal(activity.last.query.get("limit"), "20");
  assert.deepEqual([item.chat.nodeType, item.inbound?.text, item.alsoInbound[0].text, item.did[0].edited, item.turn.workedS],
    ["automation-whatsapp", "Is it open?", "Today?", true, 8]);
  assert.equal(item.inbound?.at?.toISOString(), "2026-11-25T10:00:00.000Z");
  const page = await agent.historyPage("chat-1", { limit: 1, userFilter: nc.NO_USER });
  assert.equal(page.session, "s_7");
  assert.equal(thread.last.query.get("user_id"), "none");
  assert.equal(thread.last.headers.get("NoClick-User"), null);
});

test("an agent named by its ref reads its conversations without loading it first", async () => {
  const { api } = setup();
  const loaded = api.on("GET", "/v1/agents/agent%3Acoordinator", json(AGENT));
  api.on("GET", "/v1/agents/agent%3Acoordinator/conversations", json({ object: "list", data: [{ conversation: "s_1", active: true }], next_cursor: null }));
  api.on("GET", "/v1/agents/agent%3Acoordinator/conversations/s_1", json({ messages: [{ role: "user", text: "hi" }] }));
  const agent = nc.Agent.fromId("agent:coordinator", { user: null });
  assert.equal((await agent.conversationsPage({ user: null })).data[0].conversation, "s_1");
  assert.deepEqual((await agent.history("s_1", { user: null })).map((m) => m.text), ["hi"]);
  assert.equal(loaded.calls.length, 0);
});

test("a memory layer is read and written as the account, naming whose", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const listed = api.on("GET", "/v1/agents/ag_1/memory", json({ object: "list", data: [{ name: "refunds", description: "d", version: 2 }] }));
  const saved = api.on("PUT", "/v1/agents/ag_1/memory/refunds", json({ name: "refunds", description: "d", version: 3, content: "30 days" }));
  const agent = nc.Agent.fromId("ag_1");
  assert.equal((await agent.memory.list({ userFilter: "user_42" }))[0].name, "refunds");
  assert.equal(listed.last.query.get("user_id"), "user_42");
  assert.equal(listed.last.headers.get("NoClick-User"), null);
  await agent.memory.save("refunds", "30 days", { version: 2, userFilter: nc.NO_USER });
  assert.equal(saved.last.query.get("user_id"), "none");
  assert.deepEqual(saved.last.body, { content: "30 days", version: 2 });
});

test("a WhatsApp chat's profiles and an integration's events by name", async () => {
  const { api } = setup();
  const profiles = api.on("GET", "/v1/connections/conn_1/chat_profiles", json({ object: "list", data: [{ jid: "1@c.us", name: null, avatar_url: "https://x.test/a.jpg" }] }));
  const events = api.on("GET", "/v1/integrations/slack/events", json({ object: "list", data: [{ name: "channel_message", description: "d", filters: { channel: "Required." } }] }));
  const [chat] = await nc.Connection.fromId("conn_1").chatProfiles(["1@c.us", "2@g.us"]);
  assert.deepEqual([chat.jid, chat.avatarUrl], ["1@c.us", "https://x.test/a.jpg"]);
  assert.deepEqual(profiles.last.query.getAll("jid"), ["1@c.us", "2@g.us"]);
  const [event] = await nc.Connection.integrationEvents("slack");
  assert.deepEqual([event.name, event.filters], ["channel_message", { channel: "Required." }]);
  assert.equal(events.calls.length, 1);
});

test("a human request is retrieved by its id and answered through it", async () => {
  const { api } = setup();
  const view = { id: "hr_1", operation_id: "op_h", kind: "approve", status: "pending", message: "Refund $40?" };
  api.on("GET", "/v1/humans/requests/hr_1", json(view));
  const answered = api.on("POST", "/v1/humans/requests/hr_1/answer", json({ ...view, status: "answered" }));
  const request = await nc.HumanRequest.retrieve("hr_1", { user: null });
  assert.deepEqual([request.requestId, request.requestStatus, request.id], ["hr_1", "pending", "op_h"]);
  await request.approve({ note: "Go ahead" });
  assert.deepEqual(answered.last.body, { approved: true, note: "Go ahead" });
  assert.equal(request.requestStatus, "answered");
});

test("a space's NoClick, the personal space, and one session's edits", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workspaces/ws_1/noclick", json({ object: "workspace_noclick", workspace_id: "ws_1", agent_id: "ag_9", name: "noclick-ws1", label: "NoClick · Support" }));
  const shared = api.on("POST", "/v1/me/personal_space", json({ id: "ws_p", name: "Ana", role: "owner", own: true, personal: true }));
  api.on("GET", "/v1/projects", json({ object: "list", data: [{ object: "project", id: "prj_1", name: "larkspur" }] }));
  const edits = api.on("GET", "/v1/projects/prj_1/live/edits", json({ object: "list", data: [{ seq: 4, files: ["a.js"], outcome: "hot" }], last_seq: 4 }));
  assert.equal((await nc.Workspace.fromId("ws_1").noclickAgent()).agentId, "ag_9");
  assert.equal((await nc.Workspace.personalSpace()).id, "ws_p");
  assert.equal(shared.calls.length, 1);
  const read = await nc.Project.fromName("larkspur").live.edits({ sessionId: "ls_2", after: 3 });
  assert.deepEqual([read.lastSeq, edits.last.query.get("session_id"), edits.last.query.get("after")], [4, "ls_2", "3"]);
});

