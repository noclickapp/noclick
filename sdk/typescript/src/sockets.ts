/** What every socket a token opens shares. */

import { NoClickError } from "./errors.ts";

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/**
 * A socket's address, if it's one this SDK sends a token to: wss://, or ws:// on this machine. Anything else is
 * refused before the token leaves (`what` names the socket in the refusal).
 */
export function checkedSocketUrl(url: string, what: string): string {
  let parsed: URL | null = null;
  try {
    parsed = new URL(url);
  } catch { /* refused below */ }
  if (parsed && (parsed.protocol === "wss:" || (parsed.protocol === "ws:" && LOCAL_HOSTS.has(parsed.hostname)))) {
    return url;
  }
  throw new NoClickError(`The ${what}'s address isn't a wss:// URL, so its token was not sent.`, {
    nextStep: "Check that the token comes from NoClick's API (or your server passes its url on as it is).",
  });
}

/** A wait spread over half to one and a half of `ms`, so sockets that dropped together don't all come back at once. */
export function spread(ms: number): number {
  return ms * (0.5 + Math.random());
}
