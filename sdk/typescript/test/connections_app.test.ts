// Accounts connected in the app as connections (origin "app", ref credential:<id>), the origin filter, and
// requireApproval, against the mock API: the routes and bodies each call sends, and what it parses.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, setup } from "./helpers.ts";

const NAMED = {
  object: "connection", id: "con_1", name: "gmail", integration: "gmail", credential_type: "google_gmail_oauth",
  user_id: null, status: "connected", origin: "api", access: "owner", approval_operations: [], account: null,
  verification: null, connect_link: null, used_by: [], connected_at: null, created_at: null, updated_at: null,
};
const APP_ID = "credential:9b2a1c5e-7d9f-4a31-8f6d-3f1d2c4b8a7e";
const FROM_THE_APP = { ...NAMED, id: APP_ID, name: "Gmail (ana@gmail.com)", origin: "app" };
// How the client writes the ref into a path (a colon may be percent-encoded; the server decodes it).
const PATH_REF = encodeURIComponent(APP_ID);

test("accounts connected in the app list, load and run by their credential ref", async () => {
  const { api } = setup();
  const list = api.on("GET", "/v1/connections", json(listing([NAMED, FROM_THE_APP])));
  for (const ref of new Set([APP_ID, PATH_REF])) {
    api.on("GET", `/v1/connections/${ref}`, json(FROM_THE_APP));
    api.on("POST", `/v1/connections/${ref}/operations/send_email/run`,
      json({ object: "operation_result", connection: APP_ID, result: { id: "msg_1" } }));
  }
  const direct = api.on("POST", "/v1/run", json({ object: "operation_result", connection: APP_ID, result: { id: "msg_2" } }));
  const [named, app] = await nc.Connection.list();
  assert.deepEqual([named.origin, app.origin, app.id, app.access], ["api", "app", APP_ID, "owner"]);
  await nc.Connection.list({ origin: "app" });
  assert.equal(list.last.query.get("origin"), "app");
  const gmail = nc.Connection.fromId(APP_ID);
  assert.deepEqual(await gmail.run("send_email", { to: "a@b.c" }), { id: "msg_1" });
  assert.equal((await nc.Connection.get(APP_ID)).name, "Gmail (ana@gmail.com)");
  assert.deepEqual(await nc.run(`${APP_ID}.send_email`, { to: "a@b.c" }), { id: "msg_2" });
  assert.equal((direct.last.body as { ref: string }).ref, `${APP_ID}.send_email`);
});

test("an account agent takes an app connection as a tool by its id", async () => {
  const { api } = setup();
  for (const ref of new Set([APP_ID, PATH_REF])) api.on("GET", `/v1/connections/${ref}`, json(FROM_THE_APP));
  const create = api.on("POST", "/v1/agents", json({
    object: "agent", id: "ag_1", name: "assistant", model: "openrouter/x", harness: "sdk", instructions: "hi",
    tools: [], user_id: null, workflow_id: "wf_1", created_at: "2026-09-25T10:00:00Z",
  }));
  const gmail = nc.Connection.fromId(APP_ID);
  await nc.Agent.create("assistant", {
    instructions: "hi", tools: [gmail, gmail.only("send_email_message"), `${APP_ID}.list_messages`],
  });
  assert.deepEqual((create.last.body as { tools: unknown }).tools,
    [APP_ID, `${APP_ID}.send_email_message`, `${APP_ID}.list_messages`]);
});

test("requireApproval sends the operations and keeps the answer", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/connections/gmail/require_approval",
    json({ ...NAMED, approval_operations: ["delete_message", "send_email_message"] }));
  const gmail = nc.Connection.fromName("gmail");
  assert.equal(await gmail.requireApproval("send_email_message", "delete_message"), gmail);
  assert.deepEqual(route.last.body, { operations: ["send_email_message", "delete_message"] });
  assert.deepEqual(gmail.approvalOperations, ["delete_message", "send_email_message"]);
});

test("liftApproval names what it lifts and returns the change", async () => {
  const { api } = setup();
  const lift = {
    object: "approval_policy_change", id: "chg_1", batch_id: "chg_1", scope: "credential", scope_id: "c1",
    kind: "credential_rule", target: "operations", before: { operations: ["automation-gmail.send_email_message"] },
    after: { operations: [] }, loosens: true, changed_by: "key", key_id: "key_1",
    effective_at: "2026-11-22T09:10:00+00:00", until: null, pending: true, undone_at: null, undone_by: null,
    created_at: "2026-11-22T09:00:00+00:00",
  };
  const byName = api.on("DELETE", "/v1/connections/gmail/require_approval",
    json({ ...NAMED, approval_operations: ["send_email_message"], approval_changes: [lift] }));
  const gmail = nc.Connection.fromName("gmail");
  const [change] = await gmail.liftApproval("send_email_message", "delete_message");
  assert.equal(byName.last.query.get("operations"), "send_email_message,delete_message");
  assert.deepEqual([change.id, change.scope, change.kind, change.target, change.pending],
    ["chg_1", "credential", "credential_rule", "operations", true]);
  assert.equal(change.effectiveAt?.toISOString(), "2026-11-22T09:10:00.000Z");
  // Waiting out its undo window, the rule still holds what was lifted.
  assert.deepEqual(gmail.approvalOperations, ["send_email_message"]);
  // Naming none lifts every one (by its id, now it's read).
  const byId = api.on("DELETE", "/v1/connections/con_1/require_approval", json({ ...NAMED, approval_changes: [lift] }));
  await gmail.liftApproval();
  assert.equal(byId.last.query.get("operations"), null);
});

test("an account shared with a team is read and run in that team's workspace", async () => {
  const { api } = setup();
  const TEAM = "5c0d9e4a-7b1f-4e2a-9c3d-8f6b2a1e4d70";
  const SHARED = { ...FROM_THE_APP, access: "view", organization_id: TEAM };
  const list = api.on("GET", "/v1/connections", json(listing([SHARED])));
  const runs = [...new Set([APP_ID, PATH_REF])].map((ref) => {
    api.on("GET", `/v1/connections/${ref}`, json(SHARED));
    return api.on("POST", `/v1/connections/${ref}/operations/send_email/run`,
      json({ object: "operation_result", connection: APP_ID, result: { id: "msg_1" } }));
  });
  const [shared] = await nc.Connection.list({ organizationId: TEAM });
  assert.equal(list.last.query.get("organization_id"), TEAM);
  assert.deepEqual([shared.organizationId, shared.access], [TEAM, "view"]);
  // What it does goes to the workspace it was read in, and one named by id with its workspace goes there too.
  assert.deepEqual(await shared.run("send_email", { to: "a@b.c" }), { id: "msg_1" });
  await nc.Connection.fromId(APP_ID, { organizationId: TEAM }).run("send_email", { to: "a@b.c" });
  const ran = runs.flatMap((route) => route.calls);
  assert.equal(ran.length, 2);
  assert.ok(ran.every((call) => call.query.get("organization_id") === TEAM));
  assert.equal((await nc.Connection.get(APP_ID, { organizationId: TEAM })).organizationId, TEAM);
  // The account's own carry none.
  api.on("GET", "/v1/connections/gmail", json(NAMED));
  const own = await nc.Connection.get("gmail");
  assert.equal(own.organizationId, null);
});
