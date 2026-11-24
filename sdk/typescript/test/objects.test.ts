import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { BASE, USER_ID, apiError, json, listing, operation, setup, userRow } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const CONNECTION = {
  object: "connection", id: "con_1", name: "gmail", integration: "gmail", credential_type: "gmail_oauth",
  user_id: USER_ID, status: "connected", account: "ana@gmail.com", connect_link: null,
  verification: { reachable: true, samples: ["INBOX"], message: "ok" },
  connected_at: "2026-09-25T10:00:00Z", created_at: "2026-09-25T10:00:00Z", updated_at: "2026-09-25T10:00:00Z",
};
const PENDING = {
  ...CONNECTION, status: "pending", account: null, verification: null, connected_at: null,
  connect_link: { id: "lnk_1", url: "https://noclick.com/c/1", expires_at: "2026-10-02T10:00:00Z", operation_id: "op_c" },
};

// --- users -----------------------------------------------------------------

test("user update sends only given fields (null clears), suspend and delete", async () => {
  const { api } = setup();
  api.on("GET", `/v1/users/${USER_ID}`, json(userRow()));
  const patch = api.on("PATCH", `/v1/users/${USER_ID}`, json(userRow({ name: "Ana", email: null })));
  const suspend = api.on("POST", `/v1/users/${USER_ID}/suspend`, json(userRow({ status: "suspended" })));
  const del = api.on("DELETE", `/v1/users/${USER_ID}`, json(userRow({ status: "deleted" })));
  const user = await nc.User.get(USER_ID);
  await user.update({ name: "Ana", email: null });
  assert.deepEqual(patch.last.body, { name: "Ana", email: null });
  assert.equal(user.name, "Ana");
  assert.equal((await user.suspend()).status, "suspended");
  await user.delete();
  assert.equal(user.status, "deleted");
  assert.equal(suspend.count + del.count, 2);
  assert.ok(user.createdAt instanceof Date);
});

test("update({ id }) renames the user; later calls use the new id, and a bad id is never sent", async () => {
  const { api } = setup();
  const rename = api.on("PATCH", `/v1/users/${USER_ID}`, json(userRow({ id: "acct-7", name: "Ana" })));
  const suspend = api.on("POST", "/v1/users/acct-7/suspend", json(userRow({ id: "acct-7", status: "suspended" })));
  const connections = api.on("GET", "/v1/connections", json(listing()));
  const user = nc.User.fromId(USER_ID);
  await user.update({ id: "acct-7", name: "Ana" });
  assert.deepEqual(rename.last.body, { id: "acct-7", name: "Ana" });
  assert.equal(user.id, "acct-7");
  assert.equal(user.consoleUrl, null);
  await user.suspend();
  assert.equal(suspend.count, 1);
  await nc.asUser(user, () => nc.Connection.list());
  assert.equal(connections.last.headers.get("NoClick-User"), "acct-7");

  await assert.rejects(user.update({ id: "acct 8" }), nc.InvalidRequest);
  await assert.rejects(user.update({ id: "none" }), nc.InvalidRequest);
  assert.equal(rename.count, 1);

  const taken = api.on("PATCH", "/v1/users/acct-7", apiError(409, "conflict", "That id is taken.", { existing_id: "acct-8" }));
  await assert.rejects(user.update({ id: "acct-8" }), (err: nc.Conflict) => err instanceof nc.Conflict && err.existingId === "acct-8");
  assert.equal(taken.count, 1);
  assert.equal(user.id, "acct-7");
});

test("a user's console page is keyed by its encoded id", () => {
  const client = new nc.NoClick({ apiKey: "nk_live_test", baseUrl: nc.DEFAULT_BASE_URL });
  const user = nc.User.fromId("auth0|123", { client });
  assert.equal(user.consoleUrl, `${nc.CONSOLE_BASE_URL}/users/auth0%7C123`);
});

test("user phone verification", async () => {
  const { api } = setup();
  api.on("GET", `/v1/users/${USER_ID}`, json(userRow({ phone: "+14155550100" })));
  const verify = api.on("POST", `/v1/users/${USER_ID}/phone/verify`, json({ status: "pending", expires_at: "2026-09-25T11:10:00Z" }));
  const check = api.on("POST", `/v1/users/${USER_ID}/phone/check`, json(userRow({ phone_verified_at: "2026-09-25T11:00:00Z" })));
  const user = nc.User.fromId(USER_ID);
  const sent = await user.verifyPhone();
  // The code went to the user's own number, which the response doesn't repeat.
  assert.deepEqual([sent.phone, sent.status, sent.expiresAt?.toISOString()], ["+14155550100", "pending", "2026-09-25T11:10:00.000Z"]);
  assert.deepEqual(verify.last.body, {});
  // A new number goes with the request and is the one the code went to.
  assert.equal((await user.verifyPhone({ phone: "+14155550111" })).phone, "+14155550111");
  assert.deepEqual(verify.last.body, { phone: "+14155550111" });
  await user.checkPhone("123456");
  assert.deepEqual(check.last.body, { code: "123456" });
  assert.equal(user.raw.phone_verified_at, "2026-09-25T11:00:00Z");
  assert.equal(verify.last.headers.get("NoClick-User"), null);
});

// --- operations --------------------------------------------------------------

test("wait long-polls until terminal and returns the raw result for unknown kinds", async () => {
  const { api } = setup();
  const wait = api.on(
    "GET", "/v1/operations/op_1/wait",
    json(operation({ kind: "custom.kind", status: "running" })),
    json(operation({ kind: "custom.kind", status: "succeeded", result: { n: 1 } })),
  );
  const op = nc.Operation.fromId("op_1");
  assert.deepEqual(await op.wait(), { n: 1 });
  assert.equal(wait.count, 2);
  assert.equal(wait.last.query.get("timeout_s"), "50");
  assert.equal(op.done, true);
});

test("wait rides out a long-poll a stopping server cut off", async () => {
  const { api, sleeps } = setup();
  const wait = api.on(
    "GET", "/v1/operations/op_1/wait",
    new Response("Internal Server Error", { status: 500 }),
    new TypeError("fetch failed"),
    json(operation({ kind: "custom.kind", status: "succeeded", result: { n: 1 } })),
  );
  assert.deepEqual(await nc.Operation.fromId("op_1").wait(), { n: 1 });
  assert.equal(wait.count, 3);
  assert.equal(sleeps.length, 2);
});

test("wait with timeoutS raises OperationTimeout", async () => {
  const { api } = setup();
  api.on("GET", "/v1/operations/op_1/wait", async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
    return json(operation({ status: "running" }));
  });
  await assert.rejects(nc.Operation.fromId("op_1").wait({ timeoutS: 0.01 }), (err: nc.OperationTimeout) => {
    assert.ok(err instanceof nc.OperationTimeout);
    assert.equal(err.details.operation_status, "running");
    return true;
  });
});

test("a failed operation raises its typed error; canceled and expired raise theirs", async () => {
  const { api } = setup();
  api.on("GET", "/v1/operations/op_f/wait", json(operation({
    id: "op_f", status: "failed", error: { type: "policy_denied", message: "denied", next_step: "ask" },
  })));
  api.on("GET", "/v1/operations/op_c/wait", json(operation({ id: "op_c", status: "canceled" })));
  api.on("GET", "/v1/operations/op_e/wait", json(operation({ id: "op_e", status: "expired", error: { message: "too late" } })));
  api.on("GET", "/v1/operations/op_x/wait", json(operation({ id: "op_x", status: "failed", error: { message: "boom", reason: "interrupted" } })));
  await assert.rejects(nc.Operation.fromId("op_f").wait(), (err: nc.PolicyDenied) => err instanceof nc.PolicyDenied && err.details.operation_id === "op_f");
  await assert.rejects(nc.Operation.fromId("op_c").wait(), nc.OperationCanceled);
  await assert.rejects(nc.Operation.fromId("op_e").wait(), nc.Expired);
  await assert.rejects(nc.Operation.fromId("op_x").wait(), (err: nc.OperationFailed) => err instanceof nc.OperationFailed && err.details.reason === "interrupted");
});

test("cancel and events", async () => {
  const { api } = setup();
  const cancel = api.on("POST", "/v1/operations/op_1/cancel", json(operation({ status: "canceled" })));
  api.on(
    "GET", "/v1/operations/op_1",
    json(operation({ status: "queued" })),
    json(operation({ status: "running", updated_at: "2026-09-25T10:00:01Z" })),
    json(operation({ status: "running", updated_at: "2026-09-25T10:00:01Z" })),
    json(operation({ status: "succeeded", updated_at: "2026-09-25T10:00:02Z", result: {} })),
  );
  const op = nc.Operation.fromId("op_1");
  const statuses: string[] = [];
  for await (const event of op.events({ intervalMs: 0 })) statuses.push(event.status);
  assert.deepEqual(statuses, ["queued", "running", "succeeded"]);
  // A CLI turn's step is an event of its own, and rides on each event.
  api.on(
    "GET", "/v1/operations/op_2",
    json(operation({ id: "op_2", status: "running", step: "delivering" })),
    json(operation({ id: "op_2", status: "running", step: "working" })),
    json(operation({ id: "op_2", status: "succeeded", result: {} })),
  );
  const steps: [string, string | null][] = [];
  for await (const event of nc.Operation.fromId("op_2").events({ intervalMs: 0 })) steps.push([event.status, event.step]);
  assert.deepEqual(steps, [["running", "delivering"], ["running", "working"], ["succeeded", null]]);
  await op.cancel();
  assert.equal(op.status, "canceled");
  assert.ok(cancel.last.headers.get("Idempotency-Key"));
});

// --- credentials + integrations ---------------------------------------------

test("a connection says what holds it: agents, hosted MCP servers, apps and automations with their marks", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/gmail", json({ ...CONNECTION, used_by: [
    { kind: "agent", id: "ag_1", name: "support", binding: null, marks: null, user_id: null },
    { kind: "project", id: "prj_1", name: "booking", binding: "MAIL", marks: null, user_id: USER_ID },
    { kind: "workflow", id: "wf_1", name: "Inbox triage", binding: null, marks: ["automation-gmail", "agent"], user_id: null },
  ] }));
  const gmail = await nc.Connection.get("gmail");
  assert.deepEqual(gmail.usedBy, [
    { kind: "agent", id: "ag_1", name: "support", userId: null, binding: null, marks: [] },
    { kind: "project", id: "prj_1", name: "booking", userId: USER_ID, binding: "MAIL", marks: [] },
    { kind: "workflow", id: "wf_1", name: "Inbox triage", userId: null, binding: null, marks: ["automation-gmail", "agent"] },
  ]);
});

test("fromName createIfMissing creates a pending connection on first use, for the user", async () => {
  const { api } = setup();
  const missing = api.on("GET", "/v1/connections/gmail", apiError(404, "not_found", "No"));
  const create = api.on("POST", "/v1/connections", json(PENDING, { status: 201 }));
  const gmail = nc.Connection.fromName("gmail", { integration: { name: "gmail" }, createIfMissing: true, user: "user_42" });
  assert.equal(gmail.isHydrated, false);
  await gmail.hydrate();
  assert.equal(missing.count, 1);
  assert.deepEqual(create.last.body, { name: "gmail", integration: "gmail" });
  assert.equal(create.last.headers.get("NoClick-User"), "user_42");
  assert.deepEqual([gmail.status, gmail.connected, gmail.connectUrl], ["pending", false, "https://noclick.com/c/1"]);
  assert.throws(() => nc.Connection.fromName("gmail", { createIfMissing: true }), TypeError);
});

test("wait follows the open link's operation to the connected connection", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/gmail", json(PENDING));
  const reload = api.on("GET", "/v1/connections/con_1", json(CONNECTION));
  api.on("GET", "/v1/operations/op_c/wait", json(operation({
    id: "op_c", kind: "credential.connect", status: "succeeded", result: { connection: CONNECTION },
  })));
  const gmail = nc.Connection.fromName("gmail");
  assert.equal(await gmail.wait(), gmail);
  assert.deepEqual([gmail.connected, gmail.account], [true, "ana@gmail.com"]);
  await gmail.wait();
  assert.equal(reload.count, 1); // already connected
});

test("connectLink is an operation whose wait returns the Connection, for its user", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/con_1", json(CONNECTION));
  const create = api.on("POST", "/v1/connections/con_1/connect_links", json({
    object: "connect_link", url: "https://noclick.com/c/1", expires_at: "2026-09-26T10:00:00Z", connection: "gmail",
    operation: operation({ id: "op_c", kind: "credential.connect" }),
  }));
  const wait = api.on("GET", "/v1/operations/op_c/wait", json(operation({
    id: "op_c", kind: "credential.connect", status: "succeeded", result: { connection: CONNECTION },
  })));
  const gmail = await nc.Connection.get("con_1");
  const link = await gmail.connectLink({ redirectUrl: "https://acme.ai/done", sendTo: "ana@example.com" });
  assert.ok(link instanceof nc.ConnectLink && link instanceof nc.Operation);
  assert.equal(link.url, "https://noclick.com/c/1");
  assert.equal(String(link), "https://noclick.com/c/1");
  assert.equal(link.connection, "gmail");
  assert.ok(link.expiresAt instanceof Date);
  assert.deepEqual(create.last.body, { redirect_url: "https://acme.ai/done", send_to: { email: "ana@example.com" } });
  assert.equal(create.last.headers.get("NoClick-User"), USER_ID); // the connection's user
  const connection = await link.wait();
  assert.ok(connection instanceof nc.Connection);
  assert.equal(connection.id, "con_1");
  assert.equal(connection.verification?.reachable, true);
  assert.equal(wait.last.headers.get("NoClick-User"), USER_ID);
});

test("a fresh link becomes the connection's own and wait follows it past a lapsed one", async () => {
  const { api } = setup();
  const expired = json(operation({
    id: "op_c", kind: "credential.connect", status: "expired",
    error: { type: "expired", message: "The connect link expired before anyone connected an account." },
  }));
  api.on("GET", "/v1/connections/gmail", json(PENDING));
  api.on("POST", "/v1/connections/con_1/connect_links", json({
    object: "connect_link", id: "lnk_2", url: "https://noclick.com/c/2", expires_at: "2026-10-09T10:00:00Z",
    connection: "gmail", operation: operation({ id: "op_d", kind: "credential.connect" }),
  }));
  const lapsed = api.on("GET", "/v1/operations/op_c/wait", expired);
  const fresh = api.on("GET", "/v1/operations/op_d/wait", json(operation({
    id: "op_d", kind: "credential.connect", status: "succeeded", result: { connection: CONNECTION },
  })));
  const freshPending = { ...PENDING, connect_link: { ...PENDING.connect_link, id: "lnk_2", operation_id: "op_d" } };
  api.on("GET", "/v1/connections/con_1", json(CONNECTION), json(freshPending), json(CONNECTION));

  // connectLink() makes the new link the connection's own: wait() waits on it, no refresh().
  const gmail = nc.Connection.fromName("gmail", { user: USER_ID });
  assert.equal((await gmail.hydrate()).connectUrl, "https://noclick.com/c/1");
  const link = await gmail.connectLink();
  assert.equal(gmail.connectUrl, "https://noclick.com/c/2");
  assert.equal(link.url, "https://noclick.com/c/2");
  assert.equal(await gmail.wait(), gmail);
  assert.equal(gmail.connected, true);
  assert.deepEqual([fresh.count, lapsed.count], [1, 0]);

  // A link that lapses while a fresh one is open (made anywhere) hands the wait to it.
  const other = nc.Connection._of({ raw: PENDING, user: USER_ID });
  assert.equal((await other.wait()).connected, true);
  assert.deepEqual([fresh.count, lapsed.count], [2, 1]);

  // One that lapses with nothing open raises the documented OperationExpired.
  api.on("GET", "/v1/connections/con_2", json({ ...PENDING, id: "con_2", connect_link: null }));
  const stale = nc.Connection._of({ raw: { ...PENDING, id: "con_2" }, user: USER_ID });
  await assert.rejects(stale.wait(), nc.OperationExpired);
});

test("request defaults sendTo to the user", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/connections/slack", json({ ...PENDING, id: "con_s", name: "slack", integration: "slack" }));
  const route = api.on("POST", "/v1/connections/slack/connect_links", json({ url: "u", operation: "op_9", delivery: { delivered_via: ["email"] } }));
  const link = await nc.Connection.fromName("slack", { user: USER_ID }).request({ reason: "to post" });
  assert.deepEqual(route.last.body, { reason: "to post", send_to: { user: true } });
  assert.equal(read.count, 0); // acting needs no read
  assert.equal(route.last.headers.get("NoClick-User"), USER_ID);
  assert.equal(link.id, "op_9");
  assert.deepEqual(link.deliveredVia, ["email"]);
  assert.deepEqual(link.undelivered, []);
  // A connection of the account's own goes to the owner.
  await nc.Connection.fromName("slack", { user: null }).request({ sendTo: "owner" });
  assert.deepEqual(route.last.body, { send_to: { owner: true } });
  assert.equal(route.last.headers.get("NoClick-User"), null);
});

test("a link whose email failed says so, and a link nobody was sent has no delivery", async () => {
  const { api } = setup();
  api.on(
    "POST",
    "/v1/connections/gmail/connect_links",
    json({ url: "u", operation: "op_9", delivery: { delivered_via: [], undelivered: [{ channel: "email", reason: "The email could not be sent." }] } }),
    json({ url: "u", operation: "op_10" }),
  );
  const gmail = nc.Connection.fromName("gmail", { user: USER_ID });
  const failed = await gmail.request();
  assert.deepEqual(failed.deliveredVia, []);
  assert.deepEqual(failed.undelivered, [{ channel: "email", reason: "The email could not be sent." }]);
  const unsent = await gmail.connectLink();
  assert.deepEqual([unsent.deliveredVia, unsent.undelivered], [[], []]);
});

test("markTestAccount lets a preview write through it, and unmarks", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/connections/con_1/test_account", json({ ...CONNECTION, test_account: true }));
  const gmail = nc.Connection.fromId("con_1");
  assert.equal((await gmail.markTestAccount()).testAccount, true);
  assert.deepEqual(route.last.body, { test_account: true });
  await gmail.markTestAccount(false);
  assert.deepEqual(route.last.body, { test_account: false });
});

test("an account connected in the app: who shared it, its live health, the check's whole answer, a rename", async () => {
  const { api } = setup();
  const APP = {
    ...CONNECTION, id: "credential:cred_1", name: "Team inbox", origin: "app", access: "edit",
    shared: { with: "workspace", by: { name: "Priya Raman", email: "priya@example.test" } },
    health: { healthy: false, status: "failed", hint: "Scan the code again." },
  };
  api.on("GET", "/v1/connections/credential%3Acred_1", json(APP));
  api.on("POST", "/v1/connections/credential%3Acred_1/verify", json({
    ...APP, verification: {
      reachable: true, samples: [{ label: "site", value: null }], message: "ok", noun: "repositories", total: 9,
      account_label: "octo", proves: "account", error: null,
    },
  }));
  const rename = api.on("PATCH", "/v1/connections/credential%3Acred_1", json({ ...APP, name: "Sales inbox" }));

  const account = await nc.Connection.get("credential:cred_1");
  assert.deepEqual([account.shared?.with, account.shared?.byName, account.shared?.byEmail],
    ["workspace", "Priya Raman", "priya@example.test"]);
  assert.deepEqual([account.health?.healthy, account.health?.status, account.health?.hint], [false, "failed", "Scan the code again."]);
  const checked = await account.verify();
  assert.deepEqual(
    [checked?.noun, checked?.total, checked?.accountLabel, checked?.proves, checked?.error],
    ["repositories", 9, "octo", "account", null],
  );
  assert.equal((await account.rename("Sales inbox")).name, "Sales inbox");
  assert.deepEqual(rename.last.body, { name: "Sales inbox" });
  // A named connection, whose kind of account has no live check, reads neither.
  api.on("GET", "/v1/connections/con_1", json({ ...CONNECTION, shared: null, health: null }));
  const named = await nc.Connection.get("con_1");
  assert.deepEqual([named.shared, named.health], [null, null]);
  // What the app keeps that is no connection: no integration's, named by its variables.
  api.on("GET", "/v1/connections/credential%3Acred_env", json({
    ...APP, id: "credential:cred_env", integration: null, credential_type: "agent_env", in_app_only: true,
    account: "STRIPE_KEY, SENTRY_DSN",
  }));
  const variables = await nc.Connection.get("credential:cred_env");
  assert.deepEqual([variables.inAppOnly, variables.integration, variables.account, account.inAppOnly],
    [true, null, "STRIPE_KEY, SENTRY_DSN", false]);
  // Saved as the app's own forms save one, named by its variables.
  const made = api.on("POST", "/v1/connections", json({
    ...APP, id: "credential:cred_env2", integration: null, credential_type: "agent_env", in_app_only: true,
    variables: ["STRIPE_KEY"], server_url: null,
  }));
  const saved = await nc.Connection.create("Deploy variables", { origin: "app", credentialType: "agent_env", data: { env: { STRIPE_KEY: "sk" } } });
  assert.deepEqual(made.last.body, { name: "Deploy variables", origin: "app", credential_type: "agent_env", data: { env: { STRIPE_KEY: "sk" } } });
  assert.deepEqual([saved.variables, saved.serverUrl, variables.variables], [["STRIPE_KEY"], null, null]);
});

test("create with data, list, get, verify, token, import, delete", async () => {
  const { api } = setup();
  const createRoute = api.on("POST", "/v1/connections", json(CONNECTION, { status: 201 }));
  const list = api.on("GET", "/v1/connections", json(listing([CONNECTION])));
  api.on("GET", "/v1/connections/con_1", json(CONNECTION));
  api.on("POST", "/v1/connections/con_1/verify", json({ ...CONNECTION, verification: { reachable: false, samples: [], message: "revoked" } }));
  const token = api.on("POST", "/v1/connections/con_1/token", json({ access_token: "ya29", token_type: "Bearer", expires_at: "2026-09-25T11:00:00Z" }));
  const imported = api.on("POST", "/v1/connections/con_1/import", json({ ...CONNECTION, account: "bo@gmail.com" }));
  const remove = api.on("DELETE", "/v1/connections/con_1", json({ object: "connection", id: "con_1", deleted: true }));

  const created = await nc.Connection.create("stripe", { credentialType: "stripe_api_key", data: { api_key: "sk_live" } });
  assert.deepEqual(createRoute.last.body, { name: "stripe", credential_type: "stripe_api_key", data: { api_key: "sk_live" } });
  assert.equal(created.credentialType, "gmail_oauth");

  const [listed] = await nc.Connection.list({ integration: "gmail" });
  assert.equal(list.last.query.get("integration"), "gmail");
  assert.equal(list.last.query.get("include_in_app_only"), null);
  await nc.Connection.list({ includeInAppOnly: true });
  assert.equal(list.last.query.get("include_in_app_only"), "true");
  // an owned connection acts for its user even outside asUser
  const verification = await listed.verify();
  assert.equal(verification?.reachable, false);
  assert.equal(listed.verification?.message, "revoked");
  const minted = await listed.token();
  assert.equal(minted.accessToken, "ya29");
  assert.ok(minted.expiresAt instanceof Date);
  assert.equal(token.last.headers.get("NoClick-User"), USER_ID);
  assert.equal((await listed.import({ refresh_token: "r" })).account, "bo@gmail.com");
  assert.deepEqual(imported.last.body, { data: { refresh_token: "r" } });

  const got = await nc.Connection.get("con_1");
  await got.delete();
  assert.equal(remove.count, 1);
});

test("run and lookup act in the connection's account; a pending one throws NeedsConnection", async () => {
  const { api } = setup();
  const run = api.on(
    "POST", "/v1/connections/slack/operations/send_message/run",
    json({ object: "operation_result", result: { ts: "1.2" } }),
    apiError(424, "needs_connection", "No account yet.", { connection: "slack", integration: "slack", connect_url: "https://noclick.com/c/2" }),
  );
  const lookup = api.on("POST", "/v1/connections/slack/lookup", json({ options: [{ value: "C1", label: "#general" }], next_page_token: "p2" }));
  const slack = nc.Connection.fromName("slack", { user: "user_1" });
  assert.deepEqual(await slack.run("send_message", { text: "hi" }), { ts: "1.2" });
  assert.deepEqual(run.last.body, { arguments: { text: "hi" } });
  assert.equal(run.last.headers.get("NoClick-User"), "user_1");
  const options = await slack.lookup("channel", { search: "gen" });
  assert.deepEqual(options.options.map((o) => [o.value, o.label]), [["C1", "#general"]]);
  assert.equal(options.nextPageToken, "p2");
  assert.deepEqual(lookup.last.body, { field: "channel", search: "gen" });
  await assert.rejects(slack.run("send_message", {}), (err: nc.NeedsConnection) => {
    assert.ok(err instanceof nc.NeedsConnection);
    assert.deepEqual([err.connection, err.integration, err.connectUrl], ["slack", "slack", "https://noclick.com/c/2"]);
    return true;
  });
});

const SLACK_OPERATIONS = [
  { name: "send_message", description: "Post a message", parameters: { type: "object" }, read_only: false, scopes: ["chat:write"], needs_account: true },
  { name: "list_channels", description: "Channels", parameters: {}, read_only: true, scopes: [], needs_account: true },
];

test("Connection.integrations reads the catalog, filtered by query, for no user", async () => {
  const { api } = setup();
  const catalog = api.on("GET", "/v1/integrations", json(listing([
    { object: "integration", name: "hubspot", label: "HubSpot", connect_with: ["oauth", "key"], credential_types: ["hubspot_oauth", "hubspot_api_key"], operation_count: 40, account_free_operation_count: 0, events: ["contact_created"] },
    { object: "integration", name: "exa", label: "Exa", connect_with: ["key"], credential_types: ["exa_api_key"], operation_count: 3, account_free_operation_count: 3, events: ["monitor_results"] },
  ])));
  const found = await nc.asUser(USER_ID, () => nc.Connection.integrations("crm"));
  assert.equal(catalog.last.query.get("q"), "crm");
  assert.equal(catalog.last.headers.get("NoClick-User"), null); // the catalog is the same for every user
  const [hubspot, exa] = found;
  assert.deepEqual(
    [hubspot.name, hubspot.label, hubspot.connectWith, hubspot.operationCount, hubspot.credentialTypes],
    ["hubspot", "HubSpot", ["oauth", "key"], 40, ["hubspot_oauth", "hubspot_api_key"]],
  );
  assert.equal(hubspot.raw.object, "integration");
  assert.deepEqual(exa.connectWith, ["key"]);
  assert.deepEqual([hubspot.accountFreeOperationCount, exa.accountFreeOperationCount], [0, 3]);
  // The app events an OnEvent takes from each.
  assert.deepEqual([hubspot.events, exa.events], [["contact_created"], ["monitor_results"]]);
  await nc.Connection.integrations();
  assert.equal(catalog.last.query.has("q"), false);
});

test("Connection.integrations filters by kind and reads the model providers", async () => {
  const { api } = setup();
  const catalog = api.on("GET", "/v1/integrations", json(listing([
    {
      object: "integration", name: "anthropic", label: "Claude", kind: "model", subscription: true, connect_with: ["key"],
      credential_types: ["agent_anthropic", "agent_claude_code_oauth"], operation_count: 0, account_free_operation_count: 0,
    },
    { object: "integration", name: "exa", label: "Exa", kind: "app", subscription: false, connect_with: ["key"], credential_types: [], operation_count: 3, account_free_operation_count: 3 },
  ])));
  const [anthropic, exa] = await nc.Connection.integrations(undefined, { kind: "model" });
  assert.equal(catalog.last.query.get("kind"), "model");
  assert.equal(catalog.last.query.has("q"), false);
  assert.deepEqual([anthropic.kind, anthropic.subscription, anthropic.operationCount], ["model", true, 0]);
  assert.deepEqual(anthropic.events, []); // a row that names no events (a model provider has none)
  assert.deepEqual([exa.kind, exa.subscription], ["app", false]);
  await nc.Connection.integrations("gm", { kind: "app" });
  assert.deepEqual([catalog.last.query.get("q"), catalog.last.query.get("kind")], ["gm", "app"]);
});

test("a model connection holds a key it never hands out", async () => {
  const { api } = setup();
  const claude = { ...CONNECTION, id: "con_cl", name: "claude", integration: "anthropic", credential_type: "agent_anthropic", user_id: null };
  const create = api.on("POST", "/v1/connections", json(claude, { status: 201 }));
  api.on("POST", "/v1/connections/con_cl/token", apiError(403, "permission_denied", "NoClick never hands out a model key."));
  const connection = await nc.Connection.create("claude", { integration: "anthropic", data: { api_key: "sk-ant-x" } });
  assert.deepEqual(create.last.body, { name: "claude", integration: "anthropic", data: { api_key: "sk-ant-x" } });
  await assert.rejects(connection.token(), nc.PermissionDenied);
});

test("a catalog row without its account-free count is malformed, never zero", async () => {
  const { api } = setup();
  api.on("GET", "/v1/integrations", json(listing([
    { object: "integration", name: "exa", label: "Exa", connect_with: ["key"], credential_types: [], operation_count: 3 },
  ])));
  await assert.rejects(nc.Connection.integrations(), /account_free_operation_count/);
});

// --- run: one operation by its ref -------------------------------------------------

function runResult(ref: string, result: unknown, connection: string | null = null) {
  const [integration, operation] = ref.split(".");
  return { object: "operation_result", ref, integration, operation, connection, result };
}

test("run posts the ref and arguments for the account and resolves to the result", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/run", json(runResult("exa.search", { results: [{ url: "https://a.test" }] })));
  assert.deepEqual(await nc.run("exa.search", { query: "q" }), { results: [{ url: "https://a.test" }] });
  assert.deepEqual(route.last.body, { ref: "exa.search", arguments: { query: "q" } });
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.ok(route.last.headers.get("Idempotency-Key"));
  await nc.run("exa.search");
  assert.deepEqual(route.last.body, { ref: "exa.search", arguments: {} });
});

test("run resolves a null result, and refuses a response without one", async () => {
  const { api } = setup();
  api.on("POST", "/v1/run", json(runResult("slack.delete_message", null, "con_s")), json({ object: "operation_result" }));
  assert.equal(await nc.run("slack.delete_message", { ts: "1.2" }), null);
  await assert.rejects(nc.run("slack.delete_message", { ts: "1.2" }), /missing `result`/);
});

test("run acts for the ambient user, and { user } wins", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/run", json(runResult("gmail.send_email_message", { id: "msg_1" }, "con_1")));
  await nc.asUser(USER_ID, async () => {
    assert.deepEqual(await nc.run("gmail.send_email_message", { to: ["a@b.c"] }), { id: "msg_1" });
    assert.equal(route.last.headers.get("NoClick-User"), USER_ID);
    await nc.run("gmail.send_email_message", {}, { user: null });
    assert.equal(route.last.headers.get("NoClick-User"), null);
  });
  await nc.run("gmail.send_email_message", {}, { user: "user_7" });
  assert.equal(route.last.headers.get("NoClick-User"), "user_7");
});

test("run uses the given client", async () => {
  const { api } = setup();
  const other = new nc.NoClick({ apiKey: "nk_live_other", baseUrl: BASE, fetch: api.fetch });
  const route = api.on("POST", "/v1/run", json(runResult("exa.search", [])));
  assert.deepEqual(await nc.run("exa.search", { query: "q" }, { client: other }), []);
  assert.equal(route.last.headers.get("Authorization"), "Bearer nk_live_other");
});

for (const [status, type, cls] of [
  [424, "needs_connection", nc.NeedsConnection],
  [403, "policy_denied", nc.PolicyDenied],
  [400, "invalid_request", nc.InvalidRequest],
  [404, "not_found", nc.NotFound],
] as const) {
  test(`run throws ${cls.name} when the server answers ${type}`, async () => {
    const { api } = setup();
    api.on("POST", "/v1/run", apiError(status, type, "Refused.", {
      next_step: "Create a connection named gmail.", connection: "gmail", integration: "gmail", connect_url: "https://noclick.com/c/xyz",
    }));
    const err = await nc.run("gmail.send_email_message", { to: ["a@b.c"] }, { user: USER_ID }).catch((e: unknown) => e);
    assert.ok(err instanceof cls);
    assert.deepEqual([err.message, err.status, err.nextStep], ["Refused.", status, "Create a connection named gmail."]);
    if (err instanceof nc.NeedsConnection) assert.deepEqual([err.connection, err.connectUrl], ["gmail", "https://noclick.com/c/xyz"]);
  });
}

test("run retries a held call with its approvalId", async () => {
  const { api } = setup();
  const held = apiError(402, "approval_required", "Needs approval.", {
    approval_id: "ap_1", approve_url: "https://h/1",
    operation: { object: "operation", id: "op_a", kind: "human.approve", status: "awaiting_human" },
  });
  const route = api.on("POST", "/v1/run", held, json(runResult("gmail.send_email_message", { id: "msg_1" }, "con_1")));
  const wait = api.on("GET", "/v1/operations/op_a/wait", json(operation({ id: "op_a", kind: "human.approve", status: "succeeded", result: { approved: true } })));
  const args = { to: ["a@b.c"] };
  const err = await nc.run("gmail.send_email_message", args, { user: USER_ID }).catch((e: unknown) => e);
  assert.ok(err instanceof nc.ApprovalRequired);
  assert.equal(await err.operation?.wait(), true);
  assert.equal(wait.last.headers.get("NoClick-User"), USER_ID); // polled for the user the call acted for
  const retried = await nc.run("gmail.send_email_message", args, { user: USER_ID, approvalId: err.approvalId });
  assert.deepEqual(retried, { id: "msg_1" });
  assert.deepEqual(route.calls[0].body, { ref: "gmail.send_email_message", arguments: args });
  assert.deepEqual(route.last.body, { ref: "gmail.send_email_message", arguments: args, approval_id: "ap_1" });
});

test("run refuses a ref that names no single operation, before sending", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/run", json(runResult("exa.search", [])));
  for (const ref of ["exa", "search", ".search", "exa.", ""]) {
    const err = await nc.run(ref, { query: "q" }).catch((e: unknown) => e);
    assert.ok(err instanceof nc.InvalidRequest, ref);
    assert.equal(err.details.field, "ref");
    assert.match(err.nextStep ?? "", /exa\.search/);
  }
  await assert.rejects(nc.run(nc.Connection.fromName("exa") as unknown as string), TypeError);
  assert.equal(route.count, 0);
});

test("operations and operation read the catalog of a connection named with its integration, never loading it", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/connections/work", json(CONNECTION));
  const create = api.on("POST", "/v1/connections", json(CONNECTION, { status: 201 }));
  const list = api.on("GET", "/v1/integrations/slack/operations", json(listing(SLACK_OPERATIONS)));
  const one = api.on("GET", "/v1/integrations/slack/operations/send_message", json(SLACK_OPERATIONS[0]));
  api.on("GET", "/v1/integrations/slack/operations/fly", apiError(404, "not_found", "Slack has no operation 'fly'."));
  const work = nc.Connection.fromName("work", { integration: "slack", createIfMissing: true, user: USER_ID });

  const operations = await work.operations({ search: "message" });
  assert.equal(list.last.query.get("q"), "message");
  assert.equal(list.last.headers.get("NoClick-User"), null);
  assert.deepEqual(operations.map((op) => [op.name, op.readOnly, op.needsAccount]), [["send_message", false, true], ["list_channels", true, true]]);
  const send = await work.operation("send_message");
  assert.equal(one.count, 1);
  assert.deepEqual([send.description, send.parameters, send.scopes, send.raw.name], ["Post a message", { type: "object" }, ["chat:write"], "send_message"]);
  await assert.rejects(work.operation("fly"), nc.NotFound);
  await work.operations();
  assert.equal(list.last.query.has("q"), false);
  assert.deepEqual([read.count, create.count, work.isHydrated], [0, 0, false]);
  // The hint only picks the catalog: an existing connection of that name may be another integration.
  assert.throws(() => work.integration, /not loaded yet/);
});

test("operations load a connection named without its integration to learn it, once", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/connections/crm", json({ ...CONNECTION, name: "crm", integration: "exa", credential_type: null }));
  const list = api.on("GET", "/v1/integrations/exa/operations", json(listing([
    { name: "search", description: "Search the web", parameters: {}, read_only: true, scopes: [], needs_account: false },
    { name: "answer", description: "Answer", parameters: {}, read_only: true, scopes: [] },
  ])));
  const crm = nc.Connection.fromName("crm");
  const [search, answer] = await crm.operations();
  assert.deepEqual([search.needsAccount, answer.needsAccount], [false, true]); // true unless the catalog says otherwise
  await crm.operations();
  assert.deepEqual([read.count, list.count], [1, 2]);
});

test("a pending connection runs a keyless operation through its own route", async () => {
  const { api } = setup();
  const web = { ...CONNECTION, id: "con_w", name: "web", integration: "exa", status: "pending", credential_type: null, account: null, verification: null };
  api.on("GET", "/v1/connections/web", apiError(404, "not_found", "No"));
  const create = api.on("POST", "/v1/connections", json(web, { status: 201 }));
  const run = api.on("POST", "/v1/connections/con_w/operations/search/run", json({ object: "operation_result", result: { results: [] } }));
  const conn = await nc.Connection.fromName("web", { integration: "exa", createIfMissing: true, user: USER_ID }).hydrate();
  assert.deepEqual(create.last.body, { name: "web", integration: "exa" });
  assert.deepEqual([conn.status, conn.connected, conn.account], ["pending", false, null]);
  assert.deepEqual(await conn.run("search", { query: "q" }), { results: [] });
  assert.deepEqual(run.last.body, { arguments: { query: "q" } });
  assert.equal(run.last.headers.get("NoClick-User"), USER_ID);
});

test("ApprovalRequired carries a waitable approval on the raising client; retry with approvalId", async () => {
  const { api } = setup();
  const other = new nc.NoClick({ apiKey: "nk_live_other", baseUrl: "https://api.test", fetch: api.fetch });
  api.on("POST", "/v1/connections/gmail/operations/delete_email/run", apiError(402, "approval_required", "Needs approval.", {
    approval_id: "ap_1", request_id: "hr_1", approve_url: "https://h/1",
    operation: { object: "operation", id: "op_a", kind: "human.approve", status: "awaiting_human" },
  }));
  const wait = api.on("GET", "/v1/operations/op_a/wait", json(operation({ id: "op_a", kind: "human.approve", status: "succeeded", result: { approved: true } })));
  const gmail = nc.Connection.fromName("gmail", { client: other, user: "user_42" });
  const err = await gmail.run("delete_email", { id: "m1" }).catch((e: unknown) => e);
  assert.ok(err instanceof nc.ApprovalRequired);
  assert.equal(err.operationId, "op_a");
  assert.ok(err.operation instanceof nc.HumanRequest);
  assert.equal(err.operation, err.operation); // cached
  assert.equal(await err.operation?.wait(), true);
  assert.equal(wait.last.headers.get("Authorization"), "Bearer nk_live_other");
  assert.equal(wait.last.headers.get("NoClick-User"), "user_42");
  // Approved from your own code, as the user the call acted for: the request it waits on is answered.
  const answered = api.on("POST", "/v1/humans/requests/hr_1/answer", json({ object: "human_request", id: "hr_1", status: "answered" }));
  await err.operation?.approve();
  assert.deepEqual(answered.last.body, { approved: true });
  assert.equal(answered.last.headers.get("NoClick-User"), "user_42");

  const retry = api.on("POST", "/v1/connections/gmail/operations/delete_email/run", json({ result: { deleted: true } }));
  assert.deepEqual(await gmail.run("delete_email", { id: "m1" }, { approvalId: err.approvalId }), { deleted: true });
  assert.deepEqual(retry.last.body, { arguments: { id: "m1" }, approval_id: "ap_1" });
});

// --- humans ------------------------------------------------------------------

test("user.human.ask waits to an Answer and keeps the request view", async () => {
  const { api } = setup();
  api.on("GET", `/v1/users/${USER_ID}`, json(userRow()));
  const create = api.on("POST", "/v1/humans/requests", json({
    ...operation({ id: "op_h", kind: "human.ask" }),
    request: { id: "hr_1", url: "https://noclick.com/h/hr_1", delivered_via: ["web"], undelivered: [{ channel: "email", reason: "no email on file" }] },
  }));
  api.on("GET", "/v1/operations/op_h/wait", json(operation({
    id: "op_h", kind: "human.ask", status: "succeeded", result: { choice: "Tue", text: "after 3pm" },
  })));
  const user = await nc.User.get(USER_ID);
  const req = await user.human.ask("Which day?", { options: ["Mon", "Tue"], via: "email", expiresInS: 3600 });
  assert.ok(req instanceof nc.HumanRequest && req instanceof nc.Operation);
  assert.equal(req.status, "awaiting_human");
  assert.equal(req.url, "https://noclick.com/h/hr_1");
  assert.deepEqual(req.deliveredVia, ["web"]);
  assert.equal(req.undelivered[0].channel, "email");
  assert.deepEqual(create.last.body, {
    kind: "ask", to: { user: true }, message: "Which day?", options: ["Mon", "Tue"], via: ["email"], expires_in_s: 3600,
  });
  assert.equal(create.last.headers.get("NoClick-User"), USER_ID);
  const answer = await req.wait();
  assert.deepEqual([answer.choice, answer.text], ["Tue", "after 3pm"]);
  assert.equal(req.url, "https://noclick.com/h/hr_1");
});

test("approve resolves to a boolean; notify succeeds at once; email targets carry no user", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/humans/requests", json(operation({ id: "op_a", kind: "human.approve" })));
  api.on("GET", "/v1/operations/op_a/wait", json(operation({ id: "op_a", kind: "human.approve", status: "succeeded", result: { approved: false } })));
  const req = await nc.asUser("user_42", () => new nc.Human().approve("Send it?", { details: { recipients: 12 } }));
  assert.equal(await req.wait(), false);
  assert.deepEqual(create.last.body, { kind: "approve", to: { user: true }, message: "Send it?", details: { recipients: 12 }, via: "auto" });
  assert.equal(create.last.headers.get("NoClick-User"), "user_42");

  const notify = api.on("POST", "/v1/humans/requests", json(operation({ id: "op_n", kind: "human.notify", status: "succeeded", result: {} })));
  const sent = await new nc.Human({ email: "ops@acme.ai" }).notify("Deploy finished");
  assert.equal(sent.done, true);
  assert.equal(await sent.wait(), null);
  assert.deepEqual((notify.last.body as { to: unknown }).to, { email: "ops@acme.ai" });
  assert.equal(notify.last.headers.get("NoClick-User"), null);
});

test("a Human meaning the user lets the server decide", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/humans/requests", apiError(400, "invalid_request", "to.user needs a user to act for.", {
    next_step: "Send the NoClick-User header naming the user, or pass to.email.",
  }));
  await assert.rejects(new nc.Human().ask("hello?"), (err: nc.InvalidRequest) => {
    assert.ok(err instanceof nc.InvalidRequest);
    assert.match(err.nextStep ?? "", /NoClick-User/);
    return true;
  });
  assert.deepEqual((route.last.body as { to: unknown }).to, { user: true });
});

for (const [label, pinned] of [
  ["a user session", (fetch: typeof globalThis.fetch) => nc.NoClick.forSession("nk_sess_x", { baseUrl: BASE, fetch })],
  ["a key pinned with user_id", (fetch: typeof globalThis.fetch) => new nc.NoClick({ apiKey: "nk_live_pinned", baseUrl: BASE, fetch })],
] as const) {
  test(`a Human on ${label} reaches its user`, async () => {
    const { api } = setup();
    const route = api.on("POST", "/v1/humans/requests", json(operation({ id: "op_h", kind: "human.ask" })));
    const lookedUp = api.on("GET", "/v1/connections/gmail", json({ ...PENDING, user_id: null }));
    const links = api.on("POST", "/v1/connections/gmail/connect_links", json({ url: "https://noclick.com/c/9", operation: operation({ id: "op_c", kind: "credential.connect" }) }));
    const human = new nc.Human({ client: pinned(api.fetch) });
    await human.ask("Which plan?", { options: ["A", "B"] });
    assert.deepEqual((route.last.body as { to: unknown }).to, { user: true });
    assert.equal(route.last.headers.get("NoClick-User"), null);
    await human.connect("gmail");
    assert.deepEqual((links.last.body as { send_to: unknown }).send_to, { user: true });
    assert.equal(links.last.headers.get("NoClick-User"), null);
    assert.equal(lookedUp.count, 0);
  });
}

test("connect links refuse a phone-only recipient", async () => {
  const { api } = setup();
  const lookedUp = api.on("GET", "/v1/connections/gmail", json({ ...PENDING, user_id: null }));
  const route = api.on("POST", "/v1/connections/gmail/connect_links", json({ url: "https://noclick.com/c/9", operation: operation({ id: "op_c", kind: "credential.connect" }) }));
  const gmail = nc.Connection.fromName("gmail");
  for (const call of [
    () => gmail.connectLink({ sendTo: "+14155550100" }),
    () => gmail.request({ sendTo: { phone: "+14155550100" } }),
    () => new nc.Human({ phone: "+14155550100" }).connect("gmail"),
  ]) {
    await assert.rejects(call(), (err: nc.InvalidRequest) => {
      assert.ok(err instanceof nc.InvalidRequest);
      assert.match(err.message, /email only/);
      assert.match(err.nextStep ?? "", /url yourself/);
      return true;
    });
  }
  assert.equal(route.count, 0);
  assert.equal(lookedUp.count, 0); // refused before anything is sent
  // A person with an email as well gets the link by email.
  await new nc.Human({ email: "ana@example.com", phone: "+14155550100" }).connect("gmail");
  assert.deepEqual((route.last.body as { send_to: unknown }).send_to, { email: "ana@example.com", phone: "+14155550100" });
});

test("human.connect returns a ConnectLink sent to that person", async () => {
  const { api } = setup();
  const lookedUp = api.on("GET", "/v1/connections/gmail", json({ ...PENDING, user_id: null }));
  const route = api.on("POST", "/v1/connections/gmail/connect_links", json({ url: "https://noclick.com/c/9", operation: operation({ id: "op_c", kind: "credential.connect" }) }));
  const link = await new nc.Human({ user: "user_42" }).connect("gmail", { reason: "to send your summary" });
  assert.ok(link instanceof nc.ConnectLink);
  assert.equal(link.url, "https://noclick.com/c/9");
  assert.deepEqual((route.last.body as { send_to: unknown }).send_to, { user: true });
  assert.equal(route.last.headers.get("NoClick-User"), "user_42");
  assert.equal(lookedUp.count, 0);
});

// --- agents ------------------------------------------------------------------

const AGENT = {
  object: "agent", id: "agt_1", name: "sunrise-host", model: "openrouter/x", harness: "sdk",
  instructions: "You take cake orders.", tools: ["gmail"], user_id: null, workflow_id: "wf_1",
  created_at: "2026-09-25T10:00:00Z",
};

test("fromName createIfMissing creates on first use, then messages and waits", async () => {
  const { api } = setup();
  const lookup = api.on("GET", "/v1/agents", json(listing()));
  const create = api.on("POST", "/v1/agents", json(AGENT));
  const send = api.on("POST", "/v1/agents/agt_1/messages", json(operation({ id: "op_m", kind: "agent.message", status: "queued" })));
  api.on("GET", "/v1/operations/op_m/wait", json(operation({
    id: "op_m", kind: "agent.message", status: "succeeded",
    result: { text: "Lemon cake today.", conversation: "conv_1", tool_calls: [{ tool: "search" }] },
  })));
  const agent = nc.Agent.fromName("sunrise-host", {
    createIfMissing: true, instructions: "You take cake orders.", tools: new nc.Toolkit(["gmail"]), ttlS: 600, budgetUsdPerMonth: 5,
  });
  const reply = await nc.asUser("user_42", () => agent.message("What's on today?"));
  assert.equal(reply.text, "Lemon cake today.");
  assert.equal(reply.conversation, "conv_1");
  assert.equal(reply.operationId, "op_m");
  assert.deepEqual(reply.toolCalls, [{ tool: "search" }]);
  assert.equal(lookup.last.query.get("name"), "sunrise-host");
  assert.deepEqual(create.last.body, {
    name: "sunrise-host", instructions: "You take cake orders.", tools: ["gmail"], ttl_s: 600, budget_usd_per_month: 5,
  });
  assert.deepEqual(send.last.body, { text: "What's on today?" });
  // an account-level agent talks as the user current at the call
  assert.equal(send.last.headers.get("NoClick-User"), "user_42");
});

test("a user's own agent always talks as that user; history, update, delete", async () => {
  const { api } = setup();
  const owned = { ...AGENT, user_id: USER_ID };
  api.on("GET", "/v1/agents/agt_1", json(owned));
  const send = api.on("POST", "/v1/agents/agt_1/messages", json(operation({ id: "op_m", kind: "agent.message" })));
  const history = api.on("GET", "/v1/agents/agt_1/conversations/conv%2F1", json({
    messages: [{ role: "user", text: "hi", created_at: "2026-09-25T10:00:00Z" }, { role: "assistant", text: "hello" }],
  }));
  const patch = api.on("PATCH", "/v1/agents/agt_1", json({ ...owned, instructions: "Be brief." }));
  const del = api.on("DELETE", "/v1/agents/agt_1", json({ id: "agt_1", deleted: true }));

  const agent = await nc.Agent.get("agt_1");
  const op = await nc.asUser("someone_else", () => agent.send("hi", { conversation: "conv/1" }));
  assert.ok(op instanceof nc.Operation);
  assert.equal(send.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual(send.last.body, { text: "hi", conversation: "conv/1" });

  const messages = await agent.history("conv/1");
  assert.deepEqual(messages.map((m) => [m.role, m.text]), [["user", "hi"], ["assistant", "hello"]]);
  assert.ok(messages[0].createdAt instanceof Date);
  assert.equal(history.last.headers.get("NoClick-User"), USER_ID);

  await agent.update({ instructions: "Be brief.", tools: [] });
  assert.deepEqual(patch.last.body, { instructions: "Be brief.", tools: [] });
  assert.equal(agent.instructions, "Be brief.");
  await agent.delete();
  assert.equal(del.count, 1);
});

test("Agent.create with a parent agent sends parent_id; a missing name is NotFound", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/agt_1", json(AGENT));
  const create = api.on("POST", "/v1/agents", json({ ...AGENT, id: "agt_2", name: "helper" }));
  const child = await nc.Agent.create("helper", { instructions: "Help.", parent: nc.Agent.fromId("agt_1"), ttlS: 60 });
  assert.equal(child.id, "agt_2");
  assert.deepEqual(create.last.body, { name: "helper", instructions: "Help.", ttl_s: 60, parent_id: "agt_1" });

  api.on("GET", "/v1/agents", json(listing()));
  await assert.rejects(nc.Agent.fromName("nobody").hydrate(), nc.NotFound);
  assert.throws(() => nc.Agent.fromName("x", { createIfMissing: true }), TypeError);
});

test("fromName converges an existing agent and inside asUser never matches a shared one", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([AGENT])));
  const patch = api.on("PATCH", "/v1/agents/agt_1", json({ ...AGENT, instructions: "New.", can_request: ["gmail"] }));
  const create = api.on("POST", "/v1/agents", json({ ...AGENT, id: "agt_2", user_id: USER_ID }));
  const agent = await nc.Agent.fromName("sunrise-host", {
    createIfMissing: true, instructions: "New.", tools: ["gmail"], canRequest: [{ name: "gmail" }],
  }).hydrate();
  assert.equal(agent.id, "agt_1");
  assert.deepEqual(patch.last.body, { instructions: "New.", can_request: ["gmail"] }); // only what differs
  assert.deepEqual(agent.canRequest, ["gmail"]);
  await nc.Agent.fromName("sunrise-host", { createIfMissing: true, instructions: AGENT.instructions }).hydrate();
  assert.equal(patch.count, 1);

  const own = await nc.Agent.fromName("sunrise-host", { createIfMissing: true, instructions: "x", user: "user_42" }).hydrate();
  assert.equal(own.id, "agt_2");
  assert.equal(create.count, 1);
  // Without a definition too: a user's name finds only their own agent, never the account's.
  await assert.rejects(nc.Agent.fromName("sunrise-host", { user: "user_42" }).hydrate(), nc.NotFound);
  api.on("GET", "/v1/agents", json(listing([AGENT, { ...AGENT, id: "agt_2", user_id: USER_ID }])));
  assert.equal((await nc.Agent.fromName("sunrise-host", { user: "user_42" }).hydrate()).id, "agt_2");
  assert.equal((await nc.Agent.fromName("sunrise-host").hydrate()).id, "agt_1");
});

test("an explicit null in fromName clears the field, and a field left out is never touched", async () => {
  const { api } = setup();
  const coder = { ...AGENT, harness: "claude_code", model: "sonnet", model_connection: "claude", budget_usd_per_month: 20 };
  api.on("GET", "/v1/agents", json(listing([coder])));
  const patch = api.on("PATCH", "/v1/agents/agt_1", (call: Call) => json({ ...coder, ...(call.body as object) }));
  const agent = await nc.Agent.fromName("sunrise-host", {
    createIfMissing: true, instructions: AGENT.instructions, tools: AGENT.tools, harness: "sdk", model: "openrouter/x",
    modelConnection: null, budgetUsdPerMonth: null,
  }).hydrate();
  assert.deepEqual(patch.last.body, { harness: "sdk", model: "openrouter/x", model_connection: null, budget_usd_per_month: null });
  assert.equal(agent.modelConnection, null);
  await nc.Agent.fromName("sunrise-host", {
    createIfMissing: true, instructions: AGENT.instructions, tools: AGENT.tools, harness: "claude_code", model: "sonnet",
  }).hydrate();
  assert.equal(patch.count, 1);
});

// --- harnesses ---------------------------------------------------------------

const CLAUDE = {
  ...PENDING, id: "con_cl", name: "claude", integration: "anthropic", credential_type: "agent_anthropic", user_id: null,
};
const CODER = { ...AGENT, id: "agt_cc", name: "coder", harness: "claude_code", model: "sonnet", model_connection: "claude" };

const CODEX_HARNESS = {
  object: "harness", name: "codex", label: "Codex", version: "0.156.1", default_model: "gpt-5.6-luna", custom_models: true,
  model_connection: "required", integrations: ["openai"], streaming: "final", shell: "built_in",
  notes: ["On a ChatGPT API key, codex shows tools only to codex-family models such as gpt-5-codex."],
};

test("Agent.harnesses reads the catalog for no user", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/harnesses", json(listing([
    CODEX_HARNESS,
    {
      object: "harness", name: "sdk", label: "NoClick", version: null, default_model: "openrouter/~openai/gpt-luna-latest",
      custom_models: true, model_connection: "optional", integrations: ["openrouter", "anthropic", "openai"], streaming: "tokens", shell: "code_capability",
      notes: ["Streams its reply; code, search and fetch are tools you list."],
    },
  ])));
  const [codex, sdk] = await nc.asUser(USER_ID, () => nc.Agent.harnesses());
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.deepEqual(
    [codex.name, codex.label, codex.version, codex.defaultModel, codex.customModels, codex.modelConnection, codex.integrations, codex.streaming, codex.shell],
    ["codex", "Codex", "0.156.1", "gpt-5.6-luna", true, "required", ["openai"], "final", "built_in"],
  );
  assert.deepEqual(codex.notes, CODEX_HARNESS.notes);
  assert.deepEqual([sdk.label, sdk.version, sdk.modelConnection, sdk.streaming], ["NoClick", null, "optional", "tokens"]);
});

test("harness.models searches its models for no user, through the client the harness came from", async () => {
  const { api } = setup();
  api.on("GET", "/v1/harnesses", json(listing([CODEX_HARNESS])));
  const models = api.on("GET", "/v1/harnesses/codex/models", json(listing([
    { object: "harness_model", id: "gpt-5.6-luna", label: "gpt-5.6-luna", canonical: "gpt-5.6-luna", route: "maker",
      noclick_key: { output_usd_per_million: 40, needs_funds_usd: 5 } },
    { object: "harness_model", id: "openrouter/openai/gpt-5-codex", label: null, canonical: "openai/gpt-5-codex", route: "openrouter",
      noclick_key: null },
  ])));
  const [codex] = await nc.Agent.harnesses();
  const found = await nc.asUser(USER_ID, () => codex.models({ search: "gpt-5", limit: 2 }));
  // Each model says how it's reached, the model it is, and what it costs on NoClick's key.
  assert.deepEqual(found, [
    { id: "gpt-5.6-luna", label: "gpt-5.6-luna", canonical: "gpt-5.6-luna", route: "maker",
      noclickKey: { outputUsdPerMillion: 40, needsFundsUsd: 5 } },
    { id: "openrouter/openai/gpt-5-codex", label: null, canonical: "openai/gpt-5-codex", route: "openrouter", noclickKey: null },
  ]);
  assert.deepEqual(Object.fromEntries(models.last.query), { q: "gpt-5", limit: "2" });
  assert.equal(models.last.headers.get("NoClick-User"), null);
  await codex.models();
  assert.deepEqual(Object.fromEntries(models.last.query), { limit: "50" });

  const other = new nc.NoClick({ apiKey: "nk_live_other", baseUrl: BASE, fetch: api.fetch });
  const [theirs] = await nc.Agent.harnesses({ client: other });
  await theirs.models();
  assert.equal(models.last.headers.get("Authorization"), "Bearer nk_live_other");
});

test("a CLI agent creates its lazy model connection first; fromName converges harness and modelConnection", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/claude", apiError(404, "not_found"));
  const made = api.on("POST", "/v1/connections", json(CLAUDE, { status: 201 }));
  const create = api.on("POST", "/v1/agents", json(CODER, { status: 201 }));
  const claude = nc.Connection.fromName("claude", { integration: "anthropic", createIfMissing: true });
  const coder = await nc.Agent.create("coder", { instructions: "Plan.", harness: "claude_code", model: "sonnet", modelConnection: claude });
  assert.deepEqual([coder.harness, coder.model, coder.modelConnection], ["claude_code", "sonnet", "claude"]);
  assert.deepEqual(made.last.body, { name: "claude", integration: "anthropic" });
  assert.deepEqual(create.last.body, { name: "coder", instructions: "Plan.", model: "sonnet", harness: "claude_code", model_connection: "claude" });
  // From another scope it's named by id, which the API refuses as it does in tools.
  await nc.Agent.create("mine", { instructions: "Plan.", harness: "codex", modelConnection: claude, user: USER_ID });
  assert.equal((create.last.body as Record<string, unknown>).model_connection, "connection:con_cl");

  api.on("GET", "/v1/agents", json(listing([{ ...CODER, instructions: "Plan." }])));
  const patch = api.on("PATCH", "/v1/agents/agt_cc", json({ ...CODER, instructions: "Plan.", harness: "codex", model: "gpt-5.6-luna", model_connection: "openai" }));
  await nc.Agent.fromName("coder", { createIfMissing: true, instructions: "Plan.", harness: "claude_code", modelConnection: "claude" }).hydrate();
  assert.equal(patch.count, 0);
  const moved = await nc.Agent.fromName("coder", { createIfMissing: true, instructions: "Plan.", harness: "codex", modelConnection: "openai" }).hydrate();
  // The server gives a new harness its default model, so the definition never resends one.
  assert.deepEqual(patch.last.body, { harness: "codex", model_connection: "openai" });
  assert.deepEqual([moved.harness, moved.model], ["codex", "gpt-5.6-luna"]);

  await moved.update({ harness: "sdk", modelConnection: null });
  assert.deepEqual(patch.last.body, { harness: "sdk", model_connection: null });
});

test("a turn on a CLI harness reports its step until the reply lands", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/agt_cc", json(CODER));
  api.on("POST", "/v1/agents/agt_cc/messages", json(operation({ id: "op_m", kind: "agent.message", status: "queued" }), { status: 202 }));
  const view = (status: string, step: string | null, result: unknown = null) => json(operation({ id: "op_m", kind: "agent.message", status, step, result }));
  api.on("GET", "/v1/operations/op_m", view("running", "delivering"), view("running", "working"));
  api.on("GET", "/v1/operations/op_m/wait", view("succeeded", null, {
    text: "Fixed 3 links.", conversation: "docs-1", tool_calls: [{ tool: "Bash", source: "harness" }], cost_usd: 0.04,
  }));
  const turn = await nc.Agent.fromId("agt_cc").send("Fix the links", { conversation: "docs-1" });
  assert.equal(turn.step, null);
  assert.deepEqual([(await turn.refresh()).status, turn.step], ["running", "delivering"]);
  assert.equal((await turn.refresh()).step, "working");
  const reply = await turn.wait();
  assert.deepEqual([reply.text, reply.toolCalls[0].source], ["Fixed 3 links.", "harness"]);
  assert.equal(turn.step, null);
});

test("grants read fresh; revokeGrant takes a grant or its id", async () => {
  const { api } = setup();
  const grant = {
    object: "agent_grant", id: "gr_1", connection: "work-gmail", connection_id: "con_1", integration: "gmail",
    operations: ["send_email_message"], status: "active", reason: "To send your summary.", conversation: "c1",
    created_at: "2026-09-25T10:00:00Z", granted_at: "2026-09-25T10:05:00Z",
  };
  const read = api.on("GET", "/v1/agents/agt_1", json({ ...AGENT, grants: [grant] }));
  const revoke = api.on("DELETE", "/v1/agents/agt_1/grants/gr_1", json({ object: "agent_grant", id: "gr_1", revoked: true }));
  const agent = nc.Agent.fromId("agt_1");
  const [got] = await agent.grants();
  assert.deepEqual([got.connection, got.integration, got.operations, got.status], ["work-gmail", "gmail", ["send_email_message"], "active"]);
  assert.ok(got.grantedAt instanceof Date);
  assert.equal(read.count, 2);
  await agent.revokeGrant(got);
  await agent.revokeGrant("gr_1");
  assert.equal(revoke.count, 2);
});

test("a write creates a lazy connection outright (a taken name of its integration is used); only() names some operations", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/connections/gmail", json(PENDING));
  const create = api.on(
    "POST", "/v1/connections",
    json(PENDING, { status: 201 }),
    apiError(409, "conflict", "exists", { existing_id: "con_9" }),
  );
  const existing = api.on("GET", "/v1/connections/con_9", json({ ...PENDING, id: "con_9" }));
  const link = api.on("POST", "/v1/connections/con_1/connect_links", json({ url: "u", operation: "op_c" }));
  const taken = api.on("POST", "/v1/connections/con_9/connect_links", json({ url: "u2", operation: "op_d" }));
  const gmail = nc.Connection.fromName("gmail", { integration: "gmail", createIfMissing: true });
  assert.equal((await gmail.connectLink()).url, "u");
  assert.equal((await gmail.connectLink()).url, "u");
  assert.deepEqual([create.count, link.count], [1, 2]);
  const other = nc.Connection.fromName("gmail", { integration: "gmail", createIfMissing: true, data: { api_key: "k" } });
  assert.equal((await other.connectLink()).url, "u2");
  assert.deepEqual(create.last.body, { name: "gmail", integration: "gmail", data: { api_key: "k" } });
  assert.deepEqual([taken.count, existing.count, read.count], [1, 1, 0]);
  // A taken name of another integration is refused before anything is written to it.
  const wrong = nc.Connection.fromName("gmail", { integration: "slack", createIfMissing: true });
  await assert.rejects(wrong.connectLink(), (err: nc.Conflict) => err.details.field === "integration" && err.details.integration === "gmail");
  assert.equal(taken.count, 1);

  const stripe = nc.Connection.fromName("stripe");
  const toolkit = new nc.Toolkit(["search", stripe.only("list_invoices", "get_invoice")]);
  assert.deepEqual(toolkit.tools, ["search", "stripe.list_invoices", "stripe.get_invoice"]);
  assert.throws(() => stripe.only(), TypeError);
});
