/** Where you work from, through `main` as a terminal or an agent drives it: the logins this machine keeps and the one
 *  commands use, Tab completion read from the spec (answering as the Python CLI answers), the console in a browser,
 *  the changelog, and the once-a-day update notice. */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, test } from "node:test";

import { main } from "../src/cli/main.ts";
import { host } from "../src/cli/host.ts";
import * as completion from "../src/cli/completion.ts";
import * as updates from "../src/cli/updates.ts";
import { FAILED, OK, USAGE } from "../src/cli/exits.ts";
import type { Io } from "../src/cli/output.ts";
import { load } from "../src/cli/spec.ts";
import { BASE, json, listing, setup } from "./helpers.ts";

const PROJECT = { object: "project", id: "5c2e8a1f-3b7d-4e9a-a6c4-8d1f0e2b3a79", name: "booking", url: "https://booking.noclick.site" };
const PYTHON_SDK = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "python");

function captured(terminal = false): Io & { stdout: string[]; stderr: string[] } {
  const stdout: string[] = [];
  const stderr: string[] = [];
  return {
    stdout, stderr, out: (l) => stdout.push(l), err: (l) => stderr.push(l), write: (d) => stdout.push(new TextDecoder().decode(d)),
    terminal: () => ({ out: terminal, err: terminal, columns: 100 }),
  };
}

let home = "";
let config = "";
const spawned: string[][] = [];

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), "noclick-home-"));
  config = join(home, "config");
  host.env = { NOCLICK_CONFIG_DIR: config, NOCLICK_API_URL: BASE, HOME: home, PATH: process.env.PATH, NOCLICK_KEYCHAIN: "off" };
  host.cwd = () => home;
  host.detached = (args) => void spawned.push(args);
  spawned.length = 0;
  mkdirSync(config, { recursive: true });
  writeFileSync(join(config, "config.json"), JSON.stringify({ profiles: {
    default: { store: "file", api_url: BASE, email: "ana@example.com", key_name: "Ana's laptop", key_prefix: "nk_live_aaaa" },
    work: { store: "file", api_url: BASE, email: "ana@acme.test", key_name: "Acme CI", key_prefix: "nk_live_wwww" },
  } }));
  writeFileSync(join(config, "credentials.json"), JSON.stringify({ default: "nk_live_aaaa_key", work: "nk_live_wwww_key" }));
});

test("profile use makes a login the default, and whoami says which is active and why", async () => {
  const { api } = setup();
  host.fetch = api.fetch;
  let io = captured();
  assert.equal(await main(["profile", "list"], io), OK);
  assert.ok(io.stdout.includes("*  default  ana@example.com  Ana's laptop  https://api.test"));
  assert.ok(io.stderr.includes("* is active (the default). Switch: noclick profile use <name>"));

  io = captured();
  assert.equal(await main(["profile", "use", "work"], io), OK);
  assert.deepEqual(io.stdout, ["Commands now use the profile work (ana@acme.test)."]);
  const status = api.on("GET", "/v1/status", json({ account: { id: "acct_2", name: "Acme", email: "ana@acme.test" } }));
  io = captured();
  assert.equal(await main(["whoami"], io), OK);
  assert.ok(io.stdout.includes("Profile  work (set by noclick profile use)"));
  assert.equal(status.last.headers.get("authorization"), "Bearer nk_live_wwww_key");

  // --profile, then NOCLICK_PROFILE, still win over it.
  io = captured();
  assert.equal(await main(["--profile", "default", "whoami", "--json"], io), OK);
  const said = JSON.parse(io.stdout.join("\n"));
  assert.deepEqual([said.profile, said.profile_source], ["default", "flag"]);
  host.env.NOCLICK_PROFILE = "default";
  io = captured();
  assert.equal(await main(["profile", "show", "--json"], io), OK);
  assert.equal(JSON.parse(io.stdout.join("\n")).active_source, "env");
  delete host.env.NOCLICK_PROFILE;

  io = captured();
  assert.equal(await main(["profile", "use", "nope"], io), FAILED);
  assert.ok(io.stderr.some((l) => l.includes("No stored login is called nope (stored: default, work).")));
  assert.ok(io.stderr.includes("  run: noclick login --profile nope"));
});

test("logging out of the active profile leaves no default naming it", async () => {
  const { api } = setup();
  host.fetch = api.fetch;
  assert.equal(await main(["profile", "use", "work"], captured()), OK);
  api.on("DELETE", "/v1/keys/current", json({ ok: true }));
  assert.equal(await main(["logout"], captured(), { signIn: () => {} }), OK);
  const kept = JSON.parse(readFileSync(join(config, "config.json"), "utf8"));
  assert.ok(!("work" in kept.profiles) && !("default_profile" in kept));
});

const lists = { profiles: () => ["default", "work"], apps: () => ["booking", "blog"] };
const values = (words: string[]) => completion.candidates(words, lists).map(([value]) => value);

test("Tab completes commands, flags, choices, profiles and apps from the spec", () => {
  const spec = load();
  assert.ok(["deploy", "profile", "completion", ...spec.areas().keys()].every((n) => values([""]).includes(n)));
  assert.deepEqual(values(["profile", "u"]), ["use"]);
  assert.deepEqual(values(["logs", "--level", ""]), ["warn", "error"]);
  assert.deepEqual(values(["profile", "use", ""]), ["default", "work"]);
  assert.deepEqual(values(["--profile", "w"]), ["work"]);
  assert.deepEqual(values(["logs", "b"]), ["booking", "blog"]);
  assert.deepEqual(values(["deploy", "--app", "bo"]), ["booking"]);
  assert.deepEqual(values(["no-such-command", ""]), []);
  const [area, ops] = [...spec.areas()].find(([, o]) => o.some((op) => op.params.some((p) => p.in !== "path")))!;
  const op = ops.find((o) => o.params.some((p) => p.in !== "path"))!;
  assert.ok(values([area, ""]).includes(op.command));
  assert.ok(values([area, op.command, "--"]).includes("--no-wait"));
});

test("app names come from a cache read again in the background when stale", () => {
  const started: string[] = [];
  assert.deepEqual(completion.appNames("default", 1000, (p) => void started.push(p)), []);
  completion.writeApps("default", { at: 1000, names: ["booking"] });
  assert.deepEqual(completion.appNames("default", 1100, (p) => void started.push(p)), ["booking"]);
  assert.deepEqual(completion.appNames("default", 1000 + completion.APPS_FRESH_S, (p) => void started.push(p)), ["booking"]);
  assert.deepEqual(started, ["default", "default"]);
  assert.deepEqual(spawned, []);
});

test("Tab answers as the Python CLI answers, and both print the same scripts", async (t) => {
  const python = process.env.PYTHON ?? "python3";
  const env = { ...process.env, ...host.env, PYTHONPATH: PYTHON_SDK, NOCLICK_API_KEY: "" } as NodeJS.ProcessEnv;
  const pythonSays = (args: string[]) => execFileSync(python, ["-m", "noclick", ...args], { env, encoding: "utf8" });
  try {
    pythonSays(["completion", "bash"]);
  } catch {
    t.skip("no Python with the SDK's requirements (PYTHON)");
    return;
  }
  const typescriptSays = async (args: string[]) => {
    const io = captured();
    await main(args, io);
    return io.stdout.map((l) => `${l}\n`).join("");
  };
  for (const words of [[""], ["profile", ""], ["agents", ""], ["deploy", "--"], ["logs", "--level", ""], ["account", ""],
    ["workflows", "list", "--"], ["--profile", ""], ["zzz", ""]]) {
    const args = ["__complete", "--", ...words];
    assert.equal(await typescriptSays(args), pythonSays(args), words.join(" "));
  }
  for (const shell of completion.SHELLS) {
    assert.equal(await typescriptSays(["completion", shell]), pythonSays(["completion", shell]), shell);
  }
});

test("completion --install puts each shell's script in place once", async () => {
  for (const shell of completion.SHELLS) {
    let io = captured();
    assert.equal(await main(["completion", shell, "--install"], io), OK);
    const { script, rc } = completion.places(shell);
    assert.equal(readFileSync(script, "utf8"), completion.SCRIPTS[shell]);
    assert.ok(io.stdout[0]!.endsWith(script));
    io = captured();
    assert.equal(await main(["completion", shell, "--install"], io), OK);
    if (!rc) assert.deepEqual(io.stdout.slice(1), ["fish loads it by itself."]);
    else {
      assert.deepEqual(io.stdout.slice(1), [`${rc} already loads it.`]);
      assert.equal(readFileSync(rc, "utf8").split(completion.MARK).length, 2);
    }
  }
});

test("dashboard opens the console at a terminal and prints its URL otherwise", async () => {
  const { api } = setup();
  host.fetch = api.fetch;
  host.env.NOCLICK_CONSOLE_URL = "https://console.test/developers";
  host.env.DISPLAY = ":0";
  const opened: string[] = [];
  host.openUrl = (url) => (opened.push(url), true);
  let io = captured();
  assert.equal(await main(["dashboard"], io), OK); // piped: printed, not opened
  assert.deepEqual([io.stdout, opened], [["https://console.test/developers"], []]);
  api.on("GET", "/v1/projects", json(listing([PROJECT])));
  io = captured(true);
  assert.equal(await main(["dashboard", "booking"], io), OK);
  const page = `https://console.test/developers/resources/apps/${PROJECT.id}`;
  assert.deepEqual([io.stdout, opened], [[page], [page]]);
  assert.ok(io.stderr.some((l) => l.includes("Opened it in your browser.")));
  delete host.env.NOCLICK_CONSOLE_URL;
  io = captured();
  assert.equal(await main(["dashboard"], io), FAILED); // the fake API's console isn't known
  assert.ok(io.stderr.some((l) => l.includes("NOCLICK_CONSOLE_URL")));
});

const CHANGELOG_MD = `# Changelog

> What changed in NoClick, newest first.

## November 28, 2026

### Profiles switch from the CLI

New · SDK · Next SDK release

\`noclick profile use\` makes a login the default.

### Improvements and fixes

- Fixed: a typo.

## November 20, 2026

### Older change

Improved · API

It changed.

### Improvements and fixes

- Fixed: another typo.

## Earlier

- [September 2026](https://docs.test/changelog/2026-09.md): 86 changes
`;

/** A fake docs site serving changelog.md, as NOCLICK_DOCS_URL names it; what it was asked, by path. */
async function docsSite(): Promise<{ asked: string[]; base: string; close(): void }> {
  const asked: string[] = [];
  const server = createServer((req, res) => {
    asked.push(req.url ?? "");
    const found = req.url === "/docs/changelog.md";
    res.writeHead(found ? 200 : 404, { "content-type": "text/markdown; charset=utf-8" });
    res.end(found ? CHANGELOG_MD : "no");
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}/docs`;
  host.fetch = fetch;
  host.env.NOCLICK_DOCS_URL = `${base}/`;
  return { asked, base, close: () => server.close() };
}

test("changelog lists the newest changes first from the docs page", async () => {
  const site = await docsSite();
  try {
    let io = captured();
    assert.equal(await main(["changelog", "--limit", "3"], io), OK);
    assert.deepEqual(io.stdout, ["DATE        CHANGE", "2026-11-28  Profiles switch from the CLI",
      "2026-11-28  Improvements and fixes", "2026-11-20  Older change"]);
    assert.ok(io.stderr.some((l) => l.includes("Read one whole: noclick changelog profiles-switch-from-the-cli")));
    assert.deepEqual(site.asked, ["/docs/changelog.md"]);
    io = captured();
    assert.equal(await main(["changelog", "--json", "--limit", "1"], io), OK);
    assert.deepEqual(JSON.parse(io.stdout.join("\n")).data[0], {
      date: "2026-11-28", title: "Profiles switch from the CLI", slug: "profiles-switch-from-the-cli",
      url: `${site.base}/changelog/2026-11#2026-11-28-profiles-switch-from-the-cli`, kind: "new",
      areas: "SDK · Next SDK release", body: "`noclick profile use` makes a login the default.",
    });
  } finally {
    site.close();
  }
});

test("changelog prints one change whole by its title or slug, and says where it couldn't read the page", async () => {
  const site = await docsSite();
  try {
    let io = captured();
    assert.equal(await main(["changelog", "Profiles switch from the CLI"], io), OK);
    assert.deepEqual(io.stdout, ["## Profiles switch from the CLI\n2026-11-28 · New · SDK · Next SDK release\n\n"
      + "`noclick profile use` makes a login the default."]);
    assert.ok(io.stderr.some((l) => l.includes("#2026-11-28-profiles-switch-from-the-cli")));
    io = captured();
    assert.equal(await main(["changelog", "improvements-and-fixes"], io), USAGE); // two days share it: named by date
    assert.ok(io.stderr.some((l) => l.includes("improvements-and-fixes-2026-11-28, improvements-and-fixes-2026-11-20")));
    io = captured();
    assert.equal(await main(["changelog", "improvements-and-fixes-2026-11-20"], io), OK);
    assert.ok(io.stdout[0]!.includes("another typo"));
    io = captured();
    assert.equal(await main(["changelog", "older"], io), OK);
    assert.ok(io.stdout[0]!.startsWith("## Older change\n2026-11-20 · Improved · API"));
    assert.equal(await main(["changelog", "nothing-like-this"], captured()), FAILED);
    host.env.NOCLICK_DOCS_URL = `${site.base}/missing`;
    io = captured();
    assert.equal(await main(["changelog"], io), FAILED);
    assert.ok(io.stderr.some((l) => l.includes("missing/changelog.md: it answered 404")));
  } finally {
    site.close();
  }
});

test("the update notice is said at most once a day, never where it would get in the way", () => {
  const say = { current: "0.2.6", how: updates.NPM, terminals: true, env: host.env };
  assert.equal(updates.notice([], { ...say, now: 0 }), null);
  assert.equal(spawned.length, 1); // nothing heard yet: npm is asked, by a process of its own
  const path = join(config, updates.FILE);
  writeFileSync(path, JSON.stringify({ ...JSON.parse(readFileSync(path, "utf8")), latest: "0.3.0" }));
  assert.equal(updates.notice([], { ...say, now: 60_000 }),
    "A newer noclick is out: 0.3.0 (you have 0.2.6). Update: npm install -g noclick@latest");
  assert.equal(updates.notice([], { ...say, now: 120_000 }), null);
  assert.equal(spawned.length, 1);
  const later = updates.DAY_MS + 61_000;
  assert.notEqual(updates.notice([], { ...say, now: later }), null);
  assert.equal(spawned.length, 2);
  for (const quiet of [{ argv: ["--json"] }, { env: { ...host.env, CI: "1" } }, { env: { ...host.env, NOCLICK_NO_UPDATE_CHECK: "1" } },
    { terminals: false }]) {
    assert.equal(updates.notice(quiet.argv ?? [], { ...say, now: later * 3, ...quiet }), null);
  }
  assert.ok(!updates.newer("0.3.0-rc.1", "0.2.6") && !updates.newer("0.2.6", "0.2.6") && updates.newer("0.10.0", "0.9.9"));
  assert.ok(existsSync(path));
});
