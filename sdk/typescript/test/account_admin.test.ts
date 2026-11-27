// The account and its admin routes, each as one typed call: the account and its status, keys (listed, changed,
// revoked, a setup code, a publishable one), connected apps a page at a time, a CLI sign-in answered, machines asked
// for, a user reactivated and a deletion previewed. Each is the account's own call: none sends `NoClick-User`.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup, userRow } from "./helpers.ts";

const list = (data: unknown[], nextCursor: string | null = null) => json({ object: "list", data, next_cursor: nextCursor });
const KEY = {
  object: "key", id: "key_1", kind: "api", type: "secret", name: "worker", key_prefix: "nk_live_ab12", scopes: ["agents"],
  spend_cap_usd_per_month: null, user_id: null, created_at: "2026-11-25T10:00:00Z", last_used_at: null, expires_at: null,
  revoked_at: null,
};

test("the account is read, changed and seen at a glance", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/account", json({
    object: "account", id: "acc_1", plan: { tier: "member" }, balance: { remaining_usd: 12.5 }, default_region: "eu",
    spending_paused: { message: "Top up", action: null }, meta: { scopes: ["agents"], explicit_scopes: ["keys:create"] },
  }));
  const account = await nc.asUser("user_42", () => nc.Account.get());
  assert.deepEqual([account.planTier, account.balance.remaining_usd, account.spendingPaused?.message], ["member", 12.5, "Top up"]);
  assert.equal(read.last.headers.get("NoClick-User"), null);
  const changed = api.on("PATCH", "/v1/account", json({ object: "account", id: "acc_1", default_region: null }));
  assert.equal((await nc.Account.update({ defaultRegion: null, spendCapUsd: 200 })).defaultRegion, null);
  assert.deepEqual(changed.last.body, { default_region: null, spend_cap_usd: 200 });

  api.on("GET", "/v1/status", json({ object: "status", account: { id: "acc_1", name: "Acme" }, approvals_pending: [{ id: "ap_1" }] }));
  const status = await nc.Account.status();
  assert.deepEqual([status.account.name, status.approvalsPending[0].id], ["Acme", "ap_1"]);
  api.on("GET", "/v1/public_endpoints", list([{ kind: "agent_share", id: "sh_1", name: "Support", url: "https://x", user_id: null }]));
  assert.equal((await nc.Account.publicEndpoints())[0].name, "Support");
  api.on("GET", "/v1/objects/nk_live_ab12", json({ object: "object_ref", type: "key", id: "key_1", user_id: null }));
  assert.equal((await nc.Account.resolve("nk_live_ab12")).type, "key");
  const linked = api.on("POST", "/v1/account/payment_links", json({
    object: "payment_link", kind: "funds", label: "$20 of funds", price_usd: 23, url: "https://pay", operation_id: "op_p",
  }));
  const link = await nc.Account.paymentLink({ amountUsd: 20 });
  assert.deepEqual(linked.last.body, { kind: "funds", amount_usd: 20 });
  assert.deepEqual([link.priceUsd, link.operationId], [23, "op_p"]);
});

test("keys are listed, changed and revoked, and a setup code and a publishable key made", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/keys", list([KEY], "c2"));
  const page = await nc.Key.listPage({ status: "active", limit: 1 });
  assert.deepEqual([page.data[0].keyPrefix, page.nextCursor, listed.last.query.get("status")], ["nk_live_ab12", "c2", "active"]);
  const changed = api.on("PATCH", "/v1/keys/key_1", json(KEY));
  await nc.Key.update("key_1", { name: "worker (prod)", spendCapUsdPerMonth: null });
  assert.deepEqual(changed.last.body, { name: "worker (prod)", spend_cap_usd_per_month: null });
  api.on("DELETE", "/v1/keys/key_1", json({ ...KEY, revoked_at: "2026-11-25T11:00:00Z" }));
  assert.ok((await nc.Key.revoke("key_1")).revokedAt);
  const coded = api.on("POST", "/v1/cli/setup_codes", json({ object: "setup_code", code: "nc_setup_x", key_name: "Coding agent: build an agent" }, { status: 201 }));
  const code = await nc.Key.setupCode({ name: "Coding agent: build an agent" });
  assert.deepEqual([code.code, code.keyName, coded.last.body], ["nc_setup_x", "Coding agent: build an agent", { name: "Coding agent: build an agent" }]);
  const made = api.on("POST", "/v1/keys", json({ ...KEY, type: "publishable", scopes: [] }, { status: 201 }));
  const key = await nc.Key.create("site", [], { type: "publishable", publicEndpoints: [{ kind: "agent_share", id: "sh_1" }] });
  assert.deepEqual(made.last.body, { name: "site", scopes: [], type: "publishable", public_endpoints: [{ kind: "agent_share", id: "sh_1" }] });
  assert.equal(key.type, "publishable");
});

test("connected apps, a CLI sign-in, machines and a user", async () => {
  const { api } = setup();
  const apps = api.on("GET", "/v1/connected_apps", list([{ id: "ca_1", client: { name: "Claude", id: "c" } }], "n"));
  const page = await nc.ConnectedApp.listPage({ cursor: "c1" });
  assert.deepEqual([page.data[0].clientName, page.nextCursor, apps.last.query.get("cursor")], ["Claude", "n", "c1"]);

  const login = { object: "cli_login", user_code: "WDJB-MJHT", client: "noclick-cli", hostname: "ana-mbp", key_name: "CLI on ana-mbp", status: "pending" };
  api.on("GET", "/v1/cli/logins/WDJB-MJHT", json(login));
  const answered = api.on("POST", "/v1/cli/logins/WDJB-MJHT/answer", json({ ...login, status: "approved" }));
  assert.equal((await (await nc.CliLogin.get("WDJB-MJHT")).answer(true)).status, "approved");
  assert.deepEqual(answered.last.body, { approved: true });

  api.on("GET", "/v1/machines/vetting", json({ object: "machine_vetting", status: "not_submitted", policy_version: "2026-10" }));
  assert.equal((await nc.Machine.access()).status, "not_submitted");
  const asked = api.on("POST", "/v1/machines/vetting", json({ object: "machine_vetting", status: "pending", policy_version: "2026-10" }));
  await nc.Machine.requestAccess({ companyName: "Acme", website: "https://acme.com", country: "US", useCase: "Agents", acceptUsagePolicy: true });
  assert.equal((asked.last.body as Record<string, unknown>).accept_usage_policy, true);

  const back = api.on("PATCH", "/v1/users/user_42", json(userRow({ status: "active" })));
  assert.equal((await nc.User.fromId("user_42").reactivate()).status, "active");
  assert.deepEqual(back.last.body, { status: "active" });
});

test("a deletion is previewed with what it takes", async () => {
  const { api } = setup();
  const previewed = api.on("POST", "/v1/delete_previews", json({
    object: "delete_preview", operation: "agents_delete", method: "DELETE", path: "/v1/agents/ag_1", title: "support",
    impact: { deletes: "The agent support", depends_on_it: ["2 channels"], data_lost: [], stops_billing: [], reversible: true, undo: "Restorable." },
    confirm_token: "ct_1", expires_in_s: 600,
  }, { status: 201 }));
  const preview = await nc.previewDelete("DELETE", "/v1/agents/ag_1");
  assert.deepEqual(previewed.last.body, { method: "DELETE", path: "/v1/agents/ag_1" });
  assert.deepEqual([preview.impact.dependsOnIt, preview.impact.reversible, preview.confirmToken], [["2 channels"], true, "ct_1"]);
});
