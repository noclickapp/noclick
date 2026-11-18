// App services (a project's email, payments and sign-in) over the mock API:
// the routes, bodies and user each call carries, and the typed results.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, listing, operation, setup } from "./helpers.ts";

const PROJECT = {
  object: "project", id: "prj_1", name: "booking", url: "https://booking.noclick.site", repo_id: "repo_1",
  framework: "remix", production_branch: "main", domain_names: ["acmebooking.com"], user_id: USER_ID,
  created_at: "2026-09-01T00:00:00Z",
};
const PENDING_EMAIL = {
  object: "project_email", status: "pending_dns", from_address: "noreply@acme.test", from_name: "Acme",
  domain: "acme.test", daily_limit: 200, sent_today: 0, paused_reason: null,
  records: [
    { type: "TXT", name: "@", value: "v=spf1 include:mail.noclick.site ~all", status: "pending", purpose: "SPF" },
    { type: "CNAME", name: "nc1._domainkey", value: "nc1.dkim.noclick.site", status: "verified", purpose: "DKIM" },
  ],
};
const SENT = {
  object: "sent_email", id: "em_1", to: ["ana@example.com"], subject: "Your booking", status: "delivered",
  opened: true, bounced: false, error: null, at: "2026-09-26T09:00:00Z",
};
const SIGN_IN = {
  object: "project_sign_in", status: "active", providers: ["email", "google"], users_table: "users", commit: "9f1c2ab",
  tables: ["users", "auth_sessions", "auth_accounts", "auth_verifications", "auth_rate_limits"], database: "DB",
  library: "better-auth", version: "1.7.7", update_available: "1.7.8", branch: null, edited_files: [],
  callback_urls: { google: "https://booking.noclick.site/api/auth/callback/google" },
  missing_secrets: ["GOOGLE_CLIENT_SECRET"], secrets: ["AUTH_SECRET", "AUTH_URL", "AUTH_PROXY_SECRET"], error: null,
};

// --- email -------------------------------------------------------------------

test("email.enable sends the domain by name and acts for the project's user", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/projects/prj_1/email", json(PENDING_EMAIL));
  const app = nc.Project.fromId("prj_1", { user: USER_ID });
  const email = await app.email.enable({ domain: nc.Domain.fromName("acme.test"), fromName: "Acme" });
  assert.deepEqual(route.last.body, { domain: "acme.test", from_name: "Acme" });
  assert.equal(route.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual([email.status, email.fromAddress, email.domain, email.dailyLimit], ["pending_dns", "noreply@acme.test", "acme.test", 200]);
  assert.deepEqual(email.records.map((r) => [r.type, r.name, r.status, r.purpose, r.required]), [
    ["TXT", "@", "pending", "SPF", true],
    ["CNAME", "nc1._domainkey", "verified", "DKIM", true],
  ]);
  await app.email.enable();
  assert.deepEqual(route.last.body, {});
});

test("a project by name is looked up before its email is read", async () => {
  const { api } = setup();
  const lookup = api.on("GET", "/v1/projects", json(listing([PROJECT])));
  const status = api.on("GET", "/v1/projects/prj_1/email", json({ object: "project_email", status: "off" }));
  const email = await nc.Project.fromName("booking").email.status();
  assert.equal(lookup.last.query.get("name"), "booking");
  assert.equal(status.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual([email.status, email.records, email.fromAddress], ["off", [], null]);
});

test("email.send posts one message with its idempotency key", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/projects/prj_1/email/send", json({ ...SENT, status: "queued", opened: null }));
  const app = nc.Project.fromId("prj_1");
  const sent = await app.email.send({
    to: "ana@example.com", subject: "Your booking", text: "See you Friday.", replyTo: "desk@acmebooking.com", idempotencyKey: "booking-1042",
  });
  assert.deepEqual(route.last.body, { to: ["ana@example.com"], subject: "Your booking", text: "See you Friday.", reply_to: "desk@acmebooking.com" });
  assert.equal(route.last.headers.get("Idempotency-Key"), "booking-1042");
  assert.deepEqual([sent.id, sent.status, sent.opened, sent.bounced, sent.kind], ["em_1", "queued", null, false, "message"]);
  await assert.rejects(app.email.send({ to: "ana@example.com", subject: "Empty" }), TypeError);
  assert.equal(route.count, 1);
});

test("email.send reads held while the account can't pay, and a time-sensitive send says so", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/projects/prj_1/email/send", json({ ...SENT, status: "held", opened: null }));
  const app = nc.Project.fromId("prj_1");
  assert.equal((await app.email.send({ to: "ana@example.com", subject: "New enquiry", text: "Hi" })).status, "held");
  assert.deepEqual(route.last.body, { to: ["ana@example.com"], subject: "New enquiry", text: "Hi" });
  await app.email.send({ to: "ana@example.com", subject: "Your sign-in link", text: "https://acme.test/in", timeSensitive: true });
  assert.deepEqual(route.last.body, {
    to: ["ana@example.com"], subject: "Your sign-in link", text: "https://acme.test/in", time_sensitive: true,
  });
});

test("email.sendCode sends a one-time code on its own lane", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/projects/prj_1/email/codes", json({ ...SENT, status: "sent", kind: "code", opened: null }));
  const sent = await nc.Project.fromId("prj_1").email.sendCode("ana@example.com", "482913", { expiresInS: 300 });
  assert.deepEqual(route.last.body, { to: "ana@example.com", code: "482913", purpose: "sign_in", expires_in_s: 300 });
  assert.deepEqual([sent.kind, sent.status, sent.opened], ["code", "sent", null]);
});

test("email setup carries the broadcast stream's own status and address", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1/email", json({
    ...PENDING_EMAIL, status: "active", broadcast_status: "pending_dns", broadcast_from_address: "noreply@news.acme.test",
    broadcast_sent_today: 0, broadcast_paused_reason: null,
  }));
  const email = await nc.Project.fromId("prj_1").email.status();
  assert.deepEqual([email.broadcastStatus, email.broadcastFromAddress, email.broadcastSentToday], ["pending_dns", "noreply@news.acme.test", 0]);
});

test("email reads pending, with why once setting it up failed, until its sending is set up", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1/email", json({ ...PENDING_EMAIL, status: "pending", pending_reason: "NoClick keeps trying." }));
  const email = await nc.Project.fromId("prj_1").email.status();
  assert.deepEqual([email.status, email.pendingReason], ["pending", "NoClick keeps trying."]);
});

test("email.messages reads newest first, 50 by default, filtered by recipient", async () => {
  const { api } = setup();
  const bounced = { ...SENT, id: "em_2", to: "bob@example.com", status: "bounced", bounced: true, opened: null, error: "550 mailbox unavailable" };
  const route = api.on("GET", "/v1/projects/prj_1/email/messages", json(listing([SENT, bounced])));
  const [first, second] = await nc.Project.fromId("prj_1").email.messages({ to: "ana@example.com", limit: 10 });
  assert.equal(route.last.query.get("to"), "ana@example.com");
  assert.equal(route.last.query.get("limit"), "10");
  assert.equal(first.at?.toISOString(), "2026-09-26T09:00:00.000Z");
  assert.deepEqual([second.to, second.bounced, second.error], [["bob@example.com"], true, "550 mailbox unavailable"]);
  await nc.Project.fromId("prj_1").email.messages();
  assert.equal(route.last.query.get("limit"), "50");
});

test("email.messages reads a preview's outbox: what it kept, with what it would have said", async () => {
  const { api } = setup();
  const kept = { ...SENT, status: "captured", opened: null, environment: "preview", captured: ["ana@example.com"], text: "See you Friday.", html: null };
  const route = api.on("GET", "/v1/projects/prj_1/email/messages", json(listing([kept, SENT])));
  const [message, sent] = await nc.Project.fromId("prj_1").email.messages({ environment: "preview" });
  assert.equal(route.last.query.get("environment"), "preview");
  assert.deepEqual([message.status, message.environment, message.captured, message.text], ["captured", "preview", ["ana@example.com"], "See you Friday."]);
  assert.deepEqual([sent.environment, sent.captured, sent.text], ["production", [], null]);
});

// --- payments ----------------------------------------------------------------

test("payments.enable opens a test account in a country, with a stable claim link", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/projects/prj_1/payments", json({
    object: "project_payments", mode: "test", claim_step: "claim", next_step: "Send the owner claim_url.",
    claim_url: "https://api.example.com/api/public/payments/claim/c_1", test_expires_at: "2026-12-01T09:00:00Z",
    dashboard_url: null, secrets: ["PAYMENTS_SECRET_KEY", "PAYMENTS_PUBLISHABLE_KEY"], processor: "stripe", country: "US",
    webhook_url: "https://booking.noclick.site/api/payments/webhook",
  }));
  const status = api.on("GET", "/v1/projects/prj_1/payments", json({ object: "project_payments", mode: "live", dashboard_url: "https://payments.example/d" }));
  const app = nc.Project.fromId("prj_1", { user: USER_ID });
  const payments = await app.payments.enable({ country: "US", businessName: "Acme Booking" });
  assert.deepEqual(route.last.body, { country: "US", business_name: "Acme Booking" });
  assert.equal(route.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual([payments.mode, payments.claimStep, payments.claimUrl, payments.testExpiresAt?.toISOString()],
    ["test", "claim", "https://api.example.com/api/public/payments/claim/c_1", "2026-12-01T09:00:00.000Z"]);
  assert.deepEqual([payments.country, payments.processor, payments.webhookUrl], ["US", "stripe", "https://booking.noclick.site/api/payments/webhook"]);
  assert.deepEqual(payments.secrets, ["PAYMENTS_SECRET_KEY", "PAYMENTS_PUBLISHABLE_KEY"]);
  const live = await app.payments.status();
  assert.equal(status.count, 1);
  assert.deepEqual([live.mode, live.claimUrl, live.dashboardUrl, live.secrets], ["live", null, "https://payments.example/d", []]);
});

// --- sign-in -----------------------------------------------------------------

test("signIn.enable is an operation whose wait gives the setup", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/projects/prj_1/sign_in", json(operation({ kind: "project.sign_in.enable", status: "running" })));
  const done = operation({ kind: "project.sign_in.enable", status: "succeeded", result: SIGN_IN });
  api.on("GET", "/v1/operations/op_1/wait", json(done));
  api.on("GET", "/v1/operations/op_1", json(done));
  const app = nc.Project.fromId("prj_1", { user: USER_ID });
  const op = await app.signIn.enable(["email", "google"], { branch: "add-sign-in" });
  assert.deepEqual(start.last.body, { providers: ["email", "google"], users_table: "users", branch: "add-sign-in" });
  assert.equal(start.last.headers.get("NoClick-User"), USER_ID);
  assert.ok(op instanceof nc.Operation);
  const signIn = await op.wait();
  assert.deepEqual([signIn.status, signIn.providers, signIn.usersTable, signIn.commit], ["active", ["email", "google"], "users", "9f1c2ab"]);
  assert.deepEqual([signIn.callbackUrls, signIn.missingSecrets], [{ google: "https://booking.noclick.site/api/auth/callback/google" }, ["GOOGLE_CLIENT_SECRET"]]);
  assert.deepEqual([signIn.library, signIn.version, signIn.updateAvailable, signIn.tables.length], ["better-auth", "1.7.7", "1.7.8", 5]);
  // Resumed by id, the registered reader types the result.
  const resumed = (await nc.Operation.fromId("op_1").wait()) as nc.SignInSetup;
  assert.equal(resumed.commit, "9f1c2ab");
});

test("signIn.upgrade is an operation on the version NoClick ships now", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/projects/prj_1/sign_in/upgrade", json(operation({ kind: "project.sign_in.upgrade", status: "running" })));
  api.on("GET", "/v1/operations/op_1/wait", json(operation({ kind: "project.sign_in.upgrade", status: "succeeded", result: { ...SIGN_IN, branch: "sign-in-update" } })));
  const op = await nc.Project.fromId("prj_1").signIn.upgrade({ branch: "sign-in-update" });
  assert.deepEqual(start.last.body, { branch: "sign-in-update" });
  assert.equal((await op.wait()).branch, "sign-in-update");
});

test("signIn providers sign in through NoClick, or on your own client when named", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/projects/prj_1/sign_in", json(operation({ kind: "project.sign_in.enable", status: "running" })));
  const result = { ...SIGN_IN, providers: ["email", "google", "microsoft"], managed_providers: ["microsoft"] };
  api.on("GET", "/v1/operations/op_1/wait", json(operation({ kind: "project.sign_in.enable", status: "succeeded", result })));
  const app = nc.Project.fromId("prj_1");
  const signIn = await (await app.signIn.enable(["email", "google", "microsoft"], { ownCredentials: ["google"] })).wait();
  assert.deepEqual(start.last.body, { providers: ["email", "google", "microsoft"], own_credentials: ["google"], users_table: "users" });
  assert.deepEqual([signIn.managedProviders, signIn.missingSecrets], [["microsoft"], ["GOOGLE_CLIENT_SECRET"]]);
  // An empty list moves every provider onto NoClick's; omitted, each keeps how it signs in.
  await app.signIn.enable(["email", "google"], { ownCredentials: [] });
  assert.deepEqual(start.last.body.own_credentials, []);
  await app.signIn.enable(["email", "google"]);
  assert.equal("own_credentials" in start.last.body, false);
});

test("signIn.status reads the setup", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1/sign_in", json({ object: "project_sign_in", status: "off" }));
  const signIn = await nc.Project.fromId("prj_1").signIn.status();
  assert.deepEqual([signIn.status, signIn.providers, signIn.missingSecrets], ["off", [], []]);
});
