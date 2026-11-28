import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import type { NoClickError } from "../src/errors.ts";

import { WAIT_WINDOW_S, commandsFor } from "../src/cli/commands.ts";
import { TIMED_OUT, exitCode } from "../src/cli/exits.ts";
import * as link from "../src/cli/link.ts";
import { main } from "../src/cli/main.ts";
import { FAILED, OK, REFUSED, USAGE, WAITING } from "../src/cli/output.ts";
import * as spend from "../src/cli/spend.ts";
import type { Io } from "../src/cli/output.ts";
import { load } from "../src/cli/spec.ts";
import { apiError, json, operation, setup } from "./helpers.ts";

WAIT_WINDOW_S.value = 1;

function captured(): Io & { stdout: string[]; stderr: string[] } {
  const stdout: string[] = [];
  const stderr: string[] = [];
  return { stdout, stderr, out: (line) => stdout.push(line), err: (line) => stderr.push(line) };
}

const signedIn = { signIn: () => {} };

test("every operation the spec has is a command of its own, but where a curated one has its name", () => {
  const spec = load();
  for (const op of spec.operations) {
    if (spec.shadowed(op)) continue;
    assert.equal(spec.find(op.area, op.command), op);
  }
  assert.ok(spec.curated(["deploy"]) && spec.curated(["api"]) && spec.curated(["help"]));
});

test("a generated command makes its call through the SDK, its useful value last", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/agents/support%20bot/messages", json({ id: "msg_1", url: "https://noclick.test/m/1" }));
  const io = captured();
  const code = await main(["agents", "messages-create", "support bot", "--text", "hi", "--attachments", "a1",
    "--attachments", "a2", "--data", '{"conversation": "c1", "text": "replaced"}'], io, signedIn);
  assert.equal(code, OK);
  assert.deepEqual(route.calls[0]!.body, { text: "hi", attachments: ["a1", "a2"], conversation: "c1" });
  assert.equal(io.stdout.at(-1), "https://noclick.test/m/1");
});

test("a required field left out is a usage error naming it, before any call", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/agents", json({}));
  const io = captured();
  assert.equal(await main(["agents", "create", "--name", "x", "--json"], io, signedIn), USAGE);
  const { error } = JSON.parse(io.stdout.join("\n"));
  assert.match(error.message, /--instructions/);
  assert.equal(error.next_step, "noclick describe agents create");
  assert.equal(route.calls.length, 0);
});

test("an operation it starts is waited on, and one waiting on a person exits 3", async () => {
  const { api } = setup();
  api.on("POST", "/v1/agents/a1/messages", json(operation({ id: "op_9", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_9/wait",
    json(operation({ id: "op_9", status: "awaiting_human", result: { url: "https://noclick.test/h/1" } })));
  const io = captured();
  assert.equal(await main(["agents", "messages-create", "a1", "--text", "hi"], io, signedIn), WAITING);
  assert.equal(io.stdout.at(-1), "https://noclick.test/h/1");
});

test("an API refusal exits by what it is and names the command its next step makes", async () => {
  for (const [status, type, code] of [[402, "approval_required", WAITING], [402, "spend_cap_exceeded", REFUSED],
    [400, "invalid_request", USAGE], [404, "not_found", FAILED]] as const) {
    const { api } = setup();
    api.on("GET", "/v1/agents/a1", apiError(status, type, "No.", { next_step: "List agents with GET /v1/agents." }));
    const io = captured();
    assert.equal(await main(["agents", "get", "a1", "--json"], io, signedIn), code, type);
    const { error } = JSON.parse(io.stdout.join("\n"));
    assert.deepEqual(error.commands, ["noclick agents list"]);
  }
});

test("api calls any route, describe and help need no key", async () => {
  const { api } = setup();
  const route = api.on("PATCH", "/v1/agents/a1", json({ id: "a1", name: "b" }));
  let io = captured();
  assert.equal(await main(["api", "patch", "/v1/agents/a1", "--data", '{"name": "b"}', "-q", "user_id=u1", "--json"], io, signedIn), OK);
  assert.deepEqual(route.calls[0]!.body, { name: "b" });
  assert.equal(route.calls[0]!.query.get("user_id"), "u1");

  io = captured();
  assert.equal(await main(["describe", "POST", "/v1/agents/a1/messages", "--json"], io), OK);
  assert.equal(JSON.parse(io.stdout.join("\n")).example, "noclick agents messages-create <agent_id>");
  io = captured();
  assert.equal(await main(["help", "--json"], io), OK);
  const listed = JSON.parse(io.stdout.join("\n"));
  assert.equal(listed.operations.length, load().operations.length);
  assert.equal(listed.conventions.exit_codes["3"], "waiting on a person");
});

test("a next step naming a route, an operation or a command is the command that makes it", () => {
  const commands = commandsFor(load());
  assert.deepEqual(commands.runnable("Read it again: GET /v1/workflows/{id}/approvals/{approval_id}."),
    ["noclick workflows approvals-get <workflow_id> <approval_id>"]);
  assert.deepEqual(commands.runnable("Run noclick login, or set NOCLICK_API_KEY."), ["noclick login"]);
});

test("a curated command npx noclick doesn't run yet says how to run it", async () => {
  const io = captured();
  assert.equal(await main(["db", "shell", "notes"], io, signedIn), USAGE);
  assert.ok(io.stderr.includes("  next step: pip install noclick, then noclick db shell"));
});

test("a wait that runs out exits 124 and names the command that picks it up", async () => {
  const { api } = setup();
  api.on("POST", "/v1/agents/a1/messages", json(operation({ id: "op_7", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_7/wait", json(operation({ id: "op_7", status: "running" })));
  const io = captured();
  assert.equal(await main(["agents", "messages-create", "a1", "--text", "hi", "--timeout", "0.5", "--json"], io, signedIn), TIMED_OUT);
  assert.deepEqual(JSON.parse(io.stdout.join("\n")).error.commands, ["noclick ops wait op_7"]);
});

test("a folder is linked once and read from anywhere inside it, never with a key", () => {
  const root = mkdtempSync(join(tmpdir(), "nc-link-"));
  assert.throws(() => link.appName(null, root), (err: Error) => err instanceof link.NotLinked);
  link.write("booking", { appId: "prj_1", root });
  assert.equal(readFileSync(join(root, ".noclick", ".gitignore"), "utf8"), "*\n");
  const inside = join(root, "src", "pages");
  mkdirSync(inside, { recursive: true });
  assert.deepEqual(link.find(inside), { app: "booking", appId: "prj_1", apiUrl: null, path: join(root, ".noclick", "project.json") });
  assert.equal(link.appName(null, inside), "booking");
  assert.equal(link.remove(inside)?.app, "booking");
  assert.equal(existsSync(join(root, ".noclick")), false);
});

test("--max-usd prices first and refuses above the ceiling, exit 4", async () => {
  const { api } = setup();
  api.on("POST", "/v1/estimates", json({ object: "estimate", monthly_usd: 0.42, lines: [], items: [] }));
  const io = captured();
  const items = [{ kind: "live_editing", usage: { hours: 2 } }] as never;
  assert.equal((await spend.check(io, items, 1, { what: "This session", per: "at most" })).monthlyUsd, 0.42);
  assert.ok(io.stderr.includes("This session costs about $0.42 at most (under --max-usd $1.00)."));
  await assert.rejects(spend.check(io, items, 0.1, { what: "This session", per: "at most" }),
    (err: NoClickError) => exitCode(err.type) === REFUSED && /nothing was done/.test(err.message));
});

test("agents send uploads each --file and sends it with the message, then prints the reply", async () => {
  const { api } = setup();
  const path = join(mkdtempSync(join(tmpdir(), "nc-send-")), "q3.csv");
  writeFileSync(path, "month,total\nJuly,10\n");
  api.on("GET", "/v1/agents", json({ object: "list", data: [{ object: "agent", id: "ag_1", name: "support", status: "active", user_id: null }], next_cursor: null }));
  const upload = api.on("POST", "/v1/agents/ag_1/attachments", json({ object: "agent_attachment", id: "att_1", name: "q3.csv", mime_type: "text/csv", size_bytes: 21, url: "https://files.test/q3.csv" }, { status: 201 }));
  const send = api.on("POST", "/v1/agents/ag_1/messages", json(operation({ id: "op_1", kind: "agent.message", status: "succeeded", result: { text: "July was slow.", conversation: "desk", tool_calls: [] } }), { status: 202 }));
  const io = captured();
  assert.equal(await main(["agents", "send", "support", "What stands out?", "--file", path, "--conversation", "desk"], io, signedIn), OK);
  assert.equal(upload.last.query.get("name"), "q3.csv");
  assert.deepEqual(send.last.body, { text: "What stands out?", conversation: "desk", attachments: ["att_1"] });
  assert.deepEqual(io.stdout, ["July was slow."]);
});

test("noclick alone says what to run first, and signed in, who you are and the folder's app", async () => {
  const { host } = await import("../src/cli/host.ts");
  const saved = { env: host.env, cwd: host.cwd };
  const folder = mkdtempSync(join(tmpdir(), "noclick-first-"));
  try {
    host.env = { NOCLICK_CONFIG_DIR: join(folder, "config") };
    host.cwd = () => folder;
    let io = captured();
    assert.equal(await main([], io), OK);
    const out = io.stdout.join("\n");
    assert.ok(out.includes("noclick login") && out.includes("noclick deploy") && out.includes("noclick docs cli"));
    assert.ok(out.split("\n").length <= 20 && out.includes("No account? noclick signup --accept-terms"));
    mkdirSync(join(folder, "config"));
    writeFileSync(join(folder, "config", "config.json"), JSON.stringify({ profiles: { default: { store: "file", email: "ana@acme.test" } } }));
    link.write("booking", { root: folder });
    io = captured();
    assert.equal(await main([], io), OK);
    assert.ok(io.stdout.join("\n").includes("Signed in as ana@acme.test; this folder is linked to booking."));
    assert.ok(!io.stdout.join("\n").includes("noclick login") && !io.stdout.join("\n").includes("noclick signup"));
  } finally {
    Object.assign(host, saved);
  }
});

test("--help lists the commands by section and the API as one line; --all lists every area", async () => {
  let io = captured();
  assert.equal(await main(["--help"], io), OK);
  const lines = io.stdout.join("\n").split("\n");
  const sections = lines.filter((l) => l.endsWith(":") && !l.startsWith(" ")).map((l) => l.slice(0, -1));
  assert.deepEqual(sections.slice(0, 6), ["Start", "Ship", "Configure", "Operate", "Everything else", "Teach"]);
  assert.ok(lines.some((l) => l.includes("<area> <operation>")) && !lines.some((l) => l.includes("agent-conversations")));
  io = captured();
  assert.equal(await main(["--help", "--all"], io), OK);
  assert.ok(io.stdout.join("\n").includes("agent-conversations"));
});

test("a mistyped command names the closest ones, as the Python CLI does, and exits 2", async () => {
  for (const [argv, said] of [[["deplyo"], "Unknown command 'deplyo'. Did you mean: deploy?"],
    [["secret", "sett"], "Unknown command 'secret sett'. Did you mean: secret set?"],
    [["agents", "creat"], "Did you mean: agents create, agents chat?"]] as const) {
    const io = captured();
    assert.equal(await main([...argv], io), USAGE);
    assert.equal(io.stderr.length, 1);
    assert.ok(io.stderr[0]!.includes(said) && io.stderr[0]!.includes("--help"), io.stderr[0]);
  }
});

test("a command's help ends with its examples", async () => {
  const io = captured();
  assert.equal(await main(["deploy", "--help"], io), OK);
  const examples = load().curated(["deploy"])!.examples!;
  assert.ok(io.stdout.join("\n").endsWith(["examples:", ...examples.map((e) => `  ${e}`)].join("\n")));
});

test("at a terminal it is styled; piped, or told not to, it prints plain text", async () => {
  const style = await import("../src/cli/style.ts");
  const terminal = (io: ReturnType<typeof captured>) => Object.assign(io, { terminal: () => ({ out: true, err: true, columns: 100 }) });
  const { api } = setup();
  api.on("GET", "/v1/agents/a1", apiError(404, "not_found", "No agent a1.", { next_step: "List agents with GET /v1/agents." }));
  const commands = [["--help"], ["deploy", "--help"], ["agents", "get", "a1"], []];
  const { host } = await import("../src/cli/host.ts");
  const env = host.env;
  host.env = {}; // a terminal of its own: not the CI this runs in
  const shown = async (make: () => ReturnType<typeof captured>, flags: string[] = []) => {
    const printed: string[] = [];
    for (const argv of commands) {
      const io = make();
      await main([...flags, ...argv], io, signedIn);
      printed.push([...io.stdout, ...io.stderr].join("\n"));
    }
    return printed;
  };
  try {
    const piped = await shown(captured);
    assert.ok(piped.every((text) => !text.includes("\x1b[")));
    const styled = await shown(() => terminal(captured()));
    assert.ok(styled.every((text) => text.includes("\x1b[")));
    assert.deepEqual(await shown(() => terminal(captured()), ["--color", "never"]), piped);
    assert.ok(style.visible(styled[2]!).startsWith("error: No agent a1."));
    const screen = ["booking  https://booking.noclick.site", "  live        ready 3f2a1c9 on main"];
    const fields = new style.Style(true).fields(screen);
    assert.deepEqual(fields.map(style.visible), screen);
    assert.ok(fields[1]!.includes("\x1b["));
    assert.equal(style.wanted("auto", true, { NO_COLOR: "1" }), false);
    assert.equal(style.wanted("auto", true, { CI: "true" }), false);
    assert.equal(style.wanted("always", false, { NO_COLOR: "1" }), true);
  } finally {
    host.env = env;
    style.configure("never", { out: false, err: false }, {}, () => 100);
  }
});

for (const columns of [80, 120]) {
  test(`a table fits ${columns} columns, cutting prose before ids`, async () => {
    const { Style, visible } = await import("../src/cli/style.ts");
    const id = `dep_${"8f2a1c9d3e4b5a6f7e8d9c0b1a2f3e4d"}`;
    const lines = new Style(true, { columns: () => columns }).table(["ID", "STATUS", "MESSAGE"],
      [[id, "ready", "Bigger buttons on the booking page ".repeat(4)]], "Releases of booking");
    assert.ok(lines.every((line) => visible(line).length <= columns));
    const body = visible(lines[4]!);
    assert.ok(body.includes(id) && body.replace(/[│ ]+$/, "").endsWith("…"));
    assert.equal(visible(lines[0]!).trim(), "Releases of booking");
  });
}

/** Words as a shell splits them, quotes kept together. */
const words = (line: string) => [...line.matchAll(/'([^']*)'|(\S+)/g)].map((m) => m[1] ?? m[2]!);

test("every area's list and get parse and make their call, with a global flag in front or none", async () => {
  const { configure } = await import("../src/client.ts");
  const { example } = await import("../src/cli/commands.ts");
  const spec = load();
  const calls: string[] = [];
  configure({ apiKey: "nk_live_test", baseUrl: "https://api.noclick.test", maxRetries: 0, fetch: async (input, init) => {
    calls.push(`${init?.method ?? "GET"} ${new URL(String(input)).pathname}`);
    return json({ object: "list", data: [], next_cursor: null });
  } });
  const ops = spec.operations.filter((op) => (op.command === "list" || op.command === "get") && !spec.shadowed(op));
  assert.ok(["projects", "machines", "databases", "buckets", "domains", "repos"].every((a) => ops.some((op) => op.area === a)));
  for (const flags of [[], ["--color", "never"]]) {
    for (const op of ops) {
      const line = example(op, spec);
      const io = captured();
      const before = calls.length;
      assert.equal(await main([...flags, ...words(line).slice(1)], io, signedIn), OK, `${line}: ${io.stderr.join(" ")}`);
      assert.equal(calls.length, before + 1, line);
      assert.ok(calls.at(-1)!.startsWith(op.method), line);
    }
  }
});

test("a command given as one argument says to pass its words apart; a group alone lists its commands", async () => {
  let io = captured();
  assert.equal(await main(["projects list"], io), USAGE);
  assert.ok(io.stderr.join("\n").includes("pass its words apart"));
  for (const [group, shows] of [["projects", "noclick projects list"], ["agents", "noclick agents list"], ["agents move", "noclick agents move redeem"]] as const) {
    io = captured();
    assert.equal(await main(group.split(" "), io), OK);
    assert.ok(io.stdout.some((l) => l.startsWith(shows)), group);
  }
});

test("ls runs list where a group has no ls of its own, and noclick ls lists what the account has", async () => {
  const { api } = setup();
  const projects = api.on("GET", "/v1/projects", json({ object: "list", next_cursor: null, data: [
    { object: "project", id: "p1", name: "booking", url: "https://booking.noclick.site", production: { status: "ready" } }] }));
  assert.equal(await main(["--color", "never", "projects", "ls"], captured(), signedIn), OK);
  assert.equal(projects.count, 1);
  api.on("GET", "/v1/machines", json({ object: "list", next_cursor: null, data: [
    { object: "machine", id: "m1", name: "build-box", status: "running", size: "small", region: "us", monthly_usd: 12.5 }] }));
  for (const path of ["/v1/databases", "/v1/buckets", "/v1/repos", "/v1/domains", "/v1/phone_numbers", "/v1/inboxes", "/v1/volumes"]) {
    api.on("GET", path, json({ object: "list", data: [], next_cursor: null }));
  }
  const sandboxes = api.on("GET", "/v1/sandboxes", json({ object: "list", data: [], next_cursor: null }));
  const spend = api.on("GET", "/v1/usage", json({ total_usd: 1.84, groups: [{ id: "p1", usd: 1.84 }] }));
  let io = captured();
  assert.equal(await main(["ls"], io, signedIn), OK);
  const out = io.stdout.join("\n");
  assert.ok(out.includes("Websites (1)") && out.includes("Machines (1)") && !out.includes("Databases"));
  assert.ok(out.includes("https://booking.noclick.site") && out.includes("$1.84") && out.includes("$12.50"));
  assert.equal(sandboxes.last.query.get("status"), "live");
  assert.equal(projects.last.query.get("user_id"), "all");
  assert.equal(spend.last.query.get("group_by"), "project");
  io = captured();
  assert.equal(await main(["resources", "--kind", "machines", "--json"], io, signedIn), OK);
  const body = JSON.parse(io.stdout.join("\n"));
  assert.deepEqual(Object.keys(body.kinds), ["machines"]);
  api.on("GET", "/v1/machines", apiError(403, "permission_denied", "No machines here."));
  io = captured();
  assert.equal(await main(["resources", "--kind", "machines", "--kind", "apps"], io, signedIn), OK);
  assert.ok(io.stdout.join("\n").includes("Websites (1)") && io.stderr.includes("machines: unread (No machines here.)"));
  assert.equal(await main(["resources", "--kind", "machines"], captured(), signedIn), FAILED);
});
