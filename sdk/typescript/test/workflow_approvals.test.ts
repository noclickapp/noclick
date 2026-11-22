import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, listing, setup } from "./helpers.ts";

const APPROVAL = {
  object: "workflow_approval", id: "wa_1", workflow_id: "wf_1", workflow_name: "Invoices", run_id: "run_1",
  step: "gate", title: "Pay invoice 1042",
  fields: [{ name: "amount", type: "number", label: "Amount", description: "", required: true, options: null }],
  values: { amount: "420" }, status: "pending", created_at: "2026-11-20T09:00:00Z", expires_at: "2026-11-27T09:00:00Z",
  decided_at: null, decided_by: null, decided_by_key: null, note: null, sent_to: ["email"],
};

test("a workflow's waiting steps list, and one loads by id", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/wf_1", json({ object: "workflow", id: "wf_1", name: "Invoices", version: 3 }));
  const listed = api.on("GET", "/v1/workflows/wf_1/approvals", json(listing([APPROVAL])));
  const [approval] = await nc.Workflow.fromId("wf_1").approvals({ status: "pending" });
  assert.equal(listed.last.query.get("status"), "pending");
  assert.equal(listed.last.headers.get("NoClick-User"), null);
  assert.deepEqual([approval.id, approval.workflowId, approval.runId, approval.step, approval.status], ["wa_1", "wf_1", "run_1", "gate", "pending"]);
  assert.deepEqual([approval.values, approval.fields[0].label, approval.decidedBy, approval.sentTo], [{ amount: "420" }, "Amount", null, ["email"]]);
  assert.equal(approval.expiresAt?.getUTCDate(), 27);

  api.on("GET", "/v1/workflows/wf_1/approvals/wa_1", json(APPROVAL));
  const lazy = await nc.WorkflowApproval.fromId("wf_1", "wa_1").hydrate();
  assert.deepEqual([lazy.title, lazy.workflowName], ["Pay invoice 1042", "Invoices"]);
  assert.deepEqual((await nc.WorkflowApproval.list("wf_1")).map((a) => a.id), ["wa_1"]);
});

test("code approves with values and declines as the account, never as a user", async () => {
  const { api } = setup();
  const decided = {
    ...APPROVAL, status: "approved", decided_at: "2026-11-20T09:05:00Z", decided_by: "code",
    decided_by_key: { key_id: "key_9", key_name: "approver" }, note: "Checked.", values: { amount: "400" },
  };
  const answer = api.on("POST", "/v1/workflows/wf_1/approvals/wa_1/answer", json(decided));
  const approval = await nc.asUser("user_42", () =>
    nc.WorkflowApproval.fromId("wf_1", "wa_1").approve({ note: "Checked.", values: { amount: "400" } }));
  assert.deepEqual(answer.last.body, { approved: true, note: "Checked.", values: { amount: "400" } });
  assert.equal(answer.last.headers.get("NoClick-User"), null);
  assert.deepEqual([approval.status, approval.decidedBy, approval.decidedByKey?.key_id, approval.values], ["approved", "code", "key_9", { amount: "400" }]);

  const declined = api.on("POST", "/v1/workflows/wf_1/approvals/wa_2/answer", json({ ...APPROVAL, id: "wa_2", status: "declined" }));
  assert.equal((await nc.WorkflowApproval.fromId(nc.Workflow.fromId("wf_1"), "wa_2").decline()).status, "declined");
  assert.deepEqual(declined.last.body, { approved: false });
});

test("a key without the scope, a second answer and a late one are refused", async () => {
  const { api } = setup();
  api.on("POST", "/v1/workflows/wf_1/approvals/wa_1/answer",
    apiError(403, "permission_denied", "This key lacks the 'approvals:answer' scope.", { scope: "approvals:answer" }));
  await assert.rejects(nc.WorkflowApproval.fromId("wf_1", "wa_1").approve(), (error: unknown) =>
    error instanceof nc.PermissionDenied && /approvals:answer/.test(error.message));
  api.on("POST", "/v1/workflows/wf_1/approvals/wa_2/answer", apiError(409, "conflict", "This approval was already answered."));
  await assert.rejects(nc.WorkflowApproval.fromId("wf_1", "wa_2").decline(), (error: unknown) => error instanceof nc.Conflict);
  api.on("POST", "/v1/workflows/wf_1/approvals/wa_3/answer", apiError(410, "expired", "This approval expired."));
  await assert.rejects(nc.WorkflowApproval.fromId("wf_1", "wa_3").approve(), (error: unknown) => error instanceof nc.Expired);
});

test("a step names who answers it, and says which agent decided", async () => {
  const { api } = setup();
  const agent = { object: "approver", kind: "agent", agent_id: "ag_1" };
  api.on("GET", "/v1/workflows/wf_1/approvals/wa_1", json({ ...APPROVAL, approver: agent, on_timeout: "escalate", sent_to: [] }));
  const routed = await nc.WorkflowApproval.fromId("wf_1", "wa_1").hydrate();
  assert.deepEqual([routed.approver.kind, routed.approver.agent_id, routed.onTimeout, routed.sentTo], ["agent", "ag_1", "escalate", []]);
  api.on("POST", "/v1/workflows/wf_1/approvals/wa_1/answer", json({
    ...APPROVAL, status: "approved", decided_by: "agent", approver: agent, on_timeout: "decline",
    decided_by_agent: { agent_id: "ag_1", name: "Finance lead" },
  }));
  const decided = await routed.approve();
  assert.deepEqual([decided.decidedBy, decided.decidedByAgent?.name, decided.decidedByKey], ["agent", "Finance lead", null]);
});
