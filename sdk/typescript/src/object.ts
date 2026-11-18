/**
 * Base for live API objects: lazy hydration, scope capture, `raw`.
 *
 * An object can exist before the server has been asked about it
 * (`User.fromId(...)`, `Agent.fromName(...)`, `Operation.fromId(...)`).
 * `await obj.hydrate()` loads it; methods hydrate on their own. Reading a
 * property the local hints can't answer before then throws.
 */

import { resolveClient } from "./client.ts";
import type { NoClick, QueryValue, RequestOptions } from "./client.ts";
import { Conflict, NoClickError, NotFound } from "./errors.ts";
import type { JsonObject } from "./errors.ts";
import { resolveScope, userFilterParam } from "./scope.ts";
import type { UserFilter, UserOption, UserRef } from "./scope.ts";

export type { JsonObject };

export interface ObjectInit {
  raw?: JsonObject | null;
  hints?: JsonObject;
  client?: NoClick;
  user?: UserOption;
}

/** Options every call accepts: the client and the user it acts for. */
export interface CallOptions {
  client?: NoClick;
  /** `undefined` = the ambient user (`asUser`), `null` = the account itself. */
  user?: UserOption;
}

export function parseTime(value: unknown): Date | null {
  if (typeof value !== "string") return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Drop `undefined` and `null` (fields that weren't given). */
export function compact(fields: JsonObject): JsonObject {
  const out: JsonObject = {};
  for (const [key, value] of Object.entries(fields)) if (value !== undefined && value !== null) out[key] = value;
  return out;
}

/** Drop only `undefined` (`null` clears a field in a PATCH). */
export function defined(fields: JsonObject): JsonObject {
  const out: JsonObject = {};
  for (const [key, value] of Object.entries(fields)) if (value !== undefined) out[key] = value;
  return out;
}

export function asObject(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonObject) : {};
}

export function asList(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  const data = asObject(value).data;
  return Array.isArray(data) ? data : [];
}

/** @internal Bytes as base64, for a JSON body. */
export function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

export function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function num(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

/** A number the API always sends; its absence is a malformed response, never a zero. */
export function requiredNumber(obj: JsonObject, key: string): number {
  const value = obj[key];
  if (typeof value !== "number") {
    throw new NoClickError(`The response is missing the number \`${key}\`.`, { details: { field: key, value: value ?? null } });
  }
  return value;
}

export abstract class ApiObject {
  /** Owned objects act for the user they were obtained under; catalog objects follow each call. */
  protected static capturesScope = true;

  /** @internal */ _raw: JsonObject | null;
  /** @internal */ _hints: JsonObject;
  /** @internal */ _client: NoClick | undefined;
  /** @internal `undefined` only for non-capturing objects: follow the ambient user. */
  _scope: UserOption;
  /** @internal Whether `fromName` creates the object when it's missing (`createIfMissing`). */
  _creates = false;

  constructor(init: ObjectInit) {
    this._raw = init.raw ?? null;
    this._hints = { ...(init.hints ?? {}) };
    this._client = init.client;
    const captures = (this.constructor as typeof ApiObject).capturesScope;
    this._scope = captures ? resolveScope(init.user) : init.user;
  }

  protected abstract _load(): Promise<JsonObject>;

  /** @internal */
  get _api(): NoClick {
    return resolveClient(this._client);
  }

  /**
   * @internal The user `owner` (a `user_id` the API sent) names for this object's calls to carry. None
   * from a deployed app's own code: its credential acts for the app's own user without naming one.
   */
  _ownerScope(owner: unknown): string | null {
    return typeof owner === "string" && owner && !this._api.inApp ? owner : null;
  }

  /** @internal The user this object's own calls carry. */
  _callScope(): UserOption {
    return this._ownerScope(this._raw?.user_id) ?? this._scope;
  }

  /** @internal */
  _request<T = unknown>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const user = options.user !== undefined ? options.user : this._callScope();
    return this._api.request<T>(method, path, { ...options, user });
  }

  /**
   * @internal Inside a deployed app, the `kind` called `name` for the environment its code runs in (a
   * preview branch's own, when its app gives branches their own), made on first use when `createWith`
   * says how, with what else the lookup takes (`resolving`, a database's `branch_data`); null outside one.
   */
  protected async _inApp(kind: string, name: string, createWith: JsonObject | null, resolving: JsonObject = {}): Promise<JsonObject | null> {
    if (!this._api.inApp) return null;
    const { name: _, ...made } = createWith ?? {};
    return await this._request<JsonObject>("POST", "/v1/projects/current/resources", {
      json: { kind, name, create_if_missing: createWith !== null, ...made, ...compact(resolving) },
    });
  }

  /** @internal */
  async _ensure(): Promise<JsonObject> {
    this._raw ??= await this._load();
    return this._raw;
  }

  /** @internal A known value (raw first, then hints), or undefined. */
  _known(key: string): unknown {
    if (this._raw && key in this._raw) return this._raw[key];
    return this._hints[key];
  }

  protected _field<T>(key: string): T {
    if (this._raw && key in this._raw) return this._raw[key] as T;
    if (key in this._hints) return this._hints[key] as T;
    if (this._raw) return null as T;
    throw new Error(`${this.constructor.name}.${key} is not loaded yet: await it.hydrate() first.`);
  }

  get isHydrated(): boolean {
    return this._raw !== null;
  }

  /** The server's JSON for this object (throws until hydrated). */
  get raw(): JsonObject {
    if (!this._raw) throw new Error(`${this.constructor.name} is not loaded yet: await it.hydrate() first.`);
    return this._raw;
  }

  /** Load the object from the server if it hasn't been yet. */
  async hydrate(): Promise<this> {
    await this._ensure();
    return this;
  }

  /** Re-fetch the object's current state. */
  async refresh(): Promise<this> {
    this._raw = await this._load();
    return this;
  }

  toJSON(): JsonObject {
    return this._raw ?? this._hints;
  }
}

const UUID_RE = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;

/** @internal Whether a string is a NoClick object id (a UUID) rather than a name. */
export function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

/** @internal The id of an object (loading a lazy one) or an id string. */
export async function refId(ref: string | ApiObject | undefined): Promise<string | undefined> {
  if (ref === undefined || typeof ref === "string") return ref;
  const known = ref._known("id");
  return typeof known === "string" ? known : String((await ref._ensure()).id);
}

/**
 * @internal Whether `fromName` was given fields: any option but the call's own (`client`, `user`,
 * `createIfMissing`) and those that only say where to look (`lookup`). `null` is one: it clears the field.
 * Given fields, `fromName` sets them on the object it finds; without any, it only looks the object up.
 */
export function givesFields(options: object, lookup: readonly string[] = []): boolean {
  const call = ["client", "user", "createIfMissing", ...lookup];
  return Object.entries(options).some(([key, value]) => value !== undefined && !call.includes(key));
}

/** `create`'s option to take an existing object of the name: it's returned as it is, unchanged. */
export interface AllowExisting {
  /** A taken name returns the object already there, as it is: nothing about it changes. */
  allowExisting?: boolean;
}

/**
 * @internal `create`: POST `body` to `path`. With `allowExisting`, a `key` already taken (the API's `Conflict`
 * naming `existing_id`) answers that object as it is, unchanged.
 */
export async function createNamed(
  path: string,
  body: JsonObject,
  options: AllowExisting & {
    user: UserRef | null;
    client?: NoClick;
    key?: string;
    existingPath?: (id: string) => string;
    idempotencyKey?: string;
  },
): Promise<JsonObject> {
  const api = resolveClient(options.client);
  const key = options.key ?? "name";
  try {
    return await api.request<JsonObject>("POST", path, { json: body, user: options.user, idempotencyKey: options.idempotencyKey });
  } catch (err) {
    if (!options.allowExisting || !(err instanceof Conflict) || !err.existingId) throw err;
    // Another conflict than the name being taken (its existing_id names something else) stays one.
    const found = await api
      .request<JsonObject>("GET", options.existingPath?.(err.existingId) ?? `${path}/${err.existingId}`, { user: options.user })
      .catch((read: unknown) => {
        throw read instanceof NotFound ? err : read;
      });
    if (found[key] !== body[key]) throw err;
    return found;
  }
}

/**
 * @internal `fromName` on an existing object: each argument it can't set (`given`, keyed as the API's view
 * names the field) must match what the object has, so none is ever ignored.
 */
export function checkUnchanged(kind: string, raw: JsonObject, given: JsonObject, nextStep?: string): void {
  for (const [key, wanted] of Object.entries(given)) {
    if (wanted === undefined) continue;
    const have = raw[key] ?? null;
    if (JSON.stringify(have) === JSON.stringify(wanted)) continue;
    const label = JSON.stringify(raw.name ?? raw.id);
    throw new Conflict(
      `The ${kind} ${label} already exists with ${key} ${JSON.stringify(have)}, which fromName can't change to ${JSON.stringify(wanted)}.`,
      {
        nextStep: nextStep ?? `Leave ${key} out to use it as it is, or use another name.`,
        details: { existing_id: raw.id ?? null, field: key, [key]: have },
      },
    );
  }
}

/** The largest page the /v1 list routes serve. */
export const MAX_PAGE_SIZE = 100;

/** One page of a listing; pass `nextCursor` back as `cursor` for the next (null = the last page). */
export interface Page<T> {
  data: T[];
  nextCursor: string | null;
}

/**
 * Where a page starts and how many rows it holds. `limit` must be at most `MAX_PAGE_SIZE`
 * (200 on tool calls, requests and message listings); the server refuses a larger one, never caps it.
 */
export interface PageOptions {
  cursor?: string | null;
  limit?: number;
}

/** Options every list read accepts: the client, the user it acts for, or a `userFilter`. */
export interface ReadOptions extends CallOptions {
  /** Which users the read covers (`user_id` query), instead of acting as one (`user`). */
  userFilter?: UserFilter;
}

/**
 * @internal What a read carries: a filtered read is account-level (no user header) and
 * names its users in `user_id`; otherwise the call acts for its user as usual.
 */
export async function readScope(options: ReadOptions): Promise<{ user: UserRef | null; userId: string | undefined }> {
  if (options.userFilter === undefined) return { user: resolveScope(options.user), userId: undefined };
  if (options.user !== undefined) {
    throw new TypeError("Pass user (who the call acts as) or userFilter (which users a read covers), not both.");
  }
  return { user: null, userId: await userFilterParam(options.userFilter) };
}

/** @internal A comma list from one value or several. */
export function csv(value: string | readonly string[] | undefined): string | undefined {
  if (value === undefined) return undefined;
  return typeof value === "string" ? value : value.join(",");
}

/** @internal An ISO timestamp from a `Date` or a string already in that form. */
export function isoTime(value: Date | string | undefined): string | undefined {
  return value instanceof Date ? value.toISOString() : value;
}

/** One page of a `{"object": "list", "data", "next_cursor"}` listing. */
export async function fetchPage(
  client: NoClick,
  path: string,
  options: { query?: Record<string, QueryValue>; user: UserRef | null } & PageOptions,
): Promise<Page<JsonObject>> {
  const query: Record<string, QueryValue> = { ...(options.query ?? {}), cursor: options.cursor, limit: options.limit };
  const page = asObject(await client.request("GET", path, { query, user: options.user }));
  const cursor = page.next_cursor;
  return { data: asList(page) as JsonObject[], nextCursor: cursor ? String(cursor) : null };
}

/** Every item of a listing, or the first `limit`, in pages of at most `MAX_PAGE_SIZE`. */
export async function paginate(
  client: NoClick,
  path: string,
  options: { query?: Record<string, QueryValue>; user: UserRef | null; limit?: number },
): Promise<JsonObject[]> {
  const items: JsonObject[] = [];
  let cursor: string | null = null;
  for (;;) {
    const limit = options.limit === undefined ? undefined : Math.min(options.limit - items.length, MAX_PAGE_SIZE);
    const page = await fetchPage(client, path, { query: options.query, user: options.user, cursor, limit });
    items.push(...page.data);
    if (options.limit !== undefined && items.length >= options.limit) return items.slice(0, options.limit);
    if (!page.nextCursor) return items;
    cursor = page.nextCursor;
  }
}

/** @internal One list route, read with a `userFilter` or as the call's user. */
export interface ListCall extends ReadOptions {
  path: string;
  query?: Record<string, QueryValue>;
}

type Build<T> = (raw: JsonObject, user: UserRef | null) => T;

async function prepared(call: ListCall): Promise<{ client: NoClick; query: Record<string, QueryValue>; user: UserRef | null }> {
  const { user, userId } = await readScope(call);
  return { client: resolveClient(call.client), query: { ...(call.query ?? {}), user_id: userId }, user };
}

/** @internal `X.list()`: every row (or the first `limit`) built into objects. */
export async function listAll<T>(call: ListCall & { limit?: number }, build: Build<T>): Promise<T[]> {
  const { client, query, user } = await prepared(call);
  return (await paginate(client, call.path, { query, user, limit: call.limit })).map((raw) => build(raw, user));
}

/** @internal `X.listPage()`: one page built into objects. */
export async function listPage<T>(call: ListCall & PageOptions, build: Build<T>): Promise<Page<T>> {
  const { client, query, user } = await prepared(call);
  const page = await fetchPage(client, call.path, { query, user, cursor: call.cursor, limit: call.limit });
  return { data: page.data.map((raw) => build(raw, user)), nextCursor: page.nextCursor };
}

const TEMPLATE = /\{\{(.*?)\}\}/g;
const USER_TEMPLATE = /^\s*user\.(id|email|name|metadata\.[A-Za-z0-9_-]+)\s*$/;

/**
 * @internal `bind(arguments)` checked: every `{{...}}` in a value names the user's `id`, `email`,
 * `name` or one `metadata` key.
 */
export function boundArguments(args: JsonObject): JsonObject {
  if (!Object.keys(args).length) throw new TypeError("bind() takes at least one argument: bind({ to: \"{{user.email}}\" })");
  const check = (value: unknown): void => {
    if (typeof value === "string") {
      for (const [, template] of value.matchAll(TEMPLATE)) {
        if (!USER_TEMPLATE.test(template)) {
          throw new TypeError(`{{${template}}} isn't something NoClick fills in; use {{user.id}}, {{user.email}}, {{user.name}} or {{user.metadata.<key>}}`);
        }
      }
    } else if (Array.isArray(value)) value.forEach(check);
    else if (value && typeof value === "object") Object.values(value).forEach(check);
  };
  Object.values(args).forEach(check);
  return { ...args };
}

/** @internal `tools` on the wire for some operations of one ref: `"<base>.<op>"`, or `{ tool, bind }` when arguments are bound. */
export function toolEntries(base: string, operations: readonly string[], bindings: JsonObject): (string | JsonObject)[] {
  if (!Object.keys(bindings).length) return operations.map((op) => `${base}.${op}`);
  return operations.map((op) => ({ tool: `${base}.${op}`, bind: { ...bindings } }));
}
