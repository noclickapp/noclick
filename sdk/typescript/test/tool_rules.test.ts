// What an agent may do with each app it reaches: its `toolRules`, sent as given, kept in step by `fromName` and
// cleared with `{}`, and `toolAccess()` read app by app.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi",
  tools: ["everything"], tool_rules: {}, user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null,
  expires_at: null, budget_usd_per_month: null, created_at: "2026-09-25T10:00:00Z",
};
const RULES: nc.ToolRules = { "*": "off", "work-gmail": "allow", "work-gmail.send_email_message": "ask" };

test("create and update send the rules given; the agent reads them back", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/agents", json({ ...AGENT, tool_rules: RULES }));
  const agent = await nc.Agent.create("support", { instructions: "hi", toolRules: RULES });
  assert.deepEqual(create.last.body, { name: "support", instructions: "hi", tool_rules: RULES });
  assert.deepEqual(agent.toolRules, RULES);
  const patch = api.on("PATCH", "/v1/agents/ag_1", json(AGENT));
  await agent.update({ toolRules: {} });
  assert.deepEqual(patch.last.body, { tool_rules: {} });
  assert.deepEqual(agent.toolRules, {});
});

test("fromName sets rules that differ, and leaves the same ones alone", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents", json(listing([{ ...AGENT, tool_rules: RULES }])));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json(AGENT));
  await nc.Agent.fromName("support", { createIfMissing: true, instructions: "hi", toolRules: RULES }).hydrate();
  assert.equal(patch.count, 0);
  await nc.Agent.fromName("support", { createIfMissing: true, instructions: "hi", toolRules: { "*": "off" } }).hydrate();
  assert.deepEqual(patch.last.body, { tool_rules: { "*": "off" } });
});

test("toolAccess reads each app with its actions", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("GET", "/v1/agents/ag_1/tool_access", json({
    object: "agent_tool_access", agent_id: "ag_1", mode: "restricted", listed: false, rules: RULES,
    since: "2026-11-07T10:00:00Z",
    apps: [{
      key: "work-gmail", app: "work-gmail", kind: "connection", integration: "gmail", credential_type: "gmail_oauth",
      label: "Gmail", account: "ada@example.com", status: "connected", on: true, calls: 12,
      actions: [{ key: "work-gmail.send_email_message", action: "send_email_message", title: "Send Email Message",
                  group: "Message", kind: "send", verdict: "ask", can_ask: true, calls: 3 }],
    }, {
      key: null, app: "web", kind: "web", integration: null, credential_type: null, label: "Web",
      account: "Search and read pages", status: null, on: false, calls: 0,
      actions: [{ key: "search", action: "search", title: "Search", group: null, kind: "read", verdict: "off",
                  can_ask: true, calls: 0 }],
    }],
  }));
  const access = await nc.Agent.fromId("ag_1").toolAccess();
  assert.equal(access.mode, "restricted");
  assert.equal(access.listed, false);
  assert.deepEqual(access.rules, RULES);
  assert.equal(access.since?.toISOString(), "2026-11-07T10:00:00.000Z");
  const [gmail, web] = access.apps;
  assert.deepEqual([gmail.label, gmail.account, gmail.on, gmail.calls, gmail.credentialType], ["Gmail", "ada@example.com", true, 12, "gmail_oauth"]);
  assert.deepEqual(gmail.actions[0], { key: "work-gmail.send_email_message", action: "send_email_message",
                                       title: "Send Email Message", group: "Message", kind: "send", verdict: "ask",
                                       canAsk: true, calls: 3 });
  assert.equal(web.key, null);
  assert.equal(web.actions[0].verdict, "off");
});
