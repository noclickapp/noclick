// Deploying a repository in one call: what the client sends (a URL or one of your repos, the secrets you set, the key
// you give, a dry run) and what it reads back, and reading a password NoClick made once.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const ESTIMATE = { object: "estimate", estimated: true, monthly_usd: 0.31, plan: null, included_usd_per_month: null, items: [] };
const PLAN = {
  object: "deploy_plan", dry_run: true,
  source: { kind: "url", url: "https://gitlab.com/acme/tools/console", ref: null, host: "gitlab.com",
    path: "acme/tools/console", commit: "a".repeat(40), branch: "main", default_branch: "main" },
  name: "console", runtime: "edge", framework: null, reason: "it's only files", noclick_json: true,
  account_key: { scopes: ["agents", "dicts"], given_by: "deploy", at_deploy: "asks_owner",
    can: [{ scope: "agents", can: "run your agents", reads_secrets: false }], cannot: ["make keys"],
    note: "Anyone who can change this app's code acts with this key.", variable: "NOCLICK_API_KEY" },
  secrets: {
    generated: [{ name: "APP_PASSWORD", kind: "password", description: null, shown_once: true }],
    asked: [{ name: "STRIPE_SECRET_KEY", description: "Your Stripe key", required: true, given: false }],
  },
  missing_secrets: ["STRIPE_SECRET_KEY"], refused: null, estimate: ESTIMATE, funds: { ok: true }, makes: ["repo", "project"],
};
const RESULT = {
  object: "deploy_result", project_id: "prj_1", name: "console", url: "https://console.noclick.site", repo_id: "repo_1",
  deployment_id: "dep_1", commit: "a".repeat(40), account_key: { status: "waiting", missing_scopes: [] },
  secrets: { to_reveal: [{ name: "APP_PASSWORD", expires_at: "2026-12-01T10:00:00Z" }], next_step: "Read it once." },
};

test("a dry run sends the URL and reads what the deploy would do", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/deploys", json(PLAN));
  const plan = await nc.deploy("https://gitlab.com/acme/tools/console", { dryRun: true });
  assert.deepEqual(route.last.body, { source: { url: "https://gitlab.com/acme/tools/console" }, dry_run: true });
  assert.ok(plan instanceof nc.DeployPlan);
  assert.deepEqual([plan.name, plan.runtime, plan.noclickJson, plan.makes], ["console", "edge", true, ["repo", "project"]]);
  assert.equal(plan.estimate.monthlyUsd, 0.31);
  assert.deepEqual([plan.accountKey?.scopes, plan.accountKey?.givenBy, plan.accountKey?.atDeploy],
    [["agents", "dicts"], "deploy", "asks_owner"]);
  assert.deepEqual(plan.secrets.map((s) => [s.name, s.generate, s.required, s.given, s.shownOnce]), [
    ["APP_PASSWORD", "password", true, false, true], ["STRIPE_SECRET_KEY", null, true, false, false]]);
  assert.deepEqual([plan.missingSecrets, plan.funds, plan.refused], [["STRIPE_SECRET_KEY"], { ok: true }, null]);
});

test("a deploy sends what you bring and waits for the live app", async () => {
  const { api } = setup();
  const started = { object: "operation", id: "op_d", kind: "repo.deploy", status: "queued" };
  const route = api.on("POST", "/v1/deploys", json({ object: "deploy", name: "console-live", operation: started }, { status: 202 }));
  api.on("GET", "/v1/operations/op_d/wait", json({ ...started, status: "succeeded", result: RESULT }));
  const op = await nc.deploy("https://gitlab.com/acme/tools/console", {
    ref: "v2", name: "console-live", secrets: { STRIPE_SECRET_KEY: "sk_live_1" }, accountKey: ["agents", "dicts"],
    keySpendCapUsdPerMonth: 5,
  });
  assert.deepEqual(route.last.body, {
    source: { url: "https://gitlab.com/acme/tools/console", ref: "v2" }, name: "console-live",
    secrets: { STRIPE_SECRET_KEY: "sk_live_1" }, account_key: { scopes: ["agents", "dicts"], spend_cap_usd_per_month: 5 },
  });
  assert.ok(op instanceof nc.RepoDeploy && op instanceof nc.Operation);
  const done = await op.wait();
  assert.deepEqual([done.projectId, done.url, done.repoId, done.toReveal, done.accountKey?.status],
    ["prj_1", "https://console.noclick.site", "repo_1", ["APP_PASSWORD"], "waiting"]);
});

test("your own repo by name goes as repo, and a Repo by its id", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/deploys", json(PLAN));
  await nc.deploy("console", { dryRun: true });
  assert.deepEqual((route.last.body as { source: unknown }).source, { repo: "console" });
  await nc.deploy(nc.Repo.fromId("repo_9"), { dryRun: true });
  assert.deepEqual((route.last.body as { source: unknown }).source, { repo: "repo_9" });
  await nc.deploy("git@github.com:acme/site.git", { dryRun: true });
  assert.deepEqual((route.last.body as { source: unknown }).source, { url: "git@github.com:acme/site.git" });
});

test("nothing to deploy is refused before anything is sent", async () => {
  setup();
  await assert.rejects(nc.deploy("  ", { dryRun: true }), TypeError);
});

test("a password NoClick made is read once", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/projects/prj_1/secrets/APP_PASSWORD/reveal", json({
    object: "project_secret_value", name: "APP_PASSWORD", value: "kq7rm-x2p9d-tvh4c-8nwe3", note: "Shown this once." }));
  assert.equal(await nc.Project.fromId("prj_1").secrets.reveal("APP_PASSWORD"), "kq7rm-x2p9d-tvh4c-8nwe3");
  assert.equal(route.calls.length, 1);
});
