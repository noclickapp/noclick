/** Cron: a schedule, for app schedules and agent triggers. */

import type { JsonObject } from "./object.ts";

export interface CronOptions {
  /**
   * The timezone the expression is read in; UTC by default. `"user"` reads it in a user's agent's (or
   * channel's) user's `timezone`, following them when they move (UTC while they have none; an account
   * agent refuses it); a wake-up reads it in the timezone of the user whose conversation it wakes.
   */
  tz?: string;
  /** The turn's text when this schedule wakes an agent, what it posts in a channel; apps ignore it. */
  message?: string;
}

/**
 * A schedule: a five-field cron expression (minute, hour, day of month, month, day of week: numbers,
 * `*`, ranges, steps, lists and month or day names) read in a timezone, so
 * `new Cron("0 9 * * 1-5", { tz: "America/New_York" })` means 9am New York time on weekdays, daylight
 * saving included. When both day fields are restricted a run must match both. An agent's schedule
 * wakes it with `message` (each run a conversation of its own); a wake-up's `every` wakes one
 * conversation at each time, with its `note` (a routine: `agent.wake`); a channel's posts `message`
 * in the room; an app's calls one of its paths.
 */
export class Cron {
  readonly expr: string;
  readonly tz: string;
  readonly message: string | null;

  constructor(expr: string, options: CronOptions = {}) {
    this.expr = expr;
    this.tz = options.tz ?? "UTC";
    this.message = options.message ?? null;
  }

  /** @internal */
  toWire(): JsonObject {
    return { cron: this.expr, tz: this.tz, ...(this.message !== null ? { message: this.message } : {}) };
  }
}
