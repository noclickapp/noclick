// Agents that coordinate agents (designed, not built yet): agent listing and channel subscriptions
// to NoClick's own events (spawn, jobs, ask and the agents capability are built: jobs_and_ask.test.ts;
// workspaces: workspaces.test.ts).
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, listing, operation, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "planner", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: 50,
  created_at: "2026-09-25T10:00:00Z",
};
const USER_AGENT = { ...AGENT, id: "ag_u", name: "assistant", user_id: USER_ID };

const TASK = operation({
  id: "op_t", kind: "agent.task", status: "running", step: "working", agent_id: "ag_c", started_by: "ag_1",
  conversation: "task-1", parent_conversation: "launch", updates: ["done", "blocked", { every_s: 900 }],
  latest_update: { id: "up_1", job_id: "op_t", agent_id: "ag_c", kind: "every", text: "Two of three found.", status: "running", created_at: "2026-10-01T10:00:00Z" },
});
const CHILD = { ...AGENT, id: "ag_c", name: "planner-1a2b3c4d", parent_id: "ag_1", job_id: "op_t", status: "working", child_count: 0, job: TASK };

// --- listing ----------------------------------------------------------------------------

test("Agent.list filters by status, activity, parent, lifetime and harness, and orders by activity", async () => {
  const { api } = setup();
  const list = api.on("GET", "/v1/agents", json(listing([{ ...AGENT, status: "working", last_active_at: "2026-10-01T09:30:00Z", running_turns: 2, child_count: 3 }])));
  const [agent] = await nc.Agent.list({
    status: "working", activeSince: new Date("2026-10-01T00:00:00Z"), parent: nc.Agent.fromId("ag_p"), temporary: true,
    harness: "claude_code", order: "last_active",
  });
  const q = list.last.query;
  assert.deepEqual(
    [q.get("status"), q.get("active_since"), q.get("parent_id"), q.get("temporary"), q.get("harness"), q.get("order")],
    ["working", "2026-10-01T00:00:00.000Z", "ag_p", "true", "claude_code", "last_active"],
  );
  assert.deepEqual([agent.status, agent.lastActiveAt?.toISOString(), agent.runningTurns, agent.childCount, agent.jobId, agent.job],
    ["working", "2026-10-01T09:30:00.000Z", 2, 3, null, null]);
  await nc.Agent.listPage({ temporary: false, limit: 5 });
  assert.equal(list.last.query.get("temporary"), "false");
  await assert.rejects(nc.Agent.list({ status: "paused" as nc.AgentStatus }), /status is one of working, waiting, idle, expired/);
  await assert.rejects(nc.Agent.list({ order: "name" as "created" }), /order is one of created, last_active/);
});

test("children lists an agent's children in its owner's scope", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_u", json(USER_AGENT));
  const list = api.on("GET", "/v1/agents", json(listing([CHILD])));
  const [child] = await nc.asUser("someone_else", () => nc.Agent.fromId("ag_u").children({ status: "expired", limit: 10 }));
  assert.equal(list.last.query.get("parent_id"), "ag_u");
  assert.equal(list.last.query.get("status"), "expired");
  assert.equal(list.last.headers.get("NoClick-User"), USER_ID);
  assert.equal(child.job?.id, "op_t");
});

// --- channel subscriptions ------------------------------------------------------------------

const SUB = {
  object: "subscription", id: "sub_1", channel_id: "ch_1", workspace_id: null, channels: null,
  source: { kind: "event", connection: "stripe", event: "invoice.payment_failed", filters: {} }, wake: "all", filters: {},
  status: "active", error: null, url: null, last_event_at: null, created_at: "2026-10-01T09:00:00Z",
};

test("a channel subscribes to a platform event type (built: app events and webhooks, in triggers.test.ts)", async () => {
  const { api } = setup();
  const sub = api.on("POST", "/v1/channels/ch_1/subscriptions", json(SUB));
  await nc.Channel.fromId("ch_1").subscribe("connection.disconnected");
  assert.deepEqual(sub.last.body, { source: { kind: "platform", type: "connection.disconnected" }, wake: null });
  await assert.rejects(nc.Channel.fromId("ch_1").subscribe("operation.failed", { wake: "some" as "all" }), /wake is null, "all" or a list of agents/);
});
