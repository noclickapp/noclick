// A run's steps as they ran (`getRun(id, { detail: "steps" })`), what came in to a coding harness's reply
// (`runInputs`), and a step form's check (`checkStepSettings`): what the client sends and how it reads the answer.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const WF = "2e3a9296-1bf5-4088-a20d-7c31937380c4";
const RUN = "7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a01";

test("getRun with detail reads each step as it ran and the graph it ran", async () => {
  const { api } = setup();
  const route = api.on("GET", `/v1/workflows/${WF}/runs/${RUN}`, json({
    object: "workflow_run", id: RUN, status: "failed", graph: { nodes: [{ id: "helper", type: "agent" }], edges: [], withheld: {} },
    steps: [{ id: "helper", name: "Helper", status: "failed", error: "Insufficient credits", output: null, withheld: [],
      type: "agent", operation: null, error_action: { kind: "add_funds" },
      tool_calls: [{ object: "tool_call", tool_name: "slack.send", status: "success" }] }],
  }));
  const run = await nc.Workflow.fromId(WF).getRun(RUN, { detail: "steps" });
  assert.equal(route.last.query.get("detail"), "steps");
  const [step] = run.steps;
  assert.deepEqual([step.type, step.errorAction?.kind, step.toolCalls[0].tool_name], ["agent", "add_funds", "slack.send"]);
  assert.equal((run.graph?.nodes as unknown[]).length, 1);
});

test("runInputs reads each delivery a reply answered", async () => {
  const { api } = setup();
  api.on("GET", `/v1/workflows/${WF}/runs/${RUN}/inputs`, json({ object: "list", data: [
    { object: "run_input", run_id: "d1", steps: [{ id: "hook", name: "", status: "succeeded", output: { order_id: "o_9" }, withheld: ["_webhook.headers.Authorization"] }] },
  ], next_cursor: null, total: 3 }));
  const inputs = await nc.Workflow.fromId(WF).runInputs(RUN);
  assert.equal(inputs.total, 3);
  assert.deepEqual([inputs.inputs[0].runId, inputs.inputs[0].steps[0].withheld], ["d1", ["_webhook.headers.Authorization"]]);
});

test("checkStepSettings posts the settings and reads the verdict", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/step_types/log/check", json({ object: "step_check", step_type: "log", valid: false, errors: [{ field: "message" }], satisfied_set: null }));
  const check = await nc.checkStepSettings("log", {});
  assert.deepEqual(route.last.body, { settings: {} });
  assert.deepEqual([check.valid, check.satisfiedSet, check.errors.length], [false, null, 1]);
});
