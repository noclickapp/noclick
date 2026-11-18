import assert from "node:assert/strict";
import { test } from "node:test";
import { inspect } from "node:util";

import * as nc from "../src/index.ts";
import { MockApi, USER_ID, apiError, json, listing, operation, setup, userRow } from "./helpers.ts";

const HOSTED = "https://noclick.com/dashboard/developers";
const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: "2026-09-26T12:00:00Z",
  budget_usd_per_month: 50, created_at: "2026-09-25T10:00:00Z",
};

/** A client on the hosted base URL, over the mock API. */
function hosted(api: MockApi) {
  const client = nc.configure({ apiKey: "nk_live_test", baseUrl: nc.DEFAULT_BASE_URL, maxRetries: 0, fetch: api.fetch });
  return client;
}

// --- token provider ------------------------------------------------------------

test("an apiKey function is asked for the bearer on every attempt", async () => {
  const api = new MockApi();
  const route = api.on("GET", "/v1/users", apiError(503, "server_error"), json(listing([userRow()])));
  const issued: string[] = [];
  const client = new nc.NoClick({
    baseUrl: "https://api.test",
    maxRetries: 1,
    fetch: api.fetch,
    apiKey: async () => {
      issued.push(`jwt_${issued.length + 1}`);
      return issued.at(-1) as string;
    },
  });
  client._sleep = async () => {};
  await nc.User.list({ client });
  assert.deepEqual(issued, ["jwt_1", "jwt_2"]);
  assert.deepEqual(route.calls.map((c) => c.headers.get("authorization")), ["Bearer jwt_1", "Bearer jwt_2"]);
});

test("a synchronous provider works, and one that returns nothing is Unauthenticated", async () => {
  const api = new MockApi();
  const route = api.on("GET", "/v1/brand", json({ object: "brand", name: "Acme" }));
  const client = new nc.NoClick({ baseUrl: "https://api.test", fetch: api.fetch, apiKey: () => "jwt_sync" });
  await nc.Brand.get({ client });
  assert.equal(route.last.headers.get("authorization"), "Bearer jwt_sync");
  const empty = new nc.NoClick({ baseUrl: "https://api.test", fetch: api.fetch, apiKey: () => "" });
  await assert.rejects(nc.Brand.get({ client: empty }), nc.Unauthenticated);
  assert.equal(route.count, 1);
});

test("a static key is still sent as is", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/brand", json({ object: "brand" }));
  await nc.Brand.get();
  assert.equal(route.last.headers.get("authorization"), "Bearer nk_live_test");
});

// --- pages and user filters ------------------------------------------------------

test("listPage returns one page and its nextCursor; list still drains", async () => {
  const { api } = setup();
  const route = api.on(
    "GET", "/v1/users",
    json(listing([userRow({ id: "a" })], "c2")),
    json(listing([userRow({ id: "b" })])),
  );
  const page = await nc.User.listPage({ limit: 1, q: "ac", status: "suspended" });
  assert.deepEqual(page.data.map((u) => u.id), ["a"]);
  assert.equal(page.nextCursor, "c2");
  assert.equal(route.last.query.get("limit"), "1");
  assert.equal(route.last.query.get("q"), "ac");
  assert.equal(route.last.query.get("status"), "suspended");
  assert.equal(route.last.query.get("cursor"), null);

  const next = await nc.User.listPage({ cursor: page.nextCursor });
  assert.deepEqual(next.data.map((u) => u.id), ["b"]);
  assert.equal(next.nextCursor, null);
  assert.equal(route.last.query.get("cursor"), "c2");

  const all = api.on("GET", "/v1/users", json(listing([userRow({ id: "a" })], "c2")), json(listing([userRow({ id: "b" })])));
  assert.deepEqual((await nc.User.list()).map((u) => u.id), ["a", "b"]);
  assert.equal(all.count, 2);
});

test("userFilter sends user_id and never the header, even inside asUser", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/agents", json(listing([AGENT])));
  await nc.asUser("user_42", async () => {
    await nc.Agent.listPage({ userFilter: nc.ALL_USERS });
  });
  assert.equal(route.last.query.get("user_id"), "all");
  assert.equal(route.last.headers.get("NoClick-User"), null);

  await nc.Agent.list({ userFilter: nc.NO_USER });
  assert.equal(route.last.query.get("user_id"), "none");
  await nc.Agent.list({ userFilter: "acme" });
  assert.equal(route.last.query.get("user_id"), "acme");
  await nc.Agent.list({ userFilter: nc.User.fromId(USER_ID) });
  assert.equal(route.last.query.get("user_id"), USER_ID);
  await nc.Agent.list({ userFilter: "auth0|123" });
  assert.equal(route.last.query.get("user_id"), "auth0|123");
  assert.equal(route.count, 5);
});

test("the user option is still the header, and all and none are filters, never a user's id", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/agents", json(listing([AGENT])));
  await nc.Agent.list({ user: "acme" });
  assert.equal(route.last.headers.get("NoClick-User"), "acme");
  assert.equal(route.last.query.get("user_id"), null);
  await assert.rejects(nc.Agent.list({ user: "all" }), nc.InvalidRequest);
  await assert.rejects(nc.Agent.list({ user: "none" }), nc.InvalidRequest);
  await assert.rejects(nc.Agent.list({ userFilter: "org/42" }), nc.InvalidRequest);
  await assert.rejects(nc.Agent.list({ user: "acme", userFilter: nc.ALL_USERS }), TypeError);
  assert.equal(route.count, 1);
});

test("rows from a filtered read act for their own user, account rows for the account", async () => {
  const { api } = setup();
  api.on("GET", "/v1/sandboxes", json(listing([
    { object: "sandbox", id: "sb_1", status: "running", user_id: USER_ID },
    { object: "sandbox", id: "sb_2", status: "running", user_id: null },
  ])));
  const exec1 = api.on("POST", "/v1/sandboxes/sb_1/exec", json({ stdout: "", stderr: "", exit_code: 0 }));
  const exec2 = api.on("POST", "/v1/sandboxes/sb_2/exec", json({ stdout: "", stderr: "", exit_code: 0 }));
  const [owned, account] = await nc.Sandbox.list({ userFilter: nc.ALL_USERS });
  await owned.exec("true");
  await account.exec("true");
  assert.equal(exec1.last.headers.get("NoClick-User"), USER_ID);
  assert.equal(exec2.last.headers.get("NoClick-User"), null);
});

test("every owned resource pages with a user filter", async () => {
  const { api } = setup();
  const cases: [string, () => Promise<nc.Page<unknown>>][] = [
    ["/v1/connections", () => nc.Connection.listPage({ userFilter: "acme", limit: 5 })],
    ["/v1/channels", () => nc.Channel.listPage({ userFilter: "acme", limit: 5, status: "open" })],
    ["/v1/sandboxes", () => nc.Sandbox.listPage({ userFilter: "acme", limit: 5, status: "live" })],
    ["/v1/inboxes", () => nc.Inbox.listPage({ userFilter: "acme", limit: 5 })],
    ["/v1/phone_numbers", () => nc.PhoneNumber.listPage({ userFilter: "acme", limit: 5 })],
  ];
  for (const [path, call] of cases) {
    const route = api.on("GET", path, json(listing([{ id: "x_1", user_id: USER_ID }], "next")));
    const page = await call();
    assert.equal(page.data.length, 1, path);
    assert.equal(page.nextCursor, "next", path);
    assert.equal(route.last.query.get("user_id"), "acme", path);
    assert.equal(route.last.query.get("limit"), "5", path);
    assert.equal(route.last.headers.get("NoClick-User"), null, path);
  }
});

// --- operations -----------------------------------------------------------------

test("Operation.listPage maps every filter to its query parameter", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/operations", json(listing([operation({ kind: "agent.message", status: "running" })], "c9")));
  const agent = nc.Agent.fromId("ag_1");
  const page = await nc.Operation.listPage({
    kind: ["agent.message", "sandbox.exec"],
    status: "live",
    statusNot: ["succeeded", "canceled"],
    agent,
    key: "nk_live_ab12",
    createdAfter: new Date("2026-09-25T00:00:00Z"),
    createdBefore: "2026-09-26T00:00:00Z",
    updatedAfter: new Date("2026-09-25T12:00:00Z"),
    userFilter: "acme",
    limit: 50,
  });
  const q = route.last.query;
  assert.equal(q.get("kind"), "agent.message,sandbox.exec");
  assert.equal(q.get("status"), "live");
  assert.equal(q.get("status_not"), "succeeded,canceled");
  assert.equal(q.get("agent_id"), "ag_1");
  assert.equal(q.get("key_id"), "nk_live_ab12");
  assert.equal(q.get("created_after"), "2026-09-25T00:00:00.000Z");
  assert.equal(q.get("created_before"), "2026-09-26T00:00:00Z");
  assert.equal(q.get("updated_after"), "2026-09-25T12:00:00.000Z");
  assert.equal(q.get("user_id"), "acme");
  assert.equal(q.get("limit"), "50");
  assert.equal(page.nextCursor, "c9");
  assert.equal(page.data[0].status, "running");
});

test("Operation.summary and the console view fields", async () => {
  const { api } = setup();
  const summary = api.on("GET", "/v1/operations/summary", json({
    total: 3, by_status: { queued: 0, running: 1, awaiting_human: 0, succeeded: 1, failed: 1, canceled: 0, expired: 0 },
  }));
  const result = await nc.Operation.summary({ kind: "agent.message", agent: "ag_1", createdAfter: "2026-09-25T00:00:00Z" });
  assert.equal(result.total, 3);
  assert.equal(result.byStatus.failed, 1);
  assert.equal(summary.last.query.get("agent_id"), "ag_1");
  assert.equal(summary.last.query.get("kind"), "agent.message");

  api.on("GET", "/v1/operations/op_1", json(operation({
    kind: "agent.message", status: "canceled", summary: "hi there", user_id: USER_ID, key_id: "key_1", agent_id: "ag_1",
    input: { text: "hi there" }, started_at: "2026-09-25T10:00:01Z", finished_at: "2026-09-25T10:00:04Z",
    wait_ms: 120, run_ms: 2720, held_ms: 0,
    events: [{ status: "queued", at: "2026-09-25T10:00:00Z" }, { status: "canceled", at: "2026-09-25T10:00:04Z", by: "owner" }],
  })));
  const op = await nc.Operation.fromId("op_1").hydrate();
  assert.equal(op.summaryText, "hi there");
  assert.equal(op.userId, USER_ID);
  assert.equal(op.keyId, "key_1");
  assert.equal(op.agentId, "ag_1");
  assert.deepEqual(op.input, { text: "hi there" });
  assert.equal(op.startedAt?.toISOString(), "2026-09-25T10:00:01.000Z");
  assert.equal(op.finishedAt?.toISOString(), "2026-09-25T10:00:04.000Z");
  assert.deepEqual([op.waitMs, op.runMs, op.heldMs], [120, 2720, 0]);
  assert.deepEqual(op.transitions.map((t) => [t.status, t.by]), [["queued", null], ["canceled", "owner"]]);
});

test("an operation recorded before timings existed reads null timings", async () => {
  const { api } = setup();
  api.on("GET", "/v1/operations/op_1", json(operation({ events: [], wait_ms: null, run_ms: null, held_ms: null })));
  const op = await nc.Operation.fromId("op_1").hydrate();
  assert.deepEqual([op.waitMs, op.runMs, op.heldMs, op.transitions.length], [null, null, null, 0]);
});

test("operation.toolCalls() reads the turn's calls as ToolCalls", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/operations/op_1/tool_calls", json(listing([{
    object: "tool_call", id: "tc_1", tool_name: "gmail.send_email", tool_type: "node_op", operation: "send_email",
    status: "success", error: null, arguments: { to: "a@b.c" }, result_preview: "sent", duration_ms: 42,
    credential_id: "cred_1", user_id: USER_ID, agent_id: "ag_1", conversation: "c1", execution_id: "ex_1",
    source: "agent", created_at: "2026-09-25T10:00:02Z",
  }])));
  const calls = await nc.Operation.fromId("op_1", { user: null }).toolCalls();
  assert.equal(route.count, 1);
  assert.equal(calls[0] instanceof nc.ToolCall, true);
  assert.equal(calls[0].toolName, "gmail.send_email");
  assert.deepEqual(calls[0].arguments, { to: "a@b.c" });
  assert.equal(calls[0].durationMs, 42);
  assert.equal(calls[0].createdAt?.toISOString(), "2026-09-25T10:00:02.000Z");
});

// --- console URLs ---------------------------------------------------------------

test("operations inspect with their console URL on the hosted API only", async () => {
  const api = new MockApi();
  hosted(api);
  const op = nc.Operation.fromId("op_1");
  assert.equal(op.consoleUrl, `${HOSTED}/operations?op=op_1`);
  assert.match(inspect(op), /consoleUrl: "https:\/\/noclick\.com\/dashboard\/developers\/operations\?op=op_1"/);

  setup();
  const local = nc.Operation.fromId("op_1");
  assert.equal(local.consoleUrl, null);
  assert.equal(inspect(local), 'Operation { id: "op_1" }');
});

test("errors raised by wait() name the console page on the hosted API", async () => {
  const api = new MockApi();
  hosted(api);
  api.on("GET", "/v1/operations/op_1/wait", json(operation({
    kind: "agent.message", status: "failed", error: { type: "spend_cap_exceeded", message: "User cap reached.", scope: "user" },
  })));
  const err = await nc.Operation.fromId("op_1").wait().catch((e: unknown) => e);
  assert.ok(err instanceof nc.SpendCapExceeded);
  assert.equal(err.message, `User cap reached. See ${HOSTED}/operations?op=op_1`);
  assert.equal(err.scope, "user");

  api.on("GET", "/v1/operations/op_2/wait", json(operation({ id: "op_2", status: "canceled" })));
  await assert.rejects(nc.Operation.fromId("op_2").wait(), (e: unknown) =>
    e instanceof nc.OperationCanceled && e.message === `Operation op_2 canceled. See ${HOSTED}/operations?op=op_2`);

  api.on("GET", "/v1/operations/op_3", json(operation({ id: "op_3", status: "running" })));
  await assert.rejects(nc.Operation.fromId("op_3").wait({ timeoutS: 0 }), (e: unknown) =>
    e instanceof nc.OperationTimeout && e.message.endsWith(`See ${HOSTED}/operations?op=op_3`));
});

test("errors off the hosted API keep their message", async () => {
  const { api } = setup();
  api.on("GET", "/v1/operations/op_1/wait", json(operation({ status: "failed", error: { type: "policy_denied", message: "Denied." } })));
  await assert.rejects(nc.Operation.fromId("op_1").wait(), (e: unknown) => e instanceof nc.PolicyDenied && e.message === "Denied.");
});

test("agents and users have console URLs on the hosted API", async () => {
  const api = new MockApi();
  hosted(api);
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  assert.equal((await nc.Agent.get("ag_1")).consoleUrl, `${HOSTED}/agents/ag_1`);
  assert.equal(nc.User.fromId(USER_ID).consoleUrl, `${HOSTED}/users/${USER_ID}`);
  setup();
  assert.equal(nc.User.fromId(USER_ID).consoleUrl, null);
});

// --- tool calls, requests, humans -----------------------------------------------------

test("a tool call through a hosted MCP server names it", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/tool_calls", json(listing([{
    id: "tc_2", tool_name: "hubspot.create_contact", status: "success", source: "mcp_server", mcp_server_id: "mcp_1",
  }])));
  const [call] = await nc.ToolCall.list({ source: "mcp_server" });
  assert.equal(route.last.query.get("source"), "mcp_server");
  assert.deepEqual([call.source, call.mcpServerId], ["mcp_server", "mcp_1"]);
});

test("ToolCall.listPage and summary", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/tool_calls", json(listing([{ id: "tc_1", tool_name: "search", status: "error", error: "boom" }], "n")));
  const page = await nc.ToolCall.listPage({
    tool: "gmail.*", status: "error", source: "agent", agent: "ag_1", userFilter: nc.ALL_USERS,
    since: new Date("2026-09-25T00:00:00Z"), until: "2026-09-26T00:00:00Z", limit: 200,
  });
  const q = route.last.query;
  assert.deepEqual(
    [q.get("tool"), q.get("status"), q.get("source"), q.get("agent_id"), q.get("user_id"), q.get("since"), q.get("until"), q.get("limit")],
    ["gmail.*", "error", "agent", "ag_1", "all", "2026-09-25T00:00:00.000Z", "2026-09-26T00:00:00Z", "200"],
  );
  assert.equal(page.data[0].error, "boom");
  assert.equal(page.nextCursor, "n");

  const summary = api.on("GET", "/v1/tool_calls/summary", json({ total: 1204, success: 1195, error: 9 }));
  const counts = await nc.ToolCall.summary({ agent: "ag_1", since: "2026-09-25T00:00:00Z" });
  assert.deepEqual([counts.total, counts.success, counts.error], [1204, 1195, 9]);
  assert.equal(summary.last.query.get("agent_id"), "ag_1");
});

test("ApiRequest.listPage", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/requests", json(listing([{
    id: "rq_1", actor: "key", key_id: "key_1", method: "POST", route: "/v1/policy", path_params: {}, status: 422,
    error_type: "invalid_request", duration_ms: 12, idempotency_replayed: true, operation_id: null, request_id: "req_9",
    created_at: "2026-09-25T10:00:00Z",
  }])));
  const page = await nc.ApiRequest.listPage({ method: "POST", status: "4xx", key: "nk_live_ab12", route: "/v1/policy", errorType: "invalid_request" });
  const q = route.last.query;
  assert.deepEqual([q.get("method"), q.get("status"), q.get("key_id"), q.get("route"), q.get("error_type")], ["POST", "4xx", "nk_live_ab12", "/v1/policy", "invalid_request"]);
  const row = page.data[0];
  assert.deepEqual([row.status, row.route, row.idempotencyReplayed, row.errorType], [422, "/v1/policy", true, "invalid_request"]);
});

test("HumanRequest.listPage builds lazy operations from request views", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/humans/requests", json(listing([{
    object: "human_request", id: "hr_1", kind: "approve", status: "pending", operation_id: "op_7",
    message: "Send it?", user_id: null, url: "https://noclick.com/h/hr_1", owner_can_answer: true,
  }])));
  const page = await nc.HumanRequest.listPage({ status: "pending", kind: "approve", answerable: "owner", statusNot: ["expired"], userFilter: nc.ALL_USERS });
  const q = route.last.query;
  assert.deepEqual([q.get("status"), q.get("kind"), q.get("answerable"), q.get("status_not"), q.get("user_id")], ["pending", "approve", "owner", "expired", "all"]);
  const request = page.data[0];
  assert.equal(request.id, "op_7");
  assert.equal(request.requestId, "hr_1");
  assert.equal(request.requestStatus, "pending");
  assert.equal(request.url, "https://noclick.com/h/hr_1");
  assert.equal(request.request.owner_can_answer, true);
  api.on("GET", "/v1/operations/op_7/wait", json(operation({ id: "op_7", kind: "human.approve", status: "succeeded", result: { approved: true } })));
  assert.equal(await request.wait(), true);
});

// --- agents, policy, brand, usage ---------------------------------------------------

test("agent conversations page with a user filter, and budget updates", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const route = api.on("GET", "/v1/agents/ag_1/conversations", json(listing([{
    conversation: "c1", user_id: USER_ID, title: "Refund", preview: "Can I…", turns: 4, cost_usd: 0.42, last_activity: "2026-09-25T11:00:00Z",
  }], "k")));
  const agent = nc.Agent.fromId("ag_1");
  const page = await agent.conversationsPage({ userFilter: nc.ALL_USERS, limit: 20 });
  assert.equal(route.last.query.get("user_id"), "all");
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.equal(page.nextCursor, "k");
  assert.deepEqual([page.data[0].conversation, page.data[0].turns, page.data[0].costUsd], ["c1", 4, 0.42]);
  assert.equal(page.data[0].lastActivity?.toISOString(), "2026-09-25T11:00:00.000Z");

  const drained = api.on("GET", "/v1/agents/ag_1/conversations", json(listing([{ conversation: "c1" }], "k")), json(listing([{ conversation: "c2" }])));
  assert.deepEqual((await agent.conversations({ user: "acme" })).map((c) => c.conversation), ["c1", "c2"]);
  assert.equal(drained.last.headers.get("NoClick-User"), "acme");

  assert.equal(agent.budgetUsdPerMonth, 50);
  assert.equal(agent.expiresAt?.toISOString(), "2026-09-26T12:00:00.000Z");
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({ ...AGENT, budget_usd_per_month: null }));
  await agent.update({ budgetUsdPerMonth: null });
  assert.deepEqual(patch.last.body, { budget_usd_per_month: null });
});

test("Policy.list and Policy.evaluate", async () => {
  const { api } = setup();
  api.on("GET", "/v1/policies", json(listing([
    { object: "policy", user_id: null, allow: [], deny: ["*.delete_*"], require_approval: [] },
    { object: "policy", user_id: USER_ID, allow: ["gmail.*"], deny: [], require_approval: [] },
  ])));
  const policies = await nc.Policy.list();
  assert.deepEqual(policies.map((p) => [p.userId, p.allow]), [[null, []], [USER_ID, ["gmail.*"]]]);

  const route = api.on("POST", "/v1/policy/evaluate", json({ results: [
    { tool: "gmail.send_email", verdict: "approval", matched_pattern: "gmail.*", layer: "user" },
  ] }));
  const verdicts = await nc.Policy.evaluate(["gmail__send_email"], {
    user: "acme", draft: { layer: "user", requireApproval: ["gmail.*"] },
  });
  assert.deepEqual(route.last.body, {
    tools: ["gmail__send_email"], user_id: "acme",
    draft: { layer: "user", allow: [], deny: [], require_approval: ["gmail.*"] },
  });
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.deepEqual([verdicts[0].tool, verdicts[0].verdict, verdicts[0].matchedPattern, verdicts[0].layer], ["gmail.send_email", "approval", "gmail.*", "user"]);

  await nc.Policy.evaluate("search");
  assert.deepEqual(route.last.body, { tools: ["search"] });
  await nc.asUser("user_9", () => nc.Policy.evaluate("search"));
  assert.deepEqual(route.last.body, { tools: ["search"], user_id: "user_9" });
  await nc.asUser("user_9", () => nc.Policy.evaluate("search", { user: null }));
  assert.deepEqual(route.last.body, { tools: ["search"] });
});

test("Brand.reset deletes the brand, returns the default and isDefault reads the view", async () => {
  const { api } = setup();
  const del = api.on("DELETE", "/v1/brand", json({ object: "brand", name: null, color: null, is_default: true }));
  const reset = await nc.Brand.reset();
  assert.equal(del.count, 1);
  assert.ok(reset instanceof nc.Brand);
  assert.equal(reset.isDefault, true);
  assert.equal(reset.name, null);
  api.on("GET", "/v1/brand", json({ object: "brand", name: "NoClick", is_default: true }));
  assert.equal((await nc.Brand.get()).isDefault, true);
});

test("Usage.series and Usage.limits", async () => {
  const { api } = setup();
  const series = api.on("GET", "/v1/usage/series", json({
    object: "usage_series", interval: "day", from: "2026-09-01T00:00:00Z", to: "2026-10-01T00:00:00Z", total_usd: 12.5,
    series: [{ id: "key_1", label: "Console", total_usd: 12.5, events: 3, points: [{ t: "2026-09-02T00:00:00Z", usd: 12.5, events: 3 }] }],
  }));
  const result = await nc.Usage.series({
    from: new Date("2026-09-01T00:00:00Z"), to: "2026-10-01T00:00:00Z", groupBy: "key", key: "nk_live_ab12",
    agent: "ag_1", userFilter: nc.NO_USER, interval: "day",
  });
  const q = series.last.query;
  assert.deepEqual(
    [q.get("from"), q.get("to"), q.get("group_by"), q.get("key_id"), q.get("agent_id"), q.get("user_id"), q.get("interval")],
    ["2026-09-01T00:00:00.000Z", "2026-10-01T00:00:00Z", "key", "nk_live_ab12", "ag_1", "none", "day"],
  );
  assert.equal(result.totalUsd, 12.5);
  assert.equal(result.series[0].label, "Console");
  assert.equal(result.series[0].points[0].t?.toISOString(), "2026-09-02T00:00:00.000Z");

  api.on("GET", "/v1/usage/limits", json({
    period_start: "2026-09-01T00:00:00Z", resets_at: "2026-10-01T00:00:00Z",
    keys: [{ id: "key_1", name: "Console", cap: 50, spent: 12.5 }],
    users: [{ id: "acme", cap: 10, spent: 11.2 }],
    agents: [{ id: "ag_1", name: "support", budget: 20, spent: 3, subtree_spent: 4 }],
  }));
  const limits = await nc.Usage.limits();
  assert.deepEqual([limits.keys[0].name, limits.keys[0].cap, limits.keys[0].spent], ["Console", 50, 12.5]);
  assert.deepEqual([limits.users[0].id, limits.users[0].cap, limits.users[0].spent], ["acme", 10, 11.2]);
  assert.deepEqual([limits.agents[0].budget, limits.agents[0].subtreeSpent], [20, 4]);
  assert.equal(limits.resetsAt?.toISOString(), "2026-10-01T00:00:00.000Z");
});

// --- verifier round: kind-pinned subclasses, required numbers, stuck providers ---------

test("ConnectLink.list, listPage and summary read only credential.connect operations", async () => {
  const { api } = setup();
  const all = api.on("GET", "/v1/operations", json(listing([operation({ kind: "credential.connect" })])));
  const listed = await nc.ConnectLink.list({ status: "live" });
  assert.equal(all.last.query.get("kind"), "credential.connect");
  assert.equal(all.last.query.get("status"), "live");
  assert.deepEqual(listed.map((op) => op.kind), ["credential.connect"]);

  const rows = api.on("GET", "/v1/operations", json(listing([operation({ kind: "credential.connect" })], "k")));
  const page = await nc.ConnectLink.listPage({ limit: 5 });
  assert.equal(rows.last.query.get("kind"), "credential.connect");
  assert.equal(rows.last.query.get("limit"), "5");
  assert.equal(page.nextCursor, "k");

  const summary = api.on("GET", "/v1/operations/summary", json({ total: 2, by_status: { awaiting_human: 2 } }));
  assert.equal((await nc.ConnectLink.summary()).total, 2);
  assert.equal(summary.last.query.get("kind"), "credential.connect");

  const asked = { kind: "agent.message" } as unknown as nc.KindScopedFilters;
  await assert.rejects(nc.ConnectLink.list(asked), (err: Error) => err instanceof TypeError && /Operation\.list\b/.test(err.message));
  await assert.rejects(nc.ConnectLink.listPage(asked), (err: Error) => err instanceof TypeError && /Operation\.listPage/.test(err.message));
  await assert.rejects(nc.ConnectLink.summary(asked), (err: Error) => err instanceof TypeError && /Operation\.summary/.test(err.message));
  assert.equal(summary.count, 1);
});

test("HumanRequest.summary counts only human-request operations", async () => {
  const { api } = setup();
  const summary = api.on("GET", "/v1/operations/summary", json({ total: 4, by_status: { awaiting_human: 3, succeeded: 1 } }));
  const result = await nc.HumanRequest.summary({ status: "live" });
  assert.equal(result.total, 4);
  assert.equal(summary.last.query.get("kind"), "human.ask,human.approve,human.notify");
  assert.equal(summary.last.query.get("status"), "live");
  await assert.rejects(
    nc.HumanRequest.summary({ kind: "ask" } as unknown as nc.KindScopedFilters),
    (err: Error) => err instanceof TypeError && /HumanRequest\.summary reads only/.test(err.message),
  );
  assert.equal(summary.count, 1);
});

test("a user's own agent read with userFilter goes out as an owner read (no user header)", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json({ ...AGENT, user_id: USER_ID }));
  const route = api.on("GET", "/v1/agents/ag_1/conversations", json(listing([{ conversation: "c1", user_id: USER_ID }])));
  await nc.Agent.fromId("ag_1").conversationsPage({ userFilter: nc.ALL_USERS });
  assert.equal(route.last.query.get("user_id"), "all");
  assert.equal(route.last.headers.get("NoClick-User"), null);
  // Without the filter the agent's own user is the header, which any key may read.
  await nc.Agent.fromId("ag_1").conversationsPage();
  assert.equal(route.last.headers.get("NoClick-User"), USER_ID);
  assert.equal(route.last.query.get("user_id"), null);
});

test("a summary or series missing a required number is an error, never NaN", async () => {
  const { api } = setup();
  api.on("GET", "/v1/operations/summary", json({ by_status: {} }));
  await assert.rejects(nc.Operation.summary(), (err: Error) => err instanceof nc.NoClickError && /`total`/.test(err.message));
  api.on("GET", "/v1/tool_calls/summary", json({ total: 3, success: 3 }));
  await assert.rejects(nc.ToolCall.summary(), (err: Error) => err instanceof nc.NoClickError && /`error`/.test(err.message));
  api.on("GET", "/v1/usage/series", json({ interval: "day", total_usd: 1, series: [{ id: "k", total_usd: 1, points: [] }] }));
  await assert.rejects(nc.Usage.series(), (err: Error) => err instanceof nc.NoClickError && /`events`/.test(err.message));
  api.on("GET", "/v1/usage/limits", json({ keys: [], users: [], agents: [{ id: "ag_1", budget: null, spent: 1 }] }));
  await assert.rejects(nc.Usage.limits(), (err: Error) => err instanceof nc.NoClickError && /`subtree_spent`/.test(err.message));
  // Nullable numbers stay null.
  api.on("GET", "/v1/usage/limits", json({ keys: [{ id: "key_1", cap: null, spent: 0 }], users: [], agents: [] }));
  assert.deepEqual([(await nc.Usage.limits()).keys[0].cap, (await nc.Usage.limits()).keys[0].spent], [null, 0]);
});

test("a key provider that never resolves is cut off by the timeout and by abort", async () => {
  const api = new MockApi();
  const route = api.on("GET", "/v1/brand", json({ object: "brand" }));
  const stuck = new nc.NoClick({
    baseUrl: "https://api.test", fetch: api.fetch, apiKey: () => new Promise<string>(() => {}), timeoutMs: 20, maxRetries: 0,
  });
  await assert.rejects(
    nc.Brand.get({ client: stuck }),
    (err: Error) => err instanceof nc.Unauthenticated && /did not return a key within 20ms/.test(err.message),
  );

  const patient = new nc.NoClick({ baseUrl: "https://api.test", fetch: api.fetch, apiKey: () => new Promise<string>(() => {}) });
  const controller = new AbortController();
  const call = patient.request("GET", "/v1/brand", { signal: controller.signal, user: null });
  const reason = new Error("left the page");
  controller.abort(reason);
  await assert.rejects(call, (err: unknown) => err === reason);
  assert.equal(route.count, 0);
});
