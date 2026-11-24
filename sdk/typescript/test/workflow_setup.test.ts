// `Workflow.setup()` and `Workflow.requestSetup()`: what a workflow needs from its person, as data, and sent to them as
// one request: what each call sends and how its answer reads.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const ITEMS = [
  { key: "connect:slack", kind: "connect", app: "slack", label: "Slack", reconnect: false, credential_types: ["slack_oauth"],
    steps: [{ step_id: "ops", step_name: "Tell ops" }, { step_id: "sales", step_name: "Tell sales" }] },
  { key: "setting:text:to_number", kind: "setting", step: { step_id: "text", step_name: "Text me" }, setting: "to_number",
    label: "To Number", type: "string", description: null, options: null },
];
const SETUP = { object: "workflow_setup", workflow_id: "wf_1", ready: false, items: ITEMS, request: null };

test("setup() reads what the workflow needs as data", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/wf_1/setup", json(SETUP));
  const read: nc.WorkflowSetup = await nc.Workflow.fromId("wf_1").setup();
  assert.deepEqual([read.workflowId, read.ready, read.request, read.sent], ["wf_1", false, null, null]);
  assert.deepEqual(read.items.map((i) => i.label), ["Slack", "To Number"]);
});

test("requestSetup() sends one request, how it was asked", async () => {
  const { api } = setup();
  const sent = { id: "op_1", status: "awaiting_human", request: { id: "hr_1", kind: "setup", delivered_via: ["email"] } };
  const answer = json({ ...SETUP, request: { id: "hr_1", operation_id: "op_1", parts: [] }, sent });
  const route = api.on("POST", "/v1/workflows/wf_1/setup/request", answer, answer);
  const done = await nc.Workflow.fromId("wf_1").requestSetup({ via: ["email"] });
  assert.deepEqual(route.last.body, { via: ["email"] });
  assert.equal((done.sent?.request as { kind: string }).kind, "setup");
  assert.equal(done.request?.id, "hr_1");
  await nc.Workflow.fromId("wf_1").requestSetup();
  assert.deepEqual(route.last.body, { via: "auto" });
});
