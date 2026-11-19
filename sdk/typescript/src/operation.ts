/**
 * Operations: work that outlives a request (a human's answer, a connect link,
 * an agent turn). `await op.wait()` returns the typed outcome for its kind.
 */

import { resolveClient } from "./client.ts";
import type { NoClick, QueryValue } from "./client.ts";
import {
  NoClickError, OperationCanceled, OperationExpired, OperationFailed, OperationTimeout, _registerOperationFactory,
  errorFromPayload,
} from "./errors.ts";
import { ApiObject, asObject, csv, isoTime, listAll, listPage, num, paginate, parseTime, readScope, refId, requiredNumber, str } from "./object.ts";
import type { CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { ToolCall } from "./toolCall.ts";

export type OperationStatus =
  | "queued" | "running" | "awaiting_human"
  | "succeeded" | "failed" | "canceled" | "expired";

export const TERMINAL_STATUSES: ReadonlySet<string> = new Set(["succeeded", "failed", "canceled", "expired"]);

/**
 * Where a running turn of an agent on a CLI harness is: `delivering` (starting its sandbox and
 * handing it the message) or `working` (the harness is on it).
 */
export type TurnStep = "delivering" | "working";

/**
 * Invite-only beta. Where a number's port (`phone.port_in`) is: `submitted` (with the
 * current carrier) or `scheduled` (it moves at `portAt`).
 */
export type PortStep = "submitted" | "scheduled";

/** Where a running operation is: an agent turn's `TurnStep`, or a port's `PortStep`. */
export type OperationStep = TurnStep | PortStep;

/** Long-poll window per request; the server caps `timeout_s` near this. */
export const LONG_POLL_S = 50;

export type ResultReader = (result: unknown, op: Operation<unknown>) => unknown;
const READERS = new Map<string, ResultReader>();

/** Decode a succeeded operation of `kind` into its typed outcome. */
export function registerResult(kind: string, reader: ResultReader): void {
  READERS.set(kind, reader);
}

/** One status change the server recorded (`by` names who canceled). */
export interface OperationTransition {
  status: OperationStatus;
  at: Date | null;
  by: string | null;
}

export interface OperationFilters extends ReadOptions {
  kind?: string | readonly string[];
  /** Statuses, or `"live"` for every non-terminal one. */
  status?: OperationStatus | "live" | readonly (OperationStatus | "live")[];
  statusNot?: OperationStatus | readonly OperationStatus[];
  /** An `Agent` or agent id. */
  agent?: string | ApiObject;
  /** The requesting key: its id or its prefix (`nk_live_ab12`). */
  key?: string;
  createdAfter?: Date | string;
  createdBefore?: Date | string;
  /** Rows changed since (for polling). */
  updatedAfter?: Date | string;
}

/** Filters for a subclass whose reads are pinned to its own kinds. */
export type KindScopedFilters = Omit<OperationFilters, "kind">;

/** @internal Pin `options` to `kinds`; a caller-supplied kind is refused, never silently replaced. */
export function withKinds<O extends object>(options: O, kinds: readonly string[], method: string): O & { kind: readonly string[] } {
  if ((options as { kind?: unknown }).kind !== undefined) {
    throw new TypeError(`${method} reads only ${kinds.join(", ")} operations; filter other kinds with Operation.${method.split(".")[1]}.`);
  }
  return { ...options, kind: kinds };
}

export interface OperationSummary {
  total: number;
  byStatus: Record<OperationStatus, number>;
  raw: JsonObject;
}

async function filterQuery(filters: OperationFilters): Promise<Record<string, QueryValue>> {
  return {
    kind: csv(filters.kind),
    status: csv(filters.status),
    status_not: csv(filters.statusNot),
    agent_id: await refId(filters.agent),
    key_id: filters.key,
    created_after: isoTime(filters.createdAfter),
    created_before: isoTime(filters.createdBefore),
    updated_after: isoTime(filters.updatedAfter),
  };
}

/** One stage of what an operation's work planned (a deploy's: Queued, Building, Shipping, Live). */
export interface OperationStage {
  name: string;
  status: "done" | "current" | "pending";
  startedAt: Date | null;
  endedAt: Date | null;
}

/**
 * What an operation's work reported as it went: its `step`, its `stages`, the last 50 `lines` it printed (a build's
 * log, a call's turns, an agent's tool calls), `lineCount` (every line so far) and when it last said something.
 */
export interface OperationProgress {
  step: string | null;
  stages: OperationStage[];
  lines: string[];
  lineCount: number;
  updatedAt: Date | null;
  raw: JsonObject;
}

/** @internal An operation's `progress` as its JSON shows it. */
export function toProgress(value: unknown): OperationProgress | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  return {
    step: str(raw.step),
    stages: (Array.isArray(raw.stages) ? (raw.stages as JsonObject[]) : []).map((s) => ({
      name: str(s.name) ?? "",
      status: (str(s.status) ?? "pending") as OperationStage["status"],
      startedAt: parseTime(s.started_at),
      endedAt: parseTime(s.ended_at),
    })),
    lines: Array.isArray(raw.lines) ? raw.lines.map(String) : [],
    lineCount: num(raw.line_count) ?? 0,
    updatedAt: parseTime(raw.updated_at),
    raw,
  };
}

export interface OperationEvent {
  status: OperationStatus;
  /** Where a running operation is (`delivering` or `working` for a CLI agent's turn, `submitted` or `scheduled` for a port); null otherwise. */
  step: OperationStep | null;
  updatedAt: Date | null;
  result: unknown;
  error: NoClickError | null;
  raw: JsonObject;
}

function errorOf(raw: JsonObject): NoClickError | null {
  if (!raw.error) return null;
  const fallback = raw.status === "canceled" ? OperationCanceled : raw.status === "expired" ? OperationExpired : OperationFailed;
  const err = errorFromPayload(raw.error, { fallback });
  if (err.details.operation_id === undefined) err.details.operation_id = raw.id;
  return err;
}

/** A long-running piece of work. `T` is what `wait()` resolves to. */
export class Operation<T = unknown> extends ApiObject {
  /** @internal Set on operations a method returned: it knows the outcome's type, whatever the server names the kind. */
  _reader: ResultReader | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** Operations matching the filters, newest first (or the first `limit`). */
  static async list(options: OperationFilters & { limit?: number } = {}): Promise<Operation[]> {
    const query = await filterQuery(options);
    return await listAll({ ...options, path: "/v1/operations", query }, (raw, user) => new Operation({ raw, client: options.client, user }));
  }

  /** One page of matching operations; pass `nextCursor` back as `cursor`. */
  static async listPage(options: OperationFilters & PageOptions = {}): Promise<Page<Operation>> {
    const query = await filterQuery(options);
    return await listPage({ ...options, path: "/v1/operations", query }, (raw, user) => new Operation({ raw, client: options.client, user }));
  }

  /** How many operations match, by status. */
  static async summary(options: OperationFilters = {}): Promise<OperationSummary> {
    const { user, userId } = await readScope(options);
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/operations/summary", {
      query: { ...(await filterQuery(options)), user_id: userId },
      user,
    }));
    return { total: requiredNumber(raw, "total"), byStatus: asObject(raw.by_status) as Record<OperationStatus, number>, raw };
  }

  /** A lazy reference to an operation by id. */
  static fromId<T = unknown>(operationId: string, options: CallOptions = {}): Operation<T> {
    return new Operation<T>({ hints: { id: operationId }, client: options.client, user: options.user });
  }

  /** @internal Build from an operation view (or bare id) returned by a write. */
  static _fromPayload<T>(
    payload: unknown,
    init: { client?: NoClick; user?: ObjectInit["user"]; kind?: string; reader?: (result: unknown, op: Operation<unknown>) => T },
  ): Operation<T> {
    const op = new Operation<T>(Operation._init(payload, init));
    if (init.reader) op._reader = init.reader;
    return op;
  }

  /** @internal */
  static _init(payload: unknown, init: { client?: NoClick; user?: ObjectInit["user"]; kind?: string }): ObjectInit {
    const hints: JsonObject = init.kind ? { kind: init.kind } : {};
    if (typeof payload === "string") return { hints: { ...hints, id: payload }, client: init.client, user: init.user };
    const raw = asObject(payload);
    return { raw: Object.keys(raw).length ? raw : null, hints, client: init.client, user: init.user };
  }

  get id(): string {
    return this._field("id");
  }
  get kind(): string {
    return this._field("kind");
  }
  get status(): OperationStatus {
    return this._field("status");
  }
  /**
   * Where a running operation is: an agent turn on a CLI harness `delivering`, then `working`; a
   * number's port `submitted`, then `scheduled`. Null otherwise.
   */
  get step(): OperationStep | null {
    return (this._known("step") as OperationStep | undefined) ?? null;
  }
  /** The raw result once succeeded. */
  get result(): unknown {
    return this._field("result");
  }
  get createdAt(): Date | null {
    return parseTime(this._known("created_at"));
  }
  get updatedAt(): Date | null {
    return parseTime(this._known("updated_at"));
  }
  /** The failure as a `NoClickError` (null unless it failed). */
  get error(): NoClickError | null {
    return errorOf(this.raw);
  }
  /** Whether the operation reached a terminal status. */
  get done(): boolean {
    return TERMINAL_STATUSES.has(String(this._known("status")));
  }
  /** A short line saying what it is (a message preview, an addressee, a command). */
  get summaryText(): string | null {
    return this._field("summary");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  /** The key that started it. */
  get keyId(): string | null {
    return this._field("key_id");
  }
  get agentId(): string | null {
    return this._field("agent_id");
  }
  /** What it was started with (on a single operation's view, for account principals). */
  get input(): JsonObject | null {
    return this._field("input");
  }
  get startedAt(): Date | null {
    return parseTime(this._known("started_at"));
  }
  get finishedAt(): Date | null {
    return parseTime(this._known("finished_at"));
  }
  /** Time queued before it ran. */
  get waitMs(): number | null {
    return num(this._known("wait_ms"));
  }
  /** Time running. */
  get runMs(): number | null {
    return num(this._known("run_ms"));
  }
  /** Time waiting on a person. */
  get heldMs(): number | null {
    return num(this._known("held_ms"));
  }
  /**
   * What the work reported as it went (null before it reported anything). An agent that started it hears each
   * report as an `operation` event.
   */
  get progress(): OperationProgress | null {
    return toProgress(this._known("progress"));
  }
  /** Every status change, oldest first (empty for operations recorded before they were kept). */
  get transitions(): OperationTransition[] {
    const events = this._known("events");
    return (Array.isArray(events) ? (events as JsonObject[]) : []).map((event) => ({
      status: event.status as OperationStatus,
      at: parseTime(event.at),
      by: str(event.by),
    }));
  }
  /** This operation in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    return this._api.consoleUrl("operations", this._id());
  }

  protected _id(): string {
    return String(this._known("id"));
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", `/v1/operations/${this._id()}`);
  }

  /** @internal */
  _absorb(raw: unknown): void {
    this._raw = { ...(this._raw ?? {}), ...asObject(raw) };
  }

  /**
   * Wait until the operation finishes and return its outcome (typed per kind:
   * `Connection`, `Answer`, `boolean`, `AgentReply`, ...). Throws the
   * operation's error if it failed, `OperationCanceled` / `Expired`, or
   * `OperationTimeout` after `timeoutS` seconds.
   */
  async wait(options: { timeoutS?: number } = {}): Promise<T> {
    const deadline = options.timeoutS === undefined ? null : Date.now() + options.timeoutS * 1000;
    while (!this._raw || !this._waited()) {
      let window = this._waitWindowS;
      if (deadline !== null) {
        const remaining = (deadline - Date.now()) / 1000;
        if (remaining <= 0) {
          if (!this._raw) {
            await this._ensure();
            continue;
          }
          throw this._linked(new OperationTimeout(`Operation ${this._id()} is still ${this._raw.status} after ${options.timeoutS}s.`, {
            nextStep: "Call wait() again, or check op.status later.",
            details: { operation_id: this._id(), operation_status: this._raw.status },
          }));
        }
        window = Math.min(this._waitWindowS, Math.max(1, Math.ceil(remaining)));
      }
      this._absorb(await this._request("GET", `/v1/operations/${this._id()}/wait`, {
        query: { timeout_s: window },
        timeoutMs: (window + 15) * 1000,
      }));
    }
    return this._outcome();
  }

  /** How long one read in `wait()` lets the server hold it; it answers sooner once the operation finishes. */
  protected get _waitWindowS(): number {
    return LONG_POLL_S;
  }

  /** Whether `wait()` is done: the operation finished (a kind may stop it sooner). */
  protected _waited(): boolean {
    return TERMINAL_STATUSES.has(String(this._raw?.status));
  }

  protected _outcome(): T {
    const raw = this._raw ?? {};
    const status = String(raw.status);
    if (status === "succeeded") {
      const reader = this._reader ?? READERS.get(String(this._known("kind") ?? ""));
      return (reader ? reader(raw.result, this as Operation<unknown>) : raw.result) as T;
    }
    const err = errorOf(raw);
    if (err) throw this._linked(err);
    const cls = status === "canceled" ? OperationCanceled : status === "expired" ? OperationExpired : OperationFailed;
    throw this._linked(new cls(`Operation ${this._id()} ${status}.`, { details: { operation_id: this._id() } }));
  }

  /** Point a raised error at this operation's console page. */
  protected _linked<E extends NoClickError>(err: E): E {
    const url = this.consoleUrl;
    if (url) err.message = `${err.message} See ${url}`;
    return err;
  }

  /** Yield an event for each status or step change until the operation finishes. */
  async *events(options: { intervalMs?: number } = {}): AsyncGenerator<OperationEvent> {
    const interval = options.intervalMs ?? 1000;
    let last: string | null = null;
    for (;;) {
      const raw = asObject(await this._request("GET", `/v1/operations/${this._id()}`));
      this._absorb(raw);
      const marker = `${raw.status}|${raw.step}|${raw.updated_at}`;
      if (marker !== last) {
        last = marker;
        yield {
          status: raw.status as OperationStatus,
          step: (raw.step as OperationStep | undefined) ?? null,
          updatedAt: parseTime(raw.updated_at),
          result: raw.result,
          error: errorOf(raw),
          raw,
        };
      }
      if (TERMINAL_STATUSES.has(String(raw.status))) return;
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
  }

  /** The tool calls an `agent.message` turn made, oldest first (none for other kinds). */
  async toolCalls(): Promise<ToolCall[]> {
    const rows = await paginate(this._api, `/v1/operations/${this._id()}/tool_calls`, { user: this._callScope() ?? null });
    return rows.map((raw) => new ToolCall(raw));
  }

  [Symbol.for("nodejs.util.inspect.custom")](): string {
    const parts = ["id", "kind", "status"]
      .filter((key) => this._known(key) !== undefined)
      .map((key) => `${key}: ${JSON.stringify(this._known(key))}`);
    const url = this.consoleUrl;
    if (url) parts.push(`consoleUrl: ${JSON.stringify(url)}`);
    return `${this.constructor.name} { ${parts.join(", ")} }`;
  }

  /**
   * Ask the server to cancel; returns the updated operation. A coding agent's turn (`agent.message` on a coding
   * harness) stops in its sandbox first, its harness going on from the same session, so the next turn never runs
   * beside it.
   */
  async cancel(): Promise<this> {
    const raw = await this._request("POST", `/v1/operations/${this._id()}/cancel`);
    if (raw && typeof raw === "object") this._absorb(raw);
    return this;
  }

  /**
   * Whether `undo()` can take it back now: a reversible write (a deletion that went to the trash, a
   * dict's clear, a database migration) not undone yet. `null` for kinds that record no undo.
   */
  get undoable(): boolean | null {
    return this._field("undoable") ?? null;
  }
  /** When it was undone, if it was. */
  get undoneAt(): Date | null {
    return parseTime(this._field("undone_at"));
  }
  /**
   * On a promote that bound databases, while it can be undone: what undoing it takes back from them (each goes back
   * to the moment before the promote, losing what was written since). `null` otherwise.
   */
  get undoRewinds(): string | null {
    return this._field("undo_rewinds") ?? null;
  }

  /**
   * Take back a reversible write, once: a deletion comes out of the trash, a dict's cleared keys
   * come back, a migrated database is restored to the moment before. What reached the world (an
   * email sent, a payment) has no undo: that throws `Conflict`, as does undoing twice. Returns what
   * the undo put back, as its own API shows it.
   */
  async undo(): Promise<JsonObject> {
    const raw = asObject(await this._request("POST", `/v1/operations/${this._id()}/undo`));
    this._raw = null;
    return asObject(raw.result);
  }
}

_registerOperationFactory((id, origin, kind) =>
  Operation._fromPayload<JsonObject>(id, { client: origin?.client, user: origin?.user ?? null, kind }),
);
