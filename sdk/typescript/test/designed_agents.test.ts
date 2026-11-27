// Designed agent features against the mock API: schedules (`Cron` triggers and their convergence
// from a definition; webhooks and app events are built, see triggers.test.ts), pause and resume,
// memory, workspace files, the share link, streamed turns, rehearsals, hosted MCP servers and
// simulated toolkits.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, operation, setup } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: 50,
  created_at: "2026-09-25T10:00:00Z",
};

function trigger(id: string, kind: string, spec: Record<string, unknown>, fields: Record<string, unknown> = {}) {
  return {
    object: "agent_trigger", id, kind, spec, status: "active", url: null, next_run: null, last_fired_at: null, error: null,
    created_at: "2026-09-25T10:00:00Z", ...fields,
  };
}

const CRON = trigger("tr_1", "cron", { cron: "0 8 * * 1-5", tz: "Europe/London", message: "Old summary" }, { next_run: "2026-09-28T07:00:00Z" });
const WEBHOOK = trigger("tr_2", "webhook", { name: "orders" }, { url: "https://hooks.noclick.app/t/wh_secret" });
const EMAIL = trigger("tr_3", "email", { inbox_id: "inb_1", address: "help@acme.test" });

// --- definitions ------------------------------------------------------------------

test("create sends triggers, a browser profile and a card", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/slack", json({ object: "connection", id: "cn_1", name: "slack", integration: "slack", status: "connected" }));
  const create = api.on("POST", "/v1/agents", json({ ...AGENT, trigger_kinds: ["cron", "webhook", "event"], browser_profile_id: "bp_1", card_id: "card_9", paused: false }));
  const agent = await nc.Agent.create("support", {
    instructions: "Answer #support.",
    triggers: [
      new nc.Cron("0 8 * * 1-5", { tz: "Europe/London", message: "Post the summary" }),
      new nc.OnWebhook("orders"),
      new nc.OnEvent(nc.Connection.fromName("slack"), "message", { filters: { channel: "#support" }, message: "Answer it" }),
    ],
    browserProfile: "bp_1",
    card: "card_9",
  });
  assert.deepEqual(create.last.body, {
    name: "support", instructions: "Answer #support.",
    triggers: [
      { kind: "cron", cron: "0 8 * * 1-5", tz: "Europe/London", message: "Post the summary" },
      { kind: "webhook", name: "orders" },
      { kind: "event", connection: "slack", event: "message", filters: { channel: "#support" }, message: "Answer it" },
    ],
    browser_profile_id: "bp_1", card_id: "card_9",
  });
  assert.deepEqual([agent.triggerKinds, agent.browserProfileId, agent.cardId, agent.paused], [["cron", "webhook", "event"], "bp_1", "card_9", false]);
});

test("update signs its browser in with a profile and out", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({ ...AGENT, browser_profile_id: "bp_2" }));
  const agent = await nc.Agent.fromId("ag_1").hydrate();
  await agent.update({ browserProfile: "bp_2" });
  assert.deepEqual(patch.last.body, { browser_profile_id: "bp_2" });
  assert.equal(agent.browserProfileId, "bp_2");
  await agent.update({ browserProfile: null });
  assert.deepEqual(patch.last.body, { browser_profile_id: null });
});

test("update gives a card and takes it back", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({ ...AGENT, card_id: "card_1" }));
  const agent = await nc.Agent.fromId("ag_1").hydrate();
  await agent.update({ card: "card_1" });
  assert.deepEqual(patch.last.body, { card_id: "card_1" });
  assert.equal(agent.cardId, "card_1");
  await agent.update({ card: null });
  assert.deepEqual(patch.last.body, { card_id: null });
});

test("fromName converges triggers and keeps mail triggers and webhook URLs", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([AGENT])));
  api.on("GET", "/v1/agents/ag_1/triggers", json(listing([CRON, WEBHOOK, EMAIL])));
  const removed = api.on("DELETE", "/v1/agents/ag_1/triggers/tr_1", new Response(null, { status: 204 }));
  const added = api.on("POST", "/v1/agents/ag_1/triggers", json(trigger("tr_4", "cron", {})));
  const reread = api.on("GET", "/v1/agents/ag_1", json({ ...AGENT, trigger_kinds: ["cron", "webhook", "email"] }));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json(AGENT));
  const agent = await nc.Agent.fromName("support", {
    createIfMissing: true, instructions: "hi",
    triggers: [new nc.Cron("0 8 * * 1-5", { tz: "Europe/London", message: "New summary" }), new nc.OnWebhook("orders")],
  }).hydrate();
  assert.equal(agent.id, "ag_1");
  assert.equal(patch.count, 0);
  assert.equal(removed.count, 1);
  assert.deepEqual(added.last.body, { kind: "cron", cron: "0 8 * * 1-5", tz: "Europe/London", message: "New summary" });
  assert.equal(reread.count, 1);
  assert.deepEqual(agent.triggerKinds, ["cron", "webhook", "email"]);
});


// --- triggers, pause and resume ---------------------------------------------------------

test("triggers, addTrigger and removeTrigger", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/triggers", json(listing([CRON, WEBHOOK, EMAIL])));
  const add = api.on("POST", "/v1/agents/ag_1/triggers", json(WEBHOOK));
  const deletes: string[] = [];
  for (const id of ["tr_1", "tr_2"]) {
    api.on("DELETE", `/v1/agents/ag_1/triggers/${id}`, (call: Call) => {
      deletes.push(call.path);
      return new Response(null, { status: 204 });
    });
  }
  const agent = nc.Agent.fromId("ag_1");
  const [cron, webhook, email] = await agent.triggers();
  assert.deepEqual([cron.kind, cron.spec.tz, cron.nextRun?.toISOString(), cron.defined], ["cron", "Europe/London", "2026-09-28T07:00:00.000Z", true]);
  assert.deepEqual([webhook.url, email.defined, email.spec.address], ["https://hooks.noclick.app/t/wh_secret", false, "help@acme.test"]);

  const added = await agent.addTrigger(new nc.OnWebhook("orders", { message: "A new order" }));
  assert.deepEqual(add.last.body, { kind: "webhook", name: "orders", message: "A new order" });
  assert.equal(added.url, WEBHOOK.url);

  await agent.removeTrigger(cron);
  await agent.removeTrigger("tr_2");
  await agent.removeTrigger(new nc.Cron("0 8 * * 1-5", { tz: "Europe/London", message: "Old summary" }));
  assert.deepEqual(deletes, ["/v1/agents/ag_1/triggers/tr_1", "/v1/agents/ag_1/triggers/tr_2", "/v1/agents/ag_1/triggers/tr_1"]);
  await assert.rejects(agent.removeTrigger(new nc.OnWebhook("refunds")), nc.NotFound);
  assert.throws(() => new nc.OnEvent(42 as unknown as string, "message"), TypeError);
});

test("pause and resume", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("POST", "/v1/agents/ag_1/pause", json({ ...AGENT, paused: true }));
  api.on("POST", "/v1/agents/ag_1/resume", json({ ...AGENT, paused: false }));
  const agent = nc.Agent.fromId("ag_1");
  assert.equal((await agent.pause()).paused, true);
  assert.equal((await agent.resume()).paused, false);
});

// --- memory -----------------------------------------------------------------------------

const ENTRY = {
  object: "memory_entry", name: "refunds", description: "Our refund rules", content: "Refund within 30 days.", version: 3,
  updated_at: "2026-09-25T10:00:00Z", updated_by: "agent", user_id: null,
};

test("memory reads and writes one layer, with a version check", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const checkpoint = { ...ENTRY, name: "context.3f9a0c1d2e4b5a6f", content: null, conversation: "desk" };
  const reads = api.on("GET", "/v1/agents/ag_1/memory", json(listing([{ ...ENTRY, content: null }, checkpoint])));
  api.on("GET", "/v1/agents/ag_1/memory/refunds", json(ENTRY));
  const save = api.on("PUT", "/v1/agents/ag_1/memory/refunds", json({ ...ENTRY, version: 4, updated_by: "api" }),
    apiError(409, "conflict", "refunds is at version 5.", { current_version: 5 }));
  const forget = api.on("DELETE", "/v1/agents/ag_1/memory/old%20pricing", new Response(null, { status: 204 }));

  const memory = nc.Agent.fromId("ag_1").memory;
  const [listed, folded] = await memory.list();
  assert.deepEqual([listed.name, listed.content, listed.version, listed.conversation], ["refunds", null, 3, null]);
  assert.equal(folded.conversation, "desk"); // a conversation's checkpoint
  assert.equal(reads.last.headers.get("NoClick-User"), null);
  await memory.search("refund policy", { limit: 5, user: "user_42" });
  assert.deepEqual([reads.last.query.get("q"), reads.last.query.get("limit")], ["refund policy", "5"]);
  assert.equal(reads.last.headers.get("NoClick-User"), "user_42");

  const entry = await memory.read("refunds");
  assert.deepEqual([entry.content, entry.updatedBy, entry.updatedAt?.getUTCDate()], ["Refund within 30 days.", "agent", 25]);
  const saved = await memory.save("refunds", "Refund within 14 days.", { version: entry.version });
  assert.deepEqual(save.last.body, { content: "Refund within 14 days.", version: 3 });
  assert.equal(saved.version, 4);
  await assert.rejects(memory.save("refunds", "x", { version: 3 }), (err: unknown) => err instanceof nc.Conflict && err.details.current_version === 5);
  await memory.delete("old pricing", { version: 2 });
  assert.equal(forget.last.query.get("version"), "2");
});

test("an entry lists, reads and restores its versions", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const version = {
    object: "memory_entry_version", name: "refunds", version: 3, current: true, description: "Our refund rules",
    content: null, user_id: null, saved_at: "2026-09-25T10:00:00Z",
    written_by: { type: "agent", agent_id: "ag_1", agent_name: "support", conversation: "desk" },
  };
  const listed = api.on("GET", "/v1/agents/ag_1/memory/refunds/versions", json(listing([
    version, { ...version, version: 2, current: false, written_by: { type: "api" } }])));
  api.on("GET", "/v1/agents/ag_1/memory/refunds/versions/2", json({ ...version, version: 2, current: false, content: "Refund within 30 days." }));
  const restore = api.on("POST", "/v1/agents/ag_1/memory/refunds/versions/2/restore", json({ ...ENTRY, version: 4, updated_by: "api" }));

  const memory = nc.Agent.fromId("ag_1").memory;
  const [newest, older] = await memory.versions("refunds", { user: "user_42" });
  assert.deepEqual([newest.version, newest.current, newest.content, newest.writtenBy.conversation], [3, true, null, "desk"]);
  assert.deepEqual([older.version, older.current, older.writtenBy.type, newest.savedAt?.getUTCDate()], [2, false, "api", 25]);
  assert.equal(listed.last.headers.get("NoClick-User"), "user_42");
  assert.equal((await memory.getVersion("refunds", 2)).content, "Refund within 30 days.");
  const restored = await memory.restore("refunds", 2);
  assert.deepEqual([restored.version, restored.content, restore.calls.length], [4, "Refund within 30 days.", 1]);
});

// --- workspace --------------------------------------------------------------------------

test("a workspace lists, reads, writes, links and deletes a conversation's files", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const files = api.on("GET", "/v1/agents/ag_1/workspace", json(listing([{ path: "report.csv", size_bytes: 2048, modified_at: "2026-09-25T10:00:00Z", url: "https://files.test/r" }])));
  const read = api.on("GET", "/v1/agents/ag_1/workspace/files", new Response("region,total\n"));
  const write = api.on("PUT", "/v1/agents/ag_1/workspace/files", json({ path: "notes.md", size_bytes: 5 }));
  const link = api.on("GET", "/v1/agents/ag_1/workspace/url", json({ url: "https://files.test/n", expires_at: "x" }));
  const removed = api.on("DELETE", "/v1/agents/ag_1/workspace/files", json({ path: "notes.md", deleted: true }));

  const workspace = await nc.asUser("user_42", () => nc.Agent.fromId("ag_1").workspace("ticket-1841"));
  const [report] = await workspace.files();
  assert.deepEqual([report.path, report.sizeBytes, report.url], ["report.csv", 2048, "https://files.test/r"]);
  assert.equal(files.last.query.get("conversation"), "ticket-1841");
  assert.equal(files.last.headers.get("NoClick-User"), "user_42"); // captured where it was made
  assert.equal(files.last.query.get("path"), null);
  await workspace.files({ path: "shots" });
  assert.equal(files.last.query.get("path"), "shots");
  assert.equal(new TextDecoder().decode(await workspace.read("report.csv")), "region,total\n");
  assert.equal(read.last.query.get("path"), "report.csv");
  assert.equal((await workspace.write("notes.md", "hello")).path, "notes.md");
  assert.deepEqual([write.last.body, write.last.query.get("conversation")], ["hello", "ticket-1841"]);
  assert.equal(await workspace.url("notes.md", { expiresInS: 600 }), "https://files.test/n");
  assert.equal(link.last.query.get("expires_in_s"), "600");
  assert.equal(await workspace.delete("notes.md"), undefined);
  assert.deepEqual([removed.last.query.get("path"), removed.last.headers.get("NoClick-User")], ["notes.md", "user_42"]);
});

// --- share link -------------------------------------------------------------------------

test("share, disable and rotate", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const row = { object: "share_link", agent_id: "ag_1", url: "https://noclick.com/a/lk_1", enabled: true, created_at: "2026-09-25T10:00:00Z", rotated_at: null };
  api.on("POST", "/v1/agents/ag_1/share", json(row));
  const disable = api.on("PATCH", "/v1/agents/ag_1/share", json({ ...row, enabled: false }));
  api.on("POST", "/v1/agents/ag_1/share/rotate", json({ ...row, url: "https://noclick.com/a/lk_2", rotated_at: "2026-09-26T10:00:00Z" }));
  api.on("GET", "/v1/agents/ag_1/share", apiError(404, "not_found", "Never shared."), json({ ...row, enabled: false }));
  const agent = nc.Agent.fromId("ag_1");
  assert.equal(await agent.shareLink(), null); // reading never turns it on
  assert.equal((await agent.shareLink())?.enabled, false);
  const link = await agent.share();
  assert.deepEqual([link.url, link.enabled, link.agentId], ["https://noclick.com/a/lk_1", true, "ag_1"]);
  assert.equal((await link.disable()).enabled, false);
  assert.deepEqual(disable.last.body, { enabled: false });
  assert.equal((await link.rotate()).url, "https://noclick.com/a/lk_2");
  assert.equal(link.rotatedAt?.getUTCDate(), 26);
});

// --- streaming --------------------------------------------------------------------------

const SSE = [
  ": keep-alive",
  "",
  "event: text",
  'data: {"text": "Let me "}',
  "",
  "event: tool_call",
  'data: {"tool": "stripe__list_refunds", "arguments": {"order": "1841"}}',
  "",
  "event: tool_result",
  'data: {"tool": "stripe__list_refunds", "result": [], "is_error": false}',
  "",
  "event: done",
  'data: {"text": "Let me check.", "conversation": "ticket-1841", "tool_calls": [], "operation_id": "op_9"}',
  "",
  "",
].join("\n");

/** An event-stream body delivered a few bytes at a time, as a network would. */
function chunked(text: string): Response {
  const bytes = new TextEncoder().encode(text);
  let at = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (at >= bytes.length) return controller.close();
      controller.enqueue(bytes.slice(at, at + 7));
      at += 7;
    },
  });
  return new Response(body, { headers: { "content-type": "text/event-stream" } });
}

test("stream yields each moment of the turn, then the reply", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const route = api.on("POST", "/v1/agents/ag_1/messages", () => chunked(SSE));
  const events: nc.AgentEvent[] = [];
  for await (const event of nc.Agent.fromId("ag_1").stream("Where's my refund?", { conversation: "ticket-1841", user: "user_42" })) events.push(event);
  assert.deepEqual(events.map((e) => e.type), ["text", "tool_call", "tool_result", "done"]);
  assert.deepEqual([events[1].tool, events[1].arguments], ["stripe__list_refunds", { order: "1841" }]);
  assert.deepEqual([events[2].result, events[2].isError], [[], false]);
  const reply = events[3].reply!;
  assert.deepEqual([reply.text, reply.conversation, reply.operationId], ["Let me check.", "ticket-1841", "op_9"]);
  const call = route.last;
  assert.equal(call.query.get("stream"), "1");
  assert.equal(call.headers.get("Accept"), "text/event-stream");
  assert.equal(call.headers.get("NoClick-User"), "user_42");
  assert.equal(call.headers.get("Authorization"), "Bearer nk_live_test");
  assert.deepEqual(call.body, { text: "Where's my refund?", conversation: "ticket-1841" });
});

test("a failed or refused stream throws its error", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("POST", "/v1/agents/ag_1/messages",
    () => chunked('event: error\ndata: {"error": {"type": "spend_cap_exceeded", "message": "Over its budget."}}\n\n'),
    apiError(409, "conflict", "Mid-turn."));
  const drain = async () => {
    for await (const event of nc.Agent.fromId("ag_1").stream("hi")) void event;
  };
  await assert.rejects(drain(), (err: unknown) => err instanceof nc.SpendCapExceeded && /Over its budget/.test(String(err)));
  await assert.rejects(drain(), nc.Conflict);
});

// --- rehearsals -------------------------------------------------------------------------

test("rehearse waits for a Rehearsal", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const result = {
    reply: "I've refunded order 1841.", scenario: "It arrived broken.", cost_usd: 0.04,
    tool_calls: [{ tool: "stripe__create_refund", arguments: { order: "1841" }, result: { id: "re_1" } }],
    transcript: [{ role: "tool", tool: "stripe__create_refund" }, { role: "assistant", text: "Done" }],
  };
  const start = api.on("POST", "/v1/agents/ag_1/rehearsals", json(operation({ id: "op_r", kind: "agent.rehearse", status: "running" })));
  api.on("GET", "/v1/operations/op_r/wait", json(operation({ id: "op_r", kind: "agent.rehearse", status: "succeeded", result })));
  const op = await nc.Agent.fromId("ag_1").rehearse("Refund order 1841", { scenario: "It arrived broken.", user: "user_42" });
  assert.deepEqual(start.last.body, { message: "Refund order 1841", scenario: "It arrived broken." });
  assert.equal(start.last.headers.get("NoClick-User"), "user_42");
  const run = await op.wait();
  assert.deepEqual([run.reply, run.costUsd, run.operationId, run.toolCalls.length, run.transcript.length], ["I've refunded order 1841.", 0.04, "op_r", 1, 2]);
});

// --- hosted MCP servers -----------------------------------------------------------------

const SERVER = {
  object: "mcp_server", id: "mcp_1", name: "crm-tools", url: "https://mcp.noclick.app/s/k3y", tools: ["hubspot", "search"],
  tool_count: 31, user_id: USER_ID, created_at: "2026-09-25T10:00:00Z", last_client_at: null,
};

test("McpServer create, list, update, rotate, clients and delete", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/mcp_servers", json(SERVER));
  const listed = api.on("GET", "/v1/mcp_servers", json(listing([SERVER])));
  const patch = api.on("PATCH", "/v1/mcp_servers/mcp_1", json({ ...SERVER, tools: ["hubspot", "search", "fetch"] }));
  api.on("POST", "/v1/mcp_servers/mcp_1/rotate", json({ ...SERVER, url: "https://mcp.noclick.app/s/n3w" }));
  api.on("GET", "/v1/mcp_servers/mcp_1/clients", json(listing([{ name: "Claude", version: "1.4.2", first_seen_at: "2026-09-25T10:00:00Z", last_seen_at: "2026-09-26T09:00:00Z", tool_count: 31 }])));
  const del = api.on("DELETE", "/v1/mcp_servers/mcp_1", new Response(null, { status: 204 }));

  const server = await nc.McpServer.create("crm-tools", { tools: ["hubspot", "search"], user: "acme" });
  assert.deepEqual(create.last.body, { name: "crm-tools", tools: ["hubspot", "search"] });
  assert.equal(create.last.headers.get("NoClick-User"), "acme");
  assert.deepEqual([server.url, server.toolCount, server.lastClientAt], ["https://mcp.noclick.app/s/k3y", 31, null]);
  const [row] = await nc.McpServer.list({ userFilter: nc.ALL_USERS });
  assert.equal(listed.last.query.get("user_id"), "all");
  assert.equal(row.id, server.id);
  await server.update({ tools: ["hubspot", "search", "fetch"] });
  assert.deepEqual(patch.last.body, { tools: ["hubspot", "search", "fetch"] });
  assert.equal((await server.rotate()).url, "https://mcp.noclick.app/s/n3w");
  const [claude] = await server.clients();
  assert.deepEqual([claude.name, claude.version, claude.toolCount, claude.lastSeenAt?.getUTCHours()], ["Claude", "1.4.2", 31, 9]);
  await server.delete();
  assert.equal(del.last.headers.get("NoClick-User"), USER_ID);
});

test("McpServer.fromName creates on first use, then converges", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/mcp_servers", json(listing([])), json(listing([SERVER])));
  const create = api.on("POST", "/v1/mcp_servers", json(SERVER));
  const server = nc.McpServer.fromName("crm-tools", { tools: ["hubspot", "search"], createIfMissing: true });
  assert.equal(listed.count, 0);
  assert.equal((await server.hydrate()).url, SERVER.url);
  assert.deepEqual([listed.last.query.get("name"), create.count], ["crm-tools", 1]);

  const patch = api.on("PATCH", "/v1/mcp_servers/mcp_1", json({ ...SERVER, tools: ["hubspot"] }));
  const again = await nc.McpServer.fromName("crm-tools", { tools: ["hubspot"], createIfMissing: true }).hydrate();
  assert.deepEqual([again.tools, patch.last.body], [["hubspot"], { tools: ["hubspot"] }]);
  assert.throws(() => nc.McpServer.fromName("crm-tools", { createIfMissing: true }), TypeError);
});

// --- toolkits ---------------------------------------------------------------------------

test("a simulated toolkit is one world", async () => {
  const { api } = setup();
  const calls = api.on("POST", "/v1/toolkits/call", (call: Call) =>
    json({ object: "tool_result", name: (call.body as { name: string }).name, content: "two open invoices", is_error: false, simulated: true }));
  const toolkit = new nc.Toolkit(["stripe"], { simulated: true, scenario: "Ana has two unpaid invoices" });
  await toolkit.call("stripe__list_invoices", { status: "open" });
  await toolkit.call("stripe__create_refund", { invoice: "in_1" });
  const [first, second] = calls.calls.map((c) => (c.body as { simulated: { world: string; scenario: string } }).simulated);
  assert.deepEqual(first, second);
  assert.equal(first.scenario, "Ana has two unpaid invoices");
  assert.match(first.world, /^world_/);
  await new nc.Toolkit(["stripe"]).call("stripe__list_invoices");
  assert.equal((calls.last.body as Record<string, unknown>).simulated, undefined);
  assert.throws(() => new nc.Toolkit(["stripe"], { scenario: "no world" }), TypeError);
});

const connectionRow = (id: string, name: string, userId: string | null) => ({
  object: "connection", id, name, integration: name, status: "connected", user_id: userId,
});

test("a connection from another scope stays that connection; names stay the acting user's", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/slack", json(connectionRow("cn_acme", "slack", "acme")));
  api.on("GET", "/v1/connections/gmail", json(connectionRow("cn_ours", "gmail", null)));
  api.on("GET", "/v1/connections/calendar", json(connectionRow("cn_ana", "calendar", USER_ID)));
  const create = api.on("POST", "/v1/agents", json({ object: "agent", id: "ag_2", name: "assistant", instructions: "hi", tools: [], user_id: USER_ID }));

  const acmeSlack = nc.Connection.fromName("slack", { user: "acme" });
  const ourGmail = nc.Connection.fromName("gmail", { user: null }); // the account's
  await nc.asUser(USER_ID, async () => {
    const calendar = nc.Connection.fromName("calendar");
    await nc.Agent.create("assistant", { instructions: "hi", tools: [acmeSlack, ourGmail.only("send_email_message"), calendar, "search"] });
  });
  assert.deepEqual((create.last.body as { tools: string[] }).tools, ["connection:cn_acme", "connection:cn_ours.send_email_message", "calendar", "search"]);

  // A toolkit call carries the refs only when one goes by id.
  const call = api.on("POST", "/v1/toolkits/call", json({ object: "tool_result", name: "slack__send_message_to_channel", content: "sent", is_error: false }));
  const byId = new nc.Toolkit([acmeSlack, nc.Connection.fromName("calendar", { user: USER_ID })], { user: USER_ID });
  await byId.call("slack__send_message_to_channel", { channel: "#ops", text: "hi" });
  assert.deepEqual((call.last.body as { tools: string[] }).tools, ["connection:cn_acme", "calendar"]);
  await new nc.Toolkit(["slack"]).call("slack__send_message_to_channel", { channel: "#ops" }, { user: USER_ID });
  assert.equal((call.last.body as Record<string, unknown>).tools, undefined);
});

test("toolkit.mcpServer serves the toolkit's tools", async () => {
  const { api } = setup();
  api.on("GET", "/v1/mcp_servers", json(listing([])));
  const create = api.on("POST", "/v1/mcp_servers", json(SERVER));
  const server = new nc.Toolkit(["hubspot", "search"], { user: "acme" }).mcpServer("crm-tools");
  assert.ok(server instanceof nc.McpServer && !server.isHydrated);
  await server.hydrate();
  assert.deepEqual(create.last.body, { name: "crm-tools", tools: ["hubspot", "search"] });
  assert.equal(create.last.headers.get("NoClick-User"), "acme");
  assert.throws(() => new nc.Toolkit(["hubspot"], { simulated: true }).mcpServer("x"), TypeError);
});


test("a matching queue trigger writes nothing on a re-run of fromName", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([AGENT])));
  api.on("GET", "/v1/agents/ag_1/triggers", json(listing([trigger("tr_9", "queue", { queue: "invoices", batch_size: 1 })])));
  const post = api.on("POST", "/v1/agents/ag_1/triggers", json({}));
  const removed = api.on("DELETE", "/v1/agents/ag_1/triggers/tr_9", new Response(null, { status: 204 }));
  await nc.Agent.fromName("support", { createIfMissing: true, instructions: "hi", triggers: [new nc.OnQueue("invoices")] }).hydrate();
  assert.deepEqual([post.count, removed.count], [0, 0]);
});
