// Triggers, channel subscriptions and the events catalog against the mock API: `OnWebhook` and
// `OnEvent` on an agent (create, convergence from a definition, `triggers`/`addTrigger`/
// `removeTrigger`), `channel.subscribe`/`subscriptions`/`unsubscribe`, an app's posts in a room, and
// `connection.events()`.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, setup } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: 50,
  created_at: "2026-10-01T10:00:00Z",
};

function trigger(id: string, kind: string, spec: Record<string, unknown>, fields: Record<string, unknown> = {}) {
  return {
    object: "agent_trigger", id, agent_id: "ag_1", kind, spec, status: "active", url: null, next_run: null, last_fired_at: null,
    error: null, created_at: "2026-10-01T10:00:00Z", ...fields,
  };
}

const WEBHOOK = trigger("tr_2", "webhook", { name: "orders" }, { url: "https://wh_1.example.com" });
const EVENT = trigger("tr_5", "event", { connection: "slack", event: "channel_message", filters: { channel: "C1" } }, {
  status: "error", error: "The 'slack' connection isn't connected yet, so this hears nothing.",
});
const EMAIL = trigger("tr_3", "email", { inbox_id: "inb_1", address: "help@acme.test" });
const SUB = {
  object: "subscription", id: "sub_1", channel_id: "ch_1", workspace_id: null, channels: null,
  source: { kind: "event", connection: "stripe", event: "invoice_payment_failed", filters: {} }, wake: "all", filters: null,
  status: "active", error: null, url: null, last_event_at: null, created_at: "2026-10-01T09:00:00Z",
};

test("create sends webhook and event triggers", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/slack", json({ object: "connection", id: "cn_1", name: "slack", integration: "slack", status: "connected" }));
  const create = api.on("POST", "/v1/agents", json(AGENT));
  await nc.Agent.create("support", {
    instructions: "Answer #support.",
    triggers: [
      new nc.OnWebhook("orders", { conversation: "order-{order.id}" }),
      new nc.OnEvent(nc.Connection.fromName("slack"), "channel_message", { filters: { channel: "C1" }, message: "Answer it" }),
    ],
  });
  assert.deepEqual(create.last.body, {
    name: "support", instructions: "Answer #support.",
    triggers: [
      { kind: "webhook", name: "orders", conversation: "order-{order.id}" },
      { kind: "event", connection: "slack", event: "channel_message", filters: { channel: "C1" }, message: "Answer it" },
    ],
  });
});

test("an event on an account connected in the app names it by its ref", async () => {
  const { api } = setup();
  const ref = "credential:9b2a1c5e-7d9f-4a31-8f6d-3f1d2c4b8a7e";
  api.on("GET", `/v1/connections/${encodeURIComponent(ref)}`, json({
    object: "connection", id: ref, name: "WhatsApp", origin: "app", integration: "whatsapp", status: "connected",
  }));
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const added = api.on("POST", "/v1/agents/ag_1/triggers", json(trigger("tr_7", "event", { connection: ref })));
  await nc.Agent.fromId("ag_1").addTrigger(new nc.OnEvent(nc.Connection.fromId(ref), "receive_message"));
  assert.deepEqual(added.last.body, { kind: "event", connection: ref, event: "receive_message", filters: {} });
});

test("fromName converges triggers and keeps webhook URLs and mail", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([AGENT])));
  api.on("GET", "/v1/agents/ag_1/triggers", json(listing([WEBHOOK, EVENT, EMAIL])));
  const removed = api.on("DELETE", "/v1/agents/ag_1/triggers/tr_5", json({ id: "tr_5", deleted: true }));
  const added = api.on("POST", "/v1/agents/ag_1/triggers", json(trigger("tr_6", "event", {})));
  const reread = api.on("GET", "/v1/agents/ag_1", json(AGENT));
  await nc.Agent.fromName("support", {
    createIfMissing: true, instructions: "hi", triggers: [new nc.OnWebhook("orders"), new nc.OnEvent("slack", "app_mention")],
  }).hydrate();
  assert.equal(removed.count, 1); // the old event: the webhook keeps its URL, the inbox its mail
  assert.deepEqual(added.last.body, { kind: "event", connection: "slack", event: "app_mention", filters: {} });
  assert.equal(reread.count, 1);
});

test("a matching definition writes nothing", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([AGENT])));
  api.on("GET", "/v1/agents/ag_1/triggers", json(listing([WEBHOOK, EVENT, EMAIL])));
  const post = api.on("POST", "/v1/agents/ag_1/triggers", json({}));
  const reread = api.on("GET", "/v1/agents/ag_1", json(AGENT));
  await nc.Agent.fromName("support", {
    createIfMissing: true, instructions: "hi",
    triggers: [new nc.OnWebhook("orders"), new nc.OnEvent("slack", "channel_message", { filters: { channel: "C1" } })],
  }).hydrate();
  assert.deepEqual([post.count, reread.count], [0, 0]);
});

test("triggers, addTrigger and removeTrigger", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/triggers", json(listing([WEBHOOK, EVENT, EMAIL])));
  const add = api.on("POST", "/v1/agents/ag_1/triggers", json(WEBHOOK));
  const deletes: string[] = [];
  for (const id of ["tr_2", "tr_5"]) {
    api.on("DELETE", `/v1/agents/ag_1/triggers/${id}`, (call: Call) => {
      deletes.push(call.path);
      return json({ id, deleted: true });
    });
  }
  const agent = nc.Agent.fromId("ag_1");
  const [webhook, event, email] = await agent.triggers();
  assert.deepEqual([webhook.url, webhook.defined, webhook.nextRun], ["https://wh_1.example.com", true, null]);
  assert.deepEqual([event.status, event.spec.filters, email.defined, email.spec.address], ["error", { channel: "C1" }, false, "help@acme.test"]);

  const added = await agent.addTrigger(new nc.OnWebhook("orders", { message: "A new order" }));
  assert.deepEqual(add.last.body, { kind: "webhook", name: "orders", message: "A new order" });
  assert.equal(added.url, WEBHOOK.url);

  await agent.removeTrigger(event);
  await agent.removeTrigger("tr_2");
  await agent.removeTrigger(new nc.OnEvent("slack", "channel_message", { filters: { channel: "C1" } }));
  assert.deepEqual(deletes, ["/v1/agents/ag_1/triggers/tr_5", "/v1/agents/ag_1/triggers/tr_2", "/v1/agents/ag_1/triggers/tr_5"]);
  await assert.rejects(agent.removeTrigger(new nc.OnWebhook("refunds")), nc.NotFound);
  assert.throws(() => new nc.OnEvent(42 as unknown as string, "channel_message"), TypeError);
});

test("updateTrigger changes a trigger in place", async () => {
  const schedule = trigger("tr_8", "cron", { cron: "0 8 * * 1-5", tz: "Europe/London", message: "Brief me." });
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/triggers", json(listing([schedule, WEBHOOK])));
  const patches: Call[] = [];
  for (const [id, row] of [["tr_8", { ...schedule, spec: { cron: "30 7 * * 1-5", tz: "Europe/London", message: "Brief me." } }], ["tr_2", WEBHOOK]] as const) {
    api.on("PATCH", `/v1/agents/ag_1/triggers/${id}`, (call: Call) => {
      patches.push(call);
      return json(row);
    });
  }
  const agent = nc.Agent.fromId("ag_1");
  const changed = await agent.updateTrigger("tr_8", { cron: new nc.Cron("30 7 * * 1-5", { tz: "Europe/London" }) });
  assert.deepEqual([patches[0].path, patches[0].body], ["/v1/agents/ag_1/triggers/tr_8", { cron: "30 7 * * 1-5", tz: "Europe/London" }]);
  assert.deepEqual([changed.id, changed.spec.cron], ["tr_8", "30 7 * * 1-5"]);

  // The definition you added finds it, as for removeTrigger; null clears what it was told.
  await agent.updateTrigger(new nc.Cron("0 8 * * 1-5", { tz: "Europe/London", message: "Brief me." }), { message: null });
  assert.deepEqual(patches[1].body, { message: null });
  await agent.updateTrigger(new nc.OnWebhook("orders"), { message: "A new order.", conversation: "order-{order.id}" });
  assert.deepEqual([patches[2].path, patches[2].body], ["/v1/agents/ag_1/triggers/tr_2", { message: "A new order.", conversation: "order-{order.id}" }]);
  await assert.rejects(agent.updateTrigger("tr_8", {}), /Nothing to change/);
  assert.equal(patches.length, 3);
});

test("one trigger pauses, resumes and is tried with a sample; filters and a channel's mode change in place", async () => {
  const paused = {
    ...WEBHOOK, status: "paused", paused: true, state: "paused", reason: "Paused: it doesn't wake the agent until it's resumed.",
    fix: { action: "resume" }, set_by: { kind: "agent", agent_id: "ag_9" }, read_only: false,
    actions: ["resume", "test", "update", "remove"], next_run_at: null,
  };
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/triggers", json(listing([WEBHOOK, EVENT])));
  const calls: Call[] = [];
  const record = (row: Record<string, unknown>, status = 200) => (call: Call) => {
    calls.push(call);
    return json(row, { status });
  };
  api.on("POST", "/v1/agents/ag_1/triggers/tr_2/pause", record(paused));
  api.on("POST", "/v1/agents/ag_1/triggers/tr_2/resume", record({ ...WEBHOOK, state: "live" }));
  api.on("POST", "/v1/agents/ag_1/triggers/tr_2/test", record({ object: "operation", id: "op_1", kind: "agent.rehearse", status: "queued" }, 202));
  api.on("PATCH", "/v1/agents/ag_1/triggers/tr_5", record(EVENT));

  const agent = nc.Agent.fromId("ag_1");
  const held = await agent.pauseTrigger(new nc.OnWebhook("orders"));
  assert.equal(calls[0].path, "/v1/agents/ag_1/triggers/tr_2/pause");
  assert.deepEqual([held.paused, held.state, held.fix, held.actions, held.setBy, held.readOnly],
    [true, "paused", { action: "resume" }, ["resume", "test", "update", "remove"], { kind: "agent", agentId: "ag_9" }, false]);
  assert.equal((await agent.resumeTrigger("tr_2")).state, "live");

  const run = await agent.rehearseTrigger("tr_2", { sample: { order: "A-17" } });
  assert.deepEqual([calls[2].body, run.id], [{ sample: { order: "A-17" } }, "op_1"]);
  await agent.rehearseTrigger("tr_2");
  assert.equal(calls[3].body, null); // a sample of its own

  await agent.updateTrigger("tr_5", { filters: { channel: "C2" } });
  await agent.updateTrigger("tr_5", { mode: "all" });
  assert.deepEqual([calls[4].body, calls[5].body], [{ filters: { channel: "C2" } }, { mode: "all" }]);
  // A view from before these fields reads as live, set up by a person.
  const [old] = await agent.triggers();
  assert.deepEqual([old.state, old.paused, old.setBy, old.actions], ["live", false, { kind: "person", agentId: null }, []]);
});

test("a webhook is removed by its name, unique on an agent; any other definition matches whole", async () => {
  const hook = trigger("tr_7", "webhook", { name: "orders", message: "A new order", conversation: "order-{order.id}" }, { url: "https://wh_7.example.com" });
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/triggers", json(listing([hook, EVENT])));
  const deletes: string[] = [];
  api.on("DELETE", "/v1/agents/ag_1/triggers/tr_7", (call: Call) => {
    deletes.push(call.path);
    return json({ id: "tr_7", deleted: true });
  });
  const agent = nc.Agent.fromId("ag_1");
  await agent.removeTrigger(new nc.OnWebhook("orders"));
  assert.deepEqual(deletes, ["/v1/agents/ag_1/triggers/tr_7"]);
  await assert.rejects(agent.removeTrigger(new nc.OnWebhook("refunds")), nc.NotFound);
  await assert.rejects(agent.removeTrigger(new nc.OnEvent("slack", "channel_message")), nc.NotFound);
});

test("connection.events lists the app events an OnEvent trigger can use", async () => {
  const { api } = setup();
  const connection = api.on("GET", "/v1/connections/support", json({ object: "connection", id: "cn_2", name: "support", integration: "slack", status: "connected" }));
  const read = api.on("GET", "/v1/integrations/slack/events", json(listing([
    { object: "integration_event", name: "channel_message", description: "On Channel Message", filters: { channel: "Optional: one channel" }, required_filters: [] },
  ])));
  const events = await nc.Connection.fromName("support", { integration: "slack" }).events();
  assert.equal(read.calls.length, 1);
  assert.equal(connection.count, 0); // named with its integration: the catalog alone answers
  await nc.Connection.fromName("support").events();
  assert.deepEqual([connection.count, read.calls.length], [1, 2]);
  assert.deepEqual(events.map((e) => [e.name, e.filters]), [["channel_message", { channel: "Optional: one channel" }]]);
});

// --- channel subscriptions ------------------------------------------------------------------

test("a channel subscribes to an app's events or a webhook", async () => {
  const { api } = setup();
  const sub = api.on("POST", "/v1/channels/ch_1/subscriptions", json(SUB));
  const room = nc.Channel.fromId("ch_1");

  const subscription = await room.subscribe(new nc.OnEvent("stripe", "invoice_payment_failed", { message: "A payment failed." }), { wake: "all" });
  assert.deepEqual(sub.last.body, {
    source: { kind: "event", connection: "stripe", event: "invoice_payment_failed", filters: {}, message: "A payment failed." }, wake: "all",
  });
  assert.ok(subscription instanceof nc.Subscription);
  assert.deepEqual([subscription.channelId, subscription.wake, subscription.status, subscription.source.event], ["ch_1", "all", "active", "invoice_payment_failed"]);

  await room.subscribe(new nc.OnWebhook("deploys"), { wake: [nc.Agent.fromId("ag_1"), "ag_2"], filters: { status: "failed" } });
  assert.deepEqual(sub.last.body, { source: { kind: "webhook", name: "deploys" }, wake: ["ag_1", "ag_2"], filters: { status: "failed" } });
  await room.subscribe(new nc.OnWebhook("logs"));
  assert.deepEqual(sub.last.body, { source: { kind: "webhook", name: "logs" }, wake: null });
});

test("subscribe refuses a conversation template and an app event's filters; subscriptions list and unsubscribe", async () => {
  const { api } = setup();
  const sub = api.on("POST", "/v1/channels/ch_1/subscriptions", json(SUB));
  const room = nc.Channel.fromId("ch_1");
  await assert.rejects(room.subscribe(new nc.OnWebhook("deploys", { conversation: "deploy-{id}" })), /one conversation/);
  await assert.rejects(room.subscribe(new nc.OnEvent("stripe", "charge_failed"), { filters: { amount: 1 } }), /go on the OnEvent itself/);
  await assert.rejects(room.subscribe(42 as unknown as string), /an OnPlatformEvent or a NoClick event type/);
  await assert.rejects(room.subscribe(new nc.OnWebhook("deploys"), { wake: "some" as "all" }), /wake is null, "all" or a list of agents/);
  assert.equal(sub.count, 0);

  api.on("GET", "/v1/channels/ch_1/subscriptions", json(listing([
    SUB, { ...SUB, id: "sub_2", source: { kind: "webhook", name: "deploys" }, url: "https://wh_2.example.com", wake: null },
  ])));
  const del = api.on("DELETE", "/v1/channels/ch_1/subscriptions/sub_2", json({ id: "sub_2", deleted: true }));
  const [, hook] = await room.subscriptions();
  assert.deepEqual([hook.url, hook.wake], ["https://wh_2.example.com", null]);
  await hook.unsubscribe();
  assert.equal(del.count, 1);
});

test("an app's post reads as an app message with its subscription and event", async () => {
  const { api } = setup();
  api.on("GET", "/v1/channels/ch_1/messages", json(listing([{
    object: "channel_message", id: "m_1", channel_id: "ch_1", author: { type: "app", id: null, name: "Stripe" },
    text: "Stripe invoice.payment_failed: invoice in_1", mentions: [], created_at: "2026-10-01T09:00:00Z",
    subscription_id: "sub_1", event: { type: "invoice.payment_failed", id: "evt_1" },
  }])));
  const [message] = await nc.Channel.fromId("ch_1").messages();
  assert.deepEqual([message.author.type, message.author.name, message.subscriptionId, message.event], ["app", "Stripe", "sub_1", { type: "invoice.payment_failed", id: "evt_1" }]);
});
