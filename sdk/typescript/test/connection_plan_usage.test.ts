// A Claude or ChatGPT plan's tier and usage on its connection, against the mock API.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, setup } from "./helpers.ts";

const APP_ID = "credential:9b2a1c5e-7d9f-4a31-8f6d-3f1d2c4b8a7e";
const PATH_REF = encodeURIComponent(APP_ID);
const FIVE_HOUR = {
  kind: "five_hour", label: "5-hour", models: [], used: 0.91, left: 0.09,
  resets_at: "2026-11-17T12:40:00Z", state: "near",
};
const OPUS = { kind: "weekly_model", label: "Opus weekly", models: ["Opus"], used: 0.4, left: 0.6, resets_at: null, state: "ok" };
const PLAN = {
  object: "connection", id: APP_ID, name: "Claude plan", integration: "anthropic", credential_type: "agent_claude_code_oauth",
  user_id: null, status: "connected", origin: "app", access: "owner", approval_operations: [], account: "ana@example.com",
  verification: null, connect_link: null, used_by: [], connected_at: null, created_at: null, updated_at: null,
  plan: { tier: "max_20x", label: "Ultra", runs: ["claude_code"], refusal: null },
  usage: { state: "near", tightest: FIVE_HOUR, available_at: null, as_of: "2026-11-17T11:00:00Z" },
};
const KEY = { ...PLAN, id: "con_2", name: "anthropic", origin: "api", credential_type: "anthropic_api_key", plan: null, usage: null };

test("a plan's connection carries its tier and usage summary; any other carries neither", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections", json(listing([PLAN, KEY])));
  const [plan, key] = await nc.Connection.list();
  assert.deepEqual(
    [plan.plan?.tier, plan.plan?.label, plan.plan?.runs, plan.plan?.refusal],
    ["max_20x", "Ultra", ["claude_code"], null],
  );
  const summary = plan.usageSummary!;
  assert.equal(summary.state, "near");
  assert.equal(summary.tightest?.label, "5-hour");
  assert.equal(summary.tightest?.left, 0.09);
  assert.equal(summary.tightest?.resetsAt?.toISOString(), "2026-11-17T12:40:00.000Z");
  assert.equal(summary.asOf?.toISOString(), "2026-11-17T11:00:00.000Z");
  assert.equal(summary.availableAt, null);
  assert.equal(key.plan, null);
  assert.equal(key.usageSummary, null);
});

test("usage() reads the full reading for a model, fresh only when asked", async () => {
  const { api } = setup();
  const reading = {
    object: "plan_usage", connection: APP_ID, integration: "anthropic", plan: PLAN.plan, state: "used_up",
    windows: [{ ...FIVE_HOUR, used: 1, left: 0, state: "used_up" }, OPUS],
    tightest: { ...FIVE_HOUR, used: 1, left: 0, state: "used_up" },
    available_at: "2026-11-17T12:40:00Z",
    next_steps: [
      { kind: "wait", label: "Wait until it resets", until: "2026-11-17T12:40:00Z", connection: null, pays: null },
      { kind: "connection", label: "Run on anthropic", until: null,
        connection: { id: "con_2", name: "anthropic", integration: "anthropic", credential_type: "anthropic_api_key" }, pays: "per_use" },
      { kind: "connection", label: "Run on personal (nearly used)", until: null, pays: null, state: "near",
        connection: { id: "con_3", name: "personal", integration: "anthropic", credential_type: "agent_claude_code_oauth" } },
      { kind: "connect", label: "Connect another", until: null, connection: null, pays: null },
    ],
    as_of: "2026-11-17T11:00:00Z", source: "provider",
  };
  let route = api.on("GET", `/v1/connections/${APP_ID}/usage`, json(reading));
  if (PATH_REF !== APP_ID) route = api.on("GET", `/v1/connections/${PATH_REF}/usage`, json(reading));
  const usage = await nc.Connection.fromId(APP_ID).usage({ model: "claude-opus-5-5", fresh: true });
  assert.equal(route.last.query.get("model"), "claude-opus-5-5");
  assert.equal(route.last.query.get("fresh"), "true");
  assert.equal(usage.state, "used_up");
  assert.equal(usage.connection, APP_ID);
  assert.equal(usage.plan?.label, "Ultra");
  assert.deepEqual(usage.windows.map((w) => [w.label, w.used, w.state, w.models]), [
    ["5-hour", 1, "used_up", []], ["Opus weekly", 0.4, "ok", ["Opus"]],
  ]);
  assert.equal(usage.windows[1].resetsAt, null);
  assert.equal(usage.availableAt?.toISOString(), "2026-11-17T12:40:00.000Z");
  assert.deepEqual(usage.nextSteps.map((s) => s.kind), ["wait", "connection", "connection", "connect"]);
  assert.equal(usage.integration, "anthropic");
  assert.deepEqual(usage.nextSteps.map((s) => s.state), [null, null, "near", null]);
  assert.equal(usage.nextSteps[0].until?.toISOString(), "2026-11-17T12:40:00.000Z");
  assert.deepEqual(usage.nextSteps[1].connection, {
    id: "con_2", name: "anthropic", integration: "anthropic", credentialType: "anthropic_api_key",
  });
  assert.equal(usage.nextSteps[1].pays, "per_use");
  assert.equal(usage.source, "provider");

  await nc.Connection.fromId(APP_ID).usage();
  assert.equal(route.last.query.get("model"), null);
  assert.equal(route.last.query.get("fresh"), null);
});
