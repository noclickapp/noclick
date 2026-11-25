/**
 * Your account's invite link: each person who joins NoClick through it, and starts using it, adds `rewardUsd` to your
 * balance. A user of your account has none of its own.
 *
 *     const referral = await Referral.get();
 *     console.log(referral.shareText, referral.joined, referral.earnedUsd);
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject, num, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** Your account's invite link and what it has earned. */
export class Referral {
  readonly code: string;
  readonly url: string;
  /** What a friend reads, then the link. */
  readonly shareText: string;
  /** What each friend who starts using NoClick adds to your balance. */
  readonly rewardUsd: number;
  /** How many joined through it. */
  readonly joined: number;
  /** How many of them earned the reward, and what it came to. */
  readonly earned: number;
  readonly earnedUsd: number;
  /** Whose link your account joined through, if it did. */
  readonly joinedThrough: { name: string | null; channel: string } | null;
  /** Until when your account can still apply an invite code (a day after it joined, once); null once it can't. */
  readonly canApplyUntil: Date | null;
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    const through = raw.joined_through && typeof raw.joined_through === "object" ? asObject(raw.joined_through) : null;
    this.code = String(raw.code ?? "");
    this.url = String(raw.url ?? "");
    this.shareText = String(raw.share_text ?? "");
    this.rewardUsd = num(raw.reward_usd) ?? 0;
    this.joined = num(raw.joined) ?? 0;
    this.earned = num(raw.earned) ?? 0;
    this.earnedUsd = num(raw.earned_usd) ?? 0;
    this.joinedThrough = through ? { name: str(through.name), channel: String(through.channel ?? "") } : null;
    this.canApplyUntil = parseTime(raw.can_apply_until);
    this.raw = raw;
  }

  /** Your account's invite link, how many joined and earned through it, and whose link your account joined through. */
  static async get(options: { client?: NoClick } = {}): Promise<Referral> {
    return new Referral(asObject(await resolveClient(options.client).request("GET", "/v1/referral", { user: null })));
  }

  /**
   * Apply a friend's invite `code` (or their join link) to your account, as the person they invited: only within a
   * day of your account's creation, and once. An unknown code throws `NotFound`; a second one `Conflict`.
   *
   *     await Referral.apply("ana-k3x9");
   */
  static async apply(code: string, options: { client?: NoClick } = {}): Promise<Referral> {
    return new Referral(asObject(await resolveClient(options.client).request("POST", "/v1/referral/apply", {
      json: { code }, user: null,
    })));
  }
}
