// A run from one of a workflow's steps (`Workflow.run` with `fromStep` and `only`, `Step.run`): the body each call
// sends.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const RUN = {
  object: "workflow_run", id: "run_1", workflow_id: "wf_1", status: "succeeded", inputs: {},
  outputs: { Summary: { message: "Order o_9 received" } }, error: null, source: "api", user_id: null, operation_id: "op_r",
  started_at: "2026-11-21T10:00:00Z", finished_at: "2026-11-21T10:00:02Z",
};
const operation = (status: string, result: unknown = null) => ({
  object: "operation", id: "op_r", kind: "workflow.run", status, result, error: null,
  created_at: "2026-11-21T10:00:00Z", updated_at: "2026-11-21T10:00:00Z",
});

test("a run from a step names it, and alone says so", async () => {
  const { api } = setup();
  const runs = api.on("POST", "/v1/workflows/wf_1/runs", json(operation("queued"), { status: 202 }));
  const intake = nc.Workflow.fromId("wf_1");
  await intake.run({}, { fromStep: "note" });
  assert.deepEqual(runs.last.body, { inputs: {}, from_step: "note" });
  await intake.run({}, { fromStep: intake.step("note"), only: true, idempotencyKey: "note-again" });
  assert.deepEqual(runs.last.body, { inputs: {}, from_step: "note", only: true });
  assert.equal(runs.last.headers.get("Idempotency-Key"), "note-again");
  // A run from its trigger sends what it always did.
  await intake.run({ order_id: "o_1" });
  assert.deepEqual(runs.last.body, { inputs: { order_id: "o_1" } });
});

test("a step runs the workflow from itself", async () => {
  const { api } = setup();
  const runs = api.on("POST", "/v1/workflows/wf_1/runs", json(operation("succeeded", RUN), { status: 202 }));
  const note = nc.Workflow.fromId("wf_1").step("note");
  const op = await note.run({ only: true });
  assert.deepEqual(runs.last.body, { inputs: {}, from_step: "note", only: true });
  assert.deepEqual((await op.wait()).outputs, { Summary: { message: "Order o_9 received" } });
  await note.run();
  assert.deepEqual(runs.last.body, { inputs: {}, from_step: "note" });
});
