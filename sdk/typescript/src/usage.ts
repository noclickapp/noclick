/**
 * Usage: what the account (or the current user) spent, in total, over time, and against caps.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject, isoTime, num, parseTime, readScope, refId, requiredNumber, str } from "./object.ts";
import type { ApiObject, JsonObject, ReadOptions } from "./object.ts";
import type { UserOption } from "./scope.ts";

export interface UsageOptions {
  period?: string;
  groupBy?: "user" | "key" | "agent" | "project" | "person";
  agent?: string | ApiObject;
  user?: UserOption;
  client?: NoClick;
}

/**
 * Spend for `period` (default `month`), optionally split `groupBy` user, key, agent, `project` (each
 * app) or `person` (who each charge was for: the person whose message, click or key started the work; the
 * account's owner for work nobody else started), and narrowed to one `agent`. Needs the `usage` scope. Without
 * `groupBy`, `groups` is empty.
 *
 *     const month = await usage({ groupBy: "user" });
 *     console.log(month.totalUsd, month.groups);
 *
 *     for (const person of (await usage({ groupBy: "person" })).groups) console.log(person.name, person.usd);
 */
export async function usage(options: UsageOptions = {}): Promise<Usage> {
  return await Usage.get(options);
}

export interface UsageGroup {
  id: string | null;
  /** A person's name, with `groupBy: "person"`; otherwise null. */
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

/** One key, user, agent, app, person or usage type's spend over the period. */
export interface UsageSeriesLine {
  id: string | null;
  /** A key name (`Console` for the console key), a user's id, an agent name, a person's name or a type label. */
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
  /** `project`: one line per app; `person`: one per person each charge was for. */
  groupBy?: "key" | "user" | "agent" | "type" | "project" | "person";
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

/** Every capped key, user and agent with this month's spend, and every app with a budget. */
export interface UsageLimits {
  periodStart: Date | null;
  resetsAt: Date | null;
  keys: KeyCap[];
  users: UserCap[];
  agents: AgentBudget[];
  /** Each app with a `budgetUsdPerMonth`. */
  projects: ProjectBudget[];
  raw: JsonObject;
}

function rows(value: unknown): JsonObject[] {
  return Array.isArray(value) ? (value as JsonObject[]) : [];
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

  /** Daily spend between `from` and `to`, one line per key, user, agent, app, person or usage type. */
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

  /** This month's spend of every capped key, user and agent (account principals), and of every budgeted app. */
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
    };
  }
}
