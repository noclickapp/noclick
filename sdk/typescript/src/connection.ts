/**
 * Connections: named links to your users' accounts on other services.
 *
 *     const gmail = Connection.fromName("gmail", { integration: "gmail", createIfMissing: true });
 *     if (!(await gmail.hydrate()).connected) sendToUser(gmail.connectUrl);
 *     await gmail.wait();
 *     await gmail.run("send_email_message", { ... });
 *
 * A connection is a name in one scope (a user, or your account's own). Code,
 * toolkits and agents name it, so they always act in exactly that account; two
 * accounts on one service are two connections. Reconnecting keeps the name.
 * An operation that needs no account (`exa`'s web search) needs no connection
 * either: `run("exa.search", { ... })` and `tools: ["exa.search"]` run it on
 * NoClick's key, for every user, and a connection named `exa` holding your own
 * key takes over the same refs. `Connection.integrations("mail")` finds a
 * service to connect, and `gmail.operations({ search: "send" })` shows what a
 * connection can do.
 */

import { policyChange } from "./approval.ts";
import type { PolicyChange } from "./approval.ts";
import { resolveClient } from "./client.ts";
import type { NoClick, RequestOptions } from "./client.ts";
import { Conflict, InvalidRequest, NoClickError, NotFound, OperationCanceled, OperationExpired, OperationTimeout } from "./errors.ts";
import { Database } from "./database.ts";
import type { DatabaseOperations } from "./database.ts";
import { RepoCheckout } from "./repo.ts";
import type { CheckoutOptions } from "./repo.ts";
import {
  ApiObject, asList, asObject, boundArguments, checkUnchanged, compact, createNamed, listAll, listPage, num, parseTime, refId,
  requiredNumber, str, toolEntries,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { LONG_POLL_S, Operation, registerResult, withKinds } from "./operation.ts";
import type { KindScopedFilters, OperationSummary } from "./operation.ts";
import { resolveScope, userIdOf } from "./scope.ts";
import type { UserOption, UserRef } from "./scope.ts";

/** How long WhatsApp's sign-in may take to start: its linking service can take about a minute to show a QR. */
const QR_START_TIMEOUT_MS = 150_000;

/**
 * The agent answering a WhatsApp number of your account's (`Connection.numberAgent`): `agentId` and `name`, with the
 * channel the owner talks to it in, all null while no agent answers it; `available` whether your account can put one
 * on it (it has agents of its own), and `created` whether `makeNumberAgent` made it just now.
 */
export interface NumberAgent {
  available: boolean;
  agentId: string | null;
  name: string | null;
  channelId: string | null;
  channelName: string | null;
  created: boolean;
  raw: JsonObject;
}

function toNumberAgent(value: unknown): NumberAgent {
  const raw = asObject(value);
  const agent = asObject(raw.agent ?? {});
  return {
    available: raw.available === true, agentId: str(agent.id), name: str(agent.name), channelId: str(agent.channel_id),
    channelName: str(agent.channel_name), created: raw.created === true, raw,
  };
}

/** Whether the provider accepted the credential (`reachable` null = cannot judge). */
export interface Verification {
  reachable: boolean | null;
  /** Things of the account's own, as the provider sees them (`{ label, value }`). */
  samples: unknown[];
  message: string | null;
  hint: string | null;
  /** What the samples are ("repositories", "channels"); `null` when the check named none. */
  noun: string | null;
  /** How many there are when more than the samples; `null` when the check didn't say. */
  total: number | null;
  /** Who the account signs in as; `null` when the check didn't say. */
  accountLabel: string | null;
  /** `account` when the answer is the account's own, `reachability` when the provider only accepted the key. */
  proves: string | null;
  /** The provider's own words when it turned the account down; `null` otherwise. */
  error: string | null;
  raw: JsonObject;
}

/** How an account shared with yours reaches it: shared with your account's person (`you`) or with the team
 *  workspace it's read in (`workspace`), and who shared it (`byName`, `byEmail`). */
export interface ConnectionShared {
  with: "you" | "workspace";
  byName: string | null;
  byEmail: string | null;
  raw: JsonObject;
}

/** A provider's live word on a linked session (a WhatsApp number's, a Discord install's). */
export interface ConnectionHealth {
  healthy: boolean;
  /** The provider's own word for its state (`connected`, `failed`, `installed`). */
  status: string;
  /** What to do when it isn't healthy. */
  hint: string | null;
  raw: JsonObject;
}

/** How full a plan is: `near` from 0.8 used, `used_up` at 1, `unknown` with no reading yet. */
export type PlanUsageState = "ok" | "near" | "used_up" | "unknown";

/**
 * A Claude or ChatGPT plan's tier, read at sign-in and each refresh (`tier` and `label` null until then).
 * `label` is the provider's own name for it ("Ultra", "Max 20x", "Plus"); `runs` the harnesses it can run,
 * empty when `refusal` says why it runs none ("Claude Free doesn't include Claude Code.").
 */
export interface Plan {
  tier: string | null;
  label: string | null;
  runs: string[];
  refusal: string | null;
  raw: JsonObject;
}

/** One of a plan's usage windows: `used` and `left` are fractions from 0 to 1. */
export interface PlanWindow {
  kind: "five_hour" | "weekly" | "weekly_model" | "other" | string;
  /** "5-hour", "Weekly", "Opus weekly". */
  label: string;
  /** The models it limits; empty for one that limits every model. */
  models: string[];
  used: number;
  left: number;
  /** Null once it's past its reset (it then reads as reset, `used` 0). */
  resetsAt: Date | null;
  state: "ok" | "near" | "used_up" | string;
  raw: JsonObject;
}

/** The summary every plan connection carries (`connection.usageSummary`). */
export interface PlanUsageSummary {
  state: PlanUsageState;
  /** The window that stops it first: the used-up one that resets last, else the most used. */
  tightest: PlanWindow | null;
  /** When a used-up plan runs again, else null. */
  availableAt: Date | null;
  asOf: Date | null;
  raw: JsonObject;
}

/** What to do about a plan's usage: wait, run on another of your accounts, NoClick's key, or connect another. */
export interface PlanNextStep {
  kind: "wait" | "connection" | "noclick_key" | "connect" | string;
  label: string;
  until: Date | null;
  connection: { id: string; name: string; integration: string | null; credentialType: string | null } | null;
  pays: "per_use" | "at_cost" | null;
  /** Another plan's own state for the model asked about (`near`: it's nearly used too); null for a key. */
  state: PlanUsageState | null;
  raw: JsonObject;
}

/** A plan's full usage reading (`connection.usage()`). */
export interface PlanUsage extends PlanUsageSummary {
  /** The connection's id (`credential:<id>` for one connected in the app). */
  connection: string;
  /** The plan's provider: `anthropic` (a Claude plan) or `openai` (a ChatGPT plan). */
  integration: string | null;
  plan: Plan | null;
  windows: PlanWindow[];
  nextSteps: PlanNextStep[];
  source: "provider" | "harness" | null;
}

function toPlan(value: unknown): Plan | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  return {
    tier: str(raw.tier),
    label: str(raw.label),
    runs: Array.isArray(raw.runs) ? raw.runs.map(String) : [],
    refusal: str(raw.refusal),
    raw,
  };
}

function toPlanWindow(value: unknown): PlanWindow | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  return {
    kind: String(raw.kind ?? "other"),
    label: String(raw.label ?? ""),
    models: Array.isArray(raw.models) ? raw.models.map(String) : [],
    used: num(raw.used) ?? 0,
    left: num(raw.left) ?? 0,
    resetsAt: parseTime(raw.resets_at),
    state: String(raw.state ?? "ok"),
    raw,
  };
}

function toPlanUsageSummary(value: unknown): PlanUsageSummary | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  return {
    state: (str(raw.state) ?? "unknown") as PlanUsageState,
    tightest: toPlanWindow(raw.tightest),
    availableAt: parseTime(raw.available_at),
    asOf: parseTime(raw.as_of),
    raw,
  };
}

function toPlanNextStep(value: unknown): PlanNextStep {
  const raw = asObject(value);
  const c = raw.connection && typeof raw.connection === "object" ? (raw.connection as JsonObject) : null;
  return {
    kind: String(raw.kind ?? ""),
    label: String(raw.label ?? ""),
    until: parseTime(raw.until),
    connection: c
      ? { id: String(c.id ?? ""), name: String(c.name ?? ""), integration: str(c.integration), credentialType: str(c.credential_type) }
      : null,
    pays: (str(raw.pays) as PlanNextStep["pays"]) ?? null,
    state: (str(raw.state) as PlanUsageState | null) ?? null,
    raw,
  };
}

function toPlanUsage(value: unknown): PlanUsage {
  const raw = asObject(value);
  const summary = toPlanUsageSummary(raw)!;
  return {
    ...summary,
    connection: String(raw.connection ?? ""),
    integration: str(raw.integration),
    plan: toPlan(raw.plan),
    windows: asList(raw.windows).map(toPlanWindow).filter((w): w is PlanWindow => w !== null),
    nextSteps: asList(raw.next_steps).map(toPlanNextStep),
    source: (str(raw.source) as PlanUsage["source"]) ?? null,
  };
}

/** A short-lived OAuth access token (never a refresh token or API key). */
export interface Token {
  accessToken: string;
  tokenType: string | null;
  expiresAt: Date | null;
  raw: JsonObject;
}

export interface LookupOption {
  value: unknown;
  label: string | null;
  raw: JsonObject;
}

/** A page of options; pass `nextPageToken` back as `pageToken`. */
export interface LookupOptions {
  options: LookupOption[];
  nextPageToken: string | null;
}

/**
 * `pending` until an account is connected, `disconnected` once it's revoked. A pending connection
 * still runs the operations whose `needsAccount` is false, on NoClick's key.
 */
export type ConnectionStatus = "pending" | "connected" | "disconnected";

/**
 * `app`: a service whose operations are tools. `model`: a model provider (`anthropic`, `openai`,
 * `openrouter`, ...) whose connection an agent names as its `modelConnection`, never in `tools`.
 */
export type IntegrationKind = "app" | "model";

/** A service in the catalog (`Connection.integrations()`), such as `gmail`, or a model provider such as `anthropic`. */
export interface IntegrationInfo {
  name: string;
  label: string | null;
  kind: IntegrationKind;
  /**
   * Whether its connect link also offers signing in with the provider's plan (a Claude or ChatGPT
   * subscription) instead of pasting a key, signed in by the person it belongs to.
   */
  subscription: boolean;
  /**
   * How a person connects an account: `"oauth"` (signing in), `"key"` (pasting a key or token),
   * `"qr"` (scanning a code) or `"purchase"` (a phone number, bought rather than connected).
   */
  connectWith: string[];
  operationCount: number | null;
  /**
   * How many of its operations need no account (0 for most): `run` and `tools` run them on
   * NoClick's key by the integration's name (`"exa.search"`), with no connection.
   */
  accountFreeOperationCount: number;
  /** The exact credential types: the `credentialType` that `Connection.create` and `connection.import` take. */
  credentialTypes: string[];
  /**
   * The app events an `OnEvent` trigger takes from it (`connection.events()` has their filters).
   * Empty for one that only acts: nothing it does wakes an agent.
   */
  events: string[];
  raw: JsonObject;
}

/** One operation of an integration, with its JSON-schema `parameters`. */
export interface IntegrationOperation {
  name: string;
  description: string | null;
  parameters: JsonObject;
  /** A hint from the operation's name (reads start with `list_`, `get_` and the like), not a guarantee. */
  readOnly: boolean | null;
  scopes: string[];
  /**
   * False when it runs on NoClick's key with no account at all (web search, public data), so it runs
   * with no connection (`"exa.search"`) and on a pending one; true otherwise, including when the need
   * depends on its arguments.
   */
  needsAccount: boolean;
  raw: JsonObject;
}

/**
 * An app event an integration can deliver to an agent's `OnEvent` trigger or a channel's subscription:
 * its name (`channel_message`, `contact_created`), what it means, and the filters that narrow it, each
 * with what it matches (one marked `Required.` must be given).
 */
export interface IntegrationEvent {
  name: string;
  description: string | null;
  filters: Record<string, string>;
  /**
   * What its data holds: each field's type (`"string"`, `"integer"`, `"boolean"`, `"null"`, an object, `[...]` for a
   * list), as the event has reached your account. Null until one has. Another account's events never show here.
   */
  shape: JsonObject | null;
  /** That shape with a placeholder for each value: what `subscription.test()` sends as `data`. Null with `shape`. */
  sample: JsonObject | null;
  raw: JsonObject;
}

function toIntegrationInfo(row: JsonObject): IntegrationInfo {
  return {
    name: String(row.name),
    label: str(row.label),
    kind: row.kind as IntegrationKind,
    subscription: row.subscription === true,
    connectWith: Array.isArray(row.connect_with) ? row.connect_with.map(String) : [],
    operationCount: num(row.operation_count),
    accountFreeOperationCount: requiredNumber(row, "account_free_operation_count"),
    credentialTypes: Array.isArray(row.credential_types) ? row.credential_types.map(String) : [],
    events: Array.isArray(row.events) ? row.events.map(String) : [],
    raw: row,
  };
}

function toIntegrationOperation(op: JsonObject): IntegrationOperation {
  return {
    name: String(op.name),
    description: str(op.description),
    parameters: asObject(op.parameters),
    readOnly: typeof op.read_only === "boolean" ? op.read_only : null,
    scopes: Array.isArray(op.scopes) ? op.scopes.map(String) : [],
    needsAccount: op.needs_account !== false,
    raw: op,
  };
}

/** Where a connect link is delivered (by email only): the user, an email, or the wire dict. */
export type SendTo = "user" | "owner" | true | string | JsonObject;

function toVerification(value: unknown): Verification | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  return {
    reachable: typeof raw.reachable === "boolean" ? raw.reachable : null,
    samples: Array.isArray(raw.samples) ? raw.samples : [],
    message: str(raw.message),
    hint: str(raw.hint),
    noun: str(raw.noun),
    total: typeof raw.total === "number" ? raw.total : null,
    accountLabel: str(raw.account_label),
    proves: str(raw.proves),
    error: str(raw.error),
    raw,
  };
}

function toShared(value: unknown): ConnectionShared | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  const by = asObject(raw.by ?? {});
  return { with: raw.with === "workspace" ? "workspace" : "you", byName: str(by.name), byEmail: str(by.email), raw };
}

function toHealth(value: unknown): ConnectionHealth | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  return { healthy: raw.healthy === true, status: str(raw.status) ?? "", hint: str(raw.hint), raw };
}

/** @internal An integration name from a string or an `IntegrationInfo`. */
export function integrationName(integration: string | { name: string } | undefined | null): string | undefined {
  if (integration === undefined || integration === null) return undefined;
  return typeof integration === "string" ? integration : integration.name;
}

/** @internal Connect links are delivered by email only, so a phone alone is refused. */
export function normalizeSendTo(sendTo: SendTo | undefined | null): JsonObject | undefined {
  if (sendTo === undefined || sendTo === null) return undefined;
  if (sendTo === "user" || sendTo === true) return { user: true };
  if (sendTo === "owner") return { owner: true };
  if (typeof sendTo === "string" && sendTo.includes("@")) return { email: sendTo };
  const phoneOnly =
    typeof sendTo === "string" ? sendTo.startsWith("+") : Boolean(sendTo.phone) && !sendTo.email && !sendTo.user;
  if (phoneOnly) {
    throw new InvalidRequest("Connect links are delivered by email only, and this person has only a phone number.", {
      nextStep: "Pass an email, or send the link's url yourself.",
    });
  }
  if (typeof sendTo === "object") return sendTo;
  throw new TypeError(`sendTo must be "user", "owner", an email or an object, not ${JSON.stringify(sendTo)}`);
}

export interface LinkOptions {
  redirectUrl?: string;
  reason?: string;
  /** Also deliver the link: "user", "owner" (your account's owner), an email, or an object. */
  sendTo?: SendTo;
}

/** @internal */
export function linkBody(options: LinkOptions): JsonObject {
  return compact({ redirect_url: options.redirectUrl, reason: options.reason, send_to: normalizeSendTo(options.sendTo) });
}

/** `api` for a named connection, `app` for an account connected in the NoClick app. */
export type ConnectionOrigin = "api" | "app";
/** Your account's access to a connection: its own, or shared with it to edit or to use. */
export type ConnectionAccess = "owner" | "edit" | "view";

interface ConnectionFilters {
  integration?: string | { name: string };
  origin?: ConnectionOrigin;
  /** Adds everything else the app keeps (`inAppOnly`: an agent's environment variables, an MCP server's key, a plan
   *  shared with your account), as its Connections page lists them. */
  includeInAppOnly?: boolean;
  /** A team workspace you're in (its id): read there, where those shared with that team are listed too. */
  organizationId?: string;
}

/** Where a connection is used: a team workspace you're in (its id), where one shared with that team is reached. */
export interface InWorkspace {
  organizationId?: string;
}

function connectionQuery(options: ConnectionFilters): Record<string, string | undefined> {
  return {
    integration: integrationName(options.integration), origin: options.origin, organization_id: options.organizationId,
    include_in_app_only: options.includeInAppOnly ? "true" : undefined,
  };
}

export interface ConnectionCreateOptions extends LinkOptions, CallOptions {
  /** Its integration: a name (`"gmail"`) or an `IntegrationInfo`. */
  integration?: string | { name: string };
  credentialType?: string;
  /** A credential you hold: the connection holds it at once (validated and probed first). */
  data?: JsonObject;
  /**
   * `"app"` saves an account connected in the app instead, as the app's own forms do: your account's own
   * (`credential:<id>`), its `credentialType` and `data` both given, named as you like, judged and proven first. An
   * agent's environment variables and an MCP server's key are saved this way too.
   */
  origin?: "app";
  /** With `origin: "app"`, the server an MCP server's key is for. */
  serverUrl?: string;
}

/**
 * A named connection to an account on another service. Secrets never come
 * back; `token()` mints an OAuth access token (`credentials:token` scope).
 * `status` is `pending` until someone connects an account at `connectUrl`,
 * `connected` after, and `disconnected` once it's revoked (`connectLink()`
 * mints a link to reconnect it).
 *
 * The accounts connected in the NoClick app are connections too, in your
 * account's own scope: `origin` is `"app"` and the id is `credential:<id>`
 * (their name is the app's, so refer to them by id). They run, look up,
 * verify and take `requireApproval` like any connection, and an account agent
 * takes one as a tool (the `Connection`, or `"credential:<id>"`,
 * `"credential:<id>.operation"`; a user's agent can't); the app connects
 * them, and `delete()` removes one as the app does. A connect link
 * (`connectLink()`, `request()`) reconnects one in place: a key typed there
 * replaces its own in the same credential, so everything using it keeps
 * working; its owner makes the link, or someone it's shared with to edit. One
 * shared with your account has `access` `"view"` or `"edit"`: it runs, but its
 * token, approval rules and deletion stay its owner's.
 * A Claude or ChatGPT plan you signed in to in the app is one too, an account
 * agent's `modelConnection`; a plan shared with you, or filled in by someone
 * else, isn't.
 *
 * One a teammate shared with a team workspace you're in is that team's to use,
 * in its workspace only: name the workspace (`organizationId`) to list, find
 * and run it there. A connection read in a team workspace carries it
 * (`organizationId`), and everything it does goes there, as the team's work.
 */
export class Connection extends ApiObject {
  private _createWith: JsonObject | null = null;
  /**
   * The integration `fromName` was given: the catalog the discovery methods read without loading.
   * Never reported as `integration`, which an existing connection of that name may not share.
   */
  private _integrationHint: string | null = null;
  /** What `fromName` says the connection is (its integration, credential type): checked once it's found. */
  private _identity: JsonObject = {};

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _of(init: ObjectInit): Connection {
    return new Connection(init);
  }

  /**
   * Create a connection called `name` (unique per user; a duplicate throws
   * `Conflict` with `existingId`). With `data` it holds that credential at
   * once; without, it's pending and `connectUrl` is where someone connects it.
   * With `allowExisting: true` a taken name returns the connection already there, as it is: its
   * credential isn't replaced and no link is made. One of another integration still throws the `Conflict`.
   */
  static async create(name: string, options: ConnectionCreateOptions & AllowExisting = {}): Promise<Connection> {
    const scope = resolveScope(options.user);
    const integration = integrationName(options.integration);
    const json = compact({
      name, integration, credential_type: options.credentialType, data: options.data, origin: options.origin,
      server_url: options.serverUrl, ...linkBody(options),
    });
    const raw = await createNamed("/v1/connections", json, { allowExisting: options.allowExisting, user: scope, client: options.client });
    if (options.allowExisting) checkUnchanged("connection", raw, { integration, credential_type: options.credentialType });
    return new Connection({ raw, client: options.client, user: scope });
  }

  /**
   * Sign your account in to an app. With `code`: finish a sign-in whose authorize step a page of yours ran, the
   * provider having handed its callback that code for `redirectUri` (one it has registered for that page), with the
   * PKCE `codeVerifier` the page made where the provider takes one. Without one: start a sign-in that finishes on the
   * provider's page, an agent plan's (`"codex"` for ChatGPT, `"claude_code"`, `"github_copilot"`, `"xai"`) or a
   * provider's device code. The provider's own sign-in runs, as the NoClick app's does, and stores the account's
   * credential (`credential:<id>`); `inputs` carries what its connect form takes beside the code (a shop, a
   * subdomain, a site), `oauthApp` an OAuth app of your own the sign-in ran on, `reconnect` a connection a Claude
   * plan's sign-in renews in place. An MCP server's sign-in is `"mcp"`, with an integration's MCP `credentialType`
   * (`"canva_mcp"`) or any server's `serverUrl`, and the `redirectUri` of your page its callback returns to: it waits
   * on that callback (`authorizeUrl`; `finish` with its `code` and `state`), or on a key the server takes instead
   * (`way` `key`; `finish(null, { apiKey })`). WhatsApp's is `"whatsapp"`: a QR (`qrCode`, a PNG in base64) the person
   * scans with their phone, which `finish()` (or `wait()`) asks about, answering the code WhatsApp rotated to
   * meanwhile; `reconnect` re-scans into a number whose link ended. A connect link (`connectLink()`) runs the whole
   * sign-in on NoClick's page instead, and is how one of your users signs in: this is your account's own. A code the
   * provider refuses throws `InvalidRequest` in its words.
   */
  static async signIn(provider: string, options: SignInOptions = {}): Promise<SignIn> {
    const user = resolveScope(undefined);
    const json = compact({
      provider, code: options.code, redirect_uri: options.redirectUri, code_verifier: options.codeVerifier,
      scopes: options.scopes, name: options.name, inputs: options.inputs, client: options.oauthApp,
      reconnect: options.reconnect, credential_type: options.credentialType, server_url: options.serverUrl,
    });
    // WhatsApp's start can wait about a minute for its linking service to show a QR.
    const timeoutMs = provider === "whatsapp" ? QR_START_TIMEOUT_MS : undefined;
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/connections/sign_ins", { json, user, timeoutMs }));
    return new SignIn(raw, options.client, user);
  }

  /**
   * Finish a sign-in that waits on the person by its `id` alone, as its answer may come back in another request than
   * the one that started it: the `id` of the choice they picked (`choose`), the `code` they copied from the
   * provider's page (a Claude plan) or the `code` and `state` an MCP sign-in's callback got, the `apiKey` an MCP server
   * takes in place of a sign-in, or nothing, to ask whether they've signed in (a device code). One finished, lapsed
   * or another account's throws `NotFound`.
   */
  static async finishSignIn(signInId: string, choice?: string | null,
                            options: { code?: string; state?: string; apiKey?: string; client?: NoClick } = {}): Promise<SignIn> {
    const user = resolveScope(undefined);
    const raw = asObject(await resolveClient(options.client).request(
      "POST", `/v1/connections/sign_ins/${encodeURIComponent(signInId)}/finish`,
      { json: compact({ choice: choice ?? undefined, code: options.code, state: options.state, api_key: options.apiKey }), user }));
    return new SignIn(raw, options.client, user);
  }

  /**
   * A lazy reference to the connection called `name` in the current (or
   * given) user. With `createIfMissing` it's created on first use, for
   * `integration`: holding `data` when given (a key you hold), pending with a
   * connect link otherwise. An existing connection is used as it is: `data` and the link options apply
   * only when it's created. `integration` and `credentialType` say what the connection is, so they're
   * checked, with or without `createIfMissing`: one of another integration or credential type throws
   * `Conflict` naming it. Given `integration`, `operations()`, `operation()` and `events()` read the
   * catalog without loading or creating the connection.
   */
  static fromName(name: string, options: ConnectionCreateOptions & { createIfMissing?: boolean } = {}): Connection {
    const integration = integrationName(options.integration);
    const connection = new Connection({ hints: { name }, client: options.client, user: options.user });
    connection._integrationHint = integration ?? null;
    connection._identity = { integration, credential_type: options.credentialType };
    if (options.createIfMissing) {
      if (!options.integration && !options.credentialType) {
        throw new TypeError('Connection.fromName(..., { createIfMissing: true }) needs integration');
      }
      connection._createWith = compact({
        name,
        integration,
        credential_type: options.credentialType,
        data: options.data,
        ...linkBody(options),
      });
    }
    return connection;
  }

  /**
   * A lazy reference by NoClick id; `credential:<id>` for an account connected in the app. `organizationId` names a
   * team workspace you're in, where one shared with that team is used.
   */
  static fromId(connectionId: string, options: CallOptions & InWorkspace = {}): Connection {
    return new Connection({ hints: compact({ id: connectionId, organization_id: options.organizationId }), client: options.client, user: options.user });
  }

  /** The connection with this id or name; in `organizationId`, a team workspace you're in, one shared with that team. */
  static async get(ref: string, options: CallOptions & InWorkspace = {}): Promise<Connection> {
    return await new Connection({ hints: compact({ ref, organization_id: options.organizationId }), client: options.client, user: options.user }).hydrate();
  }

  /**
   * The current user's connections (the account's own outside `asUser`), or those `userFilter` covers:
   * named ones newest first, then, in the account's own scope, the accounts connected in the app; `includeInAppOnly`
   * adds everything else the app keeps there (`inAppOnly`), as its Connections page lists them.
   * `origin` keeps only `"api"` or `"app"` ones; `organizationId` reads in a team workspace you're in, where those
   * shared with that team are listed too (and each runs there).
   *
   *     const fromTheApp = await Connection.list({ origin: "app" });
   *     const theTeams = await Connection.list({ organizationId: "5c0d9e4a-7b1f-4e2a-9c3d-8f6b2a1e4d70" });
   */
  static async list(
    options: ReadOptions & ConnectionFilters & { limit?: number } = {},
  ): Promise<Connection[]> {
    return await listAll(
      { ...options, path: "/v1/connections", query: connectionQuery(options) },
      (raw, user) => new Connection({ raw, client: options.client, user }),
    );
  }

  /** One page of connections; pass `nextCursor` back as `cursor`. */
  static async listPage(
    options: ReadOptions & PageOptions & ConnectionFilters = {},
  ): Promise<Page<Connection>> {
    return await listPage(
      { ...options, path: "/v1/connections", query: connectionQuery(options) },
      (raw, user) => new Connection({ raw, client: options.client, user }),
    );
  }

  /**
   * The services a connection can be made to and the model providers agents think with: every
   * integration, or those whose name or label contains `query` (case-insensitive), each with how a
   * person connects it (`connectWith`), how many of its operations run with no account, by its
   * name (`accountFreeOperationCount`), and the app events an `OnEvent` trigger takes from it
   * (`events`, empty for one that only acts). `kind: "model"` keeps the model providers an agent's
   * `modelConnection` names; `kind: "app"` the services whose operations are tools.
   *
   *     const [crm] = await Connection.integrations("hubspot");
   *     const hubspot = Connection.fromName("crm", { integration: crm, createIfMissing: true });
   *     const [tiktok] = await Connection.integrations("tiktok");
   *     console.log(tiktok.events);   // [] : it publishes, and no OnEvent hears it
   *     const providers = await Connection.integrations(undefined, { kind: "model" });
   */
  static async integrations(query?: string, options: { kind?: IntegrationKind; client?: NoClick } = {}): Promise<IntegrationInfo[]> {
    const page = await resolveClient(options.client).request("GET", "/v1/integrations", { query: { q: query, kind: options.kind }, user: null });
    return asList(page).map((row) => toIntegrationInfo(asObject(row)));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** Its integration (`"gmail"`); `null` for what the app keeps that is no app's account (`inAppOnly`). */
  get integration(): string | null {
    return this._field<string | null | undefined>("integration") ?? null;
  }
  get credentialType(): string | null {
    return this._field("credential_type");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get status(): ConnectionStatus {
    return this._field("status");
  }
  get connected(): boolean {
    return this.status === "connected";
  }
  get origin(): ConnectionOrigin {
    return this._field("origin");
  }
  /**
   * Kept in the NoClick app for its steps, never a connection: an agent's environment variables, an MCP server's key,
   * a plan shared with your account. It's listed, read, renamed and deleted, but never runs, is never checked, and
   * names nothing as an agent's or a step's connection.
   */
  get inAppOnly(): boolean {
    return this._field<unknown>("in_app_only") === true;
  }
  get access(): ConnectionAccess {
    return this._field("access");
  }
  /** How one connected in the app and shared with your account reaches it, and who shared it; `null` for your own
   *  and for a named connection. */
  get shared(): ConnectionShared | null {
    return toShared(this.raw.shared);
  }
  /** The provider's live word on a linked session (a WhatsApp number's, a Discord install's), read with the
   *  connection; `null` where there's nothing to ask or no telling. */
  get health(): ConnectionHealth | null {
    return toHealth(this.raw.health);
  }
  /** The team workspace it was read in (`organizationId`), where it runs; `null` in your account's own. */
  get organizationId(): string | null {
    return this._field<string | null | undefined>("organization_id") ?? null;
  }
  /** Operations its owner approves call by call wherever it runs (`*`: all); `requireApproval` adds to them and
   *  `liftApproval` lifts them. */
  get approvalOperations(): string[] {
    const ops = this._field<unknown>("approval_operations");
    return Array.isArray(ops) ? ops.map(String) : [];
  }
  /**
   * The account it reaches, as the app's Connections list names it: its login, else its email, else who a
   * check verified it as, else the number it links; an agent's environment variables by their names, an MCP server's
   * key by its server's host; `null` when none is known.
   */
  get account(): string | null {
    return this._field("account");
  }
  /** An agent's environment variables by name (never their values); `null` for anything else. */
  get variables(): string[] | null {
    const names = this._field<unknown>("variables");
    return Array.isArray(names) ? names.map(String) : null;
  }
  /** The MCP server an MCP sign-in is for; `null` for anything else (a server's key gives its host as `account`, since
   *  its address may carry a secret). */
  get serverUrl(): string | null {
    return this._field<string | null | undefined>("server_url") ?? null;
  }
  /**
   * The id of the account it holds, as a workflow step's `connections` names it, so a step's account is matched to
   * its connection; `null` while none is connected.
   */
  get credentialId(): string | null {
    return this._field<string | null | undefined>("credential_id") ?? null;
  }
  /** Whether it's a test account, which an app's preview writes through as well as reads. */
  get testAccount(): boolean {
    return this._field<unknown>("test_account") === true;
  }
  /**
   * What holds it: agents (in their tools, as their `modelConnection`, given it by their user, or with a trigger on
   * it), channels and workspaces subscribed to its events, hosted MCP servers with it in their tools, apps that bind
   * it (with the `binding` name) or whose code made it, numbers connected through it, and the automations whose steps
   * use its account (`workflow`: yours, and for an account yours owns, those in its workspace), each with whose it is.
   */
  get usedBy(): ConnectionHolder[] {
    const rows = this._field<unknown>("used_by");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((u) => ({
      kind: str(u.kind) ?? "agent", id: str(u.id) ?? "", name: str(u.name) ?? "", userId: str(u.user_id),
      binding: str(u.binding), marks: Array.isArray(u.marks) ? u.marks.map(String) : [],
    }));
  }
  /** The open link where someone connects (or reconnects) the account, if one is open. */
  get connectUrl(): string | null {
    const link = this.raw.connect_link;
    return link && typeof link === "object" ? str((link as JsonObject).url) : null;
  }
  get verification(): Verification | null {
    return toVerification(this.raw.verification);
  }
  /** A Claude or ChatGPT plan's tier and what it runs; null for any other connection. */
  get plan(): Plan | null {
    return toPlan(this.raw.plan);
  }
  /** A plan's usage over every window, as last read; null until a reading exists (and for any other connection). */
  get usageSummary(): PlanUsageSummary | null {
    return toPlanUsageSummary(this.raw.usage);
  }
  get connectedAt(): Date | null {
    return parseTime(this._field("connected_at"));
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  get updatedAt(): Date | null {
    return parseTime(this._field("updated_at"));
  }
  /** This connection's kind in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    return this._api.consoleUrl("resources", "connections");
  }

  /** @internal Its id once known, else the ref or name it was named by (`Human.ask`'s `pick` sends it). */
  get _ref(): string {
    return String(this._known("id") ?? this._hints.ref ?? this._hints.name);
  }

  private get path(): string {
    return `/v1/connections/${encodeURIComponent(this._ref)}`;
  }

  /** @internal Every call on the connection goes to the team workspace it was read in (`organizationId`). */
  override _request<T = unknown>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const organizationId = this._known("organization_id");
    if (typeof organizationId !== "string" || !path.startsWith("/v1/connections/")) return super._request<T>(method, path, options);
    return super._request<T>(method, path, { ...options, query: { ...options.query, organization_id: organizationId } });
  }

  protected async _load(): Promise<JsonObject> {
    let found: JsonObject | undefined;
    try {
      found = await this._request<JsonObject>("GET", this.path);
    } catch (err) {
      if (!(err instanceof NotFound) || !this._createWith) throw err;
    }
    if (found) return this.checked(found);
    try {
      return await this._request<JsonObject>("POST", "/v1/connections", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return this.checked(await this._request<JsonObject>("GET", `/v1/connections/${err.existingId}`));
    }
  }

  /** The connection `fromName` found, once it's what its `integration` and `credentialType` said. */
  private checked(raw: JsonObject): JsonObject {
    checkUnchanged("connection", raw, this._identity);
    return raw;
  }

  /**
   * Act by id or name with no read first. A lazy `createIfMissing` connection
   * is created first: a write creates it outright (a name already taken is
   * simply used), a use reads it first.
   */
  private async act<T = unknown>(
    method: string,
    suffix: string,
    json?: JsonObject,
    write = false,
    query?: Record<string, string | undefined>,
  ): Promise<T> {
    if (!this._raw && this._createWith) {
      if (write) {
        try {
          this._raw = await this._request<JsonObject>("POST", "/v1/connections", { json: this._createWith });
        } catch (err) {
          if (!(err instanceof Conflict) || !err.existingId) throw err;
          this._raw = this.checked(await this._request<JsonObject>("GET", `/v1/connections/${err.existingId}`));
        }
        this._createWith = null;
      } else {
        await this._ensure();
      }
    }
    return await this._request<T>(method, `${this.path}${suffix}`, { ...(json === undefined ? {} : { json }), ...(query ? { query } : {}) });
  }

  /**
   * A tool ref to some of its operations, for `tools` (`gmail.only("send_email_message")`);
   * a lazy `createIfMissing` connection is still created first.
   */
  only(...operations: string[]): ConnectionOperations {
    if (!operations.length) throw new TypeError("only() takes at least one operation name");
    return new ConnectionOperations(this, operations);
  }

  /**
   * One of its repositories (`owner/name` on its git host; a `github` connection) checked out in an
   * agent's workspace, for `Agent` `repos`: cloned into `/workspace/<path>` (the repository's name
   * when omitted) at a conversation's first turn. The agent's git reaches that repository only,
   * through NoClick, with a key made for its sandbox; the connection's own token never enters it.
   * `push` is the branches it may push to, as globs: NoClick refuses a push to any other ref, and
   * without it the checkout is read-only. `gh` only reads it; give the agent the connection's
   * operations for pull requests and issues. Sends nothing.
   *
   *     const github = Connection.fromName("github", { integration: "github", createIfMissing: true });
   *     const repos = [github.checkout("acme/docs", { push: "noclick/*" })];
   */
  checkout(repository: string, options: CheckoutOptions = {}): RepoCheckout {
    return new RepoCheckout({ repository, connection: this }, options);
  }

  /** @internal Its ref for tools or repos that run in `scope`: its name there, else `connection:<id>`. */
  async _refIn(scope: UserRef | null): Promise<string> {
    return await connectionRef(this, scope);
  }

  /**
   * A new link where someone connects (or reconnects) this connection's
   * account; `await link.wait()` resolves to the connected `Connection`. The
   * connection's own `connectUrl` is now this link's. On an account connected in
   * the app (`credential:<id>`), a key typed there goes into that same
   * credential, once, before the link expires; one shared with you to use
   * throws `PermissionDenied`.
   */
  async connectLink(options: LinkOptions = {}): Promise<ConnectLink> {
    const body = linkBody(options);
    const payload = asObject(await this.act("POST", "/connect_links", body, true));
    const link = ConnectLink._fromLink(payload, { client: this._client, user: this._callScope() });
    if (this._raw) {
      // The newest open link is the connection's (as its next read would say); unloaded, that read says it.
      this._raw = { ...this._raw, connect_link: {
        id: payload.id ?? null, url: link.url, expires_at: payload.expires_at ?? null, operation_id: link._known("id") ?? null,
      } };
    }
    return link;
  }

  /**
   * Ask the user (or `sendTo`) to connect it; `await link.wait()` resolves to the `Connection`. A
   * connection of your account's own has no user: send it to `"owner"` (your account's owner) or an email.
   */
  async request(options: LinkOptions = {}): Promise<ConnectLink> {
    return await this.connectLink({ ...options, sendTo: options.sendTo ?? "user" });
  }

  /**
   * Resolve once an account is connected (at once when it is). It follows the
   * connection, not one link: an account connected through any of its links
   * ends the wait, and a link that lapses after a fresh one was made
   * (`connectLink()` or `request()`, from anywhere) hands the wait to the fresh
   * one. Throws `OperationExpired` when the open link lapses with no fresh one,
   * or `OperationTimeout` after `timeoutS` seconds.
   */
  async wait(options: { timeoutS?: number } = {}): Promise<this> {
    const deadline = options.timeoutS === undefined ? null : Date.now() + options.timeoutS * 1000;
    let raw = await this._ensure();
    let lapsed: NoClickError | null = null;
    while (raw.status !== "connected") {
      const link = raw.connect_link && typeof raw.connect_link === "object" ? (raw.connect_link as JsonObject) : null;
      if (!link) {
        if (lapsed) throw lapsed;
        throw new InvalidRequest(`The '${String(raw.name)}' connection has no open connect link to wait on.`, {
          nextStep: "Create one with connection.connectLink() and send it to the user.",
        });
      }
      const remaining = deadline === null ? null : (deadline - Date.now()) / 1000;
      const windowS = remaining === null ? LONG_POLL_S : Math.max(0, Math.min(LONG_POLL_S, remaining));
      try {
        await Operation.fromId(String(link.operation_id), { client: this._client, user: this._callScope() })
          .wait({ timeoutS: windowS });
      } catch (err) {
        if (err instanceof OperationTimeout) {
          if (remaining !== null && remaining <= LONG_POLL_S) throw err;
        } else if (err instanceof OperationExpired || err instanceof OperationCanceled) {
          lapsed = err; // this link ended unused; the connection says what's open now
        } else {
          throw err;
        }
      }
      raw = this._raw = await this._load();
    }
    return this;
  }

  /** Replace the connection's credential with one you hold (a rotated key), validated first. An account connected in
   *  the app keeps its id and its kind: its owner, or someone it's shared with to edit, gives it the new key in place. */
  async import(data: JsonObject, options: { credentialType?: string } = {}): Promise<this> {
    this._raw = await this.act<JsonObject>("POST", "/import", compact({ data, credential_type: options.credentialType }), true);
    return this;
  }

  /** The catalog path of its integration: the loaded one, else the one it was named with, else loading it to learn it. */
  private async integrationPath(): Promise<string> {
    const known = this._known("integration");
    const integration = typeof known === "string" && known ? known : (this._integrationHint ?? String((await this._ensure()).integration));
    return `/v1/integrations/${encodeURIComponent(integration)}`;
  }

  /**
   * What its integration can do: every operation, or those whose name or description contains
   * `search` (case-insensitive), with parameter schemas and whether each `needsAccount`.
   */
  async operations(options: { search?: string } = {}): Promise<IntegrationOperation[]> {
    const page = await this._request("GET", `${await this.integrationPath()}/operations`, { query: { q: options.search }, user: null });
    return asList(page).map((op) => toIntegrationOperation(asObject(op)));
  }

  /** One of its integration's operations; throws `NotFound` for a name it doesn't have. */
  async operation(name: string): Promise<IntegrationOperation> {
    const path = `${await this.integrationPath()}/operations/${encodeURIComponent(name)}`;
    return toIntegrationOperation(asObject(await this._request("GET", path, { user: null })));
  }

  /** The app events its integration can wake an agent with, for `OnEvent` (what it pushes as it happens, never a poll). */
  async events(): Promise<IntegrationEvent[]> {
    const response = await this._request("GET", `${await this.integrationPath()}/events`, { user: null });
    return asList(response).map((row) => asObject(row)).map((row) => ({
      name: str(row.name) ?? "",
      description: str(row.description),
      filters: Object.fromEntries(Object.entries(asObject(row.filters)).map(([k, v]) => [k, String(v)])),
      shape: row.shape && typeof row.shape === "object" ? (row.shape as JsonObject) : null,
      sample: row.sample && typeof row.sample === "object" ? (row.sample as JsonObject) : null,
      raw: row,
    }));
  }

  /**
   * Run one of the integration's operations in this account. Throws
   * `NeedsConnection` while pending (an operation whose `needsAccount` is
   * false runs anyway, on NoClick's key, or on your own key once connected, and needs no
   * connection at all through `run`) and `CredentialDisconnected` once
   * revoked (both carry `connectUrl`); a policy may throw `PolicyDenied` or `ApprovalRequired`.
   * Resolves to the operation's data (what the service answered); a service that refuses the call
   * throws `UpstreamError` in its own words, its HTTP status in `details.upstream_status`.
   */
  async run<R = unknown>(operation: string, args: JsonObject = {}, options: { approvalId?: string } = {}): Promise<R> {
    const response = await this.act("POST", `/operations/${operation}/run`, compact({ arguments: args, approval_id: options.approvalId }));
    const body = asObject(response);
    return ("result" in body ? body.result : response) as R;
  }

  /** The allowed values of an ID-like field (channels, repos, sheets) in this account. */
  async lookup(
    field: string,
    options: { arguments?: JsonObject; search?: string; pageToken?: string } = {},
  ): Promise<LookupOptions> {
    const args = options.arguments && Object.keys(options.arguments).length ? options.arguments : undefined;
    const response = asObject(await this.act("POST", "/lookup", compact({
      field, arguments: args, search: options.search, page_token: options.pageToken,
    })));
    return {
      options: (Array.isArray(response.options) ? (response.options as JsonObject[]) : []).map((opt) => ({
        value: opt.value,
        label: str(opt.label),
        raw: opt,
      })),
      nextPageToken: str(response.next_page_token),
    };
  }

  /**
   * A plan's usage, window by window (a connection that isn't a Claude or ChatGPT plan throws `InvalidRequest`).
   * `model` keeps the windows that can stop that model; `fresh` asks the provider when the last reading is a few
   * minutes old, else it's NoClick's last reading.
   *
   *     const usage = await plan.usage({ model: "claude-opus-5-5", fresh: true });
   *     if (usage.state === "used_up") console.log(`back at ${usage.availableAt}`);
   */
  async usage(options: { model?: string; fresh?: boolean } = {}): Promise<PlanUsage> {
    const query = { model: options.model, fresh: options.fresh ? "true" : undefined };
    return toPlanUsage(await this.act("GET", "/usage", undefined, false, query));
  }

  /**
   * Whether the account may use the provider's API at all, where a provider can refuse it after a sign-in (Google
   * Business Profile gives a new project no quota): `valid` (null where the provider couldn't say), the provider's
   * `error` and where to fix it (`helpUrl`). An integration with no such check answers valid.
   */
  async checkAccess(): Promise<{ valid: boolean | null; error: string | null; helpUrl: string | null }> {
    const answer = asObject(await this.act("POST", "/access"));
    return { valid: typeof answer.valid === "boolean" ? answer.valid : null, error: str(answer.error), helpUrl: str(answer.help_url) };
  }

  /**
   * The agent answering a WhatsApp number your account linked by QR code (a `"whatsapp"` sign-in), and whether your
   * account can put one on it. Linking a number makes no agent on its own.
   *
   *     console.log((await (await Connection.get("credential:...")).numberAgent()).name);
   */
  async numberAgent(): Promise<NumberAgent> {
    return toNumberAgent(await this.act("GET", "/agent"));
  }

  /**
   * Put NoClick's WhatsApp agent on a number your account linked by QR code, as the app offers it once a number is
   * linked: an agent from the WhatsApp template, in a channel of its own that opens asking you whom it answers. One
   * that already answers the number is kept (`created` false). Your account's owner or one of its own keys does this;
   * an agent or an MCP client makes one with `Agent.create` and the `whatsapp` template.
   *
   *     const made = await (await Connection.get("credential:...")).makeNumberAgent();
   */
  async makeNumberAgent(): Promise<NumberAgent> {
    return toNumberAgent(await this.act("POST", "/agent"));
  }

  /**
   * Re-check the account against the provider: its things as the provider sees them, who it signs in as, or its
   * refusal in its own words. Each check asks the provider, so an account makes at most 20 a minute
   * (`RateLimited` past them).
   */
  async verify(): Promise<Verification | null> {
    this._raw = asObject(await this.act("POST", "/verify"));
    return toVerification(this._raw.verification);
  }

  /**
   * Rename an account connected in the app (`origin` `app`): the name your account and the app see, which nothing
   * finds it by. Its owner renames it, or someone it's shared with to edit (`PermissionDenied` otherwise). A named
   * connection's name is how code finds it, so it isn't renamed (`InvalidRequest`).
   *
   *     await (await Connection.get("credential:...")).rename("Sales inbox");
   */
  async rename(name: string): Promise<this> {
    this._raw = asObject(await this.act("PATCH", "", { name }, true));
    return this;
  }

  /**
   * From now on its owner approves each call of these operations wherever it runs (your code, agents, the
   * app's workflows); `"*"` means every operation. It only adds to `approvalOperations` (`liftApproval`
   * lifts). On one shared with your account it throws `PermissionDenied`.
   *
   *     await Connection.fromName("gmail").requireApproval("send_email_message", "delete_message");
   */
  async requireApproval(...operations: string[]): Promise<this> {
    this._raw = asObject(await this.act("POST", "/require_approval", { operations }));
    return this;
  }

  /**
   * Let calls of these operations run without its owner's OK again: each named as `approvalOperations` names it,
   * or none to lift every one (`"*"` lifts the rule for every operation, leaving any named on their own). Signed in
   * as your account's owner it applies at once, and so it does from your agent (NoClick's assistant, or any agent of
   * yours) on a turn your own message started, recorded as yours; one a model makes on its own (a turn no message of
   * yours started, a connected app, a key used through MCP) waits for your approval. From a key it needs one naming
   * the `approvals:policy` scope (a key with every scope, `*`, holds it only when it's named too) and
   * `credentials:use`, and it waits a 10-minute undo window, in which `ApprovalPolicy.undo(change.id)` takes it back;
   * the owner is told. Requiring approval for one of them again meanwhile takes it back too. Returns the change it
   * made (`pending` while it waits, `effectiveAt` when it takes effect). `PermissionDenied` without the scope, for a
   * call acting for one of your users or an app's code, or on one shared with your account; `Conflict` when it asks
   * no approval, or a lift of the same operation already waits.
   *
   *     const [change] = await Connection.fromName("gmail").liftApproval("send_email_message");
   *     console.log(change.pending, change.effectiveAt);
   */
  async liftApproval(...operations: string[]): Promise<PolicyChange[]> {
    const query = operations.length ? { operations: operations.join(",") } : undefined;
    this._raw = asObject(await this.act("DELETE", "/require_approval", undefined, false, query));
    return asList(this._raw.approval_changes).map(policyChange);
  }

  /**
   * Mark it as a test account (or, with `false`, not one). An app's preview only reads through a connection;
   * through a test account it writes as well, as production does. Only the account that connected it marks
   * it (`PermissionDenied` on one shared with yours), and it must hold an account (`InvalidRequest` while
   * pending).
   *
   *     await Connection.fromName("slack-sandbox").markTestAccount();
   */
  async markTestAccount(testAccount = true): Promise<this> {
    this._raw = asObject(await this.act("POST", "/test_account", { test_account: testAccount }));
    return this;
  }

  /**
   * A fresh OAuth access token for calling the provider yourself (`credentials:token` scope). A model
   * provider's connection never hands out its key or plan token (`PermissionDenied`).
   */
  async token(): Promise<Token> {
    const raw = asObject(await this.act("POST", "/token"));
    return {
      accessToken: String(raw.access_token),
      tokenType: str(raw.token_type),
      expiresAt: parseTime(raw.expires_at),
      raw,
    };
  }

  /** Delete the connection, revoking its account at the provider where possible. */
  async delete(): Promise<void> {
    await this.act("DELETE", "", undefined, true);
  }
}

/** Some of a connection's operations as tools (`connection.only(...)`), with the arguments `bind(...)` fixed. */
export class ConnectionOperations {
  readonly connection: Connection;
  readonly operations: string[];
  /** The arguments NoClick fills on every call, out of the model's reach. */
  readonly bindings: JsonObject;

  constructor(connection: Connection, operations: string[], bindings: JsonObject = {}) {
    this.connection = connection;
    this.operations = operations;
    this.bindings = bindings;
  }

  /**
   * Fix arguments of these operations: a bound parameter leaves the tool's
   * schema, so the model never sees or sets it, and NoClick fills it on every call. A value may name
   * the user the call acts for: `{{user.id}}`, `{{user.email}}`, `{{user.name}}` or
   * `{{user.metadata.<key>}}`. A bound value always wins, over what a model passes through in an
   * operation's free-form parameters too; a tool whose binding can't be filled isn't offered that
   * turn. Policy judges the final arguments. Works in agents, toolkits and hosted MCP servers.
   *
   *     gmail.only("send_email_message").bind({ to: "{{user.email}}" })
   */
  bind(args: JsonObject): ConnectionOperations {
    return new ConnectionOperations(this.connection, [...this.operations], { ...this.bindings, ...boundArguments(args) });
  }
}

/**
 * Something holding a connection: an `agent`, a `channel` or `workspace` subscribed to its events, an `mcp_server`,
 * an app (`project`) or a number (`phone_number`) connected through it.
 */
export interface ConnectionHolder {
  kind: string;
  id: string;
  name: string;
  userId: string | null;
  /** The name an app binds it under (null for anything else). */
  binding: string | null;
  /** An automation's (`workflow`) steps' node types, by which the app draws it; empty for anything else. */
  marks: string[];
}

/**
 * A tool ref: a name, `"name.operation"`, a capability, a `Connection`, `connection.only(...)`, a
 * `Database` or `db.only(...)`. A name is a connection in the scope the tools run in, else an
 * integration's operations that need no account (on NoClick's key), so `"exa.search"` needs no connection.
 * An entry read back from `agent.tools` (`{ tool, bind }`, `{ human, tools }`) is taken as it is.
 */
export type ToolRef = string | Connection | ConnectionOperations | Database | DatabaseOperations | ToolSource | JsonObject;

/** @internal One entry of `tools` on the wire: a ref string, or an object for what a string can't say. */
export type WireTool = string | JsonObject;

/** @internal Anything else that says its own wire entries for `tools`, in the scope they run in. */
export interface ToolSource {
  _toolRefs(scope: UserRef | null): Promise<WireTool[]>;
}

function isToolSource(value: unknown): value is ToolSource {
  return typeof value === "object" && value !== null && typeof (value as { _toolRefs?: unknown })._toolRefs === "function";
}

/** A wire entry as `agent.tools` reads it back (`{ tool, bind }`, `{ human, tools }`), so tools round-trip. */
function isWireEntry(value: unknown): value is JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const entry = value as JsonObject;
  return (typeof entry.tool === "string" && typeof entry.bind === "object") || (typeof entry.human === "object" && Array.isArray(entry.tools));
}

/**
 * Its name where the tools run in its own scope; `connection:<id>` from another scope, another
 * user's or the account's.
 */
async function connectionRef(connection: Connection, scope: UserRef | null): Promise<string> {
  const raw = await connection._ensure();
  // One connected in the app goes by its id, `credential:<id>`.
  if (raw.origin === "app") return String(raw.id);
  if (connection._scope === scope) return String(raw.name);
  const same = (str(raw.user_id) ?? null) === (await userIdOf(scope));
  return same ? String(raw.name) : `connection:${String(raw.id)}`;
}

/**
 * @internal The wire refs for `tools` that run in `scope` (a user, or null for the account); a lazy
 * `createIfMissing` connection is created first, and one from another scope is `"connection:<id>"`.
 */
export async function toolRefs(
  tools: readonly ToolRef[] | { refs: readonly ToolRef[] } | undefined,
  options: { scope?: UserOption } = {},
): Promise<WireTool[] | undefined> {
  if (tools === undefined) return undefined;
  const scope = resolveScope(options.scope);
  const entries = Array.isArray(tools) ? tools : (tools as { refs: readonly ToolRef[] }).refs;
  const refs: WireTool[] = [];
  for (const tool of entries) {
    if (typeof tool === "string") refs.push(tool);
    else if (tool instanceof Connection) refs.push(await connectionRef(tool, scope));
    else if (tool instanceof ConnectionOperations) {
      refs.push(...toolEntries(await connectionRef(tool.connection, scope), tool.operations, tool.bindings));
    } else if (tool instanceof Database) refs.push(`database:${await refId(tool)}`);
    else if (isToolSource(tool)) refs.push(...(await tool._toolRefs(scope))); // db.only(...), a bucket, a person, ...
    else if (isWireEntry(tool)) refs.push(tool);
    else throw new TypeError(`A tool is a Connection, a Database or a name like "gmail" or "gmail.send_email_message", not ${JSON.stringify(tool)}`);
  }
  return refs;
}

/**
 * @internal The wire `model_connection` for an agent in `scope`: a name as given, or a `Connection` (a
 * lazy `createIfMissing` one is created first; one from another scope is `connection:<id>`, shared
 * under the rule for shared tools: only a key acting for the whole account may set it, and a
 * connection holding a person's plan is never shared; invite-only beta). `null` removes it in an update.
 */
export async function modelConnectionRef(connection: string | Connection | null | undefined, scope: UserOption): Promise<string | null | undefined> {
  if (connection === undefined || connection === null || typeof connection === "string") return connection;
  if (connection instanceof Connection) return await connectionRef(connection, resolveScope(scope));
  throw new TypeError(`modelConnection is a Connection or its name, not ${JSON.stringify(connection)}`);
}

/** `ref` when it names one operation, `"name.operation"` (the server splits at the first dot). */
function operationRef(ref: string): string {
  if (typeof ref !== "string") throw new TypeError(`run() takes a ref like "exa.search", not ${typeof ref}`);
  const dot = ref.indexOf(".");
  if (dot < 1 || dot === ref.length - 1) {
    throw new InvalidRequest(`run() runs one operation, named "name.operation"; ${JSON.stringify(ref)} names none.`, {
      nextStep: 'Name the connection or integration and the operation: "exa.search", "gmail.send_email_message".',
      details: { field: "ref" },
    });
  }
  return ref;
}

/**
 * Run one operation by its ref, `"name.operation"`, as `tools` names it. `name` is a connection in
 * the scope the call acts for (the user's, else the account's), else an integration whose operation
 * needs no account, which then runs on NoClick's key with no connection at all. A connection named
 * like the integration (`exa`, holding your own key) wins, so the same ref then runs on your key. An
 * account connected in the app is `"credential:<id>.operation"`.
 *
 * Throws like `connection.run`: `NeedsConnection` (or `CredentialDisconnected`) with `connectUrl`
 * when the connection has no working account, `InvalidRequest` when the operation needs an account
 * and no connection has that name, `NotFound` when `name` is neither a connection nor an
 * integration, `PolicyDenied` or `ApprovalRequired` (retry with its `approvalId` once
 * `err.operation.wait()` resolves to true), and `UpstreamError` when the service refuses the call
 * (its own words, its HTTP status in `details.upstream_status`). Resolves to the operation's data.
 *
 *     const results = await run("exa.search", { query: "invoice automation for small businesses" });
 *     await run("gmail.send_email_message", { to: ["ana@example.com"], subject: "Hi", body: "..." }, { user: "user_42" });
 */
export async function run<R = unknown>(
  ref: string,
  args: JsonObject = {},
  options: CallOptions & { approvalId?: string } = {},
): Promise<R> {
  const response = await resolveClient(options.client).request("POST", "/v1/run", {
    json: compact({ ref: operationRef(ref), arguments: args, approval_id: options.approvalId }),
    user: options.user,
  });
  const body = asObject(response);
  if (!("result" in body)) throw new NoClickError("The response is missing `result`.", { details: { field: "result" } });
  return body.result as R;
}

const CONNECT_KINDS = ["credential.connect"] as const;

export interface SignInOptions {
  /** The code a redirect sign-in's callback handed back; without one, a sign-in that starts here starts. */
  code?: string;
  /** The redirect URI the authorize step named (with a code). */
  redirectUri?: string;
  /** The PKCE verifier the authorize step made, for a provider that takes one. */
  codeVerifier?: string;
  scopes?: string[] | string;
  /** The connection's name in the app. */
  name?: string;
  /** What the provider's connect form takes beside the code: a shop, a subdomain, a site. */
  inputs?: JsonObject;
  /** An OAuth app of your own the sign-in ran on. */
  oauthApp?: { client_id: string; client_secret: string };
  /** A connection a Claude plan's sign-in renews in place (`credential:<id>`). */
  reconnect?: string;
  /** An MCP sign-in (`"mcp"`): the integration's MCP credential type (`"canva_mcp"`); omitted with `serverUrl`. */
  credentialType?: string;
  /** An MCP sign-in (`"mcp"`) to any server: its URL. */
  serverUrl?: string;
  client?: NoClick;
}

/**
 * A sign-in to an app (`Connection.signIn`): `status` `connected` with the `credential` it stored and the
 * `connection` it is (none for a plan the platform's agents don't run on: GitHub Copilot, xAI); `choose` when the
 * provider asks the person to pick (`what`: a `project`, an `instagram_account`) from `choices` (each with its `id`);
 * or `waiting` while the person signs in on the provider's page (`way` `device`: enter `userCode` at
 * `verificationUrl`, then `wait`; `code`: open `authorizeUrl` and `finish` with the code it shows; an MCP server's
 * `redirect`: open `authorizeUrl` and `finish` with the `code` and `state` your callback got, or `key`: `finish` with
 * the key it takes). `account` is what the provider says of the account signed in to (an email, a team, a site);
 * never a token.
 */
export class SignIn {
  private readonly _raw: JsonObject;
  private readonly _client: NoClick | undefined;
  private readonly _user: ObjectInit["user"];

  /** @internal */
  constructor(raw: JsonObject, client: NoClick | undefined, user: ObjectInit["user"]) {
    this._raw = raw;
    this._client = client;
    this._user = user;
  }

  get id(): string | null {
    return (this._raw.id as string | null) ?? null;
  }
  get status(): "connected" | "choose" | "waiting" {
    return this._raw.status as "connected" | "choose" | "waiting";
  }
  get provider(): string {
    return String(this._raw.provider);
  }
  get connection(): Connection | null {
    const raw = this._raw.connection;
    return raw ? Connection._of({ raw: asObject(raw), client: this._client, user: this._user }) : null;
  }
  get credential(): JsonObject | null {
    return this._raw.credential ? { ...asObject(this._raw.credential) } : null;
  }
  get account(): JsonObject {
    return { ...asObject(this._raw.account ?? {}) };
  }
  private _waiting<T>(key: string): T | null {
    return (asObject(this._raw.waiting ?? {})[key] as T | undefined) ?? null;
  }
  get way(): "device" | "code" | "redirect" | "key" | "qr" | null {
    return this._waiting("way");
  }
  get userCode(): string | null {
    return this._waiting("user_code");
  }
  get verificationUrl(): string | null {
    return this._waiting("verification_url");
  }
  get verificationUrlComplete(): string | null {
    return this._waiting("verification_url_complete");
  }
  get authorizeUrl(): string | null {
    return this._waiting("authorize_url");
  }
  get interval(): number | null {
    return this._waiting("interval");
  }
  /** WhatsApp's QR to scan (`way` `qr`): a PNG in base64, which WhatsApp rotates while it waits. */
  get qrCode(): string | null {
    return this._waiting("qr_code");
  }
  /** An MCP sign-in's state, which its callback returns with the code. */
  get state(): string | null {
    return this._waiting("state");
  }
  /** Who an MCP server says signs it in. */
  get serverName(): string | null {
    return this._waiting("name");
  }
  /** An MCP server's proof of the account it signed in to (the tools it lists for it). */
  get verification(): Verification | null {
    return toVerification(this._raw.verification);
  }
  get expiresAt(): Date | null {
    const at = this._waiting<string>("expires_at");
    return at ? new Date(at) : null;
  }
  get what(): string | null {
    return (asObject(this._raw.choose ?? {}).what as string | undefined) ?? null;
  }
  get choices(): JsonObject[] {
    return asList(asObject(this._raw.choose ?? {}).choices ?? []).map((choice) => asObject(choice));
  }
  get raw(): JsonObject {
    return { ...this._raw };
  }

  /**
   * Finish a sign-in that waits on the person: with the `id` of the choice they picked, the `code` they copied from
   * the provider's page, or nothing, to ask whether they've signed in.
   */
  async finish(choice?: string | null, options: { code?: string; state?: string; apiKey?: string } = {}): Promise<SignIn> {
    if (!this.id) throw new InvalidRequest("This sign-in waits on no one.");
    return await Connection.finishSignIn(this.id, choice, { ...options, client: this._client });
  }

  /**
   * Ask, every `interval` seconds, whether the person has entered `userCode` (a device code's sign-in) or scanned the
   * QR (WhatsApp's), until they have, or `timeoutMs` passes (`OperationTimeout`). WhatsApp rotates its
   * QR while it waits: to show the newest, ask with `finish()` instead, which answers it as `qrCode`. A refusal (the
   * code expired, the person declined) throws `InvalidRequest`.
   */
  async wait(options: { timeoutMs?: number } = {}): Promise<SignIn> {
    const deadline = Date.now() + (options.timeoutMs ?? 900_000);
    let current: SignIn = this;
    while (current.status === "waiting") {
      if (current.way !== "device" && current.way !== "qr") {
        throw new InvalidRequest(current.way === "code"
          ? "This sign-in finishes with the code its page shows: finish(null, { code })."
          : "This sign-in finishes with its callback's code and state, or a key: finish(null, { code, state }) or finish(null, { apiKey }).");
      }
      if (Date.now() >= deadline) {
        throw new OperationTimeout(current.way === "device" ? `Nobody entered ${current.userCode} in time.` : "Nobody scanned the QR in time.");
      }
      await new Promise((done) => setTimeout(done, (current.interval ?? 5) * 1000));
      current = await Connection.finishSignIn(current.id as string, null, { client: this._client });
    }
    return current;
  }
}

/**
 * A connect page URL that is also the operation tracking it. `wait()` resolves to what it connected: the
 * `Connection`, or an agent's `AgentToolServer` for that server's sign-in link.
 */
export class ConnectLink<T = Connection> extends Operation<T> {
  /** Where the person connects. */
  url = "";
  expiresAt: Date | null = null;
  /** The connection the link fills. */
  connection: string | null = null;
  /** Channels the link went out on when `sendTo` was set (`["email"]`); empty otherwise. */
  deliveredVia: string[] = [];
  /** Channels that failed, each with a `reason`: send the link yourself. */
  undelivered: JsonObject[] = [];

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Connect-link operations (kind `credential.connect`), newest first. Rows are
   * operations: the link's URL is only in the response that created it (and on its pending connection).
   */
  static override async list(options: KindScopedFilters & { limit?: number } = {}): Promise<Operation<Connection>[]> {
    return (await Operation.list(withKinds(options, CONNECT_KINDS, "ConnectLink.list"))) as Operation<Connection>[];
  }

  /** One page of connect-link operations; pass `nextCursor` back as `cursor`. */
  static override async listPage(options: KindScopedFilters & PageOptions = {}): Promise<Page<Operation<Connection>>> {
    return (await Operation.listPage(withKinds(options, CONNECT_KINDS, "ConnectLink.listPage"))) as Page<Operation<Connection>>;
  }

  /** How many connect-link operations match, by status. */
  static override async summary(options: KindScopedFilters = {}): Promise<OperationSummary> {
    return await Operation.summary(withKinds(options, CONNECT_KINDS, "ConnectLink.summary"));
  }

  /** @internal */
  static _fromLink<T = Connection>(payload: unknown, init: { client?: NoClick; user?: ObjectInit["user"] },
    kind = "credential.connect"): ConnectLink<T> {
    const body = asObject(payload);
    const link = new ConnectLink<T>(Operation._init(body.operation, { ...init, kind }));
    link.url = String(body.url ?? "");
    link.expiresAt = parseTime(body.expires_at);
    link.connection = str(body.connection);
    const delivery = body.delivery && typeof body.delivery === "object" ? (body.delivery as JsonObject) : {};
    link.deliveredVia = Array.isArray(delivery.delivered_via) ? delivery.delivered_via.map(String) : [];
    link.undelivered = Array.isArray(delivery.undelivered) ? (delivery.undelivered as JsonObject[]) : [];
    return link;
  }

  override toString(): string {
    return this.url;
  }
}

registerResult("credential.connect", (result, op) => {
  const body = asObject(result);
  const raw = "connection" in body ? body.connection : result;
  if (typeof raw === "string") return Connection.fromId(raw, { client: op._client, user: op._scope });
  return Connection._of({ raw: asObject(raw), client: op._client, user: op._scope });
});
