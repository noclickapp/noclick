// A coding agent's own commands from a chat: the list its harness offers, a command sent in place of text, and a
// message steered into the running turn or queued behind it.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "coder", model: "sonnet", harness: "claude_code", instructions: "Fix docs.",
  tools: [], user_id: null, workflow_id: "wf_1", created_at: "2026-11-09T10:00:00Z",
};
const TURN = { object: "operation", id: "op_1", kind: "agent.message", status: "queued" };

test("commands reads what the conversation's harness offers, and how fresh the list is", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const route = api.on("GET", "/v1/agents/ag_1/conversations/main%2F1/commands", json({
    object: "agent_commands", harness: "claude_code",
    commands: [
      { name: "compact", description: "Compact the thread", argument_hint: "<instructions>", source: "harness", aliases: [] },
      { name: "pdf", description: "Read PDFs", argument_hint: "", source: "skill", aliases: [] },
    ],
    skills: [{ name: "pdf", description: "Read PDFs" }],
    capabilities: { commands: true, skills: true, compact: true, review: false, goal: false, init: false, steer: true, queue: true },
    not_supported: {}, withheld: ["config", "mcp"], mapped: [{ name: "model", to: "model" }], as_of: "2026-11-09T10:05:00Z", read_from: "another_conversation",
  }));
  const coder = nc.Agent.fromId("ag_1");
  const listed = await coder.commands("main/1");
  assert.equal(route.count, 1);
  assert.deepEqual(listed.commands[0], {
    name: "compact", description: "Compact the thread", argumentHint: "<instructions>", source: "harness", aliases: [],
  });
  assert.deepEqual(listed.skills, [{ name: "pdf", description: "Read PDFs" }]);
  assert.equal(listed.capabilities.compact, true);
  assert.equal(listed.capabilities.review, false);
  assert.deepEqual(listed.withheld, ["config", "mcp"]);
  assert.deepEqual(listed.mapped, [{ name: "model", to: "model" }]);
  assert.deepEqual([listed.asOf?.toISOString(), listed.readFrom], ["2026-11-09T10:05:00.000Z", "another_conversation"]);
});

test("a command goes in place of text, never as text", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const send = api.on("POST", "/v1/agents/ag_1/messages", json(TURN, { status: 202 }));
  const coder = nc.Agent.fromId("ag_1");
  const op = await coder.send(null, { conversation: "main", command: { name: "compact", arguments: "keep the API notes" } });
  assert.equal(op.id, "op_1");
  assert.deepEqual(send.last.body, { command: { name: "compact", arguments: "keep the API notes" }, conversation: "main" });
  await coder.send(null, { conversation: "main", command: { name: "review" }, delivery: "queue" });
  assert.deepEqual(send.last.body, { command: { name: "review" }, delivery: "queue", conversation: "main" });
  await assert.rejects(coder.send("hi", { command: { name: "compact" } }), /text or a command/);
  await assert.rejects(coder.send(null), /text or a command/);
});

test("a message steered into the running turn or queued behind it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const send = api.on("POST", "/v1/agents/ag_1/messages", json({ ...TURN, kind: "agent.ask" }, { status: 202 }));
  const coder = nc.Agent.fromId("ag_1");
  await coder.send("also update the README", { conversation: "main", delivery: "steer" });
  assert.deepEqual(send.last.body, { text: "also update the README", delivery: "steer", conversation: "main" });
  await coder.send("then open a PR", { conversation: "main", delivery: "queue" });
  assert.deepEqual(send.last.body, { text: "then open a PR", delivery: "queue", conversation: "main" });
});

test("history says which message ran a command", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/conversations/main", json({
    object: "conversation", next_cursor: null, messages: [
      { role: "user", text: "/compact", command: { name: "compact", arguments: "" }, created_at: "2026-11-09T10:00:00Z" },
      { role: "user", text: "hello", created_at: "2026-11-09T10:01:00Z" },
    ],
  }));
  const [ran, said] = await nc.Agent.fromId("ag_1").history("main");
  assert.deepEqual(ran.command, { name: "compact", arguments: "" });
  assert.equal(said.command, null);
});
