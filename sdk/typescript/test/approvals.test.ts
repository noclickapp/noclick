import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, listing, setup } from "./helpers.ts";

const APPROVAL = {
  object: "approval", id: "apr_1", status: "pending", action: "Buy +1 567 483 3618", summary: null, subject: null,
  price: { amount_usd: 1.15, recurrence: "monthly", terms: null, renewal: null }, operation: "phone_numbers_create",
  method: "POST", path: "/v1/phone_numbers", arguments: { number: "+15674833618" },
  reason: "Purchases through an API key always ask.",
  connection: { kind: "agent", name: "Support", grant_id: null, agent_id: "agt_1" }, user_id: null,
  operation_id: "op_held", held_call_status: "awaiting_human", created_at: "2026-11-19T10:00:00Z",
  expires_at: "2026-11-20T10:00:00Z", decided_at: null, decided_by: null, decided_by_key: null, note: null,
  sent_to: ["email"], impact: null, consent: [],
};

test("pending approvals list, and one loads by id", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/approvals", json(listing([APPROVAL])));
  api.on("GET", "/v1/approvals/apr_1", json(APPROVAL));
  const [approval] = await nc.Approval.list({ status: "pending" });
  assert.equal(listed.last.query.get("status"), "pending");
  assert.deepEqual([approval.id, approval.status, approval.operation, approval.operationId], ["apr_1", "pending", "phone_numbers_create", "op_held"]);
  assert.deepEqual([approval.price?.amount_usd, approval.connection.kind, approval.decidedBy], [1.15, "agent", null]);
  assert.equal(approval.expiresAt?.getUTCDate(), 20);
  const lazy = await nc.Approval.fromId("apr_1").hydrate();
  assert.deepEqual([lazy.action, lazy.sentTo], ["Buy +1 567 483 3618", ["email"]]);
});

test("code approves and declines as the account, never as a user", async () => {
  const { api } = setup();
  const decided = {
    ...APPROVAL, status: "approved", decided_at: "2026-11-19T10:05:00Z", decided_by: "code",
    decided_by_key: { key_id: "key_9", key_name: "approver" }, note: "Fine.",
  };
  const answer = api.on("POST", "/v1/approvals/apr_1/answer", json(decided));
  const approval = await nc.asUser("user_42", () => nc.Approval.fromId("apr_1").approve({ note: "Fine." }));
  assert.deepEqual(answer.last.body, { approved: true, note: "Fine." });
  assert.equal(answer.last.headers.get("NoClick-User"), null);
  assert.deepEqual([approval.status, approval.decidedBy, approval.decidedByKey?.key_id, approval.note], ["approved", "code", "key_9", "Fine."]);

  api.on("POST", "/v1/approvals/apr_2/answer", json({ ...APPROVAL, id: "apr_2", status: "declined" }));
  assert.equal((await nc.Approval.fromId("apr_2").decline()).status, "declined");
});

test("a key without the scope is refused", async () => {
  const { api } = setup();
  api.on("POST", "/v1/approvals/apr_1/answer",
    apiError(403, "permission_denied", "This key lacks the 'approvals:answer' scope.", { scope: "approvals:answer" }));
  await assert.rejects(nc.Approval.fromId("apr_1").approve(), (error: unknown) =>
    error instanceof nc.PermissionDenied && /approvals:answer/.test(error.message));
});

const POLICY = {
  object: "approval_policy",
  callers: { agent: "A platform agent's NoClick tools, and its own tool calls.", key: "A key used through MCP." },
  kinds: [
    { kind: "purchase", description: "A call with a price.", approver: "owner", outside_only: false,
      defaults: { connected_app: "under_auto_approve", agent: "ask", app: "allow" } },
    { kind: "outside_other_connection", description: "A stranger's turn beyond what it answers on.",
      approver: "connection_owner", outside_only: true, defaults: { agent: "ask" } },
  ],
};

test("the default policy reads kind by kind and caller by caller", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/approvals/policy", json(POLICY));
  const policy = await nc.asUser("user_42", () => nc.ApprovalPolicy.get());
  assert.equal(read.last.headers.get("NoClick-User"), null);
  assert.deepEqual(policy.kinds.map((k) => k.kind), ["purchase", "outside_other_connection"]);
  assert.equal(policy.default("purchase", "agent"), "ask");
  assert.equal(policy.default("purchase", "connected_app"), "under_auto_approve");
  assert.equal(policy.default("purchase", "code"), null);
  assert.deepEqual(policy.kinds[1], {
    kind: "outside_other_connection", description: "A stranger's turn beyond what it answers on.",
    approver: "connection_owner", outsideOnly: true, defaults: { agent: "ask" }, settable: false, setting: null,
    ceiling: null, effective: { agent: "ask" }, own: null,
  });
  assert.match(policy.callers.agent, /^A platform agent's/);
  assert.throws(() => policy.default("refund", "agent"), /no kind 'refund'/);
});

const CHANGE = {
  object: "approval_policy_change", id: "chg_1", batch_id: "bat_1", kind: "purchase", target: "setting", before: null,
  after: { disposition: "allow", under_usd: 20, until: null }, loosens: true, changed_by: "key", key_id: "key_9",
  effective_at: "2026-11-21T09:10:00+00:00", until: null, pending: true, undone_at: null, undone_by: null,
  created_at: "2026-11-21T09:00:00+00:00",
};

test("the account switches kinds as the account and reads back what changed", async () => {
  const { api } = setup();
  const set = {
    ...POLICY, spend_cap_set: true, changes: [CHANGE], kinds: [
      { ...POLICY.kinds[0], settable: true, setting: { disposition: "allow", under_usd: 20, until: null, pending: true },
        ceiling: null, effective: { connected_app: "under_auto_approve", agent: "allow_under", app: "allow" } },
      POLICY.kinds[1]],
  };
  const put = api.on("PUT", "/v1/approvals/policy", json(set));
  const until = new Date("2026-11-22T00:00:00Z");
  const policy = await nc.asUser("user_42", () => nc.ApprovalPolicy.set({
    settings: { purchase: { disposition: "allow", under_usd: 20 }, purge: { disposition: "allow", until }, delete: null },
  }));
  assert.equal(put.last.headers.get("NoClick-User"), null);
  assert.deepEqual(put.last.body, { settings: {
    purchase: { disposition: "allow", under_usd: 20 }, purge: { disposition: "allow", until: until.toISOString() },
    delete: null } });
  const [change] = policy.changes;
  assert.deepEqual([change.kind, change.loosens, change.pending, change.changedBy], ["purchase", true, true, "key"]);
  assert.equal(change.effectiveAt?.getUTCMinutes(), 10);
  assert.equal(policy.spendCapSet, true);
  assert.equal(policy.effective("purchase", "agent"), "allow_under");
});

test("a switch needs a cap, explain reads, and undo takes one back", async () => {
  const { api } = setup();
  api.on("PUT", "/v1/approvals/policy", apiError(403, "permission_denied", "Loosening a purchase needs a cap.",
    { reason: "spend_cap_required", field: "settings.purchase" }));
  await assert.rejects(nc.ApprovalPolicy.set({ settings: { purchase: "allow" } }), (error: unknown) =>
    error instanceof nc.PermissionDenied && /needs a cap/.test(error.message));
  const explained = api.on("POST", "/v1/approvals/policy/explain", json({
    object: "approval_explanation", kind: "purchase", caller: "agent", disposition: "ask", source: "default",
    why: "Purchases through an API key always ask.", setting: null, bounds: false }));
  const seen = await nc.ApprovalPolicy.explain("purchase", "agent", { amountUsd: 12 });
  assert.deepEqual(explained.last.body, { kind: "purchase", caller: "agent", amount_usd: 12, quoted: true, previewed: true });
  assert.deepEqual([seen.disposition, seen.source], ["ask", "default"]);
  const listed = api.on("GET", "/v1/approvals/policy/changes", json(listing([CHANGE])));
  const [change] = await nc.ApprovalPolicy.history({ limit: 5 });
  assert.equal(listed.last.query.get("limit"), "5");
  assert.equal(change.id, "chg_1");
  api.on("POST", "/v1/approvals/policy/changes/chg_1/undo", json({
    ...CHANGE, pending: false, undone_at: "2026-11-21T09:02:00+00:00", undone_by: "owner" }));
  const undone = await nc.ApprovalPolicy.undo("chg_1");
  assert.deepEqual([undone.undoneBy, undone.pending], ["owner", false]);
});

test("a key and a connected app set their own as the account, and the policy reads for one", async () => {
  const { api } = setup();
  const patched = api.on("PATCH", "/v1/keys/key_7", json({
    object: "key", id: "key_7", name: "deploy-bot",
    approvals: { purchase: { disposition: "allow", under_usd: 20, until: null, pending: false } },
    approval_changes: [{ ...CHANGE, scope: "key", scope_id: "key_7", changed_by: "owner", key_id: null, pending: false }],
  }));
  const mine = await nc.asUser("user_42", () => nc.ApprovalPolicy.setForKey("key_7", {
    purchase: { disposition: "allow", under_usd: 20 }, purge: null,
  }));
  assert.equal(patched.last.headers.get("NoClick-User"), null);
  assert.deepEqual(patched.last.body, { approvals: { purchase: { disposition: "allow", under_usd: 20 }, purge: null } });
  assert.deepEqual([mine.kind, mine.id, mine.settings.purchase.under_usd], ["key", "key_7", 20]);
  assert.deepEqual([mine.changes[0].scope, mine.changes[0].scopeId, mine.autoApproveUnderUsd], ["key", "key_7", null]);

  const app = api.on("PATCH", "/v1/connected_apps/app_1", json({
    object: "connected_app", id: "app_1", auto_approve_under_usd: null, approvals: {}, approval_changes: [] }));
  const done = await nc.ApprovalPolicy.setForConnectedApp("app_1", { autoApproveUnderUsd: null });
  assert.deepEqual(app.last.body, { auto_approve_under_usd: null });
  assert.deepEqual([done.kind, done.autoApproveUnderUsd, done.changes], ["connected_app", null, []]);
  await nc.ApprovalPolicy.setForConnectedApp("app_1", { settings: { delete: "ask" } });
  assert.deepEqual(app.last.body, { approvals: { delete: "ask" } });

  const read = api.on("GET", "/v1/approvals/policy", json({ ...POLICY, key_id: "key_7", kinds: [
    { ...POLICY.kinds[0], own: { disposition: "deny", under_usd: null, until: null },
      effective: { connected_app: "under_auto_approve", agent: "ask", app: "allow", key: "deny" } }] }));
  const policy = await nc.ApprovalPolicy.get({ keyId: "key_7" });
  assert.equal(read.last.query.get("key_id"), "key_7");
  assert.deepEqual([policy.kinds[0].own?.disposition, policy.effective("purchase", "key")], ["deny", "deny"]);
});

const AGENT = {
  object: "agent", id: "ag_1", name: "buyer", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: 50,
  created_at: "2026-09-25T10:00:00Z", approvals: {},
};
const UNDER_20 = { disposition: "allow", under_usd: 20, until: null, pending: false };

test("an agent sets its own approvals on create, update and spawn, and the policy reads and explains for it", async () => {
  const { api } = setup();
  const created = api.on("POST", "/v1/agents", json({ ...AGENT, approvals: { purchase: UNDER_20 },
    approval_changes: [{ ...CHANGE, scope: "agent", scope_id: "ag_1", changed_by: "owner", key_id: null, pending: false }] },
  { status: 201 }));
  const buyer = await nc.Agent.create("buyer", { instructions: "Buy what's asked.",
    approvals: { purchase: { disposition: "allow", under_usd: 20 } } });
  assert.deepEqual((created.last.body as { approvals: unknown }).approvals, { purchase: { disposition: "allow", under_usd: 20 } });
  assert.equal(buyer.approvals.purchase.under_usd, 20);

  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const patched = api.on("PATCH", "/v1/agents/ag_1", json(AGENT));
  await nc.Agent.fromId("ag_1").update({ approvals: { purchase: null, outside_other_connection: "allow" } });
  assert.deepEqual(patched.last.body, { approvals: { purchase: null, outside_other_connection: "allow" } });

  const spawned = api.on("POST", "/v1/agents/ag_1/children", json({ ...AGENT, id: "ag_2", parent_id: "ag_1" },
    { status: 201 }));
  await nc.Agent.fromId("ag_1").spawn("Buy a number.", { approvals: { purchase: "ask" } });
  assert.deepEqual((spawned.last.body as { approvals: unknown }).approvals, { purchase: "ask" });

  const read = api.on("GET", "/v1/approvals/policy", json({ ...POLICY, agent_id: "ag_2", kinds: [
    { ...POLICY.kinds[0], own: null,
      effective: { connected_app: "under_auto_approve", agent: "allow_under", app: "allow", key: "ask" } }] }));
  const policy = await nc.ApprovalPolicy.get({ agentId: "ag_2" });
  assert.equal(read.last.query.get("agent_id"), "ag_2");
  assert.equal(policy.effective("purchase", "agent"), "allow_under");
  const explained = api.on("POST", "/v1/approvals/policy/explain", json({
    object: "approval_explanation", kind: "purchase", caller: "agent", disposition: "allow", source: "parent",
    why: null, setting: { disposition: "allow", under_usd: 20, until: null }, bounds: false }));
  const seen = await nc.ApprovalPolicy.explain("purchase", "agent", { amountUsd: 19, agentId: "ag_2" });
  assert.equal((explained.last.body as { agent_id: unknown }).agent_id, "ag_2");
  assert.deepEqual([seen.disposition, seen.source], ["allow", "parent"]);
});
