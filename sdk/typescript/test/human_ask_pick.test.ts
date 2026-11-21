// Human.ask with pick (something in a connected account) and multiple (several choices): what the call sends and how
// the answer reads, against the mocked transport.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, operation, setup } from "./helpers.ts";

const CREATED = {
  ...operation({ id: "op_h", kind: "human.ask" }),
  request: { id: "hr_1", url: null, delivered_via: ["web", "imessage"], undelivered: [] },
};

test("a pick names the connection and field, and the answer its value", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/humans/requests", json(CREATED));
  api.on("GET", "/v1/operations/op_h/wait", json(operation({
    id: "op_h", kind: "human.ask", status: "succeeded", result: { choice: "Site", value: "acme/site", text: null },
  })));
  const req = await nc.Human.owner().ask("Which repository should it open PRs in?", {
    pick: { connection: "github", field: "repository", arguments: { visibility: "private" } },
  });
  assert.deepEqual(create.last.body, {
    kind: "ask", to: { owner: true }, message: "Which repository should it open PRs in?",
    pick: { connection: "github", field: "repository", arguments: { visibility: "private" } }, via: "auto",
  });
  const answer = await req.wait();
  assert.deepEqual([answer.choice, answer.value, answer.choices, answer.values], ["Site", "acme/site", [], []]);
});

test("a Connection is sent by its id, as the user the Human acts for", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/humans/requests", json(CREATED));
  const slack = nc.Connection.fromId("con_9");
  await nc.asUser(USER_ID, () => new nc.Human().ask("Which channel should it post in?", { pick: { connection: slack, field: "channel" } }));
  assert.deepEqual((create.last.body as { pick: unknown }).pick, { connection: "con_9", field: "channel" });
  assert.equal(create.last.headers.get("NoClick-User"), USER_ID);
});

test("multiple asks for several, and the answer names each", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/humans/requests", json(CREATED));
  api.on("GET", "/v1/operations/op_h/wait", json(operation({
    id: "op_h", kind: "human.ask", status: "succeeded", result: { choices: ["Mon", "Wed"], text: "mornings only" },
  })));
  const req = await new nc.Human({ email: "ana@example.com" }).ask("Which days can you work?", {
    options: ["Mon", "Tue", "Wed"],
    multiple: true,
  });
  assert.deepEqual(create.last.body, {
    kind: "ask", to: { email: "ana@example.com" }, message: "Which days can you work?",
    options: ["Mon", "Tue", "Wed"], multiple: true, via: "auto",
  });
  const answer = await req.wait();
  assert.deepEqual([answer.choice, answer.choices, answer.text], [null, ["Mon", "Wed"], "mornings only"]);
});

test("several of a pick read back with their values; a plain question sends neither", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/humans/requests", json(CREATED));
  api.on("GET", "/v1/operations/op_h/wait", json(operation({
    id: "op_h", kind: "human.ask", status: "succeeded",
    result: { choices: ["Site", "API"], values: ["acme/site", "acme/api"], text: null },
  })));
  const req = await nc.Human.owner().ask("Which repositories?", { pick: { connection: "github", field: "repository" }, multiple: true });
  assert.equal((create.last.body as { multiple: unknown }).multiple, true);
  const answer = await req.wait();
  assert.deepEqual([answer.choices, answer.values, answer.value], [["Site", "API"], ["acme/site", "acme/api"], null]);

  await nc.Human.owner().ask("Anything else?", { multiple: false });
  assert.deepEqual(create.last.body, { kind: "ask", to: { owner: true }, message: "Anything else?", via: "auto" });
});
