import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { BASE, USER_ID, apiError, json, listing, operation, setup, trashed } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const COMMIT = {
  sha: "9f2c1ab", message: "Add the booking form", author: "Ana Silva", branch: "main",
  created_at: "2026-09-25T09:00:00Z", files_changed: 3,
};
const REPO = {
  object: "repo", id: "repo_1", name: "booking", default_branch: "main", size_bytes: 482133, last_commit: COMMIT,
  used_by: [{ kind: "project", id: "prj_1", name: "booking" }], user_id: null, created_at: "2026-09-20T10:00:00Z",
};
const DEPLOYMENT = {
  object: "deployment", id: "dep_1", project_id: "prj_1", branch: "main", commit: "9f2c1ab",
  commit_message: "Add the booking form", status: "ready", url: "https://booking.noclick.site", production: true,
  error: null, created_at: "2026-09-25T09:01:00Z", ready_at: "2026-09-25T09:02:10Z",
};
const PROJECT = {
  object: "project", id: "prj_1", name: "booking", url: "https://booking.noclick.site", repo_id: "repo_1",
  framework: "remix", production_branch: "main", domain_names: ["acmebooking.com"], production: DEPLOYMENT,
  user_id: null, created_at: "2026-09-20T10:00:00Z",
};
const SCHEDULE = {
  object: "schedule", id: "sch_1", project_id: "prj_1", name: "/jobs/reminders", cron: "0 9 * * 1-5",
  tz: "America/New_York", path: "/jobs/reminders", status: "active", paused_reason: null,
  next_run: "2026-09-28T13:00:00Z", last_run: null, last_status: null, created_at: "2026-09-25T10:00:00Z",
};

// --- repos ---------------------------------------------------------------------

test("Repo.create, list and delete, acting for the user", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/repos", json(REPO));
  const listed = api.on("GET", "/v1/repos", json(listing([REPO])));
  const remove = api.on("DELETE", "/v1/repos/repo_1", json(trashed("repo", "repo_1", "booking")));
  const repo = await nc.asUser("user_42", () => nc.Repo.create("booking", { defaultBranch: "main" }));
  assert.deepEqual(create.last.body, { name: "booking", default_branch: "main" });
  assert.equal(create.last.headers.get("NoClick-User"), "user_42");
  assert.deepEqual([repo.name, repo.defaultBranch, repo.sizeBytes], ["booking", "main", 482133]);
  assert.deepEqual([repo.lastCommit?.sha, repo.lastCommit?.filesChanged, repo.lastCommit?.createdAt?.getUTCHours()], ["9f2c1ab", 3, 9]);
  assert.deepEqual(repo.usedBy, [{ kind: "project", id: "prj_1", name: "booking", binding: null }]);

  const [first] = await nc.Repo.list({ userFilter: nc.ALL_USERS });
  assert.equal(listed.last.query.get("user_id"), "all");
  assert.equal(listed.last.headers.get("NoClick-User"), null);
  const item = await first.delete();
  assert.equal(remove.count, 1);
  assert.deepEqual([item.kind, item.resourceId, item.name, item.operationId], ["repo", "repo_1", "booking", "op_del"]);
});

test("Repo.fromName is lazy, creates once and adopts a concurrent create", async () => {
  const { api } = setup();
  const lookup = api.on("GET", "/v1/repos", json(listing([])));
  const create = api.on("POST", "/v1/repos", json(REPO), apiError(409, "conflict", "taken", { existing_id: "repo_1" }));
  api.on("GET", "/v1/repos/repo_1", json(REPO));
  const repo = nc.Repo.fromName("booking", { createIfMissing: true });
  assert.equal(lookup.count, 0);
  await repo.hydrate();
  assert.equal(lookup.last.query.get("name"), "booking");
  assert.deepEqual(create.last.body, { name: "booking" });
  const racing = await nc.Repo.fromName("booking", { createIfMissing: true, defaultBranch: "trunk" }).hydrate();
  assert.equal(racing.id, "repo_1");
  assert.deepEqual(create.last.body, { name: "booking", default_branch: "trunk" });
  await assert.rejects(nc.Repo.fromName("nope").hydrate(), nc.NotFound);
});

test("cloneUrl, commit, read and files", async () => {
  const { api } = setup();
  const clone = api.on("POST", "/v1/repos/repo_1/clone_url", json({ url: "https://x-token:abc@git.noclick.app/booking.git" }));
  const commit = api.on("POST", "/v1/repos/repo_1/commits", json({ ...COMMIT, sha: "a1b2c3d", branch: "new-form" }));
  const files = api.on(
    "GET", "/v1/repos/repo_1/files",
    new Response('{"name": "booking"}', { headers: { "content-type": "application/octet-stream" } }),
    json(listing([{ path: "app/routes", type: "dir", size: null }, { path: "app/root.tsx", type: "file", size: 812 }])),
  );
  const repo = nc.Repo.fromId("repo_1", { user: USER_ID });
  assert.equal(await repo.cloneUrl({ write: true, ttlS: 600 }), "https://x-token:abc@git.noclick.app/booking.git");
  assert.deepEqual(clone.last.body, { write: true, ttl_s: 600 });
  assert.equal(clone.last.headers.get("NoClick-User"), USER_ID);
  await repo.cloneUrl();
  assert.deepEqual(clone.last.body, { write: false });

  const made = await repo.commit(
    { "src/index.ts": "export {};\n", "logo.png": new Uint8Array([0x89, 0x50, 0x4e, 0x47]), "old.txt": null },
    { message: "Add the lookup route", branch: "new-form" },
  );
  assert.deepEqual(commit.last.body, {
    message: "Add the lookup route",
    branch: "new-form",
    files: [
      { path: "src/index.ts", content: "export {};\n", encoding: "utf-8" },
      { path: "logo.png", content: "iVBORw==", encoding: "base64" },
      { path: "old.txt", delete: true },
    ],
  });
  assert.deepEqual([made.sha, made.branch], ["a1b2c3d", "new-form"]);

  // A file NoClick can reach goes by reference: one of the account's files, a URL, a bucket's file.
  await repo.commit(
    {
      "index.html": { attachmentId: "att_1" },
      "logo.png": { url: "https://example.com/logo.png" },
      "fonts/a.woff2": { bucketId: "bkt_1", key: "fonts/a.woff2" },
    },
    { message: "Publish the game" },
  );
  assert.deepEqual(commit.last.body, {
    message: "Publish the game",
    files: [
      { path: "index.html", attachment_id: "att_1" },
      { path: "logo.png", url: "https://example.com/logo.png" },
      { path: "fonts/a.woff2", bucket_id: "bkt_1", key: "fonts/a.woff2" },
    ],
  });

  assert.equal(await repo.readText("package.json", { ref: "main" }), '{"name": "booking"}');
  assert.deepEqual([files.last.query.get("path"), files.last.query.get("ref")], ["package.json", "main"]);
  const tree = await repo.files("app/", { recursive: true });
  assert.deepEqual([files.last.query.get("prefix"), files.last.query.get("recursive"), files.last.query.has("ref")], ["app/", "true", false]);
  assert.deepEqual(tree.map((f) => [f.type, f.path, f.size]), [["dir", "app/routes", null], ["file", "app/root.tsx", 812]]);
});

test("branches and commits", async () => {
  const { api } = setup();
  api.on("GET", "/v1/repos/repo_1/branches", json(listing([{ name: "main", head: "9f2c1ab", updated_at: "2026-09-25T09:00:00Z" }])));
  const commits = api.on("GET", "/v1/repos/repo_1/commits", json(listing([COMMIT], "c2")), json(listing([COMMIT])));
  const repo = nc.Repo.fromId("repo_1");
  const [main] = await repo.branches();
  assert.deepEqual([main.name, main.head, main.updatedAt?.getUTCHours()], ["main", "9f2c1ab", 9]);
  const [latest] = await repo.commits({ branch: "main", limit: 1 });
  assert.deepEqual([commits.last.query.get("branch"), commits.last.query.get("limit")], ["main", "1"]);
  assert.equal(latest.message, "Add the booking form");
  await repo.commits();
  assert.equal(commits.last.query.get("limit"), "20");
  const page = await repo.commitsPage({ branch: "main", limit: 50 });
  assert.deepEqual([page.nextCursor, page.data[0].message], [null, "Add the booking form"]);
  await repo.commitsPage({ branch: "main", limit: 50, cursor: "c2" });
  assert.deepEqual([commits.last.query.get("cursor"), commits.last.query.get("limit")], ["c2", "50"]);
});

test("backups list the branches agents rewrote or deleted, and restore makes one again", async () => {
  const { api } = setup();
  const backup = {
    object: "repo_backup", id: "bak_1", branch: "agent/new-form", sha: "a1b2c3d", reason: "rewritten",
    agent_id: "agt_1", created_at: "2026-10-16T09:00:00Z", expires_at: "2026-11-15T09:00:00Z",
  };
  const listed = api.on("GET", "/v1/repos/repo_1/backups", json(listing([backup])));
  const restore = api.on("POST", "/v1/repos/repo_1/backups/bak_1/restore", json({
    object: "branch", name: "agent/new-form-restored-20261016T100000Z", head: "a1b2c3d",
    updated_at: "2026-10-16T09:00:00Z", restored_from: "bak_1",
  }));
  const repo = nc.Repo.fromId("repo_1");
  const [kept] = await repo.backups({ branch: "agent/new-form" });
  assert.deepEqual([listed.last.query.get("branch"), listed.last.query.get("limit")], ["agent/new-form", "50"]);
  assert.deepEqual([kept.branch, kept.sha, kept.reason, kept.agentId, kept.expiresAt?.getUTCMonth()],
    ["agent/new-form", "a1b2c3d", "rewritten", "agt_1", 10]);
  const branch = await repo.restoreBackup(kept);
  assert.deepEqual([branch.name, branch.head], ["agent/new-form-restored-20261016T100000Z", "a1b2c3d"]);
  assert.equal((await repo.restoreBackup("bak_1")).head, "a1b2c3d");
  assert.equal(restore.calls.length, 2);
});

test("diff reads what a commit changed, file by file", async () => {
  const { api } = setup();
  const patch = "diff --git a/app/form.tsx b/app/form.tsx\n--- a/app/form.tsx\n+++ b/app/form.tsx\n@@ -1 +1 @@\n-a\n+b\n";
  api.on("GET", "/v1/repos/repo_1/commits/9f2c1ab", json({
    ...COMMIT, parents: ["1a2b3c4"], additions: 1, deletions: 1, files_changed: 2,
    files: [
      { object: "commit_file", path: "app/form.tsx", old_path: null, status: "modified", additions: 1, deletions: 1, size: 812, patch },
      { object: "commit_file", path: "public/logo.png", old_path: null, status: "added", additions: null, deletions: null, size: 20480, patch: null },
    ],
  }));
  const changes = await nc.Repo.fromId("repo_1").diff("9f2c1ab");
  assert.deepEqual([changes.commit.message, changes.parents, changes.additions, changes.deletions], ["Add the booking form", ["1a2b3c4"], 1, 1]);
  assert.deepEqual(changes.files.map((f) => [f.path, f.status, f.patch, f.additions]), [
    ["app/form.tsx", "modified", patch, 1],
    ["public/logo.png", "added", null, null],
  ]);
});

test("export and exportToGithub resolve typed; an unconnected GitHub connection asks to connect", async () => {
  const { api } = setup();
  const exp = api.on(
    "POST", "/v1/repos/repo_1/export",
    json(operation({ id: "op_e", kind: "repo.export", status: "running" }), { status: 202 }),
    json(operation({ id: "op_g", kind: "repo.export_to_github", status: "running" }), { status: 202 }),
    json(operation({ id: "op_g", kind: "repo.export_to_github", status: "running" }), { status: 202 }),
    apiError(424, "needs_connection", "The 'github' connection has no GitHub account connected yet.",
      { connection: "github", connect_url: "https://noclick.com/c/abc" }),
  );
  api.on("GET", "/v1/operations/op_e/wait", json(operation({
    id: "op_e", kind: "repo.export", status: "succeeded",
    result: { url: "https://exports.noclick.app/e.zip", size_bytes: 2048,
              contents: [{ kind: "code", name: "agent-tools", detail: "A git bundle." }] },
  })));
  api.on("GET", "/v1/operations/op_g/wait", json(operation({
    id: "op_g", kind: "repo.export_to_github", status: "succeeded", result: { url: "https://github.com/acme/agent-tools" },
  })));
  const repo = nc.Repo.fromId("repo_1");
  const bundle = await (await repo.export()).wait();
  assert.deepEqual(exp.last.body, {});
  assert.deepEqual([bundle.contents[0].kind, bundle.sizeBytes], ["code", 2048]);
  const url = await (await repo.exportToGithub({ connection: "github", owner: "acme" })).wait();
  assert.equal(url, "https://github.com/acme/agent-tools");
  assert.deepEqual(exp.last.body, { to: "github", connection: "github", owner: "acme", private: true });
  // A Connection goes by its id.
  await repo.exportToGithub({ connection: nc.Connection.fromId("con_9"), owner: "acme" });
  assert.deepEqual(exp.last.body, { to: "github", connection: "con_9", owner: "acme", private: true });
  await assert.rejects(repo.exportToGithub({ connection: "github", owner: "acme", name: "tools", private: false }),
    (err: unknown) => {
      assert.ok(err instanceof nc.NeedsConnection);
      assert.equal(err.connectUrl, "https://noclick.com/c/abc");
      return true;
    });
  assert.deepEqual(exp.last.body, { to: "github", connection: "github", owner: "acme", name: "tools", private: false });
});

test("Repo.create with fromUrl resolves to the import, whose wait() gives the copied repo", async () => {
  const { api } = setup();
  const create = api.on(
    "POST", "/v1/repos",
    json({ ...REPO, name: "blog", last_commit: null,
           operation: operation({ id: "op_i", kind: "repo.import", status: "queued", repo_id: "repo_1" }) }),
    json({ ...REPO, operation: operation({ id: "op_j", kind: "repo.import", status: "queued", repo_id: "repo_2" }) }),
  );
  api.on("GET", "/v1/operations/op_i/wait", json(operation({
    id: "op_i", kind: "repo.import", status: "succeeded", repo_id: "repo_1",
    result: { object: "repo_import", repo: { ...REPO, name: "blog", default_branch: "trunk" }, default_branch: "trunk",
              head: COMMIT, branches: 2, tags: 3, size_bytes: 48213 },
  })));
  api.on("GET", "/v1/operations/op_j/wait", json(operation({
    id: "op_j", kind: "repo.import", status: "failed", repo_id: "repo_2",
    error: { type: "invalid_request", message: "https://example.com/acme/private asked for a sign-in.",
             next_step: "Make the repository public.", field: "source.url" },
  })));

  const copy = await nc.Repo.create("blog", { fromUrl: "https://github.com/acme/blog" });
  assert.deepEqual(create.last.body, { name: "blog", source: { url: "https://github.com/acme/blog" } });
  assert.ok(copy instanceof nc.RepoImport && copy instanceof nc.Operation);
  assert.deepEqual([copy.id, copy.repoId, copy.repo._known("id")], ["op_i", "repo_1", "repo_1"]);
  const repo = await copy.wait();
  assert.ok(repo instanceof nc.Repo);
  assert.deepEqual([repo.id, repo.name, repo.defaultBranch], ["repo_1", "blog", "trunk"]);

  const refused = await nc.Repo.create("v2", { fromUrl: "https://example.com/acme/private", ref: "v2.0.0", defaultBranch: "main" });
  assert.deepEqual(create.last.body, {
    name: "v2", default_branch: "main", source: { url: "https://example.com/acme/private", ref: "v2.0.0" },
  });
  await assert.rejects(refused.wait(), (err: unknown) => {
    assert.ok(err instanceof nc.InvalidRequest);
    assert.equal(err.details.field, "source.url");
    return true;
  });
  await assert.rejects(
    nc.Repo.create("blog", { fromUrl: "https://github.com/acme/blog", allowExisting: true } as nc.RepoImportOptions),
    TypeError,
  );
  assert.equal(create.count, 2);
});

// --- projects ------------------------------------------------------------------

test("Project.fromName creates its repo first, then converges only what differs", async () => {
  const { api } = setup();
  api.on("GET", "/v1/repos", json(listing([])));
  const makeRepo = api.on("POST", "/v1/repos", json(REPO));
  const lookup = api.on("GET", "/v1/projects", json(listing([])), json(listing([{ ...PROJECT, framework: "vite" }])));
  const create = api.on("POST", "/v1/projects", json(PROJECT));
  const patch = api.on("PATCH", "/v1/projects/prj_1", json(PROJECT));
  const repo = nc.Repo.fromName("booking", { createIfMissing: true });
  const app = nc.Project.fromName("booking", { repo, createIfMissing: true });
  assert.equal(makeRepo.count + lookup.count, 0);
  await app.hydrate();
  assert.equal(makeRepo.count, 1);
  assert.deepEqual(create.last.body, { name: "booking", repo_id: "repo_1" });
  assert.equal(app.url, "https://booking.noclick.site");

  const defined = await nc.Project.fromName("booking", { repo: "repo_1", framework: "remix", createIfMissing: true }).hydrate();
  assert.equal(defined.framework, "remix");
  assert.deepEqual(patch.last.body, { framework: "remix" });

  assert.ok(app.production instanceof nc.Deployment && app.production.production);
  assert.deepEqual(app.domainNames, ["acmebooking.com"]);
  assert.ok(app.repo instanceof nc.Repo && app.repo._known("id") === "repo_1");
  assert.ok(app.secrets instanceof nc.ProjectSecrets);
  assert.ok(app.email instanceof nc.ProjectEmail && app.payments instanceof nc.ProjectPayments && app.signIn instanceof nc.ProjectSignIn);
});

test("Project.create for a user, and list across users", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/projects", json({ ...PROJECT, user_id: USER_ID }));
  const listed = api.on("GET", "/v1/projects", json(listing([PROJECT, { ...PROJECT, id: "prj_2", production: null }])));
  const app = await nc.asUser("acme", () => nc.Project.create("status-page", { framework: "astro" }));
  assert.deepEqual(create.last.body, { name: "status-page", framework: "astro" });
  assert.equal(create.last.headers.get("NoClick-User"), "acme");
  assert.equal(app.userId, USER_ID);
  const apps = await nc.Project.list({ userFilter: nc.ALL_USERS });
  assert.equal(listed.last.query.get("user_id"), "all");
  assert.deepEqual(apps.map((a) => [a.id, a.production?.status ?? null]), [["prj_1", "ready"], ["prj_2", null]]);
});

test("an app names its runtime and its own hostname", async () => {
  const { api } = setup();
  const edge = { ...PROJECT, hostname: "booking.noclick.site", runtime: "edge", production: { ...DEPLOYMENT, environment: "production" } };
  const create = api.on("POST", "/v1/projects", json(edge));
  const app = await nc.Project.create("booking", { runtime: "edge", region: "eu" });
  assert.deepEqual(create.last.body, { name: "booking", runtime: "edge", region: "eu" });
  assert.deepEqual([app.hostname, app.runtime, app.production?.environment], ["booking.noclick.site", "edge", "production"]);
});

test("an app opts into auto, and a deployment says where it ran and why", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects", json(listing([{ ...PROJECT, runtime: "edge" }])));
  const patch = api.on("PATCH", "/v1/projects/prj_1", (call: Call) => json({ ...PROJECT, ...(call.body as object) }));
  const defined = await nc.Project.fromName("booking", { runtime: "auto", createIfMissing: true }).hydrate();
  assert.equal(defined.runtime, "auto");
  assert.deepEqual(patch.last.body, { runtime: "auto" });
  await nc.Project.fromName("booking", { createIfMissing: true }).hydrate();
  assert.equal(patch.count, 1); // left out, never changed
  await nc.Project.fromId("prj_1").update({ runtime: "container", framework: null });
  assert.deepEqual(patch.last.body, { runtime: "container", framework: null });
  api.on("GET", "/v1/deployments/dep_2", json({ ...DEPLOYMENT, id: "dep_2", runtime: "container", runtime_reason: "a Dockerfile describes its server" }));
  const ran = await nc.Deployment.get("dep_2");
  assert.deepEqual([ran.runtime, ran.runtimeReason], ["container", "a Dockerfile describes its server"]);
});

test("a failed deployment names the change that fixes it", async () => {
  const { api } = setup();
  const fix = { kind: "next_upgrade", found: "15.3.2", needed: "16.4.1" };
  api.on("GET", "/v1/deployments/dep_3", json({ ...DEPLOYMENT, id: "dep_3", status: "failed", fix }));
  assert.deepEqual((await nc.Deployment.get("dep_3")).fix, fix);
  api.on("GET", "/v1/deployments/dep_4", json({ ...DEPLOYMENT, id: "dep_4" }));
  assert.equal((await nc.Deployment.get("dep_4")).fix, null);
});

test("secrets are set per environment", async () => {
  const { api } = setup();
  const put = api.on("PUT", "/v1/projects/prj_1/secrets/STRIPE_KEY", json({}));
  const listed = api.on("GET", "/v1/projects/prj_1/secrets", json(listing([
    { name: "STRIPE_KEY", environments: ["preview"], updated_at: "2026-09-25T10:00:00Z" },
  ])));
  const remove = api.on("DELETE", "/v1/projects/prj_1/secrets/STRIPE_KEY", json({}));
  const app = nc.Project.fromId("prj_1");
  await app.secrets.set("STRIPE_KEY", "sk_live_1", { environment: "production" });
  assert.deepEqual(put.last.body, { value: "sk_live_1", environment: "production" });
  await app.secrets.set("STRIPE_KEY", "sk_test_1", { environment: "all" });
  assert.deepEqual(put.last.body, { value: "sk_test_1" });
  assert.deepEqual(Object.keys(await app.secrets.list({ environment: "preview" })), ["STRIPE_KEY"]);
  assert.equal(listed.last.query.get("environment"), "preview");
  await app.secrets.list();
  assert.equal(listed.last.query.has("environment"), false);
  await app.secrets.delete("STRIPE_KEY", { environment: "preview" });
  assert.equal(remove.last.query.get("environment"), "preview");
});

test("deploy resolves the ready deployment; a failed build names its deployment", async () => {
  const { api } = setup();
  const deploy = api.on(
    "POST", "/v1/projects/prj_1/deployments",
    json(operation({ id: "op_d", kind: "project.deploy", status: "queued" }), { status: 202 }),
    json(operation({ id: "op_f", kind: "project.deploy", status: "queued" }), { status: 202 }),
  );
  api.on("GET", "/v1/operations/op_d/wait", json(operation({
    id: "op_d", kind: "project.deploy", status: "succeeded",
    result: { ...DEPLOYMENT, id: "dep_2", branch: "new-form", production: false, url: "https://new-form--booking.noclick.site" },
  })));
  api.on("GET", "/v1/operations/op_f/wait", json(operation({
    id: "op_f", kind: "project.deploy", status: "failed",
    error: { type: "operation_failed", message: "The build failed: npm run build exited 1.", deployment_id: "dep_9" },
  })));
  const logs = api.on("GET", "/v1/deployments/dep_2/logs", json(listing([
    { at: "2026-09-25T10:00:01Z", level: "info", message: "Installing dependencies", deployment_id: "dep_2" },
  ])));
  const app = nc.Project.fromId("prj_1", { user: USER_ID });
  const preview = await (await app.deploy({ branch: "new-form", commit: "a1b2c3d" })).wait();
  assert.deepEqual(deploy.last.body, { branch: "new-form", commit: "a1b2c3d" });
  assert.equal(deploy.last.headers.get("NoClick-User"), USER_ID);
  assert.ok(preview instanceof nc.Deployment);
  assert.deepEqual([preview.url, preview.production, preview.readyAt?.getUTCMinutes()], ["https://new-form--booking.noclick.site", false, 2]);
  const [line] = await preview.logs();
  assert.equal(logs.last.query.get("kind"), "build");
  assert.equal(logs.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual([line.level, line.message], ["info", "Installing dependencies"]);

  await assert.rejects((await app.deploy()).wait(), (err: unknown) => {
    assert.ok(err instanceof nc.OperationFailed);
    assert.equal(err.details.deployment_id, "dep_9");
    return true;
  });
  assert.deepEqual(deploy.last.body, {});
});

test("deployments, rollback through promote, and cancel", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/projects/prj_1/deployments", json(listing([DEPLOYMENT, { ...DEPLOYMENT, id: "dep_0", production: false }])));
  const promote = api.on("POST", "/v1/deployments/dep_0/promote", json(operation({ id: "op_p", kind: "deployment.promote", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_p/wait", json(operation({
    id: "op_p", kind: "deployment.promote", status: "succeeded", result: { ...DEPLOYMENT, id: "dep_0" },
  })));
  const cancel = api.on("POST", "/v1/deployments/dep_3/cancel", json({ ...DEPLOYMENT, id: "dep_3", status: "canceled" }));
  const app = nc.Project.fromId("prj_1");
  const [current, previous] = await app.deployments({ branch: "main", limit: 5 });
  assert.deepEqual([listed.last.query.get("branch"), listed.last.query.get("limit")], ["main", "5"]);
  assert.ok(current.production && !previous.production);
  const rolled = await (await app.rollback(previous)).wait();
  assert.deepEqual([promote.count, rolled.id, rolled.production], [1, "dep_0", true]);
  await app.rollback("dep_0");
  assert.equal(promote.count, 2);
  const stuck = nc.Deployment.fromId("dep_3");
  assert.equal(await stuck.cancel(), stuck);
  assert.equal(stuck.status, "canceled");
  assert.equal(cancel.count, 1);
});

test("a deployment is checked, promoted by force, and reads its request outcomes", async () => {
  const { api } = setup();
  const check = api.on("POST", "/v1/deployments/dep_1/check", json(operation({ id: "op_c", kind: "deployment.check", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_c/wait", json(operation({
    id: "op_c", kind: "deployment.check", status: "succeeded", result: {
      object: "deployment_check", deployment_id: "dep_1", url: "https://booking.noclick.site", passed: false,
      checked_at: "2026-09-25T09:05:00Z", cost_usd: 0.0012, paths: [
        { path: "/", url: "https://booking.noclick.site/", ok: true, problem: null, status: 200, load_ms: 840, title: "Booking",
          console_errors: [{ kind: "console", message: "Analytics" }],
          screenshot: { object: "file", id: "f_1", name: "check-home.png", url: "https://f.test/1.png", mime_type: "image/png" } },
        { path: "/book", url: "https://booking.noclick.site/book", ok: false, problem: "It answered 404.", status: 404,
          load_ms: 120, title: "Not found", console_errors: [], screenshot: null },
      ],
    },
  })));
  const promote = api.on("POST", "/v1/deployments/dep_1/promote", json(operation({ id: "op_p", kind: "deployment.promote", status: "running" }), { status: 202 }));
  const requests = api.on("GET", "/v1/deployments/dep_1/requests", json({
    object: "request_outcomes", deployment_id: "dep_1", since: "2026-09-24T09:00:00Z", until: "2026-09-25T09:00:00Z",
    requests: 120, sampled: false, errors: 3, error_rate: 0.025, by_status: { "200": 117, "500": 3 },
    slowest_routes: [{ method: "POST", path: "/api/book", requests: 20, errors: 3, p50_ms: 310, p95_ms: 1200, max_ms: 1900 }],
  }));
  const deployment = nc.Deployment.fromId("dep_1");
  const checked = await (await deployment.check(["/", "/book"])).wait();
  assert.deepEqual(check.last.body, { paths: ["/", "/book"] });
  assert.deepEqual([checked.passed, checked.costUsd, checked.paths.length], [false, 0.0012, 2]);
  const [home, book] = checked.paths;
  assert.deepEqual([home.ok, home.status, home.loadMs, home.consoleErrors], [true, 200, 840, [{ kind: "console", message: "Analytics" }]]);
  assert.equal(home.screenshot?.url, "https://f.test/1.png");
  assert.deepEqual([book.ok, book.problem, book.screenshot], [false, "It answered 404.", null]);
  await deployment.check();
  assert.equal(check.last.body, null);
  await deployment.promote();
  assert.equal(promote.last.body, null);
  await deployment.promote({ force: true });
  assert.deepEqual(promote.last.body, { force: true });
  const outcomes = await deployment.requests();
  assert.equal(requests.last.query.get("since"), null);
  assert.deepEqual([outcomes.requests, outcomes.errors, outcomes.errorRate, outcomes.byStatus], [120, 3, 0.025, { "200": 117, "500": 3 }]);
  assert.deepEqual([outcomes.slowestRoutes[0].path, outcomes.slowestRoutes[0].p95Ms], ["/api/book", 1200]);
  await deployment.requests({ since: "2026-09-20T00:00:00Z" });
  assert.equal(requests.last.query.get("since"), "2026-09-20T00:00:00Z");
});

test("bind sends name, kind and id; bindings and unbind", async () => {
  const { api } = setup();
  const bind = api.on("POST", "/v1/projects/prj_1/bindings", (call: Call) => {
    const b = call.body as { name: string; kind: string; id: string };
    return json({ object: "binding", name: b.name, kind: b.kind, resource_id: b.id, resource_name: "booking-db", created_at: "2026-09-25T10:00:00Z" });
  });
  api.on("GET", "/v1/projects/prj_1/bindings", json(listing([
    { name: "DB", kind: "database", resource_id: "db_1", resource_name: "booking-db", variables: ["DB"] },
    { name: "SHIPPING", kind: "secret", resource_id: "sec_1", resource_name: "shipping", variables: ["SHIPPING_API_KEY"] },
  ])));
  const unbind = api.on("DELETE", "/v1/projects/prj_1/bindings/CRM", json(undefined, { status: 204 }));
  const app = nc.Project.fromId("prj_1");
  const made = await app.bind("DB", nc.Database.fromId("db_1"));
  assert.deepEqual(bind.last.body, { name: "DB", kind: "database", id: "db_1" });
  assert.deepEqual([made.name, made.kind, made.resourceId, made.resourceName], ["DB", "database", "db_1", "booking-db"]);
  await app.bind("FILES", nc.Bucket.fromId("bkt_1"));
  assert.deepEqual(bind.last.body, { name: "FILES", kind: "bucket", id: "bkt_1" });
  await app.bind("CRM", nc.Connection.fromId("con_1"));
  assert.deepEqual(bind.last.body, { name: "CRM", kind: "connection", id: "con_1" });
  await app.bind("DB", "db_2", { kind: "database" });
  assert.deepEqual(bind.last.body, { name: "DB", kind: "database", id: "db_2" });
  await assert.rejects(app.bind("DB", "db_2"), TypeError);
  await app.bind("SUPPORT", nc.Agent.fromId("ag_1"));
  assert.deepEqual(bind.last.body, { name: "SUPPORT", kind: "agent", id: "ag_1" });
  assert.equal(bind.count, 5);
  const [binding, secret] = await app.bindings();
  assert.deepEqual([binding.name, binding.resourceName], ["DB", "booking-db"]);
  // What the code reads: a secret's keys under the binding's name.
  assert.deepEqual([binding.variables, secret.variables], [["DB"], ["SHIPPING_API_KEY"]]);
  assert.deepEqual(made.variables, []); // an answer that names none
  await app.unbind("CRM");
  assert.equal(unbind.count, 1);
});

test("secrets are write-only", async () => {
  const { api } = setup();
  const put = api.on("PUT", "/v1/projects/prj_1/secrets/MAPS_API_KEY", json(undefined, { status: 204 }));
  api.on("GET", "/v1/projects/prj_1/secrets", json(listing([
    { name: "MAPS_API_KEY", updated_at: "2026-09-25T10:00:00Z" }, { name: "SESSION_SECRET", updated_at: "2026-09-20T10:00:00Z" },
  ])));
  const remove = api.on("DELETE", "/v1/projects/prj_1/secrets/MAPS_API_KEY", json(undefined, { status: 204 }));
  const app = nc.Project.fromId("prj_1", { user: USER_ID });
  await app.secrets.set("MAPS_API_KEY", "key_1");
  assert.deepEqual(put.last.body, { value: "key_1" });
  assert.equal(put.last.headers.get("NoClick-User"), USER_ID);
  const secrets = await app.secrets.list();
  assert.deepEqual(Object.keys(secrets), ["MAPS_API_KEY", "SESSION_SECRET"]);
  assert.equal(secrets.MAPS_API_KEY?.getUTCDate(), 25);
  await app.secrets.delete("MAPS_API_KEY");
  assert.equal(remove.count, 1);
});

test("schedules take a Cron and a path; pause, resume, runNow, delete", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/projects/prj_1/schedules", json(SCHEDULE));
  api.on("GET", "/v1/projects/prj_1/schedules", json(listing([{ ...SCHEDULE, status: "paused", paused_reason: "5 identical failures in 30 minutes", last_status: "failed", last_error: "Answered 500." }])));
  const pause = api.on("POST", "/v1/schedules/sch_1/pause", json({ ...SCHEDULE, status: "paused" }));
  const resume = api.on("POST", "/v1/schedules/sch_1/resume", json(SCHEDULE));
  const run = api.on("POST", "/v1/schedules/sch_1/run", json({ ...SCHEDULE, last_status: "succeeded", last_run: "2026-09-25T10:05:00Z" }));
  const remove = api.on("DELETE", "/v1/schedules/sch_1", json(undefined, { status: 204 }));
  const app = nc.Project.fromId("prj_1");
  const reminders = await app.schedule(new nc.Cron("0 9 * * 1-5", { tz: "America/New_York", message: "for an agent" }), { path: "/jobs/reminders" });
  // An app's schedule calls a path: a Cron's message (an agent's turn) isn't sent.
  assert.deepEqual(create.last.body, { cron: "0 9 * * 1-5", tz: "America/New_York", path: "/jobs/reminders" });
  assert.equal(reminders.nextRun?.getUTCHours(), 13);
  await app.schedule(new nc.Cron("0 * * * *"), { path: "/jobs/sync", name: "hourly-sync" });
  assert.deepEqual(create.last.body, { cron: "0 * * * *", tz: "UTC", path: "/jobs/sync", name: "hourly-sync" });

  const [paused] = await app.schedules();
  assert.deepEqual([paused.status, paused.lastStatus, paused.pausedReason, paused.lastError], ["paused", "failed", "5 identical failures in 30 minutes", "Answered 500."]);
  assert.equal((await paused.pause()).status, "paused");
  assert.equal((await paused.resume()).status, "active");
  assert.equal((await paused.runNow()).lastStatus, "succeeded");
  assert.deepEqual([pause.count, resume.count, run.count], [1, 1, 1]);
  await nc.Schedule.fromId("sch_1").delete();
  assert.equal(remove.count, 1);
});

test("domains, logs, usage, export and delete", async () => {
  const { api } = setup();
  const domain = { object: "domain", id: "dom_1", name: "acmebooking.com", source: "bought", status: "active", records: [], serves: [], user_id: null };
  const add = api.on("POST", "/v1/projects/prj_1/domains", json(domain));
  api.on("GET", "/v1/projects/prj_1/domains", json(listing([domain])));
  const logs = api.on("GET", "/v1/projects/prj_1/logs", json(listing([{ at: "2026-09-25T10:00:00Z", level: "error", message: "SQLITE_BUSY", deployment_id: "dep_1", environment: "preview", request_id: "r1", status: null }])));
  api.on("GET", "/v1/projects/prj_1/usage", json({ requests: 18342, cpu_ms: 912000, usd: 1.84, period_start: "2026-09-01T00:00:00Z" }), json({ requests: 1 }));
  api.on("POST", "/v1/projects/prj_1/export", json(operation({ id: "op_x", kind: "project.export", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_x/wait", json(operation({
    id: "op_x", kind: "project.export", status: "succeeded", result: { url: "https://exports.noclick.app/booking.zip", contents: [{ kind: "database", name: "booking-db", detail: "A SQL dump." }] },
  })));
  const remove = api.on("DELETE", "/v1/projects/prj_1", json(trashed("project", "prj_1", "booking")));
  const app = nc.Project.fromId("prj_1");

  const dropped = api.on("DELETE", "/v1/projects/prj_1/domains/book.acme.com", json({ object: "project_domain", name: "book.acme.com", deleted: true }));
  const added = await app.addDomain("acmebooking.com");
  assert.deepEqual(add.last.body, { name: "acmebooking.com" });
  assert.ok(added instanceof nc.Domain);
  assert.deepEqual((await app.domains()).map((d) => d.name), ["acmebooking.com"]);
  await app.removeDomain("book.acme.com");
  assert.equal(dropped.count, 1);

  const [line] = await app.logs({ since: new Date("2026-09-25T09:00:00Z"), level: "error", deployment: nc.Deployment.fromId("dep_1"), limit: 50, environment: "preview" });
  const q = logs.last.query;
  assert.deepEqual([q.get("since"), q.get("level"), q.get("deployment_id"), q.get("limit"), q.get("environment")], ["2026-09-25T09:00:00.000Z", "error", "dep_1", "50", "preview"]);
  assert.deepEqual([line.level, line.message, line.deploymentId], ["error", "SQLITE_BUSY", "dep_1"]);
  assert.deepEqual([line.environment, line.requestId, line.status], ["preview", "r1", null]);
  await app.logs();
  assert.deepEqual([...logs.last.query.entries()], [["limit", "100"]]);

  const used = await app.usage();
  assert.deepEqual([used.requests, used.cpuMs, used.usd, used.periodStart?.getUTCMonth()], [18342, 912000, 1.84, 8]);
  assert.deepEqual([used.budgetUsd, used.limitedBy, used.byType], [null, null, {}]);
  await assert.rejects(app.usage(), /cpu_ms/);

  const bundle = await (await app.export()).wait();
  assert.equal(bundle.contents[0].name, "booking-db");

  const previewed = api.on("POST", "/v1/delete_previews", json({ object: "delete_preview", confirm_token: "nk_cfm_1",
    expires_in_s: 600, impact: { deletes: "Moves booking to the trash.", depends_on_it: ["It stops at book.acme.com."],
      data_lost: [], stops_billing: [], reversible: true, undo: "Restorable for 30 days." } }));
  const preview = await app.previewDelete({ deleteData: true });
  assert.deepEqual(previewed.last.body, { method: "DELETE", path: "/v1/projects/prj_1?delete_data=true" });
  assert.deepEqual([preview.deletes, preview.dependsOnIt, preview.reversible, preview.undo, preview.confirmToken],
    ["Moves booking to the trash.", ["It stops at book.acme.com."], true, "Restorable for 30 days.", "nk_cfm_1"]);
  assert.equal(remove.count, 0);  // nothing deleted by asking

  const item = await app.delete();
  assert.equal(remove.last.query.has("delete_data"), false);
  assert.deepEqual([item instanceof nc.TrashItem, item.kind, item.resourceId], [true, "project", "prj_1"]);
  await app.delete({ deleteData: true });
  assert.equal(remove.last.query.get("delete_data"), "true");
});

// --- an app at run time: its budget, its AI and its agent --------------------------

test("a budget is part of the app's definition, and update changes it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects", json(listing([{ ...PROJECT, budget_usd_per_month: 10 }])));
  const create = api.on("POST", "/v1/projects", (call: Call) => json({ ...PROJECT, ...(call.body as object) }));
  const patch = api.on("PATCH", "/v1/projects/prj_1", (call: Call) => json({ ...PROJECT, ...(call.body as object) }));

  const app = await nc.Project.create("booking", { repo: "repo_1", budgetUsdPerMonth: 25 });
  assert.deepEqual(create.last.body, { name: "booking", repo_id: "repo_1", budget_usd_per_month: 25 });
  assert.equal(app.budgetUsdPerMonth, 25);

  const defined = await nc.Project.fromName("booking", { repo: "repo_1", budgetUsdPerMonth: 25, createIfMissing: true }).hydrate();
  assert.equal(defined.budgetUsdPerMonth, 25);
  assert.deepEqual(patch.last.body, { budget_usd_per_month: 25 }); // only what differs
  await nc.Project.fromName("booking", { repo: "repo_1", createIfMissing: true }).hydrate();
  assert.equal(patch.count, 1); // a budget left out is never changed
  await nc.Project.fromName("booking", { budgetUsdPerMonth: null, createIfMissing: true }).hydrate();
  assert.deepEqual(patch.last.body, { budget_usd_per_month: null }); // null removes it

  const byId = nc.Project.fromId("prj_1");
  assert.equal(await byId.update({ budgetUsdPerMonth: 50, repo: nc.Repo.fromId("repo_2"), productionBranch: "release" }), byId);
  assert.deepEqual(patch.last.body, { repo_id: "repo_2", production_branch: "release", budget_usd_per_month: 50 });
  assert.deepEqual([byId.budgetUsdPerMonth, byId.productionBranch, byId.repoId], [50, "release", "repo_2"]);
});

test("usage shows spend against the budget and what stops the paid calls", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1/usage", json({
    requests: 18342, cpu_ms: 912000, usd: 25.04, period_start: "2026-10-01T00:00:00Z", budget_usd: 25, limited_by: "project",
    by_type: { apps: 1.84, ai: 14.2, model_tokens: 6.9, tool_runs: 1.1, databases: 0.6, app_email: 0.4 },
  }));
  const used = await nc.Project.fromId("prj_1").usage();
  assert.deepEqual([used.usd, used.budgetUsd, used.limitedBy, used.byType.ai], [25.04, 25, "project", 14.2]);
  assert.ok(Math.abs(Object.values(used.byType).reduce((a, b) => a + b, 0) - used.usd) < 1e-9);
});

test("analytics reads the app's traffic by day against the period before", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/projects/prj_1/analytics", json({
    object: "project_analytics", project_id: "prj_1", period: "7d", environment: "production", interval: "day",
    tz: "Europe/Paris", since: "2026-10-09T22:00:00+00:00", until: "2026-10-16T09:00:00+00:00", requests: 1204, errors: 3,
    error_rate: 0.0025, by_status: { "200": 1180, "404": 21, "500": 3 }, p50_ms: 42, p95_ms: 310.5,
    by_source: { browser: 1100, automated: 104 }, noclick_requests: 12,
    series: [{ at: "2026-10-09T22:00:00+00:00", requests: 160, errors: 0 }, { at: "2026-10-10T22:00:00+00:00", requests: 1044, errors: 3 }],
    top_paths: [
      { path: "/", requests: 600, browser_requests: 540, errors: 0, p95_ms: 120 },
      { path: "/api/book", requests: 90, browser_requests: 88, errors: 3, p95_ms: null },
    ],
    previous_requests: 980, previous_errors: 7, sampled: false,
  }));
  const app = nc.Project.fromId("prj_1");
  const week = await app.analytics({ tz: "Europe/Paris" });
  assert.deepEqual([read.last.query.get("period"), read.last.query.get("environment"), read.last.query.get("tz")], ["7d", "production", "Europe/Paris"]);
  assert.deepEqual([week.requests, week.previousRequests, week.errors, week.errorRate, week.interval], [1204, 980, 3, 0.0025, "day"]);
  assert.deepEqual([week.p50Ms, week.p95Ms, week.byStatus["404"]], [42, 310.5, 21]);
  assert.equal(week.series[0].at?.toISOString(), "2026-10-09T22:00:00.000Z");
  assert.deepEqual([week.series[1].requests, week.series[1].errors], [1044, 3]);
  assert.deepEqual(week.topPaths, [
    { path: "/", requests: 600, errors: 0, p95Ms: 120, browserRequests: 540 },
    { path: "/api/book", requests: 90, errors: 3, p95Ms: null, browserRequests: 88 },
  ]);
  assert.deepEqual([week.bySource, week.noclickRequests], [{ browser: 1100, automated: 104 }, 12]);
  await app.analytics({ period: "24h", environment: "all" });
  assert.deepEqual([read.last.query.get("period"), read.last.query.get("environment"), read.last.query.get("tz")], ["24h", "all", null]);
});

test("analyticsSummary reads every app's week at once", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/projects/analytics/summary", json({
    object: "project_analytics_summary", period: "7d", tz: "Europe/Paris", since: "2026-10-09T22:00:00+00:00",
    until: "2026-10-16T09:00:00+00:00", sampled: false,
    data: [
      { project_id: "prj_2", requests: 0, browser_requests: 0, errors: 0, noclick_requests: 6 },
      { project_id: "prj_1", requests: 1204, browser_requests: 1100, errors: 3, noclick_requests: 12 },
    ],
  }));
  const week = await nc.Project.analyticsSummary({ tz: "Europe/Paris", userFilter: nc.NO_USER });
  assert.deepEqual([read.last.query.get("period"), read.last.query.get("tz"), read.last.query.get("user_id")], ["7d", "Europe/Paris", "none"]);
  assert.equal(read.last.headers.get("noclick-user"), null);
  assert.deepEqual(week.apps, [
    { projectId: "prj_2", requests: 0, errors: 0, browserRequests: 0, noclickRequests: 6 },
    { projectId: "prj_1", requests: 1204, errors: 3, browserRequests: 1100, noclickRequests: 12 },
  ]);
  assert.deepEqual(week.of("prj_gone"), { projectId: "prj_gone", requests: 0, errors: 0, browserRequests: 0, noclickRequests: 0 });
  assert.equal(week.since?.toISOString(), "2026-10-09T22:00:00.000Z");
});

async function asTheApp(
  api: ReturnType<typeof setup>["api"], run: (app: nc.Project) => Promise<void>, project: object = PROJECT,
): Promise<void> {
  api.on("GET", "/v1/projects/current", json(project));
  const realFetch = globalThis.fetch;
  process.env.NOCLICK_DEPLOYMENT_TOKEN = "nk_dep_123";
  process.env.NOCLICK_API_URL = BASE;
  globalThis.fetch = api.fetch as typeof fetch;
  try {
    await run(nc.Project.current());
  } finally {
    globalThis.fetch = realFetch;
    delete process.env.NOCLICK_DEPLOYMENT_TOKEN;
    delete process.env.NOCLICK_API_URL;
  }
}

test("the running app talks to its bound agent as itself", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1/bindings/SUPPORT", json({ name: "SUPPORT", kind: "agent", resource_id: "ag_1", resource_name: "support" }));
  api.on("GET", "/v1/projects/prj_1/bindings/DB", json({ name: "DB", kind: "database", resource_id: "db_1" }));
  api.on("GET", "/v1/agents/ag_1", json({ object: "agent", id: "ag_1", name: "support", user_id: null }));
  const send = api.on("POST", "/v1/agents/ag_1/messages", json(operation({ id: "op_t", kind: "agent.message", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_t/wait", json(operation({
    id: "op_t", kind: "agent.message", status: "succeeded", result: { text: "Saturday at 10 works. Moved.", conversation: "app:prj_1:visitor-91c2" },
  })));
  await asTheApp(api, async (app) => {
    const support = await app.agent("SUPPORT");
    assert.ok(support instanceof nc.Agent);
    const reply = await support.message("Can I move my booking to Saturday?", { conversation: "visitor-91c2" });
    assert.deepEqual([reply.text, reply.conversation], ["Saturday at 10 works. Moved.", "app:prj_1:visitor-91c2"]); // the app's own thread
    assert.equal(send.last.headers.get("Authorization"), "Bearer nk_dep_123");
    assert.equal(send.last.headers.has("NoClick-User"), false);
    assert.deepEqual(send.last.body, { text: "Can I move my booking to Saturday?", conversation: "visitor-91c2" });
    await assert.rejects(app.agent("DB"), /bound to a database, not an agent/);
  });
});

test("a user's app reaches what is bound to it without naming the user its credential acts for", async () => {
  const { api } = setup();
  const OWNER = "wa-120363";
  const binding = api.on("GET", "/v1/projects/prj_1/bindings/DB", json({ name: "DB", kind: "database", resource_id: "db_1" }));
  api.on("GET", "/v1/projects/prj_1/bindings/SUPPORT", json({ name: "SUPPORT", kind: "agent", resource_id: "ag_1" }));
  const loaded = api.on("GET", "/v1/databases/db_1", json({ object: "database", id: "db_1", name: "notes", user_id: OWNER }));
  const query = api.on("POST", "/v1/databases/db_1/query", json({ object: "query_result", columns: ["n"], rows: [{ n: 1 }] }));
  api.on("GET", "/v1/agents/ag_1", json({ object: "agent", id: "ag_1", name: "support", user_id: OWNER }));
  const send = api.on("POST", "/v1/agents/ag_1/messages", json(operation({ id: "op_t", kind: "agent.message", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_t/wait", json(operation({ id: "op_t", kind: "agent.message", status: "succeeded", result: { text: "Hi" } })));
  await asTheApp(api, async (app) => {
    const db = await app.database("DB");
    await db.query("select 1 as n");
    await db.hydrate(); // what it loads names its user, which still isn't sent
    await db.query("select 1 as n");
    await (await app.agent("SUPPORT")).message("Hello", { conversation: "visitor-1" });
    for (const call of [binding.last, loaded.last, ...query.calls, send.last]) {
      assert.equal(call.headers.get("Authorization"), "Bearer nk_dep_123");
      assert.equal(call.headers.has("NoClick-User"), false, `${call.method} ${call.path}`);
    }
  }, { ...PROJECT, user_id: OWNER });
  // With a key of your own, the same database's calls name its user.
  const db = await nc.Database.fromId("db_1", { user: null }).hydrate();
  await db.query("select 1 as n");
  assert.equal(query.last.headers.get("NoClick-User"), OWNER);
});

test("app.ai is AI acting as the app, and only the app", async () => {
  const { api } = setup();
  const chat = api.on("POST", "/v1/ai/chat/completions", () => new Response(
    'data: {"choices": [{"index": 0, "delta": {"content": "Great class, cold room."}, "finish_reason": "stop"}], "cost_usd": 0.0002}\n\ndata: [DONE]\n\n',
    { headers: { "content-type": "text/event-stream" } },
  ));
  const embed = api.on("POST", "/v1/ai/embeddings", json({ data: [{ index: 0, embedding: [0.1, 0.2] }] }));
  const models = api.on("GET", "/v1/ai/models", json(listing([{ id: "agent:support", kind: "agent" }])));

  await assert.rejects(nc.Project.fromId("prj_1").ai.chat("Hi"), /Project\.current/); // your key never spends as the app
  assert.equal(chat.count, 0);

  await asTheApp(api, async (app) => {
    const reply = await app.ai.chat("Summarize in one line: the class was great but the room was cold.", { maxTokens: 60 });
    assert.deepEqual([reply.text, reply.costUsd], ["Great class, cold room.", 0.0002]);
    assert.equal(chat.last.headers.get("Authorization"), "Bearer nk_dep_123");
    assert.equal(chat.last.headers.has("NoClick-User"), false);
    assert.equal((chat.last.body as { max_tokens: number }).max_tokens, 60);
    assert.deepEqual((await app.ai.embed("yoga")).vectors, [[0.1, 0.2]]);
    assert.deepEqual((embed.last.body as { input: string[] }).input, ["yoga"]);
    const [bound] = await app.ai.models({ kind: "agent" });
    assert.equal(bound.id, "agent:support");
    assert.equal(models.last.query.get("kind"), "agent");
    assert.equal(app.ai.baseUrl, `${BASE}/v1/ai`);
    assert.deepEqual(await app.ai.headers(), { Authorization: "Bearer nk_dep_123" });
  });
});

test("a paid call past the app's budget names the app", async () => {
  const { api } = setup();
  api.on("POST", "/v1/ai/chat/completions", apiError(402, "spend_cap_exceeded", "booking reached its $25.00 monthly budget.", {
    next_step: "Raise it with app.update({ budgetUsdPerMonth }), or wait until it resets on Nov 1.",
    scope: "project", cap: 25, spent: 25.04, project_id: "prj_1", project: "booking",
  }));
  await asTheApp(api, async (app) => {
    const err = await app.ai.chat("Summarize: ...").then(() => null, (e: unknown) => e);
    assert.ok(err instanceof nc.SpendCapExceeded);
    assert.deepEqual([err.scope, err.cap, err.spent, err.details.project, err.details.project_id], ["project", 25, 25.04, "booking", "prj_1"]);
  });
});

test("Usage.limits lists app budgets, and spend groups by app", async () => {
  const { api } = setup();
  api.on("GET", "/v1/usage/limits", json({
    period_start: "2026-10-01T00:00:00Z", resets_at: "2026-11-01T00:00:00Z", keys: [], users: [], agents: [],
    projects: [{ id: "prj_1", name: "booking", user_id: null, budget: 25, spent: 25.04 }],
  }));
  const grouped = api.on("GET", "/v1/usage", json({ period: "month", total_usd: 25.04, group_by: "project", groups: [{ id: "prj_1", usd: 25.04, events: 812 }] }));
  const [budget] = (await nc.Usage.limits()).projects;
  assert.deepEqual([budget.id, budget.name, budget.userId, budget.budget, budget.spent], ["prj_1", "booking", null, 25, 25.04]);
  const month = await nc.Usage.get({ groupBy: "project" });
  assert.equal(grouped.last.query.get("group_by"), "project");
  assert.equal(month.group("prj_1").usd, 25.04);
});

test("an operation resumed by id decodes a deploy and a GitHub export", async () => {
  const { api } = setup();
  api.on("GET", "/v1/operations/op_d/wait", json(operation({ id: "op_d", kind: "project.deploy", status: "succeeded", result: DEPLOYMENT })));
  api.on("GET", "/v1/operations/op_g/wait", json(operation({ id: "op_g", kind: "repo.export_to_github", status: "succeeded", result: { url: "https://github.com/a/b" } })));
  assert.ok((await nc.Operation.fromId("op_d").wait()) instanceof nc.Deployment);
  assert.equal(await nc.Operation.fromId("op_g").wait(), "https://github.com/a/b");
});

test("deployOnPush is part of the definition, and a deployment says what started it", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/projects", json({ ...PROJECT, deploy_on_push: "production" }));
  api.on("GET", "/v1/projects", json(listing([{ ...PROJECT, deploy_on_push: "off" }])));
  const patch = api.on("PATCH", "/v1/projects/prj_1", json({ ...PROJECT, deploy_on_push: "all" }));
  api.on("GET", "/v1/projects/prj_1/deployments", json(listing([{ ...DEPLOYMENT, status: "failed", started_by: "push", error: "The app's budget is used up." }])));
  const app = await nc.Project.create("booking", { repo: "repo_1", runtime: "container", framework: "python", deployOnPush: "production" });
  assert.deepEqual(create.last.body, { name: "booking", repo_id: "repo_1", runtime: "container", framework: "python", deploy_on_push: "production" });
  assert.equal(app.deployOnPush, "production");
  const defined = await nc.Project.fromName("booking", { deployOnPush: "all", createIfMissing: true }).hydrate();
  assert.equal(defined.deployOnPush, "all");
  assert.deepEqual(patch.last.body, { deploy_on_push: "all" });
  await nc.Project.fromName("booking", { createIfMissing: true }).hydrate();
  assert.equal(patch.count, 1); // left out, never changed
  await nc.Project.fromId("prj_1").update({ deployOnPush: "all" });
  assert.deepEqual(patch.last.body, { deploy_on_push: "all" });
  const [refused] = await nc.Project.fromId("prj_1").deployments();
  assert.deepEqual([refused.startedBy, refused.status, refused.error], ["push", "failed", "The app's budget is used up."]);
});
