/**
 * Queues: durable background work, delivered at least once.
 *
 *     const jobs = Queue.fromName("invoices", { createIfMissing: true });
 *     await jobs.put({ invoice: "INV-1042" });
 *     for await (const msg of jobs.iterate({ leaseS: 60 })) {
 *       console.log("Sending", msg.body);
 *       await msg.ack();
 *     }
 *
 * A message you take is leased to you for `leaseS` seconds: `ack()` it when the work is done, or
 * it comes back for another try. One that fails `maxAttempts` times becomes a dead letter. An
 * agent can take the messages instead: `triggers: [new OnQueue(jobs)]` makes each one a turn.
 */

import { CONSOLE_BASE_URL, DEFAULT_BASE_URL } from "./client.ts";
import { TrashItem, trashed } from "./trash.ts";
import type { NoClick } from "./client.ts";
import type { UsedBy } from "./database.ts";
import { Conflict, InvalidRequest, NotFound } from "./errors.ts";
import { toExportBundle } from "./export.ts";
import type { ExportBundle } from "./export.ts";
import { ApiObject, asList, asObject, compact, createNamed, listAll, listPage, num, paginate, parseTime, str } from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import type { PlacementOptions, RegionName } from "./region.ts";
import { Operation, registerResult } from "./operation.ts";
import { resolveScope } from "./scope.ts";

/** Attempts before a message is dead-lettered, unless the queue says otherwise. */
const DEFAULT_MAX_ATTEMPTS = 5;
/** Long-poll window per request while iterating (`wait_s`). */
const ITERATE_WAIT_S = 25;

export type QueueMessageStatus = "waiting" | "delayed" | "in_flight" | "dead";

/** How full a queue was at one moment. */
export interface QueueDepth {
  at: Date | null;
  depth: number;
  inFlight: number;
}

export interface QueueCreateOptions extends CallOptions, PlacementOptions {
  /** Deliveries a message gets before it's a dead letter (1 to 100; 5 by default). */
  maxAttempts?: number;
}

/**
 * One message on a queue. A message you took with `get` or `iterate` is leased to you until
 * `leaseExpiresAt`: `ack()` when done, `nack()` to hand it back now as a failed try, `release()` to
 * hand it back without spending one. A dead letter (from
 * `deadLetters()`) says why its last attempt failed in `lastError`; `retry()` puts it back and
 * `discard()` deletes it.
 */
export class QueueMessage extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _fromView(raw: JsonObject, queueId: string, client: NoClick | undefined, user: ObjectInit["user"]): QueueMessage {
    return new QueueMessage({ raw, hints: { queue_id: queueId }, client, user });
  }

  get id(): string {
    return this._field("id");
  }
  get queueId(): string {
    return this._field("queue_id");
  }
  /** The message as you put it: JSON. */
  get body(): unknown {
    return this._field("body");
  }
  get status(): QueueMessageStatus {
    return this._field("status");
  }
  /** How many times it has been delivered, this delivery included. */
  get attempts(): number {
    return num(this._field("attempts")) ?? 0;
  }
  get enqueuedAt(): Date | null {
    return parseTime(this._field("enqueued_at"));
  }
  /** When a delayed message can first be taken (null once it can). */
  get visibleAt(): Date | null {
    return parseTime(this._field("visible_at"));
  }
  /** When your lease ends and the message goes back (null unless you hold it). */
  get leaseExpiresAt(): Date | null {
    return parseTime(this._field("lease_expires_at"));
  }
  /** Why its last attempt failed (null if none has). */
  get lastError(): string | null {
    return str(this._field("last_error"));
  }
  /** When it became a dead letter (null unless it is one). */
  get deadLetteredAt(): Date | null {
    return parseTime(this._field("dead_lettered_at"));
  }

  private path(suffix = ""): string {
    return `/v1/queues/${String(this._known("queue_id"))}/messages/${encodeURIComponent(this.id)}${suffix}`;
  }

  private deadPath(suffix = ""): string {
    return `/v1/queues/${String(this._known("queue_id"))}/dead_letters/${encodeURIComponent(this.id)}${suffix}`;
  }

  protected async _load(): Promise<JsonObject> {
    const raw = asObject(await this._request("GET", this.path()));
    const leaseId = this._known("lease_id"); // a re-read keeps the lease you hold
    return typeof leaseId === "string" && !raw.lease_id ? { ...raw, lease_id: leaseId } : raw;
  }

  private lease(): string {
    const leaseId = this._known("lease_id");
    if (typeof leaseId !== "string" || !leaseId) {
      throw new InvalidRequest("This message isn't leased to you, so there's nothing to ack, nack or release.", {
        nextStep: "Take messages with queue.get() or queue.iterate(); peek() and deadLetters() only read them.",
      });
    }
    return leaseId;
  }

  /** Mark it done: deleted, never delivered again. A late ack (the lease ran out) throws `Conflict`. */
  async ack(): Promise<void> {
    await this._request("POST", this.path("/ack"), { json: { lease_id: this.lease() } });
  }

  /**
   * Hand it back for another try after `delayS` seconds; it counts as an attempt. `error` (up to
   * 2 KB) says why: it's the message's `lastError`, which a dead letter keeps.
   */
  async nack(options: { delayS?: number; error?: string } = {}): Promise<void> {
    const json = { lease_id: this.lease(), ...compact({ delay_s: options.delayS || undefined, error: options.error }) };
    await this._request("POST", this.path("/nack"), { json });
  }

  /**
   * Hand it back untouched after `delayS` seconds without spending an attempt (`attempts` goes back,
   * `lastError` stays): for a failure that isn't the message's, like an account out of money, so a
   * backlog doesn't burn its tries. It keeps coming back until the cause is fixed.
   */
  async release(options: { delayS?: number } = {}): Promise<void> {
    const json = { lease_id: this.lease(), ...compact({ delay_s: options.delayS || undefined }) };
    await this._request("POST", this.path("/release"), { json });
  }

  /** Put a dead letter back on the queue, with its attempts reset. */
  async retry(): Promise<void> {
    await this._request("POST", this.deadPath("/retry"));
  }

  /** Delete a dead letter for good. */
  async discard(): Promise<void> {
    await this._request("DELETE", this.deadPath());
  }
}

registerResult("queue.export", toExportBundle);

/**
 * A durable queue of JSON messages, delivered at least once. `put` adds work; `get` and
 * `iterate` take it under a lease. `Queue.fromName("invoices", { createIfMissing: true })` is
 * lazy. There's no `Queue.get(id)`, since `get` takes a message: `Queue.fromId(id).hydrate()`.
 */
export class Queue extends ApiObject {
  private _createWith: JsonObject | null = null;
  private _converge: number | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create a queue, unique by name per user (a taken name throws `Conflict` with `existingId`, or with
   * `allowExisting: true` returns the queue already there, as it is). `region` keeps its messages there
   * for good: `us-east` only for now (another, or a default elsewhere, throws `InvalidRequest`).
   */
  static async create(name: string, options: QueueCreateOptions & AllowExisting = {}): Promise<Queue> {
    const scope = resolveScope(options.user);
    const json = compact({ name, max_attempts: options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS, region: options.region });
    const raw = await createNamed("/v1/queues", json, { allowExisting: options.allowExisting, user: scope, client: options.client });
    return new Queue({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the queue called `name`. A `maxAttempts` you pass is set on it every run. With
   * `createIfMissing` it's created on first use; without it, a missing queue throws `NotFound`.
   */
  static fromName(name: string, options: QueueCreateOptions & { createIfMissing?: boolean } = {}): Queue {
    const queue = new Queue({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing) {
      queue._createWith = compact({ name, max_attempts: options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS, region: options.region });
    }
    queue._converge = options.maxAttempts ?? null;
    return queue;
  }

  /** A lazy reference by id; `await Queue.fromId(id).hydrate()` loads it now. */
  static fromId(queueId: string, options: CallOptions = {}): Queue {
    return new Queue({ hints: { id: queueId }, client: options.client, user: options.user });
  }

  /** The current user's queues (or those `userFilter` covers), newest first. */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<Queue[]> {
    return await listAll({ ...options, path: "/v1/queues" }, (raw, user) => new Queue({ raw, client: options.client, user }));
  }

  /** One page of queues; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Queue>> {
    return await listPage({ ...options, path: "/v1/queues" }, (raw, user) => new Queue({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** Messages waiting to be taken, delayed ones included (as of the last load; `size()` reads it fresh). */
  get depth(): number {
    return num(this._field("depth")) ?? 0;
  }
  /** Messages leased and not yet acked. */
  get inFlight(): number {
    return num(this._field("in_flight")) ?? 0;
  }
  /** Messages that failed `maxAttempts` times. */
  get deadLetterCount(): number {
    return num(this._field("dead_letter_count")) ?? 0;
  }
  get maxAttempts(): number {
    return num(this._field("max_attempts")) ?? DEFAULT_MAX_ATTEMPTS;
  }
  /** Who consumes it: agents with an `OnQueue` trigger (`kind` `agent`) and apps that bind it. */
  get usedBy(): UsedBy[] {
    const rows = this._field<unknown>("used_by");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((u) => ({
      kind: str(u.kind) ?? "project", id: str(u.id) ?? "", name: str(u.name) ?? "", binding: str(u.binding),
    }));
  }
  /** The region it keeps its data in, fixed when it was created. */
  get region(): RegionName | null {
    return this._field("region");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** This queue in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    if (this._api.baseUrl !== DEFAULT_BASE_URL) return null;
    return `${CONSOLE_BASE_URL}/resources/queues?queue=${encodeURIComponent(String(this._known("id")))}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/queues/${id}`);
    const name = String(this._hints.name);
    const found = await this._inApp("queue", name, this._createWith);
    if (found) return found;
    const row = (asList(await this._request("GET", "/v1/queues", { query: { name } })) as JsonObject[]).find((r) => r.name === name);
    if (row) {
      if (this._converge === null || row.max_attempts === this._converge) return row;
      return await this._request<JsonObject>("PATCH", `/v1/queues/${String(row.id)}`, { json: { max_attempts: this._converge } });
    }
    if (!this._createWith) {
      throw new NotFound(`No queue is named "${name}".`, {
        nextStep: "Create it with Queue.create(...) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/queues", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this._request<JsonObject>("GET", `/v1/queues/${err.existingId}`);
    }
  }

  /** This queue's route; a reference by name is looked up (or created) first. */
  private async route(suffix = ""): Promise<string> {
    if (!this._known("id")) await this._ensure();
    return `/v1/queues/${String(this._known("id"))}${suffix}`;
  }

  private message(raw: unknown): QueueMessage {
    return QueueMessage._fromView(asObject(raw), String(this._known("id")), this._client, this._callScope());
  }

  /** Change how many deliveries a message gets before it's a dead letter (1 to 100). */
  async update(options: { maxAttempts: number }): Promise<this> {
    this._raw = await this._request<JsonObject>("PATCH", await this.route(), { json: { max_attempts: options.maxAttempts } });
    return this;
  }

  /**
   * Add a message (any JSON, up to 256 KB), hidden for `delayS` seconds (up to 7 days). Its id.
   * `dedupeKey` (up to 128 characters) makes the put safe to repeat: for 24 hours another put with
   * the same key adds nothing and returns the first message's id.
   */
  async put(body: unknown, options: { delayS?: number; dedupeKey?: string } = {}): Promise<string> {
    const [id] = await this.send([body], options.delayS, options.dedupeKey);
    return id;
  }

  /** Add up to 100 messages in one call, all or none. Their ids, in order. */
  async putMany(bodies: readonly unknown[], options: { delayS?: number } = {}): Promise<string[]> {
    return await this.send(bodies, options.delayS);
  }

  private async send(bodies: readonly unknown[], delayS?: number, dedupeKey?: string): Promise<string[]> {
    const messages = bodies.map((body) => ({ body, ...compact({ delay_s: delayS || undefined, dedupe_key: dedupeKey }) }));
    const response = await this._request("POST", await this.route("/messages"), { json: { messages } });
    return asList(response).map((row) => String(asObject(row).id));
  }

  private async take(waitS: number, leaseS: number): Promise<QueueMessage[]> {
    const response = await this._request("GET", await this.route("/messages"), {
      query: { wait_s: waitS || undefined, lease_s: leaseS, limit: 1 },
      timeoutMs: waitS ? (waitS + 15) * 1000 : undefined,
    });
    return asList(response).map((row) => this.message(row));
  }

  /**
   * Take the next message, waiting up to `timeoutS` seconds (at most 60; 0 by default) for one.
   * It's leased for `leaseS` seconds (60 by default, up to 12 hours). Null if none arrived.
   */
  async get(options: { timeoutS?: number; leaseS?: number } = {}): Promise<QueueMessage | null> {
    const [message] = await this.take(options.timeoutS ?? 0, options.leaseS ?? 60);
    return message ?? null;
  }

  /**
   * Take messages as they arrive, each leased for `leaseS`; long-polls until you `break` or `signal`
   * aborts. With `stopWhenEmpty` it ends instead the first time nothing is waiting (messages leased
   * to someone else, or delayed, don't keep it going), to drain a queue in a batch job.
   */
  async *iterate(options: { leaseS?: number; signal?: AbortSignal; stopWhenEmpty?: boolean } = {}): AsyncGenerator<QueueMessage> {
    while (!options.signal?.aborted) {
      const started = Date.now();
      const batch = await this.take(options.stopWhenEmpty ? 0 : ITERATE_WAIT_S, options.leaseS ?? 60);
      for (const message of batch) yield message;
      if (!batch.length && options.stopWhenEmpty) return;
      if (!batch.length) await this._api._sleep(Math.max(0, 1000 - (Date.now() - started))); // never spin on a short poll
    }
  }

  /** How many messages wait (delayed included; leased and dead letters not), read now. */
  async size(): Promise<number> {
    this._raw = await this._request<JsonObject>("GET", await this.route());
    return this.depth;
  }

  /** The oldest messages, waiting and in flight, without taking them (nothing is leased). */
  async peek(options: { limit?: number } = {}): Promise<QueueMessage[]> {
    const response = await this._request("GET", await this.route("/messages"), { query: { view: "peek", limit: options.limit ?? 10 } });
    return asList(response).map((row) => this.message(row));
  }

  /** The messages that failed `maxAttempts` times, newest first; kept 14 days. */
  async deadLetters(options: { limit?: number } = {}): Promise<QueueMessage[]> {
    const rows = await paginate(this._api, await this.route("/dead_letters"), { user: this._callScope() ?? null, limit: options.limit });
    return rows.map((row) => this.message(row));
  }

  /** How deep the queue has been over the last `hours` (24 by default, up to 168), a point every 15 minutes. */
  async depthHistory(options: { hours?: number } = {}): Promise<QueueDepth[]> {
    const response = await this._request("GET", await this.route("/depth"), { query: { hours: options.hours ?? 24 } });
    return asList(response).map(asObject).map((p) => ({ at: parseTime(p.at), depth: num(p.depth) ?? 0, inFlight: num(p.in_flight) ?? 0 }));
  }

  /** Drop every waiting message and every dead letter; messages in flight finish as usual. */
  async clear(): Promise<void> {
    await this._request("POST", await this.route("/clear"));
  }

  /**
   * Export every message as it stands at one moment, dead letters included, as JSON Lines: one per
   * line, oldest first, with its `status` (`waiting`, `delayed`, `in_flight` or `dead`), `attempts`
   * and `body`. `wait()` resolves to an `ExportBundle`: a zip at `url` holding the file.
   */
  async export(): Promise<Operation<ExportBundle>> {
    const payload = await this._request("POST", await this.route("/export"));
    return Operation._fromPayload<ExportBundle>(payload, { client: this._client, user: this._callScope(), kind: "queue.export", reader: toExportBundle });
  }

  /**
   * Delete the queue and its messages: it goes to the trash, restorable for 30 days. One an app binds
   * or an `OnQueue` trigger reads throws `Conflict`. Returns its `TrashItem`.
   */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this.route()), this);
  }
}
