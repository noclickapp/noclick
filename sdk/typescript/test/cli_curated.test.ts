/** The curated commands `npx noclick` runs, through `main` as a terminal or an agent drives it, over the fetch double:
 *  sign-in kept where the Python CLI reads it, a folder shipped as a commit with its secrets refused, a secret's value
 *  never printed, a purchase only under a ceiling. */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { beforeEach, test } from "node:test";

import { main } from "../src/cli/main.ts";
import { host } from "../src/cli/host.ts";
import { osKeychain } from "../src/cli/keychain.ts";
import { FAILED, INTERRUPTED, OK, REFUSED, USAGE, WAITING } from "../src/cli/exits.ts";
import type { Io } from "../src/cli/output.ts";
import { load } from "../src/cli/spec.ts";
import { RUNNERS } from "../src/cli/runners/index.ts";
import { BASE, apiError, json, listing, operation, setup } from "./helpers.ts";

const KEY = "nk_live_cli_secret_key_0123456789";
const SECRET = "sk_test_value_never_printed_42";
const APP_ID = "5c2e8a1f-0000-4000-8000-000000000001";
const PROJECT = {
  object: "project", id: APP_ID, name: "shop", url: "https://shop.noclick.site", repo_id: "repo_1",
  runtime: "edge", production_branch: "main", production: null, user_id: null, budget_usd_per_month: 10,
};
const signedIn = { signIn: () => {} };

function captured(): Io & { stdout: string[]; stderr: string[]; all(): string } {
  const stdout: string[] = [];
  const stderr: string[] = [];
  return { stdout, stderr, out: (l) => stdout.push(l), err: (l) => stderr.push(l), write: (d) => stdout.push(new TextDecoder().decode(d)), all: () => [...stdout, ...stderr].join("\n") };
}

let config = "";
let folder = "";

beforeEach(() => {
  const home = mkdtempSync(join(tmpdir(), "noclick-cli-"));
  config = join(home, "config");
  folder = mkdtempSync(join(tmpdir(), "noclick-app-"));
  // The OS keychain is per user, whatever HOME says: off, unless a test hands it a stand-in.
  host.env = { NOCLICK_CONFIG_DIR: config, NOCLICK_API_URL: BASE, HOME: home, PATH: process.env.PATH, NOCLICK_KEYCHAIN: "off" };
  host.platform = process.platform;
  host.cwd = () => folder;
  host.sleep = async () => {};
  host.stdinIsTty = () => false;
  host.run = () => {
    throw new Error("A test ran a program through host.run without a stand-in.");
  };
});

test("npx noclick runs exactly the curated commands the manifest lists", () => {
  for (const path of Object.keys(RUNNERS)) assert.ok(load().curated(path.split(" ")), path);
  const builtIn = new Set(["api", "describe", "help"]);
  const missing = load().commands.map((c) => c.path.join(" ")).filter((p) => !builtIn.has(p) && !(p in RUNNERS));
  assert.deepEqual(missing, []);
});

test("setup keeps the key where the Python CLI reads it, readable only by you, and never prints it", async () => {
  const { api } = setup();
  host.fetch = api.fetch;
  const redeem = api.on("POST", "/v1/setup", json({ key: KEY, key_id: "key_1", key_name: "Setup key", email: "ana@example.com" }));
  api.on("GET", "/v1/status", json({ account: { id: "acct_1", name: "Ana", email: "ana@example.com" } }));
  const io = captured();
  assert.equal(await main(["setup", "nc_setup_abc"], io), OK);
  assert.equal(redeem.last.headers.get("authorization"), null);
  assert.equal(io.all().includes(KEY), false);
  assert.equal(JSON.parse(readFileSync(join(config, "credentials.json"), "utf8")).default, KEY);
  assert.equal(statSync(join(config, "credentials.json")).mode & 0o777, 0o600);
  assert.equal(JSON.parse(readFileSync(join(config, "config.json"), "utf8")).profiles.default.store, "file");
  // A keychain is asked for by name, and refused before anything is redeemed.
  assert.equal(await main(["setup", "nc_setup_abc", "--store", "keychain"], captured()), FAILED);
  assert.equal(redeem.count, 1);
});

const SIGNED_UP = {
  object: "agent_signup", id: "su_1", status: "unclaimed", agent: "claude-code", key: KEY, key_id: "key_9",
  claim_url: "https://noclick.test/claim/tok_1", expires_at: "2026-12-04T00:00:00Z",
  limits: { unclaimed_days: 7, until_claimed: ["buying anything (numbers, domains, cards, machines)"] },
};

test("signup needs the terms, then keeps the key as login does and prints the claim link last", async () => {
  const { api } = setup();
  host.fetch = api.fetch;
  host.env.CLAUDECODE = "1";
  const made = api.on("POST", "/v1/agent_signups", json(SIGNED_UP, { status: 201 }));
  let io = captured();
  assert.equal(await main(["signup"], io), USAGE);
  assert.ok(io.all().includes("https://noclick.com/legal/developer-terms") && io.all().includes("https://noclick.com/legal/acceptable-use"));
  assert.equal(made.count, 0);

  io = captured();
  assert.equal(await main(["signup", "--accept-terms", "--purpose", "Track orders"], io), OK);
  assert.equal(made.last.headers.get("authorization"), null);
  assert.deepEqual(made.last.body, { agent: "claude-code", accept_terms: true, purpose: "Track orders" });
  assert.equal(io.all().includes(KEY), false);
  assert.equal(io.stdout.at(-1), "https://noclick.test/claim/tok_1");
  assert.ok(io.stderr.some((l) => l.startsWith("Works now:")) && io.all().includes("buying anything"));
  assert.equal(JSON.parse(readFileSync(join(config, "credentials.json"), "utf8")).default, KEY);

  // whoami and status say it waits for a claim, and stop once a person has claimed it.
  api.on("GET", "/v1/status", json({ account: { id: "acct_9" } }));
  const current = api.on("GET", "/v1/agent_signups/current", json({ status: "unclaimed" }), json({ status: "claimed" }));
  io = captured();
  assert.equal(await main(["whoami"], io), OK);
  assert.ok(io.stderr.includes("unclaimed: give your person https://noclick.test/claim/tok_1"));
  io = captured();
  assert.equal(await main(["whoami"], io), OK);
  assert.equal(await main(["whoami"], io), OK);
  assert.equal(io.all().includes("unclaimed"), false);
  assert.equal(current.count, 2);

  // A signed-in profile isn't signed up again.
  assert.equal(await main(["signup", "--accept-terms"], captured()), FAILED);
  assert.equal(made.count, 1);
});

test("signup refused by the gate exits 4 in the API's words and keeps nothing", async () => {
  const { api } = setup();
  host.fetch = api.fetch;
  api.on("POST", "/v1/agent_signups", apiError(403, "permission_denied", "Agents can't sign up for NoClick by themselves yet.", { reason: "not_launched" }));
  const io = captured();
  assert.equal(await main(["signup", "--accept-terms", "--agent", "my-bot"], io), REFUSED);
  assert.ok(io.all().includes("Agents can't sign up for NoClick by themselves yet."));
  assert.equal(existsSync(join(config, "credentials.json")), false);
});

test("login prints the link first, and a run cut short is picked up by the next", async () => {
  const { api } = setup();
  host.fetch = api.fetch;
  const start = api.on("POST", "/v1/cli/logins", json({
    device_code: "dev_1", user_code: "ABCD-EFGH", verification_url: "https://noclick.com/cli",
    verification_url_complete: "https://noclick.com/cli?code=ABCD-EFGH", interval_s: 5, expires_at: "2999-01-01T00:00:00Z",
  }));
  api.on("POST", "/v1/cli/logins/token", apiError(409, "conflict", "Busy."),
    json({ status: "approved", key: KEY, key_id: "key_1", key_name: "noclick-cli", email: "ana@example.com" }));
  const cut = captured();
  assert.equal(await main(["login"], cut), FAILED);
  assert.equal(cut.stdout[0], "Open https://noclick.com/cli and enter the code ABCD-EFGH");
  const done = captured();
  assert.equal(await main(["login"], done), OK);
  assert.equal(start.count, 1);
  assert.equal(done.all().includes(KEY), false);
  assert.equal(JSON.parse(readFileSync(join(config, "credentials.json"), "utf8")).default, KEY);
});

test("a login goes to the OS keychain where the machine has one, as the Python CLI keeps it, and logout takes it out", async () => {
  const { api } = setup();
  host.fetch = api.fetch;
  // A Secret Service, as secret-tool reaches it: items by their attributes, a secret only ever on stdin. A stand-in
  // on every OS, so a developer's own keychain is never touched.
  const tool = "/stand-in/secret-tool";
  host.platform = "linux";
  host.env.NOCLICK_KEYCHAIN = tool;
  const items = new Map<string, string>();
  const calls: string[][] = [];
  host.run = (command, args, input) => {
    calls.push([command, ...args]);
    assert.equal(command, tool);
    const at = (name: string) => args[args.indexOf(name) + 1];
    const id = `${at("service")}/${at("username")}`;
    if (args[0] === "lookup") return items.has(id) ? { status: 0, stdout: items.get(id)!, stderr: "" } : { status: 1, stdout: "", stderr: "" };
    if (args[0] === "store") {
      items.set(id, input ?? "");
      return { status: 0, stdout: "", stderr: "" };
    }
    items.delete(id);
    return { status: 0, stdout: "", stderr: "" };
  };
  api.on("POST", "/v1/setup", json({ key: KEY, key_id: "key_1", key_name: "Setup key", email: "ana@example.com" }));
  const io = captured();
  assert.equal(await main(["setup", "nc_setup_abc"], io), OK);
  assert.equal(items.get("noclick/default"), KEY);
  assert.ok(calls.every((call) => !call.includes(KEY))); // never in a process's arguments
  assert.deepEqual(calls.find((c) => c[1] === "store")!.slice(-6), ["service", "noclick", "username", "default", "application", "Python keyring library"]);
  assert.equal(existsSync(join(config, "credentials.json")), false);
  assert.equal(JSON.parse(readFileSync(join(config, "config.json"), "utf8")).profiles.default.store, "keychain");
  assert.ok(io.stderr.includes('The key "Setup key" is in the OS keychain. noclick logout revokes it.'));

  api.on("GET", "/v1/status", json({ account: { id: "acct_1", name: "Ana", email: "ana@example.com" }, caller: { key_name: "Setup key" } }));
  const who = captured();
  assert.equal(await main(["whoami"], who), OK);
  assert.ok(who.stdout.includes(`Key      Setup key (${KEY.slice(0, 12)}…), in the OS keychain`), who.stdout.join("\n"));

  const revoked = api.on("DELETE", "/v1/keys/current", json({ revoked: true }));
  const out = captured();
  assert.equal(await main(["logout"], out), OK);
  assert.equal(revoked.last.headers.get("authorization"), `Bearer ${KEY}`);
  assert.equal(items.size, 0);
  assert.deepEqual(out.stdout, ["Signed out."]);
});

test("a test that would reach the real OS keychain is stopped first", () => {
  delete host.env.NOCLICK_KEYCHAIN;
  assert.throws(() => osKeychain(), /A test reached the real OS keychain/);
  host.env.NOCLICK_KEYCHAIN = "off";
  assert.equal(osKeychain(), null);
});

test("on macOS the key is a generic password, service noclick and account the profile, handed to security on stdin", () => {
  const calls: { args: string[]; input?: string }[] = [];
  let held: string | null = null;
  host.platform = "darwin";
  host.env.NOCLICK_KEYCHAIN = "/stand-in/security";
  host.run = (command, args, input) => {
    assert.equal(command, "/stand-in/security");
    calls.push({ args, input });
    if (args[0] === "find-generic-password") return held === null ? { status: 44, stdout: "", stderr: "" } : { status: 0, stdout: `${held}\n`, stderr: "" };
    if (args[0] === "-i") held = /-w "([^"]*)"/.exec(input ?? "")![1]!;
    if (args[0] === "delete-generic-password") held = null;
    return { status: 0, stdout: "", stderr: "" };
  };
  const keychain = osKeychain()!;
  assert.equal(keychain.read("work"), null);
  keychain.write("work", KEY);
  assert.equal(calls.find((call) => call.args[0] === "-i")!.input, `add-generic-password -U -s "noclick" -a "work" -w "${KEY}"\n`);
  assert.ok(calls.every((call) => !call.args.includes(KEY)));
  assert.equal(keychain.read("work"), KEY);
  assert.deepEqual(calls.at(-1)!.args, ["find-generic-password", "-s", "noclick", "-a", "work", "-w"]);
  keychain.delete("work");
  assert.equal(keychain.read("work"), null);
});

test("a secret's value comes from the environment, reaches the API and is never printed", async () => {
  const { api } = setup();
  host.env.STRIPE = SECRET;
  api.on("GET", "/v1/projects", json(listing([PROJECT])));
  const put = api.on("PUT", "/v1/projects/" + APP_ID + "/secrets/STRIPE_KEY", json({ name: "STRIPE_KEY" }));
  const io = captured();
  assert.equal(await main(["secret", "set", "STRIPE_KEY", "--from-env", "STRIPE", "--app", "shop"], io, signedIn), OK, io.all());
  assert.equal(JSON.stringify(put.last.body).includes(SECRET), true);
  assert.equal(io.all().includes(SECRET), false);
  // Exactly one source: a value typed as an argument, or none at all, is a usage error.
  assert.equal(await main(["secret", "set", "STRIPE_KEY", SECRET, "--app", "shop"], captured(), signedIn), USAGE);
  assert.equal(await main(["secret", "set", "STRIPE_KEY", "--app", "shop"], captured(), signedIn), USAGE);
});

test("a domain is bought only under a ceiling; a person to pay is 3, a cap 4", async () => {
  const { api } = setup();
  const buy = api.on("POST", "/v1/domains", apiError(402, "payment_required", "Add funds to buy this."));
  assert.equal(await main(["domains", "buy", "acme.com"], captured(), signedIn), USAGE);
  assert.equal(buy.count, 0);
  assert.equal(await main(["domains", "buy", "acme.com", "--max-price", "15"], captured(), signedIn), WAITING);
  assert.equal((buy.last.body as { max_price_usd: number }).max_price_usd, 15);
  api.on("POST", "/v1/domains", apiError(402, "spend_cap_exceeded", "Over your cap."));
  assert.equal(await main(["domains", "buy", "acme.com", "--max-price", "15"], captured(), signedIn), REFUSED);
});

function deployRoutes(api: ReturnType<typeof setup>["api"], exists = true) {
  if (exists) api.on("GET", "/v1/projects", json(listing([PROJECT])));
  else api.on("GET", "/v1/projects", json(listing([])), json(listing([PROJECT])));
  api.on("GET", "/v1/repos", json(listing([])));
  api.on("POST", "/v1/repos", json({ object: "repo", id: "repo_1", name: "shop", default_branch: "main" }));
  api.on("POST", "/v1/projects", json(PROJECT));
  api.on("GET", "/v1/projects/" + APP_ID, json(PROJECT));
  api.on("GET", "/v1/repos/repo_1/branches", json(listing([{ name: "main", head: "aaa" }])));
  api.on("GET", "/v1/repos/repo_1/files", json(listing([])));
  const commit = api.on("POST", "/v1/repos/repo_1/commits", json({ sha: "abc1234def", message: "m", branch: "main" }));
  const deploy = api.on("POST", "/v1/projects/" + APP_ID + "/deployments", json(operation({ id: "op_d", kind: "project.deploy", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_d/wait", json(operation({
    id: "op_d", kind: "project.deploy", status: "succeeded",
    result: { object: "deployment", id: "dep_1", url: "https://shop.noclick.site", production: true, status: "ready" },
  })));
  return { commit, deploy };
}

test("deploy makes a folder's app, ships what isn't ignored as a commit, links it, and prints the URL last", async () => {
  folder = join(folder, "Shop");
  mkdirSync(join(folder, "node_modules"), { recursive: true });
  writeFileSync(join(folder, "index.html"), "<h1>shop</h1>");
  writeFileSync(join(folder, "node_modules", "big.js"), "x");
  writeFileSync(join(folder, "notes.log"), "x");
  writeFileSync(join(folder, ".gitignore"), "*.log\n");
  const { api } = setup();
  const { commit, deploy } = deployRoutes(api, false);
  const io = captured();
  assert.equal(await main(["deploy"], io, signedIn), OK, io.all());
  assert.deepEqual((commit.last.body as { files: Array<{ path: string }> }).files.map((f) => f.path).sort(), [".gitignore", "index.html"]);
  assert.deepEqual(deploy.last.body, { branch: "main", commit: "abc1234def" });
  assert.equal(io.stdout.at(-1), "https://shop.noclick.site");
  const link = JSON.parse(readFileSync(join(folder, ".noclick", "project.json"), "utf8"));
  assert.deepEqual([link.app, link.app_id], ["shop", APP_ID]);
});

test("a file that looks like a secret is left out and said, its names never its values", async () => {
  writeFileSync(join(folder, "index.html"), "<h1>shop</h1>");
  writeFileSync(join(folder, ".env"), `STRIPE=${SECRET}\nexport DB_URL=postgres://u:p@h/db\n`);
  writeFileSync(join(folder, ".env.example"), "STRIPE=\n");
  const { api } = setup();
  const { commit } = deployRoutes(api);
  const io = captured();
  assert.equal(await main(["deploy", "--app", "shop", "--no-wait", "--json"], io, signedIn), OK, io.all());
  assert.deepEqual((commit.last.body as { files: Array<{ path: string }> }).files.map((f) => f.path).sort(), [".env.example", "index.html"]);
  assert.deepEqual(JSON.parse(io.stdout.join("\n")).left_out, [{
    path: ".env", why: "looks like a secret, and a secret never ships in the app's code", names: ["STRIPE", "DB_URL"],
    next_steps: ["noclick secret set STRIPE --from-env STRIPE", "noclick secret set DB_URL --from-env DB_URL"],
  }]);
  assert.ok(io.stderr.includes("  noclick secret set DB_URL --from-env DB_URL"));
  assert.equal(io.all().includes(SECRET) || io.all().includes("u:p@h"), false);
});

test("a checkout with untracked files ships them as a commit; --only-committed refuses", async () => {
  const run = (...args: string[]) => execFileSync("git", args, {
    cwd: folder, env: { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.com", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.com" },
  });
  run("init", "-q", "-b", "main");
  writeFileSync(join(folder, "app.js"), "1");
  writeFileSync(join(folder, ".gitignore"), "dist/\n");
  run("add", "-A");
  run("commit", "-qm", "first");
  writeFileSync(join(folder, "new.js"), "2");
  mkdirSync(join(folder, "dist"));
  writeFileSync(join(folder, "dist", "out.js"), "built");
  const { api } = setup();
  const { commit } = deployRoutes(api);
  assert.equal(await main(["deploy", "--app", "shop", "--only-committed"], captured(), signedIn), FAILED);
  const io = captured();
  assert.equal(await main(["deploy", "--app", "shop", "--no-wait", "--json"], io, signedIn), OK, io.all());
  assert.deepEqual((commit.last.body as { files: Array<{ path: string }> }).files.map((f) => f.path).sort(), [".gitignore", "app.js", "new.js"]);
  assert.equal(JSON.parse(io.stdout.join("\n")).operation_id, "op_d");

  // An untracked .env alone leaves the checkout clean; committed, it's in the app's history either way: refused.
  run("add", "new.js");
  run("commit", "-qm", "second");
  writeFileSync(join(folder, ".env"), `STRIPE=${SECRET}\n`);
  const remote = mkdtempSync(join(tmpdir(), "noclick-remote-"));
  execFileSync("git", ["init", "-q", "--bare", "-b", "main", remote]);
  api.on("POST", "/v1/repos/repo_1/clone_url", json({ url: `file://${remote}`, expires_at: "2999-01-01T00:00:00Z" }));
  const clean = captured();
  assert.equal(await main(["deploy", "--app", "shop", "--only-committed", "--no-wait"], clean, signedIn), OK, clean.all());
  const head = String(run("rev-parse", "HEAD")).trim();
  assert.equal(String(execFileSync("git", ["rev-parse", "main"], { cwd: remote })).trim(), head);
  assert.ok(clean.stderr.includes("Left out .env: it looks like a secret, and a secret never ships in the app's code. Give the app its values with:"));
  run("add", "-f", ".env");
  run("commit", "-qm", "oops");
  const refused = captured();
  assert.equal(await main(["deploy", "--app", "shop", "--json"], refused, signedIn), FAILED);
  const { error } = JSON.parse(refused.stdout.join("\n"));
  assert.deepEqual(error.details.files, [".env"]);
  assert.match(error.next_step ?? error.nextStep ?? "", /git rm --cached \.env/);
  assert.equal(commit.count, 1);
});

test("db create prices the database under --max-usd before it makes anything", async () => {
  const { api } = setup();
  const priced = api.on("POST", "/v1/estimates", json({ object: "estimate", monthly_usd: 5, lines: [], items: [] }));
  const made = api.on("POST", "/v1/databases", json({ object: "database", id: "db_1", name: "orders", engine: "postgres" }));
  assert.equal(await main(["db", "create", "orders", "--engine", "postgres", "--max-usd", "1"], captured(), signedIn), REFUSED);
  assert.deepEqual(priced.last.body, { items: [{ kind: "database", engine: "postgres" }] });
  assert.equal(made.count, 0);
});

test("rollback serves the release before the live one, and --preview takes no value", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects", json(listing([PROJECT])));
  api.on("GET", "/v1/projects/" + APP_ID + "/deployments", json(listing([
    { object: "deployment", id: "dep_2", status: "ready", production: true, branch: "main", commit: "bbbbbbb", url: "https://shop.noclick.site" },
    { object: "deployment", id: "dep_1", status: "ready", production: false, branch: "main", commit: "aaaaaaa", url: "https://x.noclick.site" },
  ])));
  const back = api.on("POST", "/v1/deployments/dep_1/promote", json(operation({
    id: "op_r", kind: "project.rollback", status: "succeeded",
    result: { object: "deployment", id: "dep_1", url: "https://shop.noclick.site", production: true, status: "ready" },
  })));
  api.on("GET", "/v1/operations/op_r/wait", json(operation({ id: "op_r", kind: "project.rollback", status: "succeeded",
    result: { object: "deployment", id: "dep_1", url: "https://shop.noclick.site", production: true, status: "ready" } })));
  const io = captured();
  assert.equal(await main(["rollback", "--app", "shop"], io, signedIn), OK, io.all());
  assert.equal(back.count, 1); // dep_1, the ready release before the live one
  assert.equal(io.stdout.at(-1), "https://shop.noclick.site");
  // `--preview` alone is the newest preview (argparse's nargs="?"): it isn't missing its value.
  assert.equal(await main(["open", "--app", "shop", "--preview"], captured(), signedIn), 1);
});

test("a setting is written on the app it names, its value in the body", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects", json(listing([PROJECT])));
  const put = api.on("PUT", `/v1/projects/${APP_ID}/settings/PORT`, json({ name: "PORT" }));
  assert.equal(await main(["settings", "set", "shop", "PORT", "8080"], captured(), signedIn), OK);
  assert.deepEqual(put.last.body, { value: "8080" });
});

test("a clean checkout pushes the commit it is on, deploys exactly it, and prints the URL last", async () => {
  const run = (...args: string[]) => execFileSync("git", args, {
    cwd: folder, env: { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.com", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.com" },
  });
  const remote = mkdtempSync(join(tmpdir(), "noclick-remote-"));
  execFileSync("git", ["init", "-q", "--bare", "-b", "main", remote]);
  run("init", "-q", "-b", "main");
  writeFileSync(join(folder, "app.js"), "1");
  run("add", "-A");
  run("commit", "-qm", "first");
  const sha = String(run("rev-parse", "HEAD")).trim();
  const { api } = setup();
  api.on("GET", "/v1/projects", json(listing([PROJECT])));
  api.on("POST", "/v1/repos/repo_1/clone_url", json({ url: `file://${remote}`, expires_at: "2999-01-01T00:00:00Z" }));
  const deploy = api.on("POST", `/v1/projects/${APP_ID}/deployments`, json(operation({ id: "op_d", kind: "project.deploy", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_d/wait", json(operation({
    id: "op_d", kind: "project.deploy", status: "succeeded",
    result: { object: "deployment", id: "dep_1", url: "https://shop.noclick.site", production: true, status: "ready" },
  })));
  const io = captured();
  assert.equal(await main(["deploy", "--app", "shop"], io, signedIn), OK, io.all());
  assert.deepEqual(deploy.last.body, { branch: "main", commit: sha });
  assert.equal(String(execFileSync("git", ["rev-parse", "main"], { cwd: remote })).trim(), sha);
  assert.equal(io.stdout.at(-1), "https://shop.noclick.site");
});

test("a deploy draws its stages and build lines as they come, and Ctrl-C leaves it running", async () => {
  writeFileSync(join(folder, "index.html"), "<h1>shop</h1>");
  const { api } = setup();
  deployRoutes(api);
  api.on("POST", "/v1/projects/" + APP_ID + "/deployments", json(operation({ id: "op_d", kind: "project.deploy", status: "queued", updated_at: "2026-11-28T10:00:00Z" }), { status: 202 }));
  const moving = (status: string, stage: number, lines: string[], at: string, extra: Record<string, unknown> = {}) => json(operation({
    id: "op_d", kind: "project.deploy", status, updated_at: at, ...extra, progress: {
      stages: ["Queued", "Building", "Shipping", "Live"].map((name, i) => ({ name, status: i < stage ? "done" : i === stage ? "current" : "pending" })),
      lines, line_count: lines.length,
    },
  }));
  const waits = api.on("GET", "/v1/operations/op_d/wait",
    moving("running", 1, ["> vite build"], "2026-11-28T10:00:02Z"),
    moving("running", 2, ["> vite build", "built in 3.1s"], "2026-11-28T10:00:06Z"),
    moving("succeeded", 4, ["> vite build", "built in 3.1s", "==> / answered 200"], "2026-11-28T10:00:08Z",
      { result: { object: "deployment", id: "dep_2", url: "https://shop.noclick.site", production: true, status: "ready" } }));
  const io = captured();
  assert.equal(await main(["deploy", "--app", "shop"], io, signedIn), OK, io.all());
  assert.deepEqual(waits.calls.map((call) => call.query.get("changed_since")),
    ["2026-11-28T10:00:00Z", "2026-11-28T10:00:02Z", "2026-11-28T10:00:06Z"]);
  assert.equal(io.stdout.at(-1), "https://shop.noclick.site");
  const drawn = io.stderr.slice(io.stderr.indexOf("Queue…")).join("\n");
  assert.match(drawn, /^Queue…\nQueue: /);
  assert.ok(drawn.includes("Build…\n  > vite build\n  built in 3.1s\nBuild: "), drawn);
  assert.ok(drawn.includes("Release…\n  ==> / answered 200\nRelease: "), drawn);
  assert.ok(drawn.includes("Ready: https://shop.noclick.site · production · release dep_2 · "), drawn);

  // Ctrl-C mid-read stops following, never the deploy.
  api.on("GET", "/v1/operations/op_d/wait", () => new Promise<Response>(() => {}));
  const detached = captured();
  const caught = host.interrupted;
  host.interrupted = () => ({ promise: Promise.resolve(), release: () => {} });
  try {
    assert.equal(await main(["deploy", "--app", "shop", "--json"], detached, signedIn), INTERRUPTED);
  } finally {
    host.interrupted = caught;
  }
  assert.equal(JSON.parse(detached.stdout.join("\n")).operation_id, "op_d");
  assert.ok(detached.stderr.includes("Detached: it goes on. Follow it with: noclick wait op_d"), detached.all());
});

test("shell runs a command where it says and exits with the command's own code", async () => {
  const { api } = setup();
  host.fetch = api.fetch;
  const sandbox = "3b9d6f2e-1c4a-4e8b-9f7d-2a6c5e8b1d40";
  const ran = api.on("POST", `/v1/sandboxes/${sandbox}/exec`, json({ object: "sandbox_exec", stdout: "Python 3.12.7\n", stderr: "", exit_code: 3 }));
  let io = captured();
  assert.equal(await main(["shell", sandbox, "--", "python", "-c", "print('hi there')"], io, signedIn), 3);
  assert.deepEqual(ran.last.body, { command: "python -c 'print('\"'\"'hi there'\"'\"')'" });
  assert.deepEqual(io.stdout, ["Python 3.12.7"]);
  api.on("GET", "/v1/projects", json(listing([PROJECT])));
  const live = api.on("POST", `/v1/projects/${APP_ID}/live/exec`, json({ stdout: "4 passed\n", stderr: "", exit_code: 0, timed_out: false, ms: 900, vite: [] }));
  io = captured();
  assert.equal(await main(["shell", "--app", "shop", "--json", "--", "npm test"], io, signedIn), OK, io.all());
  assert.equal((live.last.body as { command: string }).command, "npm test");
  assert.deepEqual(JSON.parse(io.stdout.join("\n")), { stdout: "4 passed\n", stderr: "", exit_code: 0 });
  io = captured();
  assert.equal(await main(["shell", "--app", "shop"], io, signedIn), FAILED);
  assert.ok(io.all().includes("noclick shell --app shop -- <command>"), io.all());
});
