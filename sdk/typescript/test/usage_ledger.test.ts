// The account's ledger (parity with the Python client, tests/test_usage_ledger.py): its groups read in a time zone,
// a page of its charges narrowed and paged, and the money behind it, null where nobody is billed.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const GROUP = {
  current: true, day: "2026-11-19", created_at: "2026-11-19T09:00:00+00:00", k: "k1", user_id: "u1",
  usage_type: "api_usage", usage_subtype: "voice/call", unit_type: "seconds", user_resource: false, n: 2,
  quantity: 240, total_cost: 0.5, prompt_tokens: 0, completion_tokens: 0, workflow_id: null, number: "+14155550132",
};
const LEDGER = {
  object: "usage_groups", now: "2026-11-20T10:00:00+00:00", account: { id: "u1" },
  period: { window_start: "2026-11-01T00:00:00+00:00", window_end: "2026-12-01T00:00:00+00:00", previous_start: "2026-10-01T00:00:00+00:00" },
  fields: ["usage_type", "usage_subtype", "workflow_id", "number"], groups: [GROUP],
  directory: { workflows: {}, agents: {}, people: { u1: { name: "Ada" } } },
};
const CHARGE = {
  id: "ev_1", created_at: "2026-11-19T09:00:00+00:00", user_id: "u1", organization_id: null, usage_type: "api_usage",
  usage_subtype: "voice/call", quantity: 120, unit_type: "seconds", total_cost: 0.25, user_resource: false, k: "k1",
  metadata: { number: "+14155550132" },
};

test("the ledger reads its groups in a zone", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/usage/groups", json(LEDGER));
  const ledger = await nc.Usage.ledger({ tz: "Asia/Kolkata" });
  assert.equal(route.last.query.get("tz"), "Asia/Kolkata");
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.deepEqual([ledger.periodStart, ledger.previousStart], [new Date("2026-11-01T00:00:00Z"), new Date("2026-10-01T00:00:00Z")]);
  const [group] = ledger.groups;
  assert.deepEqual([group.key, group.current, group.day, group.subtype, group.ownResource, group.charges, group.usd], ["k1", true, "2026-11-19", "voice/call", false, 2, 0.5]);
  assert.deepEqual(group.fields, { usage_type: "api_usage", usage_subtype: "voice/call", workflow_id: null, number: "+14155550132" });
  assert.deepEqual(ledger.directory.people.u1, { name: "Ada" });
});

test("charges are narrowed and paged", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/usage/charges", json({ object: "usage_charges", rows: [CHARGE], runs: {}, next: "2026-11-19T09:00:00+00:00|ev_1" }));
  const page = await nc.Usage.charges({ keys: ["k1"], day: "2026-11-19", tz: "UTC", limit: 1 });
  assert.deepEqual(route.last.body, { keys: ["k1"], day: "2026-11-19", tz: "UTC", limit: 1 });
  const [charge] = page.charges;
  assert.deepEqual([charge.id, charge.key, charge.usd, charge.metadata], ["ev_1", "k1", 0.25, { number: "+14155550132" }]);
  assert.deepEqual(charge.at, new Date("2026-11-19T09:00:00Z"));
  assert.equal(page.next, "2026-11-19T09:00:00+00:00|ev_1");
  await nc.Usage.charges({ from: new Date("2026-11-01T00:00:00Z"), to: "2026-12-01T00:00:00Z", cursor: page.next! });
  assert.deepEqual(route.last.body, { start: "2026-11-01T00:00:00.000Z", end: "2026-12-01T00:00:00Z", cursor: page.next });
});

test("the money behind it, or null", async () => {
  const { api } = setup();
  api.on(
    "GET",
    "/v1/usage/billing",
    json({ object: "usage_billing", billing: {
      plan: { tier: "member", included_usd: 10 }, balance: { usd: -2.5, has: true }, funds: { usd: 20, fee: 1, count: 1 },
      recurring: [{ id: "r1", label: "+1 415 555 0132" }], domains: [],
    } }),
    json({ object: "usage_billing", billing: null }),
  );
  const money = await nc.Usage.billing();
  assert.ok(money);
  assert.deepEqual([money.balanceUsd, money.fundsUsd, money.feesUsd, money.plan.included_usd], [-2.5, 20, 1, 10]);
  assert.deepEqual([money.recurring[0].id, money.autoTopUp], ["r1", null]);
  assert.equal(await nc.Usage.billing(), null);
});

test("Usage.billingDetails() and billingPortal() read the plan's Stripe side", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/usage/billing/details", json({
    object: "billing_details",
    subscription: { status: "active", current_period_end: "2026-12-01T00:00:00Z", cancel_at_period_end: true },
    topup_subscription: {
      status: "active", current_period_end: "2027-01-15T08:00:00Z", cancel_at_period_end: false, credits_per_month: 400,
      interval: "year", subscription_id: "sub_topup",
    },
    payment_method: null,
  }));
  assert.deepEqual(await nc.Usage.billingDetails({ organizationId: "org_1" }), {
    subscription: { status: "active", currentPeriodEnd: "2026-12-01T00:00:00Z", cancelAtPeriodEnd: true },
    topupSubscription: {
      status: "active", currentPeriodEnd: "2027-01-15T08:00:00Z", cancelAtPeriodEnd: false, creditsPerMonth: 400,
      interval: "year", subscriptionId: "sub_topup",
    },
    paymentMethod: null,
  });
  assert.equal(read.last.query.get("organization_id"), "org_1");
  const portal = api.on("POST", "/v1/usage/billing/portal", json({ object: "billing_portal", url: "https://billing.stripe.com/p/session/test_1" }));
  assert.equal(await nc.Usage.billingPortal(), "https://billing.stripe.com/p/session/test_1");
  assert.deepEqual(portal.last.body, {});
});

test("Usage.credits() reads the meter's pool, a team workspace's by its id", async () => {
  const { api } = setup();
  const body = {
    object: "credit_usage", used: 1.5, limit: 4, period: "day", monthly_used: 3, monthly_cap: 20, topup_credits: 0,
    effective_tier: "free", is_org_credits: true, organization_id: "org_1", pool_user_id: "user_owner", balance_usd: 2.5,
  };
  const route = api.on("GET", "/v1/usage/credits", json(body), json(body));
  const meter = await nc.Usage.credits({ organizationId: "org_1" });
  assert.equal(route.last.query.get("organization_id"), "org_1");
  assert.deepEqual([meter.used, meter.limit, meter.period, meter.balanceUsd, meter.poolUserId, meter.isOrgCredits],
    [1.5, 4, "day", 2.5, "user_owner", true]);
  await nc.Usage.credits();
  assert.equal(route.last.query.get("organization_id"), null);
});
