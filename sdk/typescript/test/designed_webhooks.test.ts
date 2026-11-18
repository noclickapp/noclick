// Designed, not built yet: workflows and user export, against the mock API (routes, bodies, user
// headers, parsed results).
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, listing, operation, setup, userRow } from "./helpers.ts";

// --- workflows -----------------------------------------------------------------

const WORKFLOW = {
  object: "workflow", id: "wf_1", name: "order-intake", description: "Checks a new order.",
  inputs: { type: "object", properties: { order_id: { type: "string" } } }, app_url: "https://noclick.com/dashboard?tab=workflows&workflow=order-intake",
  created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-25T10:00:00Z",
};
const RUN = {
  object: "workflow_run", id: "run_1", workflow_id: "wf_1", status: "succeeded", inputs: { order_id: "o1" },
  outputs: { summary: "Order o1 is in stock." }, error: null, source: "api", user_id: USER_ID, operation_id: "op_r",
  started_at: "2026-09-25T10:00:00Z", finished_at: "2026-09-25T10:00:09Z",
};

test("Workflow.fromName runs for the current user and waits for the outputs", async () => {
  const { api } = setup();
  const lookup = api.on("GET", "/v1/workflows", json(listing([WORKFLOW, { ...WORKFLOW, id: "wf_2", name: "other" }])));
  const start = api.on("POST", "/v1/workflows/wf_1/runs", json(operation({ id: "op_r", kind: "workflow.run", status: "running" })));
  api.on("GET", "/v1/operations/op_r/wait", json(operation({ id: "op_r", kind: "workflow.run", status: "succeeded", result: RUN })));
  const intake = nc.Workflow.fromName("order-intake");
  assert.equal(lookup.count, 0);
  const op = await nc.asUser("acme", () => intake.run({ order_id: "o1" }, { idempotencyKey: "order-o1" }));
  assert.equal(lookup.last.query.get("name"), "order-intake");
  assert.equal(lookup.last.headers.get("NoClick-User"), null);
  assert.deepEqual(start.last.body, { inputs: { order_id: "o1" } });
  assert.equal(start.last.headers.get("NoClick-User"), "acme");
  assert.equal(start.last.headers.get("Idempotency-Key"), "order-o1");
  const run = await op.wait();
  assert.deepEqual([run.status, run.outputs.summary, run.source, run.finishedAt?.toISOString()], ["succeeded", "Order o1 is in stock.", "api", "2026-09-25T10:00:09.000Z"]);
  assert.equal(((await nc.Operation.fromId("op_r").wait()) as nc.WorkflowRun).id, "run_1");
});

test("Workflow.fromName refuses a missing or ambiguous name", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows", json(listing([WORKFLOW, { ...WORKFLOW, id: "wf_2" }])));
  await assert.rejects(nc.Workflow.fromName("order-intake").hydrate(), (err: unknown) => err instanceof nc.Conflict && /2 workflows/.test(err.message));
  await assert.rejects(nc.Workflow.fromName("nope").hydrate(), nc.NotFound);
});

test("runs, endpoint and list", async () => {
  const { api } = setup();
  const runs = api.on("GET", "/v1/workflows/wf_1/runs", json(listing([RUN, { ...RUN, id: "run_0", status: "failed", error: { message: "Timed out" } }])));
  const endpoint = api.on("PUT", "/v1/workflows/wf_1/endpoint", json({ object: "workflow_endpoint", url: "https://wf-1.example.com", public: true, method: "POST" }));
  const list = api.on("GET", "/v1/workflows", json(listing([WORKFLOW])));
  const intake = nc.Workflow.fromId("wf_1");

  const [latest, failed] = await intake.runs({ status: ["succeeded", "failed"], userFilter: nc.ALL_USERS });
  assert.deepEqual(["status", "user_id", "limit"].map((k) => runs.last.query.get(k)), ["succeeded,failed", "all", "20"]);
  assert.deepEqual([latest.id, failed.status, failed.error], ["run_1", "failed", "Timed out"]);

  const pub = await intake.endpoint({ public: true });
  assert.deepEqual(endpoint.last.body, { public: true });
  assert.deepEqual([pub.url, pub.public, pub.method], ["https://wf-1.example.com", true, "POST"]);

  const [workflow] = await nc.Workflow.list({ q: "order", limit: 5 });
  assert.equal(list.last.query.get("q"), "order");
  assert.deepEqual([workflow.name, workflow.inputs.type], ["order-intake", "object"]);
});

// --- user export -------------------------------------------------------------

const BUNDLE = {
  url: "https://exports.example.com/x/acme.zip", expires_at: "2026-10-02T10:00:00Z",
  contents: [{ kind: "agent", name: "concierge", detail: "agents/concierge.json" }],
  remaining_dependencies: ["agent runtime", "channels"],
};

test("user.export resolves to the bundle; delete({ export: true }) exports first", async () => {
  const { api } = setup();
  const start = api.on("POST", `/v1/users/${USER_ID}/export`, json(operation({ id: "op_x", kind: "user.export", status: "running" })));
  api.on("GET", "/v1/operations/op_x/wait", json(operation({ id: "op_x", kind: "user.export", status: "succeeded", result: BUNDLE })));
  const del = api.on("DELETE", `/v1/users/${USER_ID}`, json(userRow({ status: "deleted" })));

  const bundle = await (await nc.User.fromId(USER_ID).export()).wait();
  assert.deepEqual(start.last.body, {});
  assert.equal(start.last.headers.get("NoClick-User"), null);
  assert.deepEqual([bundle.url, bundle.expiresAt?.toISOString(), bundle.contents[0].name, bundle.remainingDependencies], [
    "https://exports.example.com/x/acme.zip", "2026-10-02T10:00:00.000Z", "concierge", ["agent runtime", "channels"],
  ]);

  const op = await nc.User.fromId(USER_ID).delete({ export: true });
  assert.deepEqual(start.last.body, { delete_after: true });
  assert.equal(op.kind, "user.export");
  assert.equal(del.count, 0);
  assert.equal((await op.wait()).url, BUNDLE.url);

  const user = nc.User.fromId(USER_ID);
  assert.equal(await user.delete(), undefined);
  assert.equal(user.status, "deleted");
});
