// A space template added as a new space (`Workspace.fromTemplate`) or into one you have (`addTemplate`): the dry run's
// page of asks, then the operation whose result names what arrived; a deploy of a template's address is the same add.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const ADDRESS = "https://api.noclick.com/v1/public/git/3f2a1b0c-9d8e-4f7a-8b6c-5d4e3f2a1b0c.git";
const PLAN = {
  object: "space_template_plan", dry_run: true,
  template: { name: "Social media team", description: "Posts for your brand.", word: "Social" },
  target: { workspace_id: null, name: "Social media team", new: true },
  parts: [
    { kind: "agent", name: "Writer", as: "Social Writer", line: "Drafts posts", needs: [], included: true },
    { kind: "channel", name: "ideas", as: "ideas", line: null, members: ["Social Writer"], schedules: ["Plan the week."], included: true },
  ],
  short: [],
  connections: [
    { integration: "canva", label: "Canva", node_type: "automation-canva", for: ["Designer"], connected: null },
    { integration: "linkedin", label: "LinkedIn", node_type: "automation-linkedin", for: ["Scheduler"], connected: { ref: "credential:cr_1", name: null, id: "cr_1" } },
  ],
  secrets: [{ name: "unsplash", keys: ["UNSPLASH_ACCESS_KEY"], description: null, for: ["Designer"], held: null, given: false }],
  cap: { usd_per_month: 40, from: "template", agents: [{ name: "Social Writer", usd_per_month: 40 }] },
  app: null, estimate: { monthly_usd: 1.2, items: [], agents: { up_to_usd: 40 } }, funds: { ok: true }, refused: null,
  summary: "Adds Social media team to a new space.",
};
const OPERATION = { object: "operation", id: "op_1", kind: "workspace.template_add", status: "queued", workspace_id: null, channel_id: null };
const ADDED = {
  object: "space_template_added", workspace: { id: "ws_1", name: "Social media team", new: true },
  channel: { id: "ch_noclick", name: "noclick" }, message_id: "msg_1", agents: [{ id: "ag_1", name: "Writer" }],
  channels: [{ id: "ch_1", name: "ideas" }], app: null, waiting: [{ integration: "canva", label: "Canva" }],
};

test("a template is read as its page of asks, then added as a new space", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/workspaces/from_template", (call: Call) =>
    (call.body as { dry_run?: boolean }).dry_run ? json(PLAN) : json({ object: "space_template_add", operation: OPERATION }, { status: 202 }));
  const plan = await nc.Workspace.fromTemplate(ADDRESS, { dryRun: true, capUsdPerMonth: 30 });
  assert.deepEqual(route.last.body, { source: { url: ADDRESS }, cap_usd_per_month: 30, dry_run: true });
  assert.deepEqual(plan.parts.map((p) => [p.kind, p.name, p.named]), [["agent", "Writer", "Social Writer"], ["channel", "ideas", "ideas"]]);
  assert.deepEqual(plan.connections.map((a) => [a.label, a.connected?.ref ?? null]), [["Canva", null], ["LinkedIn", "credential:cr_1"]]);
  assert.equal(plan.cap.usdPerMonth, 40);

  api.on("GET", "/v1/operations/op_1/wait", json({ ...OPERATION, status: "succeeded", workspace_id: "ws_1", channel_id: "ch_noclick", result: ADDED }));
  const adding = await nc.Workspace.fromTemplate(ADDRESS, { secrets: { unsplash: { UNSPLASH_ACCESS_KEY: "key" } }, leaveOut: [{ kind: "app" }] });
  assert.deepEqual(route.last.body, { source: { url: ADDRESS }, leave_out: [{ kind: "app" }], secrets: { unsplash: { UNSPLASH_ACCESS_KEY: "key" } } });
  assert.ok(adding instanceof nc.TemplateAdd);
  const added = await adding.wait();
  assert.deepEqual([added.workspaceId, added.channelId, added.agents[0].name], ["ws_1", "ch_noclick", "Writer"]);
});

test("a template goes into a space you have, and a deploy of its address is that add", async () => {
  const { api } = setup();
  const into = api.on("POST", "/v1/workspaces/ws_9/template/add", json({ ...PLAN, target: { workspace_id: "ws_9", name: "Lumen Coffee", new: false } }));
  const plan = await nc.Workspace.fromId("ws_9").addTemplate("social-media-team", { dryRun: true });
  assert.deepEqual(into.last.body, { source: { repo: "social-media-team" }, dry_run: true });
  assert.equal(plan.target.name, "Lumen Coffee");
  api.on("POST", "/v1/deploys", json(PLAN));
  const deployed = await nc.deploy(ADDRESS, { dryRun: true });
  assert.ok(!(deployed instanceof nc.DeployPlan) && deployed.template.name === "Social media team");
});
