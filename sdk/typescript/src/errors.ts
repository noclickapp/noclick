/**
 * The error family. The server renders every refusal as
 * `{"error": {"type", "message", "next_step", ...details}}`; `type` picks the
 * class here (mirroring the API's error types and the Python client). Extra
 * keys land in `details`, untouched (snake_case).
 */

import type { NoClick } from "./client.ts";
import type { HumanRequest } from "./human.ts";
import type { Operation } from "./operation.ts";
import type { UserRef } from "./scope.ts";
import type { BuildQuestion, WorkflowGraph } from "./workflow.ts";

export type JsonObject = { [key: string]: unknown };

/** The client and user of the call that raised an error, for its follow-up calls. */
export interface ErrorOrigin {
  client: NoClick;
  user: UserRef | null;
}

// Kept beside each error, not on it: an error is printed and serialized whole, and its client holds the key.
const origins = new WeakMap<NoClickError, ErrorOrigin>();

/** @internal Set by the client on each error a call raises. */
export function _setOrigin(err: NoClickError, origin: ErrorOrigin): void {
  origins.set(err, origin);
}

type ApprovalFactory = (details: JsonObject, origin: ErrorOrigin | undefined) => HumanRequest<boolean> | null;
let approvalFactory: ApprovalFactory | null = null;

/** @internal Registered by human.ts (a runtime import here would be circular). */
export function _registerApprovalFactory(factory: ApprovalFactory): void {
  approvalFactory = factory;
}

type OperationFactory = (operationId: string, origin: ErrorOrigin | undefined, kind: string) => Operation<JsonObject>;
let operationFactory: OperationFactory | null = null;

// The operation of a call NoClick holds for the account's owner, which runs the call once they approve.
const HELD_CALL = "gate.held_call";

/** @internal Registered by operation.ts, for the same reason. */
export function _registerOperationFactory(factory: OperationFactory): void {
  operationFactory = factory;
}

/** One way past a refusal for money: a link a person opens to pay, no sign-in needed. Hand them `url`. */
export interface Offer {
  /** `plan` (a plan that includes what was refused), `funds` (an amount added to the balance) or `topup` (a monthly add-on, on the older plans). */
  kind: string;
  /** What it buys, in words: `the Plus plan, billed monthly`. */
  label: string;
  priceUsd: number;
  url: string;
  /** When the link stops working; refused again before then, the same link comes back. */
  expiresAt: Date | null;
  /** The `payment` operation the link settles: `wait()` resolves once it's paid, and rejects with `OperationExpired` if it never is. */
  operation: Operation<JsonObject>;
}

export interface ErrorInit {
  nextStep?: string | null;
  details?: JsonObject;
  status?: number | null;
  requestId?: string | null;
  attempts?: number | null;
}

export class NoClickError extends Error {
  static errorType = "error";
  static httpStatus: number | null = null;

  type: string;
  nextStep: string | null;
  details: JsonObject;
  status: number | null;
  requestId: string | null;
  /** How many times the client sent the call before this error (1 + its retries); null when no request raised it. */
  attempts: number | null;

  constructor(message = "", init: ErrorInit = {}) {
    super(message);
    const cls = this.constructor as typeof NoClickError;
    this.name = cls.name;
    this.type = cls.errorType;
    this.nextStep = init.nextStep ?? null;
    this.details = { ...(init.details ?? {}) };
    this.status = init.status ?? cls.httpStatus;
    this.requestId = init.requestId ?? null;
    this.attempts = init.attempts ?? null;
  }

  /** Seconds the server asked us to wait (from `Retry-After`), when it did. */
  get retryAfter(): number | undefined {
    const value = this.details.retry_after;
    return typeof value === "number" ? value : undefined;
  }

  override toString(): string {
    const text = `${this.name}: ${this.message}`;
    return this.nextStep ? `${text} Next step: ${this.nextStep}` : text;
  }

  toJSON(): JsonObject {
    const sent = this.attempts === null ? {} : { attempts: this.attempts };
    return { type: this.type, message: this.message, next_step: this.nextStep, status: this.status, ...sent, ...this.details };
  }
}

function detail(err: NoClickError, key: string): string | undefined {
  const value = err.details[key];
  return typeof value === "string" ? value : undefined;
}

export class InvalidRequest extends NoClickError {
  static override errorType = "invalid_request";
  static override httpStatus = 400;
}
export class Unauthenticated extends NoClickError {
  static override errorType = "unauthenticated";
  static override httpStatus = 401;
}
abstract class Offering extends NoClickError {
  private _offers: Offer[] | null = null;

  /** The links that would lift this refusal (empty for a user's scope, which never pays for the account). */
  get offers(): Offer[] {
    if (!this._offers) {
      const rows = Array.isArray(this.details.offers) ? (this.details.offers as JsonObject[]) : [];
      this._offers = rows.map((o) => ({
        kind: String(o.kind),
        label: String(o.label),
        priceUsd: Number(o.price_usd),
        url: String(o.url),
        expiresAt: typeof o.expires_at === "string" ? new Date(o.expires_at) : null,
        operation: operationFactory!(String(o.operation_id), origins.get(this), "payment"),
      }));
    }
    return this._offers;
  }
}

/**
 * Your account can't pay for this: `balanceUsd` is what's left and `requiredUsd` what the call
 * needs, in US dollars. `offers` are links a person opens to add funds or change plan; retry once
 * one is paid. A model provider's account out of funds (your own key) throws it too, with
 * `details.reason` `"provider_out_of_funds"`. A deployed app's paid call names the app in
 * `details.project` and `details.project_id` (invite-only beta).
 *
 *     if (err instanceof PaymentRequired) for (const offer of err.offers) console.log(offer.label, offer.url);
 */
export class PaymentRequired extends Offering {
  static override errorType = "payment_required";
  static override httpStatus = 402;
  get balanceUsd(): number | undefined {
    return typeof this.details.balance_usd === "number" ? this.details.balance_usd : undefined;
  }
  get requiredUsd(): number | undefined {
    return typeof this.details.required_usd === "number" ? this.details.required_usd : undefined;
  }
}
/** The account's plan doesn't allow this: plans cap some resources. `offers` are links to the plans that do. */
export class PlanRequired extends Offering {
  static override errorType = "plan_required";
  static override httpStatus = 402;
}
export class PriceExceeded extends NoClickError {
  static override errorType = "price_exceeded";
  static override httpStatus = 402;
}

/**
 * A policy wants a person to approve this call first. The approval request is
 * already out; wait on it, then retry with `approvalId`:
 *
 *     if (err instanceof ApprovalRequired && (await err.operation?.wait()))
 *       await gmail.run("send_email_message", args, { approvalId: err.approvalId });
 *
 * A call NoClick holds for the account's owner (a purchase, a deletion that can't be undone, a change from an
 * agent or a connected app) waits on the owner instead, who approves it from the link NoClick sends them
 * (`details.sent_to` says where). NoClick makes the call itself once they do: wait on `operation` for its
 * answer, and don't retry it.
 */
export class ApprovalRequired extends NoClickError {
  static override errorType = "approval_required";
  static override httpStatus = 402;
  private _operation: HumanRequest<boolean> | Operation<JsonObject> | null = null;

  /**
   * The approval as an operation: `wait()` resolves to `true` once approved. `null` when the call's
   * credential can't read it: a user's session, or a key pinned to them, for a call someone else approves.
   *
   * A call NoClick holds for the account's owner is the held call itself instead (`operationId`): NoClick makes
   * the call once they approve, so there's nothing to retry, and `wait()` resolves to `{ status, response }`,
   * the call's HTTP status and its answer. It throws `PolicyDenied` if they decline, and `Expired` if nobody
   * answers in time.
   */
  get operation(): HumanRequest<boolean> | Operation<JsonObject> | null {
    if (!this._operation && approvalFactory) this._operation = approvalFactory(this.details, origins.get(this));
    const held = this.details.operation_id;
    if (!this._operation && operationFactory && typeof held === "string" && held) {
      this._operation = operationFactory(held, origins.get(this), HELD_CALL);
    }
    return this._operation;
  }
  get approvalId(): string | undefined {
    return detail(this, "approval_id");
  }
  /** The page where the approver answers; set only when the approver is the one the call is made for. */
  get approveUrl(): string | undefined {
    return detail(this, "approve_url");
  }
  /** The approval's operation id (`Operation.fromId(id).wait()` resolves to a boolean). */
  get operationId(): string | undefined {
    const op = this.details.operation;
    if (typeof op === "string") return op;
    if (op && typeof op === "object" && typeof (op as JsonObject).id === "string") return (op as JsonObject).id as string;
    return detail(this, "operation_id");
  }
}

export class SpendCapExceeded extends NoClickError {
  static override errorType = "spend_cap_exceeded";
  static override httpStatus = 402;
  get cap(): number | undefined {
    return typeof this.details.cap === "number" ? this.details.cap : undefined;
  }
  get spent(): number | undefined {
    return typeof this.details.spent === "number" ? this.details.spent : undefined;
  }
  /**
   * Which cap tripped: `key`, `user`, `agent`, `project` (a deployed app's own budget), ... An app's
   * paid call names the app in `details.project` and `details.project_id`.
   */
  get scope(): string | undefined {
    return detail(this, "scope");
  }
}

/**
 * You paused this user's spending (`user.pauseSpending()`), so nothing that costs money runs for
 * them until `user.resumeSpending()`. `message` and `nextStep` are for you; `userMessage` and
 * `action` are what you asked NoClick to tell the user, to show them as they are; `since` is when
 * you paused them.
 */
export class SpendingPaused extends NoClickError {
  static override errorType = "spending_paused";
  static override httpStatus = 402;
  get userMessage(): string | undefined {
    return detail(this, "user_message");
  }
  get action(): { label: string; url: string } | undefined {
    const action = this.details.action;
    if (!action || typeof action !== "object") return undefined;
    const { label, url } = action as JsonObject;
    return typeof label === "string" && typeof url === "string" ? { label, url } : undefined;
  }
  get since(): Date | undefined {
    const since = detail(this, "since");
    return since ? new Date(since) : undefined;
  }
}

export class PermissionDenied extends NoClickError {
  static override errorType = "permission_denied";
  static override httpStatus = 403;
}
export class PolicyDenied extends NoClickError {
  static override errorType = "policy_denied";
  static override httpStatus = 403;
}
export class NotFound extends NoClickError {
  static override errorType = "not_found";
  static override httpStatus = 404;
}
/**
 * It already exists (`existingId` names it), or another call holds it, like a conversation mid-turn. An edit of a
 * workflow's graph checked against a version it has moved on from (`ifVersion`) carries the workflow as it stands:
 * its `version` and `graph` (a `WorkflowGraph`), to decide again from.
 */
export class Conflict extends NoClickError {
  static override errorType = "conflict";
  static override httpStatus = 409;
  /** The workflow's graph as it stands, on a refused edit of it (`null` on any other conflict). */
  graph: WorkflowGraph | null = null;
  get existingId(): string | undefined {
    return detail(this, "existing_id");
  }
  /** The version kept, on a refused edit of a workflow's graph or of your channel sections. */
  get version(): number | undefined {
    const value = this.details.version;
    return typeof value === "number" ? value : undefined;
  }
}
export class NotAvailable extends NoClickError {
  static override errorType = "not_available";
  static override httpStatus = 409;
}
export class ActionRequired extends NoClickError {
  static override errorType = "action_required";
  static override httpStatus = 409;
}
/**
 * A workflow build waits on an answer, and `question` says what. Answer it with `build.answer(...)`
 * where `question.answerableFromCode`; otherwise send a person to `question.answerUrl`. Then
 * `build.wait()` again: it waits through a question it has thrown.
 */
export class AnswerRequired extends NoClickError {
  static override errorType = "answer_required";
  question!: BuildQuestion;
}
/** A request, link or operation expired before anyone acted on it. */
export class Expired extends NoClickError {
  static override errorType = "expired";
  static override httpStatus = 410;
}
export const OperationExpired = Expired;

abstract class ConnectionError extends NoClickError {
  /** Where the user connects (or reconnects) the account. */
  get connectUrl(): string | undefined {
    return detail(this, "connect_url");
  }
  /** The connection's name. */
  get connection(): string | undefined {
    return detail(this, "connection");
  }
  get integration(): string | undefined {
    return detail(this, "integration");
  }
}
/** The connection has no account connected yet; send the person `connectUrl`. */
export class NeedsConnection extends ConnectionError {
  static override errorType = "needs_connection";
  static override httpStatus = 424;
}
/** The connection's account was revoked or stopped working; send the person `connectUrl` to reconnect it. */
export class CredentialDisconnected extends ConnectionError {
  static override errorType = "credential_disconnected";
  static override httpStatus = 424;
}
/** A spent quota: never retried automatically. */
export class QuotaExceeded extends NoClickError {
  static override errorType = "quota_exceeded";
  static override httpStatus = 429;
}
/**
 * An agent's turn its model connection's Claude or ChatGPT plan turned down at its limit: `connection`, `window`, when
 * it's back (`resetsAt`) and what the agent did (`then`: it switched and carried on, waits until the reset, or asked
 * the owner to allow a paid key).
 */
export class PlanLimitReached extends NoClickError {
  static override errorType = "plan_limit_reached";
  static override httpStatus = 429;
  get connection(): string | undefined {
    return detail(this, "connection");
  }
  get window(): string | undefined {
    return detail(this, "window");
  }
  get resetsAt(): string | undefined {
    return detail(this, "resets_at");
  }
  get then(): Record<string, unknown> | undefined {
    return this.details.then as Record<string, unknown> | undefined;
  }
}
export class RateLimited extends NoClickError {
  static override errorType = "rate_limited";
  static override httpStatus = 429;
}
/**
 * A service NoClick relays to refused the call or failed. A refusal, such as an integration's service
 * answering a run with an error, comes in its own words, its HTTP status in `details.upstream_status`,
 * and answers 424: it isn't retried, since sending the same call again won't help. A failure (a model's
 * provider down, a service that didn't answer) answers 503 and is retried; once retries run out,
 * retrying in a moment usually works. Where it matters, as for a database's statements, `applied` says
 * whether the call took effect:
 *
 *     if (err instanceof UpstreamError && err.applied === false) await db.execute(sql, params);
 */
export class UpstreamError extends NoClickError {
  static override errorType = "upstream_error";
  static override httpStatus = 503;
  /**
   * `false` when NoClick knows the call didn't take effect (a read, or a write the service never ran), so
   * sending it again is safe; `true` when it did; `null` when NoClick can't tell, as for a write a database
   * never answered (the message says so): check before sending it again.
   */
  get applied(): boolean | null {
    return typeof this.details.applied === "boolean" ? this.details.applied : null;
  }
  /** How many times NoClick sent the call to the service before giving up. */
  get upstreamAttempts(): number | undefined {
    return typeof this.details.upstream_attempts === "number" ? this.details.upstream_attempts : undefined;
  }
}
/**
 * The work outlasted what one request may wait (about 90 seconds); it answers 503. Never retried
 * automatically, since the work may still be going on: an agent's turn goes on and lands in its
 * conversation (`details.operation_id` and `details.conversation` say where).
 */
export class RequestTimeout extends NoClickError {
  static override errorType = "request_timeout";
  static override httpStatus = 503;
}

// Client-side conditions with no server class.
/** A 5xx the server could not describe as a platform error. */
export class ServerError extends NoClickError {
  static override errorType = "server_error";
}
/** The API could not be reached, even after retries. */
export class APIConnectionError extends NoClickError {
  static override errorType = "connection_error";
}
/** An operation finished `failed` without a more specific error type. */
export class OperationFailed extends NoClickError {
  static override errorType = "operation_failed";
}
export class OperationCanceled extends NoClickError {
  static override errorType = "operation_canceled";
}
/** `operation.wait({ timeoutS })` ran out before the operation finished. */
export class OperationTimeout extends NoClickError {
  static override errorType = "operation_timeout";
}
/**
 * A webhook delivery's `NoClick-Signature` doesn't match its body, or its timestamp is too old.
 * Thrown by `Webhook.verify` in your receiver; answer it with a 400 and drop the delivery.
 */
export class WebhookSignatureError extends NoClickError {
  static override errorType = "webhook_signature_invalid";
}

const CLASSES: (typeof NoClickError)[] = [
  InvalidRequest, Unauthenticated, PaymentRequired, PlanRequired, PriceExceeded, ApprovalRequired,
  SpendCapExceeded, SpendingPaused, PermissionDenied, PolicyDenied, NotFound, Conflict, NotAvailable, ActionRequired, AnswerRequired,
  Expired, NeedsConnection, CredentialDisconnected, QuotaExceeded, PlanLimitReached, RateLimited, UpstreamError, RequestTimeout, ServerError,
  APIConnectionError,
  OperationFailed, OperationCanceled, OperationTimeout, WebhookSignatureError,
];
const BY_TYPE = new Map(CLASSES.map((cls) => [cls.errorType, cls]));
const BY_STATUS = new Map<number, typeof NoClickError>([
  [400, InvalidRequest], [401, Unauthenticated], [403, PermissionDenied], [404, NotFound],
  [409, Conflict], [410, Expired], [424, NeedsConnection], [429, RateLimited],
]);
const BASE_KEYS = new Set(["type", "message", "next_step"]);

/** Build the matching error from an `error` object (or a whole `{"error": {...}}` body). */
export function errorFromPayload(
  payload: unknown,
  options: { status?: number | null; requestId?: string | null; fallback?: typeof NoClickError } = {},
): NoClickError {
  let body: JsonObject;
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const inner = (payload as JsonObject).error;
    body = inner && typeof inner === "object" && !Array.isArray(inner) ? (inner as JsonObject) : (payload as JsonObject);
  } else {
    body = { message: payload ? String(payload) : "" };
  }
  // OpenAI's envelope (`/v1/ai`): `type` is OpenAI's, `code` the platform's.
  const code = typeof body.code === "string" && BY_TYPE.has(body.code) ? body.code : undefined;
  const type = code ?? (typeof body.type === "string" ? body.type : undefined);
  const status = options.status ?? null;
  let cls = type ? BY_TYPE.get(type) : undefined;
  if (!cls) {
    cls = status !== null && status >= 500 ? ServerError : (BY_STATUS.get(status ?? 0) ?? options.fallback ?? NoClickError);
  }
  const details: JsonObject = {};
  for (const [key, value] of Object.entries(body)) if (!BASE_KEYS.has(key)) details[key] = value;
  const message = typeof body.message === "string" && body.message ? body.message : `Request failed (${type ?? status ?? "unknown"}).`;
  const err = new cls(message, {
    nextStep: typeof body.next_step === "string" ? body.next_step : null,
    details,
    status,
    requestId: options.requestId ?? null,
  });
  if (type && type !== cls.errorType) err.type = type; // an unknown server type stays visible
  return err;
}
