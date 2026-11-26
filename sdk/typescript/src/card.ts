/**
 * Cards: virtual cards with limits, for agents that buy things.
 *
 *     const card = await Card.create("Office supplies", {
 *       limitUsd: 1500, interval: "month", merchants: ["office_supplies"], agent: buyer, requireApprovalAboveUsd: 200,
 *     });
 *     const details = await (await card.purchase(124.5, "Staples", { reason: "Toner" })).wait();
 *     for (const charge of await card.transactions({ limit: 20 })) console.log(charge.merchant, charge.amountUsd, charge.status);
 *     await card.freeze();
 *
 * Cards are your company's commercial cards, for US businesses, in dollars. They spend your
 * company's own card balance, held by Stripe Payments Company (`Card.funding()`), which you fund by bank
 * transfer: what a card pays isn't charged to your NoClick account, which pays only $0.13 per
 * card number issued. Cards need card issuing, which your company applies for once in the
 * console (`Card.program()`); until it's active these calls throw `NotAvailable`. A card number
 * is shown only on a page where the card issuer's own element displays it (`reveal()`): it never
 * passes through NoClick, your code or a model.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { agentId } from "./agent.ts";
import type { Agent } from "./agent.ts";
import { Conflict, NotFound } from "./errors.ts";
import {
  ApiObject, asObject, compact, createNamed, defined, givesFields, listAll, listPage, num, paginate, parseTime, str,
} from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { resolveScope } from "./scope.ts";

/** What `limitUsd` covers. */
export type CardInterval = "transaction" | "day" | "month" | "all_time";
export type CardStatus = "active" | "frozen" | "closed";
export type CardTransactionStatus = "approved" | "settled" | "reversed" | "declined" | "pending_approval";
export type CardProgramStatus = "not_started" | "pending_verification" | "active" | "rejected" | "restricted";
export type CardDisputeReason =
  | "fraudulent"
  | "canceled"
  | "duplicate"
  | "not_received"
  | "not_as_described"
  | "incorrect_amount";

export interface CardCreateOptions extends CallOptions {
  /** The most it spends per `interval`. */
  limitUsd: number;
  /** Default `"month"`. */
  interval?: CardInterval;
  /**
   * Merchant categories it may pay (`"office_supplies"`, `"software"`, `"travel"`, ... or a 4-digit code);
   * any when omitted, never cash, money transfers, gambling or securities.
   */
  merchants?: string | string[];
  /** The agent that pays with it. */
  agent?: Agent | string;
  /**
   * A purchase above this is approved by a person before anything is paid (`purchase`); a charge
   * above it that nobody announced is declined, and the merchant's retry passes once they approve.
   */
  requireApprovalAboveUsd?: number;
  /**
   * Every checkout (every purchase, every `reveal()`) gets a fresh number that takes one charge and
   * then closes; together they spend within `limitUsd` per `interval` (UTC days and months).
   */
  singleUse?: boolean;
}

/** `null` clears a field: `merchants: null` allows any merchant, `requireApprovalAboveUsd: null` never asks, `agent: null` takes it from its agent. */
export interface CardUpdateOptions {
  name?: string;
  limitUsd?: number;
  interval?: CardInterval;
  merchants?: string | string[] | null;
  agent?: Agent | string | null;
  requireApprovalAboveUsd?: number | null;
  /** From its next checkout. */
  singleUse?: boolean;
}

/** A settled charge disputed with the card network: `submitted`, then `won`, `lost` or `expired`. */
export interface CardDispute {
  id: string | null;
  transactionId: string | null;
  reason: CardDisputeReason | null;
  status: "submitted" | "won" | "lost" | "expired" | null;
  amountUsd: number | null;
  createdAt: Date | null;
  raw: JsonObject;
}

/**
 * One charge or refund on a card. A `charge` is `approved` (held until the merchant settles it),
 * `settled` (`settledAmountUsd`), `reversed`, `declined` or `pending_approval` (held for a person);
 * a `refund` is settled, its `amountUsd` below zero. A decline says why in `declineReason`
 * (`over_limit`, `over_budget` (an app's card, past what's left of the app's budget),
 * `merchant_not_allowed`, `frozen`, `insufficient_funds`, `amount_mismatch`,
 * `not_approved`, `approval_expired`, `awaiting_approval`, `card_closed`, `card_expired`,
 * `invalid_cvc`, `invalid_expiry`, `3ds_failed`, `issuer_declined`).
 */
export interface CardTransaction {
  id: string | null;
  cardId: string | null;
  kind: "charge" | "refund" | null;
  amountUsd: number | null;
  settledAmountUsd: number | null;
  merchant: string | null;
  /** The `Card.merchantCategories()` name its `merchantMcc` is in (null: none of them). */
  merchantCategory: string | null;
  merchantMcc: string | null;
  status: CardTransactionStatus | null;
  declineReason: string | null;
  /** The held charge's approval, an operation: `await Operation.fromId(approvalId).wait()` is `true` once approved. */
  approvalId: string | null;
  /** The `card.purchase` operation whose number paid it. */
  purchaseId: string | null;
  /** The number it was on. */
  last4: string | null;
  dispute: CardDispute | null;
  at: Date | null;
  raw: JsonObject;
}

/** Where your company sends money to fund its card balance: a wire lands the same day, ACH within days. */
export interface CardBankTransfer {
  bankName: string | null;
  routingNumber: string | null;
  accountNumber: string | null;
  networks: string[];
}

/**
 * Your company's card balance, held by Stripe Payments Company: every card spends from it. It can drop below zero
 * when a merchant takes a charge without asking; NoClick then freezes your cards until it's funded again.
 */
export interface CardFunding {
  balanceUsd: number | null;
  /** Held by charges that haven't settled. */
  pendingUsd: number | null;
  /** What cards can still spend: the balance less what's pending. */
  availableUsd: number | null;
  /** The console page with the bank details. */
  topUpUrl: string | null;
  bankTransfer: CardBankTransfer | null;
  /** Since when your cards have been frozen because the balance is below zero (null: they aren't). */
  frozenSince: Date | null;
  raw: JsonObject;
}

/**
 * Card issuing for your company: `not_started`, then `pending_verification` while the card issuer
 * verifies it (`requirementsDue`), `active`; or `rejected`, or `restricted` (it needs something
 * again). Your company applies once, in the console at `onboardingUrl`: US businesses, in dollars.
 */
export interface CardProgram {
  status: CardProgramStatus;
  requirementsDue: string[];
  companyName: string | null;
  country: string | null;
  currency: string | null;
  onboardingUrl: string | null;
  raw: JsonObject;
}

/** A session for the card issuer's embedded onboarding form (`Card.onboardingSession()`). */
export interface CardOnboardingSession {
  /** What the issuer's embedded form opens with. */
  clientSecret: string;
  /** The issuer's publishable key the form loads with. */
  publishableKey: string;
  /** The company's account at the issuer. */
  account: string;
  expiresAt: Date | null;
  program: CardProgram;
  raw: JsonObject;
}

/** A name `merchants` takes, and the merchant category codes it covers. */
export interface CardMerchantCategory {
  name: string;
  description: string | null;
  mccs: string[];
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function toDispute(value: unknown): CardDispute {
  const raw = asObject(value);
  return {
    id: str(raw.id),
    transactionId: str(raw.transaction_id),
    reason: str(raw.reason) as CardDisputeReason | null,
    status: str(raw.status) as CardDispute["status"],
    amountUsd: num(raw.amount_usd),
    createdAt: parseTime(raw.created_at),
    raw,
  };
}

function toTransaction(value: unknown): CardTransaction {
  const raw = asObject(value);
  return {
    id: str(raw.id),
    cardId: str(raw.card_id),
    kind: str(raw.kind) as CardTransaction["kind"],
    amountUsd: num(raw.amount_usd),
    settledAmountUsd: num(raw.settled_amount_usd),
    merchant: str(raw.merchant),
    merchantCategory: str(raw.merchant_category),
    merchantMcc: str(raw.merchant_mcc),
    status: str(raw.status) as CardTransactionStatus | null,
    declineReason: str(raw.decline_reason),
    approvalId: str(raw.approval_id),
    purchaseId: str(raw.purchase_id),
    last4: str(raw.last4),
    dispute: raw.dispute ? toDispute(raw.dispute) : null,
    at: parseTime(raw.at),
    raw,
  };
}

function merchantList(merchants: string | string[] | null | undefined): string[] | null | undefined {
  if (merchants === undefined || merchants === null) return merchants;
  return typeof merchants === "string" ? [merchants] : [...merchants];
}

/**
 * Invite-only beta. A card number to pay with, shown only at `url`: a page where the card
 * issuer's own element displays the number, CVC and expiry to whoever opens it, until `expiresAt`.
 * The number never passes through NoClick, your code or a model, so send `url` only to the person
 * who pays. Printing or serializing it leaves `url` out.
 */
export class CardDetails {
  readonly url: string;
  readonly expiresAt: Date | null;
  readonly last4: string | null;
  readonly brand: string | null;
  readonly expMonth: number | null;
  readonly expYear: number | null;
  /** A number that takes one charge (every number of a single-use card, every purchase's). */
  readonly singleUse: boolean;
  /** A purchase's exact amount: the most its one charge may be. */
  readonly amountUsd: number | null;
  /** When a single-use number nobody paid with closes. */
  readonly closesAt: Date | null;
  /** The name and billing address a checkout asks for: your company's. */
  readonly cardholder: string | null;
  readonly billingAddress: JsonObject | null;
  readonly raw: JsonObject;

  /** @internal */
  constructor(raw: JsonObject) {
    this.url = str(raw.url) ?? "";
    this.expiresAt = parseTime(raw.expires_at);
    this.last4 = str(raw.last4);
    this.brand = str(raw.brand);
    this.expMonth = num(raw.exp_month);
    this.expYear = num(raw.exp_year);
    this.singleUse = raw.single_use === true;
    this.amountUsd = num(raw.amount_usd);
    this.closesAt = parseTime(raw.closes_at);
    this.cardholder = str(raw.cardholder);
    this.billingAddress = raw.billing_address && typeof raw.billing_address === "object" ? (raw.billing_address as JsonObject) : null;
    this.raw = raw;
  }

  toJSON(): JsonObject {
    return { last4: this.last4, exp_month: this.expMonth, exp_year: this.expYear, cardholder: this.cardholder };
  }

  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return `CardDetails { last4: ${JSON.stringify(this.last4)}, expMonth: ${this.expMonth}, expYear: ${this.expYear} }`;
  }
}

registerResult("card.purchase", (result) => new CardDetails(asObject(result)));

/** What `fromName` sets on an existing card. */
const CONVERGED = ["limit_usd", "interval", "merchants", "require_approval_above_usd", "agent_id", "single_use"] as const;

/** A `fromName` definition: `create`'s fields, where `null` clears `agent` or `requireApprovalAboveUsd`. */
type CardDefinition = Partial<Omit<CardCreateOptions, "agent" | "requireApprovalAboveUsd">> &
  Pick<CardUpdateOptions, "agent" | "requireApprovalAboveUsd">;

/** The fields on the wire; a card is issued monthly unless `interval` says otherwise (`issued`). */
async function wireBody(name: string | undefined, options: CardDefinition, issued = false): Promise<JsonObject> {
  return compact({
    name,
    limit_usd: options.limitUsd,
    interval: options.interval ?? (issued ? "month" : undefined),
    merchants: merchantList(options.merchants),
    agent_id: await agentId(options.agent ?? undefined),
    require_approval_above_usd: options.requireApprovalAboveUsd,
    single_use: options.singleUse,
  });
}

/**
 * Invite-only beta. A virtual card with a spending limit.
 * `Card.fromName("Office supplies", { createIfMissing: true, limitUsd: 1500 })` is lazy;
 * `await card.purchase(...)` approves and pays one purchase, `await card.reveal()` shows its number
 * to a person. A card is always your company's, for its business, including buying for one of your
 * users: one issued for a user is only that user's agents' to pay with, never a card the user owns or
 * funds. It may be held by one agent, which pays with it at checkouts in its browser.
 */
export class Card extends ApiObject {
  private _createWith: { name: string; options: CardDefinition } | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Issue a virtual card called `name` (unique among its user's open cards; a
   * duplicate throws `Conflict` with `existingId`). With `allowExisting: true` a taken name returns the
   * open card already there, as it is: nothing about it changes, and no number is issued.
   */
  static async create(name: string, options: CardCreateOptions & AllowExisting): Promise<Card> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/cards", await wireBody(name, options, true), {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new Card({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the open card called `name` for the current (or given) user. Given fields, it
   * gets the card and sets the ones you pass, on every run: an existing card whose limit, interval,
   * merchants, approval threshold or agent differ gets yours. `createIfMissing` issues it when there's
   * none (`interval` is `"month"` unless you pass one); without it, a missing card throws `NotFound`. A
   * field left out is never changed; `null` clears `agent` or `requireApprovalAboveUsd`,
   * as `update` does. Each run with fields is a write: set them at startup or in a setup script, and take
   * the bare `fromName` in request handlers.
   */
  static fromName(name: string, options: CardDefinition & { createIfMissing?: boolean } = {}): Card {
    const card = new Card({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing && options.limitUsd === undefined) {
      throw new TypeError("Card.fromName(..., { createIfMissing: true }) needs limitUsd");
    }
    card._creates = Boolean(options.createIfMissing);
    if (card._creates || givesFields(options)) card._createWith = { name, options };
    return card;
  }

  static fromId(cardId: string, options: CallOptions = {}): Card {
    return new Card({ hints: { id: cardId }, client: options.client, user: options.user });
  }

  static async get(cardId: string, options: CallOptions = {}): Promise<Card> {
    return await Card.fromId(cardId, options).hydrate();
  }

  /** The current user's cards (the account's own outside `asUser`, or those `userFilter` covers). */
  static async list(options: ReadOptions & { status?: CardStatus; agent?: Agent | string; limit?: number } = {}): Promise<Card[]> {
    return await listAll(
      { ...options, path: "/v1/cards", query: { status: options.status, agent_id: await agentId(options.agent) } },
      (raw, user) => new Card({ raw, client: options.client, user }),
    );
  }

  /** One page of cards; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions & { status?: CardStatus; agent?: Agent | string } = {}): Promise<Page<Card>> {
    return await listPage(
      { ...options, path: "/v1/cards", query: { status: options.status, agent_id: await agentId(options.agent) } },
      (raw, user) => new Card({ raw, client: options.client, user }),
    );
  }

  /** Your company's card balance, which every card (the account's and every user's) spends from, and the bank details that fund it. */
  static async funding(options: { client?: NoClick } = {}): Promise<CardFunding> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/cards/funding", { user: null }));
    const transfer = raw.bank_transfer && typeof raw.bank_transfer === "object" ? asObject(raw.bank_transfer) : null;
    return {
      balanceUsd: num(raw.balance_usd),
      pendingUsd: num(raw.pending_usd),
      availableUsd: num(raw.available_usd),
      topUpUrl: str(raw.top_up_url),
      bankTransfer: transfer && {
        bankName: str(transfer.bank_name),
        routingNumber: str(transfer.routing_number),
        accountNumber: str(transfer.account_number),
        networks: strings(transfer.networks),
      },
      frozenSince: parseTime(raw.frozen_since),
      raw,
    };
  }

  /** Where your company's card issuing stands. It's applied for once, in the console. */
  static async program(options: { client?: NoClick } = {}): Promise<CardProgram> {
    return toProgram(asObject(await resolveClient(options.client).request("GET", "/v1/cards/program", { user: null })));
  }

  /**
   * Open your company's card program on first use and start a session of the card issuer's embedded onboarding
   * form, where it applies. The signed-in owner's alone (a key gets `PermissionDenied`); `Conflict` once the issuer
   * rejected the company, `NotAvailable` where cards aren't enabled.
   */
  static async onboardingSession(options: { client?: NoClick } = {}): Promise<CardOnboardingSession> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/cards/program/session", { user: null }));
    return {
      clientSecret: str(raw.client_secret) ?? "",
      publishableKey: str(raw.publishable_key) ?? "",
      account: str(raw.account) ?? "",
      expiresAt: parseTime(raw.expires_at),
      program: toProgram(asObject(raw.program)),
      raw,
    };
  }

  /** The names `merchants` takes, each with the merchant category codes it covers (a 4-digit code works too). */
  static async merchantCategories(options: { client?: NoClick } = {}): Promise<CardMerchantCategory[]> {
    const page = asObject(await resolveClient(options.client).request("GET", "/v1/cards/merchant_categories", { user: null }));
    return (Array.isArray(page.data) ? page.data : []).map((value) => {
      const row = asObject(value);
      return { name: str(row.name) ?? "", description: str(row.description), mccs: strings(row.mccs) };
    });
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  get last4(): string | null {
    return this._field("last4");
  }
  /** The card network, like `visa`. */
  get brand(): string | null {
    return this._field("brand");
  }
  get expMonth(): number | null {
    return this._field("exp_month");
  }
  get expYear(): number | null {
    return this._field("exp_year");
  }
  get status(): CardStatus {
    return this._field("status");
  }
  /**
   * Why it's frozen when you didn't freeze it: `negative_balance` while your card balance is
   * below zero (it pays again once funded). Null otherwise.
   */
  get statusReason(): "negative_balance" | null {
    return this._field("status_reason") ?? null;
  }
  /** The most it spends per `interval` (null: no limit). */
  get limitUsd(): number | null {
    return this._field("limit_usd");
  }
  get interval(): CardInterval | null {
    return this._field("interval");
  }
  /** Spent in the current interval (this calendar month's spend for a per-transaction limit). */
  get spentUsd(): number | null {
    return this._field("spent_usd");
  }
  /** When `spentUsd` starts over (null for `all_time`). */
  get resetsAt(): Date | null {
    return parseTime(this._field("resets_at"));
  }
  /** The merchant categories it may pay (null: any). */
  get merchants(): string[] | null {
    return this._field("merchants");
  }
  /** Charges above this wait for a person (null: never). */
  get requireApprovalAboveUsd(): number | null {
    return this._field("require_approval_above_usd");
  }
  /** The agent that pays with it (null if none). */
  get agentId(): string | null {
    return this._field("agent_id");
  }
  /** Whether every checkout gets a fresh number that takes one charge (`last4` is the latest one's). */
  get singleUse(): boolean {
    return this._field("single_use") === true;
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/cards/${id}`);
    const name = String(this._hints.name);
    const page = asObject(await this._request("GET", "/v1/cards", { query: { name } }));
    const rows = (Array.isArray(page.data) ? (page.data as JsonObject[]) : []).filter((row) => row.name === name && row.status !== "closed");
    if (rows.length) return await this.converge(rows[0]);
    if (!this._createWith || !this._creates) {
      throw new NotFound(`No open card is named "${name}".`, {
        nextStep: "Issue it with Card.create(...) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/cards", { json: await wireBody(this._createWith.name, this._createWith.options, true) });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // issued concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/cards/${err.existingId}`));
    }
  }

  /** Set the fields `fromName` was given on an existing card. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    if (!this._createWith) return raw;
    const { options } = this._createWith;
    // An explicit null is part of the definition: it clears the field on an existing card.
    const cleared = Object.entries({ agent_id: options.agent, require_approval_above_usd: options.requireApprovalAboveUsd })
      .filter(([, value]) => value === null);
    const wanted = { ...(await wireBody(undefined, options)), ...Object.fromEntries(cleared) };
    const changes: JsonObject = {};
    for (const key of CONVERGED) {
      if (key in wanted && JSON.stringify(raw[key] ?? null) !== JSON.stringify(wanted[key])) changes[key] = wanted[key];
    }
    if (!Object.keys(changes).length) return raw;
    return await this._request<JsonObject>("PATCH", `/v1/cards/${raw.id}`, { json: changes });
  }

  private async path(): Promise<string> {
    return `/v1/cards/${(await this._ensure()).id}`;
  }

  private async act(verb: "freeze" | "unfreeze" | "close"): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `${await this.path()}/${verb}`);
    return this;
  }

  /** Its charges and refunds, newest first, each with any dispute: the newest `limit` (20 by default; `null` for every one). */
  async transactions(options: { status?: CardTransactionStatus; limit?: number | null } = {}): Promise<CardTransaction[]> {
    const limit = options.limit === null ? undefined : (options.limit ?? 20);
    const rows = await paginate(this._api, `${await this.path()}/transactions`, {
      query: { status: options.status },
      user: this._callScope() ?? null,
      limit,
    });
    return rows.map(toTransaction);
  }

  /**
   * A page that shows the card's number to a person: the card issuer's own element displays it there,
   * for 10 minutes, so the number never passes through NoClick or your code. On a single-use card it's a
   * fresh number, which closes unused after an hour. Needs a key with the `cards:reveal` scope; every
   * reveal is recorded with the key that made it.
   */
  async reveal(): Promise<CardDetails> {
    return new CardDetails(asObject(await this._request("POST", `${await this.path()}/reveal`)));
  }

  /**
   * Approve one purchase before paying it: a number for exactly this purchase, which takes one charge of
   * at most `amountUsd` (tax and shipping included) and then closes. At or under `requireApprovalAboveUsd`
   * it's ready at once; above it the card's user (or your account's owner) is asked first. A
   * `card.purchase` operation: `wait()` resolves to the `CardDetails` to pay with, and throws
   * `PolicyDenied` (declined) or `Expired` (nobody answered in 30 minutes). Needs `cards:reveal`.
   */
  async purchase(amountUsd: number, merchant: string, options: { reason?: string } = {}): Promise<Operation<CardDetails>> {
    const payload = await this._request("POST", `${await this.path()}/purchases`, {
      json: compact({ amount_usd: amountUsd, merchant, reason: options.reason }),
    });
    return Operation._fromPayload<CardDetails>(payload, { client: this._client, user: this._callScope(), kind: "card.purchase" });
  }

  /**
   * Dispute a settled charge with the card network: `fraudulent` (nobody here made it), `canceled`,
   * `duplicate` (name the charge it copies in `duplicateOf`), `not_received`, `not_as_described` (with
   * `product`) or `incorrect_amount` (with the `amountUsd` in dispute). A wrong purchase your agent made
   * is a merchant dispute, not fraud.
   */
  async dispute(
    transaction: CardTransaction | string,
    options: {
      reason: CardDisputeReason;
      explanation: string;
      amountUsd?: number;
      product?: "merchandise" | "service";
      duplicateOf?: CardTransaction | string;
    },
  ): Promise<CardDispute> {
    const id = typeof transaction === "string" ? transaction : transaction.id;
    const original = typeof options.duplicateOf === "object" ? options.duplicateOf.id : options.duplicateOf;
    return toDispute(await this._request("POST", `${await this.path()}/transactions/${id}/dispute`, {
      json: compact({
        reason: options.reason,
        explanation: options.explanation,
        amount_usd: options.amountUsd,
        product: options.product,
        duplicate_of: original,
      }),
    }));
  }

  /** Change its limits, merchants, approval threshold, agent or name; `null` clears a field. */
  async update(fields: CardUpdateOptions): Promise<this> {
    const changes = defined({
      name: fields.name,
      limit_usd: fields.limitUsd,
      interval: fields.interval,
      merchants: merchantList(fields.merchants),
      require_approval_above_usd: fields.requireApprovalAboveUsd,
      single_use: fields.singleUse,
    });
    if (fields.agent !== undefined) changes.agent_id = fields.agent === null ? null : ((await agentId(fields.agent)) ?? null);
    this._raw = await this._request<JsonObject>("PATCH", await this.path(), { json: changes });
    return this;
  }

  /** Decline every charge until `unfreeze()`; the card keeps its number and limits. */
  async freeze(): Promise<this> {
    return await this.act("freeze");
  }

  /**
   * Let a frozen card pay again. While your card balance is below zero every card stays frozen
   * (`statusReason` `negative_balance`): this throws `Conflict` until it's funded.
   */
  async unfreeze(): Promise<this> {
    return await this.act("unfreeze");
  }

  /** Close the card for good: it declines every charge and its number is never reissued. */
  async close(): Promise<this> {
    return await this.act("close");
  }
}

function toProgram(raw: JsonObject): CardProgram {
  return {
    status: (str(raw.status) ?? "not_started") as CardProgramStatus,
    requirementsDue: strings(raw.requirements_due),
    companyName: str(raw.company_name),
    country: str(raw.country),
    currency: str(raw.currency),
    onboardingUrl: str(raw.onboarding_url),
    raw,
  };
}
