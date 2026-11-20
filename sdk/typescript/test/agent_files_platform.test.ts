// NoClick itself as an agent's tools (`Platform`), files sent with a message, and the typed events a turn shows
// (`file`, `approval`, `operation`) in a stream, a watch and the history alike.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, operation, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "ops", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: 50,
  created_at: "2026-09-25T10:00:00Z",
};
const REPORT = {
  object: "agent_attachment", id: "att_1", agent_id: "ag_1", name: "q3.pdf", mime_type: "application/pdf", size_bytes: 1200,
  kind: "file", url: "https://assets.test/u/account/att_1/q3.pdf", voice: false, duration_ms: null, peaks: null,
};
const SSE = [
  "event: file",
  `data: {"role": "user", "file": {"name": "q3.pdf", "url": "${REPORT.url}", "mime_type": "application/pdf", "size_bytes": 1200}, "operation_id": "op_1"}`,
  "",
  "event: approval",
  'data: {"approval": {"id": "ap_1", "url": "https://noclick.com/approve/ap_1", "summary": "Buy +1 415 555 0100", "price": {"amount_usd": 1.15}}, "operation_id": "op_1"}',
  "",
  "event: operation",
  'data: {"operation": {"id": "op_2", "status": "running", "summary": "Deploy acme-site"}, "operation_id": "op_1"}',
  "",
  "event: done",
  'data: {"text": "Waiting for your approval.", "conversation": "desk", "operation_id": "op_1"}',
  "",
  "",
].join("\n");

test("NoClick itself in tools, whole or narrowed by group and area", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/agents", json(AGENT));
  await nc.Agent.create("ops", { instructions: "Run our account.", tools: ["search", new nc.Platform()] });
  assert.deepEqual((create.last.body as { tools: unknown }).tools, ["search", "noclick"]);
  await nc.Agent.create("registrar", { instructions: "Keep our domains.", tools: [nc.Platform.only("domains", "read", "read")] });
  assert.deepEqual((create.last.body as { tools: unknown }).tools, ["noclick.domains", "noclick.read"]);
  assert.throws(() => nc.Platform.only(), /read, build, deploy, spend, delete/);
});

test("a file uploads to the agent, then goes with the message by id", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const upload = api.on("POST", "/v1/agents/ag_1/attachments", json(REPORT, { status: 201 }));
  const send = api.on("POST", "/v1/agents/ag_1/messages", json(operation({ id: "op_1", kind: "agent.message", status: "queued" }), { status: 202 }));
  const agent = nc.Agent.fromId("ag_1");
  const blob = new Blob([new Uint8Array([37, 80, 68, 70])], { type: "application/pdf" });
  const report = await agent.upload(blob, { name: "q3.pdf" });
  assert.deepEqual([upload.last.query.get("name"), upload.last.query.get("mime_type")], ["q3.pdf", "application/pdf"]);
  assert.deepEqual([report.id, report.kind, report.sizeBytes], ["att_1", "file", 1200]);
  await agent.send("What stands out?", { conversation: "desk", files: [report, "att_9"] });
  assert.deepEqual(send.last.body, { text: "What stands out?", conversation: "desk", attachments: ["att_1", "att_9"] });
  await agent.send("And now?", { conversation: "desk" });
  assert.deepEqual(send.last.body, { text: "And now?", conversation: "desk" });
});

test("a stream shows files, approvals and long actions; history and a watch carry a message's files", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("POST", "/v1/agents/ag_1/messages", () => new Response(SSE, { headers: { "content-type": "text/event-stream" } }));
  const events: nc.AgentEvent[] = [];
  for await (const event of nc.Agent.fromId("ag_1").stream("Buy us a number.", { conversation: "desk" })) events.push(event);
  assert.deepEqual(events.map((e) => e.type), ["file", "approval", "operation", "done"]);
  const [sent, approval, started] = events;
  assert.deepEqual([sent.role, sent.file?.name, sent.file?.kind, sent.file?.id, sent.file?.sizeBytes], ["user", "q3.pdf", "file", null, 1200]);
  assert.equal(approval.approval?.url, "https://noclick.com/approve/ap_1");
  assert.deepEqual(started.operation, { id: "op_2", status: "running", summary: "Deploy acme-site" });

  api.on("GET", "/v1/agents/ag_1/conversations/desk", json({ messages: [
    { role: "user", text: "What stands out?", created_at: "2026-10-15T10:00:00Z", files: [
      { name: "chart.png", url: "https://assets.test/chart.png", mime_type: "image/png" }] },
    { role: "assistant", text: "Revenue doubled.", created_at: "2026-10-15T10:00:05Z", tool_calls: [
      { tool: "noclick__api_call", arguments: { operation: "dicts_get" }, result: "{\"response\": {}}", is_error: false }] },
  ] }));
  const [first, reply] = await nc.Agent.fromId("ag_1").history("desk");
  assert.deepEqual(first.files.map((f) => [f.name, f.kind]), [["chart.png", "image"]]);
  assert.deepEqual([first.toolCalls, reply.files], [[], []]);
  assert.deepEqual(reply.toolCalls.map((c) => [c.tool, c.is_error]), [["noclick__api_call", false]]);
  api.on("GET", "/v1/agents/ag_1/conversations/desk/events", () => new Response(
    'event: message\ndata: {"role": "user", "text": "Look", "files": [{"name": "a.mp3", "url": "https://assets.test/a.mp3", "mime_type": "audio/mpeg"}]}\n\n' +
      'event: message\ndata: {"role": "assistant", "text": "Done.", "tool_calls": [{"tool": "noclick__search", "arguments": {}, "result": "[]", "is_error": false}]}\n\n',
    { headers: { "content-type": "text/event-stream" } }));
  const watched: nc.AgentEvent[] = [];
  for await (const event of nc.Agent.fromId("ag_1").watch("desk")) watched.push(event);
  assert.deepEqual(watched.map((e) => [e.type, e.files.map((f) => f.kind), e.toolCalls.map((c) => c.tool)]), [
    ["message", ["audio"], []],
    ["message", [], ["noclick__search"]],
  ]);
});

test("watching with replay starts with what's kept, a coding harness's output and diffs among it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const stream = api.on("GET", "/v1/agents/ag_1/conversations/task/events", () => new Response(
    'event: tool_call\ndata: {"id": "c1", "tool": "shell", "arguments": {"command": "npm test"}, "source": "harness", "operation_id": "op_1"}\n\n' +
      'event: output\ndata: {"id": "c1", "text": "ok\\n", "operation_id": "op_1"}\n\n' +
      'event: diff\ndata: {"id": "p1", "path": "src/a.ts", "kind": "update", "diff": "-a\\n+b\\n", "operation_id": "op_1"}\n\n',
    { headers: { "content-type": "text/event-stream" } }));
  const watched: nc.AgentEvent[] = [];
  for await (const event of nc.Agent.fromId("ag_1").watch("task", { replay: true })) watched.push(event);
  assert.equal(stream.last.query.get("replay"), "1");
  assert.deepEqual(watched.map((e) => [e.type, e.text, e.callId]), [
    ["tool_call", null, "c1"], ["output", "ok\n", "c1"], ["diff", null, "p1"]]);
  assert.equal(watched[0].source, "harness");
  assert.deepEqual([watched[2].path, watched[2].change, watched[2].diff], ["src/a.ts", "update", "-a\n+b\n"]);
  for await (const _ of nc.Agent.fromId("ag_1").watch("task")) void _;
  assert.equal(stream.last.query.get("replay"), null);
});

test("a coding harness's command says how it ended and what replaced its output", async () => {
  // A harness's own command ends with its exit code and time; output the stream missed comes again `whole`, replacing
  // what streamed; a new file's diff is its content; moments the sandbox couldn't send are counted.
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/conversations/task/events", () => new Response(
    'event: output\ndata: {"id": "c1", "text": "partial"}\n\n' +
      'event: output\ndata: {"id": "c1", "text": "all of it\\n", "whole": true}\n\n' +
      'event: tool_result\ndata: {"id": "c1", "tool": "shell", "source": "harness", "exit_code": 1, "duration_ms": 1520, "is_error": true, "result": "exit 1"}\n\n' +
      'event: diff\ndata: {"id": "p2", "path": "NOTES.md", "kind": "add", "diff": "# Notes\\n"}\n\n' +
      'event: status\ndata: {"status": "events_dropped", "count": 12}\n\n',
    { headers: { "content-type": "text/event-stream" } }));
  const watched: nc.AgentEvent[] = [];
  for await (const event of nc.Agent.fromId("ag_1").watch("task")) watched.push(event);
  const [partial, whole, ended, added, dropped] = watched;
  assert.deepEqual([partial.whole, whole.whole, whole.text, whole.callId], [false, true, "all of it\n", "c1"]);
  assert.deepEqual([ended.callId, ended.source, ended.exitCode, ended.durationMs, ended.isError], ["c1", "harness", 1, 1520, true]);
  assert.deepEqual([added.path, added.change, added.diff], ["NOTES.md", "add", "# Notes\n"]);
  assert.deepEqual([dropped.status, dropped.count], ["events_dropped", 12]);
  // Output names no source, exit, file or count: those stay unset.
  assert.deepEqual([partial.source, partial.exitCode, partial.path, partial.change, partial.count], [null, null, null, null, null]);
});

test("a coding agent's reply keeps its turn's steps, in the shape its live events showed them", async () => {
  // History names each message's turn; a reply's steps are its tool calls, a coding harness's own with what each
  // command printed and each edit's diff. Its live events say each step's kind as the kept steps do.
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const ran = {
    id: "c1", source: "harness", kind: "command", tool: "shell", arguments: { command: "npm test" }, command: "npm test",
    path: null, query: null, output: "Tests: 1 failed\n", exit_code: 1, duration_ms: 2400, is_error: true, result: null,
    diffs: [], created_at: "2026-11-09T10:00:01+00:00",
  };
  const edited = {
    ...ran, id: "e1", kind: "edit", tool: "edit", arguments: { path: "src/a.ts" }, command: null, path: "src/a.ts",
    output: null, exit_code: null, duration_ms: null, is_error: false,
    diffs: [{ path: "src/a.ts", kind: "update", diff: "@@ -1 +1 @@\n-a\n+b\n" }],
  };
  const searched = { tool: "search__search", arguments: { query: "vitest" }, result: "two results", is_error: false, created_at: null };
  api.on("GET", "/v1/agents/ag_1/conversations/task", json({ object: "conversation", messages: [
    { role: "user", text: "Fix the tests.", created_at: null, operation_id: "op_1" },
    { role: "assistant", text: "Fixed it.", created_at: null, operation_id: "op_1", tool_calls: [ran, searched, edited] },
    { role: "person", text: "Thanks!", created_at: null },
  ] }));
  const [asked, replied, thanked] = await nc.Agent.fromId("ag_1").history("task");
  assert.deepEqual([asked.operationId, replied.operationId, thanked.operationId], ["op_1", "op_1", null]);
  const [command, tool, edit] = replied.steps;
  assert.deepEqual([command.kind, command.callId, command.command, command.output, command.exitCode, command.durationMs,
    command.isError, command.createdAt?.toISOString()],
    ["command", "c1", "npm test", "Tests: 1 failed\n", 1, 2400, true, "2026-11-09T10:00:01.000Z"]);
  assert.deepEqual([tool.kind, tool.tool, tool.callId, tool.source, tool.result, tool.diffs], ["tool", "search__search", null, null, "two results", []]);
  assert.deepEqual([edit.kind, edit.path, edit.diffs], ["edit", "src/a.ts", [{ path: "src/a.ts", change: "update", diff: "@@ -1 +1 @@\n-a\n+b\n" }]]);
  assert.deepEqual([replied.toolCalls[0], command.raw], [ran, ran]);

  api.on("GET", "/v1/agents/ag_1/conversations/task/events", () => new Response(
    'event: tool_call\ndata: {"id": "g1", "tool": "Grep", "source": "harness", "kind": "search", "query": "TODO", "path": "src", "arguments": {"pattern": "TODO"}}\n\n' +
      'event: tool_result\ndata: {"id": "g1", "tool": "Grep", "source": "harness", "kind": "search", "is_error": false}\n\n' +
      'event: diff\ndata: {"id": "e1", "path": "src/a.ts", "kind": "update", "diff": "-a\\n+b\\n"}\n\n',
    { headers: { "content-type": "text/event-stream" } }));
  const watched: nc.AgentEvent[] = [];
  for await (const event of nc.Agent.fromId("ag_1").watch("task")) watched.push(event);
  assert.deepEqual(watched.map((e) => [e.stepKind, e.query, e.path, e.change]), [
    ["search", "TODO", "src", null], ["search", null, null, null], [null, null, "src/a.ts", "update"]]);

  // A turn's reply as its operation settles with it.
  const done = operation({ id: "op_1", kind: "agent.message", status: "succeeded", result: { text: "Fixed it.", tool_calls: [ran] } });
  api.on("GET", "/v1/operations/op_1/wait", json(done));
  const reply = await nc.Operation.fromId<nc.AgentReply>("op_1").wait();
  assert.deepEqual(reply.steps.map((step) => [step.kind, step.exitCode]), [["command", 1]]);
});

const SUMMARY = {
  label: "Read 5 files, searched 5 times", counts: { read: 7, search: 5, edit: 8, test: 3 }, failed: 3,
  changed: { label: "Changed 2 files", added: 310, removed: 0, by_script: 1, files: [
    { path: "usage.py", added: 0, removed: 0, how: ["sed", "script"] },
    { path: "test_platform_plan_usage.py", added: 310, removed: 0, how: [] }] },
  tests: { passed: 161, failed: 0, skipped: 0, total: 161, done: true, label: "161 passed" },
};
const GROUP = { id: "g:s2", label: "Read 2 files, searched for 2 patterns", counts: { read: 2, search: 2, list: 0 },
  step_ids: ["s2", "s3", "s4", "s5"], running: false };

test("a coding turn's steps say what they did in words, fold and sum up, live and kept alike", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const read = {
    id: "s3", source: "harness", kind: "command", tool: "shell", command: "sed -n 55,110p a.py",
    arguments: { command: "sed -n 55,110p a.py" }, output: "x\n", exit_code: 0, is_error: false, diffs: [],
    created_at: null, category: "read",
    label: { text: "Read a.py lines 55-110", verb: "Read", object: "a.py", detail: "lines 55-110" },
    label_source: "derived", display_command: "sed -n 55,110p a.py", lines: { from: 55, to: 110 }, output_lines: 1,
    failed: false, group: "g:s2",
  };
  const tests = { ...read, id: "s26", category: "test", label: { text: "Ran the plan usage tests", verb: "Ran" },
    label_source: "description", group: null, lines: null, output_lines: 4, tests: SUMMARY.tests,
    progress: { done: 161, total: 161 } };
  const edited = { ...read, id: "s15", kind: "edit", category: "edit", label: { text: "Edited usage.py" },
    diff_stat: { added: 3, removed: 1 }, group: null };
  api.on("GET", "/v1/agents/ag_1/conversations/task", json({ object: "conversation", messages: [
    { role: "assistant", text: "Done.", created_at: null, operation_id: "op_1", tool_calls: [read, tests, edited],
      summary: SUMMARY, groups: [GROUP] }] }));
  const [replied] = await nc.Agent.fromId("ag_1").history("task");
  const [sed, ran, edit] = replied.steps;
  assert.deepEqual([sed.category, sed.label, sed.labelSource, sed.displayCommand, sed.lines, sed.outputLines, sed.failed, sed.group],
    ["read", { text: "Read a.py lines 55-110", verb: "Read", object: "a.py", detail: "lines 55-110" }, "derived",
      "sed -n 55,110p a.py", { from: 55, to: 110 }, 1, false, "g:s2"]);
  assert.deepEqual([ran.label?.text, ran.labelSource, ran.tests, ran.progress], ["Ran the plan usage tests", "description",
    { passed: 161, failed: 0, skipped: 0, total: 161, done: true, label: "161 passed" }, { done: 161, total: 161 }]);
  assert.deepEqual(edit.diffStat, { added: 3, removed: 1 });
  const group = { id: "g:s2", label: GROUP.label, counts: GROUP.counts, stepIds: GROUP.step_ids, running: false, parent: null };
  assert.deepEqual(replied.groups, [group]);
  const summary = replied.summary!;
  assert.deepEqual([summary.label, summary.failed, summary.counts.edit, summary.tests?.label],
    ["Read 5 files, searched 5 times", 3, 8, "161 passed"]);
  assert.deepEqual(summary.changed, { label: "Changed 2 files", added: 310, removed: 0, byScript: 1, files: [
    { path: "usage.py", added: 0, removed: 0, how: ["sed", "script"] },
    { path: "test_platform_plan_usage.py", added: 310, removed: 0, how: [] }] });

  const moments: [string, unknown][] = [
    ["tool_call", { id: "s26", tool: "shell", source: "harness", kind: "command", category: "test",
      label: { text: "Running the plan usage tests", verb: "Running" }, display_command: "pytest x", group: null,
      arguments: { command: "pytest x" } }],
    ["output", { id: "s26", text: "....\n", output_lines: 3, progress: { done: 64, total: 161 },
      tests: { passed: 0, failed: 0, skipped: 0, total: 161, done: false, label: "64 of 161" } }],
    ["group", GROUP],
    ["tool_result", { id: "s26", tool: "shell", source: "harness", kind: "command", category: "test",
      label: { text: "Ran the plan usage tests" }, failed: false, group: null, tests: SUMMARY.tests, output_lines: 4 }],
    ["turn_end", { status: "succeeded", text: "Done.", operation_id: "op_1", summary: SUMMARY }],
  ];
  api.on("GET", "/v1/agents/ag_1/conversations/task/events", () => new Response(
    moments.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join(""),
    { headers: { "content-type": "text/event-stream" } }));
  const watched: nc.AgentEvent[] = [];
  for await (const event of nc.Agent.fromId("ag_1").watch("task")) watched.push(event);
  const [call, out, folded, end, turnEnd] = watched;
  assert.deepEqual([call.category, call.label?.text, call.displayCommand], ["test", "Running the plan usage tests", "pytest x"]);
  assert.deepEqual([out.progress, out.tests?.label, out.outputLines], [{ done: 64, total: 161 }, "64 of 161", 3]);
  assert.deepEqual(folded.stepGroup, group);
  assert.deepEqual([end.label?.text, end.failed, end.tests?.label], ["Ran the plan usage tests", false, "161 passed"]);
  assert.deepEqual(turnEnd.summary, summary);

  // A turn's reply as its operation settles with it.
  api.on("GET", "/v1/operations/op_1/wait", json(operation({ id: "op_1", kind: "agent.message", status: "succeeded",
    result: { text: "Done.", tool_calls: [read], summary: SUMMARY, groups: [GROUP] } })));
  const reply = await nc.Operation.fromId<nc.AgentReply>("op_1").wait();
  assert.deepEqual([reply.summary, reply.groups], [summary, [group]]);
});

test("a message says how it arrived, a note carries its data and joins a conversation once by its key", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const data = { setup: { kind: "agent", workflow_id: "wf_1" } };
  api.on("GET", "/v1/agents/ag_1/conversations/owner", json({ messages: [
    { role: "note", text: "Let’s finish setting up Bakery.", created_at: "2026-10-15T10:00:00Z", data },
    { role: "user", text: "Open Saturday?", created_at: "2026-10-15T10:01:00Z", via: "whatsapp" },
    { role: "assistant", text: "9 to 3.", created_at: "2026-10-15T10:01:05Z" },
  ] }));
  const agent = nc.Agent.fromId("ag_1");
  const [note, texted, reply] = await agent.history("owner");
  assert.deepEqual([note.role, note.data, note.via], ["note", data, null]);
  assert.deepEqual([texted.via, reply.via, reply.data], ["whatsapp", null, null]);
  api.on("GET", "/v1/agents/ag_1/conversations/owner/events", () => new Response(
    'event: message\ndata: {"role": "user", "text": "Hi", "via": "call", "operation_id": "op_1"}\n\n',
    { headers: { "content-type": "text/event-stream" } }));
  const watched: nc.AgentEvent[] = [];
  for await (const event of agent.watch("owner")) watched.push(event);
  assert.deepEqual(watched.map((e) => [e.role, e.via, e.data]), [["user", "call", null]]);

  const notes = api.on("POST", "/v1/agents/ag_1/conversations/owner/notes",
    json({ object: "note", added: true }, { status: 201 }), json({ object: "note", added: false }, { status: 201 }));
  assert.equal(await agent.note("owner", "Let’s finish setting up Bakery.", { data, key: "setup:wf_1" }), true);
  assert.deepEqual(notes.last.body, { text: "Let’s finish setting up Bakery.", data, key: "setup:wf_1" });
  assert.equal(await agent.note("owner", "Let’s finish setting up Bakery.", { data, key: "setup:wf_1" }), false);
});

test("the account's files list, then go with a message by id", async () => {
  const { api } = setup();
  const made = {
    object: "attachment", id: "res_1", name: "cake.png", mime_type: "image/png", size_bytes: 900, kind: "image",
    url: "https://assets.test/u/account/res_1/cake.png", voice: false, duration_ms: null, peaks: null,
    created_at: "2026-10-15T09:00:00+00:00",
  };
  const listed = api.on("GET", "/v1/attachments", json({ object: "list", data: [made], next_cursor: null }));
  const [cake] = await nc.attachments({ query: "cake", limit: 5 });
  assert.deepEqual([listed.last.query.get("query"), listed.last.query.get("limit")], ["cake", "5"]);
  assert.deepEqual([cake.id, cake.kind, cake.url], ["res_1", "image", made.url]);
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const send = api.on("POST", "/v1/agents/ag_1/messages", json(operation({ id: "op_1", kind: "agent.message", status: "queued" }), { status: 202 }));
  await nc.Agent.fromId("ag_1").send("Use this on the menu.", { conversation: "owner", files: [cake] });
  assert.deepEqual((send.last.body as { attachments: unknown }).attachments, ["res_1"]);
});

test("a turn shows its reasoning, its compaction and its long action's progress; history keeps the reasoning", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const progress = {
    step: null, line_count: 14, updated_at: "2026-10-15T10:00:21Z", lines: ["$ npm ci", "$ vite build"],
    stages: [
      { name: "Queued", status: "done", started_at: "2026-10-15T10:00:00Z", ended_at: "2026-10-15T10:00:03Z" },
      { name: "Building", status: "current", started_at: "2026-10-15T10:00:03Z", ended_at: null },
    ],
  };
  const sse = [
    'event: status\ndata: {"status": "compacting", "operation_id": "op_1"}\n',
    'event: reasoning\ndata: {"text": "Diagnosing workflow issues", "created_at": "2026-10-15T09:59:40Z", "operation_id": "op_1"}\n',
    `event: operation\ndata: ${JSON.stringify({ operation: { id: "op_2", kind: "project.deploy", status: "running", progress }, operation_id: "op_1" })}\n`,
    'event: done\ndata: {"text": "Deploying.", "conversation": "desk", "operation_id": "op_1"}\n\n',
  ].join("\n");
  api.on("POST", "/v1/agents/ag_1/messages", () => new Response(sse, { headers: { "content-type": "text/event-stream" } }));
  const events: nc.AgentEvent[] = [];
  for await (const event of nc.Agent.fromId("ag_1").stream("Deploy it.", { conversation: "desk" })) events.push(event);
  const [compacting, thought, deploying] = events;
  assert.deepEqual([compacting.type, compacting.status], ["status", "compacting"]);
  assert.deepEqual([thought.type, thought.text], ["reasoning", "Diagnosing workflow issues"]);
  assert.deepEqual((deploying.operation?.progress as { lines: string[] }).lines, ["$ npm ci", "$ vite build"]);

  api.on("GET", "/v1/agents/ag_1/conversations/desk", json({ messages: [
    { role: "assistant", text: "Deploying.", created_at: "2026-10-15T10:00:00Z",
      reasoning: [{ text: "Diagnosing workflow issues", created_at: "2026-10-15T09:59:40Z" }, { nope: 1 }] },
  ] }));
  const [reply] = await nc.Agent.fromId("ag_1").history("desk");
  assert.deepEqual(reply.reasoning.map((r) => [r.text, r.createdAt?.toISOString()]), [
    ["Diagnosing workflow issues", "2026-10-15T09:59:40.000Z"]]);

  api.on("GET", "/v1/operations/op_2", json(operation({ id: "op_2", kind: "project.deploy", status: "running", progress })));
  const op = await nc.Operation.fromId("op_2").hydrate();
  assert.deepEqual(op.progress?.stages.map((s) => [s.name, s.status]), [["Queued", "done"], ["Building", "current"]]);
  assert.deepEqual([op.progress?.lineCount, op.progress?.lines.at(-1)], [14, "$ vite build"]);
});
