/**
 * Your account: its plan, balance, month's spend, counts, limits and defaults (`Account.get`), changing its defaults
 * (`update`), the account at a glance with what waits and what failed (`status`), the public endpoints a publishable
 * key may call, what an id or key prefix names (`resolve`), and a one-tap payment link for its owner.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, compact, defined, num, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** What a reading call takes: another client, and a signal to stop waiting. */
export interface AccountCallOptions {
  client?: NoClick;
  signal?: AbortSignal;
}

/** What a paused user is told when a pause names no message, and the button with it. */
export interface PausedSpendingDefault {
  message: string | null;
  action: { label: string; url: string } | null;
}

/** What `Account.update` changes: only the fields given; `null` clears one. */
export interface AccountChanges {
  /** The region new resources take when a call names none; `null` clears it. */
  defaultRegion?: string | null;
  /** What a paused user is told when their spending is paused without a message; `null` removes it. */
  spendingPaused?: PausedSpendingDefault | null;
  /** The monthly spending cap in whole dollars; `null` removes it. Only the signed-in owner sets, raises or removes it. */
  spendCapUsd?: number | null;
}

/**
 * The account at a glance (`GET /v1/account`): its plan's `planTier`, `balance` (`remaining_usd`, null when it can't
 * be read, never 0), this `month`'s spend, how many of each thing it has (`counts`), its `limits` and `features`, its
 * `defaultRegion` and the default a paused user is told (`spendingPaused`), and what the platform offers (`scopes`,
 * `explicitScopes`). The signed-in owner also reads `email`, `spendCap` and `consoleKeyId`; one of the account's own
 * secret keys reads the rest.
 */
export class Account {
  readonly id: string;
  readonly email: string | null;
  /** Who owns it, as NoClick knows them (`name`, `email`, `phone`, each only when known): the signed-in owner's view only. */
  readonly owner: { name?: string; email?: string; phone?: string } | null;
  readonly planTier: string | null;
  readonly balance: JsonObject;
  readonly month: JsonObject;
  readonly spendCap: JsonObject | null;
  readonly counts: Record<string, number>;
  readonly limits: Record<string, number>;
  readonly features: Record<string, boolean>;
  readonly defaultRegion: string | null;
  readonly spendingPaused: PausedSpendingDefault | null;
  readonly consoleKeyId: string | null;
  /** What a key with every scope (`*`) holds. */
  readonly scopes: string[];
  /** The scopes a key holds only when it names them. */
  readonly explicitScopes: string[];
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    const meta = asObject(raw.meta);
    const paused = raw.spending_paused ? asObject(raw.spending_paused) : null;
    this.id = String(raw.id ?? "");
    this.email = str(raw.email);
    this.owner = raw.owner ? (asObject(raw.owner) as { name?: string; email?: string; phone?: string }) : null;
    this.planTier = str(asObject(raw.plan).tier);
    this.balance = asObject(raw.balance);
    this.month = asObject(raw.month);
    this.spendCap = raw.spend_cap ? asObject(raw.spend_cap) : null;
    this.counts = asObject(raw.counts) as Record<string, number>;
    this.limits = asObject(raw.limits) as Record<string, number>;
    this.features = asObject(raw.features) as Record<string, boolean>;
    this.defaultRegion = str(raw.default_region);
    this.spendingPaused = paused
      ? { message: str(paused.message), action: paused.action ? (asObject(paused.action) as { label: string; url: string }) : null }
      : null;
    this.consoleKeyId = str(raw.console_key_id);
    this.scopes = asList(meta.scopes).map(String);
    this.explicitScopes = asList(meta.explicit_scopes).map(String);
    this.raw = raw;
  }

  /**
   * Read the account: the signed-in owner, or one of the account's own secret keys acting for it (a key acting for one
   * of its users is refused with `PermissionDenied`).
   *
   *     const account = await Account.get();
   *     console.log(account.planTier, account.balance.remaining_usd);
   */
  static async get(options: AccountCallOptions = {}): Promise<Account> {
    return new Account(asObject(await resolveClient(options.client).request("GET", "/v1/account", { user: null, signal: options.signal })));
  }

  /**
   * Change the account's defaults: only the fields given; `null` clears one. The signed-in owner's alone. Resolves to
   * the account as it is now.
   *
   *     await Account.update({ defaultRegion: "eu", spendCapUsd: 200 });
   */
  static async update(changes: AccountChanges, options: { client?: NoClick } = {}): Promise<Account> {
    const json = defined({
      default_region: changes.defaultRegion, spending_paused: changes.spendingPaused, spend_cap_usd: changes.spendCapUsd,
    });
    return new Account(asObject(await resolveClient(options.client).request("PATCH", "/v1/account", { json, user: null })));
  }

  /**
   * The account at a glance, as the key calling sees it: which account (or which of its users the key acts for), its
   * plan, balance, this month's spend against its caps, approvals waiting on a person, what failed in the last day and
   * what ran last. A user's session is refused.
   *
   *     const status = await Account.status();
   *     console.log(status.account.name ?? status.account.id, status.balance.remaining_usd);
   */
  static async status(options: AccountCallOptions = {}): Promise<AccountStatus> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/status", { signal: options.signal }));
    return {
      account: asObject(raw.account), userId: str(raw.user_id), plan: raw.plan ? asObject(raw.plan) : null,
      balance: asObject(raw.balance), month: asObject(raw.month), caps: asList(raw.caps).map(asObject),
      approvalsPending: asList(raw.approvals_pending).map(asObject), failing: asList(raw.failing).map(asObject),
      operations: asObject(raw.operations), raw,
    };
  }

  /**
   * What a publishable key may list: the account's public endpoints (a shared agent's page, a published workflow), each
   * by `kind` and `id`. The signed-in owner's alone.
   *
   *     for (const endpoint of await Account.publicEndpoints()) console.log(endpoint.kind, endpoint.name, endpoint.url);
   */
  static async publicEndpoints(options: AccountCallOptions = {}): Promise<PublicEndpoint[]> {
    const page = await resolveClient(options.client).request("GET", "/v1/public_endpoints", { user: null, signal: options.signal });
    return asList(page).map((value) => toPublicEndpoint(asObject(value)));
  }

  /**
   * What `ref` names in the account: an object's id, a key's prefix (`nk_live_ab12…`) or one of your users' ids,
   * resolved to its `type` and `id` (and the user it belongs to). Nothing it names rejects with `NotFound`. The
   * signed-in owner's alone.
   *
   *     const found = await Account.resolve("nk_live_ab12");
   *     console.log(found.type, found.id);
   */
  static async resolve(ref: string, options: AccountCallOptions = {}): Promise<ObjectRef> {
    const raw = asObject(await resolveClient(options.client).request("GET", `/v1/objects/${encodeURIComponent(ref)}`, {
      user: null, signal: options.signal,
    }));
    return { type: str(raw.type) ?? "", id: str(raw.id) ?? "", userId: str(raw.user_id), raw };
  }

  /**
   * A one-tap link that pays for the account, made for its owner to open: funds for its balance (`amountUsd`, whole
   * dollars; the plan's fee is paid with them), or a `plan` to move to. Opening it needs no sign-in, so only the
   * signed-in owner and the account's assistant make one. Its operation (`operationId`) succeeds once they've paid;
   * the same purchase asked for again while its link is open answers that link.
   *
   *     const link = await Account.paymentLink({ kind: "funds", amountUsd: 20 });
   *     console.log(link.priceUsd, link.url);
   */
  static async paymentLink(
    request: { kind?: "funds" | "plan" | "topup"; amountUsd?: number; plan?: string; billingPeriod?: "monthly" | "yearly"; creditsPerMonth?: number },
    options: { client?: NoClick } = {},
  ): Promise<PaymentLink> {
    const json = compact({
      kind: request.kind ?? "funds", amount_usd: request.amountUsd, plan: request.plan, billing_period: request.billingPeriod,
      credits_per_month: request.creditsPerMonth,
    });
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/account/payment_links", { json, user: null }));
    return {
      kind: str(raw.kind) ?? "", label: str(raw.label) ?? "", priceUsd: num(raw.price_usd) ?? 0, url: str(raw.url) ?? "",
      expiresAt: parseTime(raw.expires_at), operationId: str(raw.operation_id), raw,
    };
  }
}

/**
 * The account at a glance (`Account.status`): `account` (its `id`, `name`, `email`, or `acting_for`: the user a key
 * acts for), `userId`, its `plan`, `balance`, `month`, `caps` with what each spent, the approvals waiting on a
 * person (`approvalsPending`), what failed in the last day (`failing`) and what ran last (`operations`).
 */
export interface AccountStatus {
  account: JsonObject;
  userId: string | null;
  plan: JsonObject | null;
  balance: JsonObject;
  month: JsonObject;
  caps: JsonObject[];
  approvalsPending: JsonObject[];
  failing: JsonObject[];
  operations: JsonObject;
  raw: JsonObject;
}

/** Something the owner made public that a publishable key may call; `name` and `url` are null once it stopped being public. */
export interface PublicEndpoint {
  kind: string;
  id: string;
  name: string | null;
  url: string | null;
  userId: string | null;
  raw: JsonObject;
}

/** What `Account.resolve` found: the object's `type` and `id`, and the user it belongs to (null: the account). */
export interface ObjectRef {
  type: string;
  id: string;
  userId: string | null;
  raw: JsonObject;
}

/** A payment link (`Account.paymentLink`): what it buys (`label`), what checkout charges (`priceUsd`), its `url`, when it lapses, and its operation. */
export interface PaymentLink {
  kind: string;
  label: string;
  priceUsd: number;
  url: string;
  expiresAt: Date | null;
  operationId: string | null;
  raw: JsonObject;
}

/** @internal */
export function toPublicEndpoint(raw: JsonObject): PublicEndpoint {
  return { kind: str(raw.kind) ?? "", id: str(raw.id) ?? "", name: str(raw.name), url: str(raw.url), userId: str(raw.user_id), raw };
}
