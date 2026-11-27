// An app's code made public (`makePublic`), taken back (`makePrivate`), and what anyone may know of an address
// (`PublicApp.lookup`).
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const PROJECT = {
  object: "project", id: "prj_1", name: "pilot-hub", url: "https://pilot-hub.noclick.site", repo_id: "repo_1",
  production_branch: "main", production: null, public: null, user_id: null, created_at: "2026-11-20T10:00:00Z",
};
const PUBLIC = {
  object: "public_app", public: true, clone_url: "https://pilot-hub.noclick.site",
  origin_url: "https://api.noclick.com/v1/public/git/3f2a1b0c-9d8e-4f7a-8b6c-5d4e3f2a1b0c.git",
  commit: { sha: "a".repeat(40), source_commit: "b".repeat(40), published_at: "2026-11-23T08:00:00Z" },
  files: 12, license: null, forks: 0, transfer_cap_usd: 5, blocked: false, summary: "Anyone will be able to clone...",
  scanned: { files: 12, findings: [] },
};

test("an app is made public after a dry run, and private again", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1", json(PROJECT));
  const route = api.on("POST", "/v1/projects/prj_1/public", (call: Call) => json((call.body as { dry_run?: boolean }).dry_run
    ? { object: "public_app_preview", public: false, would_publish: false, address: PROJECT.url, commit: "b".repeat(40),
        files: 12, summary: "...", scanned: { files: 12, findings: [{ path: ".env", why: "its name, .env" }] } }
    : PUBLIC));
  const app = nc.Project.fromId("prj_1");
  const preview = await app.makePublic({ dryRun: true });
  assert.deepEqual(route.last.body, { dry_run: true });
  assert.deepEqual([preview.wouldPublish, preview.findings[0].path, preview.public], [false, ".env", false]);
  const made = await app.makePublic({ transferCapUsd: 2 });
  assert.deepEqual(route.last.body, { transfer_cap_usd: 2 });
  assert.deepEqual([made.public, made.cloneUrl, made.commitSha, made.forks], [true, PROJECT.url, "a".repeat(40), 0]);

  api.on("DELETE", "/v1/projects/prj_1/public", json({ object: "public_app", public: false, was_public: true, note: "Copies stay." }));
  const priv = await app.makePrivate();
  assert.deepEqual([priv.public, priv.summary], [false, "Copies stay."]);
});

test("an app's view says whether its code is public", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1", json({ ...PROJECT, public: PUBLIC }));
  const app = await nc.Project.fromId("prj_1").hydrate();
  assert.ok(app.public?.originUrl?.endsWith(".git"));
  assert.equal(app.forkedFrom, null);
  api.on("GET", "/v1/projects/prj_2", json({ ...PROJECT, id: "prj_2", forked_from: { address: "pilot-hub.noclick.site" } }));
  assert.deepEqual((await nc.Project.fromId("prj_2").hydrate()).forkedFrom, { address: "pilot-hub.noclick.site" });
});

test("anyone looks an address up", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/public/apps", json({
    object: "public_app", address: "pilot-hub.noclick.site", public: true, name: "pilot-hub", title: "Pilot hub",
    clone_url: PROJECT.url, origin_url: PUBLIC.origin_url, default_branch: "main",
    commit: { sha: "a".repeat(40), published_at: "2026-11-23T08:00:00Z" }, forks: 3, license: "MIT",
    deploy: { account_key_scopes: ["apps"], build_env: [], secrets: [] }, report: "support@noclick.com",
  }));
  const found = await nc.PublicApp.lookup("pilot-hub.noclick.site");
  assert.equal(route.last.query.get("address"), "pilot-hub.noclick.site");
  assert.deepEqual([found.public, found.cloneUrl, found.forks, found.deploy.account_key_scopes], [true, PROJECT.url, 3, ["apps"]]);
});

test("a space saved as a template goes public with no app", async () => {
  const { api } = setup();
  const said = {
    object: "space_template", name: "Social media", repo_name: "social-media-template",
    contains: { agents: ["Writer"], app: false }, asks: { connections: [{ integration: "instagram", for: ["Writer"] }] },
    left_out: [], never: ["the people in the space"], files: 4, summary: "...",
  };
  const route = api.on("POST", "/v1/workspaces/ws_1/template", (call: Call) => (call.body as { dry_run?: boolean }).dry_run
    ? json(said)
    : json({ ...said, repo: { object: "repo", id: "repo_1", name: "social-media-template", default_branch: "main" },
        commit: { sha: "c".repeat(40) } }, { status: 201 }));
  const space = nc.Workspace.fromId("ws_1");
  const dry = await space.saveAsTemplate({ dryRun: true });
  assert.deepEqual([route.last.body, dry.repo], [{ dry_run: true }, null]);
  const saved = await space.saveAsTemplate({ repoName: "lumen-social", includeApp: false });
  assert.deepEqual(route.last.body, { repo_name: "lumen-social", include_app: false });
  assert.deepEqual([saved.repo?.id, saved.commitSha, saved.contains.agents], ["repo_1", "c".repeat(40), ["Writer"]]);

  const published = api.on("POST", "/v1/repos/repo_1/public", json({ ...PUBLIC, kind: "template", clone_url: PUBLIC.origin_url }));
  const made = await saved.repo!.makePublic();
  assert.deepEqual([published.last.body, made.cloneUrl], [{}, PUBLIC.origin_url]);
  api.on("GET", "/v1/public/apps", json({ object: "public_app", address: "api.noclick.com", public: true, kind: "template",
    template: { agents: ["Writer"] } }));
  const found = await nc.PublicApp.lookup(PUBLIC.origin_url);
  assert.deepEqual([found.kind, found.template], ["template", { agents: ["Writer"] }]);
});
