// What the TypeScript client gained to match the Python client: each reads the same response the Python
// one does, and the names it replaced keep working.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { BASE, USER_ID, json, listing, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, created_at: "2026-09-25T10:00:00Z",
};
const CHANNEL = {
  object: "channel", id: "ch_1", name: "orders", mode: "mentions", status: "halted", halt_reason: "agent_turn_limit",
  max_agent_turns: 6, budget_usd: 2.5, user_id: USER_ID,
  members: [{ id: "mem_1", type: "agent", agent_id: "ag_1" }, { id: "mem_2", type: "a2a", a2a_url: "https://b.ai/a2a" }],
  created_at: "2026-09-25T10:00:00Z",
};

test("an agent's A2A endpoint and card", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const card = api.on("GET", "/v1/agents/ag_1/a2a/card", json({ name: "support", url: `${BASE}/v1/agents/ag_1/a2a`, skills: [] }));
  const agent = await nc.Agent.get("ag_1");
  // Without one in the view, it's this API's own endpoint for the agent.
  assert.equal(agent.a2aUrl, `${BASE}/v1/agents/ag_1/a2a`);
  assert.deepEqual(await agent.a2aCard(), { name: "support", url: `${BASE}/v1/agents/ag_1/a2a`, skills: [] });
  assert.equal(card.count, 1);
  api.on("GET", "/v1/agents/ag_2", json({ ...AGENT, id: "ag_2", a2a_url: "https://a2a.noclick.com/ag_2" }));
  assert.equal((await nc.Agent.get("ag_2")).a2aUrl, "https://a2a.noclick.com/ag_2");
});

test("a channel's limits, why it halted, and members added and removed the way Python names them", async () => {
  const { api } = setup();
  api.on("GET", "/v1/channels/ch_1", json(CHANNEL));
  const add = api.on("POST", "/v1/channels/ch_1/members", json({ id: "mem_3", type: "a2a", a2a_url: "https://p.ai/a2a", a2a_header_names: ["Authorization"], name: "partner" }));
  const remove = api.on("DELETE", "/v1/channels/ch_1/members/mem_1", json({ ok: true }));
  const removeA2A = api.on("DELETE", "/v1/channels/ch_1/members/mem_2", json({ ok: true }));
  const channel = await nc.Channel.get("ch_1");
  assert.deepEqual([channel.maxAgentTurns, channel.budgetUsd, channel.haltReason], [6, 2.5, "agent_turn_limit"]);

  const partner = await channel.add(new nc.A2AMember("https://p.ai/a2a", { headers: { Authorization: "Bearer s" }, name: "partner" }));
  assert.deepEqual(add.last.body, { a2a_url: "https://p.ai/a2a", a2a_headers: { Authorization: "Bearer s" }, name: "partner" });
  assert.deepEqual(partner.a2aHeaderNames, ["Authorization"]);

  // The agent or URL you added is found among the members by what it is.
  await channel.remove(nc.Agent.fromId("ag_1"));
  assert.equal(remove.count, 1);
  await channel.remove("https://b.ai/a2a");
  assert.equal(removeA2A.count, 1);
  await assert.rejects(channel.remove("https://nobody.ai/a2a"), /is not a member of channel ch_1/);

  // The 0.2.0 names still do the same.
  await channel.addMember(new nc.A2AMember("https://p.ai/a2a"));
  assert.deepEqual(add.last.body, { a2a_url: "https://p.ai/a2a" });
  await channel.removeMember("mem_1");
  assert.equal(remove.count, 2);
});

test("listen is stream's old name", async () => {
  const { api } = setup();
  api.on("GET", "/v1/channels/ch_1", json(CHANNEL));
  api.on("GET", "/v1/channels/ch_1/messages", json(listing([{
    object: "channel_message", id: "msg_1", channel_id: "ch_1", author: { type: "user", id: null, name: "Ana" }, text: "hi",
    created_at: "2026-09-25T10:00:00Z",
  }])));
  const channel = await nc.Channel.get("ch_1");
  for await (const message of channel.listen({ waitS: 1 })) {
    const author: nc.ChannelAuthor = message.author;
    assert.deepEqual([message.id, author.type, author.name], ["msg_1", "user", "Ana"]);
    break;
  }
});

test("a connection's last change and console page", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/gmail", json({
    object: "connection", id: "con_1", name: "gmail", integration: "gmail", status: "connected", user_id: USER_ID,
    created_at: "2026-09-25T10:00:00Z", updated_at: "2026-09-26T08:30:00Z",
  }));
  const gmail = await nc.Connection.get("gmail");
  assert.equal(gmail.updatedAt?.toISOString(), "2026-09-26T08:30:00.000Z");
  // Off the hosted API there's no console to link to.
  assert.equal(gmail.consoleUrl, null);
  assert.equal(new nc.NoClick({ apiKey: "nk_live_x" }).consoleUrl("resources", "connections"), `${nc.CONSOLE_BASE_URL}/resources/connections`);
});

test("a sandbox's size and image, and whether a command exited 0", async () => {
  const { api } = setup();
  api.on("GET", "/v1/sandboxes/sb_1", json({
    object: "sandbox", id: "sb_1", status: "running", image: "python", timeout_s: 600, cpu: 1.5, memory_mb: 2048,
    created_at: "2026-09-25T10:00:00Z", expires_at: "2026-09-25T10:10:00Z",
  }));
  api.on("POST", "/v1/sandboxes/sb_1/exec",
    json({ stdout: "3\n", stderr: "", exit_code: 0 }), json({ stdout: "", stderr: "boom", exit_code: 1 }));
  const sandbox = await nc.Sandbox.get("sb_1");
  assert.deepEqual([sandbox.image, sandbox.timeoutS, sandbox.cpu, sandbox.memoryMb], ["python", 600, 1.5, 2048]);
  assert.equal(sandbox.createdAt?.toISOString(), "2026-09-25T10:00:00.000Z");
  assert.equal(((await sandbox.exec("python -c 'print(1 + 2)'")) as nc.ExecResult).ok, true);
  assert.equal(((await sandbox.exec("false")) as nc.ExecResult).ok, false);
});

test("a browser's time limit", async () => {
  const { api } = setup();
  api.on("GET", "/v1/browsers/br_1", json({ object: "browser", id: "br_1", status: "running", timeout_s: 900, user_id: USER_ID }));
  assert.equal((await nc.Browser.get("br_1")).timeoutS, 900);
});

test("a held tool call's approval link, and handle's old name", async () => {
  const { api } = setup();
  const held = { approval_id: "apr_1", approve_url: "https://noclick.com/approve/apr_1", approver: "owner" };
  api.on("POST", "/v1/toolkits/call", json({ name: "search", content: "held", is_error: true, approval_required: held }));
  const toolkit = new nc.Toolkit(["search"]);
  const result = await toolkit.call("search", { query: "x" });
  assert.equal(result.approveUrl, "https://noclick.com/approve/apr_1");
  const content = [{ type: "tool_use", id: "tu_1", name: "search", input: { query: "x" } }];
  assert.deepEqual(await toolkit.handleAnthropic(content), await toolkit.handle(content));
});

test("whether an app's email sends now", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1/email",
    json({ object: "project_email", status: "pending_dns" }), json({ object: "project_email", status: "active" }));
  const app = nc.Project.fromId("prj_1");
  assert.equal((await app.email.status()).canSend, false);
  assert.equal((await app.email.status()).canSend, true);
});

test("one app's line in the analytics summary, 0 for one it didn't cover", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/analytics/summary", json({
    object: "project_analytics_summary", period: "7d", tz: "UTC", sampled: false,
    data: [{ project_id: "prj_1", requests: 1204, browser_requests: 1100, errors: 3, noclick_requests: 12 }],
  }));
  const week = await nc.Project.analyticsSummary();
  assert.deepEqual(week.of(nc.Project.fromId("prj_1")),
    { projectId: "prj_1", requests: 1204, errors: 3, browserRequests: 1100, noclickRequests: 12 });
  assert.deepEqual(week.of("prj_9"),
    { projectId: "prj_9", requests: 0, errors: 0, browserRequests: 0, noclickRequests: 0 });
});

test("usage() is the account's spend, and get() finds one group", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/usage", json({
    period: "month", total_usd: 25.04, group_by: "agent", groups: [{ id: "ag_1", usd: 25.04, events: 812 }],
  }));
  const month = await nc.usage({ groupBy: "agent" });
  assert.equal(read.last.query.get("group_by"), "agent");
  assert.equal(month.get("ag_1")?.usd, 25.04);
  assert.equal(month.get("ag_9"), null);
  assert.deepEqual(month.group("ag_9"), { id: "ag_9", usd: 0, events: 0, raw: {} });
  // The 0.2.0 static reads the same.
  assert.equal((await nc.Usage.get({ groupBy: "agent" })).totalUsd, 25.04);
});
