// The step catalog (`GET /v1/step_types` and `/v1/step_types/{step_type}`): what the client sends and how it reads
// the answer.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, listing, setup } from "./helpers.ts";

const SLACK = {
  object: "step_type", type: "automation-slack", label: "Slack", description: "Slack automation",
  category: "communication", kinds: ["trigger", "tool"], trigger: false,
  operations: [
    { name: "on_channel_message", label: "On Channel Message", trigger: true, needs_account: true },
    { name: "send_message_to_channel", label: "Send Message", trigger: false, needs_account: true },
  ],
  connection: { needed: true, integration: "slack", credential_types: ["slack_oauth", "slack_bot_token"] },
  retired: null,
};
const CRON = {
  object: "step_type", type: "trigger-cron", label: "Schedule", description: "Runs on a schedule", category: null,
  kinds: ["trigger"], trigger: true, operations: [{ name: "default", label: null, trigger: false, needs_account: false }],
  connection: null, retired: null,
};

test("stepTypes() reads every page, for no user", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/step_types", json(listing([CRON], "trigger-cron")), json(listing([SLACK])));
  const found = await nc.asUser("user_42", () => nc.stepTypes());
  assert.equal(route.count, 2);
  assert.equal(route.calls[0].headers.get("NoClick-User"), null);
  assert.equal(route.calls[0].query.get("cursor"), null);
  assert.equal(route.calls[1].query.get("cursor"), "trigger-cron");
  assert.deepEqual(found.map((t) => t.type), ["trigger-cron", "automation-slack"]);

  const [cron, slack] = found;
  assert.deepEqual([cron.label, cron.kinds, cron.trigger, cron.connection, cron.schema], ["Schedule", ["trigger"], true, null, null]);
  const send = slack.operations[1];
  assert.deepEqual([send.name, send.label, send.trigger, send.needsAccount, send.description],
    ["send_message_to_channel", "Send Message", false, true, null]);
  assert.equal(slack.operations[0].trigger, true);
  assert.deepEqual([slack.connection?.needed, slack.connection?.integration, slack.connection?.credentialTypes],
    [true, "slack", ["slack_oauth", "slack_bot_token"]]);
  assert.deepEqual([slack.category, slack.retired], ["communication", null]);
});

test("a query, kind and limit are sent as the route takes them", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/step_types", json(listing([SLACK], "automation-slack")));
  const [slack] = await nc.stepTypes("post to slack", { kind: "trigger", limit: 1 });
  assert.deepEqual([route.last.query.get("q"), route.last.query.get("kind"), route.last.query.get("limit")],
    ["post to slack", "trigger", "1"]);
  assert.equal(route.count, 1);
  assert.equal(slack.type, "automation-slack");
});

test("stepType() reads one type's schema and each operation described", async () => {
  const { api } = setup();
  const schema = {
    type: "object", properties: { config: { oneOf: [{ $ref: "#/$defs/SendMessage" }] } },
    $defs: { SendMessage: { properties: { channel: { type: "string", "x-dynamic-options": {} } } } },
  };
  const described = {
    ...SLACK, operations: SLACK.operations.map((op) => ({ ...op, description: `${op.label}.` })), schema,
  };
  const route = api.on("GET", "/v1/step_types/automation-slack", json(described));
  const slack = await nc.stepType("automation-slack");
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.deepEqual(slack.schema, schema);
  assert.deepEqual(slack.operations.map((op) => op.description), ["On Channel Message.", "Send Message."]);
});

test("a type's name is one path segment, and an unknown one is NotFound", async () => {
  const { api } = setup();
  api.on("GET", "/v1/step_types/a%2Fb", apiError(404, "not_found", "No step type 'a/b'."));
  await assert.rejects(nc.stepType("a/b"), nc.NotFound);
});

test("a type that takes no settings has no schema", async () => {
  const { api } = setup();
  api.on("GET", "/v1/step_types/trigger-run", json({ ...CRON, type: "trigger-run", label: "Run", operations: [], schema: null }));
  const run = await nc.stepType("trigger-run");
  assert.equal(run.schema, null);
  assert.deepEqual(run.operations, []);
});

test("a narrowed stepType() read sends its filters and counts every operation", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/step_types/automation-slack",
    json({ ...SLACK, operations: SLACK.operations.slice(0, 1), operations_total: 2, schema: null }));
  const slack = await nc.stepType("automation-slack", { kind: "trigger", query: "new message", operation: "on_channel_message" });
  assert.deepEqual([route.calls[0].query.get("kind"), route.calls[0].query.get("q"), route.calls[0].query.get("operation")],
    ["trigger", "new message", "on_channel_message"]);
  assert.deepEqual(slack.operations.map((op) => op.name), ["on_channel_message"]);
  assert.equal(slack.operationsTotal, 2);
  await nc.stepType("automation-slack", { operation: ["on_channel_message", "send_message_to_channel"] });
  assert.equal(route.calls[1].query.get("operation"), "on_channel_message,send_message_to_channel");
  await nc.stepType("automation-slack");
  assert.deepEqual([...route.calls[2].query.keys()], []); // a plain read sends no filter
});
