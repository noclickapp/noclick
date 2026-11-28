/**
 * Both CLIs, the same command lines, one fake API: `npx noclick` (this package's CLI) and `noclick` from the Python
 * package must print the same stdout and stderr and exit the same. Each runs as its own process, as a person runs it.
 * The Python CLI runs from `../python` with `PYTHON` (default `python3`), which needs the Python package's
 * dependencies (`pip install -e "sdk/python[cli]"`, as `scripts/check.sh` does).
 *
 * `KNOWN` lists the differences there still are, each with why; a command not in it must match exactly.
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { type IncomingMessage, type ServerResponse, createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const TS_BIN = resolve(HERE, "../src/cli/bin.ts");
const PYTHON_ROOT = resolve(HERE, "../../python");

const AT = "2026-11-20T09:15:00Z";
const list = (...data: unknown[]) => ({ object: "list", data, next_cursor: null, has_more: false });
const agent = (id: string, name: string, user: string | null = null) =>
  ({ object: "agent", id, name, model: "openrouter/openai/gpt-5.4", user_id: user, status: "active", created_at: AT });
const user = (id: string, name: string) =>
  ({ object: "user", id, name, email: `${id}@example.com`, phone: null, status: "active", spend_cap_usd_per_month: null, metadata: {}, created_at: AT });
const bucket = { object: "bucket", id: "bk_1", name: "uploads", public: false, size_bytes: 2048000, object_count: 2, created_at: AT };
const op = (fields: Record<string, unknown>) => ({
  object: "operation", id: "op_1", kind: "agent.message", status: "succeeded", result: { text: "Done." }, error: null,
  created_at: AT, updated_at: AT, ...fields,
});
const kinds = {
  object: "list", data: [{
    kind: "database", label: "A database", description: "SQLite", options: { engine: "sqlite" },
    usage: [{ name: "gb", unit: "GB", description: "Stored", default: 1, most: null }],
    prices: [{ charge: "storage", description: "Stored", unit: "GB-month", unit_usd: 0.75, usage_fields: ["gb"] }],
    not_included: [],
  }],
};
const priced = {
  object: "estimate", monthly_usd: 0.75, estimated: true, plan: null, included_usd_per_month: null,
  items: [{ kind: "database", label: "A database", name: null, options: { engine: "sqlite" }, usage: { gb: 1 },
            assumed: ["gb"], monthly_usd: 0.75, not_included: ["Backups"], idle_usd_per_month: null, note: null,
            lines: [{ charge: "storage", description: "Stored", unit: "GB-month", unit_usd: 0.75, quantity: 1, usd: 0.75, assumed: true }] }],
};
const project = { object: "project", id: "p1", name: "booking", url: "https://booking.noclick.site", repo_id: "r1", runtime: "edge", production_branch: "main", production: null, user_id: null, budget_usd_per_month: 10, domain_names: [], created_at: AT };
const doc = { id: "guide:apps", kind: "guide", title: "Apps", summary: "Apps", url: "https://noclick.com/docs/guide/apps", status: "built", text: "Ship an app.", sections: [] };

/** The fake API: each `METHOD path` and what it answers. */
const ROUTES: Record<string, [number, unknown]> = {
  "GET /v1/agents": [200, list(agent("ag_1", "support"), agent("ag_2", "concierge", "user_42"))],
  "GET /v1/users": [200, list(user("user_42", "Ana"))],
  "POST /v1/users": [201, user("user_43", "Ravi")],
  "GET /v1/buckets": [200, list(bucket)],
  "GET /v1/buckets/bk_1/objects": [200, list(
    { key: "notes/", size: null, is_folder: true, updated_at: null },
    { key: "logo.png", size: 2048, content_type: "image/png", etag: "e", metadata: {}, updated_at: AT })],
  "GET /v1/docs": [200, list({ id: "guide:apps", kind: "guide", title: "Apps", url: null, snippet: "Ship an app.", status: "built" })],
  "GET /v1/docs/apps": [200, doc],
  "GET /v1/docs/nope": [404, { error: { type: "not_found", message: "No doc nope." } }],
  "GET /v1/estimates/kinds": [200, kinds],
  "POST /v1/estimates": [200, priced],
  "GET /v1/operations/op_1": [200, op({})],
  "GET /v1/operations/op_1/wait": [200, op({})],
  "GET /v1/projects": [200, list(project)],
  "GET /v1/projects/p1": [200, project],
  "GET /v1/projects/p1/deployments": [200, list(
    { object: "deployment", id: "dep_2", project_id: "p1", branch: "main", status: "ready", production: true, commit: "3f2a1c9e0b", commit_message: "Bigger buttons", created_at: AT, url: "https://booking.noclick.site" },
    { object: "deployment", id: "dep_1", project_id: "p1", branch: "main", status: "failed", production: false, commit: "9c1d2e0aa1", commit_message: "First", created_at: AT, url: null })],
  "GET /v1/projects/p1/secrets": [200, list({ object: "secret", name: "STRIPE_KEY", updated_at: AT, environment: "all" })],
  "GET /v1/projects/p1/settings": [200, list({ name: "SITE_NAME", value: "Ana's" })],
  "GET /v1/databases": [200, list({ object: "database", id: "db_1", name: "notes", engine: "sqlite", status: "ready", size_bytes: 4096, table_count: 1, created_at: AT })],
  "GET /v1/databases/db_1": [200, { object: "database", id: "db_1", name: "notes", engine: "sqlite", status: "ready", size_bytes: 4096, table_count: 1, created_at: AT }],
  "GET /v1/databases/db_1/schema": [200, list({ name: "notes", row_count: 1, columns: [{ name: "id", type: "integer", nullable: false, primary_key: true, default: null }] })],
  "POST /v1/agents/ag_1/messages": [202, op({ id: "op_3", status: "running", result: null })],
  "GET /v1/operations/op_3/wait": [200, op({ id: "op_3", result: { text: "Hello!", conversation: "c1", tool_calls: [{ tool: "web_search" }] } })],
  "GET /v1/operations/op_3": [200, op({ id: "op_3", result: { text: "Hello!", conversation: "c1", tool_calls: [{ tool: "web_search" }] } })],
  "POST /v1/databases/db_1/query": [200, { columns: ["id", "title"], rows: [{ id: 1, title: "Buy flour" }], rows_read: 1, rows_written: 0, duration_ms: 3 }],
  "GET /v1/domains/search": [200, list({ object: "domain_offer", name: "acme.dev", available: true, price_usd: 12.5, renewal_usd: 14, premium: false })],
  "GET /v1/operations/op_2": [200, op({ id: "op_2", status: "awaiting_human", result: null, question: { text: "Approve the purchase", url: "https://noclick.test/h/1" } })],
};

let base = "";
const server = createServer((req: IncomingMessage, res: ServerResponse) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  let path = url.pathname;
  if (path.startsWith("/v1/buckets/uploads")) path = path.replace("/v1/buckets/uploads", "/v1/buckets/bk_1");
  let [status, body] = ROUTES[`${req.method} ${path}`] ?? [404, { error: { type: "not_found", message: `No ${req.method} ${path} here.` } }];
  const name = url.searchParams.get("name");
  if (name && Array.isArray((body as { data?: unknown[] }).data)) { // a list's `name` filter, as the API applies it
    body = { ...(body as object), data: (body as { data: { name?: string }[] }).data.filter((row) => row.name === name) };
  }
  req.resume();
  req.on("end", () => {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  });
});

before(async () => {
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());

interface Ran { stdout: string; stderr: string; code: number }

function run(command: string[], argv: string[], stdin: string, cwd: string, env: Record<string, string>): Promise<Ran> {
  return new Promise((done, fail) => {
    const child = spawn(command[0]!, [...command.slice(1), ...argv], { cwd, env, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (b) => (stdout += b));
    child.stderr.on("data", (b) => (stderr += b));
    child.on("error", fail);
    child.on("close", (code) => done({ stdout, stderr, code: code ?? -1 }));
    child.stdin.end(stdin);
  });
}

async function both(argv: string[], stdin = ""): Promise<{ py: Ran; ts: Ran }> {
  const home = mkdtempSync(join(tmpdir(), "noclick-parity-"));
  const env: Record<string, string> = {
    PATH: process.env.PATH ?? "", HOME: home, TZ: "UTC", LANG: "C.UTF-8", NO_COLOR: "1",
    NOCLICK_API_KEY: "nk_live_parity", NOCLICK_API_URL: base, NOCLICK_CONFIG_DIR: join(home, "config"),
    PYTHONPATH: PYTHON_ROOT,
  };
  const python = process.env.PYTHON ?? "python3";
  const [py, ts] = await Promise.all([
    run([python, "-m", "noclick.cli"], argv, stdin, home, env),
    run([process.execPath, "--experimental-strip-types", "--disable-warning=ExperimentalWarning", TS_BIN], argv, stdin, home, env),
  ]);
  if (py.stderr.includes("ModuleNotFoundError")) {
    throw new Error(`The Python CLI didn't start with ${python} (set PYTHON to one with the noclick package's dependencies):\n${py.stderr}`);
  }
  return { py, ts };
}

/** Command lines across every group, each with what's piped in. */
const COMMANDS: [string[], string?][] = [
  [["agents", "list"]], [["agents", "list", "--json"]], [["agents", "list", "--limit", "1"]],
  [["users", "list"]], [["users", "create", "user_43", "--name", "Ravi"]],
  [["bucket", "ls"]], [["bucket", "ls", "uploads"]], [["bucket", "cp", "a.txt", "b.txt"]],
  [["docs"]], [["docs", "apps"]], [["docs", "nope"]], [["skill", "--json"]],
  [["mcp"]], [["mcp", "claude"]], [["mcp", "codex", "--oauth"]],
  [["estimate"]], [["estimate", "database"]], [["estimate", "--kinds"]], [["estimate", "database", "--usage", "gb=x"]],
  [["wait", "op_1"]], [["wait", "op_2"]],
  [["agents", "move", "status"]],
  [["agents", "chat", "nobody", "-m", "hi"]],
  [["db", "shell", "notes"], ".help\n"], [["db", "shell", "notes"], ".tables\nselect id, title from notes;\n"],
  [["machines", "ssh", "box"]], [["agents", "chat", "support"], "hi\n"],
  [["deplyo"]], [["projects", "list"]],
  [["releases", "--app", "booking"]], [["secret", "ls", "--app", "booking"]], [["env", "ls", "--app", "booking"]],
  [["db", "query", "notes", "select id, title from notes"]], [["domains", "search", "acme"]], [["ls", "--kind", "apps"]],
  // --json
  [["users", "list", "--json"]], [["bucket", "ls", "--json"]], [["docs", "--json"]], [["estimate", "database", "--json"]],
  [["wait", "op_1", "--json"]], [["db", "query", "notes", "select 1", "--json"]], [["domains", "search", "acme", "--json"]],
  [["releases", "--app", "booking", "--json"]], [["secret", "ls", "--app", "booking", "--json"]], [["ls", "--json", "--kind", "apps"]],
];

/** Differences there still are, by command line, and why. */
const KNOWN: Record<string, string> = {
  "agents move status": "a next step's command ending in \"...\": Python's run: line drops every trailing dot, npm's one (run: lines are pulled from prose in both; that's being reworked)",
};

test("both CLIs answer the same command lines the same way", async () => {
  const differ: string[] = [];
  for (const [argv, stdin] of COMMANDS) {
    const said = argv.join(" ");
    const { py, ts } = await both(argv, stdin ?? "");
    const same = py.stdout === ts.stdout && py.stderr === ts.stderr && py.code === ts.code;
    if (same) {
      assert.ok(!(said in KNOWN), `${said} matches now: take it out of KNOWN`);
      continue;
    }
    if (said in KNOWN) continue;
    differ.push([`$ noclick ${said}`, `python (exit ${py.code}):`, py.stdout + py.stderr, `npm (exit ${ts.code}):`, ts.stdout + ts.stderr].join("\n"));
  }
  assert.equal(differ.length, 0, `\n${differ.join("\n\n")}`);
});

