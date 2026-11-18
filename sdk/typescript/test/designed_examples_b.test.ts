// What the examples asked of connections, tools, policy, AI and data (designed, not built yet):
// checkouts, bound arguments, bucket tools, upsert, toolkit callbacks, AI headers and speakers,
// policy rules, queue delivery options and folder commits, against the fetch double.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, operation, setup } from "./helpers.ts";

const GITHUB = { object: "connection", id: "cn_1", name: "github", integration: "github", user_id: null, status: "connected" };
const GMAIL = { ...GITHUB, id: "cn_3", name: "gmail", integration: "gmail" };
const AGENT = { object: "agent", id: "ag_1", name: "assistant", instructions: "hi", tools: [], user_id: null };
const BUCKET = { object: "bucket", id: "bkt_1", name: "uploads", public: false, used_by: [], notifications: [], user_id: null };
const QUEUE = { object: "queue", id: "que_1", name: "new-recordings", depth: 0, in_flight: 0, dead_letter_count: 0, max_attempts: 5 };

const toolResult = (name: string, content: string, extra: Record<string, unknown> = {}) =>
  ({ object: "tool_result", name, content, is_error: false, needs_connection: null, ...extra });

// --- repos in an agent's workspace ------------------------------------------------

test("checkouts say where they go and what may be pushed", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/github", json(GITHUB));
  const github = nc.Connection.fromName("github");
  const docs = github.checkout("acme/docs", { push: "noclick/*" });
  assert.deepEqual([docs.repository, docs.branch, docs.path, docs.push], ["acme/docs", null, null, ["noclick/*"]]);
  assert.equal(github.checkout("acme/api", { path: "refs/api/" }).path, "refs/api");
  assert.deepEqual(await docs._wire(null), { connection: "github", repository: "acme/docs", push: ["noclick/*"] });
  assert.deepEqual(await nc.Repo.fromId("rp_1").checkout({ path: "site", branch: "main" })._wire(null), { repo_id: "rp_1", branch: "main", path: "site" });

  assert.throws(() => github.checkout("docs"), /owner\/name/);
  assert.throws(() => github.checkout("acme/docs", { path: "../etc" }), /under \/workspace/);
  assert.throws(() => github.checkout("acme/docs", { path: "/workspace/docs" }), /under \/workspace/);
  assert.throws(() => github.checkout("acme/docs", { push: [] }), /read-only/);
  // A git endpoint enforces exact branches and prefixes ending in "/*", nothing else.
  for (const bad of ["fix-*", "**", "noclick/*/wip", "*"]) {
    assert.throws(() => github.checkout("acme/docs", { push: ["main", bad] }), /isn't a push pattern/);
  }
  assert.deepEqual(github.checkout("acme/api", { push: ["fix/*", "release-2.4"] }).push, ["fix/*", "release-2.4"]);
});

test("an agent in another scope names the account's connection by id", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/github", json(GITHUB));
  const created = api.on("POST", "/v1/agents", json({ ...AGENT, user_id: "dana" }));
  const github = nc.Connection.fromName("github");
  await nc.asUser("dana", () => nc.Agent.create("docs-writer", { instructions: "Fix the docs.", repos: [github.checkout("acme/docs")] }));
  assert.deepEqual((created.last.body as { repos: unknown }).repos, [{ connection: "connection:cn_1", repository: "acme/docs" }]);
});

// --- bound arguments -------------------------------------------------------------

test("bound operations go out as objects and name only the user", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/gmail", json(GMAIL));
  const agent = api.on("POST", "/v1/agents", json(AGENT));
  const gmail = nc.Connection.fromName("gmail");
  const send = gmail.only("send_email_message").bind({ to: "{{user.email}}" });
  const signed = send.bind({ signature: "{{user.metadata.signature}}" });
  assert.deepEqual(send.bindings, { to: "{{user.email}}" });
  await nc.Agent.create("assistant", { instructions: "hi", tools: [gmail.only("fetch_emails_from_inbox"), signed, "search"] });
  assert.deepEqual((agent.last.body as { tools: unknown }).tools, [
    "gmail.fetch_emails_from_inbox",
    { tool: "gmail.send_email_message", bind: { to: "{{user.email}}", signature: "{{user.metadata.signature}}" } },
    "search",
  ]);
  assert.throws(() => gmail.only("send_email_message").bind({ to: "{{user.phone}}" }), /isn't something NoClick fills in/);
  assert.throws(() => gmail.only("send_email_message").bind({ cc: ["{{secrets.key}}"] }), /isn't something NoClick fills in/);
  assert.throws(() => gmail.only("send_email_message").bind({}), /at least one/);
});

test("tools read back from an agent go out unchanged", async () => {
  const { api } = setup();
  const bound = { tool: "gmail.send_email_message", bind: { to: "{{user.email}}" } };
  const person = { human: { email: "ops@acme.com" }, tools: ["notify", "ask"] };
  api.on("GET", "/v1/agents/ag_1", json({ ...AGENT, tools: ["search", bound, person] }));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({ ...AGENT, tools: ["search", bound, person] }));
  const agent = await nc.Agent.get("ag_1");
  await agent.update({ tools: agent.tools });
  assert.deepEqual((patch.last.body as { tools: unknown }).tools, ["search", bound, person]);
  await assert.rejects(agent.update({ tools: [{ tool: "gmail.send_email_message" }] }), TypeError);
});

test("a database upsert is bound to one table, and a bucket is five tools", async () => {
  const { api } = setup();
  const agent = api.on("POST", "/v1/agents", json(AGENT));
  const leads = nc.Database.fromId("db_1");
  const uploads = nc.Bucket.fromId("bkt_1");
  await nc.Agent.create("researcher", {
    instructions: "hi",
    tools: [leads.only("upsert").bind({ table: "enriched" }), uploads.only("put", "signed_url").bind({ prefix: "users/{{user.id}}/" }), nc.Bucket.fromId("bkt_2")],
  });
  assert.deepEqual((agent.last.body as { tools: unknown }).tools, [
    { tool: "database:db_1.upsert", bind: { table: "enriched" } },
    { tool: "bucket:bkt_1.put", bind: { prefix: "users/{{user.id}}/" } },
    { tool: "bucket:bkt_1.signed_url", bind: { prefix: "users/{{user.id}}/" } },
    "bucket:bkt_2",
  ]);
  await assert.rejects(nc.Agent.create("researcher", { instructions: "hi", tools: [leads.only("upsert")] }), /bind it/);
  assert.throws(() => uploads.only("read" as nc.BucketTool), /objects, head, put, signed_url, remove, not read/);
});

test("a toolkit sends its bound refs with each call", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/gmail", json(GMAIL));
  const call = api.on("POST", "/v1/toolkits/call", json(toolResult("gmail__send_email_message", "sent")));
  const gmail = nc.Connection.fromName("gmail");
  const toolkit = new nc.Toolkit([gmail.only("send_email_message").bind({ to: "{{user.email}}" }), "search", nc.Bucket.fromId("bkt_1")]);
  assert.deepEqual(toolkit.tools, ["gmail.send_email_message", "search", "bkt_1"]);
  await toolkit.call("gmail__send_email_message", { subject: "Hi" });
  assert.deepEqual((call.last.body as { tools: unknown }).tools, [
    { tool: "gmail.send_email_message", bind: { to: "{{user.email}}" } }, "search", "bucket:bkt_1",
  ]);
  await new nc.Toolkit(["gmail", "search"]).call("search", { query: "x" });
  assert.equal("tools" in (call.last.body as object), false);
});

// --- toolkit callbacks -----------------------------------------------------------

test("onConnect gets each result that needs a connection, with its call id", async () => {
  const { api } = setup();
  api.on("POST", "/v1/toolkits/call", (c) => {
    const name = (c.body as { name: string }).name;
    if (name === "calendar__create_event") {
      return json(toolResult(name, "Connect first.", { is_error: true, needs_connection: { integration: "google_calendar", connect_url: "https://noclick.com/c/x" } }));
    }
    if (name === "gmail__send_email") {
      return json(toolResult(name, "Waiting.", { is_error: true, approval_required: { approval_id: "ap_8", request_id: "hr_8", approve_url: "https://noclick.com/h/hr_8", operation: operation({ id: "op_8", kind: "human.approve" }) } }));
    }
    return json(toolResult(name, "found it"));
  });
  const toolkit = new nc.Toolkit(["gmail", "calendar", "search"]);
  const connects: nc.ToolResult[] = [];
  const approvals: nc.ToolResult[] = [];
  await toolkit.handleAnthropic([
    { type: "tool_use", id: "t1", name: "search", input: {} },
    { type: "tool_use", id: "t2", name: "calendar__create_event", input: { title: "Lunch" } },
    { type: "tool_use", id: "t3", name: "gmail__send_email", input: { to: "a@b.c" } },
  ], { onConnect: (r) => void connects.push(r), onApproval: (r) => void approvals.push(r) });
  assert.deepEqual(connects.map((r) => [r.callId, r.arguments, r.connectUrl]), [["t2", { title: "Lunch" }, "https://noclick.com/c/x"]]);
  assert.equal(approvals[0].callId, "t3");
  assert.ok(approvals[0].approval instanceof nc.HumanRequest);
  assert.equal(approvals[0].approval?.id, "op_8");
  assert.equal(approvals[0].approval?.requestId, "hr_8");
  await toolkit.handleOpenAI([{ id: "c1", type: "function", function: { name: "calendar__create_event", arguments: "{}" } }], {
    onConnect: (r) => void connects.push(r),
  });
  assert.equal(connects.at(-1)?.callId, "c1");
  assert.equal((await toolkit.call("search")).callId, null);
});

// --- AI -----------------------------------------------------------------------------

test("AI.headers carry the key and the acting user; transcribe asks for speakers", async () => {
  const { api } = setup();
  assert.deepEqual(await nc.AI.headers(), { Authorization: "Bearer nk_live_test" });
  assert.deepEqual(await nc.asUser("user_42", () => nc.AI.headers()), { Authorization: "Bearer nk_live_test", "NoClick-User": "user_42" });

  const route = api.on("POST", "/v1/ai/transcriptions", json({
    object: "transcript", text: "Hi.", segments: [{ start_s: 0, end_s: 1, text: "Hi.", speaker: "rep" }],
  }));
  const words = await nc.AI.transcribe("https://example.com/demo.mp3", { speakers: ["rep", "customer"] });
  assert.deepEqual(route.last.body, { url: "https://example.com/demo.mp3", speakers: ["rep", "customer"] });
  assert.equal(words.segments[0].speaker, "rep");
  await nc.AI.transcribe(new Uint8Array([73]), { speakers: true });
  assert.equal(route.last.query.get("speakers"), "true");
});

test("a long transcription runs in the background as an operation; a model prices speakers on its own", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/ai/transcriptions",
    json(operation({ id: "op_t", kind: "ai.transcription", status: "running", step: "transcribing" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_t/wait", json(operation({
    id: "op_t", kind: "ai.transcription", status: "succeeded",
    result: { object: "transcript", text: "Hi.", segments: [{ start_s: 0, end_s: 1, text: "Hi.", speaker: "speaker_1" }] },
  })));
  const job = await nc.AI.transcribe("https://example.com/all-hands.mp3", { speakers: true, background: true });
  assert.equal(job.kind, "ai.transcription");
  assert.deepEqual(start.last.body, { url: "https://example.com/all-hands.mp3", speakers: true, background: true });
  assert.equal((await job.wait()).segments[0].speaker, "speaker_1");
  await nc.AI.transcribe(new Uint8Array([73]), { speakers: ["rep", "customer"], background: true });
  assert.deepEqual([start.last.query.get("speakers"), start.last.query.get("background")], ["rep,customer", "true"]);

  api.on("GET", "/v1/ai/models", json(listing([
    { id: "noclick/transcribe-1", kind: "transcription", usd_per_minute: 0.004, usd_per_minute_with_speakers: 0.005 },
    { id: "openrouter/google/gemini-3.5-flash", kind: "transcription", usd_per_minute: 0.006, usd_per_minute_with_speakers: null },
  ])));
  const [ours, flash] = await nc.AI.models({ kind: "transcription" });
  assert.deepEqual([ours.usdPerMinuteWithSpeakers, flash.usdPerMinuteWithSpeakers], [0.005, null]);
});

// --- policy -------------------------------------------------------------------------

const POLICY = {
  object: "policy", user_id: null, allow: [], deny: [], require_approval: [
    "gmail.*", { tool: "stripe.create_refund", when: "args.amount > 10000", approver: { email: "finance@acme.com" } },
    { tool: "calendar.*", approver: { user: true } },
  ],
};

test("rules carry conditions and approvers both ways, and add and remove change one", async () => {
  const { api } = setup();
  const put = api.on("PUT", "/v1/policy", json(POLICY));
  const add = api.on("POST", "/v1/policy/add", json(POLICY));
  const remove = api.on("POST", "/v1/policy/remove", json(POLICY));
  const policy = await nc.Policy.set({
    requireApproval: [
      "gmail.*",
      new nc.Rule("stripe.create_refund", { when: "args.amount > 10000", approver: "finance@acme.com" }),
      { tool: "calendar.*", approver: new nc.Human() },
      new nc.Rule("slack.*", { approver: new nc.Human({ user: "user_42" }) }),
      new nc.Rule("hubspot.*"),
    ],
  });
  assert.deepEqual((put.last.body as { require_approval: unknown }).require_approval, [
    "gmail.*",
    { tool: "stripe.create_refund", when: "args.amount > 10000", approver: { email: "finance@acme.com" } },
    { tool: "calendar.*", approver: { user: true } },
    { tool: "slack.*", approver: { user_id: "user_42" } },
    "hubspot.*",
  ]);
  const refund = policy.requireApproval[1] as nc.Rule;
  assert.deepEqual([refund.tool, refund.when, refund.approver], ["stripe.create_refund", "args.amount > 10000", "finance@acme.com"]);
  assert.ok((policy.requireApproval[2] as nc.Rule).approver instanceof nc.Human);
  await assert.rejects(nc.Policy.set({ deny: [new nc.Rule("gmail.*", { approver: "a@b.c" })] }), /Only a requireApproval rule/);

  await nc.Policy.add([new nc.Rule("quickbooks.create_bill", { when: "args.total_amount > 2500" })]);
  assert.deepEqual(add.last.body, { list: "require_approval", rules: [{ tool: "quickbooks.create_bill", when: "args.total_amount > 2500" }] });
  await nc.asUser("user_42", async () => {
    await nc.Policy.add(["slack.*"], { to: "deny" });
    await nc.Policy.remove(["slack.*"]);
  });
  assert.deepEqual(add.last.body, { list: "deny", rules: ["slack.*"], user_id: "user_42" });
  assert.deepEqual(remove.last.body, { tools: ["slack.*"], user_id: "user_42" });
});

test("evaluate judges one call by its arguments and reports the whole rule", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/policy/evaluate", json({ results: [{
    tool: "stripe.create_refund", verdict: "approval", matched_pattern: "stripe.create_refund", layer: "account",
    rule: POLICY.require_approval[1],
  }] }));
  const [verdict] = await nc.Policy.evaluate("stripe.create_refund", { arguments: { amount: 25000 }, user: "user_42" });
  assert.deepEqual(route.last.body, { tools: ["stripe.create_refund"], arguments: { amount: 25000 }, user_id: "user_42" });
  assert.equal((verdict.rule as nc.Rule).when, "args.amount > 10000");
  await assert.rejects(nc.Policy.evaluate(["a.b", "c.d"], { arguments: {} }), /one tool/);
});

// --- queues and buckets ------------------------------------------------------------------

test("queues dedupe puts, carry a nack's error and drain until empty", async () => {
  const { api, sleeps } = setup();
  const put = api.on("POST", "/v1/queues/que_1/messages", json(listing([{ id: "msg_1" }])));
  const nack = api.on("POST", "/v1/queues/que_1/messages/msg_1/nack", new Response(null, { status: 204 }));
  const take = api.on("GET", "/v1/queues/que_1/messages",
    json(listing([{ object: "queue_message", id: "msg_1", queue_id: "que_1", body: {}, status: "in_flight", attempts: 1, lease_id: "lease_1" }])),
    json(listing([])));
  const jobs = nc.Queue.fromId("que_1");
  assert.equal(await jobs.put({ order: "o_981" }, { dedupeKey: "order-o_981" }), "msg_1");
  assert.deepEqual(put.last.body, { messages: [{ body: { order: "o_981" }, dedupe_key: "order-o_981" }] });
  const drained: nc.QueueMessage[] = [];
  for await (const msg of jobs.iterate({ stopWhenEmpty: true })) drained.push(msg);
  assert.equal(drained.length, 1);
  assert.ok(take.calls.every((c) => !c.query.has("wait_s")));
  assert.deepEqual(sleeps, []);
  await drained[0].nack({ delayS: 30, error: "The invoicing service answered 503" });
  assert.deepEqual(nack.last.body, { lease_id: "lease_1", delay_s: 30, error: "The invoicing service answered 503" });
});

test("a bucket tells a queue about new files", async () => {
  const { api } = setup();
  api.on("GET", "/v1/queues/que_1", json(QUEUE));
  const added = api.on("POST", "/v1/buckets/bkt_1/notifications", json({ ...BUCKET, notifications: [{ queue: "new-recordings", prefix: "calls/" }] }));
  const removed = api.on("POST", "/v1/buckets/bkt_1/notifications/remove", json(BUCKET));
  const bucket = nc.Bucket.fromId("bkt_1");
  await bucket.notify(nc.Queue.fromId("que_1"), { prefix: "calls/" });
  assert.deepEqual(added.last.body, { queue: "new-recordings", prefix: "calls/" });
  assert.deepEqual(bucket.notifications, [{ queue: "new-recordings", prefix: "calls/" }]);
  await bucket.notify("new-recordings", { prefix: "calls/", enabled: false });
  assert.deepEqual(removed.last.body, { queue: "new-recordings", prefix: "calls/" });
});

// --- folder commits ------------------------------------------------------------------------

const sha = (data: string) => createHash("sha1").update(`blob ${Buffer.byteLength(data)}\0${data}`).digest("hex");

test("committing a folder sends only what changed", async () => {
  const { api } = setup();
  const dist = await mkdtemp(join(tmpdir(), "nc-dist-"));
  await mkdir(join(dist, "assets"));
  await mkdir(join(dist, ".git"));
  await writeFile(join(dist, "index.html"), "<h1>Hi</h1>");
  await writeFile(join(dist, "assets", "app.js"), "run()");
  await writeFile(join(dist, "assets", "app.js.map"), "{}");
  await writeFile(join(dist, ".git", "HEAD"), "ref");
  api.on("GET", "/v1/repos/rp_1/branches", json(listing([{ name: "main", head: "abc" }])));
  const files = api.on("GET", "/v1/repos/rp_1/files",
    json(listing([
      { path: "index.html", type: "file", sha: sha("<h1>Hi</h1>") }, { path: "old.html", type: "file", sha: "x" },
      { path: "keep.map", type: "file", sha: "y" },
    ])),
    json(listing([{ path: "index.html", type: "file", sha: sha("<h1>Hi</h1>") }, { path: "assets/app.js", type: "file", sha: sha("run()") }])));
  const commits = api.on("POST", "/v1/repos/rp_1/commits", json({ sha: "def", message: "Rebuild" }));
  const site = nc.Repo.fromId("rp_1");

  const commit = await site.commit(dist, { message: "Rebuild", exclude: ["*.map"] });
  assert.equal(commit?.sha, "def");
  assert.equal(files.last.query.get("recursive"), "true");
  const sent = Object.fromEntries((commits.last.body as { files: { path: string }[] }).files.map((f) => [f.path, f]));
  assert.deepEqual(sent, {
    "assets/app.js": { path: "assets/app.js", content: "cnVuKCk=", encoding: "base64" },
    "old.html": { path: "old.html", delete: true },
  });
  assert.equal(await site.commit(dist, { message: "Again", exclude: ["*.map"] }), null);
  assert.equal(commits.count, 1);
});
