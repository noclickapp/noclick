/**
 * Domains: buy one in your user's name, connect one they own, or transfer one in.
 *
 *     const [offer] = await Domain.search("anasilva", { tlds: ["dev"], limit: 1 });
 *     const ana = { name: "Ana Silva", email: "ana@example.com", phone: "+14155550123", address: "500 Market St",
 *                   city: "San Francisco", region: "CA", postalCode: "94105", country: "US",
 *                   agreementAcceptedAt: acceptedAt };                  // when she accepted Domain.agreement()
 *     const purchase = await Domain.buy(offer, { maxPriceUsd: 20, registrant: ana, user: "user_42" });   // Ana's, charged to you
 *     const bought = await purchase.wait();
 *
 *     const owned = await Domain.connect("acme.test");                  // one they already own
 *     for (const record of owned.records) console.log(record.type, record.name, record.value);
 *     const inbox = await Inbox.create({ localPart: "help", domain: "mail.acme.test" });   // its own mail stays put
 *
 * A bought domain is registered to the person (you, or the user it's bought for) and
 * charged to your account in dollars, like everything else: NoClick never bills your users.
 * It's never deleted: turn off auto-renew to let it lapse, or `transferOut()` to move it to
 * another registrar.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { Conflict, NotFound } from "./errors.ts";
import { ApiObject, asList, asObject, compact, csv, listAll, listPage, num, parseTime, str } from "./object.ts";
import type { CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import { resolveScope } from "./scope.ts";
import type { UserOption, UserRef } from "./scope.ts";

/**
 * `awaiting_human`: its purchase is held for your policy's approver. `transferring_in`: moving to
 * NoClick from another registrar (up to about 5 days).
 */
export type DomainStatus =
  | "awaiting_human" | "registering" | "transferring_in" | "pending_dns" | "active" | "registrant_unverified"
  | "expiring" | "expired" | "transferring_out" | "failed";

/**
 * `bought` (through NoClick), `transferred` (moved here from another registrar, then
 * registered through NoClick like a bought one) or `connected` (owned elsewhere).
 */
export type DomainSource = "bought" | "transferred" | "connected";

/** A name from `Domain.search`; buy it with `Domain.buy(offer, { maxPriceUsd })`. */
export interface DomainOffer {
  name: string;
  available: boolean;
  /** What buying it charges now, for `minYears`, in US dollars. */
  priceUsd: number | null;
  /** What each renewal of `minYears` costs. */
  renewalUsd: number | null;
  /** The registry prices this name above its usual rate, often far above. */
  premium: boolean;
  /** The TLD's shortest term, in years (two for `.ai`): what `Domain.buy` registers when `years` is left out. */
  minYears: number | null;
  /** The TLD's longest term, in years. */
  maxYears: number | null;
  /**
   * During the TLD's trademark-claims period, for a name that matches a registered trademark: the
   * Trademark Clearinghouse notice (Markdown) the registrant must be shown before buying it, with
   * `acceptClaims: true` once they have (null otherwise).
   */
  claimsNotice: string | null;
  raw: JsonObject;
}

/**
 * The registrant: the person a domain is registered to, as the registry records it. ICANN
 * requires real details, kept accurate (`domain.update({ registrant })` when they change), and
 * `email` is sent a link to confirm the address, in your brand on ICANN's behalf; a person
 * confirms once, for all their domains. Domains are registered through NoClick's registrar
 * partner, which the public registration record names; privacy protection keeps the
 * registrant's details out of it.
 */
export interface DomainContact {
  name: string;
  email: string;
  /** E.164, like `+14155550123`. */
  phone: string;
  /** A second street line follows a newline. */
  address: string;
  city: string;
  postalCode: string;
  /** Two letters, like `US`. */
  country: string;
  /** The state, province or region of the address; the registry requires one. */
  region: string;
  /**
   * When set, that organization is the legal owner (ICANN's "Registered Name Holder"): never put
   * your company on a user's domain unless your company means to own it.
   */
  organization?: string;
  /**
   * When this person explicitly accepted the domain registration agreement (`Domain.agreement()`'s
   * `url`). A registration needs it: a registrant, or your account's default registrant, without
   * it is refused with `InvalidRequest` naming `registrant.agreement_accepted_at`.
   */
  agreementAcceptedAt?: Date;
}

/**
 * NoClick's domain registration agreement, from `Domain.agreement()`. The
 * page at `url` is the agreement the registrant accepts (it names the sponsoring registrar, as ICANN
 * requires), the fee schedule (registration, renewal, renewal after expiry, restore) and ICANN's
 * registrant rights and responsibilities. Show it to the person and record when they accept it, as
 * `agreementAcceptedAt` on their `DomainContact`. `version` names the revision.
 */
export interface DomainAgreement {
  url: string;
  version: string;
  raw: JsonObject;
}

/**
 * One DNS record. `name` is `@` for the domain itself, or the label before it (`www`).
 * `required` is false for a record the domain works without (a connected domain's bare-name
 * `ALIAS`, which forwarding can replace); `managed` marks one NoClick keeps for what it serves.
 */
export interface DnsRecord {
  type: string;
  name: string;
  value: string;
  /** `verified` once public DNS answers with it, `pending` until then, `conflict` when another record is in the way. */
  status: string | null;
  /** What it's for, in a few words. */
  purpose: string | null;
  required: boolean;
  managed: boolean;
  raw: JsonObject;
}

/** Something a domain points at: an app (`project`), an inbox, or your brand's pages (`brand`). */
export interface DomainService {
  kind: "project" | "inbox" | "brand";
  id: string;
  name: string;
  /** The domain's name that serves it (an app at a bought domain is served at its name and its `www`). */
  hostname: string;
}

export interface DomainBuyOptions extends CallOptions {
  /** The most it may cost now, in US dollars; above it the purchase throws `PriceExceeded`. */
  maxPriceUsd: number;
  /**
   * The term, in years: between the offer's `minYears` and `maxYears`, the TLD's minimum when
   * omitted. One the TLD doesn't offer throws `InvalidRequest` naming `years`, with the terms it does.
   */
  years?: number;
  /**
   * The person it's registered to. A user's domain (inside `asUser`, or with `user`) naming none
   * uses the user's registrant profile (`Domain.setDefaultRegistrant(contact, { user })`), and with
   * none on file throws `InvalidRequest` naming `registrant`. A domain your account buys for itself
   * uses the account's default registrant instead (`Domain.setDefaultRegistrant`), and with none set
   * throws `ActionRequired` whose `nextStep` links to the console page where it's set. A registrant
   * that is the one on file, without `agreementAcceptedAt`, takes its acceptance from there once it
   * accepted the agreement as it stands.
   */
  registrant?: DomainContact;
  /** Renew 30 days before expiry (true by default). */
  autoRenew?: boolean;
  /**
   * True once the registrant has been shown the offer's `claimsNotice` and still wants the name. A
   * name with a notice is refused without it (`ActionRequired` whose details carry
   * `claims_notice`), and nothing is bought.
   */
  acceptClaims?: boolean;
}

/**
 * What moving a domain to NoClick from its current registrar costs, and
 * whether the registry allows it now: `eligible` is false (with `reason`) while the domain is locked
 * at its registrar, inside the registry's transfer lock after a domain is registered, transferred in
 * or its registrant changes (`lockedUntil`), on a TLD NoClick doesn't register, or already with
 * NoClick's registrar under another account (moving it between accounts isn't supported yet).
 * NoClick works it out from the domain's public registration data and the registrar's price, so
 * it's a best answer until `Domain.transferIn` is accepted.
 */
export interface TransferQuote {
  name: string;
  eligible: boolean;
  /** Why it can't move now (null when it can). */
  reason: string | null;
  /** What the transfer charges your account, in US dollars; it adds `years` to the registration. */
  priceUsd: number | null;
  /** What each renewal of `years` costs after. */
  renewalUsd: number | null;
  /** The term the transfer adds to the registration: the TLD's minimum, one year for most. */
  years: number | null;
  /** The end of the registry's transfer lock, while it applies. */
  lockedUntil: Date | null;
  raw: JsonObject;
}

export interface DomainTransferOptions extends CallOptions {
  /** The code the current registrar gives to move the domain out (its EPP or auth code). */
  authCode: string;
  /** The most it may cost, in US dollars; above it the transfer throws `PriceExceeded`. */
  maxPriceUsd: number;
  /** The person it's registered to from now on: required for a user's domain, as in `Domain.buy`. */
  registrant?: DomainContact;
}

function toOffer(raw: JsonObject): DomainOffer {
  return {
    name: String(raw.name), available: raw.available === true, priceUsd: num(raw.price_usd),
    renewalUsd: num(raw.renewal_usd), premium: raw.premium === true, minYears: num(raw.min_years),
    maxYears: num(raw.max_years), claimsNotice: str(raw.claims_notice), raw,
  };
}

/** @internal A record from its wire view: a domain's, or an app's email setup. */
export function toDnsRecord(value: unknown): DnsRecord {
  const raw = asObject(value);
  return {
    type: String(raw.type), name: String(raw.name), value: String(raw.value),
    status: str(raw.status), purpose: str(raw.purpose),
    required: raw.required !== false, managed: raw.managed === true, raw,
  };
}

function contactWire(contact: DomainContact): JsonObject {
  return compact({
    name: contact.name, email: contact.email, phone: contact.phone, address: contact.address, city: contact.city,
    postal_code: contact.postalCode, country: contact.country, region: contact.region, organization: contact.organization,
    agreement_accepted_at: contact.agreementAcceptedAt instanceof Date
      ? contact.agreementAcceptedAt.toISOString()
      : contact.agreementAcceptedAt,
  });
}

function toContact(value: unknown): DomainContact | null {
  const raw = asObject(value);
  if (!Object.keys(raw).length) return null;
  const acceptedAt = parseTime(raw.agreement_accepted_at);
  return {
    name: String(raw.name), email: String(raw.email), phone: String(raw.phone), address: String(raw.address),
    city: String(raw.city), postalCode: String(raw.postal_code), country: String(raw.country), region: String(raw.region),
    ...(typeof raw.organization === "string" ? { organization: raw.organization } : {}),
    ...(acceptedAt ? { agreementAcceptedAt: acceptedAt } : {}),
  };
}

function buyWire(name: string, options: DomainBuyOptions): JsonObject {
  return compact({
    name,
    max_price_usd: options.maxPriceUsd,
    years: options.years,
    auto_renew: options.autoRenew ?? true,
    registrant: options.registrant ? contactWire(options.registrant) : undefined,
    accept_claims: options.acceptClaims ? true : undefined,
  });
}

/** What `domain.transferOut()` gives; printing it never shows the code. */
export class TransferCode {
  /** Give it to the other registrar. */
  readonly authCode: string;
  readonly unlockedAt: Date | null;
  /** When the code stops working, where the registry limits it (null otherwise); `transferOut()` again gives a fresh one. */
  readonly expiresAt: Date | null;
  readonly raw: JsonObject;

  /** @internal */
  constructor(raw: JsonObject) {
    this.authCode = str(raw.auth_code) ?? "";
    this.unlockedAt = parseTime(raw.unlocked_at);
    this.expiresAt = parseTime(raw.expires_at);
    this.raw = raw;
  }

  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return `TransferCode { unlockedAt: ${this.unlockedAt?.toISOString() ?? null} }`;
  }
}

/**
 * `domain.dns`: the records of a bought domain, whose DNS NoClick
 * hosts. A connected domain's DNS stays where it is (`domain.records` lists what to add
 * there), so these throw `NotAvailable` on one.
 */
export class DomainDns {
  private readonly domain: Domain;

  /** @internal */
  constructor(domain: Domain) {
    this.domain = domain;
  }

  /** Every record in the domain's DNS: yours, and the ones NoClick keeps (`managed`) for what it serves. */
  async records(): Promise<DnsRecord[]> {
    return asList(await this.domain._request("GET", `${await this.domain._path()}/dns`)).map(toDnsRecord);
  }

  /**
   * Add a record, or keep it if the same one is there. A `CNAME` replaces the name's existing
   * `CNAME`; other types add alongside. One that clashes with a managed record throws `Conflict`.
   */
  async set(type: string, name: string, value: string): Promise<DnsRecord> {
    return toDnsRecord(await this.domain._request("POST", `${await this.domain._path()}/dns`, { json: { type, name, value } }));
  }

  /** Remove `record` (from `records()`); a managed one throws `Conflict`. */
  async delete(record: DnsRecord): Promise<void> {
    await this.domain._request("DELETE", `${await this.domain._path()}/dns`, {
      query: { type: record.type, name: record.name, value: record.value },
    });
  }
}

/** A buy, renewal or transfer in settles with `{ domain: <the domain view> }`. */
function readDomain(result: unknown, op: Operation<unknown>): Domain {
  return Domain._fromRaw(asObject(asObject(result).domain), { client: op._client, user: op._scope });
}

registerResult("domain.buy", readDomain);
registerResult("domain.renew", readDomain);
registerResult("domain.transfer_in", readDomain);

function toTransferQuote(value: unknown): TransferQuote {
  const raw = asObject(value);
  return {
    name: String(raw.name), eligible: raw.eligible === true, reason: str(raw.reason), priceUsd: num(raw.price_usd),
    renewalUsd: num(raw.renewal_usd), years: num(raw.years), lockedUntil: parseTime(raw.locked_until), raw,
  };
}

/** What a purchase and a transfer in share: the charge, and the domain it's for. */
abstract class DomainCharge extends Operation<Domain> {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** What it charges your account, in US dollars. */
  get priceUsd(): number | null {
    return num(this._known("price_usd"));
  }
  get domainId(): string | null {
    return str(this._known("domain_id"));
  }
  /** The domain, already listed while it runs (its `status` follows it). */
  get domain(): Domain {
    return Domain.fromId(String(this._known("domain_id")), { client: this._client, user: this._callScope() });
  }
}

/**
 * A domain bought or renewed: the operation `Domain.buy` and
 * `domain.renew` return. It's charged to your account when the registry confirms it, and one that
 * fails is never charged; while your policy holds it for a person to approve, it waits in
 * `awaiting_human`. `wait()` resolves to the `Domain`.
 */
export class DomainPurchase extends DomainCharge {
  /** @internal */
  static _fromResponse(payload: unknown, init: { client?: NoClick; user?: UserOption; kind: string }): DomainPurchase {
    const purchase = new DomainPurchase(Operation._init(payload, init));
    purchase._reader = readDomain;
    return purchase;
  }

  /** A lazy reference to a purchase by operation id: resume it anywhere, price and domain included (`Operation.fromId` gives a plain operation). */
  static purchaseFromId(operationId: string, options: CallOptions = {}): DomainPurchase {
    return DomainPurchase._fromResponse(operationId, { client: options.client, user: options.user, kind: "domain.buy" });
  }
}

/**
 * A domain moving to NoClick from another registrar: the operation
 * `Domain.transferIn` returns, charged to your account like a purchase (the quote, which adds the
 * quote's `years` to the registration) once the transfer completes, with the same `priceUsd`,
 * `domainId` and `domain`. The domain is `transferring_in` while the registry and the current
 * registrar move it, up to about 5 days; `wait()` resolves to the `Domain` once it's `active`. If the
 * registry refuses (a wrong auth code is `InvalidRequest` naming `authCode`), it fails with the
 * registry's reason and nothing is charged.
 */
export class DomainTransfer extends DomainCharge {
  /** @internal */
  static _fromResponse(payload: unknown, init: { client?: NoClick; user?: UserOption }): DomainTransfer {
    const transfer = new DomainTransfer(Operation._init(payload, { ...init, kind: "domain.transfer_in" }));
    transfer._reader = readDomain;
    return transfer;
  }

  /** A lazy reference to a transfer by operation id: resume it anywhere, price and domain included (`Operation.fromId` gives a plain operation). */
  static transferFromId(operationId: string, options: CallOptions = {}): DomainTransfer {
    return DomainTransfer._fromResponse(operationId, { client: options.client, user: options.user });
  }
}

/** A domain you bought through NoClick, transferred in, or connected from elsewhere, and what it serves. */
export class Domain extends ApiObject {
  private _createWith: JsonObject | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal From a domain view another call returned (a project's `addDomain`, a purchase's result). */
  static _fromRaw(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): Domain {
    return new Domain({ raw, client: init.client, user: init.user });
  }

  /**
   * Names for sale built from `query` (a word, or a whole name), in `tlds` or a common set,
   * with close alternatives: up to `limit` (10 by default, at most 50), exact matches first, each
   * priced for the TLD's shortest term (`minYears`), with any trademark `claimsNotice`.
   */
  static async search(query: string, options: CallOptions & { tlds?: string[]; limit?: number } = {}): Promise<DomainOffer[]> {
    const page = await resolveClient(options.client).request("GET", "/v1/domains/search", {
      query: { q: query, tlds: csv(options.tlds), limit: options.limit },
      user: resolveScope(options.user),
    });
    return (asList(page) as JsonObject[]).map(toOffer);
  }

  /**
   * Register `offer` in the person's name (yours, or inside `asUser` the user's) for `years`, the
   * TLD's minimum when omitted, charged to your account and never to the user, refused with
   * `PriceExceeded` above `maxPriceUsd`. A user's domain needs `registrant`, the person's details
   * with `agreementAcceptedAt` (`InvalidRequest` without it); one your account buys for itself,
   * outside `asUser`, uses the account's default registrant when you pass none (with none set, it
   * throws `ActionRequired` whose `nextStep` links to where it's set, and nothing is bought). A name
   * with a `claimsNotice` needs `acceptClaims`. NoClick checks your account can pay before
   * registering (`PaymentRequired` otherwise) and charges it when the registry confirms the
   * registration; one that fails is never charged. A policy hold waits in `awaiting_human` until the
   * approver answers; nobody answering within 24 hours expires it, and nothing is charged. The price
   * is checked against `maxPriceUsd` again when it runs.
   */
  static async buy(offer: string | DomainOffer, options: DomainBuyOptions): Promise<DomainPurchase> {
    const scope = resolveScope(options.user);
    const payload = await resolveClient(options.client).request("POST", "/v1/domains", {
      json: buyWire(typeof offer === "string" ? offer : offer.name, options),
      user: scope,
    });
    return DomainPurchase._fromResponse(payload, { client: options.client, user: scope, kind: "domain.buy" });
  }

  /**
   * NoClick's domain registration agreement, which every registrant accepts:
   * its page names the sponsoring registrar, as ICANN requires, and carries the fee schedule
   * (registration, renewal, renewal after expiry, restore) and ICANN's registrant rights and
   * responsibilities. Show it to the person, and record when they accept it as `agreementAcceptedAt`
   * on their `DomainContact`: a registration needs it.
   */
  static async agreement(options: { client?: NoClick } = {}): Promise<DomainAgreement> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/domains/agreement", { user: null }));
    return { url: String(raw.url), version: String(raw.version), raw };
  }

  /**
   * Whether `name` (registered elsewhere) can move to NoClick now, and what it
   * costs. Nothing is charged. NoClick works it out from the domain's public registration data (its
   * registrar lock, its transfer lock, whether NoClick registers the TLD) and the registrar's price, so
   * it's a best answer until `transferIn` is accepted.
   */
  static async transferQuote(name: string, options: CallOptions = {}): Promise<TransferQuote> {
    return toTransferQuote(await resolveClient(options.client).request("GET", "/v1/domains/transfer_quote", {
      query: { name },
      user: resolveScope(options.user),
    }));
  }

  /**
   * Move `name` (a name, a `TransferQuote`, or a domain you connected) to
   * NoClick from its current registrar, with the `authCode` that registrar gives. It's charged to your
   * account like a purchase once the transfer completes (`PriceExceeded` above `maxPriceUsd`,
   * `awaiting_human` while your policy holds it), and registered to `registrant` on the same rule as
   * `Domain.buy`, `agreementAcceptedAt` included: required for a user's domain, else the account's
   * default registrant. One the registry won't move now throws
   * `NotAvailable` with the reason. Its nameservers don't change, so its DNS keeps working where it's
   * hosted; once it's `active`, `useNoClickDns()` moves the DNS to NoClick. A connected domain keeps its
   * id and what it serves; passed as a `Domain`, the transfer acts in that domain's own scope (its user,
   * else your account), while a name acts for the current user or `user`.
   */
  static async transferIn(name: string | TransferQuote | Domain, options: DomainTransferOptions): Promise<DomainTransfer> {
    let domain: string;
    let scope: UserRef | null | undefined;
    if (name instanceof Domain) {
      if (options.user !== undefined) throw new TypeError("A Domain transfers in its own scope; pass user with a name instead.");
      domain = await name._name(); // loads a lazy domain, so its user is known
      scope = name._callScope();
    } else {
      domain = typeof name === "string" ? name : name.name;
      scope = resolveScope(options.user);
    }
    const payload = await resolveClient(options.client).request("POST", "/v1/domains/transfer_in", {
      json: compact({
        name: domain,
        auth_code: options.authCode,
        max_price_usd: options.maxPriceUsd,
        registrant: options.registrant ? contactWire(options.registrant) : undefined,
      }),
      user: scope,
    });
    return DomainTransfer._fromResponse(payload, { client: options.client, user: scope });
  }

  /**
   * The registrant your account's own domains are registered to when a purchase names none (null until set); with
   * `user` (a `User` or your id for one), that user's registrant profile, which their domains use.
   */
  static async defaultRegistrant(options: { client?: NoClick; user?: UserRef | null } = {}): Promise<DomainContact | null> {
    return toContact(await resolveClient(options.client).request("GET", "/v1/domains/registrant", { user: options.user ?? null }));
  }

  /**
   * Set (or with `null` clear) the registrant your account's own domains use when a purchase names
   * none, so `Domain.buy` or `Domain.fromName(..., { createIfMissing })` outside `asUser` needs no
   * contact in code; until one is set, such a purchase throws `ActionRequired`. With `user` (a `User` or
   * your id for one) it's that user's registrant profile, with their own acceptance: their domains (`asUser`,
   * or an app of theirs) are registered to it when a purchase names none. Like any registrant, it needs
   * `agreementAcceptedAt`. It's a standing acceptance too: where your approval settings make `terms` and
   * `person_filing` standing (`ApprovalPolicy.set`), a purchase it covers, an app's code's included, runs with
   * no one asked.
   */
  static async setDefaultRegistrant(
    contact: DomainContact | null,
    options: { client?: NoClick; user?: UserRef | null } = {},
  ): Promise<DomainContact | null> {
    const api = resolveClient(options.client);
    const user = options.user ?? null;
    if (contact === null) {
      await api.request("DELETE", "/v1/domains/registrant", { user });
      return null;
    }
    return toContact(await api.request("PUT", "/v1/domains/registrant", { json: contactWire(contact), user }));
  }

  /**
   * Connect a domain the person owns (`acme.com`, or `book.acme.com`). It's `pendingDns` until
   * `records` are added where its DNS is hosted (`setupUrl` does it in one click where the host
   * supports it). On a bare domain `www` is primary and the bare name needs CNAME flattening or a forward.
   * `wildcard: true` adds the `*.<name>` records too, so every subdomain can serve an app or send an
   * app's email without a record of its own; each goes live once its certificate is issued, usually
   * within minutes of its first use.
   */
  static async connect(name: string, options: CallOptions & { wildcard?: boolean } = {}): Promise<Domain> {
    const scope = resolveScope(options.user);
    const json: JsonObject = { name, ...(options.wildcard ? { wildcard: true } : {}) };
    const raw = await resolveClient(options.client).request<JsonObject>("POST", "/v1/domains/connect", { json, user: scope });
    return new Domain({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to your domain called `name`; loading one that isn't yours throws `NotFound`. An
   * `autoRenew` you pass is set on it every run. With `createIfMissing` your code owns it idempotently:
   * the first time it's used with no such domain it's bought as `Domain.buy` would (`maxPriceUsd` is
   * required, `years` is the TLD's minimum when omitted, and a user's domain needs `registrant`).
   * `maxPriceUsd`, `years` and `registrant` say how to buy it, so they matter only then.
   */
  static fromName(name: string, options: CallOptions & Partial<DomainBuyOptions> & { createIfMissing?: boolean } = {}): Domain {
    const domain = new Domain({ hints: { name }, client: options.client, user: options.user });
    domain._creates = Boolean(options.createIfMissing);
    if (options.createIfMissing) {
      if (options.maxPriceUsd === undefined) throw new TypeError("Domain.fromName(..., { createIfMissing: true }) needs maxPriceUsd");
      domain._createWith = compact({
        ...buyWire(name, { ...options, maxPriceUsd: options.maxPriceUsd }),
        auto_renew: options.autoRenew,
      });
    } else if (options.autoRenew !== undefined) {
      domain._createWith = { name, auto_renew: options.autoRenew };
    }
    return domain;
  }

  static fromId(domainId: string, options: CallOptions = {}): Domain {
    return new Domain({ hints: { id: domainId }, client: options.client, user: options.user });
  }

  static async get(domainId: string, options: CallOptions = {}): Promise<Domain> {
    return await Domain.fromId(domainId, options).hydrate();
  }

  /** Your domains, bought and connected (the current user's inside `asUser`, or those `userFilter` covers). */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<Domain[]> {
    return await listAll({ ...options, path: "/v1/domains" }, (raw, user) => new Domain({ raw, client: options.client, user }));
  }

  /** One page of domains; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Domain>> {
    return await listPage({ ...options, path: "/v1/domains" }, (raw, user) => new Domain({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  /** The domain, like `acmebooking.com`. */
  get name(): string {
    return this._field("name");
  }
  get source(): DomainSource {
    return this._field("source");
  }
  /**
   * Whether NoClick hosts its DNS: a bought domain, or a transferred one after
   * `useNoClickDns()`. When false, `records` are added where its DNS is hosted and `dns` throws `NotAvailable`.
   */
  get noClickDns(): boolean {
    return this._field("noclick_dns") === true;
  }
  /** Whether its `*.<name>` records are set too, so every subdomain can serve. */
  get wildcard(): boolean {
    return this._field("wildcard") === true;
  }
  get status(): DomainStatus {
    return this._field("status");
  }
  /** When the registration runs out (null for a connected domain). */
  get expiresAt(): Date | null {
    return parseTime(this._field("expires_at"));
  }
  /** Renews itself 30 days before `expiresAt` (null for a connected domain). */
  get autoRenew(): boolean | null {
    return this._field("auto_renew") ?? null;
  }
  /** The end of the guaranteed renewal window after `expiresAt`: the last moment `renew()` works (null for a connected domain). */
  get renewableUntil(): Date | null {
    return parseTime(this._field("renewable_until"));
  }
  /** What renewing for `renewalYears` costs, in US dollars. */
  get renewalUsd(): number | null {
    return num(this._field("renewal_usd"));
  }
  /** The term `renewalUsd` buys, in years: the TLD's minimum (null for a connected domain). */
  get renewalYears(): number | null {
    return num(this._field("renewal_years"));
  }
  /** The person it's registered to (null for a connected domain); `update({ registrant })` changes it. */
  get registrant(): DomainContact | null {
    return toContact(this._field("registrant"));
  }
  /** The records it needs for what it serves: to add at its DNS host (connected), or kept by NoClick (bought). */
  get records(): DnsRecord[] {
    const rows = this._field<unknown>("records");
    return (Array.isArray(rows) ? rows : []).map(toDnsRecord);
  }
  /**
   * A connected domain's one-click setup, where its DNS host supports the open Domain Connect
   * standard; the host's consent page names NoClick alongside your brand (null otherwise).
   */
  get setupUrl(): string | null {
    return this._field("setup_url") ?? null;
  }
  /** What it points at: each app and inbox. */
  get serves(): DomainService[] {
    const rows = this._field<unknown>("serves");
    return Array.isArray(rows) ? (rows as DomainService[]) : [];
  }
  /** Where the link to confirm the registrant's address went, sent in your brand on ICANN's behalf (a bought domain). */
  get registrantEmail(): string | null {
    return this._field("registrant_email") ?? null;
  }
  /** While `registrant_unverified`: the day (15 days on) the domain stops resolving unless the registrant has confirmed. */
  get registrantVerifyBy(): Date | null {
    return parseTime(this._field("registrant_verify_by"));
  }
  /**
   * Until then `transferOut()` throws `NotAvailable`: the registry's transfer lock after a domain is
   * registered, transferred in or its registrant changes.
   */
  get transferLockedUntil(): Date | null {
    return parseTime(this._field("transfer_locked_until"));
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  /** The records of a bought domain. */
  get dns(): DomainDns {
    return new DomainDns(this);
  }

  override toString(): string {
    return str(this._known("name")) ?? `Domain(${this._known("id")})`;
  }

  /** @internal The name, loading a lazy domain referred to by id. */
  async _name(): Promise<string> {
    const known = this._known("name");
    return typeof known === "string" ? known : String((await this._ensure()).name);
  }

  /** @internal */
  async _path(): Promise<string> {
    const id = this._known("id");
    return `/v1/domains/${typeof id === "string" ? id : String((await this._ensure()).id)}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/domains/${id}`);
    const name = String(this._hints.name);
    const rows = (asList(await this._request("GET", "/v1/domains", { query: { name } })) as JsonObject[]).filter((row) => row.name === name);
    if (rows.length) return await this.converge(rows[0]);
    if (!this._createWith || !this._creates) {
      throw new NotFound(`No domain is named "${name}".`, {
        nextStep: "Buy it with Domain.buy(...) or connect it with Domain.connect(...).",
        details: { name },
      });
    }
    let purchase: JsonObject;
    try {
      purchase = asObject(await this._request("POST", "/v1/domains", { json: this._createWith }));
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // bought concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/domains/${err.existingId}`));
    }
    return await this._request<JsonObject>("GET", `/v1/domains/${purchase.domain_id}`);
  }

  /** Set `autoRenew` on an existing domain when `fromName` was given it. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    const wanted = this._createWith?.auto_renew;
    if (wanted === undefined || raw.auto_renew === wanted) return raw;
    return await this._request<JsonObject>("PATCH", `/v1/domains/${raw.id}`, { json: { auto_renew: wanted } });
  }

  /** Check the domain's DNS now; each record's `status` and the domain's own are as found. */
  async verify(): Promise<this> {
    this._raw = asObject(await this._request("POST", `${await this._path()}/verify`));
    return this;
  }

  /**
   * Change a bought domain's settings: `{ autoRenew: false }` lets it lapse at `expiresAt`, and
   * `registrant` replaces the details of the person it's registered to. ICANN requires accurate
   * details, so update them when the person's change. Changing the registrant's name, organization
   * or email asks the new registrant to confirm their email again (the domain is
   * `registrant_unverified` meanwhile) and may start the registry's transfer lock (see
   * `transferLockedUntil`).
   */
  async update(changes: { autoRenew?: boolean; registrant?: DomainContact }): Promise<this> {
    this._raw = asObject(await this._request("PATCH", await this._path(), {
      json: compact({ auto_renew: changes.autoRenew, registrant: changes.registrant ? contactWire(changes.registrant) : undefined }),
    }));
    return this;
  }

  /**
   * Extend a bought domain now by `years`, or the TLD's minimum term (`renewalYears`) when omitted,
   * charged to your account when the renewal lands; like a purchase it may wait in `awaiting_human`
   * for your policy's approver. After `renewableUntil` it throws `NotAvailable`: renewing past the
   * guaranteed renewal window, or restoring a domain the registry is about to delete, isn't an API
   * call (NoClick support may be able to restore it, at the registry's restore fee).
   */
  async renew(options: { years?: number; maxPriceUsd: number }): Promise<DomainPurchase> {
    const payload = await this._request("POST", `${await this._path()}/renew`, {
      json: compact({ years: options.years, max_price_usd: options.maxPriceUsd }),
    });
    return DomainPurchase._fromResponse(payload, { client: this._client, user: this._callScope(), kind: "domain.renew" });
  }

  /**
   * Move a transferred domain's DNS hosting to NoClick: the records NoClick can
   * read where it's hosted now are copied first, then its nameservers change. Resolves to the records
   * copied, for review: add any it missed with `dns.set`. On a domain whose DNS NoClick already hosts it
   * copies nothing; a connected domain throws `NotAvailable` (transfer it in first).
   */
  async useNoClickDns(): Promise<DnsRecord[]> {
    const raw = asObject(await this._request("POST", `${await this._path()}/use_noclick_dns`));
    this._raw = asObject(raw.domain);
    return asList(raw.copied).map(toDnsRecord);
  }

  /**
   * Unlock a bought or transferred domain for another registrar; inside the registry's transfer lock
   * (`transferLockedUntil`) it throws `NotAvailable`. The code works until its `expiresAt`.
   */
  async transferOut(): Promise<TransferCode> {
    return new TransferCode(asObject(await this._request("POST", `${await this._path()}/transfer_out`)));
  }

  /**
   * Disconnect a connected domain (its DNS stays as it is where it's hosted). Throws `Conflict`
   * while an inbox uses it, and on a bought domain, which can only lapse or transfer out.
   */
  async delete(): Promise<void> {
    await this._request("DELETE", await this._path());
  }
}
