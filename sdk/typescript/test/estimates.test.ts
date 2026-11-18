// Estimates: what the client sends to price things before they're made, and what it reads back.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, setup } from "./helpers.ts";

const LINE = { description: "Each request through the front door.", unit: "million requests", usage_fields: ["requests"] };
const ESTIMATE = {
  object: "estimate", estimated: true, monthly_usd: 0.311,
  plan: { name: "free", billing: "at_cost", included_usd_per_month: 5, included_usd_per_day: 1 },
  included_usd_per_month: 5,
  items: [
    {
      kind: "project", label: "App on the edge", name: "site", options: { runtime: "edge", region: "us-east", framework: null },
      usage: { requests: 100000, code_share: 0.2 }, assumed: ["framework", "code_share"], monthly_usd: 0.202,
      lines: [
        { ...LINE, charge: "front_door", unit_usd: 1.9, quantity: 0.1, usd: 0.19, assumed: false },
        { ...LINE, charge: "code_runs", unit: "million runs", unit_usd: 0.6, quantity: 0.02, usd: 0.012, assumed: true },
      ],
      not_included: ["The front door's CPU time."],
    },
    {
      kind: "database", label: "SQLite database", name: null, options: { engine: "sqlite" }, usage: { rows_written: 100000 },
      assumed: ["engine"], monthly_usd: 0.1,
      lines: [{ ...LINE, charge: "rows_written", unit: "million rows", unit_usd: 1, quantity: 0.1, usd: 0.1, assumed: true }],
      not_included: [],
    },
  ],
};

test("estimate() sends the items and reads every line, each naming its item", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/estimates", json(ESTIMATE));
  const items: nc.EstimateRequestItem[] = [{ kind: "project", name: "site", usage: { requests: 100_000 } }, { kind: "database" }];
  const est = await nc.estimate(items);
  assert.deepEqual(route.last.body, { items });
  assert.ok(est instanceof nc.Estimate);
  assert.deepEqual([est.monthlyUsd, est.estimated, est.includedUsdPerMonth], [0.311, true, 5]);
  assert.deepEqual([est.plan?.name, est.plan?.included_usd_per_day], ["free", 1]);
  const [site, database] = est.items;
  assert.deepEqual([site.kind, site.label, site.name, site.options.runtime, site.assumed, site.monthlyUsd],
    ["project", "App on the edge", "site", "edge", ["framework", "code_share"], 0.202]);
  assert.deepEqual(site.usage, { requests: 100000, code_share: 0.2 });
  assert.deepEqual([site.notIncluded, database.name], [["The front door's CPU time."], null]);
  assert.deepEqual(est.lines.map((l) => [l.kind, l.item, l.charge, l.quantity, l.unitUsd, l.usd, l.assumed]), [
    ["project", "site", "front_door", 0.1, 1.9, 0.19, false],
    ["project", "site", "code_runs", 0.02, 0.6, 0.012, true],
    ["database", null, "rows_written", 0.1, 1, 0.1, true],
  ]);
});

test("an estimate for a user says who and names no plan", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/estimates", json({ ...ESTIMATE, plan: null, included_usd_per_month: null }));
  const est = await nc.asUser(USER_ID, () => nc.estimate([{ kind: "bucket" }]));
  assert.equal(route.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual([est.plan, est.includedUsdPerMonth], [null, null]);
});

test("Estimate.kinds() says each usage, its default and each price", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/estimates/kinds", json(listing([{
    object: "estimate_kind", kind: "bucket", label: "Bucket", description: "A storage bucket for files.", options: {},
    usage: [{ name: "storage_gb", unit: "GB", description: "What it stores.", default: 1, most: null }],
    prices: [{ charge: "storage", description: "What it stores.", unit: "GB-month", unit_usd: 0.015, usage_fields: ["storage_gb"] }],
    not_included: [],
  }])));
  const [bucket] = await nc.Estimate.kinds({ region: "eu" });
  assert.equal(route.last.query.get("region"), "eu");
  assert.deepEqual(bucket.usage, [{ name: "storage_gb", unit: "GB", description: "What it stores.", default: 1, most: null }]);
  assert.deepEqual(bucket.prices, [{ charge: "storage", description: "What it stores.", unit: "GB-month", unitUsd: 0.015, usageFields: ["storage_gb"] }]);
  await nc.Estimate.kinds();
  assert.equal(route.last.query.has("region"), false);
});

test("what it can't price is refused by name", async () => {
  const { api } = setup();
  api.on("POST", "/v1/estimates", apiError(400, "invalid_request", "items[0].usage.requests: a number, 0 or more, not -5.",
    { field: "items[0].usage.requests" }));
  await assert.rejects(nc.estimate([{ kind: "project", usage: { requests: -5 } }]), (err: unknown) => {
    assert.ok(err instanceof nc.InvalidRequest);
    assert.equal(err.details.field, "items[0].usage.requests");
    return true;
  });
});
