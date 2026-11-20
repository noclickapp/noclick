// A conversation as a chat drives it: its settings, starting, forking and reverting one, the agent's one session
// cleared and resumed, its context and usage, a command NoClick has a control for, and every agent's state.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, operation, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "coder", model: "sonnet", harness: "claude_code", instructions: "Fix docs.",
  tools: [], user_id: null, workflow_id: "wf_1", created_at: "2026-11-10T10:00:00Z", effort: "high", speed: "standard",
};
const SETTINGS = {
  object: "conversation_settings", agent_id: "ag_1", conversation: "main", title: "Retries", archived: false,
  harness: "claude_code", model: "opus", effort: "high", efforts: ["low", "medium", "high", "xhigh", "max"],
  default_effort: null, speed: "fast", speeds: ["standard", "fast"], model_connection: "claude",
  accounts: [{ name: "claude", integration: "anthropic", kind: "plan", connected: true, usable: true, why: null },
             { name: "noclick", integration: null, kind: "noclick", connected: true, usable: false, why: "Not here." }],
  overridden: ["model", "speed"], permission_mode: "full-access", effective_permission_mode: "full-access",
  permission_modes: ["approval-required", "auto-accept-edits", "full-access"], not_supported: {}, forked_from: null,
};
const CONVERSATION = {
  object: "agent_conversation", conversation: "c1a2b3", agent_id: "ag_1", user_id: null, title: "Retries (fork)",
  preview: "Fix it", turns: 2, cost_usd: 0.12, last_activity: "2026-11-10T10:05:00Z", status: "active",
  handed_off_to: null, model_usage: null, archived: false,
  last_message: { role: "assistant", text: "Done.", created_at: "2026-11-10T10:05:00Z" },
  people: [{ type: "account", id: null, name: "Grace" }, { type: "user", id: "ada", name: "Ada" }],
  forked_from: { conversation: "main", message: "4", through: "5" }, agent_reads: "native",
};

test("a conversation's settings are read and changed, its model and effort being the agent's", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/conversations/main/settings", json(SETTINGS));
  const patched = api.on("PATCH", "/v1/agents/ag_1/conversations/main", json({ ...SETTINGS, model: "sonnet" }));
  const coder = nc.Agent.fromId("ag_1");
  const settings = await coder.conversation("main").settings();
  assert.deepEqual([settings.model, settings.effort, settings.speed, settings.modelConnection], ["opus", "high", "fast", "claude"]);
  assert.deepEqual(settings.efforts, ["low", "medium", "high", "xhigh", "max"]);
  assert.deepEqual(settings.speeds, ["standard", "fast"]);
  assert.deepEqual(settings.overridden, ["model", "speed"]);
  assert.deepEqual(settings.accounts.map((a) => [a.name, a.kind, a.usable]), [["claude", "plan", true], ["noclick", "noclick", false]]);
  await coder.conversation("main").update({ model: null, effort: "max", modelConnection: "noclick", title: "Retries", archived: true });
  assert.deepEqual(patched.last.body, { model: null, effort: "max", model_connection: "noclick", title: "Retries", archived: true });
});

test("conversations are started, forked from a message and listed with who's in them", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const started = api.on("POST", "/v1/agents/ag_1/conversations", json({ ...CONVERSATION, forked_from: null }));
  const forked = api.on("POST", "/v1/agents/ag_1/conversations/main/fork", json(CONVERSATION));
  const listed = api.on("GET", "/v1/agents/ag_1/conversations", json({ object: "list", data: [CONVERSATION], next_cursor: null }));
  const coder = nc.Agent.fromId("ag_1");
  await coder.startConversation({ title: "Retries" });
  assert.deepEqual(started.last.body, { title: "Retries" });
  const fork = await coder.conversation("main").fork({ message: "4" });
  assert.deepEqual(forked.last.body, { message: "4" });
  assert.deepEqual([fork.conversation, fork.forkedFrom?.message, fork.forkedFrom?.through, fork.agentReads], ["c1a2b3", "4", "5", "native"]);
  const [listedOne] = await coder.conversations({ archived: false });
  assert.equal(listed.last.query.get("archived"), "false");
  assert.equal(listedOne.lastMessage?.text, "Done.");
  assert.deepEqual(listedOne.people.map((p) => [p.type, p.name]), [["account", "Grace"], ["user", "Ada"]]);
});

test("an agent is one session: cleared, an earlier one resumed, and the active one read", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const cleared = api.on("POST", "/v1/agents/ag_1/conversations",
    json({ ...CONVERSATION, conversation: "c9", forked_from: null, active: true }, { status: 201 }));
  const resumed = api.on("POST", "/v1/agents/ag_1/conversations/c1a2b3/resume", json({ ...CONVERSATION, active: true }));
  const listed = api.on("GET", "/v1/agents/ag_1/conversations",
    json({ object: "list", data: [{ ...CONVERSATION, conversation: "c9" }], next_cursor: "p2" }),
    json({ object: "list", data: [{ ...CONVERSATION, active: true }], next_cursor: null }));
  const coder = nc.Agent.fromId("ag_1");
  const fresh = await coder.clear({ title: "Billing" });
  assert.deepEqual(cleared.last.body, { title: "Billing" });
  assert.deepEqual([fresh.conversation, fresh.active], ["c9", true]);
  const back = await coder.conversation("c1a2b3").resume();
  assert.equal(resumed.count, 1);
  assert.equal(back.active, true);
  const current = await coder.session();
  assert.deepEqual([current?.conversation, current?.active], ["c1a2b3", true]);
  assert.equal(listed.last.query.get("cursor"), "p2");
});

test("a revert goes back to before a message, and history names each message and who sent it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/conversations/main", json({
    object: "conversation", id: "main", agent_id: "ag_1", next_cursor: null, messages: [
      { id: "0", role: "user", text: "Fix it", created_at: "2026-11-10T10:00:00Z", author: { type: "user", id: "ada", name: "Ada" } },
      { id: "1", role: "assistant", text: "Done.", created_at: "2026-11-10T10:01:00Z", operation_id: "op_1" },
    ],
  }));
  const reverted = api.on("POST", "/v1/agents/ag_1/conversations/main/revert", json({
    object: "conversation_revert", conversation: "main", message: "0", text: "Fix it", dropped_turns: 1,
    files: { restored: ["app/retries.py"], kept: [], not_restored: [{ path: "big.json", why: "Too large." }], commands_not_undone: 2 },
    files_applied: "next_turn", agent_reads: "native",
  }));
  const coder = nc.Agent.fromId("ag_1");
  const [mine, reply] = await coder.history("main");
  assert.deepEqual([mine.id, mine.author?.name, reply.id, reply.author], ["0", "Ada", "1", null]);
  const done = await coder.conversation("main").revert(mine.id!, { files: true });
  assert.deepEqual(reverted.last.body, { message: "0", files: true });
  assert.deepEqual([done.text, done.droppedTurns, done.files.restored, done.files.notRestored[0].path, done.filesApplied],
    ["Fix it", 1, ["app/retries.py"], "big.json", "next_turn"]);
});

test("context and usage read the conversation; a mapped command resolves to its control's result", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/conversations/main/context", json({
    object: "conversation_context", model: "opus", used_tokens: 91000, window_tokens: 200000, percent: 45.5,
    auto_compacts_at: null, source: "harness", as_of: "2026-11-10T10:05:00Z",
  }));
  api.on("GET", "/v1/agents/ag_1/conversations/main/usage", json({
    object: "conversation_usage", cost_usd: 0.42, model_usage: null, turns: 3, pays_with: "plan",
    plan_limits: [{ label: "5-hour", used_percent: 31, resets_at: "2026-11-10T14:00:00Z" }],
  }));
  const sent = api.on("POST", "/v1/agents/ag_1/messages", json({
    object: "command_result", command: { name: "effort", arguments: "high" }, control: "effort", result: SETTINGS,
  }));
  const coder = nc.Agent.fromId("ag_1");
  const context = await coder.conversation("main").context();
  assert.deepEqual([context.usedTokens, context.windowTokens, context.percent, context.source], [91000, 200000, 45.5, "harness"]);
  const usage = await coder.conversation("main").usage();
  assert.deepEqual([usage.costUsd, usage.paysWith, usage.planLimits[0].usedPercent], [0.42, "plan", 31]);
  const outcome = await coder.conversation("main").runCommand("effort", "high");
  assert.deepEqual(sent.last.body, { command: { name: "effort", arguments: "high" }, conversation: "main" });
  assert.ok(!(outcome instanceof nc.Operation) && outcome.control === "effort");
});

test("every agent's state reads in one call, and an agent's effort and speed and the harnesses' traits read back", async () => {
  const { api } = setup();
  const states = api.on("GET", "/v1/agents/states", json({
    object: "list", read_at: "2026-11-10T10:05:00Z", data: [{
      agent_id: "ag_1", name: "coder", harness: "claude_code", state: "needs_you", conversation: "main",
      now: { tool: "Bash", kind: "command", line: "bash: pytest -x", since: "2026-11-10T10:04:00Z" },
      waiting: { asks: 1, held_calls: 0, requests: 2, total: 3 }, turn_started_at: "2026-11-10T10:03:00Z",
      last_active_at: "2026-11-10T10:04:00Z", failed: null, waking: null,
    }],
  }));
  const { data } = await nc.Agent.states({ workspace: "ws_1" });
  assert.equal(states.last.query.get("workspace_id"), "ws_1");
  assert.deepEqual([data[0].state, data[0].now?.line, data[0].waiting.total], ["needs_you", "bash: pytest -x", 3]);
  api.on("GET", "/v1/harnesses", json({ object: "list", data: [{
    object: "harness", name: "codex", label: "Codex", version: "0.162.0", default_model: "gpt-5-codex",
    custom_models: true, model_connection: "required", integrations: ["openai"], streaming: "final", shell: "built_in",
    notes: [], efforts: ["minimal", "low", "medium", "high", "xhigh"], default_effort: "medium", speeds: [],
    noclick_key: { runs: true, models: ["gpt-6-luna"] },
  }] }));
  const [codex] = await nc.Agent.harnesses();
  assert.deepEqual([codex.defaultEffort, codex.speeds, codex.noclickKey.runs, codex.noclickKey.models], ["medium", [], true, ["gpt-6-luna"]]);
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const coder = await nc.Agent.get("ag_1");
  assert.deepEqual([coder.effort, coder.speed], ["high", "standard"]);
});

const TOOL_SERVERS = {
  object: "tool_servers", source: "live", checked_at: "2026-11-10T10:06:00Z",
  data: [{ name: "noclick", status: "connected", tool_count: 12, error: null },
         { name: "linear", status: "failed", tool_count: null, error: "401 from the server" }],
  reconnect: { available: true, scope: "server", why: null },
};

test("a conversation's tool servers are read live and one is reconnected", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/conversations/main/tool_servers", json(TOOL_SERVERS));
  const again = api.on("POST", "/v1/agents/ag_1/conversations/main/tool_servers/linear/reconnect",
    json({ ...TOOL_SERVERS, data: [TOOL_SERVERS.data[0], { ...TOOL_SERVERS.data[1], status: "connecting", error: null }] }));
  const chat = nc.Agent.fromId("ag_1").conversation("main");
  const servers = await chat.toolServers();
  assert.equal(servers.source, "live");
  assert.deepEqual(servers.servers.map((s) => [s.name, s.status, s.toolCount, s.error]),
    [["noclick", "connected", 12, null], ["linear", "failed", null, "401 from the server"]]);
  assert.deepEqual(servers.reconnect, { available: true, scope: "server", why: null });
  assert.equal(servers.servers[0].tools, null);
  const after = await chat.reconnectToolServer("linear");
  assert.equal(again.calls.length, 1);
  assert.equal(after.servers[1].status, "connecting");
});

test("an agent's MCP server takes headers, which change and read back by name", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const server = { object: "agent_tool_server", id: "mcp_docs", name: "docs", url: "https://mcp.docs.example.com/mcp",
                   transport: "http", signed_in: false, headers: ["X-Api-Key"] };
  const added = api.on("POST", "/v1/agents/ag_1/tool_servers", json(server, { status: 201 }));
  const changed = api.on("PATCH", "/v1/agents/ag_1/tool_servers/mcp_docs", json({ ...server, headers: [] }));
  const coder = nc.Agent.fromId("ag_1");
  const docs = await coder.addToolServer("https://mcp.docs.example.com/mcp", { name: "docs", headers: { "X-Api-Key": "k-1" } });
  assert.deepEqual(added.last.body, { url: "https://mcp.docs.example.com/mcp", transport: "http", name: "docs", headers: { "X-Api-Key": "k-1" } });
  assert.deepEqual([docs.headers, docs.signedIn], [["X-Api-Key"], false]);
  assert.deepEqual((await coder.updateToolServer(docs, {})).headers, []);
  assert.deepEqual(changed.last.body, { headers: {} });
});

test("a conversation's tool servers name each tool where the harness lists them", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/conversations/main/tool_servers", json({ ...TOOL_SERVERS, data: [{
    ...TOOL_SERVERS.data[0], tool_count: 2,
    tools: [{ name: "search", description: "Search the account." }, { name: "fetch", description: null }] }] }));
  const [noclick] = (await nc.Agent.fromId("ag_1").conversation("main").toolServers()).servers;
  assert.deepEqual(noclick.tools, [{ name: "search", description: "Search the account." }, { name: "fetch", description: null }]);
});

const ADDED_SERVER = {
  object: "agent_tool_server", id: "mcp_docs", agent_id: "ag_1", name: "docs",
  url: "https://mcp.docs.example.com/mcp", host: "mcp.docs.example.com", transport: "http",
  signed_in: false, headers: [], sign_in: "browser", status: "signed_out",
  problem: { reason: "signed_out", message: "Its sign-in ended.", provider_said: "invalid_grant",
             since: "2026-11-18T09:00:00Z", next_step: "Sign in to it again." },
  tools: [{ name: "search_docs", description: "Search the docs." }],
  icon: { integration: "docs" }, checked_at: "2026-11-18T08:00:00Z",
};

test("an agent's MCP server says how it stands and signs in again by a link", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/tool_servers", json({ object: "list", data: [ADDED_SERVER] }));
  const made = api.on("POST", "/v1/agents/ag_1/tool_servers/mcp_docs/connect_link", json({
    object: "connect_link", url: "https://noclick.com/c/docs", expires_at: "2026-11-21T10:00:00Z",
    operation: operation({ id: "op_s", kind: "tool_server.sign_in" }) }, { status: 201 }));
  api.on("GET", "/v1/operations/op_s/wait", json(operation({
    id: "op_s", kind: "tool_server.sign_in", status: "succeeded",
    result: { tool_server: { ...ADDED_SERVER, signed_in: true, status: "unchecked", problem: null } } })));
  const [docs] = await nc.Agent.fromId("ag_1").toolServers();
  assert.deepEqual([docs.host, docs.signIn, docs.status, docs.icon],
    ["mcp.docs.example.com", "browser", "signed_out", { integration: "docs" }]);
  assert.deepEqual([docs.problem?.reason, docs.problem?.providerSaid, docs.problem?.since?.toISOString()],
    ["signed_out", "invalid_grant", "2026-11-18T09:00:00.000Z"]);
  assert.deepEqual(docs.tools, [{ name: "search_docs", description: "Search the docs." }]);
  assert.equal(docs.checkedAt?.toISOString(), "2026-11-18T08:00:00.000Z");
  const link = await docs.connectLink({ reason: "Sign in to the docs again" });
  assert.ok(link instanceof nc.ConnectLink);
  assert.deepEqual([link.url, link.id], ["https://noclick.com/c/docs", "op_s"]);
  assert.deepEqual(made.last.body, { reason: "Sign in to the docs again" });
  const again = await link.wait();
  assert.deepEqual([again.id, again.signedIn, again.status, again.problem], ["mcp_docs", true, "unchecked", null]);
  assert.equal(typeof again.connectLink, "function");
});

test("an agent's MCP servers read for a conversation say which can reconnect in place", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const read = api.on("GET", "/v1/agents/ag_1/tool_servers", json({ object: "list", data: [{
    ...ADDED_SERVER, status: "failed", reconnectable: true,
    problem: { ...ADDED_SERVER.problem, reason: "failed", message: "connection refused" } }] }));
  const [docs] = await nc.Agent.fromId("ag_1").toolServers({ conversation: "main" });
  assert.equal(read.last.query.get("conversation"), "main");
  assert.deepEqual([docs.status, docs.reconnectable, docs.problem?.message], ["failed", true, "connection refused"]);
});

test("a server read before its state was named reads as unchecked", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/tool_servers", json({ object: "list", data: [{
    object: "agent_tool_server", id: "mcp_docs", name: "docs", url: "https://mcp.docs.example.com/mcp",
    transport: "http", signed_in: false, headers: [] }] }));
  const [docs] = await nc.Agent.fromId("ag_1").toolServers();
  assert.deepEqual([docs.signIn, docs.status, docs.problem, docs.tools, docs.icon, docs.reconnectable],
    ["none", "unchecked", null, [], null, false]);
});

test("an agent's own permission mode is what its conversations start from", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json({ ...AGENT, permission_mode: "approval-required" }));
  const patched = api.on("PATCH", "/v1/agents/ag_1", json({ ...AGENT, permission_mode: "full-access" }));
  const coder = nc.Agent.fromId("ag_1");
  await coder.refresh();
  assert.equal(coder.permissionMode, "approval-required");
  await coder.update({ permissionMode: null });
  assert.deepEqual(patched.last.body, { permission_mode: null });
  assert.equal(coder.permissionMode, "full-access");
});

test("a coding agent runs Docker in a VM of its size", async () => {
  const { api } = setup();
  const made = api.on("POST", "/v1/agents", json({ ...AGENT, docker: true, sandbox_size: "large" }));
  const tester = await nc.Agent.create("tester", {
    instructions: "Run the test suite.", harness: "claude_code", modelConnection: "claude", docker: true,
    sandboxSize: "large",
  });
  const sent = made.last.body as Record<string, unknown>;
  assert.deepEqual([sent.docker, sent.sandbox_size], [true, "large"]);
  assert.deepEqual([tester.docker, tester.sandboxSize], [true, "large"]);
  const patched = api.on("PATCH", `/v1/agents/${AGENT.id}`, json({ ...AGENT, docker: false, sandbox_size: null }));
  await tester.update({ docker: false });
  assert.deepEqual(patched.last.body, { docker: false });
  assert.deepEqual([tester.docker, tester.sandboxSize], [false, null]);
  await tester.update({ sandboxSize: null });
  assert.deepEqual(patched.last.body, { sandbox_size: null });
});

test("a coding agent turns app testing on by itself unless its owner says", async () => {
  const { api } = setup();
  const made = api.on("POST", "/v1/agents", json({ ...AGENT, app_testing: "ask_first" }));
  const coder = await nc.Agent.create("coder", {
    instructions: "Keep checkout's tests green.", harness: "claude_code", modelConnection: "claude",
    appTesting: "ask_first",
  });
  assert.equal((made.last.body as Record<string, unknown>).app_testing, "ask_first");
  assert.equal(coder.appTesting, "ask_first");
  const patched = api.on("PATCH", `/v1/agents/${AGENT.id}`, json({ ...AGENT, app_testing: "never" }));
  await coder.update({ appTesting: "never" });
  assert.deepEqual(patched.last.body, { app_testing: "never" });
  assert.equal(coder.appTesting, "never");
  api.on("POST", "/v1/agents", json(AGENT));
  const older = await nc.Agent.create("older", { instructions: "x", harness: "claude_code" });
  assert.equal(older.appTesting, "by_itself"); // an older NoClick's agent reads as the default
});

test("an update sets the secrets in its shell, by id or name, and setup", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/secrets", json({ object: "list", data: [{ object: "secret", id: "4f1b2c3d-0000-4000-8000-000000000002", name: "github", keys: ["GH_TOKEN"] }], next_cursor: null }));
  const patched = api.on("PATCH", "/v1/agents/ag_1", json(AGENT));
  const coder = nc.Agent.fromId("ag_1");
  await coder.update({ secrets: ["4f1b2c3d-0000-4000-8000-000000000001", "github"], setup: [] });
  assert.deepEqual(patched.last.body, {
    secret_ids: ["4f1b2c3d-0000-4000-8000-000000000001", "4f1b2c3d-0000-4000-8000-000000000002"], setup: [],
  });
});
