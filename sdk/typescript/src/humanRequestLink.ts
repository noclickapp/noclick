/**
 * HumanRequestLink: a human request's page, as the person its link reached reads and answers it. The link is the
 * capability, so it takes no key: a page of your own reads and answers a request with the link alone.
 */

import { NoClick } from "./client.ts";
import { asObject, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** A human request as its page shows it (`HumanRequestLink.read`). */
export interface HumanRequestPage {
  id: string;
  /** `ask`, `approve`, `notify`, `hand_off`, `setup`, ... */
  kind: string;
  /** `pending` until it's answered, then `answered`, `expired`, `canceled`, ... */
  status: string;
  message: string | null;
  expiresAt: Date | null;
  /** Everything the page shows: its options, its brand, a held call's approval, a step question, a hand-off. */
  raw: JsonObject;
}

/**
 * A human request's page (`/h/{id}`), as the person its link reached reads and answers it. The id is the capability;
 * the link NoClick sends its person carries a key beside it (`?k=`), which a request asked of the account's owner, one
 * only its person answers and a held call's approval need: pass it as `key`. Who may answer is NoClick's to judge, as
 * on its own page: a request the link can't open rejects with `NotFound`, and an answer it doesn't take with its
 * reason.
 *
 *     const link = new HumanRequestLink(requestId, { key: new URL(location.href).searchParams.get("k") });
 *     const page = await link.read();
 *     if (page.kind === "approve") await link.answer({ decision: "approve" });
 */
export class HumanRequestLink {
  readonly id: string;
  readonly key: string | null;
  readonly #client: NoClick;

  /** `baseUrl`: the API's (`NOCLICK_API_URL`, then `https://api.noclick.com`); `fetch`: a custom one; `timeoutMs` and
   *  `maxRetries`: each call's, as a client's. */
  constructor(
    id: string,
    options: { key?: string | null; baseUrl?: string; fetch?: typeof fetch; timeoutMs?: number; maxRetries?: number } = {},
  ) {
    this.id = id;
    this.key = options.key ?? null;
    this.#client = new NoClick({
      apiKey: "", baseUrl: options.baseUrl, fetch: options.fetch, timeoutMs: options.timeoutMs, maxRetries: options.maxRetries,
    });
  }

  #path(suffix = ""): string {
    return `/v1/public/human_requests/${encodeURIComponent(this.id)}${suffix}`;
  }

  async #post(suffix: string, json: JsonObject): Promise<JsonObject> {
    return asObject(await this.#client.request("POST", this.#path(suffix), {
      json, query: this.key ? { k: this.key } : undefined, user: null, anonymous: true,
    }));
  }

  /** The request as its page shows it. */
  async read(): Promise<HumanRequestPage> {
    const raw = asObject(await this.#client.request("GET", this.#path(), {
      query: this.key ? { k: this.key } : undefined, user: null, anonymous: true,
    }));
    return {
      id: str(raw.id) ?? this.id, kind: str(raw.kind) ?? "", status: str(raw.status) ?? "", message: str(raw.message),
      expiresAt: parseTime(raw.expires_at), raw,
    };
  }

  /**
   * Answer it, once: a question's `choice` (or `choices`) and `text`, an approval's `decision` (`approve` or `deny`);
   * a held call's `approved`, `note` and each of its terms accepted; a step question's `connection` or `values`; a
   * file question's `secret_values` (one for each of its keys) or `file_content` (the whole file).
   * Rejects with the reason an answer isn't taken (already answered, expired, not this link's to give).
   */
  async answer(body: JsonObject): Promise<JsonObject> {
    return this.#post("/answer", body);
  }

  /** A connect question's other account: the provider's sign-in link (`url`), which comes back to the request's page
   *  and whose account answers the question. `credentialType`: which of its ways to sign in. */
  async connect(options: { credentialType?: string } = {}): Promise<{ url: string }> {
    const raw = await this.#post("/connect", options.credentialType ? { credential_type: options.credentialType } : {});
    return { url: str(raw.url) ?? "" };
  }

  /** Reply in the conversation an agent handed this link's person. */
  async reply(text: string): Promise<JsonObject> {
    return this.#post("/reply", { text });
  }

  /** Give the handed-over conversation back to the agent, which answers from the next message. */
  async handBack(): Promise<JsonObject> {
    return this.#post("/hand_back", {});
  }
}
