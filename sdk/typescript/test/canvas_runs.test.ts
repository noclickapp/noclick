// What a canvas reads and does about a workflow's runs (`Workflow.stopRun`, `runCounts`, `latestOutputs`,
// `Step.previewExpression`, `Step.clearState`, `stepOutputShape`): what each call sends and how it reads the answer.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, setup } from "./helpers.ts";

const RUN = {
  object: "workflow_run", id: "run_1", workflow_id: "wf_1", status: "failed", inputs: {}, outputs: {},
  error: { type: "canceled", message: "The operation was canceled." }, source: "api", user_id: null,
  operation_id: "op_1", started_at: "2026-11-21T10:00:00Z", finished_at: "2026-11-21T10:00:04Z",
  steps: [
    { id: "hook", name: "Hook", status: "succeeded", error: null, output: { order_id: "o_1" }, withheld: [] },
    { id: "note", name: "Summary", status: "running", error: null, output: null, withheld: [] },
  ],
};

test("stopRun() answers the run as it stands, as the caller's user inside asUser", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/workflows/wf_1/runs/run_1/stop", json(RUN), json(RUN));
  const stopped = await nc.Workflow.fromId("wf_1").stopRun("run_1");
  assert.deepEqual([stopped.status, stopped.error, stopped.operationId], ["failed", "The operation was canceled.", "op_1"]);
  assert.deepEqual(stopped.steps.map((s) => [s.id, s.status]), [["hook", "succeeded"], ["note", "running"]]);
  assert.equal(route.last.headers.get("NoClick-User"), null);
  await nc.asUser(USER_ID, () => nc.Workflow.fromId("wf_1").stopRun("run_1"));
  assert.equal(route.last.headers.get("NoClick-User"), USER_ID);
});

test("runs() narrows by how a run started, what started it, whether it waits and its error's text", async () => {
  const { api } = setup();
  const waits = { ...RUN, id: "run_2", status: "running", error: null, source: "trigger", trigger: "email", waiting_on: "approval", steps: [] };
  const page = { object: "list", data: [waits], next_cursor: null };
  const route = api.on("GET", "/v1/workflows/wf_1/runs", json(page), json({ object: "list", data: [RUN], next_cursor: null }));
  const [run] = await nc.Workflow.fromId("wf_1").runs({
    status: "running", source: ["trigger", "schedule"], trigger: "email", waiting: true, search: "refused", limit: 5,
  });
  assert.deepEqual(
    ["status", "source", "trigger", "waiting", "search", "limit"].map((name) => route.last.query.get(name)),
    ["running", "trigger,schedule", "email", "true", "refused", "5"]);
  assert.deepEqual([run.status, run.waitingOn, run.source, run.trigger], ["running", "approval", "trigger", "email"]);
  // A run from code names no trigger and, once it ended, waits on nothing; nothing asked narrows nothing.
  const [ended] = await nc.Workflow.fromId("wf_1").runs({ waiting: false });
  assert.deepEqual([ended.waitingOn, ended.trigger, route.last.query.get("waiting")], [null, null, "false"]);
  assert.deepEqual(["source", "trigger", "search"].map((name) => route.last.query.get(name)), [null, null, null]);
});

test("runCounts() reads every status and takes a userFilter", async () => {
  const { api } = setup();
  const body = {
    object: "run_counts", workflow_id: "wf_1", total: 3, by_status: { succeeded: 2, failed: 1 }, waiting: 1,
    by_source: { api: 2, schedule: 1 }, by_trigger: { email: 1 },
  };
  const route = api.on("GET", "/v1/workflows/wf_1/runs/counts", json(body), json(body));
  const counts = await nc.Workflow.fromId("wf_1").runCounts();
  assert.deepEqual([counts.total, counts.byStatus, counts.bySource], [3, { running: 0, succeeded: 2, failed: 1 }, { api: 2, schedule: 1 }]);
  assert.deepEqual([counts.waiting, counts.byTrigger], [1, { email: 1 }]);
  assert.equal(route.last.query.get("user_id"), null);
  await nc.Workflow.fromId("wf_1").runCounts({ userFilter: nc.ALL_USERS });
  assert.equal(route.last.query.get("user_id"), "all");
  assert.equal(route.last.headers.get("NoClick-User"), null);
});

test("latestOutputs() names what each step left out, and how each step's last run ended", async () => {
  const { api } = setup();
  const body = {
    object: "step_outputs", workflow_id: "wf_1", outputs: { hook: { order_id: "o_9" } },
    withheld: { hook: ["_webhook.headers.Authorization"] }, full: true, truncated: [],
    last_runs: { hook: { status: "succeeded", finished_at: "2026-11-21T10:00:04+00:00", error: null },
      note: { status: "failed", finished_at: null, error: "the shop answered 500" } },
  };
  const route = api.on("GET", "/v1/workflows/wf_1/outputs", json(body), json(body));
  const intake = nc.Workflow.fromId("wf_1");
  const latest = await intake.latestOutputs({ steps: [intake.step("hook"), "note"], full: true });
  assert.deepEqual([route.last.query.get("steps"), route.last.query.get("full")], ["hook,note", "true"]);
  assert.deepEqual([latest.outputs, latest.withheld, latest.full, latest.truncated],
    [{ hook: { order_id: "o_9" } }, { hook: ["_webhook.headers.Authorization"] }, true, []]);
  assert.deepEqual(latest.lastRuns, {
    hook: { status: "succeeded", finishedAt: new Date("2026-11-21T10:00:04Z"), error: null },
    note: { status: "failed", finishedAt: null, error: "the shop answered 500" },
  });
  await intake.latestOutputs();
  assert.deepEqual([...route.last.query.keys()], []);
});

test("previewExpression() evaluates against what was stored, or samples", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/workflows/wf_1/steps/note/expression",
    json({ object: "expression_preview", ok: true, kind: "string", keys: null, preview: "o_9" }),
    json({ ok: true, kind: "string", keys: null, preview: "eu" }),
    json({ ok: false, error: "Cannot read properties of undefined" }));
  const note = nc.Workflow.fromId("wf_1").step("note");
  const found = await note.previewExpression("$json.order_id");
  assert.deepEqual(route.last.body, { expression: "$json.order_id" });
  assert.deepEqual([found.ok, found.kind, found.keys, found.preview, found.error], [true, "string", null, "o_9", null]);
  await note.previewExpression("$vars.region", { samples: { vars: { region: "eu" } } });
  assert.deepEqual(route.last.body, { expression: "$vars.region", samples: { vars: { region: "eu" } } });
  const failed = await note.previewExpression("$('hook').nope.deeper");
  assert.deepEqual([failed.ok, failed.error], [false, "Cannot read properties of undefined"]);
});

test("clearState() acts for the account even inside asUser", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/workflows/wf_1/steps/rss/clear_state", json({
    object: "step_state", workflow_id: "wf_1", step_id: "rss", cleared: true, state_rows_deleted: 1, conversations_deleted: 0,
  }));
  const cleared = await nc.asUser(USER_ID, () => nc.Workflow.fromId("wf_1").step("rss").clearState());
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.deepEqual([cleared.stepId, cleared.stateRowsDeleted, cleared.conversationsDeleted], ["rss", 1, 0]);
});

test("stepOutputShape() reads the account's own shape of a type", async () => {
  const { api } = setup();
  const body = { object: "output_shape", type: "automation-hubspot", operation: "get_contact", shape: { id: "integer" }, suggested_refs: null };
  const route = api.on("GET", "/v1/step_types/automation-hubspot/output_shape", json(body), json(body));
  const found = await nc.stepOutputShape("automation-hubspot", { operation: "get_contact" });
  assert.equal(route.last.query.get("operation"), "get_contact");
  assert.deepEqual([found.type, found.operation, found.shape, found.suggestedRefs],
    ["automation-hubspot", "get_contact", { id: "integer" }, null]);
  await nc.stepOutputShape("automation-hubspot");
  assert.equal(route.last.query.get("operation"), null);
});

test("warmSandboxes(), template() and Step.decideProposal() read and send what the canvas's badge, Share and chat card do", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/wf_1/sandboxes", json({ object: "workflow_sandboxes", workflow_id: "wf_1", steps: { helper: 2 } }));
  api.on("GET", "/v1/workflows/wf_1/template", json({
    object: "workflow_template", workflow_id: "wf_1", published: false, template: null,
    draft: { title: "Order intake", description: "Files each order." },
  }));
  const decide = api.on("POST", "/v1/workflows/wf_1/steps/helper/conversations/__interface_chat__/decisions",
    json({ object: "step_proposal_decision", conversation: "__interface_chat__", proposal_id: "p1", decision: "dismissed" }));
  const intake = nc.Workflow.fromId("wf_1");
  assert.deepEqual(await intake.warmSandboxes(), { helper: 2 });
  const listing = await intake.template();
  assert.deepEqual([listing.published, listing.publicUrl, listing.draftTitle], [false, null, "Order intake"]);
  await intake.step("helper").decideProposal("__interface_chat__", "p1", "dismissed");
  assert.deepEqual(decide.last.body, { proposal_id: "p1", decision: "dismissed" });
});
