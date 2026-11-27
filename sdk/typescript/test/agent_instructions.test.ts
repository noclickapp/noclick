// An agent's instructions and their versions (parity with the Python client, tests/test_agent_instructions.py):
// `instructionsHistory()` read with each version's diff and who made it, and a change made on what was read, refused
// with a `Conflict` carrying them as they are now when they changed since.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "writer", model: "openrouter/x", harness: "sdk", instructions: "Write posts.\nNo emoji.",
  tools: [], user_id: null, workflow_id: "wf_1", created_at: "2026-11-20T10:00:00Z",
};
const HISTORY = {
  object: "agent_instructions", agent_id: "ag_1", instructions: "Write posts.\nNo emoji.", digest: "d".repeat(64),
  kept_days: 90,
  versions: [
    { version: 42, instructions: "Write posts.\nNo emoji.", diff: "@@ -1,2 +1,2 @@\n Write posts.\n-One emoji.\n+No emoji.",
      added: 1, removed: 1, source: "coordinator", author: { user_id: "usr_1", key_id: "key_grant" },
      said: "Drop the emoji.", restored_from: null, changed_at: "2026-11-27T09:00:00Z" },
    { version: 40, instructions: "Write posts.\nOne emoji.", diff: null, added: 0, removed: 0, source: "baseline",
      author: null, said: null, restored_from: null, changed_at: "2026-11-20T10:00:00Z" },
  ],
};

test("instructionsHistory reads each version with what it changed and who made it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const read = api.on("GET", "/v1/agents/ag_1/instructions", json(HISTORY));
  const history = await nc.Agent.fromId("ag_1").instructionsHistory({ limit: 5 });
  assert.equal(read.last.query.get("limit"), "5");
  assert.deepEqual([history.instructions, history.digest, history.keptDays], [HISTORY.instructions, "d".repeat(64), 90]);
  const [noclicks, first] = history.versions;
  assert.deepEqual(
    [noclicks.version, noclicks.source, noclicks.said, noclicks.added, noclicks.removed, noclicks.author],
    [42, "coordinator", "Drop the emoji.", 1, 1, { userId: "usr_1", keyId: "key_grant" }],
  );
  assert.equal(noclicks.changedAt?.toISOString(), "2026-11-27T09:00:00.000Z");
  assert.deepEqual([first.source, first.diff, first.author], ["baseline", null, null]);
});

test("a change names what it was made on, and one made on stale instructions is a Conflict", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({
    error: { type: "conflict", message: "Its instructions changed since this change was started from them.",
             field: "instructions", instructions: "Write posts.\nNo emoji.", digest: "e".repeat(64) },
  }, { status: 409 }));
  const writer = nc.Agent.fromId("ag_1");
  const refused = await writer.update({ instructions: "Write posts.\nTwo emoji.", ifInstructions: "d".repeat(64) }).catch((e) => e);
  assert.deepEqual(patch.last.body, { instructions: "Write posts.\nTwo emoji.", if_instructions: "d".repeat(64) });
  assert.ok(refused instanceof nc.Conflict);
  assert.deepEqual([refused.details.instructions, refused.details.digest], ["Write posts.\nNo emoji.", "e".repeat(64)]);
});
