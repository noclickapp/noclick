/**
 * Agents that coordinate agents: wake-ups, jobs and their updates, and the `agents` capability.
 *
 *     const planner = Agent.fromName("planner");
 *     await planner.wake("launch", { note: "Check whether the press list is ready.", afterS: 3600 });
 *     const researcher = await planner.spawn("Find three recent launches in our category.", {
 *       updates: ["blocked", new Before("gmail.send_email_message"), new Every(900)],
 *       conversation: "launch",
 *     });
 *     const reply = await researcher.job!.wait();
 *     const coordinator = await Agent.create("coordinator", { instructions: "...", tools: ["search", Agents.only("spawn", "status")] });
 *
 * Wake-ups at a time, on an operation or on a NoClick event, spawning with updates, jobs, `ask`
 * and the `agents` capability are built.
 */

import { Agent, wakeTimingWire } from "./agent.ts";
import type { AgentReply, WakeTiming } from "./agent.ts";
import { Cron } from "./cron.ts";
import type { NoClick } from "./client.ts";
import type { WireTool } from "./connection.ts";
import { ApiObject, asObject, num, paginate, parseTime, str } from "./object.ts";
import type { CallOptions, JsonObject, ObjectInit, Page, PageOptions } from "./object.ts";
import { Operation, withKinds } from "./operation.ts";
import type { KindScopedFilters, OperationSummary } from "./operation.ts";
import type { UserOption } from "./scope.ts";

// ── wake-ups ───────────────────────────────────────────────────────────────

/**
 * Who set a wake-up: `code` (`agent.wake`), `wake_me` (the agent's own tool), or NoClick: `update` (a
 * job's update for this agent as its parent), `answer` (the link it asked its user to connect an
 * account with is done: connected or expired), `approval` (a held call was approved or declined),
 * `notice` (news for the account's own assistant, such as a friend's invite reward) and `continue` (a turn its
 * step limit ended, carried on by itself: `turnLimits`).
 */
export type WakeupSource = "code" | "wake_me" | "update" | "answer" | "approval" | "notice" | "continue";

/** `pending` until its moment, then `delivered` (its turn started), `canceled` or `failed`. */
export type WakeupStatus = "pending" | "delivered" | "canceled" | "failed";

/**
 * One time an agent will be (or was) woken in a conversation. At its moment the conversation takes
 * a turn whose message is the `note`, followed by what woke it: the time, the operation's outcome, a
 * job's update, or a NoClick event. A running turn in that conversation goes
 * first (one turn per conversation), and the wake-up waits behind it. Durable, delivered once, and
 * billed and capped like any turn; a turn the account can't pay for fails it (`status: "failed"`,
 * `error`).
 */
export class Wakeup extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _from(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): Wakeup {
    return new Wakeup({ raw, client: init.client, user: init.user });
  }

  get id(): string {
    return this._field("id");
  }
  get agentId(): string {
    return this._field("agent_id");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  /** The conversation it wakes. */
  get conversation(): string {
    return this._field("conversation");
  }
  /** What the turn is told. */
  get note(): string {
    return this._field("note");
  }
  /** When it's due (a time wake-up), or when it became due. */
  get at(): Date | null {
    return parseTime(this._field("at"));
  }
  /** What it waits on: `{ operation_id }` or `{ event, filters }` (null for a time wake-up). */
  get when(): JsonObject | null {
    return this._field("when");
  }
  /** Its schedule, for a recurring wake-up (null for one that comes once); `at` is its next time. */
  get every(): Cron | null {
    const every = this._field<JsonObject | null>("every");
    return every ? new Cron(String(every.cron), { tz: String(every.tz) }) : null;
  }
  /** How many turns it has started (a recurring one counts up). */
  get fired(): number {
    return num(this._field("fired")) ?? 0;
  }
  get source(): WakeupSource {
    return this._field("source");
  }
  get status(): WakeupStatus {
    return this._field("status");
  }
  /**
   * What woke it: `{ at }` for a time (once delivered), `{ operation_id, kind, status, result | error }`
   * once its operation settled, `{ update }` for a job's update, and `{ event }` (the event as
   * `Event.list` reads it) for an event; null until then.
   */
  get wokenBy(): JsonObject | null {
    return this._field("woken_by");
  }
  /** The turn it started (an `agent.message` operation), once delivered. */
  get operationId(): string | null {
    return this._field("operation_id");
  }
  /** How many `wake_me` wake-ups in a row led to it (0 for anything else). */
  get depth(): number {
    return num(this._field("depth")) ?? 0;
  }
  /** Why it failed: `{ type, message }`. */
  get error(): JsonObject | null {
    return this._field("error");
  }
  /**
   * A recurring one's last missed time: `{ at, reason }`, `reason` being `credits`, `spend_cap` (the account's
   * monthly cap) or `budget` (the agent's, its key's or its user's); null if it never missed.
   */
  get missed(): JsonObject | null {
    return this._field("missed");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  get deliveredAt(): Date | null {
    return parseTime(this._field("delivered_at"));
  }
  /** The turn it started, as an operation to wait on (null until delivered). */
  get operation(): Operation<AgentReply> | null {
    const id = this.operationId;
    return id ? Operation.fromId<AgentReply>(id, { client: this._client, user: this._callScope() }) : null;
  }

  private get path(): string {
    return `/v1/agents/${this._known("agent_id")}/wakeups/${this._known("id")}`;
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", this.path);
  }

  /** Cancel it while it's pending (`Conflict` once it was delivered, canceled or failed). */
  async cancel(): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `${this.path}/cancel`);
    return this;
  }

  /**
   * Change it while it's pending: its `note`, and its time with one of `at`, `afterS` and `every` (a one-off time
   * makes a recurring one come once more). A delivery under way of what it said before starts no turn. One waiting
   * on an operation or an event keeps that; `Conflict` once it was delivered, canceled or failed.
   */
  async update(options: { note?: string } & Pick<WakeTiming, "at" | "afterS" | "every">): Promise<this> {
    const timing = await wakeTimingWire({ at: options.at, afterS: options.afterS, every: options.every }, false);
    if (options.note === undefined && Object.keys(timing).length === 0) {
      throw new TypeError("Nothing to change: pass note, or a new time with at, afterS or every");
    }
    const json = options.note === undefined ? timing : { note: options.note, ...timing };
    this._raw = await this._request<JsonObject>("PATCH", this.path, { json });
    return this;
  }
}

// ── jobs and their updates ─────────────────────────────────────────────────

/** What a job's update is: its end (`done`), a wait on a person (`blocked`), a call it's about to make (`before`), a timed one (`every`), or its own `tell_parent` (`message`). */
export type JobUpdateKind = "done" | "blocked" | "before" | "every" | "message";

/**
 * One update a job sent its parent. `text` is what the child wrote: its last reply (`done`), what it
 * wrote with the call, its reason (`before`; null on a coding harness, whose words NoClick sees only
 * when its turn ends), what it wrote when asked (`every`), its message (`message`), or NoClick's line
 * saying what it waits on (`blocked`). `tool` and `arguments` are the call a `before` update
 * announces; `result` and `error` end a `done` one; `waitingOn` says what a `blocked` one waits on
 * (`{ kind: "connection" | "approval" | "person" | "sign_in", url, operation_id }`: a connect link it
 * asked its user to open, with its `url`; a held call, never with one, so no agent approves its child's
 * call; a question it asked someone; or a step its browser needs a person for); `wakeupId` is the parent's
 * wake-up it set (null when nothing
 * was to be woken).
 */
export interface JobUpdate {
  id: string;
  jobId: string;
  agentId: string | null;
  kind: JobUpdateKind;
  text: string | null;
  tool: string | null;
  arguments: JsonObject | null;
  /** The job's status then. */
  status: string | null;
  result: unknown;
  error: JsonObject | null;
  waitingOn: JsonObject | null;
  wakeupId: string | null;
  createdAt: Date | null;
  raw: JsonObject;
}

function toJobUpdate(raw: JsonObject): JobUpdate {
  return {
    id: String(raw.id),
    jobId: String(raw.job_id),
    agentId: str(raw.agent_id),
    kind: raw.kind as JobUpdateKind,
    text: str(raw.text),
    tool: str(raw.tool),
    arguments: raw.arguments ? asObject(raw.arguments) : null,
    status: str(raw.status),
    result: raw.result ?? null,
    error: raw.error ? asObject(raw.error) : null,
    waitingOn: raw.waiting_on ? asObject(raw.waiting_on) : null,
    wakeupId: str(raw.wakeup_id),
    createdAt: parseTime(raw.created_at),
    raw,
  };
}

/**
 * Work one agent started on another: a spawned task (kind `agent.task`), or a message a coordinator
 * sent through its `agents` tools (kind `agent.message`, whose only update is `done`). `wait()`
 * resolves to an `AgentReply` either way. A task runs while the child works on it, across as many turns as it
 * takes, and finishes when its conversation goes quiet with nothing left to continue it: `running`
 * (`step` `working` while a turn runs, `waiting` while only a wake-up is pending), `awaiting_human`
 * (step `blocked`) while it waits on a person (a held call, a connection it asked its user for), then
 * `succeeded` (its result is the child's last reply), `failed` (a turn failed), `canceled`
 * (`cancel()`: its running turn stops and its pending wake-ups are canceled) or `expired` (the
 * child's `ttlS` ran out first).
 */
// `Job.list` reads tasks: a message job is an `agent.message`, which only `agent.jobs()` tells apart.
const JOB_KINDS = ["agent.task"] as const;

export class Job extends Operation<AgentReply> {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal Build from a job view (or a bare operation id). */
  static _from(payload: unknown, init: { client?: NoClick; user?: UserOption }): Job {
    return new Job(Operation._init(payload, init));
  }

  /** A lazy reference to a job by operation id: pick it up anywhere (`Operation.fromId` gives a plain operation). */
  static jobFromId(operationId: string, options: CallOptions = {}): Job {
    return Job._from(operationId, { client: options.client, user: options.user });
  }

  /** Spawned tasks (kind `agent.task`), newest first; takes `Operation.list`'s filters except `kind`. `agent.jobs()` reads an agent's message jobs too. */
  static override async list(options: KindScopedFilters & { limit?: number } = {}): Promise<Job[]> {
    const ops = await Operation.list(withKinds(options, JOB_KINDS, "Job.list"));
    return ops.map((op) => Job._from(op.raw, { client: options.client, user: op._scope }));
  }

  /** One page of jobs; pass `nextCursor` back as `cursor`. */
  static override async listPage(options: KindScopedFilters & PageOptions = {}): Promise<Page<Job>> {
    const page = await Operation.listPage(withKinds(options, JOB_KINDS, "Job.listPage"));
    return { data: page.data.map((op) => Job._from(op.raw, { client: options.client, user: op._scope })), nextCursor: page.nextCursor };
  }

  /** How many jobs match, by status; takes `Operation.summary`'s filters except `kind`. */
  static override async summary(options: KindScopedFilters = {}): Promise<OperationSummary> {
    return await Operation.summary(withKinds(options, JOB_KINDS, "Job.summary"));
  }

  /** The agent whose job it is: a task's parent, whether your code spawned it or the parent did. */
  get startedBy(): string | null {
    return str(this._known("started_by"));
  }
  /** The working agent's conversation it runs in. */
  get conversation(): string | null {
    return str(this._known("conversation"));
  }
  /** The parent's conversation its updates wake (null: they wake nobody and wait here). */
  get parentConversation(): string | null {
    return str(this._known("parent_conversation"));
  }
  /** The updates its parent required, as on the wire: `"done"`, `"blocked"`, `{ before }`, `{ every_s }`. */
  get requiredUpdates(): (string | JsonObject)[] {
    const updates = this._known("updates");
    return Array.isArray(updates) ? (updates as (string | JsonObject)[]) : [];
  }
  /** Its newest update, or null. */
  get latestUpdate(): JobUpdate | null {
    const update = this._known("latest_update");
    return update && typeof update === "object" ? toJobUpdate(update as JsonObject) : null;
  }
  /** The agent doing the work (a lazy reference), or null. */
  get agent(): Agent | null {
    const id = str(this._known("agent_id"));
    return id ? Agent.fromId(id, { client: this._client, user: this._callScope() }) : null;
  }

  /** Every update it sent its parent, oldest first. */
  async updates(): Promise<JobUpdate[]> {
    const rows = await paginate(this._api, `/v1/operations/${this._id()}/updates`, { user: this._callScope() ?? null });
    return rows.map(toJobUpdate);
  }
}

// ── what a parent requires to hear ─────────────────────────────────────────

/**
 * An update before a matching tool call runs: the call and what the child wrote with it, its reason.
 * Patterns are written as policy writes them (`"gmail.send_email_message"`, `"stripe.*"`, `"code"`).
 * The call runs right after (a call that must wait for someone is a policy `requireApproval` rule),
 * and a coding harness's own shell commands and file edits aren't tool calls NoClick sees, so it
 * can't match them (its words arrive only when its turn ends, so its update carries no reason).
 */
export class Before {
  readonly tools: string[];

  constructor(...tools: string[]) {
    if (!tools.length) throw new TypeError('Before takes at least one tool pattern: new Before("gmail.send_email_message")');
    for (const tool of tools) {
      if (typeof tool !== "string" || !tool) throw new TypeError(`A Before pattern is a tool name like "stripe.*", not ${JSON.stringify(tool)}`);
    }
    this.tools = [...tools];
  }

  /** @internal */
  toWire(): JsonObject {
    return { before: [...this.tools] };
  }
}

/**
 * An update at least every `intervalS` seconds (60 or more) while the job works: NoClick asks the
 * child for one once that long has passed since its last (on a coding harness by steering its
 * running turn, on `sdk` before its next model call), and the `tell_parent` it answers with is the
 * `every` update. A child that's only waiting isn't asked.
 */
export class Every {
  readonly intervalS: number;

  constructor(intervalS: number) {
    if (!Number.isInteger(intervalS) || intervalS < 60) {
      throw new RangeError(`Every takes a whole number of seconds, 60 or more, not ${intervalS}`);
    }
    this.intervalS = intervalS;
  }

  /** @internal */
  toWire(): JsonObject {
    return { every_s: this.intervalS };
  }
}

/**
 * When NoClick makes a spawned child report: `"done"` (always on),
 * `"blocked"` (it starts waiting on a person), `new Before(...tools)` or `new Every(intervalS)`. What
 * an update says, and when to reach out freely, belong in the child's instructions or task.
 */
export type UpdateSpec = "done" | "blocked" | Before | Every;

/** @internal `updates` on the wire: `"done"` first, then each as given. */
export function updatesWire(updates: readonly UpdateSpec[] | undefined): WireTool[] {
  const wire: WireTool[] = ["done"];
  for (const update of updates ?? []) {
    if (update === "done") continue;
    if (update === "blocked") wire.push("blocked");
    else if (update instanceof Before || update instanceof Every) wire.push(update.toWire());
    else throw new TypeError(`An update is "done", "blocked", a Before or an Every, not ${JSON.stringify(update)}`);
  }
  return wire;
}

// ── the agents capability ──────────────────────────────────────────────────

/** The tools of the `agents` capability. */
export type AgentsTool = "spawn" | "message" | "ask" | "status" | "list" | "cancel";

/**
 * The `agents` capability for an agent's `tools`: `new Agents()` (the same as `"agents"`) gives it
 * `spawn`, `message`, `ask`, `status`, `list` and `cancel` within its own scope, in its own
 * conversations (in a channel, agents work by mentions), and `Agents.only(...)` some of them.
 * `spawn` makes its own children (their updates wake it in the conversation it spawned from);
 * `message` reaches the agents it can reach (a user's agent that user's and the account's, an
 * account agent the account's), waiting up to 50 seconds for the reply, and a reply that takes
 * longer, or one it doesn't wait for, is a job whose `done` update wakes it; `ask` asks one without
 * stopping it; `status` reads an agent or a job; `list` takes `Agent.list`'s filters; `cancel` stops
 * a job it started. Its children get the capability only when it lists it for them. Policy names
 * them `agents.spawn` ... `agents.cancel`; the model sees `agents__spawn`, ...
 */
export class Agents {
  static readonly TOOLS: readonly AgentsTool[] = ["spawn", "message", "ask", "status", "list", "cancel"];
  readonly tools: AgentsTool[];

  constructor() {
    this.tools = [...Agents.TOOLS];
  }

  /** Some of the capability's tools: `Agents.only("spawn", "status")`. */
  static only(...tools: AgentsTool[]): Agents {
    if (!tools.length) throw new TypeError(`only() takes at least one of ${Agents.TOOLS.join(", ")}`);
    const unknown = tools.find((t) => !Agents.TOOLS.includes(t));
    if (unknown) throw new TypeError(`The agents tools are ${Agents.TOOLS.join(", ")}, not ${JSON.stringify(unknown)}`);
    const narrowed = new Agents();
    (narrowed as { tools: AgentsTool[] }).tools = [...new Set(tools)];
    return narrowed;
  }

  /** @internal `"agents"` when whole, else one `"agents.<tool>"` per tool. */
  async _toolRefs(): Promise<WireTool[]> {
    if (Agents.TOOLS.every((t) => this.tools.includes(t))) return ["agents"];
    return this.tools.map((t) => `agents.${t}`);
  }
}

// ── NoClick itself ─────────────────────────────────────────────────────────

/** NoClick's capability groups, as a connected app's grant names them. */
export type PlatformGroup = "read" | "build" | "deploy" | "spend" | "delete";

/**
 * NoClick itself for an agent's `tools`: `new Platform()` (the same as `"noclick"`) gives it what a
 * connected app gets on NoClick's MCP server, `search` and `fetch` (NoClick's guides and your account's
 * objects), `api_describe` and `api_call` (any API operation), and `quote`, `buy` and `delete`, acting as
 * the turn's key and the user it acts for, never more than that key may. The same gate judges them as any
 * connected app: a purchase or a deletion waits for the account's owner, who approves it on NoClick with its
 * exact price or what goes with it (the turn waits on them, and the call's outcome is the conversation's
 * next turn); a secret's value never comes from the conversation; and a turn answering someone outside the
 * agent's scope asks a person before acting outside the account. A long action it starts is an operation,
 * which `wake_me` waits on, and watchers see `approval` and `operation` events. `Platform.only(...)`
 * narrows it by capability group (without `spend` it has no `quote` or `buy`, without `delete` no
 * `delete`) and by API area (a key's scopes: `"domains"`, `"phone"`, `"agents"`...), each narrowing only
 * its own kind. Policy names its tools `noclick.search` ... `noclick.delete`.
 */
export class Platform {
  static readonly GROUPS: readonly PlatformGroup[] = ["read", "build", "deploy", "spend", "delete"];
  /** What it's narrowed to: capability groups and API areas (empty: all of NoClick). */
  readonly names: string[] = [];

  /** Part of NoClick: `Platform.only("domains")`, `Platform.only("read")`. Names are checked when the agent is saved. */
  static only(...names: (PlatformGroup | (string & {}))[]): Platform {
    if (!names.length || names.some((n) => typeof n !== "string" || !n)) {
      throw new TypeError(`only() takes capability groups (${Platform.GROUPS.join(", ")}) or API areas, like "domains"`);
    }
    const narrowed = new Platform();
    (narrowed as { names: string[] }).names = [...new Set(names)];
    return narrowed;
  }

  /** @internal `"noclick"` when whole, else one `"noclick.<name>"` per name. */
  async _toolRefs(): Promise<WireTool[]> {
    return this.names.length ? this.names.map((n) => `noclick.${n}`) : ["noclick"];
  }
}
