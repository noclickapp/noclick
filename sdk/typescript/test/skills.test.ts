// Skills as objects, attached to agents, what a memory entry says of its writer, and what runs now: the routes,
// bodies and parsed results the TypeScript client sends and reads.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, listing, setup, trashed } from "./helpers.ts";

const SKILL_ID = "3a1c9a3e-7b2f-4e60-8a19-3c4d6e8f0b21";
const SKILL = {
  object: "skill", id: SKILL_ID, name: "pdf-forms", description: "Fill PDF forms.", always: false, version: 2,
  digest: "sha256:ab", file_count: 2, size: 120, attached_to: [{ id: "ag_1", name: "support", pin: 1 }], user_id: null,
  created_at: "2026-11-10T10:00:00Z", updated_at: "2026-11-10T11:00:00Z",
};
const VERSION = {
  object: "skill_version", skill_id: SKILL_ID, version: 1, digest: "sha256:aa", name: "pdf-forms",
  description: "Fill PDF forms.", always: false, files: [{ path: "SKILL.md", size: 60, sha256: "s1" }], size: 60,
  created_by: { type: "agent", agent_id: "ag_1", agent_name: "support" }, created_at: "2026-11-10T10:00:00Z",
};
const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: null,
  skills: [{ id: SKILL_ID, pin: 1 }], created_at: "2026-11-10T10:00:00Z",
};

test("Skill.create sends the folder, text as text and bytes as base64", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/skills", json(SKILL));
  const pdf = await nc.Skill.create({ "SKILL.md": "---\nname: pdf-forms\n---\n", "logo.png": new Uint8Array([137, 80]) });
  assert.deepEqual(create.last.body, { files: [
    { path: "SKILL.md", content: "---\nname: pdf-forms\n---\n", encoding: "utf-8" },
    { path: "logo.png", content: "iVA=", encoding: "base64" },
  ] });
  assert.deepEqual([pdf.name, pdf.version, pdf.fileCount, pdf.always], ["pdf-forms", 2, 2, false]);
  assert.deepEqual(pdf.attachedTo, [{ id: "ag_1", name: "support", pin: 1 }]);

  // A taken name: the skill already there, when allowed.
  api.on("POST", "/v1/skills", apiError(409, "conflict", "taken", { existing_id: SKILL_ID }));
  api.on("GET", `/v1/skills/${SKILL_ID}`, json(SKILL));
  assert.equal((await nc.Skill.create({ "SKILL.md": "x" }, { allowExisting: true })).id, SKILL_ID);
  await assert.rejects(nc.Skill.create({ "SKILL.md": "x" }), nc.Conflict);
});

test("versions are saved, read, listed and restored", async () => {
  const { api } = setup();
  api.on("GET", `/v1/skills/${SKILL_ID}`, json(SKILL));
  const save = api.on("POST", `/v1/skills/${SKILL_ID}/versions`, json({ ...SKILL, version: 3 }));
  const versions = api.on("GET", `/v1/skills/${SKILL_ID}/versions`, json(listing([VERSION])));
  api.on("GET", `/v1/skills/${SKILL_ID}/versions/1`, json(VERSION));
  const files = api.on("GET", `/v1/skills/${SKILL_ID}/files`,
    json({ object: "skill_file", path: "SKILL.md", version: 1, size: 60, sha256: "s1", content: "---", encoding: "utf-8" }),
    json(listing([{ object: "skill_file", path: "SKILL.md", size: 60, sha256: "s1" }])));
  const restore = api.on("POST", `/v1/skills/${SKILL_ID}/versions/1/restore`, json({ ...SKILL, version: 4 }));
  const patch = api.on("PATCH", `/v1/skills/${SKILL_ID}`, json({ ...SKILL, name: "pdf-filler", version: 5 }));
  const pdf = nc.Skill.fromId(SKILL_ID);

  assert.equal((await pdf.saveVersion({ "run.sh": "echo hi" }, { removed: ["old.md"], baseVersion: 2 })).version, 3);
  assert.deepEqual(save.last.body, { files: [{ path: "run.sh", content: "echo hi", encoding: "utf-8" }],
    removed: ["old.md"], base_version: 2 });
  const [first] = await pdf.versions();
  assert.equal(versions.calls.length, 1);
  assert.deepEqual([first.version, first.createdBy, first.files[0].path],
    [1, { type: "agent", agentId: "ag_1", agentName: "support" }, "SKILL.md"]);
  assert.equal((await pdf.getVersion(1)).digest, "sha256:aa");
  const read = await pdf.read("SKILL.md", { version: 1 });
  assert.deepEqual([read.content, read.encoding], ["---", "utf-8"]);
  assert.deepEqual([files.last.query.get("path"), files.last.query.get("version")], ["SKILL.md", "1"]);
  assert.deepEqual((await pdf.files()).map((f) => f.path), ["SKILL.md"]);
  assert.equal((await pdf.restore(1)).version, 4);
  assert.equal(restore.calls.length, 1);
  assert.equal((await pdf.update({ name: "pdf-filler" })).name, "pdf-filler");
  assert.deepEqual(patch.last.body, { name: "pdf-filler" });
});

test("an agent's skills: listed in its order, attached latest or pinned, and deleted to the trash", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/skills", json(listing([SKILL])));
  api.on("GET", `/v1/skills/${SKILL_ID}`, json(SKILL));
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const update = api.on("PATCH", "/v1/agents/ag_1", json(AGENT));
  api.on("DELETE", `/v1/skills/${SKILL_ID}`, json(trashed("skill", SKILL_ID, "pdf-forms")));

  const support = nc.Agent.fromId("ag_1");
  const [pdf] = await nc.Skill.list({ agent: support });
  assert.equal(listed.last.query.get("agent_id"), "ag_1");
  await support.update({ skills: [pdf.pinned(1), SKILL_ID] });
  assert.deepEqual(update.last.body, { skills: [{ id: SKILL_ID, pin: 1 }, { id: SKILL_ID, pin: null }] });
  assert.deepEqual(support.skills, [{ id: SKILL_ID, pin: 1 }]);
  assert.equal((await pdf.delete()).kind, "skill");
});

test("a memory entry says who wrote it, and Memory.list reads one agent's", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/memories", json(listing([])));
  api.on("GET", "/v1/memories/m_1/entries/tone", json({
    object: "memory_entry", name: "tone", description: "How we write", content: "Warm.", version: 1,
    updated_by: "agent", written_by: { type: "agent", agent_id: "ag_1", agent_name: "support", conversation: "owner" },
    user_id: null, conversation: null, created_at: null, updated_at: null,
  }));
  await nc.Memory.list({ agent: "ag_1" });
  assert.equal(listed.last.query.get("agent_id"), "ag_1");
  const entry = await nc.Memory.fromId("m_1").read("tone");
  assert.deepEqual(entry.writtenBy, { type: "agent", agentId: "ag_1", agentName: "support", conversation: "owner" });
});

test("compute lists what runs now", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/compute", json({ object: "list", usd_per_hour: 0.1, data: [{
    object: "compute", kind: "agent_sandbox", id: "nc-live-1", name: "support", status: "running", user_id: null,
    region: "us-east", cpu: 1, memory_gb: 2, started_at: "2026-11-10T10:00:00Z", usd_per_hour: 0.1, usd_per_month: null,
    spent_usd_today: 0.4, running: [{ agent_id: "ag_1", agent_name: "support", conversation: "owner", harness: "codex", state: "running" }],
  }], next_cursor: null }));
  const [item] = await nc.compute({ userFilter: nc.ALL_USERS });
  assert.equal(read.last.query.get("user_id"), "all");
  assert.deepEqual([item.kind, item.usdPerHour, item.spentUsdToday, item.running[0].conversation],
    ["agent_sandbox", 0.1, 0.4, "owner"]);
});
