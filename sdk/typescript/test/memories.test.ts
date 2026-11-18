// Memories as objects, and attaching them to agents: the routes, bodies and parsed results the
// TypeScript client sends and reads.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, setup, trashed } from "./helpers.ts";

const MEM_ID = "5d1c9a3e-7b2f-4e60-8a19-3c4d6e8f0b21";
const HOME_ID = "8e2f4a6c-1b3d-4f5e-9a7c-2d4f6b8e0a13";
const MEMORY = {
  object: "memory", id: MEM_ID, name: "company", description: "What every agent should know", agent_id: null,
  attached_to: [{ id: "ag_1", name: "support", writes: false }], entry_count: 2, user_id: null,
  created_at: "2026-10-19T10:00:00Z", updated_at: "2026-10-19T10:00:00Z",
};
const ENTRY = {
  object: "memory_entry", name: "tone", description: "How we write", content: "Warm.", version: 1, updated_by: "api",
  user_id: null, conversation: null, created_at: "2026-10-19T10:00:00Z", updated_at: "2026-10-19T10:00:00Z",
};
const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: null,
  created_at: "2026-10-19T10:00:00Z",
};

test("Memory.create, list, get and fromName", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/memories", json({ ...MEMORY, id: "m_2", name: "ada-notes", user_id: USER_ID }));
  api.on("GET", "/v1/memories", json(listing([MEMORY])), json(listing([])));
  api.on("GET", `/v1/memories/${MEM_ID}`, json(MEMORY));

  const notes = await nc.asUser("user_42", () => nc.Memory.create("ada-notes"));
  assert.deepEqual(create.last.body, { name: "ada-notes" });
  assert.equal(create.last.headers.get("NoClick-User"), "user_42");
  assert.equal(notes.userId, USER_ID);

  const [company] = await nc.Memory.list();
  assert.deepEqual([company.name, company.entryCount, company.agentId], ["company", 2, null]);
  assert.deepEqual(company.attachedTo, [{ id: "ag_1", name: "support", writes: false }]);
  assert.equal((await nc.Memory.get(MEM_ID)).description, "What every agent should know");

  // Missing, and made concurrently: the existing one is taken.
  api.on("POST", "/v1/memories", apiError(409, "conflict", "taken", { existing_id: MEM_ID }));
  assert.equal((await nc.Memory.fromName("company", { createIfMissing: true }).hydrate()).id, MEM_ID);
});

test("entries are read and written one layer at a time", async () => {
  const { api } = setup();
  api.on("GET", `/v1/memories/${MEM_ID}`, json(MEMORY));
  const listed = api.on("GET", `/v1/memories/${MEM_ID}/entries`, json(listing([{ ...ENTRY, content: null }])), json(listing([ENTRY])));
  api.on("GET", `/v1/memories/${MEM_ID}/entries/tone`, json(ENTRY));
  const save = api.on("PUT", `/v1/memories/${MEM_ID}/entries/tone`, json({ ...ENTRY, version: 2 }));
  const forget = api.on("DELETE", `/v1/memories/${MEM_ID}/entries/old%20pricing`, new Response(null, { status: 204 }));
  const company = nc.Memory.fromId(MEM_ID);

  const [entry] = await company.entries();
  assert.deepEqual([entry.name, entry.content], ["tone", null]);
  await company.search("tone", { user: "user_42" });
  assert.equal(listed.last.query.get("q"), "tone");
  assert.equal(listed.last.headers.get("NoClick-User"), "user_42"); // the user's layer of the account's
  assert.equal((await company.read("tone")).content, "Warm.");
  assert.equal((await company.save("tone", "Warm, brief.", { version: 1 })).version, 2);
  assert.deepEqual(save.last.body, { content: "Warm, brief.", version: 1 });
  await company.forget("old pricing", { version: 3 });
  assert.equal(forget.last.query.get("version"), "3");
});

test("an entry's versions read and restore in its layer", async () => {
  const { api } = setup();
  api.on("GET", `/v1/memories/${MEM_ID}`, json(MEMORY));
  const version = {
    object: "memory_entry_version", name: "tone", version: 1, current: false, description: "How we write",
    content: "Warm.", user_id: null, saved_at: "2026-10-19T10:00:00Z", written_by: { type: "api" },
  };
  const listed = api.on("GET", `/v1/memories/${MEM_ID}/entries/tone/versions`, json(listing([
    { ...version, version: 2, current: true, content: null }, { ...version, content: null }])));
  api.on("GET", `/v1/memories/${MEM_ID}/entries/tone/versions/1`, json(version));
  const restore = api.on("POST", `/v1/memories/${MEM_ID}/entries/tone/versions/1/restore`, json({ ...ENTRY, version: 3 }));
  const company = nc.Memory.fromId(MEM_ID);

  const versions = await company.versions("tone", { user: "user_42" });
  assert.deepEqual(versions.map((v) => [v.version, v.current]), [[2, true], [1, false]]);
  assert.equal(listed.last.headers.get("NoClick-User"), "user_42");
  assert.equal((await company.getVersion("tone", 1)).content, "Warm.");
  assert.deepEqual([(await company.restore("tone", 1)).version, restore.calls.length], [3, 1]);
});

test("update and delete to the trash", async () => {
  const { api } = setup();
  api.on("GET", `/v1/memories/${MEM_ID}`, json(MEMORY));
  const patch = api.on("PATCH", `/v1/memories/${MEM_ID}`, json({ ...MEMORY, name: "handbook" }));
  api.on("DELETE", `/v1/memories/${MEM_ID}`, json(trashed("memory", MEM_ID, "handbook")));
  const company = nc.Memory.fromId(MEM_ID);
  assert.equal((await company.update({ name: "handbook" })).name, "handbook");
  assert.deepEqual(patch.last.body, { name: "handbook" });
  assert.equal((await company.delete()).kind, "memory");
});

test("an agent attaches memories read-only or writable, and converges by id", async () => {
  const { api } = setup();
  api.on("GET", "/v1/memories", json(listing([MEMORY])));
  api.on("GET", "/v1/agents/ag_9", json({ ...AGENT, id: "ag_9", name: "sales", memory_id: HOME_ID, memories: [] }));
  const links = [{ id: MEM_ID, writes: true }, { id: HOME_ID, writes: false }];
  const create = api.on("POST", "/v1/agents", json({ ...AGENT, id: "ag_2", name: "closer", memory_id: "m_home", memories: links }));
  const sales = nc.Agent.fromId("ag_9");

  const closer = await nc.Agent.create("closer", { instructions: "hi", memories: [nc.Memory.fromName("company").writable(), sales.memory] });
  assert.deepEqual((create.last.body as Record<string, unknown>).memories, links);
  assert.deepEqual([closer.memories, closer.memoryId], [links, "m_home"]);

  const existing = { ...AGENT, memories: [{ id: MEM_ID, writes: false }] };
  api.on("GET", "/v1/agents", json(listing([existing])));
  api.on("GET", "/v1/agents/ag_1", json(existing));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({ ...existing, memories: [] }));
  await nc.Agent.fromName("support", { createIfMissing: true, instructions: "hi", memories: ["company"] }).hydrate();
  assert.equal(patch.count, 0); // the name resolved to the id it already had
  await nc.Agent.fromId("ag_1").update({ memories: [] });
  assert.deepEqual(patch.last.body, { memories: [] });
});
