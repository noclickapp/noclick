/** Users: the people and companies your product acts for, each keyed by your own id. */

import type { NoClick } from "./client.ts";
import { Conflict, NotFound } from "./errors.ts";
import { toExportBundle } from "./export.ts";
import type { ExportBundle } from "./export.ts";
import { Human } from "./human.ts";
import { ApiObject, asObject, compact, createNamed, defined, givesFields, listAll, listPage, parseTime, str } from "./object.ts";
import type { AllowExisting, JsonObject, ObjectInit, Page, PageOptions } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import { Session } from "./session.ts";
import { checkUserId } from "./scope.ts";

export interface UserFields {
  name?: string | null;
  email?: string | null;
  phone?: string | null;
  spendCapUsdPerMonth?: number | null;
  metadata?: JsonObject | null;
  /**
   * Where they are, as an IANA name (`"America/New_York"`): every turn of an agent acting for them
   * starts with the date and time there (unless the agent has its own `timezone`), and `Cron` with
   * `tz: "user"` fires in it, following them when they move.
   */
  timezone?: string | null;
}

function wireFields(id: string | undefined, fields: UserFields): JsonObject {
  return {
    id,
    name: fields.name,
    email: fields.email,
    phone: fields.phone,
    spend_cap_usd_per_month: fields.spendCapUsdPerMonth,
    metadata: fields.metadata,
    timezone: fields.timezone,
  };
}

function userPath(id: string): string {
  return `/v1/users/${encodeURIComponent(id)}`;
}

export interface UserListOptions {
  /** A case-insensitive prefix of the id, name or email. */
  q?: string;
  status?: "active" | "suspended";
  /** Only users whose spending is (or isn't) paused. */
  spending?: "paused" | "active";
  client?: NoClick;
}

function userListCall<T extends UserListOptions>(options: T) {
  return {
    ...options,
    path: "/v1/users",
    user: null,
    query: { q: options.q, status: options.status, spending: options.spending },
  };
}

/** A verification code on its way to the user's phone. */
export interface PhoneVerification {
  phone: string | null;
  status: string | null;
  expiresAt: Date | null;
  raw: JsonObject;
}

/**
 * Whether a user can spend right now (`user.spending`). A `paused` user can't start anything that
 * costs money until `resumeSpending()`; `message` and `action` are what NoClick tells them
 * meanwhile, `since` is when you paused them, `held` how many of their messages wait to run when
 * you resume, and `pausedBy` the key that paused them (`"console"` from the console).
 */
export interface Spending {
  paused: boolean;
  message: string | null;
  action: SpendingAction | null;
  since: Date | null;
  held: number;
  pausedBy: string | null;
  raw: JsonObject;
}

/** What a paused user can do: your checkout or billing page. */
export interface SpendingAction {
  /** Up to 40 characters, like `"Top up"`. */
  label: string;
  /** An `https` URL. */
  url: string;
}

function toSpending(raw: JsonObject): Spending {
  const action = raw.action && typeof raw.action === "object" ? asObject(raw.action) : null;
  return {
    paused: raw.paused === true,
    message: typeof raw.message === "string" ? raw.message : null,
    action: action ? { label: String(action.label), url: String(action.url) } : null,
    since: parseTime(raw.since),
    held: typeof raw.held === "number" ? raw.held : 0,
    pausedBy: typeof raw.paused_by === "string" ? raw.paused_by : null,
    raw,
  };
}

registerResult("user.export", (result) => toExportBundle(result));

/**
 * One of your users (a person or a company), keyed by your own id for it.
 * `User.fromId("user_42", { createIfMissing: true })` is lazy: nothing is sent until the user is used.
 */
export class User extends ApiObject {
  private _createWith: JsonObject | null = null;

  protected constructor(init: ObjectInit) {
    super({ ...init, user: null });
  }

  /** User routes are account-level; they never carry a user header. */
  override _callScope(): null {
    return null;
  }

  /**
   * Create a user with your `id` for it. A taken `id` throws `Conflict` (its `existingId` is that id), or
   * with `allowExisting: true` returns that user, as it is: its details don't change.
   */
  static async create(
    id: string,
    options: UserFields & AllowExisting & { idempotencyKey?: string; client?: NoClick } = {},
  ): Promise<User> {
    const raw = await createNamed("/v1/users", compact(wireFields(checkUserId(id), options)), {
      allowExisting: options.allowExisting, user: null, client: options.client, key: "id", existingPath: userPath,
      idempotencyKey: options.idempotencyKey,
    });
    return new User({ raw, client: options.client });
  }

  /**
   * A lazy reference by your `id`. Given fields, it gets the user and sets the ones you pass, on every run:
   * an existing user whose fields differ gets yours (a field left out is never changed; `null` clears one,
   * as in `update`). `createIfMissing` creates it with the fields when there's none; without it, a missing
   * user throws `NotFound`.
   */
  static fromId(id: string, options: UserFields & { createIfMissing?: boolean; client?: NoClick } = {}): User {
    const user = new User({ hints: { id: checkUserId(id) }, client: options.client });
    user._creates = Boolean(options.createIfMissing);
    if (user._creates || givesFields(options)) user._createWith = defined(wireFields(id, options));
    return user;
  }

  static async get(id: string, options: { client?: NoClick } = {}): Promise<User> {
    return await User.fromId(id, options).hydrate();
  }

  /** Your users, newest first (or the first `limit`). */
  static async list(options: UserListOptions & { limit?: number } = {}): Promise<User[]> {
    return await listAll(userListCall(options), (raw) => new User({ raw, client: options.client }));
  }

  /** One page of users; pass `nextCursor` back as `cursor`. */
  static async listPage(options: UserListOptions & PageOptions = {}): Promise<Page<User>> {
    return await listPage(userListCall(options), (raw) => new User({ raw, client: options.client }));
  }

  /** Your id for the user. */
  get id(): string {
    return this._field("id");
  }
  get name(): string | null {
    return this._field("name");
  }
  get email(): string | null {
    return this._field("email");
  }
  get phone(): string | null {
    return this._field("phone");
  }
  /** When the phone was proven (null if never). */
  get phoneVerifiedAt(): Date | null {
    return parseTime(this._field("phone_verified_at"));
  }
  get spendCapUsdPerMonth(): number | null {
    return this._field("spend_cap_usd_per_month");
  }
  get metadata(): JsonObject | null {
    return this._field("metadata");
  }
  /** Their IANA timezone (null: UTC). */
  get timezone(): string | null {
    return this._field("timezone");
  }
  get status(): string {
    return this._field("status");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /**
   * Whether they can spend right now: paused or not, what NoClick tells them, and how many of their
   * messages wait (see `pauseSpending`).
   */
  get spending(): Spending | null {
    const raw = this._field<unknown>("spending");
    return raw && typeof raw === "object" ? toSpending(asObject(raw)) : null;
  }

  /** This user in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    return this._api.consoleUrl("users", this.id);
  }

  protected async _load(): Promise<JsonObject> {
    const path = userPath(this.id);
    const definition = this._createWith;
    let found: JsonObject | undefined;
    try {
      found = await this._request<JsonObject>("GET", path);
    } catch (err) {
      if (!(err instanceof NotFound) || !definition || !this._creates) throw err;
    }
    if (found || !definition) return await this.converge(found as JsonObject);
    try {
      return await this._request<JsonObject>("POST", "/v1/users", { json: compact(definition) });
    } catch (err) {
      if (!(err instanceof Conflict)) throw err; // created concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", path));
    }
  }

  /** Set the fields `fromId` was given on an existing user. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    if (!this._createWith) return raw;
    const changes: JsonObject = {};
    for (const [key, value] of Object.entries(this._createWith)) {
      if (key !== "id" && JSON.stringify(raw[key] ?? null) !== JSON.stringify(value)) changes[key] = value;
    }
    return Object.keys(changes).length ? await this._request<JsonObject>("PATCH", userPath(String(raw.id)), { json: changes }) : raw;
  }

  /** @internal Your id for the user, once it exists (created, or its fields set, first). */
  async _userId(): Promise<string> {
    if (this._createWith) await this._ensure();
    return this.id;
  }

  private async _path(): Promise<string> {
    return userPath(await this._userId());
  }

  /**
   * Change fields (`null` clears one, omitted ones stay). A new `id` renames the user: everything
   * it owns follows, and a taken id throws `Conflict`. A user acting for themselves may change their
   * own `timezone`, their session included.
   */
  async update(changes: UserFields & { id?: string }): Promise<this> {
    const id = changes.id === undefined ? undefined : checkUserId(changes.id);
    const path = await this._path();
    this._raw = await this._request<JsonObject>("PATCH", path, { json: defined(wireFields(id, changes)) });
    return this;
  }

  /** Stop all activity for this user. */
  async suspend(): Promise<this> {
    const raw = await this._request("POST", `${await this._path()}/suspend`);
    this._raw = raw && typeof raw === "object" ? asObject(raw) : { ...this._raw, status: "suspended" };
    return this;
  }

  /**
   * Let a suspended user act again: calls made for it work from now on. The account's own call: a user acting for
   * itself can't change its status.
   *
   *     await User.fromId("user_42").reactivate();
   */
  async reactivate(): Promise<this> {
    this._raw = await this._request<JsonObject>("PATCH", await this._path(), { json: { status: "active" }, user: null });
    return this;
  }

  /**
   * Stop everything that costs money for this user until `resumeSpending()`, and say what they can
   * do about it. Call it from your billing when they run out (say, at a balance alert) or fall
   * behind. `message` is what NoClick tells them, in your words, up to 500 characters; `action` is
   * your checkout or billing page. Both may use `{{user.id}}`, `{{user.name}}`, `{{user.email}}`
   * and `{{user.metadata.<key>}}`, filled in now (a field this user lacks throws `InvalidRequest`).
   * Without `message`, the default you set in the console is used; with no default either it
   * throws `InvalidRequest`. Without `action`, the default's button.
   *
   * While paused, a call your code makes for them throws `SpendingPaused`; a message they send an
   * agent is answered once per conversation with `message` and `action` and held, up to 24 hours,
   * to run when you resume; a call to a number they reach hears `message`; schedules, webhooks and
   * app events for their agents are skipped. Work under way finishes the step it's on, and what
   * they already have keeps running and billing. Only a key acting for your whole account can
   * pause or resume.
   *
   *     await user.pauseSpending({ message: "You've used your credits.", action: { label: "Top up", url: topUpUrl } });
   */
  async pauseSpending(options: { message?: string; action?: SpendingAction } = {}): Promise<this> {
    const json = compact({ message: options.message, action: options.action ? { label: options.action.label, url: options.action.url } : undefined });
    this._raw = asObject(await this._request("POST", `${await this._path()}/spending/pause`, { json }));
    return this;
  }

  /**
   * Let this user spend again. What was held for them runs now, in the order it arrived, each with
   * when it arrived so the agent knows it waited. Resuming a user who isn't paused changes nothing.
   */
  async resumeSpending(): Promise<this> {
    this._raw = asObject(await this._request("POST", `${await this._path()}/spending/resume`));
    return this;
  }

  /**
   * Mark the user deleted, which frees its id. Invite-only beta: nothing acts for them
   * afterwards (their connections' grants are revoked at each provider, their agents' triggers stop,
   * their inboxes stop receiving mail and their numbers are released), while the record (operations,
   * tool calls, conversations, usage and spend) and the data their resources hold stay until you
   * delete them. `{ export: true }` packs up everything the user holds first, as `export()` does,
   * and deletes the user once the export is stored; `wait()` resolves to the `ExportBundle`. Nothing
   * is deleted if the export fails or is canceled. Only a call acting for the account deletes users.
   */
  async delete(): Promise<void>;
  async delete(options: { export: true }): Promise<Operation<ExportBundle>>;
  async delete(options: { export?: boolean } = {}): Promise<Operation<ExportBundle> | void> {
    if (options.export) {
      const payload = await this._request("POST", `${await this._path()}/export`, { json: { delete_after: true } });
      return Operation._fromPayload<ExportBundle>(payload, { client: this._client, user: null, kind: "user.export", reader: toExportBundle });
    }
    const raw = asObject(await this._request("DELETE", await this._path()));
    this._raw = raw.id ? raw : { ...this._raw, status: "deleted" };
  }

  /**
   * Pack up everything the user holds, in forms that work without NoClick: their own agents'
   * definitions as JSON, their conversations with any agent as JSON Lines transcripts, what agents
   * remember about them as Markdown, their databases as SQL, their buckets' and volumes' files,
   * their dicts and queues as JSON Lines, their repos as git bundles, their apps' settings,
   * connections and secrets by name only (never a token or a value), and each phone number and
   * domain with the call that moves it (`transferOut`). The user keeps working; one export of a user
   * runs at a time (another throws `Conflict` naming it). `wait()` resolves to the `ExportBundle`:
   * a zip `url` valid until `expiresAt` (7 days), its `contents`, and `remainingDependencies`.
   */
  async export(): Promise<Operation<ExportBundle>> {
    const payload = await this._request("POST", `${await this._path()}/export`, { json: {} });
    return Operation._fromPayload<ExportBundle>(payload, { client: this._client, user: null, kind: "user.export", reader: toExportBundle });
  }

  /**
   * Text a verification code to the user's phone (or `phone`, which becomes its number); confirm it
   * with `checkPhone(code)`. Resolves to the number the code went to, and when the code expires.
   */
  async verifyPhone(options: { phone?: string } = {}): Promise<PhoneVerification> {
    const raw = await this._ensure();
    const response = asObject(await this._request("POST", `${await this._path()}/phone/verify`, { json: compact({ phone: options.phone }) }));
    if (response.object === "user") this._raw = response;
    return {
      phone: str(response.phone) ?? options.phone ?? str(raw.phone),
      status: str(response.status),
      expiresAt: parseTime(response.expires_at),
      raw: response,
    };
  }

  /**
   * Check the code the user received; on success the phone is verified. A wrong code throws
   * `InvalidRequest`, an expired one `Expired`, and too many tries `RateLimited`.
   */
  async checkPhone(code: string): Promise<JsonObject> {
    const raw = asObject(await this._request("POST", `${await this._path()}/phone/check`, { json: { code } }));
    if (raw.object === "user") this._raw = raw;
    return raw;
  }

  /**
   * Mint a short-lived token that acts only as this user, with `scopes` (a
   * subset of your key's: `agents`, `humans`, `credentials:request`,
   * `credentials:use`, `channels`, `inbox`, `ai`); `ttlS` is at most 24h. Hand
   * `session.token` to your frontend, or use `NoClick.forSession(session)`.
   * Revoking the minting key revokes its sessions.
   */
  async session(options: { scopes: string | string[]; ttlS?: number }): Promise<Session> {
    const userId = await this._userId(); // minted per page load: no GET unless it may need creating
    const raw = asObject(await this._request("POST", `${userPath(userId)}/sessions`, {
      json: compact({ scopes: typeof options.scopes === "string" ? [options.scopes] : [...options.scopes], ttl_s: options.ttlS }),
    }));
    return new Session(raw, userId, this._api.baseUrl);
  }

  /** The person behind this user: `await (await user.human.approve("Send it?")).wait()`. */
  get human(): Human {
    return new Human({ user: this, client: this._client });
  }
}
