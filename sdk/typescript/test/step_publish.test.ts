// An interface step's app, published with no build (`Step.publish`, `Step.renameApp`, `Step.unpublish`): the body each
// call sends and how the answer reads.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, setup } from "./helpers.ts";

const PUBLISHED = {
  object: "step_publication", workflow_id: "wf_1", step_id: "page", action: "publish", state: "published",
  url: "https://morrow.noclick.app", project_id: "prj_1", subdomain: "morrow", deployment_id: "dep_1",
  previous_url: null, trash_id: null, restorable_until: null,
};

test("publish names the subdomain the first time, as the account, and reads the app", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/workflows/wf_1/steps/page/publish", json(PUBLISHED));
  const done = await nc.asUser(USER_ID, () =>
    nc.Workflow.fromId("wf_1").step("page").publish({ subdomain: "morrow", title: "Morrow Bakehouse" }));
  assert.deepEqual(route.last.body, { action: "publish", subdomain: "morrow", title: "Morrow Bakehouse" });
  assert.equal(route.last.headers.get("NoClick-User"), null); // its app is the account's, never a user's
  assert.deepEqual([done.state, done.url, done.projectId, done.subdomain, done.deploymentId],
    ["published", "https://morrow.noclick.app", "prj_1", "morrow", "dep_1"]);
  await nc.Workflow.fromId("wf_1").step("page").publish();
  assert.deepEqual(route.last.body, { action: "publish" });
});

test("renameApp and unpublish say where it was and how it comes back", async () => {
  const { api } = setup();
  const step = nc.Workflow.fromId("wf_1").step("page");
  const renamed = api.on("POST", "/v1/workflows/wf_1/steps/page/publish", json({
    ...PUBLISHED, action: "rename", state: "renamed", url: "https://morrow-bakery.noclick.app",
    subdomain: "morrow-bakery", deployment_id: null, previous_url: "https://morrow.noclick.app",
  }));
  const moved = await step.renameApp("morrow-bakery");
  assert.deepEqual(renamed.last.body, { action: "rename", subdomain: "morrow-bakery" });
  assert.deepEqual([moved.state, moved.url, moved.previousUrl],
    ["renamed", "https://morrow-bakery.noclick.app", "https://morrow.noclick.app"]);

  const gone = api.on("POST", "/v1/workflows/wf_1/steps/page/publish", json({
    ...PUBLISHED, action: "unpublish", state: "unpublished", url: null,
    previous_url: "https://morrow-bakery.noclick.app", trash_id: "trash_9", restorable_until: "2026-12-21T10:00:00+00:00",
  }));
  const down = await step.unpublish();
  assert.deepEqual(gone.last.body, { action: "unpublish" });
  assert.deepEqual([down.state, down.url, down.trashId, down.restorableUntil?.getUTCMonth()],
    ["unpublished", null, "trash_9", 11]);
});

test("the app reads as it stands and an address is checked before a publish", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/wf_1/steps/page/app", json({
    ...PUBLISHED, action: null, state: "not_published", url: null, project_id: null, subdomain: null, deployment_id: null,
    apps_domain: "noclick.app",
  }));
  const checked = api.on("GET", "/v1/workflows/wf_1/steps/page/app/address", json({
    object: "publish_address", subdomain: "morrow", available: false, reason: "This address is already taken.", apps_domain: "noclick.app",
  }));
  const step = nc.Workflow.fromId("wf_1").step("page");
  const app = await step.app();
  assert.deepEqual([app.state, app.url, app.appsDomain], ["not_published", null, "noclick.app"]);
  const found = await step.checkAddress("morrow");
  assert.equal(checked.last.query.get("subdomain"), "morrow");
  assert.deepEqual([found.available, found.reason], [false, "This address is already taken."]);
});

test("what a workflow's State step keeps is read and set", async () => {
  const { api } = setup();
  const kept = { object: "workflow_state", workflow_id: "wf_1", step_id: "state", values: { visits: 3 } };
  const read = api.on("GET", "/v1/workflows/wf_1/state", json(kept));
  const written = api.on("PUT", "/v1/workflows/wf_1/state/visits", json({ ...kept, values: { visits: 4 } }));
  const flow = nc.Workflow.fromId("wf_1");
  const state = await flow.state({ step: "state" });
  assert.equal(read.last.query.get("step_id"), "state");
  assert.deepEqual([state.stepId, state.values], ["state", { visits: 3 }]);
  assert.deepEqual((await flow.setState("visits", 4)).values, { visits: 4 });
  assert.deepEqual(written.last.body, { value: 4 });
  await flow.setState("visits", null);
  assert.deepEqual(written.last.body, { value: null });
});
