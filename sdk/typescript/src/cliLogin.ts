/**
 * Signing a command line in: a device sign-in (`CliLogin.start`, then `poll` until a person approves it on the page it
 * names), made before there is a key, so it sends none (a setup code is `Key.redeemSetupCode`); the sign-in as the
 * account's signed-in owner reads and answers it (`CliLogin.get`, `answer`); and what `accountStatus` reads about the
 * key a client holds.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject, num, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** A sign-in waiting on a person: they open `verificationUrl` and enter `userCode`; poll with `deviceCode`. */
export interface CliLoginStart {
  deviceCode: string;
  userCode: string;
  verificationUrl: string;
  /** The page with the code already filled in. */
  verificationUrlComplete: string | null;
  /** How often to poll, in seconds. */
  intervalS: number;
  expiresAt: string | null;
  raw: JsonObject;
}

/** A poll's answer: `pending` (or `slow_down`) until approved, then the key, once. */
export interface CliLoginPoll {
  status: "pending" | "slow_down" | "approved";
  intervalS: number | null;
  /** The new key (`nk_live_...`), only when `approved`. Keep it out of anything you print. */
  key: string | null;
  keyId: string | null;
  keyName: string | null;
  email: string | null;
  raw: JsonObject;
}

/**
 * A device sign-in, what a command line does to get a key without anyone pasting one (`start`, `poll`), and one
 * waiting, as its approver reads it: the `userCode` its terminal shows, the `client` and `hostname` that started it, the address it came
 * from (`ip`), the name of the key it gets (`keyName`), its `status` (`pending`, `approved` or `denied`) and when it
 * lapses.
 */
export class CliLogin {
  readonly userCode: string;
  readonly client: string;
  readonly hostname: string;
  readonly ip: string | null;
  readonly keyName: string;
  readonly status: string;
  readonly createdAt: Date | null;
  readonly expiresAt: Date | null;
  readonly raw: JsonObject;
  readonly #api: NoClick | undefined;

  private constructor(raw: JsonObject, api: NoClick | undefined) {
    this.userCode = str(raw.user_code) ?? "";
    this.client = str(raw.client) ?? "";
    this.hostname = str(raw.hostname) ?? "";
    this.ip = str(raw.ip);
    this.keyName = str(raw.key_name) ?? "";
    this.status = str(raw.status) ?? "";
    this.createdAt = parseTime(raw.created_at);
    this.expiresAt = parseTime(raw.expires_at);
    this.raw = raw;
    this.#api = api;
  }

  /** Start a sign-in for `name` (what signs in, like `noclick-cli`) on `hostname` (its key is named after it). */
  static async start(options: { name: string; hostname: string; client?: NoClick }): Promise<CliLoginStart> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/cli/logins", {
      json: { client: options.name, hostname: options.hostname }, anonymous: true, user: null,
    }));
    return {
      deviceCode: String(raw.device_code), userCode: String(raw.user_code), verificationUrl: String(raw.verification_url),
      verificationUrlComplete: str(raw.verification_url_complete), intervalS: num(raw.interval_s) ?? 5,
      expiresAt: str(raw.expires_at), raw,
    };
  }

  /**
   * One poll of a sign-in. Throws `PermissionDenied` when the person denied it and `Expired` once it expired; an
   * approved sign-in hands its key out once.
   */
  static async poll(deviceCode: string, options: { client?: NoClick } = {}): Promise<CliLoginPoll> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/cli/logins/token", {
      json: { device_code: deviceCode }, anonymous: true, user: null,
    }));
    const status = raw.status === "approved" || raw.status === "slow_down" ? raw.status : "pending";
    return {
      status, intervalS: num(raw.interval_s), key: str(raw.key), keyId: str(raw.key_id), keyName: str(raw.key_name),
      email: str(raw.email), raw,
    };
  }

  /**
   * The sign-in waiting for `code` (as its terminal shows it, `WDJB-MJHT`); `NotFound` once it's answered, expired or
   * never started. The signed-in owner's alone.
   *
   *     const login = await CliLogin.get("WDJB-MJHT");
   *     console.log(login.hostname, login.ip);
   */
  static async get(code: string, options: { client?: NoClick; signal?: AbortSignal } = {}): Promise<CliLogin> {
    const raw = await resolveClient(options.client).request("GET", `/v1/cli/logins/${encodeURIComponent(code)}`, {
      user: null, signal: options.signal,
    });
    return new CliLogin(asObject(raw), options.client);
  }

  /**
   * Approve the sign-in (its CLI's next poll gets a key of the account, every scope but those that read secrets) or
   * deny it. Approve only one you started yourself, just now. Resolves to it, answered.
   *
   *     await (await CliLogin.get("WDJB-MJHT")).answer(true);
   */
  async answer(approved: boolean): Promise<CliLogin> {
    const raw = await resolveClient(this.#api).request("POST", `/v1/cli/logins/${encodeURIComponent(this.userCode)}/answer`, {
      json: { approved }, user: null,
    });
    return new CliLogin(asObject(raw), this.#api);
  }
}

/**
 * The account at a glance, as `GET /v1/status` answers it: which account the key acts in (`account`, or the user a key
 * acts for in `account.acting_for`), its plan, balance and spend against caps, approvals waiting on a person, what
 * failed in the last day and what ran last.
 */
export async function accountStatus(options: { client?: NoClick } = {}): Promise<JsonObject> {
  return asObject(await resolveClient(options.client).request("GET", "/v1/status", { user: null }));
}
