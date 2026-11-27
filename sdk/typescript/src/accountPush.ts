/**
 * AccountPush: the browsers that show the signed-in person NoClick's notifications (Web Push): a home-screen app on a
 * phone, a desktop browser.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** One browser that shows the person's notifications, as its push service names it (`endpoint`). */
export interface PushDevice {
  id: string;
  device: string | null;
  endpoint: string;
  createdAt: Date | null;
  lastSentAt: Date | null;
}

/** A browser's push subscription, as `PushSubscription.toJSON()` gives it. */
export interface PushSubscriptionJson {
  endpoint?: string;
  keys?: Record<string, string>;
}

const pushDevice = (raw: unknown): PushDevice => {
  const row = asObject(raw);
  return {
    id: str(row.id) ?? "",
    device: str(row.device) ?? null,
    endpoint: str(row.endpoint) ?? "",
    createdAt: parseTime(row.created_at),
    lastSentAt: parseTime(row.last_sent_at),
  };
};

/**
 * The browsers that show the signed-in person NoClick's notifications: a DM or @mention of them in a space, a
 * question or approval that needs them, and work that finished while they weren't watching. Turned on in a browser
 * from the person's own tap (`Notification.requestPermission()`, then `pushManager.subscribe` with `publicKey`), and
 * off there. The signed-in person's alone, in their own browser: any other caller rejects with `PermissionDenied`.
 */
export class AccountPush {
  /** Whether this NoClick sends notifications to browsers. */
  readonly configured: boolean;
  /** The key a browser subscribes with (`applicationServerKey`), base64url. */
  readonly publicKey: string | null;
  readonly devices: readonly PushDevice[];
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.configured = raw.configured === true;
    this.publicKey = str(raw.public_key) ?? null;
    this.devices = asList(raw.devices).map(pushDevice);
    this.raw = raw;
  }

  /**
   * Read the browsers that show the person's notifications, and the key a new one subscribes with.
   *
   *     const { publicKey, devices } = await AccountPush.get();
   */
  static async get(options: { client?: NoClick } = {}): Promise<AccountPush> {
    return new AccountPush(asObject(await resolveClient(options.client).request("GET", "/v1/account/push", { user: null })));
  }

  /**
   * Turn notifications on in this browser, with its push subscription: the same browser again (or one signed in to
   * another account before) is updated, never added twice. `device` names it for the person, like `iPhone`.
   *
   *     const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: publicKey });
   *     const { id } = await AccountPush.add(subscription.toJSON(), { device: "iPhone" });
   */
  static async add(subscription: PushSubscriptionJson, options: { device?: string; client?: NoClick } = {}): Promise<PushDevice> {
    const raw = await resolveClient(options.client).request("POST", "/v1/account/push", {
      json: { endpoint: subscription.endpoint, keys: subscription.keys, device: options.device },
      user: null,
    });
    return pushDevice(raw);
  }

  /**
   * Turn notifications off in one browser.
   *
   *     await AccountPush.remove(id);
   */
  static async remove(deviceId: string, options: { client?: NoClick } = {}): Promise<void> {
    await resolveClient(options.client).request("DELETE", `/v1/account/push/${encodeURIComponent(deviceId)}`, { user: null });
  }
}
