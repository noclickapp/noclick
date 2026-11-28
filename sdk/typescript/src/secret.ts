/** Secrets: named environment values for sandboxes, agents and apps. */

import { CONSOLE_BASE_URL, DEFAULT_BASE_URL } from "./client.ts";
import type { UsedBy } from "./database.ts";
import { Conflict, NotFound } from "./errors.ts";
import { ApiObject, asList, asObject, compact, createNamed, isUuid, listAll, listPage, parseTime, refId, str } from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { resolveScope } from "./scope.ts";
import { toVersions, versionId } from "./versions.ts";
import type { Version } from "./versions.ts";

/** A secret to pass: a `Secret`, its id, or its name (the user's own, else the account's). */
export type SecretRef = string | Secret;

export interface SecretCreateOptions extends CallOptions {
  /** Up to 100 keys, each an environment variable name (not `PATH`, `HOME` or one starting `LD_`, `NC_` or `NOCLICK_`), each value a non-empty string of up to 32,768 characters. */
  values?: Record<string, string>;
}

function checkValues<T extends string | null>(values: Record<string, T> | undefined, removable: boolean): Record<string, T> | undefined {
  if (values === undefined) return undefined;
  for (const [key, value] of Object.entries(values)) {
    if (typeof value !== "string" && !(removable && value === null)) throw new TypeError(`The value of ${key} must be a string.`);
  }
  return values;
}

/**
 * @internal `secrets` as the API takes them: ids, in order (a later secret's key wins a clash). A
 * name is looked up for `user` (its own secret first, then the account's).
 */
export async function secretIdList(secrets: SecretRef | SecretRef[] | undefined, options: CallOptions): Promise<string[] | undefined> {
  if (secrets === undefined) return undefined;
  const refs = Array.isArray(secrets) ? secrets : [secrets];
  const ids: string[] = [];
  for (const ref of refs) {
    if (ref instanceof Secret) ids.push(String(await refId(ref)));
    else if (typeof ref === "string") ids.push(isUuid(ref) ? ref : String(await refId(Secret.fromName(ref, options))));
    else throw new TypeError("A secret is a Secret, its id or its name");
  }
  return ids;
}

/**
 * Named values, such as API keys, that the code you run reads from its environment: a sandbox's
 * commands, an agent's shell, an app. Each key becomes an environment variable of that name.
 * Values are write-only: `keys` names them, and nothing reads one back. (A `Connection` is an
 * account at a service NoClick calls for you; a `Secret` is raw values for code you run.)
 */
export class Secret extends ApiObject {
  private _createWith: JsonObject | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _of(init: ObjectInit): Secret {
    return new Secret(init);
  }

  /**
   * Create a secret, unique by name per user (a taken name throws `Conflict` with `existingId`, or with
   * `allowExisting: true` returns the secret already there, its values untouched).
   */
  static async create(name: string, options: SecretCreateOptions & AllowExisting = {}): Promise<Secret> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/secrets", compact({ name, values: checkValues(options.values, false) }), {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new Secret({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the secret called `name`: the user's own first, then the account's. Given
   * `values`, it gets the current (or given) user's own and sets the keys in `values` on every run
   * (NoClick compares them, so unchanged values change nothing). Keys it doesn't name are kept.
   * `createIfMissing` creates it, holding `values`, when there's none; without it, a missing secret throws
   * `NotFound`.
   */
  static fromName(name: string, options: SecretCreateOptions & { createIfMissing?: boolean } = {}): Secret {
    const secret = new Secret({ hints: { name }, client: options.client, user: options.user });
    secret._creates = Boolean(options.createIfMissing);
    if (secret._creates || options.values !== undefined) {
      secret._createWith = compact({ name, values: checkValues(options.values, false) });
    }
    return secret;
  }

  static fromId(secretId: string, options: CallOptions = {}): Secret {
    return new Secret({ hints: { id: secretId }, client: options.client, user: options.user });
  }

  static async get(secretId: string, options: CallOptions = {}): Promise<Secret> {
    return await Secret.fromId(secretId, options).hydrate();
  }

  /** The current user's secrets and the account's (or those `userFilter` covers), names only. */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<Secret[]> {
    return await listAll({ ...options, path: "/v1/secrets" }, (raw, user) => new Secret({ raw, client: options.client, user }));
  }

  /** One page of secrets; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Secret>> {
    return await listPage({ ...options, path: "/v1/secrets" }, (raw, user) => new Secret({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** The names it holds; never their values. */
  get keys(): string[] {
    const keys = this._field<unknown>("keys");
    return Array.isArray(keys) ? keys.map(String) : [];
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** When its values last changed. */
  get updatedAt(): Date | null {
    return parseTime(this._field("updated_at"));
  }
  /** Who reads it: agents, running sandboxes, and apps (with the `binding` name). */
  get usedBy(): UsedBy[] {
    const rows = this._field<unknown>("used_by");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((u) => ({
      kind: str(u.kind) ?? "project", id: str(u.id) ?? "", name: str(u.name) ?? "", binding: str(u.binding),
    }));
  }
  /** This secret in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    if (this._api.baseUrl !== DEFAULT_BASE_URL) return null;
    return `${CONSOLE_BASE_URL}/resources/secrets?secret=${encodeURIComponent(String(this._known("id")))}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/secrets/${id}`);
    const name = String(this._hints.name);
    const rows = (asList(await this._request("GET", "/v1/secrets", { query: { name } })) as JsonObject[]).filter((r) => r.name === name);
    // This scope's own secret first; values are only ever set on its own.
    const own = rows.filter((r) => Boolean(r.user_id) === Boolean(this._scope));
    const row = this._createWith ? own[0] : (own[0] ?? rows[0]);
    if (row) return await this.converge(row);
    if (!this._createWith || !this._creates) {
      throw new NotFound(`No secret is named "${name}".`, {
        nextStep: "Create it with Secret.create(...) or pass { createIfMissing: true }.",
        details: { name, kind: "secret" },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/secrets", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/secrets/${err.existingId}`));
    }
  }

  /** Set the values `fromName` was given on an existing secret (merged; the server compares, so the same values write nothing). */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    const values = this._createWith?.values;
    if (!values) return raw;
    return await this._request<JsonObject>("PATCH", `/v1/secrets/${raw.id}`, { json: { values } });
  }

  /** This secret's route; a reference by name is looked up (or created) first. */
  private async route(): Promise<string> {
    if (!this._known("id")) await this._ensure();
    return `/v1/secrets/${String(this._known("id"))}`;
  }

  /**
   * Set values. They merge by default: the keys you pass are set, a key set to `null` is removed,
   * the rest are kept. `replace` makes it hold exactly `values`. New sandboxes see the change at
   * once, agents from their next turn, apps at their next deployment.
   */
  async update(values: Record<string, string | null>, options: { replace?: boolean } = {}): Promise<this> {
    const json = compact({ values: checkValues(values, !options.replace), replace: options.replace ? true : undefined });
    this._raw = asObject(await this._request("PATCH", await this.route(), { json }));
    return this;
  }

  /** What it held before each change of the last 30 days, newest first: the keys, never the values. */
  async versions(): Promise<Version[]> {
    return toVersions(await this._request("GET", `${await this.route()}/versions`));
  }

  /** Hold `version`'s keys and values again; they come back sealed, never shown or sent. */
  async restoreVersion(version: Version | string): Promise<this> {
    this._raw = asObject(await this._request("POST", `${await this.route()}/versions/${versionId(version)}/restore`));
    return this;
  }

  /** Delete the secret for good (its versions go with it); while an agent lists it or an app binds it, this throws `Conflict`. */
  async delete(): Promise<void> {
    await this._request("DELETE", await this.route());
  }
}
