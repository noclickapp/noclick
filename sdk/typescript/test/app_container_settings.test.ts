// An app's container settings: what each instance gets and how many are kept warm, made with it, changed (only the
// settings given, or all back to their defaults), read back with what its warm instances cost idle, and refused by the
// setting that's out of bounds; an estimate prices a container at them.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const DEFAULTS = {
  cpu: 1, memory: 512, min_instances: 0, max_instances: 10, cpu_always: false, request_timeout_s: 300,
  idle_usd_per_month: 0, note: null,
};
const WARM_NOTE = "1 instance kept warm while production serves it: about $49.93 a month even with nothing calling it.";
const APPLIES = "Its container settings apply from its next release.";
const PROJECT = {
  object: "project", id: "prj_1", name: "standup-bot", url: "https://standup-bot.noclick.site", repo_id: "repo_1",
  runtime: "container", production_branch: "main", container: DEFAULTS, production: null, user_id: null,
  created_at: "2026-09-20T10:00:00Z",
};

test("an app is made with its container settings and reads them back", async () => {
  const { api } = setup();
  const bot = { ...DEFAULTS, cpu_always: true, min_instances: 1, idle_usd_per_month: 49.93, note: WARM_NOTE };
  const create = api.on("POST", "/v1/projects", json({ ...PROJECT, container: bot }));
  const app = await nc.Project.create("standup-bot", { repo: "repo_1", runtime: "container", container: { cpuAlways: true, minInstances: 1 } });
  assert.deepEqual(create.last.body, { name: "standup-bot", repo_id: "repo_1", runtime: "container", container: { cpu_always: true, min_instances: 1 } });
  const { raw, ...container } = app.container;
  assert.deepEqual(container, {
    cpu: 1, memory: 512, minInstances: 1, maxInstances: 10, cpuAlways: true, requestTimeoutS: 300, idleUsdPerMonth: 49.93, note: WARM_NOTE,
  });
  assert.deepEqual(raw, bot);

  // Without settings, none are sent: the app runs at the defaults.
  await nc.Project.create("standup-bot-2", { repo: "repo_1" });
  assert.equal("container" in (create.last.body as object), false);
});

test("an update sends only the settings given, and null puts every one back", async () => {
  const { api } = setup();
  const patch = api.on("PATCH", "/v1/projects/prj_1", (call: Call) => {
    const given = (call.body as { container?: object | null }).container;
    return json({ ...PROJECT, notes: [APPLIES], container: { ...DEFAULTS, ...(given ?? {}) } });
  });
  const app = await nc.Project.fromId("prj_1").update({ container: { cpu: 2, memory: 4096 } });
  assert.deepEqual(patch.last.body, { container: { cpu: 2, memory: 4096 } });
  assert.deepEqual([app.container.cpu, app.container.memory, app.raw.notes], [2, 4096, [APPLIES]]);

  // Another app's settings carry over as settings alone, not what they cost.
  const warm = { ...app.container, minInstances: 1, idleUsdPerMonth: 9.86, note: "warm" };
  await nc.Project.fromId("prj_1").update({ container: warm });
  assert.deepEqual(patch.last.body, {
    container: { cpu: 2, memory: 4096, min_instances: 1, max_instances: 10, cpu_always: false, request_timeout_s: 300 },
  });

  const reset = await nc.Project.fromId("prj_1").update({ container: null });
  assert.deepEqual(patch.last.body, { container: null });
  assert.deepEqual([reset.container.minInstances, reset.container.note], [0, null]);

  // Nothing about the container is sent when it isn't given.
  await nc.Project.fromId("prj_1").update({ budgetUsdPerMonth: 25 });
  assert.deepEqual(patch.last.body, { budget_usd_per_month: 25 });
});

test("a setting out of bounds is refused by name", async () => {
  const { api } = setup();
  api.on("PATCH", "/v1/projects/prj_1", apiError(400, "invalid_request", "container.memory: 1 vCPU takes 512 to 4096 MiB of memory, not 8192: change cpu with it.", { field: "container.memory" }));
  await assert.rejects(nc.Project.fromId("prj_1").update({ container: { memory: 8192 } }), (err: unknown) =>
    err instanceof nc.InvalidRequest && err.details.field === "container.memory");

  api.on("PATCH", "/v1/projects/prj_1", apiError(400, "invalid_request",
    "Keeping 3 instances warm costs about $29.57 a month with nothing calling the app, more than its $10.00 budget: it would pause for it.",
    { field: "container.min_instances", idle_usd_per_month: 29.57 }));
  await assert.rejects(nc.Project.fromId("prj_1").update({ container: { minInstances: 3 } }), (err: unknown) =>
    err instanceof nc.InvalidRequest && err.details.field === "container.min_instances" && err.details.idle_usd_per_month === 29.57);
});

test("an estimate prices a container at its settings, saying what its warm instances cost idle", async () => {
  const { api } = setup();
  const settings = { cpu: 1, memory: 512, min_instances: 1, max_instances: 10, cpu_always: true, request_timeout_s: 300 };
  const route = api.on("POST", "/v1/estimates", json({
    object: "estimate", estimated: true, monthly_usd: 50.06, plan: null, included_usd_per_month: null,
    items: [{
      kind: "project", label: "App in a container", name: "bot", assumed: ["region"],
      options: { runtime: "container", region: "us-east", framework: null, container: settings },
      usage: { requests: 10000 }, monthly_usd: 50.06, idle_usd_per_month: 49.93, note: WARM_NOTE, not_included: [],
      lines: [{ charge: "warm_instances", description: "Instances kept warm.", unit: "instance-month", unit_usd: 49.93, quantity: 1, usd: 49.93, assumed: false }],
    }, {
      kind: "bucket", label: "Bucket", name: null, options: {}, usage: {}, assumed: [], monthly_usd: 0, lines: [], not_included: [],
    }],
  }));
  const est = await nc.estimate([
    { kind: "project", runtime: "container", name: "bot", container: { cpuAlways: true, minInstances: 1 } },
    { kind: "bucket" },
  ]);
  // The settings go as the API names them; every other field as it is.
  assert.deepEqual(route.last.body, { items: [
    { kind: "project", runtime: "container", name: "bot", container: { cpu_always: true, min_instances: 1 } },
    { kind: "bucket" },
  ] });
  const [bot, bucket] = est.items;
  assert.deepEqual([bot.idleUsdPerMonth, bot.note, bot.options.container], [49.93, WARM_NOTE, settings]);
  assert.deepEqual(bot.lines.map((l) => l.charge), ["warm_instances"]);
  assert.deepEqual([bucket.idleUsdPerMonth, bucket.note], [null, null]);
});
