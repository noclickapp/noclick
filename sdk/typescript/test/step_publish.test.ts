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
