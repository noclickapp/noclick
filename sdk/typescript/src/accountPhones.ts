/**
 * AccountPhones: the phone numbers your account's owner messages and calls NoClick from, each proven theirs.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** One number linked to the account: how it was proven (`verify`, a code texted to it; `whatsapp` or `imessage`, it
 *  texted NoClick) and when. */
export interface LinkedPhone {
  phone: string;
  source: string;
  verifiedAt: Date | null;
}

/** A code texted to a number to link it: check it with `AccountPhones.verify` before `expiresAt`. */
export interface PhoneChallenge {
  id: string;
  phone: string;
  expiresAt: Date | null;
  raw: JsonObject;
}

const linked = (raw: unknown): LinkedPhone => {
  const row = asObject(raw);
  return { phone: str(row.phone) ?? "", source: str(row.source) ?? "verify", verifiedAt: parseTime(row.verified_at) };
};

/**
 * The numbers linked to your account. A linked number reaches the account: texts and calls from it go to its owner's
 * NoClick, and the web's phone sign-in signs in to the account with it. So these are the signed-in owner's, or a key
 * of your account's own that names the `account:phones` scope (a key with `*` doesn't hold it unless it's named too);
 * any other caller rejects with `PermissionDenied`. Refusals carry their kind in `error.details.reason`
 * (`invalid_code`, `expired`, `already_linked`, `linked_elsewhere`, `last_way_in`, ...).
 */
export class AccountPhones {
  /** Whether this NoClick sends codes to link a number. */
  readonly configured: boolean;
  /** How many numbers an account may link. */
  readonly maxPhones: number;
  readonly phones: readonly LinkedPhone[];
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.configured = raw.configured === true;
    this.maxPhones = typeof raw.max_phones === "number" ? raw.max_phones : 0;
    this.phones = asList(raw.phones).map(linked);
    this.raw = raw;
  }

  /**
   * Read the numbers linked to the account.
   *
   *     const { phones, maxPhones } = await AccountPhones.get();
   */
  static async get(options: { client?: NoClick } = {}): Promise<AccountPhones> {
    return new AccountPhones(asObject(await resolveClient(options.client).request("GET", "/v1/account/phones", { user: null })));
  }

  /**
   * Text a code to `phone` (with its country code, like `+14155550123`) to link it. Resolves to the challenge the code
   * is checked against with `AccountPhones.verify`, within ten minutes.
   *
   *     const challenge = await AccountPhones.link("+14155550123");
   */
  static async link(phone: string, options: { client?: NoClick } = {}): Promise<PhoneChallenge> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/account/phones", { json: { phone }, user: null }));
    return { id: str(raw.id) ?? "", phone: str(raw.phone) ?? phone, expiresAt: parseTime(raw.expires_at), raw };
  }

  /**
   * Link the challenge's number with the code texted to it. A wrong code rejects with `InvalidRequest` (`reason`
   * `invalid_code`) and can be tried again; an expired challenge (`Expired`) or too many tries (`RateLimited`) needs a
   * new code.
   *
   *     await AccountPhones.verify(challenge.id, "123456");
   */
  static async verify(challengeId: string, code: string, options: { client?: NoClick } = {}): Promise<LinkedPhone> {
    const raw = await resolveClient(options.client).request("POST", "/v1/account/phones/verify", {
      json: { challenge_id: challengeId, code },
      user: null,
    });
    return linked(raw);
  }

  /**
   * Unlink a number: texts and calls from it no longer reach the account, at once. The only number of an account with
   * no email rejects with `Conflict` (`reason` `last_way_in`).
   *
   *     await AccountPhones.unlink("+14155550123");
   */
  static async unlink(phone: string, options: { client?: NoClick } = {}): Promise<void> {
    await resolveClient(options.client).request("DELETE", `/v1/account/phones/${encodeURIComponent(phone)}`, { user: null });
  }
}
