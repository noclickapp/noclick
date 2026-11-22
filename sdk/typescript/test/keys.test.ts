// `Key.create`: one of your account's own keys holding `keys:create` makes another, no wider than itself. It's the
// account's own call, so it never sends `NoClick-User` inside `asUser`; the secret comes back once.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";

const MADE = {
  object: "key", id: "key_2", kind: "api", type: "secret", name: "queue worker", key_prefix: "nk_live_ab12",
  scopes: ["queues", "agents"], spend_cap_usd_per_month: 20, user_id: null, created_at: "2026-11-21T09:30:00+00:00",
  last_used_at: null, expires_at: "2026-12-01T00:00:00+00:00", revoked_at: null, minted_by: "key_1", approvals: {},
  raw_key: "nk_live_FAKESECRET0001",
};

test("Key.create sends what it names and returns the secret once", async () => {
  const { api } = setup();
  const made = api.on("POST", "/v1/keys", json(MADE));
  const key = await nc.asUser("user_42", () => nc.Key.create("queue worker", ["queues", "agents"], {
    spendCapUsdPerMonth: 20, expiresAt: new Date("2026-12-01T00:00:00Z"),
  }));
  assert.deepEqual(made.last.body, {
    name: "queue worker", scopes: ["queues", "agents"], spend_cap_usd_per_month: 20,
    expires_at: "2026-12-01T00:00:00.000Z",
  });
  assert.equal(made.last.headers.get("NoClick-User"), null); // the account's own call: never a user's
  assert.deepEqual([key.id, key.mintedBy, key.spendCapUsdPerMonth, key.secret], ["key_2", "key_1", 20, "nk_live_FAKESECRET0001"]);
  assert.equal(key.expiresAt?.toISOString(), "2026-12-01T00:00:00.000Z");
  assert.equal("raw_key" in key.raw, false);
});

test("a key wider than its maker rejects with PermissionDenied", async () => {
  const { api } = setup();
  api.on("POST", "/v1/keys", apiError(403, "permission_denied", "This key can't make a key holding phone."));
  await assert.rejects(nc.Key.create("too wide", ["phone"]), nc.PermissionDenied);
});

test("Key.create pins a key to a user", async () => {
  const { api } = setup();
  const made = api.on("POST", "/v1/keys", json({ ...MADE, user_id: "dana" }));
  const key = await nc.Key.create("dana's worker", ["agents"], { userId: "dana" });
  assert.equal((made.last.body as Record<string, unknown>).user_id, "dana");
  assert.equal(key.userId, "dana");
});
