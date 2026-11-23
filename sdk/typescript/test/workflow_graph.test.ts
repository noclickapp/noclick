// A workflow's graph through its handles, against the mock API answering as the API's `/v1` graph routes do:
// the graph read whole into typed steps, each single edit as a one-op batch with
// no version check, a batch sent once and atomically with its `ifVersion`, a stale batch refused with the workflow
// as it stands, an op that can't apply named, versions paged, read and restored.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, listing, setup } from "./helpers.ts";

const WF = "wf_1";
const EDITS = `/v1/workflows/${WF}/edits`;
const CREDENTIAL = "9b2a1c5e-7d9f-4a31-8f6d-3f1d2c4b8a7e";
// An account connected in the app: its connection's id is credential:<this>.
const IN_APP = "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f";

const HOOK = {
  id: "hook", type: "trigger-webhook", position: { x: 0, y: 0 },
  config: { label: "New order", http_method: "POST", webhook_url: "https://wf-1.noclick.run" },
};
const WRITER = {
  id: "writer", type: "agent", position: { x: 320, y: 0 },
  config: {
    label: "Writer", operation: "default", model: "openrouter/anthropic/claude-sonnet-4", system_prompt: "Summarize the order.",
    credentialIds: { agent_openrouter: CREDENTIAL }, channel__label: "#orders",
  },
};
const LINEAR = {
  id: "linear", type: "automation-linear", position: { x: 320, y: 200 },
  config: { label: "Linear", operation: "create_issue", disabled: true, mockedOutput: { id: "ISS-1" } },
};
// A step the canvas saved in its own shape: its fields beside data.config.
const CANVAS = {
  id: "post", type: "automation-slack", position: { x: 640, y: 0 },
  data: { label: "Post it", operation: "send_message_to_channel", disabled: false, config: { channel: "#team", text: "{{ $('writer').text }}" } },
};
const NOTE = {
  id: "stickyNote-1-abc123", type: "stickyNote", position: { x: 0, y: -150 },
  config: { content: "Orders land here.", color: 8 }, width: 240, height: 120,
};
const EDGES = [
  { id: "hook-writer", source: "hook", target: "writer", type: "animated" },
  { id: "linear-writer", source: "linear", target: "writer", type: "animated", targetHandle: "bottom" },
  { id: "writer-post", source: "writer", target: "post", type: "animated" },
];

/** A graph as the routes show one (`public_graph`): nodes as stored, edges, the secrets left out. */
function bare(nodes: object[] = [HOOK, WRITER, LINEAR, CANVAS, NOTE], edges: object[] = EDGES, withheld: object = { writer: ["api_key"] }) {
  return { nodes, edges, withheld };
}

const DEFINITION = {
  name: "Order intake", description: "Files each order.",
  settings: { variable_definitions: [{ name: "team", value: "#orders" }, { name: "token" }] },
  settings_withheld: ["variable_definitions[1].value"],
};

/** `GET /v1/workflows/{id}/graph`: the workflow's definition, its secrets left out by path. */
function read(version = 4, graph: object = bare()) {
  return { object: "workflow_graph", workflow_id: WF, version, ...DEFINITION, graph };
}

/** `POST /v1/workflows/{id}/edits`; with `include_graph`, the definition as `/graph` reads it. */
function edited(
  version: number, results: object[],
  extra: { steps?: object; graph?: object; changed?: boolean; summary?: string; historyVersion?: number } = {},
) {
  const changed = extra.changed ?? true;
  return {
    object: "workflow_edit", workflow_id: WF, version, changed, history_version: extra.historyVersion ?? (changed ? version : null),
    summary: extra.summary ?? "changed it", results, steps: extra.steps ?? {}, ...(extra.graph ? { ...DEFINITION, graph: extra.graph } : {}),
  };
}

/** `GET /v1/workflows/{id}`: the workflow at a glance, with its version. */
function view(version = 4, extra: object = {}) {
  return { object: "workflow", id: WF, name: "Order intake", description: "Files each order.", version, access: "owner", steps: [], ...extra };
}

/** The 409 a stale `if_version` answers: the workflow as it stands. */
function stale(version: number, graph: object) {
  return apiError(409, "conflict", `The workflow is at version ${version}, not 4: it changed since it was read.`, {
    next_step: "Apply the edits to the graph returned here and send them again with if_version set to its version.",
    workflow_id: WF, version, graph,
  });
}

/** A version of the history: its own number, fixed, and the workflow's version its latest write left. */
function versionRow(historyVersion: number, version = historyVersion + 10, source = "api", extra: object = {}) {
  const author = source === "baseline" ? null : { user_id: "u_1", key_id: "key_1" };
  return {
    object: "workflow_version", workflow_id: WF, history_version: historyVersion, version, source,
    author, authors: author ? [author] : [], summary: `version ${historyVersion}`,
    changes: [`version ${historyVersion}`], restored_from: null, created_at: "2026-10-30T10:00:00Z", updated_at: "2026-10-30T10:04:00Z", ...extra,
  };
}

const ops = (route: { last: { body: unknown } }) => (route.last.body as { ops: unknown[] }).ops;

// --- reading -------------------------------------------------------------------------

test("a graph reads the whole definition into typed steps, notes and edges", async () => {
  const { api } = setup();
  const route = api.on("GET", `/v1/workflows/${WF}/graph`, json(read(4, {
    ...bare(undefined, undefined, { writer: ["api_key"], hook: ["headers[0].value"] }), variables_withheld: ["api_base"],
  })));
  const workflow = nc.Workflow.fromId(WF);
  assert.throws(() => workflow.version, /not loaded yet/);
  const graph = await workflow.graph();
  assert.equal(route.count, 1);
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.ok(graph instanceof nc.WorkflowGraph);
  assert.deepEqual([graph.workflowId, graph.version, workflow.version], [WF, 4, 4]);
  assert.deepEqual([graph.name, graph.description, graph.settings, graph.settingsWithheld], [
    "Order intake", "Files each order.", DEFINITION.settings, ["variable_definitions[1].value"]]);
  assert.deepEqual([graph.variablesWithheld, graph.withheld], [["api_base"], { writer: ["api_key"], hook: ["headers[0].value"] }]);

  assert.deepEqual(graph.steps.map((s) => s.id), ["hook", "writer", "linear", "post"]);
  const [hook, writer, linear, post] = graph.steps;
  assert.deepEqual([hook.type, hook.name, hook.operation, hook.enabled], ["trigger-webhook", "New order", null, true]);
  assert.deepEqual(hook.settings, { http_method: "POST", webhook_url: "https://wf-1.noclick.run" });
  assert.deepEqual(hook.withheld, ["headers[0].value"]);
  // Its name, operation and connections are fields of their own, never settings; the app's label cache isn't one.
  assert.deepEqual(writer.settings, { model: "openrouter/anthropic/claude-sonnet-4", system_prompt: "Summarize the order." });
  assert.deepEqual([writer.connections, writer.withheld, writer.position], [{ agent_openrouter: CREDENTIAL }, ["api_key"], { x: 320, y: 0 }]);
  assert.deepEqual([linear.enabled, linear.mockOutput, linear.settings], [false, { id: "ISS-1" }, {}]);
  assert.deepEqual([post.name, post.operation, post.settings], ["Post it", "send_message_to_channel", { channel: "#team", text: "{{ $('writer').text }}" }]);
  assert.deepEqual([writer.verdict, writer.notes], [null, {}]);
  assert.equal(writer.workflow, workflow);

  const [note] = graph.notes;
  assert.deepEqual([note.type, note.settings.content], ["stickyNote", "Orders land here."]);
  assert.deepEqual(graph.edges, [
    { id: "hook-writer", from: "hook", to: "writer", kind: "data", handle: null, targetHandle: null },
    { id: "linear-writer", from: "linear", to: "writer", kind: "tools", handle: null, targetHandle: null },
    { id: "writer-post", from: "writer", to: "post", kind: "data", handle: null, targetHandle: null },
  ]);
  assert.equal(graph.displayMetadata, null);
  assert.equal(graph.step("writer"), writer);
  assert.equal(graph.step("Post it"), post);
  assert.throws(() => graph.step("Nope"), nc.NotFound);
});

test("a step's account is the connection naming its credential id", async () => {
  const { api } = setup();
  api.on("GET", `/v1/workflows/${WF}/graph`, json(read()));
  const named = {
    object: "connection", id: "6f3c2d1e-0a9b-4c8d-9e7f-5a4b3c2d1e0f", name: "openrouter", integration: "openrouter",
    credential_type: "agent_openrouter", origin: "api", status: "connected", credential_id: CREDENTIAL,
  };
  const inApp = { ...named, id: `credential:${IN_APP}`, name: "OpenRouter key", origin: "app", credential_id: IN_APP };
  const pending = { ...named, id: "0e1d2c3b-4a59-4687-9a8b-7c6d5e4f3a2b", name: "later", status: "pending", credential_id: null };
  api.on("GET", "/v1/connections", json(listing([named, inApp, pending])));
  const writer = (await nc.Workflow.fromId(WF).graph()).step("writer");
  const connections = await nc.Connection.list();
  const byCredential = new Map(connections.filter((c) => c.credentialId).map((c) => [c.credentialId, c]));
  assert.equal(byCredential.get(writer.connections.agent_openrouter)?.name, "openrouter");
  assert.deepEqual(connections.map((c) => c.credentialId), [CREDENTIAL, IN_APP, null]);
});

test("the workflow's version comes with its read and moves with each answer", async () => {
  const { api } = setup();
  api.on("GET", `/v1/workflows/${WF}`, json(view(7)));
  api.on("POST", `/v1/workflows/${WF}/pause`, json(view(8, { paused: true })));
  api.on("POST", EDITS, json(edited(9, [{ op: "layout" }], { changed: false })));
  const workflow = await nc.Workflow.fromId(WF).hydrate();
  assert.equal(workflow.version, 7); // read with the workflow
  await workflow.pause("Quiet week");
  assert.equal(workflow.version, 8); // a pause writes its triggers' records
  const moved = await workflow.edit({ ifVersion: workflow.version ?? undefined }, (e) => e.layout());
  assert.deepEqual([workflow.version, moved?.historyVersion], [9, null]); // moving things is no version of the history
});

test("a name two steps share is refused by name", async () => {
  const { api } = setup();
  api.on("GET", `/v1/workflows/${WF}/graph`, json(read(4, bare([CANVAS, { ...CANVAS, id: "post2" }], []))));
  const graph = await nc.Workflow.fromId(WF).graph();
  assert.throws(() => graph.step("Post it"), (err: unknown) => err instanceof nc.Conflict && (err.details.ids as string[]).length === 2);
  assert.equal(graph.step("post2").id, "post2");
});

test("a step handle sends nothing until it's loaded", async () => {
  const { api } = setup();
  const route = api.on("GET", `/v1/workflows/${WF}/graph`, json(read()));
  const workflow = nc.Workflow.fromId(WF);
  const writer = workflow.step("writer");
  assert.equal(route.count, 0);
  assert.equal(writer.id, "writer");
  assert.throws(() => writer.name, /not loaded yet/);
  assert.equal((await writer.hydrate()).name, "Writer");
  assert.equal(route.count, 1);
  // Another handle reads from the graph this one loaded; refresh reads it again.
  assert.equal((await workflow.step("hook").hydrate()).type, "trigger-webhook");
  assert.equal(route.count, 1);
  await writer.refresh();
  assert.equal(route.count, 2);
  await assert.rejects(workflow.step("ghost").hydrate(), (err: unknown) => err instanceof nc.NotFound && err.details.step === "ghost");
});

// --- single edits ----------------------------------------------------------------------

test("addStep is one edit with its id and the graph as written", async () => {
  const { api } = setup();
  const added = { id: "done", type: "log", position: { x: 640, y: 200 }, config: { label: "Done", message: "ok" } };
  const route = api.on("POST", EDITS, json(edited(5, [{ op: "add_step", id: "done", resolutions: { message: "ok" } }], {
    steps: { done: { config_valid: true } }, graph: bare([HOOK, added], []),
  })));
  const workflow = nc.Workflow.fromId(WF);
  const done = await workflow.addStep("log", { name: "Done", settings: { message: "ok" }, id: "done" });
  assert.deepEqual(route.last.body, {
    ops: [{ op: "add_step", type: "log", settings: { message: "ok" }, name: "Done", id: "done" }], include_graph: true,
  });
  assert.ok(done instanceof nc.Step);
  assert.deepEqual([done.id, done.name, done.position], ["done", "Done", { x: 640, y: 200 }]);
  assert.deepEqual([done.verdict, done.notes], [{ config_valid: true }, { resolutions: { message: "ok" } }]);
  assert.equal(workflow.version, 5);
  assert.equal(workflow.lastEdit?.results[0].id, "done");

  // Left without an id, it's named from its type, as the API names one.
  await workflow.addStep("automation-gmail", { operation: "send_email_message", position: { x: 10, y: 20 } });
  const [op] = ops(route) as { id: string; position: unknown }[];
  assert.match(op.id, /^automation-gmail-\d+-[0-9a-f]{6}$/);
  assert.deepEqual(op.position, { x: 10, y: 20 });
  assert.equal("if_version" in (route.last.body as object), false);
});

test("each step method is one op", async () => {
  const { api } = setup();
  const route = api.on("POST", EDITS, json(edited(5, [{ op: "x", id: "writer" }], { graph: bare() })));
  const workflow = nc.Workflow.fromId(WF);
  const writer = workflow.step("writer");

  assert.equal(await writer.update({ settings: { system_prompt: "Be brief." }, name: "Brief writer", enabled: false }), writer);
  assert.deepEqual(ops(route), [{ op: "update_step", id: "writer", settings: { system_prompt: "Be brief." }, name: "Brief writer", enabled: false }]);
  await writer.update({ operation: "default" });
  assert.deepEqual(ops(route), [{ op: "update_step", id: "writer", operation: "default" }]);
  await writer.patch("system_prompt", "@@ Summarize\n-Summarize the order.\n+Summarize it.");
  assert.deepEqual(ops(route), [{ op: "patch_step", id: "writer", field: "system_prompt", patch: "@@ Summarize\n-Summarize the order.\n+Summarize it." }]);
  await workflow.step("hook").connect(writer);
  assert.deepEqual(ops(route), [{ op: "connect", from: "hook", to: "writer", kind: "data" }]);
  await workflow.step("linear").connect("writer", { kind: "tools" });
  assert.deepEqual(ops(route), [{ op: "connect", from: "linear", to: "writer", kind: "tools" }]);
  await workflow.step("loop").connect("writer", { handle: "loop" });
  assert.deepEqual(ops(route), [{ op: "connect", from: "loop", to: "writer", kind: "data", handle: "loop" }]);
  await workflow.step("hook").disconnect("writer");
  assert.deepEqual(ops(route), [{ op: "disconnect", from: "hook", to: "writer" }]);
  await writer.mock({ text: "A summary." });
  assert.deepEqual(ops(route), [{ op: "mock_step", id: "writer", output: { text: "A summary." } }]);
  await writer.unmock();
  assert.deepEqual(ops(route), [{ op: "unmock_step", id: "writer" }]);
  assert.equal(await writer.remove(), undefined);
  assert.deepEqual(ops(route), [{ op: "remove_step", id: "writer" }]);
  // One op each, never a version check, and always the graph back.
  for (const call of route.calls) {
    const sent = call.body as { if_version?: number; include_graph?: boolean };
    assert.deepEqual([sent.if_version, sent.include_graph], [undefined, true]);
  }
});

test("setConnection sends a connection's ref, its name or id, and null takes one off", async () => {
  const { api } = setup();
  const route = api.on("POST", EDITS, json(edited(5, [{ op: "set_connection", id: "post", slot: "slack_oauth" }], { graph: bare() })));
  const post = nc.Workflow.fromId(WF).step("post");
  await post.setConnection(nc.Connection.fromId(`credential:${CREDENTIAL}`));
  assert.deepEqual(ops(route), [{ op: "set_connection", id: "post", connection: `credential:${CREDENTIAL}` }]);
  const named = "4c1e9a2b-7f3d-4e8a-9b6c-2d5f8e1a3c7b";
  await post.setConnection(nc.Connection.fromId(named));
  assert.deepEqual(ops(route), [{ op: "set_connection", id: "post", connection: named }]);
  await post.setConnection("work-slack");
  assert.deepEqual(ops(route), [{ op: "set_connection", id: "post", connection: "work-slack" }]);
  await post.setConnection(CREDENTIAL, { slot: "slack_oauth" });
  assert.deepEqual(ops(route), [{ op: "set_connection", id: "post", connection: CREDENTIAL, slot: "slack_oauth" }]);
  await post.setConnection(null, { slot: "slack_oauth" });
  assert.deepEqual(ops(route), [{ op: "set_connection", id: "post", connection: null, slot: "slack_oauth" }]);
  assert.deepEqual(post.notes, { slot: "slack_oauth" });
});

test("an edit surfaces its notes and verdicts", async () => {
  const { api } = setup();
  const switched = { ...WRITER, config: { label: "Writer", model: "codex", codex_model: "gpt-5" } };
  const harnessSwitch = { from: "sdk", to: "codex", removed_fields: ["temperature"], unlinked_credentials: ["openrouter"] };
  api.on("POST", EDITS, json(edited(5, [{ op: "update_step", id: "writer", changed: true, harness_switch: harnessSwitch }], {
    steps: {
      writer: { config_valid: false, validation_error: "Codex needs an OpenAI key.", missing_required: ["credentials"] },
      post: { config_valid: true },
    },
    graph: bare([HOOK, switched], []),
  })));
  const workflow = nc.Workflow.fromId(WF);
  const writer = await workflow.step("writer").update({ settings: { model: "codex" } });
  assert.deepEqual(writer.notes, { changed: true, harness_switch: harnessSwitch });
  assert.deepEqual([writer.verdict?.config_valid, writer.verdict?.missing_required], [false, ["credentials"]]);
  assert.deepEqual([writer.settings, writer.connections], [{ model: "codex", codex_model: "gpt-5" }, {}]);
  assert.deepEqual(workflow.lastEdit?.steps.post, { config_valid: true });
  assert.deepEqual(writer.references, []);
});

test("an edit names the reads that won't resolve", async () => {
  const { api } = setup();
  const unresolved = [
    { field: "title", step: "hook", key: "ordr_id", known_keys: ["order_id", "total"] },
    { field: "title", step: "hok", reference: "{{ $('hok').order_id }}", missing: true, near: "hook" },
  ];
  api.on("POST", EDITS, json(edited(5, [{ op: "update_step", id: "linear", changed: true }], {
    steps: { linear: { config_valid: true, references: unresolved } },
    graph: bare([HOOK, LINEAR], []),
  })));
  const workflow = nc.Workflow.fromId(WF);
  const linear = await workflow.step("linear").update({ settings: { title: "{{ $('hook').ordr_id }} {{ $('hok').order_id }}" } });
  assert.deepEqual(linear.references, unresolved);
  assert.deepEqual(linear.verdict?.references, unresolved);
});

test("the workflow's own fields, notes and moves", async () => {
  const { api } = setup();
  const route = api.on("POST", EDITS, json(edited(5, [{ op: "x", id: "stickyNote-9" }], { graph: bare() })));
  api.on("GET", `/v1/workflows/${WF}`, json({ object: "workflow", id: WF, name: "Order desk", description: "Files each order in Linear." }));
  const workflow = nc.Workflow.fromId(WF);
  assert.equal(await workflow.update({ name: "Order desk", description: "Files each order in Linear." }), workflow);
  assert.deepEqual(ops(route), [{ op: "update_workflow", name: "Order desk", description: "Files each order in Linear." }]);
  // The edit may have renamed it: the next read loads the workflow again.
  assert.equal((await workflow.hydrate()).name, "Order desk");

  const note = await workflow.addNote("Orders land here.", { near: [workflow.step("hook"), "writer"], color: 3 });
  const [sent] = ops(route) as { id: string }[];
  assert.deepEqual(sent, { op: "add_note", content: "Orders land here.", id: sent.id, color: 3, near: ["hook", "writer"] });
  assert.match(sent.id, /^stickyNote-/);
  assert.equal(note.id, sent.id);
  await workflow.addNote("The order stretch.", { id: "span", after: "hook", before: "post" });
  assert.deepEqual(ops(route), [{ op: "add_note", content: "The order stretch.", id: "span", after: "hook", before: "post" }]);

  const moved = await workflow.move("post", { x: 900, y: 40 });
  assert.deepEqual(ops(route), [{ op: "move", id: "post", position: { x: 900, y: 40 } }]);
  assert.deepEqual([moved.id, moved.position], ["post", { x: 640, y: 0 }]); // the answer's graph says where it is
});

// --- batches -----------------------------------------------------------------------------

test("a batch is one request in order with its version, and later ops name new steps", async () => {
  const { api } = setup();
  const added = { id: "post2", type: "automation-slack", position: { x: 0, y: 0 }, config: { label: "Post again", operation: "send_message_to_channel" } };
  const route = api.on("POST", EDITS, json(edited(5, [
    { op: "add_step", id: "post2" }, { op: "connect", from: "writer", to: "post2", kind: "data", edge_id: "writer-post2" },
    { op: "update_step", id: "writer", changed: true }, { op: "define_variable", name: "team" },
    { op: "add_test_run", name: "Big order", slug: "big-order", trigger_type: "trigger-webhook" }, { op: "layout" },
  ], { steps: { post2: { config_valid: false, missing_required: ["channel"] } }, graph: bare([HOOK, WRITER, added]), summary: "added 'Post again'" })));
  const workflow = nc.Workflow.fromId(WF);
  let again: nc.Step | undefined;
  let batch: nc.EditBatch | undefined;
  const result = await workflow.edit({ ifVersion: 4, includeGraph: true }, (e) => {
    batch = e;
    again = e.addStep("automation-slack", { operation: "send_message_to_channel", name: "Post again", id: "post2" });
    e.connect("writer", again);
    e.updateStep(workflow.step("writer"), { settings: { system_prompt: "Be brief." } });
    e.defineVariable("team", { value: "#team", description: "Where it posts" });
    e.addTestRun("hook", "Big order", '{"total": 900}', { title: "A big order" });
    e.layout();
    assert.equal(route.count, 0);
    assert.equal(e.ops.length, 6);
  });
  assert.equal(route.count, 1);
  assert.deepEqual(route.last.body, {
    ops: [
      { op: "add_step", type: "automation-slack", operation: "send_message_to_channel", name: "Post again", id: "post2" },
      { op: "connect", from: "writer", to: "post2", kind: "data" },
      { op: "update_step", id: "writer", settings: { system_prompt: "Be brief." } },
      { op: "define_variable", name: "team", value: "#team", description: "Where it posts" },
      { op: "add_test_run", trigger: "hook", name: "Big order", body: '{"total": 900}', title: "A big order" },
      { op: "layout" },
    ],
    if_version: 4, include_graph: true,
  });
  assert.ok(result);
  assert.deepEqual([result.version, result.historyVersion, result.changed, result.summary], [5, 5, true, "added 'Post again'"]);
  // Asked for the graph, the answer is the workflow as written, as graph() reads it.
  assert.deepEqual(result.graph?.steps.map((s) => s.id), ["hook", "writer", "post2"]);
  assert.deepEqual([result.graph?.name, result.graph?.settingsWithheld], ["Order intake", ["variable_definitions[1].value"]]);
  // The step the batch added knows what the batch said about it, and reads from the graph it wrote.
  assert.deepEqual([again?.verdict, again?.name], [{ config_valid: false, missing_required: ["channel"] }, "Post again"]);
  assert.equal(workflow.version, 5);
  assert.equal(workflow.lastEdit, result);
  assert.equal(batch?.result, result);
  assert.throws(() => batch?.layout(), /sent already/);
});

test("a batch whose function throws or queues nothing sends nothing", async () => {
  const { api } = setup();
  const route = api.on("POST", EDITS, json(edited(5, [])));
  const workflow = nc.Workflow.fromId(WF);
  await assert.rejects(workflow.edit({}, (e) => {
    e.removeStep("writer");
    throw new Error("changed my mind");
  }), /changed my mind/);
  assert.equal(await workflow.edit({}, async () => {}), null);
  assert.equal(route.count, 0);
});

test("a connection given to a batch is resolved when it's sent", async () => {
  const { api } = setup();
  const route = api.on("POST", EDITS, json(edited(5, [{ op: "remove_step", id: "writer" }])));
  await nc.Workflow.fromId(WF).edit({ ifVersion: 4 }, async (e) => {
    e.removeStep("writer");
    e.setConnection("post", nc.Connection.fromId(`credential:${CREDENTIAL}`));
  });
  assert.deepEqual(route.last.body, {
    ops: [{ op: "remove_step", id: "writer" }, { op: "set_connection", id: "post", connection: `credential:${CREDENTIAL}` }],
    if_version: 4,
  });
});

test("an agent step's secrets go by name, whatever names them", async () => {
  // `secrets` on an agent step (its update, a batch's add or update, the workflow's add): names, or `Secret` objects
  // sent as their names; [] takes them all off. Never a value.
  const { api } = setup();
  const route = api.on("POST", EDITS, json(edited(5, [{ op: "update_step", id: "writer" }], { graph: bare() })));
  api.on("GET", "/v1/secrets", json(listing([
    { object: "secret", id: "sec_1", name: "shipping", keys: ["SHIPPING_TOKEN"], user_id: null, used_by: [] }])));
  const workflow = nc.Workflow.fromId(WF);
  await workflow.step("writer").update({ secrets: ["warehouse", nc.Secret.fromName("shipping")] });
  assert.deepEqual(ops(route), [{ op: "update_step", id: "writer", settings: { secrets: ["warehouse", "shipping"] } }]);
  await workflow.step("writer").update({ settings: { message: "Go." }, secrets: ["warehouse"] });
  assert.deepEqual(ops(route), [{ op: "update_step", id: "writer", settings: { message: "Go.", secrets: ["warehouse"] } }]);
  await workflow.step("writer").update({ secrets: [] });
  assert.deepEqual(ops(route), [{ op: "update_step", id: "writer", settings: { secrets: [] } }]);

  await workflow.edit({}, async (e) => {
    e.addStep("agent", { id: "second", settings: { model: "openrouter/anthropic/claude-sonnet-4" }, secrets: [nc.Secret.fromName("shipping")] });
    e.updateStep("writer", { secrets: ["warehouse"] });
  });
  assert.deepEqual(ops(route), [
    { op: "add_step", type: "agent", id: "second", settings: { model: "openrouter/anthropic/claude-sonnet-4", secrets: ["shipping"] } },
    { op: "update_step", id: "writer", settings: { secrets: ["warehouse"] } },
  ]);
});

test("a setting only the person knows is left for them", async () => {
  // `leftForUser` on a step's update, a batch's add or update and the workflow's add: the settings' names, sent as
  // the edit takes them. Never beside a made-up value.
  const { api } = setup();
  const left = { config_valid: false, left_for_user: ["to_number"] };
  const route = api.on("POST", EDITS, json(edited(5, [{ op: "update_step", id: "writer", changed: true }], {
    graph: bare(), steps: { writer: left },
  })));
  const workflow = nc.Workflow.fromId(WF);
  const step = await workflow.step("writer").update({ leftForUser: ["to_number"] });
  assert.deepEqual(ops(route), [{ op: "update_step", id: "writer", left_for_user: ["to_number"] }]);
  assert.deepEqual(step.verdict, left);
  await workflow.step("writer").update({ settings: { body: "Down." }, leftForUser: ["to_number"] });
  assert.deepEqual(ops(route), [
    { op: "update_step", id: "writer", settings: { body: "Down." }, left_for_user: ["to_number"] }]);

  await workflow.edit({}, async (e) => {
    e.addStep("automation-http-request", { id: "check", operation: "send_http_get_request", leftForUser: ["url"] });
    e.updateStep("writer", { leftForUser: ["from_number", "to_number"] });
  });
  assert.deepEqual(ops(route), [
    { op: "add_step", type: "automation-http-request", id: "check", operation: "send_http_get_request", left_for_user: ["url"] },
    { op: "update_step", id: "writer", left_for_user: ["from_number", "to_number"] },
  ]);
});

// --- refusals ----------------------------------------------------------------------------

test("a stale batch is a Conflict carrying the workflow as it stands", async () => {
  const { api } = setup();
  const now = bare([HOOK, { ...WRITER, config: { ...WRITER.config, label: "Renamed" } }], []);
  const route = api.on("POST", EDITS, stale(6, now), json(edited(7, [{ op: "update_step", id: "writer", changed: true }])));
  const workflow = nc.Workflow.fromId(WF);
  let changed: nc.Conflict | undefined;
  try {
    await workflow.edit({ ifVersion: 4 }, (e) => e.updateStep("writer", { name: "Writer v2" }));
  } catch (err) {
    if (!(err instanceof nc.Conflict)) throw err;
    changed = err;
  }
  assert.ok(changed?.graph instanceof nc.WorkflowGraph);
  assert.deepEqual([changed.version, changed.graph.version, changed.graph.step("writer").name], [6, 6, "Renamed"]);
  assert.match(changed.nextStep ?? "", /if_version/);
  // The handle now knows the workflow as it stands: read, decide again, send again.
  assert.equal(workflow.version, 6);
  assert.equal((await workflow.step("writer").hydrate()).name, "Renamed");
  const again = await workflow.edit({ ifVersion: workflow.version ?? undefined }, (e) => e.updateStep("writer", { name: "Writer v2" }));
  assert.equal((route.last.body as { if_version: number }).if_version, 6);
  assert.equal(again?.version, 7);
});

test("the documented retry loop decides again from the conflict's graph", async () => {
  const { api } = setup();
  const first = bare([HOOK, WRITER, CANVAS], []);
  const movedOn = bare([HOOK, WRITER, { ...CANVAS, data: { ...CANVAS.data, config: { ...CANVAS.data.config, channel: "#sales" } } }], []);
  api.on("GET", `/v1/workflows/${WF}/graph`, json(read(4, first)));
  const route = api.on("POST", EDITS, stale(5, movedOn), json(edited(6, [])));
  const workflow = nc.Workflow.fromId(WF);
  let graph = await workflow.graph();
  for (let attempt = 0; attempt < 3; attempt++) {
    const post = graph.step("Post it");
    try {
      await workflow.edit({ ifVersion: graph.version }, (e) => e.updateStep(post, { settings: { text: `${post.settings.channel}: done` } }));
      break;
    } catch (err) {
      if (!(err instanceof nc.Conflict) || !err.graph) throw err;
      graph = err.graph;
    }
  }
  assert.deepEqual(route.calls.map((c) => (c.body as { if_version: number }).if_version), [4, 5]);
  assert.deepEqual((ops(route)[0] as { settings: object }).settings, { text: "#sales: done" });
});

test("an op that can't apply is named and nothing lands", async () => {
  const { api } = setup();
  api.on("POST", EDITS, apiError(400, "invalid_request", "No step 'ghost' in this workflow.", {
    next_step: "Fix ops[1] and send the batch again; nothing of it was applied.", field: "ops[1].id", op: 1,
  }));
  const workflow = nc.Workflow.fromId(WF);
  await assert.rejects(workflow.edit({}, (e) => {
    e.updateStep("writer", { name: "Kept?" });
    e.removeStep("ghost");
  }), (err: unknown) => err instanceof nc.InvalidRequest && err.details.field === "ops[1].id" && err.details.op === 1);
  assert.deepEqual([workflow._version, workflow.lastEdit], [null, null]);
});

test("an agent's workflow keeps its agent's own step", async () => {
  const { api } = setup();
  api.on("POST", EDITS, apiError(400, "invalid_request", "'agent' is the agent 'helper' itself: its workflow keeps it.", {
    next_step: "Leave 'agent' in, or delete the agent (DELETE /v1/agents/ag_1).", agent_id: "ag_1",
  }));
  const workflow = nc.Workflow.fromId(WF);
  await assert.rejects(workflow.step("agent").remove(),
    (err: unknown) => err instanceof nc.InvalidRequest && err.details.agent_id === "ag_1");
  assert.equal(workflow.lastEdit, null);
});

test("a canvas saves as one batch in its own terms", async () => {
  const { api } = setup();
  const route = api.on("POST", EDITS, json(edited(5, [])));
  await nc.Workflow.fromId(WF).edit({ ifVersion: 4, source: "canvas" }, (e) => {
    e.updateStep("writer", { settings: { system_prompt: "Be brief.", channel__label: null } });
    e.connect("state", "code", { targetHandle: "state", id: "xy-edge__state-code" });
    e.disconnect("writer", "post", { id: "writer-post" });
    e.addNote("Read me", { id: "note-2", position: { x: 40, y: -120 }, width: 280, height: 160 });
    e.move("note-2", { x: 60, y: -140 }, { width: 320, height: 200 });
    e.updateWorkflow({ displayMetadata: { viewport: { x: 0, y: 0, zoom: 1 } } });
  });
  assert.deepEqual(route.last.body, {
    ops: [
      { op: "update_step", id: "writer", settings: { system_prompt: "Be brief.", channel__label: null } },
      { op: "connect", from: "state", to: "code", kind: "data", target_handle: "state", id: "xy-edge__state-code" },
      { op: "disconnect", from: "writer", to: "post", id: "writer-post" },
      { op: "add_note", content: "Read me", id: "note-2", width: 280, height: 160, position: { x: 40, y: -120 } },
      { op: "move", id: "note-2", position: { x: 60, y: -140 }, width: 320, height: 200 },
      { op: "update_workflow", display_metadata: { viewport: { x: 0, y: 0, zoom: 1 } } },
    ],
    if_version: 4, source: "canvas",
  });
});

test("a canvas names itself on its batch and a closing tab's last one outlives the page", async () => {
  const { api } = setup();
  const route = api.on("POST", EDITS, json(edited(5, [])));
  const layout = { layout: [{ i: "post", x: 0, y: 0, w: 6, h: 4 }], tabOrder: ["post"] };
  await nc.Workflow.fromId(WF).edit({ ifVersion: 4, source: "canvas", origin: "canvas-tab-1" }, (e) => {
    e.connect("writer", "post", { handle: "right", targetHandle: "left", id: "xy-edge__writerright-postleft" });
    e.setConnection("writer", CREDENTIAL, { slot: "agent_claude_code" });
    e.updateWorkflow({ interface: layout });
  });
  assert.equal(route.last.keepalive, false);
  assert.deepEqual(route.last.body, {
    ops: [
      { op: "connect", from: "writer", to: "post", kind: "data", handle: "right", target_handle: "left",
        id: "xy-edge__writerright-postleft" },
      { op: "set_connection", id: "writer", connection: CREDENTIAL, slot: "agent_claude_code" },
      { op: "update_workflow", interface: layout },
    ],
    if_version: 4, source: "canvas", origin: "canvas-tab-1",
  });
  await nc.Workflow.fromId(WF).edit({ source: "canvas", origin: "canvas-tab-1", keepalive: true }, (e) => {
    e.updateStep("writer", { settings: { system_prompt: "Last words." } });
  });
  assert.equal(route.last.keepalive, true);
  assert.deepEqual(route.last.body, {
    ops: [{ op: "update_step", id: "writer", settings: { system_prompt: "Last words." } }],
    source: "canvas", origin: "canvas-tab-1",
  });
});

test("the Interface tab's layout is one of the workflow's own fields", async () => {
  const { api } = setup();
  const route = api.on("POST", EDITS, json(edited(6, [])));
  const layout = { layout: [], tabOrder: [] };
  await nc.Workflow.fromId(WF).update({ interface: layout });
  assert.deepEqual(route.last.body, { ops: [{ op: "update_workflow", interface: layout }], include_graph: true });
});

test("a graph reads what the app shows and an edge's input", async () => {
  const { api } = setup();
  api.on("GET", `/v1/workflows/${WF}/graph`, json({
    ...read(4, bare([HOOK], [{ id: "s-c", source: "state", target: "code", targetHandle: "state" }])),
    display_metadata: { viewport: { zoom: 2 } },
  }));
  const graph = await nc.Workflow.fromId(WF).graph();
  assert.deepEqual(graph.displayMetadata, { viewport: { zoom: 2 } });
  assert.deepEqual(graph.edges, [{ id: "s-c", from: "state", to: "code", kind: "data", handle: null, targetHandle: "state" }]);
  assert.deepEqual([graph.access, graph.agent], [null, null]);
});

test("a graph reads what its reader may do with it and whose agent it is", async () => {
  const { api } = setup();
  api.on("GET", `/v1/workflows/${WF}/graph`, json({
    ...read(4, bare([HOOK])), access: "editor", agent: { id: "agt_1", name: "Support", yours: true },
  }));
  const graph = await nc.Workflow.fromId(WF).graph();
  assert.deepEqual([graph.access, graph.agent], ["editor", { id: "agt_1", name: "Support", yours: true }]);
});

test("a batch held for the owner surfaces as its approval and lands nothing", async () => {
  const { api } = setup();
  api.on("GET", `/v1/workflows/${WF}/graph`, json(read()));
  api.on("POST", EDITS, apiError(402, "approval_required", "Edit 'Order intake': it waits for the account's owner.", {
    next_step: "Tell them to tap the link NoClick sent them.", status: "awaiting_approval", approval_id: "appr_1",
    operation_id: "op_held", summary: "Edit 'Order intake'", sent_to: ["whatsapp"], expires_at: "2026-10-31T10:00:00Z",
  }));
  const workflow = nc.Workflow.fromId(WF);
  await workflow.graph();
  await assert.rejects(workflow.edit({ ifVersion: 4 }, (e) => e.removeStep("post")),
    (err: unknown) => err instanceof nc.ApprovalRequired && err.operationId === "op_held" && err.approvalId === "appr_1"
      // The held batch is its own operation: NoClick applies it once the owner approves.
      && err.operation?.id === "op_held" && err.operation.kind === "gate.held_call");
  assert.deepEqual([workflow.version, workflow.lastEdit], [4, null]);
  assert.equal((await workflow.step("post").hydrate()).name, "Post it");
});

test("a conflict's graph holds the steps alone", async () => {
  const { api } = setup();
  api.on("POST", EDITS, stale(6, bare([HOOK], [])));
  const err = await nc.Workflow.fromId(WF).edit({ ifVersion: 4 }, (e) => e.layout()).catch((e: unknown) => e);
  assert.ok(err instanceof nc.Conflict && err.graph);
  assert.deepEqual(err.graph.steps.map((s) => s.id), ["hook"]);
  assert.deepEqual([err.graph.name, err.graph.description, err.graph.settings, err.graph.settingsWithheld], [null, null, null, null]);
});

test("a conflict elsewhere has no graph", () => {
  const error = new nc.Conflict("It already exists.", { details: { existing_id: "ag_1" } });
  assert.deepEqual([error.graph, error.version, error.existingId], [null, undefined, "ag_1"]);
});

// --- versions ----------------------------------------------------------------------------

test("versions page through the cursor", async () => {
  const { api } = setup();
  const route = api.on("GET", `/v1/workflows/${WF}/versions`,
    json(listing([versionRow(5, 15), versionRow(4, 12, "canvas", {
      authors: [{ user_id: "u_1", key_id: "key_1" }, { user_id: "u_2", key_id: null }],
    })], "12")),
    json(listing([versionRow(3, 9, "restore", { restored_from: 1 }), versionRow(1, 1, "baseline")])));
  const versions = await nc.Workflow.fromId(WF).versions({ limit: null });
  assert.deepEqual(versions.map((v) => [v.historyVersion, v.version, v.source]), [
    [5, 15, "api"], [4, 12, "canvas"], [3, 9, "restore"], [1, 1, "baseline"]]);
  assert.equal(route.calls[1].query.get("cursor"), "12");
  assert.deepEqual([versions[0].author, versions[3].author], [{ user_id: "u_1", key_id: "key_1" }, null]);
  // A canvas session is one version, whoever edited in it: its author first.
  assert.deepEqual(versions[1].authors, [{ user_id: "u_1", key_id: "key_1" }, { user_id: "u_2", key_id: null }]);
  assert.deepEqual([versions[0].authors, versions[3].authors], [[{ user_id: "u_1", key_id: "key_1" }], []]);
  assert.deepEqual([versions[2].restoredFrom, versions[0].graph, versions[0].changes], [1, null, ["version 5"]]);
  assert.equal(versions[0].createdAt?.getUTCFullYear(), 2026);
});

test("one page of versions, and one version with its whole definition", async () => {
  const { api } = setup();
  const pageRoute = api.on("GET", `/v1/workflows/${WF}/versions`, json(listing([versionRow(5)], "15")));
  api.on("GET", `/v1/workflows/${WF}/versions/2`, json({
    ...versionRow(2, 12, "api", { graph: bare([HOOK, WRITER], []) }), ...DEFINITION, name: "Order intake (old)",
  }));
  api.on("GET", `/v1/workflows/${WF}/versions/9`, apiError(404, "not_found", "This workflow has no version 9."));
  const workflow = nc.Workflow.fromId(WF);
  const page = await workflow.versionsPage({ limit: 1, cursor: "20" });
  assert.deepEqual([page.data.map((v) => v.historyVersion), page.nextCursor, pageRoute.last.query.get("limit")], [[5], "15", "1"]);
  const two = await workflow.versionAt(2);
  assert.deepEqual([two.historyVersion, two.version, two.graph?.version], [2, 12, 12]);
  assert.deepEqual(two.graph?.steps.map((s) => s.id), ["hook", "writer"]);
  assert.deepEqual([two.graph?.name, two.graph?.description, two.graph?.settingsWithheld], [
    "Order intake (old)", "Files each order.", ["variable_definitions[1].value"]]);
  await assert.rejects(workflow.versionAt(9), nc.NotFound);
});

test("restoring a version is a version of its own, checked against the version it's given", async () => {
  const { api } = setup();
  const route = api.on("POST", `/v1/workflows/${WF}/versions/2/restore`,
    stale(6, bare([HOOK], [])), json({ ...edited(7, [], { summary: "restored version 2", historyVersion: 4 }), restored_from: 2 }));
  const workflow = nc.Workflow.fromId(WF);
  await assert.rejects(workflow.restore({ historyVersion: 2, ifVersion: 5 }), (err: unknown) => err instanceof nc.Conflict && err.version === 6);
  assert.deepEqual([route.last.body, workflow.version], [{ if_version: 5 }, 6]);
  assert.equal(await workflow.restore({ historyVersion: 2 }), workflow);
  assert.deepEqual(route.last.body, {});
  const edit = workflow.lastEdit;
  assert.deepEqual([workflow.version, edit?.historyVersion, edit?.restoredFrom, edit?.summary], [7, 4, 2, "restored version 2"]);
  await assert.rejects(workflow.restore({ ifVersion: 7 }), TypeError);
});

test("naming versions keeps them, and a name comes back off", async () => {
  const { api } = setup();
  const named = versionRow(5, 5, "api", {
    label: "Before Slack", note: "Sends at 8.", labeled_by: { user_id: "u_1" }, labeled_at: "2026-11-21T10:00:00Z",
  });
  const now = api.on("POST", `/v1/workflows/${WF}/versions`, json(named, { status: 201 }));
  const patch = api.on("PATCH", `/v1/workflows/${WF}/versions/5`,
    json({ ...named, label: "Before the Slack change" }),
    json({ ...named, label: null, note: null, labeled_by: null, labeled_at: null }));
  const listed = api.on("GET", `/v1/workflows/${WF}/versions`, json(listing([named])), json(listing([named])));
  const workflow = nc.Workflow.fromId(WF);
  const saved = await workflow.nameVersion("Before Slack", { note: "Sends at 8.", ifVersion: 4 });
  assert.deepEqual(now.last.body, { label: "Before Slack", note: "Sends at 8.", if_version: 4 });
  assert.deepEqual([saved.label, saved.note, saved.labeledBy, saved.labeledAt?.getUTCFullYear()], [
    "Before Slack", "Sends at 8.", { user_id: "u_1" }, 2026]);
  const renamed = await workflow.nameVersion("Before the Slack change", { historyVersion: 5 });
  assert.deepEqual([patch.last.body, renamed.label], [{ label: "Before the Slack change", note: null }, "Before the Slack change"]);
  assert.equal((await workflow.unnameVersion(5)).label, null);
  assert.deepEqual(patch.last.body, { label: null });
  assert.deepEqual((await workflow.versions({ named: true })).map((v) => v.label), ["Before Slack"]);
  assert.equal(listed.last.query.get("named"), "true");
  await workflow.versions();
  assert.equal(listed.last.query.get("named"), null);
});

test("naming the version it's at twice is a Conflict naming the first", async () => {
  const { api } = setup();
  api.on("POST", `/v1/workflows/${WF}/versions`, apiError(409, "conflict", "Nothing changed since the version named 'Start'.", {
    history_version: 2, label: "Start",
  }));
  await assert.rejects(nc.Workflow.fromId(WF).nameVersion("Start again"),
    (err: unknown) => err instanceof nc.Conflict && err.details.label === "Start");
});

test("restore without a version still brings it back from the trash", async () => {
  const { api } = setup();
  const route = api.on("POST", `/v1/workflows/${WF}/restore`, json(view(3, { name: "x" })));
  const workflow = nc.Workflow.fromId(WF);
  assert.equal((await workflow.restore()).name, "x");
  assert.deepEqual([route.count, workflow.version], [1, 3]);
});

// --- fromName ----------------------------------------------------------------------------

test("fromName with a description gets, then sets it where it differs", async () => {
  const { api } = setup();
  const row = { object: "workflow", id: WF, name: "Order intake", description: "Old." };
  api.on("GET", "/v1/workflows", json(listing([row])));
  const edits = api.on("POST", EDITS, json(edited(4, [{ op: "update_workflow" }], { changed: false })));
  api.on("GET", `/v1/workflows/${WF}`, json({ ...row, description: "Files each order." }));
  const workflow = await nc.Workflow.fromName("Order intake", { description: "Files each order." }).hydrate();
  assert.equal(workflow.description, "Files each order.");
  assert.deepEqual(edits.last.body, { ops: [{ op: "update_workflow", description: "Files each order." }] });
  // As it already has it, nothing is set; and the bare handle only looks it up.
  await nc.Workflow.fromName("Order intake", { description: "Old." }).hydrate();
  await nc.Workflow.fromName("Order intake").hydrate();
  assert.equal(edits.count, 1);
});

test("steps of a workflow reached by name load it once", async () => {
  const { api } = setup();
  const lookup = api.on("GET", "/v1/workflows", json(listing([{ object: "workflow", id: WF, name: "Order intake" }])));
  const route = api.on("POST", EDITS, json(edited(5, [{ op: "connect" }], { graph: bare() })));
  const workflow = nc.Workflow.fromName("Order intake");
  await workflow.step("hook").connect("writer");
  await workflow.step("writer").connect("post");
  assert.deepEqual([lookup.count, route.count, lookup.last.query.get("name")], [1, 2, "Order intake"]);
});


test("an edit that settles waits and says what its writes left", async () => {
  const { api } = setup();
  const route = api.on("POST", EDITS, json({
    ...edited(5, [{ op: "add_step", id: "hook" }], { graph: bare([HOOK], []) }), settled: true,
    unregistered: { stripe: "Finish setup before activation: connect a Stripe account." },
    warnings: ["Your Gmail account won't work in this workflow's automatic runs."],
  }), json(edited(6, [{ op: "update_step", id: "hook" }])));
  const workflow = nc.Workflow.fromId(WF);
  const settled = await workflow.edit({ settle: true, includeGraph: true }, (e) => {
    e.addStep("trigger-webhook", { id: "hook", name: "Hook" });
  });
  assert.equal((route.last.body as { settle: boolean }).settle, true);
  assert.equal(settled?.settled, true);
  assert.deepEqual(settled?.unregistered, { stripe: "Finish setup before activation: connect a Stripe account." });
  assert.deepEqual(settled?.warnings, ["Your Gmail account won't work in this workflow's automatic runs."]);
  assert.equal(settled?.graph?.step("hook").settings.webhook_url, "https://wf-1.noclick.run");
  // Without settle the field isn't sent, and an answer without them reads as none.
  const plain = await workflow.edit({}, (e) => { e.updateStep("hook", { name: "Order placed" }); });
  assert.equal("settle" in (route.last.body as object), false);
  assert.deepEqual([plain?.settled, plain?.unregistered, plain?.warnings], [null, {}, []]);
});

test("settle waits for what earlier edits set going and changes nothing", async () => {
  const { api } = setup();
  const route = api.on("POST", EDITS, json({ ...edited(5, [], { changed: false }), settled: false, unregistered: {} }));
  const settled = await nc.Workflow.fromId(WF).settle();
  assert.deepEqual(route.last.body, { ops: [], settle: true });
  assert.deepEqual([settled.settled, settled.changed], [false, false]);
});
