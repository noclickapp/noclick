// An app's key to the account (`app.accountKey`): read where it stands, give it, take it away, replace its bearers.
// Nothing here ever carries a key's value: the API answers none.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, operation, setup } from "./helpers.ts";

const ASKS = {
  scopes: ["agents", "channels"], commit: "9f2c1ab",
  can: [
    { scope: "agents", can: "run, change and delete your agents", reads_secrets: false },
    { scope: "channels", can: "read and post in your spaces and channels", reads_secrets: false },
  ],
};
const WAITING = {
  object: "app_account_key", project_id: "prj_1", status: "waiting", variable: "NOCLICK_API_KEY", asks: ASKS, key: null,
  missing_scopes: [],
  request: { status: "waiting", scopes: ["agents", "channels"], asked_at: "2026-11-23T09:00:00+00:00", approval_id: "apr_1", operation_id: "op_held" },
  cannot: ["make, change or revoke API keys, its own included"], note: "Anyone who can change it.",
};
const GRANTED = {
  ...WAITING, status: "granted", request: null,
  key: {
    id: "key_1", name: "console (the app's key to the account)", scopes: ["agents", "channels"], spend_cap_usd_per_month: 50,
    granted_at: "2026-11-23T09:05:00+00:00", last_used_at: null,
  },
};

test("where an app's key stands reads what it asks for and what it waits on", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1/account_key", json(WAITING));
  const key = await nc.Project.fromId("prj_1").accountKey.get();
  assert.deepEqual([key.status, key.granted, key.variable], ["waiting", false, "NOCLICK_API_KEY"]);
  assert.deepEqual(key.asks.map((line) => [line.scope, line.readsSecrets]), [["agents", false], ["channels", false]]);
  assert.equal(key.asks[0].can, "run, change and delete your agents");
  assert.deepEqual([key.commit, key.keyId, key.scopes, key.missingScopes], ["9f2c1ab", null, [], []]);
  assert.deepEqual([key.request?.status, key.request?.approvalId, key.request?.operationId], ["waiting", "apr_1", "op_held"]);
  assert.equal(key.request?.askedAt?.getUTCFullYear(), 2026);
  assert.deepEqual(key.cannot, WAITING.cannot);

  api.on("GET", "/v1/projects/prj_2/account_key", json({ ...WAITING, status: "none", asks: null, request: null }));
  const none = await nc.Project.fromId("prj_2").accountKey.get();
  assert.deepEqual([none.status, none.asks, none.commit, none.request], ["none", [], null, null]);
});

test("giving it sends the scopes and never a key", async () => {
  const { api } = setup();
  const give = api.on("PUT", "/v1/projects/prj_1/account_key", json(GRANTED));
  const app = nc.Project.fromId("prj_1");
  const key = await app.accountKey.give(["agents", "channels"], { spendCapUsdPerMonth: 50 });
  assert.deepEqual(give.last.body, { scopes: ["agents", "channels"], spend_cap_usd_per_month: 50 });
  assert.deepEqual([key.granted, key.keyId, key.scopes, key.spendCapUsdPerMonth], [true, "key_1", ["agents", "channels"], 50]);
  assert.equal(key.grantedAt?.getUTCFullYear(), 2026);
  assert.equal(key.lastUsedAt, null);
  assert.ok(!JSON.stringify(key.raw).includes("nk_"));

  // Left out, the scopes are what its repository asks for now, and a cap it holds is left alone.
  api.on("GET", "/v1/projects/prj_1/account_key", json(WAITING));
  await app.accountKey.give();
  assert.deepEqual(give.last.body, { scopes: ["agents", "channels"] });
  await app.accountKey.give(["agents", "channels"], { spendCapUsdPerMonth: null });
  assert.deepEqual(give.last.body, { scopes: ["agents", "channels"], spend_cap_usd_per_month: null });
});

test("what its repository doesn't ask for is a conflict, and a held one waits for the owner", async () => {
  const { api } = setup();
  api.on("PUT", "/v1/projects/prj_1/account_key", json({
    error: { type: "conflict", message: "The app console's repository asks for agents, channels.", asks: ["agents", "channels"] },
  }, { status: 409 }));
  await assert.rejects(nc.Project.fromId("prj_1").accountKey.give(["agents", "queues"]), (refused: unknown) => {
    assert.ok(refused instanceof nc.Conflict);
    assert.deepEqual(refused.details.asks, ["agents", "channels"]);
    return true;
  });
  api.on("PUT", "/v1/projects/prj_2/account_key", json({
    error: { type: "approval_required", message: "It waits for the account's owner.", approval_id: "apr_2", operation_id: "op_2", sent_to: ["email"] },
  }, { status: 402 }));
  await assert.rejects(nc.Project.fromId("prj_2").accountKey.give(["agents"]), (held: unknown) => {
    assert.ok(held instanceof nc.ApprovalRequired);
    assert.equal(held.details.approval_id, "apr_2");
    return true;
  });
});

test("taking it away and replacing its bearers", async () => {
  const { api } = setup();
  const revoke = api.on("POST", "/v1/projects/prj_1/account_key/revoke", json({
    ...WAITING, status: "revoked", request: { ...WAITING.request, status: "revoked", approval_id: null, operation_id: null },
  }));
  const gone = await nc.Project.fromId("prj_1").accountKey.revoke();
  assert.equal(revoke.count, 1);
  assert.deepEqual([gone.status, gone.request?.status, gone.request?.approvalId], ["revoked", "revoked", null]);

  const rotate = api.on("POST", "/v1/projects/prj_1/account_key/rotate", json(operation({ id: "op_r", kind: "deployment.promote", status: "queued" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_r/wait", json(operation({
    id: "op_r", kind: "deployment.promote", status: "succeeded",
    result: { object: "deployment", id: "dep_1", project_id: "prj_1", status: "ready", production: true },
  })));
  const released = await (await nc.Project.fromId("prj_1").accountKey.rotate()).wait();
  assert.equal(rotate.count, 1);
  assert.ok(released instanceof nc.Deployment);
  assert.equal(released.id, "dep_1");
});
