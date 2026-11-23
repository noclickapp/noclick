// Drafting a workflow's steps (`Workflow.draft`): the body it sends and the result its operation settles with.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const DRAFTED = {
  object: "workflow_draft", workflow_id: "wf_1", mode: "full", version: 7, history_version: 3, changed: true,
  summary: "Changed 2 steps",
  steps: {
    fetch: { drafted: true, error: null, operation: "list_messages", settings: ["query"], unfilled: ["label_ids"],
      config_valid: true, references: [] },
    post: { drafted: false, error: "No operation fits", operation: null, settings: [], unfilled: [], config_valid: false,
      references: [{ field: "text", step: "fetch", key: "body", known_keys: ["messages"] }] },
  },
};
const operation = (status: string, result: unknown = null) => ({
  object: "operation", id: "op_d", kind: "workflow.draft", status, result, error: null,
  created_at: "2026-11-21T10:00:00Z", updated_at: "2026-11-21T10:00:00Z",
});

test("a draft names its steps, their goals and its mode", async () => {
  const { api } = setup();
  const drafts = api.on("POST", "/v1/workflows/wf_1/drafts", json(operation("queued"), { status: 202 }));
  const brief = nc.Workflow.fromId("wf_1");
  await brief.draft([brief.step("fetch"), { id: "post", goal: "Post a summary to #team" }],
    { instructions: "Every morning, summarize my email" });
  assert.deepEqual(drafts.last.body, {
    steps: [{ id: "fetch" }, { id: "post", goal: "Post a summary to #team" }], mode: "full",
    instructions: "Every morning, summarize my email",
  });
  await brief.draft(["post"], { mode: "field", field: "text" });
  assert.deepEqual(drafts.last.body, { steps: [{ id: "post" }], mode: "field", field: "text" });
});

test("a draft's result is each step's verdict", async () => {
  const { api } = setup();
  api.on("POST", "/v1/workflows/wf_1/drafts", json(operation("succeeded", DRAFTED), { status: 202 }));
  const op = await nc.Workflow.fromId("wf_1").draft(["fetch", "post"]);
  assert.equal(op.kind, "workflow.draft");
  const result = await op.wait();
  assert.deepEqual([result.version, result.historyVersion, result.changed], [7, 3, true]);
  assert.deepEqual(result.steps.fetch.unfilled, ["label_ids"]);
  assert.equal(result.steps.post.error, "No operation fits");
  assert.deepEqual((result.steps.post.references as nc.JsonObject[])[0].known_keys, ["messages"]);
});

test("a draft that writes nothing asks so and reads the edits it answers", async () => {
  const { api } = setup();
  const preview = {
    object: "workflow_draft", workflow_id: "wf_1", mode: "full", written: false, version: 7, history_version: null,
    changed: true, summary: "Changed 1 step",
    steps: { post: { drafted: true, error: null, operation: "send_message", settings: ["text"], unfilled: [],
      withheld: [], config_valid: true, references: [] } },
    edits: [{ op: "update_step", id: "post", operation: "send_message", settings: { text: "Hi" } }],
  };
  const drafts = api.on("POST", "/v1/workflows/wf_1/drafts", json(operation("succeeded", preview), { status: 202 }));
  const result = await (await nc.Workflow.fromId("wf_1").draft(["post"], { write: false })).wait();
  assert.deepEqual(drafts.last.body, { steps: [{ id: "post" }], mode: "full", write: false });
  assert.deepEqual([result.written, result.version, result.historyVersion], [false, 7, null]);
  assert.deepEqual(result.edits, preview.edits);
});

test("a written draft reads as written", async () => {
  const { api } = setup();
  api.on("POST", "/v1/workflows/wf_1/drafts", json(operation("succeeded", DRAFTED), { status: 202 }));
  const result = await (await nc.Workflow.fromId("wf_1").draft(["fetch"])).wait();
  assert.deepEqual([result.written, result.edits], [true, []]);
});
