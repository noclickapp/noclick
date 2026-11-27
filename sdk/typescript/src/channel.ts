/**
 * Channels: a shared room where your user, your agents and remote (A2A) agents talk. A message can carry
 * files (`channel.upload`, then `post(text, { files })`), which the agents it wakes read in their turn, and
 * members react to messages with emoji (`channel.react`). A subscription
 * posts an app's events, a webhook's calls or NoClick's own events into it (`channel.subscribe`). A channel can live in a
 * `Workspace`, which holds channels and their members like a workspace in a team chat.
 *
 * `Channel.fromName` gets a standing room (opening it if it's missing) and sets what you pass on it, and a
 * `Cron` on a channel (its `triggers`) posts its message into the room on a schedule, as your account.
 *
 * As in a team chat, a message can start a thread (`channel.reply`, read with `channel.replies`): its replies stay
 * out of the main timeline (`channel.messages`) unless sent `alsoInChannel`, and an agent woken by a reply answers
 * in that thread. You follow the threads you start, post in or are @mentioned in (`Channel.threads` lists them,
 * with what you haven't read). Members pin messages (`channel.pin`, `channel.pins`), a channel keeps bookmarks
 * (`channel.addBookmark`), and `channel.files` and `channel.links` read what was posted in it. `channel.delete()`
 * moves it to the trash.
 */

import { attachmentIds, toAttachments, uploadFile } from "./attachment.ts";
import type { Attachment, FileInput, UploadOptions } from "./attachment.ts";
import { Agent, agentId } from "./agent.ts";
import { Cron } from "./cron.ts";
import { Conflict, NotFound } from "./errors.ts";
import { trashed } from "./trash.ts";
import type { TrashItem } from "./trash.ts";
import { OnEvent, OnPlatformEvent, OnWebhook, toAgentTrigger, triggerKey } from "./trigger.ts";
import type { AgentTrigger } from "./trigger.ts";
import { User } from "./user.ts";
import {
  ApiObject, asList, asObject, compact, createNamed, defined, givesFields, listAll, listPage, parseTime, refId, str,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { resolveScope } from "./scope.ts";
import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import type { UserOption } from "./scope.ts";
import type { Workspace } from "./workspace.ts";

/**
 * Who a post is from: an `Agent`, `{ agentId }`, or the user (`"user"`, a `User`; in a workspace's
 * channel a `User` posts as that one of its users). Omitted = the account.
 */
export type ChannelPostAs = Agent | { agentId: string } | "user" | User | { user: true };

/**
 * A remote agent reached over A2A. `headers` (e.g. `Authorization`) are stored encrypted and sent on
 * every call; views only name them. Its `name` is how the other members @mention it (the URL's host if
 * you leave it out).
 *
 *     const partner = new A2AMember("https://agents.partner.com/a2a", { headers: { Authorization: "Bearer ..." }, name: "partner" });
 *     await room.add(partner);
 */
export class A2AMember {
  readonly url: string;
  readonly headers: Record<string, string> | null;
  readonly name: string | null;

  constructor(url: string, options: { headers?: Record<string, string>; name?: string } = {}) {
    this.url = url;
    this.headers = options.headers ?? null;
    this.name = options.name ?? null;
  }
}

/**
 * Who posts, or a remote agent: an `A2AMember` or its A2A URL (`"https://..."` or `{ a2aUrl }`).
 * Objects may carry a display `name`.
 */
export type ChannelMemberInput =
  | ChannelPostAs
  | A2AMember
  | string
  | { a2aUrl: string; headers?: Record<string, string>; name?: string }
  | { agentId: string; name?: string };

/**
 * Who posted a message: `type` is `user` (a person), `account` (your account), `agent`, `workflow_agent`
 * (an agent from your app's Automations, `id` its member id), `a2a` (an outside agent), `system`
 * (NoClick saying why the room halted), or `app` (an event a subscription posted, `name` being the app's
 * or the webhook's).
 */
export interface ChannelAuthor {
  type: string;
  id: string | null;
  name: string | null;
}

/** One of the members a membership entry names: its channel member id and what it is. */
export interface ChannelMembershipMember {
  id: string;
  type: string;
  name: string;
  agentId: string | null;
  userId: string | null;
}

/**
 * Who joined or left a channel, kept in it as a `system` message (`ChannelMessage.membership`): `by` `added` or
 * `removed` `members`. `by` is null when NoClick did it (a member left the space, or its automation's node went), and
 * names the member itself when a person joined (by posting) or left by themselves. No agent answers it, it wakes no
 * one and it's never unread.
 */
export interface ChannelMembership {
  action: "added" | "removed";
  by: ChannelAuthor | null;
  members: ChannelMembershipMember[];
}

function toMembership(raw: JsonObject): ChannelMembership | null {
  const event = raw.event && typeof raw.event === "object" ? asObject(raw.event) : null;
  if (!event || event.type !== "membership" || asObject(raw.author ?? {}).type !== "system") return null;
  return {
    action: event.action === "removed" ? "removed" : "added",
    by: event.by && typeof event.by === "object" ? toAuthor(event.by) : null,
    members: (Array.isArray(event.members) ? (event.members as JsonObject[]) : []).map((m) => ({
      id: String(m.id), type: str(m.type) ?? "", name: str(m.name) ?? "", agentId: str(m.agent_id), userId: str(m.user_id),
    })),
  };
}

export interface ChannelMember {
  id: string;
  /**
   * `agent`, `user` or `a2a`, or `workflow_agent`: an agent from your NoClick app's Automations,
   * added in the app (its `raw` names its `workflow_id`, `node_id` and `workflow_name`).
   */
  type: string | null;
  agentId: string | null;
  /** A `user` member's id (your id for them). */
  userId: string | null;
  a2aUrl: string | null;
  /** The names of the headers an A2A member carries (never their values). */
  a2aHeaderNames: string[];
  name: string | null;
  raw: JsonObject;
}

function toMember(raw: JsonObject): ChannelMember {
  return {
    id: String(raw.id),
    type: str(raw.type),
    agentId: str(raw.agent_id),
    userId: str(raw.user_id),
    a2aUrl: str(raw.a2a_url),
    a2aHeaderNames: Array.isArray(raw.a2a_header_names) ? (raw.a2a_header_names as string[]) : [],
    name: str(raw.name),
    raw,
  };
}

/** A file on a channel's message: an `Attachment`. */
export type ChannelAttachment = Attachment;

/** One emoji on a message: how many reacted with it, and who. */
export interface ChannelReaction {
  emoji: string;
  count: number;
  by: { type: string; id: string | null; name: string | null }[];
}

function toReaction(raw: JsonObject): ChannelReaction {
  const by = Array.isArray(raw.by) ? (raw.by as JsonObject[]) : [];
  return {
    emoji: str(raw.emoji) ?? "",
    count: typeof raw.count === "number" ? raw.count : by.length,
    by: by.map((b) => ({ type: str(b.type) ?? "", id: str(b.id), name: str(b.name) })),
  };
}

export interface ChannelMessage {
  id: string;
  channelId: string;
  author: ChannelAuthor;
  text: string;
  /** The members it @mentions by name, and `channel`, `here` or `everyone` (which wake every agent). */
  mentions: unknown[];
  createdAt: Date | null;
  /**
   * The subscription that posted it, for an `app` message. A `system` message carries an `event` too: a pin's
   * notice `{ type: "pinned", message_id }`, or who joined or left `{ type: "membership", ... }` (`membership`).
   */
  subscriptionId: string | null;
  /** The event as it arrived (bounded), for an `app` message. */
  event: JsonObject | null;
  /** The files it carries. */
  attachments: Attachment[];
  /** Its reactions, one per emoji in the order each was first used. */
  reactions: ChannelReaction[];
  /** For a reply: the message whose thread it's in. */
  threadId: string | null;
  /** A reply posted in the main timeline too. */
  alsoInChannel: boolean;
  /** How many replies its thread has. */
  replyCount: number;
  lastReplyAt: Date | null;
  /** Who replied in its thread, most recent first, each once (at most 5). */
  replyAuthors: ChannelAuthor[];
  /** Whether you follow its thread. */
  following: boolean;
  /** The replies in its thread you haven't read (counted for a thread you follow). */
  unreadReplies: number;
  /** Who pinned it and when, or null. */
  pinned: { by: ChannelAuthor; at: Date | null } | null;
  /** Its channel's name, on a workspace's messages (`Workspace.messages`). */
  channelName?: string | null;
  /** A `system` message saying who joined or left: what changed (`ChannelMembership`); null for any other message. */
  membership?: ChannelMembership | null;
  raw: JsonObject;
}

/** A thread you follow (`Channel.threads`): where it is, the message that started it and its latest reply. */
export interface ChannelThread {
  /** The id of the message that started it. */
  id: string;
  channelId: string;
  channelName: string;
  workspaceId: string | null;
  parent: ChannelMessage;
  latestReply: ChannelMessage | null;
  replyCount: number;
  /** The replies you haven't read. */
  unreadCount: number;
  following: boolean;
  lastReplyAt: Date | null;
  raw: JsonObject;
}

/** One of your own sections of your channels (`Channel.sections`): its name, whether it's folded, its channels in order. */
export interface ChannelSection {
  /** A UUID: make one for a new section (`crypto.randomUUID()`), which keeps it. */
  id: string;
  name: string;
  /** Folded: only its channels with something unread show. */
  folded: boolean;
  channelIds: string[];
}

/** The built-in lists of a channel sidebar, which fold too. */
export type ChannelSectionsList = "starred" | "channels";

/**
 * Your own sections of a workspace's channels (or of your channels in no workspace), as a sidebar groups them, and
 * which built-in lists are folded. A channel sits in one section at most; one in none is in the Channels list.
 */
export interface ChannelSections {
  workspaceId: string | null;
  /** The version they were read at: pass it back to `Channel.saveSections` (0 until the first save). */
  version: number;
  sections: ChannelSection[];
  folded: ChannelSectionsList[];
  updatedAt: Date | null;
  raw: JsonObject;
}

/** A pinned message: who pinned it, and when. */
export interface ChannelPin {
  message: ChannelMessage;
  by: ChannelAuthor;
  at: Date | null;
}

/** A link saved in a channel. */
export interface ChannelBookmark {
  id: string;
  channelId: string;
  title: string;
  url: string;
  by: ChannelAuthor;
  createdAt: Date | null;
  raw: JsonObject;
}

/** A file posted in a channel (or in one of its threads: `threadId`). */
export interface ChannelFile {
  messageId: string;
  threadId: string | null;
  author: ChannelAuthor;
  createdAt: Date | null;
  file: Attachment;
}

/** A web address posted in a channel (or one of its threads); `title` is a markdown link's text. */
export interface ChannelLink {
  messageId: string;
  threadId: string | null;
  author: ChannelAuthor;
  createdAt: Date | null;
  url: string;
  title: string | null;
  domain: string;
}

export interface ChannelCreateOptions extends CallOptions {
  members?: ChannelMemberInput[];
  /** One line on what the channel is for. */
  topic?: string;
  /**
   * Who a person's message wakes: `all` (the server's default) every agent, `mentions` only the agents it mentions
   * by name. An agent's message wakes only the agents it mentions, in either mode.
   */
  mode?: "mentions" | "all";
  /** Hard stop: agent turns since a person last posted. */
  maxAgentTurns?: number;
  /** Hard stop: how deep agents may @mention each other in one chain. */
  maxMentionHops?: number;
  budgetUsd?: number;
  /**
   * The `Workspace` (or its id) it lives in: its agents and users must be the workspace's members
   * (anyone else throws `InvalidRequest`), and it can hold several of your users. A `Workspace`
   * carries its scope, so `user` beside one is refused; with an id, `user` says whose workspace it is.
   */
  workspace?: string | Workspace;
}

/**
 * A channel your code defines: `budgetUsd: null` lifts the budget, `null` puts `maxAgentTurns` or
 * `maxMentionHops` back to its default (20 and 8), and `triggers` are `Cron` schedules whose `message`
 * is posted in the room on each tick, as your account.
 */
export interface ChannelDefinition extends Omit<ChannelCreateOptions, "maxAgentTurns" | "maxMentionHops" | "budgetUsd"> {
  maxAgentTurns?: number | null;
  maxMentionHops?: number | null;
  budgetUsd?: number | null;
  triggers?: Cron[];
}

/** What `fromName` sets on an existing channel. */
const CONVERGED = ["topic", "mode", "max_agent_turns", "max_mention_hops", "budget_usd"] as const;

/** The hard stops a channel opens with; `null` in a definition puts one back. */
const DEFAULT_STOPS = { maxAgentTurns: 20, maxMentionHops: 8 } as const;

/** A channel's trigger on the wire: a `Cron` whose `message` is what it posts. */
function channelTrigger(trigger: Cron): JsonObject {
  if (!(trigger instanceof Cron)) throw new TypeError("A channel's trigger is a Cron");
  if (!trigger.message) throw new TypeError("A channel's Cron needs a message: it's what the schedule posts in the room.");
  return { kind: "cron", ...trigger.toWire() };
}

/**
 * A channel given a `Workspace` acts in that workspace's scope (a `user` beside it is refused); one given a
 * workspace id, in `user`'s; any other has one user.
 */
function channelScope(members: ChannelMemberInput[], user: CallOptions["user"], workspace?: string | Workspace): CallOptions["user"] {
  if (typeof workspace === "string") return user;
  if (workspace !== undefined) {
    if (user !== undefined) throw new TypeError("A channel in a Workspace lives in the workspace's scope; pass user with a workspace id instead.");
    return workspace._callScope();
  }
  const userMembers = members.filter((m): m is User => m instanceof User);
  if (!userMembers.length) return user;
  const member = userMembers[0];
  if (userMembers.some((t) => t !== member) || (user !== undefined && user !== member)) {
    throw new TypeError("A channel has one user: pass it once, as a member or as { user }.");
  }
  return member;
}

function sameMember(member: ChannelMember, spec: JsonObject): boolean {
  if (spec.agent_id) return member.agentId === spec.agent_id;
  if (spec.a2a_url) return member.a2aUrl === spec.a2a_url;
  if (spec.user_id) return member.type === "user" && member.userId === spec.user_id;
  return spec.user === true && member.type === "user";
}

/** A member on the wire; in a workspace a `User` is named (`{ user_id }`), since a workspace channel can hold several. */
async function wireMember(member: ChannelMemberInput, inWorkspace = false): Promise<JsonObject> {
  if (inWorkspace && member instanceof User) return { user_id: await member._userId() };
  if (member === "user" || member instanceof User) return { user: true };
  if (typeof member === "string" && /^https?:\/\//.test(member)) return { a2a_url: member };
  if (typeof member === "string") throw new TypeError(`A channel member string is "user" or an A2A URL, not ${JSON.stringify(member)}`);
  if (member instanceof Agent) return { agent_id: await agentId(member) };
  if (member instanceof A2AMember) {
    const headers = member.headers && Object.keys(member.headers).length ? { a2a_headers: { ...member.headers } } : {};
    return { a2a_url: member.url, ...headers, ...(member.name ? { name: member.name } : {}) };
  }
  const name = "name" in member && typeof member.name === "string" ? { name: member.name } : {};
  if ("agentId" in member) return { agent_id: member.agentId, ...name };
  if ("a2aUrl" in member) {
    const headers = member.headers && Object.keys(member.headers).length ? { a2a_headers: { ...member.headers } } : {};
    return { a2a_url: member.a2aUrl, ...headers, ...name };
  }
  if ("user" in member && member.user === true) return { user: true };
  throw new TypeError(`A channel member is an Agent, { agentId }, "user", a User or an A2A URL, not ${JSON.stringify(member)}`);
}

/** Whether `member` is the one `spec` (what `wireMember` sends) names. */
function matches(member: ChannelMember, spec: JsonObject): boolean {
  if (spec.agent_id) return member.agentId === spec.agent_id;
  if (spec.a2a_url) return member.a2aUrl === spec.a2a_url;
  if (spec.user_id) return member.type === "user" && member.userId === spec.user_id;
  return Boolean(spec.user) && member.type === "user";
}

function toAuthor(value: unknown): ChannelAuthor {
  const author = asObject(value);
  return { type: str(author.type) ?? "", id: str(author.id), name: str(author.name) };
}

export function toMessage(raw: JsonObject): ChannelMessage {
  const pinned = raw.pinned && typeof raw.pinned === "object" ? asObject(raw.pinned) : null;
  return {
    id: String(raw.id),
    channelId: String(raw.channel_id),
    author: toAuthor(raw.author),
    text: str(raw.text) ?? "",
    mentions: Array.isArray(raw.mentions) ? raw.mentions : [],
    createdAt: parseTime(raw.created_at),
    subscriptionId: str(raw.subscription_id),
    event: raw.event && typeof raw.event === "object" ? (raw.event as JsonObject) : null,
    attachments: toAttachments(raw.attachments),
    reactions: (Array.isArray(raw.reactions) ? (raw.reactions as JsonObject[]) : []).map(toReaction),
    threadId: str(raw.thread_id),
    alsoInChannel: raw.also_in_channel === true,
    replyCount: typeof raw.reply_count === "number" ? raw.reply_count : 0,
    lastReplyAt: parseTime(raw.last_reply_at),
    replyAuthors: (Array.isArray(raw.reply_authors) ? raw.reply_authors : []).map(toAuthor),
    following: raw.following === true,
    unreadReplies: typeof raw.unread_replies === "number" ? raw.unread_replies : 0,
    pinned: pinned ? { by: toAuthor(pinned.by), at: parseTime(pinned.at) } : null,
    channelName: str(raw.channel_name),
    membership: toMembership(raw),
    raw,
  };
}

function toThread(raw: JsonObject): ChannelThread {
  return {
    id: String(raw.id),
    channelId: String(raw.channel_id),
    channelName: str(raw.channel_name) ?? "",
    workspaceId: str(raw.workspace_id),
    parent: toMessage(asObject(raw.parent)),
    latestReply: raw.latest_reply ? toMessage(asObject(raw.latest_reply)) : null,
    replyCount: Number(raw.reply_count ?? 0),
    unreadCount: Number(raw.unread_count ?? 0),
    following: raw.following === true,
    lastReplyAt: parseTime(raw.last_reply_at),
    raw,
  };
}

function toSections(raw: JsonObject): ChannelSections {
  return {
    workspaceId: str(raw.workspace_id),
    version: Number(raw.version ?? 0),
    sections: asList(raw.sections).map((item) => {
      const s = asObject(item);
      return { id: String(s.id), name: str(s.name) ?? "", folded: s.folded === true, channelIds: asList(s.channel_ids).map(String) };
    }),
    folded: asList(raw.folded).map(String) as ChannelSectionsList[],
    updatedAt: parseTime(raw.updated_at),
    raw,
  };
}

function toBookmark(raw: JsonObject): ChannelBookmark {
  return {
    id: String(raw.id),
    channelId: String(raw.channel_id),
    title: str(raw.title) ?? "",
    url: str(raw.url) ?? "",
    by: toAuthor(raw.by),
    createdAt: parseTime(raw.created_at),
    raw,
  };
}

function shelfEntry(raw: JsonObject): Omit<ChannelFile, "file"> {
  return { messageId: String(raw.message_id), threadId: str(raw.thread_id), author: toAuthor(raw.author), createdAt: parseTime(raw.created_at) };
}

/** A message or its id. */
function messageRef(message: ChannelMessage | string): string {
  return encodeURIComponent(typeof message === "string" ? message : message.id);
}

/** The thread a message is in, or starts. */
function threadRef(message: ChannelMessage | string): string {
  return encodeURIComponent(typeof message === "string" ? message : message.threadId ?? message.id);
}

/** Paging back through a timeline or a thread. */
export interface MessagesOptions {
  after?: string;
  before?: string;
  newest?: boolean;
  waitS?: number;
  limit?: number;
}

/** A member's reaction as the query its removal takes. */
function asQuery(spec: JsonObject | undefined): Record<string, string | undefined> {
  if (!spec) return {};
  return { agent_id: str(spec.agent_id) ?? undefined, user_id: str(spec.user_id) ?? undefined, user: spec.user === true ? "true" : undefined };
}

// ── subscriptions ──────────────────────────────────────────────────────────

/**
 * What a subscription posts: an app's events through a connection (`new OnEvent(connection, event,
 * { filters })`, the same sources as an agent's event triggers), a webhook URL (`new OnWebhook(name)`:
 * each POST posts its body), or a NoClick event: its type (`"operation.failed"`, `"agent.job.update"`;
 * `*` patterns as webhooks take them) or `new OnPlatformEvent(type, { message })`, posted as the app
 * named for the type. A channel hears its user's events (one of your account's, every event), never
 * those of its own halting or its own agents' turns.
 */
export type SubscriptionSource = OnEvent | OnWebhook | OnPlatformEvent | string;

/** Who takes a turn on each event: nobody (`null`), every agent member (`"all"`), or these. */
export type SubscriptionWake = null | "all" | (Agent | string)[];

/** @internal `{ source, wake, filters? }` on the wire. */
export async function subscriptionWire(source: SubscriptionSource, wake: SubscriptionWake | undefined, filters: JsonObject | undefined): Promise<JsonObject> {
  let wire: JsonObject;
  if (typeof source === "string" && source) source = new OnPlatformEvent(source);
  if (source instanceof OnEvent || source instanceof OnWebhook || source instanceof OnPlatformEvent) {
    if (source.conversation !== null) throw new TypeError("A channel is one conversation: a subscription's source takes no conversation.");
    if (source instanceof OnEvent && filters !== undefined) throw new TypeError("An app event's filters go on the OnEvent itself.");
    if (source instanceof OnPlatformEvent) {
      if (source.filters !== null && filters !== undefined) throw new TypeError("Pass a NoClick event's filters once: on the OnPlatformEvent, or as filters.");
      filters = source.filters ?? filters;
      wire = { kind: "platform", type: source.type, ...compact({ message: source.message }) };
    } else wire = await source.toWire();
  } else throw new TypeError("A subscription's source is an OnEvent, an OnWebhook, an OnPlatformEvent or a NoClick event type");
  let wakeWire: null | "all" | string[];
  if (wake === undefined || wake === null) wakeWire = null;
  else if (wake === "all") wakeWire = "all";
  else if (Array.isArray(wake)) wakeWire = await Promise.all(wake.map(async (agent) => String(await agentId(agent))));
  else throw new TypeError('wake is null, "all" or a list of agents');
  return { source: wire, wake: wakeWire, ...compact({ filters }) };
}

/**
 * Something a channel, or a whole workspace's channels, hear: each event posts in the room as a
 * message from that app, and `wake` decides which agents take a turn. Hard stops still apply: an event
 * post counts as a post from outside the agents, so it wakes a halted channel as a person's post does,
 * and the budget still stops it. `status` is `error` (with `error`) while it can't hear anything, like
 * an app-event source whose connection isn't connected, a closed channel or an archived workspace.
 */
export class Subscription extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _from(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): Subscription {
    return new Subscription({ raw, client: init.client, user: init.user });
  }

  get id(): string {
    return this._field("id");
  }
  /** The channel it posts into (null for a workspace's). */
  get channelId(): string | null {
    return this._field("channel_id");
  }
  /** The workspace whose channels it posts into (null for a channel's). */
  get workspaceId(): string | null {
    return this._field("workspace_id");
  }
  /** A workspace's: `"all"` (channels made later too) or the channel ids. Null for a channel's. */
  get channels(): "all" | string[] | null {
    return this._field("channels");
  }
  /** The app whose path its events are POSTed to (`project.subscribe`); null for a channel's or a workspace's. */
  get projectId(): string | null {
    return this._field<string | null>("project_id") ?? null;
  }
  /** An app's: the path NoClick POSTs each event to, signed. */
  get path(): string | null {
    return this._field<string | null>("path") ?? null;
  }
  /** What it posts, as on the wire: `{ kind: "event" | "webhook" | "platform", ... }`. */
  get source(): JsonObject {
    return this._field("source");
  }
  get wake(): null | "all" | string[] {
    return this._field("wake");
  }
  get filters(): JsonObject {
    return this._field<JsonObject | null>("filters") ?? {};
  }
  get status(): "active" | "error" {
    return this._field("status");
  }
  get error(): string | null {
    return this._field("error");
  }
  /** A webhook source's URL: each POST to it posts in the room. */
  get url(): string | null {
    return this._field("url");
  }
  get lastEventAt(): Date | null {
    return parseTime(this._field("last_event_at"));
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  private get parent(): string {
    const workspace = this._known("workspace_id");
    const channel = this._known("channel_id");
    const project = this._known("project_id");
    if (typeof project === "string") return `/v1/projects/${project}`;
    return typeof channel === "string" ? `/v1/channels/${channel}` : `/v1/workspaces/${workspace}`;
  }

  private get base(): string {
    return `${this.parent}/subscriptions/${this._known("id")}`;
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", this.base);
  }

  /** Stop it: nothing more posts, and a webhook source's URL stops answering. */
  async unsubscribe(): Promise<void> {
    await this._request("DELETE", this.base);
  }

  /** An app's subscription's own: a channel's events are its messages, with nothing to list or test. */
  private appPath(what: string): string {
    const project = this._known("project_id");
    if (typeof project !== "string") {
      throw new TypeError(`${what} is an app's subscription's: a channel's events are its messages.`);
    }
    return `/v1/projects/${project}/subscriptions/${this._known("id")}`;
  }

  /**
   * An app's: each event sent to its path, newest first, with the body sent, its attempts and the app's last
   * answer. `status` narrows them (`"failed"`, or several).
   */
  async deliveries(options: { status?: SubscriptionDeliveryStatus | SubscriptionDeliveryStatus[]; limit?: number } = {}): Promise<SubscriptionDelivery[]> {
    const status = Array.isArray(options.status) ? options.status.join(",") : options.status;
    const rows = asList(await this._request("GET", `${this.appPath("deliveries()")}/deliveries`, {
      query: { status, limit: options.limit },
    })) as JsonObject[];
    return rows.map(toSubscriptionDelivery);
  }

  /**
   * An app's: POST a sample of its event to its path now and wait for the answer (10 seconds at most). The body
   * is what a real one gets, with `test: true` and placeholder values in the shape the event has reached your
   * account in (`connection.events()` shows it); until one has, `data` is empty and `text` says so. It's listed
   * among its deliveries and never tried again.
   */
  async test(): Promise<SubscriptionDelivery> {
    return toSubscriptionDelivery(asObject(await this._request("POST", `${this.appPath("test()")}/test`)));
  }
}

export type SubscriptionDeliveryStatus = "pending" | "retrying" | "delivered" | "failed";

/**
 * One event on its way to an app's path: `pending` (its first try), `retrying` (the app didn't answer 2xx; tried
 * again for three days), `delivered` (a 2xx) or `failed`. `requestBody` is exactly what was sent, every try the
 * same, its `id` this delivery's.
 */
export interface SubscriptionDelivery {
  id: string;
  subscriptionId: string;
  status: SubscriptionDeliveryStatus;
  /** A sample sent by `subscription.test()`, not a real event. */
  test: boolean;
  attempts: number;
  responseStatus: number | null;
  responseBody: string | null;
  requestBody: string;
  durationMs: number | null;
  error: string | null;
  nextRetryAt: Date | null;
  deliveredAt: Date | null;
  createdAt: Date | null;
  raw: JsonObject;
}

function toSubscriptionDelivery(raw: JsonObject): SubscriptionDelivery {
  return {
    id: String(raw.id),
    subscriptionId: String(raw.subscription_id),
    status: String(raw.status) as SubscriptionDeliveryStatus,
    test: raw.test === true,
    attempts: Number(raw.attempts ?? 0),
    responseStatus: typeof raw.response_status === "number" ? raw.response_status : null,
    responseBody: str(raw.response_body),
    requestBody: String(raw.request_body ?? ""),
    durationMs: typeof raw.duration_ms === "number" ? raw.duration_ms : null,
    error: str(raw.error),
    nextRetryAt: parseTime(raw.next_retry_at),
    deliveredAt: parseTime(raw.delivered_at),
    createdAt: parseTime(raw.created_at),
    raw,
  };
}

/** The threads list's filters as the API takes them. */
async function threadsQuery(options: { workspace?: string | Workspace; unread?: boolean }) {
  return { workspace_id: await refId(options.workspace), unread: options.unread ? "true" : undefined };
}

/** A channel list's filters as the API takes them. */
async function channelQuery(options: { status?: string; workspace?: string | Workspace; agent?: string | Agent; kind?: "channel" | "dm" }) {
  return { status: options.status, workspace_id: await refId(options.workspace), agent_id: await agentId(options.agent), kind: options.kind };
}

/** A channel's newest message, as a list shows it (its text cut to 200 characters). */
export interface ChannelLastMessage {
  id: string;
  text: string;
  author: ChannelAuthor;
  createdAt: Date | null;
}

function toLastMessage(raw: unknown): ChannelLastMessage | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as JsonObject;
  const author = asObject(row.author);
  return {
    id: String(row.id),
    text: str(row.text) ?? "",
    author: { type: str(author.type) ?? "", id: str(author.id), name: str(author.name) },
    createdAt: parseTime(row.created_at),
  };
}

export class Channel extends ApiObject {
  private _createWith: ({ name: string } & ChannelDefinition) | null = null;
  /** `fromName`'s workspace, where the name is looked up. */
  private _workspace: string | Workspace | undefined = undefined;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Open a channel. A `User` member means "open it for that user" (it is the call's user); in a
   * `workspace` the channel takes the workspace's scope and each `User` is a member, and its name is
   * unique among the workspace's open channels: there `allowExisting: true` returns the open channel
   * already called `name`, as it is (outside a workspace names aren't unique, so it takes a `workspace`).
   */
  static async create(name: string, options: ChannelCreateOptions & AllowExisting = {}): Promise<Channel> {
    const inWorkspace = options.workspace !== undefined;
    if (options.allowExisting && !inWorkspace) {
      throw new TypeError("Channel.create(..., { allowExisting: true }) needs workspace: only a workspace's channel names are unique");
    }
    const scope = resolveScope(channelScope(options.members ?? [], options.user, options.workspace));
    const members = options.members ? await Promise.all(options.members.map((m) => wireMember(m, inWorkspace))) : undefined;
    const raw = await createNamed("/v1/channels", compact({
        name,
        workspace_id: await refId(options.workspace),
        members,
        mode: options.mode,
        max_agent_turns: options.maxAgentTurns,
        max_mention_hops: options.maxMentionHops,
        budget_usd: options.budgetUsd,
        topic: options.topic,
      }), { allowExisting: options.allowExisting, user: scope, client: options.client });
    return new Channel({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the open channel called `name` for the current (or given) user, or in
   * `workspace` (where the name is unique among its open channels). Given fields, it gets the channel and
   * sets the ones you pass, on every run: on an existing channel an agent or A2A member your code no longer
   * lists is removed and a new one added, settings that differ get yours, and `triggers` are set like an
   * agent's. `createIfMissing` opens it when there's none; without it, a missing channel throws
   * `NotFound`. A field left out is never changed;
   * `budgetUsd: null` lifts the budget, and `null` puts `maxAgentTurns` or `maxMentionHops` back to its
   * default (20 and 8). Each run with fields is a write: set them at startup or in a setup script, and
   * take the bare `fromName` in request handlers.
   */
  static fromName(name: string, options: ChannelDefinition & { createIfMissing?: boolean } = {}): Channel {
    const user = channelScope(options.members ?? [], options.user, options.workspace);
    const channel = new Channel({ hints: { name }, client: options.client, user });
    channel._workspace = options.workspace;
    channel._creates = Boolean(options.createIfMissing);
    if (channel._creates || givesFields(options, ["workspace"])) channel._createWith = { ...options, name };
    return channel;
  }

  /**
   * The current user's channels (the account's own outside `asUser`, or those `userFilter` covers), at
   * most `limit`; `workspace` keeps one workspace's, `agent` the ones that agent is a member of.
   */
  static async list(
    options: ReadOptions & { status?: "open" | "closed"; limit?: number; workspace?: string | Workspace; agent?: string | Agent; kind?: "channel" | "dm" } = {},
  ): Promise<Channel[]> {
    return await listAll(
      { ...options, path: "/v1/channels", query: await channelQuery(options) },
      (raw, user) => new Channel({ raw, client: options.client, user }),
    );
  }

  /** One page of channels; pass `nextCursor` back as `cursor`. */
  static async listPage(
    options: ReadOptions & PageOptions & { status?: "open" | "closed"; workspace?: string | Workspace; agent?: string | Agent; kind?: "channel" | "dm" } = {},
  ): Promise<Page<Channel>> {
    return await listPage(
      { ...options, path: "/v1/channels", query: await channelQuery(options) },
      (raw, user) => new Channel({ raw, client: options.client, user }),
    );
  }

  /**
   * The DM between you and one other person of a `workspace` (a workspace of your account, or one you joined),
   * opened the first time: `"account"` names the account's owner (from a person in it), else that person's user
   * (a `User` or their user id). Only its two people read it.
   */
  static async dm(withWhom: User | string, options: CallOptions & { workspace: string | Workspace }): Promise<Channel> {
    const member: JsonObject = withWhom === "account" ? { account: true } : { user_id: withWhom instanceof User ? await withWhom._userId() : withWhom };
    const scope = resolveScope(channelScope([], options.user, options.workspace));
    const raw = await createNamed("/v1/channels", { kind: "dm", workspace_id: await refId(options.workspace), members: [member] }, {
      user: scope,
      client: options.client,
    });
    return new Channel({ raw, client: options.client, user: scope });
  }

  /**
   * The threads you follow across your channels (the account's own outside `asUser`), newest reply first, at most
   * `limit`; `unread` keeps those with replies you haven't read, `workspace` one workspace's.
   */
  static async threads(
    options: CallOptions & { workspace?: string | Workspace; unread?: boolean; limit?: number } = {},
  ): Promise<ChannelThread[]> {
    return await listAll({ ...options, path: "/v1/channels/threads", query: await threadsQuery(options) }, toThread);
  }

  /** One page of `threads`; pass `nextCursor` back as `cursor`. */
  static async threadsPage(
    options: CallOptions & PageOptions & { workspace?: string | Workspace; unread?: boolean } = {},
  ): Promise<Page<ChannelThread>> {
    return await listPage({ ...options, path: "/v1/channels/threads", query: await threadsQuery(options) }, toThread);
  }

  /**
   * Your own sections of a workspace's channels (`workspace` omitted: your channels in no workspace), as a sidebar
   * groups them, and which built-in lists are folded. Version 0 with no sections until the first save.
   */
  static async sections(options: CallOptions & { workspace?: string | Workspace } = {}): Promise<ChannelSections> {
    const raw = await resolveClient(options.client).request("GET", "/v1/channels/sections", {
      query: { workspace_id: await refId(options.workspace) },
      user: options.user,
    });
    return toSections(asObject(raw));
  }

  /**
   * Save your sections of a workspace's channels, replacing them whole. `version` is the one they were read at: a save
   * made since wins, and this one throws `Conflict` (its `version` is the one kept), so read them again and make the
   * change on that.
   */
  static async saveSections(
    layout: { version: number; sections: ChannelSection[]; folded?: ChannelSectionsList[] },
    options: CallOptions & { workspace?: string | Workspace } = {},
  ): Promise<ChannelSections> {
    const raw = await resolveClient(options.client).request("PUT", "/v1/channels/sections", {
      json: {
        workspace_id: await refId(options.workspace),
        version: layout.version,
        sections: layout.sections.map((s) => ({ id: s.id, name: s.name, folded: s.folded, channel_ids: s.channelIds })),
        folded: layout.folded ?? [],
      },
      user: options.user,
    });
    return toSections(asObject(raw));
  }

  static fromId(channelId: string, options: CallOptions = {}): Channel {
    return new Channel({ hints: { id: channelId }, client: options.client, user: options.user });
  }

  static async get(channelId: string, options: CallOptions = {}): Promise<Channel> {
    return await Channel.fromId(channelId, options).hydrate();
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** One line on what the channel is for. */
  get topic(): string {
    return this._field<string | null>("topic") ?? "";
  }
  get mode(): string | null {
    return this._field("mode");
  }
  /**
   * Messages since you last read it (`markRead`; your own posts count as read): your account's read point, or as a
   * person in a workspace, your own (0 in a channel you aren't in).
   */
  get unreadCount(): number {
    return this._field<number | null>("unread_count") ?? 0;
  }
  /** Whether you starred it (`star`): yours alone, never shown to anyone else. */
  get starred(): boolean {
    return this._field<boolean | null>("starred") === true;
  }
  /** Whether you muted it (`mute`): unread for you only for what @mentions you, and a space's NoClick alerts you then. */
  get muted(): boolean {
    return this._field<boolean | null>("muted") === true;
  }
  /**
   * Messages since you last read it that @mention you by name, as a person in a workspace (the account is never
   * mentioned): while it's muted, its `unreadCount`.
   */
  get mentionCount(): number {
    return this._field<number | null>("mention_count") ?? 0;
  }
  /** `channel`, or `dm`: a workspace's direct messages between two people. */
  get kind(): "channel" | "dm" {
    return this._field<"channel" | "dm" | null>("kind") ?? "channel";
  }
  /** Its newest message, when a read returns it (lists and gets do). */
  get lastMessage(): ChannelLastMessage | null {
    return toLastMessage(this._field("last_message"));
  }
  /** Where the NoClick app opens it (one of your account's own; `null` for a user's). */
  get appUrl(): string | null {
    return this._field("app_url");
  }
  /** Why a halted channel stopped (it wakes when a person posts). */
  get haltReason(): string | null {
    return this._field("halt_reason");
  }
  /** How many turns its agents may take in a row before a person posts again. */
  get maxAgentTurns(): number | null {
    return this._field("max_agent_turns");
  }
  /** What its agents' turns may spend, in US dollars. */
  get budgetUsd(): number | null {
    return this._field("budget_usd");
  }
  get status(): string | null {
    return this._field("status");
  }
  get members(): ChannelMember[] {
    return (this._field<JsonObject[] | null>("members") ?? []).map(toMember);
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  /** The workspace it lives in (null for a channel on its own). */
  get workspaceId(): string | null {
    return this._field("workspace_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  /** Its path once its id is known (a channel reached by name loads first). */
  private async path(): Promise<string> {
    const id = this._known("id") ?? (await this._ensure()).id;
    return `/v1/channels/${id}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/channels/${id}`);
    const name = String(this._hints.name);
    const workspaceId = await refId(this._workspace);
    const rows = (asList(await this._request("GET", "/v1/channels", { query: { name, status: "open", workspace_id: workspaceId } })) as JsonObject[])
      .filter((row) => row.name === name && row.status !== "closed");
    if (rows.length) return await this.converge(rows[0]);
    const definition = this._createWith;
    if (!definition || !this._creates) {
      throw new NotFound(`No open channel is named "${name}".`, {
        nextStep: "Open it with Channel.create(...) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    const inWorkspace = workspaceId !== undefined;
    const members = await Promise.all(
      (definition.members ?? []).filter((m) => inWorkspace || !(m instanceof User)).map((m) => wireMember(m, inWorkspace)),
    );
    const json = compact({
      name,
      workspace_id: workspaceId,
      members,
      mode: definition.mode,
      max_agent_turns: definition.maxAgentTurns,
      max_mention_hops: definition.maxMentionHops,
      budget_usd: definition.budgetUsd,
      topic: definition.topic,
      triggers: definition.triggers?.map(channelTrigger),
    });
    try {
      return await this._request<JsonObject>("POST", "/v1/channels", { json });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // opened concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/channels/${err.existingId}`));
    }
  }

  /** Set the fields `fromName` was given on an existing channel. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    const definition = this._createWith;
    if (!definition) return raw;
    const id = String(raw.id);
    const settings: JsonObject = {
      topic: definition.topic,
      mode: definition.mode,
      max_agent_turns: definition.maxAgentTurns === null ? DEFAULT_STOPS.maxAgentTurns : definition.maxAgentTurns,
      max_mention_hops: definition.maxMentionHops === null ? DEFAULT_STOPS.maxMentionHops : definition.maxMentionHops,
      budget_usd: definition.budgetUsd,
    };
    const changes: JsonObject = {};
    for (const key of CONVERGED) {
      if (settings[key] !== undefined && JSON.stringify(raw[key] ?? null) !== JSON.stringify(settings[key])) changes[key] = settings[key];
    }
    let current = Object.keys(changes).length ? await this._request<JsonObject>("PATCH", `/v1/channels/${id}`, { json: changes }) : raw;
    let changed = false;
    if (definition.members) {
      // In a workspace its users are members like its agents; elsewhere the user is the channel's own.
      const inWorkspace = this._workspace !== undefined;
      const wanted = await Promise.all(
        definition.members.filter((m) => (inWorkspace || !(m instanceof User)) && m !== "user").map((m) => wireMember(m, inWorkspace)),
      );
      const have = (Array.isArray(current.members) ? (current.members as JsonObject[]) : []).map(toMember);
      const managed = new Set(inWorkspace ? ["agent", "a2a", "user"] : ["agent", "a2a"]);
      for (const member of have) {
        if (managed.has(String(member.type)) && !wanted.some((spec) => sameMember(member, spec))) {
          await this._request("DELETE", `/v1/channels/${id}/members/${encodeURIComponent(member.id)}`);
          changed = true;
        }
      }
      for (const spec of wanted) {
        if (!have.some((member) => sameMember(member, spec))) {
          await this._request("POST", `/v1/channels/${id}/members`, { json: spec });
          changed = true;
        }
      }
    }
    if (definition.triggers) {
      const wanted = new Map(definition.triggers.map(channelTrigger).map((t) => [triggerKey(t), t]));
      const rows = asList(await this._request("GET", `/v1/channels/${id}/triggers`)) as JsonObject[];
      const have = new Map(rows.map((r) => [triggerKey({ kind: r.kind, ...asObject(r.spec) }), r]));
      for (const [key, row] of have) if (!wanted.has(key)) await this._request("DELETE", `/v1/channels/${id}/triggers/${row.id}`);
      for (const [key, json] of wanted) if (!have.has(key)) await this._request("POST", `/v1/channels/${id}/triggers`, { json });
    }
    if (changed) current = await this._request<JsonObject>("GET", `/v1/channels/${id}`);
    return current;
  }

  /** Its schedules: each `Cron` that posts in the room, with its `nextRun`. */
  async triggers(): Promise<AgentTrigger[]> {
    return (asList(await this._request("GET", `${await this.path()}/triggers`)) as JsonObject[]).map(toAgentTrigger);
  }

  /**
   * Post `trigger.message` in the room on the `Cron`'s schedule, as your account, waking whom a
   * person's post would (up to 20). On a channel whose `fromName(name, { triggers })` sets its schedules,
   * that code sets the list instead, and removes one added here the next time it runs.
   */
  async addTrigger(trigger: Cron): Promise<AgentTrigger> {
    const json = channelTrigger(trigger);
    return toAgentTrigger(asObject(await this._request("POST", `${await this.path()}/triggers`, { json })));
  }

  /**
   * Remove a schedule: an `AgentTrigger` (or its id), or the `Cron` you added
   * (`NotFound` if the channel has none like it).
   */
  async removeTrigger(trigger: AgentTrigger | string | Cron): Promise<void> {
    const path = await this.path();
    let triggerId: string;
    if (typeof trigger === "string") triggerId = trigger;
    else if (trigger instanceof Cron) {
      const wanted = triggerKey(channelTrigger(trigger));
      const match = (await this.triggers()).find((t) => triggerKey({ kind: t.kind, ...t.spec }) === wanted);
      if (!match) {
        throw new NotFound("The channel has no schedule like that.", {
          nextStep: "List them with channel.triggers() and remove one of those.",
          details: { channel_id: this._known("id") ?? null },
        });
      }
      triggerId = match.id;
    } else triggerId = trigger.id;
    await this._request("DELETE", `${path}/triggers/${triggerId}`);
  }

  /**
   * Change an open channel's name, topic, mode or hard stops; what's left out stays (`budgetUsd: null` lifts the
   * budget). A workspace's open channels each have their own name: a taken one raises `Conflict` with `existingId`.
   */
  async update(changes: { name?: string; topic?: string; mode?: "mentions" | "all"; maxAgentTurns?: number; maxMentionHops?: number; budgetUsd?: number | null }): Promise<this> {
    this._raw = await this._request<JsonObject>("PATCH", await this.path(), {
      json: defined({
        name: changes.name,
        topic: changes.topic,
        mode: changes.mode,
        max_agent_turns: changes.maxAgentTurns,
        max_mention_hops: changes.maxMentionHops,
        budget_usd: changes.budgetUsd,
      }),
    });
    return this;
  }

  /**
   * Store a file to post with a message, kept as an account file capped as those are: 10 MB an image
   * (JPEG, PNG, WebP or GIF), 15 MB a document, 20 MB audio or video. A file posts once.
   */
  async upload(file: FileInput, options: UploadOptions = {}): Promise<Attachment> {
    return uploadFile((method, path, init) => this._request(method, path, init), `${await this.path()}/attachments`, file, options);
  }

  /**
   * Post a message (as the account, the user, or one of your agents). `files` are attachments from
   * `upload` (or their ids), at most 100; a message with files may say nothing. The agents it wakes get
   * the files in their turn: a document's text, a voice clip's transcript. `thread` posts it as a reply in
   * that message's thread (a reply: the thread it's in), and `alsoInChannel` in the main timeline too.
   * `@channel`, `@here` or `@everyone` wakes every agent in the channel.
   */
  async post(
    text: string,
    options: { as?: ChannelPostAs; files?: (Attachment | string)[]; thread?: ChannelMessage | string; alsoInChannel?: boolean } = {},
  ): Promise<ChannelMessage> {
    const as = options.as === undefined ? undefined : await wireMember(options.as, await this.namesUsers(options.as));
    const attachments = attachmentIds(options.files);
    const threadId = options.thread === undefined ? undefined : typeof options.thread === "string" ? options.thread : options.thread.id;
    const raw = await this._request("POST", `${await this.path()}/messages`, {
      json: compact({ text, as, attachments, thread_id: threadId, also_in_channel: options.alsoInChannel || undefined }),
    });
    return toMessage(asObject(raw));
  }

  /**
   * Reply in `message`'s thread: it stays out of the main timeline unless `alsoInChannel`. The agents it wakes
   * answer in the thread. You follow the thread, read through your reply.
   */
  async reply(
    message: ChannelMessage | string,
    text: string,
    options: { as?: ChannelPostAs; files?: (Attachment | string)[]; alsoInChannel?: boolean } = {},
  ): Promise<ChannelMessage> {
    return await this.post(text, { ...options, thread: message });
  }

  /**
   * The main timeline oldest first (top-level messages, and replies also sent to it): after `after` (a message id),
   * where `waitS` holds the request until something arrives or the wait runs out; or the `limit` just `before` one;
   * or the `newest`. A thread's replies are read with `replies`.
   */
  async messages(options: MessagesOptions = {}): Promise<ChannelMessage[]> {
    return (await this.messagesPage(options)).data;
  }

  /** A page of `messages`; reading back (`before` or `newest`), `nextCursor` is the next `before` while older remain. */
  async messagesPage(options: MessagesOptions = {}): Promise<Page<ChannelMessage>> {
    return await this.readMessages(`${await this.path()}/messages`, options);
  }

  /** `message`'s thread, oldest first, read as `messages` reads the timeline. */
  async replies(message: ChannelMessage | string, options: MessagesOptions = {}): Promise<ChannelMessage[]> {
    return (await this.repliesPage(message, options)).data;
  }

  /** A page of `replies`; reading back (`before` or `newest`), `nextCursor` is the next `before` while older remain. */
  async repliesPage(message: ChannelMessage | string, options: MessagesOptions = {}): Promise<Page<ChannelMessage>> {
    return await this.readMessages(`${await this.path()}/messages/${threadRef(message)}/replies`, options);
  }

  private async readMessages(path: string, options: MessagesOptions): Promise<Page<ChannelMessage>> {
    if ([options.after, options.before, options.newest].filter(Boolean).length > 1) throw new TypeError("Pass one of after, before or newest.");
    const page = asObject(
      await this._request("GET", path, {
        query: { after: options.after, before: options.before, newest: options.newest ? "true" : undefined, wait_s: options.waitS, limit: options.limit },
        timeoutMs: options.waitS ? (options.waitS + 15) * 1000 : undefined,
      })
    );
    return { data: (asList(page) as JsonObject[]).map(toMessage), nextCursor: str(page.next_cursor) };
  }

  /** One message as it now is, with its reactions, its thread's counts and its pin. */
  async message(messageId: string): Promise<ChannelMessage> {
    return toMessage(asObject(await this._request("GET", `${await this.path()}/messages/${encodeURIComponent(messageId)}`)));
  }

  /** Mark `message`'s thread read for you, through `reply` or its newest; returns the message. */
  async markThreadRead(message: ChannelMessage | string, reply?: ChannelMessage | string): Promise<ChannelMessage> {
    const replyId = reply === undefined ? undefined : typeof reply === "string" ? reply : reply.id;
    const raw = await this._request("POST", `${await this.path()}/messages/${threadRef(message)}/read`, { json: compact({ reply_id: replyId }) });
    return toMessage(asObject(raw));
  }

  /** Follow `message`'s thread (read through its newest reply now); returns the message. */
  async follow(message: ChannelMessage | string): Promise<ChannelMessage> {
    return toMessage(asObject(await this._request("POST", `${await this.path()}/messages/${threadRef(message)}/follow`)));
  }

  /** Stop following `message`'s thread, until you post in it or are @mentioned there; returns the message. */
  async unfollow(message: ChannelMessage | string): Promise<ChannelMessage> {
    return toMessage(asObject(await this._request("DELETE", `${await this.path()}/messages/${threadRef(message)}/follow`)));
  }

  /**
   * Say you connected the account an agent's `message` asks for (the id of one of its `event.asks` of kind
   * `connect`): the ask names you from now on, the first to say so kept. Refused until it's connected; returns the
   * message.
   */
  async askConnected(message: ChannelMessage | string, askId: string): Promise<ChannelMessage> {
    const path = `${await this.path()}/messages/${messageRef(message)}/asks/${encodeURIComponent(askId)}/connected`;
    return toMessage(asObject(await this._request("POST", path)));
  }

  /** Pin a message, as your account or `as` a member (at most 100 a channel); the room is told once. */
  async pin(message: ChannelMessage | string, options: { as?: ChannelPostAs } = {}): Promise<ChannelMessage> {
    const as = options.as === undefined ? undefined : await wireMember(options.as, await this.namesUsers(options.as));
    return toMessage(asObject(await this._request("POST", `${await this.path()}/messages/${messageRef(message)}/pin`, { json: compact({ as }) })));
  }

  /** Unpin a message; one that isn't pinned changes nothing. */
  async unpin(message: ChannelMessage | string): Promise<ChannelMessage> {
    return toMessage(asObject(await this._request("DELETE", `${await this.path()}/messages/${messageRef(message)}/pin`)));
  }

  /** Its pinned messages, newest pin first. */
  async pins(): Promise<ChannelPin[]> {
    const rows = asList(await this._request("GET", `${await this.path()}/pins`)) as JsonObject[];
    return rows.map((raw) => ({ message: toMessage(asObject(raw.message)), by: toAuthor(raw.by), at: parseTime(raw.at) }));
  }

  /** Its saved links, in the order they were added. */
  async bookmarks(): Promise<ChannelBookmark[]> {
    return (asList(await this._request("GET", `${await this.path()}/bookmarks`)) as JsonObject[]).map(toBookmark);
  }

  /** Save a link (at most 100 a channel); without a `title` the address's host names it. */
  async addBookmark(bookmark: { url: string; title?: string; as?: ChannelPostAs }): Promise<ChannelBookmark> {
    const as = bookmark.as === undefined ? undefined : await wireMember(bookmark.as, await this.namesUsers(bookmark.as));
    const raw = await this._request("POST", `${await this.path()}/bookmarks`, { json: compact({ url: bookmark.url, title: bookmark.title, as }) });
    return toBookmark(asObject(raw));
  }

  /** Change a bookmark's address or title (an empty title: named by its host again). */
  async updateBookmark(bookmark: ChannelBookmark | string, changes: { url?: string; title?: string }): Promise<ChannelBookmark> {
    const id = typeof bookmark === "string" ? bookmark : bookmark.id;
    const raw = await this._request("PATCH", `${await this.path()}/bookmarks/${encodeURIComponent(id)}`, { json: defined({ url: changes.url, title: changes.title }) });
    return toBookmark(asObject(raw));
  }

  async removeBookmark(bookmark: ChannelBookmark | string): Promise<void> {
    const id = typeof bookmark === "string" ? bookmark : bookmark.id;
    await this._request("DELETE", `${await this.path()}/bookmarks/${encodeURIComponent(id)}`);
  }

  /** The files posted in it and its threads, newest first; `q` matches their names. Pass `nextCursor` back as `cursor`. */
  async files(options: { q?: string } & PageOptions = {}): Promise<Page<ChannelFile>> {
    const page = asObject(await this._request("GET", `${await this.path()}/files`, { query: { q: options.q, limit: options.limit, cursor: options.cursor ?? undefined } }));
    const data = (asList(page) as JsonObject[]).map((raw) => ({ ...shelfEntry(raw), file: toAttachments([raw.file])[0] }));
    return { data, nextCursor: str(page.next_cursor) };
  }

  /** The web addresses posted in it and its threads, newest first; `q` matches the address or its text. */
  async links(options: { q?: string } & PageOptions = {}): Promise<Page<ChannelLink>> {
    const page = asObject(await this._request("GET", `${await this.path()}/links`, { query: { q: options.q, limit: options.limit, cursor: options.cursor ?? undefined } }));
    const data = (asList(page) as JsonObject[]).map((raw) => ({
      ...shelfEntry(raw), url: str(raw.url) ?? "", title: str(raw.title), domain: str(raw.domain) ?? "",
    }));
    return { data, nextCursor: str(page.next_cursor) };
  }

  /** React with one emoji, as your account or `as` a member; once per emoji each (a message holds 20 different). */
  async react(message: ChannelMessage | string, emoji: string, options: { as?: ChannelPostAs } = {}): Promise<ChannelMessage> {
    const as = options.as === undefined ? undefined : await wireMember(options.as, await this.namesUsers(options.as));
    const id = typeof message === "string" ? message : message.id;
    const raw = await this._request("POST", `${await this.path()}/messages/${encodeURIComponent(id)}/reactions`, { json: compact({ emoji, as }) });
    return toMessage(asObject(raw));
  }

  /** Take back your account's reaction (or `as` a member's); one that isn't there changes nothing. */
  async unreact(message: ChannelMessage | string, emoji: string, options: { as?: ChannelPostAs } = {}): Promise<ChannelMessage> {
    const as = options.as === undefined ? undefined : await wireMember(options.as, await this.namesUsers(options.as));
    const id = typeof message === "string" ? message : message.id;
    const raw = await this._request("DELETE", `${await this.path()}/messages/${encodeURIComponent(id)}/reactions/${encodeURIComponent(emoji)}`, {
      query: asQuery(as),
    });
    return toMessage(asObject(raw));
  }

  /** Mark it read for your account, through `message` or its newest; `unreadCount` counts from there, never back. */
  async markRead(message?: ChannelMessage | string): Promise<this> {
    const messageId = message === undefined ? undefined : typeof message === "string" ? message : message.id;
    this._raw = asObject(await this._request("POST", `${await this.path()}/read`, { json: compact({ message_id: messageId }) }));
    return this;
  }

  /**
   * Say you're typing in the channel (`on`), or that you stopped: the other people reading it see so for a few
   * seconds, under the name the channel knows you by, and nothing is kept. Send it again every few seconds while keys
   * are pressed, and `false` once the message is sent or the box is cleared. For the account itself, or a person in one
   * of its workspaces; at most once a second per channel.
   */
  async typing(on = true): Promise<void> {
    await this._request("POST", `${await this.path()}/typing`, { json: { typing: on } });
  }

  /** @deprecated Use `stream`. */
  listen(options: { after?: string; waitS?: number; signal?: AbortSignal } = {}): AsyncGenerator<ChannelMessage> {
    return this.stream(options);
  }

  /**
   * Every message (from the start, or after `after`) as it arrives, until `signal` aborts; a halted
   * channel keeps it going, so `break` once you have what you need.
   */
  async *stream(options: { after?: string; waitS?: number; signal?: AbortSignal } = {}): AsyncGenerator<ChannelMessage> {
    let after = options.after;
    while (!options.signal?.aborted) {
      for (const message of await this.messages({ after, waitS: options.waitS ?? 30 })) {
        after = message.id;
        yield message;
      }
    }
  }

  /** Add an agent, the user or an A2A member; a workspace's channel takes the workspace's agents and users. */
  async add(member: ChannelMemberInput): Promise<ChannelMember> {
    const json = await wireMember(member, await this.namesUsers(member));
    return toMember(asObject(await this._request("POST", `${await this.path()}/members`, { json })));
  }

  /** @deprecated Use `add`. */
  async addMember(member: ChannelMemberInput): Promise<ChannelMember> {
    return await this.add(member);
  }

  /** Whether `member` is a `User` this channel names by id: one in a workspace's channel, which can hold several. */
  private async namesUsers(member: unknown): Promise<boolean> {
    if (!(member instanceof User)) return false;
    return this._workspace !== undefined || Boolean((await this._ensure()).workspace_id);
  }

  /** Remove a member: a `ChannelMember`, its id, or the agent, user or A2A member you added. */
  async remove(member: ChannelMemberInput | ChannelMember): Promise<void> {
    let memberId: string;
    if (typeof member === "object" && member !== null && "a2aHeaderNames" in member) memberId = member.id;
    else if (typeof member === "string" && !/^https?:\/\//.test(member) && member !== "user") memberId = member;
    else {
      const spec = await wireMember(member as ChannelMemberInput, await this.namesUsers(member));
      this._raw = await this._load();
      const found = this.members.find((m) => matches(m, spec));
      if (!found) throw new TypeError(`${JSON.stringify(spec)} is not a member of channel ${this._known("id")}`);
      memberId = found.id;
    }
    await this._request("DELETE", `${await this.path()}/members/${encodeURIComponent(memberId)}`);
  }

  /** @deprecated Use `remove`. */
  async removeMember(member: string | ChannelMember): Promise<void> {
    await this.remove(member);
  }

  /**
   * Post an app's events, a webhook's calls or NoClick's own events into the room, as messages from
   * that app. `wake`: nobody (the default; agents see the post on their next turn), `"all"` (every
   * agent member takes a turn) or some member agents. `filters` are dotted paths into a webhook's JSON
   * body or a NoClick event's `data` (an `OnEvent` carries its own). Up to 20 a channel.
   */
  async subscribe(source: SubscriptionSource, options: { wake?: SubscriptionWake; filters?: JsonObject } = {}): Promise<Subscription> {
    const json = await subscriptionWire(source, options.wake, options.filters);
    const raw = await this._request<JsonObject>("POST", `${await this.path()}/subscriptions`, { json });
    return Subscription._from(raw, { client: this._client, user: this._callScope() });
  }

  /** Its subscriptions, oldest first. */
  async subscriptions(): Promise<Subscription[]> {
    const rows = asList(await this._request("GET", `${await this.path()}/subscriptions`)) as JsonObject[];
    return rows.map((raw) => Subscription._from(raw, { client: this._client, user: this._callScope() }));
  }

  /**
   * Move the channel to the trash: its agents' turns there are canceled and what it hears stops, restorable for
   * 30 days with everything it held. Returns its `TrashItem`.
   */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this.path()), this);
  }

  /** Close the channel: no more posts or agent turns. */
  async close(): Promise<this> {
    const raw = asObject(await this._request("POST", `${await this.path()}/close`));
    this._raw = raw.id ? raw : { ...(this._raw ?? this._hints), status: "closed" };
    return this;
  }

  /**
   * Open a closed channel again, as it was: its members, its history and the events it heard (while its
   * subscriptions are still in the trash). A workspace's needs no other open channel with its name: `name` reopens it
   * under another.
   */
  async reopen(options: { name?: string } = {}): Promise<this> {
    this._raw = asObject(await this._request("POST", `${await this.path()}/reopen`, { json: compact({ name: options.name }) }));
    return this;
  }

  private async preference(path: "star" | "mute", on: boolean): Promise<this> {
    this._raw = asObject(await this._request(on ? "POST" : "DELETE", `${await this.path()}/${path}`));
    return this;
  }

  /** Star the channel for yourself alone (a person in a workspace: one you're in). */
  async star(): Promise<this> {
    return this.preference("star", true);
  }

  /** Take your star off the channel. */
  async unstar(): Promise<this> {
    return this.preference("star", false);
  }

  /** Mute the channel for yourself alone: unread only for what @mentions you, and a space's NoClick alerts you only then. */
  async mute(): Promise<this> {
    return this.preference("mute", true);
  }

  /** Unmute the channel. */
  async unmute(): Promise<this> {
    return this.preference("mute", false);
  }

  /**
   * Join the channel, as a person in its workspace who sees it (never a DM, nor a closed one): it keeps an entry that
   * you joined. In it already, nothing changes.
   */
  async join(): Promise<this> {
    this._raw = asObject(await this._request("POST", `${await this.path()}/join`));
    return this;
  }

  /** Leave the channel, as a person in its workspace (never a DM): it keeps an entry that you left. */
  async leave(): Promise<void> {
    await this._request("POST", `${await this.path()}/leave`);
  }
}
