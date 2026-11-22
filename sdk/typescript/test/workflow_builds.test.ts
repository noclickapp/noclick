// Building workflows from code, against the mock API: the routes and bodies each call sends, and
// what it parses (the build's question, its result).
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { workflowTuning } from "../src/workflow.ts";
import { apiError, json, operation, setup } from "./helpers.ts";

const WORKFLOW = {
  object: "workflow", id: "wf_1", name: "Morning brief", description: null, inputs: {},
  app_url: "https://noclick.com/dashboard?tab=workflows&workflow=wf_1", created_at: "2026-10-12T10:00:00Z", updated_at: "2026-10-12T10:00:00Z", steps: [],
};
const STEPS = [
  { id: "daily", name: "Every morning", type: "trigger-cron", operation: null },
  { id: "mail", name: "Email the brief", type: "automation-gmail", operation: "send_email" },
];
const RESULT = { object: "workflow_build", workflow_id: "wf_1", summary: "It emails you every morning at 8.", steps: STEPS, app_url: "https://noclick.com/dashboard?tab=workflows&workflow=wf_1" };
const QUESTION = {
  id: "ask-1", title: "A few details", answer_url: "https://noclick.com/b/l1", answerable_from_code: true,
  inputs: [{ id: "channel", label: "Which channel?", type: "text", description: "", required: true }],
};
const building = (fields: Record<string, unknown> = {}) =>
  operation({ id: "op_b", kind: "workflow.build", status: "running", step: "building", workflow_id: "wf_1", ...fields });

test("Workflow.create with instructions builds it, and wait gives its steps", async () => {
  const { api } = setup();
  const made = api.on("POST", "/v1/workflows", json({ ...WORKFLOW, build: building() }, { status: 201 }));
  api.on("GET", "/v1/operations/op_b/wait", json(building({ status: "succeeded", result: RESULT })));
  const brief = await nc.Workflow.create("Morning brief", { instructions: "Every day at 8, email me my calendar" });
  assert.deepEqual(made.last.body, { name: "Morning brief", instructions: "Every day at 8, email me my calendar" });
  assert.equal(made.last.headers.get("NoClick-User"), null);
  const build = brief.latestBuild;
  assert.ok(build instanceof nc.WorkflowBuild);
  assert.equal(build.workflowId, "wf_1");
  const result = await build.wait();
  assert.equal(result.summary, "It emails you every morning at 8.");
  assert.deepEqual(result.steps.map((s) => [s.name, s.operation]), [["Every morning", null], ["Email the brief", "send_email"]]);
});

test("a workflow created without instructions has no build", async () => {
  const { api } = setup();
  api.on("POST", "/v1/workflows", json(WORKFLOW, { status: 201 }));
  assert.equal((await nc.Workflow.create("Morning brief")).latestBuild, null);
});

test("a build that asks is answered from code", async () => {
  const { api } = setup();
  workflowTuning.questionPollMs = 0;
  const started = api.on("POST", "/v1/workflows/wf_1/builds", json(building(), { status: 202 }));
  const reads = api.on("GET", "/v1/operations/op_b",
    json(building()), json(building({ status: "awaiting_human", step: "asking", question: QUESTION })),
    json(building({ status: "succeeded", result: RESULT })));
  const answered = api.on("POST", "/v1/workflows/wf_1/builds/op_b/answer", json(building()));
  const brief = nc.Workflow.fromId("wf_1");
  const build = await brief.build("Also post it to Slack");
  assert.deepEqual(started.last.body, { instructions: "Also post it to Slack" });
  assert.equal(brief.latestBuild, build);
  const question = await build.nextQuestion();
  assert.ok(question?.answerableFromCode);
  assert.equal(question?.answerUrl, "https://noclick.com/b/l1");
  assert.equal(await build.answer({ channel: "#team" }, { message: "Keep it short" }), build);
  assert.deepEqual(answered.last.body, { values: { channel: "#team" }, message: "Keep it short" });
  assert.equal(await build.nextQuestion(), null);
  assert.equal(reads.count, 3);
});

test("a build asks through human requests, and code answers accounts and secrets", async () => {
  const { api } = setup();
  const asked = {
    ...QUESTION, sent_to: ["email", "web"],
    inputs: [
      { id: "slack", label: "Connect Slack", type: "credential", credential_type: "slack_oauth", request_id: "hr_1" },
      { id: "env", label: "Its token", type: "env", env_keys: [{ name: "WAREHOUSE_TOKEN" }], request_id: "hr_2" },
    ],
  };
  api.on("POST", "/v1/workflows/wf_1/builds", json(building({ status: "awaiting_human", step: "asking", question: asked }), { status: 202 }));
  const answered = api.on("POST", "/v1/workflows/wf_1/builds/op_b/answer", json(building()));
  const build = await nc.Workflow.fromId("wf_1").build("Post it to Slack");
  assert.deepEqual(build.question?.sentTo, ["email", "web"]);
  assert.deepEqual(build.question?.inputs.map((i) => i.request_id), ["hr_1", "hr_2"]);
  await build.answer({ slack: "credential:c1" }, { secretValues: { env: { WAREHOUSE_TOKEN: "t0k" } } });
  assert.deepEqual(answered.last.body, { values: { slack: "credential:c1" }, secret_values: { env: { WAREHOUSE_TOKEN: "t0k" } } });
});

test("a build or a new workflow can ask nothing", async () => {
  const { api } = setup();
  const made = api.on("POST", "/v1/workflows", json({ ...WORKFLOW, build: building() }, { status: 201 }));
  const started = api.on("POST", "/v1/workflows/wf_1/builds", json(building(), { status: 202 }));
  await nc.Workflow.create("Morning brief", { instructions: "Email me at 8", questions: "assume" });
  await nc.Workflow.fromId("wf_1").build("Text me too", { questions: "assume" });
  assert.deepEqual(made.last.body, { name: "Morning brief", instructions: "Email me at 8", questions: "assume" });
  assert.deepEqual(started.last.body, { instructions: "Text me too", questions: "assume" });
});

test("wait stops at a question, then waits through it for its answer", async () => {
  // The guide's first example, wait() straight after create(), blocked its whole timeout on a question
  // nobody was shown (2026-10-28): wait() throws the question, and once it has, waits for the answer.
  const { api } = setup();
  api.on("POST", "/v1/workflows/wf_1/builds", json(building(), { status: 202 }));
  const asking = building({ status: "awaiting_human", step: "asking", question: QUESTION });
  const waits = api.on("GET", "/v1/operations/op_b/wait",
    json(building()), json(asking), json(asking), json(building({ status: "succeeded", result: RESULT })));
  const build = await nc.Workflow.fromId("wf_1").build("Also post it to Slack");
  const asked = await build.wait({ timeoutS: 900 }).then(() => null, (err: unknown) => err);
  assert.ok(asked instanceof nc.AnswerRequired);
  assert.equal(asked.question.inputs[0]?.id, "channel");
  assert.equal(asked.question.answerUrl, "https://noclick.com/b/l1");
  assert.equal(asked.details.operation_id, "op_b");
  assert.match(asked.nextStep ?? "", /build\.answer\(/);
  assert.match(asked.message, /^The build is waiting on an answer: A few details/);
  // A person answers at answerUrl while this waits: the question it threw doesn't throw again.
  assert.equal((await build.wait({ timeoutS: 900 })).summary, "It emails you every morning at 8.");
  assert.equal(waits.count, 4);
  // Each read waits on the server only briefly, so a question surfaces in seconds, not a long poll.
  assert.deepEqual([...new Set(waits.calls.map((c) => c.query.get("timeout_s")))], [String(workflowTuning.questionWaitS)]);
});

test("a new question throws, and one nextQuestion already returned does not", async () => {
  const { api } = setup();
  api.on("POST", "/v1/workflows/wf_1/builds", json(building(), { status: 202 }));
  const second = { ...QUESTION, id: "ask-2", title: null, inputs: [{ id: "time", label: "What time?", type: "text" }] };
  api.on("GET", "/v1/operations/op_b", json(building({ status: "awaiting_human", step: "asking", question: QUESTION })));
  api.on("GET", "/v1/operations/op_b/wait",
    json(building({ status: "awaiting_human", step: "asking", question: QUESTION })),
    json(building({ status: "awaiting_human", step: "asking", question: second })),
    json(building({ status: "succeeded", result: RESULT })));
  const build = await nc.Workflow.fromId("wf_1").build("Also post it to Slack");
  assert.equal((await build.nextQuestion())?.id, "ask-1");
  const asked = await build.wait().then(() => null, (err: unknown) => err);
  assert.ok(asked instanceof nc.AnswerRequired);
  assert.equal(asked.question.id, "ask-2");
  assert.match(asked.message, /waiting on an answer: What time\?/);
  assert.equal((await build.wait()).steps[0]?.id, "daily");
});

test("a finished build carries facts beside the builder's words", async () => {
  const { api } = setup();
  const readiness = {
    status: "needs_setup", meaning: "Something is in the way.", warnings: [], unverified: [],
    issues: [{ step: "mail", code: "invalid_config", message: "Email the brief: to is required" }],
  };
  const facts = {
    ...RESULT, built: true, version: 7, readiness, sent_back: 2, unread: [],
    verdicts: { daily: { config_valid: true }, mail: { config_valid: false, missing_required: ["to"] } },
  };
  api.on("POST", "/v1/workflows/wf_1/builds", json(building(), { status: 202 }));
  api.on("GET", "/v1/operations/op_b/wait", json(building({ status: "succeeded", result: facts })),
    json(building({ status: "succeeded", result: RESULT })));
  const result = await (await nc.Workflow.fromId("wf_1").build("Email it to the team too")).wait();
  assert.deepEqual([result.built, result.version, result.sentBack, result.unread], [true, 7, 2, []]);
  assert.equal(result.readiness?.status, "needs_setup");
  assert.equal(result.readiness?.issues[0]?.step, "mail");
  assert.deepEqual(result.verdicts?.mail, { config_valid: false, missing_required: ["to"] });
  // A result from before facts were carried says none of them.
  const older = await (await nc.Workflow.fromId("wf_1").build("Again")).wait();
  assert.deepEqual([older.built, older.version, older.readiness, older.verdicts, older.sentBack, older.unread],
    [null, null, null, null, 0, []]);
});

test("facts that weren't read are null and named", async () => {
  const { api } = setup();
  const unread = { ...RESULT, built: null, version: null, readiness: null, verdicts: null, sent_back: 0, unread: ["built", "version", "readiness", "verdicts"] };
  api.on("POST", "/v1/workflows/wf_1/builds", json(building(), { status: 202 }));
  api.on("GET", "/v1/operations/op_b/wait", json(building({ status: "succeeded", result: unread })));
  const result = await (await nc.Workflow.fromId("wf_1").build("Email it to the team too")).wait();
  assert.equal(result.readiness, null);
  assert.deepEqual(result.unread, ["built", "version", "readiness", "verdicts"]);
});

test("steps come with one workflow, and delete trashes it", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/wf_1", json({ ...WORKFLOW, steps: STEPS }));
  const gone = api.on("DELETE", "/v1/workflows/wf_1", json({ object: "workflow", id: "wf_1", deleted: true }));
  const brief = await nc.Workflow.get("wf_1");
  assert.deepEqual(brief.steps.map((s) => s.id), ["daily", "mail"]);
  await brief.delete();
  assert.equal(gone.count, 1);
});

test("a build in progress is a Conflict", async () => {
  const { api } = setup();
  api.on("POST", "/v1/workflows/wf_1/builds", apiError(409, "conflict", "A build is already pending for this workflow."));
  await assert.rejects(nc.Workflow.fromId("wf_1").build("Text me too"), nc.Conflict);
});
