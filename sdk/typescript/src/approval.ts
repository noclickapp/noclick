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
 */

import { resolveClient } from "./client.ts";
import { ApiObject, compact, listAll, parseTime } from "./object.ts";
import type { CallOptions, JsonObject, ObjectInit, ReadOptions } from "./object.ts";

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
