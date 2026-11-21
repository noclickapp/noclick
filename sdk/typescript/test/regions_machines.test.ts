// Regions (built for sandboxes and agents, designed on the data and hosting resources) and
// machines (designed, not built yet): the routes, bodies and parsed results the client sends and reads.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, operation, setup } from "./helpers.ts";

const REGIONS = [
  ["us-east", "US East"], ["us-west", "US West"], ["eu", "Europe"], ["ap", "Asia-Pacific"],
].map(([name, label]) => ({ object: "region", name, label, location: `${label} somewhere`, kinds: ["sandbox", "agent"], default: name === "eu" }));
const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: null,
  region: "us-east", created_at: "2026-10-01T10:00:00Z",
};
const MACHINE_ID = "3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b40";
const MACHINE = {
  object: "machine", id: MACHINE_ID, name: "support-box", size: "medium", cpu: 4, memory_gb: 8, disk_gb: 160, region: "eu",
  status: "running", status_reason: null, monthly_usd: 78, max_monthly_usd: 120, network: true, volumes: {},
  ports: [{ port: 8080, url: "https://m-8080.example", public: false }],
  agent_count: 1, image: "noclick-machine:2026.10", restarts: 0, last_restart_at: null, user_id: null, created_at: "2026-10-01T10:00:00Z",
};

test("regions() reads the catalog for the account, with the default marked", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/regions", json(listing(REGIONS)));
  const regions = await nc.asUser("user_42", () => nc.regions({ kind: "sandbox" }));
  assert.equal(route.last.query.get("kind"), "sandbox");
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.deepEqual(regions.map((r) => r.name), ["us-east", "us-west", "eu", "ap"]);
  assert.deepEqual([regions[2].label, regions[2].kinds, regions[2].default], ["Europe", ["sandbox", "agent"], true]);
  await nc.regions();
  assert.equal(route.last.query.get("kind"), null);
});

test("a sandbox and an agent take a region and read it back", async () => {
  const { api } = setup();
  const sandbox = api.on("POST", "/v1/sandboxes", json({ object: "sandbox", id: "sb_1", status: "running", region: "eu" }));
  const created = await nc.Sandbox.create({ image: "python", region: "eu" });
  assert.deepEqual(sandbox.last.body, { image: "python", region: "eu" });
  assert.equal(created.region, "eu");

  const agent = api.on("POST", "/v1/agents", json({ ...AGENT, region: "eu" }));
  const support = await nc.Agent.create("support", { instructions: "hi", region: "eu" });
  assert.equal((agent.last.body as Record<string, unknown>).region, "eu");
  assert.equal(support.region, "eu");
});

test("Agent.fromName sends its region to an existing agent elsewhere, and the conflict surfaces", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([AGENT])));
  const patch = api.on("PATCH", "/v1/agents/ag_1", apiError(409, "conflict", "fixed", { region: "us-east" }));
  await assert.rejects(nc.Agent.fromName("support", { createIfMissing: true, instructions: "hi", region: "eu" }).hydrate(), nc.Conflict);
  assert.deepEqual(patch.last.body, { region: "eu" });
  await nc.Agent.fromName("support", { createIfMissing: true, instructions: "hi" }).hydrate();
  assert.equal(patch.count, 1);
});

test("data and hosting resources take a region (designed)", async () => {
  const { api } = setup();
  const routes = Object.fromEntries(["volumes", "buckets", "queues", "dicts", "databases", "projects"].map((kind) => [
    kind, api.on("POST", `/v1/${kind}`, json({ object: kind.slice(0, -1), id: "x_1", name: "n", region: "eu" })),
  ]));
  await nc.Volume.create("datasets", { region: "eu" });
  await nc.Bucket.create("records", { region: "eu" });
  await nc.Queue.create("jobs", { region: "eu" });
  await nc.Dict.create("seen", { region: "eu" });
  const db = await nc.Database.create("orders", { engine: "postgres", region: "eu" });
  await nc.Project.create("booking", { repo: "repo_1", region: "eu" });
  for (const route of Object.values(routes)) assert.equal((route.last.body as Record<string, unknown>).region, "eu");
  assert.equal(db.region, "eu");
  await nc.Volume.create("cache");
  assert.deepEqual(routes.volumes.last.body, { name: "cache" });
});

test("machines: sizes list each host's disk and price, and create can name a host", async () => {
  const { api } = setup();
  api.on("GET", "/v1/machines/sizes", json(listing([
    {
      object: "machine_size", name: "small", cpu: 2, memory_gb: 4, disk_gb: 40, monthly_usd: 8.39, working_conversations: 2,
      hosts: [
        { host: "hetzner", regions: ["eu"], disk_gb: 40, monthly_usd: 8.39 },
        { host: "digitalocean", regions: ["us-east", "us-west", "eu", "ap"], disk_gb: 80, monthly_usd: 31.2 },
      ],
    },
  ])));
  const create = api.on("POST", "/v1/machines", json({ ...MACHINE, host: "digitalocean" }));
  const [small] = await nc.Machine.sizes();
  assert.deepEqual([small.diskGb, small.monthlyUsd], [40, 8.39]);
  assert.deepEqual(small.hosts, [
    { host: "hetzner", regions: ["eu"], diskGb: 40, monthlyUsd: 8.39 },
    { host: "digitalocean", regions: ["us-east", "us-west", "eu", "ap"], diskGb: 80, monthlyUsd: 31.2 },
  ]);
  const box = await nc.Machine.create("support-box", { region: "eu", host: "digitalocean", maxMonthlyUsd: 40 });
  assert.deepEqual(create.last.body, { name: "support-box", size: "small", region: "eu", max_monthly_usd: 40, host: "digitalocean" });
  assert.equal(box.host, "digitalocean");
});

test("machines: sizes are size first, each at its cheapest, with where else it can be bought", async () => {
  const { api } = setup();
  const sizes = api.on("GET", "/v1/machines/sizes", json(listing([{
    object: "machine_size", name: "small", cpu: 2, memory_gb: 4, working_conversations: 2, available: true, region: "eu",
    host: "hetzner", disk_gb: 40, monthly_usd: 8.39, dominated_by: null,
    regions: [
      { region: "eu", host: "hetzner", disk_gb: 40, monthly_usd: 8.39, dominated_by: null },
      { region: "us-east", host: "digitalocean", disk_gb: 80, monthly_usd: 31.2, dominated_by: null },
    ],
    hosts: [{ host: "hetzner", regions: ["eu"], disk_gb: 40, monthly_usd: 8.39 }],
  }])));
  const create = api.on("POST", "/v1/machines", json({ ...MACHINE, host: "hetzner" }));
  const [small] = await nc.Machine.sizes();
  assert.equal(sizes.last.query.has("region") || sizes.last.query.has("include_dominated"), false);
  assert.deepEqual([small.available, small.region, small.host, small.diskGb, small.monthlyUsd, small.dominatedBy], [true, "eu", "hetzner", 40, 8.39, null]);
  assert.deepEqual(small.regions[1], { region: "us-east", host: "digitalocean", diskGb: 80, monthlyUsd: 31.2, dominatedBy: null });
  // Bought exactly as offered: its region, host and price pinned.
  await nc.Machine.create("support-box", { size: small.name, region: small.region!, host: small.host!, maxMonthlyUsd: small.monthlyUsd });
  assert.deepEqual(create.last.body, { name: "support-box", size: "small", region: "eu", max_monthly_usd: 8.39, host: "hetzner" });
  await nc.Machine.sizes({ region: "us-east" });
  assert.equal(sizes.last.query.get("region"), "us-east");
});

test("machines: sizes can include what another size beats and what can't be bought", async () => {
  const { api } = setup();
  const sizes = api.on("GET", "/v1/machines/sizes", json(listing([
    {
      object: "machine_size", name: "medium", cpu: 4, memory_gb: 8, working_conversations: 4, available: true, region: "eu",
      host: "digitalocean", disk_gb: 160, monthly_usd: 62.4, dominated_by: "large",
      regions: [{ region: "eu", host: "digitalocean", disk_gb: 160, monthly_usd: 62.4, dominated_by: "large" }], hosts: [],
    },
    {
      object: "machine_size", name: "xlarge", cpu: 16, memory_gb: 32, working_conversations: 16, available: false, region: "eu",
      host: null, disk_gb: 320, monthly_usd: 42.59, dominated_by: null, regions: [], hosts: [],
    },
  ])));
  const [medium, xlarge] = await nc.Machine.sizes({ region: "eu", includeDominated: true });
  assert.equal(sizes.last.query.get("include_dominated"), "true");
  assert.deepEqual([medium.available, medium.monthlyUsd, medium.dominatedBy], [true, 62.4, "large"]);
  assert.deepEqual(medium.regions, [{ region: "eu", host: "digitalocean", diskGb: 160, monthlyUsd: 62.4, dominatedBy: "large" }]);
  assert.deepEqual([xlarge.available, xlarge.host, xlarge.regions], [false, null, []]);
});

test("machines: fromName holds a machine's host fixed", async () => {
  const { api } = setup();
  api.on("GET", "/v1/machines", json(listing([{ ...MACHINE, host: "hetzner" }])));
  const box = nc.Machine.fromName("support-box", { createIfMissing: true, host: "digitalocean", maxMonthlyUsd: 120 });
  await assert.rejects(box.hydrate(), nc.Conflict);
});

test("machines: sizes, create, exec, ports, agents and lifecycle (designed)", async () => {
  const { api } = setup();
  const sizes = api.on("GET", "/v1/machines/sizes", json(listing([
    { object: "machine_size", name: "small", cpu: 2, memory_gb: 4, disk_gb: 80, monthly_usd: 39, working_conversations: 2 },
  ])));
  const create = api.on("POST", "/v1/machines", json(MACHINE));
  const path = `/v1/machines/${MACHINE_ID}`;
  api.on("GET", path, json(MACHINE));
  const exec = api.on("POST", `${path}/exec`, json({ stdout: "ok\n", stderr: "", exit_code: 0 }),
    json(operation({ id: "op_x", kind: "machine.exec", status: "running" }), { status: 202 }));
  const expose = api.on("POST", `${path}/ports`, json({ port: 3000, url: "https://m-3000.example", public: true }));
  const close = api.on("DELETE", `${path}/ports/3000`, json({}));
  api.on("GET", `${path}/agents`, json(listing([{ ...AGENT, machine_id: MACHINE_ID }])));
  const restart = api.on("POST", `${path}/restart`, json(operation({ id: "op_r", kind: "machine.restart", status: "running" })));
  const update = api.on("PATCH", path, json({ ...MACHINE, size: "large" }));
  const remove = api.on("DELETE", path, json({}));

  const [small] = await nc.Machine.sizes();
  assert.deepEqual([small.name, small.cpu, small.monthlyUsd, small.workingConversations], ["small", 2, 39, 2]);
  assert.equal(sizes.last.headers.get("NoClick-User"), null);

  const box = await nc.Machine.create("support-box", { size: "medium", region: "eu", maxMonthlyUsd: 120 });
  assert.deepEqual(create.last.body, { name: "support-box", size: "medium", region: "eu", max_monthly_usd: 120 });
  assert.deepEqual([box.status, box.region, box.monthlyUsd, box.ports[0].url], ["running", "eu", 78, "https://m-8080.example"]);
  assert.deepEqual([box.network, box.statusReason], [true, null]);
  await nc.Machine.create("locked-box", { maxMonthlyUsd: 60, network: ["pypi.org"] });
  assert.deepEqual(create.last.body, { name: "locked-box", size: "small", network: ["pypi.org"], max_monthly_usd: 60 });

  assert.equal((await box.exec("df -h")).stdout, "ok\n");
  const background = await box.exec("tar czf x.tgz /home", { background: true, timeoutS: 1800 });
  assert.equal(background.kind, "machine.exec");
  assert.deepEqual(exec.last.body, { command: "tar czf x.tgz /home", background: true, timeout_s: 1800 });
  const port = await box.expose(3000, { public: true });
  assert.deepEqual([port.url, port.public, expose.last.body], ["https://m-3000.example", true, { port: 3000, public: true }]);
  await box.closePort(3000);
  assert.equal(close.count, 1);
  assert.equal((await box.agents())[0].machine_id, MACHINE_ID);
  assert.equal((await box.restart()).kind, "machine.restart");
  assert.equal(restart.count, 1);
  await box.update({ size: "large", maxMonthlyUsd: 240 });
  assert.deepEqual(update.last.body, { size: "large", max_monthly_usd: 240 });
  await box.update({ network: ["pypi.org"] });
  assert.deepEqual(update.last.body, { network: ["pypi.org"] });
  await box.delete();
  assert.equal(remove.count, 1);

  assert.throws(() => nc.Machine.fromName("support-box", { createIfMissing: true }), TypeError);
});

test("machines: a page reads its month, who works and how hard; its folders list and its shell opens", async () => {
  const { api } = setup();
  const path = `/v1/machines/${MACHINE_ID}`;
  api.on("GET", path, json({
    ...MACHINE, spent_usd_this_month: 16.64, started_at: "2026-11-04T09:00:00Z", working_count: 1,
    agent_states: [{ agent_id: "ag_1", working: true }],
    health: { cpus: 4, load_1m: 1.2, cpu_percent: 30, memory_used_gb: 2.6, memory_total_gb: 8, disk_used_gb: 31, disk_total_gb: 160 },
    pending: { size: "large", move: false },
  }));
  const listed = api.on("GET", `${path}/files`,
    json({ object: "list", path: "/home/noclick", next_cursor: "/home/noclick/apps",
      data: [{ object: "machine_entry", path: "/home/noclick/apps", type: "directory", size: null, updated_at: null }] }),
    json({ object: "list", path: "/home/noclick", next_cursor: null,
      data: [{ object: "machine_entry", path: "/home/noclick/notes.txt", type: "file", size: 98, updated_at: "2026-11-16T10:00:00Z" }] }));
  api.on("POST", `${path}/shell`, json({
    object: "machine_shell", machine_id: MACHINE_ID, url: "wss://api.noclick.test/v1/terminals/attach", token: "tok_1",
    token_expires_at: "2026-11-16T10:02:00Z", idle_limit_s: 900,
  }));
  const box = await nc.Machine.get(MACHINE_ID);
  assert.deepEqual([box.spentUsdThisMonth, box.workingCount, box.pending], [16.64, 1, { size: "large", move: false }]);
  assert.deepEqual(box.agentStates, [{ agentId: "ag_1", working: true }]);
  assert.deepEqual([box.health?.cpuPercent, box.health?.diskTotalGb, box.startedAt?.getUTCDate()], [30, 160, 4]);
  const entries = await box.files.list();
  assert.deepEqual(entries.map((e) => [e.path, e.type, e.size]), [["/home/noclick/apps", "directory", null], ["/home/noclick/notes.txt", "file", 98]]);
  assert.equal(listed.last.query.get("cursor"), "/home/noclick/apps");
  const shell = await box.shell();
  assert.deepEqual([shell.token, shell.idleLimitS], ["tok_1", 900]);
});

test("an agent runs on a machine (designed)", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/agents", json({ ...AGENT, machine_id: MACHINE_ID }));
  const update = api.on("PATCH", "/v1/agents/ag_1", json({ ...AGENT, machine_id: null }));
  const box = nc.Machine.fromId(MACHINE_ID);
  const agent = await nc.Agent.create("support", { instructions: "hi", harness: "claude_code", modelConnection: "claude", machine: box });
  assert.equal((create.last.body as Record<string, unknown>).machine_id, MACHINE_ID);
  assert.equal(agent.machineId, MACHINE_ID);
  await agent.update({ machine: null });
  assert.deepEqual(update.last.body, { machine_id: null });
  await nc.asUser("user_42", () => nc.Agent.create("mine", { instructions: "hi", machine: MACHINE_ID }));
  assert.equal(create.last.headers.get("NoClick-User"), USER_ID);
});

const OWN_ID = "7c1d9a20-2b6f-4e0a-9d51-3f8e6a4b2c10";
const CODE = "nc_mach_4Hq9xY";
const PAIRING = {
  code: CODE, command: `curl -fsSL https://noclick.com/machine.sh | sudo sh -s -- --code ${CODE}`,
  commands: {
    linux: `curl -fsSL https://noclick.com/machine.sh | sudo sh -s -- --code ${CODE}`,
    mac: `curl -fsSL https://noclick.com/machine.sh | sh -s -- --code ${CODE}`,
    linux_unattended: `curl -fsSL https://noclick.com/machine.sh | sudo sh -s -- --code ${CODE} --yes`,
    mac_unattended: `curl -fsSL https://noclick.com/machine.sh | sh -s -- --code ${CODE} --yes`,
  },
  expires_at: "2026-11-10T14:32:00Z", installing_on: null, refused: null,
};
const REFUSED = {
  system: "Darwin", arch: "x86_64", hostname: "imac", at: "2026-11-10T14:12:03Z", next_step: "Run the command on a Linux server ...",
  message: "This is macOS on x86_64: NoClick runs agents on Linux servers on x86-64 or ARM64, and Macs with Apple silicon.",
};
const OWN = {
  ...MACHINE, id: OWN_ID, kind: "own", name: "machine-3f2a1c", size: null, cpu: null, memory_gb: null, disk_gb: null,
  os: null, hostname: null, status: "provisioning", monthly_usd: 0, max_monthly_usd: null, ports: [], agent_count: 0,
  image: null, last_seen_at: null, max_conversations: null, conversations_at_once: null, agent_share: 0.75,
  agent_share_fixed: false, pairing: PAIRING, docker: true, app_testing: "ask_first", workspaces: "local",
};

test("your own machine: added with a code, set up on the server, then online or offline", async () => {
  const { api } = setup();
  const add = api.on("POST", "/v1/machines/own", json(OWN));
  const path = `/v1/machines/${OWN_ID}`;
  const fresh = { ...PAIRING, code: "nc_mach_newer", command: "curl ... --code nc_mach_newer" };
  const renew = api.on("POST", `${path}/pairing_code`, json({ ...OWN, pairing: fresh }));
  const online = {
    ...OWN, name: "office-mini", status: "running", cpu: 8, memory_gb: 32, disk_gb: 450, os: "Ubuntu 24.04.1 LTS",
    hostname: "office-mini", last_seen_at: "2026-11-10T14:02:00Z", conversations_at_once: 6, pairing: null,
  };
  const update = api.on("PATCH", path, json({ ...online, max_conversations: 2, conversations_at_once: 2 }));
  const list = api.on("GET", "/v1/machines", json(listing([online])));

  const home = await nc.asUser("user_42", () => nc.Machine.addOwn());
  assert.deepEqual(add.last.body, {});
  assert.equal(add.last.headers.get("NoClick-User"), null);
  assert.deepEqual([home.kind, home.status, home.size, home.monthlyUsd, home.maxMonthlyUsd],
    ["own", "provisioning", null, 0, null]);
  assert.deepEqual([home.pairing?.code, home.pairing?.command, home.pairing?.installingOn],
    [CODE, PAIRING.command, null]);
  assert.equal(home.pairing?.expiresAt?.toISOString(), "2026-11-10T14:32:00.000Z");
  // A Mac's form runs as its person: no sudo. Each again with --yes, to run unattended.
  assert.deepEqual(home.pairing?.commands, {
    linux: PAIRING.commands.linux, mac: PAIRING.commands.mac,
    linuxUnattended: PAIRING.commands.linux_unattended, macUnattended: PAIRING.commands.mac_unattended,
  });
  assert.equal(home.pairing?.refused, null);
  await nc.Machine.addOwn({ name: "build-box", maxConversations: 3, agentShare: 1, docker: true });
  assert.deepEqual(add.last.body, { name: "build-box", max_conversations: 3, agent_share: 1, docker: true });
  assert.deepEqual([home.agentShare, home.agentShareFixed, home.docker, home.appTesting], [0.75, false, true, "ask_first"]);
  await nc.Machine.addOwn({ appTesting: "never" });
  assert.deepEqual(add.last.body, { app_testing: "never" });
  assert.equal(home.workspaces, "local");
  await nc.Machine.addOwn({ workspaces: "saved" });
  assert.deepEqual(add.last.body, { workspaces: "saved" });

  await home.newPairingCode();
  assert.equal(renew.count, 1);
  assert.equal(home.pairing?.code, "nc_mach_newer");

  const [box] = await nc.Machine.list({ kind: "own" });
  assert.equal(list.last.query.get("kind"), "own");
  assert.deepEqual([box.status, box.os, box.hostname, box.cpu, box.memoryGb, box.conversationsAtOnce, box.pairing],
    ["running", "Ubuntu 24.04.1 LTS", "office-mini", 8, 32, 6, null]);
  assert.equal(box.lastSeenAt?.toISOString(), "2026-11-10T14:02:00.000Z");
  await nc.Machine.list();
  assert.equal(list.last.query.get("kind"), null);

  await box.update({ maxConversations: 2 });
  assert.deepEqual(update.last.body, { max_conversations: 2 });
  assert.deepEqual([box.maxConversations, box.conversationsAtOnce], [2, 2]);
  await box.update({ maxConversations: null });
  assert.deepEqual(update.last.body, { max_conversations: null });
  await box.update({ agentShare: 0.5 });
  assert.deepEqual(update.last.body, { agent_share: 0.5 });
  await box.update({ docker: true });
  assert.deepEqual(update.last.body, { docker: true });
  await box.update({ appTesting: "by_itself" });
  assert.deepEqual(update.last.body, { app_testing: "by_itself" });
  await box.update({ workspaces: "saved" });
  assert.deepEqual(update.last.body, { workspaces: "saved" });
});

test("whether agents run on machines here: the list says so, and each machine", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/machines", json({ ...listing([{ ...MACHINE, agents_enabled: false }]), agents_enabled: false }));
  assert.equal(await nc.Machine.agentsEnabledHere(), false);
  assert.equal(route.last.query.get("limit"), "1");
  assert.equal(route.last.headers.get("NoClick-User"), null);
  const [box] = await nc.Machine.list();
  assert.equal(box.agentsEnabled, false);
});

test("a box turned away reads on the machine's pairing", async () => {
  const { api } = setup();
  api.on("GET", `/v1/machines/${OWN_ID}`, json({ ...OWN, pairing: { ...PAIRING, code: null, command: null, refused: REFUSED } }));
  const refused = (await nc.Machine.get(OWN_ID)).pairing?.refused;
  assert.deepEqual([refused?.system, refused?.arch, refused?.hostname, refused?.message, refused?.nextStep],
    ["Darwin", "x86_64", "imac", REFUSED.message, REFUSED.next_step]);
  assert.equal(refused?.at?.toISOString(), "2026-11-10T14:12:03.000Z");
});
