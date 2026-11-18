// An app's subscriptions against the mocked API, as the Python client's `test_app_subscriptions.py` drives them:
// `project.subscribe` POSTs an `OnEvent`'s events to a path, `subscriptions`/`deliveries`/`test`/`unsubscribe` read and
// drive them, `connection.events()` carries each event's shape and sample, and `agent.rehearseTrigger` test-runs the
// turn a sample would start.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, operation, setup } from "./helpers.ts";

const SOURCE = { kind: "event", connection: "whatsapp", event: "receive_message", filters: {} };

function subscription(fields: Record<string, unknown> = {}) {
  return {
    object: "subscription", id: "sub_1", channel_id: null, workspace_id: null, project_id: "prj_1", path: "/hooks/whatsapp",
    channels: null, source: SOURCE, wake: null, filters: null, status: "active", error: null, url: null, last_event_at: null,
    created_at: "2026-11-04T09:00:00Z", ...fields,
  };
}

function delivery(fields: Record<string, unknown> = {}) {
  return {
    object: "subscription_delivery", id: "dl_1", subscription_id: "sub_1", status: "delivered", test: false, attempts: 1,
    response_status: 204, response_body: null, request_body: '{"object":"app_event"}', duration_ms: 40, error: null,
    next_retry_at: null, delivered_at: "2026-11-04T09:00:01Z", created_at: "2026-11-04T09:00:00Z", ...fields,
  };
}

test("an app subscribes to a connection's events at one of its paths", async () => {
  const { api } = setup();
  const made = api.on("POST", "/v1/projects/prj_1/subscriptions", json(subscription()));
  const app = nc.Project.fromId("prj_1");
  const hook = await app.subscribe(new nc.OnEvent("whatsapp", "receive_message"), { path: "/hooks/whatsapp" });
  assert.deepEqual(made.last.body, { source: SOURCE, path: "/hooks/whatsapp" });
  assert.ok(hook instanceof nc.Subscription);
  assert.deepEqual([hook.projectId, hook.path, hook.channelId, hook.status], ["prj_1", "/hooks/whatsapp", null, "active"]);
  await assert.rejects(app.subscribe(new nc.OnWebhook("orders") as never, { path: "/hooks/orders" }), TypeError);
  await assert.rejects(
    app.subscribe(new nc.OnEvent("whatsapp", "receive_message", { message: "Answer it" }), { path: "/hooks/whatsapp" }),
    TypeError,
  );
  assert.equal(made.count, 1);
});

test("an app's subscription lists what it sent, tests and stops", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1/subscriptions", json(listing([subscription()])));
  const sent = api.on("GET", "/v1/projects/prj_1/subscriptions/sub_1/deliveries", json(listing([
    delivery({ status: "retrying", error: "Answered 500", response_status: 500, next_retry_at: "2026-11-04T09:01:00Z" }),
  ])));
  const tested = api.on("POST", "/v1/projects/prj_1/subscriptions/sub_1/test", json(delivery({ id: "dl_2", test: true })));
  const gone = api.on("DELETE", "/v1/projects/prj_1/subscriptions/sub_1", json({ id: "sub_1", deleted: true }));

  const [hook] = await nc.Project.fromId("prj_1").subscriptions();
  const [retrying] = await hook.deliveries({ status: ["retrying", "failed"] });
  assert.equal(sent.last.query.get("status"), "retrying,failed");
  assert.deepEqual([retrying.status, retrying.error, retrying.responseStatus], ["retrying", "Answered 500", 500]);
  assert.ok(retrying.nextRetryAt instanceof Date && retrying.requestBody === '{"object":"app_event"}');
  const sample = await hook.test();
  assert.ok(tested.count === 1 && sample.test && sample.status === "delivered" && sample.id === "dl_2");
  await hook.unsubscribe();
  assert.equal(gone.count, 1);
});

test("an event's shape and sample come with the catalog", async () => {
  const { api } = setup();
  const shape = { event: "string", payload: { from: "string", body: "string", hasMedia: "boolean" } };
  const sample = { event: "sample event", payload: { from: "sample from", body: "sample body", hasMedia: false } };
  api.on("GET", "/v1/integrations/whatsapp/events", json(listing([
    { object: "integration_event", name: "receive_message", description: "A message arrives", filters: {}, required_filters: [], shape, sample },
    { object: "integration_event", name: "unseen", description: "Not seen yet", filters: {}, required_filters: [], shape: null, sample: null },
  ])));
  const [seen, unseen] = await nc.Connection.fromName("whatsapp", { integration: "whatsapp" }).events();
  assert.deepEqual([seen.shape, seen.sample], [shape, sample]);
  assert.deepEqual([unseen.shape, unseen.sample], [null, null]);
});

test("rehearseTrigger runs the turn a sample of its event starts", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json({ object: "agent", id: "ag_1", name: "inbox", tools: [], created_at: "2026-11-04T09:00:00Z" }));
  const start = api.on("POST", "/v1/agents/ag_1/triggers/tr_5/test", json(operation({ id: "op_r", kind: "agent.rehearse", status: "running" })));
  api.on("GET", "/v1/operations/op_r/wait", json(operation({
    id: "op_r", kind: "agent.rehearse", status: "succeeded", result: { reply: "Replied.", tool_calls: [], transcript: [] },
  })));
  const op = await nc.Agent.fromId("ag_1").rehearseTrigger("tr_5");
  assert.equal(start.count, 1);
  assert.equal((await op.wait()).reply, "Replied.");
});
