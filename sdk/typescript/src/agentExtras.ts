/**
 * An agent's memory, workspace files, share link, live events and test runs.
 *
 *     const support = Agent.fromName("support");
 *     await support.memory.save("refunds", "Refund within 30 days of purchase.", { description: "Our refund rules" });
 *     const files = await support.workspace().files();
 *     const link = await support.share();
 *     for await (const event of support.stream("Where's my refund?", { conversation: "ticket-1841" })) console.log(event.type, event.text);
 *     const run = await (await support.rehearse("A customer asks for a refund on order 1841")).wait();
 */

import type { Agent, AgentReply, AgentStepKind, HarnessName, MessageSpace, MessageSubagent, MessageTrigger, MessageVia, ModelUsage, ReasoningLine } from "./agent.ts";
import type { MessageAuthor } from "./agentConversations.ts";
import type { Attachment } from "./attachment.ts";
import type { NoClick } from "./client.ts";
import { NotFound } from "./errors.ts";
import { ApiObject, asList, asObject, compact, num, paginate, parseTime, str } from "./object.ts";
import type { JsonObject, ObjectInit, Page, PageOptions } from "./object.ts";
import { registerResult } from "./operation.ts";
import { toExecResult } from "./sandbox.ts";
import type { ExecResult } from "./sandbox.ts";
import type { UserOption } from "./scope.ts";
import { TerminalConnection } from "./terminal.ts";
import type { TerminalConnectOptions } from "./terminal.ts";
import { toVolumeEntry } from "./volume.ts";
import type { VolumeEntry } from "./volume.ts";

// ── memory ─────────────────────────────────────────────────────────────────

/**
 * One named note in an agent's memory. `version` goes up with every save; pass the one you read
 * back to `save` or `delete` so you never overwrite a change the agent made since. `content` is
 * null in a listing (`read` loads it). `updatedBy` is `agent`, `api` or `console`.
 *
 * `conversation` is set on a conversation's checkpoint: a long conversation keeps its older
 * history folded into one entry, named `context.` and a hash, which its turns read in place of
 * that history. Read it to see what the agent carries forward; an edit wins over the next
 * summary, and deleting it forgets that history for good. The agent never sees it outside that
 * conversation.
 */
/** Who last wrote a memory entry: an agent's turn (which agent, in which conversation), a person in the app, or a key. */
export interface MemoryWriter {
  type: "agent" | "api" | "console" | null;
  agentId: string | null;
  agentName: string | null;
  conversation: string | null;
}

export interface MemoryEntry {
  name: string;
  description: string;
  content: string | null;
  version: number;
  updatedAt: Date | null;
  updatedBy: "agent" | "api" | "console" | null;
  /** Who last wrote it: for an agent, which one and in which of its conversations. */
  writtenBy: MemoryWriter;
  userId: string | null;
  conversation: string | null;
  raw: JsonObject;
}

function toMemoryWriter(value: unknown): MemoryWriter {
  const raw = value && typeof value === "object" ? (value as JsonObject) : {};
  return {
    type: str(raw.type) as MemoryWriter["type"],
    agentId: str(raw.agent_id),
    agentName: str(raw.agent_name),
    conversation: str(raw.conversation),
  };
}

/** @internal */
export function toMemoryEntry(raw: JsonObject): MemoryEntry {
  return {
    name: String(raw.name),
    description: str(raw.description) ?? "",
    content: str(raw.content),
    version: num(raw.version) ?? 0,
    updatedAt: parseTime(raw.updated_at),
    updatedBy: str(raw.updated_by) as MemoryEntry["updatedBy"],
    writtenBy: toMemoryWriter(raw.written_by),
    userId: str(raw.user_id),
    conversation: str(raw.conversation),
    raw,
  };
}

/**
 * One version of a memory entry, as it was saved. Every save keeps the version it replaces, so an
 * entry keeps its last 50 versions, the one it holds now (`current`) included; a conversation's
 * checkpoint keeps none. `content` is null in a listing (`getVersion` loads it), and `savedAt` is
 * when that version was saved.
 */
export interface MemoryEntryVersion {
  name: string;
  version: number;
  current: boolean;
  description: string;
  content: string | null;
  writtenBy: MemoryWriter;
  userId: string | null;
  savedAt: Date | null;
  raw: JsonObject;
}

/** @internal */
export function toMemoryEntryVersion(raw: JsonObject): MemoryEntryVersion {
  return {
    name: String(raw.name),
    version: num(raw.version) ?? 0,
    current: raw.current === true,
    description: str(raw.description) ?? "",
    content: str(raw.content),
    writtenBy: toMemoryWriter(raw.written_by),
    userId: str(raw.user_id),
    savedAt: parseTime(raw.saved_at),
    raw,
  };
}

/**
 * `agent.memory`: named notes the agent keeps across conversations. Every turn starts with each
 * entry's name and description; the agent reads a body when it needs one, and saves what it
 * learns. Your code can seed, read, correct and forget entries the same way.
 *
 * An account agent keeps two layers: entries saved outside `asUser` are the account's, read in
 * every user's conversations, and what it learns while talking to a user is that user's
 * alone. A user's own agent has one memory, the user's. The agent changes the account's entries
 * only in conversations your code has with it outside `asUser`, and only reads its memory when it
 * answers someone outside your account (an inbox's sender, a caller, a visitor to its share link).
 * A long conversation also keeps its checkpoint here, in that conversation's layer
 * (`MemoryEntry.conversation`).
 *
 * It's a `Memory` (its id is `agent.memoryId`) that goes with the agent: another agent of its
 * scope can read it too, with `memories: [agent.memory]`, and named memories (`Memory`) are
 * attached the same way.
 */
export class AgentMemory {
  private readonly agent: Agent;

  private constructor(agent: Agent) {
    this.agent = agent;
  }

  /** @internal */
  static _of(agent: Agent): AgentMemory {
    return new AgentMemory(agent);
  }

  private async call(method: string, suffix: string, user: UserOption, options: { query?: JsonObject; json?: unknown } = {}): Promise<unknown> {
    const raw = await this.agent._ensure();
    return await this.agent._request(method, `/v1/agents/${raw.id}/memory${suffix}`, {
      ...options,
      query: options.query as Record<string, string | number | undefined>,
      user: this.agent._talkScope(user),
    });
  }

  /** The entries of one layer (the account's outside `asUser`, else the user's), by name, without their content. */
  async list(options: { user?: UserOption } = {}): Promise<MemoryEntry[]> {
    return (asList(await this.call("GET", "", options.user)) as JsonObject[]).map(toMemoryEntry);
  }

  /**
   * Search what the agent remembers in a scope, the way the agent does (a user's entries and the
   * account's): entries whose name, description or content holds any of the query's words (`refund`
   * also finds `refunds`), or whose name or description holds the query; best first, with content
   * (10 unless `limit` says otherwise, at most 100).
   */
  async search(query: string, options: { limit?: number; user?: UserOption } = {}): Promise<MemoryEntry[]> {
    const rows = asList(await this.call("GET", "", options.user, { query: { q: query, limit: options.limit } })) as JsonObject[];
    return rows.map(toMemoryEntry);
  }

  /** One entry in full; a name with no entry throws `NotFound`. */
  async read(name: string, options: { user?: UserOption } = {}): Promise<MemoryEntry> {
    return toMemoryEntry(asObject(await this.call("GET", `/${encodeURIComponent(name)}`, options.user)));
  }

  /**
   * Write an entry, creating it if the name is new. `description` is the line the agent sees every
   * turn (required for a new entry, kept when omitted). With `version` the save only lands if the
   * entry is still at that version, else `Conflict`; without it, it replaces whatever is there.
   */
  async save(name: string, content: string, options: { description?: string; version?: number; user?: UserOption } = {}): Promise<MemoryEntry> {
    const json = compact({ content, description: options.description, version: options.version });
    return toMemoryEntry(asObject(await this.call("PUT", `/${encodeURIComponent(name)}`, options.user, { json })));
  }

  /** Forget an entry; with `version`, only if it is still at that version (else `Conflict`). */
  async delete(name: string, options: { version?: number; user?: UserOption } = {}): Promise<void> {
    await this.call("DELETE", `/${encodeURIComponent(name)}`, options.user, { query: { version: options.version } });
  }

  /**
   * An entry's versions, newest first: the one it holds now, then those kept from earlier saves (its
   * last 50 in all), without their content. A name with no entry throws `NotFound`.
   */
  async versions(name: string, options: { user?: UserOption } = {}): Promise<MemoryEntryVersion[]> {
    const rows = asList(await this.call("GET", `/${encodeURIComponent(name)}/versions`, options.user)) as JsonObject[];
    return rows.map(toMemoryEntryVersion);
  }

  /** One version of an entry, with its content; one it no longer keeps throws `NotFound`. */
  async getVersion(name: string, version: number, options: { user?: UserOption } = {}): Promise<MemoryEntryVersion> {
    return toMemoryEntryVersion(asObject(await this.call("GET", `/${encodeURIComponent(name)}/versions/${version}`, options.user)));
  }

  /**
   * Put an entry back as it was at `version`: a new version holding that one's content and
   * description, so the one it replaces is kept too.
   */
  async restore(name: string, version: number, options: { user?: UserOption } = {}): Promise<MemoryEntry> {
    return toMemoryEntry(asObject(await this.call("POST", `/${encodeURIComponent(name)}/versions/${version}/restore`, options.user)));
  }

  /** `list`, as `Memory` calls it. */
  async entries(options: { user?: UserOption } = {}): Promise<MemoryEntry[]> {
    return await this.list(options);
  }

  /** `delete`, as `Memory` calls it. */
  async forget(name: string, options: { version?: number; user?: UserOption } = {}): Promise<void> {
    await this.delete(name, options);
  }

  /** @internal The id of this agent's own memory, to attach it to another agent. */
  async _memoryId(): Promise<string> {
    return String((await this.agent._ensure()).memory_id);
  }
}

// ── workspace ──────────────────────────────────────────────────────────────

/** A file in a conversation's workspace; `url` downloads it without a key for about an hour. */
export interface WorkspaceFile {
  /** Relative to `/workspace`. */
  path: string;
  sizeBytes: number;
  modifiedAt: Date | null;
  url: string | null;
  raw: JsonObject;
}

function toWorkspaceFile(raw: JsonObject): WorkspaceFile {
  return { path: String(raw.path), sizeBytes: num(raw.size_bytes) ?? 0, modifiedAt: parseTime(raw.modified_at), url: str(raw.url), raw };
}

/**
 * The files an agent works on (`agent.workspace()`): what it writes with its shell or its tools, and what you put
 * there for it. An agent has one `/workspace`, which every turn sees whoever it answers, and a clear or a resume
 * leaves as it is; an account agent's user has their own. (A `Workspace` is something else: channels and their
 * members.)
 */
export class AgentWorkspace {
  /** The conversation it was named by, if any: accepted and ignored, since an agent has one workspace. */
  readonly conversation: string | undefined;
  private readonly agent: Agent;
  private readonly user: UserOption;

  private constructor(agent: Agent, conversation: string | undefined, user: UserOption) {
    this.agent = agent;
    this.conversation = conversation;
    this.user = user;
  }

  /** @internal */
  static _of(agent: Agent, conversation: string | undefined, user: UserOption): AgentWorkspace {
    return new AgentWorkspace(agent, conversation, user);
  }

  private async call<T>(method: string, suffix: string, options: { query?: Record<string, string | number | undefined>; body?: string | Uint8Array; responseType?: "bytes" } = {}): Promise<T> {
    const raw = await this.agent._ensure();
    return await this.agent._request<T>(method, `/v1/agents/${raw.id}/workspace${suffix}`, {
      ...options,
      query: { conversation: this.conversation, ...(options.query ?? {}) },
      user: this.agent._talkScope(this.user),
    });
  }

  /** Every file in the workspace, each with a download `url` (empty until the agent writes one). */
  async files(): Promise<WorkspaceFile[]> {
    return (asList(await this.call("GET", "")) as JsonObject[]).map(toWorkspaceFile);
  }

  /** Read one file's bytes; a missing file throws `NotFound`. */
  async read(path: string): Promise<Uint8Array> {
    return await this.call<Uint8Array>("GET", "/files", { query: { path }, responseType: "bytes" });
  }

  /**
   * Put a file in the workspace (text as UTF-8), replacing one at that path; at most 100 MB. A coding
   * harness's sandbox stays up between turns and sees it once it starts again.
   */
  async write(path: string, data: string | Uint8Array): Promise<WorkspaceFile> {
    return toWorkspaceFile(asObject(await this.call("PUT", "/files", { query: { path }, body: data })));
  }

  /** Delete one file from the workspace; a missing file does nothing. */
  async delete(path: string): Promise<void> {
    await this.call("DELETE", "/files", { query: { path } });
  }

  /** A link that downloads one file without a key, for `expiresInS` seconds (an hour by default, a day at most). */
  async url(path: string, options: { expiresInS?: number } = {}): Promise<string> {
    return String(asObject(await this.call("GET", "/url", { query: { path, expires_in_s: options.expiresInS } })).url);
  }
}

// ── sandbox ────────────────────────────────────────────────────────────────

/** Where a conversation's agent works: a sandbox of the conversation's own, an agent's `machine`, or an app's `live` container. */
export type SandboxPlace = "sandbox" | "machine" | "live";

/**
 * The machine a conversation's agent works on, as it stands. A coding agent's sandbox starts with a turn and stops a
 * minute after its last; an `sdk` agent's shell lives only during a turn, so it reads `stopped`. `cpu` and `memoryMb`
 * are what it reserved (null while stopped), `usdPerHour` what an hour of it costs, `spentUsdToday` what its sandbox
 * charged since midnight UTC (null where the conversation has no sandbox of its own), and `workspace` the folder kept
 * between its runs.
 */
export interface ConversationSandbox {
  agentId: string;
  conversation: string;
  harness: HarnessName;
  place: SandboxPlace;
  status: "running" | "stopped";
  startedAt: Date | null;
  cpu: number | null;
  memoryMb: number | null;
  region: string | null;
  usdPerHour: number | null;
  spentUsdToday: number | null;
  machineId: string | null;
  projectId: string | null;
  workspace: string | null;
  raw: JsonObject;
}

function toConversationSandbox(raw: JsonObject): ConversationSandbox {
  return {
    agentId: String(raw.agent_id), conversation: String(raw.conversation), harness: raw.harness as HarnessName,
    place: raw.place as SandboxPlace, status: raw.status === "running" ? "running" : "stopped",
    startedAt: parseTime(raw.started_at), cpu: num(raw.cpu), memoryMb: num(raw.memory_mb), region: str(raw.region),
    usdPerHour: num(raw.usd_per_hour), spentUsdToday: num(raw.spent_usd_today), machineId: str(raw.machine_id),
    projectId: str(raw.project_id), workspace: str(raw.workspace), raw,
  };
}

/** One page of a sandbox's folder; `source` says where it was read: the running `sandbox`, or what its `workspace` kept. */
export interface SandboxFilesPage extends Page<VolumeEntry> {
  source: "sandbox" | "workspace";
}

export interface SandboxFilesOptions {
  /** Everything below the folder, not just what's in it (git's objects left out unless listed by their path). */
  recursive?: boolean;
}

/**
 * The machine an agent works on (`agent.sandbox()`): what it is and costs, its files and your own commands on it,
 * beside the agent's work. An agent has one, whoever it answers. While its sandbox runs, its files are read there with every
 * secret it holds taken out; while it's stopped, from what its workspace kept. Files and commands need the account's
 * owner: signed in, or its secret key with the `agents:terminal` scope. Sends nothing yet.
 *
 *     const machine = coder.sandbox();
 *     if ((await machine.get()).status === "running") console.log((await machine.exec("git status --short")).stdout);
 */
export class AgentSandbox {
  /** The conversation it was named by; none reads it through the agent's session. */
  readonly conversation: string | undefined;
  private readonly agent: Agent;
  private readonly user: UserOption;

  private constructor(agent: Agent, conversation: string | undefined, user: UserOption) {
    this.agent = agent;
    this.conversation = conversation;
    this.user = user;
  }

  /** @internal */
  static _of(agent: Agent, conversation: string | undefined, user: UserOption): AgentSandbox {
    return new AgentSandbox(agent, conversation, user);
  }

  private async route(suffix = ""): Promise<string> {
    const raw = await this.agent._ensure();
    const conversation = this.conversation ?? (await this.agent.session({ user: this.user }))?.conversation;
    if (!conversation) throw new NotFound("It has no session yet, so nothing has run on its sandbox: message it first.");
    return `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}/sandbox${suffix}`;
  }

  /** Where it runs, whether it's running and since when, what it reserved and costs. */
  async get(): Promise<ConversationSandbox> {
    return toConversationSandbox(asObject(await this.agent._request("GET", await this.route(), { user: this.agent._talkScope(this.user) })));
  }

  private listQuery(path: string, options: SandboxFilesOptions) {
    return { path, view: "list", recursive: options.recursive ? "true" : undefined };
  }

  /**
   * What's in the folder at `path` (absolute; its workspace by default), a folder before what's in it, fetched page by
   * page. A path that doesn't exist throws `NotFound`.
   */
  async files(path = "/workspace", options: SandboxFilesOptions & { limit?: number } = {}): Promise<VolumeEntry[]> {
    const rows = await paginate(this.agent._api, await this.route("/files"), {
      query: this.listQuery(path, options), user: this.agent._talkScope(this.user), limit: options.limit,
    });
    return rows.map(toVolumeEntry);
  }

  /** One page of `files`, and where it was read; pass `nextCursor` back as `cursor`. */
  async filesPage(path = "/workspace", options: SandboxFilesOptions & PageOptions = {}): Promise<SandboxFilesPage> {
    const raw = asObject(await this.agent._request("GET", await this.route("/files"), {
      query: { ...this.listQuery(path, options), cursor: options.cursor, limit: options.limit },
      user: this.agent._talkScope(this.user),
    }));
    return {
      data: asList(raw).map(toVolumeEntry), nextCursor: str(raw.next_cursor),
      source: raw.source === "sandbox" ? "sandbox" : "workspace",
    };
  }

  /** One file's bytes (up to 16 MB), its secrets taken out; a missing file throws `NotFound`. */
  async read(path: string): Promise<Uint8Array> {
    return await this.agent._request<Uint8Array>("GET", await this.route("/files"), {
      query: { path }, responseType: "bytes", user: this.agent._talkScope(this.user),
    });
  }

  /**
   * Run a bash command in its running sandbox, in the agent's working directory, beside its work: the agent isn't
   * stopped, and the sandbox stays up while the command runs. A stopped conversation throws `Conflict` (its next
   * turn starts its sandbox). `timeoutS` is 60 by default, at most 90.
   */
  async exec(command: string, options: { timeoutS?: number } = {}): Promise<ExecResult> {
    return toExecResult(await this.agent._request("POST", await this.route("/exec"), {
      json: compact({ command, timeout_s: options.timeoutS }), user: this.agent._talkScope(this.user),
    }));
  }

  /**
   * Your own shell (`bash -l`) on its running sandbox, in the agent's working directory, beside its work: the agent
   * isn't stopped, and the sandbox stays up while you type. Resolves to a single-use `token` for `url` (two minutes);
   * `connect()` it from the browser as a take-over's terminal is. It closes as bash exits, after `idleLimitS` with
   * nothing typed, or when its connection closes; while it's open, `connect` renews it by asking for the shell
   * again. A stopped conversation throws `Conflict`.
   *
   *     const shell = await coder.sandbox().shell();
   *     const connection = shell.connect({ cols: term.cols, rows: term.rows, onData: (bytes) => term.write(bytes) });
   *     term.onData((text) => connection.write(text));
   */
  async shell(): Promise<SandboxShell> {
    return new SandboxShell(asObject(await this.agent._request("POST", await this.route("/shell"), {
      user: this.agent._talkScope(this.user),
    })), async () => (await this.shell()).token);
  }
}

/** A shell on a conversation's sandbox (`AgentSandbox.shell`): `connect()` opens it, once per token. */
export class SandboxShell {
  readonly agentId: string;
  readonly conversation: string;
  /** The terminal websocket it opens on. */
  readonly url: string;
  /** Opens `url` once, within two minutes: its first message's `token`. */
  readonly token: string;
  readonly tokenExpiresAt: Date | null;
  /** It closes after this long with nothing typed. */
  readonly idleLimitS: number | null;
  readonly raw: JsonObject;
  private connected = false;
  private readonly renew?: () => Promise<string>;

  /** @internal */
  constructor(raw: JsonObject, renew?: () => Promise<string>) {
    this.renew = renew;
    this.agentId = String(raw.agent_id);
    this.conversation = String(raw.conversation);
    this.url = String(raw.url);
    this.token = String(raw.token);
    this.tokenExpiresAt = parseTime(raw.token_expires_at);
    this.idleLimitS = num(raw.idle_limit_s);
    this.raw = raw;
  }

  /** Open the shell: `onState` hears `exited` (and why) as it ends, and it closes for good (`final`). */
  connect(options: TerminalConnectOptions = {}): TerminalConnection {
    if (this.connected) throw new TypeError("A shell token opens it once: ask for another with sandbox.shell()");
    this.connected = true;
    return new TerminalConnection(this.url, this.token, { ...options, renew: options.renew ?? this.renew });
  }
}

// ── coding agents ──────────────────────────────────────────────────────────

/** Where a coding agent's current or next turn runs. */
export type CodingPlace = "live" | "sandbox" | "machine";
export type CodingState = "working" | "waiting" | "warm" | "paused" | "stopped";

/** Why a coding agent isn't doing anything (`expired`, `disconnected`, `spending_paused`, `spend_cap`, `out_of_funds`, `budget`, `failed_start`, `paused`). */
export interface CodingPause {
  reason: string;
  message: string;
}

/** Whose model credential it thinks with: `key`, a person's `plan`, NoClick's own (`noclick`), or `pending` until it's connected. */
export interface CodingCredential {
  kind: "key" | "plan" | "noclick" | "pending";
  connection: string | null;
  credentialType: string | null;
  connected: boolean | null;
}

/** Its turn in flight (or a `lost` one): `title` as whoever handed it over named it, `text` the start of what it was asked. */
export interface CodingJob {
  operationId: string;
  conversation: string | null;
  status: string;
  step: string | null;
  since: Date | null;
  title: string | null;
  text: string;
  lost: boolean;
  raw: JsonObject;
}

/** A conversation of its with a place up now; a sandbox's `cpu` and `memoryMb` are what it reserved. */
export interface CodingRun {
  conversation: string | null;
  place: CodingPlace;
  since: Date | null;
  busy: boolean;
  projectId: string | null;
  daemon: boolean | null;
  cpu: number | null;
  memoryMb: number | null;
}

/** The app a coding agent codes, by `name` (what code finds it by) and `title` (as a person reads it); `coder` for the app's own coding agent. */
export interface CodingApp {
  projectId: string;
  name: string | null;
  title: string | null;
  coder: boolean;
}

/** One coding agent, as `Agent.coding()` reads it: its `state`, its `place`, whose model credential it thinks with, its current `job` and the conversations up now (`runs`). */
export interface CodingAgent {
  agentId: string;
  name: string;
  userId: string | null;
  app: CodingApp | null;
  harness: HarnessName;
  model: string | null;
  credential: CodingCredential;
  place: CodingPlace;
  state: CodingState;
  paused: CodingPause | null;
  pauses: CodingPause[];
  job: CodingJob | null;
  runs: CodingRun[];
  spentUsdThisMonth: number;
  modelUsageThisMonth: ModelUsage;
  raw: JsonObject;
}

/** How many coding agents run on each harness and model, in each state and place. */
export interface CodingCount {
  harness: HarnessName;
  model: string | null;
  state: CodingState;
  place: CodingPlace;
  count: number;
}

/**
 * Every coding agent of the account (or its users'), what each is doing right now and where: `agents`, then `counts`
 * by harness, model, state and place, `byState`, `pausedByReason`, and `unread`: what couldn't be read (an app's
 * container, the sandbox registry), whose runs are unknown, never shown down.
 */
export interface CodingAgents {
  agents: CodingAgent[];
  counts: CodingCount[];
  byState: Record<string, number>;
  pausedByReason: Record<string, number>;
  readAt: Date | null;
  unread: string[];
  raw: JsonObject;
}

function toPause(value: unknown): CodingPause {
  const raw = asObject(value);
  return { reason: String(raw.reason), message: String(raw.message ?? "") };
}

function toCodingAgent(value: unknown): CodingAgent {
  const raw = asObject(value);
  const credential = asObject(raw.credential);
  const app = raw.app ? asObject(raw.app) : null;
  const job = raw.job ? asObject(raw.job) : null;
  const usage = asObject(raw.model_usage_this_month);
  return {
    agentId: String(raw.agent_id), name: String(raw.name), userId: str(raw.user_id),
    app: app && { projectId: String(app.project_id), name: str(app.name), title: str(app.title), coder: Boolean(app.coder) },
    harness: raw.harness as HarnessName, model: str(raw.model),
    credential: {
      kind: credential.kind as CodingCredential["kind"], connection: str(credential.connection),
      credentialType: str(credential.credential_type),
      connected: typeof credential.connected === "boolean" ? credential.connected : null,
    },
    place: raw.place as CodingPlace, state: raw.state as CodingState,
    paused: raw.paused ? toPause(raw.paused) : null, pauses: (Array.isArray(raw.pauses) ? raw.pauses : []).map(toPause),
    job: job && {
      operationId: String(job.operation_id), conversation: str(job.conversation), status: String(job.status),
      step: str(job.step), since: parseTime(job.since), title: str(job.title), text: String(job.text ?? ""),
      lost: Boolean(job.lost), raw: job,
    },
    runs: (Array.isArray(raw.runs) ? raw.runs : []).map((value) => {
      const run = asObject(value);
      return {
        conversation: str(run.conversation), place: run.place as CodingPlace, since: parseTime(run.since),
        busy: Boolean(run.busy), projectId: str(run.project_id),
        daemon: typeof run.daemon === "boolean" ? run.daemon : null, cpu: num(run.cpu), memoryMb: num(run.memory_mb),
      };
    }),
    spentUsdThisMonth: num(raw.spent_usd_this_month) ?? 0,
    modelUsageThisMonth: {
      inputTokens: num(usage.input_tokens) ?? 0, outputTokens: num(usage.output_tokens) ?? 0,
      cachedTokens: num(usage.cached_tokens) ?? 0, usd: num(usage.usd) ?? 0, raw: usage,
    },
    raw,
  };
}

/** @internal */
export function toCodingAgents(value: unknown): CodingAgents {
  const raw = asObject(value);
  return {
    agents: asList(raw).map(toCodingAgent),
    counts: (Array.isArray(raw.counts) ? raw.counts : []).map((value) => {
      const count = asObject(value);
      return { harness: count.harness as HarnessName, model: str(count.model), state: count.state as CodingState,
               place: count.place as CodingPlace, count: num(count.count) ?? 0 };
    }),
    byState: asObject(raw.by_state) as Record<string, number>,
    pausedByReason: asObject(raw.paused_by_reason) as Record<string, number>,
    readAt: parseTime(raw.read_at), unread: (Array.isArray(raw.unread) ? raw.unread : []).map(String), raw,
  };
}

// ── share link ─────────────────────────────────────────────────────────────

/**
 * An agent's public chat page. Anyone with `url` can talk to the agent, no sign-in: each visitor
 * in conversations of their own, billed to you. Your brand dresses the page. `createdAt` is when
 * it was first shared.
 */
export class ShareLink extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _from(raw: JsonObject, init: { agentId: string; client?: NoClick; user?: UserOption }): ShareLink {
    return new ShareLink({ raw, hints: { agent_id: init.agentId }, client: init.client, user: init.user });
  }

  get url(): string {
    return this._field("url");
  }
  get enabled(): boolean {
    return Boolean(this._field("enabled"));
  }
  get agentId(): string {
    return this._field("agent_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** When the URL last changed (null if it never has). */
  get rotatedAt(): Date | null {
    return parseTime(this._field("rotated_at"));
  }

  private get path(): string {
    return `/v1/agents/${this._known("agent_id")}/share`;
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", this.path);
  }

  /** Turn the page off: visitors see the agent isn't available. `agent.share()` turns it back on at the same URL. */
  async disable(): Promise<this> {
    this._raw = await this._request<JsonObject>("PATCH", this.path, { json: { enabled: false } });
    return this;
  }

  /** Give the page a new URL; the old one stops at once. */
  async rotate(): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `${this.path}/rotate`);
    return this;
  }
}

// ── live events ────────────────────────────────────────────────────────────

/**
 * One moment of a streamed turn or a watched conversation. `type` is `text` (`text` is the next
 * piece of the reply), `tool_call` (`tool`, its wire name like `gmail__send_email_message`, and its
 * `arguments`; `held` when policy holds it for a person), `tool_result` (`tool`, its `result`: the
 * start of what it returned, up to 500 characters, or its error; and whether it `isError`), `file`
 * (a `file` the message carried, `role` `user`, or the turn made, `assistant`), `reasoning` (`text` is
 * one short line of what the model is thinking, the title of a section of its reasoning, sent as it
 * completes), `status` (`compacting` while a long conversation's older history is summarized, then
 * `compacted`), `approval` (its
 * `"noclick"` tools held a purchase or a deletion for the account's owner: the `approval`),
 * `operation` (they started a long action: the `operation`, which comes again with its `progress`
 * each time the work reports some and once more when it ends) or `done` (`reply` is the whole
 * `AgentReply`, as `message` resolves to). `agent.watch()` also yields `message` (a whole message:
 * its `role`, `text`, `files` and `via` or `trigger`; a reply, its `toolCalls` and `reasoning`; a `note`, its `data`), `status` (the conversation's new `status`) and
 * `turn_end` once a turn of the conversation ends, however it started and whether or not it saved a reply (its
 * `status`: `succeeded`, `failed`, `canceled` or `expired`; `text`, its reply's words, empty when it said nothing). `operationId` names
 * the turn an event belongs to (null for a message no turn sent, like a person's reply). `history()`
 * reads messages in the same shape. The type `call` is reserved for a phone call's moments. A coding harness's turn
 * (Codex, Claude Code and the like) also tells what its commands print as they run, `output` (`text`, its command's
 * `callId`, and `whole` when it replaces what came before of that command), and each file it changes, `diff` (`path`,
 * `change` and the `diff`). Its own steps' `tool_call` and `tool_result` say `source` `harness`, name their `callId`
 * and say what kind of step it is (`stepKind`), a `tool_call` what it's about (`command`, `path` or `query`), a
 * command's result its `exitCode` and `durationMs`: the fields a finished turn's `AgentStep` keeps. A `status` of
 * `events_dropped` says `count` moments its sandbox couldn't send. On a machine, a turn waiting for its harness's
 * image says `downloading` while it downloads (`text`, like "Downloading OpenCode for this machine: 450 MB of
 * 1.31 GB", with `downloaded_bytes` and `total_bytes` in `raw`), then `downloaded`.
 */
export interface AgentEvent {
  type:
    | "text" | "reasoning" | "tool_call" | "tool_result" | "file" | "approval" | "operation" | "done" | "message"
    | "status" | "output" | "diff" | "turn_end" | (string & {});
  text: string | null;
  tool: string | null;
  arguments: JsonObject | null;
  result: unknown;
  isError: boolean;
  reply: AgentReply | null;
  /** A `message`'s sender: `user`, `assistant`, `person` (someone it was handed off to) or `note` (`agent.note`). */
  role: "user" | "assistant" | "person" | "note" | null;
  /** A held `tool_call`: who `approver` is and, when the request is addressed to the scope you read as, the approval's `request_id` and page `url`. */
  held: JsonObject | null;
  /**
   * A `status` event's: the conversation's new status, or a turn's own (`compacting`, then `compacted`; a coding
   * harness's `events_dropped`; on a machine, `downloading`, then `downloaded`). A `turn_end`'s: how the turn ended.
   */
  status:
    | "active" | "awaiting_human" | "handed_off" | "compacting" | "compacted" | "events_dropped" | "downloading"
    | "downloaded" | "succeeded" | "failed" | "canceled" | "expired" | null;
  /** A `file` event's file. */
  file: Attachment | null;
  /** A `message` event's files. */
  files: Attachment[];
  /** A `message` event's tool calls (a reply's): each `{tool, arguments, result, is_error}`, as its turn's events showed it. */
  toolCalls: JsonObject[];
  /**
   * An `approval` event's: its `id`, `summary`, exact `price` (a purchase), `expires_at` and `sent_to`,
   * the apps NoClick sent the account's owner its link on (never the link).
   */
  approval: JsonObject | null;
  /**
   * An `operation` event's: the long action's `id` (an `Operation`'s), `kind`, `status` and `summary` and, once
   * the work reported some, its `progress` (`Operation.progress`, with its last 3 `lines`).
   */
  operation: JsonObject | null;
  /** A `user` message's way in, when not the API. */
  via: MessageVia | null;
  /** A `note` message's data. */
  data: JsonObject | null;
  /** A `user` message no person sent: what started its turn (`Message.trigger`). */
  trigger: MessageTrigger | null;
  /** A `message` event's reasoning (a reply's): `Message.reasoning`. */
  reasoning: ReasoningLine[];
  /**
   * A coding harness's step: the `tool_call`, the `output` of its command, its `tool_result` and the `diff` of each
   * file it changed share it.
   */
  callId: string | null;
  /** `harness` for a step a coding harness took itself (its own shell, its edits), not a tool NoClick gave it. */
  source: "harness" | (string & {}) | null;
  /** A harness command's `tool_result`: its exit code (null when it never exited). */
  exitCode: number | null;
  /** A harness command's `tool_result`: how long it ran. */
  durationMs: number | null;
  /** A harness step's `tool_call` and `tool_result`: `command`, `edit`, `read`, `search` or `tool` (`AgentStep.kind`). */
  stepKind: AgentStepKind | null;
  /** A harness command's `tool_call`: the command it runs. */
  command: string | null;
  /**
   * A `request` event's: what a coding harness asks a person (an approval or a question), as it waits and as it ends,
   * in the shape `agent.requests` lists (answer it with `agent.answer`).
   */
  request: JsonObject | null;
  /** A harness search's `tool_call`: what it looks for. */
  query: string | null;
  /** An `output` that replaces what streamed of its command so far, rather than continuing it. */
  whole: boolean;
  /** A `diff`'s file, or the file (a page's URL) a harness step's `tool_call` edits or reads. */
  path: string | null;
  /** What happened to a `diff`'s file. */
  change: "add" | "update" | "delete" | (string & {}) | null;
  /** A `diff`'s change: a unified diff, or a new file's whole content. */
  diff: string | null;
  /** A `status` `events_dropped`'s: how many moments its sandbox couldn't send. */
  count: number | null;
  operationId: string | null;
  /** A `message`'s id in its thread (`Message.id`). */
  messageId: string | null;
  /** Who sent a `user` `message` (`Message.author`). */
  author: MessageAuthor | null;
  /** A `message` an agent sent its owner from another of its conversations (`Message.notification`). */
  notification?: boolean;
  /** A notification's space, when it passes on a space's news (`Message.space`). */
  space?: MessageSpace | null;
  /** The coding harness's subagent a `user` `message` was written for (`Message.subagent`). */
  subagent?: MessageSubagent | null;
  /** The chat a `message` of the agent's session came from, where it isn't the session's own (`Message.chat`). */
  chat?: string | null;
  raw: JsonObject;
}

// ── test runs ──────────────────────────────────────────────────────────────

/**
 * A test run: a real turn of the agent (its model, instructions and tools) where a simulated world
 * answers every tool call, so nothing is sent and no account is touched. `toolCalls` are the calls
 * it made, each with the `tool` (its tool name, like `gmail__search_emails`), its `arguments` and
 * the `result` the world answered (null if the world couldn't); `transcript` is the turn step by
 * step: `role` `assistant` steps (its `text` between calls, then the reply) and `tool` steps. On a
 * coding harness its own shell and file steps are `tool` steps with `source` `harness`: they ran
 * for real, in the run's own sandbox. `costUsd` is what the run cost you.
 */
export interface Rehearsal {
  reply: string;
  toolCalls: JsonObject[];
  transcript: JsonObject[];
  scenario: string | null;
  costUsd: number | null;
  operationId: string | null;
  raw: JsonObject;
}

registerResult("agent.rehearse", (result, op): Rehearsal => {
  const raw = asObject(result);
  return {
    reply: str(raw.reply) ?? "",
    toolCalls: Array.isArray(raw.tool_calls) ? (raw.tool_calls as JsonObject[]) : [],
    transcript: Array.isArray(raw.transcript) ? (raw.transcript as JsonObject[]) : [],
    scenario: str(raw.scenario),
    costUsd: num(raw.cost_usd),
    operationId: str(op._known("id")),
    raw,
  };
});
