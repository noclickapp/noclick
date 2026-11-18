// Wake-ups: `agent.wake` at a time, after a while or when an operation settles, in the talking
// user's thread; `agent.wakeups` and `cancel`. Waking on a platform event is designed, not built:
// the server answers `not_available`.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "planner", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: 50,
  created_at: "2026-09-25T10:00:00Z",
};
const USER_AGENT = { ...AGENT, id: "ag_u", name: "assistant", user_id: USER_ID };

const WAKEUP = {
  object: "wakeup", id: "wk_1", agent_id: "ag_1", user_id: USER_ID, conversation: "launch", note: "Check the press list.",
  at: "2026-10-02T09:00:00Z", when: null, source: "code", status: "pending", woken_by: null, operation_id: null, depth: 0,
  error: null, created_at: "2026-10-01T09:00:00Z", delivered_at: null,
};

test("wake sets a time, a delay or an operation, in the talking user's thread", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const wake = api.on("POST", "/v1/agents/ag_1/wakeups", json(WAKEUP));
  const planner = nc.Agent.fromId("ag_1");

  const wakeup = await planner.wake("launch", { note: "Check the press list.", at: new Date("2026-10-02T09:00:00Z"), user: USER_ID });
  assert.deepEqual(wake.last.body, { conversation: "launch", note: "Check the press list.", at: "2026-10-02T09:00:00.000Z" });
  assert.equal(wake.last.headers.get("NoClick-User"), USER_ID); // an account agent talking to a user
  assert.ok(wakeup instanceof nc.Wakeup);
  assert.deepEqual(
    [wakeup.id, wakeup.conversation, wakeup.source, wakeup.status, wakeup.depth, wakeup.at?.toISOString(), wakeup.operation],
    ["wk_1", "launch", "code", "pending", 0, "2026-10-02T09:00:00.000Z", null],
  );

  await planner.wake("launch", { note: "Again in an hour.", afterS: 3600 });
  assert.deepEqual(wake.last.body, { conversation: "launch", note: "Again in an hour.", after_s: 3600 });
  assert.equal(wake.last.headers.get("NoClick-User"), null);

  await planner.wake("launch", { note: "The researcher finished.", when: nc.Job.jobFromId("op_t") });
  assert.deepEqual(wake.last.body, { conversation: "launch", note: "The researcher finished.", when: { operation_id: "op_t" } });

  // Several: it wakes once, when the last of them settles.
  await planner.wake("launch", { note: "Both are in.", when: [nc.Job.jobFromId("op_a"), nc.Job.jobFromId("op_b")] });
  assert.deepEqual(wake.last.body, { conversation: "launch", note: "Both are in.", when: { operation_ids: ["op_a", "op_b"] } });
  await assert.rejects(planner.wake("launch", { note: "Nothing.", when: [] }), TypeError);

  await planner.wake("launch", { note: "Tomorrow.", at: "2026-10-02T09:00:00+02:00" });
  assert.equal((wake.last.body as { at: string }).at, "2026-10-02T09:00:00+02:00");
});

test("an event wake-up is designed, and the server says so", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const wake = api.on("POST", "/v1/agents/ag_1/wakeups", apiError(409, "not_available", "Waking on a platform event isn't available yet."));
  await assert.rejects(
    nc.Agent.fromId("ag_1").wake("launch", { note: "Calendar connected.", when: "connection.connected", filters: { name: "calendar" } }),
    (err: unknown) => err instanceof nc.NotAvailable && /platform event/.test(err.message),
  );
  assert.deepEqual(wake.last.body, {
    conversation: "launch", note: "Calendar connected.", when: { event: "connection.connected", filters: { name: "calendar" } },
  });
});

test("wake refuses what it can't send, before sending", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const wake = api.on("POST", "/v1/agents/ag_1/wakeups", json(WAKEUP));
  const planner = nc.Agent.fromId("ag_1");
  await assert.rejects(planner.wake("launch", { note: "x" }), /exactly one of at, afterS, when and every/);
  await assert.rejects(planner.wake("launch", { note: "x", afterS: 60, when: "connection.connected" }), /exactly one/);
  await assert.rejects(planner.wake("launch", { note: "" , afterS: 60 }), /needs a note/);
  await assert.rejects(planner.wake("launch", { note: "x", at: "2026-10-02T09:00:00" }), /needs its offset/);
  await assert.rejects(planner.wake("launch", { note: "x", when: nc.Job.jobFromId("op_t"), filters: { a: 1 } }), /filters go with an event type/);
  assert.equal(wake.count, 0);
});

test("a routine wakes on a schedule, and changes", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const every = { cron: "0 8 * * 1-5", tz: "user" };
  const wake = api.on("POST", "/v1/agents/ag_1/wakeups", json({ ...WAKEUP, every, fired: 3 }));
  const planner = nc.Agent.fromId("ag_1");
  const briefing = await planner.wake("briefing", { note: "Brief me.", every: new nc.Cron("0 8 * * 1-5", { tz: "user" }) });
  assert.deepEqual(wake.last.body, { conversation: "briefing", note: "Brief me.", every });
  assert.deepEqual([briefing.every?.expr, briefing.every?.tz, briefing.fired], ["0 8 * * 1-5", "user", 3]);

  const patch = api.on("PATCH", "/v1/agents/ag_1/wakeups/wk_1", json({ ...WAKEUP, every, note: "Brief me at 7." }));
  await briefing.update({ note: "Brief me at 7.", every: new nc.Cron("0 7 * * 1-5", { tz: "user" }) });
  assert.deepEqual(patch.last.body, { note: "Brief me at 7.", every: { cron: "0 7 * * 1-5", tz: "user" } });
  assert.equal(briefing.note, "Brief me at 7.");
  await briefing.update({ afterS: 7200 });
  assert.deepEqual(patch.last.body, { after_s: 7200 });

  await assert.rejects(briefing.update({}), /Nothing to change/);
  await assert.rejects(briefing.update({ afterS: 60, every: new nc.Cron("0 7 * * *") }), /at most one/);
  await assert.rejects(planner.wake("c", { note: "x", every: new nc.Cron("0 9 * * 1", { message: "hi" }) }), /no message/);
});

test("the server refuses a hundred-and-first pending wake-up", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("POST", "/v1/agents/ag_1/wakeups", apiError(429, "quota_exceeded", "The agent already has 100 pending wake-ups.", { limit: 100 }));
  await assert.rejects(nc.Agent.fromId("ag_1").wake("launch", { note: "x", afterS: 60 }), nc.QuotaExceeded);
});

test("wakeups lists and filters; a wake-up cancels and opens its turn", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_u", json(USER_AGENT));
  const delivered = {
    ...WAKEUP, agent_id: "ag_u", id: "wk_2", status: "delivered", source: "wake_me", depth: 2, operation_id: "op_m",
    delivered_at: "2026-10-01T11:00:00Z", woken_by: { at: "2026-10-01T11:00:00+00:00" },
  };
  const list = api.on("GET", "/v1/agents/ag_u/wakeups", json(listing([{ ...WAKEUP, agent_id: "ag_u" }, delivered])));
  const cancel = api.on("POST", "/v1/agents/ag_u/wakeups/wk_1/cancel", json({ ...WAKEUP, agent_id: "ag_u", status: "canceled" }));

  const [pending, done] = await nc.Agent.fromId("ag_u").wakeups({ conversation: "launch", status: "pending" });
  assert.equal(list.last.query.get("conversation"), "launch");
  assert.equal(list.last.query.get("status"), "pending");
  assert.equal(list.last.headers.get("NoClick-User"), USER_ID); // a user's own agent talks as its user
  assert.deepEqual(
    [done.source, done.depth, done.operationId, done.wokenBy, done.deliveredAt?.toISOString()],
    ["wake_me", 2, "op_m", { at: "2026-10-01T11:00:00+00:00" }, "2026-10-01T11:00:00.000Z"],
  );
  assert.equal(done.operation?.id, "op_m");
  assert.equal((await pending.cancel()).status, "canceled");
  assert.equal(cancel.count, 1);
});

test("cancelling one that already ran is a conflict", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/wakeups", json(listing([{ ...WAKEUP, user_id: null, status: "delivered" }])));
  api.on("POST", "/v1/agents/ag_1/wakeups/wk_1/cancel", apiError(409, "conflict", "The wake-up is already delivered.", { wakeup_status: "delivered" }));
  const [ran] = await nc.Agent.fromId("ag_1").wakeups();
  await assert.rejects(ran.cancel(), nc.Conflict);
});

test("wakeups read across users' threads, and each cancels in its own thread", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const ours = { ...WAKEUP, user_id: null };
  const theirs = { ...WAKEUP, id: "wk_2", conversation: "ada" };
  const list = api.on("GET", "/v1/agents/ag_1/wakeups", json(listing([ours, theirs])));
  const cancel = api.on("POST", "/v1/agents/ag_1/wakeups/wk_2/cancel", json({ ...theirs, status: "canceled" }));
  const [mine, other] = await nc.Agent.fromId("ag_1").wakeups({ status: "pending", userFilter: nc.ALL_USERS });
  assert.deepEqual([list.last.query.get("user_id"), list.last.query.get("status")], ["all", "pending"]);
  assert.equal(list.last.headers.get("NoClick-User"), null);
  assert.deepEqual([mine.userId, other.userId], [null, USER_ID]);
  await other.cancel();
  assert.equal(cancel.last.headers.get("NoClick-User"), USER_ID);
  await assert.rejects(nc.Agent.fromId("ag_1").wakeups({ user: "someone", userFilter: nc.ALL_USERS }), /not both/);
});
