/**
 * Notifications: the email alerts NoClick sends your account's owner, one switch for each kind.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject } from "./object.ts";
import type { JsonObject } from "./object.ts";

/**
 * Which kinds of email alert NoClick sends your account's owner: `categories` maps each kind (`run_failure`,
 * `credits`, `spend_cap`, `digest`, ...) to whether it's on. A kind never turned off is on. They're what Settings →
 * Notifications in the NoClick app shows, and every alert email carries a one-click link that turns its own kind off.
 */
export class Notifications {
  readonly categories: Record<string, boolean>;
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.categories = Object.fromEntries(Object.entries(asObject(raw.categories)).map(([kind, on]) => [kind, on === true]));
    this.raw = raw;
  }

  /**
   * Read which kinds of email alert your account's owner gets. Any of your account's own keys may, but one held to
   * one of your users, which rejects with `PermissionDenied`: they're the owner's.
   *
   *     const alerts = await Notifications.get();
   *     console.log(alerts.categories.digest); // true until it's turned off
   */
  static async get(options: { client?: NoClick } = {}): Promise<Notifications> {
    return new Notifications(asObject(await resolveClient(options.client).request("GET", "/v1/notifications", { user: null })));
  }

  /**
   * Turn kinds of email alert to your account's owner on (`true`) or off (`false`), in one change; a kind you leave
   * out stays as it is. A kind NoClick doesn't send, or a value that isn't `true` or `false`, rejects with
   * `InvalidRequest` and changes nothing. Resolves to every kind, as it stands after the change.
   *
   *     await Notifications.update({ digest: false, run_failure: true });
   */
  static async update(categories: Record<string, boolean>, options: { client?: NoClick } = {}): Promise<Notifications> {
    const raw = await resolveClient(options.client).request("PATCH", "/v1/notifications", {
      json: { categories },
      user: null,
    });
    return new Notifications(asObject(raw));
  }
}
