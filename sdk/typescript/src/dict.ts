/**
 * Dicts: a key-value store for small state that code and agents share.
 *
 *     const seen = Dict.fromName("processed-orders", { createIfMissing: true });
 *     if (!(await seen.has("o_1841"))) await seen.put("o_1841", { status: "refunded" });
 *     console.log(await seen.increment("refunds-today"));
 *
 * Keys are strings and values are JSON, never a language's own serialization, so a value your
 * TypeScript writes reads the same from Python, an agent or the console.
 */

import { CONSOLE_BASE_URL, DEFAULT_BASE_URL } from "./client.ts";
import { TrashItem, trashed } from "./trash.ts";
import type { UsedBy } from "./database.ts";
import { Conflict, NotFound } from "./errors.ts";
import { toExportBundle } from "./export.ts";
import type { ExportBundle } from "./export.ts";
import { ApiObject, asList, asObject, compact, createNamed, fetchPage, listAll, listPage, num, paginate, parseTime, str } from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import type { PlacementOptions, RegionName } from "./region.ts";
import { Operation, registerResult } from "./operation.ts";
import { resolveScope } from "./scope.ts";

/**
 * One key of a dict as `items()` reads it: its value, when it expires (null if it doesn't),
 * when it was last written and the size of its value as JSON.
 */
export interface DictItem {
  key: string;
  value: unknown;
  expiresAt: Date | null;
  updatedAt: Date | null;
  sizeBytes: number | null;
  raw: JsonObject;
}

/**
 * One write to a dict, from its history: `op` is `created` (the key was new), `changed` or `deleted`,
 * and `previous` the value it replaced (null for a new key). A key changed again within a minute adds
 * none, so a busy key keeps one a minute.
 */
export interface DictChange {
  id: string;
  key: string;
  op: "created" | "changed" | "deleted";
  previous: unknown;
  previousExpiresAt: Date | null;
  at: Date | null;
  raw: JsonObject;
}

function toDictChange(value: unknown): DictChange {
  const raw = asObject(value);
  return {
    id: str(raw.id) ?? "", key: str(raw.key) ?? "", op: raw.op as DictChange["op"], previous: raw.previous ?? null,
    previousExpiresAt: parseTime(raw.previous_expires_at), at: parseTime(raw.at), raw,
  };
}

/** Expiry for a write: `ttlS` seconds from now. Without it a key stays until it's removed. */
export interface DictWriteOptions {
  ttlS?: number;
}

/** Which keys a listing covers: those starting with `prefix`, in key order. */
export interface DictListOptions {
  prefix?: string;
}

function toDictItem(value: unknown): DictItem {
  const raw = asObject(value);
  return {
    key: str(raw.key) ?? "",
    value: raw.value ?? null,
    expiresAt: parseTime(raw.expires_at),
    updatedAt: parseTime(raw.updated_at),
    sizeBytes: num(raw.size_bytes),
    raw,
  };
}

/** The value as it's stored: JSON, checked here so a bad value fails before it's sent. */
function json(value: unknown): unknown {
  if (value === undefined || typeof value === "function" || typeof value === "symbol" || typeof value === "bigint") {
    throw new TypeError(`A Dict stores JSON values, not ${typeof value}.`);
  }
  if (typeof value === "number" && !Number.isFinite(value)) throw new TypeError(`A Dict stores JSON values, not ${value}.`);
  return value;
}

function checkKey(key: string): string {
  if (typeof key !== "string" || !key) throw new TypeError("A Dict key is a non-empty string.");
  return key;
}

/** A 404 about the key (the dict exists) rather than about the dict. */
function missingKey(err: unknown, key: string): boolean {
  return err instanceof NotFound && err.details.key === key;
}

registerResult("dict.export", toExportBundle);

/**
 * A key-value store: string keys, JSON values, optional expiry per key. `get`, `put`, `has`,
 * `remove` and `size` are what Python writes as `d[key]`, `d[key] = value`, `key in d`,
 * `del d[key]` and `len(d)`; each is a call to the API, so two processes see each other's
 * writes at once. `Dict.fromName("processed-orders", { createIfMissing: true })` is lazy.
 * There's no `Dict.get(id)`, since `get` reads a key: `Dict.fromId(id).hydrate()` loads one.
 */
export class Dict extends ApiObject {
  private _createWith: JsonObject | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create a dict, unique by name per user (a taken name throws `Conflict` with `existingId`, or with
   * `allowExisting: true` returns the dict already there, as it is). `region` keeps its keys there for
   * good: `us-east` only for now (another, or a default elsewhere, throws `InvalidRequest`).
   */
  static async create(name: string, options: CallOptions & PlacementOptions & AllowExisting = {}): Promise<Dict> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/dicts", compact({ name, region: options.region }), {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new Dict({ raw, client: options.client, user: scope });
  }

  /** A lazy reference to the dict called `name`; with `createIfMissing` it's created on first use. */
  static fromName(name: string, options: CallOptions & PlacementOptions & { createIfMissing?: boolean } = {}): Dict {
    const store = new Dict({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing) store._createWith = compact({ name, region: options.region });
    return store;
  }

  /** A lazy reference by id; `await Dict.fromId(id).hydrate()` loads it now. */
  static fromId(dictId: string, options: CallOptions = {}): Dict {
    return new Dict({ hints: { id: dictId }, client: options.client, user: options.user });
  }

  /** The current user's dicts (or those `userFilter` covers), newest first. */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<Dict[]> {
    return await listAll({ ...options, path: "/v1/dicts" }, (raw, user) => new Dict({ raw, client: options.client, user }));
  }

  /** One page of dicts; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Dict>> {
    return await listPage({ ...options, path: "/v1/dicts" }, (raw, user) => new Dict({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** How many keys it holds, as of the last load; `size()` reads it fresh. */
  get keyCount(): number | null {
    return this._field("key_count");
  }
  /** The size of its keys and values as JSON. */
  get sizeBytes(): number | null {
    return this._field("size_bytes");
  }
  /** The apps that bind it. */
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
  /** This dict in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    if (this._api.baseUrl !== DEFAULT_BASE_URL) return null;
    return `${CONSOLE_BASE_URL}/resources/dicts?dict=${encodeURIComponent(String(this._known("id")))}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/dicts/${id}`);
    const name = String(this._hints.name);
    const found = await this._inApp("dict", name, this._createWith);
    if (found) return found;
    const row = (asList(await this._request("GET", "/v1/dicts", { query: { name } })) as JsonObject[]).find((r) => r.name === name);
    if (row) return row;
    if (!this._createWith) {
      throw new NotFound(`No dict is named "${name}".`, {
        nextStep: "Create it with Dict.create(...) or pass { createIfMissing: true }.",
        details: { name, kind: "dict" },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/dicts", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this._request<JsonObject>("GET", `/v1/dicts/${err.existingId}`);
    }
  }

  /** This dict's route; a reference by name is looked up (or created) first. */
  private async route(suffix = ""): Promise<string> {
    if (!this._known("id")) await this._ensure();
    return `/v1/dicts/${String(this._known("id"))}${suffix}`;
  }

  private async itemRoute(key: string, suffix = ""): Promise<string> {
    return await this.route(`/items/${encodeURIComponent(checkKey(key))}${suffix}`);
  }

  /** A key's value, or `undefined` when it's missing or expired (a stored `null` reads as `null`). */
  async get<T = unknown>(key: string): Promise<T | undefined> {
    try {
      return asObject(await this._request("GET", await this.itemRoute(key))).value as T;
    } catch (err) {
      if (missingKey(err, key)) return undefined;
      throw err;
    }
  }

  /** Whether the key is there (and hasn't expired). */
  async has(key: string): Promise<boolean> {
    try {
      await this._request("GET", await this.itemRoute(key));
      return true;
    } catch (err) {
      if (missingKey(err, key)) return false;
      throw err;
    }
  }

  /** Write a key. With `ttlS` it expires then; without, it stays until removed (and loses any expiry). */
  async put(key: string, value: unknown, options: DictWriteOptions = {}): Promise<void> {
    await this._request("PUT", await this.itemRoute(key), { json: { value: json(value), ...compact({ ttl_s: options.ttlS }) } });
  }

  /**
   * Write a key only if it isn't there, atomically: of any number of callers racing, exactly
   * one wins. A lock (with `ttlS`, so a crashed holder's lock frees itself) or a run-once check.
   * Whether this call wrote it.
   */
  async putIfAbsent(key: string, value: unknown, options: DictWriteOptions = {}): Promise<boolean> {
    const body = { value: json(value), if_absent: true, ...compact({ ttl_s: options.ttlS }) };
    return asObject(await this._request("PUT", await this.itemRoute(key), { json: body })).written === true;
  }

  /**
   * Add `by` (default 1, may be negative) to a counter, atomically; a missing key starts at 0.
   * `ttlS` sets its expiry only when this call creates it. The value after the increment.
   */
  async increment(key: string, options: DictWriteOptions & { by?: number } = {}): Promise<number> {
    const by = options.by ?? 1;
    if (!Number.isInteger(by)) throw new TypeError(`increment adds an integer, not ${by}.`);
    const raw = asObject(await this._request("POST", await this.itemRoute(key, "/increment"), { json: compact({ by, ttl_s: options.ttlS }) }));
    return Number(raw.value);
  }

  /** Write up to 1,000 keys in one call, all or none; `ttlS` applies to each. */
  async update(items: Readonly<Record<string, unknown>> | ReadonlyMap<string, unknown>, options: DictWriteOptions = {}): Promise<void> {
    const entries = items instanceof Map ? [...items.entries()] : Object.entries(items);
    const wire = entries.map(([key, value]) => ({ key: checkKey(key), value: json(value), ...compact({ ttl_s: options.ttlS }) }));
    await this._request("POST", await this.route("/items"), { json: { items: wire } });
  }

  /** Remove a key and return its value, or `undefined` if it wasn't there. */
  async pop<T = unknown>(key: string): Promise<T | undefined> {
    try {
      return asObject(await this._request("DELETE", await this.itemRoute(key))).value as T;
    } catch (err) {
      if (missingKey(err, key)) return undefined;
      throw err;
    }
  }

  /** Remove a key; whether it was there. (`delete()` deletes the whole dict.) */
  async remove(key: string): Promise<boolean> {
    try {
      await this._request("DELETE", await this.itemRoute(key));
      return true;
    } catch (err) {
      if (missingKey(err, key)) return false;
      throw err;
    }
  }

  /** How many keys it holds, read now. */
  async size(): Promise<number> {
    this._raw = await this._load();
    return num(this._raw.key_count) ?? 0;
  }

  private async *walk(prefix: string | undefined, keysOnly: boolean, limit: number | undefined): AsyncGenerator<JsonObject> {
    const path = await this.route("/items");
    let cursor: string | null = null;
    let count = 0;
    for (;;) {
      const size = limit === undefined ? undefined : Math.min(limit - count, 100);
      const page = await fetchPage(this._api, path, {
        query: { prefix, view: keysOnly ? "keys" : undefined }, user: this._callScope() ?? null, cursor, limit: size,
      });
      for (const row of page.data) {
        yield row;
        if (limit !== undefined && ++count >= limit) return;
      }
      if (!page.nextCursor) return;
      cursor = page.nextCursor;
    }
  }

  /** The keys in order (or those starting with `prefix`), fetched page by page. */
  async keys(options: DictListOptions & { limit?: number } = {}): Promise<string[]> {
    const keys: string[] = [];
    for await (const row of this.walk(options.prefix, true, options.limit)) keys.push(String(row.key));
    return keys;
  }

  /** The keys and their values, in key order (or those starting with `prefix`), with each key's expiry. */
  async items(options: DictListOptions & { limit?: number } = {}): Promise<DictItem[]> {
    const items: DictItem[] = [];
    for await (const row of this.walk(options.prefix, false, options.limit)) items.push(toDictItem(row));
    return items;
  }

  /** One page of items in key order; pass `nextCursor` back as `cursor`. */
  async itemsPage(options: DictListOptions & PageOptions = {}): Promise<Page<DictItem>> {
    const page = await fetchPage(this._api, await this.route("/items"), {
      query: { prefix: options.prefix }, user: this._callScope() ?? null, cursor: options.cursor, limit: options.limit,
    });
    return { data: page.data.map(toDictItem), nextCursor: page.nextCursor };
  }

  /** Remove every key; the dict stays, empty. Its operation's `undo()` puts back what it removed. */
  async clear(): Promise<Operation> {
    const raw = asObject(await this._request("POST", await this.route("/clear")));
    return Operation.fromId(String(raw.operation_id), { client: this._client, user: this._callScope() });
  }

  /** Its writes of the last 30 days, newest first, each with the value it replaced; `key` keeps one key's. */
  async history(key?: string, options: { limit?: number } = {}): Promise<DictChange[]> {
    const rows = await paginate(this._api, await this.route("/history"), {
      query: { key }, user: this._callScope() ?? null, limit: options.limit,
    });
    return rows.map(toDictChange);
  }

  /**
   * Put the key back as `change` found it: the value it replaced, or gone, when the change created
   * the key. A value that has expired since throws `Conflict`.
   */
  async restoreChange(change: DictChange | string): Promise<void> {
    const id = typeof change === "string" ? change : change.id;
    await this._request("POST", await this.route(`/history/${encodeURIComponent(id)}/restore`));
  }

  /**
   * Export every key as it stands at one moment, as JSON Lines: one `{"key", "value", "expires_at"}`
   * per line, in key order. `wait()` resolves to an `ExportBundle`: a zip at `url` holding the file.
   */
  async export(): Promise<Operation<ExportBundle>> {
    const payload = await this._request("POST", await this.route("/export"));
    return Operation._fromPayload<ExportBundle>(payload, { client: this._client, user: this._callScope(), kind: "dict.export", reader: toExportBundle });
  }

  /**
   * Delete the dict and every key in it: it goes to the trash, restorable for 30 days. One an app
   * binds goes to the trash too: the app keeps its binding, reaching nothing until you restore the
   * dict. Returns its `TrashItem`: `restore()` puts it back, keys and all.
   */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this.route()), this);
  }
}
