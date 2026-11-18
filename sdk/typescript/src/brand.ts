/**
 * Brand: how human requests (the `/h/{id}` page and emails) present your product, and the OAuth
 * apps your users connect with. One per account.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import type { Domain } from "./domain.ts";
import { asObject, str } from "./object.ts";
import type { JsonObject } from "./object.ts";
import { secretIdList } from "./secret.ts";
import type { SecretRef } from "./secret.ts";

export interface BrandFields {
  name?: string | null;
  logoUrl?: string | null;
  /** The pages' accent, as `#RRGGBB` (or `#RGB`); kept as lowercase `#rrggbb`. */
  color?: string | null;
  supportUrl?: string | null;
  emailFromName?: string | null;
  /**
   * A domain your account holds (a `Domain` or its name, like `connect.acme.com`) that serves the
   * approval, question and hand-off pages NoClick shows your users, and that the emails bringing them
   * there link to (they come from NoClick's address under `emailFromName`; connect links stay on
   * NoClick's host for now). A bought domain gets its CNAME at once; a connected one lists the records
   * to add in its `records`: the CNAME, and a TXT that proves the name is yours. The domain's
   * `serves` then includes `brand`. `null` moves the pages back to NoClick's host.
   */
  domain?: string | Domain | null;
  /**
   * Your own OAuth app per provider (`google`, `slack`, `box`, ...): an account `Secret` (or its id
   * or name) holding `CLIENT_ID` and `CLIENT_SECRET`, so the consent screen names you. Register the
   * provider's `oauthRedirectUrls` entry with the app. Connect links made after it is set sign in
   * with it and each connection keeps (and refreshes on) the app it was made with, so connections
   * made before keep NoClick's until they're reconnected. On `update` only the providers named
   * change (links made after for one mapped to `null` sign in with NoClick's app), and
   * `oauthApps: null` removes them all.
   */
  oauthApps?: Record<string, SecretRef | null> | null;
}

export class Brand {
  readonly name: string | null;
  readonly logoUrl: string | null;
  readonly color: string | null;
  readonly supportUrl: string | null;
  readonly emailFromName: string | null;
  /** True while nothing is set (the defaults are shown). */
  readonly isDefault: boolean;
  /** The host your approval, question and hand-off pages are served from; null: NoClick's. */
  readonly domain: string | null;
  /** Your own OAuth app per provider, as `{ provider: secret id }`. */
  readonly oauthApps: Record<string, string>;
  /**
   * The redirect URI to register with your app at every provider you can bring one for, as
   * `{ provider: url }`: you need it to create the app, before it is named in `oauthApps`.
   */
  readonly oauthRedirectUrls: Record<string, string>;
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.name = str(raw.name);
    this.logoUrl = str(raw.logo_url);
    this.color = str(raw.color);
    this.supportUrl = str(raw.support_url);
    this.emailFromName = str(raw.email_from_name);
    this.isDefault = raw.is_default === true;
    this.domain = str(raw.domain);
    this.oauthApps = Object.fromEntries(Object.entries(asObject(raw.oauth_apps)).map(([k, v]) => [k, String(v)]));
    this.oauthRedirectUrls = Object.fromEntries(Object.entries(asObject(raw.oauth_redirect_urls)).map(([k, v]) => [k, String(v)]));
    this.raw = raw;
  }

  static async get(options: { client?: NoClick } = {}): Promise<Brand> {
    return new Brand(asObject(await resolveClient(options.client).request("GET", "/v1/brand", { user: null })));
  }

  /** Remove the account's brand: pages and emails go back to the defaults (returned, `isDefault` true). */
  static async reset(options: { client?: NoClick } = {}): Promise<Brand> {
    return new Brand(asObject(await resolveClient(options.client).request("DELETE", "/v1/brand", { user: null })));
  }

  /**
   * Replace the brand: fields left out are cleared. To change one field, use `update`.
   *
   * @example
   * console.log((await Brand.get()).oauthRedirectUrls.google);   // create your Google app with this
   * await Brand.set({ name: "Acme", oauthApps: { google: "google-oauth-app" } });
   */
  static async set(fields: BrandFields, options: { client?: NoClick } = {}): Promise<Brand> {
    const json = await brandBody({ name: null, logoUrl: null, color: null, supportUrl: null, emailFromName: null, ...fields }, options.client, { replace: true });
    const raw = await resolveClient(options.client).request("PUT", "/v1/brand", { json, user: null });
    return new Brand(asObject(raw));
  }

  /**
   * Change only the fields you pass; the rest stay as they are. `null` clears a field. Before you've
   * set a brand, it changes NoClick's default one: the name stays `NoClick` until you give it yours.
   *
   * @example
   * await Brand.update({ color: "#ff5500" });   // name, logo and the rest are kept
   * await Brand.update({ supportUrl: null });   // no support link from now on
   * await Brand.update({ oauthApps: { google: null } });   // new Google links use NoClick's app
   */
  static async update(fields: BrandFields, options: { client?: NoClick } = {}): Promise<Brand> {
    const json = await brandBody(fields, options.client, { replace: false });
    const raw = await resolveClient(options.client).request("PATCH", "/v1/brand", { json, user: null });
    return new Brand(asObject(raw));
  }
}

const WIRE: Record<string, string> = {
  name: "name", logoUrl: "logo_url", color: "color", supportUrl: "support_url", emailFromName: "email_from_name",
};

/**
 * The wire body for the fields given (`undefined` leaves a field out, `null` clears it). On a
 * `replace` `domain` and `oauthApps` go on the wire only with a value: left out already means none.
 */
async function brandBody(fields: BrandFields, client: NoClick | undefined, { replace }: { replace: boolean }): Promise<JsonObject> {
  const json: JsonObject = {};
  for (const [key, wire] of Object.entries(WIRE)) {
    const value = fields[key as keyof BrandFields];
    if (value !== undefined) json[wire] = value as string | null;
  }
  if (fields.domain !== undefined && !(replace && fields.domain === null)) {
    json.domain = fields.domain === null || typeof fields.domain === "string" ? fields.domain : await fields.domain._name();
  }
  if (fields.oauthApps !== undefined && !(replace && fields.oauthApps === null)) {
    if (fields.oauthApps === null) json.oauth_apps = null;
    else {
      const named = Object.entries(fields.oauthApps).filter((entry): entry is [string, SecretRef] => entry[1] !== null);
      const ids = (await secretIdList(named.map(([, secret]) => secret), { user: null, client })) ?? [];
      const byProvider = new Map(named.map(([provider], i) => [provider, ids[i]]));
      json.oauth_apps = Object.fromEntries(Object.keys(fields.oauthApps).map((provider) => [provider, byProvider.get(provider) ?? null]));
    }
  }
  return json;
}
