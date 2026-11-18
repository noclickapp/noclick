// Cards (designed, not built yet), browsers and browser profiles, against the mock API.
import assert from "node:assert/strict";
import { test } from "node:test";
import { inspect } from "node:util";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, operation, setup } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const CARD = {
  object: "card", id: "card_1", name: "Office supplies", last4: "4242", brand: "visa", exp_month: 9, exp_year: 2029,
  status: "active", limit_usd: 1500, interval: "month", spent_usd: 412.3, resets_at: "2026-10-01T00:00:00Z",
  merchants: ["office_supplies"], require_approval_above_usd: 200, agent_id: "agt_2", user_id: USER_ID,
  created_at: "2026-09-01T10:00:00Z",
};
const CHARGE = {
  object: "card_transaction", id: "tx_1", card_id: "card_1", amount_usd: 86.4, merchant: "Staples",
  merchant_category: "office_supplies", status: "approved", decline_reason: null, approval_id: null, at: "2026-09-25T10:00:00Z",
};
const HELD = { ...CHARGE, id: "tx_2", amount_usd: 640, merchant: "Herman Miller", status: "pending_approval", approval_id: "op_appr" };

// --- cards ---------------------------------------------------------------------

test("Card.create sends the limits and resolves the agent", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([{ object: "agent", id: "agt_2", name: "concierge", user_id: "acme" }])));
  const create = api.on("POST", "/v1/cards", json(CARD));
  const card = await nc.asUser("acme", () =>
    nc.Card.create("Office supplies", {
      limitUsd: 1500, merchants: ["office_supplies"], agent: nc.Agent.fromName("concierge"), requireApprovalAboveUsd: 200,
    }),
  );
  assert.deepEqual(create.last.body, {
    name: "Office supplies", limit_usd: 1500, interval: "month", merchants: ["office_supplies"], agent_id: "agt_2",
    require_approval_above_usd: 200,
  });
  assert.equal(create.last.headers.get("NoClick-User"), "acme");
  assert.deepEqual([card.last4, card.brand, card.spentUsd, card.interval], ["4242", "visa", 412.3, "month"]);
  assert.equal(card.resetsAt?.toISOString(), "2026-10-01T00:00:00.000Z");

  await nc.Card.create("Software", { limitUsd: 200, interval: "transaction", merchants: "software" });
  assert.deepEqual(create.last.body, { name: "Software", limit_usd: 200, interval: "transaction", merchants: ["software"] });
});

test("Card.fromName skips closed cards and converges only what differs", async () => {
  const { api } = setup();
  const lookup = api.on("GET", "/v1/cards", json(listing([{ ...CARD, id: "card_0", status: "closed" }, CARD])));
  const patch = api.on("PATCH", "/v1/cards/card_1", json({ ...CARD, limit_usd: 2000 }));
  const card = nc.Card.fromName("Office supplies", {
    createIfMissing: true, limitUsd: 2000, merchants: ["office_supplies"], requireApprovalAboveUsd: 200, user: "acme",
  });
  assert.equal(lookup.count, 0);
  await card.hydrate();
  assert.equal(lookup.last.query.get("name"), "Office supplies");
  assert.deepEqual(patch.last.body, { limit_usd: 2000 });
  assert.deepEqual([card.id, card.limitUsd], ["card_1", 2000]);
  assert.throws(() => nc.Card.fromName("Travel", { createIfMissing: true }), /limitUsd/);
});

test("an explicit null in Card.fromName clears the agent and the approval threshold", async () => {
  const { api } = setup();
  const held = { ...CARD, agent_id: "agt_1", require_approval_above_usd: 200 };
  api.on("GET", "/v1/cards", json(listing([held])));
  const patch = api.on("PATCH", "/v1/cards/card_1", (call: Call) => json({ ...held, ...(call.body as object) }));
  const card = await nc.Card.fromName("Office supplies", {
    createIfMissing: true, limitUsd: held.limit_usd, merchants: held.merchants, agent: null, requireApprovalAboveUsd: null,
  }).hydrate();
  assert.deepEqual(patch.last.body, { agent_id: null, require_approval_above_usd: null });
  assert.equal(card.agentId, null);
});

test("Card.fromName issues a missing card, and says when there is none", async () => {
  const { api } = setup();
  api.on("GET", "/v1/cards", json(listing([])));
  const create = api.on("POST", "/v1/cards", json({ ...CARD, id: "card_9", name: "Travel" }));
  const card = await nc.Card.fromName("Travel", { createIfMissing: true, limitUsd: 3000, merchants: ["travel"] }).hydrate();
  assert.equal(card.id, "card_9");
  assert.deepEqual(create.last.body, { name: "Travel", limit_usd: 3000, interval: "month", merchants: ["travel"] });
  await assert.rejects(nc.Card.fromName("Gone").hydrate(), (err: unknown) => err instanceof nc.NotFound && /No open card/.test(err.message));
});

test("Card.list filters across users without the user header", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/cards", json(listing([CARD])));
  const [card] = await nc.Card.list({ status: "frozen", agent: "agt_2", userFilter: nc.ALL_USERS });
  assert.deepEqual([route.last.query.get("status"), route.last.query.get("agent_id"), route.last.query.get("user_id")], ["frozen", "agt_2", "all"]);
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.equal(card.name, "Office supplies");
  assert.equal((await nc.Card.listPage({ limit: 1 })).nextCursor, null);
});

test("transactions are typed, and a held one waits on its approval", async () => {
  const { api } = setup();
  api.on("GET", "/v1/cards/card_1", json(CARD));
  const history = api.on("GET", "/v1/cards/card_1/transactions", json(listing([HELD, CHARGE])));
  api.on("GET", "/v1/operations/op_appr/wait", json(operation({ id: "op_appr", kind: "human.approve", status: "succeeded", result: { approved: true } })));
  const card = nc.Card.fromId("card_1", { user: USER_ID });
  const [held, paid] = await card.transactions({ limit: 5 });
  assert.equal(history.last.query.get("limit"), "5");
  assert.equal(history.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual([paid.merchant, paid.amountUsd, paid.status, paid.at?.getUTCDate()], ["Staples", 86.4, "approved", 25]);
  assert.deepEqual([held.status, held.approvalId], ["pending_approval", "op_appr"]);
  assert.equal(await nc.Operation.fromId(held.approvalId!).wait(), true);
  await card.transactions({ status: "declined", limit: null });
  assert.deepEqual([history.last.query.get("status"), history.last.query.get("limit")], ["declined", null]);
});

const DETAILS = {
  object: "card_details", card_id: "card_1", url: "https://noclick.com/c/rv_1", expires_at: "2026-10-02T10:10:00Z",
  last4: "4242", brand: "visa", exp_month: 9, exp_year: 2029, single_use: false, amount_usd: null, closes_at: null,
  cardholder: "Acme Corp", billing_address: { postal_code: "94107", country: "US" },
};

test("reveal is a page and never the number", async () => {
  const { api } = setup();
  api.on("GET", "/v1/cards/card_1", json(CARD));
  api.on("POST", "/v1/cards/card_1/reveal", json(DETAILS));
  const details = await nc.Card.fromId("card_1").reveal();
  assert.deepEqual([details.url, details.last4, details.cardholder], ["https://noclick.com/c/rv_1", "4242", "Acme Corp"]);
  assert.equal(details.billingAddress?.postal_code, "94107");
  assert.ok(!("number" in details) && !("cvc" in details));
  // The url shows the number to whoever opens it: printing leaves it out.
  assert.ok(!inspect(details).includes("rv_1") && !JSON.stringify(details).includes("rv_1"));
});

test("a purchase is an operation that waits for its approval and resolves to its number", async () => {
  const { api } = setup();
  api.on("GET", "/v1/cards/card_1", json(CARD));
  const start = api.on("POST", "/v1/cards/card_1/purchases", json(operation({ id: "op_buy", kind: "card.purchase" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_buy/wait", json(operation({
    id: "op_buy", kind: "card.purchase", status: "succeeded", result: { ...DETAILS, single_use: true, amount_usd: 124.5 },
  })));
  const op = await nc.Card.fromId("card_1").purchase(124.5, "Staples", { reason: "Toner" });
  assert.deepEqual(start.last.body, { amount_usd: 124.5, merchant: "Staples", reason: "Toner" });
  const details = await op.wait();
  assert.ok(details instanceof nc.CardDetails);
  assert.deepEqual([details.amountUsd, details.singleUse], [124.5, true]);
});

test("a settled charge is disputed with its reason, and Card.program and merchantCategories are the account's", async () => {
  const { api } = setup();
  api.on("GET", "/v1/cards/card_1", json(CARD));
  const filed = api.on("POST", "/v1/cards/card_1/transactions/tx_1/dispute", json({
    object: "card_dispute", id: "dp_1", transaction_id: "tx_1", reason: "not_received", status: "submitted", amount_usd: 86.4,
  }));
  const dispute = await nc.Card.fromId("card_1").dispute("tx_1", { reason: "not_received", explanation: "Never came" });
  assert.deepEqual(filed.last.body, { reason: "not_received", explanation: "Never came" });
  assert.deepEqual([dispute.id, dispute.status], ["dp_1", "submitted"]);
  const program = api.on("GET", "/v1/cards/program", json({
    object: "card_program", status: "active", requirements_due: [], company_name: "Acme", country: "US", currency: "usd",
    onboarding_url: "https://noclick.com/dashboard/developers/cards/onboarding",
  }));
  api.on("GET", "/v1/cards/merchant_categories", json(listing([{ name: "software", description: "Software.", mccs: ["5734"] }])));
  const state = await nc.asUser("acme", () => nc.Card.program());
  assert.equal(program.last.headers.get("NoClick-User"), null);
  assert.deepEqual([state.status, state.companyName], ["active", "Acme"]);
  const [software] = await nc.Card.merchantCategories();
  assert.deepEqual([software.name, software.mccs], ["software", ["5734"]]);
});

test("update clears with null and leaves out the rest; freeze, unfreeze and close", async () => {
  const { api } = setup();
  api.on("GET", "/v1/cards/card_1", json(CARD));
  const patch = api.on("PATCH", "/v1/cards/card_1", json({ ...CARD, merchants: null, agent_id: null }));
  const card = await nc.Card.fromId("card_1").update({ limitUsd: 2000, merchants: null, agent: null });
  assert.deepEqual(patch.last.body, { limit_usd: 2000, merchants: null, agent_id: null });
  assert.deepEqual([card.merchants, card.agentId], [null, null]);
  api.on("POST", "/v1/cards/card_1/freeze", json({ ...CARD, status: "frozen" }));
  api.on("POST", "/v1/cards/card_1/unfreeze", json(CARD));
  api.on("POST", "/v1/cards/card_1/close", json({ ...CARD, status: "closed" }));
  assert.equal((await card.freeze()).status, "frozen");
  assert.equal((await card.unfreeze()).status, "active");
  assert.equal((await card.close()).status, "closed");
});

test("Card.funding is the account's balance, whoever asks", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/cards/funding", json({
    balance_usd: 2480, pending_usd: 640, available_usd: 1840, top_up_url: "https://noclick.com/dashboard/developers/cards/funding",
    bank_transfer: { bank_name: "TEST BANK", routing_number: "110000000", account_number: "000123", networks: ["ach", "wire"] },
  }));
  const funding = await nc.asUser("acme", () => nc.Card.funding());
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.deepEqual([funding.balanceUsd, funding.pendingUsd, funding.availableUsd], [2480, 640, 1840]);
  assert.deepEqual([funding.bankTransfer?.routingNumber, funding.bankTransfer?.networks], ["110000000", ["ach", "wire"]]);
});

test("cards not enabled throw NotAvailable", async () => {
  const { api } = setup();
  api.on("POST", "/v1/cards", apiError(409, "not_available", "Cards aren't enabled for this account."));
  await assert.rejects(nc.Card.create("Software", { limitUsd: 200 }), nc.NotAvailable);
});

// --- browser profiles -----------------------------------------------------------

const PROFILE = {
  object: "browser_profile", id: "bp_1", name: "ana-work", user_id: USER_ID,
  sites: [{ domain: "portal.example.com", signed_in_at: "2026-09-20T10:00:00Z", signed_in_by: "ana@example.com", last_used_at: "2026-09-25T10:00:00Z" }],
  last_used_at: "2026-09-25T10:00:00Z", created_at: "2026-09-20T09:00:00Z",
};
const LOGIN = {
  object: "browser_login", url: "https://noclick.com/b/login_1", expires_at: "2026-09-26T10:00:00Z", domain: "portal.example.com",
  delivery: { delivered_via: ["email"], undelivered: [] },
  operation: operation({ id: "op_login", kind: "browser.login", status: "awaiting_human" }),
};

test("BrowserProfile.fromName creates on first use", async () => {
  const { api } = setup();
  const lookup = api.on("GET", "/v1/browser_profiles", json(listing([])));
  const create = api.on("POST", "/v1/browser_profiles", json(PROFILE));
  const profile = nc.BrowserProfile.fromName("ana-work", { createIfMissing: true, user: "user_42" });
  assert.equal(lookup.count, 0);
  await profile.hydrate();
  assert.equal(lookup.last.query.get("name"), "ana-work");
  assert.equal(lookup.last.headers.get("NoClick-User"), "user_42");
  assert.deepEqual(create.last.body, { name: "ana-work" });
  assert.deepEqual(profile.sites.map((s) => [s.domain, s.lastUsedAt?.getUTCDate(), s.signedInBy]), [["portal.example.com", 25, "ana@example.com"]]);
  await assert.rejects(nc.BrowserProfile.fromName("other").hydrate(), nc.NotFound);
});

test("login sends a live-browser link and resolves to the sign-in", async () => {
  const { api } = setup();
  api.on("GET", "/v1/browser_profiles", json(listing([PROFILE])));
  const start = api.on("POST", "/v1/browser_profiles/bp_1/login", json(LOGIN));
  api.on("GET", "/v1/operations/op_login/wait", json(operation({
    id: "op_login", kind: "browser.login", status: "succeeded", result: { site: { domain: "portal.example.com", signed_in_at: "2026-09-26T09:00:00Z" } },
  })));
  const profile = nc.BrowserProfile.fromName("ana-work", { user: "user_42" });
  const login = await profile.login("https://portal.example.com", { reason: "to download your invoices" });
  assert.deepEqual(start.last.body, { url: "https://portal.example.com", reason: "to download your invoices" });
  assert.equal(start.last.headers.get("NoClick-User"), USER_ID);
  assert.ok(login instanceof nc.Operation);
  assert.deepEqual([String(login), login.domain, login.deliveredVia, login.status], ["https://noclick.com/b/login_1", "portal.example.com", ["email"], "awaiting_human"]);
  const site = await login.wait();
  assert.deepEqual([site.domain, site.lastUsedAt, site.signedInBy], ["portal.example.com", null, null]);

  await profile.login("https://vendor.example.com", { human: new nc.Human({ email: "ops@acme.test" }) });
  assert.deepEqual(start.last.body, { url: "https://vendor.example.com", human: { email: "ops@acme.test" } });
});

test("BrowserLogin.list is pinned to its kind", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/operations", json(listing([])));
  await nc.BrowserLogin.list({ status: "awaiting_human" });
  assert.equal(route.last.query.get("kind"), "browser.login");
});

test("forget and delete act by id with no read first", async () => {
  const { api } = setup();
  const get = api.on("GET", "/v1/browser_profiles/bp_1", json(PROFILE));
  const forget = api.on("DELETE", "/v1/browser_profiles/bp_1/sites/portal.example.com", new Response(null, { status: 204 }));
  const del = api.on("DELETE", "/v1/browser_profiles/bp_1", new Response(null, { status: 204 }));
  const profile = await nc.BrowserProfile.get("bp_1");
  await profile.forget("portal.example.com");
  assert.equal(forget.count, 1);
  assert.deepEqual(profile.sites, []);
  await nc.BrowserProfile.fromId("bp_1").delete();
  assert.deepEqual([del.count, get.count], [1, 1]);
});

// --- browsers ---------------------------------------------------------------------

const BROWSER = {
  object: "browser", id: "br_1", status: "running", profile_id: "bp_1", agent_id: null, live_url: "https://noclick.com/live/br_1",
  url: "about:blank", title: "", timeout_s: 900, cost_usd: 0, user_id: USER_ID, created_at: "2026-09-26T10:00:00Z",
  expires_at: "2026-09-26T10:15:00Z", closed_at: null,
};
const ACT = {
  done: true, summary: "Downloaded 3 invoices from September.", url: "https://portal.example.com/invoices",
  steps: [{ action: "click", detail: "September", url: "https://portal.example.com/invoices" }],
  downloads: [{ name: "INV-0912.pdf", size_bytes: 48213, url: "https://files.example.com/d/1" }],
  cost_usd: 0.18,
};

test("Browser.create with a profile acts for its user; close stops it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/browser_profiles", json(listing([PROFILE])));
  const create = api.on("POST", "/v1/browsers", json(BROWSER));
  const close = api.on("DELETE", "/v1/browsers/br_1", json({ ...BROWSER, status: "closed" }));
  const profile = nc.BrowserProfile.fromName("ana-work", { user: "user_42" });
  const browser = await nc.Browser.create({ profile, timeoutS: 900, human: new nc.Human({ email: "ana@example.com" }) });
  assert.deepEqual(create.last.body, { profile_id: "bp_1", timeout_s: 900, human: { email: "ana@example.com" } });
  assert.equal(create.last.headers.get("NoClick-User"), USER_ID);
  assert.equal(browser.liveUrl, "https://noclick.com/live/br_1");
  await browser.close();
  assert.deepEqual([close.count, browser.status], [1, "closed"]);
});

test("goto, extract, screenshot and content", async () => {
  const { api } = setup();
  const goto = api.on("POST", "/v1/browsers/br_1/goto", json({ url: "https://portal.example.com/invoices", title: "Invoices" }));
  const extract = api.on("POST", "/v1/browsers/br_1/extract", json({ data: [{ number: "INV-0912", total_usd: 120.5 }] }));
  const shot = api.on("GET", "/v1/browsers/br_1/screenshot", new Response(new Uint8Array([137, 80, 78, 71]), { status: 200, headers: { "content-type": "image/png" } }));
  const content = api.on("GET", "/v1/browsers/br_1/content", json({ content: "# Invoices" }));
  const browser = nc.Browser.fromId("br_1", { user: USER_ID });
  const page = await browser.goto("https://portal.example.com/invoices");
  assert.deepEqual(goto.last.body, { url: "https://portal.example.com/invoices" });
  assert.deepEqual([page.url, page.title, browser.url, browser.title], [
    "https://portal.example.com/invoices", "Invoices", "https://portal.example.com/invoices", "Invoices",
  ]);
  const rows = await browser.extract<{ number: string }[]>("the invoice numbers and totals", { schema: { type: "array" } });
  assert.equal(rows[0].number, "INV-0912");
  assert.deepEqual(extract.last.body, { query: "the invoice numbers and totals", schema: { type: "array" } });
  assert.deepEqual([...(await browser.screenshot({ fullPage: true }))], [137, 80, 78, 71]);
  assert.equal(shot.last.query.get("full_page"), "true");
  assert.equal(await browser.content(), "# Invoices");
  assert.equal(content.last.query.get("format"), "markdown");
});

test("act waits for the result, holds on a person, or returns the operation", async () => {
  const { api } = setup();
  const act = api.on(
    "POST", "/v1/browsers/br_1/act",
    json(operation({ id: "op_act", kind: "browser.act", status: "running" }), { status: 202 }),
    json(operation({ id: "op_act2", kind: "browser.act", status: "running" }), { status: 202 }),
  );
  const waits = api.on(
    "GET", "/v1/operations/op_act/wait",
    json(operation({ id: "op_act", kind: "browser.act", status: "awaiting_human" })),
    json(operation({ id: "op_act", kind: "browser.act", status: "succeeded", result: ACT })),
  );
  api.on("GET", "/v1/operations/op_act2/wait", json(operation({ id: "op_act2", kind: "browser.act", status: "succeeded", result: { done: false, summary: "Ran out of steps." } })));
  const browser = nc.Browser.fromId("br_1");
  const result = await browser.act("Download every invoice from September", { maxSteps: 40 });
  assert.deepEqual(act.calls[0].body, { instruction: "Download every invoice from September", max_steps: 40 });
  assert.equal(waits.count, 2); // a CAPTCHA held it on a person first
  assert.deepEqual([result.done, result.summary, result.steps[0].action, result.downloads[0].sizeBytes, result.costUsd], [
    true, "Downloaded 3 invoices from September.", "click", 48213, 0.18,
  ]);
  const op = await browser.act("Compare flights", { background: true });
  assert.ok(op instanceof nc.Operation);
  assert.deepEqual(act.calls[1].body, { instruction: "Compare flights" });
  const later = await op.wait();
  assert.deepEqual([later.done, later.summary, later.downloads], [false, "Ran out of steps.", []]);
});

test("Browser.list reads by profile and status", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/browsers", json(listing([BROWSER])));
  const [browser] = await nc.Browser.list({ profile: nc.BrowserProfile.fromId("bp_1"), status: "live", userFilter: nc.ALL_USERS });
  assert.deepEqual([route.last.query.get("profile_id"), route.last.query.get("status"), route.last.query.get("user_id")], ["bp_1", "live", "all"]);
  assert.equal(browser.expiresAt?.getUTCMinutes(), 15);
});

test("browser operations decode by kind anywhere", async () => {
  const { api } = setup();
  api.on("GET", "/v1/operations/op_act/wait", json(operation({ id: "op_act", kind: "browser.act", status: "succeeded", result: ACT })));
  const result = (await nc.Operation.fromId("op_act").wait()) as nc.ActResult;
  assert.equal(result.summary, "Downloaded 3 invoices from September.");
});
