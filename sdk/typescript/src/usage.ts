/**
 * Usage: what the account (or the current user) spent, in total, over time, and against caps, and the workstreams
 * it's counted under.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject, compact, isoTime, num, parseTime, readScope, refId, requiredNumber, str } from "./object.ts";
import type { ApiObject, JsonObject, ReadOptions } from "./object.ts";
import type { UserOption } from "./scope.ts";

export interface UsageOptions {
  period?: string;
  groupBy?: "user" | "key" | "agent" | "project" | "person" | "workstream";
  agent?: string | ApiObject;
  user?: UserOption;
  client?: NoClick;
}

/**
 * Spend for `period` (default `month`), optionally split `groupBy` user, key, agent, `project` (each
 * app), `person` (who each charge was for: the person whose message, click or key started the work; the
 * account's owner for work nobody else started) or `workstream` (the line of work it belongs to, as the agent that
 * started it named it; the `null` one is work nobody named one for), and narrowed to one `agent`. Needs the `usage`
 * scope. Without `groupBy`, `groups` is empty.
 *
 *     const month = await usage({ groupBy: "user" });
 *     console.log(month.totalUsd, month.groups);
 *
 *     for (const person of (await usage({ groupBy: "person" })).groups) console.log(person.name, person.usd);
 *
 *     for (const line of (await usage({ groupBy: "workstream" })).groups) console.log(line.name ?? "(unnamed)", line.usd);
 */
export async function usage(options: UsageOptions = {}): Promise<Usage> {
  return await Usage.get(options);
}

export interface UsageGroup {
  id: string | null;
  /** A person's name, with `groupBy: "person"`, or a workstream's, with `groupBy: "workstream"`; otherwise null. */
  name: string | null;
  usd: number;
  events: number;
  raw: JsonObject;
}

export interface UsagePoint {
  /** The start of the interval. */
  t: Date | null;
  usd: number;
  events: number;
}

/** One key, user, agent, app, person, workstream or usage type's spend over the period. */
export interface UsageSeriesLine {
  id: string | null;
  /**
   * A key name (`Console` for the console key), a user's id, an agent name, a person's name, a workstream's name or a
   * type label.
   */
  label: string | null;
  totalUsd: number;
  events: number;
  points: UsagePoint[];
  raw: JsonObject;
}

export interface UsageSeries {
  interval: string;
  from: Date | null;
  to: Date | null;
  totalUsd: number;
  series: UsageSeriesLine[];
  raw: JsonObject;
}

export interface UsageSeriesOptions extends ReadOptions {
  /** Default: the current month (at most 92 days). */
  from?: Date | string;
  to?: Date | string;
  interval?: "day";
  /** `project`: one line per app; `person`: one per person each charge was for; `workstream`: one per workstream. */
  groupBy?: "key" | "user" | "agent" | "type" | "project" | "person" | "workstream";
  /** A key id or prefix. */
  key?: string;
  /** An `Agent` or agent id. */
  agent?: string | ApiObject;
}

/** A capped key's spend this month. */
export interface KeyCap {
  id: string;
  name: string | null;
  cap: number | null;
  spent: number;
  raw: JsonObject;
}

/** A capped user's spend this month. */
export interface UserCap {
  /** Your id for the user. */
  id: string;
  cap: number | null;
  spent: number;
  raw: JsonObject;
}

/** A budgeted agent's spend this month; `subtreeSpent` adds the agents it spawned. */
export interface AgentBudget {
  id: string;
  name: string | null;
  budget: number | null;
  spent: number;
  subtreeSpent: number;
  raw: JsonObject;
}

/** A budgeted app's spend this month; `userId` is the user it belongs to (null: your account's own). */
export interface ProjectBudget {
  id: string;
  name: string | null;
  userId: string | null;
  budget: number | null;
  spent: number;
  raw: JsonObject;
}

/**
 * Who set your account's monthly cap last: `by` (`owner`, signed in; `key`, one of your account's keys; `connection`,
 * an MCP connection; `agent`, an agent's turn; `assistant`, your NoClick assistant), the person it was for
 * (`responsibleUserId`: the person whose message started the agent's turn, the person a connection acts for, else
 * your account's owner), the key it was made with, the connection (`grantId`) and agent (`agentId`, its `turnId`) it
 * came through and their name (`client`), the approval a raise ran on, the cap before and after, and when.
 */
export interface CapChange {
  by: string;
  responsibleUserId: string | null;
  keyId: string | null;
  grantId: string | null;
  agentId: string | null;
  turnId: string | null;
  client: string | null;
  approvalId: string | null;
  capBeforeUsd: number | null;
  capAfterUsd: number | null;
  at: Date | null;
  raw: JsonObject;
}

/**
 * Your account's monthly spending cap: `capUsd` (null while none is set) and, where one is set, what its billing
 * period has spent (`spentUsd`), when that period started and resets, and whether it's `reached`: then every call
 * that costs money rejects with `SpendCapExceeded`. `setBy` says who set it last (null: nobody has, or only NoClick's
 * own hold on an account no person has claimed).
 */
export interface AccountCap {
  capUsd: number | null;
  spentUsd: number | null;
  periodStart: Date | null;
  resetsAt: Date | null;
  reached: boolean;
  raw: JsonObject;
  setBy: CapChange | null;
}

/** Every capped key, user and agent with this month's spend, every app with a budget, and your account's own cap. */
export interface UsageLimits {
  periodStart: Date | null;
  resetsAt: Date | null;
  keys: KeyCap[];
  users: UserCap[];
  agents: AgentBudget[];
  /** Each app with a `budgetUsdPerMonth`. */
  projects: ProjectBudget[];
  raw: JsonObject;
  /** Your account's monthly spending cap, over its billing period. */
  account: AccountCap | null;
}

/**
 * One group of the account's ledger: its charges in one period (this billing period or the one before), one day
 * and one set of breakdown fields, added up.
 */
export interface LedgerGroup {
  /** The group's key: list its charges with `Usage.charges({ keys: [key] })`. */
  key: string;
  /** In this billing period (true) or the one before. */
  current: boolean;
  /** Its day (`YYYY-MM-DD`) in the zone the ledger was read in. */
  day: string;
  usageType: string;
  /** What was charged for: a model's id, or a service like `voice/call` or `apps/hosting`. */
  subtype: string;
  unit: string;
  /** On the account's own key or resource: nobody was charged. */
  ownResource: boolean;
  /** How many charges it holds. */
  charges: number;
  quantity: number;
  usd: number;
  /** Every breakdown field (`UsageLedger.fields`) by name: the automation, agent step, person, app, key… it names. */
  fields: Record<string, unknown>;
  raw: JsonObject;
}

/** The account's ledger: every charge it was billed in its billing period and the one before, grouped. */
export interface UsageLedger {
  periodStart: Date | null;
  periodEnd: Date | null;
  /** Where the period before starts. */
  previousStart: Date | null;
  /** The fields each group is split by. */
  fields: string[];
  groups: LedgerGroup[];
  /** Names for what the groups name, by kind (`workflows`, `agents`, `people`, `projects`, `keys`…) and id. */
  directory: Record<string, Record<string, JsonObject>>;
  raw: JsonObject;
}

/** One charge in the account's ledger. */
export interface LedgerCharge {
  id: string;
  at: Date | null;
  usageType: string;
  subtype: string;
  unit: string;
  quantity: number;
  usd: number;
  ownResource: boolean;
  /** Its group's key. */
  key: string;
  /** What it was for: the automation, agent step and run, the number, sender, key or app it names. */
  metadata: JsonObject;
  raw: JsonObject;
}

/** A page of the ledger's charges, newest first. */
export interface UsageCharges {
  charges: LedgerCharge[];
  /** The runs the charges were recorded in, by run id. */
  runs: Record<string, JsonObject>;
  /** Pass as `cursor` for the next page; null at the end. */
  next: string | null;
  raw: JsonObject;
}

export interface UsageChargesOptions {
  /** Default: the billing period's start. */
  from?: Date | string;
  /** Default: the billing period's end. */
  to?: Date | string;
  /** Only charges in these groups (`LedgerGroup.key`). */
  keys?: string[];
  /** Only charges on this day (`YYYY-MM-DD`) in `tz`. */
  day?: string;
  /** The IANA time zone the ledger was read in. */
  tz?: string;
  /** The previous page's `next`. */
  cursor?: string;
  /** Charges per page, up to 500 (default 50). */
  limit?: number;
  client?: NoClick;
}

/**
 * The money behind the ledger, as the credit gate reads it. One of the account's own keys reads the plan, the
 * balance, funds added and what's scheduled; `autoTopUp` and friends' credit (in `raw`) are the signed-in owner's.
 */
export interface UsageBilling {
  /** The plan, its window and its pools: included usage, Free's daily share, an older plan's top-up. */
  plan: JsonObject;
  /** What was added less what it paid for; below zero is owed. */
  balanceUsd: number;
  /** Funds added this period, and the plan's fee on them. */
  fundsUsd: number;
  feesUsd: number;
  /** Charges that come on a date: a number's month, a connection's hours. */
  recurring: JsonObject[];
  /** Domains that renew soon. */
  domains: JsonObject[];
  /** Auto top-up, for the signed-in owner; null otherwise. */
  autoTopUp: JsonObject | null;
  raw: JsonObject;
}

/**
 * The plan's subscription, an older plan's credit top-up subscription and the default card, as Stripe holds them for
 * the signed-in owner (or a team workspace they own or administer); each null where there's none.
 */
export interface BillingDetails {
  subscription: {
    status: string;
    /** When it renews, or ends when it's set to end; ISO 8601. */
    currentPeriodEnd: string | null;
    cancelAtPeriodEnd: boolean;
  } | null;
  topupSubscription: {
    status: string;
    currentPeriodEnd: string | null;
    cancelAtPeriodEnd: boolean;
    creditsPerMonth: number;
    interval: "month" | "year";
    subscriptionId: string;
  } | null;
  paymentMethod: { brand: string; last4: string; expMonth: number; expYear: number } | null;
}

/**
 * The pool a workspace's work draws on, as NoClick's balance meter reads it, in credits: the included usage `used`
 * against `limit` in the `period` (`day` where the plan counts by day, else `month`), the month's `monthlyUsed`
 * against `monthlyCap`, and the dollar balance drawn after it. `poolUserId` is whose pool it is; `isOrgCredits` when
 * that's the owner of a team workspace you're in, not you.
 */
export interface UsageCredits {
  used: number;
  limit: number | null;
  period: string;
  monthlyUsed: number | null;
  monthlyCap: number | null;
  balanceUsd: number | null;
  tier: string | null;
  poolUserId: string;
  isOrgCredits: boolean;
  raw: JsonObject;
}

function rows(value: unknown): JsonObject[] {
  return Array.isArray(value) ? (value as JsonObject[]) : [];
}

function ledgerGroup(raw: JsonObject, fields: string[]): LedgerGroup {
  return {
    key: String(raw.k),
    current: raw.current === true,
    day: String(raw.day),
    usageType: String(raw.usage_type),
    subtype: String(raw.usage_subtype),
    unit: String(raw.unit_type),
    ownResource: raw.user_resource === true,
    charges: requiredNumber(raw, "n"),
    quantity: requiredNumber(raw, "quantity"),
    usd: requiredNumber(raw, "total_cost"),
    fields: Object.fromEntries(fields.map((name) => [name, raw[name] ?? null])),
    raw,
  };
}

function ledgerCharge(raw: JsonObject): LedgerCharge {
  return {
    id: String(raw.id),
    at: parseTime(raw.created_at),
    usageType: String(raw.usage_type),
    subtype: String(raw.usage_subtype),
    unit: String(raw.unit_type),
    quantity: requiredNumber(raw, "quantity"),
    usd: requiredNumber(raw, "total_cost"),
    ownResource: raw.user_resource === true,
    key: String(raw.k),
    metadata: asObject(raw.metadata),
    raw,
  };
}

function capChange(raw: JsonObject): CapChange {
  return {
    by: String(raw.by),
    responsibleUserId: str(raw.responsible_user_id),
    keyId: str(raw.key_id),
    grantId: str(raw.grant_id),
    agentId: str(raw.agent_id),
    turnId: str(raw.turn_id),
    client: str(raw.client),
    approvalId: str(raw.approval_id),
    capBeforeUsd: num(raw.cap_before_usd),
    capAfterUsd: num(raw.cap_after_usd),
    at: parseTime(raw.at),
    raw,
  };
}

function accountCap(raw: JsonObject): AccountCap {
  return {
    capUsd: num(raw.cap_usd),
    spentUsd: num(raw.spent_usd),
    periodStart: parseTime(raw.period_start),
    resetsAt: parseTime(raw.resets_at),
    reached: raw.reached === true,
    raw,
    setBy: raw.set_by ? capChange(asObject(raw.set_by)) : null,
  };
}

export class Usage {
  readonly period: string;
  readonly totalUsd: number;
  readonly groups: UsageGroup[];
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.period = str(raw.period) ?? "";
    this.totalUsd = Number(raw.total_usd ?? 0);
    this.groups = (Array.isArray(raw.groups) ? (raw.groups as JsonObject[]) : []).map((group) => ({
      id: str(group.id),
      name: str(group.name),
      usd: Number(group.usd ?? 0),
      events: Number(group.events ?? 0),
      raw: group,
    }));
    this.raw = raw;
  }

  /** @deprecated Use `usage()`. */
  static async get(options: UsageOptions = {}): Promise<Usage> {
    const raw = await resolveClient(options.client).request("GET", "/v1/usage", {
      query: { period: options.period ?? "month", group_by: options.groupBy, agent_id: await refId(options.agent) },
      user: options.user,
    });
    return new Usage(asObject(raw));
  }

  /**
   * The spend of one user, key, agent, app or person id in a grouped usage (null is the account's own); an id
   * that spent nothing reads as $0 with no events.
   */
  group(id: string | null): UsageGroup {
    return this.get(id) ?? { id, name: null, usd: 0, events: 0, raw: {} };
  }

  /** The group of an id that spent something in a grouped usage, else null. */
  get(id: string | null): UsageGroup | null {
    if (!this.raw.group_by) throw new TypeError("This usage isn't grouped: read it with usage({ groupBy }).");
    return this.groups.find((group) => group.id === id) ?? null;
  }

  /** Daily spend between `from` and `to`, one line per key, user, agent, app, person, workstream or usage type. */
  static async series(options: UsageSeriesOptions = {}): Promise<UsageSeries> {
    const { user, userId } = await readScope(options);
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/usage/series", {
      query: {
        from: isoTime(options.from),
        to: isoTime(options.to),
        interval: options.interval,
        group_by: options.groupBy,
        key_id: options.key,
        user_id: userId,
        agent_id: await refId(options.agent),
      },
      user,
    }));
    return {
      interval: str(raw.interval) ?? "",
      from: parseTime(raw.from),
      to: parseTime(raw.to),
      totalUsd: requiredNumber(raw, "total_usd"),
      series: rows(raw.series).map((line) => ({
        id: str(line.id),
        label: str(line.label),
        totalUsd: requiredNumber(line, "total_usd"),
        events: requiredNumber(line, "events"),
        points: rows(line.points).map((point) => ({ t: parseTime(point.t), usd: requiredNumber(point, "usd"), events: requiredNumber(point, "events") })),
        raw: line,
      })),
      raw,
    };
  }

  /**
   * The account's ledger, as Settings → Usage reads it: every charge it was billed in its billing period and the
   * one before (its automations' runs, its chat with NoClick, a teammate's work it pays for, its keys' and agents'
   * calls), grouped by day in `tz` and by every field a breakdown splits by, with names for what they were for.
   * For the signed-in owner and the account's own secret keys. `usage()` reads only what its keys and agents spent.
   *
   *     const ledger = await Usage.ledger({ tz: "Europe/London" });
   *     const thisPeriod = ledger.groups.filter((g) => g.current && !g.ownResource);
   *     console.log(thisPeriod.reduce((sum, g) => sum + g.usd, 0));
   */
  static async ledger(options: { tz?: string; client?: NoClick } = {}): Promise<UsageLedger> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/usage/groups", {
      query: { tz: options.tz }, user: null,
    }));
    const period = asObject(raw.period);
    const fields = Array.isArray(raw.fields) ? raw.fields.map(String) : [];
    return {
      periodStart: parseTime(period.window_start),
      periodEnd: parseTime(period.window_end),
      previousStart: parseTime(period.previous_start),
      fields,
      groups: rows(raw.groups).map((group) => ledgerGroup(group, fields)),
      directory: asObject(raw.directory) as Record<string, Record<string, JsonObject>>,
      raw,
    };
  }

  /**
   * A page of the ledger's charges, newest first, narrowed to groups (`keys`) or a day; the billing period's by
   * default. Pass `next` back as `cursor` for the page after it.
   *
   *     const ledger = await Usage.ledger();
   *     const calls = ledger.groups.filter((g) => g.current && g.subtype === "voice/call").map((g) => g.key);
   *     let page = await Usage.charges({ keys: calls });
   *     while (page.next) page = await Usage.charges({ keys: calls, cursor: page.next });
   */
  static async charges(options: UsageChargesOptions = {}): Promise<UsageCharges> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/usage/charges", {
      json: compact({
        start: isoTime(options.from), end: isoTime(options.to), keys: options.keys, day: options.day, tz: options.tz,
        cursor: options.cursor, limit: options.limit,
      }),
      user: null,
    }));
    return {
      charges: rows(raw.rows).map(ledgerCharge),
      runs: asObject(raw.runs) as Record<string, JsonObject>,
      next: str(raw.next),
      raw,
    };
  }

  /**
   * The money behind the ledger, as the credit gate reads it: the plan and its pools, the balance, funds added and
   * what's scheduled to be charged; null where nobody is billed.
   */
  static async billing(options: { client?: NoClick } = {}): Promise<UsageBilling | null> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/usage/billing", { user: null }));
    if (raw.billing === null || raw.billing === undefined) return null;
    const billing = asObject(raw.billing);
    const funds = asObject(billing.funds);
    return {
      plan: asObject(billing.plan),
      balanceUsd: requiredNumber(asObject(billing.balance), "usd"),
      fundsUsd: requiredNumber(funds, "usd"),
      feesUsd: requiredNumber(funds, "fee"),
      recurring: rows(billing.recurring),
      domains: rows(billing.domains),
      autoTopUp: billing.autoTopUp ? asObject(billing.autoTopUp) : null,
      raw: billing,
    };
  }

  /**
   * Change auto top-up, as the app's billing settings do (the signed-in owner's alone: it charges their saved method):
   * refill `amountUsd` when the balance falls below `thresholdUsd`, at most `monthlyCapUsd` a month, all whole dollars
   * within the funds checkout's rules; `enabled` turns it on (only with a method saved during a payment made with Refill
   * automatically) or off, and left out keeps it as it is. Resolves with it as it stands.
   */
  static async setAutoTopUp(
    settings: { enabled?: boolean; thresholdUsd: number; amountUsd: number; monthlyCapUsd: number },
    options: { client?: NoClick } = {},
  ): Promise<JsonObject> {
    return asObject(await resolveClient(options.client).request("PUT", "/v1/usage/billing/auto_topup", {
      json: compact({
        enabled: settings.enabled, threshold_usd: settings.thresholdUsd, amount_usd: settings.amountUsd,
        monthly_cap_usd: settings.monthlyCapUsd,
      }),
      user: null,
    }));
  }

  /**
   * The plan's Stripe subscription, an older plan's credit top-up subscription and the default card. The signed-in
   * owner's alone; `organizationId` names a team workspace they own or administer.
   *
   *     const { subscription, paymentMethod } = await Usage.billingDetails();
   */
  static async billingDetails(options: { organizationId?: string; client?: NoClick } = {}): Promise<BillingDetails> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/usage/billing/details", {
      query: { organization_id: options.organizationId },
      user: null,
    }));
    const sub = raw.subscription ? asObject(raw.subscription) : null;
    const topup = raw.topup_subscription ? asObject(raw.topup_subscription) : null;
    const card = raw.payment_method ? asObject(raw.payment_method) : null;
    return {
      subscription: sub && {
        status: str(sub.status) ?? "", currentPeriodEnd: str(sub.current_period_end), cancelAtPeriodEnd: sub.cancel_at_period_end === true,
      },
      topupSubscription: topup && {
        status: str(topup.status) ?? "", currentPeriodEnd: str(topup.current_period_end),
        cancelAtPeriodEnd: topup.cancel_at_period_end === true, creditsPerMonth: Number(topup.credits_per_month ?? 0),
        interval: topup.interval === "year" ? "year" : "month", subscriptionId: str(topup.subscription_id) ?? "",
      },
      paymentMethod: card && {
        brand: str(card.brand) ?? "unknown", last4: str(card.last4) ?? "", expMonth: Number(card.exp_month ?? 0),
        expYear: Number(card.exp_year ?? 0),
      },
    };
  }

  /**
   * A session on Stripe's customer portal, where the signed-in owner changes their plan, card and invoices: open its
   * URL within a few minutes. `organizationId` names a team workspace they own or administer.
   *
   *     window.location.href = await Usage.billingPortal();
   */
  static async billingPortal(options: { organizationId?: string; client?: NoClick } = {}): Promise<string> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/usage/billing/portal", {
      json: compact({ organization_id: options.organizationId }),
      user: null,
    }));
    const url = str(raw.url);
    if (!url) throw new Error("NoClick answered no customer portal URL.");
    return url;
  }

  /**
   * What NoClick's balance meter shows: the included usage used and its cap, the balance, and whose pool it is.
   * `organizationId` names a team workspace you're in, whose work draws on its owner's pool.
   */
  static async credits(options: { organizationId?: string; client?: NoClick } = {}): Promise<UsageCredits> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/usage/credits", {
      query: { organization_id: options.organizationId },
      user: null,
    }));
    return {
      used: requiredNumber(raw, "used"),
      limit: num(raw.limit),
      period: str(raw.period) ?? "month",
      monthlyUsed: num(raw.monthly_used),
      monthlyCap: num(raw.monthly_cap),
      balanceUsd: num(raw.balance_usd),
      tier: str(raw.effective_tier),
      poolUserId: String(raw.pool_user_id),
      isOrgCredits: raw.is_org_credits === true,
      raw,
    };
  }

  /**
   * This month's spend of every capped key, user and agent (account principals), of every budgeted app, and your
   * account's own monthly cap (`account`).
   */
  static async limits(options: { client?: NoClick } = {}): Promise<UsageLimits> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/usage/limits", { user: null }));
    return {
      periodStart: parseTime(raw.period_start),
      resetsAt: parseTime(raw.resets_at),
      keys: rows(raw.keys).map((row) => ({
        id: String(row.id), name: str(row.name), cap: num(row.cap), spent: requiredNumber(row, "spent"), raw: row,
      })),
      users: rows(raw.users).map((row) => ({
        id: String(row.id), cap: num(row.cap), spent: requiredNumber(row, "spent"), raw: row,
      })),
      agents: rows(raw.agents).map((row) => ({
        id: String(row.id), name: str(row.name), budget: num(row.budget), spent: requiredNumber(row, "spent"),
        subtreeSpent: requiredNumber(row, "subtree_spent"), raw: row,
      })),
      projects: rows(raw.projects).map((row) => ({
        id: String(row.id), name: str(row.name), userId: str(row.user_id), budget: num(row.budget),
        spent: requiredNumber(row, "spent"), raw: row,
      })),
      raw,
      account: raw.account ? accountCap(asObject(raw.account)) : null,
    };
  }

  /**
   * Set your account's monthly spending cap, in whole dollars; `null` removes it. Past it, every call that costs
   * money rejects with `SpendCapExceeded` until the billing period resets. Your account's own keys lower the cap, or
   * set one where there's none; raising or removing it is your account's owner's (in Settings → Plan and billing in
   * the NoClick app), so from a key it rejects with `PermissionDenied` and changes nothing. Through MCP, and from an
   * agent on the word of the person whose message started its turn, a raise or a removal waits for the owner's
   * approval. Needs the `usage` scope. Resolves to the cap as it stands, with who set it (`setBy`).
   *
   *     const cap = await Usage.setAccountCap(50);
   *     console.log(cap.capUsd, cap.spentUsd, cap.resetsAt);
   */
  static async setAccountCap(capUsd: number | null, options: { client?: NoClick } = {}): Promise<AccountCap> {
    const raw = await resolveClient(options.client).request("PUT", "/v1/usage/limits/account", {
      json: { cap_usd: capUsd },
      user: null,
    });
    return accountCap(asObject(raw));
  }
}

/**
 * A line of work your spend is counted under. An agent names one when it starts work (a child's task, a message it
 * hands another agent, an app's coding job; `agent.spawn(task, { workstream })`), from your workstreams or a new
 * name, and every charge of that work, and of what it starts, belongs to it. A person renames one, or archives it
 * once its work is done: its charges still read under it, and it leaves the workstreams agents choose from until
 * it's brought back or an agent names it again.
 *
 *     for (const workstream of await Workstream.list()) console.log(workstream.name, workstream.spentUsd);
 *     await Workstream.rename("Menu", "Bakery site");   // merges Menu into Bakery site
 *     await Workstream.archive("Q3 launch");
 */
export class Workstream {
  readonly id: string;
  /** As it was first written; matched whatever its case. */
  readonly name: string;
  /** What it spent this month (a call acting for one of your users: that user's share). */
  readonly spentUsd: number;
  readonly events: number;
  /** Put away: out of the workstreams agents choose from, its charges still under it. */
  readonly archived: boolean;
  readonly createdAt: Date | null;
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.id = String(raw.id);
    this.name = String(raw.name);
    this.spentUsd = num(raw.spent_usd) ?? 0;
    this.events = num(raw.events) ?? 0;
    this.archived = raw.archived === true;
    this.createdAt = parseTime(raw.created_at);
    this.raw = raw;
  }

  /**
   * Your open workstreams (`archived: true`: the ones put away), most spent this month first, each with what it spent
   * (as `usage({ groupBy: "workstream" })` counts it). Needs the `usage` scope.
   */
  static async list(options: { archived?: boolean; user?: UserOption; client?: NoClick } = {}): Promise<Workstream[]> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/workstreams", {
      user: options.user,
      query: options.archived ? { archived: true } : undefined,
    }));
    return rows(raw.data).map((row) => new Workstream(row));
  }

  /**
   * Rename `workstream` (a `Workstream`, its name in any case, or its id) to `name`. Renamed onto another
   * workstream's name, it merges into that one: its charges so far read as that one's (none is rewritten), and
   * `raw.merged_from` names it. Your account's alone: a call acting for one of your users can't. Answers the
   * workstream it reads as now, without this month's spend (`Workstream.list()` reads it). Needs the `usage` scope.
   */
  static async rename(workstream: string | Workstream, name: string, options: { client?: NoClick } = {}): Promise<Workstream> {
    return Workstream.change(workstream, { name }, options);
  }

  /**
   * Archive `workstream` (a `Workstream`, its name in any case, or its id) once its work is done: its charges still
   * read under it, and it leaves `Workstream.list()` (`{ archived: true }` lists it) and the workstreams agents choose
   * from, until `unarchive` brings it back or an agent names it again. Your account's alone. Needs the `usage` scope.
   */
  static async archive(workstream: string | Workstream, options: { client?: NoClick } = {}): Promise<Workstream> {
    return Workstream.change(workstream, { archived: true }, options);
  }

  /** Bring an archived `workstream` back among your open ones. Your account's alone. Needs the `usage` scope. */
  static async unarchive(workstream: string | Workstream, options: { client?: NoClick } = {}): Promise<Workstream> {
    return Workstream.change(workstream, { archived: false }, options);
  }

  private static async change(workstream: string | Workstream, json: JsonObject, options: { client?: NoClick }): Promise<Workstream> {
    const ref = typeof workstream === "string" ? workstream : workstream.id;
    const raw = await resolveClient(options.client).request("PATCH", `/v1/workstreams/${encodeURIComponent(ref)}`, {
      json,
      user: null,
    });
    return new Workstream(asObject(raw));
  }
}
