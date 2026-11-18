// Spawn with the updates a parent requires, jobs and their updates, ask, and the agents capability
// that does these from inside an agent: built.
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
  conversation: "task", parent_conversation: "launch", updates: ["done", "blocked", { every_s: 900 }],
  latest_update: { id: "up_1", job_id: "op_t", agent_id: "ag_c", kind: "every", text: "Two of three found.", status: "running", created_at: "2026-10-01T10:00:00Z" },
});
const CHILD = { ...AGENT, id: "ag_c", name: "planner-1a2b3c4d", parent_id: "ag_1", job_id: "op_t", status: "working", child_count: 0, job: TASK };

// --- spawn, jobs and updates --------------------------------------------------------------

test("spawn starts the task at once with the updates its parent requires", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const spawn = api.on("POST", "/v1/agents/ag_1/children", json(CHILD, { status: 201 }));
  api.on("GET", "/v1/operations/op_t/wait", json({ ...TASK, status: "succeeded", result: { text: "Three launches, summarized.", conversation: "task", tool_calls: [] } }));

  const child = await nc.Agent.fromId("ag_1").spawn("Find three recent launches in our category.", {
    updates: ["blocked", new nc.Before("gmail.send_email_message", "stripe.*"), new nc.Every(900), "done"],
    conversation: "launch", instructions: "Report what you found and where.", tools: ["search", "fetch"],
    budgetUsd: 0.5, ttlS: 900, model: "openrouter/y", harness: "sdk", modelConnection: "openrouter", name: "researcher", user: USER_ID,
  });
  assert.deepEqual(spawn.last.body, {
    task: "Find three recent launches in our category.",
    updates: ["done", "blocked", { before: ["gmail.send_email_message", "stripe.*"] }, { every_s: 900 }],
    conversation: "launch", instructions: "Report what you found and where.", tools: ["search", "fetch"],
    budget_usd_per_month: 0.5, ttl_s: 900, model: "openrouter/y", harness: "sdk", model_connection: "openrouter", name: "researcher",
  });
  assert.equal(spawn.last.headers.get("NoClick-User"), USER_ID); // the parent's conversation is the user's thread
  assert.equal(child.parentId, "ag_1");
  const job = child.job;
  assert.ok(job instanceof nc.Job);
  assert.equal(child.job, job); // one job object per agent
  assert.deepEqual(
    [job.kind, job.status, job.step, job.startedBy, job.conversation, job.parentConversation, job.requiredUpdates],
    ["agent.task", "running", "working", "ag_1", "task", "launch", ["done", "blocked", { every_s: 900 }]],
  );
  assert.deepEqual([job.latestUpdate?.kind, job.latestUpdate?.text], ["every", "Two of three found."]);
  assert.equal(job.agent?.id, "ag_c");
  const reply = await job.wait();
  assert.deepEqual([reply.text, reply.conversation, reply.operationId], ["Three launches, summarized.", "task", "op_t"]);

  await nc.Agent.fromId("ag_1").spawn("Just this.");
  assert.deepEqual(spawn.last.body, { task: "Just this.", updates: ["done"] });
});

test("spawn refuses an empty task and updates it doesn't know", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const spawn = api.on("POST", "/v1/agents/ag_1/children", json(CHILD));
  const planner = nc.Agent.fromId("ag_1");
  await assert.rejects(planner.spawn(""), /needs the task/);
  await assert.rejects(planner.spawn("x", { updates: ["sometimes" as nc.UpdateSpec] }), /An update is "done", "blocked", a Before or an Every/);
  assert.throws(() => new nc.Before(), /at least one tool pattern/);
  assert.throws(() => new nc.Every(30), /60 or more/);
  assert.throws(() => new nc.Every(90.5), /whole number of seconds/);
  assert.equal(spawn.count, 0);
});

test("a job reads its updates, and an agent's jobs filter by status, kind, worker and conversation", async () => {
  const { api } = setup();
  const updates = api.on("GET", "/v1/operations/op_t/updates", json(listing([
    { id: "up_1", job_id: "op_t", agent_id: "ag_c", kind: "before", text: "Emailing the press list now.", tool: "gmail.send_email_message",
      arguments: { to: ["press@acme.com"] }, status: "running", wakeup_id: "wk_9", created_at: "2026-10-01T10:00:00Z" },
    { id: "up_2", job_id: "op_t", agent_id: "ag_c", kind: "blocked", text: "Waiting on an approval.", status: "awaiting_human",
      waiting_on: { kind: "approval", url: null, operation_id: "op_h" }, created_at: "2026-10-01T10:05:00Z" },
  ])));
  const [before, blocked] = await nc.Job.jobFromId("op_t").updates();
  assert.equal(updates.count, 1);
  assert.deepEqual([before.kind, before.tool, before.arguments, before.wakeupId, before.createdAt?.toISOString()],
    ["before", "gmail.send_email_message", { to: ["press@acme.com"] }, "wk_9", "2026-10-01T10:00:00.000Z"]);
  assert.deepEqual([blocked.kind, blocked.waitingOn, blocked.status, blocked.result, blocked.error], ["blocked", { kind: "approval", url: null, operation_id: "op_h" }, "awaiting_human", null, null]);

  api.on("GET", "/v1/agents/ag_u", json(USER_AGENT));
  const jobs = api.on("GET", "/v1/agents/ag_u/jobs", json(listing([TASK])));
  const [job] = await nc.Agent.fromId("ag_u").jobs({ status: ["running", "awaiting_human"], kind: "task", agent: "ag_c", conversation: "launch", limit: 5 });
  const q = jobs.last.query;
  assert.deepEqual([q.get("status"), q.get("kind"), q.get("agent_id"), q.get("conversation"), q.get("limit")],
    ["running,awaiting_human", "agent.task", "ag_c", "launch", "5"]);
  assert.equal(jobs.last.headers.get("NoClick-User"), USER_ID);
  assert.ok(job instanceof nc.Job);
  await nc.Agent.fromId("ag_u").jobs({ kind: "message", status: "live" });
  assert.deepEqual([jobs.last.query.get("kind"), jobs.last.query.get("status")], ["agent.message", "live"]);
  await assert.rejects(nc.Agent.fromId("ag_u").jobs({ kind: "turn" as "task" }), /kind is task or message/);
});

test("Job.list, listPage and summary read only jobs (spawned tasks), and refuse a kind", async () => {
  const { api } = setup();
  const list = api.on("GET", "/v1/operations", json(listing([TASK, { ...TASK, id: "op_t2", status: "succeeded" }], "cur_2")));
  const summary = api.on("GET", "/v1/operations/summary", json({ total: 2, by_status: { running: 1, succeeded: 1 } }));
  const jobs = await nc.Job.list({ status: "live", agent: "ag_c", limit: 2 });
  assert.deepEqual([list.last.query.get("kind"), list.last.query.get("status"), list.last.query.get("agent_id")], ["agent.task", "live", "ag_c"]);
  assert.ok(jobs.every((job) => job instanceof nc.Job));
  assert.deepEqual(jobs.map((job) => job.kind), ["agent.task", "agent.task"]);
  assert.equal(jobs[0].parentConversation, "launch");
  const page = await nc.Job.listPage({ limit: 2 });
  assert.equal(list.last.query.get("kind"), "agent.task");
  assert.ok(page.data[0] instanceof nc.Job);
  assert.equal(page.nextCursor, "cur_2");
  assert.equal((await nc.Job.summary({ status: "live" })).total, 2);
  assert.equal(summary.last.query.get("kind"), "agent.task");
  await assert.rejects(nc.Job.list({ kind: "human.ask" } as nc.KindScopedFilters), /Job.list reads only agent.task/);
  await assert.rejects(nc.Job.listPage({ kind: "human.ask" } as nc.KindScopedFilters), /Job.listPage reads only/);
  await assert.rejects(nc.Job.summary({ kind: "human.ask" } as nc.KindScopedFilters), /Job.summary reads only/);
});

// --- ask --------------------------------------------------------------------------------

test("ask answers from a snapshot by default, or joins the running turn", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const ask = api.on("POST", "/v1/agents/ag_1/ask", json(operation({ id: "op_a", kind: "agent.ask", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_a/wait", json(operation({
    id: "op_a", kind: "agent.ask", status: "succeeded", result: { text: "Two of three launches are in.", conversation: "task", joined: null },
  })));
  const planner = nc.Agent.fromId("ag_1");
  const reply = await planner.ask("How far along are you?", { conversation: "task", user: USER_ID });
  assert.deepEqual(ask.last.body, { question: "How far along are you?", conversation: "task" });
  assert.equal(ask.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual([reply.text, reply.conversation, reply.operationId], ["Two of three launches are in.", "task", "op_a"]);

  await planner.ask("Skip the third; we have enough.", { interject: true });
  assert.deepEqual(ask.last.body, { question: "Skip the third; we have enough.", interject: true });
});

test("interject with nothing running is an ordinary message, and a plan-backed snapshot is not available", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const ask = api.on("POST", "/v1/agents/ag_1/ask", json(operation({ id: "op_m", kind: "agent.message", status: "queued" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_m/wait", json(operation({
    id: "op_m", kind: "agent.message", status: "succeeded", result: { text: "Noted.", conversation: "issue-1", tool_calls: [] },
  })));
  const reply = await nc.Agent.fromId("ag_1").ask("Skip the e2e suite.", { conversation: "issue-1", interject: true });
  assert.deepEqual([reply.text, reply.operationId], ["Noted.", "op_m"]);
  assert.equal(ask.count, 1);

  api.on("POST", "/v1/agents/ag_1/ask", json({ error: {
    type: "not_available", message: "This agent thinks with a Claude or ChatGPT plan, ...", reason: "plan_snapshot",
    next_step: "Ask with interject=True to put the question into its running turn, or message it.",
  } }, { status: 409 }));
  await assert.rejects(nc.Agent.fromId("ag_1").ask("Status?", { conversation: "docs-1" }), nc.NotAvailable);
});

// --- the agents capability ----------------------------------------------------------------

test("the agents capability is \"agents\" whole, or one ref per tool", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/agents", json(AGENT));
  await nc.Agent.create("coordinator", { instructions: "You run the launch.", tools: ["search", new nc.Agents()] });
  assert.deepEqual((create.last.body as { tools: unknown }).tools, ["search", "agents"]);
  await nc.Agent.create("coordinator", { instructions: "You run the launch.", tools: [nc.Agents.only("spawn", "status", "cancel")] });
  assert.deepEqual((create.last.body as { tools: unknown }).tools, ["agents.spawn", "agents.status", "agents.cancel"]);
  assert.deepEqual(nc.Agents.only(...nc.Agents.TOOLS).tools, [...nc.Agents.TOOLS]);
  assert.deepEqual(await nc.Agents.only(...nc.Agents.TOOLS)._toolRefs(), ["agents"]);
  assert.throws(() => nc.Agents.only(), /at least one of spawn, message, ask, status, list, cancel/);
  assert.throws(() => nc.Agents.only("delete" as nc.AgentsTool), /not "delete"/);
});

test("an agent lists the apps that bind it (designed, not built yet)", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json({ ...AGENT, used_by: [{ kind: "project", id: "prj_1", name: "booking", binding: "SUPPORT" }] }));
  const agent = nc.Agent.fromId("ag_1");
  await agent.hydrate();
  assert.deepEqual(agent.usedBy, [{ kind: "project", id: "prj_1", name: "booking", binding: "SUPPORT" }]);
});
