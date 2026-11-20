// A step's outputs (`Step.outputs`, `Step.output`): what each call sends and how it reads the answer.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, setup } from "./helpers.ts";

const DELIVERY = {
  object: "step_output", workflow_id: "wf_1", step_id: "hook", iteration: null, run_id: "run_9", source: "trigger",
  status: "succeeded", error: null, created_at: "2026-11-20T09:00:00Z", no_event: false,
  preview: 'order_id="o_9", items=[1 items]', withheld: ["_webhook.headers.Authorization"],
};
const PLACEHOLDER = { ...DELIVERY, run_id: "run_8", source: "app", no_event: true, preview: 'status="no_event"', withheld: [] };

test("outputs() reads newest first, page by page", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/workflows/wf_1/steps/hook/outputs", json(listing([DELIVERY], "run_9:hook")), json(listing([PLACEHOLDER])));
  const found = await nc.Workflow.fromId("wf_1").step("hook").outputs({ search: "o_9", limit: null });
  assert.equal(route.count, 2);
  assert.deepEqual([route.calls[0].query.get("search"), route.calls[0].query.get("cursor")], ["o_9", null]);
  assert.equal(route.calls[1].query.get("cursor"), "run_9:hook");
  const [delivery, placeholder] = found;
  assert.deepEqual([delivery.runId, delivery.source, delivery.status, delivery.noEvent, delivery.iteration],
    ["run_9", "trigger", "succeeded", false, null]);
  assert.deepEqual(delivery.withheld, ["_webhook.headers.Authorization"]);
  assert.equal(delivery.preview?.startsWith('order_id="o_9"'), true);
  assert.equal(delivery.output, null);
  assert.equal(delivery.createdAt?.getUTCFullYear(), 2026);
  assert.deepEqual([placeholder.noEvent, placeholder.source], [true, "app"]);
});

test("outputs() takes ten by default and reads as a user inside asUser", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/workflows/wf_1/steps/hook/outputs", json(listing([DELIVERY])));
  await nc.asUser("user_42", () => nc.Workflow.fromId("wf_1").step("hook").outputs());
  assert.deepEqual([route.last.query.get("limit"), route.last.query.get("search")], ["10", null]);
  assert.equal(route.last.headers.get("NoClick-User"), "user_42");
});

test("output() reads one run's output whole or a part", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/workflows/wf_1/steps/note/outputs/run_9", json({
    ...DELIVERY, step_id: "note", iteration: 2, preview: null, output: "A1", path: "items[0].sku", full: true, truncated: false,
  }));
  const note = nc.Workflow.fromId("wf_1").step("note");
  const read = await note.output("run_9", { path: "items[0].sku", full: true, iteration: 2 });
  assert.deepEqual([route.last.query.get("path"), route.last.query.get("full"), route.last.query.get("iteration")],
    ["items[0].sku", "true", "2"]);
  assert.deepEqual([read.output, read.path, read.full, read.truncated, read.iteration, read.stepId],
    ["A1", "items[0].sku", true, false, 2, "note"]);
  await note.output("run_9");
  assert.deepEqual([...route.last.query.keys()], []);
});

test("a run's step names the secrets left out of it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/wf_1/runs/run_1", json({
    object: "workflow_run", id: "run_1", workflow_id: "wf_1", status: "succeeded", inputs: {}, outputs: {}, error: null,
    source: "trigger", user_id: null, operation_id: null, started_at: "2026-10-12T10:00:00Z",
    finished_at: "2026-10-12T10:00:03Z",
    steps: [{ id: "hook", name: "Hook", status: "succeeded", error: null, output: { order_id: "o1" }, withheld: ["_webhook.headers.Authorization"] }],
  }));
  const [hook] = (await nc.Workflow.fromId("wf_1").getRun("run_1")).steps;
  assert.deepEqual(hook.withheld, ["_webhook.headers.Authorization"]);
});
