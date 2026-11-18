// Moves from a laptop: `AgentMove.create` makes one (its code and prompt only then), `refresh` follows it as the Draft
// screen does on each platform:resource frame, `cancel` calls it off; the moving side carries what it chose with the
// move's own key and finishes it.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { FINISH_POLL_MS } from "../src/agentMove.ts";
import { json, setup } from "./helpers.ts";

const ARRIVED = {
  session: null, repo: null, files: [], consent: [], secrets: [], setup: [], checkout: null, mcp_servers: [], skills: [],
  memories: [], note: null, instructions: null, carried: [],
};
const MOVE = {
  object: "agent_move", id: "mv_1", status: "waiting", workspace_id: "ws_1", draft: { name: "Docs fixer" }, source: null,
  arrived: ARRIVED, steps: [], agent_id: null, conversation: null, error: null, guide_url: "https://noclick.com/move.md",
  expires_at: "2026-11-10T10:30:00Z", created_at: "2026-11-10T10:00:00Z",
};

test("make a move, follow what arrives, and call it off", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/agents/moves", json({ ...MOVE, code: "nc_move_abc", prompt: "Move this session to NoClick: …" }, { status: 201 }));
  const move = await nc.AgentMove.create({ name: "Docs fixer", workspaceId: "ws_1", harness: "claude_code", machine: "mc_1" });
  assert.deepEqual(create.last.body, { workspace_id: "ws_1", name: "Docs fixer", harness: "claude_code", machine_id: "mc_1" });
  assert.deepEqual([move.id, move.status, move.code, move.guideUrl], ["mv_1", "waiting", "nc_move_abc", "https://noclick.com/move.md"]);
  assert.match(move.prompt ?? "", /^Move this session/);

  api.on("GET", "/v1/agents/moves/mv_1", json({
    ...MOVE, status: "finishing",
    source: { harness: "claude_code", host: "ana-mbp", cwd: "/Users/ana/code/acme", cli_version: "2.1.295", session_id: "s1", title: "Fix retries" },
    arrived: { ...ARRIVED, session: { harness: "claude_code", session_id: "s1", title: "Fix retries", messages: 182, tool_calls: 40 },
               repo: { repo_id: "rp_1", name: "acme", branch: "laptop/ana-mbp-20261110", path: "acme" },
               files: [{ path: "notes/spec.md", size_bytes: 36 }],
               secrets: [{ name: "database-url", to: { env: "DATABASE_URL" } }],
               mcp_servers: [{ name: "linear", url: "https://mcp.linear.app/mcp", transport: "http",
                               headers: [{ name: "Authorization", secret: "linear-token" }], needs_sign_in: false },
                             { name: "notion", url: "https://mcp.notion.com/mcp", transport: "http", headers: [],
                               needs_sign_in: true }],
               memories: [{ name: "deploy-steps", description: "How it deploys" }], note: { chars: 80 } },
    steps: [{ name: "agent", label: "Making it", status: "done", detail: "Docs fixer on Claude Code" },
            { name: "space", label: "Adding it to the space", status: "running" }],
  }));
  const read = nc.AgentMove.fromId("mv_1");
  await read.refresh();
  assert.equal(read.status, "finishing");
  assert.equal(read.code, null);
  assert.deepEqual(read.source, { harness: "claude_code", host: "ana-mbp", cwd: "/Users/ana/code/acme", cliVersion: "2.1.295", sessionId: "s1", title: "Fix retries" });
  const arrived = read.arrived;
  assert.deepEqual(arrived.session, { harness: "claude_code", sessionId: "s1", title: "Fix retries", messages: 182, toolCalls: 40 });
  assert.deepEqual(arrived.repo, { repoId: "rp_1", name: "acme", branch: "laptop/ana-mbp-20261110" });
  assert.deepEqual(arrived.files, [{ path: "notes/spec.md", sizeBytes: 36 }]);
  assert.deepEqual(arrived.secrets, [{ name: "database-url", to: { env: "DATABASE_URL" } }]);
  assert.deepEqual(arrived.mcpServers, [{ name: "linear", url: "https://mcp.linear.app/mcp", transport: "http",
                                          headers: [{ name: "Authorization", secret: "linear-token" }], needsSignIn: false },
                                        { name: "notion", url: "https://mcp.notion.com/mcp", transport: "http", headers: [],
                                          needsSignIn: true }]);
  assert.deepEqual(arrived.memories, [{ name: "deploy-steps", description: "How it deploys" }]);
  assert.deepEqual(read.steps.map((s) => [s.name, s.status]), [["agent", "done"], ["space", "running"]]);

  const cancel = api.on("POST", "/v1/agents/moves/mv_1/cancel", json({ ...MOVE, status: "canceled" }));
  await read.cancel();
  assert.equal(read.status, "canceled");
  assert.equal(cancel.count, 1);
});

test("the moving side carries its session and finishes", async () => {
  const { api, sleeps } = setup();
  const redeem = api.on("POST", "/v1/moves/redeem", new Response("nk_live_movekey\n", { headers: { "Content-Type": "text/plain" } }));
  assert.equal(await nc.AgentMove.redeem("nc_move_abc", { host: "ana-mbp" }), "nk_live_movekey");
  assert.equal(redeem.last.body, "code=nc_move_abc&host=ana-mbp");

  const view = { ...MOVE, status: "moving", lands_as: { name: "Docs fixer", harness: "claude_code", cwd: "/workspace/acme" },
                 endpoints: ["GET /v1/moves/current — The move this key carries"] };
  api.on("GET", "/v1/moves/current", json(view));
  const moving = await nc.AgentMove.current();
  assert.equal(moving.landsAs?.cwd, "/workspace/acme");
  assert.deepEqual(moving.endpoints, ["GET /v1/moves/current — The move this key carries"]);
  const source = api.on("PUT", "/v1/moves/current/source", json(view));
  const session = api.on("PUT", "/v1/moves/current/session", json(view));
  const consent = api.on("PUT", "/v1/moves/current/consent", json(view));
  const secret = api.on("PUT", "/v1/moves/current/secrets/linear-token", json(view));
  const setupCall = api.on("PUT", "/v1/moves/current/setup", json(view));
  const checkout = api.on("PUT", "/v1/moves/current/checkout", json(view));
  const plan = api.on("POST", "/v1/moves/current/plan_link", json({ object: "plan_link", url: "https://x.test/p" }));
  const note = api.on("PUT", "/v1/moves/current/note", json(view));
  const connector = api.on("PUT", "/v1/moves/current/mcp_servers/notion", json(view));
  const running = { ...view, status: "finishing", steps: [{ name: "secrets", label: "Bringing its secrets", status: "running" }] };
  const finish = api.on("POST", "/v1/moves/current/finish", json({ ...running, steps: [] }));

  await moving.setSource({ harness: "claude_code", host: "ana-mbp", cwd: "/Users/ana/code/acme" });
  assert.deepEqual(source.last.body, { harness: "claude_code", host: "ana-mbp", cwd: "/Users/ana/code/acme" });
  await moving.uploadSession(new TextEncoder().encode("TAR"), { harness: "claude_code", cwd: "/Users/ana/code/acme" });
  assert.equal(session.last.query.get("harness"), "claude_code");
  const asked = [{ name: "linear-token", kind: "Linear API key", to: "env LINEAR_API_KEY" }];
  await moving.consent(asked, { confirmed: true });
  assert.deepEqual(consent.last.body, { secrets: asked, confirmed: true });
  await moving.putSecret("linear-token", "lin_x", { to: { env: "LINEAR_API_KEY" } });
  assert.deepEqual(secret.last.body, { value: "lin_x", to: { env: "LINEAR_API_KEY" } });
  await moving.setSetup(["npm install -g @linear/cli"]);
  assert.deepEqual(setupCall.last.body, { commands: ["npm install -g @linear/cli"] });
  await moving.setCheckout("https://github.com/acme/web.git", "noclick/ana", { secret: "linear-token" });
  assert.deepEqual(checkout.last.body, { url: "https://github.com/acme/web.git", branch: "noclick/ana", secret: "linear-token" });
  assert.equal((await moving.planLink()).url, "https://x.test/p");
  assert.equal(plan.calls.length, 1);
  await moving.addMcpServer("notion", "https://mcp.notion.com/mcp", { signIn: "browser" });
  assert.deepEqual(connector.last.body, { url: "https://mcp.notion.com/mcp", transport: "http", headers: {}, sign_in: "browser" });
  await moving.setNote("Next: a test for the third retry.");
  assert.equal(note.last.body, "Next: a test for the third retry.");
  // The finish answers at once and runs on NoClick: the move is read until it ends, a failed step throwing its own error.
  const refusal = { type: "conflict", message: "The carried OpenRouter key doesn't run Claude Code here.",
                    next_step: 'Finish again on one it runs: {"harness": "opencode"}.' };
  const reads = api.on("GET", "/v1/moves/current", json(running), json({
    ...view, status: "failed", error: refusal.message, next_step: refusal.next_step,
    steps: [{ name: "agent", label: "Making it", status: "failed", error: refusal.message, failure: refusal }] }));
  sleeps.length = 0;
  await assert.rejects(moving.finish(), (e: unknown) => e instanceof nc.Conflict && e.nextStep === refusal.next_step);
  assert.equal(finish.count, 1);
  assert.deepEqual(sleeps, [FINISH_POLL_MS, FINISH_POLL_MS]);
  assert.equal(reads.count, 2);
  api.on("GET", "/v1/moves/current", json({ ...view, status: "done", agent_id: "ag_1", conversation: "moved-s1" }));
  await moving.finish({ harness: "opencode", model: "openrouter/anthropic/claude-sonnet-4.5" });
  assert.deepEqual([moving.status, moving.agentId, moving.conversation], ["done", "ag_1", "moved-s1"]);
  assert.deepEqual(finish.last.body, { harness: "opencode", model: "openrouter/anthropic/claude-sonnet-4.5" });
  assert.equal((await moving.finish({ wait: false })).status, "finishing");
  const asking = api.on("POST", "/v1/moves/current/finish", json({ ...view, question: "No MCP server and no skill?" }));
  await moving.finish({ none: ["mcp_servers", "skills"] });
  assert.deepEqual(asking.last.body, { none: ["mcp_servers", "skills"] });
  assert.equal(moving.question, "No MCP server and no skill?");
  assert.equal(finish.last.headers.get("NoClick-User"), null);
});

test("the person signs in to a tool server the move carried needing it", async () => {
  const { api } = setup();
  const carried = { name: "notion", to: { tool_server: "notion" }, url: "https://mcp.notion.com/mcp", needs_sign_in: false,
                    step: "mcp-1", reused: false, credential_id: "cr_1" };
  const route = api.on("POST", "/v1/agents/moves/mv_1/sign_ins/notion",
                       json({ ...MOVE, status: "done", agent_id: "ag_1", arrived: { ...ARRIVED, carried: [carried] } }));
  const move = await nc.AgentMove.fromId("mv_1").connectSignIn("notion", "cr_1");
  assert.deepEqual(route.last.body, { credential_id: "cr_1" });
  assert.deepEqual(move.arrived.carried, [carried]);
});

test("an agent says where a move made it from", async () => {
  const { api } = setup();
  const movedFrom = { move_id: "mv_1", host: "ana-mbp", folder: "/Users/ana/code/acme", at: "2026-11-10T10:30:00+00:00" };
  const row = { object: "agent", id: "ag_1", name: "coder", model: "sonnet", harness: "claude_code", instructions: "",
                tools: [], user_id: null, workflow_id: "wf_1", created_at: "2026-11-10T10:00:00Z" };
  api.on("GET", "/v1/agents/ag_1", json({ ...row, moved_from: movedFrom }));
  api.on("GET", "/v1/agents/ag_2", json({ ...row, id: "ag_2", moved_from: null }));
  const agent = nc.Agent.fromId("ag_1");
  await agent.refresh();
  assert.deepEqual(agent.movedFrom, { moveId: "mv_1", host: "ana-mbp", folder: "/Users/ana/code/acme", at: new Date("2026-11-10T10:30:00+00:00") });
  const other = nc.Agent.fromId("ag_2");
  await other.refresh();
  assert.equal(other.movedFrom, null);
});
