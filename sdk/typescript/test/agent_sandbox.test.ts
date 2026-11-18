// An agent's sandbox: `agent.sandbox()` reads what it is and costs (`get`), its files a folder at a
// time (`files`, `filesPage`, `read`) and runs a command beside the agent's work (`exec`); `Agent.coding()` reads every
// coding agent and what each is doing.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, listing, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "coder", model: "claude-sonnet-4-5", harness: "claude_code", instructions: "hi",
  tools: [], user_id: null, created_at: "2026-10-29T10:00:00Z",
};
const SANDBOX = {
  object: "agent_sandbox", agent_id: "ag_1", conversation: "main thread", harness: "claude_code", place: "sandbox",
  status: "running", started_at: "2026-11-09T10:00:00Z", cpu: 1.0, memory_mb: 4096, region: null,
  usd_per_hour: 0.162, spent_usd_today: 0.012, machine_id: null, project_id: null, workspace: "/workspace",
};
const ENTRY = { object: "sandbox_entry", path: "/workspace/src", type: "directory", size: null, updated_at: null };
const PATH = "/v1/agents/ag_1/conversations/main%20thread/sandbox";

test("what a conversation's sandbox is and costs", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const read = api.on("GET", PATH, json(SANDBOX));
  const machine = nc.Agent.fromId("ag_1").sandbox("main thread");
  assert.equal(read.count, 0);  // nothing sent yet
  const now = await machine.get();
  assert.deepEqual(
    [now.place, now.status, now.cpu, now.memoryMb, now.usdPerHour, now.spentUsdToday, now.workspace, now.machineId],
    ["sandbox", "running", 1, 4096, 0.162, 0.012, "/workspace", null]);
  assert.equal(now.startedAt?.toISOString(), "2026-11-09T10:00:00.000Z");
  assert.equal(machine.conversation, "main thread");
});

test("without a conversation it's read through the agent's session, and none yet is NotFound", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const sessions = api.on("GET", "/v1/agents/ag_1/conversations",
    json(listing([{ object: "conversation", conversation: "c9", active: true }])),
    json(listing([{ object: "conversation", conversation: "c1", active: false }])));
  const read = api.on("GET", "/v1/agents/ag_1/conversations/c9/sandbox", json({ ...SANDBOX, conversation: "c9" }));
  assert.equal((await nc.Agent.fromId("ag_1").sandbox().get()).status, "running");
  assert.equal(read.count, 1);
  await assert.rejects(nc.Agent.fromId("ag_1").sandbox().get(), nc.NotFound);
  assert.equal(sessions.count, 2);
});

test("its files a folder at a time, and one file's bytes", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const files = api.on("GET", `${PATH}/files`,
    json({ ...listing([ENTRY], "/workspace/src"), source: "sandbox" }),
    json({ ...listing([{ ...ENTRY, path: "/workspace/src/app.py", type: "file", size: 11 }]), source: "sandbox" }));
  const machine = nc.Agent.fromId("ag_1").sandbox("main thread");
  const all = await machine.files("/workspace", { recursive: true });
  assert.deepEqual(all.map((e) => [e.path, e.type, e.size]), [["/workspace/src", "directory", null],
                                                             ["/workspace/src/app.py", "file", 11]]);
  assert.deepEqual([files.calls[0].query.get("view"), files.calls[0].query.get("recursive"),
                    files.calls[1].query.get("cursor")], ["list", "true", "/workspace/src"]);

  api.on("GET", `${PATH}/files`, json({ ...listing([ENTRY], "/workspace/src"), source: "workspace" }));
  const page = await machine.filesPage();
  assert.deepEqual([page.source, page.nextCursor, page.data[0].path], ["workspace", "/workspace/src", "/workspace/src"]);

  const bytes = api.on("GET", `${PATH}/files`, () => new Response(new TextEncoder().encode("TOKEN=[redacted]")));
  assert.equal(new TextDecoder().decode(await machine.read("/workspace/.env")), "TOKEN=[redacted]");
  assert.deepEqual([bytes.last.query.get("path"), bytes.last.query.get("view")], ["/workspace/.env", null]);
});

test("a command beside the agent's work, as the user whose thread it is", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const ran = api.on("POST", `${PATH}/exec`, json({
    object: "sandbox_exec", agent_id: "ag_1", conversation: "main thread", exit_code: 1, stdout: "M src/app.py\n",
    stderr: "", timed_out: false, stdout_truncated: false, stderr_truncated: false,
  }));
  const result = await nc.Agent.fromId("ag_1").sandbox("main thread", { user: USER_ID }).exec("git status --short",
                                                                                             { timeoutS: 30 });
  assert.deepEqual(ran.last.body, { command: "git status --short", timeout_s: 30 });
  assert.equal(ran.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual([result.exitCode, result.ok, result.stdout], [1, false, "M src/app.py\n"]);
});

test("every coding agent and what it's doing", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/agents/coding", json({
    object: "list", read_at: "2026-11-09T10:05:00Z", unread: ["sandboxes"],
    data: [{
      object: "coding_agent", agent_id: "ag_1", name: "coder", user_id: null,
      app: { project_id: "prj_1", name: "bakery", title: "Morrow Bakehouse", coder: true },
      harness: "codex", model: "gpt-6-luna",
      credential: { kind: "plan", connection: "chatgpt", credential_type: "agent_codex_oauth", connected: true },
      place: "sandbox", state: "working", paused: null, pauses: [],
      job: { operation_id: "op_1", conversation: "code", status: "running", step: "working",
             since: "2026-11-09T10:00:00Z", title: "Fix the menu", text: "Fix the menu page" },
      runs: [{ conversation: "code", place: "sandbox", since: "2026-11-09T09:59:00Z", busy: true, cpu: 1.0,
               memory_mb: 4096 }],
      spent_usd_this_month: 1.25,
      model_usage_this_month: { input_tokens: 10, output_tokens: 5, cached_tokens: 2, usd: 0.4 },
    }],
    counts: [{ harness: "codex", model: "gpt-6-luna", state: "working", place: "sandbox", count: 1 }],
    by_state: { working: 1, waiting: 0, warm: 0, paused: 0, stopped: 0 }, paused_by_reason: {},
  }));
  const coding = await nc.Agent.coding();
  const [agent] = coding.agents;
  assert.deepEqual([agent.name, agent.state, agent.app?.title, agent.credential.kind, agent.job?.title, agent.job?.lost],
    ["coder", "working", "Morrow Bakehouse", "plan", "Fix the menu", false]);
  assert.deepEqual([agent.runs[0].busy, agent.runs[0].cpu, agent.runs[0].memoryMb, agent.runs[0].daemon],
    [true, 1, 4096, null]);
  assert.deepEqual([agent.spentUsdThisMonth, agent.modelUsageThisMonth.usd], [1.25, 0.4]);
  assert.deepEqual([coding.counts[0].count, coding.byState.working, coding.unread], [1, 1, ["sandboxes"]]);
  assert.equal(coding.readAt?.toISOString(), "2026-11-09T10:05:00.000Z");
  assert.equal(read.last.query.get("user_id"), null);
  await nc.Agent.coding({ userFilter: nc.ALL_USERS });
  assert.equal(read.last.query.get("user_id"), "all");
});

class ShellSocket {
  static last: ShellSocket;
  readonly sent: (string | Uint8Array)[] = [];
  binaryType = "blob";
  onopen?: () => void;
  onmessage?: (event: { data: unknown }) => void;
  onclose?: (event: { code: number; reason: string }) => void;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    ShellSocket.last = this;
  }
  send(data: string | Uint8Array) {
    this.sent.push(data);
  }
  close() {}
}

test("a shell is a token the terminal's connection opens once, ending for good as bash exits", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const opened = api.on("POST", `${PATH}/shell`, json({
    object: "sandbox_shell", agent_id: "ag_1", conversation: "main thread", url: "wss://api.test/v1/terminals/attach",
    token: "tok_sh", token_expires_at: "2026-11-09T10:02:00Z", idle_limit_s: 900,
  }));
  const shell = await nc.Agent.fromId("ag_1").sandbox("main thread").shell();
  assert.equal(opened.count, 1);
  assert.deepEqual([shell.url, shell.token, shell.idleLimitS, shell.tokenExpiresAt?.toISOString()],
    ["wss://api.test/v1/terminals/attach", "tok_sh", 900, "2026-11-09T10:02:00.000Z"]);

  const seen: { data: string[]; states: string[]; closed: { code: number; final: boolean }[] } = {
    data: [], states: [], closed: [] };
  const connection = shell.connect({
    cols: 90, rows: 25, WebSocket: ShellSocket as unknown as typeof WebSocket,
    onData: (bytes) => seen.data.push(new TextDecoder().decode(bytes)),
    onState: (status) => seen.states.push(`${status.state}:${status.reason ?? ""}`),
    onClose: ({ code, final }) => seen.closed.push({ code, final }),
  });
  const socket = ShellSocket.last;
  socket.onopen?.();
  assert.deepEqual(JSON.parse(socket.sent[0] as string), { type: "auth", token: "tok_sh", cols: 90, rows: 25 });
  socket.onmessage?.({ data: JSON.stringify({ type: "ready", state: "open", shell: "s1" }) });
  connection.write("exit\r");
  assert.equal(new TextDecoder().decode(socket.sent[1] as Uint8Array), "exit\r");
  socket.onmessage?.({ data: new TextEncoder().encode("logout\r\n").buffer });
  socket.onmessage?.({ data: JSON.stringify({ type: "state", state: "exited", reason: "exited", exit_code: 0 }) });
  socket.onclose?.({ code: nc.TERMINAL_CLOSED_FOR_GOOD.ended, reason: "The shell ended." });
  assert.deepEqual([seen.data, seen.states, seen.closed], [["logout\r\n"], ["exited:exited"], [{ code: 4410, final: true }]]);
  assert.throws(() => shell.connect({ WebSocket: ShellSocket as unknown as typeof WebSocket }), /once/);
});
