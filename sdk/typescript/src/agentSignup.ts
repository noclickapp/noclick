/**
 * Claiming an account an AI agent made for itself: the claim link it hands a person (`noclick.com/claim/<token>`)
 * names a token, which the signed-in person reads (`previewClaim`) and answers (`answerClaim`). Both are a signed-in
 * person's own calls (a session), never a key.
 *
 *     const claim = await AgentSignup.previewClaim(token);
 *     await AgentSignup.answerClaim(token, "claim", { acceptTerms: true, keyAccess: "build" });
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** What the agent's key may do once its account is claimed. */
export type ClaimKeyAccess = "full" | "build" | "revoked";

/** Claiming an account an AI agent made for itself. */
export class AgentSignup {
  private constructor() {}

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
