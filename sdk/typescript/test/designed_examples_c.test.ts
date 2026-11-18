// Designed from the examples (users, inboxes, phone numbers, channels, apps, domains, brand, cards),
// and numbers you bring (connected or ported), against the mock API: routes, bodies, convergence and
// the client's own refusals.
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";
import { inspect } from "node:util";

import * as nc from "../src/index.ts";
import { BASE, USER_ID, apiError, json, listing, operation, setup, userRow } from "./helpers.ts";

const INBOX = {
  object: "inbox", id: "inb_1", name: "support", address: "help@acme.test", agent_id: "agt_1", senders: "anyone",
  user_id: null, created_at: "2026-09-25T10:00:00Z",
};
const NUMBER = {
  object: "phone_number", id: "pn_1", name: "front-desk", number: "+14155550123", agent_id: null, monthly_usd: 1.5,
  record_calls: false, user_id: null, created_at: "2026-09-25T10:00:00Z",
};
const CHANNEL = {
  object: "channel", id: "ch_1", name: "daily", mode: "mentions", status: "open", max_agent_turns: 12, budget_usd: null,
  user_id: null, created_at: "2026-09-25T10:00:00Z",
  members: [
    { id: "m_1", type: "agent", agent_id: "agt_1", name: "writer" },
    { id: "m_2", type: "agent", agent_id: "agt_old", name: "old" },
  ],
};
const PROJECT = { object: "project", id: "prj_1", name: "booking", url: "https://booking.noclick.site", repo_id: "rp_1", user_id: null };
const DOMAIN = { object: "domain", id: "dom_1", name: "acmebooking.com", source: "bought", status: "active", auto_renew: true };
const CONTACT: nc.DomainContact = {
  name: "Dana Reyes", email: "dana@acmebooking.test", phone: "+14155550188", address: "1 Ferry Building",
  city: "San Francisco", region: "CA", postalCode: "94111", country: "US",
};

function cron(id: string, expr: string, message: string) {
  return {
    object: "agent_trigger", id, kind: "cron", spec: { cron: expr, tz: "UTC", message }, status: "active",
    next_run: "2026-10-02T09:00:00Z", created_at: "2026-09-25T10:00:00Z",
  };
}

// --- users ---------------------------------------------------------------------

test("a user's timezone is sent, converged and cleared", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/users", json(userRow({ timezone: "America/Sao_Paulo" })));
  const user = await nc.User.create(USER_ID, { timezone: "America/Sao_Paulo" });
  assert.deepEqual(create.last.body, { id: USER_ID, timezone: "America/Sao_Paulo" });
  assert.equal(user.timezone, "America/Sao_Paulo");

  api.on("GET", `/v1/users/${USER_ID}`, json(userRow({ email: "ana@example.com", timezone: "UTC" })));
  const patch = api.on("PATCH", `/v1/users/${USER_ID}`, json(userRow({ timezone: "Europe/Lisbon" })));
  const converged = await nc.User.fromId(USER_ID, { createIfMissing: true, email: "ana@example.com", timezone: "Europe/Lisbon" }).hydrate();
  assert.equal(converged.timezone, "Europe/Lisbon");
  assert.deepEqual(patch.last.body, { timezone: "Europe/Lisbon" });
  await nc.User.fromId(USER_ID).update({ timezone: null });
  assert.deepEqual(patch.last.body, { timezone: null });
});

// --- inboxes -------------------------------------------------------------------

test("Inbox.create sends a name and senders; fromName converges and creates", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/inboxes", json(INBOX));
  await nc.Inbox.create({ localPart: "help", name: "support", agent: "agt_1", senders: "users" });
  assert.deepEqual(create.last.body, { name: "support", local_part: "help", agent_id: "agt_1", senders: "users" });

  const lookup = api.on("GET", "/v1/inboxes", json(listing([{ ...INBOX, id: "inb_0", name: "other" }, INBOX])));
  const patch = api.on("PATCH", "/v1/inboxes/inb_1", json({ ...INBOX, agent_id: null, senders: "owner" }));
  const inbox = nc.Inbox.fromName("support", { createIfMissing: true, localPart: "help", agent: null, senders: "owner" });
  assert.equal(lookup.count, 0);
  await inbox.hydrate();
  assert.equal(lookup.last.query.get("name"), "support");
  assert.deepEqual(patch.last.body, { agent_id: null, senders: "owner" });
  assert.equal(inbox.senders, "owner");

  api.on("GET", "/v1/inboxes", json(listing([])));
  await nc.Inbox.fromName("fresh", { createIfMissing: true, localPart: "fresh", domain: "acme.test" }).hydrate();
  assert.deepEqual(create.last.body, { name: "fresh", local_part: "fresh", domain: "acme.test" });
  await assert.rejects(nc.Inbox.fromName("gone").hydrate(), nc.NotFound);
});

test("inbox listings by agent, messages since a time, and what a message woke", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/inboxes", json(listing([INBOX])));
  const [inbox] = await nc.Inbox.list({ agent: "agt_1" });
  assert.equal(listed.last.query.get("agent_id"), "agt_1");

  const messages = api.on("GET", "/v1/inboxes/inb_1/messages", json(listing([{
    id: "msg_1", inbox_id: "inb_1", from: "ana@example.com", conversation: "inbox:inb_1:thr_9",
    agent_operation_id: "op_turn", agent_error: null,
  }])));
  const [mail] = await inbox.messages({ since: new Date("2026-09-30T00:00:00Z") });
  assert.equal(messages.last.query.get("since"), "2026-09-30T00:00:00.000Z");
  assert.deepEqual([mail.conversation, mail.agentError, mail.agentOperation?.id], ["inbox:inb_1:thr_9", null, "op_turn"]);

  const wait = api.on("POST", "/v1/inboxes/inb_1/wait_for", json(operation({ id: "op_w", kind: "inbox.wait_for", status: "running" })));
  await nc.Inbox.fromName("support").waitFor({ sender: "noreply@github.com", since: "2026-09-30T12:00:00Z" });
  assert.deepEqual(wait.last.body, { sender: "noreply@github.com", since: "2026-09-30T12:00:00Z" });
});

// --- phone numbers -------------------------------------------------------------

test("PhoneNumber.fromName buys once, then converges recording", async () => {
  const { api } = setup();
  api.on("GET", "/v1/phone_numbers", json(listing([])));
  const buy = api.on("POST", "/v1/phone_numbers", json(NUMBER));
  const number = await nc.PhoneNumber.fromName("front-desk", { createIfMissing: true, areaCode: 415, maxMonthlyUsd: 5 }).hydrate();
  assert.equal(number.number, "+14155550123");
  assert.deepEqual(buy.last.body, { name: "front-desk", area_code: "415", max_monthly_usd: 5 });
  assert.throws(() => nc.PhoneNumber.fromName("front-desk", { createIfMissing: true }), /maxMonthlyUsd/);

  api.on("GET", "/v1/phone_numbers", json(listing([NUMBER])));
  const patch = api.on("PATCH", "/v1/phone_numbers/pn_1", json({ ...NUMBER, record_calls: true }));
  const recorded = await nc.PhoneNumber.fromName("front-desk", { createIfMissing: true, maxMonthlyUsd: 5, recordCalls: true }).hydrate();
  assert.deepEqual([recorded.recordCalls, patch.last.body], [true, { record_calls: true }]);
  assert.equal(buy.count, 1);
});

test("answerWith transfers, texts and answers only users; calls are filtered", async () => {
  const { api } = setup();
  const answer = api.on("POST", "/v1/phone_numbers/pn_1/answer", json({ ...NUMBER, agent_id: "agt_1" }));
  const number = nc.PhoneNumber.fromId("pn_1");
  await number.answerWith("agt_1", { transferTo: new nc.Human({ phone: "+14155550142" }), texts: true, callers: "users" });
  assert.deepEqual(answer.last.body, { agent_id: "agt_1", transfer_to: "+14155550142", texts: true, callers: "users" });
  await number.answerWith("agt_1");
  assert.deepEqual(answer.last.body, { agent_id: "agt_1" });
  await number.answerWith("agt_1", { callers: "owner" });
  assert.deepEqual(answer.last.body, { agent_id: "agt_1", callers: "owner" });
  await assert.rejects(number.answerWith("agt_1", { callers: "friends" as nc.PhoneCallers }), /"anyone", "users" or "owner"/);
  await assert.rejects(number.answerWith("agt_1", { transferTo: new nc.Human({ email: "dana@example.com" }) }), /with a phone/);

  const history = api.on("GET", "/v1/phone_numbers/pn_1/calls", json(listing([{
    id: "call_9", direction: "inbound", from: "+14155550100", status: "completed", transcript: [], user_id: USER_ID,
    recording_url: "https://files.noclick.test/rec/call_9?sig=x",
  }])));
  const [call] = await number.calls({ direction: "inbound", since: new Date("2026-09-23T00:00:00Z"), limit: 50 });
  assert.deepEqual([history.last.query.get("direction"), history.last.query.get("since"), history.last.query.get("limit")],
    ["inbound", "2026-09-23T00:00:00.000Z", "50"]);
  assert.deepEqual([call.userId, call.recordingUrl], [USER_ID, "https://files.noclick.test/rec/call_9?sig=x"]);
});

// --- numbers you bring ------------------------------------------------------------

const PROVIDER = {
  object: "connection", id: "conn_7", name: "phone-provider", integration: "twilio",
  credential_type: "twilio_account", status: "connected", user_id: null,
};
const CONNECTED = { ...NUMBER, id: "pn_2", source: "connected", connection: "phone-provider", monthly_usd: null };
const PORTED = { ...NUMBER, id: "pn_3", number: "+14155550188", source: "ported", monthly_usd: 1.5 };

test("PhoneNumber.connectable lists the provider account's numbers", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/phone-provider", json(PROVIDER));
  const route = api.on("GET", "/v1/phone_numbers/connectable", json(listing([
    { number: "+14155550123", label: "Front desk", routed_elsewhere: true },
    { number: "+14155550124", label: "(415) 555-0124", routed_elsewhere: false, phone_number_id: "pn_2", agent_id: "agt_1" },
  ])));
  const [taken, free] = await nc.PhoneNumber.connectable(nc.Connection.fromName("phone-provider"));
  assert.equal(route.last.query.get("connection"), "conn_7");
  assert.deepEqual([taken.number, taken.label, taken.routedElsewhere, free.routedElsewhere], ["+14155550123", "Front desk", true, false]);
  assert.deepEqual([taken.phoneNumberId, taken.agentId, free.phoneNumberId, free.agentId], [null, null, "pn_2", "agt_1"]);
  await nc.PhoneNumber.connectable("phone-provider", { user: "user_42" });
  assert.deepEqual([route.last.query.get("connection"), route.last.headers.get("NoClick-User")], ["phone-provider", "user_42"]);
});

test("PhoneNumber.connect connects a number you keep; fromName connects it once", async () => {
  const { api } = setup();
  const connect = api.on("POST", "/v1/phone_numbers/connect", json(CONNECTED));
  const number = await nc.PhoneNumber.connect(
    { number: "+14155550123", label: null, routedElsewhere: true, phoneNumberId: null, agentId: null, raw: {} },
    { connection: "phone-provider", name: "front-desk", user: "user_42" },
  );
  assert.deepEqual(connect.last.body, { number: "+14155550123", connection: "phone-provider", name: "front-desk" });
  assert.equal(connect.last.headers.get("NoClick-User"), "user_42");
  assert.deepEqual([number.source, number.connection, number.monthlyUsd], ["connected", "phone-provider", null]);

  api.on("GET", "/v1/phone_numbers", json(listing([])));
  const named = await nc.PhoneNumber.fromName("front-desk", { createIfMissing: true, connect: "+14155550123", connection: "phone-provider" }).hydrate();
  assert.deepEqual(connect.last.body, { name: "front-desk", number: "+14155550123", connection: "phone-provider" });
  assert.equal(named.source, "connected");
  assert.throws(() => nc.PhoneNumber.fromName("front-desk", { createIfMissing: true, connect: "+14155550123" }), /needs connection/);
  assert.throws(
    () => nc.PhoneNumber.fromName("front-desk", { createIfMissing: true, connect: "+14155550123", connection: "phone-provider", maxMonthlyUsd: 5 }),
    /not both/,
  );

  api.on("POST", "/v1/phone_numbers/connect", apiError(409, "conflict", "+14155550123 is answered by the receptionist agent.", { existing_id: "pn_2" }));
  await assert.rejects(nc.PhoneNumber.connect("+14155550123", { connection: "phone-provider" }), (err: unknown) =>
    err instanceof nc.Conflict && err.existingId === "pn_2");
});

test("disconnect hands a connected number back", async () => {
  const { api } = setup();
  const disconnect = api.on("POST", "/v1/phone_numbers/pn_2/disconnect", json(CONNECTED));
  const number = nc.PhoneNumber.fromId("pn_2");
  await number.disconnect();
  assert.deepEqual([disconnect.count, number.released], [1, true]);
});

const FERRY: nc.StreetAddress = { street: "1 Ferry Building", city: "San Francisco", region: "CA", postalCode: "94111" };
const FERRY_WIRE = { street: "1 Ferry Building", city: "San Francisco", region: "CA", postal_code: "94111" };

test("PhoneNumber.portIn waits for the signature, then the carrier", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/phone_numbers/port_in", json(operation({
    id: "op_port", kind: "phone.port_in", status: "awaiting_human", number: "+14155550188",
    sign_url: "https://noclick.com/sign/loa_1", port_at: null, monthly_usd: 1.5,
  })));
  const port = await nc.PhoneNumber.portIn("+14155550188", {
    accountHolder: "dana@harbordental.test", accountName: "Harbor Dental LLC", serviceAddress: FERRY,
    accountNumber: "8812-4410-09", pin: "4410", bill: new TextEncoder().encode("%PDF-1.7"), maxMonthlyUsd: 5,
    name: "front-desk", requestedAt: new Date("2026-10-12T09:00:00Z"),
  });
  assert.deepEqual(start.last.body, {
    numbers: ["+14155550188"], max_monthly_usd: 5, name: "front-desk", account_holder: "dana@harbordental.test",
    account_name: "Harbor Dental LLC", service_address: FERRY_WIRE, account_number: "8812-4410-09", pin: "4410",
    bill: "JVBERi0xLjc=", requested_at: "2026-10-12T09:00:00.000Z",
  });
  assert.ok(port instanceof nc.PortRequest && port instanceof nc.Operation);
  assert.deepEqual([port.status, port.signUrl, port.number, port.monthlyUsd], ["awaiting_human", "https://noclick.com/sign/loa_1", "+14155550188", 1.5]);

  api.on("GET", "/v1/operations/op_port", json(operation({
    id: "op_port", kind: "phone.port_in", status: "running", step: "scheduled", sign_url: "https://noclick.com/sign/loa_1",
    port_at: "2026-10-14T13:00:00Z",
  })));
  const scheduled = await nc.PortRequest.portFromId("op_port").hydrate();
  assert.deepEqual([scheduled.step, scheduled.portAt?.getUTCDate(), scheduled.signUrl], ["scheduled", 14, null]);
  api.on("GET", "/v1/operations/op_port/wait", json(operation({ id: "op_port", kind: "phone.port_in", status: "succeeded", result: { phone_numbers: [PORTED] } })));
  const [number] = await port.wait();
  assert.ok(number instanceof nc.PhoneNumber);
  assert.deepEqual([number.source, number.number], ["ported", "+14155550188"]);
});

test("PhoneNumber.portIn takes several numbers on one letter, signed by a Human", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/phone_numbers/port_in", json(operation({
    id: "op_p2", kind: "phone.port_in", status: "awaiting_human", number: "+14155550188",
    numbers: [{ number: "+14155550188", status: "draft", port_at: null }, { number: "+14155550189", status: "draft", port_at: null }],
  })));
  const port = await nc.PhoneNumber.portIn(["+14155550188", "+14155550189"], {
    accountHolder: new nc.Human({ email: "dana@harbordental.test", phone: "+14155550142" }),
    accountName: "Harbor Dental LLC", serviceAddress: FERRY, accountNumber: "8812-4410-09", billingNumber: "+14155550100",
    remainingNumbers: ["+14155550100"], maxMonthlyUsd: 5,
  });
  const sent = start.last.body as { numbers: string[]; billing_number: string; account_holder: unknown; remaining_numbers: string[] };
  assert.deepEqual([sent.numbers, sent.billing_number], [["+14155550188", "+14155550189"], "+14155550100"]);
  assert.deepEqual(sent.remaining_numbers, ["+14155550100"]); // a partial port: the main number stays
  assert.equal(sent.account_holder, "dana@harbordental.test"); // the person signs; only their email goes
  assert.deepEqual(port.numbers.map((n) => [n.number, n.status, n.portAt]), [["+14155550188", "draft", null], ["+14155550189", "draft", null]]);
  const details = { accountName: "x", serviceAddress: FERRY, accountNumber: "1", maxMonthlyUsd: 5 };
  await assert.rejects(nc.PhoneNumber.portIn("+14155550188", { ...details, accountHolder: new nc.Human({ phone: "+14155550142" }) }), /with an email/);
  await assert.rejects(nc.PhoneNumber.portIn("+14155550188", { ...details, accountHolder: 42 as unknown as string }), /accountHolder/);
});

test("a TextingRegistration is created, corrected, verified and deleted", async () => {
  const { api } = setup();
  const view = {
    object: "texting_registration", id: "tr_1", status: "pending", brand_name: "Harbor Dental", setup_usd: 32.5, monthly_usd: 2.5,
    segment_usd: 0.0083, fields: [],
  };
  const made = api.on("POST", "/v1/texting_registrations", json(view, { status: 201 }));
  const registration = await nc.TextingRegistration.create({
    legalName: "Harbor Dental LLC", brandName: "Harbor Dental", entityType: "private_company", taxId: "12-3456789",
    industry: "healthcare", website: "https://harbordental.test", address: FERRY,
    contact: { name: "Dana Ruiz", email: "dana@harbordental.test", phone: "+14155550142" },
    privacyUrl: "https://harbordental.test/privacy", termsUrl: "https://harbordental.test/terms", maxSetupUsd: 40, maxMonthlyUsd: 5,
  });
  const sent = made.last.body as Record<string, unknown>;
  assert.deepEqual([sent.entity_type, sent.tax_id, sent.address, sent.privacy_url, sent.max_setup_usd], [
    "private_company", "12-3456789", FERRY_WIRE, "https://harbordental.test/privacy", 40,
  ]);
  assert.ok(!("stock" in sent));
  assert.deepEqual([registration.status, registration.setupUsd, registration.segmentUsd], ["pending", 32.5, 0.0083]);

  api.on("GET", "/v1/texting_registrations/tr_1", json({ ...view, status: "rejected", fields: ["tax_id"] }));
  const refused = await nc.TextingRegistration.get("tr_1");
  assert.deepEqual([refused.status, refused.fields], ["rejected", ["tax_id"]]);
  const corrected = api.on("PATCH", "/v1/texting_registrations/tr_1", json({ ...view, status: "pending" }));
  assert.equal((await refused.update({ taxId: "98-7654321" })).status, "pending");
  assert.deepEqual(corrected.last.body, { tax_id: "98-7654321" });
  const verified = api.on("POST", "/v1/texting_registrations/tr_1/verify", json({ ...view, status: "in_review" }));
  assert.equal((await refused.verify("482913")).status, "in_review");
  assert.deepEqual(verified.last.body, { code: "482913" });
  const gone = api.on("DELETE", "/v1/texting_registrations/tr_1", json({ id: "tr_1", deleted: true }));
  await refused.delete();
  assert.equal(gone.count, 1);
});

test("a number texts, lists its texts and opens a transfer out", async () => {
  const { api } = setup();
  const answer = api.on("POST", "/v1/phone_numbers/pn_1/answer", json({ id: "pn_1", texts: true }));
  const number = await nc.PhoneNumber.fromId("pn_1").answerWith("ag_1", { texts: true });
  assert.deepEqual(answer.last.body, { agent_id: "ag_1", texts: true });
  assert.equal(number.texts, true);
  const texts = api.on("GET", "/v1/phone_numbers/pn_1/texts", json(listing([{
    object: "phone_text", id: "tx_1", direction: "inbound", from: "+14155550100", to: "+14155550123", text: "STOP", keyword: "stop",
    status: "received", segments: 1, cost_usd: 0.005,
  }])));
  const [text] = await number.textMessages({ direction: "inbound" });
  assert.equal(texts.last.query.get("direction"), "inbound");
  assert.deepEqual([text.fromNumber, text.keyword, text.text, text.costUsd], ["+14155550100", "stop", "STOP", 0.005]);
  api.on("POST", "/v1/phone_numbers/pn_1/transfer_out", json({
    object: "transfer_out", phone_number_id: "pn_1", number: "+14155550123", account_name: "NoClick Inc", account_number: "4155550123",
    billing_number: "+14155550123", pin: "73019284", service_address: "548 Market St, San Francisco, CA 94104",
    expires_at: "2026-11-01T00:00:00Z",
  }));
  const details = await number.transferOut();
  assert.ok(details instanceof nc.TransferOut);
  assert.deepEqual(
    [details.pin, details.accountNumber, details.billingNumber, details.expiresAt?.getUTCMonth()],
    ["73019284", "4155550123", "+14155550123", 10],
  );
  assert.ok(!inspect(details).includes("73019284"));
});

test("a rejected port retries with corrections, and a live one cancels", async () => {
  const { api } = setup();
  api.on("GET", "/v1/operations/op_port/wait", json(operation({
    id: "op_port", kind: "phone.port_in", status: "failed",
    error: { type: "invalid_request", message: "The account number doesn't match the carrier's records.", field: "account_number" },
  })));
  const port = nc.PortRequest.portFromId("op_port");
  await assert.rejects(port.wait(), (err: unknown) => err instanceof nc.InvalidRequest && err.details.field === "account_number");
  const retry = api.on("POST", "/v1/phone_numbers/port_in/op_port/retry", json(operation({
    id: "op_port2", kind: "phone.port_in", status: "running", step: "submitted",
  })));
  const again = await port.retry({ accountNumber: "8812-4410-07" });
  assert.deepEqual(retry.last.body, { account_number: "8812-4410-07" }); // the rest is kept
  await port.retry({ remainingNumbers: [] });
  assert.deepEqual(retry.last.body, { remaining_numbers: [] }); // every number on the account moves
  assert.ok(again instanceof nc.PortRequest);
  assert.deepEqual([again.id, again.step], ["op_port2", "submitted"]);

  api.on("POST", "/v1/operations/op_port2/cancel", json(operation({ id: "op_port2", kind: "phone.port_in", status: "canceled" })));
  assert.equal((await again.cancel()).status, "canceled");
});

test("PortRequest.list is typed and pinned to its kind", async () => {
  const { api } = setup();
  const rows = [
    operation({ id: "op_a", kind: "phone.port_in", status: "awaiting_human", number: "+14155550188", sign_url: "https://noclick.com/sign/loa_1" }),
    operation({ id: "op_b", kind: "phone.port_in", status: "running", step: "scheduled", number: "+14155550199", port_at: "2026-10-14T13:00:00Z" }),
  ];
  const listed = api.on("GET", "/v1/operations", json(listing(rows)));
  const [waiting, scheduled] = await nc.PortRequest.list({ status: "live", userFilter: nc.ALL_USERS });
  assert.deepEqual([listed.last.query.get("kind"), listed.last.query.get("status"), listed.last.query.get("user_id")], ["phone.port_in", "live", "all"]);
  assert.ok(waiting instanceof nc.PortRequest);
  assert.equal(waiting.signUrl, "https://noclick.com/sign/loa_1");
  assert.deepEqual([scheduled.step, scheduled.portAt?.getUTCDate(), scheduled.signUrl], ["scheduled", 14, null]);
  api.on("GET", "/v1/operations", json(listing(rows, "c2")));
  const page = await nc.PortRequest.listPage({ limit: 2 });
  assert.deepEqual([page.data.map((p) => p.id), page.nextCursor], [["op_a", "op_b"], "c2"]);
  assert.ok(page.data[0] instanceof nc.PortRequest);
  await assert.rejects(nc.PortRequest.list({ kind: "phone.call" } as nc.KindScopedFilters), /reads only phone.port_in/);
});

// --- channels ------------------------------------------------------------------

test("Channel.fromName opens a room with members and schedules", async () => {
  const { api } = setup();
  api.on("GET", "/v1/channels", json(listing([{ ...CHANNEL, status: "closed" }])));
  const create = api.on("POST", "/v1/channels", json(CHANNEL));
  const room = await nc.Channel.fromName("daily", {
    createIfMissing: true, members: [nc.Agent.fromId("agt_1")], maxAgentTurns: 12,
    triggers: [new nc.Cron("0 9 * * 1-5", { message: "@writer draft today's changelog" })],
  }).hydrate();
  assert.equal(room.id, "ch_1");
  assert.deepEqual(create.last.body, {
    name: "daily", members: [{ agent_id: "agt_1" }], max_agent_turns: 12,
    triggers: [{ kind: "cron", cron: "0 9 * * 1-5", tz: "UTC", message: "@writer draft today's changelog" }],
  });
});

test("Channel.fromName converges settings, members and schedules", async () => {
  const { api } = setup();
  api.on("GET", "/v1/channels", json(listing([CHANNEL])));
  const patch = api.on("PATCH", "/v1/channels/ch_1", json({ ...CHANNEL, max_agent_turns: 20 }));
  const removed = api.on("DELETE", "/v1/channels/ch_1/members/m_2", new Response(null, { status: 204 }));
  const added = api.on("POST", "/v1/channels/ch_1/members", json({ id: "m_3", type: "agent", agent_id: "agt_2" }));
  api.on("GET", "/v1/channels/ch_1/triggers", json(listing([cron("tr_1", "0 8 * * *", "old"), cron("tr_2", "0 9 * * 1-5", "@writer go")])));
  const dropped = api.on("DELETE", "/v1/channels/ch_1/triggers/tr_1", new Response(null, { status: 204 }));
  const fresh = api.on("POST", "/v1/channels/ch_1/triggers", json(cron("tr_3", "0 17 * * 5", "@writer wrap up")));
  const reread = api.on("GET", "/v1/channels/ch_1", json(CHANNEL));
  await nc.Channel.fromName("daily", {
    createIfMissing: true, members: [nc.Agent.fromId("agt_1"), nc.Agent.fromId("agt_2")], maxAgentTurns: 20, budgetUsd: null,
    triggers: [new nc.Cron("0 9 * * 1-5", { message: "@writer go" }), new nc.Cron("0 17 * * 5", { message: "@writer wrap up" })],
  }).hydrate();
  assert.deepEqual(patch.last.body, { max_agent_turns: 20 });
  assert.deepEqual([removed.count, added.last.body, dropped.count], [1, { agent_id: "agt_2" }, 1]);
  assert.deepEqual(fresh.last.body, { kind: "cron", cron: "0 17 * * 5", tz: "UTC", message: "@writer wrap up" });
  assert.equal(reread.count, 1);
});

test("Channel.fromName: null puts a limit back to its default and lifts the budget", async () => {
  const { api } = setup();
  api.on("GET", "/v1/channels", json(listing([{ ...CHANNEL, max_mention_hops: 3, budget_usd: 5 }])));
  const patch = api.on("PATCH", "/v1/channels/ch_1", json(CHANNEL));
  await nc.Channel.fromName("daily", { createIfMissing: true, maxAgentTurns: null, maxMentionHops: null, budgetUsd: null }).hydrate();
  assert.deepEqual(patch.last.body, { max_agent_turns: 20, max_mention_hops: 8, budget_usd: null });
  api.on("GET", "/v1/channels", json(listing([{ ...CHANNEL, max_agent_turns: 20, max_mention_hops: 8 }])));
  await nc.Channel.fromName("daily", { createIfMissing: true, maxAgentTurns: null, maxMentionHops: null }).hydrate();
  assert.equal(patch.count, 1);
});

test("channel triggers: list, add, remove by definition", async () => {
  const { api } = setup();
  api.on("GET", "/v1/channels/ch_1/triggers", json(listing([cron("tr_1", "0 9 * * 1-5", "@writer go")])));
  const add = api.on("POST", "/v1/channels/ch_1/triggers", json(cron("tr_2", "0 16 * * 5", "@writer wrap up")));
  const del = api.on("DELETE", "/v1/channels/ch_1/triggers/tr_1", new Response(null, { status: 204 }));
  const room = nc.Channel.fromId("ch_1");
  const [trigger] = await room.triggers();
  assert.deepEqual([trigger.kind, trigger.spec.message, trigger.defined], ["cron", "@writer go", true]);
  await room.addTrigger(new nc.Cron("0 16 * * 5", { message: "@writer wrap up" }));
  assert.equal((add.last.body as { message: string }).message, "@writer wrap up");
  await room.removeTrigger(new nc.Cron("0 9 * * 1-5", { message: "@writer go" }));
  assert.equal(del.count, 1);
  await assert.rejects(room.removeTrigger(new nc.Cron("0 1 * * *", { message: "nope" })), nc.NotFound);
  await assert.rejects(room.addTrigger(new nc.Cron("0 9 * * *")), /message/);
});

// --- apps ----------------------------------------------------------------------

test("Project.current signs in with the deployment and reads what it's bound to", async () => {
  const { api } = setup();
  delete process.env.NOCLICK_DEPLOYMENT_TOKEN;
  assert.throws(() => nc.Project.current(), nc.Unauthenticated);

  const current = api.on("GET", "/v1/projects/current", json(PROJECT));
  for (const [name, kind] of [["DB", "database"], ["FILES", "bucket"], ["SESSIONS", "dict"], ["JOBS", "queue"], ["CRM", "connection"]]) {
    api.on("GET", `/v1/projects/prj_1/bindings/${name}`, json({ name, kind, resource_id: `${kind}_1` }));
  }
  const realFetch = globalThis.fetch;
  process.env.NOCLICK_DEPLOYMENT_TOKEN = "nk_dep_123";
  process.env.NOCLICK_API_URL = BASE;
  globalThis.fetch = api.fetch as typeof fetch;
  try {
    const app = nc.Project.current();
    const db = await app.database("DB");
    assert.deepEqual([app.name, db.id], ["booking", "database_1"]);
    assert.equal(current.last.headers.get("Authorization"), "Bearer nk_dep_123");
    assert.ok((await app.bucket("FILES")) instanceof nc.Bucket);
    assert.ok((await app.dict("SESSIONS")) instanceof nc.Dict);
    assert.ok((await app.queue("JOBS")) instanceof nc.Queue);
    assert.ok((await app.connection("CRM")) instanceof nc.Connection);
    await assert.rejects(app.queue("DB"), /bound to a database, not a queue/);
  } finally {
    globalThis.fetch = realFetch;
    delete process.env.NOCLICK_DEPLOYMENT_TOKEN;
    delete process.env.NOCLICK_API_URL;
  }
});

test("verifyRequest checks the schedule's signature with the deployment's secret", async () => {
  const app = nc.Project.fromId("prj_1");
  const payload = '{"schedule":"reminders"}';
  const now = Math.floor(Date.now() / 1000);
  const signature = createHmac("sha256", "whsec_app").update(`${now}.${payload}`).digest("hex");
  const headers = { "noclick-signature": `t=${now},v1=${signature}` };
  delete process.env.NOCLICK_SIGNING_SECRET;
  await assert.rejects(app.verifyRequest(payload, headers), nc.Unauthenticated);
  process.env.NOCLICK_SIGNING_SECRET = "whsec_app";
  try {
    await app.verifyRequest(payload, headers);
    await assert.rejects(app.verifyRequest("{}", headers), nc.WebhookSignatureError);
  } finally {
    delete process.env.NOCLICK_SIGNING_SECRET;
  }
});

test("project settings read back; email broadcasts are named", async () => {
  const { api } = setup();
  const put = api.on("PUT", "/v1/projects/prj_1/settings/PUBLIC_BASE_URL", new Response(null, { status: 204 }));
  api.on("GET", "/v1/projects/prj_1/settings", json(listing([{ name: "PUBLIC_BASE_URL", value: "https://book.acme.com" }])));
  const app = nc.Project.fromId("prj_1");
  await app.settings.set("PUBLIC_BASE_URL", "https://book.acme.com");
  assert.deepEqual(put.last.body, { value: "https://book.acme.com" });
  assert.deepEqual(await app.settings.list(), { PUBLIC_BASE_URL: "https://book.acme.com" });

  const enable = api.on("POST", "/v1/projects/prj_1/email", json({ status: "active", postal_address: "1 Ferry Bldg", broadcast_daily_limit: 50000 }));
  const setupEmail = await app.email.enable({ postalAddress: "1 Ferry Bldg" });
  assert.deepEqual([enable.last.body, setupEmail.broadcastDailyLimit], [{ postal_address: "1 Ferry Bldg" }, 50000]);

  const send = api.on("POST", "/v1/projects/prj_1/email/broadcasts", json(operation({ id: "op_b", kind: "project.email.broadcast", status: "running" })));
  api.on("GET", "/v1/operations/op_b/wait", json(operation({
    id: "op_b", kind: "project.email.broadcast", status: "succeeded",
    result: { id: "bc_1", subject: "News", sent: 2, skipped: [{ to: "c@x.test", reason: "unsubscribed" }] },
  })));
  const result = await (await app.email.broadcast({ to: ["a@x.test", "b@x.test", "c@x.test"], subject: "News", html: "<p>Hi</p>", idempotencyKey: "news-2026-10" })).wait();
  assert.deepEqual(send.last.body, { to: ["a@x.test", "b@x.test", "c@x.test"], subject: "News", html: "<p>Hi</p>" });
  assert.equal(send.last.headers.get("Idempotency-Key"), "news-2026-10");
  assert.deepEqual([result.sent, result.skipped[0].reason], [2, "unsubscribed"]);

  const lift = api.on("POST", "/v1/projects/prj_1/email/resubscribe", json({ address: "ana@example.com", resubscribed: true }));
  assert.equal(await app.email.resubscribe("ana@example.com"), true);
  assert.deepEqual(lift.last.body, { address: "ana@example.com" });

  // The processor is the same for every app, so it's there before payments are enabled.
  api.on("GET", "/v1/projects/prj_1/payments", json({ mode: "off", secrets: [], processor: "acmepay" }));
  const payments = await app.payments.status();
  assert.deepEqual([payments.mode, payments.processor], ["off", "acmepay"]);
});

// --- domains, brand, cards -----------------------------------------------------

test("Domain.fromName buys once; default registrant; wildcard connect", async () => {
  const { api } = setup();
  api.on("GET", "/v1/domains", json(listing([])));
  const buy = api.on("POST", "/v1/domains", json({ ...operation({ id: "op_d", kind: "domain.buy", status: "running" }), domain_id: "dom_1" }));
  api.on("GET", "/v1/domains/dom_1", json({ ...DOMAIN, status: "registering" }));
  const domain = await nc.Domain.fromName("acmebooking.com", { createIfMissing: true, maxPriceUsd: 15 }).hydrate();
  assert.equal(domain.status, "registering");
  assert.deepEqual(buy.last.body, { name: "acmebooking.com", max_price_usd: 15 }); // the TLD's minimum term
  assert.throws(() => nc.Domain.fromName("acmebooking.com", { createIfMissing: true }), /maxPriceUsd/);

  api.on("GET", "/v1/domains", json(listing([DOMAIN])));
  const patch = api.on("PATCH", "/v1/domains/dom_1", json({ ...DOMAIN, auto_renew: false }));
  await nc.Domain.fromName("acmebooking.com", { createIfMissing: true, maxPriceUsd: 15, autoRenew: false }).hydrate();
  assert.deepEqual(patch.last.body, { auto_renew: false });

  const put = api.on("PUT", "/v1/domains/registrant", json({ name: "Dana Reyes", email: "dana@acmebooking.test" }));
  const del = api.on("DELETE", "/v1/domains/registrant", new Response(null, { status: 204 }));
  assert.equal((await nc.Domain.setDefaultRegistrant(CONTACT))?.email, "dana@acmebooking.test");
  assert.equal((put.last.body as { postal_code: string }).postal_code, "94111");
  assert.equal(await nc.Domain.setDefaultRegistrant(null), null);
  assert.equal(del.count, 1);

  const connect = api.on("POST", "/v1/domains/connect", json({ ...DOMAIN, source: "connected", wildcard: true }));
  assert.equal((await nc.Domain.connect("apps.acme.test", { wildcard: true })).wildcard, true);
  assert.deepEqual(connect.last.body, { name: "apps.acme.test", wildcard: true });
});

test("Brand serves from your domain with your OAuth apps; single-use cards", async () => {
  const { api } = setup();
  api.on("GET", "/v1/secrets", json(listing([{ object: "secret", id: "sec_1", name: "google-oauth-app" }])));
  const put = api.on("PUT", "/v1/brand", json({ name: "Acme", domain: "connect.acme.com", oauth_apps: { google: "sec_1" } }));
  const brand = await nc.Brand.set({ name: "Acme", domain: "connect.acme.com", oauthApps: { google: "google-oauth-app" } });
  assert.deepEqual((put.last.body as { domain: string; oauth_apps: unknown }).oauth_apps, { google: "sec_1" });
  assert.deepEqual([brand.domain, brand.oauthApps], ["connect.acme.com", { google: "sec_1" }]);
  await nc.Brand.set({ name: "Acme" });
  assert.equal("domain" in (put.last.body as object), false);

  const row = { object: "card", id: "card_1", name: "Marketplace", status: "active", limit_usd: 500, interval: "month", single_use: true };
  const create = api.on("POST", "/v1/cards", json(row));
  const card = await nc.Card.create("Marketplace", { limitUsd: 500, singleUse: true });
  assert.deepEqual(create.last.body, { name: "Marketplace", limit_usd: 500, interval: "month", single_use: true });
  assert.equal(card.singleUse, true);
  api.on("GET", "/v1/cards", json(listing([row])));
  const patch = api.on("PATCH", "/v1/cards/card_1", json({ ...row, single_use: false }));
  await nc.Card.fromName("Marketplace", { createIfMissing: true, limitUsd: 500, singleUse: false }).hydrate();
  assert.deepEqual(patch.last.body, { single_use: false });
  await nc.Card.fromName("Marketplace", { createIfMissing: true, limitUsd: 500 }).hydrate();
  assert.equal(patch.count, 1);
});
