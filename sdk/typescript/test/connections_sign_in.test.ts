// Signing your account in to an app whose authorize step a page of yours ran (Connection.signIn), against the mock
// API: the body it sends (its secrets under their own fields), the connection it answers, and a pick finished.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const APP_CONNECTION = {
  object: "connection", id: "credential:c1", name: "ada@example.test", integration: "google_sheets",
  credential_type: "google_sheets_oauth", user_id: null, status: "connected", origin: "app", access: "owner",
  approval_operations: [], account: null, verification: null, connect_link: null, used_by: [], connected_at: null,
  created_at: null, updated_at: null,
};

test("signIn sends the code and its secrets and answers the account's connection", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/connections/sign_ins", json({
    object: "sign_in", id: null, status: "connected", provider: "google", connection: APP_CONNECTION,
    account: { email: "ada@example.test" }, choose: null,
  }));
  const signedIn = await nc.Connection.signIn("google", {
    code: "g-code", redirectUri: "https://app.test/cb", scopes: ["email"], name: "Mine", inputs: { region: "eu" },
    oauthApp: { client_id: "own", client_secret: "own-secret" },
  });
  assert.deepEqual(route.last.body, {
    provider: "google", code: "g-code", redirect_uri: "https://app.test/cb", scopes: ["email"], name: "Mine",
    inputs: { region: "eu" }, client: { client_id: "own", client_secret: "own-secret" },
  });
  assert.deepEqual([signedIn.status, signedIn.provider, signedIn.id], ["connected", "google", null]);
  assert.equal(signedIn.connection?.id, "credential:c1");
  assert.deepEqual([signedIn.account, signedIn.choices], [{ email: "ada@example.test" }, []]);
});

test("a sign-in that asks for a pick is finished with it", async () => {
  const { api } = setup();
  api.on("POST", "/v1/connections/sign_ins", json({
    object: "sign_in", id: "si_1", status: "choose", provider: "supabase", connection: null, account: {},
    choose: { what: "project", choices: [{ id: "proj-a", name: "Alpha" }, { id: "proj-b", name: "Beta" }] },
  }));
  const finish = api.on("POST", "/v1/connections/sign_ins/si_1/finish", json({
    object: "sign_in", id: null, status: "connected", provider: "supabase", connection: APP_CONNECTION,
    account: { project_url: "https://proj-b.supabase.co" }, choose: null,
  }));
  const signedIn = await nc.Connection.signIn("supabase", { code: "s", redirectUri: "https://app.test/cb", codeVerifier: "v" });
  assert.deepEqual([signedIn.status, signedIn.what, signedIn.choices.map((c) => c.id)], ["choose", "project", ["proj-a", "proj-b"]]);
  const done = await signedIn.finish("proj-b");
  assert.deepEqual(finish.last.body, { choice: "proj-b" });
  assert.deepEqual([done.status, done.connection?.id], ["connected", "credential:c1"]);
  await assert.rejects(done.finish("proj-a"), nc.InvalidRequest);
});

test("a pick is finished by the sign-in's id alone", async () => {
  const { api } = setup();
  const finish = api.on("POST", "/v1/connections/sign_ins/si_9/finish", json({
    object: "sign_in", id: null, status: "connected", provider: "facebook", connection: APP_CONNECTION,
    account: { instagram_username: "ada" }, choose: null,
  }));
  const done = await nc.Connection.finishSignIn("si_9", "ig-2");
  assert.deepEqual(finish.last.body, { choice: "ig-2" });
  assert.deepEqual([done.status, done.account], ["connected", { instagram_username: "ada" }]);
});

const waitingSignIn = (shown: Record<string, unknown> = {}) => ({
  object: "sign_in", id: "si_w", status: "waiting", provider: "codex", credential: null, connection: null, account: {},
  choose: null, waiting: {
    way: "device", user_code: "ABCD-1234", verification_url: "https://auth.openai.com/codex/device",
    verification_url_complete: null, authorize_url: null, interval: 0, expires_at: "2026-11-24T12:00:00+00:00", ...shown,
  },
});
const CONNECTED_PLAN = {
  object: "sign_in", id: null, status: "connected", provider: "codex",
  credential: { id: "c1", name: "ChatGPT (Codex)", credential_type: "agent_codex_oauth" },
  connection: APP_CONNECTION, account: {}, choose: null, waiting: null,
};

test("a device code's sign-in starts and is waited on until the person enters it", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/connections/sign_ins", json(waitingSignIn()));
  const polls = api.on("POST", "/v1/connections/sign_ins/si_w/finish", json(waitingSignIn()), json(CONNECTED_PLAN));
  const chatgpt = await nc.Connection.signIn("codex", { name: "ChatGPT" });
  assert.deepEqual(start.last.body, { provider: "codex", name: "ChatGPT" });
  assert.deepEqual([chatgpt.status, chatgpt.way, chatgpt.userCode, chatgpt.verificationUrl, chatgpt.interval],
    ["waiting", "device", "ABCD-1234", "https://auth.openai.com/codex/device", 0]);
  const done = await chatgpt.wait();
  assert.equal(polls.calls.length, 2);
  assert.deepEqual([done.status, done.credential?.credential_type], ["connected", "agent_codex_oauth"]);
});

test("a Claude plan's sign-in finishes with the code its page showed", async () => {
  const { api } = setup();
  api.on("POST", "/v1/connections/sign_ins", json(waitingSignIn({
    way: "code", user_code: null, verification_url: null, authorize_url: "https://claude.ai/oauth/authorize?x=1",
  })));
  const finish = api.on("POST", "/v1/connections/sign_ins/si_w/finish", json({ ...CONNECTED_PLAN, provider: "claude_code" }));
  const claude = await nc.Connection.signIn("claude_code", { reconnect: "credential:c1" });
  assert.equal(claude.authorizeUrl, "https://claude.ai/oauth/authorize?x=1");
  await assert.rejects(claude.wait(), nc.InvalidRequest);
  const done = await claude.finish(null, { code: "pasted#state" });
  assert.deepEqual(finish.last.body, { code: "pasted#state" });
  assert.equal(done.status, "connected");
});
