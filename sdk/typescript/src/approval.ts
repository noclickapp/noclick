/**
 * Approvals: the calls NoClick holds for your account's owner's yes, read and answered from your own code. When an
 * agent, a connected app, a key used through MCP or an app's own code makes a purchase, a deletion that can't be
 * undone, a call your policy holds or one that raises a spending limit, NoClick holds the exact call and sends your
 * account's owner a link to approve it. Your code may answer it too, with one of your account's secret keys that
 * names the `approvals:answer` scope (a key with every scope, `*`, holds it only when it's named too).
 *
 *     for (const approval of await Approval.list({ status: "pending" })) {
 *       if (approval.price && Number(approval.price.amount_usd) <= 20) await approval.approve({ note: "Under $20: fine." });
 *     }
 *
 * A key never answers a call made with it (by its own code, through MCP, or by an agent or app acting as it), never
 * approves one whose terms a person accepts (it may decline it), and approves only what it could make itself: the
 * scopes the call needs (never a call only the owner and their NoClick assistant make), and a price that fits the
 * key's own monthly cap beside what it spent and approved this month (what it approves also counts against what it
 * may still spend itself). NoClick then runs an approved call itself, once, exactly as it was held, with no scope the
 * answering key lacks. While your account holds a key that would approve it, a call whose link reaches no person is
 * still held, with an empty `sentTo`, for your code (or the owner, signed in) to answer.
 *
 * Rather than poll, your code can hear each one: a webhook subscribed to `approval.requested` gets it as it's held,
 * and to `approval.decided` as it's approved, declined, expired or withdrawn. The event's `data` is the approval as
 * it reads here, never its link:
 *
 *     const event = await Webhook.verify(body, headers, secret);
 *     if (event.type === "approval.requested") {
 *       await Approval.fromId(String(event.data.id)).decline({ note: "Nothing is bought on weekends." });
 *     }
 *
 * What NoClick holds, kind by kind and for which callers, reads as `ApprovalPolicy.get()`, and your account switches
 * any kind it may (`ApprovalPolicy.set`) so it needn't wait for a person at all. A key, or a connected app, sets its own
 * within the account's ceiling (`ApprovalPolicy.setForKey`, `ApprovalPolicy.setForConnectedApp`), and so does an agent
 * (`agent.update({ approvals })`), whose children follow it, only ever tighter.
 *
 * An agent gives your workflows' steps your account's own connections and secrets itself (`attach_connection`, allowed
 * by default); switched to `ask`, its edit waits for the owner's yes, and to `deny`, it asks them which account to use:
 *
 *     await ApprovalPolicy.set({ settings: { attach_connection: "ask" } });
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { ApiObject, asList, asObject, compact, defined, listAll, parseTime } from "./object.ts";
import type { CallOptions, JsonObject, ObjectInit, ReadOptions } from "./object.ts";

/** One kind of call NoClick may hold for a person: what it does by default, and what your account switched. */
export interface HoldKind {
  /** Its name (`purchase`, `delete`, `raise_limit`, `attach_connection`, ...). */
  kind: string;
  /** What it covers, in a person's words. */
  description: string;
  /**
   * Who answers it: `owner` (the account's owner, from the link NoClick sends them) or `connection_owner` (whoever owns
   * the connection the call runs on: its user, else the account's owner).
   */
  approver: string;
  /** It applies only on a turn answering someone outside the agent's scope. */
  outsideOnly: boolean;
  /**
   * What it does by default for each kind of caller it applies to (`ApprovalPolicy.callers` names them): `allow`,
   * `ask`, `deny`, `under_auto_approve` (a quoted purchase at or under the connection's auto-approve amount runs,
   * anything else asks) or `once_previewed` (a deletion its preview confirmed runs).
   */
  defaults: Record<string, string>;
  /** Whether your account may switch it (`ApprovalPolicy.set`). */
  settable: boolean;
  /** What your account set it to (`disposition`, `under_usd`, `until`, `effective_at`, `pending`), or null. */
  setting: JsonObject | null;
  /** The loosest a narrower scope may set it to, or null. */
  ceiling: JsonObject | null;
  /**
   * What each caller meets now: a default, or `allow`, `ask`, `deny` or `allow_under` (a purchase at or under the
   * setting's `under_usd` runs) by your account's setting (or the key's, connected app's or agent's own, read with
   * `get({ keyId })` or `get({ agentId })`).
   */
  effective: Record<string, string>;
  /** Read for a key, connected app or agent: what it sets for itself, or null. */
  own: JsonObject | null;
}

/** One change to your account's approval switches, to a key's, connected app's or agent's own, or a connection's
 *  approval rule lifted (`Connection.liftApproval`, or its owner's page in the app). */
export interface PolicyChange {
  id: string;
  batchId: string;
  /** Whose settings it changed: `account`, `key`, `connected_app`, `agent` or `credential` (a connection's approval
   *  rule), and that key's, connected app's, agent's or connection's account's id. */
  scope: string;
  scopeId: string | null;
  /** The kind it changed (`credential_rule` for a connection's rule). */
  kind: string;
  /** `setting`, `ceiling`, `auto_approve` (a connected app's auto-approve amount) or `operations` (a connection's
   *  rule). */
  target: string;
  before: JsonObject | null;
  /** What it set (`disposition`, `under_usd`, `until`; a connection's rule, its `operations`); null put NoClick's
   *  default back. */
  after: JsonObject | null;
  /** It lets a caller do more than before: a key's loosening waits out an undo window first. */
  loosens: boolean;
  /** `owner` (signed in), `key` (with `keyId`), or through NoClick's tools `assistant` (NoClick's), `agent` or
   *  `connection` (a connected app): on the owner's word or approval, or a loosening the account lets them make. */
  changedBy: string;
  keyId: string | null;
  effectiveAt: Date | null;
  until: Date | null;
  /** It still waits out its undo window: `ApprovalPolicy.undo` takes it back. A lift of a connection's rule waiting is
   *  taken back too by approval required for one of its operations again (`undoneBy` `superseded`). */
  pending: boolean;
  undoneAt: Date | null;
  undoneBy: string | null;
  createdAt: Date | null;
  raw: JsonObject;
}

/** What a call of one kind by one kind of caller meets now, and why. */
export interface ApprovalExplanation {
  kind: string;
  caller: string;
  /** `allow`, `ask`, `deny`, or `under_auto_approve` where it turns on the connection's own amount. */
  disposition: string;
  /** `key` (the key's or connected app's own setting), `account` (your setting), `bounds` (NoClick asks this caller
   *  first) or `default`. */
  source: string;
  /** What a held call's approval would say; null when it runs. */
  why: string | null;
  setting: JsonObject | null;
  raw: JsonObject;
}

/** A kind's switch: `"allow"`, `"ask"`, `"deny"`, the same as an object (a purchase may take `under_usd`; any kind
 *  `until`), or null for NoClick's default. */
export type ApprovalSetting = "allow" | "ask" | "deny" | {
  disposition: "allow" | "ask" | "deny";
  under_usd?: number;
  until?: Date | string;
} | null;

/** A key's or connected app's own approval settings, as a change left them. */
export interface OwnApprovals {
  /** `key` or `connected_app`, and its id. */
  kind: string;
  id: string;
  /** What it sets for itself, by kind (`disposition`, `under_usd`, `until`, `effective_at`, `pending`). */
  settings: Record<string, JsonObject>;
  /** A connected app's auto-approve amount (null: it asks before every purchase); null for a key. */
  autoApproveUnderUsd: number | null;
  /** Each change the call made. */
  changes: PolicyChange[];
  raw: JsonObject;
}

function ownApprovals(kind: string, entry: unknown): OwnApprovals {
  const raw = asObject(entry);
  return {
    kind, id: String(raw.id), settings: { ...(asObject(raw.approvals) as Record<string, JsonObject>) },
    autoApproveUnderUsd: (raw.auto_approve_under_usd as number | null | undefined) ?? null,
    changes: asList(raw.approval_changes).map(policyChange), raw,
  };
}

/** A change as the API sends it (`ApprovalPolicy.history`, `Connection.liftApproval`). */
export function policyChange(entry: unknown): PolicyChange {
  const c = asObject(entry);
  return {
    id: String(c.id), batchId: String(c.batch_id), scope: String(c.scope ?? "account"),
    scopeId: (c.scope_id as string | null | undefined) ?? null, kind: String(c.kind), target: String(c.target),
    before: (c.before as JsonObject | null) ?? null, after: (c.after as JsonObject | null) ?? null,
    loosens: Boolean(c.loosens), changedBy: String(c.changed_by), keyId: (c.key_id as string | null) ?? null,
    effectiveAt: parseTime(c.effective_at), until: parseTime(c.until), pending: Boolean(c.pending),
    undoneAt: parseTime(c.undone_at), undoneBy: (c.undone_by as string | null) ?? null, createdAt: parseTime(c.created_at),
    raw: c,
  };
}

/** @internal Approval settings by kind as the API takes them (an agent's `approvals` among them). */
export function wireSettings(settings: Record<string, ApprovalSetting> | undefined): JsonObject | undefined {
  if (settings === undefined) return undefined;
  return Object.fromEntries(Object.entries(settings).map(([kind, value]) => [kind,
    value && typeof value === "object"
      ? { ...value, ...(value.until instanceof Date ? { until: value.until.toISOString() } : {}) }
      : value])) as JsonObject;
}

/**
 * What NoClick holds for a person, kind by kind and for which callers: its defaults, and what your account switched
 * (`set`), so no call ever needs a person for good.
 *
 *     const policy = await ApprovalPolicy.get();
 *     policy.default("purchase", "agent"); // "ask"
 *     await ApprovalPolicy.set({ settings: { purchase: { disposition: "allow", under_usd: 20 } } });
 */
export class ApprovalPolicy {
  /** Each kind of hold. */
  readonly kinds: HoldKind[];
  /** Each kind of caller, by name (`connected_app`, `assistant`, `agent`, `key`, `code`, `app`), with what it is. */
  readonly callers: Record<string, string>;
  /** Whether the account has a monthly spending cap: loosening a purchase or a deletion past the default needs one. */
  readonly spendCapSet: boolean;
  /** The changes the call that returned it made (`set`); empty from `get`. */
  readonly changes: PolicyChange[];
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.raw = raw;
    this.kinds = asList(raw.kinds).map((entry) => {
      const k = asObject(entry);
      const defaults = { ...(asObject(k.defaults) as Record<string, string>) };
      return {
        kind: String(k.kind), description: String(k.description), approver: String(k.approver),
        outsideOnly: Boolean(k.outside_only), defaults, settable: Boolean(k.settable),
        setting: (k.setting as JsonObject | null) ?? null, ceiling: (k.ceiling as JsonObject | null) ?? null,
        effective: k.effective ? { ...(asObject(k.effective) as Record<string, string>) } : { ...defaults },
        own: (k.own as JsonObject | null | undefined) ?? null,
      };
    });
    this.callers = { ...(asObject(raw.callers) as Record<string, string>) };
    this.spendCapSet = Boolean(raw.spend_cap_set);
    this.changes = asList(raw.changes).map(policyChange);
  }

  /**
   * What waits for a person: each kind of hold (a purchase, a deletion that can't be undone, a spending limit raised,
   * a call whose terms a person accepts, ...), what it covers, who approves it, what it does by default for each
   * kind of caller (a connected app, NoClick's assistant, an agent's tools, a key used through MCP, code, an app's
   * own code), and what your account switched. With `keyId`, `connectedAppId` or `agentId`, also what that key,
   * connected app or agent sets for itself (each kind's `own`), which `effective` reads for its calls (an agent's
   * through its parent's, which it follows where it sets none).
   */
  static async get(
    options: { keyId?: string; connectedAppId?: string; agentId?: string; client?: NoClick } = {},
  ): Promise<ApprovalPolicy> {
    const raw = await resolveClient(options.client).request("GET", "/v1/approvals/policy", {
      query: { key_id: options.keyId, connected_app_id: options.connectedAppId, agent_id: options.agentId },
      user: null,
    });
    return new ApprovalPolicy(asObject(raw));
  }

  /**
   * Switch what NoClick holds for a person, for your whole account, from the kinds `get` lists as `settable`. Kinds
   * you don't name stay as they are; null puts one back to NoClick's default. `ceilings` are the loosest a narrower
   * scope (a key, an agent) may set. Signed in as the account's owner, or with one of its own secret keys naming the
   * `approvals:policy` scope (`*` holds it only when it's named too). A key's loosening takes effect after a 10-minute
   * undo window, and the owner is told. Throws `PermissionDenied` (`reason` `spend_cap_required`) when it loosens a
   * purchase or a deletion past the default while the account has no monthly spending cap.
   */
  static async set(
    options: { settings?: Record<string, ApprovalSetting>; ceilings?: Record<string, ApprovalSetting>; client?: NoClick },
  ): Promise<ApprovalPolicy> {
    const raw = await resolveClient(options.client).request("PUT", "/v1/approvals/policy", {
      json: compact({ settings: wireSettings(options.settings), ceilings: wireSettings(options.ceilings) }), user: null,
    });
    return new ApprovalPolicy(asObject(raw));
  }

  /**
   * What a call of `kind` by `caller` would meet now, and why: the key's or connected app's own setting (`keyId`,
   * `connectedAppId`: the call is its), an agent's own or its parent's (`agentId`, with `caller` `"agent"`: `source`
   * `agent` or `parent`), your account's setting, what NoClick asks that caller first, or the default. Nothing runs
   * and nothing is held.
   */
  static async explain(
    kind: string, caller: string,
    options: {
      amountUsd?: number; quoted?: boolean; previewed?: boolean; keyId?: string; connectedAppId?: string;
      agentId?: string; client?: NoClick;
    } = {},
  ): Promise<ApprovalExplanation> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/approvals/policy/explain", {
      json: compact({ kind, caller, amount_usd: options.amountUsd, quoted: options.quoted ?? true,
        previewed: options.previewed ?? true, key_id: options.keyId, connected_app_id: options.connectedAppId,
        agent_id: options.agentId }),
      user: null,
    }));
    return {
      kind: String(raw.kind), caller: String(raw.caller), disposition: String(raw.disposition),
      source: String(raw.source), why: (raw.why as string | null) ?? null, setting: (raw.setting as JsonObject | null) ?? null,
      raw,
    };
  }

  /** Every change to your account's approval switches, newest first: the first 20, or the first `limit` (at most 100). */
  static async history(options: { limit?: number; client?: NoClick } = {}): Promise<PolicyChange[]> {
    const raw = await resolveClient(options.client).request("GET", "/v1/approvals/policy/changes", {
      query: { limit: options.limit }, user: null,
    });
    return asList(asObject(raw).data).map(policyChange);
  }

  /**
   * Take back a change still waiting out its undo window (a key's loosening): what was in effect before it stands
   * again. Throws `Conflict` once it's in effect, undone already, or replaced by a later change.
   */
  static async undo(changeId: string, options: { client?: NoClick } = {}): Promise<PolicyChange> {
    const raw = await resolveClient(options.client).request(
      "POST", `/v1/approvals/policy/changes/${encodeURIComponent(changeId)}/undo`, { user: null });
    return policyChange(raw);
  }

  /**
   * Switch what one of your secret keys waits for, in place of the account's, for the calls it makes through MCP and
   * the code it runs: each named kind as `set` takes it, or null for the account's. Never looser than the account's
   * ceiling for the kind (else its own setting, else NoClick's default for a key): raise the ceiling with
   * `set({ ceilings })` first; lowering it later tightens every key at once. A purchase or a deletion past the default
   * needs a monthly cap on the account. Any of your account's keys tightens them; loosening takes one naming
   * `approvals:policy` (it waits a 10-minute undo window, and a key never loosens itself). Your agents change them when
   * you say so; one acting on its own waits for you.
   *
   *     await ApprovalPolicy.set({ ceilings: { purchase: { disposition: "allow", under_usd: 50 } } });
   *     await ApprovalPolicy.setForKey(keyId, { purchase: { disposition: "allow", under_usd: 20 } });
   */
  static async setForKey(
    keyId: string, settings: Record<string, ApprovalSetting>, options: { client?: NoClick } = {},
  ): Promise<OwnApprovals> {
    const raw = await resolveClient(options.client).request("PATCH", `/v1/keys/${encodeURIComponent(keyId)}`, {
      json: { approvals: wireSettings(settings) as JsonObject }, user: null,
    });
    return ownApprovals("key", raw);
  }

  /**
   * Switch what a connected app (an MCP client a person connected, NoClick's assistant's grant among them) waits for,
   * in place of the account's, for its calls and its code's: `settings` as `setForKey` takes them, and its
   * `autoApproveUnderUsd`, the price at or under which a purchase it makes goes through unasked (null: it asks before
   * every one), at or under its monthly cap and the account's ceiling for purchases. Any of your account's keys
   * tightens them; loosening takes one naming `approvals:policy` (which only lowers an auto-approve amount). Your agents
   * change them when you say so; a connected app or an agent acting on its own waits for you.
   *
   *     await ApprovalPolicy.setForConnectedApp(appId, { autoApproveUnderUsd: 10 });
   */
  static async setForConnectedApp(
    connectedAppId: string,
    options: { settings?: Record<string, ApprovalSetting>; autoApproveUnderUsd?: number | null; client?: NoClick },
  ): Promise<OwnApprovals> {
    const raw = await resolveClient(options.client).request(
      "PATCH", `/v1/connected_apps/${encodeURIComponent(connectedAppId)}`, {
        json: defined({ approvals: wireSettings(options.settings), auto_approve_under_usd: options.autoApproveUnderUsd }),
        user: null,
      });
    return ownApprovals("connected_app", raw);
  }

  private find(kind: string): HoldKind {
    const found = this.kinds.find((k) => k.kind === kind);
    if (!found) {
      throw new Error(`NoClick holds no kind '${kind}': it holds ${this.kinds.map((k) => k.kind).join(", ")}.`);
    }
    return found;
  }

  /** What `kind` does by default for `caller`, whatever your account switched; null where it doesn't apply. Throws for a kind NoClick doesn't hold. */
  default(kind: string, caller: string): string | null {
    return this.find(kind).defaults[caller] ?? null;
  }

  /** What `kind` does for `caller` now: your account's setting where it switched one, else the default. */
  effective(kind: string, caller: string): string | null {
    return this.find(kind).effective[caller] ?? null;
  }
}


export type ApprovalStatus = "pending" | "approved" | "declined" | "expired" | "used" | "canceled";

export interface ApprovalListOptions extends ReadOptions {
  /** One status; omitted, every one. */
  status?: ApprovalStatus;
  /** The first this many (20 unless you say, at most 100). */
  limit?: number;
}

/** A call held for your account's owner's yes, as they see it on its page. */
export class Approval extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** A lazy reference to an approval by its id (an `ApprovalRequired`'s `approvalId`). */
  static fromId(approvalId: string, options: Pick<CallOptions, "client"> = {}): Approval {
    return new Approval({ hints: { id: approvalId }, client: options.client, user: null });
  }

  /**
   * Calls held for your account's owner's yes, newest first: the first 20, or the first `limit` (at most 100).
   * Acting for a user, that user's alone.
   */
  static async list(options: ApprovalListOptions = {}): Promise<Approval[]> {
    return await listAll({ ...options, path: "/v1/approvals", query: { status: options.status } },
      (raw) => new Approval({ raw, client: options.client, user: null }));
  }

  get id(): string {
    return this._field("id");
  }
  /** Where it stands (`used`: approved, and run). */
  get status(): ApprovalStatus {
    return this._field("status");
  }
  /** What the call does, in a person's words. */
  get action(): string | null {
    return this._field("action");
  }
  /** A purchase's price (`amount_usd`, `recurrence`, `terms`, `renewal`); null for anything else. */
  get price(): JsonObject | null {
    return this._field("price");
  }
  /** Why it waits for a person. */
  get reason(): string | null {
    return this._field("reason");
  }
  /** The API operation it calls, by name (`phone_numbers_create`). */
  get operation(): string {
    return this._field("operation");
  }
  get method(): string | null {
    return this._field("method");
  }
  get path(): string | null {
    return this._field("path");
  }
  /** Its arguments as the page shows them, secrets masked. */
  get arguments(): JsonObject {
    return this._field("arguments");
  }
  /** Who made it: `kind` (`assistant`, `agent`, `connected_app` or `key`) and `name`. */
  get connection(): JsonObject {
    return this._field("connection");
  }
  /** The user it acts for (null for your account). */
  get userId(): string | null {
    return this._field("user_id");
  }
  /**
   * The held call's operation: `Operation.fromId(...).wait()` gives what it returned once approved, or throws once
   * declined or expired.
   */
  get operationId(): string {
    return this._field("operation_id");
  }
  /** What a deletion takes with it; null for anything else. */
  get impact(): JsonObject | null {
    return this._field("impact");
  }
  /** Terms a person accepts by approving it (each `terms`, `title`, `url`): only the owner approves such a call. */
  get consent(): JsonObject[] {
    return this._field("consent");
  }
  /**
   * Where NoClick sent the owner its link: `whatsapp`, `imessage`, `email`, or `web` (a card in the chat); empty when
   * it reached nobody and waits for your code.
   */
  get sentTo(): string[] {
    return this._field("sent_to");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** When it lapses unanswered (a day after it was held). */
  get expiresAt(): Date | null {
    return parseTime(this._field("expires_at"));
  }
  get decidedAt(): Date | null {
    return parseTime(this._field("decided_at"));
  }
  /** Who decided: `owner` (signed in, or from NoClick's link) or `code`; null while pending. */
  get decidedBy(): "owner" | "code" | null {
    return this._field("decided_by");
  }
  /** The key whose code decided (`key_id`, `key_name`); null otherwise. */
  get decidedByKey(): { key_id: string; key_name: string | null } | null {
    return this._field("decided_by_key");
  }
  /** What whoever decided wrote with it. */
  get note(): string | null {
    return this._field("note");
  }

  protected async _load(): Promise<JsonObject> {
    return await this._request<JsonObject>("GET", this.at(), { user: null });
  }

  private at(suffix = ""): string {
    return `/v1/approvals/${encodeURIComponent(String(this._known("id")))}${suffix}`;
  }

  private async answer(approved: boolean, note: string | undefined): Promise<this> {
    this._raw = await resolveClient(this._client).request<JsonObject>("POST", this.at("/answer"), {
      json: compact({ approved, note }), user: null,
    });
    return this;
  }

  /**
   * Approve it from your own code, with one of your account's secret keys that names the `approvals:answer` scope;
   * NoClick then runs the call itself, once, exactly as it was held. Throws `PermissionDenied` for the key the call
   * was made with, a call whose terms a person accepts, one needing a scope the key lacks or only the owner makes, a
   * key acting for a user, and a key without the scope; `SpendCapExceeded` when its price, beside what the key spent
   * and approved this month, is past the key's own monthly cap.
   */
  approve(options: { note?: string } = {}): Promise<this> {
    return this.answer(true, options.note);
  }

  /**
   * Decline it from your own code, as `approve` answers it: the call never runs, and whoever made it is told why,
   * with your `note`. A call whose terms a person accepts may be declined from code too.
   */
  decline(options: { note?: string } = {}): Promise<this> {
    return this.answer(false, options.note);
  }
}
