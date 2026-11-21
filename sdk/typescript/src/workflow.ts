/**
 * Workflows, built from a description or edited step by step, and run from code.
 *
 *     const brief = await Workflow.create("Morning brief");
 *     await (await brief.build("Every day at 8, email me today's calendar")).wait();
 *     const run = await (await brief.run()).wait();
 *
 * Your keys read every workflow your account can open in the app, its own and those shared with it
 * (`access`), and change, build and run the ones they can edit (one a team workspace's owner pays
 * for is billed to them). NoClick's builder (the one in the app) builds and changes one from what
 * you describe: a `WorkflowBuild` you wait on, which may stop to ask something first, and which can
 * publish the workflow's app too. A run starts where its trigger does, with the inputs as the
 * trigger's payload. A run started inside `asUser` (or with `user`) is recorded for that user and
 * counts toward their spend cap; its steps still use the app's connections.
 *
 * A workflow's graph is also a handle you change directly: `graph()` reads its steps, each `Step`
 * changes with one call (`update`, `connect`, ...), and `edit()` sends several changes as one batch
 * that lands whole or not at all, refused with `Conflict` when the workflow moved on since the
 * version you read. Every change is a version, listed by `versions()` and undone with
 * `restore({ historyVersion })`.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import type { Connection } from "./connection.ts";
import { AnswerRequired, Conflict, NotFound, OperationTimeout } from "./errors.ts";
import {
  ApiObject, asList, asObject, compact, csv, givesFields, listAll, listPage, num, paginate, parseTime, readScope, refId,
  str,
} from "./object.ts";
import type { CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import { resolveScope } from "./scope.ts";
import { Secret } from "./secret.ts";
import type { SecretRef } from "./secret.ts";
import { WorkflowApproval } from "./workflowApproval.ts";
import type { WorkflowApprovalListOptions } from "./workflowApproval.ts";

export type WorkflowRunStatus = "running" | "succeeded" | "failed";

/**
 * One of your account's workflow folders, as the app's Automations page shows it: `Workflow.folders()` lists them,
 * `Workflow.createFolder()` makes one and `workflow.moveTo()` files a workflow in one.
 */
export interface WorkflowFolder {
  id: string;
  name: string;
  description: string | null;
  /** The folder it's in; null at the top. */
  parentId: string | null;
  /** How deep it sits: 0 at the top, 10 at most. */
  depth: number;
  /** How many workflows are in it (not counting its folders'). */
  workflowCount: number;
  createdAt: Date | null;
  updatedAt: Date | null;
  raw: JsonObject;
}

function toFolder(raw: JsonObject): WorkflowFolder {
  return {
    id: String(raw.id),
    name: String(raw.name),
    description: str(raw.description),
    parentId: str(raw.parent_id),
    depth: Number(raw.depth),
    workflowCount: Number(raw.workflow_count ?? 0),
    createdAt: parseTime(raw.created_at),
    updatedAt: parseTime(raw.updated_at),
    raw,
  };
}

function folderIdOf(folder: WorkflowFolder | string | null): string | null {
  return folder !== null && typeof folder === "object" ? folder.id : folder;
}

/**
 * What one step did in a run: `status` is `succeeded`, `failed` (`error` says why) or `skipped`;
 * `output` is what it produced, with long lists and text cut short and never a secret (`withheld`
 * names, by path, what was left out). `Step.output` reads it whole.
 */
export interface RunStep {
  id: string;
  name: string;
  status: string;
  error: string | null;
  output: unknown;
  withheld: string[];
}

/**
 * What one step produced in one run (`Step.outputs`, `Step.output`). `runId` is the run's id (`Workflow.getRun` reads
 * a run from code by it), `source` how it started (as `WorkflowRun.source` says it), `status` the step's there
 * (`succeeded`, `failed` with `error`, `skipped`). A trigger's deliveries are its outputs too: `noEvent` marks a manual
 * run's placeholder for one that got no event. `iteration` is set for one iteration of a step that runs in a loop.
 *
 * A listing gives a one-line `preview` (`path=value` pairs); one read gives the `output`, with long text and lists cut
 * short (`truncated`) unless read `full`, or the part at `path`. Never a secret: `withheld` names, by path, what was
 * left out (a request's `Authorization` header, a key, a token).
 */
export interface StepOutput {
  stepId: string;
  runId: string;
  workflowId: string | null;
  iteration: number | null;
  source: string | null;
  status: string | null;
  error: string | null;
  createdAt: Date | null;
  noEvent: boolean;
  preview: string | null;
  output: unknown;
  path: string | null;
  full: boolean;
  truncated: boolean;
  withheld: string[];
  raw: JsonObject;
}

/**
 * One run of a workflow. `status` is `running` (a run waiting on an approval or a delay too),
 * `succeeded` or `failed` (`error` says why). `outputs` holds what its final steps produced (each
 * step that finished with nothing after it running), by step name. `source` is how it started:
 * `api`, `endpoint`, `schedule`, `trigger` (an event, like a webhook or an email) or `app`;
 * `inputs` and `operationId` are set for a run started from code. `steps` says what each step did,
 * read with one run (`Workflow.getRun`); empty in a list.
 */
export interface WorkflowRun {
  id: string;
  workflowId: string | null;
  status: WorkflowRunStatus;
  inputs: JsonObject;
  outputs: JsonObject;
  error: string | null;
  source: string | null;
  userId: string | null;
  operationId: string | null;
  startedAt: Date | null;
  finishedAt: Date | null;
  steps: RunStep[];
  raw: JsonObject;
}

/**
 * A workflow's test run, as the app's Test Run plays one: a staged event arrived at one of its triggers
 * (`trigger`: `{step_id, type, name}`) and the agents it reached took a real turn while a simulated world
 * answered every tool call, so nothing was sent and no account was touched. `testRun` is the run it played
 * (`{key, name, custom}`; `null` for a message you typed). `reply` is the agent's closing words; `toolCalls` the
 * calls it made, each with its `tool`, `arguments` and the `result` the world answered; `transcript` the run step
 * by step (`role` `assistant` steps, its `text`, and `tool` steps; a coding harness's own shell and file steps carry
 * `source` `harness`). `scenario` is the world it ran in, `note` says when it wrote nothing or what it did to act was
 * simulated, and `costUsd` is what it cost you.
 */
export interface WorkflowRehearsal {
  workflowId: string | null;
  testRun: JsonObject | null;
  trigger: JsonObject | null;
  reply: string;
  toolCalls: JsonObject[];
  transcript: JsonObject[];
  scenario: string | null;
  note: string | null;
  costUsd: number | null;
  operationId: string | null;
  raw: JsonObject;
}

/** What `Workflow.rehearse` stages: a test run the workflow offers, or a message you type on one of its triggers. */
export interface WorkflowRehearseOptions extends CallOptions {
  /** A test run the workflow offers, by its name or key, as its Test Run screen lists them. */
  testRun?: string;
  /** Instead of `testRun`: the trigger step (a `Step`, its id or its type) to stage `body` on. */
  trigger?: StepRef;
  /** With `trigger`: the staged message's body. */
  body?: string;
  /** With `trigger`: its subject or title. */
  title?: string;
  /** With `trigger`: who it's from, by name. */
  author?: string;
  /** With `trigger`: who it's from, by address or handle. */
  handle?: string;
  /** What the simulated world is like; its answers keep to it. Omitted, the staged situation's own. */
  scenario?: string;
}

/**
 * The URL a workflow answers at: send `method` (`POST`) with the inputs as a JSON body, and the
 * run's outputs come back (a run longer than 30 seconds answers `202` with its operation). A
 * `public` endpoint also takes a publishable key (`nk_pub_...`) that lists it, so a web page can
 * call it; otherwise it needs a secret key.
 */
export interface WorkflowEndpoint {
  url: string;
  public: boolean;
  method: string;
  raw: JsonObject;
}

/** @internal */
export function toWorkflowRun(value: unknown): WorkflowRun {
  const raw = asObject(value);
  const error = raw.error;
  return {
    id: str(raw.id) ?? "",
    workflowId: str(raw.workflow_id),
    status: (str(raw.status) ?? "running") as WorkflowRunStatus,
    inputs: asObject(raw.inputs),
    outputs: asObject(raw.outputs),
    error: error && typeof error === "object" ? str((error as JsonObject).message) : str(error),
    source: str(raw.source),
    userId: str(raw.user_id),
    operationId: str(raw.operation_id),
    startedAt: parseTime(raw.started_at),
    finishedAt: parseTime(raw.finished_at),
    steps: Array.isArray(raw.steps) ? raw.steps.map(toRunStep) : [],
    raw,
  };
}

function toRunStep(value: unknown): RunStep {
  const raw = asObject(value);
  return {
    id: str(raw.id) ?? "",
    name: str(raw.name) ?? "",
    status: str(raw.status) ?? "",
    error: str(raw.error),
    output: raw.output ?? null,
    withheld: asList(raw.withheld).map(String),
  };
}

/** @internal */
export function toStepOutput(value: unknown): StepOutput {
  const raw = asObject(value);
  return {
    stepId: str(raw.step_id) ?? "",
    runId: str(raw.run_id) ?? "",
    workflowId: str(raw.workflow_id),
    iteration: typeof raw.iteration === "number" ? raw.iteration : null,
    source: str(raw.source),
    status: str(raw.status),
    error: str(raw.error),
    createdAt: parseTime(raw.created_at),
    noEvent: raw.no_event === true,
    preview: str(raw.preview),
    output: raw.output ?? null,
    path: str(raw.path),
    full: raw.full === true,
    truncated: raw.truncated === true,
    withheld: asList(raw.withheld).map(String),
    raw,
  };
}

/** What `Step.output` reads: the part at `path`, the whole output (`full`), one `iteration` of a step in a loop. */
export interface StepOutputOptions extends CallOptions {
  path?: string;
  full?: boolean;
  iteration?: number;
}

/**
 * How many runs `Workflow.runs` lists (`Workflow.runCounts`): the `total`, `byStatus` (`running`, `succeeded`,
 * `failed`, each there even at 0) and `bySource` (`api`, `endpoint`, `schedule`, `trigger`, `app`: only those with
 * runs). A run from code counts once, however many executions it spans.
 */
export interface WorkflowRunCounts {
  workflowId: string;
  total: number;
  byStatus: Record<WorkflowRunStatus, number>;
  bySource: Record<string, number>;
  raw: JsonObject;
}

/**
 * Each step's latest output, whatever run it's from (`Workflow.latestOutputs`): `outputs` by step id, each cut short
 * as a run's steps are unless read `full` (`truncated` names the steps cut), never a secret (`withheld`: each step's
 * paths left out). A step that never stored one isn't in `outputs`.
 */
export interface LatestOutputs {
  workflowId: string;
  outputs: JsonObject;
  withheld: Record<string, string[]>;
  full: boolean;
  truncated: string[];
  raw: JsonObject;
}

/**
 * What an expression gives (`Step.previewExpression`): `ok`, with the value's `kind` (`object`, `array`, `string`,
 * `number`, `boolean`, `null`), an object's `keys` and a short `preview`; or `ok` false with the `error`.
 */
export interface ExpressionPreview {
  ok: boolean;
  kind: string | null;
  keys: string[] | null;
  preview: string | null;
  error: string | null;
  raw: JsonObject;
}

/** What `Step.clearState` forgot: how many of its state records and of its conversations were deleted. */
export interface ClearedStepState {
  stepId: string;
  stateRowsDeleted: number;
  conversationsDeleted: number;
  raw: JsonObject;
}

function toRunCounts(value: unknown): WorkflowRunCounts {
  const raw = asObject(value);
  return {
    workflowId: str(raw.workflow_id) ?? "",
    total: Number(raw.total ?? 0),
    byStatus: { running: 0, succeeded: 0, failed: 0, ...(asObject(raw.by_status) as Record<string, number>) },
    bySource: { ...(asObject(raw.by_source) as Record<string, number>) },
    raw,
  };
}

function toLatestOutputs(value: unknown): LatestOutputs {
  const raw = asObject(value);
  const withheld: Record<string, string[]> = {};
  for (const [step, paths] of Object.entries(asObject(raw.withheld))) withheld[step] = asList(paths).map(String);
  return {
    workflowId: str(raw.workflow_id) ?? "",
    outputs: asObject(raw.outputs),
    withheld,
    full: raw.full === true,
    truncated: asList(raw.truncated).map(String),
    raw,
  };
}

function toExpressionPreview(value: unknown): ExpressionPreview {
  const raw = asObject(value);
  return {
    ok: raw.ok === true,
    kind: str(raw.kind),
    keys: Array.isArray(raw.keys) ? raw.keys.map(String) : null,
    preview: str(raw.preview),
    error: str(raw.error),
    raw,
  };
}

function toEndpoint(value: unknown): WorkflowEndpoint {
  const raw = asObject(value);
  return { url: str(raw.url) ?? "", public: raw.public === true, method: str(raw.method) ?? "POST", raw };
}

/** Whether a step that takes an account has one, and whether it works (`healthy` is `null` when NoClick can't tell). */
export interface StepConnection {
  attached: boolean;
  healthy: boolean | null;
  hint: string | null;
}

/** A trigger step's state: what keeps it from firing, and when it fires next. */
export interface StepTrigger {
  error: string | null;
  pausedReason: string | null;
  nextRun: string | null;
}

/**
 * One step of a workflow, as the app shows it: its `name`, its kind (`type`, like
 * `automation-gmail` or `trigger-cron`) and the `operation` it does there (`null` for a step with
 * one thing to do). Read with one workflow, a step also says whether it's `enabled`, its `settings`
 * (never a secret; long values cut short), its `connection` (`null` for a step that takes no
 * account) and, for a trigger, its `trigger` state (`null` for any other step).
 */
export interface WorkflowStep {
  id: string;
  name: string;
  type: string;
  operation: string | null;
  enabled: boolean;
  settings: JsonObject;
  connection: StepConnection | null;
  trigger: StepTrigger | null;
}

/** How two steps are wired: `kind` is `data`, or `tools` for a step an agent uses as a tool. */
export interface WorkflowEdge {
  from: string;
  to: string;
  kind: "data" | "tools";
}

/** Whether a workflow is set up to run: its `status` and the `issues` in the way. */
export interface WorkflowReadiness {
  status: string;
  /** What `status` means, in a sentence. */
  meaning: string;
  /** What's in the way of it working, a step whose last run failed among them. */
  issues: { step: string | null; code: string; message: string }[];
  /** What doesn't stop it running: an agent's tool with no account connected, which only a call to it needs. */
  warnings: { step: string | null; code: string; message: string }[];
  /** The steps no run has completed yet: set up, but nothing has shown they work. */
  unverified: { step: string | null; code: string; message: string }[];
}

/** A URL a workflow answers at: its `endpoint`, its published `app`, or a hosted `mcp` server. */
export interface WorkflowUrl {
  kind: string;
  url: string;
  step: string | null;
  public: boolean;
}

/**
 * What a build waits on. Each of `inputs` is `{ id, label, type, description, options? }`; answer
 * them with `build.answer({ [id]: value })` where `answerableFromCode`. An input of type
 * `credential` (an account to connect) or `env` (secret values) needs a person: send them to
 * `answerUrl`, and the build goes on once they answer.
 */
export interface BuildQuestion {
  id: string | null;
  title: string | null;
  inputs: JsonObject[];
  answerUrl: string | null;
  answerableFromCode: boolean;
  raw: JsonObject;
}

/**
 * A finished build: what the builder says it did (`summary`), the workflow's `steps` as they now
 * stand, and, when it published the workflow's app, `published` (`state` is `published`,
 * `renamed` or `unpublished`; unpublished, `trashId` restores it until `restorableUntil`).
 *
 * Beside the builder's words, facts no model wrote: whether it `built` anything (`false`: the
 * workflow is as it was, whatever `summary` says), the `version` it ended on (what
 * `edit({ ifVersion })` takes), its `readiness` as `Workflow.readiness` reads it, and each step's
 * verdict by step id (`verdicts`: `config_valid`, `validation_error`, `missing_required`, as an
 * edit answers them). `sentBack` counts the times the build went back to the builder for settings
 * the run engine rejects (at most 2) before it finished. A fact NoClick couldn't read is `null` and
 * named in `unread`: then nothing says the workflow is ready.
 */
export interface WorkflowBuildResult {
  workflowId: string | null;
  summary: string | null;
  steps: WorkflowStep[];
  appUrl: string | null;
  published: { state: string; url: string | null; trashId: string | null; restorableUntil: string | null } | null;
  built: boolean | null;
  version: number | null;
  readiness: WorkflowReadiness | null;
  verdicts: Record<string, JsonObject> | null;
  sentBack: number;
  unread: string[];
  raw: JsonObject;
}

/** What `publish` takes: the app's `subdomain` (`morrow` is morrow.noclick.app) and `title`. */
export interface PublishOptions {
  subdomain?: string;
  title?: string;
}

function toPublished(raw: JsonObject): NonNullable<WorkflowBuildResult["published"]> {
  return { state: str(raw.state) ?? "published", url: str(raw.url), trashId: str(raw.trash_id),
    restorableUntil: str(raw.restorable_until) };
}

function toStep(value: unknown): WorkflowStep {
  const raw = asObject(value);
  const connection = raw.connection && typeof raw.connection === "object" ? asObject(raw.connection) : null;
  const trigger = raw.trigger && typeof raw.trigger === "object" ? asObject(raw.trigger) : null;
  return {
    id: str(raw.id) ?? "",
    name: str(raw.name) ?? "",
    type: str(raw.type) ?? "",
    operation: str(raw.operation),
    enabled: raw.enabled !== false,
    settings: asObject(raw.settings),
    connection: connection
      ? { attached: connection.attached === true, healthy: typeof connection.healthy === "boolean" ? connection.healthy : null, hint: str(connection.hint) }
      : null,
    trigger: trigger ? { error: str(trigger.error), pausedReason: str(trigger.paused_reason), nextRun: str(trigger.next_run) } : null,
  };
}

function toQuestion(value: unknown): BuildQuestion {
  const raw = asObject(value);
  return {
    id: str(raw.id),
    title: str(raw.title),
    inputs: Array.isArray(raw.inputs) ? (raw.inputs as JsonObject[]) : [],
    answerUrl: str(raw.answer_url),
    answerableFromCode: raw.answerable_from_code === true,
    raw,
  };
}

function toReadiness(value: unknown): WorkflowReadiness {
  const raw = asObject(value);
  return {
    status: str(raw.status) ?? "",
    meaning: str(raw.meaning) ?? "",
    issues: Array.isArray(raw.issues) ? (raw.issues as WorkflowReadiness["issues"]) : [],
    warnings: Array.isArray(raw.warnings) ? (raw.warnings as WorkflowReadiness["warnings"]) : [],
    unverified: Array.isArray(raw.unverified) ? (raw.unverified as WorkflowReadiness["unverified"]) : [],
  };
}

function toBuildResult(value: unknown): WorkflowBuildResult {
  const raw = asObject(value);
  const verdicts: Record<string, JsonObject> = {};
  for (const [id, verdict] of Object.entries(asObject(raw.verdicts))) verdicts[id] = asObject(verdict);
  return {
    workflowId: str(raw.workflow_id),
    summary: str(raw.summary),
    steps: Array.isArray(raw.steps) ? raw.steps.map(toStep) : [],
    appUrl: str(raw.app_url),
    published: raw.published && typeof raw.published === "object" ? toPublished(asObject(raw.published)) : null,
    built: typeof raw.built === "boolean" ? raw.built : null,
    version: typeof raw.version === "number" ? raw.version : null,
    readiness: raw.readiness && typeof raw.readiness === "object" ? toReadiness(raw.readiness) : null,
    verdicts: raw.verdicts && typeof raw.verdicts === "object" ? verdicts : null,
    sentBack: typeof raw.sent_back === "number" ? raw.sent_back : 0,
    unread: Array.isArray(raw.unread) ? raw.unread.filter((name): name is string => typeof name === "string") : [],
    raw,
  };
}

/**
 * A finished draft: the workflow's `version` once the drafted steps were written (one version of its history,
 * `historyVersion`; `changed` false when the drafter changed nothing), a `summary` of what changed, and for each step
 * it drafted (`steps`, by id) the verdict an edit answers (`config_valid`, `validation_error`, `missing_required`,
 * `references`) beside `drafted`, its `operation`, the `settings` it wrote, the ones it left for a person (`unfilled`:
 * a choice read from the connected account, a value only they know) and, for a step it couldn't draft (left as it
 * was), its `error`.
 */
export interface WorkflowDraftResult {
  workflowId: string;
  mode: string;
  version: number | null;
  historyVersion: number | null;
  changed: boolean;
  summary: string | null;
  steps: Record<string, JsonObject>;
  raw: JsonObject;
}

/** A step to draft: a `Step`, its id, or `{ id, goal }` (what it's for, which a drafted step keeps). */
export type DraftStep = StepRef | { id: StepRef; goal?: string };

/** What `Workflow.draft` takes beside its steps. */
export interface DraftOptions {
  /**
   * `full` (the default) picks each step's operation and fills its settings; `operation` picks only the operation;
   * `fields` fills the settings of the operation a step has; `field` fills the one setting `field` names.
   */
  mode?: "full" | "operation" | "fields" | "field";
  /** The setting mode `field` fills. */
  field?: string;
  /** What the workflow does, in words, for the drafter to read beside each step's goal. */
  instructions?: string;
}

function toDraftResult(value: unknown): WorkflowDraftResult {
  const raw = asObject(value);
  const steps = asObject(raw.steps);
  return {
    workflowId: str(raw.workflow_id) ?? "",
    mode: str(raw.mode) ?? "full",
    version: typeof raw.version === "number" ? raw.version : null,
    historyVersion: typeof raw.history_version === "number" ? raw.history_version : null,
    changed: raw.changed === true,
    summary: str(raw.summary),
    steps: Object.fromEntries(Object.entries(steps).map(([id, step]) => [id, asObject(step)])),
    raw,
  };
}

registerResult("workflow.run", (result) => toWorkflowRun(result));
registerResult("workflow.build", (result) => toBuildResult(result));
registerResult("workflow.draft", (result) => toDraftResult(result));

function toRehearsal(result: unknown, op: Operation<unknown>): WorkflowRehearsal {
  const raw = asObject(result);
  const obj = (value: unknown): JsonObject | null => (value && typeof value === "object" ? asObject(value) : null);
  return {
    workflowId: str(raw.workflow_id),
    testRun: obj(raw.test_run),
    trigger: obj(raw.trigger),
    reply: str(raw.reply) ?? "",
    toolCalls: Array.isArray(raw.tool_calls) ? (raw.tool_calls as JsonObject[]) : [],
    transcript: Array.isArray(raw.transcript) ? (raw.transcript as JsonObject[]) : [],
    scenario: str(raw.scenario),
    note: str(raw.note),
    costUsd: num(raw.cost_usd),
    operationId: str(op._known("id")),
    raw,
  };
}

registerResult("workflow.rehearse", toRehearsal);

/**
 * @internal How often `nextQuestion` looks while the build works (the server's wait answers only once it's
 * done), and how long one read in a build's `wait()` lets the server hold it, so a question surfaces in seconds.
 */
export const workflowTuning = { questionPollMs: 2000, questionWaitS: 5 };

const BUILD_DONE = ["succeeded", "failed", "canceled", "expired"];

/**
 * A build of a workflow from a description (kind `workflow.build`). It's an `Operation`: `wait()`
 * resolves to the `WorkflowBuildResult`, or throws why the build failed.
 *
 * While it builds, `step` is `building`. When the builder needs something it's `awaiting_human`
 * (step `asking`) and `question` says what: answer it with `answer()`, or send a person to its
 * `answerUrl`. `wait()` stops at a question it hasn't shown you, throwing `AnswerRequired` with it;
 * called again, it waits through that question for its answer. `nextQuestion()` resolves as soon as
 * there is one.
 */
export class WorkflowBuild extends Operation<WorkflowBuildResult> {
  private readonly _questionsShown = new Set<string | null>();

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** Whether `question` was already shown to the caller; records that it now has been. */
  private _shown(question: BuildQuestion): boolean {
    if (this._questionsShown.has(question.id)) return true;
    this._questionsShown.add(question.id);
    return false;
  }

  protected override get _waitWindowS(): number {
    return workflowTuning.questionWaitS;
  }

  protected override _waited(): boolean {
    const raw = this._raw ?? {};
    if (raw.status === "awaiting_human" && raw.question) {
      const question = toQuestion(raw.question);
      if (!this._shown(question)) {
        const asks = question.title ?? question.inputs.map((input) => input.label).find((label) => typeof label === "string");
        const err = new AnswerRequired(`The build is waiting on an answer: ${asks ?? "the builder has a question"}`, {
          nextStep: "Answer it with build.answer({ inputId: value }) where question.answerableFromCode, else send a person to question.answerUrl; then call wait() again.",
          details: { operation_id: this._id(), question: raw.question as JsonObject },
        });
        err.question = question;
        throw this._linked(err);
      }
    }
    return super._waited();
  }

  /** @internal Build from an operation view (or a bare operation id). */
  static _from(payload: unknown, init: { client?: NoClick }): WorkflowBuild {
    return new WorkflowBuild(Operation._init(payload, { ...init, user: null, kind: "workflow.build" }));
  }

  get workflowId(): string | null {
    return str(this._known("workflow_id")) ?? str(asObject(this._known("input")).workflow_id);
  }

  /** What the build waits on (`null` unless it's asking). */
  get question(): BuildQuestion | null {
    const raw = this._raw?.question;
    return raw ? toQuestion(raw) : null;
  }

  /** Resolve once the build asks something (its `question`) or finishes (`null`: `wait()` gives the result). */
  async nextQuestion(options: { timeoutS?: number } = {}): Promise<BuildQuestion | null> {
    const deadline = options.timeoutS === undefined ? null : Date.now() + options.timeoutS * 1000;
    for (;;) {
      this._absorb(await this._request("GET", `/v1/operations/${this._id()}`));
      const raw = this._raw ?? {};
      if (raw.status === "awaiting_human" && raw.question) {
        const question = toQuestion(raw.question);
        this._shown(question);
        return question;
      }
      if (BUILD_DONE.includes(String(raw.status))) return null;
      if (deadline !== null && Date.now() >= deadline) {
        throw new OperationTimeout(`Build ${this._id()} is still ${String(raw.status)} after ${options.timeoutS}s.`, {
          nextStep: "Call nextQuestion() or wait() again.",
          details: { operation_id: this._id() },
        });
      }
      await new Promise((resolve) => setTimeout(resolve, workflowTuning.questionPollMs));
    }
  }

  /**
   * Answer the question the build waits on, by input id; `message` tells the builder anything
   * else, `skip: true` goes on without answering. An input only a person can answer (an account
   * to connect, secret values) throws `InvalidRequest` naming `answerUrl`. Resolves to this build,
   * `running` again.
   */
  async answer(values: JsonObject = {}, options: { message?: string; skip?: boolean } = {}): Promise<this> {
    const raw = await this._request("POST", `/v1/workflows/${this.workflowId}/builds/${this._id()}/answer`, {
      json: compact({ values, message: options.message, skip: options.skip || undefined }),
    });
    this._absorb(raw);
    return this;
  }
}

// --- the graph ----------------------------------------------------------

/** Where a step sits on the canvas. */
export interface Position {
  x: number;
  y: number;
}

/**
 * How two steps of a graph are wired: `kind` is `data`, or `tools` for a step wired into an agent as its tools;
 * `handle` names which output of `from` it leaves (`null` for its only one), `targetHandle` which input of `to` it
 * joins, for a step with several (a code step's `state`).
 */
export interface GraphEdge {
  id: string | null;
  from: string;
  to: string;
  kind: "data" | "tools";
  handle: string | null;
  targetHandle: string | null;
}

/** A step, or its id. */
export type StepRef = Step | string;

/** What `Step.update` (and a batch's `updateStep`) changes; a field left out is never touched. */
export interface StepUpdate {
  /**
   * Settings to change, merged into the step's (a nested object merges, any other value replaces, and `null` takes
   * that setting out, a secret included).
   */
  settings?: JsonObject;
  name?: string;
  operation?: string;
  /** `false` switches the step off; `true` back on. */
  enabled?: boolean;
  /**
   * An agent step's secrets: the account's own, in its shell's environment on every run, as `Secret` objects or
   * their names, replacing the ones it had (`[]` takes them all off). Only a key acting for the whole account of the
   * workflow's owner gives a step one, and an agent's own tools as your approval settings let them
   * (`attach_connection`, allowed by default); any other caller keeps or drops what it was given. Their values never
   * show in a read of the workflow, nor to the agent's model.
   */
  secrets?: SecretRef[];
}

/** What `addStep` takes beside the step's type. */
export interface AddStepOptions {
  /** What it does, one of its type's operations. */
  operation?: string;
  settings?: JsonObject;
  /** An agent step's secrets, as `StepUpdate.secrets` takes them. */
  secrets?: SecretRef[];
  /** Its name in the app. */
  name?: string;
  /** Its id; made from its type when left out. */
  id?: string;
  /** Where it sits; left out, it's laid out beside the rest. */
  position?: Position;
}

/** Where `addNote` puts a note and how it looks. */
export interface AddNoteOptions {
  id?: string;
  /** The app's colours, 0 to 20. */
  color?: number;
  /** Steps it sits beside. */
  near?: StepRef[];
  /** Which side of `near`: `above` (the default), `below`, `left` or `right`. */
  direction?: "above" | "below" | "left" | "right";
  /** With `before`: the first step of the stretch it covers. */
  after?: StepRef;
  /** With `after`: the last step of the stretch it covers. */
  before?: StepRef;
  width?: number;
  height?: number;
  /** Where it sits, instead of beside steps (`near`, or `after` and `before`). */
  position?: Position;
}

/** What `Workflow.edit` checks and answers. */
export interface EditOptions {
  /** The version the edits were made against (a read's `version`): refused with `Conflict` when it moved on since. */
  ifVersion?: number;
  /** `true`: the answer carries the graph as written. */
  includeGraph?: boolean;
  /**
   * `canvas`: the edits are a canvas's saves. Each setting `updateStep` sends replaces that setting whole and is kept
   * as written (never rewritten nor refused for its value; the step's verdict says it isn't ready), an edge joins the
   * handles it names, a connection sits under the slot it's given (one the step takes), and they join the canvas
   * session's version (saves within five minutes of its first, whoever made them).
   */
  source?: "canvas";
  /**
   * A name the sender gives itself (letters, digits, `-` and `_`, up to 64; a canvas tab's own id): what the
   * workflow's open canvases hear of this write names it, so the canvas that sent it knows the change is its own.
   */
  origin?: string;
  /** In a browser, send the batch so it outlives the page (a closing tab's last save; `RequestOptions.keepalive`). */
  keepalive?: boolean;
  /**
   * `true`: wait, up to 30 seconds, for what the batch sets going (a trigger's registration: its webhook, its
   * schedule, its inbox; a removed step's teardown) before the answer: `settled` says whether it finished in time,
   * the graph (with `includeGraph`) carries what it wrote on the steps (a trigger's `webhook_url`), and
   * `unregistered` names, by step, why each trigger it left unregistered can't be registered yet.
   */
  settle?: boolean;
}

/** What `Workflow.update` changes; a field left out is never touched. */
export interface WorkflowUpdate {
  name?: string;
  description?: string;
  /** Its settings to change, by top-level key; only its owner changes them. */
  settings?: JsonObject;
  /**
   * What the app shows of it (its canvas's viewport, the step open in its panel; 16 KB at most), replacing what's
   * kept: never a version, nor a change anyone is told of.
   */
  displayMetadata?: JsonObject;
  /**
   * Its Interface tab's layout as the app draws it (each block's place on the grid, the tabs' order; 256 KB at most),
   * replacing what's kept: part of its graph, so it moves the version.
   */
  interface?: JsonObject;
}

/** What `nameVersion` takes beside its label. */
export interface NameVersionOptions {
  /** A line about it. */
  note?: string;
  /** The version of its history to name; left out, the version the workflow is at now (a checkpoint). */
  historyVersion?: number;
  /** For the version it's at now: refused with `Conflict` when the workflow moved on since this version. */
  ifVersion?: number;
}

/**
 * What an edit did: the workflow's `version` once it and what it set in motion were written (a trigger's
 * registration writes too), to edit on from; whether its definition `changed`; the version of its history it
 * landed in (`historyVersion`, what `versionAt` and `restore` name: a version of its own, which this key's next
 * edits join for five minutes from its first; a layout-only edit is none); a `summary`; each op's `results` in
 * order (an added step's `id`, and what the
 * edit did on its own: `resolutions`, `harness_switch`, `coerced_values`, `stripped_trigger_refs`,
 * `http_auth_credential_hint`); and, for each step an op touched, whether it's ready to run (`steps`:
 * `config_valid`, `validation_error`, `missing_required`, `agent_credential_hint`, and `references`: each read of
 * another step's output that won't resolve, as `Step.references` reads them). `graph` is the workflow as
 * written, read as `Workflow.graph()` reads it, when the edit asked for it; `restoredFrom` names the version of its
 * history a restore put back. `warnings` say what an edit did that won't work as it may look (a workspace member's
 * own connection given to a team workflow's step, which its owner's automatic runs can't use). An edit sent with
 * `settle` also says whether what it set going finished in time (`settled`) and, by step, why each trigger it left
 * unregistered can't be registered yet (`unregistered`).
 */
export interface WorkflowEdit {
  workflowId: string;
  version: number;
  historyVersion: number | null;
  changed: boolean;
  summary: string | null;
  results: JsonObject[];
  steps: Record<string, JsonObject>;
  graph: WorkflowGraph | null;
  restoredFrom: number | null;
  warnings: string[];
  settled: boolean | null;
  unregistered: Record<string, string>;
  raw: JsonObject;
}

/**
 * One version of a workflow's history: its own number (`historyVersion`, what `versionAt` and `restore` take,
 * fixed once given), the workflow's `version` its latest write left, where the change came from (`source`: `api`,
 * `canvas`, `builder`, `mcp`, `coordinator`, `deploy`, `restore`, `baseline`, the workflow before its history
 * began, or `checkpoint`, one saved in the app before its history was kept, numbered below 1), who began it
 * (`author`: `{ user_id, key_id }`, `null` for the baseline) and everyone who wrote into it (`authors`, its author
 * first), a `summary` and its `changes`, and for a restore the version of the history it put back (`restoredFrom`).
 * A named version (a checkpoint: `Workflow.nameVersion`) has its `label` and `note`, who named it (`labeledBy`) and
 * when (`labeledAt`), and is kept for good while it has a name.
 *
 * Saves in the app's canvas within five minutes of a session's first are one version, whoever made them. Any other
 * change (from your code, the builder, an MCP client, NoClick's assistant, a restore) is a version of its own, which
 * only the same key's next changes from the same place join, within five minutes of its first; so `updatedAt` is its
 * latest write. `graph` is the whole definition it holds, its name, description and settings with its steps, read
 * with `Workflow.versionAt` (`null` in a list): a restore puts all of it back. Its steps are as they were, and
 * changing one changes the workflow's step of that id as it is now.
 */
export interface WorkflowVersion {
  workflowId: string;
  historyVersion: number;
  version: number;
  source: string;
  author: { user_id: string; key_id: string | null } | null;
  authors: { user_id: string; key_id: string | null }[];
  summary: string | null;
  changes: string[];
  restoredFrom: number | null;
  createdAt: Date | null;
  updatedAt: Date | null;
  graph: WorkflowGraph | null;
  label: string | null;
  note: string | null;
  labeledBy: { user_id: string } | null;
  labeledAt: Date | null;
  raw: JsonObject;
}

/**
 * One choice a step's setting takes, as the app's dropdown lists it: its `value` (what the setting takes), its
 * `label` and what the service says beside it (`metadata`: an icon, a count; `null` for none).
 */
export interface StepOption {
  value: unknown;
  label: unknown;
  metadata: JsonObject | null;
}

/**
 * A page of the choices a step's `field` takes (`Step.options`). `nextPageToken` reads the next page; `withheld`
 * names, by path, a choice or a part of one left out because it held a secret.
 */
export interface StepOptions {
  field: string;
  options: StepOption[];
  nextPageToken: string | null;
  withheld: string[];
  raw: JsonObject;
}

/** What `Step.options` sends beside the field. */
export interface StepOptionsQuery {
  /** The step's settings as its form holds them, over the saved ones: what a list that depends on another reads. */
  settings?: JsonObject;
  /** Narrows the choices, where the service can search them. */
  search?: string;
  /** The `nextPageToken` of the page before. */
  pageToken?: string;
}

/**
 * A widget's value on a step (`Step.value`): `value`, or `values` where it fills several of the step's settings at
 * once (a trigger's address, whether it's registered, why not). `withheld` names, by path, what was left out
 * because it held a secret (a webhook's signing secret, a signed upload link).
 */
export interface StepValue {
  field: string;
  value: unknown;
  values: JsonObject | null;
  withheld: string[];
  raw: JsonObject;
}

/**
 * What `Step.publish`, `Step.renameApp` and `Step.unpublish` left of an interface step's app: its `state`
 * (`published`, `renamed` or `unpublished`) and `url`, as a build's `published` names them; the app itself
 * (`projectId`, a `Project`'s id, and its `subdomain`); the release a publish made (`deploymentId`); where it answered
 * before a rename or an unpublish (`previousUrl`); and, unpublished, the trash entry that restores it (`trashId`)
 * until `restorableUntil`.
 */
export interface StepPublication {
  workflowId: string;
  stepId: string;
  action: string;
  state: string;
  url: string | null;
  projectId: string | null;
  subdomain: string | null;
  deploymentId: string | null;
  previousUrl: string | null;
  trashId: string | null;
  restorableUntil: Date | null;
  raw: JsonObject;
}

function toStepPublication(value: unknown): StepPublication {
  const raw = asObject(value);
  return {
    workflowId: str(raw.workflow_id) ?? "",
    stepId: str(raw.step_id) ?? "",
    action: str(raw.action) ?? "",
    state: str(raw.state) ?? "",
    url: str(raw.url),
    projectId: str(raw.project_id),
    subdomain: str(raw.subdomain),
    deploymentId: str(raw.deployment_id),
    previousUrl: str(raw.previous_url),
    trashId: str(raw.trash_id),
    restorableUntil: parseTime(raw.restorable_until),
    raw,
  };
}

function toStepOptions(value: unknown): StepOptions {
  const raw = asObject(value);
  return {
    field: str(raw.field) ?? "",
    options: asList(raw.options).map((option) => {
      const found = asObject(option);
      return { value: found.value ?? null, label: found.label ?? null, metadata: found.metadata ? asObject(found.metadata) : null };
    }),
    nextPageToken: str(raw.next_page_token),
    withheld: asList(raw.withheld).map(String),
    raw,
  };
}

function toStepValue(value: unknown): StepValue {
  const raw = asObject(value);
  return {
    field: str(raw.field) ?? "",
    value: raw.value ?? null,
    values: raw.values ? asObject(raw.values) : null,
    withheld: asList(raw.withheld).map(String),
    raw,
  };
}

// A step's config holds these beside its settings; each is a field of its own on a `Step`.
const OWN_FIELDS = new Set(["label", "operation", "disabled", "credentialIds", "mockedOutput"]);
// The canvas's node shape keeps these beside its `data.config` (the API's shape keeps them all in `config`).
const DATA_FIELDS = ["label", "operation", "credentialIds", "model", "disabled", "mockedOutput"];
const NOTE = "stickyNote";
// The handle a step wired into an agent as its tools joins on.
const TOOLS_HANDLE = "bottom";

/** A stored step's config, from either node shape the graph holds. */
function nodeConfig(node: JsonObject): JsonObject {
  const merged: JsonObject = {};
  const data = asObject(node.data);
  Object.assign(merged, asObject(data.config));
  for (const key of DATA_FIELDS) if (key in data && !(key in merged)) merged[key] = data[key];
  Object.assign(merged, asObject(node.config));
  return merged;
}

function toEdge(value: unknown): GraphEdge {
  const raw = asObject(value);
  const tools = raw.targetHandle === TOOLS_HANDLE;
  return {
    id: str(raw.id),
    from: str(raw.source) ?? str(raw.sourceId) ?? "",
    to: str(raw.target) ?? str(raw.targetId) ?? "",
    kind: tools ? "tools" : "data",
    handle: str(raw.sourceHandle),
    targetHandle: tools ? null : str(raw.targetHandle),
  };
}

/** An id for a step added without one, made as the API makes one: its type, the time, six hex digits. */
function newId(kind: string): string {
  return `${kind}-${Date.now()}-${globalThis.crypto.randomUUID().replace(/-/g, "").slice(0, 6)}`;
}

function stepId(step: StepRef): string {
  if (step instanceof Step) return step.id;
  if (typeof step === "string") return step;
  throw new TypeError("A step is a Step or its id.");
}

/** An agent step's `secrets` as the API takes them: names (a `Secret` is its name, once it's loaded or created). */
async function secretNames(secrets: unknown[]): Promise<string[]> {
  const names: string[] = [];
  for (const secret of secrets) {
    if (secret instanceof Secret) names.push(String((await secret._ensure()).name));
    else if (typeof secret === "string") names.push(secret);
    else throw new TypeError("A secret is a Secret or its name.");
  }
  return names;
}

/** `op` as the API takes it: a connection given as an object is its ref, secrets given as objects their names. */
async function sentOp(op: JsonObject): Promise<JsonObject> {
  if (op.op === "set_connection") {
    const connection = op.connection as Connection | string | null;
    return { ...op, connection: connection === null ? null : ((await refId(connection)) ?? null) };
  }
  const settings = op.settings as JsonObject | undefined;
  if ((op.op === "add_step" || op.op === "update_step") && Array.isArray(settings?.secrets) && settings.secrets.length) {
    return { ...op, settings: { ...settings, secrets: await secretNames(settings.secrets) } };
  }
  return op;
}

/** A step's `settings`, with an agent step's `secrets` (sent as names). */
function stepSettings(settings: JsonObject | undefined, secrets: SecretRef[] | undefined): JsonObject | undefined {
  return secrets === undefined ? settings : { ...settings, secrets };
}

function addStepOp(type: string, options: AddStepOptions): JsonObject {
  return compact({
    op: "add_step", type, operation: options.operation, settings: stepSettings(options.settings, options.secrets),
    name: options.name, id: options.id ?? newId(type),
    position: options.position ? { x: options.position.x, y: options.position.y } : undefined,
  });
}

function updateStepOp(step: StepRef, update: StepUpdate): JsonObject {
  return compact({
    op: "update_step", id: stepId(step), settings: stepSettings(update.settings, update.secrets), name: update.name,
    operation: update.operation, enabled: update.enabled,
  });
}

function edgeOp(op: string, from: StepRef, to: StepRef, fields: JsonObject): JsonObject {
  return { op, from: stepId(from), to: stepId(to), ...compact(fields) };
}

function noteOp(content: string, options: AddNoteOptions): JsonObject {
  return {
    op: "add_note", content, id: options.id ?? newId(NOTE),
    ...compact({
      color: options.color, near: options.near?.map(stepId), direction: options.direction,
      after: options.after === undefined ? undefined : stepId(options.after),
      before: options.before === undefined ? undefined : stepId(options.before), width: options.width, height: options.height,
      position: options.position ? { x: options.position.x, y: options.position.y } : undefined,
    }),
  };
}

function updateWorkflowOp(update: WorkflowUpdate): JsonObject {
  return compact({
    op: "update_workflow", name: update.name, description: update.description, settings: update.settings,
    display_metadata: update.displayMetadata, interface: update.interface,
  });
}

/**
 * The definition an answer carries beside its graph (`GET .../graph`, an edit with `includeGraph`, one version), or
 * null when it carries none.
 */
function definitionOf(raw: JsonObject, workflow: Workflow): WorkflowGraph | null {
  if (!raw.graph || typeof raw.graph !== "object") return null;
  return new WorkflowGraph(raw.graph, { workflow, workflowId: str(raw.workflow_id) ?? "", version: raw.version as number, definition: raw });
}

const numberOrNull = (value: unknown): number | null => (typeof value === "number" ? value : null);

function toWorkflowEdit(value: unknown, workflow: Workflow): WorkflowEdit {
  const raw = asObject(value);
  const steps: Record<string, JsonObject> = {};
  for (const [id, verdict] of Object.entries(asObject(raw.steps))) steps[id] = asObject(verdict);
  return {
    workflowId: str(raw.workflow_id) ?? "",
    version: raw.version as number,
    historyVersion: numberOrNull(raw.history_version),
    changed: raw.changed === true,
    summary: str(raw.summary),
    results: Array.isArray(raw.results) ? raw.results.map(asObject) : [],
    steps,
    graph: definitionOf(raw, workflow),
    restoredFrom: numberOrNull(raw.restored_from),
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
    settled: typeof raw.settled === "boolean" ? raw.settled : null,
    unregistered: Object.fromEntries(Object.entries(asObject(raw.unregistered)).map(([k, v]) => [k, String(v)])),
    raw,
  };
}

function toAuthor(value: unknown): { user_id: string; key_id: string | null } {
  const raw = asObject(value);
  return { user_id: str(raw.user_id) ?? "", key_id: str(raw.key_id) };
}

function toWorkflowVersion(value: unknown, workflow: Workflow): WorkflowVersion {
  const raw = asObject(value);
  return {
    workflowId: str(raw.workflow_id) ?? "",
    historyVersion: raw.history_version as number,
    version: raw.version as number,
    source: str(raw.source) ?? "",
    author: raw.author && typeof raw.author === "object" ? toAuthor(raw.author) : null,
    authors: Array.isArray(raw.authors) ? raw.authors.map(toAuthor) : [],
    summary: str(raw.summary),
    changes: Array.isArray(raw.changes) ? raw.changes.map(String) : [],
    restoredFrom: numberOrNull(raw.restored_from),
    createdAt: parseTime(raw.created_at),
    updatedAt: parseTime(raw.updated_at),
    graph: definitionOf(raw, workflow),
    label: str(raw.label),
    note: str(raw.note),
    labeledBy: raw.labeled_by && typeof raw.labeled_by === "object" ? { user_id: String(asObject(raw.labeled_by).user_id) } : null,
    labeledAt: parseTime(raw.labeled_at),
    raw,
  };
}

/**
 * One step of a workflow's graph: its trigger, an app's operation, an agent, a note. `Workflow.graph()` reads them
 * all; `Workflow.step(id)` is a handle to one by id (`await step.hydrate()` loads its fields).
 *
 * Its fields are as stored: `type` (`automation-gmail`, `agent`, `trigger-cron`), its `name` in the app, the
 * `operation` it does, whether it's `enabled`, its `settings` (never a secret: `withheld` names the ones left out),
 * its `connections` (each slot's connected account, by id), where it sits (`position`) and the output it gives on
 * test runs instead of running (`mockOutput`). A note on the canvas is a step of type `stickyNote` (its text is
 * `settings.content`), listed in `WorkflowGraph.notes`.
 *
 * Each method is one edit, applied as its own version: the step comes back as written, with what the edit said
 * about it (`notes`) and whether it's ready to run (`verdict`). To change several things at once, or only if the
 * workflow hasn't changed since you read it, use `Workflow.edit()`.
 */
export class Step extends ApiObject {
  /** @internal */ _workflow!: Workflow;
  /** @internal */ _withheld: string[] = [];
  /** @internal */ _verdict: JsonObject | null = null;
  /** @internal */ _notes: JsonObject = {};

  protected constructor(init: ObjectInit) {
    super({ ...init, user: null });
  }

  /** @internal */
  static _of(workflow: Workflow, id: string, node: JsonObject | null = null, withheld: string[] = []): Step {
    const step = new Step({ raw: node, hints: { id }, client: workflow._client });
    step._workflow = workflow;
    step._withheld = [...withheld];
    return step;
  }

  override _callScope(): null {
    return null;
  }

  /** @internal */
  _fromGraph(graph: WorkflowGraph): JsonObject {
    const node = graph._node(this.id);
    if (!node) {
      throw new NotFound(`No step "${this.id}" in this workflow.`, {
        nextStep: "Read its steps with (await workflow.graph()).steps.",
        details: { step: this.id },
      });
    }
    this._withheld = [...(graph.withheld[this.id] ?? [])];
    return node;
  }

  protected async _load(): Promise<JsonObject> {
    return this._fromGraph(await this._workflow._readGraph());
  }

  override async _ensure(): Promise<JsonObject> {
    if (!this._raw) {
      const cached = this._workflow._graph;
      this._raw = cached?._node(this.id) ? this._fromGraph(cached) : await this._load();
    }
    return this._raw;
  }

  private config(): JsonObject {
    return nodeConfig(this.raw);
  }

  /** Its id in the workflow, which edits name it by. */
  get id(): string {
    return String(this._hints.id);
  }
  /** The workflow it's a step of. */
  get workflow(): Workflow {
    return this._workflow;
  }
  /** What kind of step it is: `automation-gmail`, `agent`, `trigger-cron`, `stickyNote` for a note. */
  get type(): string {
    return str(this.raw.type) ?? "";
  }
  /** Its name in the app (`null` when it has none and the app shows its type). */
  get name(): string | null {
    return str(this.config().label) || null;
  }
  /** What it does, one of its type's operations (`null` for a step with one thing to do). */
  get operation(): string | null {
    return str(this.config().operation) || null;
  }
  /** Whether it runs: a step switched off (`update({ enabled: false })`) is passed over. */
  get enabled(): boolean {
    return !(this.raw.disabled || this.config().disabled);
  }
  /** Its settings, by field name, as stored (a secret is never read back: see `withheld`). */
  get settings(): JsonObject {
    const out: JsonObject = {};
    for (const [key, value] of Object.entries(this.config())) if (!OWN_FIELDS.has(key) && !key.endsWith("__label")) out[key] = value;
    return out;
  }
  /**
   * The accounts connected to it: each slot (a connection type, like `gmail_oauth`) to the id of the account there,
   * which the connection holding it names as its `credentialId`.
   */
  get connections(): Record<string, string> {
    return { ...(asObject(this.config().credentialIds) as Record<string, string>) };
  }
  /** Where it sits on the canvas. */
  get position(): Position | null {
    const found = this.raw.position;
    return found && typeof found === "object" ? { ...(found as Position) } : null;
  }
  /** What it outputs on test runs instead of running (`mock()`), or `null`. */
  get mockOutput(): unknown {
    const config = this.config();
    return "mockedOutput" in config ? config.mockedOutput : (this.raw.mockedOutput ?? null);
  }
  /**
   * The settings left out of `settings` because they hold a secret (a key, a token, a password), each by its path:
   * `api_key`, `auth.password`, `headers[0].value`. An update that leaves them out keeps them.
   */
  get withheld(): string[] {
    void this.raw;
    return [...this._withheld];
  }
  /**
   * Whether it's ready to run, as the last edit through this handle that touched it judged: `config_valid`, and
   * when it isn't, `validation_error` and `missing_required`; an agent's `agent_credential_hint`; and `references`
   * (see `references`). `null` until an edit judged it (a read doesn't).
   */
  get verdict(): JsonObject | null {
    return this._verdict;
  }
  /**
   * Each read of another step's output in its settings (`{{ $('x').key }}`) that won't resolve at run time, as the
   * last edit through this handle that touched it judged: `{field, step, key, known_keys}` for a key `x`'s output
   * isn't known to have (`known_keys`: what it has, from what `x` declares, its latest output in this workflow, or
   * what your account's own runs of its type showed), or `{field, step, reference, missing, near}` for a step `x`
   * the workflow doesn't have (`near`: the one it likely means). A read of a step whose output nothing has shown yet
   * isn't judged. Empty when every read resolves, or before an edit judged it.
   */
  get references(): JsonObject[] {
    const found = this._verdict?.references;
    return Array.isArray(found) ? (found as JsonObject[]) : [];
  }
  /**
   * What the last edit through this handle answered for its change, beyond the step's id: `changed` for an
   * update, the edge for a connect, and anything the edit did on its own, such as `resolutions`,
   * `harness_switch`, `coerced_values` or `stripped_trigger_refs`.
   */
  get notes(): JsonObject {
    return { ...this._notes };
  }

  /** @internal This step as `edit` wrote it, with what it said about it. */
  _absorb(edit: WorkflowEdit, result: JsonObject | null = null): void {
    const node = edit.graph?._node(this.id);
    if (node && edit.graph) {
      this._raw = node;
      this._withheld = [...(edit.graph.withheld[this.id] ?? [])];
    }
    if (result) {
      const { op: _op, id: _id, ...notes } = result;
      this._notes = notes;
    }
    if (this.id in edit.steps) this._verdict = edit.steps[this.id];
  }

  /** @internal */
  async _edit(op: JsonObject, ...also: StepRef[]): Promise<this> {
    const edit = await this._workflow._send([op], { includeGraph: true });
    this._absorb(edit, edit.results[0] ?? null);
    for (const other of also) if (other instanceof Step && other !== this) other._absorb(edit);
    return this;
  }

  /**
   * Change its settings, name or operation, or switch it off or on. `settings` merge into what it has (a nested
   * object merges, any other value replaces, and `null` takes that setting out, a secret included); a field you leave
   * out is never touched. An agent given another
   * `model` on another harness drops the old harness's own settings and connections, as the app does
   * (`notes.harness_switch` says what went). A value that can't be is refused with `InvalidRequest` naming the
   * field, and nothing changes. Resolves to this step as written, with `notes` and `verdict`.
   */
  async update(update: StepUpdate): Promise<this> {
    return await this._edit(updateStepOp(this, update));
  }

  /**
   * Change part of one long text setting (an agent's instructions, a step's code) with a patch: `@@` lines naming
   * text that's there, then `-` lines to remove and `+` lines to add.
   */
  async patch(field: string, patch: string): Promise<this> {
    return await this._edit({ op: "patch_step", id: this.id, field, patch });
  }

  /**
   * Take the step out of the workflow, with its edges. A trigger's schedule or webhook stops with it. Removing a step
   * that holds an app, conversations or files deletes them for good, so it may be held for the account's owner
   * (`ApprovalRequired`), as a batch is (`Workflow.edit`).
   */
  async remove(): Promise<void> {
    await this._workflow._send([{ op: "remove_step", id: this.id }], { includeGraph: true });
  }

  /**
   * Wire this step into `other`. `kind: "data"` runs `other` after it with its output; `kind: "tools"` makes its
   * operations tools of `other`, an agent (or an MCP step). `handle` names which of this step's outputs, for a step
   * with several, and `targetHandle` which of `other`'s inputs (a code step's `state`). Connecting what's already
   * connected changes nothing; `notes` holds the edge.
   */
  async connect(other: StepRef, options: { kind?: "data" | "tools"; handle?: string; targetHandle?: string } = {}): Promise<this> {
    return await this._edit(edgeOp("connect", this, other, {
      kind: options.kind ?? "data", handle: options.handle, target_handle: options.targetHandle,
    }), other);
  }

  /** Remove the edge from this step to `other`; one that isn't there throws `InvalidRequest`. */
  async disconnect(other: StepRef, options: { handle?: string } = {}): Promise<this> {
    return await this._edit(edgeOp("disconnect", this, other, { handle: options.handle }), other);
  }

  /**
   * Connect an account to the step: one of the account's own connections, as a `Connection` (connected in the app,
   * `credential:<id>`, or a named one), its ref or id, or a named connection's name; the step takes the account it
   * holds. Its slot is the account's own type unless `slot` names it; `null` with `slot` takes the account in that
   * slot off. One of a user's connections, one holding no working account, or one your account may not use is
   * refused (`InvalidRequest` naming it), as is one of a type the step doesn't take; a caller that doesn't act for
   * the whole account (a user's key, an app's code) only keeps one the workflow already uses. An agent's own tools
   * attach your account's own connections in your account's own workflows, never another member's, a user's or one
   * held for someone else, as your approval settings let them (`attach_connection`: allowed by default; asked, the
   * edit waits for the owner's yes, `ApprovalRequired`).
   */
  async setConnection(connection: Connection | string | null, options: { slot?: string } = {}): Promise<this> {
    return await this._edit({ op: "set_connection", id: this.id, connection, ...compact({ slot: options.slot }) });
  }

  /** Have the step give `output` on test runs instead of running, so the steps after it can be tried. */
  async mock(output: unknown): Promise<this> {
    return await this._edit({ op: "mock_step", id: this.id, output });
  }

  /** Have the step run for real on test runs again. */
  async unmock(): Promise<this> {
    return await this._edit({ op: "unmock_step", id: this.id });
  }

  /**
   * Run the workflow from this step: it and what comes after it (`only: true`: it alone), the steps before it giving
   * the outputs they last stored. `Workflow.run` with `fromStep` says more.
   */
  async run(options: Omit<WorkflowRunOptions, "fromStep"> = {}): Promise<Operation<WorkflowRun>> {
    return await this._workflow.run({}, { ...options, fromStep: this.id });
  }

  /**
   * What the step produced, run by run, newest first, each a `StepOutput` with its run, how that run started, the
   * step's status there and a one-line `preview`. A trigger's deliveries are its outputs (`noEvent` marks a manual
   * run's placeholder). `search` keeps those holding the text (any case), reading 100 at a time. Inside `asUser` (or
   * with `user`) only the runs recorded for that user are read. The newest `limit` (10 by default; `null` for every
   * one).
   */
  async outputs(options: CallOptions & { search?: string; limit?: number | null } = {}): Promise<StepOutput[]> {
    const { search, limit, ...call } = options;
    const path = await this._workflow._stepOutputsPath(this.id);
    const first = limit === undefined ? 10 : (limit ?? undefined);
    return await listAll({ ...call, client: call.client ?? this._client, path, query: { search }, limit: first }, (raw) => toStepOutput(raw));
  }

  /**
   * What the step produced in one run (`runId`, as `outputs()` or `Workflow.runs()` name it): its `output`, long text
   * and lists cut short unless `full`, or only the part at `path` (`payload.items[0].id`, as a preview names it).
   * `iteration` reads one iteration of a step that runs in a loop. Never a secret (`withheld`); a path to one throws
   * `InvalidRequest`, as does a path that isn't there (naming what is). A run the step stored nothing in throws
   * `NotFound`.
   */
  async output(runId: string, options: StepOutputOptions = {}): Promise<StepOutput> {
    const { path, full, iteration, client, user } = options;
    const raw = await (client ?? this._api).request("GET", `${await this._workflow._stepOutputsPath(this.id)}/${runId}`, {
      query: { path, full: full ? "true" : undefined, iteration },
      user,
    });
    return toStepOutput(raw);
  }

  /**
   * What an expression in one of the step's settings gives, evaluated as a run evaluates it (what goes inside `{{ }}`,
   * like `$('hook').order_id` or `$json.items.length`), as the app's editor previews it while you type. It's evaluated
   * against what every other step last stored (never a secret, so an expression reaching one finds nothing there),
   * or against `samples`, each step's output by step id (`vars` the workflow's variables). `$json` is the step's one
   * input's output, when it has one. Changes nothing; an expression that fails resolves with `ok` false and its
   * `error`.
   */
  async previewExpression(expression: string, options: CallOptions & { samples?: JsonObject } = {}): Promise<ExpressionPreview> {
    const { samples, client, user } = options;
    const raw = await (client ?? this._api).request("POST", `${await this._workflow._stepPath(this.id)}/expression`, {
      json: { expression, ...compact({ samples }) },
      user,
    });
    return toExpressionPreview(raw);
  }

  /**
   * Forget what the step keeps between runs, as the app's Clear state does: its state (an RSS step's seen items, a
   * State step's values) and its conversations (an agent step's threads), so its next run starts fresh. Clearing an
   * agent step deletes its conversations for good: a deletion, which through MCP waits for your account's owner (preview
   * it with `POST /v1/delete_previews`). Takes what changing the workflow takes, and always acts for your account, never
   * one of your users: an agent step's threads are every user's.
   */
  async clearState(): Promise<ClearedStepState> {
    const raw = asObject(await this._api.request("POST", `${await this._workflow._stepPath(this.id)}/clear_state`, { user: null }));
    return {
      stepId: str(raw.step_id) ?? this.id,
      stateRowsDeleted: Number(raw.state_rows_deleted ?? 0),
      conversationsDeleted: Number(raw.conversations_deleted ?? 0),
      raw,
    };
  }

  /**
   * The choices `field` takes, as the app's dropdown lists them: read from the account the step connects to (a
   * Google account's spreadsheets, a Slack workspace's channels) by the step's own lookup, with its settings as saved
   * and `settings` laid over them (what a list that depends on another reads, like the tabs of a spreadsheet you
   * haven't saved yet). `search` narrows them where the service can search. A page at a time: pass `pageToken` its
   * `nextPageToken`. A connection whose owner reviews its calls holds the lookup for them (`ApprovalRequired`).
   * Takes edit access to the workflow.
   */
  async options(field: string, query: StepOptionsQuery = {}): Promise<StepOptions> {
    return toStepOptions(await this._request("POST", `${await this._workflow._stepPath(this.id)}/options`, {
      json: compact({ field, settings: query.settings, search: query.search, page_token: query.pageToken }),
    }));
  }

  /**
   * A widget's value on the step, as the app loads it beside the step's settings: a trigger's address, minted and
   * registered where its events come from (`webhook_url`), an app's event subscription (`subscription_status`), the
   * files in a filesystem step's volume (`file_browser`), an alarm's schedules (`active_alarms`), an MCP step's
   * hosted link (`hosted_url`). `settings` are laid over the step's saved ones. One that mints or registers something
   * changes the account; a hosted MCP link's URL is its capability, so no MCP connection loads it. Takes edit access
   * to the workflow.
   */
  async value(field: string, options: { settings?: JsonObject } = {}): Promise<StepValue> {
    return toStepValue(await this._request("POST", `${await this._workflow._stepPath(this.id)}/values`, {
      json: compact({ field, settings: options.settings }),
    }));
  }

  private async publication(body: JsonObject): Promise<StepPublication> {
    return toStepPublication(await this._api.request("POST", `${await this._workflow._stepPath(this.id)}/publish`, {
      json: compact(body),
      user: null,
    }));
  }

  /**
   * Put this interface step's app live as the app's canvas does, with no build: at `subdomain` the first time
   * (`morrow` is morrow.noclick.app); again, the saved edits at the address it has (a `subdomain` other than its own
   * throws `Conflict`: `renameApp` moves it). An app in the trash comes back where it was. Takes what changing the
   * workflow takes, and through MCP `deploy`, as `Workflow.publish` does.
   *
   * @example
   * const page = Workflow.fromName("Morrow Bakehouse site").step("page");
   * console.log((await page.publish({ subdomain: "morrow" })).url); // https://morrow.noclick.app
   */
  async publish(options: PublishOptions = {}): Promise<StepPublication> {
    return await this.publication({ action: "publish", subdomain: options.subdomain, title: options.title });
  }

  /** Move this interface step's app to `subdomain`, publishing no edits; its old address stops answering. */
  async renameApp(subdomain: string): Promise<StepPublication> {
    return await this.publication({ action: "rename", subdomain });
  }

  /**
   * Take this interface step's app down, to the trash: its public URL stops answering and its page's key stops
   * working. For 30 days its address stays its own, and restoring it (or `publish()`) brings it back there with the
   * same key; the result's `trashId` restores it. One not published changes nothing.
   */
  async unpublish(): Promise<StepPublication> {
    return await this.publication({ action: "unpublish" });
  }
}

/**
 * A workflow's definition as it was read, at `version`: its `name`, `description` and `settings` (its variables,
 * its Test Runs and the rest), its `steps` (each a `Step` you can change), its `notes` (steps of type `stickyNote`)
 * and its `edges`.
 *
 * A secret is never read back, and writing a step or the settings back without one keeps it: `withheld` names, by
 * step id, the paths of the settings left out (`api_key`, `auth.password`, `headers[0].value`), `settingsWithheld`
 * those of the workflow's own settings (`variable_definitions[1].value`), and `variablesWithheld` the graph's own
 * variables. The graph a `Conflict` carries holds the steps and edges alone: its `name`, `description`,
 * `settings` and `settingsWithheld` are `null`. `displayMetadata` is what the app shows of the workflow (its
 * canvas's viewport, the step open in its panel), read with `graph()`: never part of a version.
 */
export class WorkflowGraph {
  readonly workflowId: string;
  readonly version: number;
  readonly name: string | null;
  readonly description: string | null;
  readonly settings: JsonObject | null;
  readonly settingsWithheld: string[] | null;
  readonly steps: Step[];
  readonly notes: Step[];
  readonly edges: GraphEdge[];
  readonly withheld: Record<string, string[]>;
  readonly variablesWithheld: string[];
  readonly displayMetadata: JsonObject | null;
  readonly raw: JsonObject;

  /**
   * @internal `value`: the graph (`nodes`, `edges`, `withheld`); `definition`: the answer it came in, with the
   * workflow's own fields beside it (none for a conflict's).
   */
  constructor(value: unknown, init: { workflow: Workflow; workflowId: string; version: number; definition?: JsonObject }) {
    const raw = asObject(value);
    const withheld: Record<string, string[]> = {};
    for (const [id, names] of Object.entries(asObject(raw.withheld))) withheld[id] = Array.isArray(names) ? names.map(String) : [];
    const nodes = (Array.isArray(raw.nodes) ? raw.nodes : []).map(asObject).filter((node) => node.id !== undefined && node.id !== null);
    const made = nodes.map((node) => Step._of(init.workflow, String(node.id), node, withheld[String(node.id)] ?? []));
    const own = init.definition;
    this.workflowId = init.workflowId;
    this.version = init.version;
    this.name = own ? str(own.name) : null;
    this.description = own ? str(own.description) : null;
    this.settings = own?.settings && typeof own.settings === "object" ? { ...asObject(own.settings) } : null;
    this.settingsWithheld = own ? (Array.isArray(own.settings_withheld) ? own.settings_withheld.map(String) : []) : null;
    this.steps = made.filter((_, i) => nodes[i].type !== NOTE);
    this.notes = made.filter((_, i) => nodes[i].type === NOTE);
    this.edges = (Array.isArray(raw.edges) ? raw.edges : []).map(toEdge);
    this.withheld = withheld;
    this.variablesWithheld = Array.isArray(raw.variables_withheld) ? raw.variables_withheld.map(String) : [];
    this.displayMetadata = own?.display_metadata && typeof own.display_metadata === "object" ? { ...asObject(own.display_metadata) } : null;
    this.raw = raw;
  }

  /** @internal */
  _node(id: string): JsonObject | null {
    const nodes = Array.isArray(this.raw.nodes) ? this.raw.nodes.map(asObject) : [];
    return nodes.find((node) => String(node.id) === id) ?? null;
  }

  /**
   * One of its steps or notes, by id, else by its name in the app. None by that id or name throws `NotFound`; a
   * name two steps share throws `Conflict` (name it by id).
   */
  step(ref: string): Step {
    const everything = [...this.steps, ...this.notes];
    const found = everything.find((step) => step.id === ref);
    if (found) return found;
    const named = everything.filter((step) => step.name === ref);
    if (named.length > 1) {
      throw new Conflict(`${named.length} steps are named "${ref}".`, {
        nextStep: "Name the step by its id.",
        details: { name: ref, ids: named.map((step) => step.id) },
      });
    }
    if (!named.length) {
      throw new NotFound(`No step has the id or name "${ref}".`, {
        nextStep: "Read the steps' ids and names with graph.steps.",
        details: { step: ref },
      });
    }
    return named[0];
  }
}

/**
 * The edits `Workflow.edit()` collects: each method queues one, and they're sent as one batch once the function
 * you hand `edit()` resolves, applied in order as one version, or not at all (an op that can't apply throws
 * `InvalidRequest` naming it, and nothing of the batch lands). A function that throws sends nothing.
 *
 * Steps are named by `Step` or by id; a step `addStep` queues has its id already, so later edits in the batch can
 * name it. Once sent, `result` is the `WorkflowEdit`.
 */
export class EditBatch {
  /** @internal */ readonly _workflow: Workflow;
  /** @internal */ readonly _options: EditOptions;
  /** @internal */ readonly _ops: JsonObject[] = [];
  /** @internal */ readonly _added: [number, Step][] = [];
  /** @internal */ _result: WorkflowEdit | null = null;

  /** @internal */
  constructor(workflow: Workflow, options: EditOptions) {
    this._workflow = workflow;
    this._options = options;
  }

  /** The edits queued so far, as the API takes them (a connection given as an object is resolved when sent). */
  get ops(): JsonObject[] {
    return this._ops.map((op) => ({ ...op }));
  }

  /** What the batch did, once it was sent (`null` before, or when nothing was queued). */
  get result(): WorkflowEdit | null {
    return this._result;
  }

  private queue(op: JsonObject): void {
    if (this._result) throw new Error("This batch was sent already: start another with workflow.edit().");
    this._ops.push(op);
  }

  /** @internal */
  async _send(): Promise<WorkflowEdit | null> {
    if (!this._ops.length) return null;
    const edit = await this._workflow._send(this._ops, this._options);
    for (const [index, step] of this._added) step._absorb(edit, edit.results[index] ?? null);
    this._result = edit;
    return edit;
  }

  /**
   * Queue a new step of `type` (`automation-gmail`, `agent`, `trigger-cron`), doing `operation` with `settings`.
   * `id` names it (made from its type when left out); without `position` it's laid out beside the rest. Returns
   * the step, whose `id` later edits in the batch can name.
   */
  addStep(type: string, options: AddStepOptions = {}): Step {
    const op = addStepOp(type, options);
    this.queue(op);
    const step = Step._of(this._workflow, String(op.id));
    this._added.push([this._ops.length - 1, step]);
    return step;
  }

  /** Queue a change to a step, as `Step.update` makes it. */
  updateStep(step: StepRef, update: StepUpdate): void {
    this.queue(updateStepOp(step, update));
  }

  /** Queue a patch to one long text setting of a step, as `Step.patch` makes it. */
  patchStep(step: StepRef, field: string, patch: string): void {
    this.queue({ op: "patch_step", id: stepId(step), field, patch });
  }

  /** Queue taking a step (or a note) out, with its edges. */
  removeStep(step: StepRef): void {
    this.queue({ op: "remove_step", id: stepId(step) });
  }

  /**
   * Queue an edge from `source` into `target`, as `Step.connect` makes it; `id` names the edge (made for it when left
   * out), as a canvas names its own.
   */
  connect(source: StepRef, target: StepRef, options: { kind?: "data" | "tools"; handle?: string; targetHandle?: string; id?: string } = {}): void {
    this.queue(edgeOp("connect", source, target, {
      kind: options.kind ?? "data", handle: options.handle, target_handle: options.targetHandle, id: options.id,
    }));
  }

  /** Queue removing the edge from `source` into `target` (`id`: the one edge of that id, when two join them). */
  disconnect(source: StepRef, target: StepRef, options: { handle?: string; id?: string } = {}): void {
    this.queue(edgeOp("disconnect", source, target, { handle: options.handle, id: options.id }));
  }

  /** Queue connecting an account to a step, as `Step.setConnection` does (`null` with `slot` takes one off). */
  setConnection(step: StepRef, connection: Connection | string | null, options: { slot?: string } = {}): void {
    this.queue({ op: "set_connection", id: stepId(step), connection: connection as unknown, ...compact({ slot: options.slot }) });
  }

  /** Queue giving a step `output` on test runs instead of running it. */
  mockStep(step: StepRef, output: unknown): void {
    this.queue({ op: "mock_step", id: stepId(step), output });
  }

  /** Queue having a step run for real on test runs again. */
  unmockStep(step: StepRef): void {
    this.queue({ op: "unmock_step", id: stepId(step) });
  }

  /** Queue a change to the workflow's own fields, as `Workflow.update` makes it. */
  updateWorkflow(update: WorkflowUpdate): void {
    this.queue(updateWorkflowOp(update));
  }

  /**
   * Queue moving a step (or a note) on the canvas, and for one drawn at a size (a note) giving it `width` and
   * `height`. Moving things is never a version of its own.
   */
  move(step: StepRef, position: Position, size: { width?: number; height?: number } = {}): void {
    this.queue({ op: "move", id: stepId(step), position: { x: position.x, y: position.y }, ...compact({ width: size.width, height: size.height }) });
  }

  /** Queue laying every step out again, as the app's Tidy up does. */
  layout(): void {
    this.queue({ op: "layout" });
  }

  /** Queue a note on the canvas, as `Workflow.addNote` makes it; returns the note, whose `id` later edits can name. */
  addNote(content: string, options: AddNoteOptions = {}): Step {
    const op = noteOp(content, options);
    this.queue(op);
    const note = Step._of(this._workflow, String(op.id));
    this._added.push([this._ops.length - 1, note]);
    return note;
  }

  /**
   * Queue defining a workflow variable: a value its steps read as `{{vars.name}}`, changed in one place. `perUser`
   * asks each person who copies the workflow for their own. Only the workflow's owner defines one.
   */
  defineVariable(name: string, options: { value?: string; description?: string; perUser?: boolean } = {}): void {
    this.queue(compact({ op: "define_variable", name, value: options.value ?? "", description: options.description, per_user: options.perUser || undefined }));
  }

  /**
   * Queue a Test Run: a message staged on `trigger` (a trigger step wired into an agent, or its type) that the
   * app's Test Run plays to the agent. Only the workflow's owner adds one.
   */
  addTestRun(trigger: StepRef, name: string, body: string, options: { title?: string; author?: string; handle?: string } = {}): void {
    this.queue(compact({ op: "add_test_run", trigger: stepId(trigger), name, body, title: options.title, author: options.author, handle: options.handle }));
  }
}

export interface WorkflowRunOptions extends CallOptions {
  idempotencyKey?: string;
  /**
   * Run this step and what comes after it instead, the steps before it giving the outputs they last stored, as the
   * app's Run from here does. A run from a step takes no inputs, unless it's a trigger that does.
   */
  fromStep?: StepRef;
  /** With `fromStep`: run that step alone, nothing after it. */
  only?: boolean;
}

/**
 * A workflow built in the NoClick app: its trigger, steps and outputs. Run it with
 * `run(inputs)`; `inputs` names what its trigger takes. `access` is your account's: `owner`,
 * `editor` or `viewer` (one shared with it); building, running, testing and publishing it take
 * edit access, billed to whoever pays for it (a team workspace's owner; its app stays its owner's);
 * pausing and deleting it take owning it and paying for it.
 *
 * It's also a handle to its graph: `graph()` reads its steps whole, each `Step` changes with one
 * call, and `edit()` sends several changes as one version, checked against the version you read
 * (`version`) when you say so. Editing takes edit access, as the app's canvas does: an `editor`
 * edits a workflow shared with it.
 */
export class Workflow extends ApiObject {
  /** @internal The graph as this handle last read or wrote it (null: read it again), and the version it was at. */
  _graph: WorkflowGraph | null = null;
  /** @internal */ _version: number | null = null;
  /** @internal */ _lastEdit: WorkflowEdit | null = null;
  /** @internal The fields `fromName` sets on the workflow it finds. */
  _createWith: { description?: string } | null = null;

  protected constructor(init: ObjectInit) {
    super({ ...init, user: null });
  }

  /** Workflow routes are account-level; only a run acts for a user. */
  override _callScope(): null {
    return null;
  }

  /**
   * A lazy reference to the workflow called `name` in the app; two with that name throw `Conflict` on first use,
   * and none `NotFound`. Given `description`, it gets the workflow, then sets its description when it differs,
   * every time it runs; nothing else about the workflow is touched.
   */
  static fromName(name: string, options: { description?: string; client?: NoClick } = {}): Workflow {
    const workflow = new Workflow({ hints: { name }, client: options.client });
    if (givesFields(options)) workflow._createWith = compact({ description: options.description }) as { description?: string };
    return workflow;
  }

  static fromId(workflowId: string, options: { client?: NoClick } = {}): Workflow {
    return new Workflow({ hints: { id: workflowId }, client: options.client });
  }

  static async get(workflowId: string, options: { client?: NoClick } = {}): Promise<Workflow> {
    return await Workflow.fromId(workflowId, options).hydrate();
  }

  /**
   * The workflows your account can open (its own and those shared with it), most recently changed first; `q` is a
   * prefix of the name, `search` text its name or description holds (in any case).
   */
  static async list(options: { q?: string; search?: string; limit?: number; client?: NoClick } = {}): Promise<Workflow[]> {
    return await listAll({ ...options, path: "/v1/workflows", user: null, query: { q: options.q, search: options.search } },
      (raw) => new Workflow({ raw, client: options.client }));
  }

  /** One page of workflows; pass `nextCursor` back as `cursor`. */
  static async listPage(options: PageOptions & { q?: string; search?: string; client?: NoClick } = {}): Promise<Page<Workflow>> {
    return await listPage({ ...options, path: "/v1/workflows", user: null, query: { q: options.q, search: options.search } },
      (raw) => new Workflow({ raw, client: options.client }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  get description(): string | null {
    return this._field("description");
  }
  /** A JSON schema of what `run` takes: a form's fields, any object for a webhook, empty if nothing. */
  get inputs(): JsonObject {
    return asObject(this._field("inputs"));
  }
  /** Where to open it in the NoClick app. */
  get appUrl(): string | null {
    return this._field("app_url");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  get updatedAt(): Date | null {
    return parseTime(this._field("updated_at"));
  }
  /** Your account's access: `owner`, `editor` or `viewer`. */
  get access(): string {
    return this._field("access");
  }
  /** The folder of your account's it's in (`Workflow.folders()`); null at the top, and for one shared with you. */
  get folderId(): string | null {
    return str(this._field("folder_id"));
  }
  /**
   * What it's made of, at a glance, in a list too: at most four of its step types, its triggers first, then its
   * agents (one on a coding harness as `agent:<harness>`, `agent:codex`), then the rest, never a note.
   */
  get stepTypes(): string[] {
    const raw = this._field<unknown>("step_types");
    return Array.isArray(raw) ? raw.map(String) : [];
  }
  /** Its steps in order, each with its settings, connection and trigger state (read with one workflow, not in a list). */
  get steps(): WorkflowStep[] {
    const raw = this._field<unknown>("steps");
    return Array.isArray(raw) ? raw.map(toStep) : [];
  }
  /** How its steps are wired. */
  get edges(): WorkflowEdge[] {
    const raw = this._field<unknown>("edges");
    return Array.isArray(raw) ? (raw as WorkflowEdge[]) : [];
  }
  /** Whether a pause switched its triggers off. */
  get paused(): boolean {
    return this._field<unknown>("paused") === true;
  }
  /** Whether it's set up to run, what its status means, and the issues in the way. */
  get readiness(): WorkflowReadiness {
    return toReadiness(this._field<unknown>("readiness"));
  }
  /** The URLs it answers at. */
  get urls(): WorkflowUrl[] {
    const raw = this._field<unknown>("urls");
    return Array.isArray(raw) ? (raw as WorkflowUrl[]) : [];
  }

  private startedBuild: WorkflowBuild | null = null;

  /** The build `create(..., { instructions })` or `build()` started here (`null` otherwise). */
  get latestBuild(): WorkflowBuild | null {
    if (this.startedBuild) return this.startedBuild;
    const raw = this._raw?.build;
    return raw ? WorkflowBuild._from(raw, { client: this._client }) : null;
  }

  /**
   * A new workflow in your account. With `instructions` NoClick's builder starts building it:
   * wait on `latestBuild`. A name your account already has throws `Conflict` (change that one with
   * `build`).
   */
  static async create(
    name: string,
    options: { instructions?: string; description?: string; client?: NoClick } = {},
  ): Promise<Workflow> {
    const raw = await resolveClient(options.client).request<JsonObject>("POST", "/v1/workflows", {
      json: compact({ name, instructions: options.instructions, description: options.description }),
    });
    return new Workflow({ raw, client: options.client });
  }

  /**
   * Your account's workflow folders, as the app's Automations page shows them: the ones it made in its own workspace,
   * the shallowest first, then by name. A workflow's `folderId` names the one it's in.
   *
   *     for (const folder of await Workflow.folders()) console.log("  ".repeat(folder.depth) + folder.name);
   */
  static async folders(options: { client?: NoClick } = {}): Promise<WorkflowFolder[]> {
    const rows = await paginate(resolveClient(options.client), "/v1/workflows/folders", { user: null });
    return rows.map(toFolder);
  }

  /**
   * A new folder in your account's workspace, at the top or in `parent` (a folder or its id), as the app makes one. A
   * name `parent`'s folders already have throws `Conflict`, naming that folder (`folder_id`).
   *
   *     const reports = await Workflow.createFolder("Reports");
   *     await Workflow.fromName("Morning brief").moveTo(await Workflow.createFolder("Weekly", { parent: reports }));
   */
  static async createFolder(
    name: string,
    options: { description?: string; parent?: WorkflowFolder | string; client?: NoClick } = {},
  ): Promise<WorkflowFolder> {
    const raw = await resolveClient(options.client).request("POST", "/v1/workflows/folders", {
      json: compact({ name, description: options.description, parent_id: folderIdOf(options.parent ?? null) }),
      user: null,
    });
    return toFolder(asObject(raw));
  }

  /**
   * Delete one of your account's folders (a folder or its id), as the app does: the workflows in it move to its parent
   * (the top, for one at the top) and the folders in it go with it, their workflows moving to the top. No workflow is
   * deleted. Answers the folder as it was.
   *
   *     for (const folder of await Workflow.folders()) {
   *       if (folder.workflowCount === 0) await Workflow.deleteFolder(folder);
   *     }
   */
  static async deleteFolder(folder: WorkflowFolder | string, options: { client?: NoClick } = {}): Promise<WorkflowFolder> {
    const raw = await resolveClient(options.client).request(
      "DELETE", `/v1/workflows/folders/${encodeURIComponent(folderIdOf(folder) ?? "")}`, { user: null });
    return toFolder(asObject(raw));
  }

  /**
   * Move it into one of your account's folders (a folder or its id), or out to the top with `null`, as dragging it does
   * in the app. It takes what changing it takes: owning it and paying for it. Answers it read again, its `folderId`
   * the folder it's in now.
   *
   *     const brief = Workflow.fromName("Morning brief");
   *     await brief.moveTo(await Workflow.createFolder("Reports"));
   *     await brief.moveTo(null);   // back to the top
   */
  async moveTo(folder: WorkflowFolder | string | null): Promise<this> {
    return this.took(await this._request<JsonObject>("POST", `${await this.path()}/move`, {
      json: { folder_id: folderIdOf(folder) },
    }));
  }

  protected async _load(): Promise<JsonObject> {
    return this.took(await this.readView())._raw as JsonObject;
  }

  /** The workflow as an answer shows it (a read's, a pause's, a resume's), with the version it's at. */
  private took(raw: JsonObject): this {
    this._raw = raw;
    if (typeof raw.version === "number") this._version = raw.version;
    return this;
  }

  private async readView(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/workflows/${id}`);
    const name = String(this._hints.name);
    const page = await this._request("GET", "/v1/workflows", { query: { name } });
    const rows = (asList(page) as JsonObject[]).filter((row) => row.name === name);
    if (!rows.length) {
      throw new NotFound(`No workflow is named "${name}".`, {
        nextStep: "Check the name in the NoClick app, or list them with Workflow.list().",
        details: { name },
      });
    }
    if (rows.length > 1) {
      throw new Conflict(`${rows.length} workflows are named "${name}".`, {
        nextStep: "Rename one in the app, or use Workflow.fromId(...).",
        details: { name, ids: rows.map((row) => row.id) },
      });
    }
    return await this.converge(rows[0]);
  }

  /** Set the fields `fromName` was given on the workflow it found, where they differ. */
  private async converge(row: JsonObject): Promise<JsonObject> {
    const description = this._createWith?.description;
    if (description === undefined || row.description === description) return row;
    const path = `/v1/workflows/${String(row.id)}`;
    this._wrote(await this._request("POST", `${path}/edits`, { json: { ops: [updateWorkflowOp({ description })] } }));
    return await this._request<JsonObject>("GET", path);
  }

  private async path(): Promise<string> {
    const id = this._known("id");
    return `/v1/workflows/${typeof id === "string" ? id : (await this._ensure()).id}`;
  }

  /** @internal Where one of its steps is (its id one path segment). */
  async _stepPath(stepId: string): Promise<string> {
    return `${await this.path()}/steps/${encodeURIComponent(stepId)}`;
  }

  /** @internal Where one of its steps' outputs are read. */
  async _stepOutputsPath(stepId: string): Promise<string> {
    return `${await this._stepPath(stepId)}/outputs`;
  }

  // --- its graph --------------------------------------------------------

  /**
   * Its version as this handle last read or wrote it: what `edit({ ifVersion })` checks against. Every change to its
   * definition moves it on, and so do NoClick's own records of a trigger's registration. Throws until the workflow
   * is loaded (`hydrate()`), its graph read or an edit made.
   */
  get version(): number | null {
    return this._version ?? this._field<number | null>("version") ?? null;
  }

  /** What this handle's last edit did (`null` until one): its version, summary, each op's results and verdicts. */
  get lastEdit(): WorkflowEdit | null {
    return this._lastEdit;
  }

  /** @internal */
  async _readGraph(): Promise<WorkflowGraph> {
    const raw = asObject(await this._request("GET", `${await this.path()}/graph`));
    const graph = new WorkflowGraph(raw.graph, {
      workflow: this, workflowId: str(raw.workflow_id) ?? "", version: raw.version as number, definition: raw,
    });
    this._graph = graph;
    this._version = graph.version;
    return graph;
  }

  /**
   * Read its definition whole: its name, description and settings, every step with its settings as stored (never a
   * secret), its notes and edges, at its current `version`, which this handle's `version` now is.
   */
  async graph(): Promise<WorkflowGraph> {
    return await this._readGraph();
  }

  /**
   * A handle to one of its steps by id. Nothing is sent: an edit through it names the step by its id, and
   * `await step.hydrate()` loads its fields from the graph (a step that isn't there throws `NotFound` then).
   */
  step(id: string): Step {
    const cached = this._graph?._node(id) ?? null;
    return Step._of(this, id, cached, cached ? (this._graph?.withheld[id] ?? []) : []);
  }

  /** @internal One batch of `ops`; a refusal for a stale version carries the workflow as it stands (`Conflict.graph`). */
  async _send(ops: JsonObject[], options: EditOptions = {}): Promise<WorkflowEdit> {
    const path = await this.path();
    const sent: JsonObject[] = [];
    for (const op of ops) sent.push(await sentOp(op));
    let raw: unknown;
    try {
      raw = await this._request("POST", `${path}/edits`, {
        json: compact({
          ops: sent, if_version: options.ifVersion, include_graph: options.includeGraph || undefined, source: options.source,
          origin: options.origin, settle: options.settle || undefined,
        }),
        keepalive: options.keepalive,
      });
    } catch (err) {
      this._stale(err);
      throw err;
    }
    return this._wrote(raw);
  }

  /** @internal */
  _stale(err: unknown): void {
    if (!(err instanceof Conflict)) return;
    const graph = err.details.graph;
    const version = err.details.version;
    if (graph && typeof graph === "object" && typeof version === "number") {
      err.graph = new WorkflowGraph(graph, { workflow: this, workflowId: str(err.details.workflow_id) ?? "", version });
      this._graph = err.graph;
      this._version = version;
    }
  }

  /** @internal What a write did is this handle's now. */
  _wrote(raw: unknown): WorkflowEdit {
    const edit = toWorkflowEdit(raw, this);
    this._graph = edit.graph;
    this._version = edit.version;
    this._lastEdit = edit;
    // Its name, description and steps may have moved with the edit: the next read loads them again.
    if (edit.workflowId) {
      this._hints.id = edit.workflowId;
      this._raw = null;
    }
    return edit;
  }

  /**
   * Add a step of `type` (`automation-gmail`, `agent`, `trigger-cron`) doing `operation` with `settings`, as one
   * edit. `id` names it (made from its type when left out); without `position` it's laid out beside the rest. A
   * type, operation or value that can't be is refused with `InvalidRequest` naming it, and a setting it can't run
   * without yet is in its `verdict`. Resolves to the new `Step`, with its `verdict` and `notes`.
   */
  async addStep(type: string, options: AddStepOptions = {}): Promise<Step> {
    const op = addStepOp(type, options);
    return await Step._of(this, String(op.id))._edit(op);
  }

  /**
   * Change its name, description or settings (by top-level key; only its owner changes those). A field you leave
   * out is never touched. Resolves to this workflow, which loads again the next time you read a field.
   */
  async update(update: WorkflowUpdate): Promise<this> {
    await this._send([updateWorkflowOp(update)], { includeGraph: true });
    return this;
  }

  /**
   * Put a note on the canvas: `near` some steps (`direction`: `above`, the default, `below`, `left` or `right`), or
   * over a stretch of them from `after` to `before`. Resolves to the note: a `Step` of type `stickyNote`.
   */
  async addNote(content: string, options: AddNoteOptions = {}): Promise<Step> {
    const op = noteOp(content, options);
    return await Step._of(this, String(op.id))._edit(op);
  }

  /** Move a step (or a note) on the canvas. Where things sit is never a version of its own. Resolves to the step. */
  async move(step: StepRef, position: Position): Promise<Step> {
    const handle = step instanceof Step ? step : Step._of(this, stepId(step));
    return await handle._edit({ op: "move", id: handle.id, position: { x: position.x, y: position.y } });
  }

  /**
   * Collect several edits with `build` and send them as one batch once it resolves: they're applied in order and
   * land as one version, or none of them do. With `ifVersion` (a version you read: `version`,
   * `(await graph()).version`, or the last edit's) the batch is refused with `Conflict` when the workflow moved on
   * since, and the error carries the workflow as it stands (`graph` and `version`). `includeGraph` has the answer
   * carry the workflow as written, read as `graph()` reads it. Resolves to the `WorkflowEdit` (`null` when `build`
   * queued nothing); a `build` that throws sends nothing.
   *
   * A batch that can't be undone from its versions alone (one that removes a step holding an app, conversations or
   * files) may be held for the account's owner when an agent, a connected app or a deployed app's code sends it: it
   * throws `ApprovalRequired`, nothing of it has landed, and NoClick applies it once they approve (its `operation`
   * settles then, with the batch's answer). The workflow one of your agents runs on is edited as its canvas edits it:
   * the agent follows its prompt, harness and model, its own step stays (removing it throws `InvalidRequest` naming
   * the agent, `details.agent_id`), and a key that couldn't change the agent can't change it this way either.
   *
   * `source: "canvas"` says the edits are a canvas's saves (`EditOptions.source`).
   */
  async edit(options: EditOptions, build: (batch: EditBatch) => unknown): Promise<WorkflowEdit | null> {
    const batch = new EditBatch(this, options);
    await build(batch);
    return await batch._send();
  }

  /**
   * Wait, up to 30 seconds, for what earlier edits set going (their triggers' registrations, removed steps'
   * teardowns), changing nothing, as an edit with `settle` waits for its own: `settled` says whether it finished in
   * time, `unregistered` (by step) why each trigger left unregistered can't be yet, and with `includeGraph` the answer
   * carries the workflow as that left it.
   *
   *     const settled = await brief.settle({ includeGraph: true });
   *     console.log(settled.graph?.step("hook").settings.webhook_url);
   */
  async settle(options: { includeGraph?: boolean } = {}): Promise<WorkflowEdit> {
    return await this._send([], { includeGraph: options.includeGraph, settle: true });
  }

  /**
   * Its versions, newest first, kept 90 days (a named one for good): the first `limit` (20 by default; `null` for
   * all), fetched page by page. `named: true` lists only the named ones, its checkpoints.
   */
  async versions(options: { limit?: number | null; named?: boolean } = {}): Promise<WorkflowVersion[]> {
    const path = `${await this.path()}/versions`;
    const limit = options.limit === undefined ? 20 : (options.limit ?? undefined);
    const query = options.named ? { named: "true" } : undefined;
    return await listAll({ path, user: null, client: this._client, limit, query }, (raw) => toWorkflowVersion(raw, this));
  }

  /** One page of its versions, newest first (`named: true`: the named ones); pass `nextCursor` back as `cursor`. */
  async versionsPage(options: PageOptions & { named?: boolean } = {}): Promise<Page<WorkflowVersion>> {
    const { named, ...page } = options;
    const path = `${await this.path()}/versions`;
    const query = named ? { named: "true" } : undefined;
    return await listPage({ ...page, path, user: null, client: this._client, query }, (raw) => toWorkflowVersion(raw, this));
  }

  /**
   * Name a version of its history, keeping it for good while it has a name: the version it's at now (a checkpoint,
   * as the app saves one; `ifVersion` refuses it with `Conflict` when the workflow moved on since you read it), or
   * the one `historyVersion` names, or another name for a named one. No later change joins a named version. Naming
   * the version it's at now when it has a name already throws `Conflict` naming it (`details.label`). Restore it
   * with `restore({ historyVersion })`. A name someone else gave is changed only by them or the workflow's owner.
   */
  async nameVersion(label: string, options: NameVersionOptions = {}): Promise<WorkflowVersion> {
    const path = `${await this.path()}/versions`;
    const raw = options.historyVersion === undefined
      ? await this._request("POST", path, { json: compact({ label, note: options.note, if_version: options.ifVersion }) })
      : await this._request("PATCH", `${path}/${options.historyVersion}`, { json: { label, note: options.note ?? null } });
    return toWorkflowVersion(raw, this);
  }

  /**
   * Take a version's name away (a checkpoint deleted): it's kept 90 days from its last write then, as any version.
   * Only who named it or the workflow's owner takes it away.
   */
  async unnameVersion(historyVersion: number): Promise<WorkflowVersion> {
    return toWorkflowVersion(await this._request("PATCH", `${await this.path()}/versions/${historyVersion}`, { json: { label: null } }), this);
  }

  /**
   * One version of its history, by its `historyVersion`, with the definition it holds (its `graph`: name,
   * description, settings and steps as they were); a version it doesn't have (kept 90 days) throws `NotFound`.
   */
  async versionAt(historyVersion: number): Promise<WorkflowVersion> {
    return toWorkflowVersion(await this._request("GET", `${await this.path()}/versions/${historyVersion}`), this);
  }

  /**
   * Change the workflow by describing the change; NoClick's builder makes it, reading the workflow
   * as it stands. `publish: true` then puts its app live (or pass `{ subdomain, title }`; `publish()`
   * and `unpublish()` publish without a change). One build at a time: another in progress throws
   * `Conflict`. A change costs AI usage, as building in the app does. `wait()` resolves to the
   * `WorkflowBuildResult`; `nextQuestion()` resolves to anything it asks first.
   */
  async build(instructions?: string, options: { publish?: boolean | JsonObject } = {}): Promise<WorkflowBuild> {
    const publish = options.publish === true ? {} : options.publish || undefined;
    const payload = await this._request("POST", `${await this.path()}/builds`, { json: compact({ instructions, publish }) });
    this.startedBuild = WorkflowBuild._from(payload, { client: this._client });
    return this.startedBuild;
  }

  /**
   * Have NoClick's drafter (the builder's own) pick `steps`' operations and fill their settings, the steps together.
   * Each step is a `Step`, its id, or `{ id, goal }`: its goal says what it's for (the drafter reads it, and a drafted
   * step keeps it). `mode` `full` (the default) picks each step's operation and fills its settings (a step drafts
   * against the operation each step it reads was given), `operation` picks only the operation, `fields` fills the
   * settings of the operation a step has, `field` fills the one setting `field` names; `instructions` say what the
   * workflow does. A step the workflow doesn't have, a note, a step that provides an agent its tools or a setting it
   * doesn't have throws `InvalidRequest` before anything runs. What's drafted lands as one version of the workflow,
   * written as an edit with your key is; the drafter never connects an account. It costs its AI usage, at cost. The
   * operation (kind `workflow.draft`) reports each step as it lands (`progress`); `wait()` resolves to the
   * `WorkflowDraftResult`, each step's verdict among it, or throws when no step could be drafted.
   */
  async draft(steps: readonly DraftStep[], options: DraftOptions = {}): Promise<Operation<WorkflowDraftResult>> {
    const entries = steps.map((step) =>
      typeof step === "object" && !(step instanceof Step)
        ? compact({ id: stepId(step.id), goal: step.goal })
        : { id: stepId(step) });
    const payload = await this._request("POST", `${await this.path()}/drafts`, {
      json: compact({ steps: entries, mode: options.mode ?? "full", field: options.field, instructions: options.instructions }),
    });
    return Operation._fromPayload<WorkflowDraftResult>(payload, { client: this._client, kind: "workflow.draft", reader: toDraftResult });
  }

  /** Put the workflow's app live as it now stands, at `subdomain` (omitted, the address it has); the result's `published` holds its `url`. */
  async publish(options: PublishOptions = {}): Promise<WorkflowBuild> {
    return await this.build(undefined, { publish: compact({ subdomain: options.subdomain, title: options.title }) });
  }

  /**
   * Take the workflow's app down, to the trash: its public URL stops answering. For 30 days its address stays its own,
   * and restoring it (or `publish()`) brings it back there with the same key; the result's `published` names the
   * `trashId` that restores it and until when (`restorableUntil`).
   */
  async unpublish(): Promise<WorkflowBuild> {
    return await this.build(undefined, { publish: { action: "unpublish" } });
  }

  /** Switch off each of its triggers that's on, with `reason` beside them: nothing starts it on its own until `resume()`. Runs from code still start. */
  async pause(reason?: string): Promise<this> {
    return this.took(await this._request<JsonObject>("POST", `${await this.path()}/pause`, { json: compact({ reason }) }));
  }

  /** Switch back on each trigger a pause switched off (never one turned off by hand). */
  async resume(): Promise<this> {
    return this.took(await this._request<JsonObject>("POST", `${await this.path()}/resume`));
  }

  /**
   * Bring the workflow back from the trash (within 30 days of `delete()`); its schedules and webhooks register
   * again. With `historyVersion`, put that version of its history back instead (`versions()` lists them): its graph,
   * name, description and settings, as a new version of its own (source `restore`), so it's undone by restoring the
   * one before it. `ifVersion` (the workflow's `version` you read) refuses it with `Conflict`, carrying the workflow
   * as it stands, when the workflow moved on since. One that takes away a step holding an app, conversations or files
   * may be held for the account's owner, as a batch is (`ApprovalRequired`). After a version's restore, `version` is
   * the new one and `lastEdit` says what it did.
   */
  async restore(options: { historyVersion?: number; ifVersion?: number } = {}): Promise<this> {
    if (options.historyVersion !== undefined) {
      const path = await this.path();
      let raw: unknown;
      try {
        raw = await this._request("POST", `${path}/versions/${options.historyVersion}/restore`, { json: compact({ if_version: options.ifVersion }) });
      } catch (err) {
        this._stale(err);
        throw err;
      }
      this._wrote(raw);
      return this;
    }
    if (options.ifVersion !== undefined) throw new TypeError("ifVersion checks a version's restore: pass historyVersion too.");
    const id = this._known("id");
    if (typeof id !== "string") {
      throw new NotFound("A workflow in the trash is restored by id.", { nextStep: "Use Workflow.fromId(...).restore()." });
    }
    return this.took(await this._request<JsonObject>("POST", `/v1/workflows/${id}/restore`));
  }

  /** Move the workflow to the trash: its schedules and webhooks stop now, and `restore()` brings it back within 30 days. */
  async delete(): Promise<void> {
    await this._request("DELETE", await this.path());
  }

  /**
   * Start a run with `inputs` (checked against the workflow's `inputs` schema; a mismatch throws
   * `InvalidRequest` naming the field). What would stop the run is refused before anything runs: a
   * step with no account connected throws `NeedsConnection`, and a workflow that can't start from
   * code or isn't set up `ActionRequired`. `wait()` resolves to the finished `WorkflowRun`, or
   * throws the run's error if it failed.
   *
   * `fromStep` runs that step and what comes after it instead (`only: true`: that step alone), the steps before it
   * giving the outputs they last stored. A step that provides an agent its tools has no run of its own
   * (`InvalidRequest`, `details.reason` `tool_provider`).
   */
  async run(inputs: JsonObject = {}, options: WorkflowRunOptions = {}): Promise<Operation<WorkflowRun>> {
    const scope = resolveScope(options.user);
    const from = options.fromStep === undefined ? undefined : stepId(options.fromStep);
    const payload = await this._api.request("POST", `${await this.path()}/runs`, {
      json: { inputs, ...compact({ from_step: from, only: options.only ? true : undefined }) },
      user: scope,
      idempotencyKey: options.idempotencyKey,
    });
    return Operation._fromPayload<WorkflowRun>(payload, { client: this._client, user: scope, kind: "workflow.run", reader: toWorkflowRun });
  }

  /**
   * A test run of the workflow, as the app's Test Run plays one: a staged event arrives at one of its triggers and
   * the agents it reaches take a real turn (their models, instructions and tools) while a simulated world answers
   * every tool call, so nothing is sent, no account is touched and its connections needn't be connected yet (its
   * agents' model connections must be). The steps after an agent that would reach an account never run.
   *
   * `testRun` plays one the workflow offers, by its name or key, as its Test Run screen lists them: a staged
   * situation for one of its triggers, or one authored for it (`edit().addTestRun`). Or stage a message you type on
   * `trigger` (a trigger `Step`, its id or its type): `body`, with `title`, `author` and `handle`. `scenario` says
   * what the simulated world is like. One the workflow doesn't offer throws `NotFound` naming the ones it does.
   * Billed as the app's Test Run is; an account has up to 10 queued or running at once (`QuotaExceeded` past that).
   * `wait()` resolves to the `WorkflowRehearsal`: the agent's `reply` and the `toolCalls` it made with what the
   * world answered.
   */
  async rehearse(options: WorkflowRehearseOptions): Promise<Operation<WorkflowRehearsal>> {
    const scope = resolveScope(options.user);
    const payload = await this._api.request("POST", `${await this.path()}/rehearsals`, {
      json: compact({
        test_run: options.testRun, trigger: options.trigger === undefined ? undefined : stepId(options.trigger),
        body: options.body, title: options.title, author: options.author, handle: options.handle,
        scenario: options.scenario,
      }),
      user: scope,
    });
    return Operation._fromPayload<WorkflowRehearsal>(payload, {
      client: this._client, user: scope, kind: "workflow.rehearse", reader: toRehearsal,
    });
  }

  /**
   * Recent runs, newest first, however they started. Outside `asUser` you read runs recorded for
   * your account; `userFilter` reads your users'. The first `limit` (20 by default).
   */
  async runs(options: ReadOptions & { status?: WorkflowRunStatus | readonly WorkflowRunStatus[]; limit?: number } = {}): Promise<WorkflowRun[]> {
    const path = `${await this.path()}/runs`;
    const { status, limit = 20, ...read } = options;
    return await listAll({ ...read, client: read.client ?? this._client, path, query: { status: csv(status) }, limit }, (raw) => toWorkflowRun(raw));
  }

  /**
   * One run, with what each step did (`steps`: status, error and output, in order); an unknown id throws `NotFound`.
   * While it runs, each step reads as it moves (`running`, then how it ended with its output); `watch` says when, with a
   * `workflow_run` change naming the run (`change` `step` when a step moved, `run` when it started or ended).
   */
  async getRun(runId: string): Promise<WorkflowRun> {
    return toWorkflowRun(await this._request("GET", `${await this.path()}/runs/${runId}`));
  }

  /**
   * Stop a run that's running, however it started, as the app's stop does: the step it's on stops at once and nothing
   * after it runs. A run from code is its operation's cancel (the operation reads `canceled`). Takes what starting one
   * takes; inside `asUser` (or with `user`) only that user's runs. Resolves to the run once it stopped (or as it stands
   * after a few seconds). A run that already ended throws `Conflict`, as does any other that waits with nothing running
   * (an approval, a delay).
   */
  async stopRun(runId: string, options: CallOptions = {}): Promise<WorkflowRun> {
    const raw = await (options.client ?? this._api).request("POST", `${await this.path()}/runs/${runId}/stop`, {
      user: options.user,
    });
    return toWorkflowRun(raw);
  }

  /**
   * How many runs `runs()` lists: in all, `byStatus` and `bySource`. Outside `asUser` you count the runs recorded for
   * your account; `userFilter` counts your users'.
   */
  async runCounts(options: ReadOptions = {}): Promise<WorkflowRunCounts> {
    const { user, userId } = await readScope(options);
    const raw = await (options.client ?? this._api).request("GET", `${await this.path()}/runs/counts`, {
      query: { user_id: userId },
      user,
    });
    return toRunCounts(raw);
  }

  /**
   * Each step's latest output, whatever run it's from, as the app's canvas shows the workflow when it opens: cut short
   * as a run's steps are unless `full`, never a secret. `steps` reads only those steps' (their ids). Inside `asUser`
   * (or with `user`) only that user's runs are read.
   */
  async latestOutputs(options: CallOptions & { steps?: readonly StepRef[]; full?: boolean } = {}): Promise<LatestOutputs> {
    const { steps, full, client, user } = options;
    const raw = await (client ?? this._api).request("GET", `${await this.path()}/outputs`, {
      query: { steps: steps?.length ? steps.map(stepId).join(",") : undefined, full: full ? "true" : undefined },
      user,
    });
    return toLatestOutputs(raw);
  }

  /**
   * Its Approval steps, newest first: those its runs wait at (`status: "pending"`), and those approved, declined or
   * expired: the first 20, or the first `limit` (at most 100). NoClick asks your account's owner to answer each;
   * your code answers one with a key naming `approvals:answer` (`approval.approve()`, `approval.decline()`).
   */
  async approvals(options: Omit<WorkflowApprovalListOptions, "client"> = {}): Promise<WorkflowApproval[]> {
    const id = this._known("id");
    const workflowId = typeof id === "string" ? id : (await this._ensure()).id;
    return await WorkflowApproval.list(String(workflowId), { ...options, client: this._client });
  }

  /**
   * The workflow's HTTP endpoint, turned on if it wasn't. `public: true` lets a publishable key
   * call it from a web page, with per-visitor rate limits; `public: false` requires a secret key
   * again; leave it out to keep what it is.
   */
  async endpoint(options: { public?: boolean } = {}): Promise<WorkflowEndpoint> {
    const raw = await this._request("PUT", `${await this.path()}/endpoint`, { json: compact({ public: options.public }) });
    return toEndpoint(raw);
  }
}
