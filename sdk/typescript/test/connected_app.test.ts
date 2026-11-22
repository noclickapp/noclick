// Connected apps (`ConnectedApp`): the account's signed-in owner lists them, revokes one and restores a revoked one
// NoClick makes, as it was. They're the account's, so none sends `NoClick-User` inside `asUser`.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";

const ASSISTANT = {
  object: "connected_app", id: "ca_1", client: { name: "NoClick (your assistant)", uri: null, id: "noclick:coordinator" },
  capabilities: ["read", "build"], spend_cap_usd_per_month: 25, auto_approve_under_usd: null, approvals: {},
  spent_usd_this_month: 1.5, user_id: null, resource: "https://mcp.noclick.com", key_id: "key_1",
  created_at: "2026-11-01T00:00:00+00:00", last_used_at: null, revoked_at: "2026-11-21T09:30:00+00:00",
  restorable: true, profile: "default",
};
const CLAUDE = {
  ...ASSISTANT, id: "ca_2", client: { name: "Claude", uri: "https://claude.ai", id: "c-1" }, revoked_at: null,
  restorable: false,
};

test("ConnectedApp.list reads every page as the account", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/connected_apps",
    json({ object: "list", data: [ASSISTANT], next_cursor: "ca_1" }),
    json({ object: "list", data: [CLAUDE], next_cursor: null }));
  const apps = await nc.asUser("user_42", () => nc.ConnectedApp.list());
  assert.equal(listed.last.query.get("cursor"), "ca_1");
  assert.deepEqual(apps.map((a) => [a.id, a.clientName, a.clientId, a.revoked, a.restorable]), [
    ["ca_1", "NoClick (your assistant)", "noclick:coordinator", true, true],
    ["ca_2", "Claude", "c-1", false, false],
  ]);
  assert.deepEqual([apps[0].capabilities, apps[0].spendCapUsdPerMonth, apps[0].lastUsedAt], [["read", "build"], 25, null]);
  assert.equal(apps[0].revokedAt?.toISOString(), "2026-11-21T09:30:00.000Z");
  assert.equal(listed.last.headers.get("NoClick-User"), null);
});

test("ConnectedApp.restore turns a revoked one back on, and revoke ends it", async () => {
  const { api } = setup();
  const restored = api.on("POST", "/v1/connected_apps/ca_1/restore", json({ ...ASSISTANT, revoked_at: null }));
  const app = await nc.asUser("user_42", () => nc.ConnectedApp.restore("ca_1"));
  assert.deepEqual([app.revoked, app.capabilities], [false, ["read", "build"]]);
  assert.equal(restored.last.headers.get("NoClick-User"), null);

  api.on("DELETE", "/v1/connected_apps/ca_1", json(ASSISTANT));
  assert.equal((await nc.ConnectedApp.revoke("ca_1")).revoked, true);
});

test("a client a person connected isn't restored, and a key is refused", async () => {
  const { api } = setup();
  api.on("POST", "/v1/connected_apps/ca_2/restore",
    apiError(409, "conflict", "Claude is a client you connected, so it isn't restored: connect it again.", { reason: "reconnect" }));
  await assert.rejects(nc.ConnectedApp.restore("ca_2"), nc.Conflict);
  api.on("POST", "/v1/connected_apps/ca_1/restore",
    apiError(403, "permission_denied", "This call is for the signed-in account owner, not an API key."));
  await assert.rejects(nc.ConnectedApp.restore("ca_1"), nc.PermissionDenied);
});
