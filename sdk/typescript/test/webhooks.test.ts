// Webhooks and events against the mock API (routes, bodies, user headers, parsed results), plus
// Webhook.verify on real signatures, and agents and channels hearing NoClick's events.
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";
import { inspect } from "node:util";

import * as nc from "../src/index.ts";
import { USER_ID, json, listing, setup } from "./helpers.ts";

const SECRET = "nk_whsec_3f9c2a7e5b1d4c8a";
const HOOK = {
  object: "webhook", id: "wh_1", url: "https://api.yourco.test/noclick/events", events: ["operation.succeeded", "human.answered"],
  enabled: true, status: "healthy", description: "Production receiver", success_rate_24h: 0.998, last_failure: null,
  user_id: null, created_at: "2026-09-25T10:00:00Z",
};
const DELIVERY = {
  object: "webhook_delivery", id: "whd_1", webhook_id: "wh_1", event_id: "evt_1", event_type: "operation.failed",
  status: "retrying", attempts: 3, response_status: 502, response_body: "Bad gateway", request_body: '{"id":"evt_1"}',
  duration_ms: 10004, next_retry_at: "2026-09-25T12:00:00Z", created_at: "2026-09-25T10:00:00Z",
};
const EVENT = {
  object: "event", id: "evt_1", type: "operation.failed", user_id: USER_ID,
  data: { object: "operation", id: "op_9", kind: "agent.message", status: "failed" }, created_at: "2026-09-25T10:00:00Z",
};

function signed(payload: string, secret = SECRET, at = Math.floor(Date.now() / 1000)): Record<string, string> {
  const mac = createHmac("sha256", secret).update(`${at}.${payload}`).digest("hex");
  return { "content-type": "application/json", "noclick-signature": `t=${at},v1=${mac}` };
}

// --- webhooks ------------------------------------------------------------------

test("Webhook.fromName owns the endpoint in code and reveals its secret", async () => {
  const { api } = setup();
  const url = HOOK.url;
  const lookup = api.on("GET", "/v1/webhooks", json(listing([])), json(listing([HOOK])));
  const create = api.on("POST", "/v1/webhooks", json({ ...HOOK, secret: SECRET }));
  const patch = api.on("PATCH", "/v1/webhooks/wh_1", json({ ...HOOK, events: ["operation.*"] }));
  const reveal = api.on("GET", "/v1/webhooks/wh_1/secret", json({ object: "webhook_secret", secret: SECRET }));
  const made = await nc.Webhook.fromName(url, { createIfMissing: true, events: ["operation.succeeded", "human.answered"] }).hydrate();
  assert.equal(made.secret, SECRET);
  assert.equal(lookup.last.query.get("url"), url);
  assert.deepEqual(create.last.body, { url, events: ["operation.succeeded", "human.answered"] });
  const found = await nc.Webhook.fromName(url, { createIfMissing: true, events: ["operation.*"] }).hydrate();
  assert.deepEqual([found.id, create.count, patch.last.body], ["wh_1", 1, { events: ["operation.*"] }]);
  assert.equal(found.secret, null);
  assert.equal(await found.revealSecret(), SECRET);
  assert.deepEqual([found.secret, reveal.count], [SECRET, 1]);
  assert.throws(() => nc.Webhook.fromName(url, { createIfMissing: true }), /events/);
});

test("Webhook.create shows the secret once and never prints it", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/webhooks", json({ ...HOOK, secret: SECRET }));
  api.on("GET", "/v1/webhooks/wh_1", json(HOOK));
  const hook = await nc.Webhook.create("https://api.yourco.test/noclick/events", {
    events: ["operation.succeeded", "human.answered"], description: "Production receiver",
  });
  assert.deepEqual(create.last.body, { url: "https://api.yourco.test/noclick/events", events: ["operation.succeeded", "human.answered"], description: "Production receiver" });
  assert.equal(create.last.headers.get("NoClick-User"), null);
  assert.ok(create.last.headers.get("Idempotency-Key"));
  assert.deepEqual([hook.secret, hook.status, hook.successRate24h, hook.enabled], [SECRET, "healthy", 0.998, true]);
  assert.ok(!inspect(hook).includes(SECRET));
  assert.equal((await nc.Webhook.get("wh_1")).secret, null);
});

test("a user's webhook is created for that user, and acts for it after", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/webhooks", json({ ...HOOK, user_id: USER_ID }));
  const hook = await nc.asUser("acme", () => nc.Webhook.create("https://api.yourco.test/acme", { events: ["connection.*"] }));
  assert.equal(create.last.headers.get("NoClick-User"), "acme");
  const del = api.on("DELETE", "/v1/webhooks/wh_1", new Response(null, { status: 204 }));
  await hook.delete();
  assert.equal(del.last.headers.get("NoClick-User"), USER_ID);
});

test("list, update, rotateSecret", async () => {
  const { api } = setup();
  const list = api.on("GET", "/v1/webhooks", json(listing([HOOK, { ...HOOK, id: "wh_2", status: "failing", last_failure: { response_status: 500 } }])));
  const patch = api.on("PATCH", "/v1/webhooks/wh_1", json({ ...HOOK, enabled: false, status: "disabled" }));
  const rotate = api.on("POST", "/v1/webhooks/wh_1/rotate_secret", json({ ...HOOK, secret: "nk_whsec_new" }));
  const [first, failing] = await nc.Webhook.list({ userFilter: nc.ALL_USERS, limit: 10 });
  assert.equal(list.last.query.get("user_id"), "all");
  assert.deepEqual([failing.status, failing.lastFailure], ["failing", { response_status: 500 }]);

  await first.update({ enabled: false, events: ["operation.*"] });
  assert.deepEqual(patch.last.body, { enabled: false, events: ["operation.*"] });
  assert.equal(first.status, "disabled");
  await first.update({ description: null });
  assert.deepEqual(patch.last.body, { description: null });

  assert.equal(await first.rotateSecret({ graceS: 0 }), "nk_whsec_new");
  assert.deepEqual(rotate.last.body, { grace_s: 0 });
  assert.equal(first.secret, "nk_whsec_new");
});

test("test, deliveries and redeliver", async () => {
  const { api } = setup();
  const send = api.on("POST", "/v1/webhooks/wh_1/test", json({ ...DELIVERY, id: "whd_t", status: "succeeded", attempts: 1, response_status: 204 }));
  const deliveries = api.on("GET", "/v1/webhooks/wh_1/deliveries", json(listing([DELIVERY])));
  const redeliver = api.on("POST", "/v1/webhooks/wh_1/deliveries/whd_1/redeliver", json({ ...DELIVERY, status: "succeeded", attempts: 4, response_status: 200 }));
  const hook = nc.Webhook.fromId("wh_1");

  const sent = await hook.test("human.answered");
  assert.deepEqual(send.last.body, { event_type: "human.answered" });
  assert.deepEqual([sent.status, sent.ok, sent.responseStatus], ["succeeded", true, 204]);
  await hook.test();
  assert.deepEqual(send.last.body, { event_type: "operation.succeeded" });

  const [missed] = await hook.deliveries({ status: ["retrying", "failed"], event: nc.Event.fromId("evt_1"), limit: 5 });
  assert.deepEqual([deliveries.last.query.get("status"), deliveries.last.query.get("event_id"), deliveries.last.query.get("limit")], ["retrying,failed", "evt_1", "5"]);
  assert.deepEqual([missed.attempts, missed.responseStatus, missed.ok, missed.durationMs], [3, 502, false, 10004]);
  assert.equal(missed.nextRetryAt?.toISOString(), "2026-09-25T12:00:00.000Z");

  assert.deepEqual([(await hook.redeliver(missed)).attempts, redeliver.count], [4, 1]);
  await hook.redeliver("whd_1");
  assert.equal(redeliver.count, 2);
});

// --- verifying a delivery ------------------------------------------------------

test("Webhook.verify returns the signed body's event", async () => {
  const payload = JSON.stringify(EVENT);
  const event = await nc.Webhook.verify(payload, signed(payload), SECRET);
  assert.ok(event instanceof nc.Event);
  assert.deepEqual([event.id, event.type, event.userId, event.data.id], ["evt_1", "operation.failed", USER_ID, "op_9"]);
  // Bytes and fetch's Headers verify too.
  const bytes = new TextEncoder().encode(payload);
  assert.equal((await nc.Webhook.verify(bytes, new Headers(signed(payload)), SECRET)).id, "evt_1");
  assert.equal((await nc.Webhook.verify(bytes.buffer, signed(payload), SECRET)).id, "evt_1");
});

test("Webhook.verify takes either secret while rotating", async () => {
  const payload = JSON.stringify(EVENT);
  const at = Math.floor(Date.now() / 1000);
  const old = signed(payload, "nk_whsec_old", at)["noclick-signature"];
  const fresh = signed(payload, "nk_whsec_new", at)["noclick-signature"].split(",")[1];
  const both = { "NoClick-Signature": `${old},${fresh}` };
  assert.equal((await nc.Webhook.verify(payload, both, "nk_whsec_new")).id, "evt_1");
  assert.equal((await nc.Webhook.verify(payload, both, "nk_whsec_old")).id, "evt_1");
  assert.equal((await nc.Webhook.verify(payload, signed(payload, "nk_whsec_old"), ["nk_whsec_new", "nk_whsec_old"])).id, "evt_1");
});

test("Webhook.verify refuses what it can't prove", async () => {
  const payload = JSON.stringify(EVENT);
  const now = Math.floor(Date.now() / 1000);
  const cases: [string, Record<string, string>, string, RegExp][] = [
    [payload, {}, SECRET, /no NoClick-Signature/],
    [payload, { "NoClick-Signature": "sha256=abc" }, SECRET, /isn't t=<timestamp>/],
    [payload, signed(payload, SECRET, now - 301), SECRET, /more than the 300s/],
    [payload, signed(payload), "nk_whsec_wrong", /No signature matches/],
    [payload.replace("failed", "succeeded"), signed(payload), SECRET, /No signature matches/],
  ];
  for (const [body, headers, secret, message] of cases) {
    await assert.rejects(nc.Webhook.verify(body, headers, secret), (err: unknown) => {
      assert.ok(err instanceof nc.WebhookSignatureError);
      assert.equal(err.type, "webhook_signature_invalid");
      assert.match(err.message, message);
      return true;
    });
  }
  assert.equal((await nc.Webhook.verify(payload, signed(payload, SECRET, now - 600), SECRET, { toleranceS: 900 })).id, "evt_1");
});

// --- events --------------------------------------------------------------------

test("Event.list filters, and reads across users with userFilter", async () => {
  const { api } = setup();
  const list = api.on("GET", "/v1/events", json(listing([EVENT], "c2")));
  const page = await nc.Event.listPage({ type: ["operation.failed", "domain.*"], since: new Date("2026-09-20T00:00:00Z"), userFilter: nc.ALL_USERS, limit: 1 });
  assert.deepEqual(
    ["type", "since", "user_id", "limit"].map((k) => list.last.query.get(k)),
    ["operation.failed,domain.*", "2026-09-20T00:00:00.000Z", "all", "1"],
  );
  assert.equal(list.last.headers.get("NoClick-User"), null);
  assert.deepEqual([page.nextCursor, page.data[0].type], ["c2", "operation.failed"]);

  await nc.asUser("user_42", () => nc.Event.list({ type: "human.answered", limit: 1 }));
  assert.equal(list.last.headers.get("NoClick-User"), "user_42");
});

test("an event's full view carries its deliveries", async () => {
  const { api } = setup();
  const full = api.on("GET", "/v1/events/evt_1", json({ ...EVENT, deliveries: [DELIVERY] }));
  const event = await nc.Event.get("evt_1");
  assert.deepEqual(event.deliveries.map((d) => [d.webhookId, d.status]), [["wh_1", "retrying"]]);
  assert.equal(full.count, 1);
});

test("Event.types is the catalog, the same for every user", async () => {
  const { api } = setup();
  const types = api.on("GET", "/v1/events/types", json(listing([
    { name: "operation.succeeded", description: "An operation finished.", emitted: true },
    { name: "card.authorization.requested", description: "A card purchase waits for approval.", emitted: false },
  ])));
  const catalog = await nc.asUser("acme", () => nc.Event.types());
  assert.equal(types.last.headers.get("NoClick-User"), null);
  assert.deepEqual(catalog.map((t) => [t.name, t.area, t.emitted]), [
    ["operation.succeeded", "operation", true], ["card.authorization.requested", "card", false]]);
});

// --- agents and channels hearing NoClick's events ---------------------------------

test("an agent's trigger on a NoClick event", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json({ object: "agent", id: "ag_1", name: "triage", user_id: null }));
  const add = api.on("POST", "/v1/agents/ag_1/triggers", json({
    object: "agent_trigger", id: "tr_1", agent_id: "ag_1", kind: "platform",
    spec: { type: "operation.failed", filters: { kind: "agent.task" }, message: "Find out why." },
    status: "active", url: null, next_run: null, last_fired_at: null, error: null, created_at: "2026-10-01T10:00:00Z",
  }));
  const added = await nc.Agent.fromId("ag_1").addTrigger(
    new nc.OnPlatformEvent("operation.failed", { filters: { kind: "agent.task" }, message: "Find out why." }));
  assert.deepEqual(add.last.body, { kind: "platform", type: "operation.failed", filters: { kind: "agent.task" }, message: "Find out why." });
  assert.deepEqual([added.kind, added.defined, added.spec.type], ["platform", true, "operation.failed"]);
});

test("a channel subscribes to NoClick events", async () => {
  const { api } = setup();
  const subscribe = api.on("POST", "/v1/channels/ch_1/subscriptions", json({
    object: "subscription", id: "sub_1", channel_id: "ch_1", workspace_id: null, channels: null,
    source: { kind: "platform", type: "operation.failed" }, wake: null, filters: { kind: "agent.task" },
    status: "active", error: null, url: null, last_event_at: null, created_at: "2026-10-01T10:00:00Z",
  }));
  const room = nc.Channel.fromId("ch_1");
  await room.subscribe("operation.failed", { filters: { kind: "agent.task" } });
  assert.deepEqual(subscribe.last.body, { source: { kind: "platform", type: "operation.failed" }, wake: null, filters: { kind: "agent.task" } });
  await room.subscribe(new nc.OnPlatformEvent("operation.failed", { filters: { kind: "agent.task" }, message: "Look." }));
  assert.deepEqual(subscribe.last.body, {
    source: { kind: "platform", type: "operation.failed", message: "Look." }, wake: null, filters: { kind: "agent.task" },
  });
  await assert.rejects(room.subscribe(new nc.OnPlatformEvent("operation.failed", { filters: { kind: "x" } }), { filters: { kind: "y" } }), TypeError);
  await assert.rejects(room.subscribe(new nc.OnPlatformEvent("operation.failed", { conversation: "c-{data.id}" })), TypeError);
});
