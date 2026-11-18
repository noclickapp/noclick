import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const ANTHROPIC_TOOLS = [
  { name: "search", description: "Search the web", input_schema: { type: "object" } },
  { name: "gmail__send_email", description: "Send", input_schema: { type: "object" } },
];

function toolsApi() {
  const s = setup();
  const definitions = s.api.on("POST", "/v1/toolkits/definitions", (call: Call) =>
    json({ object: "tool_definitions", format: (call.body as { format: string }).format, tools: ANTHROPIC_TOOLS }));
  const calls = s.api.on("POST", "/v1/toolkits/call", (call: Call) => {
    const body = call.body as { name: string; arguments: { query?: string } };
    if (body.name === "gmail__send_email") {
      return json({
        object: "tool_result", name: body.name, content: "Connect Gmail first.", is_error: true,
        needs_connection: { connection: "gmail", integration: "gmail", connect_url: "https://noclick.com/c/1" },
      });
    }
    return json({
      object: "tool_result", name: body.name, is_error: false,
      content: [{ type: "text", text: `results for ${body.arguments.query}` }],
    });
  });
  return { ...s, definitions, calls };
}

test("definitions are cached per format", async () => {
  const { definitions } = toolsApi();
  const toolkit = new nc.Toolkit(["search", "gmail.send_email"]);
  assert.deepEqual(await toolkit.definitions(), ANTHROPIC_TOOLS);
  assert.deepEqual(await toolkit.definitions({ format: "anthropic" }), ANTHROPIC_TOOLS);
  assert.equal(definitions.count, 1);
  assert.deepEqual(definitions.last.body, { tools: ["search", "gmail.send_email"], format: "anthropic" });
  await toolkit.definitions({ format: "openai" });
  assert.equal(definitions.count, 2);
  assert.equal((definitions.last.body as { format: string }).format, "openai");
});

test("call returns a ToolResult; needs_connection is a normal result", async () => {
  toolsApi();
  const toolkit = new nc.Toolkit("gmail");
  const needs = await toolkit.call("gmail__send_email", { to: "a@b.c" });
  assert.equal(needs.isError, true);
  assert.equal(needs.connectUrl, "https://noclick.com/c/1");
  assert.equal(needs.needsConnection?.integration, "gmail");
  const ok = await toolkit.call("search", { query: "cake" });
  assert.equal(ok.text, "results for cake");
  assert.equal(ok.needsConnection, null);
});

test("a shared toolkit follows the current user; a pinned one does not", async () => {
  const { calls } = toolsApi();
  const shared = new nc.Toolkit(["search"]);
  for (const user of ["user_1", "user_2"]) {
    await nc.asUser(user, () => shared.call("search", { query: "x" }));
    assert.equal(calls.last.headers.get("NoClick-User"), user);
  }
  await shared.call("search", { query: "x" }, { user: "user_9" });
  assert.equal(calls.last.headers.get("NoClick-User"), "user_9");

  const pinned = new nc.Toolkit(["search"], { user: "user_42" });
  await nc.asUser("someone_else", () => pinned.call("search", { query: "x" }));
  assert.equal(calls.last.headers.get("NoClick-User"), "user_42");
});

test("handleAnthropic answers a message object or a bare content list", async () => {
  toolsApi();
  const content = [
    { type: "text", text: "Let me look." },
    { type: "tool_use", id: "toolu_1", name: "search", input: { query: "cake" } },
    { type: "tool_use", id: "toolu_2", name: "gmail__send_email", input: { to: "a@b.c" } },
  ];
  const results = await new nc.Toolkit(["search", "gmail"]).handle({ role: "assistant", content, stop_reason: "tool_use" });
  assert.deepEqual(results, [
    { type: "tool_result", tool_use_id: "toolu_1", content: [{ type: "text", text: "results for cake" }], is_error: false },
    { type: "tool_result", tool_use_id: "toolu_2", content: "Connect Gmail first.", is_error: true },
  ]);
  assert.deepEqual(await new nc.Toolkit(["search"]).handle(content), results);
});

test("handleAnthropic runs calls concurrently and keeps their order", async () => {
  const { calls } = toolsApi();
  const content = Array.from({ length: 5 }, (_, i) => ({ type: "tool_use", id: `t${i}`, name: "search", input: { query: String(i) } }));
  const results = await new nc.Toolkit(["search"]).handle(content);
  assert.deepEqual(results.map((r) => r.tool_use_id), ["t0", "t1", "t2", "t3", "t4"]);
  assert.equal(calls.count, 5);
});

test("handleOpenAI answers chat tool calls; malformed arguments never reach the API", async () => {
  const { calls } = toolsApi();
  const toolCalls = [
    { id: "call_1", type: "function", function: { name: "search", arguments: JSON.stringify({ query: "tea" }) } },
    { id: "call_2", type: "function", function: { name: "search", arguments: "{not json" } },
  ];
  const messages = await new nc.Toolkit(["search"]).handleOpenAI({ role: "assistant", tool_calls: toolCalls });
  assert.deepEqual(messages[0], { role: "tool", tool_call_id: "call_1", content: "results for tea" });
  assert.equal((messages[1] as { tool_call_id: string }).tool_call_id, "call_2");
  assert.match((messages[1] as { content: string }).content, /not valid JSON/);
  assert.equal(calls.count, 1);
});

test("handleOpenAI accepts a ChatCompletion and Responses function_call items", async () => {
  toolsApi();
  const toolkit = new nc.Toolkit(["search"]);
  const completion = {
    id: "c1", object: "chat.completion",
    choices: [{ index: 0, finish_reason: "tool_calls", message: {
      role: "assistant", content: null,
      tool_calls: [{ id: "call_7", type: "function", function: { name: "search", arguments: "{\"query\": \"jam\"}" } }],
    } }],
  };
  assert.deepEqual(await toolkit.handleOpenAI(completion), [{ role: "tool", tool_call_id: "call_7", content: "results for jam" }]);
  const items = [{ type: "function_call", call_id: "fc_1", name: "search", arguments: "{\"query\": \"figs\"}" }];
  assert.deepEqual(await toolkit.handleOpenAI(items), [{ type: "function_call_output", call_id: "fc_1", output: "results for figs" }]);
  assert.deepEqual(await toolkit.handleOpenAI({ id: "resp_1", output: items }), [{ type: "function_call_output", call_id: "fc_1", output: "results for figs" }]);
});

test("toolkit entries accept Connections (a lazy one is created first); approvalId rides the call", async () => {
  const { api, calls } = toolsApi();
  api.on("GET", "/v1/connections/gmail", apiError(404, "not_found", "No"));
  const created = api.on("POST", "/v1/connections", json({ object: "connection", id: "con_1", name: "gmail", integration: "gmail" }, { status: 201 }));
  const gmail = nc.Connection.fromName("gmail", { integration: "gmail", createIfMissing: true });
  const toolkit = new nc.Toolkit([gmail, "search"]);
  assert.deepEqual(toolkit.tools, ["gmail", "search"]);
  await toolkit.definitions();
  assert.equal(created.count, 1);
  assert.throws(() => new nc.Toolkit([{ name: "gmail" } as unknown as nc.ToolRef]), TypeError); // an IntegrationInfo is not a tool
  await toolkit.call("search", { query: "x" }, { approvalId: "ap_1" });
  assert.deepEqual(calls.last.body, { name: "search", arguments: { query: "x" }, approval_id: "ap_1" });
});

// What toolkits/service answers: a hold for someone else carries neither link, request nor operation;
// one addressed to the caller carries all three, the operation as its full object.
const HELD = { approval_id: "ap_9", request_id: null, approve_url: null, operation: null, approver: "owner" };
const HELD_FOR_YOU = {
  approval_id: "ap_8", request_id: "hr_8", approve_url: "https://noclick.com/h/hr_8", approver: "user",
  operation: {
    object: "operation", id: "op_8", kind: "human.approve", status: "awaiting_human", result: null, error: null,
    created_at: "2026-09-25T10:00:00Z", updated_at: "2026-09-25T10:00:00Z",
  },
};

function policyApi() {
  const s = setup();
  // The shapes /v1/toolkits/call answers a refused or held call with: never an HTTP error.
  s.api.on("POST", "/v1/toolkits/call", (call: Call) => {
    const name = (call.body as { name: string }).name;
    if (name === "gmail__delete_email") {
      return json({ object: "tool_result", name, content: "gmail.delete_email is denied by policy.", is_error: true });
    }
    if (name === "gmail__send_email") {
      return json({
        object: "tool_result", name, content: "This call is waiting for the account owner's approval.", is_error: true,
        approval_required: HELD,
      });
    }
    if (name === "gmail__forward_email") {
      return json({
        object: "tool_result", name, content: "This call is waiting for your approval.", is_error: true,
        approval_required: HELD_FOR_YOU,
      });
    }
    return json({ object: "tool_result", name, content: "found it", is_error: false });
  });
  return s;
}

test("a held call is an error result; its approval stays out of the model's view", async () => {
  const s = policyApi();
  const toolkit = new nc.Toolkit(["gmail", "search"]);
  const held = await toolkit.call("gmail__send_email", {});
  assert.equal(held.isError, true);
  assert.deepEqual(held.approvalRequired, HELD);
  const denied = await toolkit.call("gmail__delete_email", {});
  assert.equal(denied.isError, true);
  assert.equal(denied.approvalRequired, null);
  const yours = await toolkit.call("gmail__forward_email", {});
  assert.equal(yours.approvalRequired?.approve_url, "https://noclick.com/h/hr_8");
  // Typed as the operation object: its fields are readable, and a string id would not compile here.
  assert.equal(yours.approvalRequired?.operation?.id, "op_8");
  assert.equal(yours.approvalRequired?.operation?.object, "operation");
  assert.equal(held.approval, null);
  // Approved from your own code: the request it waits on is answered, not the policy approval.
  assert.equal(yours.approval?.requestId, "hr_8");
  const answered = s.api.on("POST", "/v1/humans/requests/hr_8/answer", json({
    object: "human_request", id: "hr_8", kind: "approve", status: "answered", note: "Fine.",
  }));
  assert.equal((await yours.approval?.approve({ note: "Fine." }))?.requestStatus, "answered");
  assert.deepEqual(answered.last.body, { approved: true, note: "Fine." });
  const blocks = await toolkit.handle([
    { type: "tool_use", id: "t1", name: "gmail__send_email", input: {} },
    { type: "tool_use", id: "t2", name: "gmail__forward_email", input: {} },
  ]);
  assert.equal(blocks[0].is_error, true);
  assert.equal(blocks[1].is_error, true);
  const seenByModel = JSON.stringify(blocks);
  for (const secret of ["ap_9", "ap_8", "hr_8", "op_8"]) assert.ok(!seenByModel.includes(secret));
});

test("the handle helpers pass held calls to onApproval", async () => {
  policyApi();
  const toolkit = new nc.Toolkit(["gmail", "search"]);
  const seen: nc.ToolResult[] = [];
  await toolkit.handle([
    { type: "tool_use", id: "t1", name: "search", input: {} },
    { type: "tool_use", id: "t2", name: "gmail__send_email", input: { to: "a@b.c" } },
  ], { onApproval: (result) => { seen.push(result); } });
  assert.deepEqual(seen.map((r) => [r.name, r.approvalRequired]), [["gmail__send_email", HELD]]);

  const messages = await toolkit.handleOpenAI([
    { id: "c1", type: "function", function: { name: "gmail__send_email", arguments: "{}" } },
    { id: "c2", type: "function", function: { name: "search", arguments: "{bad" } },
    { id: "c3", type: "function", function: { name: "gmail__delete_email", arguments: "{}" } },
  ], { onApproval: async (result) => { seen.push(result); } });
  assert.equal(seen.length, 2);
  assert.deepEqual(seen[1].approvalRequired, HELD);
  assert.deepEqual(messages.map((m) => (m as { tool_call_id: string }).tool_call_id), ["c1", "c2", "c3"]);
  assert.ok(!JSON.stringify(messages).includes("ap_9"));
});
