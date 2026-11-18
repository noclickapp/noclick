// A workflow read in full, paused, resumed, restored and published, and one run with its steps, against the
// mock API: the routes and bodies each call sends, and what it parses.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, operation, setup } from "./helpers.ts";

const FULL = {
  object: "workflow", id: "wf_1", name: "Order intake", description: null, access: "owner", inputs: { type: "object" },
  app_url: "https://noclick.com/dashboard?tab=workflows&workflow=wf_1", created_at: "2026-10-12T10:00:00Z", updated_at: "2026-10-12T10:00:00Z",
  steps: [
    {
      id: "hook", name: "Hook", type: "trigger-webhook", operation: null, enabled: true, settings: { http_method: "POST" },
      connection: null, trigger: { error: null, paused_reason: null, next_run: null },
    },
    {
      id: "ticket", name: "Ticket", type: "automation-linear", operation: "create_issue", enabled: true,
      settings: { title: "Order" }, connection: { attached: false, healthy: null, hint: null }, trigger: null,
    },
  ],
  edges: [{ from: "hook", to: "ticket", kind: "data" }],
  paused: false,
  readiness: {
    status: "needs_setup",
    meaning: "Something is in the way of it running: each issue says what, and where.",
    issues: [{ step: "ticket", code: "missing_credentials", message: "Ticket: connect an account" }],
  },
  urls: [{ kind: "endpoint", url: "https://api.noclick.com/v1/workflows/wf_1/endpoint", step: null, public: false }],
};

test("one workflow reads in full", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/wf_1", json(FULL));
  const workflow = await nc.Workflow.get("wf_1");
  assert.deepEqual([workflow.access, workflow.paused, workflow.readiness.status], ["owner", false, "needs_setup"]);
  assert.equal(workflow.readiness.meaning, FULL.readiness.meaning);
  const [hook, ticket] = workflow.steps;
  assert.deepEqual([hook.enabled, hook.settings, hook.trigger, hook.connection], [
    true, { http_method: "POST" }, { error: null, pausedReason: null, nextRun: null }, null]);
  assert.deepEqual([ticket.trigger, ticket.connection], [null, { attached: false, healthy: null, hint: null }]);
  assert.deepEqual(workflow.edges, [{ from: "hook", to: "ticket", kind: "data" }]);
  assert.equal(workflow.urls[0].kind, "endpoint");
});

test("pause, resume and restore read the workflow again", async () => {
  const { api } = setup();
  const paused = api.on("POST", "/v1/workflows/wf_1/pause", json({ ...FULL, paused: true }));
  api.on("POST", "/v1/workflows/wf_1/resume", json(FULL));
  api.on("POST", "/v1/workflows/wf_1/restore", json(FULL));
  const workflow = nc.Workflow.fromId("wf_1");
  assert.equal((await workflow.pause("Too noisy")).paused, true);
  assert.deepEqual(paused.last.body, { reason: "Too noisy" });
  assert.equal((await workflow.resume()).paused, false);
  assert.equal((await workflow.restore()).name, "Order intake");
});

test("publishing is a build with publish", async () => {
  const { api } = setup();
  const builds = api.on("POST", "/v1/workflows/wf_1/builds",
    json(operation({ id: "op_b", kind: "workflow.build", status: "running", workflow_id: "wf_1" }), { status: 202 }));
  const workflow = nc.Workflow.fromId("wf_1");
  await workflow.publish({ subdomain: "morrow", title: "Morrow" });
  assert.deepEqual(builds.last.body, { publish: { subdomain: "morrow", title: "Morrow" } });
  await workflow.unpublish();
  assert.deepEqual(builds.last.body, { publish: { action: "unpublish" } });
  await workflow.build("Add a contact form", { publish: true });
  assert.deepEqual(builds.last.body, { instructions: "Add a contact form", publish: {} });
});

test("one run reads with its steps", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/wf_1/runs/run_1", json({
    object: "workflow_run", id: "run_1", workflow_id: "wf_1", status: "failed", inputs: {}, outputs: {},
    error: { type: "platform_error", message: "Step 'Ticket' failed: no team" }, source: "trigger", user_id: null,
    operation_id: null, started_at: "2026-10-12T10:00:00Z", finished_at: "2026-10-12T10:00:03Z",
    steps: [
      { id: "hook", name: "Hook", status: "succeeded", error: null, output: { order_id: "o1" } },
      { id: "ticket", name: "Ticket", status: "failed", error: "no team", output: null },
    ],
  }));
  const run = await nc.Workflow.fromId("wf_1").getRun("run_1");
  assert.equal(run.error, "Step 'Ticket' failed: no team");
  assert.deepEqual(run.steps.map((s) => [s.name, s.status, s.error]), [["Hook", "succeeded", null], ["Ticket", "failed", "no team"]]);
  assert.deepEqual(run.steps[0].output, { order_id: "o1" });
});
