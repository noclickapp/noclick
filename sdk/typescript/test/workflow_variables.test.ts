// `Workflow.variables()`: a workflow's variables with their values, which no other read carries: what the call sends,
// how it reads the answer, and that a refusal is the API's.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, setup } from "./helpers.ts";

const VARIABLES = {
  object: "workflow_variables", workflow_id: "wf_1", version: 12,
  definitions: [
    { name: "api_token", value: "tok-held-back", description: "The shop's API token" },
    { name: "repo", value: "acme/shop", per_user: true },
    { name: "region" },
    { name: "page", value: "1" },
  ],
  variables: { page: 3, last_cursor: "c_9" },
};

test("variables() reads each variable with its value, as the account itself", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/workflows/wf_1/variables", json(VARIABLES));
  const read: nc.WorkflowVariables = await nc.Workflow.fromId("wf_1").variables();
  assert.deepEqual([read.workflowId, read.version], ["wf_1", 12]);
  assert.deepEqual(read.definitions, VARIABLES.definitions);
  assert.deepEqual(read.variables, { page: 3, last_cursor: "c_9" });
  // What {{vars.name}} reads: a definition's value, the graph's own over it; one with no value isn't there.
  assert.deepEqual(read.values, { api_token: "tok-held-back", repo: "acme/shop", page: 3, last_cursor: "c_9" });
  assert.equal(route.last.headers.get("NoClick-User"), null);
});

test("variables() rejects with the API's refusal for anyone but its owner", async () => {
  const { api } = setup();
  const refusal = () => apiError(403, "permission_denied", "This key lacks the 'workflows:variables' scope.", { scope: "workflows:variables" });
  api.on("GET", "/v1/workflows/wf_1/variables", refusal(), refusal());
  await assert.rejects(nc.Workflow.fromId("wf_1").variables(), (err: unknown) => {
    assert.ok(err instanceof nc.PermissionDenied);
    assert.match(err.message, /workflows:variables/);
    return true;
  });
  await assert.rejects(nc.asUser(USER_ID, () => nc.Workflow.fromId("wf_1").variables()), nc.PermissionDenied);
});

test("a workflow with none reads empty", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/wf_1/variables", json({ object: "workflow_variables", workflow_id: "wf_1", version: 1, definitions: [], variables: {} }));
  const read = await nc.Workflow.fromId("wf_1").variables();
  assert.deepEqual([read.definitions, read.variables, read.values], [[], {}, {}]);
});
