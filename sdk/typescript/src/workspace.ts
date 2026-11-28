/**
 * Workspaces: channels and their members (agents and people) in one place, like a Slack workspace.
 *
 *     const acme = Workspace.fromName("Acme", { createIfMissing: true, members: [support, billing, ana], budgetUsdPerMonth: 200 });
 *     const room = await Channel.create("escalations", { workspace: acme, members: [support, ana] });
 *     await acme.subscribe(new OnEvent("stripe", "invoice_payment_failed"), { channels: "all", wake: "all" });
 *
 * A workspace lives in a scope you already have: your account, or one of your users (`asUser`).
 */

import { Agent, agentId } from "./agent.ts";
import { Channel, Subscription, subscriptionWire, toMessage } from "./channel.ts";
import type { ChannelMessage, SubscriptionSource, SubscriptionWake } from "./channel.ts";
import { Conflict, NotFound } from "./errors.ts";
import {
  ApiObject, asList, asObject, compact, createNamed, defined, givesFields, listAll, listPage, num, parseTime, refId, str,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import type { NoClick as NoClickClient } from "./client.ts";
import { resolveClient } from "./client.ts";
import { Repo } from "./repo.ts";
import { resolveScope } from "./scope.ts";
import { Session } from "./session.ts";
import { templateAnswer, templateBody } from "./spaceTemplate.ts";
import type { TemplateAdd, TemplateOptions, TemplatePlan } from "./spaceTemplate.ts";
import { trashed } from "./trash.ts";
import type { TrashItem } from "./trash.ts";
import { User } from "./user.ts";

/** A person's role in a workspace: `admin` invites and removes people, `member` reads every channel, `guest` only its own. */
export type WorkspaceRole = "admin" | "member" | "guest";

/**
 * One of a workspace's members: an agent, or one of your users (`type` `user`, `userId` your id
 * for them). An account workspace holds any of your users, each posting as
 * themselves; a user's own workspace has that one user. A `person` is someone who joined it from their own
 * NoClick sign-in (their `userId` is that login's id), with their `email` and when they were last active.
 */
export interface WorkspaceMember {
  id: string;
  type: "agent" | "user";
  agentId: string | null;
  userId: string | null;
  name: string | null;
  /** A user's role (`null` for an agent). */
  role: WorkspaceRole | null;
  person: boolean;
  email: string | null;
  lastSeenAt: Date | null;
  createdAt: Date | null;
  joinedAt: Date | null;
  raw: JsonObject;
}

function toWorkspaceMember(raw: JsonObject): WorkspaceMember {
  return {
    id: String(raw.id),
    type: raw.type as WorkspaceMember["type"],
    agentId: str(raw.agent_id),
    userId: str(raw.user_id),
    name: str(raw.name),
    role: (str(raw.role) as WorkspaceRole | null) ?? null,
    person: raw.person === true,
    email: str(raw.email),
    lastSeenAt: parseTime(raw.last_seen_at),
    createdAt: parseTime(raw.created_at),
    joinedAt: parseTime(raw.joined_at ?? raw.created_at),
    raw,
  };
}

/** A workspace as the signed-in person sees it (`Workspace.mine`): their account's (`own`) or one they joined. */
export interface MyWorkspace {
  id: string;
  name: string;
  logoUrl: string | null;
  own: boolean;
  role: "owner" | WorkspaceRole;
  status: string | null;
  /** Whose it is: the account's owner's name (`null` for your own). */
  accountName: string | null;
  /** Your user id in that account (your login id; `null` for your own). */
  userId: string | null;
  memberId: string | null;
  joinedAt: Date | null;
  /**
   * A personal space: the one every account has, its owner's own (made on first read), where what's made without
   * naming a space goes. Never archived, deleted or left; listed first among your own.
   */
  personal: boolean;
  raw: JsonObject;
}

function toMyWorkspace(raw: JsonObject): MyWorkspace {
  return {
    id: String(raw.id),
    name: str(raw.name) ?? "",
    logoUrl: str(raw.logo_url),
    own: raw.own === true,
    role: (str(raw.role) ?? "member") as MyWorkspace["role"],
    status: str(raw.status),
    accountName: str(raw.account_name),
    userId: str(raw.user_id),
    memberId: str(raw.member_id),
    joinedAt: parseTime(raw.joined_at),
    personal: raw.personal === true,
    raw,
  };
}

/** What an invite is for, read without joining (`Workspace.invitation`). */
/** A space's own NoClick: the agent that answers in it, made the first time it's asked for. */
export interface SpaceNoClick {
  workspaceId: string;
  /** Put it in a channel by this id. */
  agentId: string;
  name: string;
  /** How a person reads it: `NoClick · <space>`. */
  label: string;
  raw: JsonObject;
}

export interface InvitePreview {
  workspace: { id: string; name: string; logoUrl: string | null };
  accountName: string | null;
  invitedBy: string | null;
  role: WorkspaceRole;
  type: "link" | "email";
  email: string | null;
  status: string;
  alreadyMember: boolean;
  expiresAt: Date | null;
  raw: JsonObject;
}

/**
 * An invite into a workspace: a link anyone signed in may use (`type` `link`, up to `maxUses`), or one emailed to
 * an address. Its `url` is where accepting it opens, while it can still be used.
 */
export class WorkspaceInvite {
  readonly raw: JsonObject;
  readonly #client: NoClickClient | undefined;
  readonly #user: CallOptions["user"];

  /** @internal */
  constructor(raw: JsonObject, client?: NoClickClient, user?: CallOptions["user"]) {
    this.raw = raw;
    this.#client = client;
    this.#user = user;
  }

  get id(): string {
    return String(this.raw.id);
  }
  get workspaceId(): string {
    return String(this.raw.workspace_id);
  }
  get type(): "link" | "email" {
    return this.raw.type as "link" | "email";
  }
  get role(): WorkspaceRole {
    return this.raw.role as WorkspaceRole;
  }
  get email(): string | null {
    return str(this.raw.email);
  }
  get url(): string | null {
    return str(this.raw.url);
  }
  get uses(): number {
    return num(this.raw.uses) ?? 0;
  }
  get maxUses(): number | null {
    return num(this.raw.max_uses);
  }
  get usesLeft(): number | null {
    return num(this.raw.uses_left);
  }
  get invitedBy(): string | null {
    return str(this.raw.invited_by);
  }
  /** `active`, `accepted`, `revoked`, `expired` or `used_up`. */
  get status(): string {
    return str(this.raw.status) ?? "active";
  }
  get expiresAt(): Date | null {
    return parseTime(this.raw.expires_at);
  }
  get sentAt(): Date | null {
    return parseTime(this.raw.sent_at);
  }
  get createdAt(): Date | null {
    return parseTime(this.raw.created_at);
  }

  async #call(method: string, suffix = ""): Promise<WorkspaceInvite> {
    const raw = await resolveClient(this.#client).request<JsonObject>(
      method, `/v1/workspaces/${this.workspaceId}/invites/${this.id}${suffix}`, { user: resolveScope(this.#user) });
    return new WorkspaceInvite(raw, this.#client, this.#user);
  }

  /** Turn it off: its link stops working at once (who joined with it stays). */
  async revoke(): Promise<WorkspaceInvite> {
    return await this.#call("DELETE");
  }

  /** Email an email invite again, good for another 7 days. */
  async resend(): Promise<WorkspaceInvite> {
    return await this.#call("POST", "/resend");
  }

  /** A link's new link: this one stops; the new one keeps its role, uses left and expiry. */
  async rotate(): Promise<WorkspaceInvite> {
    return await this.#call("POST", "/rotate");
  }
}

/** What a workspace can share with its people. */
export type WorkspaceResourceKind = "connection" | "app" | "database" | "files" | "repo" | "skill" | "memory" | "machine" | "automation";

/**
 * One of your account's resources shared with a workspace: every person in it reaches it at `membersLevel` (its
 * admins and members) or `guestsLevel` (its guests), and `levels` are the kind's, lowest first (`agents`: through
 * its agents only). `level` is what you hold through it (the account: its highest). A machine is shared for agents to
 * run on: at `run` the workspace's agents run there and its people see it, at `use` they may also move its agents onto
 * it and off it; its shell and files stay yours. An automation (one of your workflows) is seen with its runs at
 * `runs`, also run at `run` (members' default) and also changed at `edit`, its runs billed to you.
 */
export class WorkspaceResource {
  readonly raw: JsonObject;
  readonly #client: NoClickClient | undefined;
  readonly #user: CallOptions["user"];

  /** @internal */
  constructor(raw: JsonObject, client?: NoClickClient, user?: CallOptions["user"]) {
    this.raw = raw;
    this.#client = client;
    this.#user = user;
  }

  get id(): string {
    return String(this.raw.id);
  }
  get workspaceId(): string {
    return String(this.raw.workspace_id);
  }
  get kind(): WorkspaceResourceKind {
    return this.raw.kind as WorkspaceResourceKind;
  }
  /** Its id in its own area (a connection's, an app's, a bucket's...). */
  get ref(): string {
    return String(this.raw.ref);
  }
  /** Its name (`null` once it's gone). */
  get name(): string | null {
    return str(this.raw.name);
  }
  get membersLevel(): string {
    return String(this.raw.members_level);
  }
  get guestsLevel(): string {
    return String(this.raw.guests_level);
  }
  get levels(): string[] {
    return Array.isArray(this.raw.levels) ? (this.raw.levels as string[]) : [];
  }
  get level(): string | null {
    return str(this.raw.level);
  }
  get addedAt(): Date | null {
    return parseTime(this.raw.added_at);
  }

  #path(): string {
    return `/v1/workspaces/${this.workspaceId}/resources/${this.id}`;
  }

  /** Change what its members or guests get (an omitted one stays); the account's own. */
  async update(changes: { membersLevel?: string; guestsLevel?: string }): Promise<WorkspaceResource> {
    const raw = await resolveClient(this.#client).request<JsonObject>("PATCH", this.#path(), {
      json: compact({ members_level: changes.membersLevel, guests_level: changes.guestsLevel }),
      user: resolveScope(this.#user),
    });
    return new WorkspaceResource(raw, this.#client, this.#user);
  }

  /** Take it from the workspace's people; your account keeps it, and agents that hold it as their own keep it. */
  async remove(): Promise<void> {
    await resolveClient(this.#client).request("DELETE", this.#path(), { user: resolveScope(this.#user) });
  }
}

/** One kind on a workspace's Resources tab: how many, the counts it breaks into, and its items. */
export interface WorkspaceSummaryKind {
  count: number;
  items: JsonObject[];
  [count: string]: number | JsonObject[];
}

/**
 * A workspace's resources in one read (`workspace.summary()`): `kinds.agents` (`working`, `waiting`, `idle`),
 * `machines` (`up`, and `shared`: the machines shared with it, each with the agents here placed on it), `channels`,
 * `numbers`, `email`, and each shareable kind as its Resources tab names it (`connections`, `websites`, `databases`,
 * `files`, `code`, `skills`, `memories`), each item `linked` when shared.
 */
export interface WorkspaceSummary {
  workspaceId: string;
  kinds: Record<string, WorkspaceSummaryKind>;
  raw: JsonObject;
}

/**
 * A space saved as a template (`workspace.saveAsTemplate()`): the repository holding it (null on a dry run), what it
 * holds, what it asks whoever adds it for, and what stayed behind.
 */
export interface SpaceTemplate {
  name: string;
  repoName: string;
  repo: Repo | null;
  /** Its parts by name: `channels`, `agents`, `skills`, `memories`, `automations`, `stores`, and whether it carries an `app`. */
  contains: JsonObject;
  /** What it asks for: `connections` (`{integration, for}`), `secrets` (`{name, keys, for}`), and `budget_usd_per_month`. */
  asks: JsonObject;
  leftOut: { what: string; why: string }[];
  /** What a template never carries, in a person's words. */
  never: string[];
  files: number;
  commitSha: string | null;
  summary: string;
  raw: JsonObject;
}

/**
 * A question your own NoClick asked a space's NoClick (`Workspace.questions`): `waiting` until it's answered once,
 * then `answered` with its `answer`, or `unanswered` when the space's NoClick couldn't.
 */
export interface SpaceQuestion {
  id: string;
  workspaceId: string;
  question: string;
  status: "waiting" | "answered" | "unanswered";
  answer: string | null;
  askedAt: Date | null;
  answeredAt: Date | null;
  raw: JsonObject;
}

function toSpaceQuestion(raw: JsonObject): SpaceQuestion {
  return {
    id: String(raw.id), workspaceId: String(raw.workspace_id), question: str(raw.question) ?? "",
    status: (str(raw.status) ?? "waiting") as SpaceQuestion["status"], answer: str(raw.answer),
    askedAt: parseTime(raw.asked_at), answeredAt: parseTime(raw.answered_at), raw,
  };
}

/** Who a workspace holds: your `Agent`s and your `User`s. */
export type WorkspaceMemberInput = Agent | User;

async function wireWorkspaceMember(member: WorkspaceMemberInput, role?: WorkspaceRole): Promise<JsonObject> {
  if (member instanceof Agent) {
    if (role) throw new TypeError("An agent in a workspace has no role; a role is a user's.");
    return { agent_id: await agentId(member) };
  }
  if (member instanceof User) return compact({ user_id: await member._userId(), role });
  throw new TypeError(`A workspace member is an Agent or a User, not ${JSON.stringify(member)}`);
}

function sameWorkspaceMember(member: WorkspaceMember, spec: JsonObject): boolean {
  return spec.agent_id ? member.agentId === spec.agent_id : member.type === "user" && member.userId === spec.user_id;
}

export interface WorkspaceCreateOptions extends CallOptions {
  members?: WorkspaceMemberInput[];
  /** What its channels' agent turns may spend in a month; once reached, its channels halt until the month turns or the cap goes up. */
  budgetUsdPerMonth?: number | null;
  /** An https URL of its logo (the product shows its initials without one). */
  logoUrl?: string | null;
}

/** What `fromName` sets on an existing workspace. */
const CONVERGED = ["budget_usd_per_month", "logo_url"] as const;

/**
 * A container for channels and their members (agents and people) inside a scope you already have:
 * your account, or one of your users. Its `budgetUsdPerMonth` caps what its channels spend in a UTC
 * month (once reached, each channel halts as it would next start a turn); `archive()` closes its
 * channels and keeps everything readable, taking no more changes; `subscribe` posts events into several
 * of its channels at once. Up to 100 active a scope, 50 open channels and 200 members each.
 */
export class Workspace extends ApiObject {
  private _createWith: ({ name: string } & WorkspaceCreateOptions) | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Make a workspace (names are unique per scope; a taken one throws `Conflict` with `existingId`, or with
   * `allowExisting: true` returns the workspace already there, as it is: its members and settings don't change).
   */
  static async create(name: string, options: WorkspaceCreateOptions & AllowExisting = {}): Promise<Workspace> {
    const scope = resolveScope(options.user);
    const members = options.members ? await Promise.all(options.members.map((m) => wireWorkspaceMember(m))) : undefined;
    const json = compact({ name, members, budget_usd_per_month: options.budgetUsdPerMonth, logo_url: options.logoUrl });
    const raw = await createNamed("/v1/workspaces", json, { allowExisting: options.allowExisting, user: scope, client: options.client });
    return new Workspace({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the active workspace called `name` in the current (or given) scope. Given fields,
   * it gets the workspace and sets the ones you pass, on every run: on an existing one a member your code no
   * longer lists is removed, a new one added, and `budgetUsdPerMonth` and `logoUrl` set to yours; a field
   * left out is never changed, and `null` clears the cap or the logo. `createIfMissing` makes it when
   * there's none; without it, a missing workspace throws `NotFound`. Each run with fields is a write: set them at startup or in a setup script, and
   * take the bare `fromName` in request handlers.
   */
  static fromName(name: string, options: WorkspaceCreateOptions & { createIfMissing?: boolean } = {}): Workspace {
    const workspace = new Workspace({ hints: { name }, client: options.client, user: options.user });
    workspace._creates = Boolean(options.createIfMissing);
    if (workspace._creates || givesFields(options)) workspace._createWith = { ...options, name };
    return workspace;
  }

  static fromId(workspaceId: string, options: CallOptions = {}): Workspace {
    return new Workspace({ hints: { id: workspaceId }, client: options.client, user: options.user });
  }

  static async get(workspaceId: string, options: CallOptions = {}): Promise<Workspace> {
    return await Workspace.fromId(workspaceId, options).hydrate();
  }

  /**
   * The current scope's workspaces (or those `userFilter` covers), newest first; `status` keeps `active` or
   * `archived` ones, `agent` the ones that agent is a member of.
   */
  static async list(options: ReadOptions & { status?: "active" | "archived"; limit?: number; agent?: string | Agent } = {}): Promise<Workspace[]> {
    return await listAll(
      { ...options, path: "/v1/workspaces", query: { status: options.status, agent_id: await agentId(options.agent) } },
      (raw, user) => new Workspace({ raw, client: options.client, user }),
    );
  }

  /** One page of workspaces; pass `nextCursor` back as `cursor`. */
  static async listPage(
    options: ReadOptions & PageOptions & { status?: "active" | "archived"; agent?: string | Agent } = {},
  ): Promise<Page<Workspace>> {
    return await listPage(
      { ...options, path: "/v1/workspaces", query: { status: options.status, agent_id: await agentId(options.agent) } },
      (raw, user) => new Workspace({ raw, client: options.client, user }),
    );
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  get logoUrl(): string | null {
    return this._field("logo_url");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get status(): "active" | "archived" {
    return this._field("status");
  }
  /** The account's personal space, made the first time it's read: where what's made without naming a space goes. */
  get personal(): boolean {
    return this._field<boolean | null>("personal") === true;
  }
  get budgetUsdPerMonth(): number | null {
    return this._field("budget_usd_per_month");
  }
  /** What its channels spent this month, in US dollars. */
  get spentUsd(): number | null {
    return num(this._field("spent_usd"));
  }
  get channelCount(): number {
    return num(this._field("channel_count")) ?? 0;
  }
  get members(): WorkspaceMember[] {
    return (this._field<JsonObject[] | null>("members") ?? []).map(toWorkspaceMember);
  }
  /** Your role in it: `owner` (your account's, or your user's own), else the role you joined with. */
  get role(): "owner" | WorkspaceRole | null {
    return this._field("role");
  }
  /** How many people are in it, its account's owner included, of `peopleLimit`, the most its account's plan
   * allows (3 on Free, 50 on Member). */
  get peopleCount(): number {
    return num(this._field("people_count")) ?? 0;
  }
  get peopleLimit(): number | null {
    return num(this._field("people_limit"));
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  /**
   * The space's own NoClick (an account's own spaces have one; the personal space's is the account's own NoClick),
   * made the first time it's asked for: put it in a channel by its `agentId`.
   *
   *     const helper = await Workspace.fromName("Support").noclickAgent();
   *     await channel.addMember(helper.agentId);
   */
  async noclickAgent(): Promise<SpaceNoClick> {
    const raw = await this._request<JsonObject>("GET", `${await this.path()}/noclick`, { user: null });
    return { workspaceId: str(raw.workspace_id) ?? "", agentId: str(raw.agent_id) ?? "", name: str(raw.name) ?? "",
             label: str(raw.label) ?? "", raw };
  }

  /** Its path once its id is known (a workspace reached by name loads first). */
  private async path(): Promise<string> {
    const id = this._known("id") ?? (await this._ensure()).id;
    return `/v1/workspaces/${id}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/workspaces/${id}`);
    const name = String(this._hints.name);
    const rows = (asList(await this._request("GET", "/v1/workspaces", { query: { name, status: "active" } })) as JsonObject[])
      .filter((row) => row.name === name && row.status !== "archived");
    if (rows.length) return await this.converge(rows[0]);
    const definition = this._createWith;
    if (!definition || !this._creates) {
      throw new NotFound(`No workspace is named "${name}".`, {
        nextStep: "Make it with Workspace.create(...) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    const json = compact({
      name,
      members: definition.members ? await Promise.all(definition.members.map((m) => wireWorkspaceMember(m))) : undefined,
      budget_usd_per_month: definition.budgetUsdPerMonth,
      logo_url: definition.logoUrl,
    });
    try {
      return await this._request<JsonObject>("POST", "/v1/workspaces", { json });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // made concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/workspaces/${err.existingId}`));
    }
  }

  /** Set the fields `fromName` was given on an existing workspace. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    const definition = this._createWith;
    if (!definition) return raw;
    const id = String(raw.id);
    const settings: JsonObject = { budget_usd_per_month: definition.budgetUsdPerMonth, logo_url: definition.logoUrl };
    const changes: JsonObject = {};
    for (const key of CONVERGED) {
      if (settings[key] !== undefined && JSON.stringify(raw[key] ?? null) !== JSON.stringify(settings[key])) changes[key] = settings[key];
    }
    let current = Object.keys(changes).length ? await this._request<JsonObject>("PATCH", `/v1/workspaces/${id}`, { json: changes }) : raw;
    if (definition.members) {
      const wanted = await Promise.all(definition.members.map((m) => wireWorkspaceMember(m)));
      const have = (Array.isArray(current.members) ? (current.members as JsonObject[]) : []).map(toWorkspaceMember);
      let changed = false;
      for (const member of have) {
        if (!wanted.some((spec) => sameWorkspaceMember(member, spec))) {
          await this._request("DELETE", `/v1/workspaces/${id}/members/${encodeURIComponent(member.id)}`);
          changed = true;
        }
      }
      for (const spec of wanted) {
        if (!have.some((member) => sameWorkspaceMember(member, spec))) {
          await this._request("POST", `/v1/workspaces/${id}/members`, { json: spec });
          changed = true;
        }
      }
      if (changed) current = await this._request<JsonObject>("GET", `/v1/workspaces/${id}`);
    }
    return current;
  }

  /** Change its name, logo or spend cap (`null` clears the logo or the cap; an omitted field stays). */
  async update(changes: { name?: string; logoUrl?: string | null; budgetUsdPerMonth?: number | null }): Promise<this> {
    this._raw = await this._request<JsonObject>("PATCH", await this.path(), {
      json: defined({ name: changes.name, logo_url: changes.logoUrl, budget_usd_per_month: changes.budgetUsdPerMonth }),
    });
    return this;
  }

  /**
   * Upload its logo: a JPEG, PNG, WebP or GIF of at most 2 MB, kept as an account file that `logoUrl`
   * then points at. Bytes need `mimeType` (a `Blob` has its own type).
   */
  async setLogo(image: Blob | Uint8Array | ArrayBuffer, options: { mimeType?: string } = {}): Promise<this> {
    const mimeType = options.mimeType ?? (image instanceof Blob && image.type ? image.type : undefined);
    if (!mimeType) throw new TypeError("Say the image's type: { mimeType: 'image/png' }.");
    this._raw = await this._request<JsonObject>("PUT", `${await this.path()}/logo`, { body: image, query: { mime_type: mimeType } });
    return this;
  }

  /** Close its channels and stop its subscriptions, keeping everything readable; `status` becomes `archived`. */
  async archive(): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `${await this.path()}/archive`);
    return this;
  }

  /**
   * Move it to the trash with its channels (their messages, DMs and files), its invites and its own NoClick,
   * restorable for 30 days as it was. Its people lose it meanwhile; your agents and users stay. Returns its
   * `TrashItem`.
   */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this.path()), this);
  }

  /**
   * Make an archived workspace active again: the channels its archiving closed open again, and its subscriptions
   * hear again. Its name must be free among your active workspaces (`Conflict`).
   */
  async unarchive(): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `${await this.path()}/unarchive`);
    return this;
  }

  /** Its channels, newest first (`status`: `open` or `closed`). */
  async channels(options: { status?: "open" | "closed" } = {}): Promise<Channel[]> {
    await this._ensure();
    return await Channel.list({ workspace: this, status: options.status, user: this._callScope(), client: this._client });
  }

  /** Add an agent or one of your users (with its `role`, `member` by default). */
  async add(member: WorkspaceMemberInput, options: { role?: WorkspaceRole } = {}): Promise<WorkspaceMember> {
    const json = await wireWorkspaceMember(member, options.role);
    const added = toWorkspaceMember(asObject(await this._request("POST", `${await this.path()}/members`, { json })));
    if (this._raw) this._raw = { ...this._raw, members: [...(Array.isArray(this._raw.members) ? this._raw.members : []), added.raw] };
    return added;
  }

  /** Remove a member (a `WorkspaceMember`, its id, or the `Agent` or `User`); it leaves every channel here too. */
  async remove(member: string | WorkspaceMember | WorkspaceMemberInput): Promise<void> {
    let memberId: string;
    if (typeof member === "string") memberId = member;
    else if (member instanceof Agent || member instanceof User) {
      const spec = await wireWorkspaceMember(member);
      this._raw = await this._load();
      const found = this.members.find((m) => sameWorkspaceMember(m, spec));
      if (!found) throw new NotFound("That isn't a member of this workspace.", { details: { workspace_id: this._known("id") ?? null } });
      memberId = found.id;
    } else memberId = member.id;
    await this._request("DELETE", `${await this.path()}/members/${encodeURIComponent(memberId)}`);
    if (this._raw && Array.isArray(this._raw.members)) {
      this._raw = { ...this._raw, members: (this._raw.members as JsonObject[]).filter((m) => m.id !== memberId) };
    }
  }

  /** Change a person's role (the workspace's owner, or an admin of it). */
  async setRole(member: string | WorkspaceMember, role: WorkspaceRole): Promise<WorkspaceMember> {
    const memberId = typeof member === "string" ? member : member.id;
    const raw = asObject(await this._request("PATCH", `${await this.path()}/members/${encodeURIComponent(memberId)}`, { json: { role } }));
    return toWorkspaceMember(raw);
  }

  /**
   * A link anyone signed in to NoClick may use to join (its `url`), as `role` (`member` by default), at most
   * `maxUses` times, for `expiresInDays` (30 by default, at most 90). People who join become users of your account,
   * and what they do in the workspace bills it. Its owner or an admin; 50 invites a day.
   */
  async inviteLink(options: { role?: WorkspaceRole; expiresInDays?: number; maxUses?: number } = {}): Promise<WorkspaceInvite> {
    const raw = await this._request<JsonObject>("POST", `${await this.path()}/invite_links`, {
      json: compact({ role: options.role, expires_in_days: options.expiresInDays, max_uses: options.maxUses }),
    });
    return new WorkspaceInvite(raw, this._client, this._callScope());
  }

  /** Email `email` an invite, good for 7 days, that only a NoClick sign-in with that email accepts. */
  async invite(email: string, options: { role?: WorkspaceRole } = {}): Promise<WorkspaceInvite> {
    const raw = await this._request<JsonObject>("POST", `${await this.path()}/invites`, { json: compact({ email, role: options.role }) });
    return new WorkspaceInvite(raw, this._client, this._callScope());
  }

  /** Its invites, newest first (`status` keeps one: `active`, `accepted`, `revoked`, `expired`, `used_up`). */
  async invites(options: { status?: string } = {}): Promise<WorkspaceInvite[]> {
    const rows = asList(await this._request("GET", `${await this.path()}/invites`, { query: { status: options.status } })) as JsonObject[];
    return rows.map((raw) => new WorkspaceInvite(raw, this._client, this._callScope()));
  }

  /**
   * What your account shares with it (`kind` keeps one); a person in it reads what reaches them, with their `level`.
   */
  async resources(options: { kind?: WorkspaceResourceKind } = {}): Promise<WorkspaceResource[]> {
    const rows = asList(await this._request("GET", `${await this.path()}/resources`, { query: { kind: options.kind } })) as JsonObject[];
    return rows.map((raw) => new WorkspaceResource(raw, this._client, this._callScope()));
  }

  /**
   * Share one of your account's resources with it (its id, or the object: a `Database`, a `Bucket`...): every person
   * in it gets it at `membersLevel` (the kind's default when left out) or, a guest, `guestsLevel` (`none`), and
   * anyone who joins later. A connection is shared by its id.
   */
  async share(
    kind: WorkspaceResourceKind,
    ref: string | ApiObject,
    options: { membersLevel?: string; guestsLevel?: string } = {},
  ): Promise<WorkspaceResource> {
    const raw = await this._request<JsonObject>("POST", `${await this.path()}/resources`, {
      json: compact({ kind, ref: await refId(ref), members_level: options.membersLevel, guests_level: options.guestsLevel }),
    });
    return new WorkspaceResource(raw, this._client, this._callScope());
  }

  /**
   * What was said across its open channels since `since` (the last 24 hours when left out), in one read: each message
   * of a channel's main timeline posted since then, or whose thread had a reply since (`replyCount`; read the replies
   * with the channel's `replies`), with its `channelName`. Only the channels you see in it, never a DM. Up to `limit`
   * (50 by default), oldest first: pass the last as `after` to read on.
   */
  async messages(options: { since?: Date | string; after?: ChannelMessage | string; limit?: number } = {}): Promise<ChannelMessage[]> {
    const since = options.since instanceof Date ? options.since.toISOString() : options.since;
    const after = typeof options.after === "string" ? options.after : options.after?.id;
    const rows = asList(await this._request("GET", `${await this.path()}/messages`, { query: { since, cursor: after, limit: options.limit } }));
    return (rows as JsonObject[]).map(toMessage);
  }

  /** Its Resources tab in one read: agents, machines, channels, numbers, email and each shareable kind. */
  async summary(): Promise<WorkspaceSummary> {
    const raw = await this._request<JsonObject>("GET", `${await this.path()}/summary`);
    return { workspaceId: String(raw.workspace_id), kinds: asObject(raw.kinds) as unknown as Record<string, WorkspaceSummaryKind>, raw };
  }

  /**
   * Save the space as a template: a new repository of yours holding its `space.json` (its channels, agents and their
   * instructions, the skills and memories they use, the automations it shares), those parts' files, and the code of
   * the app it shares. Wherever one of your connections is named, the template names its integration and asks for
   * it. Never its messages, data, people, accounts or secrets' values (`never`); `leftOut` names what else stayed
   * behind and why. The repository is private until you make it public (`template.repo.makePublic()`). Only one of
   * the account's own spaces, never the personal space. `dryRun` says what would go in, making nothing.
   */
  async saveAsTemplate(options: {
    repoName?: string; description?: string; app?: string | ApiObject; includeApp?: boolean; dryRun?: boolean;
  } = {}): Promise<SpaceTemplate> {
    const raw = await this._request<JsonObject>("POST", `${await this.path()}/template`, {
      json: compact({
        repo_name: options.repoName, description: options.description,
        app_id: options.app === undefined ? undefined : await refId(options.app),
        include_app: options.includeApp === false ? false : undefined, dry_run: options.dryRun || undefined,
      }),
    });
    const repo = raw.repo && typeof raw.repo === "object" ? asObject(raw.repo) : null;
    return {
      name: str(raw.name) ?? "", repoName: str(raw.repo_name) ?? "",
      repo: repo ? Repo._fromView(repo, { client: this._client, user: this._callScope() }) : null,
      contains: asObject(raw.contains), asks: asObject(raw.asks),
      leftOut: asList(raw.left_out) as { what: string; why: string }[], never: asList(raw.never) as string[],
      files: num(raw.files) ?? 0, commitSha: str(asObject(raw.commit).sha), summary: str(raw.summary) ?? "", raw,
    };
  }

  /**
   * Add a space template to this space, beside what's there: its channels carry the template's word
   * (`#social-ideas`), an agent whose name you have already carries it too ("Social Writer"); nothing you have is
   * reused or merged. `leaveOut` names the parts that stay out (every channel out brings just the agents). Otherwise
   * as `Workspace.fromTemplate`.
   *
   *     const plan = await lumen.addTemplate(address, { leaveOut: [{ kind: "app" }], dryRun: true });
   *     console.log(plan.parts.filter((p) => p.included).map((p) => p.named));
   *     await (await lumen.addTemplate(address, { leaveOut: [{ kind: "app" }] })).wait();
   */
  async addTemplate(source: string | ApiObject, options: TemplateOptions & { dryRun: true }): Promise<TemplatePlan>;
  async addTemplate(source: string | ApiObject, options?: TemplateOptions & { dryRun?: false }): Promise<TemplateAdd>;
  async addTemplate(source: string | ApiObject, options: TemplateOptions = {}): Promise<TemplatePlan | TemplateAdd> {
    const raw = await this._request<JsonObject>("POST", `${await this.path()}/template/add`, {
      json: await templateBody(source, options),
    });
    return templateAnswer(asObject(raw), { client: this._client, user: this._callScope() });
  }

  /**
   * Add a space template as a new space of yours: its channels, agents (with their instructions, skills and
   * memories), automations, data stores and app, each made in your account, all of it or none. Each account it uses
   * is one you have (never asked again) or waits for you to connect, and the space's `#noclick` opens on a welcome
   * post saying what arrived, a row to connect each account left and a first task to tap. `source` is the template's
   * address (its origin URL, or a `noclick.com/deploy?repo=` link naming it) or one of your repos holding a
   * `space.json`. Resolves to a `TemplateAdd` whose `wait()` gives a `TemplateAdded`; with `dryRun: true`, to its
   * `TemplatePlan`. Only the account adds one.
   *
   *     const plan = await Workspace.fromTemplate(address, { dryRun: true });
   *     console.log(plan.summary, plan.cap.usdPerMonth, plan.connections.filter((a) => !a.connected));
   *     const added = await (await Workspace.fromTemplate(address, {
   *       secrets: { unsplash: { UNSPLASH_ACCESS_KEY: key } },
   *     })).wait();
   */
  static async fromTemplate(source: string | ApiObject, options: TemplateOptions & { name?: string; dryRun: true }): Promise<TemplatePlan>;
  static async fromTemplate(source: string | ApiObject, options?: TemplateOptions & { name?: string; dryRun?: false }): Promise<TemplateAdd>;
  static async fromTemplate(source: string | ApiObject, options: TemplateOptions & { name?: string } = {}): Promise<TemplatePlan | TemplateAdd> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/workspaces/from_template", {
      json: await templateBody(source, options, compact({ name: options.name })), user: null,
    }));
    return templateAnswer(raw, { client: options.client, user: null });
  }

  /**
   * The workspaces you see, signed in to NoClick: your personal space first (`personal`), your account's other active
   * ones (`own`, role `owner`), then the active ones you joined in other accounts, with your role and whose each is,
   * then your account's archived ones (`status` archived), which `unarchive` brings back. One of the account's own
   * secret keys reads the account's own ones, never those you joined.
   */
  static async mine(options: { client?: NoClickClient } = {}): Promise<MyWorkspace[]> {
    const rows = asList(await resolveClient(options.client).request("GET", "/v1/me/workspaces", { user: null })) as JsonObject[];
    return rows.map(toMyWorkspace);
  }

  /**
   * A session acting as you in a workspace you joined: `session.client()` reads and posts in its channels and talks
   * to its agents, as your user in its account. It lasts `ttlS` (an hour by default, at most a day): mint another
   * before it lapses.
   */
  static async session(workspace: string | MyWorkspace, options: { client?: NoClickClient; ttlS?: number } = {}): Promise<Session> {
    const id = typeof workspace === "string" ? workspace : workspace.id;
    const api = resolveClient(options.client);
    const raw = await api.request<JsonObject>("POST", `/v1/me/workspaces/${id}/sessions`, {
      json: compact({ ttl_s: options.ttlS }),
      user: null,
    });
    return new Session(raw, str(raw.user_id) ?? "", api.baseUrl);
  }

  /**
   * What your own NoClick asked a space's NoClick (a space you own or joined), newest first, each with its answer once
   * it came: read with your own key, or a `session` in the space.
   */
  static async questions(workspace: string | MyWorkspace, options: { client?: NoClickClient } = {}): Promise<SpaceQuestion[]> {
    const id = typeof workspace === "string" ? workspace : workspace.id;
    const rows = asList(await resolveClient(options.client).request("GET", `/v1/workspaces/${id}/questions`, { user: null }));
    return (rows as JsonObject[]).map(toSpaceQuestion);
  }

  /**
   * Your personal space: the space every account has, made the first time it's read, where an agent or a channel
   * made without naming a space goes. Invite people to it as to any space; they never see your own chat with NoClick
   * there. Signed in to NoClick; answers it as `mine()` lists it (first).
   *
   *     const personal = await Workspace.personalSpace();
   *     console.log(personal.id, personal.name);
   */
  static async personalSpace(options: { client?: NoClickClient } = {}): Promise<MyWorkspace> {
    return toMyWorkspace(await resolveClient(options.client).request<JsonObject>("POST", "/v1/me/personal_space", { user: null }));
  }

  /** Leave a workspace you joined (and each of its channels). */
  static async leave(workspace: string | MyWorkspace, options: { client?: NoClickClient } = {}): Promise<void> {
    const id = typeof workspace === "string" ? workspace : workspace.id;
    await resolveClient(options.client).request("DELETE", `/v1/me/workspaces/${id}`, { user: null });
  }

  /** What an invite is for (the workspace, who invited you, the role), read without joining; signed in. */
  static async invitation(token: string, options: { client?: NoClickClient } = {}): Promise<InvitePreview> {
    const raw = await resolveClient(options.client).request<JsonObject>("GET", `/v1/invites/${encodeURIComponent(token)}`, { user: null });
    const workspace = asObject(raw.workspace);
    return {
      workspace: { id: String(workspace.id), name: str(workspace.name) ?? "", logoUrl: str(workspace.logo_url) },
      accountName: str(raw.account_name),
      invitedBy: str(raw.invited_by),
      role: raw.role as WorkspaceRole,
      type: raw.type as "link" | "email",
      email: str(raw.email),
      status: str(raw.status) ?? "active",
      alreadyMember: raw.already_member === true,
      expiresAt: parseTime(raw.expires_at),
      raw,
    };
  }

  /** Join an invite's workspace as yourself (signed in); answers it as `mine()` lists it. */
  static async acceptInvite(token: string, options: { client?: NoClickClient } = {}): Promise<MyWorkspace> {
    const raw = await resolveClient(options.client).request<JsonObject>("POST", `/v1/invites/${encodeURIComponent(token)}/accept`, { user: null });
    return toMyWorkspace(raw);
  }

  /**
   * Post an app's events, a webhook's calls or a platform event type into several of its channels:
   * `channels` is `"all"` (channels made later too) or a list. `wake` and `filters` as `channel.subscribe`
   * takes them. Up to 20 a workspace.
   */
  async subscribe(
    source: SubscriptionSource,
    options: { channels: "all" | (Channel | string)[]; wake?: SubscriptionWake; filters?: JsonObject },
  ): Promise<Subscription> {
    if (!options || (options.channels !== "all" && !Array.isArray(options.channels))) {
      throw new TypeError('subscribe() needs channels: "all" or a list of the workspace\'s channels');
    }
    const channels = options.channels === "all" ? "all" : await Promise.all(options.channels.map(async (c) => String(await refId(c))));
    const json = { ...(await subscriptionWire(source, options.wake, options.filters)), channels };
    const raw = await this._request<JsonObject>("POST", `${await this.path()}/subscriptions`, { json });
    return Subscription._from(raw, { client: this._client, user: this._callScope() });
  }

  /** Its own subscriptions (each channel's are on the channel), oldest first. */
  async subscriptions(): Promise<Subscription[]> {
    const rows = asList(await this._request("GET", `${await this.path()}/subscriptions`)) as JsonObject[];
    return rows.map((raw) => Subscription._from(raw, { client: this._client, user: this._callScope() }));
  }
}
