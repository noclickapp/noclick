/**
 * BrowserLink: a person's page for a browser, as the person its link reached uses it. The link is the capability, so
 * it takes no key: a page of your own reads the link, acts on it and shows its browser with the link alone.
 */

import { BrowserViewConnection } from "./browserView.ts";
import type { BrowserViewConnectOptions } from "./browserView.ts";
import { NoClick } from "./client.ts";
import { asObject, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** `live`: a browser's live view; `login`: a link to sign in to a site once; `ask`: a step a model asked a person to
 *  finish. */
export type BrowserLinkPurpose = "live" | "login" | "ask";
/** `open`: a sign-in nobody started yet; `live` while its browser works; then `done`, `expired` or `closed`. */
export type BrowserLinkStatus = "open" | "live" | "done" | "expired" | "closed";

/** The account's brand, as a link's page wears it. */
export interface BrowserLinkBrand {
  name: string | null;
  logoUrl: string | null;
  color: string | null;
  supportUrl: string | null;
}

/** A browser link as its page shows it (`BrowserLink.read`): never the account, its user or the browser. */
export interface BrowserLinkPage {
  id: string;
  purpose: BrowserLinkPurpose;
  status: BrowserLinkStatus;
  /** The site a sign-in is for, or a step asks to sign in to again. */
  domain: string | null;
  /** What it's for, in the words of whoever sent it. */
  reason: string | null;
  expiresAt: Date | null;
  brand: BrowserLinkBrand;
  raw: JsonObject;
}

function pageOf(raw: JsonObject, id: string): BrowserLinkPage {
  const brand = asObject(raw.brand);
  return {
    id: str(raw.id) ?? id,
    purpose: (str(raw.purpose) ?? "live") as BrowserLinkPurpose,
    status: (str(raw.status) ?? "closed") as BrowserLinkStatus,
    domain: str(raw.domain),
    reason: str(raw.reason),
    expiresAt: parseTime(raw.expires_at),
    brand: { name: str(brand.name), logoUrl: str(brand.logo_url), color: str(brand.color), supportUrl: str(brand.support_url) },
    raw,
  };
}

/**
 * A person's page for a browser (`/live/{id}`): a browser's live view, a link to sign in to a site once, or a step a
 * model asked a person to finish, as the person its link reached uses it. The id is the capability: it works until
 * it's done, revoked (its browser closed, its work settled) or expired, and then every call rejects (`NotFound` for
 * a link that never was, `NotAvailable` or `Expired` for one that stopped working) and every view of it ends.
 *
 *     const link = new BrowserLink(linkId);
 *     if ((await link.read()).status === "open") await link.start();
 *     const view = link.view({ onPicture: (jpeg) => show(jpeg), onEnd: () => link.read() });
 *     await link.type({ text: "482913" });
 *     await link.done();
 */
export class BrowserLink {
  readonly id: string;
  readonly #client: NoClick;

  /** `baseUrl`: the API's (`NOCLICK_API_URL`, then `https://api.noclick.com`); `fetch`: a custom one; `timeoutMs`,
   *  `maxRetries` and `backoffMs`: each call's, as a client's. */
  constructor(
    id: string,
    options: { baseUrl?: string; fetch?: typeof fetch; timeoutMs?: number; maxRetries?: number; backoffMs?: number } = {},
  ) {
    this.id = id;
    this.#client = new NoClick({
      apiKey: "", baseUrl: options.baseUrl, fetch: options.fetch, timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries, backoffMs: options.backoffMs,
    });
  }

  #path(suffix = ""): string {
    return `/v1/public/browser_links/${encodeURIComponent(this.id)}${suffix}`;
  }

  async #post(suffix: string, json: JsonObject = {}): Promise<JsonObject> {
    return asObject(await this.#client.request("POST", this.#path(suffix), { json, user: null, anonymous: true }));
  }

  /** The link as its page shows it: what it's for, whether its browser works, and the account's brand. */
  async read(): Promise<BrowserLinkPage> {
    return pageOf(asObject(await this.#client.request("GET", this.#path(), { user: null, anonymous: true })), this.id);
  }

  /** Open a sign-in link: its browser starts now on the site (once; opening it again shows the same one). */
  async start(): Promise<BrowserLinkPage> {
    return pageOf(await this.#post("/start"), this.id);
  }

  /** Type `text` where the page has focus, or press `key` (`Enter`, `Backspace`, `Tab`, ...): a phone's way in. */
  async type(input: { text: string } | { key: string }): Promise<void> {
    await this.#post("/type", "text" in input ? { text: input.text } : { key: input.key });
  }

  /** The person has finished: a sign-in is saved, the step a model asked for carries on. A live view has nothing to
   *  finish (its browser closes instead). */
  async done(): Promise<BrowserLinkPage> {
    return pageOf(await this.#post("/done"), this.id);
  }

  /**
   * Show the link's browser live in this page, until it ends or you `close()` it: its pictures, and at full size what
   * a person does sent back to it (`send`); a `thumb` view only watches, in smaller pictures. It needs no token (the
   * link, in its address, is the capability), opens again after a dropped connection, and ends for good when the link
   * stops working, which is the moment to `read()` it again. See `BrowserViewConnection`.
   */
  view(options: { thumb?: boolean } & BrowserViewConnectOptions = {}): BrowserViewConnection {
    const thumb = options.thumb === true;
    const url = `${this.#client.baseUrl.replace(/^http/, "ws")}${this.#path("/view")}${thumb ? "?size=thumb" : ""}`;
    return new BrowserViewConnection(() => Promise.resolve({ url, token: null }), !thumb, options, true);
  }
}
