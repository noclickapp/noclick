/**
 * Connected apps: the MCP clients your account's owner allowed to connect, and NoClick's own connections (its
 * assistant's), each a caller of its own with the bounds set for it. Only the owner, signed in, lists, revokes and
 * restores them.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject, fetchPage, num, paginate, parseTime, str } from "./object.ts";
import type { JsonObject, Page, PageOptions } from "./object.ts";

/**
 * One connection, revoked or not: the client (`clientName`, and `clientId`, `noclick:` for one NoClick makes itself),
 * the capability groups it holds (`read`, `build`, `deploy`, `spend`, `delete`), its monthly cap and the amount under
 * which a purchase it makes goes through unasked (null: none of its own, and it asks before every one), what it spent
 * this month, and the user it acts for (null: your account). `restorable`: once revoked, the owner may turn it back on
 * as it was (a connection NoClick makes); a client a person connected connects again instead.
 */
export class ConnectedApp {
  readonly id: string;
  readonly clientName: string;
  readonly clientId: string;
  readonly clientUri: string | null;
  readonly capabilities: string[];
  readonly spendCapUsdPerMonth: number | null;
  readonly autoApproveUnderUsd: number | null;
  readonly spentUsdThisMonth: number;
  readonly userId: string | null;
  readonly restorable: boolean;
  readonly createdAt: Date | null;
  readonly lastUsedAt: Date | null;
  readonly revokedAt: Date | null;
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    const client = asObject(raw.client);
    this.id = String(raw.id ?? "");
    this.clientName = str(client.name) ?? "";
    this.clientId = str(client.id) ?? "";
    this.clientUri = str(client.uri);
    this.capabilities = Array.isArray(raw.capabilities) ? raw.capabilities.map(String) : [];
    this.spendCapUsdPerMonth = num(raw.spend_cap_usd_per_month);
    this.autoApproveUnderUsd = num(raw.auto_approve_under_usd);
    this.spentUsdThisMonth = num(raw.spent_usd_this_month) ?? 0;
    this.userId = str(raw.user_id);
    this.restorable = raw.restorable === true;
    this.createdAt = parseTime(raw.created_at);
    this.lastUsedAt = parseTime(raw.last_used_at);
    this.revokedAt = parseTime(raw.revoked_at);
    this.raw = raw;
  }

  get revoked(): boolean {
    return this.revokedAt !== null;
  }

  /**
   * Every connection, newest first, revoked ones too (or the first `limit`). The account's signed-in owner's alone: a
   * key, a user's session, an app's code or an MCP connection rejects with `PermissionDenied`.
   *
   *     for (const app of await ConnectedApp.list()) console.log(app.clientName, app.revoked ? "revoked" : "live");
   */
  static async list(options: { limit?: number; client?: NoClick } = {}): Promise<ConnectedApp[]> {
    const rows = await paginate(resolveClient(options.client), "/v1/connected_apps", { user: null, limit: options.limit });
    return rows.map((raw) => new ConnectedApp(raw));
  }

  /** One page of `list()`, newest first; pass `nextCursor` back as `cursor`. The signed-in owner's alone. */
  static async listPage(options: PageOptions & { client?: NoClick } = {}): Promise<Page<ConnectedApp>> {
    const page = await fetchPage(resolveClient(options.client), "/v1/connected_apps", {
      user: null, cursor: options.cursor, limit: options.limit,
    });
    return { data: page.data.map((raw) => new ConnectedApp(raw)), nextCursor: page.nextCursor };
  }

  /**
   * End a connection: its next call fails. Revoking one again changes nothing. The signed-in owner's alone. Resolves
   * to it, with `revokedAt` set.
   *
   *     await ConnectedApp.revoke(app.id);
   */
  static async revoke(connectedAppId: string, options: { client?: NoClick } = {}): Promise<ConnectedApp> {
    const raw = await resolveClient(options.client).request("DELETE", `/v1/connected_apps/${encodeURIComponent(connectedAppId)}`, {
      user: null,
    });
    return new ConnectedApp(asObject(raw));
  }

  /**
   * Turn a revoked connection NoClick makes (`restorable`: its assistant's) back on, as it was when revoked: its
   * groups, cap, auto-approve amount and own approval settings, never wider. Its next call works; restoring a live one
   * changes nothing. A client a person connected rejects with `Conflict` (it connects again, as a new connection). The
   * signed-in owner's alone: a key, an app's code, an MCP connection or an agent rejects with `PermissionDenied`.
   * Resolves to it, live (`revokedAt` null).
   *
   *     const assistant = (await ConnectedApp.list()).find((a) => a.restorable && a.revoked);
   *     if (assistant) await ConnectedApp.restore(assistant.id);
   */
  static async restore(connectedAppId: string, options: { client?: NoClick } = {}): Promise<ConnectedApp> {
    const raw = await resolveClient(options.client).request(
      "POST", `/v1/connected_apps/${encodeURIComponent(connectedAppId)}/restore`, { user: null },
    );
    return new ConnectedApp(asObject(raw));
  }
}
