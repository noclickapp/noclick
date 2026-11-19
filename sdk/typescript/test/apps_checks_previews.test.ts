// An app's check paths that ask its API, what a deploy and a preview say about themselves, the checks that wait,
// sign in and review, where a deployment serves, how far behind a log read can be, and sign-in committed without a
// deploy.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, operation, setup } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const DEPLOYMENT = {
  object: "deployment", id: "dep_1", project_id: "prj_1", branch: "main", commit: "9f2c1ab", commit_message: "Add the booking form",
  status: "ready", url: "https://booking.noclick.site", production: true, environment: "production", error: null,
  serves: { production: "https://booking.noclick.site", preview: null },
  created_at: "2026-09-25T09:01:00Z", ready_at: "2026-09-25T09:02:10Z",
};
const PROJECT = {
  object: "project", id: "prj_1", name: "booking", url: "https://booking.noclick.site", repo_id: "repo_1",
  production_branch: "main", preview_resources: "branch", check_paths: [], production: DEPLOYMENT, user_id: null,
  created_at: "2026-09-20T10:00:00Z",
};
const CHECK_PATHS: nc.CheckPath[] = ["/", { path: "/api/health", status: 200 }, { path: "/api/bookings", json: true }];

test("an app is made with its preview data and check paths, and kept to them", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/projects", json({ ...PROJECT, check_paths: CHECK_PATHS }));
  const app = await nc.Project.create("booking", { repo: "repo_1", previewResources: "shared", checkPaths: CHECK_PATHS });
  assert.deepEqual(create.last.body, { name: "booking", repo_id: "repo_1", preview_resources: "shared", check_paths: CHECK_PATHS });
  assert.deepEqual(app.checkPaths, CHECK_PATHS);

  // Your code is the definition: an app whose check paths or preview resources differ is brought in step.
  api.on("GET", "/v1/projects", json(listing([PROJECT])));
  const patch = api.on("PATCH", "/v1/projects/prj_1", (call: Call) => json({ ...PROJECT, ...(call.body as object) }));
  const defined = await nc.Project.fromName("booking", { previewResources: "shared", checkPaths: CHECK_PATHS, createIfMissing: true }).hydrate();
  assert.equal(defined.previewResources, "shared");
  assert.deepEqual(patch.last.body, { preview_resources: "shared", check_paths: CHECK_PATHS });
  api.on("GET", "/v1/projects", json(listing([{ ...PROJECT, check_paths: CHECK_PATHS }])));
  await nc.Project.fromName("booking", { checkPaths: [...CHECK_PATHS], createIfMissing: true }).hydrate();
  assert.equal(patch.count, 1); // the same paths change nothing

  await nc.Project.fromId("prj_1").update({ checkPaths: [{ path: "/api/health", status: 204 }] });
  assert.deepEqual(patch.last.body, { check_paths: [{ path: "/api/health", status: 204 }] });
});

test("a deploy says whether its code answered and what a preview writes to", async () => {
  const { api } = setup();
  const deploy = api.on("POST", "/v1/projects/prj_1/deployments", json(operation({ id: "op_d", kind: "project.deploy", status: "queued" }), { status: 202 }));
  const previewData = "This preview writes to its own copy of DB (database), made at its first write.";
  const unchecked = "Static files answered every path asked (/), so the app's server code never ran.";
  api.on("GET", "/v1/operations/op_d/wait", json(operation({
    id: "op_d", kind: "project.deploy", status: "succeeded", result: {
      ...DEPLOYMENT, id: "dep_2", branch: "new-form", production: false, environment: "preview",
      url: "https://new-form--booking.noclick.site", serves: { production: null, preview: "https://new-form--booking.noclick.site" },
      code_unchecked: unchecked, preview_data: previewData,
    },
  })));
  const preview = await (await nc.Project.fromId("prj_1").deploy({ branch: "new-form" })).wait();
  assert.deepEqual(deploy.last.body, { branch: "new-form" });
  assert.deepEqual([preview.codeUnchecked, preview.previewData, preview.warning], [unchecked, previewData, null]);
  assert.deepEqual(preview.serves, { production: null, preview: "https://new-form--booking.noclick.site" });

  api.on("GET", "/v1/operations/op_d/wait", json(operation({
    id: "op_d", kind: "project.deploy", status: "succeeded",
    result: {
      ...DEPLOYMENT, warning: "It's live, but https://booking.noclick.site/api/health answered 500, not 200.",
      next_step: "Read the app's runtime log, fix the cause, then deploy again.",
    },
  })));
  const live = await (await nc.Project.fromId("prj_1").deploy()).wait();
  assert.ok(live.warning?.endsWith("answered 500, not 200."));
  assert.equal(live.nextStep, "Read the app's runtime log, fix the cause, then deploy again.");
  assert.deepEqual([live.codeUnchecked, live.previewData, preview.nextStep], [null, null, null]);

  // A deployment read later names where it serves, and a promoted preview serves both.
  api.on("GET", "/v1/deployments/dep_3", json({
    ...DEPLOYMENT, id: "dep_3", environment: "preview",
    serves: { production: "https://booking.noclick.site", preview: "https://new-form--booking.noclick.site" },
    check: { operation_id: "op_c", passed: true, url: "https://booking.noclick.site", checked_at: "2026-09-25T09:05:00Z", paths: [], code_unchecked: unchecked },
  }));
  const promoted = await nc.Deployment.get("dep_3");
  assert.deepEqual([promoted.serves?.production, promoted.environment], ["https://booking.noclick.site", "preview"]);
  assert.deepEqual([promoted.lastCheck?.code_unchecked, promoted.warning], [unchecked, null]);
});

const CHECK = {
  object: "deployment_check", deployment_id: "dep_1", url: "https://booking.noclick.site", passed: false,
  checked_at: "2026-09-25T09:05:00Z", cost_usd: 0.0042, paths: [
    {
      path: "/", url: "https://booking.noclick.site/", ok: false, problem: "A picture it shows doesn't load: /images/hero.jpg.",
      status: 200, load_ms: 840, title: "Booking", broken_images: ["/images/hero.jpg"], console_errors: [],
      screenshot: { object: "file", id: "f_1", url: "https://f.test/1.png" }, undeliverable_emails: ["hello@bistro.invalid-domain.com"],
    },
    {
      path: "/api/health", url: "https://booking.noclick.site/api/health", ok: true, problem: null, status: 200, load_ms: 95,
      title: null, broken_images: [], console_errors: [], screenshot: null, undeliverable_emails: [], expected: { status: 200 },
    },
  ],
  review: {
    model: "openrouter/anthropic/claude-haiku-5.5", scores: { task: 4, forms: 3 },
    issues: [{ where: "/", what: "The date field has no label", fix: "Label it" }], passed: false, cost_usd: 0.003,
  },
};

test("a check asks requests, waits, signs in and reviews", async () => {
  const { api } = setup();
  const check = api.on("POST", "/v1/deployments/dep_1/check", json(operation({ id: "op_c", kind: "deployment.check", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_c/wait", json(operation({ id: "op_c", kind: "deployment.check", status: "succeeded", result: CHECK })));

  const deployment = nc.Deployment.fromId("dep_1");
  const checked = await (await deployment.check(["/", { path: "/api/health", status: 200 }], {
    review: { brief: "A booking page for one bistro", rubric: "app" }, waitFor: "main#booking", settleMs: 2500,
    headers: { Authorization: "Bearer test-session" }, cookies: [{ name: "session", value: "s_1" }],
  })).wait();
  assert.deepEqual(check.last.body, {
    paths: ["/", { path: "/api/health", status: 200 }], review: { brief: "A booking page for one bistro", rubric: "app" },
    wait_for: "main#booking", settle_ms: 2500, headers: { Authorization: "Bearer test-session" }, cookies: [{ name: "session", value: "s_1" }],
  });

  const [page, health] = checked.paths;
  assert.deepEqual([page.ok, page.brokenImages, page.undeliverableEmails, page.expected], [false, ["/images/hero.jpg"], ["hello@bistro.invalid-domain.com"], null]);
  assert.deepEqual([health.ok, health.expected, health.screenshot, health.loadMs], [true, { status: 200 }, null, 95]);
  const review = checked.review!;
  assert.deepEqual([review.passed, review.scores, review.claims, review.error, review.costUsd], [false, { task: 4, forms: 3 }, [], null, 0.003]);
  assert.deepEqual(review.issues.map((issue) => issue.fix), ["Label it"]);
  assert.equal(checked.codeUnchecked, null);

  // Its code never ran: every path passed from the release's files.
  api.on("GET", "/v1/operations/op_c/wait", json(operation({
    id: "op_c", kind: "deployment.check", status: "succeeded",
    result: { ...CHECK, passed: true, review: null, code_unchecked: "Static files answered every path." },
  })));
  const passed = await (await deployment.check(["/"])).wait();
  assert.deepEqual(check.last.body, { paths: ["/"] });
  assert.deepEqual([passed.codeUnchecked, passed.review], ["Static files answered every path.", null]);

  await deployment.check(undefined, { review: { brief: "A bistro in Lyon", facts: "Open 7-11pm" } });
  assert.deepEqual(check.last.body, { review: { brief: "A bistro in Lyon", facts: "Open 7-11pm" } });
  await deployment.check();
  assert.equal(check.last.body, null); // the app's own check paths
});

test("a review that couldn't answer says why", async () => {
  const { api } = setup();
  api.on("POST", "/v1/deployments/dep_1/check", json(operation({ id: "op_c", kind: "deployment.check", status: "running" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_c/wait", json(operation({
    id: "op_c", kind: "deployment.check", status: "succeeded", result: {
      ...CHECK, review: { model: "openrouter/anthropic/claude-haiku-5.5", error: "No page loaded, so there was nothing to look at.", cost_usd: 0 },
    },
  })));
  const { review } = await (await nc.Deployment.fromId("dep_1").check(["/"], { review: { brief: "A bistro" } })).wait();
  assert.deepEqual([review?.passed, review?.scores, review?.issues, review?.error], [null, {}, [], "No page loaded, so there was nothing to look at."]);
});

test("log reads say how far behind they can be", async () => {
  const { api } = setup();
  const line = {
    at: "2026-09-25T10:00:00Z", level: "error", message: "GET /api/health -> 500", deployment_id: "dep_1",
    environment: "preview", request_id: "r1", status: 500,
  };
  const appLogs = api.on("GET", "/v1/projects/prj_1/logs", json({ ...listing([line]), delay_s: 60 }));
  const lines = await nc.Project.fromId("prj_1").logs({ environment: "preview" });
  assert.ok(Array.isArray(lines));
  assert.deepEqual([lines.delayS, lines[0].status, lines[0].requestId], [60, 500, "r1"]);
  assert.equal(appLogs.last.query.get("environment"), "preview");

  const runtime = api.on("GET", "/v1/deployments/dep_1/logs", json({ ...listing([line]), delay_s: 30 }));
  const tail = await nc.Deployment.fromId("dep_1").logs({ kind: "runtime", level: "error", environment: "production", limit: 5 });
  assert.deepEqual(Object.fromEntries(runtime.last.query), { kind: "runtime", level: "error", environment: "production", limit: "5" });
  assert.deepEqual([tail.delayS, tail.map((l) => l.message)], [30, ["GET /api/health -> 500"]]);

  // A build's log is kept whole as it's written: no delay to speak of.
  const build = api.on("GET", "/v1/deployments/dep_1/logs", json(listing([{ ...line, level: "info", message: "Building" }])));
  const built = await nc.Deployment.fromId("dep_1").logs();
  assert.deepEqual(Object.fromEntries(build.last.query), { kind: "build" });
  assert.deepEqual([built.delayS, built[0].message], [null, "Building"]);
});

test("sign-in commits without deploying when asked", async () => {
  const { api } = setup();
  const enable = api.on("POST", "/v1/projects/prj_1/sign_in", json(operation({ kind: "project.sign_in.enable", status: "running" })));
  const upgrade = api.on("POST", "/v1/projects/prj_1/sign_in/upgrade", json(operation({ kind: "project.sign_in.upgrade", status: "running" })));
  const app = nc.Project.fromId("prj_1");
  await app.signIn.enable(["email"], { deploy: false });
  assert.deepEqual(enable.last.body, { providers: ["email"], users_table: "users", deploy: false });
  await app.signIn.enable(["email"], { deploy: true });
  assert.equal("deploy" in (enable.last.body as object), false); // deployed, as before
  await app.signIn.upgrade({ deploy: false });
  assert.deepEqual(upgrade.last.body, { deploy: false });
  await app.signIn.upgrade({ branch: "sign-in-update" });
  assert.deepEqual(upgrade.last.body, { branch: "sign-in-update" });
});

test("an app's previews are kept to a link, and its deploy and owner hand the link out", async () => {
  const { api } = setup();
  const said = "Its previews stay public until NoClick's front door is updated.";
  const patch = api.on("PATCH", "/v1/projects/prj_1", (call: Call) => json({ ...PROJECT, ...(call.body as object), notes: [said] }));
  const app = await nc.Project.fromId("prj_1").update({ previewAccess: "link", previewPublicPaths: ["/api/webhooks/*"] });
  assert.deepEqual(patch.last.body, { preview_access: "link", preview_public_paths: ["/api/webhooks/*"] });
  assert.deepEqual([app.previewAccess, app.previewPublicPaths, app.raw.notes], ["link", ["/api/webhooks/*"], [said]]);

  const linkUrl = "https://new-form--booking.noclick.site/?preview=p1~1800604800~prj_1~new-form--booking.noclick.site~ab";
  const made = api.on("POST", "/v1/projects/prj_1/previews/link", json({
    object: "preview_link", project_id: "prj_1", branch: "new-form", url: linkUrl,
    preview_url: "https://new-form--booking.noclick.site", preview_access: "link", expires_at: "2027-01-21T08:00:00Z",
  }));
  const link = await app.previewLink({ branch: "new-form", expiresIn: 3600 });
  assert.deepEqual(made.last.body, { branch: "new-form", expires_in: 3600 });
  assert.deepEqual([link.url, link.branch, link.previewUrl, link.previewAccess], [linkUrl, "new-form", "https://new-form--booking.noclick.site", "link"]);
  assert.equal(link.expiresAt?.getUTCFullYear(), 2027);
  await app.previewLink();
  assert.deepEqual(made.last.body, {});

  api.on("POST", "/v1/projects/prj_1/deployments", json(operation({ id: "op_p", kind: "project.deploy", status: "queued" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_p/wait", json(operation({
    id: "op_p", kind: "project.deploy", status: "succeeded", result: {
      ...DEPLOYMENT, id: "dep_3", branch: "new-form", production: false, environment: "preview",
      url: "https://new-form--booking.noclick.site", preview_link: linkUrl,
    },
  })));
  const preview = await (await app.deploy({ branch: "new-form" })).wait();
  assert.deepEqual([preview.url, preview.previewLink], ["https://new-form--booking.noclick.site", linkUrl]);
  assert.equal(app.production?.previewLink, null); // production is always public
});

test("stopping an app's preview links answers the app with what it did", async () => {
  const { api } = setup();
  const said = "Every link to its previews made before now stops opening them within 30 seconds.";
  const stop = api.on("POST", "/v1/projects/prj_1/previews/links/revoke", json({ ...PROJECT, preview_access: "link", notes: [said] }));
  const app = nc.Project.fromId("prj_1");
  assert.equal(await app.revokePreviewLinks(), app);
  assert.equal(stop.calls.length, 1);
  assert.deepEqual([app.previewAccess, app.raw.notes], ["link", [said]]);
});
