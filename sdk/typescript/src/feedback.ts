/** Feedback: a note to the NoClick team. */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { compact } from "./object.ts";

export type FeedbackKind = "bug" | "idea" | "general";
const KINDS: readonly FeedbackKind[] = ["bug", "idea", "general"];

/**
 * Tell the NoClick team something: a `bug`, an `idea`, or anything (`general`, the default). It
 * reaches them as the app's feedback button does, from any key, an agent's included; an account
 * sends up to 20 a day (`RateLimited` past that). `pageUrl` and `userAgent` say where it was sent from.
 *
 *     await feedback("Agent.list could filter by workflow.", { kind: "idea" });
 */
export async function feedback(
  message: string,
  options: { kind?: FeedbackKind; pageUrl?: string; userAgent?: string; client?: NoClick } = {},
): Promise<void> {
  const kind = options.kind ?? "general";
  if (!KINDS.includes(kind)) throw new TypeError(`kind is one of ${KINDS.join(", ")}, not ${JSON.stringify(kind)}`);
  await resolveClient(options.client).request("POST", "/v1/feedback", {
    json: compact({ message, kind, page_url: options.pageUrl, user_agent: options.userAgent }),
    user: null,
  });
}
