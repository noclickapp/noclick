/**
 * An agent's conversations as a chat drives them: each one's settings (the agent's model, reasoning effort, speed and
 * the account its model runs on, which every conversation runs on, and the conversation's own permission mode),
 * starting, forking, reverting and resuming one, how full its model's context is, what it cost, and every agent's
 * state for a list of them.
 *
 *     const settings = await coder.conversation("main").settings();
 *     await coder.conversation("main").update({ effort: "high" });
 *     const fork = await coder.conversation("main").fork({ message: history.at(-1)!.id! });
 *     const { data } = await Agent.states();
 */

import type { HarnessName, ModelUsage, PermissionMode, StepCategory } from "./agent.ts";
import type { ConnectLink, LinkOptions } from "./connection.ts";
import { asObject, num, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** How fast a conversation's model runs: `fast` where its harness has a fast mode (`speeds`). */
export type AgentSpeed = "standard" | "fast";

/** What a conversation can run its model on: one of its scope's model connections, or NoClick's own key. */
export interface ModelAccount {
  /** The connection's name to pass as `modelConnection` (`"noclick"` for NoClick's key; null on `sdk`, whose NoClick router takes no connection). */
  name: string | null;
  integration: string | null;
  /** `key`, a provider's `plan` (a Claude or ChatGPT sign-in), or `noclick`: NoClick's own key, at the model's cost. */
  kind: "key" | "plan" | "noclick";
  connected: boolean;
  /** Whether it runs the conversation's harness on its model now; `why` says why not. */
  usable: boolean;
  why: string | null;
}

/**
 * A conversation's settings: what its next turn runs on (the agent's `model`, `effort`, `speed` and `modelConnection`,
 * which every conversation runs on), the efforts and speeds its harness takes on that model, what can pay for it
 * (`accounts`), its permission mode (the strictest the harness enforces in `effectivePermissionMode`), its `title`,
 * whether it's `archived`, and the conversation it was forked from.
 */
export interface ConversationSettings {
  conversation: string;
  title: string | null;
  archived: boolean;
  harness: HarnessName | null;
  model: string | null;
  /** null: the model's own default (`defaultEffort`, when the harness says it). */
  effort: string | null;
  /** The efforts its harness takes on its model, weakest first, in the harness's own words ([]: none). */
  efforts: string[];
  defaultEffort: string | null;
  speed: AgentSpeed;
  /** `["standard", "fast"]` where its harness has a fast mode on its model; [] where it has none. */
  speeds: AgentSpeed[];
  modelConnection: string | null;
  accounts: ModelAccount[];
  /** What the conversation sets itself: its `permission_mode`. */
  overridden: string[];
  permissionMode: PermissionMode;
  effectivePermissionMode: PermissionMode;
  permissionModes: PermissionMode[];
  notSupported: Record<string, string>;
  forkedFrom: ForkedFrom | null;
  raw: JsonObject;
}

/**
 * What `conversation(name).update` changes: `permissionMode`, `title` and `archived` the conversation's; `model`,
 * `effort`, `speed` and `modelConnection` the agent's, for every conversation (`null` clears all but `model`).
 */
export interface ConversationChanges {
  model?: string | null;
  effort?: string | null;
  speed?: AgentSpeed | null;
  modelConnection?: string | null;
  permissionMode?: PermissionMode;
  title?: string;
  archived?: boolean;
}

/** The conversation a fork came from, the message it was forked at, and its own last copied message (`through`). */
export interface ForkedFrom {
  conversation: string;
  message: string;
  through: string | null;
}

/** Who sent a `user` message to an agent: the account, one of your users, another agent, or an app's code. */
export interface MessageAuthor {
  type: "account" | "user" | "agent" | "app";
  id: string | null;
  name: string | null;
}

/** A conversation's newest message, as a list shows it. */
export interface LastMessage {
  role: string;
  text: string;
  createdAt: Date | null;
}

/** @internal */
export function toAuthor(value: unknown): MessageAuthor | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  const type = str(raw.type);
  return type === "account" || type === "user" || type === "agent" || type === "app"
    ? { type, id: str(raw.id), name: str(raw.name) } : null;
}

/** @internal */
export function toForkedFrom(value: unknown): ForkedFrom | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  return { conversation: String(raw.conversation), message: String(raw.message), through: str(raw.through) };
}

/** @internal */
export function toLastMessage(value: unknown): LastMessage | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  return { role: str(raw.role) ?? "", text: str(raw.text) ?? "", createdAt: parseTime(raw.created_at) };
}

/** @internal */
export function toConversationSettings(raw: JsonObject): ConversationSettings {
  const list = (value: unknown) => (Array.isArray(value) ? value.map(String) : []);
  return {
    conversation: str(raw.conversation) ?? "",
    title: str(raw.title),
    archived: raw.archived === true,
    harness: str(raw.harness) as HarnessName | null,
    model: str(raw.model),
    effort: str(raw.effort),
    efforts: list(raw.efforts),
    defaultEffort: str(raw.default_effort),
    speed: (str(raw.speed) ?? "standard") as AgentSpeed,
    speeds: list(raw.speeds) as AgentSpeed[],
    modelConnection: str(raw.model_connection),
    accounts: (Array.isArray(raw.accounts) ? (raw.accounts as JsonObject[]) : []).map((a) => ({
      name: str(a.name), integration: str(a.integration), kind: (str(a.kind) ?? "key") as ModelAccount["kind"],
      connected: a.connected === true, usable: a.usable === true, why: str(a.why),
    })),
    overridden: list(raw.overridden),
    permissionMode: (str(raw.permission_mode) ?? "full-access") as PermissionMode,
    effectivePermissionMode: (str(raw.effective_permission_mode) ?? "full-access") as PermissionMode,
    permissionModes: list(raw.permission_modes) as PermissionMode[],
    notSupported: Object.fromEntries(Object.entries(asObject(raw.not_supported)).map(([k, v]) => [k, String(v)])),
    forkedFrom: toForkedFrom(raw.forked_from),
    raw,
  };
}

/** @internal The wire body of `conversation(name).update`. */
export function conversationChanges(changes: ConversationChanges): JsonObject {
  const wire: JsonObject = {};
  const put = (key: string, value: unknown) => {
    if (value !== undefined) wire[key] = value as JsonObject[string];
  };
  put("model", changes.model);
  put("effort", changes.effort);
  put("speed", changes.speed);
  put("model_connection", changes.modelConnection);
  put("permission_mode", changes.permissionMode);
  put("title", changes.title);
  put("archived", changes.archived);
  return wire;
}

/**
 * A revert: the message it went back to before (its `text`, to put back in the composer), how many turns left the
 * thread and what the agent reads, and the files: `restored` (their edits are undone before its next turn, in its
 * sandbox, where they are), `kept` (with `files: false`), `notRestored` (and why: an edit too large to have been kept
 * whole) and `commandsNotUndone` (commands whose changes no diff records). `agentReads`: `native` when the agent reads
 * the thread as it is now in its own history, `context` when its next turn carries it as context.
 */
export interface ConversationRevert {
  conversation: string;
  message: string;
  text: string;
  droppedTurns: number;
  files: { restored: string[]; kept: string[]; notRestored: { path: string; why: string }[]; commandsNotUndone: number };
  filesApplied: "next_turn" | null;
  agentReads: "native" | "context";
  raw: JsonObject;
}

/** @internal */
export function toRevert(raw: JsonObject): ConversationRevert {
  const files = asObject(raw.files);
  const list = (value: unknown) => (Array.isArray(value) ? value.map(String) : []);
  return {
    conversation: str(raw.conversation) ?? "",
    message: str(raw.message) ?? "",
    text: str(raw.text) ?? "",
    droppedTurns: num(raw.dropped_turns) ?? 0,
    files: {
      restored: list(files.restored), kept: list(files.kept),
      notRestored: (Array.isArray(files.not_restored) ? (files.not_restored as JsonObject[]) : [])
        .map((f) => ({ path: String(f.path), why: String(f.why ?? "") })),
      commandsNotUndone: num(files.commands_not_undone) ?? 0,
    },
    filesApplied: str(raw.files_applied) as ConversationRevert["filesApplied"],
    agentReads: (str(raw.agent_reads) ?? "native") as ConversationRevert["agentReads"],
    raw,
  };
}

/**
 * How full the model's context was at the conversation's last turn: `usedTokens` of `windowTokens` (`percent`), as
 * its coding harness reported them (`source` `harness`) or as NoClick's runtime sent its last call (`noclick`), and
 * where it folds the thread by itself (`autoCompactsAt`, a share of the window). Null figures before a first turn.
 */
export interface ConversationContext {
  model: string | null;
  usedTokens: number | null;
  windowTokens: number | null;
  percent: number | null;
  autoCompactsAt: number | null;
  source: "harness" | "noclick" | null;
  asOf: Date | null;
  raw: JsonObject;
}

/** @internal */
export function toContext(raw: JsonObject): ConversationContext {
  return {
    model: str(raw.model), usedTokens: num(raw.used_tokens), windowTokens: num(raw.window_tokens),
    percent: num(raw.percent), autoCompactsAt: num(raw.auto_compacts_at),
    source: str(raw.source) as ConversationContext["source"], asOf: parseTime(raw.as_of), raw,
  };
}

/** One limit of a provider's plan: how much of it is used and when it resets. */
export interface PlanLimit {
  label: string;
  usedPercent: number | null;
  resetsAt: Date | null;
}

/**
 * What a conversation cost: `costUsd` (what its turns were charged), its model calls on your own key or plan
 * (`modelUsage`, null on NoClick's key), its `turns`, what pays for its model (`paysWith`) and, on a plan, the plan's
 * limits where its harness reported them.
 */
export interface ConversationUsage {
  costUsd: number;
  modelUsage: ModelUsage | null;
  turns: number;
  paysWith: "noclick" | "key" | "plan";
  planLimits: PlanLimit[];
  raw: JsonObject;
}

/** @internal */
export function toUsage(raw: JsonObject, modelUsage: (value: unknown) => ModelUsage | null): ConversationUsage {
  return {
    costUsd: num(raw.cost_usd) ?? 0, modelUsage: modelUsage(raw.model_usage), turns: num(raw.turns) ?? 0,
    paysWith: (str(raw.pays_with) ?? "noclick") as ConversationUsage["paysWith"],
    planLimits: (Array.isArray(raw.plan_limits) ? (raw.plan_limits as JsonObject[]) : []).map((l) => ({
      label: String(l.label ?? ""), usedPercent: num(l.used_percent), resetsAt: parseTime(l.resets_at),
    })),
    raw,
  };
}

/** What a command NoClick has a control for came to (`/model`, `/effort`, `/new`, `/context`, `/usage`…). */
export interface CommandResult {
  control: string;
  command: { name: string; arguments: string };
  /** The control's answer: conversation settings, a new conversation, its context, its usage, or an operation. */
  result: JsonObject;
  raw: JsonObject;
}

/** @internal */
export function toCommandResult(raw: JsonObject): CommandResult {
  const command = asObject(raw.command);
  return {
    control: String(raw.control), command: { name: String(command.name), arguments: str(command.arguments) ?? "" },
    result: asObject(raw.result), raw,
  };
}

/** An agent's state for a list of agents, the first that holds, in this order. */
export type AgentState = "needs_you" | "working" | "with_you" | "waking" | "failed" | "idle";

/** The tool call an agent runs now: a short `line` such as `bash: pytest -x` or `edit app/retries.py`. */
export interface AgentNow {
  tool: string;
  kind: "command" | "edit" | "read" | "search" | "tool";
  line: string;
  since: Date | null;
  /** Whether that step still runs (false once it ended and the turn goes on). */
  running: boolean;
  /** That step in words, in its tense (`Running the plan usage tests`), as a coding harness's step says it. */
  label: string | null;
  category: StepCategory | null;
  /** What the turn did so far (`Read 5 files, searched 5 times`). */
  summary: string | null;
}

/**
 * One agent as a list shows it: its `state` (`needs_you`: something waits on a person, its harness's request
 * included; `working`: a turn runs; `with_you`: a person has one of its conversations; `waking`: a turn of its own
 * is about to start; `failed`: its last turn failed; `idle`), the `conversation` that state is in, the tool call it
 * runs `now`, what `waiting` counts (asks, held calls and its harness's requests: `total` is the badge), and when.
 */
export interface AgentStateRow {
  agentId: string;
  name: string;
  harness: HarnessName;
  state: AgentState;
  conversation: string | null;
  now: AgentNow | null;
  waiting: { asks: number; heldCalls: number; requests: number; total: number };
  turnStartedAt: Date | null;
  lastActiveAt: Date | null;
  failed: { message: string; at: Date | null } | null;
  waking: { at: Date | null; why: string } | null;
  raw: JsonObject;
}

/** Every agent's state: `data`, and when it was read. */
export interface AgentStates {
  data: AgentStateRow[];
  readAt: Date | null;
  raw: JsonObject;
}

/** @internal */
export function toAgentStates(value: unknown): AgentStates {
  const raw = asObject(value);
  const rows = Array.isArray(raw.data) ? (raw.data as JsonObject[]) : [];
  return {
    data: rows.map((row) => {
      const now = row.now ? asObject(row.now) : null;
      const waiting = asObject(row.waiting);
      const failed = row.failed ? asObject(row.failed) : null;
      const waking = row.waking ? asObject(row.waking) : null;
      return {
        agentId: String(row.agent_id), name: String(row.name ?? ""), harness: row.harness as HarnessName,
        state: (str(row.state) ?? "idle") as AgentState, conversation: str(row.conversation),
        now: now && { tool: String(now.tool ?? ""), kind: (str(now.kind) ?? "tool") as AgentNow["kind"],
                      line: String(now.line ?? ""), since: parseTime(now.since), running: now.running !== false,
                      label: str(now.label), category: str(now.category) as StepCategory | null,
                      summary: str(now.summary) },
        waiting: { asks: num(waiting.asks) ?? 0, heldCalls: num(waiting.held_calls) ?? 0,
                   requests: num(waiting.requests) ?? 0, total: num(waiting.total) ?? 0 },
        turnStartedAt: parseTime(row.turn_started_at), lastActiveAt: parseTime(row.last_active_at),
        failed: failed && { message: String(failed.message ?? ""), at: parseTime(failed.at) },
        waking: waking && { at: parseTime(waking.at), why: String(waking.why ?? "") },
        raw: row,
      };
    }),
    readAt: parseTime(raw.read_at),
    raw,
  };
}

/** A tool an MCP server offers: its `name` and `description`, as the server lists it. */
export interface ToolServerTool {
  name: string;
  description: string | null;
}

/**
 * What's wrong with an agent's MCP server, as a connection's `disconnected` says it: `reason` (`needs_sign_in`,
 * `signed_out`, `refused`, `revoked` or `failed`), NoClick's one line (`message`), the server's own words where it
 * said any (`providerSaid`), since when (`since`, null for a server never signed in to) and what to do (`nextStep`).
 */
export interface ToolServerProblem {
  reason: string;
  message: string;
  providerSaid: string | null;
  since: Date | null;
  nextStep: string | null;
}

/** One MCP server a conversation's coding harness reaches its tools on, as it stands. */
export interface ToolServer {
  name: string;
  /** `connected`, `connecting` (its handshake hasn't finished) or `failed`. */
  status: "connected" | "connecting" | "failed";
  /** How many tools it offers the model, where the harness says (null where it doesn't). */
  toolCount: number | null;
  /** Why it failed, in the harness's or the server's words. */
  error: string | null;
  /** Each tool it offers, where the harness lists them (Claude Code and Codex do; null where it doesn't). */
  tools: ToolServerTool[] | null;
}

function toTools(raw: unknown): ToolServerTool[] {
  return (Array.isArray(raw) ? raw : []).filter((t) => t && typeof t === "object").map((t) => {
    const tool = asObject(t);
    return { name: String(tool.name ?? ""), description: str(tool.description) };
  });
}

/**
 * The tool servers of a conversation: read live from its running harness (`source: "live"`), else as its last turn
 * found them (`"last_turn"`), else none yet (`"none"`). `reconnect` says whether one server's handshake can be done
 * again in place (`scope: "server"`), only all of them at once (`"all"`), or not, and why not.
 */
export interface ToolServers {
  servers: ToolServer[];
  source: "live" | "last_turn" | "none";
  checkedAt: Date | null;
  reconnect: { available: boolean; scope: "server" | "all" | null; why: string | null };
  raw: JsonObject;
}

/**
 * An MCP server an agent has as tools: a step of its automation (`id`, what `removeToolServer` takes), reached at its
 * `url` (on `host`) over `transport` (`http` or `sse`), letting its client in as `signIn` says (`none`, `key`: the
 * `headers` named, whose values are never read back, or `browser`: a person's sign-in, `signedIn` once one is set).
 * Its `status`: `connected`, `needs_sign_in` (nothing lets it in yet), `signed_out` (its sign-in was refused or
 * revoked), `failed` (its last run found no tools), `unchecked` (no run since it was last let in) or, read for a
 * conversation, `connecting` (its harness's handshake hasn't finished), with what's wrong in `problem`; the `tools` it
 * offered and when that was found (`checkedAt`); whether that conversation's harness can connect it again in place now
 * (`reconnectable`); and what draws it (`icon`: `{ integration }`, `{ mark: "noclick" }`, or null: draw its name's
 * first letter). Listed in the order they were added.
 */
export interface AgentToolServer {
  id: string;
  name: string;
  url: string | null;
  transport: "http" | "sse";
  signedIn: boolean;
  headers: string[];
  raw: JsonObject;
  agentId: string | null;
  host: string | null;
  signIn: "none" | "key" | "browser";
  status: "connected" | "connecting" | "needs_sign_in" | "signed_out" | "failed" | "unchecked";
  problem: ToolServerProblem | null;
  tools: ToolServerTool[];
  icon: { integration: string } | { mark: "noclick" } | null;
  checkedAt: Date | null;
  reconnectable: boolean;
  /**
   * Mint a link where someone signs in to this server (`signIn` `browser`), the first time or again: NoClick's MCP
   * sign-in for it, which becomes the server's sign-in once it lands. `sendTo` also delivers it. A server that takes
   * a key rejects with `Conflict`: give it headers with `agent.updateToolServer`. `await link.wait()` resolves to
   * this server as it stands then.
   */
  connectLink(options?: LinkOptions): Promise<ConnectLink<AgentToolServer>>;
}

/** @internal */
export function toAgentToolServer(
  raw: JsonObject, connectLink: (server: AgentToolServer, options: LinkOptions) => Promise<ConnectLink<AgentToolServer>>,
): AgentToolServer {
  const problem = raw.problem && typeof raw.problem === "object" ? asObject(raw.problem) : null;
  const icon = raw.icon && typeof raw.icon === "object" ? asObject(raw.icon) : null;
  const server: AgentToolServer = {
    id: String(raw.id ?? ""), name: String(raw.name ?? ""), url: str(raw.url),
    transport: raw.transport === "sse" ? "sse" : "http", signedIn: raw.signed_in === true,
    headers: Array.isArray(raw.headers) ? raw.headers.map(String) : [], raw,
    agentId: str(raw.agent_id), host: str(raw.host),
    signIn: (str(raw.sign_in) ?? "none") as AgentToolServer["signIn"],
    status: (str(raw.status) ?? "unchecked") as AgentToolServer["status"],
    problem: problem && {
      reason: String(problem.reason ?? ""), message: String(problem.message ?? ""),
      providerSaid: str(problem.provider_said), since: parseTime(problem.since), nextStep: str(problem.next_step),
    },
    tools: toTools(raw.tools),
    icon: icon && (typeof icon.integration === "string" ? { integration: icon.integration }
      : icon.mark === "noclick" ? { mark: "noclick" } : null),
    checkedAt: parseTime(raw.checked_at), reconnectable: raw.reconnectable === true,
    connectLink: (options = {}) => connectLink(server, options),
  };
  return server;
}

/** @internal */
export function toToolServers(raw: JsonObject): ToolServers {
  const reconnect = asObject(raw.reconnect);
  return {
    servers: (Array.isArray(raw.data) ? raw.data : []).map((s) => {
      const server = asObject(s);
      return {
        name: String(server.name ?? ""), status: (str(server.status) ?? "failed") as ToolServer["status"],
        toolCount: num(server.tool_count), error: str(server.error),
        tools: server.tools == null ? null : toTools(server.tools),
      };
    }),
    source: (str(raw.source) ?? "none") as ToolServers["source"], checkedAt: parseTime(raw.checked_at),
    reconnect: {
      available: reconnect.available === true, scope: (str(reconnect.scope) ?? null) as ToolServers["reconnect"]["scope"],
      why: str(reconnect.why),
    },
    raw,
  };
}
