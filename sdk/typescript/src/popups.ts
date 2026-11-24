/**
 * Popups: the popups and banners of the NoClick app your account's owner can turn off, and back on.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject } from "./object.ts";
import type { JsonObject } from "./object.ts";

/**
 * Which of the NoClick app's popups and banners your account's owner sees: `popups` maps each one (`run_results`, the
 * outputs shown after a workflow runs; `invite_banner`, the nudge to share a workflow's live invite link;
 * `publish_banner`, the nudge to publish an interface) to whether it shows. One never turned off shows. They're what
 * Settings → Popups in the NoClick app shows, and a popup's own "Don't show again" turns it off too.
 */
export class Popups {
  readonly popups: Record<string, boolean>;
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.popups = Object.fromEntries(Object.entries(asObject(raw.popups)).map(([name, shown]) => [name, shown === true]));
    this.raw = raw;
  }

  /**
   * Read which of the app's popups your account's owner sees. Any of your account's own keys may, but one held to one
   * of your users, which rejects with `PermissionDenied`: they're the owner's.
   *
   *     const { popups } = await Popups.get();
   *     console.log(popups.run_results); // true until it's turned off
   */
  static async get(options: { client?: NoClick } = {}): Promise<Popups> {
    return new Popups(asObject(await resolveClient(options.client).request("GET", "/v1/popups", { user: null })));
  }

  /**
   * Show (`true`) or stop showing (`false`) the app's popups to your account's owner, in one change; a popup you leave
   * out stays as it is. A popup the app doesn't have, or a value that isn't `true` or `false`, rejects with
   * `InvalidRequest` and changes nothing. Resolves to every popup, as it stands after the change.
   *
   *     await Popups.update({ invite_banner: false });
   */
  static async update(popups: Record<string, boolean>, options: { client?: NoClick } = {}): Promise<Popups> {
    const raw = await resolveClient(options.client).request("PATCH", "/v1/popups", { json: { popups }, user: null });
    return new Popups(asObject(raw));
  }

  /**
   * Every "show this once" flag the NoClick app keeps for your account's owner, by its key: each popup's "Don't show
   * again" and each tour they finished (`true`: seen, so not shown again). A key not there is unseen.
   *
   *     const seen = await Popups.seenOnce();
   *     if (!seen.invite_walkthrough) console.log("They haven't taken the invite tour");
   */
  static async seenOnce(options: { client?: NoClick } = {}): Promise<Record<string, boolean>> {
    return seenOf(asObject(await resolveClient(options.client).request("GET", "/v1/popups/seen", { user: null })));
  }

  /**
   * Mark "show this once" flags seen (`true`) or unseen again (`false`), in one change; the rest stay as they are. A
   * key is lowercase letters, digits and `_`. Resolves to every flag, as it stands after the change.
   *
   *     await Popups.setSeenOnce({ invite_walkthrough: true });
   */
  static async setSeenOnce(flags: Record<string, boolean>, options: { client?: NoClick } = {}): Promise<Record<string, boolean>> {
    const raw = await resolveClient(options.client).request("PATCH", "/v1/popups/seen", { json: { seen_once: flags }, user: null });
    return seenOf(asObject(raw));
  }
}

function seenOf(raw: JsonObject): Record<string, boolean> {
  return Object.fromEntries(Object.entries(asObject(raw.seen_once)).map(([key, seen]) => [key, seen === true]));
}
