/**
 * What a `noclick` command's exit status means: the one table both CLIs follow (Python's `noclick/_cli/exits.py`),
 * so an agent acts on it without reading the words.
 *
 * 0 done, 1 failed, 2 the command line was wrong (or the API refused its arguments), 3 waiting on a person (the link
 * is printed), 4 refused by a limit, a price or a policy, 124 a wait ran out (the work goes on), 130 Ctrl-C.
 */

import { NoClickError } from "../errors.ts";
import type { ErrorInit } from "../errors.ts";

export const OK = 0;
export const FAILED = 1;
export const USAGE = 2;
export const WAITING = 3;
export const REFUSED = 4;
export const TIMED_OUT = 124;
export const INTERRUPTED = 130;

/** Each status in a word, as `noclick help --json` lists them. */
export const MEANINGS: Record<string, string> = {
  [OK]: "done", [FAILED]: "failed", [USAGE]: "usage", [WAITING]: "waiting on a person",
  [REFUSED]: "refused by a limit, a price or a policy", [TIMED_OUT]: "a wait ran out",
  [INTERRUPTED]: "interrupted (Ctrl-C)",
};

/** What only a person can do now (approve, pay, answer, sign in): `link` is where they do it. Exits 3. */
export class WaitingOnPerson extends NoClickError {
  static override errorType = "waiting_on_person";

  constructor(message: string, init: ErrorInit & { link?: string | null } = {}) {
    super(message, init);
    if (!("link" in this.details)) this.details.link = init.link ?? null;
  }
}

/** A `--max-usd` (or another ceiling the command line set) the action would pass: nothing was done. Exits 4. */
export class OverLimit extends NoClickError {
  static override errorType = "over_limit";
}

export const WAITING_TYPES = new Set([
  "waiting_on_person", "payment_required", "plan_required", "approval_required", "action_required",
  "answer_required", "needs_connection", "credential_disconnected",
]);
export const REFUSED_TYPES = new Set([
  "over_limit", "price_exceeded", "spend_cap_exceeded", "spending_paused", "permission_denied", "policy_denied",
  "quota_exceeded", "plan_limit_reached", "rate_limited",
]);
export const USAGE_TYPES = new Set(["invalid_request", "not_linked"]);
const TIMED_OUT_TYPES = new Set(["operation_timeout"]);
/** An operation's status that only a person moves on. */
export const WAITING_STATUSES = new Set(["awaiting_human", "awaiting_approval", "awaiting_payment"]);

/** The exit status an error of `errorType` means. */
export function exitCode(errorType: string | null | undefined): number {
  if (!errorType) return FAILED;
  if (WAITING_TYPES.has(errorType)) return WAITING;
  if (REFUSED_TYPES.has(errorType)) return REFUSED;
  if (USAGE_TYPES.has(errorType)) return USAGE;
  if (TIMED_OUT_TYPES.has(errorType)) return TIMED_OUT;
  return FAILED;
}

/** Where a person acts on an error that waits on them, when it says. */
export function linkOf(error: { details?: Record<string, unknown> }): string | null {
  const details = error.details ?? {};
  for (const name of ["link", "approve_url", "answer_url", "url", "connect_url", "payment_url", "checkout_url"]) {
    const value = details[name];
    if (typeof value === "string" && value) return value;
  }
  return null;
}
