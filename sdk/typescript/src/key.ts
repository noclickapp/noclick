/**
 * Keys: one of your account's own keys makes another for your code, no wider than itself.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, num, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** What `Key.create` makes beside its name and scopes. */
export interface KeyOptions {
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
    if (options.spendCapUsdPerMonth !== undefined) body.spend_cap_usd_per_month = options.spendCapUsdPerMonth;
    if (options.expiresAt !== undefined) body.expires_at = options.expiresAt.toISOString();
    if (options.userId !== undefined) body.user_id = options.userId;
    const raw = await resolveClient(options.client).request("POST", "/v1/keys", { json: body, user: null });
    return new Key(asObject(raw));
  }
}
