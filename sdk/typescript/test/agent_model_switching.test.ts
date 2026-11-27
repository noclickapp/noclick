// Switching an agent's model connection: its rule (modelSwitching), the switch its own tool makes, the owner's say-so
// for paid keys, and a plan's limit as its own error.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, listing, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "atlas", model: "sonnet", harness: "claude_code", instructions: "Keep tests green.",
  tools: [], user_id: null, workflow_id: "wf_1", created_at: "2026-11-17T10:00:00Z", model_connection: "claude-personal",
  model_switching: { mode: "switch", allowed: null },
  switched_from: { connection: "claude-work", name: "claude-work", window: "five_hour", resets_at: "2026-11-17T15:20:00+00:00" },
};
const GRANT = {
  id: "g_1", agent_id: "ag_1", connections: ["kestrel-api"], scope: "standing", source: "cited",
  evidence: { where: "channel", channel_id: "ch_1", message_id: "m_1", at: "2026-11-17T15:10:00Z", quote: "you two use the Anthropic key", link: null },
  granted_by: { type: "owner", id: "u_1" }, expires_at: null, used_at: null, revoked_at: null, created_at: "2026-11-17T15:10:30Z",
};

test("its rule reads back, and is sent as the API takes it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({ ...AGENT, model_switching: { mode: "stay", allowed: null } }));
  const atlas = nc.Agent.fromId("ag_1");
  await atlas.refresh();
  assert.deepEqual(atlas.modelSwitching, { mode: "switch", allowed: null, harness: "same" });
  assert.deepEqual(atlas.switchedFrom, { connection: "claude-work", name: "claude-work", window: "five_hour", resetsAt: "2026-11-17T15:20:00+00:00" });
  // Only what's given is sent, so the rule's other part stays as it is: never a mode it wasn't given.
  await atlas.update({ modelSwitching: { mode: "stay" } });
  assert.deepEqual(patch.last.body, { model_switching: { mode: "stay" } });
  await atlas.update({ modelSwitching: { allowed: ["claude-personal", "kestrel-api"] } });
  assert.deepEqual(patch.last.body, { model_switching: { allowed: ["claude-personal", "kestrel-api"] } });
  await atlas.update({ modelSwitching: { allowed: null } });
  assert.deepEqual(patch.last.body, { model_switching: { allowed: null } });
  await atlas.update({ modelSwitching: { harness: "any" } });
  assert.deepEqual(patch.last.body, { model_switching: { harness: "any" } });
  await atlas.update({ modelSwitching: null });
  assert.deepEqual(patch.last.body, { model_switching: null });
});

test("fromName sets only a part of the rule that differs", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([AGENT])));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json(AGENT));
  await nc.Agent.fromName("atlas", { createIfMissing: true, instructions: AGENT.instructions, modelSwitching: { mode: "switch" } }).hydrate();
  assert.equal(patch.count, 0);
  await nc.Agent.fromName("atlas", { createIfMissing: true, instructions: AGENT.instructions, modelSwitching: { mode: "stay" } }).hydrate();
  assert.deepEqual(patch.last.body, { model_switching: { mode: "stay" } });
});

test("a switch names its connection and cites the owner's words", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const switched = api.on("POST", "/v1/agents/ag_1/model/switch", json({
    status: "asked", connection: "kestrel-api", harness: "claude_code", pays: "per_use", request_id: "hr_1",
  }));
  const done = await nc.Agent.fromId("ag_1").switchModel("kestrel-api", {
    reason: "told to in #usage", scope: "standing",
    evidence: { channel_id: "ch_1", message_id: "m_1", quote: "you two use the Anthropic key" },
  });
  assert.deepEqual([done.status, done.connection, done.pays, done.requestId], ["asked", "kestrel-api", "per_use", "hr_1"]);
  assert.deepEqual(switched.last.body, {
    connection: "kestrel-api", reason: "told to in #usage", scope: "standing",
    evidence: { channel_id: "ch_1", message_id: "m_1", quote: "you two use the Anthropic key" },
  });
});

test("the owner's say-so is listed with the agent, given, and taken back with its update", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json({ ...AGENT, model_grants: [GRANT] }));
  const given = api.on("POST", "/v1/agents/ag_1/model/grants", json({ ...GRANT, source: "owner" }, { status: 201 }));
  const revoked = api.on("PATCH", "/v1/agents/ag_1", json({
    ...AGENT, model_grants: [{ ...GRANT, revoked_at: "2026-11-18T09:00:00Z" }],
  }));
  const atlas = nc.Agent.fromId("ag_1");
  const [grant] = await atlas.modelGrants();
  assert.deepEqual([grant.scope, grant.source, grant.evidence.quote], ["standing", "cited", "you two use the Anthropic key"]);
  assert.equal((await atlas.grantModelSwitch(["kestrel-api"])).source, "owner");
  assert.deepEqual(given.last.body, { connections: ["kestrel-api"], scope: "standing" });
  assert.equal((await atlas.revokeModelGrant(grant)).revokedAt, "2026-11-18T09:00:00Z");
  assert.deepEqual(revoked.last.body, { revoke_model_grants: ["g_1"] });
});

test("a plan's limit is its own error, with when it's back and what the agent did", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", apiError(429, "plan_limit_reached", "Your Claude plan (claude-work) is used up.", {
    reason: "plan_limit", connection: "claude-work", window: "five_hour", resets_at: "2026-11-17T15:20:00+00:00",
    then: { waiting_until: "2026-11-17T15:20:00+00:00" },
  }));
  const err = await nc.Agent.fromId("ag_1").refresh().catch((e: unknown) => e);
  assert.ok(err instanceof nc.PlanLimitReached);
  assert.deepEqual([err.connection, err.window, err.resetsAt], ["claude-work", "five_hour", "2026-11-17T15:20:00+00:00"]);
  assert.deepEqual(err.then, { waiting_until: "2026-11-17T15:20:00+00:00" });
});
