// Invites, links and a workflow's accounts: a workflow's runs a page at a time and the accounts its steps use; a
// request for someone else's account and whether one works where it's used; joining through a share's or a team's
// invite, a team's picture and single sign-on; the account's invite link; and claiming an agent's own account.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const WF = "6f1c2d3e-4a5b-4c6d-8e7f-9a0b1c2d3e4f";

test("a workflow's runs read a page at a time, and its accounts by name and owner", async () => {
  const { api } = setup();
  const runs = api.on("GET", `/v1/workflows/${WF}/runs`, json({
    object: "list", data: [{ object: "workflow_run", id: "run_1", status: "failed" }], next_cursor: "c2",
  }));
  const workflow = nc.Workflow.fromId(WF);
  const page = await workflow.runsPage({ status: "failed", limit: 50, cursor: "c1" });
  assert.deepEqual([page.data[0].id, page.nextCursor], ["run_1", "c2"]);
  assert.deepEqual([runs.last.query.get("status"), runs.last.query.get("limit"), runs.last.query.get("cursor")], ["failed", "50", "c1"]);

  api.on("GET", `/v1/workflows/${WF}/connections`, json({ credentials: [
    { id: "cred_1", name: "Ops Gmail", credential_type: "gmail_oauth", owned_by_me: false, owner_name: "dana" },
  ] }));
  const [account] = await workflow.connections();
  assert.deepEqual([account.id, account.credentialType, account.ownedByMe, account.ownerName], ["cred_1", "gmail_oauth", false, "dana"]);
});

test("asking someone for their account, and checking one works where it's used", async () => {
  const { api } = setup();
  const asked = api.on("POST", "/v1/connections/connect_links", json({
    object: "credential_request", success: true, provide_url: "https://noclick.com/credential/provide/tok",
    request: { id: "req_1", credential_type: "slack_oauth", target_email: "sam@example.com", status: "pending", expires_at: "2026-12-01T00:00:00Z" },
  }, { status: 201 }));
  const request = await nc.ConnectLink.create("slack_oauth", { email: "sam@example.com", message: "For the digest" });
  assert.deepEqual(asked.last.body, { credential_type: "slack_oauth", target_email: "sam@example.com", message: "For the digest" });
  assert.deepEqual([request.id, request.url, request.status], ["req_1", "https://noclick.com/credential/provide/tok", "pending"]);

  const checked = api.on("GET", "/v1/connections/conn_1/access", json({ runs_for_owner: false, reason: "Not selected." }));
  const access = await nc.Connection.fromId("conn_1").accessFor({ workflow: WF, nodeType: "automation-gmail" });
  assert.deepEqual([checked.last.query.get("workflow_id"), checked.last.query.get("node_type")], [WF, "automation-gmail"]);
  assert.deepEqual([access.runsForOwner, access.reason, access.valid], [false, "Not selected.", null]);
});

test("joining through a share's invite, and a team's invite, picture and single sign-on", async () => {
  const { api } = setup();
  api.on("POST", "/v1/shares/invites/tok_s/accept", json({ object: "share_invite", workflow_id: WF, workflow_name: "Intake", refresh_session: true }));
  assert.deepEqual(await nc.Share.acceptInvite("tok_s"), { workflowId: WF, workflowName: "Intake", refreshSession: true });

  api.on("GET", "/v1/organizations/invites/tok_o", json({ object: "organization_invite", organization_name: "Acme", role: "admin" }));
  assert.equal((await nc.Organization.invitation("tok_o")).organization_name, "Acme");
  const icon = api.on("PUT", "/v1/organizations/org_1/icon", json({ object: "organization_icon", icon_url: "https://x/i.png" }));
  assert.equal((await nc.Organization.uploadIcon("org_1", "aGk=")).icon_url, "https://x/i.png");
  assert.deepEqual(icon.last.body, { image_data: "aGk=" });
  const sso = api.on("PUT", "/v1/organizations/org_1/sso", json({ object: "organization_sso", domain: "acme.com" }));
  await nc.Organization.configureSso("org_1", { domain: "acme.com", metadataUrl: "https://idp.acme.com/metadata" });
  assert.deepEqual(sso.last.body, { domain: "acme.com", metadata_url: "https://idp.acme.com/metadata" });
  const off = api.on("DELETE", "/v1/organizations/org_1/sso", json({ object: "organization_sso" }));
  await nc.Organization.disableSso("org_1");
  assert.equal(off.calls.length, 1);
});

test("the account's invite link, applying one, and claiming an agent's own account", async () => {
  const { api } = setup();
  const view = { object: "referral", code: "ana-k3x9", url: "https://noclick.com/join/ana-k3x9", share_text: "Try it",
                 reward_usd: 5, joined: 2, earned: 1, earned_usd: 5, joined_through: null, can_apply_until: null };
  api.on("GET", "/v1/referral", json(view));
  const referral = await nc.Referral.get();
  assert.deepEqual([referral.code, referral.joined, referral.earnedUsd, referral.joinedThrough], ["ana-k3x9", 2, 5, null]);
  const applied = api.on("POST", "/v1/referral/apply", json({ ...view, joined_through: { name: "Sam", channel: "web" } }));
  assert.deepEqual((await nc.Referral.apply("sam-1")).joinedThrough, { name: "Sam", channel: "web" });
  assert.deepEqual(applied.last.body, { code: "sam-1" });

  const preview = api.on("POST", "/v1/agent_signups/claims/preview", json({ agent: { name: "Builder" }, may_claim: true }));
  assert.equal((await nc.AgentSignup.previewClaim("tok_c")).may_claim, true);
  assert.deepEqual(preview.last.body, { token: "tok_c" });
  const answered = api.on("POST", "/v1/agent_signups/claims/answer", json({ status: "claimed" }));
  await nc.AgentSignup.answerClaim("tok_c", "claim", { acceptTerms: true, keyAccess: "build" });
  assert.deepEqual(answered.last.body, { token: "tok_c", decision: "claim", accept_terms: true, key_access: "build" });
});
