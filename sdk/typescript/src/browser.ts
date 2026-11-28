/**
 * Browsers: a browser an agent drives, and profiles that keep a person's logins.
 *
 *     const profile = BrowserProfile.fromName("ana-work", { createIfMissing: true, user: "user_42" });
 *     await (await profile.login("https://portal.example.com", { reason: "to download your invoices" })).wait();
 *
 *     const browser = await Browser.create({ profile, timeoutS: 900 });
 *     try {
 *       await browser.goto("https://portal.example.com/invoices");
 *       console.log((await browser.act("Download every invoice from September")).summary);
 *     } finally {
 *       await browser.close();
 *     }
 *
 * A browser is Chromium in a sandbox, driven by a model that sees the page and acts on it.
 * NoClick solves the CAPTCHAs it can; when a page still needs a person (one it couldn't solve, a
 * two-factor code), the browser parks, unbilled, while that person finishes the step on a page
 * NoClick sends them. A profile keeps the sign-ins a person made once; when a site signs it out,
 * the next browser asks that person to sign in again the same way and saves the new sign-in. It
 * counts as a credential, so it is never exported and only its own user's browsers and agents use it.
 */

import type { Agent } from "./agent.ts";
import type { Connection } from "./connection.ts";
import { BrowserLiveView, BrowserViewConnection } from "./browserView.ts";
import type { BrowserViewConnectOptions, BrowserViewOptions } from "./browserView.ts";
import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { Conflict, NotFound } from "./errors.ts";
import type { Human } from "./human.ts";
import type { Machine } from "./machine.ts";
import { ApiObject, asObject, compact, createNamed, listAll, listPage, num, parseTime, refId, str } from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { Operation, registerResult, withKinds } from "./operation.ts";
import type { KindScopedFilters, OperationSummary } from "./operation.ts";
import { resolveScope } from "./scope.ts";

/** `parked`: waiting on a person, or (an agent's browser) for its conversation's next turn; neither billed nor counted against `timeoutS`. */
export type BrowserStatus = "starting" | "running" | "parked" | "closed" | "failed";
export type BrowserContentFormat = "markdown" | "text" | "html";
/**
 * What runs a browser: NoClick's remote browsers, a coding agent's own place (its sandbox, its container on a machine),
 * or a machine you started it on.
 */
export type BrowserPlace = "remote" | "sandbox" | "machine";

/** Where the browser is: the page's `url` (after redirects) and `title`. */
export interface PageState {
  url: string | null;
  title: string | null;
  raw: JsonObject;
}

/** One action an `act` took. */
export interface BrowserActStep {
  /** `click`, `type`, `scroll`, `goto`, `download`, `wait_for_person`, ... */
  action: string;
  detail: string | null;
  url: string | null;
  /** The element it acted on, as the page names it (a field's label, a button's text); never what it typed. */
  target: string | null;
}

/** A step of a browser's newest `act`, as a person watching it is told: what it did and to what, never what it typed. */
export interface BrowserWatchedStep {
  action: string;
  target: string | null;
  at: Date | null;
}

/** A step a person is asked to finish in the browser: its `act` waits on them. */
export interface BrowserWaitingOn {
  /** What they're asked to do, in a sentence. */
  person: string;
  /** Whether it's you they asked: only that person takes the browser over and hands it back. */
  forYou: boolean;
}

/** A file an `act` saved. `url` is signed and valid for an hour. */
export interface BrowserDownload {
  name: string;
  sizeBytes: number | null;
  url: string;
}

/** How an `act` went: `done` is false when it ran out of steps or couldn't go on (`summary` says why). */
export interface ActResult {
  done: boolean;
  summary: string;
  steps: BrowserActStep[];
  url: string | null;
  downloads: BrowserDownload[];
  costUsd: number | null;
  raw: JsonObject;
}

/**
 * A site a profile is signed in to. When the site signs the profile out, the next browser that meets
 * its sign-in page asks `signedInBy` to sign in again in the live view, as for a two-factor code,
 * and saves the new sign-in.
 */
export interface SiteLogin {
  domain: string;
  signedInAt: Date | null;
  /**
   * The email of the person who signed in (the one `login` asked), and who is asked again when the
   * sign-in expires; null for a link you passed on yourself, and then the browser's `human` is asked.
   */
  signedInBy: string | null;
  /** When a browser last used the sign-in (null if never). */
  lastUsedAt: Date | null;
  raw: JsonObject;
}

function toPageState(value: unknown): PageState {
  const raw = asObject(value);
  return { url: str(raw.url), title: str(raw.title), raw };
}

function toActResult(value: unknown): ActResult {
  const raw = asObject(value);
  const list = (key: string) => (Array.isArray(raw[key]) ? (raw[key] as JsonObject[]) : []);
  return {
    done: raw.done === true,
    summary: str(raw.summary) ?? "",
    steps: list("steps").map((s) => ({ action: str(s.action) ?? "", detail: str(s.detail), url: str(s.url), target: str(s.target) })),
    url: str(raw.url),
    downloads: list("downloads").map((d) => ({ name: str(d.name) ?? "", sizeBytes: num(d.size_bytes), url: str(d.url) ?? "" })),
    costUsd: num(raw.cost_usd),
    raw,
  };
}

function toSiteLogin(value: unknown): SiteLogin {
  const raw = asObject(value);
  return {
    domain: str(raw.domain) ?? "", signedInAt: parseTime(raw.signed_in_at), signedInBy: str(raw.signed_in_by),
    lastUsedAt: parseTime(raw.last_used_at), raw,
  };
}

registerResult("browser.act", toActResult);
registerResult("browser.login", (result) => toSiteLogin("site" in asObject(result) ? asObject(result).site : result));

/** Which browsers a listing reads. */
export interface BrowserFilters {
  profile?: BrowserProfile | string;
  status?: BrowserStatus | "live";
  /** An agent's browsers. */
  agent?: Agent | string;
  /** One conversation's (with `agent`). */
  conversation?: string;
}

async function filterQuery(options: BrowserFilters): Promise<Record<string, string | undefined>> {
  return {
    profile_id: await refId(options.profile), status: options.status, agent_id: await refId(options.agent),
    conversation: options.conversation,
  };
}

/** The wire address of the person a page or sign-in asks. */
function humanTo(human: Human | undefined): JsonObject | undefined {
  return human === undefined ? undefined : human._address;
}

const LOGIN_KINDS = ["browser.login"] as const;

/**
 * A live-browser link where a person signs in to a site, and the
 * operation that finishes once they have: `await login.wait()` resolves to the `SiteLogin`.
 */
export class BrowserLogin extends Operation<SiteLogin> {
  /** The page where the person signs in, in a live browser. */
  url = "";
  expiresAt: Date | null = null;
  /** The site's domain. */
  domain: string | null = null;
  /** Channels the link went out on (`["email"]`); empty when nobody was sent it. */
  deliveredVia: string[] = [];
  /** Channels that failed, each with a `reason`: send the link yourself. */
  undelivered: JsonObject[] = [];

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** Sign-in operations (kind `browser.login`), newest first. */
  static override async list(options: KindScopedFilters & { limit?: number } = {}): Promise<Operation<SiteLogin>[]> {
    return (await Operation.list(withKinds(options, LOGIN_KINDS, "BrowserLogin.list"))) as Operation<SiteLogin>[];
  }

  /** One page of sign-in operations; pass `nextCursor` back as `cursor`. */
  static override async listPage(options: KindScopedFilters & PageOptions = {}): Promise<Page<Operation<SiteLogin>>> {
    return (await Operation.listPage(withKinds(options, LOGIN_KINDS, "BrowserLogin.listPage"))) as Page<Operation<SiteLogin>>;
  }

  /** How many sign-in operations match, by status. */
  static override async summary(options: KindScopedFilters = {}): Promise<OperationSummary> {
    return await Operation.summary(withKinds(options, LOGIN_KINDS, "BrowserLogin.summary"));
  }

  /** @internal */
  static _fromLink(payload: unknown, init: { client?: NoClick; user?: ObjectInit["user"] }): BrowserLogin {
    const body = asObject(payload);
    const login = new BrowserLogin(Operation._init(body.operation, { ...init, kind: "browser.login" }));
    login.url = str(body.url) ?? "";
    login.expiresAt = parseTime(body.expires_at);
    login.domain = str(body.domain);
    const delivery = asObject(body.delivery);
    login.deliveredVia = Array.isArray(delivery.delivered_via) ? delivery.delivered_via.map(String) : [];
    login.undelivered = Array.isArray(delivery.undelivered) ? (delivery.undelivered as JsonObject[]) : [];
    return login;
  }

  override toString(): string {
    return this.url;
  }
}

/**
 * Saved sign-ins for one person.
 * `BrowserProfile.fromName("ana-work", { createIfMissing: true, user: "user_42" })` is lazy;
 * `profile.login(url)` asks the person to sign in once, and browsers started with the profile are signed in.
 * Its `region` is where its browsers run; its sign-ins are kept in the US whatever the region.
 */
export class BrowserProfile extends ApiObject {
  private _createOnLoad = false;
  private _region: string | undefined;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create an empty profile called `name` (unique per user; a duplicate throws `Conflict` with
   * `existingId`, or with `allowExisting: true` returns the profile already there, signed in where it
   * was). `region` is where its browsers run (`regions({ kind: "browser" })`; the account's default when
   * omitted), fixed for its life; its sign-ins are kept in the US.
   */
  static async create(name: string, options: CallOptions & AllowExisting & { region?: string } = {}): Promise<BrowserProfile> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/browser_profiles", compact({ name, region: options.region }), {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new BrowserProfile({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the profile called `name`; with `createIfMissing` it's created, empty, on
   * first use, in `region` when you pass one.
   */
  static fromName(name: string, options: CallOptions & { createIfMissing?: boolean; region?: string } = {}): BrowserProfile {
    const profile = new BrowserProfile({ hints: { name }, client: options.client, user: options.user });
    profile._createOnLoad = options.createIfMissing ?? false;
    profile._region = options.region;
    return profile;
  }

  static fromId(profileId: string, options: CallOptions = {}): BrowserProfile {
    return new BrowserProfile({ hints: { id: profileId }, client: options.client, user: options.user });
  }

  static async get(profileId: string, options: CallOptions = {}): Promise<BrowserProfile> {
    return await BrowserProfile.fromId(profileId, options).hydrate();
  }

  /** The current user's profiles (the account's own outside `asUser`, or those `userFilter` covers). */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<BrowserProfile[]> {
    return await listAll({ ...options, path: "/v1/browser_profiles" }, (raw, user) => new BrowserProfile({ raw, client: options.client, user }));
  }

  /** One page of profiles; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<BrowserProfile>> {
    return await listPage({ ...options, path: "/v1/browser_profiles" }, (raw, user) => new BrowserProfile({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** Where its browsers run, fixed when it is created. */
  get region(): string | null {
    return this._field("region");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  /** The sites it is signed in to, most recently signed in first (throws until hydrated). */
  get sites(): SiteLogin[] {
    const sites = this.raw.sites;
    return Array.isArray(sites) ? sites.map(toSiteLogin) : [];
  }
  /** When a browser last used it (null if never). */
  get lastUsedAt(): Date | null {
    return parseTime(this._field("last_used_at"));
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/browser_profiles/${id}`);
    const name = String(this._hints.name);
    const page = asObject(await this._request("GET", "/v1/browser_profiles", { query: { name } }));
    const rows = (Array.isArray(page.data) ? (page.data as JsonObject[]) : []).filter((row) => row.name === name);
    if (rows.length) return rows[0];
    if (!this._createOnLoad) {
      throw new NotFound(`No browser profile is named "${name}".`, {
        nextStep: "Create it with BrowserProfile.create(...) or pass { createIfMissing: true }.",
        details: { name, kind: "browser_profile" },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/browser_profiles", { json: compact({ name, region: this._region }) });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this._request<JsonObject>("GET", `/v1/browser_profiles/${err.existingId}`);
    }
  }

  private async path(): Promise<string> {
    return `/v1/browser_profiles/${await refId(this)}`;
  }

  /**
   * Ask a person to sign in to the site at `url` in a live browser; the sign-in is saved to this
   * profile. `human` is who is asked: the profile's user when omitted (an account profile with
   * no `human` sends nothing, so pass the link's `url` on yourself). `await login.wait()`
   * resolves to the `SiteLogin`. You ask once: when the site signs the profile out, the browser that
   * meets its sign-in page asks the same person again (`SiteLogin.signedInBy`). The link's browser
   * starts (and is billed) only once the person opens it.
   */
  async login(url: string, options: { human?: Human; reason?: string } = {}): Promise<BrowserLogin> {
    const payload = await this._request("POST", `${await this.path()}/login`, {
      json: compact({ url, reason: options.reason, human: humanTo(options.human) }),
    });
    return BrowserLogin._fromLink(payload, { client: this._client, user: this._callScope() });
  }

  /**
   * Sign the profile out of `domain` and drop what it and its subdomains stored. A short browser
   * (about a minute, billed like any) clears them and saves the profile; this resolves once it has.
   * It throws `Conflict` (naming the browser) while another browser saves into the profile, and a
   * browser already using the profile keeps the old state until it closes.
   */
  async forget(domain: string): Promise<void> {
    await this._request("DELETE", `${await this.path()}/sites/${encodeURIComponent(domain)}`);
    if (this._raw && Array.isArray(this._raw.sites)) {
      this._raw = { ...this._raw, sites: (this._raw.sites as JsonObject[]).filter((s) => s.domain !== domain) };
    }
  }

  /** Delete the profile and every sign-in in it. */
  async delete(): Promise<void> {
    await this._request("DELETE", await this.path());
  }
}

export interface BrowserCreateOptions extends CallOptions {
  /**
   * Signed in to this profile's sites; the browser acts in the profile's user, runs in its region and
   * saves new sign-ins into it when it closes. One such browser per profile at a time: a second throws
   * `Conflict` naming the first (`browser_id`).
   */
  profile?: BrowserProfile | string;
  /** How long it may run: 300 by default, up to 3600; time waiting on a person doesn't count. */
  timeoutS?: number;
  /** Where it runs without a profile (`regions({ kind: "browser" })`); the account's default when omitted. */
  region?: string;
  /** NoClick solves the CAPTCHAs it can before asking a person (default); `false` for sites whose terms forbid it. */
  solveCaptchas?: boolean;
  /** Who is asked when a page needs a person: the user by default, you for an account browser. */
  human?: Human;
  /**
   * Run it on this machine (one NoClick runs for you, or your own), in a container of its own with no agent: it reaches
   * sites from the machine, costs nothing beyond the machine and keeps no profile (leave `profile` and `region` out).
   * Its key needs the `machines` scope too, and a machine a space shares with you takes it at `use`. While that machine
   * fetches the browser's image (its first, on a machine with no agents) the browser is `starting`, and runs once the
   * image is held, or ends `failed` saying why (`endReason`).
   */
  machine?: Machine | string;
}

export interface BrowserActOptions {
  /** At most this many actions: 50 by default, up to 200. */
  maxSteps?: number;
  /** https URLs (a bucket's `signedUrl` works) NoClick downloads into the browser for the task's forms; up to 5. */
  files?: string[];
  /**
   * It may create an account where the task needs one: NoClick makes the password, types it, and keeps it in the
   * account's 1Password (the connection's vault for new logins) or else as a new website login for the site, with
   * the username the task gives.
   */
  signUp?: boolean;
  /** Seconds to wait here; the step keeps going after. */
  timeoutS?: number;
  /** Return at once with an `Operation` whose `wait()` resolves to the `ActResult`. */
  background?: boolean;
}

/**
 * A running browser; it closes at `expiresAt`, or when you `close()` it.
 * Billed per minute while it runs, plus the model tokens `act` and `extract` use; time it waits on a
 * person is neither billed nor counted against `timeoutS`.
 */
export class Browser extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Start a browser; with `profile` it is signed in to the profile's sites and acts in the profile's user, and with
   * `machine` it runs on that machine, alone.
   *
   * @example
   * const box = Machine.fromName("build-box");
   * const browser = await Browser.create({ machine: box, timeoutS: 900 });
   * console.log(browser.place, browser.placeName); // "machine", "build-box"
   */
  static async create(options: BrowserCreateOptions = {}): Promise<Browser> {
    let scope = resolveScope(options.user);
    if (options.user === undefined && options.profile instanceof BrowserProfile) {
      await options.profile._ensure();
      scope = options.profile._callScope() ?? null;
    }
    const raw = await resolveClient(options.client).request<JsonObject>("POST", "/v1/browsers", {
      json: compact({
        profile_id: await refId(options.profile), timeout_s: options.timeoutS, region: options.region,
        solve_captchas: options.solveCaptchas === false ? false : undefined, human: humanTo(options.human),
        machine_id: await refId(options.machine),
      }),
      user: scope,
    });
    return new Browser({ raw, client: options.client, user: scope });
  }

  static fromId(browserId: string, options: CallOptions = {}): Browser {
    return new Browser({ hints: { id: browserId }, client: options.client, user: options.user });
  }

  static async get(browserId: string, options: CallOptions = {}): Promise<Browser> {
    return await Browser.fromId(browserId, options).hydrate();
  }

  /**
   * The current user's browsers, newest first: optionally one profile's, or an agent's (one `conversation`'s: an
   * agent's browser works in the conversation whose turn started it, one at a time); `status: "live"` lists those
   * starting, running or parked.
   */
  static async list(options: ReadOptions & BrowserFilters & { limit?: number } = {}): Promise<Browser[]> {
    return await listAll(
      { ...options, path: "/v1/browsers", query: await filterQuery(options) },
      (raw, user) => new Browser({ raw, client: options.client, user }),
    );
  }

  /** One page of browsers; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions & BrowserFilters = {}): Promise<Page<Browser>> {
    return await listPage(
      { ...options, path: "/v1/browsers", query: await filterQuery(options) },
      (raw, user) => new Browser({ raw, client: options.client, user }),
    );
  }

  get id(): string {
    return this._field("id");
  }
  get status(): BrowserStatus {
    return this._field("status");
  }
  /** How long it may run; parked time doesn't count. */
  get timeoutS(): number | null {
    return this._field("timeout_s");
  }
  /** Where it runs: its profile's region, else the one it was created in. */
  get region(): string | null {
    return this._field("region");
  }
  /**
   * What runs it: `remote` (NoClick's remote browsers), or, for a coding agent's own browser beside it, `sandbox`
   * (its sandbox) or `machine` (its container on a machine, `placeName`), which reaches what the agent runs on localhost;
   * a browser started with `machine` is `machine` too, in a container of its own there.
   */
  get place(): BrowserPlace {
    return this._field("place") ?? "remote";
  }
  /** The machine it runs on, for a browser whose `place` is `machine`. */
  get placeName(): string | null {
    return this._field("place_name") ?? null;
  }
  /** The profile it is signed in with (null if none). */
  get profileId(): string | null {
    return this._field("profile_id");
  }
  /** The agent driving it, for an agent's browser. */
  get agentId(): string | null {
    return this._field("agent_id");
  }
  /** The conversation it works in, for a browser an agent's turn started. */
  get conversation(): string | null {
    return this._field("conversation");
  }
  /** Its newest `act`'s operation. */
  get actId(): string | null {
    return this._field("act_id");
  }
  /** Whether an `act` is driving it now. */
  get acting(): boolean {
    return this._field("acting") === true;
  }
  /** The steps its newest `act` has taken so far. */
  get steps(): BrowserWatchedStep[] {
    const steps = this._field<JsonObject[] | null>("steps") ?? [];
    return steps.map((s) => ({ action: str(s.action) ?? "", target: str(s.target), at: parseTime(s.at) }));
  }
  /** Whether a person has taken it over (`takeOver`): its `act` waits until they hand it back. */
  get held(): boolean {
    return this._field("held") === true;
  }
  /** A step a person is asked to finish in it, while its `act` waits on them. */
  get waitingOn(): BrowserWaitingOn | null {
    const waiting = this._field<JsonObject | null>("waiting_on");
    return waiting ? { person: str(waiting.person) ?? "", forYou: waiting.for_you === true } : null;
  }
  /**
   * A NoClick page where you watch it live and can take over; it works while the browser runs, with no sign-in, so
   * treat it like a password. Only a caller that may take the browser over reads it: your account's keys (one acting
   * for a user too) and its signed-in owner. An MCP connection, an agent's turn and an app's code read null.
   */
  get liveUrl(): string | null {
    return this._field("live_url");
  }
  /** The page it is on. */
  get url(): string | null {
    return this._field("url");
  }
  get title(): string | null {
    return this._field("title");
  }
  /** A picture of the page it last stopped on (its `act`'s end, or its conversation's turn's), signed for an hour from
   *  each read; null before it first stopped. */
  get frameUrl(): string | null {
    return this._field("frame_url");
  }
  /** Whether NoClick solves CAPTCHAs before asking a person. */
  get solveCaptchas(): boolean | null {
    return this._field("solve_captchas");
  }
  /** Seconds it has waited parked: not billed, not counted against `timeoutS`. */
  get parkedS(): number | null {
    return this._field("parked_s");
  }
  /** What it has cost so far: minutes and model tokens. */
  get costUsd(): number | null {
    return this._field("cost_usd");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** When it started running (null while it starts). */
  get startedAt(): Date | null {
    return parseTime(this._field("started_at"));
  }
  get expiresAt(): Date | null {
    return parseTime(this._field("expires_at"));
  }
  get closedAt(): Date | null {
    return parseTime(this._field("closed_at"));
  }
  /**
   * Why it ended, once `closed` or `failed`: `closed` (you closed it), `expired`, `idle`, `ended`, `start_failed`, and
   * for one on a machine `image_pull_failed` or `image_timed_out` (its machine couldn't fetch its image, or not in time).
   */
  get endReason(): string | null {
    return this._field("end_reason") ?? null;
  }

  private get path(): string {
    return `/v1/browsers/${this._known("id")}`;
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", this.path);
  }

  /** Open `url` and wait for the page to load. */
  async goto(url: string): Promise<PageState> {
    const state = toPageState(await this._request("POST", `${this.path}/goto`, { json: { url } }));
    this._raw = { ...(this._raw ?? this._hints), url: state.url, title: state.title };
    return state;
  }

  /**
   * Have the model carry out `instruction` on the page, with `files` downloaded into the browser first
   * for its forms. NoClick solves the CAPTCHAs it can, giving one half a minute; one still there, or a
   * two-factor prompt, parks the browser (not billed, not counted against its timeout) and sends a person
   * a page carrying the live view, and the step waits until they have dealt with it; so does the sign-in
   * page of a site whose saved sign-in expired, and the new sign-in is saved to the profile.
   * The website logins the browser may use (connections of integration `website_login`), and each login item with a
   * site in a connected 1Password's vaults (named `<vault>/<item title>`, read from 1Password as they're typed), are
   * told to the model by name and username only: on a site's sign-in form NoClick types them in, with the two-factor
   * code, and the model never reads them. A code the site emails or texts, and a verification link it emails, NoClick waits for where the
   * login says and types or opens it; one that never comes is asked of a person. `signUp` lets it create an account,
   * kept in the account's 1Password (the connection's vault for new logins) or else as a new website login, with the
   * username the task gives, else an email address of the login's own where NoClick receives the site's mail
   * (`Connection.loginMail`); the step that signed up says where it went. Both only in a browser no agent is beside (a remote
   * one, or one alone on a machine).
   * `{ background: true }` returns at once with an `Operation` whose `wait()` resolves to the `ActResult`.
   */
  act(instruction: string, options: BrowserActOptions & { background: true }): Promise<Operation<ActResult>>;
  act(instruction: string, options?: BrowserActOptions & { background?: false }): Promise<ActResult>;
  async act(instruction: string, options: BrowserActOptions = {}): Promise<ActResult | Operation<ActResult>> {
    const payload = await this._request("POST", `${this.path}/act`, {
      json: compact({ instruction, max_steps: options.maxSteps, files: options.files, sign_up: options.signUp || undefined }),
    });
    const op = Operation._fromPayload<ActResult>(payload, {
      client: this._client, user: this._callScope(), kind: "browser.act", reader: toActResult,
    });
    return options.background ? op : await op.wait({ timeoutS: options.timeoutS });
  }

  /**
   * Sign in on the page the browser is on (the site's sign-in page) with a website login, a connection of
   * integration `website_login`, by name, id or object, or a connected 1Password's login item by its name,
   * `"<vault>/<item title>"`. NoClick types its username and password (and its two-factor code) into the site's own
   * form, submits it, and carries on through a
   * next page asking for more, with no model: no value reaches your code, a step or a log. It types only on the
   * login's own sites, over https, and only in a browser no agent is beside.
   *
   * @example
   *   const login = await Connection.create("acme-billing", {
   *     integration: "website_login",
   *     data: { site: "billing.acme.com", username: "ana@acme.test", password: process.env.ACME_PASSWORD },
   *   });
   *   await browser.goto("https://billing.acme.com/login");
   *   const result = await browser.signIn(login);
   *   console.log(result.done, result.summary);
   */
  async signIn(connection: string | Connection, options: { timeoutS?: number } = {}): Promise<ActResult> {
    const payload = await this._request("POST", `${this.path}/sign_in`, {
      json: { connection: await refId(connection) },
    });
    const op = Operation._fromPayload<ActResult>(payload, {
      client: this._client, user: this._callScope(), kind: "browser.act", reader: toActResult,
    });
    return await op.wait({ timeoutS: options.timeoutS });
  }

  /** Read what `query` describes off the page, shaped by `schema` (a JSON Schema) when you pass one. */
  async extract<T = unknown>(query: string, options: { schema?: JsonObject } = {}): Promise<T> {
    const response = asObject(await this._request("POST", `${this.path}/extract`, { json: compact({ query, schema: options.schema }) }));
    return response.data as T;
  }

  /** A PNG of the viewport, or the whole page with `fullPage`. */
  async screenshot(options: { fullPage?: boolean } = {}): Promise<Uint8Array> {
    return await this._request<Uint8Array>("GET", `${this.path}/screenshot`, {
      query: { full_page: options.fullPage ? "true" : undefined },
      responseType: "bytes",
    });
  }

  /** The page's content as markdown (default), text or html. */
  async content(options: { format?: BrowserContentFormat } = {}): Promise<string> {
    const response = asObject(await this._request("GET", `${this.path}/content`, { query: { format: options.format ?? "markdown" } }));
    return str(response.content) ?? "";
  }

  /**
   * Take the browser over from its agent, as a person: it waits for you (unbilled), and an `act` in it stops at its
   * next step until you `handBack()`. Drive it from its `liveUrl`. Asked to finish a step in it (`waitingOn`), only
   * the person asked takes it over.
   */
  async takeOver(): Promise<void> {
    this._raw = asObject(await this._request("POST", `${this.path}/take_over`));
  }

  /**
   * Hand the browser back: a step you were asked to finish counts as finished (as Done on its page does), and the
   * `act` waiting on you carries on; with nothing asked, it's the agent's again.
   */
  async handBack(): Promise<void> {
    this._raw = asObject(await this._request("POST", `${this.path}/hand_back`));
  }

  /**
   * A single-use token for the browser's live view, for a page of your own: `connect()` the result once, within two
   * minutes, or hand its `url` and `token` to the page from your server. `thumb`: smaller pictures for a tile.
   * `control`: a view that drives it, once you've taken it over (`takeOver`); it ends when it's handed back. Your
   * account's keys and its signed-in owner get one; an MCP connection, an agent's turn and an app's code don't.
   */
  async liveView(options: BrowserViewOptions = {}): Promise<BrowserLiveView> {
    if (options.control && options.thumb) throw new TypeError("A view that drives the browser shows it full size: leave out thumb");
    const raw = options.control
      ? await this._request("POST", `${this.path}/live_control`)
      : await this._request("POST", `${this.path}/live_view`, { json: { thumb: options.thumb === true } });
    return BrowserLiveView._from(asObject(raw), { client: this._client, user: this._callScope() });
  }

  /**
   * Show the browser live in this page: asks for a token (`liveView`) and connects, and again with a new token
   * whenever the view needs to open again, until it ends or you `close()` it. See `BrowserViewConnection`.
   */
  view(options: BrowserViewOptions & BrowserViewConnectOptions = {}): BrowserViewConnection {
    const control = options.control === true;
    return new BrowserViewConnection(async () => {
      const minted = await this.liveView({ control, thumb: options.thumb });
      return { url: minted.url, token: minted.token ?? "" };
    }, control, options, true);
  }

  /** Close the browser now (billing stops with it). The profile keeps any new sign-ins. */
  async close(): Promise<void> {
    const raw = asObject(await this._request("DELETE", this.path));
    this._raw = { ...(this._raw ?? this._hints), ...raw, status: "closed" };
  }
}
