import assert from "node:assert/strict";
import { test } from "node:test";
import { inspect } from "node:util";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, operation, setup } from "./helpers.ts";

const DOMAIN_ID = "5c8e2a1f-7b3d-4e96-a0c4-9d1f6b2e8a57";
const BOOKING = {
  object: "domain", id: DOMAIN_ID, name: "acmebooking.com", source: "bought", status: "active",
  expires_at: "2027-09-01T00:00:00Z", renewable_until: "2027-09-26T00:00:00Z", auto_renew: true, renewal_usd: 12.5,
  renewal_years: 1, setup_url: null,
  records: [{ type: "ALIAS", name: "@", value: "cname.noclick.site", status: "verified", purpose: "Serves booking", managed: true }],
  serves: [{ kind: "project", id: "prj_1", name: "booking" }],
  registrant_email: "dana@acmebooking.test", registrant_verify_by: null,
  registrant: {
    name: "Dana Reyes", email: "dana@acmebooking.test", phone: "+14155550188", address: "1 Ferry Building",
    city: "San Francisco", region: "CA", postal_code: "94111", country: "US", organization: "Acme Booking",
    agreement_accepted_at: "2026-09-01T08:00:00Z",
  },
  transfer_locked_until: "2026-10-31T00:00:00Z", user_id: null, created_at: "2026-09-01T00:00:00Z",
};
const ACME = {
  object: "domain", id: "dom_2", name: "acme.test", source: "connected", status: "pending_dns",
  expires_at: null, auto_renew: null, setup_url: "https://dns.example/connect?template=noclick",
  records: [
    { type: "CNAME", name: "www", value: "cname.noclick.site", status: "verified", purpose: "Primary address" },
    { type: "ALIAS", name: "@", value: "cname.noclick.site", status: "pending", required: false },
  ],
  serves: [], user_id: USER_ID, created_at: "2026-09-25T10:00:00Z",
};

test("Domain.search reads offers", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/domains/search", json(listing([
    { name: "acmebooking.com", available: true, price_usd: 11.25, renewal_usd: 12.5, premium: false, min_years: 1, max_years: 10, claims_notice: null },
    { name: "book.app", available: true, price_usd: 2400, renewal_usd: 30, premium: true },
    {
      name: "acmebooking.ai", available: true, price_usd: 160, renewal_usd: 160, premium: false, min_years: 2, max_years: 10,
      claims_notice: "**Trademark notice**: acmebooking matches a mark.",
    },
  ])));
  const offers = await nc.Domain.search("acmebooking", { tlds: ["com", "app", "ai"], limit: 3 });
  assert.deepEqual([route.last.query.get("q"), route.last.query.get("tlds"), route.last.query.get("limit")], ["acmebooking", "com,app,ai", "3"]);
  assert.deepEqual(offers.map((o) => [o.name, o.available, o.priceUsd, o.renewalUsd, o.premium, o.minYears, o.maxYears]), [
    ["acmebooking.com", true, 11.25, 12.5, false, 1, 10],
    ["book.app", true, 2400, 30, true, null, null],
    ["acmebooking.ai", true, 160, 160, false, 2, 10], // what buying charges now, for two years
  ]);
  assert.deepEqual(offers.map((o) => o.claimsNotice), [null, null, "**Trademark notice**: acmebooking matches a mark."]);
});

test("Domain.buy charges with a registrant and resolves to the domain", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/domains", json(operation({ id: "op_b", kind: "domain.buy", status: "running", domain_id: DOMAIN_ID, price_usd: 11.25 })));
  api.on("GET", "/v1/operations/op_b/wait", json(operation({ id: "op_b", kind: "domain.buy", status: "succeeded", result: { domain: BOOKING } })));
  const offer: nc.DomainOffer = {
    name: "acmebooking.com", available: true, priceUsd: 11.25, renewalUsd: 12.5, premium: false, minYears: 1, maxYears: 10,
    claimsNotice: null, raw: {},
  };
  const purchase = await nc.Domain.buy(offer, {
    maxPriceUsd: 15,
    years: 2,
    registrant: {
      name: "Ana Silva", email: "ana@example.com", phone: "+14155550123", address: "500 Market St",
      city: "San Francisco", region: "CA", postalCode: "94105", country: "US",
      agreementAcceptedAt: new Date("2026-10-02T09:30:00Z"),
    },
  });
  assert.deepEqual(start.last.body, {
    name: "acmebooking.com", max_price_usd: 15, years: 2, auto_renew: true,
    registrant: {
      name: "Ana Silva", email: "ana@example.com", phone: "+14155550123", address: "500 Market St",
      city: "San Francisco", postal_code: "94105", country: "US", region: "CA",
      agreement_accepted_at: "2026-10-02T09:30:00.000Z",
    },
  });
  assert.ok(purchase instanceof nc.DomainPurchase && purchase instanceof nc.Operation);
  assert.deepEqual([purchase.priceUsd, purchase.domainId, purchase.status], [11.25, DOMAIN_ID, "running"]);
  const domain = await purchase.wait();
  assert.ok(domain instanceof nc.Domain);
  assert.deepEqual([domain.name, domain.source, domain.renewalUsd, domain.autoRenew], ["acmebooking.com", "bought", 12.5, true]);
  assert.equal(domain.expiresAt?.getUTCFullYear(), 2027);
  assert.deepEqual(domain.serves, [{ kind: "project", id: "prj_1", name: "booking" }]);
  assert.deepEqual(domain.records.map((r) => [r.type, r.managed, r.required]), [["ALIAS", true, true]]);
  assert.deepEqual([domain.renewalYears, domain.renewableUntil?.getUTCDate()], [1, 26]);
  assert.deepEqual([domain.registrant?.name, domain.registrant?.region, domain.registrant?.organization], ["Dana Reyes", "CA", "Acme Booking"]);
  assert.equal(domain.registrant?.agreementAcceptedAt?.toISOString(), "2026-09-01T08:00:00.000Z");
});

const ANA: nc.DomainContact = {
  name: "Ana Silva", email: "ana@example.com", phone: "+14155550123", address: "500 Market St",
  city: "San Francisco", region: "CA", postalCode: "94105", country: "US", agreementAcceptedAt: new Date("2026-10-02T09:30:00Z"),
};
const ANA_WIRE = {
  name: "Ana Silva", email: "ana@example.com", phone: "+14155550123", address: "500 Market St",
  city: "San Francisco", postal_code: "94105", country: "US", region: "CA", agreement_accepted_at: "2026-10-02T09:30:00.000Z",
};

test("years are sent only when given, and claims only when accepted", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/domains", json(operation({ id: "op_b", kind: "domain.buy", status: "running", domain_id: DOMAIN_ID, price_usd: 160 })));
  await nc.Domain.buy("acmebooking.ai", { maxPriceUsd: 200, registrant: ANA }); // the TLD's minimum term
  assert.deepEqual(start.last.body, { name: "acmebooking.ai", max_price_usd: 200, auto_renew: true, registrant: ANA_WIRE });
  await nc.Domain.buy("acmebooking.ai", { maxPriceUsd: 400, years: 4, registrant: ANA, acceptClaims: true });
  assert.deepEqual(start.last.body, {
    name: "acmebooking.ai", max_price_usd: 400, years: 4, auto_renew: true, registrant: ANA_WIRE, accept_claims: true,
  });

  api.on("GET", "/v1/domains", json(listing([])));
  api.on("GET", `/v1/domains/${DOMAIN_ID}`, json({ ...BOOKING, name: "acmebooking.co", status: "registering" }));
  await nc.Domain.fromName("acmebooking.co", { createIfMissing: true, maxPriceUsd: 200, years: 5 }).hydrate();
  assert.deepEqual(start.last.body, { name: "acmebooking.co", max_price_usd: 200, years: 5 });
});

test("a claim, a term and a missing agreement are refused", async () => {
  const { api } = setup();
  api.on("POST", "/v1/domains", apiError(409, "action_required", "acmebooking.ai matches a registered trademark.", {
    claims_notice: "**Trademark notice**: acmebooking matches a mark.",
  }));
  await assert.rejects(nc.Domain.buy("acmebooking.ai", { maxPriceUsd: 200, registrant: ANA }), (err: unknown) =>
    err instanceof nc.ActionRequired && String(err.details.claims_notice).startsWith("**Trademark notice**"));

  api.on("POST", "/v1/domains", apiError(400, "invalid_request", ".co registers for 1 to 5 years.", { field: "years" }));
  await assert.rejects(nc.Domain.buy("acmebooking.co", { maxPriceUsd: 200, years: 10, registrant: ANA }), (err: unknown) =>
    err instanceof nc.InvalidRequest && err.details.field === "years");

  api.on("POST", "/v1/domains", apiError(400, "invalid_request", "The registrant hasn't accepted the registration agreement.", {
    field: "registrant.agreement_accepted_at",
  }));
  const unaccepted = { ...ANA, agreementAcceptedAt: undefined };
  await assert.rejects(nc.Domain.buy("anasilva.dev", { maxPriceUsd: 20, registrant: unaccepted }), (err: unknown) =>
    err instanceof nc.InvalidRequest && err.details.field === "registrant.agreement_accepted_at");
});

test("a user's registrant profile is set, read and cleared for that user; the account's otherwise", async () => {
  const { api } = setup();
  const wire = { name: "Ana Silva", email: "ana@example.com", phone: "+14155550123", address: "500 Market St",
    city: "San Francisco", region: "CA", postal_code: "94105", country: "US", agreement_accepted_at: "2026-11-20T09:30:00Z" };
  const put = api.on("PUT", "/v1/domains/registrant", json(wire));
  const get = api.on("GET", "/v1/domains/registrant", json(wire));
  const del = api.on("DELETE", "/v1/domains/registrant", json(undefined, { status: 204 }));
  const saved = await nc.Domain.setDefaultRegistrant(ANA, { user: "user_42" });
  assert.equal(put.last.headers.get("NoClick-User"), "user_42");
  assert.equal(saved?.name, "Ana Silva");
  assert.equal((await nc.Domain.defaultRegistrant({ user: "user_42" }))?.email, "ana@example.com");
  assert.equal(get.last.headers.get("NoClick-User"), "user_42");
  await nc.asUser("user_42", () => nc.Domain.defaultRegistrant());
  assert.equal(get.last.headers.get("NoClick-User"), null); // the account's, whoever asks, unless user is named
  assert.equal(await nc.Domain.setDefaultRegistrant(null, { user: "user_42" }), null);
  assert.equal(del.last.headers.get("NoClick-User"), "user_42");
});

test("Domain.agreement is the account's", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/domains/agreement", json({ object: "domain_agreement", url: "https://agreements.example/domains", version: "2026-10-02" }));
  const agreement = await nc.asUser("user_42", () => nc.Domain.agreement());
  assert.equal(route.last.headers.get("NoClick-User"), null); // account level, whoever asks
  assert.deepEqual([agreement.url, agreement.version, agreement.raw.object], ["https://agreements.example/domains", "2026-10-02", "domain_agreement"]);
});

test("a user's domain is registered to them and charged to the account", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/domains", json(operation({ id: "op_u", kind: "domain.buy", status: "running", domain_id: DOMAIN_ID, price_usd: 14 })));
  // Naming none, the user's registrant profile on file is what it's registered to: NoClick reads it (and refuses,
  // naming registrant, where there's none).
  await nc.asUser("user_42", () => nc.Domain.buy("anasilva.dev", { maxPriceUsd: 20 }));
  assert.equal((start.last.body as { registrant?: unknown }).registrant, undefined);
  assert.equal(start.last.headers.get("NoClick-User"), "user_42");

  const purchase = await nc.Domain.buy("anasilva.dev", { maxPriceUsd: 20, registrant: ANA, user: "user_42" });
  assert.equal((start.last.body as { registrant: { email: string } }).registrant.email, "ana@example.com");
  assert.equal(start.last.headers.get("NoClick-User"), "user_42");
  assert.deepEqual([purchase.status, purchase.priceUsd], ["running", 14]);
});

test("a purchase your policy holds waits for approval", async () => {
  const { api } = setup();
  api.on("POST", "/v1/domains", json(operation({ id: "op_p", kind: "domain.buy", status: "awaiting_human", domain_id: DOMAIN_ID })));
  api.on("GET", `/v1/domains/${DOMAIN_ID}`, json({ ...BOOKING, name: "anasilva.dev", status: "awaiting_human" }));
  const purchase = await nc.Domain.buy("anasilva.dev", { maxPriceUsd: 20, registrant: ANA });
  assert.equal(purchase.status, "awaiting_human");
  assert.equal((await purchase.domain.hydrate()).status, "awaiting_human");

  api.on("GET", "/v1/operations/op_p", json(operation({ id: "op_p", kind: "domain.buy", status: "awaiting_human", price_usd: 19 })));
  api.on("GET", "/v1/operations/op_p/wait", json(operation({ id: "op_p", kind: "domain.buy", status: "succeeded", result: { domain: BOOKING } })));
  const resumed = await nc.DomainPurchase.purchaseFromId("op_p").hydrate();
  assert.deepEqual([resumed.status, resumed.priceUsd], ["awaiting_human", 19]);
  assert.ok((await nc.Operation.fromId("op_p").wait()) instanceof nc.Domain);
});

test("a purchase above the ceiling throws PriceExceeded", async () => {
  const { api } = setup();
  api.on("POST", "/v1/domains", apiError(402, "price_exceeded", "book.app costs $2,400.00, more than max_price_usd."));
  await assert.rejects(nc.Domain.buy("book.app", { maxPriceUsd: 15 }), nc.PriceExceeded);
});

test("Domain.connect lists the records to add", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/domains/connect", json(ACME));
  const domain = await nc.Domain.connect("acme.test", { user: "acme" });
  assert.deepEqual(route.last.body, { name: "acme.test" });
  assert.equal(route.last.headers.get("NoClick-User"), "acme");
  assert.deepEqual([domain.status, domain.source, domain.setupUrl, domain.autoRenew, domain.expiresAt], [
    "pending_dns", "connected", "https://dns.example/connect?template=noclick", null, null,
  ]);
  const [www, apex] = domain.records;
  assert.deepEqual([www.type, www.name, www.status, www.purpose, www.required, www.managed], ["CNAME", "www", "verified", "Primary address", true, false]);
  assert.deepEqual([apex.required, apex.status], [false, "pending"]);
  assert.equal(String(domain), "acme.test");
});

test("Domain.fromName looks the domain up once and acts by id", async () => {
  const { api } = setup();
  const lookup = api.on("GET", "/v1/domains", json(listing([{ ...ACME, name: "acme.test.example" }, ACME])));
  const verify = api.on("POST", "/v1/domains/dom_2/verify", json({ ...ACME, status: "active" }));
  const domain = nc.Domain.fromName("acme.test");
  assert.equal(lookup.count, 0);
  await domain.verify();
  assert.equal(lookup.last.query.get("name"), "acme.test");
  assert.deepEqual([lookup.count, verify.count, domain.status, domain.id], [1, 1, "active", "dom_2"]);
  assert.equal(verify.last.headers.get("NoClick-User"), USER_ID);

  api.on("GET", "/v1/domains", json(listing([])));
  await assert.rejects(nc.Domain.fromName("nope.test").hydrate(), nc.NotFound);
});

test("Domain.list, listPage and get", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/domains", json(listing([BOOKING, ACME], "c2")));
  api.on("GET", `/v1/domains/${DOMAIN_ID}`, json(BOOKING));
  const page = await nc.Domain.listPage({ limit: 2, userFilter: nc.ALL_USERS });
  assert.deepEqual([listed.last.query.get("user_id"), listed.last.query.get("limit")], ["all", "2"]);
  assert.deepEqual([page.data.map((d) => d.name), page.nextCursor], [["acmebooking.com", "acme.test"], "c2"]);
  const domain = await nc.Domain.get(DOMAIN_ID);
  assert.equal(domain.transferLockedUntil?.getUTCMonth(), 9);
  assert.equal((await nc.Domain.list({ limit: 1 })).length, 1);
});

test("domain.dns reads, sets and deletes records", async () => {
  const { api } = setup();
  const base = `/v1/domains/${DOMAIN_ID}/dns`;
  api.on("GET", base, json(listing([
    { type: "ALIAS", name: "@", value: "cname.noclick.site", status: "verified", managed: true },
    { type: "TXT", name: "@", value: "google-site-verification=abc", status: "verified" },
  ])));
  const create = api.on("POST", base, json({ type: "TXT", name: "@", value: "v=spf1 -all", status: "pending" }));
  const remove = api.on("DELETE", base, new Response(null, { status: 204 }));
  const domain = nc.Domain.fromId(DOMAIN_ID);
  const [managed, mine] = await domain.dns.records();
  assert.deepEqual([managed.managed, mine.managed], [true, false]);
  const saved = await domain.dns.set("TXT", "@", "v=spf1 -all");
  assert.deepEqual(create.last.body, { type: "TXT", name: "@", value: "v=spf1 -all" });
  assert.deepEqual([saved.value, saved.status], ["v=spf1 -all", "pending"]);
  await domain.dns.delete(mine);
  assert.deepEqual(
    [remove.last.query.get("type"), remove.last.query.get("name"), remove.last.query.get("value")],
    ["TXT", "@", "google-site-verification=abc"],
  );
});

test("update, renew, transferOut and delete", async () => {
  const { api } = setup();
  const path = `/v1/domains/${DOMAIN_ID}`;
  const patch = api.on("PATCH", path, json({ ...BOOKING, auto_renew: false }));
  const renew = api.on("POST", `${path}/renew`, json(operation({ id: "op_r", kind: "domain.renew", status: "running" })));
  api.on("GET", "/v1/operations/op_r/wait", json(operation({
    id: "op_r", kind: "domain.renew", status: "succeeded", result: { domain: { ...BOOKING, expires_at: "2029-09-01T00:00:00Z" } },
  })));
  api.on("POST", `${path}/transfer_out`, json({
    object: "transfer_code", auth_code: "Xy7#pQ2!", unlocked_at: "2026-11-02T09:00:00Z", expires_at: "2026-11-07T09:00:00Z",
  }));
  const remove = api.on("DELETE", path, new Response(null, { status: 204 }));

  const domain = nc.Domain.fromId(DOMAIN_ID);
  assert.equal(await domain.update({ autoRenew: false }), domain);
  assert.deepEqual(patch.last.body, { auto_renew: false });
  assert.equal(domain.autoRenew, false);
  await domain.update({ registrant: ANA });
  assert.deepEqual(patch.last.body, { registrant: ANA_WIRE });
  const renewal = await domain.renew({ years: 2, maxPriceUsd: 30 });
  assert.deepEqual(renew.last.body, { years: 2, max_price_usd: 30 });
  assert.ok(renewal instanceof nc.DomainPurchase);
  assert.equal((await renewal.wait()).expiresAt?.getUTCFullYear(), 2029);
  await domain.renew({ maxPriceUsd: 15 }); // the TLD's minimum term
  assert.deepEqual(renew.last.body, { max_price_usd: 15 });

  const code = await domain.transferOut();
  assert.equal(code.authCode, "Xy7#pQ2!");
  assert.equal(code.unlockedAt?.toISOString(), "2026-11-02T09:00:00.000Z");
  assert.equal(code.expiresAt?.toISOString(), "2026-11-07T09:00:00.000Z");
  assert.ok(!inspect(code).includes("Xy7"));
  await domain.delete();
  assert.equal(remove.count, 1);
});

test("transferOut inside the lock throws NotAvailable", async () => {
  const { api } = setup();
  api.on("POST", `/v1/domains/${DOMAIN_ID}/transfer_out`, apiError(409, "not_available", "acmebooking.com can't move until 2026-10-31."));
  await assert.rejects(nc.Domain.fromId(DOMAIN_ID).transferOut(), nc.NotAvailable);
});

test("Inbox.create puts an address on a domain", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/inboxes", json({ object: "inbox", id: "inb_9", address: "help@acmebooking.com", agent_id: null, user_id: null }));
  const inbox = await nc.Inbox.create({ localPart: "help", domain: nc.Domain.fromName("acmebooking.com") });
  assert.deepEqual(create.last.body, { local_part: "help", domain: "acmebooking.com" });
  assert.equal(inbox.address, "help@acmebooking.com");

  api.on("GET", `/v1/domains/${DOMAIN_ID}`, json(BOOKING));
  await nc.Inbox.create({ domain: nc.Domain.fromId(DOMAIN_ID) }); // a lazy domain loads for its name
  assert.deepEqual(create.last.body, { domain: "acmebooking.com" });
  await nc.Inbox.create({ domain: "mail.acme.test" }); // on a connected domain, a subdomain of it
  assert.deepEqual(create.last.body, { domain: "mail.acme.test" });

  api.on("POST", "/v1/inboxes", apiError(409, "conflict", "acme.test's mail stays where it is: put the inbox on a subdomain of it."));
  await assert.rejects(nc.Inbox.create({ localPart: "help", domain: "acme.test" }), nc.Conflict);
});

test("an inbox reads its threads, and a thread whole with the replies it sent", async () => {
  const { api } = setup();
  const thread = {
    object: "inbox_thread", id: "thr_1", inbox_id: "inb_9", conversation: "inbox:inb_9:thr_1", subject: "Order 1841",
    correspondent: "ada@customer.example", message_count: 2, last_direction: "outbound", snippet: "On it.",
    last_at: "2026-10-14T09:00:00Z",
  };
  const page = api.on("GET", "/v1/inboxes/inb_9/threads", json(listing([thread], "41")));
  const inbox = nc.Inbox.fromId("inb_9");
  const threads = await inbox.threads({ limit: 1 });
  assert.equal(page.last.query.get("limit"), "1");
  assert.equal(threads.nextCursor, "41");
  const [listed] = threads.data;
  assert.deepEqual([listed.subject, listed.messageCount, listed.lastDirection, listed.messages], ["Order 1841", 2, "outbound", []]);

  api.on("GET", "/v1/inboxes/inb_9/threads/thr_1", json({
    ...thread,
    messages: [
      { object: "inbox_message", id: "thr_1", inbox_id: "inb_9", direction: "inbound", from: "ada@customer.example", to: "help@acmebooking.com", subject: "Order 1841", text: "Where is it?" },
      { object: "inbox_message", id: "m_2", inbox_id: "inb_9", direction: "outbound", from: "help@acmebooking.com", to: "ada@customer.example", subject: "Re: Order 1841", text: "On it." },
    ],
  }));
  const whole = await inbox.thread("thr_1");
  assert.deepEqual(whole.messages.map((m) => [m.direction, m.sender, m.text]), [
    ["inbound", "ada@customer.example", "Where is it?"],
    ["outbound", "help@acmebooking.com", "On it."],
  ]);
});

test("an inbox on its domain sends new mail, and follows up on a thread", async () => {
  const { api } = setup();
  const sent = {
    object: "inbox_message", id: "m_3", inbox_id: "inb_9", direction: "outbound", from: "hello@acmebooking.com",
    to: "orders@millbrook.test", subject: "Saturday delivery", text: "Can you deliver?", status: "sending",
    delivery_status: null, delivery_error: null,
  };
  const route = api.on("POST", "/v1/inboxes/inb_9/messages", json(sent, { status: 201 }));
  const inbox = nc.Inbox.fromId("inb_9");
  const message = await inbox.send({ to: "orders@millbrook.test", subject: "Saturday delivery", text: "Can you deliver?", idempotencyKey: "ask-1" });
  assert.deepEqual(route.last.body, { to: "orders@millbrook.test", subject: "Saturday delivery", text: "Can you deliver?" });
  assert.equal(route.last.headers.get("idempotency-key"), "ask-1");
  assert.deepEqual([message.direction, message.status, message.deliveryStatus], ["outbound", "sending", null]);

  await inbox.send({ text: "7am works?", thread: "thr_1" });
  assert.deepEqual(route.last.body, { text: "7am works?", thread_id: "thr_1" });
});

test("renewing past the guaranteed window is NotAvailable", async () => {
  const { api } = setup();
  api.on("POST", `/v1/domains/${DOMAIN_ID}/renew`, apiError(409, "not_available", "acmebooking.com could be renewed until 2027-09-26."));
  await assert.rejects(nc.Domain.fromId(DOMAIN_ID).renew({ maxPriceUsd: 15 }), nc.NotAvailable);
});

// --- transfer a domain in --------------------------------------------------------

const MOVED = {
  ...ACME, source: "transferred", status: "active", noclick_dns: false, expires_at: "2027-11-02T00:00:00Z",
  auto_renew: true, transfer_locked_until: "2026-12-31T00:00:00Z",
};

test("Domain.transferQuote says whether it can move", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/domains/transfer_quote", json({
    object: "transfer_quote", name: "fresh.test", eligible: false, price_usd: 11.25, renewal_usd: 12.5, years: 1,
    reason: "fresh.test was registered on 2026-09-01; the registry's transfer lock holds it.", locked_until: "2026-10-31T00:00:00Z",
  }));
  const quote = await nc.Domain.transferQuote("fresh.test", { user: "acme" });
  assert.deepEqual([route.last.query.get("name"), route.last.headers.get("NoClick-User")], ["fresh.test", "acme"]);
  assert.deepEqual([quote.name, quote.eligible, quote.priceUsd, quote.renewalUsd, quote.years, quote.lockedUntil?.getUTCDate()], [
    "fresh.test", false, 11.25, 12.5, 1, 31,
  ]);
  assert.match(quote.reason ?? "", /transfer lock/);
});

test("Domain.transferIn is charged, waits for the registry, and resolves to the domain", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/domains/transfer_in", json(operation({
    id: "op_t", kind: "domain.transfer_in", status: "running", domain_id: "dom_2", price_usd: 11.25,
  })));
  api.on("GET", "/v1/domains/dom_2", json({ ...ACME, status: "transferring_in" }));
  api.on("GET", "/v1/operations/op_t/wait", json(operation({ id: "op_t", kind: "domain.transfer_in", status: "succeeded", result: { domain: MOVED } })));
  const quote: nc.TransferQuote = { name: "acme.test", eligible: true, reason: null, priceUsd: 11.25, renewalUsd: 12.5, years: 1, lockedUntil: null, raw: {} };
  const transfer = await nc.Domain.transferIn(quote, { authCode: "Xy7#pQ2!", maxPriceUsd: 15 });
  assert.deepEqual(start.last.body, { name: "acme.test", auth_code: "Xy7#pQ2!", max_price_usd: 15 });
  assert.equal(start.last.headers.get("NoClick-User"), null);
  assert.ok(transfer instanceof nc.DomainTransfer && transfer instanceof nc.Operation);
  assert.equal("purchaseFromId" in nc.DomainTransfer, false); // its own factory, of its own kind
  assert.deepEqual([transfer.status, transfer.priceUsd, (await transfer.domain.hydrate()).status], ["running", 11.25, "transferring_in"]);
  const domain = await transfer.wait();
  assert.deepEqual([domain.source, domain.status, domain.noClickDns, domain.transferLockedUntil?.getUTCMonth()], ["transferred", "active", false, 11]);

  api.on("GET", "/v1/operations/op_t", json(operation({ id: "op_t", kind: "domain.transfer_in", status: "running" })));
  const lazy = nc.DomainTransfer.transferFromId("op_t");
  assert.equal(lazy.kind, "domain.transfer_in"); // known before it loads
  const resumed = await lazy.hydrate();
  assert.ok(resumed instanceof nc.DomainTransfer);
  assert.equal((await resumed.wait()).source, "transferred");
});

test("a connected domain transfers in its own scope, a user's to their registrant", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/domains/dom_2", json(ACME));
  const start = api.on("POST", "/v1/domains/transfer_in", json(operation({ id: "op_c", kind: "domain.transfer_in", status: "awaiting_human", domain_id: "dom_2" })));
  const acme = nc.Domain.fromId("dom_2");
  await nc.Domain.transferIn(acme, { authCode: "Xy7#pQ2!", maxPriceUsd: 15 }); // user_42's: their registrant profile
  assert.equal(start.count, 1);
  assert.equal((start.last.body as { registrant?: unknown }).registrant, undefined);
  const held = await nc.asUser("someone_else", () => nc.Domain.transferIn(acme, { authCode: "Xy7#pQ2!", maxPriceUsd: 15, registrant: ANA }));
  assert.equal((start.last.body as { name: string }).name, "acme.test"); // the lazy domain loads for its name
  assert.equal(start.last.headers.get("NoClick-User"), USER_ID); // the domain's own user, not the ambient one
  assert.equal(held.status, "awaiting_human");
  assert.equal((await held.domain.hydrate()).status, "pending_dns");
  assert.equal(read.last.headers.get("NoClick-User"), USER_ID);

  api.on("GET", "/v1/domains/dom_9", json({ ...ACME, id: "dom_9", name: "acme.dev", user_id: null }));
  await nc.Domain.transferIn(nc.Domain.fromId("dom_9"), { authCode: "Xy7#pQ2!", maxPriceUsd: 15 });
  assert.equal(start.last.headers.get("NoClick-User"), null); // an account domain: the account
  await assert.rejects(nc.Domain.transferIn(acme, { authCode: "Xy7#pQ2!", maxPriceUsd: 15, registrant: ANA, user: "user_7" }), /own scope/);

  await nc.asUser("user_42", () => nc.Domain.transferIn("anasilva.dev", { authCode: "Kq9!mT4z", maxPriceUsd: 20 }));
  assert.equal(start.last.headers.get("NoClick-User"), "user_42");
  assert.equal(start.count, 4);
});

test("a transfer the registry refuses fails with its reason", async () => {
  const { api } = setup();
  api.on("POST", "/v1/domains/transfer_in", apiError(409, "not_available", "fresh.test can't move until 2026-10-31."));
  await assert.rejects(nc.Domain.transferIn("fresh.test", { authCode: "Xy7#pQ2!", maxPriceUsd: 15 }), nc.NotAvailable);

  api.on("POST", "/v1/domains/transfer_in", json(operation({ id: "op_x", kind: "domain.transfer_in", status: "running" })));
  api.on("GET", "/v1/operations/op_x/wait", json(operation({
    id: "op_x", kind: "domain.transfer_in", status: "failed",
    error: { type: "invalid_request", message: "The registry refused the auth code; nothing was charged.", field: "auth_code" },
  })));
  const transfer = await nc.Domain.transferIn("acme.test", { authCode: "wrong", maxPriceUsd: 15 });
  await assert.rejects(transfer.wait(), (err: unknown) => err instanceof nc.InvalidRequest && err.details.field === "auth_code");
});

test("domain.useNoClickDns copies what it can read, for review", async () => {
  const { api } = setup();
  const move = api.on("POST", "/v1/domains/dom_2/use_noclick_dns", json({
    domain: { ...MOVED, noclick_dns: true },
    copied: [{ type: "MX", name: "@", value: "10 mx.mail.example", status: "verified" }],
  }));
  const domain = nc.Domain.fromId("dom_2");
  const copied = await domain.useNoClickDns();
  assert.equal(move.count, 1);
  assert.deepEqual(copied.map((r) => [r.type, r.value]), [["MX", "10 mx.mail.example"]]);
  assert.deepEqual([domain.noClickDns, domain.source], [true, "transferred"]);

  api.on("POST", "/v1/domains/dom_3/use_noclick_dns", apiError(409, "not_available", "acme.dev is registered elsewhere."));
  await assert.rejects(nc.Domain.fromId("dom_3").useNoClickDns(), nc.NotAvailable);
});
