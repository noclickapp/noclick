// An app edited live: its switch, its session started (once, with the link that opens it in live mode), commands run
// in it with what each edit did in the open pages, its edits read back, and its end, which deploys only once its build
// and check pass.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, operation, setup } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const PROJECT = {
  object: "project", id: "prj_1", name: "larkspur", url: "https://larkspur.noclick.site", repo_id: "repo_1",
  production_branch: "main", preview_resources: "branch", check_paths: [], live_editing: false, production: null,
  user_id: null, created_at: "2026-10-20T10:00:00Z",
};
const HOT = {
  seq: 12, boot: "b-7f3a", at: 1793040000180, files: ["src/render.js"], outcome: "hot",
  updates: [{ type: "js-update", path: "/src/render.js", acceptedPath: "/src/render.js" }],
  clients: 2, applied: { ok: 2, failed: 0, errors: [] },
};
const RELOAD = {
  seq: 13, boot: "b-7f3a", at: 1793040003000, files: ["src/main.js"], outcome: "reload",
  reload: { path: "*", triggeredBy: "/src/main.js", reason: "no-boundary", chain: ["/src/main.js", "/index.html"] }, clients: 1,
};
const ERROR = {
  seq: 14, boot: "b-7f3a", at: 1793040007000, files: ["src/update.js"], outcome: "error",
  error: { message: "Unexpected token", file: "/site/src/update.js", loc: { line: 4, column: 9 }, plugin: "vite:esbuild" }, clients: 1,
};
const SESSION = {
  object: "live_session", id: "ls_1", project_id: "prj_1", state: "live", phase: null, boot_id: "b-7f3a", workdir: "/site",
  mode: "vite", url: "https://larkspur.noclick.site", viewers: { connected: 1, visible: 1 },
  git: { branch: "noclick-live", head: null, pushed: null, dirty: false, state: "clean" },
  data: [{
    kind: "database", name: "DB", production_id: "db_1", copy_id: null, with_data: true,
    note: "A copy with production's data, made at the session's first write.",
  }],
  readiness: { ready: true, mode: "vite", reasons: [] }, edits: { count: 3, hot: 2, reload: 1, error: 0, last_seq: 13 },
  timings: { live_ms: 4300 }, where: { do_colo: "IAD", container_colo: "IAD" }, worker_version: "v1",
  started_at: "2026-10-27T09:00:00Z", live_at: "2026-10-27T09:00:04Z", ended_at: null, end_reason: null, error: null,
  release: null, needs_source: null,
  limits: { idle_grace_s: 30, idle_end_s: 30, max_quiet_with_viewers_s: 14400, max_session_s: 43200, hold_warming_s: 30, end_grace_s: 900 },
};
const ENTER_URL = "https://larkspur.noclick.site/__noclick/live/3hK9qLm2ZxR7tVb4NcW8pY";

test("the switch turns live editing on and says what keeps an app from it", async () => {
  const { api } = setup();
  const patch = api.on("PATCH", "/v1/projects/prj_1", (call: Call) =>
    json({ ...PROJECT, ...(call.body as object), live_editing_set_by: "owner" }));
  const app = nc.Project.fromId("prj_1");
  assert.equal(await app.update({ liveEditing: true }), app);
  assert.deepEqual(patch.last.body, { live_editing: true });
  assert.equal(app.liveEditing, true);
  assert.equal(app.liveEditingSetBy, "owner");

  api.on("GET", "/v1/projects/prj_1/live", json({
    object: "live", project_id: "prj_1", enabled: true, supported: true, session: SESSION,
    attached: [{ agent_id: "ag_1", conversation: "owner" }],
  }));
  const status = await app.live.status();
  assert.deepEqual([status.enabled, status.supported, status.unsupportedReason], [true, true, null]);
  assert.deepEqual(status.attached, [{ agentId: "ag_1", conversation: "owner" }]);
  const session = status.session!;
  assert.equal(session.open, true);
  assert.deepEqual([session.state, session.mode, session.workdir, session.viewers], ["live", "vite", "/site", { connected: 1, visible: 1 }]);
  assert.deepEqual(session.edits, { count: 3, hot: 2, reload: 1, error: 0, lastSeq: 13 });
  assert.deepEqual(session.data, [{
    kind: "database", name: "DB", productionId: "db_1", copyId: null, withData: true,
    note: "A copy with production's data, made at the session's first write.",
  }]);
  assert.deepEqual([session.liveAt?.toISOString(), session.endedAt], ["2026-10-27T09:00:04.000Z", null]);
  // The timers in force, by the names a start shortens them with.
  assert.deepEqual(session.limits, { idleGraceS: 30, idleEndS: 30, maxQuietWithViewersS: 14400, maxSessionS: 43200, holdWarmingS: 30 });
  assert.equal(session.git?.state, "clean");

  // An app it can't run on says why, and has had no session.
  api.on("GET", "/v1/projects/prj_2/live", json({
    object: "live", project_id: "prj_2", enabled: false, supported: false,
    unsupported_reason: "Live editing works with apps on the edge for now.", session: null, attached: [],
  }));
  const other = await nc.Project.fromId("prj_2").live.status();
  assert.deepEqual([other.supported, other.unsupportedReason, other.session], [false, "Live editing works with apps on the edge for now.", null]);

  api.on("PATCH", "/v1/projects/prj_3", apiError(409, "conflict", "A live session writes only to copies of the app's data."));
  await assert.rejects(nc.Project.fromId("prj_3").update({ liveEditing: true }), nc.Conflict);
});

test("a session starts once with the link that opens it, and shortens its timers", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/projects/prj_1/live/sessions", json({ ...SESSION, enter_url: ENTER_URL }));
  const live = nc.Project.fromId("prj_1").live;
  const session = await live.start();
  assert.equal(start.last.body, null); // nothing asked: the server's defaults
  assert.deepEqual([session.id, session.enterUrl, session.url], ["ls_1", ENTER_URL, "https://larkspur.noclick.site"]);

  // Waiting answers the session as it stands once the request has waited as long as it may: still warming.
  const warmingStart = api.on("POST", "/v1/projects/prj_1/live/sessions",
    json({ ...SESSION, state: "warming", phase: "starting_container", live_at: null, enter_url: ENTER_URL }));
  const warming = await live.start({ wait: true, refreshData: true, limits: { idleGraceS: 30, idleEndS: 30 } });
  assert.deepEqual(warmingStart.last.body, { wait: true, refresh_data: true, limits: { idle_grace_s: 30, idle_end_s: 30 } });
  assert.deepEqual([warming.state, warming.phase, warming.open, warming.liveAt], ["warming", "starting_container", true, null]);

  const link = api.on("POST", "/v1/projects/prj_1/live/enter_links", json({ url: ENTER_URL, expires_at: "2026-10-27T11:00:00Z" }));
  const made = await live.enterLink();
  assert.equal(link.last.body, null);
  assert.deepEqual([made.url, made.expiresAt?.toISOString()], [ENTER_URL, "2026-10-27T11:00:00.000Z"]);
});

test("a command runs in the session and says what each edit did", async () => {
  const { api } = setup();
  const run = api.on("POST", "/v1/projects/prj_1/live/exec",
    json({
      stdout: "", stderr: "", exit_code: 0, ms: 412, truncated: { stdout: false, stderr: false }, written_at: 1793040000123,
      vite: [HOT, RELOAD], earlier: [ERROR],
    }),
    json({
      stdout: "", stderr: "sed: can't read src/x.js", exit_code: 2, ms: 8, truncated: { stdout: false, stderr: false },
      written_at: null, vite: [],
    }),
    apiError(409, "conflict", "The app's live session is still starting, so the command didn't run.", { state: "warming" }));
  const live = nc.Project.fromId("prj_1").live;
  const result = await live.exec("sed -i 's/Score/Points/' src/render.js", { timeoutS: 30 });
  assert.deepEqual(run.last.body, { command: "sed -i 's/Score/Points/' src/render.js", timeout_s: 30 });
  assert.deepEqual([result.ok, result.exitCode, result.timedOut, result.ms], [true, 0, false, 412]);
  const [hot, reload] = result.vite;
  assert.deepEqual([hot.outcome, hot.files, hot.clients, hot.applied], ["hot", ["src/render.js"], 2, { ok: 2, failed: 0, errors: [] }]);
  assert.deepEqual([reload.outcome, reload.reload?.reason, reload.reload?.chain], ["reload", "no-boundary", ["/src/main.js", "/index.html"]]);
  assert.deepEqual(result.earlier.map((e) => [e.seq, e.outcome, e.error?.message]), [[14, "error", "Unexpected token"]]);

  // A failing command is a result, and the default timeout is the most a command answered in its request runs.
  const failed = await live.exec("sed -i 's/a/b/' src/x.js");
  assert.deepEqual(run.last.body, { command: "sed -i 's/a/b/' src/x.js", timeout_s: 90 });
  assert.deepEqual([failed.ok, failed.vite, failed.earlier], [false, [], []]);

  // A session still starting refuses a command answered in its request: it didn't run.
  await assert.rejects(live.exec("npm test"),
    (err: unknown) => err instanceof nc.Conflict && /didn't run/.test(err.message) && err.details.state === "warming");
});

test("a long command, or one for a starting session, runs in the background", async () => {
  const { api } = setup();
  const run = api.on("POST", "/v1/projects/prj_1/live/exec",
    json(operation({ id: "op_x", kind: "project.live_exec", status: "queued" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_x/wait", json(operation({
    id: "op_x", kind: "project.live_exec", status: "succeeded", result: {
      stdout: "added 1 package", stderr: "", exit_code: 0, ms: 41250, truncated: { stdout: false, stderr: false },
      written_at: 1793040041250, vite: [RELOAD],
    },
  })));
  const op = await nc.Project.fromId("prj_1").live.exec("npm install canvas-confetti", { background: true, timeoutS: 300 });
  assert.deepEqual([op.kind, run.last.body], ["project.live_exec", { command: "npm install canvas-confetti", background: true, timeout_s: 300 }]);
  const installed = await op.wait();
  assert.deepEqual([installed.ok, installed.stdout, installed.ms], [true, "added 1 package", 41250]);
  assert.deepEqual(installed.vite.map((edit) => edit.reload?.reason), ["no-boundary"]);
});

test("edits read back a page at a time", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/projects/prj_1/live/edits",
    json({ object: "list", data: [HOT, RELOAD, ERROR], last_seq: 14 }), json({ object: "list", data: [], last_seq: 14 }));
  const live = nc.Project.fromId("prj_1").live;
  const edits = await live.edits();
  assert.deepEqual([edits.map((e) => e.outcome), edits.lastSeq], [["hot", "reload", "error"], 14]);
  assert.deepEqual(Object.fromEntries(read.last.query), { limit: "50" });
  assert.deepEqual(edits[2].error?.loc, { line: 4, column: 9 });

  const later = await live.edits({ after: 14, limit: 10 });
  assert.deepEqual(Object.fromEntries(read.last.query), { after: "14", limit: "10" });
  assert.deepEqual([[...later], later.lastSeq], [[], 14]);
});

test("the end deploys only what passed, and waits like any operation", async () => {
  const { api } = setup();
  const end = api.on("POST", "/v1/projects/prj_1/live/end", json(operation({ id: "op_e", kind: "project.live_end", status: "queued" }), { status: 202 }));
  api.on("GET", "/v1/operations/op_e/wait",
    json(operation({
      id: "op_e", kind: "project.live_end", status: "succeeded",
      result: { object: "live_end", project_id: "prj_1", session_id: "ls_1", outcome: "deployed", deployment_id: "dep_7" },
    })),
    json(operation({
      id: "op_e", kind: "project.live_end", status: "failed",
      error: { type: "operation_failed", message: "What the live session edited wasn't deployed: It failed its check: / answered 500." },
    })));
  const live = nc.Project.fromId("prj_1").live;
  const op = await live.end();
  assert.deepEqual([op.kind, end.last.body], ["project.live_end", { deploy: true }]);
  const ended = await op.wait();
  assert.deepEqual([ended.outcome, ended.sessionId, ended.deploymentId, ended.mainBehind], ["deployed", "ls_1", "dep_7", false]);

  await live.end({ deploy: false });
  assert.deepEqual(end.last.body, { deploy: false });

  // A build or check that failed fails the operation: production was never touched.
  await assert.rejects((await live.end()).wait(), (err: unknown) => err instanceof nc.OperationFailed && /wasn't deployed/.test(err.message));
});
