/**
 * Webhooks and events: everything that happens, delivered to your server, signed.
 *
 *     const hook = Webhook.fromName("https://api.yourco.test/noclick/events", {
 *       createIfMissing: true, events: ["operation.*", "human.answered"],
 *     });
 *     const secret = await hook.revealSecret(); // needs the webhooks:reveal scope
 *
 *     // in your receiver
 *     const event = await Webhook.verify(await request.text(), request.headers, process.env.NOCLICK_WEBHOOK_SECRET!);
 *
 * Every event is also kept for 30 days: `Event.list({ type: "domain.*" })`.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { Conflict, NotFound, WebhookSignatureError } from "./errors.ts";
import {
  ApiObject, asList, asObject, compact, createNamed, csv, defined, givesFields, isoTime, listAll, listPage, num, paginate, parseTime,
  str,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { resolveScope } from "./scope.ts";

/** The header every delivery carries: `t=<unix seconds>,v1=<hex HMAC-SHA256 of "t.body">`. */
export const WEBHOOK_SIGNATURE_HEADER = "NoClick-Signature";

export type WebhookStatus = "healthy" | "failing" | "disabled";
export type WebhookDeliveryStatus = "pending" | "retrying" | "succeeded" | "failed";

/**
 * One kind of event: its `name` (`operation.succeeded`), what it means, and its `area` (the part
 * before the first dot). `emitted` is whether NoClick sends it today: the rest are listed so your
 * code can subscribe before the primitive behind them ships.
 */
export interface EventType {
  name: string;
  description: string;
  area: string;
  emitted: boolean;
  raw: JsonObject;
}

/**
 * One event sent (or on its way) to one webhook. `status` is `pending` (not tried yet),
 * `retrying` (an attempt failed; `nextRetryAt` says when the next one is), `succeeded` (your
 * server answered 2xx) or `failed` (three days of retries ran out). `responseStatus` and
 * `responseBody` (its first 4 KB) are from the latest attempt; `requestBody` is the JSON sent.
 */
export interface WebhookDelivery {
  id: string;
  webhookId: string | null;
  eventId: string | null;
  eventType: string | null;
  status: WebhookDeliveryStatus;
  /** Whether your server accepted it (a 2xx). */
  ok: boolean;
  attempts: number;
  responseStatus: number | null;
  responseBody: string | null;
  requestBody: string | null;
  durationMs: number | null;
  /** Why the latest attempt failed (`Answered 502`, `No answer within 10 seconds.`); null once it succeeded. */
  error: string | null;
  nextRetryAt: Date | null;
  createdAt: Date | null;
  raw: JsonObject;
}

/** @internal */
export function toWebhookDelivery(value: unknown): WebhookDelivery {
  const raw = asObject(value);
  const status = (str(raw.status) ?? "pending") as WebhookDeliveryStatus;
  return {
    id: str(raw.id) ?? "",
    webhookId: str(raw.webhook_id),
    eventId: str(raw.event_id),
    eventType: str(raw.event_type),
    status,
    ok: status === "succeeded",
    attempts: num(raw.attempts) ?? 0,
    responseStatus: num(raw.response_status),
    responseBody: str(raw.response_body),
    requestBody: str(raw.request_body),
    durationMs: num(raw.duration_ms),
    error: str(raw.error),
    nextRetryAt: parseTime(raw.next_retry_at),
    createdAt: parseTime(raw.created_at),
    raw,
  };
}

function toEventType(value: unknown): EventType {
  const raw = asObject(value);
  const name = str(raw.name) ?? "";
  return { name, description: str(raw.description) ?? "", area: name.split(".")[0], emitted: raw.emitted === true, raw };
}

export interface EventListOptions extends ReadOptions {
  /** One type or several; `*` matches the rest of a name (`domain.*`). */
  type?: string | readonly string[];
  since?: Date | string;
  until?: Date | string;
}

function eventQuery(options: EventListOptions) {
  return { type: csv(options.type), since: isoTime(options.since), until: isoTime(options.until) };
}

/**
 * Something that happened: an operation finished, a person answered, a domain went live.
 * `type` names it (see `Event.types()`) and `data` is the object it's about, as its own read
 * returns it (`data.object` names the kind, `data.id` its id). Delivered to your webhooks, and
 * kept for 30 days.
 */
export class Event extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _fromView(raw: JsonObject, init: { client?: NoClick; user?: ObjectInit["user"] } = {}): Event {
    return new Event({ raw, client: init.client, user: init.user });
  }

  static fromId(eventId: string, options: CallOptions = {}): Event {
    return new Event({ hints: { id: eventId }, client: options.client, user: options.user });
  }

  /** Load an event by id now, with its deliveries; an unknown id (or one older than 30 days) throws `NotFound`. */
  static async get(eventId: string, options: CallOptions = {}): Promise<Event> {
    return await Event.fromId(eventId, options).hydrate();
  }

  /**
   * Events newest first, from the last 30 days. Outside `asUser` you read your account's own
   * events; `userFilter` reads your users'.
   */
  static async list(options: EventListOptions & { limit?: number } = {}): Promise<Event[]> {
    return await listAll({ ...options, path: "/v1/events", query: eventQuery(options) }, (raw, user) => new Event({ raw, client: options.client, user }));
  }

  /** One page of events; pass `nextCursor` back as `cursor`. */
  static async listPage(options: EventListOptions & PageOptions = {}): Promise<Page<Event>> {
    return await listPage({ ...options, path: "/v1/events", query: eventQuery(options) }, (raw, user) => new Event({ raw, client: options.client, user }));
  }

  /** The catalog of event types a webhook can subscribe to, in catalog order (grouped by area). */
  static async types(options: { client?: NoClick } = {}): Promise<EventType[]> {
    return asList(await resolveClient(options.client).request("GET", "/v1/events/types", { user: null })).map(toEventType);
  }

  get id(): string {
    return this._field("id");
  }
  /** What happened, like `operation.succeeded`. */
  get type(): string {
    return this._field("type");
  }
  /** The object the event is about, as its own read returns it. */
  get data(): JsonObject {
    return asObject(this._field("data"));
  }
  /** The user it happened for (null for your account's own). */
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /**
   * Where this event went: one delivery per webhook that subscribes to it. The full view carries
   * them (`Event.get(id)`, or `await event.refresh()` for one from a listing).
   */
  get deliveries(): WebhookDelivery[] {
    const rows = this._known("deliveries");
    return Array.isArray(rows) ? rows.map(toWebhookDelivery) : [];
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", `/v1/events/${this._known("id")}`);
  }
}

// ── verifying a delivery ───────────────────────────────────────────────────

/** Request headers as `fetch` (`Headers`) or Node (`req.headers`) hands them over. */
export type WebhookHeaders = Headers | Readonly<Record<string, string | readonly string[] | undefined>>;

function headerValue(headers: WebhookHeaders, name: string): string | null {
  if (typeof Headers !== "undefined" && headers instanceof Headers) return headers.get(name);
  const wanted = name.toLowerCase();
  for (const [key, value] of Object.entries(headers as Record<string, string | readonly string[] | undefined>)) {
    if (key.toLowerCase() !== wanted || value === undefined) continue;
    return typeof value === "string" ? value : value.join(", ");
  }
  return null;
}

/** `t=1727366400,v1=ab..,v1=cd..` → timestamp and signatures; a rotation signs twice. */
function parseSignature(header: string): { timestamp: number | null; signatures: string[] } {
  let timestamp: number | null = null;
  const signatures: string[] = [];
  for (const part of header.split(",")) {
    const [key, ...rest] = part.trim().split("=");
    const value = rest.join("=").trim();
    if (key === "t" && /^\d+$/.test(value)) timestamp = Number(value);
    else if (key === "v1" && value) signatures.push(value);
  }
  return { timestamp, signatures };
}

const encoder = new TextEncoder();

async function hmacHex(secret: string, message: Uint8Array): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new TypeError("Webhook.verify needs Web Crypto (globalThis.crypto.subtle), which Node 20+, Deno, Bun, workers and browsers have.");
  }
  const key = await subtle.importKey("raw", encoder.encode(secret) as BufferSource, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await subtle.sign("HMAC", key, message as BufferSource));
  return Array.from(mac, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Compares without stopping at the first difference, so timing says nothing about the signature. */
function sameText(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function bodyBytes(payload: string | Uint8Array | ArrayBuffer): Uint8Array {
  if (typeof payload === "string") return encoder.encode(payload);
  return payload instanceof Uint8Array ? payload : new Uint8Array(payload);
}

/**
 * @internal Check a `NoClick-Signature` header over a raw body (`Webhook.verify`,
 * `Project.verifyRequest`); the body's bytes once it verifies.
 */
export async function verifySignature(
  payload: string | Uint8Array | ArrayBuffer,
  headers: WebhookHeaders,
  secret: string | readonly string[],
  tolerance: number,
): Promise<Uint8Array> {
  const body = bodyBytes(payload);
  const header = headerValue(headers, WEBHOOK_SIGNATURE_HEADER);
  if (!header) {
    throw new WebhookSignatureError(`The request has no ${WEBHOOK_SIGNATURE_HEADER} header.`, {
      nextStep: "Pass the request's headers as they arrived; answer 400 if it really has none.",
    });
  }
  const { timestamp, signatures } = parseSignature(header);
  if (timestamp === null || !signatures.length) {
    throw new WebhookSignatureError(`The ${WEBHOOK_SIGNATURE_HEADER} header isn't t=<timestamp>,v1=<signature>.`, { details: { header } });
  }
  const skew = Math.abs(Date.now() / 1000 - timestamp);
  if (skew > tolerance) {
    throw new WebhookSignatureError(`The delivery was signed ${Math.floor(skew)}s from now, more than the ${tolerance}s allowed.`, {
      nextStep: "Check your server's clock; a replayed delivery is refused on purpose.",
      details: { timestamp, tolerance_s: tolerance },
    });
  }
  const prefix = encoder.encode(`${timestamp}.`);
  const signed = new Uint8Array(prefix.length + body.length);
  signed.set(prefix);
  signed.set(body, prefix.length);
  const expected = await Promise.all((typeof secret === "string" ? [secret] : [...secret]).map((s) => hmacHex(s, signed)));
  if (!expected.some((e) => signatures.some((s) => sameText(e, s)))) {
    throw new WebhookSignatureError("No signature matches the body with this secret.", {
      nextStep: "Verify the raw body (not re-serialized JSON) with the webhook's current secret.",
    });
  }
  return body;
}

// ── webhooks ───────────────────────────────────────────────────────────────

export interface WebhookCreateOptions extends CallOptions {
  /** The event types it receives; `operation.*` or `*` for more at once. */
  events: readonly string[];
  description?: string;
  idempotencyKey?: string;
}

/** A field you leave out is unchanged; `description: null` clears it. */
export interface WebhookChanges {
  url?: string;
  events?: readonly string[];
  /** `false` pauses it: events that happen meanwhile are not delivered later. */
  enabled?: boolean;
  description?: string | null;
}

/**
 * An endpoint on your server that receives events, signed with its secret. One created for a
 * user (inside `asUser`, or with `user`) receives only that user's events; your account's
 * own receive every event, your users' included.
 */
export class Webhook extends ApiObject {
  private _createWith: JsonObject | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * A lazy reference to the webhook delivering to `url` for the current (or given) user; `url` names
   * it, since a scope has one webhook per address. Given `events` or `description`, it gets the webhook
   * and sets them, on every run. `createIfMissing` creates it with `events` (and `description`) when
   * there's none; without it, a missing webhook throws `NotFound`. Each run with fields is a write: do it
   * at startup or in a setup script, not per request.
   * `secret` holds the signing secret when this call created it; otherwise read it with `revealSecret()`.
   */
  static fromName(
    url: string,
    options: CallOptions & { createIfMissing?: boolean; events?: readonly string[]; description?: string } = {},
  ): Webhook {
    const hook = new Webhook({ hints: { url }, client: options.client, user: options.user });
    if (options.createIfMissing && !options.events?.length) {
      throw new TypeError("Webhook.fromName(..., { createIfMissing: true }) needs events");
    }
    hook._creates = Boolean(options.createIfMissing);
    if (hook._creates || givesFields(options)) {
      hook._createWith = compact({ url, events: options.events && [...options.events], description: options.description });
    }
    return hook;
  }

  /**
   * Start delivering `events` to `url`, an `https` address your server answers. `secret` is shown on the
   * result this once. A scope has one webhook per address: another throws `Conflict` with `existingId`, or
   * with `allowExisting: true` returns the one already there, as it is (its events don't change, and its
   * `secret` isn't shown: `revealSecret()` reads it).
   */
  static async create(url: string, options: WebhookCreateOptions & AllowExisting): Promise<Webhook> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/webhooks", compact({ url, events: [...options.events], description: options.description }), {
      allowExisting: options.allowExisting, user: scope, client: options.client, key: "url", idempotencyKey: options.idempotencyKey,
    });
    return new Webhook({ raw, client: options.client, user: scope });
  }

  static fromId(webhookId: string, options: CallOptions = {}): Webhook {
    return new Webhook({ hints: { id: webhookId }, client: options.client, user: options.user });
  }

  static async get(webhookId: string, options: CallOptions = {}): Promise<Webhook> {
    return await Webhook.fromId(webhookId, options).hydrate();
  }

  /** Your account's webhooks (or the current user's, or those `userFilter` covers). */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<Webhook[]> {
    return await listAll({ ...options, path: "/v1/webhooks" }, (raw, user) => new Webhook({ raw, client: options.client, user }));
  }

  /** One page of webhooks; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Webhook>> {
    return await listPage({ ...options, path: "/v1/webhooks" }, (raw, user) => new Webhook({ raw, client: options.client, user }));
  }

  /**
   * Check a delivery in your receiver: `payload` is the raw body exactly as it arrived (not parsed
   * and re-serialized), `headers` its headers and `secret` the webhook's, or several while you
   * rotate. The `NoClick-Signature` header is `t=<unix seconds>,v1=<hex>`, where the hex is
   * HMAC-SHA256 of `"<t>.<body>"` keyed with the secret; a timestamp more than `toleranceS`
   * (300) from now is refused, so a captured delivery can't be replayed. Sends nothing.
   * Throws `WebhookSignatureError` for a missing or malformed header, a stale timestamp, or no match.
   */
  static async verify(
    payload: string | Uint8Array | ArrayBuffer,
    headers: WebhookHeaders,
    secret: string | readonly string[],
    options: { toleranceS?: number } = {},
  ): Promise<Event> {
    const body = await verifySignature(payload, headers, secret, options.toleranceS ?? 300);
    let raw: unknown;
    try {
      raw = JSON.parse(new TextDecoder().decode(body));
    } catch {
      throw new WebhookSignatureError("The signed body isn't JSON.");
    }
    return Event._fromView(asObject(raw));
  }

  get id(): string {
    return this._field("id");
  }
  get url(): string {
    return this._field("url");
  }
  /** The event types it receives; `*` matches the rest of a name. */
  get events(): string[] {
    const value = this._field<unknown>("events");
    return Array.isArray(value) ? value.map(String) : [];
  }
  get enabled(): boolean {
    return this._field("enabled");
  }
  /** `healthy`, `failing` (its latest deliveries failed; retries continue) or `disabled`. */
  get status(): WebhookStatus {
    return this._field("status");
  }
  get description(): string | null {
    return this._field("description");
  }
  /** The share of attempts in the last 24 hours your server answered 2xx (null if none). */
  get successRate24h(): number | null {
    return num(this._field("success_rate_24h"));
  }
  /** The latest failed attempt: `at`, `response_status` and `error` (null if none). */
  get lastFailure(): JsonObject | null {
    const value = this._field<unknown>("last_failure");
    return value && typeof value === "object" ? (value as JsonObject) : null;
  }
  /** The user whose events it receives (null: every event). */
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /**
   * The signing secret (`nk_whsec_...`), on the object that created the webhook (`create`, or
   * `fromName` when it created one), `rotateSecret` or `revealSecret`; any other read leaves it out.
   */
  get secret(): string | null {
    return str(this._raw?.secret);
  }

  /** This webhook's route; a reference by url is looked up (or created) first. */
  private async path(): Promise<string> {
    if (typeof this._known("id") !== "string") await this._ensure();
    return `/v1/webhooks/${this._known("id")}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/webhooks/${id}`);
    const url = String(this._hints.url);
    const page = await this._request("GET", "/v1/webhooks", { query: { url } });
    // This scope's own endpoint: an account webhook never stands in for a user's.
    const [row] = (asList(page) as JsonObject[]).filter((r) => r.url === url && Boolean(r.user_id) === Boolean(this._scope));
    if (row) return await this.converge(row);
    if (!this._createWith || !this._creates) {
      throw new NotFound(`No webhook delivers to "${url}".`, {
        nextStep: "Create it with Webhook.create(...) or pass { createIfMissing: true }.",
        details: { url },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/webhooks", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/webhooks/${err.existingId}`));
    }
  }

  /** Set the fields `fromName` was given on an existing webhook. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    if (!this._createWith) return raw;
    const changes: JsonObject = {};
    for (const [key, value] of Object.entries(this._createWith)) {
      if (key !== "url" && JSON.stringify(raw[key] ?? null) !== JSON.stringify(value)) changes[key] = value;
    }
    return Object.keys(changes).length ? await this._request<JsonObject>("PATCH", `/v1/webhooks/${raw.id}`, { json: changes }) : raw;
  }

  /**
   * Read the current signing secret, so a receiver that starts from code (or a webhook `fromName`
   * found rather than created) can verify deliveries. Needs a key with the `webhooks:reveal` scope,
   * which full access leaves out; every reveal is recorded with the key that made it.
   */
  async revealSecret(): Promise<string> {
    const revealed = asObject(await this._request("GET", `${await this.path()}/secret`));
    this._raw = { ...(this._raw ?? {}), secret: revealed.secret ?? null };
    return str(revealed.secret) ?? "";
  }

  /** Printing a webhook never shows its secret. */
  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return `Webhook { id: ${JSON.stringify(this._known("id") ?? null)}, url: ${JSON.stringify(this._known("url") ?? null)}, status: ${JSON.stringify(this._known("status") ?? null)} }`;
  }

  /** Change where it delivers, what it receives, or pause it (`enabled: false`). */
  async update(changes: WebhookChanges): Promise<this> {
    const json = defined({ url: changes.url, events: changes.events ? [...changes.events] : undefined, enabled: changes.enabled, description: changes.description });
    this._raw = await this._request<JsonObject>("PATCH", await this.path(), { json });
    return this;
  }

  /** Delete the webhook; deliveries still retrying stop. */
  async delete(): Promise<void> {
    await this._request("DELETE", await this.path());
  }

  /**
   * Replace the signing secret. For `graceS` (default a day, at most 7 days) each delivery is
   * signed with both, so deliveries keep verifying while you deploy the new one; `graceS: 0` if the
   * old one leaked. Resolves to the new secret, shown this once (also on `hook.secret`).
   */
  async rotateSecret(options: { graceS?: number } = {}): Promise<string> {
    this._raw = asObject(await this._request("POST", `${await this.path()}/rotate_secret`, { json: compact({ grace_s: options.graceS }) }));
    return str(this._raw.secret) ?? "";
  }

  /**
   * Send a sample event of `eventType` now, signed like a real one, and wait up to 10 seconds for
   * your server's answer. It isn't retried and isn't recorded in `Event.list`.
   */
  async test(eventType = "operation.succeeded"): Promise<WebhookDelivery> {
    return toWebhookDelivery(await this._request("POST", `${await this.path()}/test`, { json: { event_type: eventType } }));
  }

  /** Deliveries newest first (the last 30 days), optionally only those with `status` or of one `event`. */
  async deliveries(
    options: { status?: WebhookDeliveryStatus | readonly WebhookDeliveryStatus[]; event?: Event | string; limit?: number } = {},
  ): Promise<WebhookDelivery[]> {
    const event = options.event instanceof Event ? options.event.id : options.event;
    const rows = await paginate(this._api, `${await this.path()}/deliveries`, {
      query: { status: csv(options.status), event_id: event },
      user: this._callScope() ?? null,
      limit: options.limit,
    });
    return rows.map(toWebhookDelivery);
  }

  /** Send a delivery's event again now (the same event id), whatever its status. */
  async redeliver(delivery: WebhookDelivery | string): Promise<WebhookDelivery> {
    const id = typeof delivery === "string" ? delivery : delivery.id;
    return toWebhookDelivery(await this._request("POST", `${await this.path()}/deliveries/${encodeURIComponent(id)}/redeliver`));
  }
}
