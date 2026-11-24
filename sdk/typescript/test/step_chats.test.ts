// An agent step's chats (`Step.conversations`, `conversation`, `deleteConversation`, `message`): what each call sends
// and how it reads the answer.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, setup } from "./helpers.ts";

const CHAT = {
  object: "step_conversation", conversation: "orders", title: "Orders", preview: "Where's 1042?", turns: 2,
  last_activity: "2026-11-24T10:00:00+00:00", agent_model: "openrouter/x", shared: false,
};
const OP = { object: "operation", id: "op_1", kind: "workflow.run", status: "queued", result: null, error: null };

test("a step's chats are listed and read for the person, never a user", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/workflows/wf_1/steps/helper/conversations",
    json({ object: "list", data: [CHAT, { ...CHAT, conversation: "share:l:v:c", shared: true }] }));
  const chats = await nc.asUser(USER_ID, () => nc.Workflow.fromId("wf_1").step("helper").conversations({ limit: 20 }));
  assert.equal(listed.last.headers.get("NoClick-User"), null);
  assert.equal(listed.last.query.get("limit"), "20");
  assert.deepEqual(chats.map((c) => [c.conversation, c.turns, c.shared, c.messages]),
    [["orders", 2, false, null], ["share:l:v:c", 2, true, null]]);
  const messages = [{ role: "user", message: "Where's 1042?" }, { role: "assistant", message: "Shipped." }];
  api.on("GET", "/v1/workflows/wf_1/steps/helper/conversations/a%2Fb",
    json({ object: "step_conversation_thread", conversation: "a/b", messages }));
  const thread = await nc.Workflow.fromId("wf_1").step("helper").conversation("a/b");
  assert.deepEqual([thread.conversation, thread.messages], ["a/b", messages]);
});

test("deleteConversation() deletes one", async () => {
  const { api } = setup();
  const route = api.on("DELETE", "/v1/workflows/wf_1/steps/helper/conversations/orders",
    json({ object: "step_conversation", conversation: "orders", deleted: true }));
  await nc.Workflow.fromId("wf_1").step("helper").deleteConversation("orders");
  assert.equal(route.calls.length, 1);
});

test("message() says something as a run from the step", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/workflows/wf_1/steps/helper/messages",
    json({ object: "step_message", conversation: "orders", run: OP }, { status: 202 }),
    json({ object: "step_message", conversation: "__interface_chat__", run: OP }, { status: 202 }));
  const op = await nc.Workflow.fromId("wf_1").step("helper").message("Total {{ x }}", {
    conversation: "orders", model: "openrouter/x", attachments: [{ resource_id: "r1" }],
  });
  assert.deepEqual(route.last.body, { message: "Total {{ x }}", conversation: "orders", model: "openrouter/x", attachments: [{ resource_id: "r1" }] });
  assert.deepEqual([op.id, op.kind], ["op_1", "workflow.run"]);
  await nc.Workflow.fromId("wf_1").step("helper").message("hi");
  assert.deepEqual(route.last.body, { message: "hi" });
});
