/**
 * An account an AI agent makes for itself: `signUp` makes it (with no key) and answers its key and a claim link for
 * the agent's person, and `current` reads whether a person has claimed it. The claim link
 * (`noclick.com/claim/<token>`) names a token, which the signed-in person reads (`previewClaim`) and answers
 * (`answerClaim`), each a signed-in person's own call (a session), never a key.
 *
 *     const made = await AgentSignup.signUp("claude-code", { acceptTerms: true });
 *     const claim = await AgentSignup.previewClaim(token);
 *     await AgentSignup.answerClaim(token, "claim", { acceptTerms: true, keyAccess: "build" });
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** What the agent's key may do once its account is claimed. */
export type ClaimKeyAccess = "full" | "build" | "revoked";

/** An account an AI agent made for itself, and claiming it. */
export class AgentSignup {
  private constructor() {}

  /**
   * Make a NoClick account for the agent calling, sent with no key. `acceptTerms` must be `true`: it accepts
   * NoClick's Developer Terms and Acceptable Use Policy for whoever runs the agent. `purpose` is what the account is
   * for, which the person sees as they claim it; `email`, the only person who may claim it. Answers the sign-up: its
   * `key` (shown this once: keep it out of anything you print), `claim_url`, `expires_at`, `limits` and `terms`. A
   * `PermissionDenied` with `reason` `not_launched` while agent sign-up is switched off.
   */
  static async signUp(agent: string, options: { acceptTerms: boolean; purpose?: string; email?: string; client?: NoClick }): Promise<JsonObject> {
    const json: JsonObject = { agent, accept_terms: options.acceptTerms };
    if (options.purpose !== undefined) json.purpose = options.purpose;
    if (options.email !== undefined) json.email = options.email;
    return asObject(await resolveClient(options.client).request("POST", "/v1/agent_signups", { json, user: null, anonymous: true }));
  }

  /**
   * The sign-up that made this key: its `status` (`unclaimed`, `claimed`, `declined` or `expired`), `expires_at`
   * and, while unclaimed, `limits`. A `NotFound` for a key no agent's sign-up made.
   */
  static async current(options: { client?: NoClick } = {}): Promise<JsonObject> {
    return asObject(await resolveClient(options.client).request("GET", "/v1/agent_signups/current", { user: null }));
  }

  /**
   * The claim page's view: the agent and what it made, what waits for the claim (its spending included), and whether
   * the signed-in person may claim it.
   */
  static async previewClaim(token: string, options: { client?: NoClick } = {}): Promise<JsonObject> {
    return asObject(await resolveClient(options.client).request("POST", "/v1/agent_signups/claims/preview", {
      json: { token }, user: null,
    }));
  }

  /**
   * Answer a claim: `claim` folds the agent's account and what it made into the signed-in person's (it needs
   * `acceptTerms`: the person accepting NoClick's Terms for it), its key acting there as `keyAccess` says (`full` by
   * default, `build`, or `revoked`); `decline` ends the agent's account now. Answers the claim's view as it is then.
   */
  static async answerClaim(token: string, decision: "claim" | "decline",
    options: { acceptTerms?: boolean; keyAccess?: ClaimKeyAccess; client?: NoClick } = {}): Promise<JsonObject> {
    const json: JsonObject = { token, decision };
    if (options.acceptTerms !== undefined) json.accept_terms = options.acceptTerms;
    if (options.keyAccess !== undefined) json.key_access = options.keyAccess;
    return asObject(await resolveClient(options.client).request("POST", "/v1/agent_signups/claims/answer", {
      json, user: null,
    }));
  }
}
