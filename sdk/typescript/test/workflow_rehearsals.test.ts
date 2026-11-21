// A workflow's test run (`Workflow.rehearse`): the body each call sends and how its result reads.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, operation, setup } from "./helpers.ts";

const CALL = { tool: "slack__send_message_to_channel", arguments: { channel: "#support" }, result: { ok: true } };
const REHEARSAL = {
  workflow_id: "wf_1", test_run: { key: "refund-request", name: "Refund request", custom: true },
  trigger: { step_id: "mail", type: "automation-gmail", name: "Inbox" },
  reply: "I've told the team.", tool_calls: [CALL],
  transcript: [{ role: "tool", ...CALL }, { role: "assistant", text: "I've told the team." }],
  scenario: "An ordinary working day.", note: "What it did to act was simulated.", cost_usd: 0.004,
};

test("a test run names what it plays and reads what the agent did", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/workflows/wf_1/rehearsals", json(
    operation({ id: "op_t", kind: "workflow.rehearse", status: "succeeded", result: REHEARSAL }), { status: 202 }));
  const test = await nc.Workflow.fromId("wf_1").rehearse({ testRun: "Refund request", scenario: "Order 1042 shipped late." });
  assert.deepEqual(route.last.body, { test_run: "Refund request", scenario: "Order 1042 shipped late." });
  const done = await test.wait();
  assert.deepEqual([done.reply, done.toolCalls, done.costUsd, done.operationId],
    ["I've told the team.", [CALL], 0.004, "op_t"]);
  assert.equal(done.testRun?.name, "Refund request");
  assert.equal(done.trigger?.step_id, "mail");
  assert.equal(done.note, "What it did to act was simulated.");
});

test("a message of your own is staged on a trigger step", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/workflows/wf_1/rehearsals", json(
    operation({ id: "op_t", kind: "workflow.rehearse", status: "queued" }), { status: 202 }));
  const inbox = nc.Workflow.fromId("wf_1");
  await inbox.rehearse({ trigger: inbox.step("mail"), body: "My order never came.", title: "Order 1042", author: "Ana",
    handle: "ana@example.com" });
  assert.deepEqual(route.last.body, { trigger: "mail", body: "My order never came.", title: "Order 1042", author: "Ana",
    handle: "ana@example.com" });
  await nc.asUser(USER_ID, () => inbox.rehearse({ trigger: "automation-gmail", body: "Hello?" }));
  assert.deepEqual(route.last.body, { trigger: "automation-gmail", body: "Hello?" });
  assert.equal(route.last.headers.get("NoClick-User"), USER_ID);
});
