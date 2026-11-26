// An agent for some apps (Agent.forApps), as NoClick's agents pages set one up, against the mock API: what it sends,
// for the account itself, and the agent, its channel and what it still needs read back.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

test("an agent for apps is made for the account, with what it still needs", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/agents/for_apps", json({
    object: "agent_for_apps", created: true,
    agent: { id: "agt_1", name: "Roblox agent", harness: "hermes", model: "openrouter/~openai/gpt-luna-latest", model_connection: "roblox-agent-model" },
    channel: { id: "ch_1", name: "roblox" },
    needs: [
      { kind: "app", integration: "roblox", node_type: "automation-roblox", label: "Roblox", description: "Manage Roblox experiences", connected: false },
      { kind: "model", connected: false },
    ],
  }));
  const made = await nc.Agent.forApps(["roblox"], { harness: "hermes" });
  assert.deepEqual(route.last.body, { apps: ["roblox"], harness: "hermes" });
  assert.equal(route.last.headers.get("noclick-user"), null);
  assert.deepEqual([made.agent.id, made.channel, made.created], ["agt_1", { id: "ch_1", name: "roblox" }, true]);
  assert.deepEqual(made.needs.map((n) => [n.kind, n.nodeType, n.connected]), [["app", "automation-roblox", false], ["model", null, false]]);
});
