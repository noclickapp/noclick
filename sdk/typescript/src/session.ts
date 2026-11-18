/**
 * User sessions: a short-lived token for one user, safe to hand to a browser.
 *
 *     const session = await user.session({ scopes: ["agents", "humans"], ttlS: 3600 });
 *     res.json({ token: session.token });          // your frontend uses it as its API key
 *     NoClick.forSession(session);                 // or act as that user from the server
 */

import { NoClick } from "./client.ts";
import type { ClientOptions } from "./client.ts";
import { parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

export { SESSION_TOKEN_PREFIX } from "./client.ts";

/** A token pinned to one user with a subset of the minting key's scopes. Printing it never shows the token. */
export class Session {
  readonly id: string | null;
  readonly token: string;
  readonly userId: string | null;
  readonly scopes: string[];
  readonly expiresAt: Date | null;
  readonly raw: JsonObject;
  /** The API the session was minted on. */
  readonly baseUrl: string | undefined;

  /** @internal */
  constructor(raw: JsonObject, fallbackUserId: string, baseUrl?: string) {
    this.id = str(raw.id);
    this.token = str(raw.token) ?? "";
    this.userId = str(raw.user_id) ?? fallbackUserId;
    this.scopes = Array.isArray(raw.scopes) ? (raw.scopes as string[]) : [];
    this.expiresAt = parseTime(raw.expires_at);
    this.raw = raw;
    this.baseUrl = baseUrl;
  }

  /** Whether `expiresAt` has passed (by this machine's clock). */
  get expired(): boolean {
    return this.expiresAt !== null && this.expiresAt.getTime() <= Date.now();
  }

  /** A client that acts as this session: `await Agent.list({ client: session.client() })`. */
  client(options: Omit<ClientOptions, "apiKey"> = {}): NoClick {
    return NoClick.forSession(this, options);
  }

  /** Serializes with the token: sending a session to your frontend is deliberate. */
  toJSON(): JsonObject {
    return { id: this.id, token: this.token, user_id: this.userId, scopes: this.scopes, expires_at: this.raw.expires_at ?? null };
  }

  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return `Session { id: ${JSON.stringify(this.id)}, userId: ${JSON.stringify(this.userId)}, scopes: ${JSON.stringify(this.scopes)}, expiresAt: ${this.expiresAt?.toISOString() ?? null} }`;
  }
}
