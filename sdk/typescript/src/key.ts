/**
 * Keys: one of your account's own keys makes another for your code, no wider than itself.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, defined, fetchPage, num, paginate, parseTime, str } from "./object.ts";
import type { JsonObject, Page, PageOptions } from "./object.ts";

/** A public endpoint a publishable key may call, by its `kind` and `id` (`Account.publicEndpoints()` lists them). */
export interface PublicEndpointRef {
  kind: string;
  id: string;
}

/** What a publishable key may call, and how hard its visitors may call it. */
export interface PublicAccess {
  publicEndpoints?: PublicEndpointRef[];
  /** Calls one visitor may make a minute. */
  perVisitorLimitPerMinute?: number;
  /** The web origins that may use it (none: any). */
  allowedOrigins?: string[];
}

/** What `Key.create` makes beside its name and scopes. */
export interface KeyOptions extends PublicAccess {
  /** `secret` (the default) acts for the account; `publishable` (the signed-in owner's to make) only calls its public
   *  endpoints, from a web page, and takes no scopes. */
  type?: "secret" | "publishable";
  /** A monthly cap: required (at most its own) when the key making it has one. */
  spendCapUsdPerMonth?: number;
  /** When it expires: required (no later than its own) when the key making it expires. */
  expiresAt?: Date;
  /** Pins it to one of your users: it acts only for them. */
  userId?: string;
  client?: NoClick;
}

/**
 * A platform secret key of your account's: its `id`, `name`, `scopes`, monthly cap, expiry, the user it's pinned to
 * (`userId`) and the key that made it (`mintedBy`; `null` for one the owner made). `secret` is the key itself
 * (`nk_live_...`): `Key.create` returns it once, and nothing shows it again.
 */
export class Key {
  readonly id: string;
  readonly name: string;
  readonly scopes: string[];
  readonly spendCapUsdPerMonth: number | null;
  readonly expiresAt: Date | null;
  readonly userId: string | null;
  readonly mintedBy: string | null;
  /** `secret` or `publishable`. */
  readonly type: string;
  /** What shows of it everywhere: `nk_live_ab12`. */
  readonly keyPrefix: string | null;
  readonly createdAt: Date | null;
  readonly lastUsedAt: Date | null;
  readonly revokedAt: Date | null;
  readonly secret: string | null;
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.id = str(raw.id) ?? "";
    this.name = str(raw.name) ?? "";
    this.scopes = asList(raw.scopes).map(String);
    this.spendCapUsdPerMonth = num(raw.spend_cap_usd_per_month);
    this.expiresAt = parseTime(raw.expires_at);
    this.userId = str(raw.user_id);
    this.mintedBy = str(raw.minted_by);
    this.type = str(raw.type) ?? "secret";
    this.keyPrefix = str(raw.key_prefix);
    this.createdAt = parseTime(raw.created_at);
    this.lastUsedAt = parseTime(raw.last_used_at);
    this.revokedAt = parseTime(raw.revoked_at);
    this.secret = str(raw.raw_key);
    this.raw = Object.fromEntries(Object.entries(raw).filter(([field]) => field !== "raw_key"));
  }

  /**
   * Make a secret key from your server, with one of your account's own keys that names the `keys:create` scope (a key
   * with every scope, `*`, holds it only when it's named too). The new key is no wider than the one making it: only
   * scopes it holds itself (`*` only from a key holding `*`), a monthly cap when it has one, at most its own, an
   * expiry when it has one, no later, and the approval settings it set for itself. It names the key that made it
   * (`mintedBy`) and never outlives it: revoking a key revokes every key it made, and theirs. A key without
   * `keys:create`, one acting for a user, or a key wider than the one making it rejects with `PermissionDenied`
   * (its `field` names what). Signed in, the account's owner makes any key.
   *
   *     const worker = await Key.create("queue worker", ["queues", "agents"], { spendCapUsdPerMonth: 20 });
   *     process.env.WORKER_KEY = worker.secret!;
   */
  static async create(name: string, scopes: string[], options: KeyOptions = {}): Promise<Key> {
    const body: JsonObject = { name, scopes: [...scopes] };
    if (options.type !== undefined) body.type = options.type;
    if (options.spendCapUsdPerMonth !== undefined) body.spend_cap_usd_per_month = options.spendCapUsdPerMonth;
    if (options.expiresAt !== undefined) body.expires_at = options.expiresAt.toISOString();
    if (options.userId !== undefined) body.user_id = options.userId;
    Object.assign(body, publicAccessWire(options));
    const raw = await resolveClient(options.client).request("POST", "/v1/keys", { json: body, user: null });
    return new Key(asObject(raw));
  }

  /**
   * Every key of the account, newest first (`status`: `active`, `revoked` or `all`, the default), each with what it
   * spent this month (`raw.spent_usd_this_month`). The signed-in owner's alone.
   *
   *     for (const key of await Key.list({ status: "active" })) console.log(key.name, key.keyPrefix);
   */
  static async list(options: { status?: KeyStatus; limit?: number; client?: NoClick } = {}): Promise<Key[]> {
    const rows = await paginate(resolveClient(options.client), "/v1/keys", {
      query: { status: options.status }, user: null, limit: options.limit,
    });
    return rows.map((raw) => new Key(raw));
  }

  /** One page of `list()`; pass `nextCursor` back as `cursor`. */
  static async listPage(options: PageOptions & { status?: KeyStatus; client?: NoClick } = {}): Promise<Page<Key>> {
    const page = await fetchPage(resolveClient(options.client), "/v1/keys", {
      query: { status: options.status }, user: null, cursor: options.cursor, limit: options.limit,
    });
    return { data: page.data.map((raw) => new Key(raw)), nextCursor: page.nextCursor };
  }

  /**
   * Change a key: its `name`, its monthly cap (`null` removes it) and a publishable key's endpoints, visitor limit and
   * origins; only the fields given. The signed-in owner's alone (a key's own approval settings: `Approval.setForKey`).
   *
   *     await Key.update(key.id, { name: "queue worker (prod)", spendCapUsdPerMonth: 50 });
   */
  static async update(
    keyId: string, changes: PublicAccess & { name?: string; spendCapUsdPerMonth?: number | null }, options: { client?: NoClick } = {},
  ): Promise<Key> {
    const json = { ...defined({ name: changes.name, spend_cap_usd_per_month: changes.spendCapUsdPerMonth }), ...publicAccessWire(changes) };
    return new Key(asObject(await resolveClient(options.client).request("PATCH", `/v1/keys/${encodeURIComponent(keyId)}`, { json, user: null })));
  }

  /**
   * Revoke a key: its next call fails, and every key it made is revoked with it. The signed-in owner's alone. Resolves
   * to the key, with `revokedAt` set.
   *
   *     await Key.revoke(key.id);
   */
  static async revoke(keyId: string, options: { client?: NoClick } = {}): Promise<Key> {
    return new Key(asObject(await resolveClient(options.client).request("DELETE", `/v1/keys/${encodeURIComponent(keyId)}`, { user: null })));
  }

  /**
   * A one-time setup code (`nc_setup_...`, 30 minutes) a coding agent redeems for a key of the account
   * (`noclick setup <code>`, or `POST /v1/setup`), so the key lands in its project, never in its context. The signed-in
   * owner's alone.
   *
   *     const { code } = await Key.setupCode();
   */
  static async setupCode(options: { client?: NoClick } = {}): Promise<SetupCode> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/cli/setup_codes", { user: null }));
    return { code: str(raw.code) ?? "", keyName: str(raw.key_name) ?? "", expiresAt: parseTime(raw.expires_at), raw };
  }

  /** Revoke the key the client signs in with (a sign-out): every later call with it is refused. */
  static async revokeCurrent(options: { client?: NoClick } = {}): Promise<void> {
    await resolveClient(options.client).request("DELETE", "/v1/keys/current", { user: null });
  }

  /**
   * Redeem a one-time setup code (`nc_setup_...`, which the console's quickstart hands a coding agent) for a key of
   * the account, once, with no key of your own: its `secret` shown this once, with its `id` and `name`
   * (`raw.email` is the account's). Keep it out of anything you print.
   *
   *     const key = await Key.redeemSetupCode("nc_setup_...");
   *     const client = new NoClick({ apiKey: key.secret! });
   */
  static async redeemSetupCode(code: string, options: { client?: NoClick } = {}): Promise<Key> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/setup", {
      body: new URLSearchParams({ code }).toString(), contentType: "application/x-www-form-urlencoded", user: null,
      anonymous: true,
    }));
    const { key, ...rest } = raw;
    return new Key({ ...rest, id: raw.key_id, name: raw.key_name, raw_key: key } as JsonObject);
  }
}

/** Which keys `Key.list` reads. */
export type KeyStatus = "active" | "revoked" | "all";

/** A setup code (`Key.setupCode`): the `code`, the name of the key it becomes, and when it lapses. */
export interface SetupCode {
  code: string;
  keyName: string;
  expiresAt: Date | null;
  raw: JsonObject;
}

function publicAccessWire(access: PublicAccess): JsonObject {
  return defined({
    public_endpoints: access.publicEndpoints?.map((e) => ({ kind: e.kind, id: e.id })),
    per_visitor_limit_per_minute: access.perVisitorLimitPerMinute, allowed_origins: access.allowedOrigins,
  });
}
