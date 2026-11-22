import assert from "node:assert/strict";
import { test } from "node:test";
import { inspect } from "node:util";

import * as nc from "../src/index.ts";
import { BASE, USER_ID, apiError, json, listing, operation, setup, trashed, userRow } from "./helpers.ts";
import type { Call } from "./helpers.ts";

// --- sessions ----------------------------------------------------------------

const SESSION = {
  object: "session", id: "ses_1", token: "nk_sess_secret123", user_id: USER_ID, scopes: ["agents", "humans"],
  expires_at: "2026-09-25T11:00:00Z",
};

test("user.session mints a token without a lookup and never prints it", async () => {
  const { api } = setup();
  const lookup = api.on("GET", `/v1/users/${USER_ID}`, json(userRow()));
  const mint = api.on("POST", `/v1/users/${USER_ID}/sessions`, json(SESSION));
  const session = await nc.User.fromId(USER_ID).session({ scopes: ["agents", "humans"], ttlS: 3600 });
  assert.equal(lookup.count, 0);
  assert.deepEqual(mint.last.body, { scopes: ["agents", "humans"], ttl_s: 3600 });
  assert.equal(mint.last.headers.get("NoClick-User"), null);
  assert.ok(session instanceof nc.Session);
  assert.deepEqual([session.id, session.token, session.userId, session.scopes], ["ses_1", "nk_sess_secret123", USER_ID, ["agents", "humans"]]);
  assert.equal(session.expiresAt?.toISOString(), "2026-09-25T11:00:00.000Z");
  assert.ok(!inspect(session).includes("nk_sess"));
  assert.equal(JSON.parse(JSON.stringify(session)).token, "nk_sess_secret123"); // serializing is deliberate

  await nc.User.fromId(USER_ID).session({ scopes: "inbox" });
  assert.deepEqual(mint.last.body, { scopes: ["inbox"] });
});

test("a createIfMissing user is made sure of once before minting", async () => {
  const { api } = setup();
  const lookup = api.on("GET", `/v1/users/${USER_ID}`, json(userRow({ email: "ana@example.com" })));
  const mint = api.on("POST", `/v1/users/${USER_ID}/sessions`, json(SESSION));
  const user = nc.User.fromId(USER_ID, { createIfMissing: true, email: "ana@example.com" });
  await user.session({ scopes: ["agents"] });
  await user.session({ scopes: ["agents"] });
  assert.equal(lookup.count, 1);
  assert.equal(mint.count, 2);
});

test("a session for an id with reserved URL characters goes to its encoded path", async () => {
  const { api } = setup();
  const mint = api.on("POST", "/v1/users/auth0%7C123/sessions", json({ ...SESSION, user_id: "auth0|123" }));
  const session = await nc.User.fromId("auth0|123").session({ scopes: ["agents"] });
  assert.equal(mint.count, 1);
  assert.equal(session.userId, "auth0|123");
});

test("a session client authenticates with the token", async () => {
  const { api } = setup();
  api.on("POST", `/v1/users/${USER_ID}/sessions`, json(SESSION));
  const session = await nc.User.fromId(USER_ID).session({ scopes: ["agents"] });
  const clients = [
    session.client({ fetch: api.fetch }),
    nc.NoClick.forSession(session, { fetch: api.fetch }),
    nc.NoClick.forSession(session.token, { baseUrl: BASE, fetch: api.fetch }),
    new nc.NoClick({ apiKey: session.token, baseUrl: BASE, fetch: api.fetch }),
  ];
  const agents = api.on("GET", "/v1/agents", json(listing([])));
  for (const client of clients) {
    assert.equal(client.baseUrl, BASE);
    await nc.Agent.list({ client });
    assert.equal(agents.last.headers.get("Authorization"), "Bearer nk_sess_secret123");
    assert.equal(agents.last.headers.get("NoClick-User"), null);
  }
  assert.throws(() => nc.NoClick.forSession("nk_live_abc"), /nk_sess_/);
});

// --- agents: listing --------------------------------------------------------

test("fromName never finds an expired agent: it gave its name up", async () => {
  const { api } = setup();
  const expired = { object: "agent", id: "agt_old", name: "helper", user_id: null, status: "expired" };
  api.on("GET", "/v1/agents", json(listing([expired])));
  const create = api.on("POST", "/v1/agents", json({ object: "agent", id: "agt_new", name: "helper", user_id: null, status: "idle" }));
  const helper = await nc.Agent.fromName("helper", { createIfMissing: true, instructions: "Help." }).hydrate();
  assert.equal(helper.id, "agt_new");
  assert.equal(create.count, 1);
  await assert.rejects(nc.Agent.fromName("helper").hydrate(), nc.NotFound);
});

test("a user's read of an account agent has no activity, and ttlS reads back", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/agt_s", json({
    object: "agent", id: "agt_s", name: "shared", user_id: null, ttl_s: 900, expires_at: "2026-09-25T10:15:00Z",
    status: null, last_active_at: null, running_turns: null, child_count: null,
  }));
  const agent = await nc.asUser(USER_ID, () => nc.Agent.get("agt_s"));
  assert.deepEqual([agent.status, agent.lastActiveAt, agent.runningTurns, agent.childCount], [null, null, null, null]);
  assert.equal(agent.ttlS, 900);
});

// --- agents: capability tools ------------------------------------------------

test("agents take search, fetch and code tools", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/agents", (call: Call) =>
    json({ object: "agent", id: "agt_1", name: "researcher", tools: (call.body as { tools: string[] }).tools }));
  const agent = await nc.Agent.create("researcher", { instructions: "Research.", tools: ["search", "fetch", "code", "gmail"] });
  assert.deepEqual((create.last.body as { tools: string[] }).tools, ["search", "fetch", "code", "gmail"]);
  assert.deepEqual(agent.tools, ["search", "fetch", "code", "gmail"]);
});

// --- channels ----------------------------------------------------------------

const CHANNEL = {
  object: "channel", id: "ch_1", name: "launch", mode: "mentions", status: "open", user_id: USER_ID,
  members: [{ id: "mem_1", type: "a2a", a2a_url: "https://remote.ai/a2a", name: "remote", a2a_header_names: ["Authorization"] }],
  created_at: "2026-09-25T10:00:00Z",
};

test("Channel.list filters, follows cursors and stops at limit", async () => {
  const { api } = setup();
  const route = api.on(
    "GET", "/v1/channels",
    json(listing([CHANNEL, { ...CHANNEL, id: "ch_2" }], "c2")),
    json(listing([{ ...CHANNEL, id: "ch_3" }, { ...CHANNEL, id: "ch_4" }], "c3")),
  );
  const channels = await nc.asUser("user_42", () => nc.Channel.list({ status: "open", limit: 3 }));
  assert.deepEqual(channels.map((c) => c.id), ["ch_1", "ch_2", "ch_3"]);
  assert.deepEqual(route.calls.map((c) => [c.query.get("status"), c.query.get("limit"), c.query.get("cursor")]), [
    ["open", "3", null], ["open", "1", "c2"], // only what's still needed
  ]);
  assert.equal(route.last.headers.get("NoClick-User"), "user_42");
  assert.deepEqual(channels[0].members[0].a2aHeaderNames, ["Authorization"]);
  assert.equal(channels[0].members[0].a2aUrl, "https://remote.ai/a2a");
});

test("Channel.list pages a limit over the server's page size", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/channels", (call) => {
    const size = Number(call.query.get("limit"));
    const start = Number(call.query.get("cursor") ?? 0);
    assert.ok(size <= 100, "the server refuses a larger page");
    const rows = Array.from({ length: size }, (_, i) => ({ ...CHANNEL, id: `ch_${start + i}` }));
    return json(listing(rows, String(start + size)));
  });
  const channels = await nc.Channel.list({ limit: 150 });
  assert.deepEqual(route.calls.map((c) => [c.query.get("limit"), c.query.get("cursor")]), [["100", null], ["50", "100"]]);
  assert.deepEqual(channels.map((c) => c.id), Array.from({ length: 150 }, (_, i) => `ch_${i}`));
});

test("Channel.list without a limit reads every page", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/channels", json(listing([CHANNEL], "c2")), json(listing([{ ...CHANNEL, id: "ch_2" }])));
  assert.deepEqual((await nc.Channel.list()).map((c) => c.id), ["ch_1", "ch_2"]);
  assert.equal(route.calls[0].query.get("limit"), null);
});

test("A2A members carry headers on the wire; views only name them", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/channels", json(CHANNEL));
  const add = api.on("POST", "/v1/channels/ch_1/members", json({ id: "mem_2", type: "a2a", a2a_url: "https://b.ai/a2a", a2a_header_names: ["X-Key"] }));
  const channel = await nc.Channel.create("launch", {
    members: [{ a2aUrl: "https://remote.ai/a2a", headers: { Authorization: "Bearer s3cret" }, name: "remote" }, { a2aUrl: "https://c.ai/a2a", headers: {} }],
  });
  assert.deepEqual((create.last.body as { members: unknown[] }).members, [
    { a2a_url: "https://remote.ai/a2a", a2a_headers: { Authorization: "Bearer s3cret" }, name: "remote" },
    { a2a_url: "https://c.ai/a2a" },
  ]);
  const member = await channel.add(new nc.A2AMember("https://b.ai/a2a", { headers: { "X-Key": "k" } }));
  assert.deepEqual(add.last.body, { a2a_url: "https://b.ai/a2a", a2a_headers: { "X-Key": "k" } });
  assert.deepEqual([member.id, member.type, member.a2aHeaderNames], ["mem_2", "a2a", ["X-Key"]]);
});

// --- inbox -------------------------------------------------------------------

const INBOX = { object: "inbox", id: "inb_1", address: "signup-7k2@in.noclick.app", agent_id: null, user_id: USER_ID, created_at: "2026-09-25T10:00:00Z" };

function mail(id: string, fields: Record<string, unknown> = {}) {
  return { object: "inbox_message", id, inbox_id: "inb_1", from: "noreply@github.com", subject: "Your code", received_at: "2026-09-25T10:00:00Z", ...fields };
}

test("Inbox create (with an agent), list, get and delete", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/inboxes", json({ ...INBOX, agent_id: "agt_1" }));
  const list = api.on("GET", "/v1/inboxes", json(listing([INBOX])));
  api.on("GET", "/v1/inboxes/inb_1", json(INBOX));
  const del = api.on("DELETE", "/v1/inboxes/inb_1", json(trashed("inbox", "inb_1", "signup")));

  const inbox = await nc.asUser("user_42", () => nc.Inbox.create({ localPart: "signup", agent: nc.Agent.fromId("agt_1") }));
  assert.equal(create.last.headers.get("NoClick-User"), "user_42");
  assert.deepEqual(create.last.body, { local_part: "signup", agent_id: "agt_1" });
  assert.deepEqual([inbox.address, inbox.agentId], ["signup-7k2@in.noclick.app", "agt_1"]);
  await nc.Inbox.create({ agent: "agt_2" });
  assert.deepEqual(create.last.body, { agent_id: "agt_2" });

  const [first] = await nc.Inbox.list({ limit: 5 });
  assert.equal(list.last.query.get("limit"), "5");
  assert.equal((await nc.Inbox.get("inb_1")).id, first.id);
  await inbox.delete();
  assert.equal(del.count, 1);
  assert.equal(del.last.headers.get("NoClick-User"), USER_ID);
});

test("inbox messages, the full view, and replies", async () => {
  const { api } = setup();
  const poll = api.on("GET", "/v1/inboxes/inb_1/messages", json(listing([mail("m1"), mail("m2", { text: "inline" })])));
  const full = api.on("GET", "/v1/inboxes/inb_1/messages/m1", json(mail("m1", { text: "Your code is 481516", html: "<p>Your code is 481516</p>", attachments: [{ filename: "a.pdf", text: "invoice" }] })));
  const reply = api.on("POST", "/v1/inboxes/inb_1/messages/m1/reply", json({ object: "inbox_reply", id: "r1", status: "sent", delivery_status: "delivered" }));

  const inbox = nc.Inbox.fromId("inb_1", { user: USER_ID });
  const [m1, m2] = await inbox.messages({ after: "m0", waitS: 10 });
  assert.deepEqual([poll.last.query.get("after"), poll.last.query.get("wait_s")], ["m0", "10"]);
  assert.deepEqual([m1.sender, m1.subject, m1.text, m2.text], ["noreply@github.com", "Your code", "", "inline"]);
  assert.equal(m1.receivedAt?.getUTCHours(), 10);
  await inbox.messages({ after: m2 });
  assert.equal(poll.last.query.get("after"), "m2");

  await m1.refresh();
  assert.equal(`${m1}`, "Your code is 481516");
  assert.deepEqual(m1.attachments, [{ filename: "a.pdf", text: "invoice" }]);
  assert.equal(m1.html, "<p>Your code is 481516</p>");
  const one = await inbox.message("m1");
  assert.equal(one.text, "Your code is 481516");
  assert.equal(full.count, 2);

  const sent = await m1.reply("Thanks!");
  assert.deepEqual(reply.last.body, { text: "Thanks!" });
  assert.deepEqual([sent.id, sent.status, sent.deliveryStatus], ["r1", "sent", "delivered"]);
  assert.equal(reply.last.headers.get("NoClick-User"), USER_ID);
});

test("a message's sender says where it comes from", async () => {
  const { api } = setup();
  api.on("GET", "/v1/inboxes/inb_1/messages", json(listing([
    mail("m1", { from_source: "header", envelope_from: "0100abc@send.mail.github.com", authenticated: true }),
    mail("m2", { from: "mallory@attacker.example", from_source: "envelope", envelope_from: "mallory@attacker.example", authenticated: false }),
  ])));
  const [aligned, forged] = await nc.Inbox.fromId("inb_1").messages();
  assert.deepEqual([aligned.sender, aligned.senderSource, aligned.envelopeSender, aligned.authenticated],
    ["noreply@github.com", "header", "0100abc@send.mail.github.com", true]);
  assert.deepEqual([forged.sender, forged.senderSource, forged.envelopeSender, forged.authenticated],
    ["mallory@attacker.example", "envelope", "mallory@attacker.example", false]);
});

test("inbox.stream long-polls and paces empty polls", async () => {
  const { api, sleeps } = setup();
  const poll = api.on("GET", "/v1/inboxes/inb_1/messages", json(listing([mail("m1")])), json(listing([])), json(listing([mail("m2")])));
  const seen: string[] = [];
  for await (const message of nc.Inbox.fromId("inb_1").stream({ waitS: 5 })) {
    seen.push(message.id);
    if (seen.length === 2) break;
  }
  assert.deepEqual(seen, ["m1", "m2"]);
  assert.deepEqual(poll.calls.map((c) => c.query.get("after")), [null, "m1", "m1"]);
  assert.equal(sleeps.length, 1);
});

test("inbox.waitFor resolves to the matching message, whatever the kind is called", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/inboxes/inb_1/wait_for", json(operation({ id: "op_w", kind: "inbox.message", status: "running" })));
  api.on("GET", "/v1/operations/op_w/wait", json(operation({
    id: "op_w", kind: "inbox.message", status: "succeeded", result: { message: { id: "m9", text: "Code: 1234" } },
  })));
  const reply = api.on("POST", "/v1/inboxes/inb_1/messages/m9/reply", json({ id: "r2" }));
  const op = await nc.Inbox.fromId("inb_1").waitFor({ sender: "noreply@github.com", subjectContains: "code", timeoutS: 300 });
  assert.deepEqual(start.last.body, { sender: "noreply@github.com", subject_contains: "code", timeout_s: 300 });
  const message = await op.wait();
  assert.ok(message instanceof nc.InboxMessage);
  assert.equal(message.text, "Code: 1234");
  await message.reply("got it"); // remembers the inbox it came from
  assert.equal(reply.count, 1);
});

test("an expired inbox wait throws Expired; Operation.fromId decodes the kind", async () => {
  const { api } = setup();
  api.on("POST", "/v1/inboxes/inb_1/wait_for", json(operation({ id: "op_w", kind: "inbox.wait_for", status: "running" })));
  api.on("GET", "/v1/operations/op_w/wait", json(operation({
    id: "op_w", kind: "inbox.wait_for", status: "expired", error: { type: "expired", message: "No matching message arrived in 300s." },
  })));
  await assert.rejects((await nc.Inbox.fromId("inb_1").waitFor({ subjectContains: "code" })).wait(), nc.Expired);

  api.on("GET", "/v1/operations/op_z/wait", json(operation({ id: "op_z", kind: "inbox.wait_for", status: "succeeded", result: { message: mail("m9", { text: "y" }) } })));
  const decoded = await nc.Operation.fromId("op_z").wait();
  assert.ok(decoded instanceof nc.InboxMessage);
  assert.equal(decoded.text, "y");
});

// --- phone numbers -----------------------------------------------------------

const NUMBER = {
  object: "phone_number", id: "pn_1", number: "+14155550123", agent_id: null, monthly_usd: 1.5, user_id: null,
  created_at: "2026-09-25T10:00:00Z",
};
const TRANSCRIPT = [
  { role: "assistant", text: "Hi, calling to confirm Friday.", at: 1.2 },
  { role: "user", text: "Yes, see you then.", at: 4 },
];
const CALL = {
  object: "phone_call", id: "call_1", phone_number_id: "pn_1", direction: "outbound", to: "+14155550100", from: "+14155550123",
  status: "completed", goal: "Confirm Friday.", agent_id: "agt_1", call_sid: "CA1", seconds: 42, error: null, transcript: TRANSCRIPT,
  created_at: "2026-09-25T10:00:00Z", ended_at: "2026-09-25T10:00:42Z",
};
/** What the call operation settles with at hang-up. */
const CALL_RESULT = { object: "phone_call", id: "call_1", status: "completed", to: "+14155550100", call_sid: "CA1", seconds: 42, cost_usd: 0.21, transcript: TRANSCRIPT };

const AVAILABLE = {
  number: "+14155550123", country: "US", type: "local", monthly_usd: 1.5, upfront_usd: 1.25, locality: "San Francisco",
  region: "CA", capabilities: ["voice", "SMS"], requirements: { needs: "none", items: [] }, texting: "registration",
};

test("phone numbers: search, buy, list, release", async () => {
  const { api } = setup();
  const search = api.on("GET", "/v1/phone_numbers/available", json(listing([AVAILABLE])));
  const buy = api.on("POST", "/v1/phone_numbers", json(NUMBER));
  api.on("GET", "/v1/phone_numbers", json(listing([NUMBER])));
  const release = api.on("DELETE", "/v1/phone_numbers/pn_1", json({ object: "phone_number", id: "pn_1", deleted: true }));

  const [pick] = await nc.PhoneNumber.available({ areaCode: 415, contains: "555", limit: 1 });
  assert.deepEqual([search.last.query.get("area_code"), search.last.query.get("contains"), search.last.query.get("limit")], ["415", "555", "1"]);
  assert.deepEqual([pick.number, pick.monthlyUsd, pick.upfrontUsd, pick.locality, pick.country, pick.type, pick.texting],
    ["+14155550123", 1.5, 1.25, "San Francisco", "US", "local", "registration"]);
  assert.deepEqual([pick.capabilities, pick.requirements.needs], [["voice", "SMS"], "none"]);

  // The pick's own one-time price is the ceiling for it, unless the call names another.
  const number = await nc.PhoneNumber.buy(pick, { maxMonthlyUsd: 5 });
  assert.deepEqual(buy.last.body, { number: "+14155550123", country: "US", type: "local", max_monthly_usd: 5, max_upfront_usd: 1.25 });
  assert.deepEqual([number.number, `${number}`, number.monthlyUsd], ["+14155550123", "+14155550123", 1.5]);
  await nc.PhoneNumber.buy("+14155550999", { maxMonthlyUsd: 2 });
  assert.deepEqual(buy.last.body, { number: "+14155550999", max_monthly_usd: 2 });

  assert.deepEqual((await nc.PhoneNumber.list()).map((n) => n.id), ["pn_1"]);
  await number.release();
  assert.equal(release.count, 1);
  assert.equal(number.released, true);
  assert.equal(number.number, "+14155550123");
});

test("a holder profile is filed once and a purchase files it", async () => {
  const { api } = setup();
  const holder = { name: "Dana Ruiz", street: "Keizersgracht 1", city: "Amsterdam", postal_code: "1015 CJ", country: "NL", phone: "+31612345670" };
  const profile = { object: "phone_number_holder", user_id: "user_42", holder, requirements: { req_type: "Passport" },
    accepted_at: "2026-11-20T09:30:00+00:00", updated_at: "2026-11-20T09:31:00+00:00" };
  const put = api.on("PUT", "/v1/phone_numbers/holder", json(profile));
  const get = api.on("GET", "/v1/phone_numbers/holder", json(profile));
  const del = api.on("DELETE", "/v1/phone_numbers/holder", json(undefined, { status: 204 }));
  const buy = api.on("POST", "/v1/phone_numbers", json(NUMBER));
  const dana = { name: "Dana Ruiz", street: "Keizersgracht 1", city: "Amsterdam", postalCode: "1015 CJ", country: "NL", phone: "+31612345670" };
  const filed = await nc.PhoneNumber.setHolderProfile(dana, { acceptedAt: "2026-11-20T09:30:00Z", requirements: { req_type: "Passport" }, user: "user_42" });
  assert.deepEqual(put.last.body, { holder, requirements: { req_type: "Passport" }, accepted_at: "2026-11-20T09:30:00Z" });
  assert.equal(put.last.headers.get("NoClick-User"), "user_42");
  assert.deepEqual([filed?.holder.postalCode, filed?.userId], ["1015 CJ", "user_42"]);
  assert.equal((await nc.PhoneNumber.holderProfile({ user: "user_42" }))?.acceptedAt?.getUTCFullYear(), 2026);
  assert.equal(get.last.headers.get("NoClick-User"), "user_42");
  await assert.rejects(nc.PhoneNumber.setHolderProfile(dana), /acceptedAt/);
  await nc.PhoneNumber.buy("+31612345678", { country: "NL", type: "mobile", maxMonthlyUsd: 3, holderOnFile: true });
  assert.deepEqual(buy.last.body, { number: "+31612345678", country: "NL", type: "mobile", max_monthly_usd: 3, holder_on_file: true });
  assert.equal(await nc.PhoneNumber.setHolderProfile(null), null);
  assert.equal(del.count, 1);
});

test("phone numbers abroad: filters, coverage, places, and an address where the country asks", async () => {
  const { api } = setup();
  const search = api.on("GET", "/v1/phone_numbers/available", json(listing([{
    ...AVAILABLE, number: "+31612345678", country: "NL", type: "mobile", monthly_usd: 2.5, upfront_usd: 2.5, locality: null,
    region: null, texting: "unavailable", requirements: { needs: "address", items: [{ kind: "address", name: "Address anywhere", description: "" }] },
  }])));
  const coverage = api.on("GET", "/v1/phone_numbers/coverage", json(listing([
    { object: "phone_number_coverage", country: "NL", types: ["mobile"], texting_types: [], documents_types: [] },
    { object: "phone_number_coverage", country: "IN", types: ["local", "mobile"], texting_types: [], documents_types: ["local"], steps_types: ["mobile"] },
  ])));
  const places = api.on("GET", "/v1/phone_numbers/places", json(listing([{ object: "phone_number_place", kind: "locality", value: "Amsterdam", region: "" }])));
  const buy = api.on("POST", "/v1/phone_numbers", json(NUMBER));

  assert.deepEqual(await nc.PhoneNumber.coverage(), [
    { country: "NL", types: ["mobile"], textingTypes: [], documentsTypes: [], stepsTypes: [] },
    { country: "IN", types: ["local", "mobile"], textingTypes: [], documentsTypes: ["local"], stepsTypes: ["mobile"] },
  ]);
  assert.equal(coverage.count, 1);
  assert.deepEqual(await nc.PhoneNumber.places("NL", { type: "mobile" }), [{ kind: "locality", value: "Amsterdam", region: "" }]);
  assert.deepEqual([places.last.query.get("country"), places.last.query.get("type")], ["NL", "mobile"]);
  const [pick] = await nc.PhoneNumber.available({
    country: "NL", type: "mobile", locality: "Amsterdam", region: "NH", startsWith: "6", endsWith: "78", features: "voice_sms",
  });
  assert.deepEqual(["country", "type", "locality", "region", "starts_with", "ends_with", "features"].map((k) => search.last.query.get(k)),
    ["NL", "mobile", "Amsterdam", "NH", "6", "78", "voice_sms"]);
  assert.equal(pick.requirements.needs, "address");
  await nc.PhoneNumber.buy(pick, {
    maxMonthlyUsd: 3, maxUpfrontUsd: 3,
    address: { name: "Dana Ruiz", street: "Keizersgracht 1", city: "Amsterdam", postalCode: "1015 CJ", country: "NL", phone: "+31612345670" },
  });
  assert.deepEqual(buy.last.body, {
    number: "+31612345678", country: "NL", type: "mobile", max_monthly_usd: 3, max_upfront_usd: 3,
    address: { name: "Dana Ruiz", street: "Keizersgracht 1", city: "Amsterdam", postal_code: "1015 CJ", country: "NL", phone: "+31612345670" },
  });
});

const IDENTITY_TYPE = {
  id: "req_type", kind: "textual", name: "Identity Document Type", description: "", example: "Passport",
  values: ["Identity card", "Driving license", "Passport", "Other"],
};
const IDENTITY = { id: "req_doc", kind: "document", name: "Identity Document", description: "", example: "", values: [] };
const DOCUMENT = {
  object: "phone_number_document", id: "doc_1", requirement_id: "req_doc", requirement_name: "Identity Document",
  filename: "passport.pdf", uploaded_at: "2026-10-10T12:00:00Z",
};
const ORDER = {
  object: "phone_number_order", id: "ord_1", number: "+390212345678", country: "IT", type: "local", status: "in_review",
  reason: null, deadline: null, monthly_usd: 1, upfront_usd: 1, phone_number_id: null,
  requirements: { needs: "documents", items: [IDENTITY_TYPE, IDENTITY] }, created_at: "2026-10-10T12:00:00Z",
  updated_at: "2026-10-10T12:00:00Z",
};

test("a number with documents is ordered, corrected, and becomes the number once the carrier completes it", async () => {
  const { api } = setup();
  const upload = api.on("POST", "/v1/phone_numbers/documents", json(DOCUMENT));
  const buy = api.on("POST", "/v1/phone_numbers", json(ORDER));
  const pdf = new TextEncoder().encode("%PDF-1.4 passport");

  const passport = await nc.PhoneNumber.uploadDocument(pdf, { requirement: IDENTITY as nc.NumberRequirement, country: "IT", filename: "passport.pdf" });
  assert.deepEqual(upload.last.body, {
    country: "IT", type: "local", requirement_id: "req_doc", filename: "passport.pdf", file: Buffer.from(pdf).toString("base64"),
  });
  assert.deepEqual([passport.id, passport.requirementName, passport.uploadedAt?.toISOString()], ["doc_1", "Identity Document", "2026-10-10T12:00:00.000Z"]);
  await nc.PhoneNumber.uploadDocument(new Blob([pdf]), { requirement: "req_doc", country: "IT", type: "mobile", filename: "scan.pdf" });
  const scan = upload.last.body as Record<string, unknown>;
  assert.deepEqual([scan.type, scan.filename], ["mobile", "scan.pdf"]);

  const address = { name: "Giulia Rossi", street: "Via Roma 1", city: "Milano", postalCode: "20121", country: "IT", phone: "+393471234567" };
  const order = await nc.PhoneNumber.buy("+390212345678", {
    country: "IT", maxMonthlyUsd: 5, maxUpfrontUsd: 5, address, requirements: { req_type: "Passport", req_doc: passport },
  });
  assert.deepEqual((buy.last.body as Record<string, unknown>).requirements, { req_type: "Passport", req_doc: "doc_1" });
  assert.ok(order instanceof nc.PhoneNumberOrder);
  assert.deepEqual([order.id, order.status, order.number, order.phoneNumberId], ["ord_1", "in_review", "+390212345678", null]);
  await assert.rejects(order.phoneNumber(), nc.Conflict); // not yours until it completes

  // The carrier sends it back; corrections are resubmitted on the same order.
  api.on("GET", "/v1/phone_numbers/orders/ord_1", json({ ...ORDER, status: "rejected", reason: "Upload the photo page.", deadline: "2026-10-24T00:00:00Z" }));
  await order.refresh();
  assert.deepEqual([order.status, order.reason, order.deadline?.toISOString()], ["rejected", "Upload the photo page.", "2026-10-24T00:00:00.000Z"]);
  const resubmit = api.on("POST", "/v1/phone_numbers/orders/ord_1/resubmit", json(ORDER));
  await order.resubmit({ address, requirements: { req_type: "Passport", req_doc: "doc_2" } });
  assert.deepEqual(resubmit.last.body, {
    address: { name: "Giulia Rossi", street: "Via Roma 1", city: "Milano", postal_code: "20121", country: "IT", phone: "+393471234567" },
    requirements: { req_type: "Passport", req_doc: "doc_2" },
  });
  assert.equal(order.status, "in_review");

  // Once it completes, it's the number.
  api.on("GET", "/v1/phone_numbers/orders/ord_1", json({ ...ORDER, status: "completed", requirements: null, phone_number_id: "pn_1" }));
  api.on("GET", "/v1/phone_numbers/pn_1", json(NUMBER));
  const completed = await nc.PhoneNumberOrder.retrieve("ord_1");
  const number = await completed.phoneNumber();
  assert.ok(number instanceof nc.PhoneNumber);
  assert.equal(number.id, "pn_1");
});

test("phone errors: price ceiling and the feature gate", async () => {
  const { api } = setup();
  api.on("POST", "/v1/phone_numbers", apiError(402, "price_exceeded", "This number costs $8.00/month.", { monthly_usd: 8 }));
  api.on("GET", "/v1/phone_numbers/available", apiError(409, "not_available", "Phone numbers aren't enabled for this account."));
  await assert.rejects(nc.PhoneNumber.buy("+14155550123", { maxMonthlyUsd: 5 }), (err: nc.PriceExceeded) => {
    assert.ok(err instanceof nc.PriceExceeded);
    assert.equal(err.details.monthly_usd, 8);
    return true;
  });
  await assert.rejects(nc.PhoneNumber.available(), nc.NotAvailable);
});

test("answerWith, call (connected or not) and calls", async () => {
  const { api } = setup();
  api.on("GET", "/v1/phone_numbers/pn_1", json(NUMBER));
  const answer = api.on("POST", "/v1/phone_numbers/pn_1/answer", json({ ...NUMBER, agent_id: "agt_1" }));
  const place = api.on("POST", "/v1/phone_numbers/pn_1/calls",
    json(operation({ id: "op_c", kind: "phone.call", status: "running" })),
    json(operation({ id: "op_d", kind: "phone.call", status: "running" })));
  api.on("GET", "/v1/operations/op_c/wait", json(operation({ id: "op_c", kind: "phone.call", status: "succeeded", result: CALL_RESULT })));
  api.on("GET", "/v1/operations/op_d/wait", json(operation({
    id: "op_d", kind: "phone.call", status: "succeeded", result: { ...CALL_RESULT, status: "not_connected", seconds: 0, transcript: [] },
  })));
  const history = api.on("GET", "/v1/phone_numbers/pn_1/calls", json(listing([CALL, { ...CALL, id: "call_2", direction: "inbound" }])));

  const number = await nc.PhoneNumber.get("pn_1");
  assert.equal(await number.answerWith(nc.Agent.fromId("agt_1")), number);
  assert.deepEqual(answer.last.body, { agent_id: "agt_1" });
  assert.equal(number.agentId, "agt_1");

  const call = await (await number.call("+14155550100", { goal: "Confirm Friday." })).wait();
  assert.deepEqual(place.last.body, { to: "+14155550100", goal: "Confirm Friday." });
  assert.deepEqual([call.id, call.status, call.seconds, call.costUsd], ["call_1", "completed", 42, 0.21]);
  assert.deepEqual(call.transcript, TRANSCRIPT);
  assert.equal(call.text, "assistant: Hi, calling to confirm Friday.\nuser: Yes, see you then.");

  const other = await (await number.call("+14155550101", { goal: "Ask about the order.", agent: "agt_2" })).wait();
  assert.deepEqual(place.last.body, { to: "+14155550101", goal: "Ask about the order.", agent_id: "agt_2" });
  assert.deepEqual([other.status, other.transcript, other.text], ["not_connected", [], ""]);

  const listed = await number.calls();
  assert.deepEqual(listed.map((c) => c.direction), ["outbound", "inbound"]);
  assert.deepEqual([listed[0].fromNumber, listed[0].endedAt?.getUTCSeconds()], ["+14155550123", 42]);
  assert.equal(history.count, 1);
});

test("a call is read live and hung up, by its id or the operation that placed it", async () => {
  const { api } = setup();
  const live = {
    ...CALL, status: "calling", transcript: [], seconds: null, ended_at: null, answered_at: "2026-09-25T10:00:09Z", ended_by: null,
    lines: [{ turn: 1, who: "them", text: "Hello?" }, { turn: 1, who: "agent", text: "Hi, it's Ada." }],
  };
  api.on("POST", "/v1/phone_numbers/pn_1/calls", json(operation({ id: "op_c", kind: "phone.call", status: "running", call_id: "call_1", phone_number_id: "pn_1" })));
  const read = api.on("GET", "/v1/phone_numbers/calls/call_1", json(live), json({ ...live, status: "completed", ended_by: "hang_up", transcript: TRANSCRIPT }));
  const hangUp = api.on("POST", "/v1/phone_numbers/calls/call_1/hang_up", json(live), json(live));

  const op = await nc.PhoneNumber.fromId("pn_1", { user: USER_ID }).call("+14155550100", { goal: "Confirm Friday." });
  const call = await nc.PhoneNumber.getCall(op);
  assert.deepEqual([call.status, call.answeredAt?.getUTCSeconds(), call.endedBy], ["calling", 9, null]);
  assert.deepEqual(call.lines, [{ turn: 1, who: "them", text: "Hello?" }, { turn: 1, who: "agent", text: "Hi, it's Ada." }]);
  // The operation's user goes with it, as the call it placed did.
  assert.equal(read.last.headers.get("NoClick-User"), USER_ID);

  assert.equal((await nc.PhoneNumber.hangUp(op)).status, "calling"); // it ends a moment later, as any end does
  await nc.PhoneNumber.hangUp("call_1", { user: null });
  assert.equal(hangUp.last.headers.get("NoClick-User"), null);
  assert.equal(hangUp.count, 2);

  assert.equal((await nc.PhoneNumber.getCall("call_1")).endedBy, "hang_up");
  api.on("GET", "/v1/operations/op_h", json(operation({ id: "op_h" })));
  await assert.rejects(nc.PhoneNumber.getCall(nc.Operation.fromId("op_h")), TypeError); // an operation that isn't a call
});

test("hanging up a call that ended is a Conflict", async () => {
  const { api } = setup();
  api.on("POST", "/v1/phone_numbers/calls/call_1/hang_up", apiError(409, "conflict", "The call already ended (completed).", { call_status: "completed" }));
  await assert.rejects(nc.PhoneNumber.hangUp("call_1"), nc.Conflict);
});

// --- sandbox background exec -------------------------------------------------

test("background exec returns an operation resolving to the ExecResult", async () => {
  const { api } = setup();
  const exec = api.on("POST", "/v1/sandboxes/sbx_1/exec", json(operation({ id: "op_x", kind: "exec", status: "running" })));
  api.on("GET", "/v1/operations/op_x/wait", json(operation({
    id: "op_x", kind: "exec", status: "succeeded", result: { stdout: "built\n", stderr: "", exit_code: 0 },
  })));
  const sandbox = nc.Sandbox.fromId("sbx_1", { user: USER_ID });
  const op = await sandbox.exec("make all", { background: true, timeoutS: 1800 });
  assert.ok(op instanceof nc.Operation);
  assert.deepEqual(exec.last.body, { command: "make all", background: true, timeout_s: 1800 });
  assert.equal(exec.last.headers.get("NoClick-User"), USER_ID);
  const result = await op.wait();
  assert.deepEqual([result.stdout, result.exitCode], ["built\n", 0]);

  api.on("GET", "/v1/operations/op_y/wait", json(operation({ id: "op_y", kind: "sandbox.exec", status: "succeeded", result: { stdout: "", stderr: "fail", exit_code: 1 } })));
  const failed = await nc.Operation.fromId<nc.ExecResult>("op_y").wait();
  assert.deepEqual([failed.exitCode, failed.stderr], [1, "fail"]); // a non-zero exit is still a result
});

// --- agents built in the app -------------------------------------------------

test("an agent built in the app is listed and messaged like any other", async () => {
  const { api } = setup();
  const triage = {
    object: "agent", id: "node:wf_9:triage", origin: "app", name: "Triage", harness: "sdk", model: "openai/gpt-5",
    workflow_id: "wf_9", node_id: "triage", workflow_name: "Support desk", access: "owner", enabled: true,
    app_url: "https://noclick.com/dashboard?tab=workflows&workflow=wf_9", created_at: "2026-09-25T10:00:00Z",
  };
  const agents = api.on("GET", "/v1/agents", json(listing([triage])));
  const send = api.on("POST", "/v1/agents/node:wf_9:triage/messages",
    json(operation({ id: "op_w", kind: "workflow.agent_message", status: "running" })));
  api.on("GET", "/v1/operations/op_w/wait", json(operation({
    id: "op_w", kind: "workflow.agent_message", status: "succeeded", result: { text: "Two tickets are urgent.", conversation: "c_1" },
  })));
  const [agent] = await nc.Agent.list({ origin: "app" });
  assert.equal(agents.last.query.get("origin"), "app");
  assert.deepEqual([agent.origin, agent.workflowName, agent.nodeId, agent.access, agent.enabled, agent.appUrl],
    ["app", "Support desk", "triage", "owner", true, "https://noclick.com/dashboard?tab=workflows&workflow=wf_9"]);
  const reply = await agent.message("Anything urgent?");
  assert.deepEqual(send.last.body, { text: "Anything urgent?" });
  assert.deepEqual([reply.text, reply.conversation], ["Two tickets are urgent.", "c_1"]);
  await assert.rejects(nc.Agent.list({ origin: "workflow" as nc.AgentOrigin }), TypeError);
});
