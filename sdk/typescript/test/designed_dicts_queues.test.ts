// Dicts, queues and the OnQueue trigger (built; their exports designed): the routes, bodies and
// parsed results the TypeScript client sends and reads, against the fetch double.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, operation, setup, trashed } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const SEEN = {
  object: "dict", id: "dct_1", name: "processed-orders", key_count: 18240, size_bytes: 2411520,
  used_by: [{ kind: "project", id: "prj_1", name: "booking", binding: "SEEN" }], user_id: null, created_at: "2026-09-25T10:00:00Z",
};
const JOBS = {
  object: "queue", id: "que_1", name: "invoices", depth: 14, in_flight: 2, dead_letter_count: 1, max_attempts: 5,
  used_by: [{ kind: "agent", id: "ag_1", name: "support-bot", binding: null }], user_id: null, created_at: "2026-09-25T10:00:00Z",
};
const AGENT = {
  object: "agent", id: "ag_1", name: "support-bot", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: 50,
  created_at: "2026-09-25T10:00:00Z",
};

const item = (key: string, value: unknown, extra: Record<string, unknown> = {}) => ({
  object: "dict_item", key, value, expires_at: null, updated_at: "2026-09-26T09:00:00Z", size_bytes: 24, ...extra,
});
const missing = (key: string) => apiError(404, "not_found", `No key ${key}.`, { key });
const message = (id = "msg_1", extra: Record<string, unknown> = {}) => ({
  object: "queue_message", id, queue_id: "que_1", body: { invoice: "INV-1042" }, status: "in_flight", attempts: 1,
  enqueued_at: "2026-09-26T09:00:00Z", visible_at: null, lease_expires_at: "2026-09-26T09:02:00Z", last_error: null,
  dead_lettered_at: null, lease_id: `lease_${id}`, ...extra,
});
const empty = () => new Response(null, { status: 204 });

// --- dicts ----------------------------------------------------------------------

test("Dict.create, list and fromName", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/dicts", json({ ...SEEN, id: "dct_2", name: "feature-flags" }), json({ ...SEEN, id: "dct_9", name: "cache" }));
  const lookup = api.on("GET", "/v1/dicts", json(listing([SEEN], "c2")), json(listing([{ ...SEEN, name: "cache-old" }])), json(listing([])));

  await nc.asUser("acme", () => nc.Dict.create("feature-flags"));
  assert.deepEqual(create.last.body, { name: "feature-flags" });
  assert.equal(create.last.headers.get("NoClick-User"), "acme");

  const page = await nc.Dict.listPage({ userFilter: nc.ALL_USERS, limit: 10 });
  assert.deepEqual([lookup.last.query.get("user_id"), page.nextCursor], ["all", "c2"]);
  const [first] = page.data;
  assert.deepEqual([first.keyCount, first.sizeBytes, first.usedBy[0].binding, first.createdAt?.getUTCFullYear(), first.consoleUrl], [18240, 2411520, "SEEN", 2026, null]);

  const lazy = nc.Dict.fromName("cache", { createIfMissing: true });
  assert.equal(lazy.name, "cache");
  await lazy.hydrate();
  assert.equal(lazy.id, "dct_9"); // an exact name only: the near miss isn't it
  assert.equal(lookup.last.query.get("name"), "cache");
  await assert.rejects(nc.Dict.fromName("cache").hydrate(), (err: unknown) => err instanceof nc.NotFound && /createIfMissing/.test(String(err)));
});

test("get, has, put, putIfAbsent, increment, update, pop and remove", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/dicts/dct_1/items/o_1841", json(item("o_1841", { status: "refunded" })));
  api.on("GET", "/v1/dicts/dct_1/items/o_1842", missing("o_1842"));
  const put = api.on("PUT", "/v1/dicts/dct_1/items/lock%3Anightly", json({ key: "lock:nightly", written: true }), json({ key: "lock:nightly", written: false }));
  const bump = api.on("POST", "/v1/dicts/dct_1/items/visits/increment", json({ key: "visits", value: 42 }));
  const many = api.on("POST", "/v1/dicts/dct_1/items", json({ written: 2 }));
  api.on("DELETE", "/v1/dicts/dct_1/items/o_1841", json(item("o_1841", { status: "refunded" })));
  api.on("DELETE", "/v1/dicts/dct_1/items/o_1842", missing("o_1842"));
  api.on("GET", "/v1/dicts/dct_1", json({ ...SEEN, key_count: 3 }));
  api.on("GET", "/v1/dicts/dct_404/items/a", apiError(404, "not_found", "No such dict."));
  const seen = nc.Dict.fromId("dct_1", { user: USER_ID });

  assert.deepEqual(await seen.get("o_1841"), { status: "refunded" });
  assert.equal(read.last.headers.get("NoClick-User"), USER_ID);
  assert.equal(await seen.get("o_1842"), undefined);
  assert.deepEqual([await seen.has("o_1841"), await seen.has("o_1842")], [true, false]);
  await assert.rejects(nc.Dict.fromId("dct_404").get("a"), nc.NotFound); // a missing dict is not a missing key

  await seen.put("lock:nightly", "worker-3", { ttlS: 300 });
  assert.deepEqual(put.last.body, { value: "worker-3", ttl_s: 300 });
  assert.equal(await seen.putIfAbsent("lock:nightly", "worker-4"), false);
  assert.deepEqual(put.last.body, { value: "worker-4", if_absent: true });
  await seen.put("lock:nightly", null);
  assert.deepEqual(put.last.body, { value: null });
  await assert.rejects(seen.put("x", undefined), TypeError);
  await assert.rejects(seen.put("", 1), TypeError);

  assert.equal(await seen.increment("visits"), 42);
  assert.deepEqual(bump.last.body, { by: 1 });
  await seen.increment("visits", { by: -5, ttlS: 3600 });
  assert.deepEqual(bump.last.body, { by: -5, ttl_s: 3600 });
  await assert.rejects(seen.increment("visits", { by: 1.5 }), TypeError);

  await seen.update({ a: 1, b: [2] }, { ttlS: 60 });
  assert.deepEqual(many.last.body, { items: [{ key: "a", value: 1, ttl_s: 60 }, { key: "b", value: [2], ttl_s: 60 }] });
  await seen.update(new Map([["c", null]]));
  assert.deepEqual(many.last.body, { items: [{ key: "c", value: null }] });

  assert.deepEqual(await seen.pop("o_1841"), { status: "refunded" });
  assert.equal(await seen.pop("o_1842"), undefined);
  assert.deepEqual([await seen.remove("o_1841"), await seen.remove("o_1842")], [true, false]);
  assert.deepEqual([await seen.size(), seen.keyCount], [3, 3]);
});

test("keys, items and itemsPage page through in key order", async () => {
  const { api } = setup();
  const pages = api.on("GET", "/v1/dicts/dct_1/items", (call: Call) =>
    json(call.query.get("cursor") ? listing([item("o_3", 3)]) : listing([item("o_1", 1, { expires_at: "2026-09-27T00:00:00Z" }), item("o_2", 2)], "c2")),
  );
  const seen = nc.Dict.fromId("dct_1");

  assert.deepEqual(await seen.keys({ prefix: "o_" }), ["o_1", "o_2", "o_3"]);
  assert.deepEqual([pages.calls[0].query.get("prefix"), pages.calls[0].query.get("view"), pages.calls[1].query.get("cursor")], ["o_", "keys", "c2"]);
  const items = await seen.items({ limit: 2 });
  assert.deepEqual([pages.last.query.get("view"), pages.last.query.get("limit")], [null, "2"]);
  assert.deepEqual(items.map((i) => [i.key, i.value]), [["o_1", 1], ["o_2", 2]]);
  assert.deepEqual([items[0].expiresAt?.getUTCDate(), items[1].expiresAt, items[0].sizeBytes], [27, null, 24]);
  const page = await seen.itemsPage({ prefix: "o_", limit: 2 });
  assert.deepEqual([page.nextCursor, page.data[0].key], ["c2", "o_1"]);
});

test("clear, export and delete", async () => {
  const { api } = setup();
  const clear = api.on("POST", "/v1/dicts/dct_1/clear", json({ removed: 18240, operation_id: "op_clear" }));
  api.on("POST", "/v1/dicts/dct_1/export", json(operation({
    kind: "dict.export", status: "succeeded",
    result: { url: "https://exports.example.com/processed-orders.zip", expires_at: null, contents: [], remaining_dependencies: [] },
  })));
  api.on("DELETE", "/v1/dicts/dct_1", apiError(409, "conflict", "The booking app binds processed-orders as SEEN."));
  const seen = nc.Dict.fromId("dct_1");
  assert.equal((await seen.clear()).id, "op_clear");
  assert.equal(clear.count, 1);
  assert.match(String((await (await seen.export()).wait()).url), /processed-orders\.zip$/);
  await assert.rejects(seen.delete(), nc.Conflict);
});

// --- queues ---------------------------------------------------------------------

test("Queue.create, list, and fromName converging maxAttempts", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/queues", json({ ...JOBS, id: "que_2", name: "erp-exports", max_attempts: 10 }));
  api.on("GET", "/v1/queues", json(listing([JOBS], "c2")), json(listing([JOBS])), json(listing([JOBS])), json(listing([])));
  const patch = api.on("PATCH", "/v1/queues/que_1", json({ ...JOBS, max_attempts: 8 }));

  assert.equal((await nc.Queue.create("erp-exports", { maxAttempts: 10 })).maxAttempts, 10);
  assert.deepEqual(create.last.body, { name: "erp-exports", max_attempts: 10 });
  await nc.Queue.create("invoices");
  assert.deepEqual(create.last.body, { name: "invoices", max_attempts: 5 });

  const [first] = (await nc.Queue.listPage({ userFilter: nc.ALL_USERS })).data;
  assert.deepEqual([first.depth, first.inFlight, first.deadLetterCount, first.usedBy[0].kind, first.usedBy[0].binding], [14, 2, 1, "agent", null]);

  assert.equal((await nc.Queue.fromName("invoices", { createIfMissing: true }).hydrate()).maxAttempts, 5);
  assert.equal(patch.count, 0); // nothing passed: left as it is
  assert.equal((await nc.Queue.fromName("invoices", { createIfMissing: true, maxAttempts: 8 }).hydrate()).maxAttempts, 8);
  assert.deepEqual(patch.last.body, { max_attempts: 8 });
  await nc.Queue.fromName("webhook-buffer", { createIfMissing: true }).hydrate();
  assert.deepEqual(create.last.body, { name: "webhook-buffer", max_attempts: 5 });
});

test("put, putMany, get with a lease, ack and nack", async () => {
  const { api } = setup();
  const post = api.on("POST", "/v1/queues/que_1/messages", (call: Call) =>
    json(listing((call.body as { messages: unknown[] }).messages.map((_, i) => ({ object: "queue_message", id: `msg_${i + 1}` })))),
  );
  const take = api.on("GET", "/v1/queues/que_1/messages", json(listing([message()])), json(listing([])));
  const ack = api.on("POST", "/v1/queues/que_1/messages/msg_1/ack", empty());
  const nack = api.on("POST", "/v1/queues/que_1/messages/msg_1/nack", empty());
  const jobs = nc.Queue.fromId("que_1", { user: USER_ID });

  assert.equal(await jobs.put({ invoice: "INV-1042" }), "msg_1");
  assert.deepEqual(post.last.body, { messages: [{ body: { invoice: "INV-1042" } }] });
  await jobs.put("later", { delayS: 3600 });
  assert.deepEqual(post.last.body, { messages: [{ body: "later", delay_s: 3600 }] });
  assert.deepEqual(await jobs.putMany(["a", "b"]), ["msg_1", "msg_2"]);

  const msg = await jobs.get({ timeoutS: 30, leaseS: 120 });
  assert.ok(msg);
  assert.deepEqual([take.last.query.get("wait_s"), take.last.query.get("lease_s"), take.last.query.get("limit")], ["30", "120", "1"]);
  assert.deepEqual([msg.body, msg.attempts, msg.status, msg.queueId, msg.leaseExpiresAt?.getUTCMinutes()], [{ invoice: "INV-1042" }, 1, "in_flight", "que_1", 2]);
  await msg.ack();
  assert.deepEqual(ack.last.body, { lease_id: "lease_msg_1" });
  await msg.nack({ delayS: 60 });
  assert.deepEqual(nack.last.body, { lease_id: "lease_msg_1", delay_s: 60 });
  const release = api.on("POST", "/v1/queues/que_1/messages/msg_1/release", empty());
  await msg.release({ delayS: 3600 }); // handed back without spending an attempt
  assert.deepEqual(release.last.body, { lease_id: "lease_msg_1", delay_s: 3600 });
  assert.equal(await jobs.get(), null);
  assert.equal(take.last.query.get("wait_s"), null);
});

test("iterate long-polls until you stop", async () => {
  const { api, sleeps } = setup();
  const take = api.on("GET", "/v1/queues/que_1/messages", json(listing([message("msg_1")])), json(listing([])), json(listing([message("msg_2"), message("msg_3")])));
  const taken: string[] = [];
  for await (const msg of nc.Queue.fromId("que_1").iterate({ leaseS: 90 })) {
    taken.push(msg.id);
    if (taken.length === 3) break;
  }
  assert.deepEqual(taken, ["msg_1", "msg_2", "msg_3"]);
  assert.deepEqual([...new Set(take.calls.map((c) => c.query.get("wait_s")))], ["25"]);
  assert.equal(take.calls[0].query.get("lease_s"), "90");
  assert.equal(sleeps.length, 1); // the empty poll didn't spin
});

test("peek, dead letters, retry and discard", async () => {
  const { api } = setup();
  const peek = api.on("GET", "/v1/queues/que_1/messages", json(listing([message("msg_5", { status: "waiting", lease_id: null })])));
  api.on("GET", "/v1/queues/que_1/dead_letters", json(listing([message("msg_7", { status: "dead", attempts: 5, lease_id: null, last_error: "Stripe says the invoice doesn't exist.", dead_lettered_at: "2026-09-26T08:00:00Z" })])));
  const retry = api.on("POST", "/v1/queues/que_1/dead_letters/msg_7/retry", empty());
  const discard = api.on("DELETE", "/v1/queues/que_1/dead_letters/msg_7", empty());
  const jobs = nc.Queue.fromId("que_1");

  const [waiting] = await jobs.peek({ limit: 5 });
  assert.deepEqual([peek.last.query.get("view"), peek.last.query.get("limit"), waiting.status], ["peek", "5", "waiting"]);
  await assert.rejects(waiting.ack(), (err: unknown) => err instanceof nc.InvalidRequest && /isn't leased/.test(String(err)));
  const [letter] = await jobs.deadLetters();
  assert.deepEqual([letter.attempts, letter.status, letter.deadLetteredAt?.getUTCHours()], [5, "dead", 8]);
  assert.match(String(letter.lastError), /doesn't exist/);
  await letter.retry();
  await letter.discard();
  assert.deepEqual([retry.count, discard.count], [1, 1]);
});

test("size, depthHistory, update, clear, export and delete", async () => {
  const { api } = setup();
  api.on("GET", "/v1/queues/que_1", json({ ...JOBS, depth: 16 }));
  const history = api.on("GET", "/v1/queues/que_1/depth", json(listing([
    { at: "2026-09-26T08:00:00Z", depth: 3, in_flight: 1 }, { at: "2026-09-26T08:15:00Z", depth: 16, in_flight: 2 },
  ])));
  const patch = api.on("PATCH", "/v1/queues/que_1", json({ ...JOBS, max_attempts: 10 }));
  const clear = api.on("POST", "/v1/queues/que_1/clear", json({ removed: 15 }));
  api.on("POST", "/v1/queues/que_1/export", json(operation({
    kind: "queue.export", status: "succeeded",
    result: { url: "https://exports.example.com/invoices.zip", expires_at: null, contents: [], remaining_dependencies: [] },
  })));
  const del = api.on("DELETE", "/v1/queues/que_1", json(trashed("queue", "que_1", "invoices")));
  const jobs = nc.Queue.fromId("que_1");

  assert.deepEqual([await jobs.size(), jobs.depth], [16, 16]);
  const points = await jobs.depthHistory({ hours: 6 });
  assert.equal(history.last.query.get("hours"), "6");
  assert.deepEqual(points.map((p) => [p.depth, p.inFlight]), [[3, 1], [16, 2]]);
  assert.equal((await jobs.update({ maxAttempts: 10 })).maxAttempts, 10);
  assert.deepEqual(patch.last.body, { max_attempts: 10 });
  await jobs.clear();
  assert.match(String((await (await jobs.export()).wait()).url), /invoices\.zip$/);
  assert.equal((await jobs.delete()).name, "invoices");
  assert.deepEqual([clear.count, del.count], [1, 1]);
});

// --- the OnQueue trigger ----------------------------------------------------------

test("OnQueue wires by name, creating a lazy queue first", async () => {
  const { api } = setup();
  api.on("GET", "/v1/queues", json(listing([])));
  const createQueue = api.on("POST", "/v1/queues", json(JOBS));
  const create = api.on("POST", "/v1/agents", json(AGENT));
  await nc.Agent.create("support-bot", {
    instructions: "You chase unpaid invoices.",
    triggers: [
      new nc.OnQueue(nc.Queue.fromName("invoices", { createIfMissing: true }), { message: "Chase this unpaid invoice." }),
      new nc.OnQueue("webhook-buffer", { batchSize: 10 }),
    ],
  });
  assert.equal(createQueue.count, 1);
  assert.deepEqual((create.last.body as { triggers: unknown }).triggers, [
    { kind: "queue", queue: "invoices", batch_size: 1, message: "Chase this unpaid invoice." },
    { kind: "queue", queue: "webhook-buffer", batch_size: 10 },
  ]);
  assert.throws(() => new nc.OnQueue(42 as unknown as string), TypeError);
  assert.throws(() => new nc.OnQueue("invoices", { batchSize: 0 }), RangeError);
});

test("an agent's queue trigger reads back", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/triggers", json(listing([{
    object: "agent_trigger", id: "tr_9", kind: "queue", spec: { queue: "invoices", batch_size: 1, message: null }, status: "active",
    url: null, next_run: null, last_fired_at: "2026-09-26T09:00:00Z", error: null, created_at: "2026-09-20T10:00:00Z",
  }])));
  const [trigger] = await nc.Agent.fromId("ag_1").triggers();
  assert.deepEqual([trigger.kind, trigger.spec.queue, trigger.spec.batch_size, trigger.lastFiredAt?.getUTCHours()], ["queue", "invoices", 1, 9]);
});
