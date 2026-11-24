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

test("an MCP server's sign-in waits on its callback and finishes with its code and state", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/connections/sign_ins", json(waitingSignIn({
    way: "redirect", user_code: null, verification_url: null, interval: null,
    authorize_url: "https://auth.example.com/authorize?x=1", state: "st_1", name: "Example Auth",
  })));
  const finish = api.on("POST", "/v1/connections/sign_ins/si_w/finish", json({
    object: "sign_in", id: null, status: "connected", provider: "mcp",
    credential: { id: "c1", name: "Example", credential_type: "mcp_oauth" }, connection: null, account: {},
    choose: null, waiting: null, verification: { reachable: true, proves: "account", samples: [{ label: "search" }] },
  }));
  const server = await nc.Connection.signIn("mcp", {
    serverUrl: "https://mcp.example.com/mcp", redirectUri: "https://app.example.com/callback", name: "Example",
  });
  assert.deepEqual(start.last.body, {
    provider: "mcp", server_url: "https://mcp.example.com/mcp", redirect_uri: "https://app.example.com/callback",
    name: "Example",
  });
  assert.deepEqual([server.way, server.authorizeUrl, server.state, server.serverName],
    ["redirect", "https://auth.example.com/authorize?x=1", "st_1", "Example Auth"]);
  await assert.rejects(server.wait(), /callback's code and state/);
  const done = await server.finish(null, { code: "the-code", state: server.state ?? undefined });
  assert.deepEqual(finish.last.body, { code: "the-code", state: "st_1" });
  assert.deepEqual([done.status, done.verification?.reachable], ["connected", true]);
});

test("an MCP server that takes a key finishes with it", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/connections/sign_ins", json(waitingSignIn({
    way: "key", user_code: null, verification_url: null, interval: null,
  })));
  const finish = api.on("POST", "/v1/connections/sign_ins/si_w/finish", json({
    object: "sign_in", id: null, status: "connected", provider: "mcp",
    credential: { id: "c1", name: "Canva", credential_type: "canva_mcp" }, connection: null, account: {},
    choose: null, waiting: null, verification: null,
  }));
  const canva = await nc.Connection.signIn("mcp", { credentialType: "canva_mcp", redirectUri: "https://app.example.com/callback" });
  assert.deepEqual([(start.last.body as Record<string, unknown>).credential_type, canva.way], ["canva_mcp", "key"]);
  const done = await canva.finish(null, { apiKey: "sk-typed" });
  assert.deepEqual(finish.last.body, { api_key: "sk-typed" });
  assert.deepEqual([done.status, done.verification], ["connected", null]);
});

test("WhatsApp's sign-in is a QR waited on until the phone scans it", async () => {
  const { api } = setup();
  const qr = (code: string) => waitingSignIn({ way: "qr", user_code: null, verification_url: null, qr_code: code, interval: 0 });
  const start = api.on("POST", "/v1/connections/sign_ins", json(qr("iVBORw0KGgo=")));
  const polls = api.on("POST", "/v1/connections/sign_ins/si_w/finish", json(qr("cm90YXRlZA==")), json({
    ...CONNECTED_PLAN, provider: "whatsapp", account: { phone_number: "12025550101" },
    credential: { id: "c1", name: "Shop line", credential_type: "whatsapp_qr" },
  }));
  const number = await nc.Connection.signIn("whatsapp", { name: "Shop line" });
  assert.deepEqual(start.last.body, { provider: "whatsapp", name: "Shop line" });
  assert.deepEqual([number.way, number.qrCode], ["qr", "iVBORw0KGgo="]);
  assert.equal((await number.finish()).qrCode, "cm90YXRlZA==");
  const done = await number.wait();
  assert.equal(polls.calls.length, 2);
  assert.deepEqual([done.status, done.account], ["connected", { phone_number: "12025550101" }]);
});

test("a WhatsApp number's agent is read and made", async () => {
  const { api } = setup();
  const agent = { id: "a1", name: "WhatsApp", channel_id: "ch1", channel_name: "whatsapp" };
  api.on("GET", "/v1/connections/credential%3Ac1", json(APP_CONNECTION));
  const read = api.on("GET", "/v1/connections/credential%3Ac1/agent", json({ object: "number_agent", available: true, agent: null }));
  const made = api.on("POST", "/v1/connections/credential%3Ac1/agent", json({
    object: "number_agent", available: true, agent, created: true,
  }));
  const number = await nc.Connection.get("credential:c1");
  const nobody = await number.numberAgent();
  assert.deepEqual([nobody.available, nobody.agentId, nobody.name, nobody.created], [true, null, null, false]);
  assert.equal(read.calls.length, 1);
  const answered = await number.makeNumberAgent();
  assert.equal(made.calls.length, 1);
  assert.deepEqual([answered.agentId, answered.name, answered.channelId, answered.channelName, answered.created],
    ["a1", "WhatsApp", "ch1", "whatsapp", true]);
});
