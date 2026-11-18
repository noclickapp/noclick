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
