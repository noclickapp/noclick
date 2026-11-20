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
    approver: "connection_owner", outsideOnly: true, defaults: { agent: "ask" },
  });
  assert.match(policy.callers.agent, /^A platform agent's/);
  assert.throws(() => policy.default("refund", "agent"), /no kind 'refund'/);
});
