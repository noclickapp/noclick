/**
 * Inboxes: an email address your code or agent receives mail at.
 *
 *     const inbox = await Inbox.create({ localPart: "signup" });
 *     console.log(inbox.address);
 *     const wait = await inbox.waitFor({ sender: "noreply@github.com", subjectContains: "code", timeoutS: 300 });
 *     console.log((await wait.wait()).text);
 *
 * With `agent`, every inbound message wakes that agent, in its email thread's own conversation
 * (`message.conversation`), and the agent answers on the thread with a `reply` tool bound to the
 * thread's latest message. Replies go to the sender only; an inbox on a domain you bought also writes
 * new mail to one person at a time (`inbox.send`).
 * Inboxes have names (`Inbox.fromName`). Mail proven to be from one of your users runs as that user,
 * and `senders` says whose mail wakes the agent.
 */

import { TrashItem, trashed } from "./trash.ts";
import type { NoClick } from "./client.ts";
import { agentId } from "./agent.ts";
import type { Agent } from "./agent.ts";
import type { Domain } from "./domain.ts";
import { Conflict, NotFound } from "./errors.ts";
import {
  ApiObject, asList, asObject, checkUnchanged, compact, createNamed, defined, givesFields, isoTime, listAll, listPage, parseTime,
  str,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import { resolveScope } from "./scope.ts";
import type { UserOption } from "./scope.ts";

/** Long-poll window per request (`wait_s`). */
const STREAM_WAIT_S = 25;

/**
 * Whose mail wakes an inbox's agent: `anyone`, `users` (only mail proven to be from one of your users,
 * by a DKIM signature aligned with the sender, or SPF) or `owner` (the inbox's own user, or your account's
 * owner). It never changes who a turn runs as: on an account inbox, mail
 * proven to be from one of your users runs as that user under every setting.
 */
export type InboxSenders = "anyone" | "users" | "owner";

/** What `fromName` sets on an existing inbox. */
const CONVERGED = ["agent_id", "senders", "conversation"] as const;

/** What `inbox.send(...)` takes: `text`, `html` or both; `to` and `subject` unless it follows up on `thread`. */
export interface InboxSendOptions {
  to?: string;
  subject?: string;
  text?: string;
  html?: string;
  /** A thread (or its id) of this inbox to follow up on. */
  thread?: string | InboxThread;
  idempotencyKey?: string;
}

/** What `message.reply(...)` sent: `status` is ours, `deliveryStatus` the mail provider's. */
export interface InboxReply {
  id: string | null;
  status: string | null;
  deliveryStatus: string | null;
  raw: JsonObject;
}

/**
 * One email received by an inbox. A listing may trim the body: `inbox.message(id)` or
 * `await message.refresh()` loads the full view (text and digested attachments).
 */
export class InboxMessage extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _fromView(raw: JsonObject, init: { inboxId?: string | null; client?: NoClick; user?: UserOption }): InboxMessage {
    return new InboxMessage({ raw, hints: compact({ inbox_id: init.inboxId }), client: init.client, user: init.user });
  }

  get id(): string {
    return this._field("id");
  }
  get inboxId(): string | null {
    return str(this._known("inbox_id"));
  }
  /** `inbound` (received), or `outbound`: mail the inbox sent (a reply, or new mail), in a thread's messages. */
  get direction(): "inbound" | "outbound" {
    return this._known("direction") === "outbound" ? "outbound" : "inbound";
  }
  /**
   * `received`; for mail the inbox sent, `sending` (queued), `sent` or `failed` (it never went:
   * `deliveryError` says why).
   */
  get status(): string | null {
    return str(this._known("status"));
  }
  /** How mail the inbox sent landed: `delivered`, `bounced`, `complained` or `failed`; null until it's known. */
  get deliveryStatus(): string | null {
    return str(this._known("delivery_status"));
  }
  /** Why sent mail failed or bounced, when it did. */
  get deliveryError(): string | null {
    return str(this._known("delivery_error"));
  }
  /**
   * Who sent it: the message's From address when a DKIM signature aligned with it verified (as for mail a
   * sending service delivers under its own bounce address), else the envelope sender. `senderSource` says which.
   */
  get sender(): string | null {
    return str(this._known("from"));
  }
  /**
   * Where `sender` comes from: `header` (the From address, vouched for by an aligned DKIM signature) or
   * `envelope` (the envelope sender). null for mail the inbox sent.
   */
  get senderSource(): "header" | "envelope" | null {
    const source = this._known("from_source");
    return source === "header" || source === "envelope" ? source : null;
  }
  /** The envelope sender (SMTP MAIL FROM), often a sending service's bounce address. null for mail the inbox sent. */
  get envelopeSender(): string | null {
    return str(this._known("envelope_from"));
  }
  /**
   * Whether `sender` is vouched for, by an aligned DKIM signature (or, for the envelope sender, SPF).
   * `waitFor({ sender })` matches only authenticated mail. Who the mail runs as, and whether it's from the
   * inbox's own person, is decided on the envelope sender alone.
   */
  get authenticated(): boolean {
    return this._known("authenticated") === true;
  }
  get to(): unknown {
    return this._known("to") ?? null;
  }
  get subject(): string | null {
    return str(this._known("subject"));
  }
  /** The body as text. */
  get text(): string {
    return str(this._known("text")) ?? "";
  }
  /** The HTML body, if it had one. */
  get html(): string | null {
    return str(this._known("html"));
  }
  /** Attachments, each digested to text. */
  get attachments(): JsonObject[] {
    const value = this._known("attachments");
    return Array.isArray(value) ? (value as JsonObject[]) : [];
  }
  get receivedAt(): Date | null {
    return parseTime(this._known("received_at"));
  }
  /**
   * The conversation its email thread is with the inbox's agent: every message of one thread shares it.
   * A message from one of your users is in that user's conversations (`agent.history(conversation, { user })`).
   */
  get conversation(): string | null {
    return str(this._known("conversation"));
  }
  /** The agent turn this message woke (null if none); `wait()` resolves to its `AgentReply`. */
  get agentOperation(): Operation<unknown> | null {
    const id = str(this._known("agent_operation_id"));
    return id ? Operation.fromId(id, { client: this._client, user: this._callScope() }) : null;
  }
  /**
   * Why it didn't wake the inbox's agent, or why that turn failed: a sender `senders` doesn't let in, a
   * paused agent, a spent budget, the turn's own error (null otherwise).
   */
  get agentError(): string | null {
    return str(this._known("agent_error"));
  }

  private get path(): string {
    return `/v1/inboxes/${this._known("inbox_id")}/messages/${this._known("id")}`;
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", this.path);
  }

  override toString(): string {
    return this.text;
  }

  /** Reply to the sender (only the sender; the thread is kept). */
  async reply(text: string): Promise<InboxReply> {
    const raw = asObject(await this._request("POST", `${this.path}/reply`, { json: { text } }));
    return { id: str(raw.id), status: str(raw.status), deliveryStatus: str(raw.delivery_status), raw };
  }
}

/** One email thread of an inbox: what it received from one correspondent and the replies it sent them. */
export interface InboxThread {
  id: string;
  /** The conversation it is with the inbox's agent (`message.conversation`). */
  conversation: string | null;
  /** Its first message's subject. */
  subject: string | null;
  /** Who the inbox writes with on it. */
  correspondent: string | null;
  messageCount: number;
  /** Whether its newest message was received (`inbound`) or sent (`outbound`). */
  lastDirection: "inbound" | "outbound";
  /** The start of its newest message. */
  snippet: string | null;
  lastAt: Date | null;
  /** Its messages, both ways, oldest first: read whole (`inbox.thread(id)`) only. */
  messages: InboxMessage[];
  raw: JsonObject;
}

/** A wait settles with `{ message: <the message view> }`. */
function readMessage(result: unknown, op: Operation<unknown>, inboxId?: string): InboxMessage {
  return InboxMessage._fromView(asObject(asObject(result).message), { inboxId, client: op._client, user: op._scope });
}

registerResult("inbox.wait_for", (result, op) => readMessage(result, op));

export interface InboxCreateOptions extends CallOptions {
  /**
   * The part before the `@` (generated when omitted). One already taken is a `Conflict`; a reserved role name such
   * as `support` on NoClick's domain is an `InvalidRequest`.
   */
  localPart?: string;
  /** Woken by every inbound message. In `fromName`, `null` takes the inbox from its agent. */
  agent?: Agent | string | null;
  /**
   * An address on your own domain (a `Domain`, its name, or a name under it): any address on one you bought;
   * on one you connected, a name under it (`help@mail.acme.com`), so its existing mail keeps working.
   */
  domain?: Domain | string;
  /** What your code calls it, unique among its user's inboxes (a taken one is a `Conflict` with `existingId`). */
  name?: string;
  /** Whose mail wakes the agent (`anyone` by default). */
  senders?: InboxSenders;
  /**
   * The agent's conversation each message lands in, a template over `{sender}` and `{thread}`:
   * `"mail-{sender}"` is one per correspondent, `"owner"` the conversation `agent.message` reaches with
   * that key. Omitted, each email thread is a conversation of its own.
   */
  conversation?: string;
}

async function domainName(domain: Domain | string | undefined): Promise<string | undefined> {
  return typeof domain === "object" ? await domain._name() : domain;
}

async function wireInbox(options: InboxCreateOptions): Promise<JsonObject> {
  return compact({
    name: options.name,
    local_part: options.localPart,
    agent_id: await agentId(options.agent ?? undefined),
    domain: await domainName(options.domain),
    senders: options.senders,
    conversation: options.conversation,
  });
}

/** An email address that receives mail. `inbox.address` is where to send it. */
export class Inbox extends ApiObject {
  private _createWith: InboxCreateOptions | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create an inbox, named if you like (`Inbox.fromName` finds it). On an account inbox, a message
   * proven to be from one of your users (the email on their `User`, with an aligned DKIM signature or SPF)
   * runs as that user whatever `senders` says; any other runs as your account, and a user's own inbox
   * runs every message as that user. Each email thread is a conversation of its own with the agent
   * (`message.conversation`), and the agent gets a `reply` tool bound to the thread's latest message: it
   * answers that sender, on that thread, and nobody else, so a turn that resumes after an approval still
   * answers on the same thread. With `allowExisting: true` (and a `name`) a taken name returns the inbox
   * already there, as it is: nothing about it changes.
   */
  static async create(options: InboxCreateOptions & AllowExisting = {}): Promise<Inbox> {
    if (options.allowExisting && options.name === undefined) {
      throw new TypeError("Inbox.create({ allowExisting: true }) needs name: it's the name that's found taken");
    }
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/inboxes", await wireInbox(options), {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new Inbox({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the inbox called `name` for the current (or given) user. Given fields, it gets
   * the inbox and sets the ones you pass, on every run: an existing inbox whose `agent`, `senders` or
   * `conversation` differs gets yours. `createIfMissing` creates it when there's none; without it, a
   * missing inbox throws `NotFound`. Its
   * address (`localPart`, `domain`) is set once, when it's created: an existing inbox at another throws
   * `Conflict` naming it. A field left out is never changed; `agent: null` takes it from its agent. Each
   * run with fields is a write: set them at startup or in a setup script, and take the bare `fromName`
   * in request handlers.
   */
  static fromName(name: string, options: Omit<InboxCreateOptions, "name"> & { createIfMissing?: boolean } = {}): Inbox {
    const inbox = new Inbox({ hints: { name }, client: options.client, user: options.user });
    inbox._creates = Boolean(options.createIfMissing);
    if (inbox._creates || givesFields(options)) inbox._createWith = { ...options, name };
    return inbox;
  }

  static fromId(inboxId: string, options: CallOptions = {}): Inbox {
    return new Inbox({ hints: { id: inboxId }, client: options.client, user: options.user });
  }

  static async get(inboxId: string, options: CallOptions = {}): Promise<Inbox> {
    return await Inbox.fromId(inboxId, options).hydrate();
  }

  /**
   * The current user's inboxes (the account's own outside `asUser`, or those `userFilter` covers).
   * `agent` keeps the ones whose mail wakes it.
   */
  static async list(options: ReadOptions & { agent?: Agent | string; limit?: number } = {}): Promise<Inbox[]> {
    return await listAll(
      { ...options, path: "/v1/inboxes", query: { agent_id: await agentId(options.agent) } },
      (raw, user) => new Inbox({ raw, client: options.client, user }),
    );
  }

  /** One page of inboxes; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions & { agent?: Agent | string } = {}): Promise<Page<Inbox>> {
    return await listPage(
      { ...options, path: "/v1/inboxes", query: { agent_id: await agentId(options.agent) } },
      (raw, user) => new Inbox({ raw, client: options.client, user }),
    );
  }

  get id(): string {
    return this._field("id");
  }
  /** What your code calls it (null for one created without a name). */
  get name(): string | null {
    return this._field("name");
  }
  get address(): string {
    return this._field("address");
  }
  /** The agent each inbound message wakes (null if none). */
  get agentId(): string | null {
    return this._field("agent_id");
  }
  /** Whose mail wakes its agent. */
  get senders(): InboxSenders | null {
    return this._field("senders");
  }
  /** The conversation each message lands in, a template over `{sender}` and `{thread}` (null: each thread's own). */
  get conversation(): string | null {
    return this._field("conversation");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  /** Its path once its id is known (an inbox reached by name loads first). */
  private async path(): Promise<string> {
    const id = this._known("id") ?? (await this._ensure()).id;
    return `/v1/inboxes/${id}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/inboxes/${id}`);
    const name = String(this._hints.name);
    const rows = (asList(await this._request("GET", "/v1/inboxes", { query: { name } })) as JsonObject[]).filter((row) => row.name === name);
    if (rows.length) return await this.converge(rows[0]);
    if (!this._createWith || !this._creates) {
      throw new NotFound(`No inbox is named "${name}".`, {
        nextStep: "Create it with Inbox.create({ name }) or pass { createIfMissing: true }.",
        details: { name, kind: "inbox" },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/inboxes", { json: await wireInbox(this._createWith) });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/inboxes/${err.existingId}`));
    }
  }

  /** Set the fields `fromName` was given on an existing inbox, after checking its address. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    if (!this._createWith) return raw;
    const options = this._createWith;
    const [local, host] = String(raw.address ?? "").toLowerCase().split("@");
    const domain = await domainName(options.domain);
    checkUnchanged("inbox", { ...raw, local_part: local, domain: host ?? null }, {
      local_part: options.localPart?.toLowerCase(), domain: domain?.toLowerCase(),
    });
    const wanted: JsonObject = { ...(await wireInbox(options)), ...(options.agent === null ? { agent_id: null } : {}) };
    const changes: JsonObject = {};
    for (const key of CONVERGED) {
      if (key in wanted && JSON.stringify(raw[key] ?? null) !== JSON.stringify(wanted[key])) changes[key] = wanted[key];
    }
    if (!Object.keys(changes).length) return raw;
    return await this._request<JsonObject>("PATCH", `/v1/inboxes/${raw.id}`, { json: changes });
  }

  /**
   * Change which agent its mail wakes (`null`: none), whose mail does, or the conversation it lands in
   * (`conversation`, a template; `null`: each thread's own), from the next message.
   */
  async update(changes: {
    agent?: Agent | string | null; senders?: InboxSenders; conversation?: string | null;
  }): Promise<this> {
    const json = defined({ senders: changes.senders });
    if (changes.conversation !== undefined) json.conversation = changes.conversation;
    if (changes.agent !== undefined) json.agent_id = changes.agent === null ? null : ((await agentId(changes.agent)) ?? null);
    this._raw = await this._request<JsonObject>("PATCH", await this.path(), { json });
    return this;
  }

  /**
   * Delete the inbox: its address stops receiving mail, and it goes to the trash with its mail,
   * restorable for 30 days. Returns its `TrashItem`.
   */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this.path()), this);
  }

  private toMessage(raw: JsonObject): InboxMessage {
    return InboxMessage._fromView(raw, { inboxId: str(this._known("id")), client: this._client, user: this._callScope() });
  }

  /**
   * Messages oldest first, after `after` (a message or its id). With `waitS` the server holds the
   * request until one arrives. `since` keeps those received at or after it.
   */
  async messages(options: { after?: string | InboxMessage; since?: Date | string; waitS?: number } = {}): Promise<InboxMessage[]> {
    const after = options.after instanceof InboxMessage ? options.after.id : options.after;
    const page = await this._request("GET", `${await this.path()}/messages`, {
      query: { after, since: isoTime(options.since), wait_s: options.waitS },
      timeoutMs: options.waitS ? (options.waitS + 15) * 1000 : undefined,
    });
    return (asList(page) as JsonObject[]).map((raw) => this.toMessage(raw));
  }

  /** One message in full: text, sender, subject and digested attachments. */
  async message(messageId: string): Promise<InboxMessage> {
    return this.toMessage(asObject(await this._request("GET", `${await this.path()}/messages/${encodeURIComponent(messageId)}`)));
  }

  private toThread(raw: JsonObject): InboxThread {
    const messages = Array.isArray(raw.messages) ? (raw.messages as JsonObject[]).map((m) => this.toMessage(m)) : [];
    return {
      id: String(raw.id),
      conversation: str(raw.conversation),
      subject: str(raw.subject),
      correspondent: str(raw.correspondent),
      messageCount: typeof raw.message_count === "number" ? raw.message_count : messages.length,
      lastDirection: raw.last_direction === "outbound" ? "outbound" : "inbound",
      snippet: str(raw.snippet),
      lastAt: parseTime(raw.last_at),
      messages,
      raw,
    };
  }

  /** One page of its email threads, the most recently active first; pass `nextCursor` back as `cursor`. */
  async threads(options: PageOptions = {}): Promise<Page<InboxThread>> {
    const page = asObject(await this._request("GET", `${await this.path()}/threads`, {
      query: { cursor: options.cursor ?? undefined, limit: options.limit },
    }));
    return { data: (asList(page) as JsonObject[]).map((raw) => this.toThread(raw)), nextCursor: str(page.next_cursor) };
  }

  /** One thread whole: what it received and the replies it sent, oldest first. */
  async thread(threadId: string): Promise<InboxThread> {
    return this.toThread(asObject(await this._request("GET", `${await this.path()}/threads/${encodeURIComponent(threadId)}`)));
  }

  /**
   * New mail from this inbox to one person: business mail you mean to send, never bulk or cold outreach.
   * Only an inbox on a domain you bought sends new mail (one on `noclick.email` replies); up to 100 new
   * emails per address a day. With `thread`, a follow-up: `to` and `subject` default to its correspondent
   * and `Re:` its subject, and it lands in the recipient's copy of the thread. The message comes back
   * `sending` until it goes (minutes, the first time an address sends), then `sent`.
   *
   *     await inbox.send({ to: "orders@millbrook.test", subject: "Saturday delivery", text: "Can you deliver on Saturday?" });
   */
  async send(options: InboxSendOptions): Promise<InboxMessage> {
    const threadId = typeof options.thread === "string" ? options.thread : options.thread?.id;
    const raw = asObject(await this._request("POST", `${await this.path()}/messages`, {
      json: compact({ to: options.to, subject: options.subject, text: options.text, html: options.html, thread_id: threadId }),
      idempotencyKey: options.idempotencyKey,
    }));
    return this.toMessage(raw);
  }

  /**
   * Every message (from the start, after `after`, or received at or after `since`) as it arrives;
   * long-polls until you `break` or `signal` aborts.
   */
  async *stream(options: { after?: string | InboxMessage; since?: Date | string; waitS?: number; signal?: AbortSignal } = {}): AsyncGenerator<InboxMessage> {
    let after = options.after instanceof InboxMessage ? options.after.id : options.after;
    while (!options.signal?.aborted) {
      const started = Date.now();
      const batch = await this.messages({ after, since: after ? undefined : options.since, waitS: options.waitS ?? STREAM_WAIT_S });
      for (const message of batch) {
        after = message.id;
        yield message;
      }
      if (!batch.length) await this._api._sleep(Math.max(0, 1000 - (Date.now() - started))); // never spin on a short poll
    }
  }

  /**
   * Watch for the first message matching `sender` and/or `subjectContains` (a sign-up code, a
   * receipt). `wait()` resolves to the `InboxMessage`, or throws `Expired` once `timeoutS` passes.
   * `since` lets a message that arrived at or after it match too, so a wait started after you trigger
   * the email can't miss it.
   */
  async waitFor(options: { sender?: string; subjectContains?: string; since?: Date | string; timeoutS?: number } = {}): Promise<Operation<InboxMessage>> {
    const path = await this.path();
    const inboxId = String(this._known("id"));
    const payload = await this._request("POST", `${path}/wait_for`, {
      json: compact({ sender: options.sender, subject_contains: options.subjectContains, since: isoTime(options.since), timeout_s: options.timeoutS }),
    });
    return Operation._fromPayload<InboxMessage>(payload, {
      client: this._client, user: this._callScope(), kind: "inbox.wait_for",
      reader: (result, op) => readMessage(result, op, inboxId),
    });
  }
}
