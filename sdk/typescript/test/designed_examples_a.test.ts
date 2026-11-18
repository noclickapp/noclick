// What writing the examples asked of agents, people and triggers (designed, not built yet): people
// as tools and hand-offs, time, networks and shells, model usage, answering held calls from code,
// live conversations, conversation keys on triggers, one queue turn at a time, and the harness and inbox lookups.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, listing, operation, setup, userRow } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: 50,
  created_at: "2026-09-25T10:00:00Z",
};

function sse(text: string): Response {
  return new Response(text, { headers: { "content-type": "text/event-stream" } });
}

// --- definitions: time, network, shell ----------------------------------------------

test("create sends timezone, network and shell", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/agents", json({ ...AGENT, timezone: "Europe/Berlin", network: ["pypi.org"], shell: false }));
  const agent = await nc.Agent.create("support", {
    instructions: "hi", timezone: "Europe/Berlin", network: ["pypi.org", "*.npmjs.org"], shell: false,
  });
  assert.deepEqual(create.last.body, {
    name: "support", instructions: "hi", timezone: "Europe/Berlin", network: ["pypi.org", "*.npmjs.org"], shell: false,
  });
  assert.deepEqual([agent.timezone, agent.network, agent.shell], ["Europe/Berlin", ["pypi.org"], false]);
});

test("fromName converges the new fields, and null clears the timezone", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([{ ...AGENT, timezone: "UTC", network: true, shell: true }])));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({ ...AGENT, timezone: null, network: false }));
  await nc.Agent.fromName("support", { createIfMissing: true, instructions: "hi", timezone: null, network: false, shell: true }).hydrate();
  assert.deepEqual(patch.last.body, { timezone: null, network: false });
});

test("update sends network, timezone and shell; a sandbox takes a list of hosts", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({ ...AGENT, network: ["api.stripe.com"] }));
  const agent = await nc.Agent.fromId("ag_1").update({ network: ["api.stripe.com"], timezone: "America/New_York", shell: true });
  assert.deepEqual(patch.last.body, { network: ["api.stripe.com"], timezone: "America/New_York", shell: true });
  assert.deepEqual(agent.network, ["api.stripe.com"]);

  const sandbox = api.on("POST", "/v1/sandboxes", json({ object: "sandbox", id: "sb_1", status: "running", network: ["pypi.org"] }));
  const sb = await nc.Sandbox.create({ image: "python", network: ["pypi.org"] });
  assert.deepEqual(sandbox.last.body, { image: "python", network: ["pypi.org"] });
  assert.deepEqual(sb.network, ["pypi.org"]);
});

test("repos clone checkouts from a connection and a repo", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/github", json({ object: "connection", id: "cn_gh", name: "github", integration: "github", status: "connected" }));
  const create = api.on("POST", "/v1/agents", json(AGENT));
  await nc.Agent.create("fixer", {
    instructions: "hi",
    repos: [nc.Connection.fromName("github").checkout("acme/web", { push: ["agent/*"] }), nc.Repo.fromId("rp_1").checkout({ branch: "main", path: "site" })],
  });
  assert.deepEqual((create.last.body as { repos: unknown }).repos, [
    { connection: "github", repository: "acme/web", push: ["agent/*"] },
    { repo_id: "rp_1", branch: "main", path: "site" },
  ]);
});

test("a cron read in the user's timezone", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const add = api.on("POST", "/v1/agents/ag_1/triggers", json({ object: "agent_trigger", id: "tr_1", kind: "cron", spec: {} }));
  await nc.Agent.fromId("ag_1").addTrigger(new nc.Cron("0 8 * * *", { tz: "user", message: "Brief me" }));
  assert.deepEqual(add.last.body, { kind: "cron", cron: "0 8 * * *", tz: "user", message: "Brief me" });
});

// --- people as tools --------------------------------------------------------------------

test("people in tools say who they reach", async () => {
  const { api } = setup();
  api.on("GET", `/v1/users/${USER_ID}`, json(userRow()));
  const create = api.on("POST", "/v1/agents", json(AGENT));
  const ops = new nc.Human({ email: "ops@acme.com", phone: "+14155550123" });
  await nc.Agent.create("support", {
    instructions: "hi",
    tools: ["search", ops.only("notify", "ask"), new nc.Human(), nc.User.fromId(USER_ID).human.only("hand_off")],
  });
  assert.deepEqual((create.last.body as { tools: unknown }).tools, [
    "search",
    { human: { email: "ops@acme.com", phone: "+14155550123" }, tools: ["notify", "ask"] },
    { human: { user: true }, tools: ["notify", "ask", "hand_off"] },
    { human: { user_id: USER_ID }, tools: ["hand_off"] },
  ]);
  assert.throws(() => ops.only("approve" as nc.HumanTool), /notify, ask and hand_off/);
  assert.throws(() => ops.only(), TypeError);
  assert.ok(ops.only("ask") instanceof nc.HumanOperations);
});

test("handBack gives a conversation back; a conversation says when it's handed off", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const back = api.on("POST", "/v1/agents/ag_1/conversations/ticket%2F1841/hand_back", new Response(null, { status: 204 }));
  const agent = nc.Agent.fromId("ag_1");
  await agent.handBack("ticket/1841", { user: USER_ID });
  assert.equal(back.last.headers.get("NoClick-User"), USER_ID);

  api.on("GET", "/v1/agents/ag_1/conversations", json(listing([{
    conversation: "ticket-1841", user_id: USER_ID, status: "handed_off", handed_off_to: "lead@acme.com",
    model_usage: { input_tokens: 1200, output_tokens: 300, cached_tokens: 800, usd: 0.0123 },
  }])));
  const [convo] = await agent.conversations({ userFilter: nc.ALL_USERS });
  assert.deepEqual([convo.status, convo.handedOffTo, convo.modelUsage?.cachedTokens, convo.modelUsage?.usd],
    ["handed_off", "lead@acme.com", 800, 0.0123]);
});

// --- replies and live conversations ------------------------------------------------------

test("a reply carries its model usage", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("POST", "/v1/agents/ag_1/messages", json(operation({
    id: "op_m", kind: "agent.message", status: "succeeded",
    result: { text: "Done.", model_usage: { input_tokens: 10, output_tokens: 5, cached_tokens: 0, usd: 0.001 } },
  })));
  const reply = await nc.Agent.fromId("ag_1").message("hi");
  assert.deepEqual([reply.modelUsage?.inputTokens, reply.modelUsage?.outputTokens, reply.modelUsage?.usd], [10, 5, 0.001]);
});

test("watch follows a conversation, held calls included", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const route = api.on("GET", "/v1/agents/ag_1/conversations/ticket-1841/events", () => sse([
    'event: message\ndata: {"role": "person", "text": "I\'ve refunded it."}',
    'event: status\ndata: {"status": "active"}',
    'event: tool_call\ndata: {"tool": "stripe__create_refund", "operation_id": "op_7", "held": {"request_id": "hr_1", "url": "https://noclick.com/h/hr_1"}}',
    "", "",
  ].join("\n\n")));
  const events: nc.AgentEvent[] = [];
  for await (const event of nc.Agent.fromId("ag_1").watch("ticket-1841", { user: USER_ID })) events.push(event);
  assert.deepEqual(events.map((e) => [e.type, e.role, e.status]), [["message", "person", null], ["status", null, "active"], ["tool_call", null, null]]);
  assert.deepEqual([events[2].held?.url, events[2].operationId], ["https://noclick.com/h/hr_1", "op_7"]);
  assert.equal(route.last.headers.get("Accept"), "text/event-stream");
  assert.equal(route.last.headers.get("NoClick-User"), USER_ID);
});

// --- held calls: answered from code -------------------------------------------------------

test("approve and decline carry a note", async () => {
  const { api } = setup();
  api.on("GET", "/v1/humans/requests", json(listing([{ id: "hr_1", operation_id: "op_h", kind: "approve", status: "pending" }])));
  const answer = api.on("POST", "/v1/humans/requests/hr_1/answer",
    json({ id: "hr_1", kind: "approve", status: "answered", note: "Fine." }),
    json({ id: "hr_1", kind: "approve", status: "answered", note: "Ask finance." }));
  const [request] = await nc.HumanRequest.list({ status: "pending", kind: "approve" });
  assert.equal(await request.approve({ note: "Fine." }), request);
  assert.deepEqual(answer.last.body, { approved: true, note: "Fine." });
  assert.deepEqual([request.requestStatus, request.note], ["answered", "Fine."]);
  await request.decline({ note: "Ask finance." });
  assert.deepEqual(answer.last.body, { approved: false, note: "Ask finance." });
  assert.equal(request.note, "Ask finance.");
  // A request known only by its operation (no request view) can't be answered.
  await assert.rejects(nc.HumanRequest._fromView<boolean>({ operation_id: "op_h", kind: "approve" }, {}).approve(), /no request id/);
});

// --- triggers: conversation keys, one queue turn at a time ---------------------------------

test("triggers take a conversation template, and a queue's turns run one at a time", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const add = api.on("POST", "/v1/agents/ag_1/triggers", json({ object: "agent_trigger", id: "tr_1", kind: "event", spec: {} }));
  const agent = nc.Agent.fromId("ag_1");
  await agent.addTrigger(new nc.OnEvent("github", "issue.labeled", { filters: { label: "agent" }, conversation: "issue-{issue.number}" }));
  assert.deepEqual(add.last.body, {
    kind: "event", connection: "github", event: "issue.labeled", filters: { label: "agent" }, conversation: "issue-{issue.number}",
  });
  await agent.addTrigger(new nc.OnWebhook("orders", { conversation: "order-{order.id}" }));
  assert.deepEqual(add.last.body, { kind: "webhook", name: "orders", conversation: "order-{order.id}" });
  await agent.addTrigger(new nc.OnQueue("signups", { conversation: "customer-{customer_id}" }));
  assert.deepEqual(add.last.body, { kind: "queue", queue: "signups", batch_size: 1, conversation: "customer-{customer_id}" });
  // An agent takes one turn at a time: there is no concurrency to ask for, and none is sent.
  // @ts-expect-error concurrency is gone
  await agent.addTrigger(new nc.OnQueue("signups", { concurrency: 5 }));
  assert.deepEqual(add.last.body, { kind: "queue", queue: "signups", batch_size: 1 });
  assert.throws(() => new nc.OnQueue("signups", { batchSize: 10, conversation: "c-{id}" }), /batch holds several/);
});

// --- lookups: one harness, an agent's inboxes ---------------------------------------------

test("harnessInfo finds one by name; inboxes lists the inboxes that wake an agent", async () => {
  const { api } = setup();
  api.on("GET", "/v1/harnesses", json(listing([
    { object: "harness", name: "sdk", default_model: "openrouter/x", custom_models: true, model_connection: "optional", integrations: [], streaming: "tokens", shell: "code_capability" },
    { object: "harness", name: "opencode", default_model: "opencode/x", custom_models: true, model_connection: "required", integrations: ["openrouter"], streaming: "final", shell: "built_in" },
  ])));
  assert.equal((await nc.Agent.harnessInfo("opencode")).defaultModel, "opencode/x");
  await assert.rejects(nc.Agent.harnessInfo("codex"), (err: nc.NotFound) => err instanceof nc.NotFound && /sdk, opencode/.test(err.nextStep ?? ""));

  api.on("GET", "/v1/agents/ag_1", json({ ...AGENT, user_id: USER_ID }));
  const inboxes = api.on("GET", "/v1/inboxes", json(listing([{ object: "inbox", id: "inb_1", address: "help@acme.test", agent_id: "ag_1", user_id: USER_ID }])));
  const [inbox] = await nc.Agent.fromId("ag_1").inboxes();
  assert.equal(inbox.address, "help@acme.test");
  assert.equal(inboxes.last.query.get("agent_id"), "ag_1");
  assert.equal(inboxes.last.headers.get("NoClick-User"), USER_ID);
});
