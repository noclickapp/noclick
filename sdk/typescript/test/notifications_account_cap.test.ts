// The email alerts NoClick sends your account's owner (`Notifications`), and your account's own monthly spending cap
// (`Usage.limits().account`, `Usage.setAccountCap`): both the account's, never a user's, so neither sends
// `NoClick-User` inside `asUser`.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";

const CATEGORIES = { run_failure: true, credits: true, digest: false, spend_cap: true };
const CAP = {
  object: "spend_cap", cap_usd: 50, spent_usd: 12.5, period_start: "2026-11-01T00:00:00+00:00",
  resets_at: "2026-12-01T00:00:00+00:00", reached: false,
};
const LIMITS = {
  object: "usage_limits", period_start: "2026-11-01T00:00:00+00:00", resets_at: "2026-12-01T00:00:00+00:00",
  keys: [], users: [], agents: [], projects: [],
};

test("Notifications.get reads every kind, on or off, as the account", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/notifications", json({ object: "notifications", categories: CATEGORIES }));
  const alerts = await nc.asUser("user_42", () => nc.Notifications.get());
  assert.deepEqual(alerts.categories, CATEGORIES);
  assert.equal(read.last.headers.get("NoClick-User"), null); // the owner's alerts: never a user's
});

test("Notifications.update sends only the kinds it names", async () => {
  const { api } = setup();
  const patch = api.on("PATCH", "/v1/notifications", json({
    object: "notifications", categories: { ...CATEGORIES, digest: true, credits: false },
  }));
  const alerts = await nc.Notifications.update({ digest: true, credits: false });
  assert.deepEqual(patch.last.body, { categories: { digest: true, credits: false } });
  assert.equal(patch.last.headers.get("NoClick-User"), null);
  assert.deepEqual([alerts.categories.digest, alerts.categories.credits, alerts.categories.run_failure], [true, false, true]);
});

test("a kind NoClick doesn't send rejects with InvalidRequest", async () => {
  const { api } = setup();
  api.on("PATCH", "/v1/notifications", apiError(400, "invalid_request", "categories.newsletter: not a category"));
  await assert.rejects(nc.Notifications.update({ newsletter: false }), nc.InvalidRequest);
});

const SET_BY = {
  by: "agent", responsible_user_id: "6c1f0e9a-0000-4000-8000-000000000001", key_id: "key_1", grant_id: null,
  agent_id: "ag_1", turn_id: "op_1", client: "support", approval_id: null, cap_before_usd: 80, cap_after_usd: 50,
  at: "2026-11-21T09:30:00+00:00",
};

test("Usage.limits carries the account's own cap and who set it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/usage/limits", json({ ...LIMITS, account: { ...CAP, set_by: SET_BY } }),
    json({ ...LIMITS, account: { object: "spend_cap", cap_usd: null, set_by: null } }));
  const { account } = await nc.Usage.limits();
  assert.deepEqual([account?.capUsd, account?.spentUsd, account?.reached], [50, 12.5, false]);
  assert.equal(account?.resetsAt?.toISOString(), "2026-12-01T00:00:00.000Z");
  const who = account?.setBy;
  assert.deepEqual([who?.by, who?.responsibleUserId, who?.agentId, who?.turnId, who?.client, who?.grantId],
    ["agent", SET_BY.responsible_user_id, "ag_1", "op_1", "support", null]);
  assert.deepEqual([who?.capBeforeUsd, who?.capAfterUsd, who?.at?.toISOString()], [80, 50, "2026-11-21T09:30:00.000Z"]);
  const none = (await nc.Usage.limits()).account;
  assert.deepEqual([none?.capUsd, none?.spentUsd, none?.periodStart, none?.reached, none?.setBy],
    [null, null, null, false, null]);
});

test("Usage.setAccountCap puts it as the account", async () => {
  const { api } = setup();
  const put = api.on("PUT", "/v1/usage/limits/account", json({ ...CAP, cap_usd: 30 }));
  const cap = await nc.asUser("user_42", () => nc.Usage.setAccountCap(30));
  assert.deepEqual(put.last.body, { cap_usd: 30 });
  assert.equal(put.last.headers.get("NoClick-User"), null);
  assert.deepEqual([cap.capUsd, cap.spentUsd], [30, 12.5]);
});

test("a key raising or removing the cap rejects with PermissionDenied", async () => {
  const { api } = setup();
  const put = api.on("PUT", "/v1/usage/limits/account", apiError(403, "permission_denied",
    "A key only lowers the account's monthly spending cap, or sets one where there's none: this removes its spending "
    + "cap of $50.00 a month, which is the account's owner's to do."));
  await assert.rejects(nc.Usage.setAccountCap(null), nc.PermissionDenied);
  assert.deepEqual(put.last.body, { cap_usd: null });
});
