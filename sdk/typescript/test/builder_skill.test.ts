// The skills NoClick's builder loads (`BuilderSkill`): the account's, never a user's, so none sends `NoClick-User`
// inside `asUser`.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";

const VOICE = {
  object: "builder_skill", id: "6c1f0e9a-0000-4000-8000-0000000000a1", name: "Brand voice", description: "How we write.",
  scope: "owned", owner_id: "u_ada", enabled: true, muted: false, has_text: true, has_workflow: false,
  created_at: "2026-11-14T09:00:00+00:00", updated_at: "2026-11-14T09:00:00+00:00",
};
const TONE = { ...VOICE, id: "6c1f0e9a-0000-4000-8000-0000000000a2", name: "Support tone", scope: "shared", owner_id: "u_priya" };

test("BuilderSkill.list reads the account's own and those shared with it, as the account", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/builder_skills", json({ object: "list", data: [VOICE, TONE] }));
  const skills = await nc.asUser("user_42", () => nc.BuilderSkill.list());
  assert.deepEqual(skills.map((s) => [s.name, s.scope, s.enabled, s.muted, s.hasText]), [
    ["Brand voice", "owned", true, false, true],
    ["Support tone", "shared", true, false, true],
  ]);
  assert.equal(skills[0].bodyText, null);
  assert.equal(read.last.headers.get("NoClick-User"), null);
});

test("BuilderSkill.create sends what it says, and get reads it whole", async () => {
  const { api } = setup();
  const made = api.on("POST", "/v1/builder_skills", json({ ...VOICE, body_text: "Short sentences.", body_workflow: null }, { status: 201 }));
  const read = api.on("GET", `/v1/builder_skills/${VOICE.id}`, json({ ...VOICE, body_text: "Short sentences.", body_workflow: { nodes: [] } }));
  const skill = await nc.BuilderSkill.create({ name: "Brand voice", description: "How we write.", bodyText: "Short sentences." });
  assert.deepEqual(made.last.body, { name: "Brand voice", description: "How we write.", body_text: "Short sentences." });
  assert.equal(skill.bodyText, "Short sentences.");
  const whole = await nc.BuilderSkill.get(VOICE.id);
  assert.deepEqual(whole.bodyWorkflow, { nodes: [] });
  assert.equal(read.calls.length, 1);
});

test("update sends only what changes, and a mute is the account's own", async () => {
  const { api } = setup();
  api.on("GET", "/v1/builder_skills", json({ object: "list", data: [VOICE, TONE] }));
  const patch = api.on("PATCH", `/v1/builder_skills/${TONE.id}`, json({ ...TONE, muted: true }));
  const [, tone] = await nc.BuilderSkill.list();
  const muted = await tone.update({ muted: true });
  assert.deepEqual(patch.last.body, { muted: true });
  assert.equal(muted.muted, true);
});

test("changing one shared to read rejects with PermissionDenied, and delete names it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/builder_skills", json({ object: "list", data: [VOICE, TONE] }));
  api.on("PATCH", `/v1/builder_skills/${TONE.id}`, apiError(403, "permission_denied", "shared with the account to read"));
  const removed = api.on("DELETE", `/v1/builder_skills/${VOICE.id}`, json({ object: "builder_skill", id: VOICE.id, deleted: true }));
  const [voice, tone] = await nc.BuilderSkill.list();
  await assert.rejects(tone.update({ enabled: false }), nc.PermissionDenied);
  await voice.delete();
  assert.equal(removed.calls.length, 1);
});
