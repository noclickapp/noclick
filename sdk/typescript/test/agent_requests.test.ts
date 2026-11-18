// A coding agent's permission mode per conversation, and answering what its harness asks a person from code.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "coder", model: "sonnet", harness: "claude_code", instructions: "Fix docs.",
  tools: [], user_id: null, workflow_id: "wf_1", created_at: "2026-11-09T10:00:00Z",
};
const ASKED = {
  object: "harness_request", id: "req_1", kind: "approval", action: "command", title: "Run git push origin main",
  detail: "git push origin main", status: "pending", options: [{ option_id: "allow_once", name: "Approve", kind: "allow_once" }],
  operation_id: "op_1", created_at: "2026-11-10T10:00:00Z", expires_at: "2026-11-10T10:20:00Z",
};

test("a conversation's permission mode is set and read back", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const route = api.on("PATCH", "/v1/agents/ag_1/conversations/main%2F1", json({
    object: "conversation_settings", permission_mode: "auto", effective_permission_mode: "approval-required",
    permission_modes: ["approval-required", "auto-accept-edits", "full-access"], not_supported: { auto: "No review here." },
  }));
  const settings = await nc.Agent.fromId("ag_1").setPermissionMode("main/1", "auto");
  assert.deepEqual(route.last.body, { permission_mode: "auto" });
  assert.deepEqual([settings.permissionMode, settings.effectivePermissionMode], ["auto", "approval-required"]);
  assert.deepEqual(settings.permissionModes, ["approval-required", "auto-accept-edits", "full-access"]);
  assert.equal(settings.notSupported.auto, "No review here.");
});

test("what the harness asks is listed and answered", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const listed = api.on("GET", "/v1/agents/ag_1/conversations/main/requests", json({ object: "list", data: [ASKED] }));
  const coder = nc.Agent.fromId("ag_1");
  const [asked] = await coder.requests("main", { status: "pending" });
  assert.equal(listed.last.query.get("status"), "pending");
  assert.deepEqual([asked.id, asked.kind, asked.action, asked.title], ["req_1", "approval", "command", "Run git push origin main"]);
  assert.equal(asked.options[0].optionId, "allow_once");
  assert.equal(asked.expiresAt?.toISOString(), "2026-11-10T10:20:00.000Z");
  const answered = api.on("POST", "/v1/agents/ag_1/conversations/main/requests/req_1", json({
    ...ASKED, status: "answered", answer: { decision: "reject_once", note: "Use a branch." },
  }));
  const done = await coder.answer("main", "req_1", "reject_once", { note: "Use a branch." });
  assert.deepEqual(answered.last.body, { decision: "reject_once", note: "Use a branch." });
  assert.equal(done.status, "answered");
  const question = api.on("POST", "/v1/agents/ag_1/conversations/main/requests/req_q", json({ ...ASKED, id: "req_q", kind: "question" }));
  await coder.answer("main", "req_q", "allow_once", { answers: { "Which color?": ["Blue"] } });
  assert.deepEqual(question.last.body, { decision: "allow_once", answers: { "Which color?": ["Blue"] } });
});
