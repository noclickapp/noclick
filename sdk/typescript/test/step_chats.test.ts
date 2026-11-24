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

test("a step's chat page turns on, off and rotates; never shared reads null", async () => {
  const { api } = setup();
  const share = { object: "share_link", url: "https://noclick.test/a/l1", enabled: true, workflow_id: "wf_1", step_id: "helper", created_at: "2026-11-24T09:00:00+00:00" };
  api.on("POST", "/v1/workflows/wf_1/steps/helper/share", json(share));
  const link = await nc.Workflow.fromId("wf_1").step("helper").share();
  assert.deepEqual([link.url, link.enabled, link.stepId, link.agentId], [share.url, true, "helper", null]);
  const off = api.on("PATCH", "/v1/workflows/wf_1/steps/helper/share", json({ ...share, enabled: false }));
  assert.equal((await link.disable()).enabled, false);
  assert.deepEqual(off.last.body, { enabled: false });
  api.on("POST", "/v1/workflows/wf_1/steps/helper/share/rotate", json({ ...share, url: "https://noclick.test/a/l2" }));
  assert.equal((await link.rotate()).url, "https://noclick.test/a/l2");
  api.on("GET", "/v1/workflows/wf_1/steps/helper/share", json({ error: { type: "not_found", message: "no" } }, { status: 404 }));
  assert.equal(await nc.Workflow.fromId("wf_1").step("helper").shareLink(), null);
});

test("workspace() lists a conversation's files and deleteWorkspaceFile() deletes one", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/workflows/wf_1/steps/helper/workspace", json({
    object: "list", data: [{ object: "workspace_file", path: "out/report.md", size_bytes: 8, modified_at: "2026-11-24T10:00:00+00:00", url: "https://api.test/f?t=1" }],
    next_cursor: null, truncated: false, workspace: "/workspace", exists: true, upload_url: "https://api.test/u?t=2",
  }));
  const space = await nc.Workflow.fromId("wf_1").step("helper").workspace("orders");
  assert.equal(listed.last.query.get("conversation"), "orders");
  assert.deepEqual([space.files.map((f) => [f.path, f.sizeBytes]), space.workspace, space.exists, space.uploadUrl],
    [[["out/report.md", 8]], "/workspace", true, "https://api.test/u?t=2"]);
  const gone = api.on("DELETE", "/v1/workflows/wf_1/steps/helper/workspace/files", json({ object: "workspace_file", path: "out/report.md", deleted: true }));
  await nc.Workflow.fromId("wf_1").step("helper").deleteWorkspaceFile("out/report.md", { conversation: "orders" });
  assert.deepEqual([gone.last.query.get("path"), gone.last.query.get("conversation")], ["out/report.md", "orders"]);
});
