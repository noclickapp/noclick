// `fromName` gets (or creates), then sets the fields it's given; an argument it can't set on an existing object is
// checked, never ignored. `create(..., { allowExisting: true })` makes an object once and leaves it alone.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, setup, userRow } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, parent_id: "ag_parent", ttl_s: null, created_at: "2026-09-25T10:00:00Z",
};

type JsonRow = Record<string, unknown>;

const taken = (existingId = "x_1") => apiError(409, "conflict", "It already exists.", { existing_id: existingId });

/** The `Conflict` naming `field` and the value the object has. */
const naming = (field: string, value: unknown) => (err: unknown) =>
  err instanceof nc.Conflict && err.details.field === field && JSON.stringify(err.details[field]) === JSON.stringify(value);

// --- fields fromName can't set -------------------------------------------------------

test("an agent's ttlS and parent are checked, never ignored", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([AGENT])));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json(AGENT));
  await assert.rejects(nc.Agent.fromName("support", { createIfMissing: true, instructions: "new", ttlS: 3600 }).hydrate(), naming("ttl_s", null));
  await assert.rejects(
    nc.Agent.fromName("support", { createIfMissing: true, instructions: "new", parent: "ag_other" }).hydrate(),
    (err: nc.Conflict) => naming("parent_id", "ag_parent")(err) && err.existingId === "ag_1" && /parent_id/.test(err.message),
  );
  assert.equal(patch.count, 0);
  // Given as the agent has them, they pass, and the fields fromName can set are set.
  await nc.Agent.fromName("support", { createIfMissing: true, instructions: "new", parent: "ag_parent" }).hydrate();
  assert.deepEqual(patch.last.body, { instructions: "new" });
});

test("a machine's region is checked and its ceiling set", async () => {
  const { api } = setup();
  const machine = { object: "machine", id: "m_1", name: "box", size: "small", region: "eu", max_monthly_usd: 120, network: true, volumes: {} };
  api.on("GET", "/v1/machines", json(listing([machine])));
  const patch = api.on("PATCH", "/v1/machines/m_1", json(machine));
  await assert.rejects(nc.Machine.fromName("box", { createIfMissing: true, region: "us-east", maxMonthlyUsd: 120 }).hydrate(), naming("region", "eu"));
  assert.equal(patch.count, 0);
  // Its own region passes; the ceiling it's given is the one the new size is judged against, set with it.
  await nc.Machine.fromName("box", { createIfMissing: true, region: "eu", size: "medium", maxMonthlyUsd: 150 }).hydrate();
  assert.deepEqual(patch.last.body, { size: "medium", max_monthly_usd: 150 });
  await nc.Machine.fromName("box", { createIfMissing: true, size: "medium", maxMonthlyUsd: 120 }).hydrate();
  assert.deepEqual(patch.last.body, { size: "medium" });
});

test("an inbox's address is checked", async () => {
  const { api } = setup();
  const inbox = { object: "inbox", id: "inb_1", name: "support", address: "help@mail.acme.test", agent_id: null, senders: "anyone" };
  api.on("GET", "/v1/inboxes", json(listing([inbox])));
  const patch = api.on("PATCH", "/v1/inboxes/inb_1", json(inbox));
  await assert.rejects(nc.Inbox.fromName("support", { createIfMissing: true, localPart: "sales" }).hydrate(), naming("local_part", "help"));
  await assert.rejects(
    nc.Inbox.fromName("support", { createIfMissing: true, localPart: "help", domain: "acme.test" }).hydrate(),
    naming("domain", "mail.acme.test"),
  );
  await nc.Inbox.fromName("support", { createIfMissing: true, localPart: "Help", domain: "mail.acme.test", senders: "users" }).hydrate();
  assert.deepEqual(patch.last.body, { senders: "users" });
});

test("a connected number is checked against connect", async () => {
  const { api } = setup();
  const number = { object: "phone_number", id: "pn_2", name: "front-desk", number: "+14155550123", source: "connected", record_calls: false };
  api.on("GET", "/v1/phone_numbers", json(listing([number])));
  await assert.rejects(
    nc.PhoneNumber.fromName("front-desk", { createIfMissing: true, connect: "+14155550199", connection: "phone-provider" }).hydrate(),
    naming("number", "+14155550123"),
  );
  const found = await nc.PhoneNumber.fromName("front-desk", { createIfMissing: true, connect: "+1 (415) 555-0123", connection: "phone-provider" }).hydrate();
  assert.equal(found.id, "pn_2");
});

test("a connection's integration and credential type are checks", async () => {
  const { api } = setup();
  api.on("GET", "/v1/connections/claude", json({
    object: "connection", id: "con_1", name: "claude", integration: "anthropic", credential_type: "agent_anthropic_api_key", user_id: null,
  }));
  await assert.rejects(nc.Connection.fromName("claude", { integration: "openai" }).hydrate(), naming("integration", "anthropic"));
  await assert.rejects(
    nc.Connection.fromName("claude", { integration: "anthropic", credentialType: "agent_claude_code_oauth" }).hydrate(),
    naming("credential_type", "agent_anthropic_api_key"),
  );
  assert.equal((await nc.Connection.fromName("claude", { integration: "anthropic" }).hydrate()).id, "con_1");
});

// --- fields without createIfMissing ----------------------------------------------------

const URL_ = "https://api.yourco.test/noclick/events";
type Lazy = { hydrate(): Promise<unknown> };
// kind -> [the existing object, fromName with one field and no createIfMissing, the PATCH it sends]
const SETS: Record<string, [JsonRow, () => Lazy, JsonRow]> = {
  agents: [{ ...AGENT, id: "x_1" }, () => nc.Agent.fromName("support", { instructions: "new" }), { instructions: "new" }],
  cards: [{ id: "x_1", name: "Travel", status: "active", limit_usd: 100, interval: "day" },
    () => nc.Card.fromName("Travel", { limitUsd: 200 }), { limit_usd: 200 }],
  channels: [{ id: "x_1", name: "billing", status: "open", members: [] },
    () => nc.Channel.fromName("billing", { topic: "Billing questions" }), { topic: "Billing questions" }],
  machines: [{ id: "x_1", name: "box", size: "small", region: "eu", max_monthly_usd: 120 },
    () => nc.Machine.fromName("box", { maxMonthlyUsd: 150 }), { max_monthly_usd: 150 }],
  mcp_servers: [{ id: "x_1", name: "crm-tools", tools: ["search"] },
    () => nc.McpServer.fromName("crm-tools", { tools: ["search", "fetch"] }), { tools: ["search", "fetch"] }],
  domains: [{ id: "x_1", name: "acme.test", auto_renew: false },
    () => nc.Domain.fromName("acme.test", { autoRenew: true }), { auto_renew: true }],
  phone_numbers: [{ id: "x_1", name: "front-desk", number: "+14155550123", record_calls: false },
    () => nc.PhoneNumber.fromName("front-desk", { recordCalls: true }), { record_calls: true }],
  inboxes: [{ id: "x_1", name: "support", address: "help@noclick.email", senders: "anyone" },
    () => nc.Inbox.fromName("support", { senders: "users" }), { senders: "users" }],
  projects: [{ id: "x_1", name: "booking", deploy_on_push: "off" },
    () => nc.Project.fromName("booking", { deployOnPush: "production" }), { deploy_on_push: "production" }],
  secrets: [{ id: "x_1", name: "shipping", user_id: null, keys: ["API_KEY"] },
    () => nc.Secret.fromName("shipping", { values: { API_KEY: "new" } }), { values: { API_KEY: "new" } }],
  webhooks: [{ id: "x_1", url: URL_, events: ["operation.*"], user_id: null },
    () => nc.Webhook.fromName(URL_, { events: ["human.answered"] }), { events: ["human.answered"] }],
  workspaces: [{ id: "x_1", name: "Acme", status: "active", budget_usd_per_month: null, members: [] },
    () => nc.Workspace.fromName("Acme", { budgetUsdPerMonth: 50 }), { budget_usd_per_month: 50 }],
  queues: [{ id: "x_1", name: "jobs", max_attempts: 5 }, () => nc.Queue.fromName("jobs", { maxAttempts: 8 }), { max_attempts: 8 }],
};

test("fields without createIfMissing are set on the one that exists, and a missing one is NotFound", async () => {
  for (const kind of Object.keys(SETS).sort()) {
    const { api } = setup();
    const [row, lazy, sent] = SETS[kind];
    const read = api.on("GET", `/v1/${kind}`, json(listing([row])), json(listing([])));
    const patch = api.on("PATCH", `/v1/${kind}/x_1`, json(row));
    const create = api.on("POST", `/v1/${kind}`, json(row));
    await lazy().hydrate();
    assert.deepEqual(patch.last.body, sent, kind);
    await assert.rejects(lazy().hydrate(), nc.NotFound, kind);
    assert.deepEqual([read.count, patch.count, create.count], [2, 1, 0], kind);
  }
});

test("a user's fields without createIfMissing are set", async () => {
  const { api } = setup();
  const found = api.on("GET", `/v1/users/${USER_ID}`, json(userRow()), apiError(404, "not_found", "No"));
  const patch = api.on("PATCH", `/v1/users/${USER_ID}`, json(userRow({ name: "Ana" })));
  const create = api.on("POST", "/v1/users", json(userRow()));
  await nc.User.fromId(USER_ID, { name: "Ana" }).hydrate();
  assert.deepEqual(patch.last.body, { name: "Ana" });
  await assert.rejects(nc.User.fromId(USER_ID, { name: "Ana" }).hydrate(), nc.NotFound);
  assert.deepEqual([found.count, create.count], [2, 0]);
});

test("a bare fromName sets nothing", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([AGENT])));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json(AGENT));
  assert.equal((await nc.Agent.fromName("support").hydrate()).id, "ag_1");
  assert.equal(patch.count, 0);
});

test("fields it can't set are checked without createIfMissing too", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([AGENT])));
  await assert.rejects(nc.Agent.fromName("support", { ttlS: 60 }).hydrate(), naming("ttl_s", null));
  api.on("GET", "/v1/inboxes", json(listing([{ id: "inb_1", name: "support", address: "help@noclick.email" }])));
  await assert.rejects(nc.Inbox.fromName("support", { localPart: "sales" }).hydrate(), naming("local_part", "help"));
  api.on("GET", "/v1/phone_numbers", json(listing([{ id: "pn_1", name: "front-desk", number: "+14155550123" }])));
  await assert.rejects(nc.PhoneNumber.fromName("front-desk", { connect: "+14155550199" }).hydrate(), naming("number", "+14155550123"));
});

// --- create(..., { allowExisting: true }) ----------------------------------------------

test("Agent.create with allowExisting returns the agent untouched", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/agents", taken("ag_1"));
  const found = api.on("GET", "/v1/agents/ag_1", json({ ...AGENT, instructions: "edited in the app" }));
  await assert.rejects(nc.Agent.create("support", { instructions: "hi" }), nc.Conflict);
  assert.equal(found.count, 0);
  const agent = await nc.Agent.create("support", { instructions: "hi", allowExisting: true });
  assert.deepEqual([agent.id, agent.instructions, create.count, found.count], ["ag_1", "edited in the app", 2, 1]);
});

test("allowExisting keeps a conflict that isn't the name", async () => {
  const { api } = setup();
  api.on("POST", "/v1/agents", taken("ag_9"));
  api.on("GET", "/v1/agents/ag_9", json({ ...AGENT, id: "ag_9", name: "someone-else" }));
  await assert.rejects(nc.Agent.create("support", { instructions: "hi", allowExisting: true }), (err: nc.Conflict) => err.existingId === "ag_9");
  api.on("POST", "/v1/projects", taken("repo_1"));
  await assert.rejects(nc.Project.create("booking", { allowExisting: true }), (err: nc.Conflict) => err.existingId === "repo_1");
});

const ROWS: Record<string, Record<string, unknown>> = {
  cards: { object: "card", id: "x_1", name: "Travel", status: "active" },
  machines: { object: "machine", id: "x_1", name: "box", region: "eu" },
  mcp_servers: { object: "mcp_server", id: "x_1", name: "crm-tools", tools: [] },
  inboxes: { object: "inbox", id: "x_1", name: "support", address: "help@noclick.email" },
  projects: { object: "project", id: "x_1", name: "booking" },
  secrets: { object: "secret", id: "x_1", name: "shipping", keys: ["API_KEY"] },
  workspaces: { object: "workspace", id: "x_1", name: "Acme", members: [] },
  connections: { object: "connection", id: "x_1", name: "slack", integration: "slack" },
  buckets: { object: "bucket", id: "x_1", name: "uploads" },
  dicts: { object: "dict", id: "x_1", name: "seen" },
  queues: { object: "queue", id: "x_1", name: "jobs" },
  volumes: { object: "volume", id: "x_1", name: "data" },
  databases: { object: "database", id: "x_1", name: "orders", engine: "sqlite" },
  memories: { object: "memory", id: "x_1", name: "company" },
  repos: { object: "repo", id: "x_1", name: "site" },
  browser_profiles: { object: "browser_profile", id: "x_1", name: "ana-work" },
  channels: { object: "channel", id: "x_1", name: "billing", status: "open", members: [] },
};

type Made = { id: string; name: string | null };
const CREATES: Record<string, (allowExisting?: boolean) => Promise<Made>> = {
  cards: (allowExisting) => nc.Card.create("Travel", { limitUsd: 100, allowExisting }),
  machines: (allowExisting) => nc.Machine.create("box", { maxMonthlyUsd: 60, allowExisting }),
  mcp_servers: (allowExisting) => nc.McpServer.create("crm-tools", { tools: ["search"], allowExisting }),
  inboxes: (allowExisting) => nc.Inbox.create({ name: "support", localPart: "help", allowExisting }) as Promise<Made>,
  projects: (allowExisting) => nc.Project.create("booking", { repo: "repo_1", allowExisting }),
  secrets: (allowExisting) => nc.Secret.create("shipping", { values: { API_KEY: "new" }, allowExisting }),
  workspaces: (allowExisting) => nc.Workspace.create("Acme", { allowExisting }),
  connections: (allowExisting) => nc.Connection.create("slack", { integration: "slack", allowExisting }),
  buckets: (allowExisting) => nc.Bucket.create("uploads", { allowExisting }),
  dicts: (allowExisting) => nc.Dict.create("seen", { allowExisting }),
  queues: (allowExisting) => nc.Queue.create("jobs", { allowExisting }),
  volumes: (allowExisting) => nc.Volume.create("data", { allowExisting }),
  databases: (allowExisting) => nc.Database.create("orders", { allowExisting }),
  memories: (allowExisting) => nc.Memory.create("company", { allowExisting }),
  repos: (allowExisting) => nc.Repo.create("site", { allowExisting }),
  browser_profiles: (allowExisting) => nc.BrowserProfile.create("ana-work", { allowExisting }),
  channels: (allowExisting) => nc.Channel.create("billing", { workspace: "ws_1", allowExisting }) as Promise<Made>,
};

test("every named create takes allowExisting", async () => {
  for (const kind of Object.keys(CREATES).sort()) {
    const { api } = setup();
    const create = api.on("POST", `/v1/${kind}`, taken());
    const found = api.on("GET", `/v1/${kind}/x_1`, json(ROWS[kind]));
    await assert.rejects(CREATES[kind](), nc.Conflict, kind);
    const made = await CREATES[kind](true);
    assert.deepEqual([made.id, made.name], ["x_1", ROWS[kind].name], kind);
    assert.deepEqual([create.count, found.count], [2, 1], kind);
  }
});

test("User and Webhook creates find theirs by id and url", async () => {
  const { api } = setup();
  api.on("POST", "/v1/users", taken(USER_ID));
  const read = api.on("GET", `/v1/users/${USER_ID}`, json(userRow({ name: "Ana" })));
  const user = await nc.User.create(USER_ID, { name: "Bo", allowExisting: true });
  assert.deepEqual([user.name, read.count], ["Ana", 1]);

  const url = "https://api.yourco.test/noclick/events";
  api.on("POST", "/v1/webhooks", taken("wh_1"));
  api.on("GET", "/v1/webhooks/wh_1", json({ object: "webhook", id: "wh_1", url, events: ["operation.*"], user_id: null }));
  const hook = await nc.Webhook.create(url, { events: ["human.answered"], allowExisting: true });
  assert.deepEqual([hook.id, hook.events, hook.secret], ["wh_1", ["operation.*"], null]);
});

test("allowExisting says what it needs to find one", async () => {
  setup();
  await assert.rejects(nc.Channel.create("billing", { allowExisting: true }), /needs workspace/);
  await assert.rejects(nc.Inbox.create({ localPart: "help", allowExisting: true }), /needs name/);
});

test("a connection found by allowExisting is still its integration", async () => {
  const { api } = setup();
  api.on("POST", "/v1/connections", taken("con_1"));
  api.on("GET", "/v1/connections/con_1", json({ object: "connection", id: "con_1", name: "slack", integration: "discord", credential_type: "DiscordBot" }));
  await assert.rejects(nc.Connection.create("slack", { integration: "slack", allowExisting: true }), naming("integration", "discord"));
});
