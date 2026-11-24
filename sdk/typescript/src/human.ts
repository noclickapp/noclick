/** Humans: ask a person, get an approval, send a notice, request a connection. */

import { Agent, agentId } from "./agent.ts";
import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { Connection } from "./connection.ts";
import type { ConnectLink } from "./connection.ts";
import { _registerApprovalFactory } from "./errors.ts";
import { asObject, compact, csv, listAll, listPage, str } from "./object.ts";
import type { JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { Operation, registerResult, withKinds } from "./operation.ts";
import type { Workflow } from "./workflow.ts";
import type { KindScopedFilters, OperationSummary } from "./operation.ts";
import { resolveScope, userIdOf } from "./scope.ts";
import type { UserOption } from "./scope.ts";

/**
 * What the person chose (`choice`) and/or wrote (`text`). A `pick`'s answer names the choice in the
 * account too (`value`: a repository's `owner/name`, a channel's id); a question asked with
 * `multiple` names each one they chose (`choices`, and a pick's `values`).
 */
export interface Answer {
  choice: string | null;
  text: string | null;
  value: string | null;
  choices: string[];
  values: string[];
  /** A `connect` question's: the connection set on the step, by its ref (also its `value`; `choice` is its name). */
  connection: string | null;
  /** A `secret` question's: the secret its values went into, never the values. */
  secret: string | null;
  raw: unknown;
}

/**
 * Something to pick in a connected account (`Human.ask`'s `pick`): the connection (a `Connection`, or
 * its id or name) and the field its lookup lists (`connection.lookup` names them: `repository`,
 * `team_id`, `channel`), with the values that field depends on (a spreadsheet's id for its sheets).
 */
export interface HumanPick {
  connection: string | Connection;
  field: string;
  arguments?: JsonObject;
}

/** A workflow step a question fills in: its workflow (a `Workflow` or its id) and its id in the graph. */
export interface HumanStepRef {
  workflow: string | Workflow;
  stepId: string;
}

/**
 * Which of the account's connections a workflow step uses (`Human.ask`'s `connect`, asked of the owner): the app or
 * model provider (`integration`) or the one kind of credential (`credentialType`), and the step; `slot` narrows it
 * to one kind the step keys connections by.
 */
export interface HumanConnectAsk {
  integration?: string;
  credentialType?: string;
  step: HumanStepRef & { slot?: string };
}

/**
 * A secret's values (`Human.ask`'s `secret`): typed on NoClick's page and kept as the account's secret `name`, its
 * `keys` each a value; with `step`, an agent step's shell gets it too (the owner's only).
 */
export interface HumanSecretAsk {
  name: string;
  keys: string[];
  step?: HumanStepRef;
}

/**
 * What `HumanRequest.answer` takes: a question's choice(s) and/or text, a connect question's connection, or a secret
 * question's values.
 */
export interface HumanAnswerFields {
  choice?: string;
  choices?: string[];
  text?: string;
  /** One of the account's connections that fits (a `Connection`, or its ref or name). */
  connection?: string | Connection;
  /** A value for each of the secret's keys: kept in the secret, never with the answer. */
  secretValues?: Record<string, string>;
}

/** What `Human.ask` takes beside its question. */
export interface HumanAskOptions {
  /** The answers they choose from (up to 20); left out, they answer in their own words. */
  options?: string[];
  /** In place of `options`: something in a connected account. The choices are read from it, and an account that holds just one answers at once with it. */
  pick?: HumanPick;
  /** They may choose several of the options, or of a pick's choices. */
  multiple?: boolean;
  /** Asked of the owner: which of the account's connections a workflow step uses. NoClick sets the one they choose as them, and an account holding just one that fits answers at once with it. Needs the `workflows` scope. */
  connect?: HumanConnectAsk;
  /** A secret's values, typed on NoClick's page (its link carries a key: the request's id alone opens nothing), never shown to you or a model. Needs the `secrets` scope. */
  secret?: HumanSecretAsk;
  via?: Via;
  expiresInS?: number;
}

function stepRef(step: HumanStepRef & { slot?: string }): JsonObject {
  const workflowId = typeof step.workflow === "string" ? step.workflow : step.workflow.id;
  return compact({ workflow_id: workflowId, step_id: step.stepId, slot: step.slot });
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];

/** An email confirmed for the owner (`Human.confirmEmail`). */
export interface OwnerEmail {
  email: string;
  /** `added`, or `verified` when an agent's turn confirmed it: it's added once that turn ends. */
  status: string;
  /** An account that already had the email took this one in. */
  merged: boolean;
}

/** One of NoClick's own numbers the owner texts it on (`Human.reach`): `app` is `whatsapp` or `imessage`. */
export interface OwnerLine {
  app: string;
  number: string;
}

/** Where the owner texts NoClick (`Human.reach`). */
export interface OwnerReach {
  /** NoClick's own numbers, one for each app it answers on. */
  lines: OwnerLine[];
  /** Whether a phone of the owner's is linked to the account; which one is never said. */
  phoneLinked: boolean;
  /** The address the owner emails their assistant at; null before it has one. */
  email: OwnerEmailAddress | null;
}

/** The address the owner emails their assistant at. */
export interface OwnerEmailAddress {
  address: string;
  /** The owner turned its mail off: the address stays theirs, and mail to it is ignored. */
  paused: boolean;
  /** Anyone's mail to it reaches the assistant, not only the owner's. */
  fromAnyone: boolean;
}

/** `"auto"` or the channels to use, e.g. `["email", "web"]`. */
export type Via = "auto" | string | string[];

registerResult("human.ask", (result): Answer => {
  if (result && typeof result === "object") {
    const body = result as JsonObject;
    return {
      choice: str(body.choice),
      text: str(body.text),
      value: str(body.value),
      choices: strings(body.choices),
      values: strings(body.values),
      connection: str(body.connection),
      secret: str(body.secret),
      raw: result,
    };
  }
  const text = result === null || result === undefined ? null : String(result);
  return { choice: null, text, value: null, choices: [], values: [], connection: null, secret: null, raw: result };
});
registerResult("human.approve", (result) =>
  result && typeof result === "object" ? Boolean((result as JsonObject).approved) : Boolean(result),
);
registerResult("human.notify", () => null);

export type HumanRequestStatus = "pending" | "answered" | "delivered" | "expired" | "canceled";

// `string & {}` keeps the names suggested while staying compatible with `Operation.list`'s filters.
type OneOrMany<T extends string> = T | (string & {}) | readonly (T | (string & {}))[];

export interface HumanRequestFilters extends ReadOptions {
  status?: OneOrMany<HumanRequestStatus>;
  statusNot?: OneOrMany<HumanRequestStatus>;
  kind?: OneOrMany<"ask" | "approve" | "notify">;
  /**
   * `"owner"`: only requests the signed-in account owner may answer; `"code"`: only those your code
   * may answer with `approve` or `decline`. A call NoClick holds for the account's owner (a purchase or a
   * deletion, whose `request.owner_only` is true) is listed only for a key that names the `approvals:answer`
   * scope, and never one made with that key or one whose terms a person accepts (see `Approval`).
   */
  answerable?: "owner" | "code";
}

function requestQuery(filters: HumanRequestFilters) {
  return {
    status: csv(filters.status),
    status_not: csv(filters.statusNot),
    kind: csv(filters.kind),
    answerable: filters.answerable,
  };
}

const HUMAN_KINDS = ["human.ask", "human.approve", "human.notify"] as const;

/** A request to a person; also the operation that finishes when they answer. */
export class HumanRequest<T> extends Operation<T> {
  private _view: JsonObject = {};

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _fromResponse<T>(raw: unknown, init: { client?: NoClick; user?: UserOption; kind: string }): HumanRequest<T> {
    const request = new HumanRequest<T>(Operation._init(raw, init));
    request._view = asObject(asObject(raw).request);
    return request;
  }

  /**
   * @internal The request a held call waits on, from its `approval_required` details (`operation`,
   * `request_id`, `approve_url`); null when your key can't read it (a user's session, or a key pinned
   * to the user, for a call someone else approves). An approval asked as your account (the owner's, or
   * a person's a rule names) is waited on as your account.
   */
  static _held(approval: JsonObject, init: { client?: NoClick; user?: UserOption }): HumanRequest<boolean> | null {
    const held = approval.operation;
    if (!(typeof held === "string" || (held && typeof held === "object"))) return null;
    const asAccount = typeof held === "object" && "user_id" in held && (held as JsonObject).user_id === null;
    const user = asAccount ? null : init.user;
    const request = HumanRequest._fromResponse<boolean>(held, { ...init, user, kind: "human.approve" });
    request._view = compact({ id: approval.request_id, url: approval.approve_url });
    return request;
  }

  /** @internal From a request view (a listing row): the operation stays lazy. */
  static _fromView<T>(view: JsonObject, init: { client?: NoClick; user?: UserOption }): HumanRequest<T> {
    const hints = compact({ id: view.operation_id, kind: typeof view.kind === "string" ? `human.${view.kind}` : undefined });
    const request = new HumanRequest<T>({ hints, client: init.client, user: init.user });
    request._view = view;
    return request;
  }

  /** Requests your code and agents sent, newest first (or the first `limit`). */
  static override async list(options: HumanRequestFilters & { limit?: number } = {}): Promise<HumanRequest<unknown>[]> {
    return await listAll(
      { ...options, path: "/v1/humans/requests", query: requestQuery(options) },
      (raw, user) => HumanRequest._fromView<unknown>(raw, { client: options.client, user }),
    );
  }

  /** One page of requests; pass `nextCursor` back as `cursor`. */
  static override async listPage(options: HumanRequestFilters & PageOptions = {}): Promise<Page<HumanRequest<unknown>>> {
    return await listPage(
      { ...options, path: "/v1/humans/requests", query: requestQuery(options) },
      (raw, user) => HumanRequest._fromView<unknown>(raw, { client: options.client, user }),
    );
  }

  /** How many human-request operations (ask, approve, notify) match, by operation status. */
  static override async summary(options: KindScopedFilters = {}): Promise<OperationSummary> {
    return await Operation.summary(withKinds(options, HUMAN_KINDS, "HumanRequest.summary"));
  }

  /** The request's own id (the operation's is `id`). */
  get requestId(): string | null {
    return str(this._view.id);
  }
  /** `pending`, `answered`, `delivered`, `expired` or `canceled`. */
  get requestStatus(): HumanRequestStatus | null {
    return str(this._view.status) as HumanRequestStatus | null;
  }

  /** The request as created: `url`, `delivered_via`, `undelivered`, ... */
  get request(): JsonObject {
    return { ...this._view };
  }
  /** The page where the person answers (`/h/{id}`); embed or send it yourself. */
  get url(): string | null {
    return str(this._view.url);
  }
  get deliveredVia(): string[] {
    return Array.isArray(this._view.delivered_via) ? (this._view.delivered_via as string[]) : [];
  }
  /** Channels that failed, each with a `reason`. */
  get undelivered(): JsonObject[] {
    return Array.isArray(this._view.undelivered) ? (this._view.undelivered as JsonObject[]) : [];
  }

  /** What the approver wrote with their answer (null until answered, or if they wrote nothing). */
  get note(): string | null {
    const result = this._known("result");
    if (result && typeof result === "object" && "note" in result) return str((result as JsonObject).note);
    return str(this._view.note);
  }

  private async respond(body: JsonObject): Promise<this> {
    const requestId = this.requestId;
    if (!requestId) throw new TypeError("This request has no request id to answer; list it with HumanRequest.list(...).");
    this._view = asObject(await this._request("POST", `/v1/humans/requests/${encodeURIComponent(requestId)}/answer`, {
      json: compact(body),
    }));
    return this;
  }

  /**
   * Answer a question from your own code, as the person it waits on (who may: as `approve` says): a `choice` (or
   * `choices`) and/or `text`; a connect question's `connection` (one of the account's that fits), which NoClick sets
   * on the step as your key, so it needs the `workflows` scope and a key acting for your whole account, never a
   * user's or an agent's own tools; a secret question's `secretValues`, kept in the secret and never with the
   * answer, which needs the `secrets` scope.
   *
   * @example
   * for (const request of await HumanRequest.list({ status: "pending", kind: "ask", answerable: "code" })) {
   *   if (request.request.connect) await request.answer({ connection: "work-slack" });
   * }
   */
  answer(fields: HumanAnswerFields): Promise<this> {
    const connection = fields.connection instanceof Connection ? fields.connection._ref : fields.connection;
    return this.respond({
      choice: fields.choice,
      choices: fields.choices?.length ? [...fields.choices] : undefined,
      text: fields.text,
      connection,
      secret_values: fields.secretValues ? { ...fields.secretValues } : undefined,
    });
  }

  /**
   * Approve it from your own code, as the person it waits on: with a key acting for your account,
   * an approval routed to your account; with a user's session or inside `asUser`, one addressed to
   * that user; a call NoClick holds for the account's owner, only with a key that names the
   * `approvals:answer` scope, as `Approval.approve` answers it (anyone else gets `PermissionDenied`).
   * A held operation call then runs exactly as it
   * was held (a held shell command or other tool, the agent makes again itself), and the agent gets
   * a turn in the same conversation with its result, its reply going out where the conversation
   * lives: on an email thread, the same thread (the inbox agent's `reply` tool is bound to the
   * thread's latest message).
   */
  approve(options: { note?: string } = {}): Promise<this> {
    return this.respond({ approved: true, note: options.note });
  }

  /** Decline it: a held call never runs, and the agent gets a turn saying so, with your `note`. */
  decline(options: { note?: string } = {}): Promise<this> {
    return this.respond({ approved: false, note: options.note });
  }
}

_registerApprovalFactory((details, origin) => HumanRequest._held(details, { client: origin?.client, user: origin?.user ?? null }));

function via(value: Via | undefined): string | string[] {
  if (value === undefined) return "auto";
  if (typeof value === "string") return value === "auto" ? value : [value];
  return [...value];
}

/** The tools a person gives an agent: `notify`, `ask` and `hand_off`. */
export type HumanTool = "notify" | "ask" | "hand_off";
const HUMAN_TOOLS: readonly HumanTool[] = ["notify", "ask", "hand_off"];

/** Some of a person's tools for an agent (`human.only(...)`), for `tools`. */
export class HumanOperations {
  readonly human: Human;
  readonly tools: HumanTool[];

  constructor(human: Human, tools: HumanTool[]) {
    this.human = human;
    this.tools = tools;
  }

  /** @internal */
  async _toolRefs(): Promise<JsonObject[]> {
    return [{ human: await this.human._toolAddress(), tools: HUMAN_TOOLS.filter((t) => this.tools.includes(t)) }];
  }
}

export interface HumanOptions {
  email?: string;
  phone?: string;
  /** The user this person is (default: the user current at each call). */
  user?: UserOption;
  client?: NoClick;
}

/**
 * A person to reach. `user.human` (or `new Human()`, meaning the user
 * current at each call, or the one a session or user-pinned key acts for)
 * is the user; `Human.owner()` is your account's owner; `new Human({ email })` is anyone else.
 * Every method returns an operation: `await req.wait()` for the outcome.
 *
 * `via` says where a message goes: `"auto"` (the default), or a list of `"web"` (only the page: you
 * pass `request.url` on), `"email"`, and for the owner `"whatsapp"` and `"imessage"`, sent from
 * NoClick's own numbers to the number they text NoClick from. `"auto"` is the app the owner last
 * texted NoClick on, else email. `"sms"` and `"call"` throw `NotAvailable` for now. What couldn't be
 * sent is listed in `undelivered`, never implied.
 */
export class Human {
  private readonly scope: UserOption;
  private readonly client: NoClick | undefined;
  private to: JsonObject;

  /**
   * Your account's owner: the person behind the account, reached by email and on the app they text
   * NoClick from. Only your account reaches them: it always acts as your account, inside `asUser` too,
   * and a user's session or a key pinned to a user throws `PermissionDenied`.
   *
   *     await Human.owner().notify("The site is live: https://morrowbakery.com");
   */
  static owner(options: { client?: NoClick } = {}): Human {
    const human = new Human({ user: null, client: options.client });
    human.to = { owner: true };
    return human;
  }

  /**
   * Send what this person texts or says to NoClick's own numbers (its WhatsApp and iMessage numbers and
   * its voice number) to `agent` (one of your account's). A text's reply goes back on the app they texted
   * on once the agent's turn ends, and texts sent while it's busy go in its next turn, in order; on a call,
   * each thing they say is a turn whose reply is read aloud as it's written. `null` hands them back to
   * NoClick's assistant. Only `Human.owner()` reaches NoClick's numbers: your users reach an agent on a
   * number of your own (`PhoneNumber.answerWith`). `conversation` is the agent's conversation each text or
   * call lands in, a template over `{channel}` (`whatsapp`, `imessage` or `call`); omitted, `"owner"`.
   * Give an inbox and a number the same key and the person's email, calls and texts are one conversation.
   *
   *     const assistant = Agent.fromName("assistant");
   *     await Human.owner().answerWith(assistant);
   *     await assistant.message("What's on today?", { conversation: "owner" }); // the same thread
   */
  async answerWith(agent: Agent | string | null, options: { conversation?: string } = {}): Promise<this> {
    if (!this.to.owner) {
      throw new TypeError("Only Human.owner() texts NoClick's own numbers; give a user a number of your own with PhoneNumber.answerWith.");
    }
    const json = { agent_id: agent === null ? null : ((await agentId(agent)) ?? null), ...compact({ conversation: options.conversation }) };
    await resolveClient(this.client).request("POST", "/v1/humans/owner/answer", { json, user: null });
    return this;
  }

  /** The agent this person's texts to NoClick's own numbers go to (`answerWith`), or `null` when NoClick's assistant answers them. */
  async answering(): Promise<Agent | null> {
    if (!this.to.owner) throw new TypeError("Only Human.owner() texts NoClick's own numbers.");
    const raw = asObject(await resolveClient(this.client).request("GET", "/v1/humans/owner/answer", { user: null }));
    const found = str(raw.agent_id);
    return found ? Agent.fromId(found, { client: this.client, user: null }) : null;
  }

  /**
   * NoClick's own numbers the owner texts it on, whether a phone of theirs is linked (never which), and the
   * address they email their assistant at (`email`, null before it has one). Show a number only once a phone is
   * linked: a text from a phone the account hasn't linked starts an account of its own, and linking one is the
   * owner's, signed in to NoClick. Your account's own key reads it, never a user's.
   *
   *     const { lines, phoneLinked } = await Human.owner().reach();
   *     if (phoneLinked) for (const line of lines) console.log(`${line.app}: ${line.number}`);
   */
  async reach(): Promise<OwnerReach> {
    if (!this.to.owner) throw new TypeError("Only Human.owner() texts NoClick's own numbers.");
    const raw = asObject(await resolveClient(this.client).request("GET", "/v1/humans/owner/reach", { user: null }));
    const lines = Array.isArray(raw.lines) ? raw.lines.map(asObject) : [];
    const email = raw.email ? asObject(raw.email) : null;
    return {
      lines: lines.map((line) => ({ app: str(line.app) ?? "", number: str(line.number) ?? "" })),
      phoneLinked: Boolean(raw.phone_linked),
      email: email && { address: str(email.address) ?? "", paused: email.paused === true, fromAnyone: email.from_anyone === true },
    };
  }

  /**
   * Where the signed-in owner is, from their browser (an IANA zone such as `"Europe/London"`): the clock of the
   * account's assistant, and of each of its own agents NoClick placed, moves there; a zone chosen through the API
   * stays. The signed-in owner's alone: a key rejects with `PermissionDenied`.
   *
   *     await Human.owner().setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone);
   */
  async setTimezone(timezone: string): Promise<void> {
    if (!this.to.owner) throw new TypeError("Only Human.owner() says where the owner is.");
    await resolveClient(this.client).request("PUT", "/v1/humans/owner/timezone", { json: { timezone }, user: null });
  }

  /**
   * Send a code to `email` for the owner of an account made by texting NoClick (which has none);
   * `confirmEmail` with the code makes it theirs. Throws `Conflict` when the account already has an
   * email, `RateLimited` after too many codes.
   *
   *     const owner = Human.owner();
   *     await owner.addEmail("maya@morrowbakery.com");
   *     await owner.confirmEmail(code);
   */
  async addEmail(email: string): Promise<void> {
    if (!this.to.owner) throw new TypeError("Only Human.owner() takes an email this way.");
    await resolveClient(this.client).request("POST", "/v1/humans/owner/email", { json: { email }, user: null });
  }

  /**
   * The code `addEmail` sent: on a match the email is the owner's to sign in with, or, when an account
   * already has it, that account takes this one in (`merged`). Whether an account has the email is said
   * only once the code matches. `status` is `added`, or `verified` when an agent's turn confirmed it
   * (it's added once that turn ends).
   *
   *     const confirmed = await Human.owner().confirmEmail("482913");
   */
  async confirmEmail(code: string): Promise<OwnerEmail> {
    if (!this.to.owner) throw new TypeError("Only Human.owner() takes an email this way.");
    const raw = asObject(
      await resolveClient(this.client).request("POST", "/v1/humans/owner/email/confirm", { json: { code }, user: null }),
    );
    return { email: str(raw.email) ?? "", status: str(raw.status) ?? "", merged: Boolean(raw.merged) };
  }

  /** @internal Who this person is on the wire (`{email}`, `{phone}` or `{user: true}`), for calls that address them. */
  get _address(): JsonObject {
    return this.to;
  }

  constructor(options: HumanOptions = {}) {
    this.scope = options.user;
    this.client = options.client;
    this.to = options.email || options.phone ? compact({ email: options.email, phone: options.phone }) : { user: true };
  }

  /**
   * @internal Who this person is in an agent's tools: an email or phone, a user by your id, or
   * (`new Human()`) the user each turn acts for.
   */
  async _toolAddress(): Promise<JsonObject> {
    if (!this.to.user || this.scope === undefined) return { ...this.to };
    const userId = await userIdOf(resolveScope(this.scope));
    return userId ? { user_id: userId } : { ...this.to };
  }

  /** @internal */
  async _toolRefs(): Promise<JsonObject[]> {
    return [{ human: await this._toolAddress(), tools: [...HUMAN_TOOLS] }];
  }

  /**
   * Some of the tools this person gives an agent, for `tools`. In an
   * agent's tools a `Human` gives it three, each addressed only to this person: `notify`, `ask`
   * (the turn waits, `awaiting_human`, and the answer arrives as the next turn) and `hand_off`
   * (the conversation goes to this person, with a page and an email carrying the transcript and a
   * reply box; their replies post as `person` messages and the agent stays quiet until
   * `agent.handBack(conversation)`; on a call it's transferred to the person's `phone`). Policy
   * names them `human.notify`, `human.ask` and `human.hand_off`.
   *
   *     const manager = new Human({ email: "ops@acme.com" });
   *     await Agent.create("support", { instructions: "...", tools: ["search", manager.only("notify", "ask")] });
   */
  only(...tools: HumanTool[]): HumanOperations {
    if (!tools.length) throw new TypeError("only() takes at least one of notify, ask and hand_off");
    const unknown = tools.find((t) => !HUMAN_TOOLS.includes(t));
    if (unknown) throw new TypeError(`A person's tools are notify, ask and hand_off, not ${JSON.stringify(unknown)}`);
    return new HumanOperations(this, [...tools]);
  }

  private async send<T>(kind: string, body: JsonObject): Promise<HumanRequest<T>> {
    const scope = resolveScope(this.scope);
    const raw = await resolveClient(this.client).request("POST", "/v1/humans/requests", {
      json: { kind, to: this.to, ...compact(body) },
      user: scope,
    });
    return HumanRequest._fromResponse<T>(raw, { client: this.client, user: scope, kind: `human.${kind}` });
  }

  /**
   * Ask a question; `wait()` resolves to an `Answer`. `pick` asks, in place of `options`, for
   * something in one of their connected accounts, and `multiple` lets them choose several.
   *
   * @example
   * const answer = await (await Human.owner().ask("Which repositories should the reviewer watch?", {
   *   pick: { connection: "github", field: "repository" },
   *   multiple: true,
   * })).wait();
   * console.log(answer.values); // ["acme/site", "acme/api"]
   */
  ask(message: string, options: HumanAskOptions = {}): Promise<HumanRequest<Answer>> {
    const pick = options.pick;
    return this.send<Answer>("ask", {
      message,
      options: options.options?.length ? [...options.options] : undefined,
      pick: pick
        ? compact({
            connection: pick.connection instanceof Connection ? pick.connection._ref : pick.connection,
            field: pick.field,
            arguments: pick.arguments,
          })
        : undefined,
      multiple: options.multiple ? true : undefined,
      connect: options.connect
        ? compact({
            integration: options.connect.integration,
            credential_type: options.connect.credentialType,
            step: stepRef(options.connect.step),
          })
        : undefined,
      secret: options.secret
        ? compact({
            name: options.secret.name,
            keys: [...options.secret.keys],
            step: options.secret.step ? stepRef(options.secret.step) : undefined,
          })
        : undefined,
      via: via(options.via),
      expires_in_s: options.expiresInS,
    });
  }

  /** Ask for a yes/no; `wait()` resolves to `true` when approved. */
  approve(message: string, options: { details?: unknown; via?: Via; expiresInS?: number } = {}): Promise<HumanRequest<boolean>> {
    return this.send<boolean>("approve", {
      message,
      details: options.details,
      via: via(options.via),
      expires_in_s: options.expiresInS,
    });
  }

  /** Send a notice (the operation succeeds once it's sent). */
  notify(message: string, options: { via?: Via } = {}): Promise<HumanRequest<null>> {
    return this.send<null>("notify", { message, via: via(options.via) });
  }

  /**
   * Ask this person to connect `connection` (a `Connection` or its name, in
   * this person's user); `wait()` resolves to the connected `Connection`.
   */
  connect(connection: string | Connection, options: { reason?: string; redirectUrl?: string } = {}): Promise<ConnectLink> {
    const target =
      typeof connection === "string" ? Connection.fromName(connection, { user: this.scope, client: this.client }) : connection;
    return target.connectLink({ reason: options.reason, redirectUrl: options.redirectUrl, sendTo: this.to });
  }
}
