/**
 * The trash: what was deleted and can still be put back. Deleting an app, database, bucket, dict,
 * queue, repo, volume, inbox or agent moves it here, restorable for 30 days, then purged for good; each of
 * their `delete()` methods returns its `TrashItem`. A database's restore lands what it rewound here too,
 * as a `database_copy`: restoring that puts it back into its database. While it's in the trash its name
 * is free and its storage is billed as before; restoring is free. `purge()` is the one deletion that
 * can't be undone.
 */

import { ApiObject, listAll, listPage, parseTime } from "./object.ts";
import type { CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";

export type TrashKind =
  | "project" | "database" | "database_copy" | "bucket" | "dict" | "queue" | "repo" | "volume" | "inbox" | "agent"
  | "skill" | "memory";

export interface TrashListOptions extends ReadOptions {
  /** One kind; omitted, every kind. */
  kind?: TrashKind;
}

/** Something deleted, restorable until `purgeAfter`. */
export class TrashItem extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** A lazy reference to an item in the trash by its id. */
  static fromId(trashId: string, options: CallOptions = {}): TrashItem {
    return new TrashItem({ hints: { id: trashId }, client: options.client, user: options.user });
  }

  /** @internal The item a delete answered with. */
  static _fromDeleted(raw: JsonObject, init: Omit<ObjectInit, "raw">): TrashItem {
    return new TrashItem({ ...init, raw: { ...(raw.trash as JsonObject), operation_id: raw.operation_id ?? null } });
  }

  /** What's in the trash, newest first. */
  static async list(options: TrashListOptions & { limit?: number } = {}): Promise<TrashItem[]> {
    return await listAll({ ...options, path: "/v1/trash", query: { kind: options.kind } },
      (raw, user) => new TrashItem({ raw, client: options.client, user }));
  }

  /** One page of the trash; pass `nextCursor` back as `cursor`. */
  static async listPage(options: TrashListOptions & PageOptions = {}): Promise<Page<TrashItem>> {
    return await listPage({ ...options, path: "/v1/trash", query: { kind: options.kind } },
      (raw, user) => new TrashItem({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  /** What it is. */
  get kind(): TrashKind {
    return this._field("kind");
  }
  /** Its id as it was, and will be again once restored. */
  get resourceId(): string {
    return this._field("resource_id");
  }
  get name(): string | null {
    return this._field("name");
  }
  /** The user it was deleted from (null for the account's). */
  get userId(): string | null {
    return this._field("user_id");
  }
  get trashedAt(): Date | null {
    return parseTime(this._field("trashed_at"));
  }
  /** When it's purged for good unless restored first. */
  get purgeAfter(): Date | null {
    return parseTime(this._field("purge_after"));
  }
  /** The deletion's operation (on the item a `delete()` returned): `Operation.undo()` on it restores it too. */
  get operationId(): string | null {
    return this._field("operation_id");
  }

  protected async _load(): Promise<JsonObject> {
    return await this._request<JsonObject>("GET", this.path());
  }

  private path(suffix = ""): string {
    return `/v1/trash/${encodeURIComponent(String(this._known("id")))}${suffix}`;
  }

  /**
   * Put it back where it was, under its name, with everything in it; throws `Conflict` when
   * something new has taken its name since. A `database_copy` goes back into its database: a
   * restore of its own (its `operation`), which keeps what the database holds now as a copy the
   * same way. Returns the restored resource as its own API shows it.
   */
  async restore(): Promise<JsonObject> {
    return await this._request<JsonObject>("POST", this.path("/restore"));
  }

  /** Delete it for good now: the one deletion that can't be undone. */
  async purge(): Promise<void> {
    await this._request("DELETE", this.path());
  }
}

/**
 * What a deletion would do, in words a person reads before agreeing: what it `deletes`, what stops working
 * (`dependsOnIt`), the data that goes (`dataLost`), what stops being billed (`stopsBilling`), and whether it's
 * `reversible` and how (`undo`). Nothing is deleted by asking. `confirmToken` is what a call through MCP sends to
 * confirm it, within `expiresInS`.
 */
export interface DeletePreview {
  deletes: string;
  dependsOnIt: string[];
  dataLost: string[];
  stopsBilling: string[];
  reversible: boolean;
  undo: string | null;
  confirmToken: string | null;
  expiresInS: number | null;
  raw: JsonObject;
}

/** @internal A `POST /v1/delete_previews` answer as a `DeletePreview`. */
export function toDeletePreview(value: unknown): DeletePreview {
  const raw = (value && typeof value === "object" ? value : {}) as JsonObject;
  const impact = (raw.impact && typeof raw.impact === "object" ? raw.impact : {}) as JsonObject;
  const strings = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);
  return {
    deletes: typeof impact.deletes === "string" ? impact.deletes : "", dependsOnIt: strings(impact.depends_on_it),
    dataLost: strings(impact.data_lost), stopsBilling: strings(impact.stops_billing), reversible: impact.reversible === true,
    undo: typeof impact.undo === "string" ? impact.undo : null,
    confirmToken: typeof raw.confirm_token === "string" ? raw.confirm_token : null,
    expiresInS: typeof raw.expires_in_s === "number" ? raw.expires_in_s : null, raw,
  };
}

/** @internal The `TrashItem` a delete answered with, acting as the object that was deleted. */
export function trashed(raw: unknown, from: ApiObject): TrashItem {
  return TrashItem._fromDeleted(raw as JsonObject, { client: from._client, user: from._callScope() });
}
