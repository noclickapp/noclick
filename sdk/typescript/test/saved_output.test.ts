// Outputs saved under a name (`SavedOutput`): the account's own, read and changed on the workflow they're shown on.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";

const WF = "wf_1";
const ORDER = {
  object: "saved_output", id: "so_1", name: "A paid order", step_type: "automation-shopify", output: { ok: true },
  visibility: "user", owner_id: "u_ada", mine: true, created_at: "2026-11-24T09:00:00+00:00", updated_at: "2026-11-24T09:00:00+00:00",
};

test("SavedOutput.list reads a step type's saved outputs on the workflow, as the account", async () => {
  const { api } = setup();
  const read = api.on("GET", `/v1/workflows/${WF}/saved_outputs`, json({ object: "list", data: [ORDER] }));
  const saved = await nc.asUser("user_42", () => nc.SavedOutput.list(WF, "automation-shopify"));
  assert.deepEqual(saved.map((s) => [s.name, s.stepType, s.visibility, s.mine, s.output]), [
    ["A paid order", "automation-shopify", "user", true, { ok: true }],
  ]);
  assert.equal(read.last.query.get("step_type"), "automation-shopify");
  assert.equal(read.last.headers.get("NoClick-User"), null);
});

test("create sends what it saves, update and delete name it, and a plan's limit rejects with PlanRequired", async () => {
  const { api } = setup();
  const made = api.on(
    "POST",
    `/v1/workflows/${WF}/saved_outputs`,
    json(ORDER, { status: 201 }),
    apiError(402, "plan_required", "Plan limit reached")
  );
  const patch = api.on("PATCH", `/v1/workflows/${WF}/saved_outputs/so_1`, json({ ...ORDER, visibility: "public" }));
  const removed = api.on("DELETE", `/v1/workflows/${WF}/saved_outputs/so_1`, json({ object: "saved_output", id: "so_1", deleted: true }));
  const saved = await nc.SavedOutput.create(WF, { stepType: "automation-shopify", name: "A paid order", output: { ok: true } });
  assert.deepEqual(made.last.body, { step_type: "automation-shopify", name: "A paid order", output: { ok: true } });
  assert.equal((await saved.update({ visibility: "public" })).visibility, "public");
  assert.deepEqual(patch.last.body, { visibility: "public" });
  await saved.delete();
  assert.equal(removed.calls.length, 1);
  await assert.rejects(nc.SavedOutput.create(WF, { stepType: "automation-shopify", name: "More", output: {} }), nc.PlanRequired);
});
