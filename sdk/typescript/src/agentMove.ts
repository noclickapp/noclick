/**
 * Moves: a coding agent's session on a laptop (Claude Code, Codex, OpenCode, Hermes or OpenClaw) copies itself onto a
 * NoClick agent and carries on there. The laptop keeps its own session.
 *
 *     const move = await AgentMove.create({ name: "Docs fixer", workspaceId });
 *     copy(move.prompt);                 // a person pastes it into the session they want moved
 *     // on each platform:resource frame of kind "agent_move" for move.id:
 *     await move.refresh();
 *     move.status;                       // "moving", then "finishing", then "done"
 *     move.arrived.files;                // what the agent carried so far
 *     if (move.status === "done") open(move.agentId!, move.conversation!);
 *
 * The agent in that session follows the guide the prompt names, with the move's own key.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { errorFromPayload, OperationFailed } from "./errors.ts";
import { ApiObject, compact, parseTime, refId, str } from "./object.ts";
import type { CallOptions, JsonObject, ObjectInit } from "./object.ts";

/** `waiting` (its code unused), `moving` (things arriving), `finishing`, `done`, `failed` (finish again), `canceled`, `expired`. */
export type AgentMoveStatus = "waiting" | "moving" | "finishing" | "done" | "failed" | "canceled" | "expired";

/** Where the session moves from, as the moving agent says. */
export interface AgentMoveSource {
  harness: string;
  host: string;
  cwd: string;
  cliVersion: string | null;
  sessionId: string | null;
  title: string | null;
}

/** What arrived so far: names, sizes and counts, never a value. */
export interface AgentMoveArrived {
  session: { harness: string; sessionId: string | null; title: string | null; messages: number; toolCalls: number } | null;
  repo: { repoId: string; name: string; branch: string } | null;
  files: { path: string; sizeBytes: number }[];
  /** The secrets the person said yes to carrying: each by name, what it is and where it goes, never a value. */
  consent: { name: string; kind: string; to: string }[];
  /** Each secret carried, by name, and where it goes in the copy: `{env}`, `{file, mode}`, `{model}` or `{}`. */
  secrets: { name: string; to: JsonObject }[];
  setup: string[];
  checkout: { url: string; branch: string; path: string; secret: string | null; username: string | null } | null;
  /** Each tool server carried; `needsSignIn` when its login lived in a browser and the person signs in to it here. */
  mcpServers: { name: string; url: string; transport: string; headers: { name: string; secret?: string }[]; needsSignIn: boolean }[];
  skills: { name: string; files: number }[];
  memories: { name: string; description: string }[];
  note: { chars: number } | null;
  instructions: { chars: number } | null;
  /** Once finished: what it made the account's of each secret, model key and tool server login, never a value. */
  carried: JsonObject[];
}

/** One step of the finish, in order: `secrets`, `agent`, `space`, `files`, `tools`, `skills`, `memories`, `conversation`. */
export interface AgentMoveStep {
  name: "secrets" | "agent" | "space" | "files" | "tools" | "skills" | "memories" | "conversation";
  label: string;
  status: "running" | "done" | "failed";
  detail?: string;
  error?: string;
  /** A failed step's error whole: `type`, `message`, `next_step`. */
  failure?: JsonObject;
}

/** How often `finish` reads a move whose finish NoClick is running, in milliseconds. */
export const FINISH_POLL_MS = 2000;

export interface AgentMoveCreateOptions extends CallOptions {
  /** The space (workspace) the agent joins. */
  workspaceId?: string;
  /** Its name; omitted, the moving agent's choice, else its folder's. */
  name?: string;
  /** `claude_code`, `codex`, `opencode`, `hermes` or `openclaw`; omitted, the session's own. */
  harness?: string;
  /** Its model in the harness's format; omitted, the session's or the harness's default. */
  model?: string;
  /** The connection holding its model's key or plan; omitted, the account's own that runs it. */
  modelConnection?: string | ApiObject;
  /** The machine (or its id) it runs on, judged as placing an agent there is; omitted, a sandbox of its own. Its
   * setup and secrets' files run in its container there as in a sandbox. */
  machine?: string | ApiObject;
}

const list = (value: unknown): JsonObject[] => (Array.isArray(value) ? (value as JsonObject[]) : []);

/**
 * A move from a laptop. Make one with `create` (its `code` and `prompt` come only then), follow it with
 * `refresh` on each `platform:resource` frame of kind `agent_move`, and `cancel` it to call it off.
 */
export class AgentMove extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Make a move: a one-time code, good once for 30 minutes, and the prompt a person pastes into the coding-agent
   * session they want moved. The agent there carries what its work needs and finishes the move, which makes the agent.
   */
  static async create(options: AgentMoveCreateOptions = {}): Promise<AgentMove> {
    const { client, user } = options;
    const json = compact({
      workspace_id: options.workspaceId, name: options.name, harness: options.harness, model: options.model,
      model_connection: await refId(options.modelConnection), machine_id: await refId(options.machine),
    });
    const raw = await resolveClient(client).request<JsonObject>("POST", "/v1/agents/moves", { json, user });
    return new AgentMove({ raw, client, user });
  }

  /** A lazy reference to a move by id. */
  static fromId(moveId: string, options: CallOptions = {}): AgentMove {
    return new AgentMove({ hints: { id: moveId }, client: options.client, user: options.user });
  }

  /** The move a move's own key belongs to (the moving agent's side). */
  static async current(options: { client?: NoClick } = {}): Promise<AgentMove> {
    const move = new AgentMove({ client: options.client, user: null });
    await move.hydrate();
    return move;
  }

  protected _load(): Promise<JsonObject> {
    const id = this._known("id");
    return this._request<JsonObject>("GET", id ? `/v1/agents/moves/${id}` : "/v1/moves/current");
  }

  get id(): string {
    return this._field("id");
  }
  get status(): AgentMoveStatus {
    return this._field("status");
  }
  /** The one-time code (from `create` only). */
  get code(): string | null {
    return str(this._field("code"));
  }
  /** What a person pastes into the session to move (from `create` only). */
  get prompt(): string | null {
    return str(this._field("prompt"));
  }
  /** The guide the moving agent follows. */
  get guideUrl(): string {
    return this._field("guide_url");
  }
  get workspaceId(): string | null {
    return str(this._field("workspace_id"));
  }
  /** Where it moves from, once the moving agent says. */
  get source(): AgentMoveSource | null {
    const raw = this._field<JsonObject | null>("source");
    if (!raw) return null;
    return {
      harness: String(raw.harness ?? ""), host: String(raw.host ?? ""), cwd: String(raw.cwd ?? ""),
      cliVersion: str(raw.cli_version), sessionId: str(raw.session_id), title: str(raw.title),
    };
  }
  /** What arrived so far, for the "Found on your laptop" list. */
  get arrived(): AgentMoveArrived {
    const raw = this._field<JsonObject | null>("arrived") ?? {};
    const session = raw.session as JsonObject | null;
    const repo = raw.repo as JsonObject | null;
    return {
      session: session
        ? { harness: String(session.harness), sessionId: str(session.session_id), title: str(session.title),
            messages: Number(session.messages ?? 0), toolCalls: Number(session.tool_calls ?? 0) }
        : null,
      repo: repo ? { repoId: String(repo.repo_id), name: String(repo.name), branch: String(repo.branch) } : null,
      files: list(raw.files).map((f) => ({ path: String(f.path), sizeBytes: Number(f.size_bytes ?? 0) })),
      consent: list(raw.consent).map((c) => ({ name: String(c.name), kind: String(c.kind), to: String(c.to) })),
      secrets: list(raw.secrets).map((s) => ({ name: String(s.name), to: (s.to as JsonObject) ?? {} })),
      setup: Array.isArray(raw.setup) ? (raw.setup as unknown[]).map(String) : [],
      checkout: raw.checkout
        ? { url: String((raw.checkout as JsonObject).url), branch: String((raw.checkout as JsonObject).branch),
            path: String((raw.checkout as JsonObject).path), secret: str((raw.checkout as JsonObject).secret),
            username: str((raw.checkout as JsonObject).username) }
        : null,
      mcpServers: list(raw.mcp_servers).map((s) => ({
        name: String(s.name), url: String(s.url), transport: String(s.transport),
        headers: list(s.headers).map((h) => ({ name: String(h.name), ...(h.secret ? { secret: String(h.secret) } : {}) })),
        needsSignIn: Boolean(s.needs_sign_in),
      })),
      skills: list(raw.skills).map((s) => ({ name: String(s.name), files: Number(s.files ?? 0) })),
      memories: list(raw.memories).map((m) => ({ name: String(m.name), description: String(m.description ?? "") })),
      note: (raw.note as { chars: number } | null) ?? null,
      instructions: (raw.instructions as { chars: number } | null) ?? null,
      carried: list(raw.carried),
    };
  }
  /** The finish's progress, in order. */
  get steps(): AgentMoveStep[] {
    return list(this._field("steps")) as unknown as AgentMoveStep[];
  }
  /** The agent it made, once `done`. */
  get agentId(): string | null {
    return str(this._field("agent_id"));
  }
  /** The agent's conversation holding the moved session, once `done`. */
  get conversation(): string | null {
    return str(this._field("conversation"));
  }
  /** Why it failed. */
  get error(): string | null {
    return str(this._field("error"));
  }
  /** What the moving agent does next while a finish runs (read the move again) or after one failed. */
  get nextStep(): string | null {
    return str(this._field("next_step"));
  }
  get expiresAt(): Date | null {
    return parseTime(this._field("expires_at"));
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  /** Call the move off: its key stops working and what arrived goes. A finished move's agent stays. */
  async cancel(): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `/v1/agents/moves/${this._known("id")}/cancel`);
    return this;
  }

  /** Give a tool server the move carried needing sign-in the person's sign-in to it: the `mcp_oauth` connection
   * NoClick's own MCP sign-in made for its URL. Its `carried` entry then no longer needs sign-in. */
  async connectSignIn(name: string, credentialId: string): Promise<this> {
    this._raw = await this._request<JsonObject>(
      "POST", `/v1/agents/moves/${this._known("id")}/sign_ins/${encodeURIComponent(name)}`, { json: { credential_id: credentialId } });
    return this;
  }

  /** What the move was made with: `name`, `harness`, `model`, `model_connection`. */
  get draft(): JsonObject {
    return (this._field<JsonObject | null>("draft") ?? {}) as JsonObject;
  }
  /** Where it lands (the moving side): the agent's `name` and `harness`, `cwd`, where its session moves to, and
   * `machine` (`id`, `name`), the machine it runs on, or null for a sandbox of its own. */
  get landsAs(): JsonObject | null {
    return this._field<JsonObject | null>("lands_as") ?? null;
  }
  /** What a finish asks before it makes anything (a session that carried no MCP server and no skill: none?). */
  get question(): string | null {
    return str(this._field("question"));
  }
  /** The move's calls (the moving side), one line each: method, path and what it does. */
  get endpoints(): string[] {
    const raw = this._field<unknown>("endpoints");
    return Array.isArray(raw) ? raw.map(String) : [];
  }

  /**
   * Redeem a move code for the move's own key, once: it reaches only this move, for an hour. Keep it out of anything
   * you print.
   */
  static async redeem(code: string, options: { host?: string; client?: NoClick } = {}): Promise<string> {
    const form = new URLSearchParams({ code, ...(options.host ? { host: options.host } : {}) }).toString();
    const key = await resolveClient(options.client).request<string>("POST", "/v1/moves/redeem", {
      body: form, contentType: "application/x-www-form-urlencoded", user: null, responseType: "bytes",
    });
    return new TextDecoder().decode(key as unknown as Uint8Array).trim();
  }

  private async moving(method: string, path: string, options: { json?: unknown; body?: Uint8Array | string; query?: Record<string, string> } = {}): Promise<this> {
    this._raw = await this._request<JsonObject>(method, `/v1/moves/current${path}`, {
      ...options, ...(options.body !== undefined ? { contentType: "application/octet-stream" } : {}), user: null,
    });
    return this;
  }

  /**
   * Say where the session moves from: its harness, machine and folder, and, where the session's own files don't record
   * them, the model, effort (`"xhigh"`) and speed (`"fast"`) it runs at. What's said wins over what the session upload
   * read; the rest of that stays.
   */
  setSource(source: { harness: string; host: string; cwd: string; cliVersion?: string; sessionId?: string; title?: string; model?: string; effort?: string; speed?: string }): Promise<this> {
    return this.moving("PUT", "/source", { json: compact({
      harness: source.harness, host: source.host, cwd: source.cwd, cli_version: source.cliVersion,
      session_id: source.sessionId, title: source.title, model: source.model, effort: source.effort,
      speed: source.speed,
    }) });
  }

  /** The session's own files: a tar of paths relative to the harness's home (`~/.claude` for Claude Code). */
  uploadSession(data: Uint8Array, options: { harness: string; cwd: string; sessionId?: string }): Promise<this> {
    return this.moving("PUT", "/session", { body: data, query: compact({
      harness: options.harness, cwd: options.cwd, session_id: options.sessionId,
    }) as Record<string, string> });
  }

  /** A NoClick repo for the code (made once) and a push `url`, good for 10 minutes: treat it as a secret. */
  repo(options: { name?: string; branch?: string } = {}): Promise<JsonObject> {
    return this._request<JsonObject>("POST", "/v1/moves/current/repo", { json: compact({ ...options }), user: null });
  }

  /** A file from outside the repo, placed at `/workspace/<path>` (up to 100 MB). */
  putFile(path: string, data: Uint8Array | string): Promise<this> {
    return this.moving("PUT", "/files", { body: data, query: { path } });
  }

  /**
   * The secrets the person said yes to carrying, each `{name, kind, to}` as they read it (never a value);
   * `confirmed: true` once they said yes in the session. A secret is carried only once it's listed here.
   */
  consent(secrets: { name: string; kind: string; to: string }[], options: { confirmed: boolean }): Promise<this> {
    return this.moving("PUT", "/consent", { json: { secrets, confirmed: options.confirmed } });
  }

  /**
   * One secret the session uses, sealed as it lands, and where it goes in the copy: `{env: NAME}`,
   * `{file: path, mode?}`, `{model: provider}` (the model key it runs on), or none for one a tool server's header
   * or the checkout refers to by name.
   */
  putSecret(name: string, value: string, options: { to?: JsonObject } = {}): Promise<this> {
    return this.moving("PUT", `/secrets/${encodeURIComponent(name)}`, { json: { value, to: options.to ?? {} } });
  }

  /** What the copy's sandbox runs as it starts (after its secrets' files are written): the CLIs the session used. */
  setSetup(commands: string[]): Promise<this> {
    return this.moving("PUT", "/setup", { json: { commands } });
  }

  /** The session's own git remote, checked out in the copy at the branch it pushed its work to. */
  setCheckout(url: string, branch: string, options: { path?: string; secret?: string; username?: string } = {}): Promise<this> {
    return this.moving("PUT", "/checkout", { json: compact({ url, branch, ...options }) });
  }

  /** The person's one-tap sign-in to the plan the session's harness runs on: its tokens never move. */
  planLink(): Promise<JsonObject> {
    return this._request<JsonObject>("POST", "/v1/moves/current/plan_link", { user: null });
  }

  /** A remote MCP server it used (a public https URL); the agent gets its tools. A header is text, or `{secret}`.
   * `signIn: "browser"` for one whose login lives in a browser (a claude.ai connector, an OAuth sign-in): it moves
   * with no headers and no login, and the person signs in to it once on NoClick. */
  addMcpServer(
    name: string, url: string,
    options: { transport?: "http" | "sse"; headers?: Record<string, string | { secret: string }>; signIn?: "browser" } = {},
  ): Promise<this> {
    return this.moving("PUT", `/mcp_servers/${encodeURIComponent(name)}`, {
      json: compact({ url, transport: options.transport ?? "http", headers: options.headers ?? {}, sign_in: options.signIn }),
    });
  }

  /** A skill: its folder as a tar, SKILL.md at its top. */
  addSkill(name: string, data: Uint8Array): Promise<this> {
    return this.moving("PUT", `/skills/${encodeURIComponent(name)}`, { body: data });
  }

  /** Something it learned, kept in its NoClick memory. */
  addMemory(name: string, content: string, options: { description: string }): Promise<this> {
    return this.moving("PUT", `/memories/${encodeURIComponent(name)}`, { json: { content, description: options.description } });
  }

  /** The handoff note: what it's in the middle of and what's next. The agent reads it first. */
  setNote(text: string): Promise<this> {
    return this.moving("PUT", "/note", { body: text });
  }

  /** Its instructions: what it was told for every project (a user-level CLAUDE.md or AGENTS.md). */
  setInstructions(text: string): Promise<this> {
    return this.moving("PUT", "/instructions", { body: text });
  }

  /**
   * Make the agent from what arrived (the moving agent's side, with the move's own key). NoClick runs the finish's
   * steps (`finishing`) and this reads the move until they end, `done`; a failed step throws its own error, whose
   * `nextStep` says what to do. `wait: false` returns it `finishing`.
   */
  async finish(
    options: { name?: string; model?: string; modelConnection?: string; harness?: string; none?: ("mcp_servers" | "skills")[]; wait?: boolean } = {},
  ): Promise<this> {
    await this.moving("POST", "/finish", {
      json: compact({ name: options.name, model: options.model, model_connection: options.modelConnection,
                      harness: options.harness, none: options.none }),
    });
    const wait = options.wait ?? true;
    while (wait && this.status === "finishing") {
      await this._api._sleep(FINISH_POLL_MS);
      await this.moving("GET", "");
    }
    if (wait && this.status === "failed") {
      const failed = this.steps.find((s) => s.status === "failed");
      throw errorFromPayload(failed?.failure ?? { message: this.error, next_step: this.nextStep }, { fallback: OperationFailed });
    }
    return this;
  }
}
