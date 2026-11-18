// An agent's turn limits: how far one of its turns goes (steps, usd, minutes), sent as given and kept in step by
// `fromName`, cleared with `null`; a reply names the limit that ended its turn.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, operation, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "builder", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: null,
  created_at: "2026-09-25T10:00:00Z",
};

test("create sends the limits given", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/agents", json({ ...AGENT, turn_limits: { steps: 100 } }));
  const agent = await nc.Agent.create("builder", { instructions: "hi", turnLimits: { steps: 100 } });
  assert.deepEqual(create.last.body, { name: "builder", instructions: "hi", turn_limits: { steps: 100 } });
  assert.deepEqual(agent.turnLimits, { steps: 100 });
});

test("fromName converges the limits, in the order the agent keeps them, and null clears them", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([{ ...AGENT, turn_limits: { steps: 100, usd: 2, minutes: 30 } }])));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json(AGENT));
  await nc.Agent.fromName("builder", { createIfMissing: true, instructions: "hi",
                                       turnLimits: { minutes: 30, usd: 2, steps: 100 } }).hydrate();
  assert.equal(patch.count, 0);  // as defined: nothing to change

  await nc.Agent.fromName("builder", { createIfMissing: true, instructions: "hi", turnLimits: { steps: 150 } }).hydrate();
  assert.deepEqual(patch.last.body, { turn_limits: { steps: 150 } });
  await nc.Agent.fromName("builder", { createIfMissing: true, instructions: "hi", turnLimits: null }).hydrate();
  assert.deepEqual(patch.last.body, { turn_limits: null });
});

test("update sends the limits, and null goes back to the defaults", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({ ...AGENT, turn_limits: { steps: 150, usd: 3 } }));
  const agent = await nc.Agent.fromId("ag_1").update({ turnLimits: { steps: 150, usd: 3 } });
  assert.deepEqual(patch.last.body, { turn_limits: { steps: 150, usd: 3 } });
  assert.deepEqual(agent.turnLimits, { steps: 150, usd: 3 });
  await nc.Agent.fromId("ag_1").update({ turnLimits: null });
  assert.deepEqual(patch.last.body, { turn_limits: null });
});

test("a reply names the limit that ended its turn", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("POST", "/v1/agents/ag_1/messages", json(operation({
    id: "op_m", kind: "agent.message", status: "succeeded",
    result: { text: "Two pages are up; the rest is next.", ended_by: "steps" },
  })));
  assert.equal((await nc.Agent.fromId("ag_1").message("Build the site")).endedBy, "steps");
  api.on("POST", "/v1/agents/ag_1/messages", json(operation({
    id: "op_n", kind: "agent.message", status: "succeeded", result: { text: "Done." },
  })));
  assert.equal((await nc.Agent.fromId("ag_1").message("hi")).endedBy, null);
});
