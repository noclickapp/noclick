// Human.ask with connect (which connection a workflow step uses) and secret (a secret's values), and
// HumanRequest.answer from code: what the calls send and how the answers read, against the mocked transport.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, operation, setup } from "./helpers.ts";

const CREATED = {
  ...operation({ id: "op_h", kind: "human.ask" }),
  request: { id: "hr_1", url: null, delivered_via: ["web"], undelivered: [] },
};

test("connect names the step, and the answer its connection", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/humans/requests", json(CREATED));
  api.on("GET", "/v1/operations/op_h/wait", json(operation({
    id: "op_h", kind: "human.ask", status: "succeeded",
    result: { choice: "Slack", value: "credential:c1", connection: "credential:c1", version: 3 },
  })));
  const req = await nc.Human.owner().ask("Which Slack should Post use?", {
    connect: { integration: "slack", step: { workflow: nc.Workflow.fromId("wf_1"), stepId: "post" } },
  });
  assert.deepEqual(create.last.body, {
    kind: "ask", to: { owner: true }, message: "Which Slack should Post use?",
    connect: { integration: "slack", step: { workflow_id: "wf_1", step_id: "post" } }, via: "auto",
  });
  const answer = await req.wait();
  assert.deepEqual([answer.connection, answer.value, answer.choice, answer.secret], ["credential:c1", "credential:c1", "Slack", null]);
});

test("secret names its keys and step, and the answer only the secret", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/humans/requests", json(CREATED));
  api.on("GET", "/v1/operations/op_h/wait", json(operation({
    id: "op_h", kind: "human.ask", status: "succeeded",
    result: { secret: "warehouse", secret_id: "sec_1", keys: ["WAREHOUSE_TOKEN"] },
  })));
  const req = await nc.Human.owner().ask("The warehouse token, please.", {
    secret: { name: "warehouse", keys: ["WAREHOUSE_TOKEN"], step: { workflow: "wf_1", stepId: "agent" } },
  });
  assert.deepEqual((create.last.body as { secret: unknown }).secret, {
    name: "warehouse", keys: ["WAREHOUSE_TOKEN"], step: { workflow_id: "wf_1", step_id: "agent" },
  });
  const answer = await req.wait();
  assert.deepEqual([answer.secret, answer.connection], ["warehouse", null]);
});

test("code answers with a connection or the values; approve still sends its decision", async () => {
  const { api } = setup();
  api.on("POST", "/v1/humans/requests", json(CREATED));
  const answered = api.on("POST", "/v1/humans/requests/hr_1/answer", json({ id: "hr_1", status: "answered" }));
  const req = await nc.Human.owner().ask("Which Slack?", {
    connect: { credentialType: "slack_oauth", step: { workflow: "wf_1", stepId: "post", slot: "slack_oauth" } },
  });
  await req.answer({ connection: nc.Connection.fromId("con_9") });
  assert.deepEqual(answered.last.body, { connection: "con_9" });
  await req.answer({ secretValues: { WAREHOUSE_TOKEN: "v" } });
  assert.deepEqual(answered.last.body, { secret_values: { WAREHOUSE_TOKEN: "v" } });
  assert.equal(req.requestStatus, "answered");
  await req.approve({ note: "fine" });
  assert.deepEqual(answered.last.body, { approved: true, note: "fine" });
});
