/** Agents: hosted agents you message by name. */

import { AgentMemory, AgentSandbox, AgentWorkspace, ShareLink, toCodingAgents } from "./agentExtras.ts";
import { TrashItem, trashed } from "./trash.ts";
import { wireSettings } from "./approval.ts";
import type { ScopeApprovals } from "./approval.ts";
import { attachmentIds, toAttachment, toAttachments, uploadFile } from "./attachment.ts";
import type { Attachment, FileInput, UploadOptions } from "./attachment.ts";
import type { AgentEvent, CodingAgents, Rehearsal } from "./agentExtras.ts";
import {
  conversationChanges, toAgentStates, toAuthor, toCommandResult, toContext, toConversationSettings, toForkedFrom,
  toAgentToolServer, toLastMessage, toRevert, toToolServers, toUsage,
} from "./agentConversations.ts";
import type {
  AgentSpeed, AgentStates, CommandResult, ConversationChanges, ConversationContext, ConversationRevert,
  AgentToolServer, ConversationSettings, ConversationUsage, ForkedFrom, LastMessage, MessageAuthor, ToolServers,
} from "./agentConversations.ts";
import type { BrowserProfile } from "./browser.ts";
import type { Card } from "./card.ts";
import type { ChannelAuthor } from "./channel.ts";
import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { ConnectLink, linkBody, modelConnectionRef, toolRefs } from "./connection.ts";
import type { Connection, ConnectionStatus, LinkOptions, ToolRef } from "./connection.ts";
import type { UsedBy } from "./database.ts";
import { Job, Wakeup, updatesWire } from "./coordination.ts";
import type { UpdateSpec, WakeupStatus } from "./coordination.ts";
import { Cron } from "./cron.ts";
import { Conflict, NotFound } from "./errors.ts";
import { Inbox } from "./inbox.ts";
import type { Machine } from "./machine.ts";
import {
  ApiObject, asList, asObject, checkUnchanged, compact, createNamed, csv, defined, givesFields, isoTime, listAll, listPage, num, parseTime,
  readScope, refId, str,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import type { OperationStatus } from "./operation.ts";
import { secretIdList } from "./secret.ts";
import { Terminal } from "./terminal.ts";
import type { SecretRef } from "./secret.ts";
import { resolveScope } from "./scope.ts";
import type { UserFilter, UserOption, UserRef } from "./scope.ts";
import type { RegionName } from "./region.ts";
import type { RepoCheckout } from "./repo.ts";
import type { NetworkAccess } from "./sandbox.ts";
import { DEFINED_TRIGGER_KINDS, namedBy, toAgentTrigger, triggerKey } from "./trigger.ts";
import type { AgentTrigger, TriggerChanges, TriggerDefinition } from "./trigger.ts";
import { volumeMountIds } from "./volume.ts";
import type { VolumeRef } from "./volume.ts";
import { memoryLinks } from "./memory.ts";
import { skillLinks } from "./skill.ts";
import type { SkillRef } from "./skill.ts";
import type { MemoryRef } from "./memory.ts";

/**
 * What an agent's model calls on your own key or plan (its `modelConnection`) used: tokens in
 * (`cachedTokens` of them read from the provider's cache), tokens out, and what they come to in US
 * dollars at the provider's list price. NoClick doesn't bill these calls; this is how you see them.
 * A coding harness on a plan counts what it reports, priced as if it ran on a key.
 */
export interface ModelUsage {
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number;
  usd: number;
  raw: JsonObject;
}

function toModelUsage(raw: unknown): ModelUsage | null {
  if (!raw || typeof raw !== "object") return null;
  const body = raw as JsonObject;
  return {
    inputTokens: num(body.input_tokens) ?? 0,
    outputTokens: num(body.output_tokens) ?? 0,
    cachedTokens: num(body.cached_tokens) ?? 0,
    usd: num(body.usd) ?? 0,
    raw: body,
  };
}

/**
 * One of a coding harness's own commands to run instead of a message (`compact`, `review`, a custom command, a
 * skill), as `agent.commands(conversation)` lists them: `name` without the slash, `arguments` what follows it.
 */
export interface AgentCommandInput {
  name: string;
  arguments?: string;
}

/**
 * How a message sent while the agent works on a turn (it takes one at a time) is delivered: `steer` puts it into that
 * turn when it's in the same conversation (its operation answers with that turn's reply; else it's an ordinary
 * message), `queue` (or omitted) runs it as the agent's next turn.
 */
export type MessageDelivery = "steer" | "queue";

/** Where a harness command comes from: the harness itself, your own (a project's or plugin's), a skill, an MCP prompt. */
export type AgentCommandSource = "harness" | "custom" | "skill" | "mcp";

/** One command a conversation's harness offers. */
export interface AgentCommand {
  name: string;
  description: string;
  /** What its arguments look like (`<instructions>`, `[env]`), empty when it names none. */
  argumentHint: string;
  source: AgentCommandSource;
  /** Other names it answers to. */
  aliases: string[];
}

/** One skill a conversation's harness has. */
export interface AgentSkill {
  name: string;
  description: string;
}

/**
 * What a conversation's harness offers a person to run, read from the harness itself (Claude Code, Codex, OpenCode,
 * OpenClaw; Hermes Agent lists skills and runs no commands). Kept per agent and harness, so a stopped sandbox's last
 * list still answers: `asOf` says when it was read and `readFrom` whose sandbox read it (both null before its
 * sandbox ever started: send a message first).
 */
export interface AgentCommands {
  harness: string;
  commands: AgentCommand[];
  skills: AgentSkill[];
  /** `commands`, `skills`, `compact`, `review`, `goal`, `init`, `steer`, `queue`. */
  capabilities: Record<string, boolean>;
  /** What NoClick can't run on this harness, and why. */
  notSupported: Record<string, string>;
  /**
   * Commands NoClick never runs from a chat, whatever the harness offers: those that change what NoClick sets up and
   * guards for the agent (its MCP servers, permissions, credentials, model provider, process or settings files:
   * Claude Code's `/config`, OpenClaw's owner commands).
   */
  withheld: string[];
  /**
   * The harness's commands NoClick has a control of its own for, each with that control (`model`, `effort`, `new`,
   * `usage`, `context`, `plan`, `delivery`, `ask`): Claude Code's `/model` is the model picker, its `/clear` a new
   * session. A page offers the control in their place.
   */
  mapped: { name: string; to: string }[];
  asOf: Date | null;
  readFrom: "this_conversation" | "another_conversation" | null;
  raw: JsonObject;
}

/** When a conversation's coding harness asks a person before acting (`full-access`, the default, asks nothing). */
export type PermissionMode = "approval-required" | "auto-accept-edits" | "auto" | "full-access";
/** The VM a Docker agent works in: `small` (2 CPUs, 4 GB), `medium` (4 CPUs, 8 GB) or `large` (8 CPUs, 16 GB). */
export type SandboxSize = "small" | "medium" | "large";
/**
 * How a coding agent may turn app testing on (Docker in its sandbox, for a task that runs the app or its tests against
 * a real database): `by_itself` turns it on when a task needs it and off once it's done, saying each in its chat;
 * `ask_first` asks the account's owner in the chat each time; `never`.
 */
export type AppTesting = "by_itself" | "ask_first" | "never";

/**
 * How an agent moves to another of its owner's model connections when its plan runs out, or when it's told to.
 * `switch` (the default): by itself, to any of the owner's own Claude or ChatGPT plans freely, and to a paid key (an
 * API key, NoClick's key at cost) only on the owner's say-so. `stay`: it never leaves its connection, and at a limit
 * waits for the reset. `allowed`: the connections (names) it moves between freely, paid keys included; null for the
 * default rule.
 */
export interface ModelSwitching {
  mode?: "switch" | "stay";
  /** The connections it moves between freely, tried in this order; null: the default rule. */
  allowed?: string[] | null;
  /** `same` (the default): only to a connection that runs its own harness, else it waits; `any`: another too. */
  harness?: "same" | "any";
}

/** `modelSwitching` as it's set: its allowed connections by name or as `Connection`s. Only what's given changes. */
export interface ModelSwitchingChange {
  mode?: "switch" | "stay";
  allowed?: (string | Connection)[] | null;
  harness?: "same" | "any";
}

/** While a plan's limit has an agent on another connection: the one it left, and when that one is back. */
export interface SwitchedFrom {
  connection: string;
  name: string | null;
  window: string | null;
  resetsAt: string | null;
}

/**
 * The owner's say-so for an agent's paid keys: which (`connections`, null for any), `once` or `standing`, and how they
 * gave it (`source`: `cited`, words of theirs the agent cited, `evidence` saying where and when, the quote and a link;
 * `asked`, their tap; `owner`, their own call).
 */
export interface ModelSwitchGrant {
  id: string;
  connections: string[] | null;
  scope: "once" | "standing";
  source: "cited" | "asked" | "owner";
  evidence: JsonObject;
  grantedBy: JsonObject;
  usedAt: string | null;
  revokedAt: string | null;
  createdAt: string | null;
  raw: JsonObject;
}

/** What `agent.switchModel` did: `switched`, `unchanged`, or `asked` (the owner's one tap, `requestId`). */
export interface ModelSwitchResult {
  status: "switched" | "unchanged" | "asked";
  connection: string;
  harness?: string;
  model?: string;
  pays?: "plan" | "per_use" | "at_cost";
  requestId?: string;
  message?: string;
  raw: JsonObject;
}

/** `modelSwitching` on the wire: only what's given (an update changes only those), each allowed connection by its ref. */
async function switchingWire(value: ModelSwitchingChange | null | undefined, scope: UserOption): Promise<JsonObject | null | undefined> {
  if (value === undefined || value === null) return value;
  const wire: JsonObject = {};
  if (value.mode !== undefined) wire.mode = value.mode;
  if (value.harness !== undefined) wire.harness = value.harness;
  if (value.allowed !== undefined) {
    wire.allowed = value.allowed === null ? null
      : await Promise.all(value.allowed.map((c) => modelConnectionRef(c, scope))) as string[];
  }
  return wire;
}

function toModelSwitchGrant(raw: JsonObject): ModelSwitchGrant {
  return {
    id: String(raw.id), connections: (raw.connections as string[] | null) ?? null,
    scope: raw.scope as ModelSwitchGrant["scope"], source: raw.source as ModelSwitchGrant["source"],
    evidence: (raw.evidence as JsonObject) ?? {}, grantedBy: (raw.granted_by as JsonObject) ?? {},
    usedAt: (raw.used_at as string | null) ?? null, revokedAt: (raw.revoked_at as string | null) ?? null,
    createdAt: (raw.created_at as string | null) ?? null, raw,
  };
}

/** A person's answer to what a coding harness asks (ACP's `session/request_permission` options, and cancel). */
export type RequestDecision = "allow_once" | "allow_always" | "reject_once" | "cancel";

/**
 * What a coding harness asks a person mid-turn: an `approval` (`action`: `command`, `edit`, `plan` (leaving Claude
 * Code's plan mode, its `plan` text), `read`, `fetch` or `tool`; `title` in a line, `detail` the command or the
 * files) or a `question` (`questions`, each `{id, header, question, options, multi_select}`). `status` is `pending`
 * until it's `answered`, `expired` (nobody answered in time: declined) or `canceled` (its turn stopped).
 */
export interface HarnessRequest {
  id: string;
  kind: "approval" | "question";
  status: "pending" | "answered" | "expired" | "canceled";
  action: string | null;
  title: string | null;
  detail: string | null;
  plan: string | null;
  questions: JsonObject[];
  options: { optionId: string; name: string; kind: string }[];
  answer: JsonObject | null;
  /** What it was answered with (`allow_once`, `reject_once`, …) and when; null until it's answered. */
  decision: string | null;
  answeredAt: Date | null;
  /** Why it was closed unanswered: its turn ended first (failed, stopped, timed out). */
  canceledReason: string | null;
  operationId: string | null;
  createdAt: Date | null;
  expiresAt: Date | null;
  raw: JsonObject;
}

function toHarnessRequest(raw: JsonObject): HarnessRequest {
  const listed = (value: unknown) => (Array.isArray(value) ? (value as JsonObject[]) : []);
  return {
    id: str(raw.id) ?? "",
    kind: (str(raw.kind) ?? "approval") as HarnessRequest["kind"],
    status: (str(raw.status) ?? "pending") as HarnessRequest["status"],
    action: str(raw.action),
    title: str(raw.title),
    detail: str(raw.detail),
    plan: str(raw.plan),
    questions: listed(raw.questions),
    options: listed(raw.options).map((o) => ({ optionId: String(o.option_id), name: String(o.name), kind: String(o.kind) })),
    answer: raw.answer ? asObject(raw.answer) : null,
    decision: str(raw.decision),
    answeredAt: parseTime(raw.answered_at),
    canceledReason: str(raw.canceled_reason),
    operationId: str(raw.operation_id),
    createdAt: parseTime(raw.created_at),
    expiresAt: parseTime(raw.expires_at),
    raw,
  };
}

function toCommands(raw: JsonObject): AgentCommands {
  const listed = (value: unknown) => (Array.isArray(value) ? (value as JsonObject[]) : []);
  return {
    harness: str(raw.harness) ?? "",
    commands: listed(raw.commands).map((c) => ({
      name: String(c.name),
      description: str(c.description) ?? "",
      argumentHint: str(c.argument_hint) ?? "",
      source: (str(c.source) ?? "custom") as AgentCommandSource,
      aliases: Array.isArray(c.aliases) ? c.aliases.map(String) : [],
    })),
    skills: listed(raw.skills).map((s) => ({ name: String(s.name), description: str(s.description) ?? "" })),
    capabilities: Object.fromEntries(Object.entries(asObject(raw.capabilities)).map(([k, v]) => [k, v === true])),
    notSupported: Object.fromEntries(Object.entries(asObject(raw.not_supported)).map(([k, v]) => [k, String(v)])),
    withheld: Array.isArray(raw.withheld) ? raw.withheld.map(String) : [],
    mapped: listed(raw.mapped).map((m) => ({ name: String(m.name), to: String(m.to) })),
    asOf: parseTime(raw.as_of),
    readFrom: (str(raw.read_from) as AgentCommands["readFrom"]) ?? null,
    raw,
  };
}

/** The wire body of a message, or of a command sent in its place. */
function messageBody(text: string | null, options: { conversation?: string | null; files?: (Attachment | string)[];
  command?: AgentCommandInput; delivery?: MessageDelivery }): JsonObject {
  if ((text === null || text === undefined) === !options.command) {
    throw new TypeError("Send text or a command, not both.");
  }
  const command = options.command ? compact({ name: options.command.name, arguments: options.command.arguments }) : undefined;
  return compact({
    text: text ?? undefined, command, delivery: options.delivery, conversation: options.conversation,
    attachments: attachmentIds(options.files),
  });
}

/** The agent's answer to one message. */
export interface AgentReply {
  text: string;
  /** Pass back as `conversation` to continue the same thread. */
  conversation: string | null;
  /**
   * The turn's tool calls, each `{tool, arguments, result, is_error, created_at}` as `history()` shows a reply's
   * (a failed call's `result` is its error); a coding harness's own steps add `source: "harness"` and the rest of a
   * `AgentStep` (its `id`, `kind`, `command`, `path`, `output`, `exit_code`, `duration_ms`, `diffs`), in the order
   * they happened.
   */
  toolCalls: JsonObject[];
  /** `toolCalls` as `AgentStep`s. */
  steps: AgentStep[];
  operationId: string | null;
  /** The turn's model calls on your own key or plan (null on NoClick's key, whose cost is its `cost_usd`). */
  modelUsage?: ModelUsage | null;
  /**
   * The limit that ended the turn before it finished (its `turnLimits`), its text then saying where the work
   * stands; null when the agent answered.
   */
  endedBy?: TurnLimitName | null;
  /** What a coding harness's turn did (null for a turn with no harness steps). */
  summary?: TurnSummary | null;
  /** Its harness steps' folds, in order. */
  groups?: StepGroup[];
  raw: JsonObject;
}

/** What can end a turn before the agent answers: its steps, its spend or its minutes (`turnLimits`). */
export type TurnLimitName = "steps" | "spend" | "time";

/**
 * How far one turn of an `sdk` agent goes, each limit left out at its default: `steps` (model calls; 30, at most
 * 200), `usd` (what they cost; $1, at most $25) and `minutes` (15, at most 60).
 */
export interface TurnLimits {
  steps?: number;
  usd?: number;
  minutes?: number;
}

/** `turnLimits` on the wire: the limits given, in the order the agent keeps them (undefined: the defaults). */
function limitsWire(limits: TurnLimits | null | undefined): JsonObject | undefined {
  const given = compact({ steps: limits?.steps, usd: limits?.usd, minutes: limits?.minutes });
  return Object.keys(given).length ? given : undefined;
}

/** `active`; `awaiting_human` while a turn waits on a person; `handed_off` while a person has it. */
export type ConversationStatus = "active" | "awaiting_human" | "handed_off";

/** One thread with an agent (a user's, or the account's own). */
export interface Conversation {
  /** Pass as `conversation` to continue it, or to `history()`. */
  conversation: string;
  userId: string | null;
  title: string | null;
  preview: string | null;
  turns: number | null;
  costUsd: number | null;
  lastActivity: Date | null;
  /** `active`, `awaiting_human` (a turn waits on a person: its question, a held call, a sign-in) or `handed_off`. */
  status: ConversationStatus | null;
  /** Who a `handed_off` conversation is with: the person's email or phone. */
  handedOffTo: string | null;
  /** Its model calls on your own key or plan, all turns together (null on NoClick's key). */
  modelUsage: ModelUsage | null;
  /** Its newest message (null before any). */
  lastMessage: LastMessage | null;
  /** Who is in it: the people who wrote in it, the thread's own person first. */
  people: MessageAuthor[];
  archived: boolean;
  /** The conversation it was forked from, and at which message. */
  forkedFrom: ForkedFrom | null;
  /** A fork's: `native` when the agent reads the copied thread in its own history, `context` when carried as context. */
  agentReads: "native" | "context" | null;
  /** Whether it's the agent's session now, the one conversation everyone talking to it shares; the others can be resumed. */
  active: boolean;
  raw: JsonObject;
}

function toConversation(raw: JsonObject): Conversation {
  return {
    conversation: String(raw.conversation),
    userId: str(raw.user_id),
    title: str(raw.title),
    preview: str(raw.preview),
    turns: num(raw.turns),
    costUsd: num(raw.cost_usd),
    lastActivity: parseTime(raw.last_activity),
    status: str(raw.status) as ConversationStatus | null,
    handedOffTo: str(raw.handed_off_to),
    modelUsage: toModelUsage(raw.model_usage),
    lastMessage: toLastMessage(raw.last_message),
    people: (Array.isArray(raw.people) ? raw.people : []).map(toAuthor).filter((a): a is MessageAuthor => a !== null),
    archived: raw.archived === true,
    forkedFrom: toForkedFrom(raw.forked_from),
    agentReads: str(raw.agent_reads) as Conversation["agentReads"],
    active: raw.active === true,
    raw,
  };
}

/** A step's kind: a coding harness's shell `command`, file `edit`, `read` or `search`, or any other `tool` (NoClick's own among them). */
export type AgentStepKind = "command" | "edit" | "read" | "search" | "tool";

/** What a coding harness's step did, as NoClick judged it from what it runs. */
export type StepCategory = "read" | "search" | "list" | "edit" | "test" | "install" | "run" | "tool";

/**
 * What a coding harness's step did, in words, in its tense: running as it runs (`Reading attachments.py`), done once
 * it ended (`Read attachments.py lines 55-110`). `text` is the whole line; `verb`, `object` and `detail` its parts.
 */
export interface StepLabel {
  text: string;
  verb: string | null;
  object: string | null;
  detail: string | null;
}

/**
 * A test run's counts, read from what it printed (pytest, vitest, jest, node's runner, cargo): as it streams (`done`
 * false; `total` once it's known) and at its end, and in words (`label`: `161 passed`, `2 of 43 failed`, `64 of 161`).
 */
export interface StepTests {
  passed: number;
  failed: number;
  skipped: number;
  total: number | null;
  done: boolean;
  label: string;
}

/** How far a step is where it reported a count: `done` of `total`. A step that names no total has none. */
export interface StepProgress {
  done: number;
  total: number;
}

/** The lines an edit's diffs added and removed. */
export interface DiffStat {
  added: number;
  removed: number;
}

/**
 * Reads, searches and listings a coding harness made in a row, folded into one line as Claude Code folds them (never
 * a failed step): `label` (`Read 6 files, searched for 3 patterns`; `Reading …` while one runs), its `counts`
 * (`read`: files, `search`, `list`), its steps (`stepIds`) and `parent`, the subagent call whose steps they are. A
 * group no longer standing (a step left it) has no `stepIds`.
 */
export interface StepGroup {
  id: string;
  label: string | null;
  counts: Record<string, number>;
  stepIds: string[];
  running: boolean;
  parent: string | null;
}

/** A file a turn changed: the lines its edits added and removed, and `how` where not by an edit tool (`sed`, `script`). */
export interface ChangedFile {
  path: string;
  added: number;
  removed: number;
  how: string[];
}

/** The files a turn changed (`label`: `Changed 5 files`), and how many only by a script or a command (`byScript`). */
export interface TurnChanges {
  label: string;
  files: ChangedFile[];
  added: number;
  removed: number;
  byScript: number;
}

/**
 * What a coding harness's turn did: `label` (`Read 9 files, searched 7 times`), its steps' `counts` by category, how
 * many `failed`, what it `changed` and its last test run's counts (`tests`).
 */
export interface TurnSummary {
  label: string | null;
  counts: Record<string, number>;
  failed: number;
  changed: TurnChanges | null;
  tests: StepTests | null;
}

const counts = (value: unknown): Record<string, number> =>
  Object.fromEntries(Object.entries(value && typeof value === "object" ? asObject(value) : {}).map(([k, v]) => [k, Number(v ?? 0)]));

/** @internal */
export function toStepLabel(value: unknown): StepLabel | null {
  if (!value || typeof value !== "object") return null;
  const raw = asObject(value);
  return raw.text ? { text: String(raw.text), verb: str(raw.verb), object: str(raw.object), detail: str(raw.detail) } : null;
}

/** @internal */
export function toStepTests(value: unknown): StepTests | null {
  if (!value || typeof value !== "object") return null;
  const raw = asObject(value);
  return {
    passed: num(raw.passed) ?? 0, failed: num(raw.failed) ?? 0, skipped: num(raw.skipped) ?? 0, total: num(raw.total),
    done: raw.done === true, label: str(raw.label) ?? "",
  };
}

/** @internal */
export function toStepProgress(value: unknown): StepProgress | null {
  if (!value || typeof value !== "object") return null;
  const raw = asObject(value);
  const total = num(raw.total);
  return total ? { done: num(raw.done) ?? 0, total } : null;
}

/** @internal */
export function toDiffStat(value: unknown): DiffStat | null {
  if (!value || typeof value !== "object") return null;
  const raw = asObject(value);
  return { added: num(raw.added) ?? 0, removed: num(raw.removed) ?? 0 };
}

/** @internal */
export function toStepGroup(value: unknown): StepGroup | null {
  if (!value || typeof value !== "object") return null;
  const raw = asObject(value);
  if (!raw.id) return null;
  return {
    id: String(raw.id), label: str(raw.label), counts: counts(raw.counts),
    stepIds: Array.isArray(raw.step_ids) ? raw.step_ids.map(String) : [], running: raw.running === true,
    parent: str(raw.parent),
  };
}

/** @internal */
export function toStepGroups(value: unknown): StepGroup[] {
  return (Array.isArray(value) ? value : []).map(toStepGroup).filter((g): g is StepGroup => g !== null);
}

/** @internal */
export function toTurnSummary(value: unknown): TurnSummary | null {
  if (!value || typeof value !== "object") return null;
  const raw = asObject(value);
  const changed = raw.changed && typeof raw.changed === "object" ? asObject(raw.changed) : null;
  return {
    label: str(raw.label), counts: counts(raw.counts), failed: num(raw.failed) ?? 0,
    changed: changed && {
      label: str(changed.label) ?? "",
      files: (Array.isArray(changed.files) ? (changed.files as JsonObject[]) : []).map((f) => ({
        path: str(f.path) ?? "", added: num(f.added) ?? 0, removed: num(f.removed) ?? 0,
        how: Array.isArray(f.how) ? f.how.map(String) : [],
      })),
      added: num(changed.added) ?? 0, removed: num(changed.removed) ?? 0, byScript: num(changed.by_script) ?? 0,
    },
    tests: toStepTests(raw.tests),
  };
}

/** One file a step changed: a unified diff, or a new file's whole content (`change` `add`), at most 16,384 characters. */
export interface AgentStepDiff {
  path: string;
  change: "add" | "update" | "delete" | (string & {}) | null;
  diff: string;
}

/**
 * One step of a turn as its reply keeps it (`Message.steps`, `AgentReply.steps`). A coding harness's own step
 * (`source` `harness`) has the fields its live events showed as it ran, under its `callId`: its `tool_call` (`kind`,
 * `tool`, `arguments`, `command`, `path`, `query`), its command's `output` (the last 4,096 characters; what came
 * before reads `[… N characters not shown …]`), its `tool_result` (`exitCode`, `durationMs`, `isError`, `result`)
 * and each `diff`. A turn keeps at most 200 such steps and 256,000 characters of their output and diffs, the
 * newest steps' first. NoClick's own tool calls are `kind` `tool`, with no `callId`.
 *
 * What a harness's step did, in words, judged once by NoClick as it ran: its `category`, its `label` and where that
 * came from (`labelSource`: the harness's own `description`, Codex's `actions`, or `derived` from the command), the
 * command as shown (`displayCommand`: no `cd` into where it runs, heredocs shortened), a read's `lines`, how many lines
 * it printed (`outputLines`), a test run's `tests`, a count it reported (`progress`), an edit's `diffStat`, whether it
 * `failed` (a search that found nothing didn't) and the `group` it folds into (`StepGroup.id`).
 */
export interface AgentStep {
  kind: AgentStepKind;
  tool: string;
  callId: string | null;
  source: "harness" | (string & {}) | null;
  arguments: JsonObject;
  command: string | null;
  path: string | null;
  query: string | null;
  output: string | null;
  exitCode: number | null;
  durationMs: number | null;
  isError: boolean;
  result: unknown;
  diffs: AgentStepDiff[];
  createdAt: Date | null;
  category: StepCategory | null;
  label: StepLabel | null;
  labelSource: "description" | "actions" | "derived" | null;
  displayCommand: string | null;
  lines: { from: number | null; to: number | null } | null;
  outputLines: number | null;
  tests: StepTests | null;
  progress: StepProgress | null;
  diffStat: DiffStat | null;
  failed: boolean | null;
  group: string | null;
  /** The files a read or an edit named, as it named them. */
  paths: string[];
  raw: JsonObject;
}

const STEP_KINDS: readonly string[] = ["command", "edit", "read", "search", "tool"];

/** @internal A reply's tool call, or a coding harness's step, as its JSON shows it. */
export function toAgentStep(raw: JsonObject): AgentStep {
  const kind = str(raw.kind);
  return {
    kind: (kind && STEP_KINDS.includes(kind) ? kind : "tool") as AgentStepKind,
    tool: str(raw.tool) ?? "",
    callId: str(raw.id),
    source: str(raw.source),
    arguments: raw.arguments ? asObject(raw.arguments) : {},
    command: str(raw.command),
    path: str(raw.path),
    query: str(raw.query),
    output: str(raw.output),
    exitCode: num(raw.exit_code),
    durationMs: num(raw.duration_ms),
    isError: raw.is_error === true,
    result: raw.result ?? null,
    diffs: Array.isArray(raw.diffs)
      ? (raw.diffs as JsonObject[]).map((d) => ({ path: str(d.path) ?? "", change: str(d.kind), diff: str(d.diff) ?? "" }))
      : [],
    createdAt: parseTime(raw.created_at),
    category: str(raw.category) as StepCategory | null,
    label: toStepLabel(raw.label),
    labelSource: str(raw.label_source) as AgentStep["labelSource"],
    displayCommand: str(raw.display_command),
    lines: raw.lines && typeof raw.lines === "object"
      ? { from: num(asObject(raw.lines).from), to: num(asObject(raw.lines).to) } : null,
    outputLines: num(raw.output_lines),
    tests: toStepTests(raw.tests),
    progress: toStepProgress(raw.progress),
    diffStat: toDiffStat(raw.diff_stat),
    failed: typeof raw.failed === "boolean" ? raw.failed : null,
    group: str(raw.group),
    paths: Array.isArray(raw.paths) ? raw.paths.map(String) : [],
    raw,
  };
}

function toolCallsOf(value: unknown): JsonObject[] {
  return Array.isArray(value) ? (value as JsonObject[]) : [];
}

/** @internal One server-sent event of a streamed turn or a watched conversation. */
export function toAgentEvent(type: string, data: JsonObject): AgentEvent {
  if (type === "done") {
    const reply: AgentReply = {
      text: str(data.text) ?? "",
      conversation: str(data.conversation),
      toolCalls: toolCallsOf(data.tool_calls),
      steps: toolCallsOf(data.tool_calls).map(toAgentStep),
      operationId: str(data.operation_id),
      modelUsage: toModelUsage(data.model_usage),
      endedBy: str(data.ended_by) as TurnLimitName | null,
      summary: toTurnSummary(data.summary),
      groups: toStepGroups(data.groups),
      raw: data,
    };
    return {
      type, text: reply.text, tool: null, arguments: null, result: null, isError: false, reply,
      role: null, held: null, status: null, file: null, files: [], toolCalls: [], approval: null, operation: null,
      via: null, data: null, trigger: null, reasoning: [], callId: null, source: null, exitCode: null, durationMs: null,
      whole: false, path: null, change: null, diff: null, count: null, stepKind: null, command: null, query: null,
      request: null, operationId: reply.operationId, messageId: null, author: null, notification: false, space: null,
      subagent: null, category: null, label: null, displayCommand: null, group: null, stepGroup: null, tests: null,
      progress: null, outputLines: null, diffStat: null, failed: null, summary: reply.summary ?? null, raw: data,
    };
  }
  return {
    type, text: str(data.text), tool: str(data.tool), arguments: data.arguments ? asObject(data.arguments) : null,
    result: data.result ?? null, isError: Boolean(data.is_error), reply: null,
    role: str(data.role) as AgentEvent["role"], held: data.held ? asObject(data.held) : null,
    status: str(data.status) as AgentEvent["status"], file: data.file ? toAttachment(asObject(data.file)) : null,
    files: toAttachments(data.files), toolCalls: toolCallsOf(data.tool_calls),
    approval: data.approval ? asObject(data.approval) : null,
    operation: data.operation ? asObject(data.operation) : null,
    via: str(data.via) as MessageVia | null, data: data.data ? asObject(data.data) : null,
    trigger: toTrigger(data.trigger), reasoning: toReasoning(data.reasoning), callId: str(data.id),
    source: str(data.source), exitCode: num(data.exit_code), durationMs: num(data.duration_ms),
    whole: data.whole === true, path: str(data.path), change: type === "diff" ? str(data.kind) : null,
    diff: str(data.diff), count: num(data.count),
    stepKind: type === "tool_call" || type === "tool_result" ? (str(data.kind) as AgentStepKind | null) : null,
    command: str(data.command), query: str(data.query), operationId: str(data.operation_id),
    request: type === "request" && data.request ? asObject(data.request) : null,
    messageId: type === "message" ? str(data.id) : null, author: type === "message" ? toAuthor(data.author) : null,
    notification: data.notification === true, space: toSpace(data.space),
    subagent: type === "message" ? toSubagent(data.subagent) : null,
    channel: type === "message" ? toMessageChannel(data.channel) : null,
    chat: type === "message" ? str(data.chat) : null,
    category: str(data.category) as StepCategory | null,
    label: toStepLabel(data.label),
    displayCommand: str(data.display_command),
    group: type === "tool_call" || type === "tool_result" ? str(data.group) : null,
    stepGroup: type === "group" ? toStepGroup(data) : null,
    tests: toStepTests(data.tests),
    progress: toStepProgress(data.progress),
    outputLines: num(data.output_lines),
    diffStat: toDiffStat(data.diff_stat),
    failed: typeof data.failed === "boolean" ? data.failed : null,
    summary: toTurnSummary(data.summary),
    raw: data,
  };
}

/** @internal A reply's reasoning lines as its JSON shows them. */
export function toReasoning(value: unknown): ReasoningLine[] {
  return Array.isArray(value)
    ? value.filter((line): line is JsonObject => !!line && typeof line === "object" && typeof (line as JsonObject).text === "string")
        .map((line) => ({ text: str(line.text) ?? "", createdAt: parseTime(line.created_at) }))
    : [];
}

/** @internal A conversation's message as its JSON shows it. */
export function toMessage(m: JsonObject): Message {
  return {
    id: str(m.id),
    author: toAuthor(m.author),
    role: str(m.role) ?? "",
    text: str(m.text) ?? "",
    createdAt: parseTime(m.created_at),
    files: toAttachments(m.files),
    toolCalls: toolCallsOf(m.tool_calls),
    steps: toolCallsOf(m.tool_calls).map(toAgentStep),
    operationId: str(m.operation_id),
    via: str(m.via) as MessageVia | null,
    data: m.data ? asObject(m.data) : null,
    trigger: toTrigger(m.trigger),
    reasoning: toReasoning(m.reasoning),
    command: m.command ? { name: String(asObject(m.command).name), arguments: str(asObject(m.command).arguments) ?? "" } : null,
    notification: m.notification === true,
    space: toSpace(m.space),
    subagent: toSubagent(m.subagent),
    channel: toMessageChannel(m.channel),
    chat: str(m.chat),
    summary: toTurnSummary(m.summary),
    groups: toStepGroups(m.groups),
    raw: m,
  };
}

/**
 * A connection the agent's user gave it at run time (it asked with its `request_connection` tool,
 * within `canRequest`). `status` is `requested` until the user connects, then `active`;
 * `operations` null means every operation.
 */
export interface AgentGrant {
  id: string;
  connection: string;
  integration: string;
  operations: string[] | null;
  status: "requested" | "active";
  reason: string | null;
  conversation: string | null;
  createdAt: Date | null;
  grantedAt: Date | null;
  raw: JsonObject;
}

function toGrant(raw: JsonObject): AgentGrant {
  return {
    id: String(raw.id),
    connection: String(raw.connection),
    integration: String(raw.integration),
    operations: Array.isArray(raw.operations) ? raw.operations.map(String) : null,
    status: raw.status as AgentGrant["status"],
    reason: str(raw.reason),
    conversation: str(raw.conversation),
    createdAt: parseTime(raw.created_at),
    grantedAt: parseTime(raw.granted_at),
    raw,
  };
}

/**
 * How a `user` message reached the agent when not through the API: a text to NoClick's number on `whatsapp` or
 * `imessage`, said on a phone `call`, or `email` to one of its inboxes.
 */
export type MessageVia = "whatsapp" | "imessage" | "call" | "email";

/**
 * What started the turn of a `user` message no person sent: a trigger (`kind` is its kind: `webhook`, `event`,
 * `cron`, `platform` or `queue`), a wake-up (`wakeup`), or NoClick carrying on once app testing changed
 * (`app_testing`), with its `id` and `title`; a NoClick event's (`platform`) has its `event` (`{id, type, data}`).
 */
export interface MessageTrigger {
  kind: string;
  id: string;
  title?: string | null;
  event?: { id: string; type: string; data: JsonObject } | null;
}

/** @internal */
export function toTrigger(value: unknown): MessageTrigger | null {
  return value && typeof value === "object" && typeof (value as JsonObject).kind === "string"
    ? (value as unknown as MessageTrigger)
    : null;
}

/**
 * The space a notification passes news on from: a space's NoClick alerted the person, or answered a question their
 * NoClick asked it. `label` is what that NoClick goes by outside its space ("NoClick · Launch").
 */
export interface MessageSpace {
  workspaceId: string;
  name: string;
  label: string;
}

/** The coding harness's subagent a `user` message was written for (`AgentConversation.messageSubagent`): the harness's
 *  call that runs it (`id`, its step's id) and what it was asked (`title`). */
export interface MessageSubagent {
  id: string;
  title: string;
}

/** A post a channel's turn delivered (`MessageChannel.posts`): who wrote it, as the channel names them, its words (cut
 *  at 2,000 characters), when, the thread it's in, and its files' names. */
export interface MessageChannelPost {
  id: string;
  author: ChannelAuthor;
  text: string;
  createdAt: Date | null;
  threadId: string | null;
  files: { name: string; mimeType: string | null }[];
}

/**
 * What a channel's turn delivered, as the channel has it (`Message.channel`): the channel, its space, the thread the
 * agent's reply posts in (its first post's author and words; null in the channel itself) and each post. A page draws
 * these; the message's `text` is what the agent read, with the ids and rules for replying.
 */
export interface MessageChannel {
  id: string;
  name: string;
  space: { id: string; name: string } | null;
  thread: { id: string; author: ChannelAuthor; text: string } | null;
  posts: MessageChannelPost[];
}

const toChannelAuthor = (value: unknown): ChannelAuthor => {
  const a = value && typeof value === "object" ? (value as JsonObject) : {};
  return { type: str(a.type) ?? "", id: str(a.id), name: str(a.name) };
};

/** @internal */
export function toMessageChannel(value: unknown): MessageChannel | null {
  if (!value || typeof value !== "object") return null;
  const c = value as JsonObject;
  if (typeof c.id !== "string" || !Array.isArray(c.posts)) return null;
  const space = c.space && typeof c.space === "object" ? (c.space as JsonObject) : null;
  const thread = c.thread && typeof c.thread === "object" ? (c.thread as JsonObject) : null;
  return {
    id: c.id,
    name: str(c.name) ?? "",
    space: space && typeof space.id === "string" ? { id: space.id, name: str(space.name) ?? "" } : null,
    thread: thread && typeof thread.id === "string" ? { id: thread.id, author: toChannelAuthor(thread.author), text: str(thread.text) ?? "" } : null,
    posts: c.posts
      .filter((p): p is JsonObject => !!p && typeof p === "object" && typeof (p as JsonObject).id === "string")
      .map((p) => ({
        id: str(p.id) ?? "",
        author: toChannelAuthor(p.author),
        text: str(p.text) ?? "",
        createdAt: parseTime(p.created_at),
        threadId: str(p.thread_id),
        files: Array.isArray(p.files)
          ? p.files.filter((f): f is JsonObject => !!f && typeof f === "object").map((f) => ({ name: str(f.name) ?? "", mimeType: str(f.mime_type) }))
          : [],
      })),
  };
}

/** @internal */
export function toSubagent(value: unknown): MessageSubagent | null {
  if (!value || typeof value !== "object") return null;
  const found = value as JsonObject;
  return typeof found.id === "string" ? { id: found.id, title: str(found.title) ?? "" } : null;
}

/** @internal */
export function toSpace(value: unknown): MessageSpace | null {
  if (!value || typeof value !== "object") return null;
  const space = value as JsonObject;
  return typeof space.workspace_id === "string"
    ? { workspaceId: space.workspace_id, name: str(space.name) ?? "", label: str(space.label) ?? "" }
    : null;
}

/** One short line of what a turn's model was thinking (the title of a section of its reasoning). */
export interface ReasoningLine {
  text: string;
  createdAt: Date | null;
}

/**
 * One message of a conversation: its `role` is `user`, `assistant`, `person` (someone it was handed off to) or
 * `note` (a line added with `agent.note`, with its `data`).
 */
export interface Message {
  /** Its place in the thread, which stays (a revert marks, never removes): pass it to `forkConversation` or `revertConversation`. */
  id: string | null;
  /**
   * Who sent a `user` message: `user` (one of your users, or you in a workspace you joined: `id` is that user's id),
   * `account` (the account itself, its owner or a key), `agent` (another agent's turn) or `app` (an app's code);
   * null for one no person sent (a trigger's, a wake-up's) or sent before NoClick kept it.
   */
  author: MessageAuthor | null;
  role: string;
  text: string;
  createdAt: Date | null;
  /** The files it carried (a `user` message's, sent with `files`). */
  files: Attachment[];
  /**
   * A reply's tool calls: each `{tool, arguments, result, is_error, created_at}`, as its turn's `tool_call` and
   * `tool_result` events showed it (`arguments` cut short are `{_truncated: true}`); a coding harness's reply has its
   * own steps among them, in the order they happened (`AgentStep`).
   */
  toolCalls: JsonObject[];
  /** `toolCalls` as `AgentStep`s. */
  steps: AgentStep[];
  /** The turn it belongs to (an `agent.message` operation's id; null for a message no turn sent, like a person's). */
  operationId: string | null;
  /** A reply's reasoning, as its turn's `reasoning` events showed it. */
  reasoning: ReasoningLine[];
  /** How a `user` message arrived when not through the API (null otherwise). */
  via: MessageVia | null;
  /** A `note`'s data, as `agent.note` added it. */
  data: JsonObject | null;
  /** What started the turn of a `user` message no person sent (null for one someone sent). */
  trigger: MessageTrigger | null;
  /** The harness command a `user` message ran in place of text (null for a message). */
  command: AgentCommandInput | null;
  /** An agent's message to its owner from another of its conversations (a `human__notify` that joined this thread). */
  notification?: boolean;
  /** A `notification` passing on a space's news: the space it's from (null otherwise). */
  space?: MessageSpace | null;
  /** A `user` message written for one of its coding harness's subagents: which one (null otherwise). */
  subagent?: MessageSubagent | null;
  /** A channel's turn's `user` message: the posts it delivered, as the channel has them (null otherwise). */
  channel?: MessageChannel | null;
  /**
   * The chat a message of the agent's session came from, where it isn't the session's own: the `conversation` it was
   * sent to (a WhatsApp chat's id, `channel:<id>`, `owner`, a shared page's visitor), which its reply goes back to
   * (null otherwise).
   */
  chat?: string | null;
  /** What a coding harness's reply's turn did (null where it says nothing). */
  summary?: TurnSummary | null;
  /** Its harness steps' folds, in order. */
  groups?: StepGroup[];
  raw: JsonObject;
}

/** Which of a conversation's messages `history` reads. */
export interface AgentHistoryOptions {
  /** The newest this many (1-200), oldest first; every message when omitted. */
  limit?: number;
  /** Just before this cursor: a `nextCursor` of `historyPage`. */
  before?: string;
  user?: UserOption;
  /**
   * Whose thread it is, read as the account (`user_id`): a user's (a `User` or your id for one) or `NO_USER` for the
   * account's own, instead of acting as the user (`user`). A suspended user's thread reads this way too.
   */
  userFilter?: UserFilter;
}

/** A page of `history`, with the agent's session: the one conversation everyone talking to it shares now. */
export interface HistoryPage extends Page<Message> {
  /** The agent's session as the read found it (a read of a conversation nobody wrote in yet names the one it makes). */
  session: string | null;
}

/** The chat an activity item happened in, and who it's with. */
export interface ActivityChat {
  /** The conversation. */
  key: string;
  /** A person's name, or a group's as kept for it. */
  name: string | null;
  /** `direct`, `group` or `self` (the owner's own chat). */
  kind: string | null;
  /** E.164. */
  number: string | null;
  /** The chat's picture, where one was kept. */
  avatar: string | null;
  /** The trigger's node, which names the app the chat is on. */
  nodeType: string | null;
}

/** A message that came in, as its trigger's node reads it. */
export interface ActivityMessage {
  senderName: string | null;
  senderId: string | null;
  senderNumber: string | null;
  senderAvatar: string | null;
  text: string;
  /** `{ kind, url, duration, transcript }`: a voice note, an image, a file; the transcript once the turn read it. */
  media: JsonObject | null;
  quotedText: string | null;
  at: Date | null;
  messageId: string | null;
}

/** One thing the agent did on a turn, in order. */
export interface ActivityAction {
  /** `reply`, `reaction`, `note`, `reminder`, `found`, `held`, `failed` or `quiet`. */
  kind: string;
  text: string | null;
  emoji: string | null;
  at: Date | null;
  /** On a `held` call: the request its owner answers. */
  heldRequestId: string | null;
  messageId: string | null;
  /** The tool it called (none for the turn's own end). */
  tool: string | null;
  /** A file a reply sent: `{ kind, url }`. */
  media: JsonObject | null;
  /** When a reminder wakes it. */
  when: string | null;
  /** The memory entry a note saved. */
  name: string | null;
  /** A reply the agent edited since. */
  edited: boolean;
}

/** The turn an activity item is: its `agent.message` operation and thread. */
export interface ActivityTurn {
  id: string;
  conversationId: string;
  /** `running` (its actions fill as its calls complete), `done` or `failed`. */
  status: string;
  startedAt: Date | null;
  workedS: number | null;
  /** The trigger (`{ kind, id, title }`) or the wake-up that started it. */
  startedBy: JsonObject | null;
  /** Every call it made, `{ tool, at, error }`. */
  steps: JsonObject[];
}

/**
 * A turn a trigger's event or a wake-up started where no one watched: the chat it happened in, what came in
 * (`inbound`, then `alsoInbound`, the messages it answered too), what the agent did, and the turn.
 */
export interface AgentActivity {
  chat: ActivityChat;
  /** The message that started it; null for a turn a wake-up started. */
  inbound: ActivityMessage | null;
  /** Messages that came in while the agent was busy and that the same turn answered, oldest first. */
  alsoInbound: ActivityMessage[];
  did: ActivityAction[];
  turn: ActivityTurn;
  raw: JsonObject;
}

function toActivityMessage(value: unknown): ActivityMessage {
  const raw = asObject(value);
  return {
    senderName: str(raw.sender_name), senderId: str(raw.sender_id), senderNumber: str(raw.sender_number),
    senderAvatar: str(raw.sender_avatar), text: str(raw.text) ?? "",
    media: raw.media && typeof raw.media === "object" ? (raw.media as JsonObject) : null,
    quotedText: str(raw.quoted_text), at: parseTime(raw.at), messageId: str(raw.message_id),
  };
}

function toAgentActivity(value: unknown): AgentActivity {
  const raw = asObject(value);
  const chat = asObject(raw.chat);
  const turn = asObject(raw.turn);
  return {
    chat: {
      key: str(chat.key) ?? "", name: str(chat.name), kind: str(chat.kind), number: str(chat.number),
      avatar: str(chat.avatar), nodeType: str(chat.node_type),
    },
    inbound: raw.inbound && typeof raw.inbound === "object" ? toActivityMessage(raw.inbound) : null,
    alsoInbound: asList(raw.also_inbound).map(toActivityMessage),
    did: asList(raw.did).map((row) => {
      const d = asObject(row);
      return {
        kind: str(d.kind) ?? "", text: str(d.text), emoji: str(d.emoji), at: parseTime(d.at),
        heldRequestId: str(d.held_request_id), messageId: str(d.message_id), tool: str(d.tool),
        media: d.media && typeof d.media === "object" ? (d.media as JsonObject) : null, when: str(d.when),
        name: str(d.name), edited: d.edited === true,
      };
    }),
    turn: {
      id: str(turn.id) ?? "", conversationId: str(turn.conversation_id) ?? "", status: str(turn.status) ?? "done",
      startedAt: parseTime(turn.started_at), workedS: num(turn.worked_s),
      startedBy: turn.started_by && typeof turn.started_by === "object" ? (turn.started_by as JsonObject) : null,
      steps: asList(turn.steps).map((step) => asObject(step)),
    },
    raw,
  };
}

/**
 * Left out when it's created, everything in its scope (`"everything"`): every connection, ones
 * connected later too, operations that need no account, the web and NoClick itself, plus the
 * account's owner to notify and ask for an account agent. A list narrows it to what it names:
 * connections (a `Connection`, or its name: every operation), one operation of one
 * (`"gmail.send_email_message"`), the capabilities `"search"` and `"fetch"`, a `Toolkit`, a
 * `Database` (its `query`, `execute` and `schema`, or `db.only(...)`; invite-only beta), a browser
 * (`"browser"`, or `"browser.act"` and the like), or a person (a
 * `Human` or `human.only(...)`: tools that notify, ask or hand off to them): at most 64 tools
 * in all. A string names a connection in the agent's own user (the account for an account agent,
 * whose `"credential:<id>"` names an account connected in the NoClick app), else an integration's operations that need no account (on NoClick's key), so
 * `tools: ["exa.search"]` (or `"exa"`, all of them) needs no connection. A `Connection` object from
 * another scope, another user's or the account's, stays that connection (a key acting for the whole
 * account only). A lazy `createIfMissing` connection is created first. Every agent can also run shell
 * commands (the `code` capability; a policy that denies `code` refuses them, and `shell: false` removes it).
 */
export type AgentTools = ToolRef[] | { refs: ToolRef[] };

/** `allow` runs a call, `ask` holds it for the owner's yes (an approval), `off` refuses it. */
export type ToolRule = "allow" | "ask" | "off";

/**
 * What an agent may do with each app it reaches, as `{ key: ToolRule }`. A key is an app as `tools` names it (a
 * connection's name, `"credential:<id>"`, an integration's, `"noclick"`, `"search"`, `"fetch"`), one action of it
 * (`"work-gmail.delete_email_message"`; NoClick's are its groups, `"noclick.spend"`), or `"*"` for whatever the rest
 * don't name. The most specific key naming a call decides it; none, it's allowed. With everything, `"*": "off"` keeps
 * it to the apps the rules turn on, so an account connected later starts off.
 */
export type ToolRules = Record<string, ToolRule>;

/** One action of an app in `agent.toolAccess()`: its rule `key`, what its rules say of it and how often it ran. */
export interface AgentToolAction {
  key: string;
  action: string;
  title: string;
  /** Its integration's own grouping of it (`Message`, `Invoices`); null for NoClick's and the web's. */
  group: string | null;
  /** What it does, from its name: `read`, `send`, `change`, `delete` or `money` (a hint, never a rule). */
  kind: "read" | "send" | "change" | "delete" | "money";
  verdict: ToolRule;
  /** False where `ask` can't hold it (reading never waits for a person). */
  canAsk: boolean;
  /** Its calls that ran since `since`. */
  calls: number;
}

/** One app in `agent.toolAccess()`: a connection of its scope, an integration its rules name, NoClick or the web. */
export interface AgentToolApp {
  /** Its rule key; null for the web, whose two actions (`search`, `fetch`) are keys of their own. */
  key: string | null;
  app: string;
  kind: "connection" | "integration" | "noclick" | "web";
  integration: string | null;
  credentialType: string | null;
  label: string;
  /** The account it's connected as (else its name), or what it does for NoClick and the web. */
  account: string | null;
  status: ConnectionStatus | null;
  /** Whether anything of it may run. */
  on: boolean;
  calls: number;
  actions: AgentToolAction[];
}

/**
 * One version of an agent's instructions (`agent.instructionsHistory()`): the text it held, what it changed from the
 * version before as a unified diff's hunks (`diff`, null for the oldest kept), who made it and when. `source` is
 * `app` (its owner on NoClick's pages), `canvas`, `coordinator` (NoClick's assistant), `agent` (another agent's
 * turn), `api` (code), `restore` or `baseline` (as it was when versions began to be kept); `said` is what the owner
 * said that an agent's turn made it on.
 */
export interface AgentInstructionsVersion {
  version: number;
  instructions: string;
  diff: string | null;
  added: number;
  removed: number;
  source: string;
  author: { userId: string; keyId: string | null } | null;
  said: string | null;
  restoredFrom: number | null;
  changedAt: Date | null;
}

/**
 * An agent's instructions as they stand, their `digest` (what `update({ instructions, ifInstructions })` names them
 * by), and the versions in which they changed, newest first, the first the ones in use, kept `keptDays` days.
 */
export interface AgentInstructions {
  instructions: string;
  digest: string;
  versions: AgentInstructionsVersion[];
  keptDays: number;
  raw: JsonObject;
}

function toInstructions(raw: JsonObject): AgentInstructions {
  const version = (v: JsonObject): AgentInstructionsVersion => {
    const author = v.author && typeof v.author === "object" ? (v.author as JsonObject) : null;
    return {
      version: Number(v.version), instructions: String(v.instructions ?? ""), diff: str(v.diff),
      added: Number(v.added ?? 0), removed: Number(v.removed ?? 0), source: String(v.source ?? ""),
      author: author ? { userId: String(author.user_id), keyId: str(author.key_id) } : null,
      said: str(v.said), restoredFrom: typeof v.restored_from === "number" ? v.restored_from : null,
      changedAt: parseTime(v.changed_at),
    };
  };
  return {
    instructions: String(raw.instructions ?? ""), digest: String(raw.digest ?? ""),
    versions: (Array.isArray(raw.versions) ? (raw.versions as JsonObject[]) : []).map(version),
    keptDays: Number(raw.kept_days ?? 0), raw,
  };
}

/**
 * What an agent may do with each app it reaches (`agent.toolAccess()`). `mode` is `restricted` when it's kept to the
 * apps its rules turn on; `listed` when its `tools` are a list rather than everything, whose `rules` are what that
 * list amounts to.
 */
export interface AgentToolAccess {
  mode: "everything" | "restricted";
  listed: boolean;
  rules: ToolRules;
  since: Date | null;
  apps: AgentToolApp[];
  raw: JsonObject;
}

function toToolAccess(raw: JsonObject): AgentToolAccess {
  const action = (a: JsonObject): AgentToolAction => ({
    key: String(a.key), action: String(a.action), title: String(a.title), group: str(a.group),
    kind: a.kind as AgentToolAction["kind"], verdict: a.verdict as ToolRule, canAsk: a.can_ask !== false,
    calls: Number(a.calls ?? 0),
  });
  return {
    mode: raw.mode === "restricted" ? "restricted" : "everything",
    listed: raw.listed === true,
    rules: asObject(raw.rules) as ToolRules,
    since: parseTime(raw.since),
    apps: (Array.isArray(raw.apps) ? (raw.apps as JsonObject[]) : []).map((app) => ({
      key: str(app.key), app: String(app.app), kind: app.kind as AgentToolApp["kind"], integration: str(app.integration),
      credentialType: str(app.credential_type), label: String(app.label), account: str(app.account),
      status: (str(app.status) as ConnectionStatus | null), on: app.on === true, calls: Number(app.calls ?? 0),
      actions: (Array.isArray(app.actions) ? (app.actions as JsonObject[]) : []).map(action),
    })),
    raw,
  };
}

/** What runs an agent: NoClick's own agent loop (`sdk`), or a coding agent in a sandbox of its own. */
export type HarnessName = "sdk" | "claude_code" | "codex" | "opencode" | "hermes" | "openclaw";

/** How a model id reaches its model: its maker's own API, OpenRouter, or OpenCode Zen (`opencode`, `opencode-go`). */
export type HarnessModelRoute = "maker" | "openrouter" | "opencode" | "opencode-go";

/**
 * A model a harness offers, by the `id` its `model` takes. One model reached several ways is a row per way, each with
 * its `route` and the same `canonical`, the model as its maker names it (`anthropic/claude-sonnet-5-5`); a model
 * reached one way is its own `canonical`.
 */
export interface HarnessModel {
  id: string;
  label: string | null;
  canonical: string;
  route: HarnessModelRoute;
  /** What it costs on NoClick's own key; null where the key doesn't run it on this harness, or its price can't be read now. */
  noclickKey: HarnessModelPrice | null;
}

/**
 * A model's price on NoClick's own key: its output per million tokens (null for a router priced as the model it
 * picks for each call), and `needsFundsUsd`, the funds your account must have added (not its plan's included usage)
 * to put an agent on it there: set for a model over $2 a million output tokens, else null. An agent already on one
 * keeps running, and your own key or plan is never held to it.
 */
export interface HarnessModelPrice {
  outputUsdPerMillion: number | null;
  needsFundsUsd: number | null;
}

/**
 * What can run an agent: one of `Agent.harnesses()`. `sdk` is NoClick's own agent loop; the others
 * are coding agents that run in a sandbox of their own, with a shell and files, and think with the
 * key or plan of a `modelConnection`. `models()` searches the models it offers.
 */
export interface HarnessInfo {
  /** What `harness` takes. */
  name: HarnessName;
  label: string | null;
  /** The version NoClick runs (null for `sdk`). */
  version: string | null;
  /** The model an agent on it gets when you give none. */
  defaultModel: string;
  /** Whether `model` also takes models `models()` doesn't offer. */
  customModels: boolean;
  /** `required` for every CLI harness, `optional` for `sdk`. */
  modelConnection: "required" | "optional";
  /** The model providers (`kind: "model"` integrations) whose connection it can think with. */
  integrations: string[];
  /** `tokens` when the reply streams as it's written, `final` when it arrives whole. */
  streaming: "tokens" | "final";
  /** `built_in` when it has its own shell and file tools, `code_capability` when its shell is the `code` tool. */
  shell: "built_in" | "code_capability";
  /** What to know before choosing it (a model that needs a particular key, say). */
  notes: string[];
  /** The reasoning efforts it takes on its default model, weakest first ([]: none); a conversation's settings list its model's. */
  efforts: string[];
  /** The effort it runs at when none is set (null: the model's own). */
  defaultEffort: string | null;
  /** `["standard", "fast"]` where it has a fast mode on its default model, else []. */
  speeds: AgentSpeed[];
  /** Whether a coding agent on it may run on NoClick's own key (`modelConnection: "noclick"`, at the model's cost), the models to suggest there, or why not. */
  noclickKey: { runs: boolean; models: string[]; why: string | null };
  /** The permission modes it enforces ([]: none, as on `sdk`), and why it runs the others as another. */
  permissionModes: PermissionMode[];
  notSupported: Record<string, string>;
  /**
   * The models it offers, its default first: the first `limit` (50; at most 200), or those whose id
   * or label contains `search` (case-insensitive). A search after a few quiet minutes reads the
   * providers' lists afresh, so it can take seconds.
   *
   *     const models = await opencode.models({ search: "claude", limit: 10 });
   */
  models(options?: { search?: string; limit?: number }): Promise<HarnessModel[]>;
  raw: JsonObject;
}

/**
 * What an agent made for some apps (`Agent.forApps`) needs before it can start: an account of one of its apps
 * (`kind` `"app"`, with its `integration`, `nodeType` and `label`), or its model (`"model"`), and whether it's in.
 */
export interface AgentForAppsNeed {
  kind: "app" | "model";
  connected: boolean;
  integration: string | null;
  nodeType: string | null;
  label: string | null;
  /** What it does in that app, as the app describes itself. */
  description: string | null;
}

/** An agent for some apps (`Agent.forApps`), the channel it talks in, what it still needs, and whether this call made it. */
export interface AgentForApps {
  agent: Agent;
  channel: { id: string; name: string } | null;
  needs: AgentForAppsNeed[];
  created: boolean;
  raw: JsonObject;
}

function toAgentForAppsNeed(raw: JsonObject): AgentForAppsNeed {
  return {
    kind: raw.kind === "model" ? "model" : "app",
    connected: raw.connected === true,
    integration: str(raw.integration),
    nodeType: str(raw.node_type),
    label: str(raw.label),
    description: str(raw.description),
  };
}

function toHarnessInfo(raw: JsonObject, client: NoClick | undefined): HarnessInfo {
  const name = raw.name as HarnessName;
  return {
    name,
    label: str(raw.label),
    version: str(raw.version),
    defaultModel: String(raw.default_model),
    customModels: raw.custom_models === true,
    modelConnection: raw.model_connection as HarnessInfo["modelConnection"],
    integrations: asList(raw.integrations).map(String),
    streaming: raw.streaming as HarnessInfo["streaming"],
    shell: raw.shell as HarnessInfo["shell"],
    notes: asList(raw.notes).map(String),
    efforts: asList(raw.efforts).map(String),
    defaultEffort: str(raw.default_effort),
    speeds: asList(raw.speeds).map(String) as AgentSpeed[],
    noclickKey: {
      runs: asObject(raw.noclick_key).runs === true,
      models: asList(asObject(raw.noclick_key).models).map(String),
      why: str(asObject(raw.noclick_key).why),
    },
    permissionModes: asList(raw.permission_modes).map(String) as PermissionMode[],
    notSupported: Object.fromEntries(Object.entries(asObject(raw.not_supported)).map(([k, v]) => [k, String(v)])),
    async models(options = {}) {
      const page = await resolveClient(client).request("GET", `/v1/harnesses/${encodeURIComponent(name)}/models`, {
        query: { q: options.search, limit: options.limit ?? 50 },
        user: null,
      });
      return asList(page).map((m) => asObject(m)).map((m) => ({
        id: String(m.id),
        label: str(m.label),
        canonical: str(m.canonical) ?? String(m.id),
        route: (str(m.route) ?? "maker") as HarnessModelRoute,
        noclickKey: m.noclick_key
          ? { outputUsdPerMillion: num(asObject(m.noclick_key).output_usd_per_million), needsFundsUsd: num(asObject(m.noclick_key).needs_funds_usd) }
          : null,
      }));
    },
    raw,
  };
}

/** Where a move from a laptop made an agent from (`Agent.movedFrom`). */
export interface AgentMovedFrom {
  moveId: string;
  host: string | null;
  folder: string | null;
  at: Date | null;
}

export interface AgentFields {
  instructions?: string;
  /**
   * The harness's own model: an OpenRouter id with the `openrouter/` prefix on `sdk`, an alias such
   * as `sonnet` on `claude_code`, a `provider/model` on `opencode`, `hermes` and `openclaw`; the
   * harness's default when omitted.
   */
  model?: string;
  /**
   * What runs it: `sdk` (the default), NoClick's own agent loop, or a coding agent in a sandbox of
   * its own (`claude_code`, `codex`, `opencode`, `hermes`, `openclaw`). A new harness without a
   * `model` takes that harness's default model, and each conversation carries on on it.
   */
  harness?: HarnessName;
  /**
   * The connection whose key or plan it thinks with: a `Connection` of a `kind: "model"`
   * integration such as `anthropic`, or its name, in the agent's own scope (a lazy
   * `createIfMissing` one is created first). Every CLI harness needs one, and it may still be
   * pending; on `sdk` it's optional and lets `model` name `anthropic/...` or `openai/...` on your key.
   * In `fromName`, `null` clears it (back to `sdk` takes `harness: "sdk", modelConnection: null`).
   */
  modelConnection?: string | Connection | null;
  /**
   * How hard its model reasons in every conversation: one of its harness's `efforts`
   * (`Agent.harnesses()`, or a conversation's settings). In `update` and `fromName`, `null` clears it.
   */
  effort?: string | null;
  /** `fast` runs its model in its harness's fast mode where it has one (`speeds`). In `update`, `null` clears it. */
  speed?: AgentSpeed | null;
  /**
   * How far its coding harness goes before asking a person, in each conversation that sets none (a conversation's
   * `setPermissionMode` wins): one of its harness's `permissionModes`. In `update`, `null` puts back `full-access`.
   */
  permissionMode?: PermissionMode | null;
  /**
   * Commands a coding agent's sandbox (its container, on a machine) runs as it starts, in order, after its `repos`
   * and with its secrets in the environment (a CLI installed, a config file written); up to 20. In `update`, `[]`
   * clears them.
   */
  setup?: string[];
  /**
   * Docker in a coding agent's sandbox, which is then a VM of `sandboxSize` with dockerd running before its first
   * turn: `docker`, `docker compose` and testcontainers work as on any Linux machine. The VM is billed at its cost
   * for all of its size while it's up. In `update`, `false` drops its size.
   */
  docker?: boolean;
  /** The VM a Docker agent works in (`SandboxSize`; `small` unless it says). In `update`, `null` is `small` again. */
  sandboxSize?: SandboxSize | null;
  /**
   * How it may turn Docker on for a task that needs it, without `docker` (`AppTesting`; `by_itself` unless it says).
   * In `update`, `never` turns off what's on now, from its next turn.
   */
  appTesting?: AppTesting;
  /**
   * How it moves to another of the owner's model connections (`ModelSwitching`): left out, it switches by itself to
   * any of their own plans and asks before a paid key. In `update`, `null` is the default rule again; letting it switch
   * more freely is the owner's own call.
   */
  modelSwitching?: ModelSwitchingChange | null;
  tools?: AgentTools;
  /** What it may do with each app it reaches (`ToolRules`). In `update`, `{}` clears them. */
  toolRules?: ToolRules;
  /**
   * What it may ask its user to connect at run time (a `request_connection` tool): integration
   * names (or `IntegrationInfo`s), single `"integration.operation"`s, or `"*"`. What the user connects
   * is a grant (`grants()`), kept apart from the agent's fields.
   */
  canRequest?: (string | { name: string })[];
}

function integrationRefs(entries: (string | { name: string })[] | undefined): string[] | undefined {
  return entries?.map((entry) => (typeof entry === "string" ? entry : entry.name));
}

/**
 * What `fromName` sets on an existing agent (`triggers` too, through the triggers
 * sub-resource).
 */
const CONVERGED = [
  "instructions", "model", "harness", "model_connection", "tools", "tool_rules", "can_request", "budget_usd_per_month",
  "browser_profile_id", "card_id", "volumes", "memories", "skills", "secret_ids", "timezone", "repos", "network", "shell", "region",
  "machine_id", "turn_limits", "effort", "speed", "permission_mode", "setup", "docker", "sandbox_size",
  "app_testing", "model_switching",
] as const;

/** Whether `fromName` sets `key`: `model_switching` is sent as only its given parts, so only those count. */
function drifted(key: string, have: unknown, want: unknown): boolean {
  const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  if (key === "model_switching" && want && typeof want === "object") {
    return Object.entries(want as JsonObject).some(([k, v]) => !same((have as JsonObject | null)?.[k], v));
  }
  return !same(have, want);
}

/** An agent's own approval settings, as `create`, `update` and `spawn` take them. */
export interface AgentApprovalsOption {
  /**
   * What its own calls wait for a person on, in place of the account's, by kind of hold (`ApprovalPolicy.get()` lists
   * the settable ones): `"allow"`, `"ask"`, `"deny"`, or `{ disposition, under_usd?, until? }` (a purchase allowed at
   * or under `under_usd`, asked above). Never looser than the account's ceiling for the kind (raise it with
   * `ApprovalPolicy.set({ ceilings })`), a child's never looser than its parent's (which it follows where it sets
   * none), and a purchase or a deletion past the default needs a monthly cap on the account. Loosening is the owner's:
   * signed in, their own message to one of their agents, or a key naming `approvals:policy` (after a 10-minute undo
   * window); an agent acting on its own waits for their yes. In `update`, a kind set to `null` goes back to the
   * account's (a child's, to its parent's). `toolRules` turning `noclick.spend` or `noclick.delete` to `"allow"` set
   * `purchase` or `delete` to allow with it. `routing` among them names who answers its held calls first, in place of
   * its parent's or the account's approver (finally the owner), as `ApprovalPolicy.set`'s `routing` takes it: never
   * the agent itself nor one of its children (its parent may approve its calls).
   */
  approvals?: ScopeApprovals;
}

export interface AgentCreateOptions extends AgentFields, CallOptions {
  /**
   * A temporary agent: after this many seconds it's `expired`, taking no turns (its pending
   * wake-ups are canceled) and readable for 30 days, then deleted. Set when it's created, for good: an
   * existing agent with another makes `fromName` throw `Conflict` naming its `ttl_s`.
   */
  ttlS?: number;
  /**
   * Its parent: a child's budget is held out of what the parent's has left; without one, it draws on the
   * parent's as it spends. Set when it's created, for good: an existing agent with another makes
   * `fromName` throw `Conflict` naming its `parent_id`.
   */
  parent?: string | Agent;
  /** In `fromName`, `null` clears it, as `browserProfile` and `card` do. */
  budgetUsdPerMonth?: number | null;
  /** What wakes it without a message: `OnWebhook`, `OnEvent`, `OnPlatformEvent`, `Cron` and `OnQueue`. */
  triggers?: TriggerDefinition[];
  /**
   * The profile its `browser` tool signs in with (a `BrowserProfile` or id of its own user's, or the
   * account's for an account agent): each conversation gets a browser of its own for a turn, a step only
   * a person can do holds the turn `awaiting_human`, and its calls follow policy as `browser.*`. In
   * `update`, `null` signs it out.
   */
  browserProfile?: string | BrowserProfile | null;
  /**
   * Invite-only beta. The card it holds and pays with (a `Card` or id of its own scope; giving one
   * takes the key's `cards` scope): a card has one agent at a time. It gets `card__status` and
   * `card__purchase` (approve before paying: above the card's threshold the turn waits for a person, whose
   * answer is its next turn), which policy names `card.status` and `card.purchase`, and never sees the
   * number. A turn answering someone outside its scope, or a test run, buys nothing. A child it spawns pays
   * with the same card only when given `"card"` in its tools. In `update`, `null` takes its card back.
   */
  card?: string | Card | null;
  /**
   * Volumes its shell mounts read-write, by absolute path, in every conversation, up to 5:
   * `{ "/data": Volume.fromName("datasets") }` (a `Volume`, an id or a name: its user's own, else the
   * account's). Not `/workspace`, `/root` or a system folder. An `sdk` agent's shell sees each as the
   * turn started and saves its writes when it ends; a coding harness's sandbox, while it's up.
   */
  volumes?: Record<string, VolumeRef>;
  /**
   * The `Memory`s it reads besides its own (`agent.memory`), in order, up to 10: a `Memory`, its id or name
   * (its user's own, else the account's), or another agent's `memory`. Each is read-only to it unless given as
   * `memory.writable()`; a user's agent reads the account's memories but never writes them, and never another
   * user's. Every turn starts with each entry's name and description, its own memory's first.
   */
  memories?: MemoryRef[];
  /**
   * The `Skill`s it uses, in order, up to 20: a `Skill` (`skill.pinned(n)` to hold one version), its id or name (its
   * user's own, else the account's). A coding harness finds them where it reads skills; an `sdk` agent sees each
   * one's name and description every turn and reads one with `skill__read`.
   */
  skills?: SkillRef[];
  /**
   * Secrets whose keys become environment variables in its shell, up to 20, a later one's key winning
   * (a `Secret`, an id or a name: its user's own, else the account's; an account agent's, the account's
   * only). A model provider's key (`OPENAI_API_KEY` and the like) belongs on `modelConnection`: a
   * secret holding one throws `InvalidRequest`.
   */
  secrets?: SecretRef[];
  /**
   * The IANA timezone every turn is told the date and time in; without one, the acting user's
   * `timezone`, else UTC. An account's own agent made without one starts in its owner's, where their
   * NoClick assistant tells the time. In `fromName`, `null` clears it.
   */
  timezone?: string | null;
  /**
   * Repositories cloned into its workspace (`/workspace/<name>`) at a conversation's first turn:
   * `connection.checkout(...)` through a `github` connection of its own scope, or `repo.checkout(...)`
   * for a NoClick `Repo` of its own scope, up to 10 (none with `shell: false`). Its `git` reaches those
   * repositories only, through NoClick, with a key made for its sandbox; a push goes through only to the branches the
   * checkout's `push` globs name (none: read-only), judged by NoClick on the way to the git host,
   * since a harness's own `git push` is no tool call a policy could judge. `gh` only reads a git host's.
   */
  repos?: RepoCheckout[];
  /**
   * What its shell and code may reach: `true` (anywhere, the default), `false`, or up to 50 hosts
   * (`"pypi.org"`, or `"*.example.com"` for a domain and its subdomains), over HTTPS on port 443 only.
   * What it needs to work stays reachable, and `false` leaves only that: an `sdk` agent's shell reaches
   * NoClick's git proxy when it has `repos` (its model and tools run on NoClick); a coding harness reaches
   * NoClick's API, NoClick's proxy for its model on a key and for git, and on a Claude or ChatGPT plan that
   * provider's own hosts. Its tools run on NoClick, outside the limit. Omitted, its parent's, else
   * anywhere; the children it spawns take its. Where NoClick can't keep to a limited network (a coding
   * harness on a key other than Claude, ChatGPT or OpenRouter, say), it throws `NotAvailable` rather
   * than widen it. In `update`, from its next turn.
   */
  network?: NetworkAccess;
  /**
   * `false` takes the shell (the `code` capability) away from an `sdk` agent, and from the children it
   * spawns; a CLI harness refuses it with `InvalidRequest`, since its shell is the harness.
   */
  shell?: boolean;
  /**
   * How far one turn of an `sdk` agent goes before it wraps up:
   * `{ steps: 100, usd: 2, minutes: 45 }`, each left out at its default ($1 of model calls and 30 minutes, with
   * 200 model calls as a backstop; at most 200, $25 and 60). A turn its steps end stops there saying nothing and
   * carries on by itself in a follow-up turn on the same conversation, up to 3 in a row, unless a message comes
   * first; one its spend or minutes end says where the work stands and waits to be asked (`reply.endedBy` names
   * the limit). A coding harness ends its own turns, and refuses it with `InvalidRequest`. In `update` (from its
   * next turn) and `fromName`, `null` goes back to the defaults.
   */
  turnLimits?: TurnLimits | null;
  /**
   * Where its sandboxes run (`regions()`), for good: a coding harness runs there whole, and an `sdk`
   * agent's shell does while its loop runs in NoClick's own service. Omitted, its parent's, else your
   * account's default region, else wherever NoClick has capacity. An existing agent elsewhere makes
   * `fromName` throw `Conflict` naming its `region`.
   */
  region?: RegionName;
  /**
   * Invite-only beta. The always-on `Machine` (or its id) its harness runs on instead of a
   * sandbox of its own: nothing reaped when it's quiet, no per-minute sandbox charge, in the
   * machine's region. A coding harness there reaches its model through NoClick's credential proxy,
   * so its `modelConnection` holds a Claude, ChatGPT or OpenRouter key, or your account's own plan: a
   * Claude plan on `claude_code` or a ChatGPT plan on `codex`, its sign-in kept in that agent's own
   * container (the answer's `notes` say so). Anyone else's plan throws `NotAvailable`; a machine runs
   * at most 50 agents. In `update`, `null` moves it back to sandboxes.
   */
  machine?: string | Machine | null;
}

/** A trigger definition as the API takes it: a Cron, or any trigger class that says its own wire form. */
async function triggerWire(trigger: TriggerDefinition): Promise<JsonObject> {
  if (trigger instanceof Cron) return { kind: "cron", ...trigger.toWire() };
  if (isTriggerClass(trigger)) return await trigger.toWire();
  throw new TypeError("A trigger is a Cron, OnWebhook, OnEvent, OnPlatformEvent or OnQueue");
}

function isTriggerClass(value: unknown): value is { toWire(): JsonObject | Promise<JsonObject> } {
  return typeof value === "object" && value !== null && !(value instanceof Cron) && typeof (value as { toWire?: unknown }).toWire === "function";
}

function readReply(result: unknown, op: Operation<unknown>): AgentReply {
  const body = result && typeof result === "object" ? (result as JsonObject) : { text: result };
  return {
    text: str(body.text) ?? "",
    conversation: str(body.conversation),
    toolCalls: toolCallsOf(body.tool_calls),
    steps: toolCallsOf(body.tool_calls).map(toAgentStep),
    operationId: str(op._known("id")),
    modelUsage: toModelUsage(body.model_usage),
    endedBy: str(body.ended_by) as TurnLimitName | null,
    summary: toTurnSummary(body.summary),
    groups: toStepGroups(body.groups),
    raw: body,
  };
}

/** The operation a tool server's connect link is (`AgentToolServer.connectLink`). */
const TOOL_SERVER_SIGN_IN = "tool_server.sign_in";

registerResult(TOOL_SERVER_SIGN_IN, (result, op) => {
  const body = asObject(result);
  const server = asObject("tool_server" in body ? body.tool_server : result);
  return Agent.fromId(String(server.agent_id ?? ""), { client: op._client, user: op._scope }).toolServer(server);
});
// A turn, a spawned task and an answered `ask` all resolve to a reply.
registerResult("agent.message", readReply);
registerResult("agent.task", readReply);
registerResult("agent.ask", readReply);
// A message to an agent built in the app.
registerResult("workflow.agent_message", readReply);

async function repoWires(repos: RepoCheckout[] | undefined, scope: UserRef | null): Promise<JsonObject[] | undefined> {
  if (repos === undefined) return undefined;
  return await Promise.all(repos.map((checkout) => {
    if (typeof checkout?._wire !== "function") throw new TypeError("repos takes connection.checkout(...) or repo.checkout(...)");
    return checkout._wire(scope);
  }));
}

/** @internal The id of an `Agent` (loading a lazy one) or an id string. */
export function agentId(agent: string | Agent | undefined): Promise<string | undefined> {
  return refId(agent);
}

/** `scope` is the agent's user (null for the account): a connection from another scope is sent by id. */
async function wireBody(name: string, options: AgentCreateOptions, parentId: string | undefined, scope: UserOption): Promise<JsonObject> {
  return compact({
    name,
    instructions: options.instructions,
    model: options.model,
    harness: options.harness,
    model_connection: await modelConnectionRef(options.modelConnection, scope),
    tools: await toolRefs(options.tools, { scope }),
    tool_rules: options.toolRules,
    can_request: integrationRefs(options.canRequest),
    ttl_s: options.ttlS,
    parent_id: parentId,
    budget_usd_per_month: options.budgetUsdPerMonth,
    triggers: options.triggers ? await Promise.all(options.triggers.map(triggerWire)) : undefined,
    browser_profile_id: await refId((options.browserProfile ?? undefined) as string | ApiObject | undefined),
    card_id: await refId((options.card ?? undefined) as string | ApiObject | undefined),
    volumes: await volumeMountIds(options.volumes, options),
    memories: await memoryLinks(options.memories, options),
    skills: await skillLinks(options.skills, options),
    secret_ids: await secretIdList(options.secrets, options),
    timezone: options.timezone ?? undefined,
    repos: await repoWires(options.repos, resolveScope(scope)),
    network: options.network,
    shell: options.shell,
    region: options.region,
    machine_id: await refId((options.machine ?? undefined) as string | ApiObject | undefined),
    turn_limits: limitsWire(options.turnLimits),
    effort: options.effort ?? undefined,
    speed: options.speed ?? undefined,
    permission_mode: options.permissionMode ?? undefined,
    setup: options.setup,
    docker: options.docker,
    sandbox_size: options.sandboxSize ?? undefined,
    app_testing: options.appTesting,
    model_switching: (await switchingWire(options.modelSwitching, scope)) ?? undefined,
  });
}

/** The fields a definition's explicit `null` clears on an existing agent, as `update` does. */
function cleared(options: AgentCreateOptions): JsonObject {
  const nullable: JsonObject = {
    model_connection: options.modelConnection, budget_usd_per_month: options.budgetUsdPerMonth,
    browser_profile_id: options.browserProfile as string | null | undefined, card_id: options.card as string | null | undefined,
    timezone: options.timezone, turn_limits: options.turnLimits === null ? null : undefined,
    effort: options.effort, speed: options.speed, permission_mode: options.permissionMode,
  };
  return Object.fromEntries(Object.entries(nullable).filter(([, value]) => value === null));
}

/**
 * `working` (a turn queued or running), `waiting` (its turns wait on a person: a question, a
 * held call), `idle`, or `expired` (past its `ttlS`: no turns, readable for 30 days). Pausing
 * stops triggers, not work: see `paused`.
 */
export type AgentStatus = "working" | "waiting" | "idle" | "expired";

const AGENT_STATUSES: readonly AgentStatus[] = ["working", "waiting", "idle", "expired"];
const AGENT_ORDERS = ["created", "last_active"] as const;

/** `Agent.list`'s filters. */
export interface AgentListOptions extends ReadOptions {
  name?: string;
  /** Only agents with this status. */
  status?: AgentStatus;
  /** Only agents with a turn since then. */
  activeSince?: Date | string;
  /** Only the children of this agent (an `Agent` or id). */
  parent?: string | Agent;
  /** `true`: only agents with a `ttlS`; `false`: only agents without one. */
  temporary?: boolean;
  /** Only agents on this harness. */
  harness?: HarnessName;
  /** `created` (the default: newest first) or `last_active` (most recently active first, those that never ran last). */
  order?: (typeof AGENT_ORDERS)[number];
  /** Only agents made through the API (`api`) or built in the NoClick app (`app`). */
  origin?: AgentOrigin;
}

/** Where an agent was made: through the API, or in the NoClick app. */
export type AgentOrigin = "api" | "app";
const AGENT_ORIGINS: readonly AgentOrigin[] = ["api", "app"];

async function listQuery(options: AgentListOptions): Promise<Record<string, string | boolean | undefined>> {
  if (options.status !== undefined && !AGENT_STATUSES.includes(options.status)) {
    throw new TypeError(`status is one of ${AGENT_STATUSES.join(", ")}, not ${JSON.stringify(options.status)}`);
  }
  if (options.order !== undefined && !AGENT_ORDERS.includes(options.order)) {
    throw new TypeError(`order is one of ${AGENT_ORDERS.join(", ")}, not ${JSON.stringify(options.order)}`);
  }
  if (options.origin !== undefined && !AGENT_ORIGINS.includes(options.origin)) {
    throw new TypeError(`origin is one of ${AGENT_ORIGINS.join(", ")}, not ${JSON.stringify(options.origin)}`);
  }
  return {
    name: options.name,
    status: options.status,
    active_since: isoTime(options.activeSince),
    parent_id: await agentId(options.parent),
    temporary: options.temporary,
    harness: options.harness,
    order: options.order,
    origin: options.origin,
  };
}

/** What `spawn` takes beside the task. */
export interface SpawnOptions {
  /** When NoClick makes the child report, beside `"done"` (always on): `"blocked"`, `new Before(...)`, `new Every(...)`. */
  updates?: UpdateSpec[];
  /** The parent's conversation its updates wake; without one they wake nobody and wait on the job. */
  conversation?: string;
  /** The child's standing instructions: what its updates should say, and when to reach out freely. */
  instructions?: string;
  /**
   * Some of its parent's tools (it gets none of them otherwise); a tool its parent lacks is refused. `"card"`
   * gives it the card its parent pays with.
   */
  tools?: AgentTools;
  /** Its budget, held out of what its parent's has left; omitted, it draws on its parent's as it spends. */
  budgetUsd?: number;
  /** It expires this many seconds after it's made. */
  ttlS?: number;
  /** The parent's model when omitted. */
  model?: string;
  /** The parent's harness when omitted. */
  harness?: HarnessName;
  /** The parent's model connection when omitted. */
  modelConnection?: string | Connection;
  /** `<parent>-<8 hex>` when omitted. */
  name?: string;
  /**
   * The line of work the task belongs to (`Workstream`): one of yours, matched whatever its case, or a new name,
   * which makes one. Every charge of the job, and of what it starts, is counted under it.
   */
  workstream?: string;
  /**
   * The child's own approval settings (as `create` takes them), within its parent's, which it follows where it sets
   * none: one looser than its parent's throws `InvalidRequest`.
   */
  approvals?: ScopeApprovals;
  /** Whose conversation `conversation` is (an account parent talking to a user: that user's thread). */
  user?: UserOption;
}

/** A wake-up's time: one of `at`, `afterS`, `when` and `every`. */
export interface WakeTiming {
  /** A moment: a `Date`, or an ISO 8601 string with its offset. */
  at?: Date | string;
  /** This many seconds from now. */
  afterS?: number;
  /**
   * When an operation reaches a terminal status (a `Job`, a `HumanRequest`, a `ConnectLink`, ...; one that has wakes
   * it at once), once when the last of several does (a list of them, up to 20: its turn is told what each came to,
   * and a child's `done` update for one of those jobs comes in that turn), or a NoClick event type such as
   * `"connection.connected"` (`*` matches the rest of a name): the first matching event after it was set wakes it.
   * A user's conversation hears that user's events; one of your account's own hears every event, your users'
   * included.
   */
  when?: Operation<unknown> | readonly Operation<unknown>[] | string;
  /** With an event `when`: dotted paths into the event's `data` that must equal these values. */
  filters?: JsonObject;
  /**
   * A routine: it wakes the conversation at each time of this `Cron` until it's canceled (`tz: "user"` follows the
   * conversation's user). The note is what it's told, so the `Cron` takes no `message`.
   */
  every?: Cron;
}

/** When `wake` wakes the conversation: exactly one of `at`, `afterS`, `when` and `every`. */
export interface WakeOptions extends WakeTiming {
  /** What the turn is told, 1 to 4,000 characters. */
  note: string;
  /** Whose conversation it is, as `message()` takes it. */
  user?: UserOption;
}

const ISO_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/i;

async function wakeWire(conversation: string, options: WakeOptions): Promise<JsonObject> {
  if (!options || typeof options.note !== "string" || !options.note) throw new TypeError("wake() needs a note: what the turn is told");
  return compact({ conversation, note: options.note, ...(await wakeTimingWire(options, true)) });
}

/** @internal The wire form of a wake-up's time: exactly one of its fields, or (`exactlyOne` false) at most one. */
export async function wakeTimingWire(options: WakeTiming, exactlyOne: boolean): Promise<JsonObject> {
  const given = [options.at, options.afterS, options.when, options.every].filter((v) => v !== undefined).length;
  if (exactlyOne ? given !== 1 : given > 1) {
    throw new TypeError(`A wake-up's time is ${exactlyOne ? "exactly" : "at most"} one of at, afterS, when and every`);
  }
  if (options.filters !== undefined && typeof options.when !== "string") {
    throw new TypeError("filters go with an event type in when, like when: \"connection.connected\"");
  }
  let every: JsonObject | undefined;
  if (options.every !== undefined) {
    if (!(options.every instanceof Cron)) throw new TypeError("every is a Cron, like new Cron(\"0 9 * * 1\", { tz: \"Europe/London\" })");
    if (options.every.message !== null) throw new TypeError("A recurring wake-up is told its note, so its Cron takes no message");
    every = { cron: options.every.expr, tz: options.every.tz };
  }
  let at: string | undefined;
  if (options.at !== undefined) {
    if (typeof options.at === "string" && !ISO_OFFSET.test(options.at)) {
      throw new TypeError(`at needs its offset, like "2026-10-02T09:00:00Z", not ${JSON.stringify(options.at)}`);
    }
    if (!(options.at instanceof Date) && typeof options.at !== "string") throw new TypeError("at is a Date or an ISO 8601 string");
    at = isoTime(options.at);
  }
  if (options.afterS !== undefined && (typeof options.afterS !== "number" || !Number.isFinite(options.afterS))) {
    throw new TypeError(`afterS is a number of seconds, not ${JSON.stringify(options.afterS)}`);
  }
  let when: JsonObject | undefined;
  if (typeof options.when === "string") when = compact({ event: options.when, filters: options.filters });
  else if (options.when instanceof Operation) when = { operation_id: await refId(options.when) };
  else if (Array.isArray(options.when) && options.when.length && options.when.every((w) => w instanceof Operation)) {
    when = { operation_ids: await Promise.all(options.when.map((w) => refId(w))) };
  } else if (options.when !== undefined) throw new TypeError("when is an Operation, a list of them or a platform event type");
  return compact({ at, after_s: options.afterS, when, every });
}

/** `agent.jobs()`'s filters. */
export interface JobFilters {
  /** Statuses, or `"live"` for every non-terminal one. */
  status?: OperationStatus | "live" | readonly (OperationStatus | "live")[];
  /** `task` (spawned), or `message` (sent with its `agents` tools). */
  kind?: "task" | "message";
  /** The agent doing the work (an `Agent` or id). */
  agent?: string | Agent;
  /** The parent's conversation that started them. */
  conversation?: string;
  limit?: number;
}

const JOB_KINDS = { task: "agent.task", message: "agent.message" } as const;

/**
 * A hosted agent. `Agent.fromName("host", { createIfMissing: true, instructions })`
 * is lazy; `(await agent.message("hi")).text` talks to it.
 *
 * An account-level agent is shared: each user that messages it (via
 * `asUser` or `{ user }`) gets its own conversations. A user's own agent
 * always talks as that user.
 */
export class Agent extends ApiObject {
  private _createWith: { name: string; options: AgentCreateOptions } | null = null;
  private _job: Job | null | undefined = undefined;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create an agent (names are unique per account and user; a duplicate throws `Conflict` with `existingId`).
   * With `allowExisting: true` a taken name returns the agent already there, as it is: nothing about it
   * changes, so it's made once and left alone after.
   */
  static async create(
    name: string, options: AgentCreateOptions & AgentApprovalsOption & AllowExisting & { instructions: string },
  ): Promise<Agent> {
    const scope = resolveScope(options.user);
    const json = defined({ ...await wireBody(name, options, await agentId(options.parent), scope),
      approvals: wireSettings(options.approvals) });
    const raw = await createNamed("/v1/agents", json, { allowExisting: options.allowExisting, user: scope, client: options.client });
    return new Agent({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the agent called `name` for the current (or given) user: inside `asUser` only
   * that user's own agent, never an account agent of the same name. Given fields, it gets the agent and
   * sets the ones you pass, on every run: an existing agent whose instructions, model, `modelConnection`,
   * tools, `canRequest`, budget or another field `update` takes differ gets yours (the grants its user
   * gave it are kept), and its `triggers` too. `createIfMissing` only decides what happens when there's
   * none: `true` creates it (`instructions` is required then), else it throws `NotFound`. A field left
   * out is never changed; `null` clears `modelConnection`, `budgetUsdPerMonth`, `browserProfile` or
   * `card`, as `update` does. `region`, `ttlS` and `parent` are set when it's created, for good: an
   * existing agent with another throws `Conflict` naming it.
   *
   * Setting fields is a write, every time it runs: do it at startup or in a setup script, and take the
   * bare `Agent.fromName("support")` in request handlers, or two versions of your server would keep
   * overwriting each other's values. To make an agent once and leave it alone after, use
   * `Agent.create(name, { ..., allowExisting: true })`.
   */
  static fromName(name: string, options: AgentCreateOptions & { createIfMissing?: boolean } = {}): Agent {
    const agent = new Agent({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing && !options.instructions) {
      throw new TypeError("Agent.fromName(..., { createIfMissing: true }) needs instructions");
    }
    if (options.parent !== undefined && typeof options.parent !== "string") {
      throw new TypeError("Agent.fromName takes parent as an id");
    }
    agent._creates = Boolean(options.createIfMissing);
    // Pinned to the agent's own user: volume and secret names are looked up there on first use.
    if (agent._creates || givesFields(options)) agent._createWith = { name, options: { ...options, user: agent._scope ?? null } };
    return agent;
  }

  static fromId(agentId: string, options: CallOptions = {}): Agent {
    return new Agent({ hints: { id: agentId }, client: options.client, user: options.user });
  }

  static async get(agentId: string, options: CallOptions = {}): Promise<Agent> {
    return await Agent.fromId(agentId, options).hydrate();
  }

  /**
   * The agents the current user can message: inside `asUser` their own and the account's (messaged, not
   * changed; `userId` null), so a `name` may match one of each; outside it, the account's. `userFilter`
   * lists exactly whose instead. Expired agents are listed
   * for the 30 days they're kept; `status`, `activeSince`, `parent`, `temporary` and `harness` filter, and
   * `order: "last_active"` reads a column the turn runner stamps, on an index of its own.
   *
   * After the account's API agents come the ones built in the NoClick app, which are the account's too
   * (`origin: "api"` or `"app"` lists only one kind); only `name` and `harness` apply to them, and the
   * other filters leave them out. `send` and `message` reach them; what they are is changed in the app.
   *
   *     for (const agent of await Agent.list({ origin: "app" })) console.log(agent.name, agent.workflowName, agent.appUrl);
   */
  static async list(options: AgentListOptions & { limit?: number } = {}): Promise<Agent[]> {
    return await listAll(
      { ...options, path: "/v1/agents", query: await listQuery(options) },
      (raw, user) => new Agent({ raw, client: options.client, user }),
    );
  }

  /** One page of agents; pass `nextCursor` back as `cursor`. Takes `list`'s filters. */
  static async listPage(options: AgentListOptions & PageOptions = {}): Promise<Page<Agent>> {
    return await listPage(
      { ...options, path: "/v1/agents", query: await listQuery(options) },
      (raw, user) => new Agent({ raw, client: options.client, user }),
    );
  }

  /**
   * What can run an agent: each one's default model, whether it needs a `modelConnection` and which
   * providers serve it (`models()` searches its models). On a CLI harness a reply arrives whole, a
   * conversation's first turn starts its sandbox (warm a minute between turns) and its uptime is billed.
   *
   *     const codex = (await Agent.harnesses()).find((h) => h.name === "codex");
   *     const models = await codex?.models({ search: "gpt-5" });
   */
  static async harnesses(options: { client?: NoClick } = {}): Promise<HarnessInfo[]> {
    const page = await resolveClient(options.client).request("GET", "/v1/harnesses", { user: null });
    return asList(page).map((row) => toHarnessInfo(asObject(row), options.client));
  }

  /**
   * An agent for some of your apps, as NoClick's agents pages set one up: named for them ("Roblox agent"), on
   * `harness`, holding everything on your account, with a channel of its own in your personal space that opens with
   * what it still needs and says hello, with first tasks to tap, once nothing is missing. Its model runs on a model
   * account of yours that runs the harness's model, else NoClick's own key where the harness takes it, else a model
   * connection waiting for your key or plan. Made once for the same apps and harness: asked again, it's the one made
   * (`created` false). Your account's owner or one of its own keys makes it; a user's can't.
   *
   *     const made = await Agent.forApps(["roblox"], { harness: "hermes" });
   *     console.log(made.agent.name, made.channel?.name, made.needs.filter((n) => !n.connected));
   */
  static async forApps(apps: string[], options: { harness?: HarnessName; client?: NoClick } = {}): Promise<AgentForApps> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/agents/for_apps", {
      json: { apps, harness: options.harness ?? "sdk" }, user: null,
    }));
    const made = asObject(raw.agent);
    const channel = asObject(raw.channel ?? {});
    return {
      agent: new Agent({ hints: { id: String(made.id), ...(typeof made.name === "string" ? { name: made.name } : {}) }, client: options.client, user: null }),
      channel: typeof channel.id === "string" ? { id: channel.id, name: String(channel.name) } : null,
      needs: asList(raw.needs).map((n) => toAgentForAppsNeed(asObject(n))),
      created: raw.created === true,
      raw,
    };
  }

  /**
   * Every coding agent, and what each is doing. An agent on `claude_code`, `codex`, `opencode`, `hermes` or
   * `openclaw` (an app's own coding agent among them), with its `state` (`working`, `waiting` on a person, `warm`,
   * `paused` and why, `stopped`), where it runs, on whose model credential, its current job, each conversation that's
   * up (`runs`, a sandbox's with what it reserved) and its spend since the first of the month; then counts by
   * harness, model, state and place. Read from the turns, containers and sandboxes themselves. `userFilter` narrows
   * it to whose; omitted, every one of the account's for an account's key, a user's own for theirs.
   *
   *     const { agents, byState } = await Agent.coding();
   *     for (const agent of agents) console.log(agent.name, agent.state, agent.job?.title);
   */
  static async coding(options: ReadOptions = {}): Promise<CodingAgents> {
    const { user, userId } = await readScope(options);
    return toCodingAgents(await resolveClient(options.client).request("GET", "/v1/agents/coding", {
      query: { user_id: userId }, user,
    }));
  }

  /**
   * Every agent's state, for a list of agents. What it's doing (`state`), the tool call it runs `now`,
   * what waits on a person (`waiting`, the badge's `total`) and when, read from its turns, asks and held calls. A page
   * follows it on the `platform:agent` frames. `workspace` keeps a workspace's agents.
   *
   *     const { data } = await Agent.states();
   *     for (const row of data) console.log(row.name, row.state, row.now?.line);
   */
  static async states(options: ReadOptions & { workspace?: string } = {}): Promise<AgentStates> {
    const { user, userId } = await readScope(options);
    return toAgentStates(await resolveClient(options.client).request("GET", "/v1/agents/states", {
      query: { user_id: userId, workspace_id: options.workspace }, user,
    }));
  }

  /**
   * One of `harnesses()` by name; an unknown name throws `NotFound` naming the ones there are.
   *
   *     const opencode = await Agent.harnessInfo("opencode");
   */
  static async harnessInfo(name: string, options: { client?: NoClick } = {}): Promise<HarnessInfo> {
    const harnesses = await Agent.harnesses(options);
    const found = harnesses.find((h) => h.name === name);
    if (found) return found;
    throw new NotFound(`No harness is named "${name}".`, {
      nextStep: `Use one of: ${harnesses.map((h) => h.name).join(", ")}.`,
      details: { name },
    });
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  get model(): string | null {
    return this._field("model");
  }
  get harness(): HarnessName | null {
    return this._field("harness");
  }
  /**
   * The connection whose key or plan it thinks with, by name (null on `sdk` without one). Hidden,
   * like `instructions`, from a user's session reading an account agent.
   */
  get modelConnection(): string | null {
    return this._field("model_connection");
  }
  get instructions(): string | null {
    return this._field("instructions");
  }
  /**
   * What it can use, as listed: refs, `{ tool, bind }` for an operation with arguments bound and
   * `{ human, tools }` for a person.
   */
  get tools(): (string | JsonObject)[] {
    return this._field("tools") ?? [];
  }
  /** What it may ask its user to connect at run time. */
  /** What it may do with each app it reaches (`ToolRules`); empty, everything its tools give is allowed. */
  get toolRules(): ToolRules {
    return this._field("tool_rules") ?? {};
  }
  get canRequest(): string[] {
    return this._field("can_request") ?? [];
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get workflowId(): string | null {
    return this._field("workflow_id");
  }
  /** `api` for an agent made through the API, `app` for one built in the NoClick app (an id like `node:<workflow>:<node>`). */
  get origin(): AgentOrigin | null {
    return this._field("origin");
  }
  /** An agent made for apps's step in its workflow (null for an API agent). */
  get nodeId(): string | null {
    return this._field("node_id");
  }
  /** An agent made for apps's workflow, by name. */
  get workflowName(): string | null {
    return this._field("workflow_name");
  }
  /** An agent made for apps's workflow as you hold it: `owner`, or `editor` or `viewer` when it was shared with you (only an owner's or an editor's takes messages). */
  get access(): string | null {
    return this._field("access");
  }
  /** Whether an agent made for apps is switched on; a disabled one takes no messages. */
  get enabled(): boolean | null {
    return this._field("enabled");
  }
  /** Where an agent made for apps is changed: its workflow in the NoClick app. */
  get appUrl(): string | null {
    return this._field("app_url");
  }
  /** Its parent, whose budget it draws on. */
  get parentId(): string | null {
    return this._field("parent_id");
  }
  /**
   * Whether it's one of NoClick's helpers, made for NoClick's own work rather than one of your agents: an app's coding
   * agent (which NoClick hands each change to that app's code), or a child one of NoClick's own agents spawned.
   */
  get helper(): boolean {
    return Boolean(this._field("helper"));
  }
  /**
   * Whether it's a NoClick, your account's own or one of your spaces', rather than one of your agents: NoClick's own
   * app shows it as NoClick, never by the name it's found by (a space's is `noclick-<the space's id>`).
   */
  get noclick(): boolean {
    return Boolean(this._field("noclick"));
  }
  /**
   * The names it went by before it was renamed, the latest first. Each still reaches it (`agent:<old name>`,
   * `fromName`, an @mention in a channel) and stays reserved for it: no other agent of its scope takes one.
   */
  get formerNames(): string[] {
    return this._field("former_names") ?? [];
  }
  /** The time to live it was created with, in seconds (null if it isn't temporary); `expiresAt` is when it runs out. */
  get ttlS(): number | null {
    return this._field("ttl_s");
  }
  /** When a temporary agent expires (null if it isn't): it then stays readable, `expired`, for 30 days. */
  get expiresAt(): Date | null {
    return parseTime(this._field("expires_at"));
  }
  get budgetUsdPerMonth(): number | null {
    return this._field("budget_usd_per_month");
  }
  /** While a budget set for one run holds (`update({ budgetForRun: true })`), the budget that comes back as that run
   *  ends and after which run (`operationId` null: its next turn); null otherwise. */
  get budgetRestore(): { budgetUsdPerMonth: number | null; operationId: string | null } | null {
    const held = this._field<JsonObject | null>("budget_restore");
    return held ? { budgetUsdPerMonth: (held.budget_usd_per_month as number | null) ?? null,
      operationId: (held.operation_id as string | null) ?? null } : null;
  }
  /** The region its sandboxes run in, fixed when it was created; `null`: wherever NoClick has capacity. */
  get region(): RegionName | null {
    return this._field("region");
  }
  /** Invite-only beta. The `Machine` its harness runs on (null: a sandbox of its own). */
  get machineId(): string | null {
    return this._field("machine_id");
  }
  /** This agent in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    return this._api.consoleUrl("agents", this.id);
  }
  /** The A2A JSON-RPC endpoint (`message/send`, `tasks/get`); callers authenticate with a platform key as a bearer token. */
  get a2aUrl(): string {
    return this._field<string | null>("a2a_url") ?? `${this._api.baseUrl}/v1/agents/${this.id}/a2a`;
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** Whether `pause()` stopped its triggers (false too for a user reading an account agent). */
  get paused(): boolean {
    return Boolean(this._field("paused"));
  }
  /** The kinds of its triggers (`cron`, `webhook`, `event`, `platform`, `email`, `call`); an agent with `cron` is an automation. */
  get triggerKinds(): string[] {
    return this._field("trigger_kinds") ?? [];
  }
  /** The browser profile its `browser` tool signs in with. */
  get browserProfileId(): string | null {
    return this._field("browser_profile_id");
  }
  /** Invite-only beta. The card it holds and pays with (null: none of its own). */
  get cardId(): string | null {
    return this._field("card_id");
  }
  /** The volumes its shell mounts: `{ path: volume id }`. */
  get volumes(): Record<string, string> {
    return this._field<Record<string, string> | null>("volumes") ?? {};
  }
  /** Its own memory (`agent.memory`) as a `Memory` id, to attach to other agents. */
  get memoryId(): string | null {
    return this._field("memory_id");
  }
  /** Its skills: each `{ id, pin }` (`pin` null: the latest). */
  get skills(): { id: string; pin: number | null }[] | null {
    return this._field<{ id: string; pin: number | null }[] | null>("skills");
  }

  /** The memories it reads besides its own, in order: each `{ id, writes }` (null for a user's session reading an account agent). */
  get memories(): { id: string; writes: boolean }[] | null {
    return this._field<{ id: string; writes: boolean }[] | null>("memories");
  }
  /** The secrets in its shell's environment, in order (a later one's key wins). */
  get secretIds(): string[] {
    return this._field<string[] | null>("secret_ids") ?? [];
  }
  /** The IANA timezone its turns tell the time in (null: the acting user's, else UTC). */
  get timezone(): string | null {
    return this._field("timezone");
  }
  /** The repositories cloned into its workspace: each its `connection`, `repository`, `branch`, `path` and `push` globs. */
  get repos(): JsonObject[] {
    return this._field<JsonObject[] | null>("repos") ?? [];
  }
  /**
   * What its shell and code reach: `true` (anywhere), `false` (only what it needs to work) or the hosts
   * it may reach besides, as sent.
   */
  get network(): NetworkAccess | null {
    return this._field("network");
  }
  /** Whether it has a shell (the `code` capability; `false` only on `sdk`). */
  get shell(): boolean | null {
    return this._field("shell");
  }
  /** How far one of its turns goes, as set (null, or a limit left out: 200 steps, $1 and 30 minutes). */
  get turnLimits(): TurnLimits | null {
    return this._field("turn_limits");
  }
  /** Its conversations' reasoning effort (null: the model's own). */
  get effort(): string | null {
    return this._field("effort") ?? null;
  }
  /** `fast`: its conversations run in fast mode. */
  get speed(): "standard" | "fast" {
    return this._field("speed") ?? "standard";
  }
  /** How far its coding harness goes before asking a person where a conversation sets nothing. */
  get permissionMode(): PermissionMode {
    return this._field("permission_mode") ?? "full-access";
  }
  /**
   * What its own calls wait for a person on in place of the account's, by kind of hold (`disposition`, `under_usd`,
   * `until`, `effective_at`, `pending`), and `routing`: who answers its held calls first (`approver`, `on_timeout`,
   * `expires_in_s`); empty where it sets none (a child follows its parent's).
   */
  get approvals(): Record<string, JsonObject> {
    return { ...(asObject(this._field("approvals")) as Record<string, JsonObject>) };
  }
  /** Commands its sandbox (its container, on a machine) runs as it starts, after its repos and before its harness. */
  get setup(): string[] {
    return asList(this._field("setup")).map(String);
  }
  /** Whether Docker runs in its sandbox, a VM of `sandboxSize` (a coding harness only). */
  get docker(): boolean {
    return Boolean(this._field("docker"));
  }
  /** The VM a Docker agent works in; null without Docker. */
  get sandboxSize(): SandboxSize | null {
    return this._field<SandboxSize | null>("sandbox_size") ?? null;
  }
  /** How it may turn Docker on for a task that needs it (`AppTesting`). */
  get appTesting(): AppTesting {
    return this._field<AppTesting | null>("app_testing") ?? "by_itself";
  }
  /** What an hour of app testing costs where its sandbox runs; null without a sandbox of its own. */
  get appTestingUsdPerHour(): number | null {
    return this._field<number | null>("app_testing_usd_per_hour") ?? null;
  }
  /** How it moves to another of the owner's model connections (`ModelSwitching`). */
  get modelSwitching(): Required<ModelSwitching> {
    const raw = this._field<JsonObject | null>("model_switching") ?? {};
    return { mode: (raw.mode as "switch" | "stay") ?? "switch", allowed: (raw.allowed as string[] | null) ?? null,
      harness: (raw.harness as "same" | "any") ?? "same" };
  }
  /** While a plan's limit has it on another connection, the one it left (its first turn after goes back); else null. */
  get switchedFrom(): SwitchedFrom | null {
    const raw = this._field<JsonObject | null>("switched_from");
    if (!raw) return null;
    return { connection: String(raw.connection), name: (raw.name as string | null) ?? null,
             window: (raw.window as string | null) ?? null, resetsAt: (raw.resets_at as string | null) ?? null };
  }
  /** Where a move from a laptop made it (its move, machine, folder and when); null otherwise. */
  get movedFrom(): AgentMovedFrom | null {
    const raw = this._field<JsonObject | null>("moved_from");
    if (!raw) return null;
    return { moveId: String(raw.move_id), host: str(raw.host), folder: str(raw.folder), at: parseTime(raw.at) };
  }
  /** The apps that bind it: `kind` (`project`), `id`, `name` and the `binding` name. */
  get usedBy(): UsedBy[] {
    const rows = this._field<unknown>("used_by");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((u) => ({
      kind: str(u.kind) ?? "project", id: str(u.id) ?? "", name: str(u.name) ?? "", binding: str(u.binding),
    }));
  }
  /**
   * `working`, `waiting`, `idle` or `expired`; `paused` is its own field (pausing stops triggers, not work). Null, like the
   * activity fields below, for a user's session reading an account agent.
   */
  get status(): AgentStatus | null {
    return this._field("status");
  }
  /** When a turn of its last started or ended (null: it never ran, or hidden like `status`). */
  get lastActiveAt(): Date | null {
    return parseTime(this._field("last_active_at"));
  }
  /** How many of its turns are queued, running or waiting on a person, any conversation (null: hidden like `status`). */
  get runningTurns(): number | null {
    return num(this._field("running_turns"));
  }
  /** How many live (not expired) children it has (`children()` lists them; null: hidden like `status`). */
  get childCount(): number | null {
    return num(this._field("child_count"));
  }
  /** The task it was spawned with (its operation id), or null. */
  get jobId(): string | null {
    return this._field("job_id");
  }
  /** The task it was spawned with, as a `Job` to wait on, or null. */
  get job(): Job | null {
    if (this._job === undefined) {
      const embedded = this._known("job");
      const id = this._known("job_id");
      this._job = embedded && typeof embedded === "object"
        ? Job._from(embedded, { client: this._client, user: this._callScope() })
        : typeof id === "string" ? Job.jobFromId(id, { client: this._client, user: this._callScope() }) : null;
    }
    return this._job;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/agents/${id}`);
    const name = String(this._hints.name);
    const page = await this._request("GET", "/v1/agents", { query: { name } });
    // This scope's own agent, never an account agent of the same name the user can also see, and
    // never an expired one: it gave its name up when it expired. One renamed since still goes by it.
    const rows = (asList(page) as JsonObject[]).filter(
      (row) =>
        (row.name === name || (Array.isArray(row.former_names) && row.former_names.includes(name))) &&
        Boolean(row.user_id) === Boolean(this._scope) &&
        row.status !== "expired",
    );
    if (rows.length) return await this.converge(rows[0]);
    if (!this._createWith || !this._creates) {
      throw new NotFound(`No agent is named "${name}".`, {
        nextStep: "Create it with Agent.create(...) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    try {
      const { name: createName, options } = this._createWith;
      const json = await wireBody(createName, options, options.parent as string | undefined, this._scope);
      return await this._request<JsonObject>("POST", "/v1/agents", { json });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/agents/${err.existingId}`));
    }
  }

  /** Set the fields `fromName` was given on an existing agent, after checking the ones it can't set. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    if (!this._createWith) return raw;
    const { name, options } = this._createWith;
    checkUnchanged("agent", raw, { ttl_s: options.ttlS, parent_id: options.parent as string | undefined });
    const wanted = { ...(await wireBody(name, options, undefined, this._scope)), ...cleared(options) };
    const changes: JsonObject = {};
    for (const key of CONVERGED) {
      if (key in wanted && drifted(key, raw[key], wanted[key])) changes[key] = wanted[key];
    }
    let current = raw;
    if (Object.keys(changes).length) current = await this._request<JsonObject>("PATCH", `/v1/agents/${raw.id}`, { json: changes });
    if (options.triggers && (await this.convergeTriggers(String(raw.id), wanted.triggers as JsonObject[]))) {
      current = await this._request<JsonObject>("GET", `/v1/agents/${raw.id}`);
    }
    return current;
  }

  /**
   * Add the triggers your code lists and the agent lacks, remove the defined ones it no longer
   * lists; mail and call triggers are left alone. Whether anything changed.
   */
  private async convergeTriggers(agentId: string, definitions: JsonObject[]): Promise<boolean> {
    const wanted = new Map(definitions.map((d) => [triggerKey(d), d]));
    const rows = asList(await this._request("GET", `/v1/agents/${agentId}/triggers`)) as JsonObject[];
    const have = new Map(
      rows.filter((r) => DEFINED_TRIGGER_KINDS.has(String(r.kind))).map((r) => [triggerKey({ kind: r.kind, ...asObject(r.spec) }), r]),
    );
    for (const [key, row] of have) if (!wanted.has(key)) await this._request("DELETE", `/v1/agents/${agentId}/triggers/${row.id}`);
    for (const [key, json] of wanted) if (!have.has(key)) await this._request("POST", `/v1/agents/${agentId}/triggers`, { json });
    return wanted.size !== have.size || [...wanted.keys()].some((key) => !have.has(key));
  }

  /** @internal Whose conversations a call is in: a user's own agent always talks as its user. */
  _talkScope(user: UserOption): UserRef | null {
    return this._ownerScope(this._raw?.user_id) ?? resolveScope(user);
  }

  /**
   * Store a file to send this agent with a message, capped as account files are: 10 MB an image (JPEG, PNG,
   * WebP or GIF), 15 MB a document, 20 MB audio or video. Send it once, with
   * `message(text, { files: [attachment] })`.
   */
  async upload(file: FileInput, options: UploadOptions = {}): Promise<Attachment> {
    const raw = await this._ensure();
    return uploadFile((method, path, init) => this._request(method, path, init), `/v1/agents/${raw.id}/attachments`, file, options);
  }

  /**
   * Start a turn without waiting; `wait()` resolves to the `AgentReply`. `files` go with it, as `message` sends them.
   * `command` runs one of the conversation's harness's own commands in place of `text` (pass `text` as null), as
   * `commands` lists them, never parsed from text. `delivery` decides a message sent while the agent works on a turn
   * (it takes one at a time): `steer` joins that turn when it's in the same conversation, `queue` (or omitted) runs it
   * next; a command is never steered.
   *
   *     await coder.send(null, { conversation: "main", command: { name: "compact" } });
   *     await coder.send("also update the README", { conversation: "main", delivery: "steer" });
   */
  async send(
    text: string | null,
    options: {
      conversation?: string | null; files?: (Attachment | string)[]; user?: UserOption; command?: AgentCommandInput;
      delivery?: MessageDelivery;
    } = {},
  ): Promise<Operation<AgentReply>> {
    const raw = await this._ensure();
    const scope = this._talkScope(options.user);
    const payload = await this._request("POST", `/v1/agents/${raw.id}/messages`, { json: messageBody(text, options), user: scope });
    return Operation._fromPayload<AgentReply>(payload, { client: this._client, user: scope, kind: "agent.message" });
  }

  /**
   * What the conversation's harness offers a person to run. Send one with `send(null, { command })`. It names its
   * commands and skills as the harness itself last listed them, what NoClick can and can't run there
   * (`capabilities`, `notSupported`), and how fresh the list is (`asOf`, `readFrom`).
   *
   *     const { commands } = await coder.commands("main");
   */
  async commands(conversation: string, options: { user?: UserOption } = {}): Promise<AgentCommands> {
    const raw = await this._ensure();
    return toCommands(asObject(await this._request(
      "GET",
      `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}/commands`,
      { user: this._talkScope(options.user) },
    )));
  }

  /**
   * Set how far the conversation's coding harness goes before asking a person. `approval-required` asks before
   * commands and edits, `auto-accept-edits` runs edits and asks about commands, `auto` has its own review approve
   * routine work, and `full-access` (the default) asks nothing. Questions reach a person in every mode. Its next
   * message runs in it.
   *
   *     await coder.setPermissionMode("main", "approval-required");
   */
  async setPermissionMode(conversation: string, mode: PermissionMode,
                          options: { user?: UserOption } = {}): Promise<ConversationSettings> {
    const raw = await this._ensure();
    return toConversationSettings(asObject(await this._request(
      "PATCH", `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}`,
      { json: { permission_mode: mode }, user: this._talkScope(options.user) },
    )));
  }

  /**
   * Start a new session (a chat's `/new` or `/clear`), as `clear` does, with `conversation` naming its key (one that
   * already has messages throws `Conflict`); omitted, NoClick makes one. Everyone talking to the agent shares it from
   * now on, and the one it leaves is kept, listed and can be resumed. Throws `Conflict` while the agent is working on
   * a turn.
   */
  async startConversation(options: { conversation?: string; title?: string; user?: UserOption } = {}):
    Promise<Conversation> {
    const raw = await this._ensure();
    return toConversation(asObject(await this._request(
      "POST", `/v1/agents/${raw.id}/conversations`,
      { json: compact({ conversation: options.conversation, title: options.title }), user: this._talkScope(options.user) },
    )));
  }

  /**
   * Start a new session, like `/clear` in a terminal: everyone talking to the agent shares it from now on. The one it
   * leaves is kept, listed and can be resumed (`conversation(name).resume()`), and the agent's files stay as they
   * are. Throws `Conflict` while the agent is working on a turn. Resolves to the new conversation, `active`.
   *
   *     const before = await coder.session();
   *     await coder.clear();
   *     await coder.message("Start on the billing page");   // the new session
   *     await coder.conversation(before!.conversation).resume();
   */
  async clear(options: { title?: string; user?: UserOption } = {}): Promise<Conversation> {
    return await this.startConversation(options);
  }

  /**
   * The agent's session: the one conversation everyone talking to it shares, where a message without a
   * `conversation` goes (the current user's, or the account's outside `asUser`). Null before the agent has one.
   *
   *     const current = await support.session();
   *     if (current) console.log(await support.history(current.conversation, { limit: 20 }));
   */
  async session(options: { user?: UserOption } = {}): Promise<Conversation | null> {
    let cursor: string | undefined;
    for (;;) {
      const page = await this.conversationsPage({ cursor, user: options.user });
      const found = page.data.find((c) => c.active);
      if (found || !page.nextCursor) return found ?? null;
      cursor = page.nextCursor;
    }
  }

  /**
   * One of its conversations, as a chat reads and changes it. Its settings, a fork, a revert, resuming it as the
   * agent's session, its context and usage, a command; no request until you call one.
   *
   *     const chat = coder.conversation("main");
   *     await chat.update({ effort: "high" });
   */
  conversation(name: string, options: { user?: UserOption } = {}): AgentConversation {
    return AgentConversation._of(this, name, options.user);
  }

  /**
   * What the conversation's coding harness asked a person, newest first. `status` keeps `pending`, `answered`,
   * `expired` or `canceled` ones.
   *
   *     const waiting = await coder.requests("main", { status: "pending" });
   */
  async requests(conversation: string,
                 options: { status?: HarnessRequest["status"]; user?: UserOption } = {}): Promise<HarnessRequest[]> {
    const raw = await this._ensure();
    const listed = asObject(await this._request(
      "GET", `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}/requests`,
      { query: options.status ? { status: options.status } : undefined, user: this._talkScope(options.user) },
    ));
    return (Array.isArray(listed.data) ? (listed.data as JsonObject[]) : []).map(toHarnessRequest);
  }

  /**
   * Answer what the conversation's coding harness asks. The `decision` is `allow_once`, `allow_always` (for the rest
   * of the session, where the harness can), `reject_once` (with a `note` the agent reads; a question: skip it) or
   * `cancel` (the turn stops). A question is answered with `answers` ({question: labels or your own words}) and `allow_once`. A
   * person's answer: never through an MCP connection.
   *
   *     await coder.answer("main", waiting[0].id, "reject_once", { note: "Push to a branch, not main." });
   */
  async answer(conversation: string, requestId: string, decision: RequestDecision,
               options: { note?: string; answers?: Record<string, string | string[]>; user?: UserOption } = {}):
    Promise<HarnessRequest> {
    const raw = await this._ensure();
    const json: JsonObject = { decision };
    if (options.note) json.note = options.note;
    if (options.answers) json.answers = options.answers as JsonObject;
    return toHarnessRequest(asObject(await this._request(
      "POST",
      `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}/requests/${encodeURIComponent(requestId)}`,
      { json, user: this._talkScope(options.user) },
    )));
  }

  /**
   * Send `text` and wait for the reply. Without `conversation` it goes to the agent's session, the one conversation
   * everyone talking to it shares (`session()`); pass the reply's `conversation` back to stay in that thread.
   * `files` (at most 100) are attachments from `upload`, or their ids: the turn reads them as the agent's
   * media digest does, a document's text, a voice clip's transcript, an image as an image.
   */
  async message(
    text: string,
    options: { conversation?: string | null; files?: (Attachment | string)[]; timeoutS?: number; user?: UserOption } = {},
  ): Promise<AgentReply> {
    const operation = await this.send(text, options);
    return await operation.wait({ timeoutS: options.timeoutS });
  }

  /**
   * The messages of one conversation, oldest first. Every one, or the `limit` newest (1-200), just before `before`
   * (a `nextCursor` of `historyPage`). Each with its `role`, `text`, the `files` it carried, how it arrived (`via`,
   * for a text, a call or an email) and, a reply, its `toolCalls`; a `note` has its `data`.
   */
  async history(conversation: string, options: AgentHistoryOptions = {}): Promise<Message[]> {
    return (await this.historyPage(conversation, options)).data;
  }

  /**
   * @internal Its conversations' path. One named by a ref (`Agent.fromId("agent:coordinator")`) reads them without
   * loading the agent first, a round trip less.
   */
  async _conversationsPath(): Promise<string> {
    const named = this._raw ? undefined : this._hints.id;
    if (typeof named === "string" && named.startsWith("agent:")) return `/v1/agents/${encodeURIComponent(named)}/conversations`;
    return `/v1/agents/${(await this._ensure()).id}/conversations`;
  }

  /** @internal What a read of a conversation carries: as its user, or as the account naming whose (`userFilter`). */
  private async conversationScope(options: { user?: UserOption; userFilter?: UserFilter }):
    Promise<{ user: UserRef | null; query: Record<string, string | undefined> }> {
    if (options.userFilter === undefined) return { user: this._talkScope(options.user), query: {} };
    const { user, userId } = await readScope({ userFilter: options.userFilter, user: options.user });
    return { user, query: { user_id: userId } };
  }

  /**
   * The turns a trigger's event or a wake-up started in one conversation, newest first (the `limit` latest, 50 by
   * default, at most 200): the chat each happened in and who it's with, what came in (a voice note with its
   * transcript, a file, what it quoted) and what the agent did, in order. A running turn's `did` fills as its calls
   * complete. A turn a message from your code started isn't one. `userFilter` reads a user's as the account.
   *
   *     for (const item of await support.activity("whatsapp:+14155550101", { limit: 20 })) {
   *       console.log(item.chat.name, item.inbound?.text, item.did.map((d) => d.kind));
   *     }
   */
  async activity(conversation: string, options: { limit?: number; user?: UserOption; userFilter?: UserFilter } = {}): Promise<AgentActivity[]> {
    const scope = await this.conversationScope(options);
    const response = await this._request("GET", `${await this._conversationsPath()}/${encodeURIComponent(conversation)}/activity`, {
      query: { limit: options.limit, ...scope.query }, user: scope.user,
    });
    return asList(response).map(toAgentActivity);
  }

  /**
   * A page of `history`, to read a long thread back from its newest messages. The `limit` newest (1-200), just
   * before `before`, oldest first. `nextCursor`, while older ones remain, is the `before` of the page before it.
   *
   *     let page = await support.historyPage("ticket-1841", { limit: 50 });
   *     while (page.nextCursor) page = await support.historyPage("ticket-1841", { limit: 50, before: page.nextCursor });
   */
  async historyPage(conversation: string, options: AgentHistoryOptions = {}): Promise<HistoryPage> {
    const scope = await this.conversationScope(options);
    const response = asObject(await this._request(
      "GET",
      `${await this._conversationsPath()}/${encodeURIComponent(conversation)}`,
      { query: { limit: options.limit, before: options.before, ...scope.query }, user: scope.user },
    ));
    const messages = Array.isArray(response.messages) ? (response.messages as JsonObject[]) : [];
    return { data: messages.map(toMessage), nextCursor: str(response.next_cursor), session: str(response.session) };
  }

  /**
   * Withdraw the question the agent asked your account's owner once it no longer needs them. It was answered or
   * handled another way, in one of the account's conversations. Its page and card then refuse a late answer, the turn
   * that asked ends, and the agent reads `note` (1-4,000 characters: who answered, what was already sent) at its
   * next turn there. `questionId` names the question (its `HumanRequest.requestId`) when more than one waits there;
   * the others keep waiting. It acts as the account, which alone withdraws one, never a user. With none waiting, or
   * several and none named, it throws `Conflict`. Resolves to the text of each question withdrawn.
   *
   *     await support.withdrawQuestion("ticket-1841", "Ana approved the refund on the phone; it's issued.");
   */
  async withdrawQuestion(conversation: string, note: string, options: { questionId?: string } = {}): Promise<string[]> {
    const raw = await this._ensure();
    const response = asObject(await this._request(
      "POST",
      `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}/withdraw_question`,
      { json: compact({ note, question_id: options.questionId }), user: null },
    ));
    return Array.isArray(response.withdrawn) ? response.withdrawn.map(String) : [];
  }

  /**
   * Add a line to a conversation without starting a turn. It shows in `history` and `watch` as a `note` with its
   * `data` (JSON, at most 4,096 bytes), and the agent reads both when its next turn starts, once. A `key` adds it
   * once: resolves to `false` when a note with that key already was.
   *
   *     await support.note("ticket-1841", "Ada upgraded to the Pro plan.", { data: { plan: "pro" }, key: "plan:pro" });
   */
  async note(
    conversation: string,
    text: string,
    options: { data?: JsonObject; key?: string; user?: UserOption } = {},
  ): Promise<boolean> {
    const raw = await this._ensure();
    const response = asObject(await this._request(
      "POST",
      `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}/notes`,
      { json: compact({ text, data: options.data, key: options.key }), user: this._talkScope(options.user) },
    ));
    return response.added === true;
  }

  private async conversationCall(options: ReadOptions & { archived?: boolean }):
    Promise<{ path: string; query: Record<string, boolean | undefined> } & ReadOptions> {
    const path = await this._conversationsPath();
    const user = options.userFilter === undefined ? this._talkScope(options.user) : options.user;
    return { user, userFilter: options.userFilter, client: this._client, path, query: { archived: options.archived } };
  }

  /**
   * Its conversations, most recent first (the current user's, or those `userFilter` covers). `archived` keeps the
   * archived ones (true) or the others (false).
   * `userFilter` reads across users without the user header, which only the signed-in owner
   * may do on a user's own agent; with a secret key, read such an agent's threads without it.
   */
  async conversations(options: ReadOptions & { limit?: number; archived?: boolean } = {}): Promise<Conversation[]> {
    return await listAll({ ...(await this.conversationCall(options)), limit: options.limit }, toConversation);
  }

  /** One page of its conversations; pass `nextCursor` back as `cursor`. */
  async conversationsPage(options: ReadOptions & PageOptions & { archived?: boolean } = {}): Promise<Page<Conversation>> {
    return await listPage({ ...(await this.conversationCall(options)), cursor: options.cursor, limit: options.limit }, toConversation);
  }

  /**
   * Give a conversation back to the agent after it handed it to a person
   * (its `hand_off` tool). The person's replies stay in its history, and the agent answers again
   * from the next message. The person can hand it back from their page too.
   */
  async handBack(conversation: string, options: { user?: UserOption } = {}): Promise<void> {
    const raw = await this._ensure();
    await this._request("POST", `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}/hand_back`, {
      user: this._talkScope(options.user),
    });
  }

  /**
   * Take over a coding agent's conversation. Its harness's own terminal (Claude Code, Codex, OpenCode, Hermes Agent
   * or OpenClaw) on the session the agent works in, for the account's owner. The turn in flight finishes first unless
   * `interrupt` stops it (its delivery fails, saying the owner took over); messages wait until it's handed back. Needs
   * the signed-in owner or the account's secret key with the `agents:terminal` scope: a terminal shows the sandbox's
   * keys and tokens. Asked again while it's taken over, it resolves to a new token (a reload, a second tab). Throws
   * `Conflict` when nothing of the conversation is running (send it a message first).
   *
   *     const terminal = await coder.takeOver("main", { interrupt: true, cols: 120, rows: 36 });
   *     const connection = terminal.connect({ onData: (bytes) => term.write(bytes) });
   */
  async takeOver(
    conversation: string,
    options: { interrupt?: boolean; cols?: number; rows?: number; user?: UserOption } = {},
  ): Promise<Terminal> {
    const raw = await this._ensure();
    const scope = this._talkScope(options.user);
    const view = await this._request<JsonObject>(
      "POST",
      `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}/terminal`,
      { json: compact({ interrupt: options.interrupt || undefined, cols: options.cols, rows: options.rows }), user: scope },
    );
    return Terminal._from(view, { client: this._client, user: scope });
  }

  /** Where a coding agent's conversation's terminal stands, with no token. Open it with `takeOver`, give it back
   *  with `Terminal.handBack`. */
  async terminal(conversation: string, options: { user?: UserOption } = {}): Promise<Terminal> {
    const raw = await this._ensure();
    const scope = this._talkScope(options.user);
    const view = await this._request<JsonObject>(
      "GET",
      `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}/terminal`,
      { user: scope },
    );
    return Terminal._from(view, { client: this._client, user: scope });
  }

  /**
   * Change fields; returns the updated agent. A new `harness` without a `model` takes that harness's
   * default model; `modelConnection: null` removes an `sdk` agent's own model key; `secrets` are those in its shell,
   * in place of the ones it has (`[]` takes them all away). `name` renames it, unique among its scope's agents: its
   * old name keeps reaching it and stays reserved for it (`formerNames`), and a NoClick keeps its name.
   * `budgetForRun: true` with `budgetUsdPerMonth` sets that budget for one run alone (its turn under way, else its
   * next one): the budget it replaced comes back once that run ends, however it ends (`budgetRestore` says what comes
   * back meanwhile). A budget set without it stands until changed.
   *
   *     await coder.update({ budgetUsdPerMonth: 2, budgetForRun: true });
   *     console.log(coder.budgetRestore);   // { budgetUsdPerMonth: 10, operationId: null }
   */
  async update(
    changes: Omit<AgentFields, "modelConnection"> & {
      name?: string;
      budgetUsdPerMonth?: number | null;
      budgetForRun?: boolean;
      modelConnection?: string | Connection | null;
      /**
       * The `digest` of the instructions this change was made on (`instructionsHistory()`): new `instructions` are
       * refused with a `Conflict` whose `details.instructions` are them as they are now, when they changed since.
       */
      ifInstructions?: string;
    } & Pick<AgentCreateOptions, "timezone" | "repos" | "network" | "shell" | "browserProfile" | "card" | "machine" |
      "memories" | "skills" | "turnLimits" | "secrets"> & AgentApprovalsOption,
  ): Promise<this> {
    const raw = await this._ensure();
    this._raw = await this._request<JsonObject>("PATCH", `/v1/agents/${raw.id}`, {
      json: defined({
        memories: await memoryLinks(changes.memories, { client: this._client, user: this._callScope() }),
        skills: await skillLinks(changes.skills, { client: this._client, user: this._callScope() }),
        name: changes.name,
        instructions: changes.instructions,
        if_instructions: changes.ifInstructions,
        model: changes.model,
        harness: changes.harness,
        model_connection: await modelConnectionRef(changes.modelConnection, this._callScope()),
        tools: await toolRefs(changes.tools, { scope: this._callScope() }),
        tool_rules: changes.toolRules,
        can_request: integrationRefs(changes.canRequest),
        budget_usd_per_month: changes.budgetUsdPerMonth,
        budget_for_run: changes.budgetForRun || undefined,
        timezone: changes.timezone,
        repos: await repoWires(changes.repos, resolveScope(this._callScope())),
        network: changes.network,
        shell: changes.shell,
        browser_profile_id: changes.browserProfile === undefined ? undefined
          : changes.browserProfile === null ? null : await refId(changes.browserProfile as string | ApiObject),
        card_id: changes.card === undefined ? undefined
          : changes.card === null ? null : await refId(changes.card as string | ApiObject),
        machine_id: changes.machine === undefined ? undefined
          : changes.machine === null ? null : await refId(changes.machine as string | ApiObject),
        turn_limits: changes.turnLimits === undefined ? undefined : limitsWire(changes.turnLimits) ?? null,
        effort: changes.effort,
        speed: changes.speed,
        permission_mode: changes.permissionMode,
        setup: changes.setup,
        docker: changes.docker,
        sandbox_size: changes.sandboxSize,
        app_testing: changes.appTesting,
        model_switching: await switchingWire(changes.modelSwitching, this._callScope()),
        secret_ids: await secretIdList(changes.secrets, { client: this._client, user: this._callScope() }),
        approvals: wireSettings(changes.approvals),
      }),
    });
    return this;
  }

  /** The connections its user gave it at run time (requested or active), oldest first. */
  async grants(): Promise<AgentGrant[]> {
    const raw = await this._ensure();
    this._raw = await this._request<JsonObject>("GET", `/v1/agents/${raw.id}`);
    return (Array.isArray(this._raw.grants) ? (this._raw.grants as JsonObject[]) : []).map(toGrant);
  }

  /**
   * Its instructions as they stand and the versions in which they changed, newest first: each one's text, its diff
   * from the one before, who made it and, for a change an agent made on the owner's message, their words. A change
   * made on what you read stays safe with `update({ instructions, ifInstructions: history.digest })`; restoring a
   * version is that update with its `instructions`.
   *
   *     const history = await writer.instructionsHistory();
   *     await writer.update({ instructions: history.versions[1].instructions, ifInstructions: history.digest });
   */
  async instructionsHistory(options: { limit?: number } = {}): Promise<AgentInstructions> {
    const raw = await this._ensure();
    return toInstructions(await this._request<JsonObject>("GET", `/v1/agents/${raw.id}/instructions`, {
      query: { limit: options.limit },
    }));
  }

  /**
   * What it may do with each app it reaches, app by app: each connection of its scope, NoClick and the web, whether
   * it's on, each action with what its rules say of it, and how often each ran in the last 7 days. Change it with
   * `update({ toolRules })`.
   */
  async toolAccess(): Promise<AgentToolAccess> {
    const raw = await this._ensure();
    return toToolAccess(await this._request<JsonObject>("GET", `/v1/agents/${raw.id}/tool_access`));
  }

  /**
   * Move it onto another model connection (a `Connection`, its name, or `"noclick"` for NoClick's key): its harness
   * and model too where that one runs another, its conversations carrying over from their next turn. The same call its
   * own `switch_model` tool makes, by its `modelSwitching` rule: any of the owner's own plans; a paid key on the
   * owner's own call, or with `evidence` citing where they said so (`{channel_id, message_id, quote}`), which NoClick
   * checks is theirs, for this switch or (`scope: "standing"`) whenever a plan runs out; else NoClick asks them.
   */
  async switchModel(connection: string | Connection, options: { reason?: string; evidence?: JsonObject; scope?: "once" | "standing" } = {}): Promise<ModelSwitchResult> {
    const raw = await this._ensure();
    const ref = await modelConnectionRef(connection, this._callScope());
    const done = await this._request<JsonObject>("POST", `/v1/agents/${raw.id}/model/switch`, {
      json: compact({ connection: ref, reason: options.reason, evidence: options.evidence, scope: options.scope ?? "once" }),
    });
    return {
      status: done.status as ModelSwitchResult["status"], connection: String(done.connection),
      harness: done.harness as string | undefined, model: done.model as string | undefined,
      pays: done.pays as ModelSwitchResult["pays"], requestId: done.request_id as string | undefined,
      message: done.message as string | undefined, raw: done,
    };
  }

  /** The owner's say-so for its paid keys, newest first: each with how, where and when they gave it. */
  async modelGrants(): Promise<ModelSwitchGrant[]> {
    const raw = await this._ensure();
    this._raw = await this._request<JsonObject>("GET", `/v1/agents/${raw.id}`);
    return ((this._raw.model_grants as JsonObject[]) ?? []).map(toModelSwitchGrant);
  }

  /** Let it move onto paid keys by itself (`connections`, or any): the owner's own call. */
  async grantModelSwitch(connections: (string | Connection)[] | null = null, options: { scope?: "once" | "standing" } = {}): Promise<ModelSwitchGrant> {
    const raw = await this._ensure();
    const refs = connections === null ? null : await Promise.all(connections.map(
      (c) => modelConnectionRef(c, this._callScope())));
    return toModelSwitchGrant(await this._request<JsonObject>("POST", `/v1/agents/${raw.id}/model/grants`, {
      json: { connections: refs, scope: options.scope ?? "standing" },
    }));
  }

  /** Take back the owner's say-so (a `ModelSwitchGrant` or its id). */
  async revokeModelGrant(grant: ModelSwitchGrant | string): Promise<ModelSwitchGrant> {
    const raw = await this._ensure();
    const id = typeof grant === "string" ? grant : grant.id;
    this._raw = await this._request<JsonObject>("PATCH", `/v1/agents/${raw.id}`, { json: { revoke_model_grants: [id] } });
    const revoked = ((this._raw.model_grants as JsonObject[]) ?? []).find((g) => g.id === id);
    if (!revoked) throw new Error(`grant ${id} isn't among the agent's model grants`);
    return toModelSwitchGrant(revoked);
  }

  /** Take back a grant (an `AgentGrant` or its id): its tools leave the agent; the connection stays the user's. */
  async revokeGrant(grant: string | AgentGrant): Promise<void> {
    const raw = await this._ensure();
    await this._request("DELETE", `/v1/agents/${raw.id}/grants/${typeof grant === "string" ? grant : grant.id}`);
  }

  /**
   * Delete the agent and its sub-agents: they go to the trash, restorable for 30 days (pending
   * wake-ups and jobs end now). Returns its `TrashItem`.
   */
  async delete(): Promise<TrashItem> {
    const raw = await this._ensure();
    return trashed(await this._request("DELETE", `/v1/agents/${raw.id}`), this);
  }

  // ── triggers ──

  /**
   * What wakes it besides a message: schedules, webhooks, app and NoClick events, queues, and the inboxes
   * and numbers that hand it mail and calls.
   */
  async triggers(): Promise<AgentTrigger[]> {
    const raw = await this._ensure();
    return (asList(await this._request("GET", `/v1/agents/${raw.id}/triggers`)) as JsonObject[]).map(toAgentTrigger);
  }

  /**
   * Add a trigger (up to 20): an `OnWebhook` (its `url` is where to POST), an `OnEvent` (`error` until its
   * connection is connected) or a `Cron` (`nextRun` says when it fires; `paused` while the agent is). Where
   * `fromName(name, { triggers })` sets the triggers, that code's list wins the next time it runs.
   */
  async addTrigger(trigger: TriggerDefinition): Promise<AgentTrigger> {
    const json = await triggerWire(trigger);
    const raw = await this._ensure();
    return toAgentTrigger(asObject(await this._request("POST", `/v1/agents/${raw.id}/triggers`, { json })));
  }

  /**
   * Remove a trigger: an `AgentTrigger`, its id, or the definition you added (`NotFound` if none matches; an
   * `OnWebhook` by its unique `name`). Mail and call triggers change on their inbox or number.
   */
  async removeTrigger(trigger: AgentTrigger | string | TriggerDefinition): Promise<void> {
    const raw = await this._ensure();
    await this._request("DELETE", `/v1/agents/${raw.id}/triggers/${await this.triggerId(trigger)}`);
  }

  // ── MCP servers ──

  /**
   * Its MCP servers, each a step of its automation, in the order they were added, with each one's state: how it
   * lets its client in (`signIn`), its `status` and `problem`, the `tools` its last run found, its `host` and
   * `icon`. With `conversation`, each as that conversation's coding harness last said it where that's newer
   * (`status` `connecting` too), and whether it can connect one again in place now (`reconnectable`:
   * `agent.conversation(name).reconnectToolServer(server.name)`).
   */
  async toolServers(options: { conversation?: string } = {}): Promise<AgentToolServer[]> {
    const raw = await this._ensure();
    const query = options.conversation ? { conversation: options.conversation } : undefined;
    return (asList(await this._request("GET", `/v1/agents/${raw.id}/tool_servers`, { query })) as JsonObject[])
      .map((server) => this.toolServer(server));
  }

  /** @internal */
  toolServer(raw: JsonObject): AgentToolServer {
    return toAgentToolServer(raw, async (server: AgentToolServer, options: LinkOptions) => {
      const agent = await this._ensure();
      const payload = await this._request(
        "POST", `/v1/agents/${agent.id}/tool_servers/${encodeURIComponent(server.id)}/connect_link`,
        { json: linkBody(options) });
      return ConnectLink._fromLink<AgentToolServer>(payload, { client: this._client, user: this._callScope() },
        TOOL_SERVER_SIGN_IN);
    });
  }

  /**
   * Give it an MCP server's tools from its next turn. The server is a step of its automation, reached at its public
   * https URL (`transport: "sse"` for one that speaks only the older SSE), named `name`, else after the URL's host
   * (`mcp.linear.app` is `linear`). `credential` is the account's own sign-in to it, which NoClick's MCP sign-in
   * makes, or `headers` carry the key it takes instead (`{ Authorization: "Bearer <key>" }`): kept as a credential,
   * sent on every request, never read back. A server that asks its client to sign in, given neither, is added
   * waiting for a person (`status` `needs_sign_in`): `server.connectLink()` signs them in. Up to 20. Returns the
   * `AgentToolServer` as added: its `id` is what `removeToolServer` takes.
   */
  async addToolServer(url: string, options: { name?: string; transport?: "http" | "sse"; credential?: string; headers?: Record<string, string> } = {}): Promise<AgentToolServer> {
    const raw = await this._ensure();
    const json: JsonObject = { url, transport: options.transport ?? "http" };
    if (options.name) json.name = options.name;
    if (options.credential) json.credential_id = options.credential;
    if (options.headers && Object.keys(options.headers).length) json.headers = options.headers;
    return this.toolServer(asObject(await this._request("POST", `/v1/agents/${raw.id}/tool_servers`, { json })));
  }

  /**
   * Replace an MCP server's headers. From its next turn it sends `headers` (a new key; `{}`: none), and those
   * given before are deleted.
   */
  async updateToolServer(server: string | AgentToolServer, headers: Record<string, string>): Promise<AgentToolServer> {
    const raw = await this._ensure();
    const step = typeof server === "string" ? server : server.id;
    return this.toolServer(asObject(await this._request("PATCH", `/v1/agents/${raw.id}/tool_servers/${encodeURIComponent(step)}`, { json: { headers } })));
  }

  /**
   * Take an MCP server away (by `AgentToolServer` or `id`). Its tools stop from its next turn and the headers
   * given it go; its sign-in stays connected.
   */
  async removeToolServer(server: string | AgentToolServer): Promise<void> {
    const raw = await this._ensure();
    const step = typeof server === "string" ? server : server.id;
    await this._request("DELETE", `/v1/agents/${raw.id}/tool_servers/${encodeURIComponent(step)}`);
  }

  /**
   * Change a trigger in place: it keeps its id, its history, and a webhook its URL. `cron` moves a schedule
   * to its time in its `tz` at once (and changes its `message` when the `Cron` has one); `message` changes what
   * any trigger's turn is told, and `conversation` the template a webhook, event or queue trigger keys
   * its conversations by (`null` clears either); `filters` replaces an app event's or NoClick event's filters (it
   * hears by them from the next delivery); `mode` changes the mode of a channel the agent sits in. A webhook's
   * name, an event's connection and event, and a queue stay: remove it and add another for that. `trigger` is an
   * `AgentTrigger`, its id, or the definition you added, as for `removeTrigger`. Checked and registered as
   * `addTrigger` does; a paused schedule takes its new time when it resumes. Returns the trigger as it is now,
   * with its new `nextRunAt`.
   */
  async updateTrigger(trigger: AgentTrigger | string | TriggerDefinition, changes: TriggerChanges): Promise<AgentTrigger> {
    const json: JsonObject = {
      ...(changes.cron ? changes.cron.toWire() : {}),
      ...(changes.message !== undefined ? { message: changes.message } : {}),
      ...(changes.conversation !== undefined ? { conversation: changes.conversation } : {}),
      ...(changes.filters !== undefined ? { filters: changes.filters } : {}),
      ...(changes.mode !== undefined ? { mode: changes.mode } : {}),
    };
    if (!Object.keys(json).length) {
      throw new TypeError("Nothing to change: pass cron, message, conversation, filters or mode.");
    }
    const raw = await this._ensure();
    const path = `/v1/agents/${raw.id}/triggers/${await this.triggerId(trigger)}`;
    return toAgentTrigger(asObject(await this._request("PATCH", path, { json })));
  }

  /**
   * Pause one trigger, the agent running on. A schedule is skipped (its `nextRunAt` still reads), a webhook's
   * calls and app or NoClick events are acknowledged and dropped, a queue's messages wait on the queue. Pause
   * the agent (`pause()`) to stop everything that wakes it. Returns the trigger as it is now.
   */
  async pauseTrigger(trigger: AgentTrigger | string | TriggerDefinition): Promise<AgentTrigger> {
    return this.switchTrigger(trigger, "pause");
  }

  /**
   * Resume a trigger paused on its own, or one its failures stopped. It wakes the agent again (a schedule at
   * its next run), unless the agent itself is paused.
   */
  async resumeTrigger(trigger: AgentTrigger | string | TriggerDefinition): Promise<AgentTrigger> {
    return this.switchTrigger(trigger, "resume");
  }

  private async switchTrigger(trigger: AgentTrigger | string | TriggerDefinition, to: "pause" | "resume"): Promise<AgentTrigger> {
    const raw = await this._ensure();
    const path = `/v1/agents/${raw.id}/triggers/${await this.triggerId(trigger)}/${to}`;
    return toAgentTrigger(asObject(await this._request("POST", path)));
  }

  /** An `AgentTrigger`'s id, an id, or the id of the trigger a definition names. */
  private async triggerId(trigger: AgentTrigger | string | TriggerDefinition): Promise<string> {
    if (typeof trigger === "string") return trigger;
    if (!(trigger instanceof Cron) && !isTriggerClass(trigger)) return trigger.id;
    const raw = await this._ensure();
    const wanted = namedBy(await triggerWire(trigger));
    const match = (await this.triggers()).find((t) => t.defined && namedBy({ kind: t.kind, ...t.spec }) === wanted);
    if (!match) {
      throw new NotFound(`${String(raw.name)} has no trigger like that.`, {
        nextStep: "List them with agent.triggers() and use one of those.",
        details: { agent_id: raw.id },
      });
    }
    return match.id;
  }

  // ── inboxes, pause, memory, files, sharing, streaming and test runs ──

  /** The inboxes whose mail wakes it (created or updated with it as their `agent`). */
  async inboxes(): Promise<Inbox[]> {
    const raw = await this._ensure();
    return await Inbox.list({ agent: String(raw.id), user: this._callScope(), client: this._client });
  }

  /**
   * Stop every trigger from waking it: scheduled runs are skipped (not made up), webhook calls get a 409
   * their sender can retry, and app events, mail and calls meanwhile don't wake it. Messages your code sends
   * still run, as do calls under way.
   */
  async pause(): Promise<this> {
    const raw = await this._ensure();
    this._raw = await this._request<JsonObject>("POST", `/v1/agents/${raw.id}/pause`);
    return this;
  }

  /** Let its triggers wake it again, including one that stopped after failing; a schedule picks up at its next run. */
  async resume(): Promise<this> {
    const raw = await this._ensure();
    this._raw = await this._request<JsonObject>("POST", `/v1/agents/${raw.id}/resume`);
    return this;
  }

  /** What it remembers across conversations: `list`, `search`, `read`, `save` and `delete` named entries. */
  get memory(): AgentMemory {
    return AgentMemory._of(this);
  }

  /** The files it works on: its one `/workspace` (a `conversation` is accepted and ignored). Sends nothing yet. */
  workspace(conversation?: string, options: { user?: UserOption } = {}): AgentWorkspace {
    return AgentWorkspace._of(this, conversation, resolveScope(options.user));
  }

  /**
   * The machine it works on, one whoever it answers. An `AgentSandbox`: what it is and costs, its files, and your own
   * commands on it beside its work. Without a `conversation` it's read through its session. Sends nothing yet.
   *
   *     const machine = coder.sandbox();
   *     const { status, cpu, memoryMb, spentUsdToday } = await machine.get();
   */
  sandbox(conversation?: string, options: { user?: UserOption } = {}): AgentSandbox {
    return AgentSandbox._of(this, conversation, resolveScope(options.user));
  }

  /** Its A2A agent card (the JSON other agents discover it by): its `name`, JSON-RPC `url` and `skills`. */
  async a2aCard(): Promise<JsonObject> {
    const raw = await this._ensure();
    return asObject(await this._request("GET", `/v1/agents/${raw.id}/a2a/card`));
  }

  /**
   * Turn on its public chat page, or read it if it's on. Anyone with the link can talk to the agent,
   * no sign-in, each visitor in conversations of their own. Visitors' turns bill to you.
   */
  async share(): Promise<ShareLink> {
    const raw = await this._ensure();
    const link = await this._request<JsonObject>("POST", `/v1/agents/${raw.id}/share`);
    return ShareLink._from(link, { agentId: String(raw.id), client: this._client, user: this._callScope() });
  }

  /** Its chat page as it is, without turning it on (`share()` does that); null if it was never shared. */
  async shareLink(): Promise<ShareLink | null> {
    const raw = await this._ensure();
    try {
      const link = await this._request<JsonObject>("GET", `/v1/agents/${raw.id}/share`);
      return ShareLink._from(link, { agentId: String(raw.id), client: this._client, user: this._callScope() });
    } catch (err) {
      if (err instanceof NotFound) return null;
      throw err;
    }
  }

  /**
   * Send `text` (and any `files`) and watch the turn: the reply as it's written, each tool call and result,
   * file, approval and long action, then `done` with the whole `AgentReply`. The same turn as
   * `message`, billed the same; a failed turn throws its error.
   */
  async *stream(
    text: string,
    options: { conversation?: string | null; files?: (Attachment | string)[]; user?: UserOption; signal?: AbortSignal } = {},
  ): AsyncGenerator<AgentEvent> {
    const raw = await this._ensure();
    const events = this._api._events("POST", `/v1/agents/${raw.id}/messages`, {
      json: compact({ text, conversation: options.conversation, attachments: attachmentIds(options.files) }),
      query: { stream: 1 },
      user: this._talkScope(options.user),
      signal: options.signal,
    });
    for await (const [type, data] of events) {
      yield toAgentEvent(type, data);
      if (type === "done") return;
    }
  }

  /**
   * Follow one conversation live, whoever moves it. Turns a trigger, an answered `ask` or an
   * approved held call started, messages sent from another client or session, and a person's
   * replies after a hand-off. Yields `message` (a whole message, with its `role`, `files` and, a reply, its `toolCalls`), `text`,
   * `tool_call` (`held` names the approval when policy holds it), `tool_result`, `file`, `approval`
   * and `operation` (from its `"noclick"` tools) and `status` events; a coding harness's turn adds `output` and
   * `diff` (`AgentEvent`). Your own turns show up too; tell them apart by `operationId`. It runs until you stop
   * reading or abort `signal`. `replay` starts with the moments of the last hour that are still kept, so a turn
   * joined halfway is seen from its start.
   */
  async *watch(conversation: string, options: { user?: UserOption; signal?: AbortSignal; replay?: boolean } = {}): AsyncGenerator<AgentEvent> {
    const raw = await this._ensure();
    const events = this._api._events("GET", `/v1/agents/${raw.id}/conversations/${encodeURIComponent(conversation)}/events`, {
      user: this._talkScope(options.user),
      query: options.replay ? { replay: 1 } : undefined,
      signal: options.signal,
    });
    for await (const [type, data] of events) yield toAgentEvent(type, data);
  }

  /**
   * A test run: a real turn where a simulated world answers every tool call, so nothing is sent or touched
   * and only its model connection need be connected. `scenario` sets that world;
   * without one, an ordinary busy day. Billed like a turn, against its budget; up to 10 per account queued or
   * running at once (`QuotaExceeded` past that). `wait()` resolves to the `Rehearsal`.
   */
  async rehearse(message: string, options: { scenario?: string; user?: UserOption } = {}): Promise<Operation<Rehearsal>> {
    const raw = await this._ensure();
    const scope = this._talkScope(options.user);
    const payload = await this._request("POST", `/v1/agents/${raw.id}/rehearsals`, {
      json: compact({ message, scenario: options.scenario }),
      user: scope,
    });
    return Operation._fromPayload<Rehearsal>(payload, { client: this._client, user: scope, kind: "agent.rehearse" });
  }

  /**
   * A test run of the turn a trigger would start now, without a real delivery. The agent reads what `sample` would
   * hand it (a webhook's body; an app event's or a NoClick event's data; a queue message's body; an email's
   * `{from, subject, text}`; a channel post's text or `{text, from}`), else a sample of its own (a schedule's or a
   * recurring wake-up's run; an app event's values placeholders in the shape it has reached your account in, no data
   * until one has; a NoClick event's from the event catalog), under the trigger's `message`, its tool calls answered
   * by a simulated world as in `rehearse`. A call and an approval can't be tested. `trigger` is an `AgentTrigger`,
   * its id, or the definition you added. `wait()` resolves to the `Rehearsal`.
   */
  async rehearseTrigger(trigger: AgentTrigger | string | TriggerDefinition,
                        options: { sample?: unknown } = {}): Promise<Operation<Rehearsal>> {
    const raw = await this._ensure();
    const path = `/v1/agents/${raw.id}/triggers/${await this.triggerId(trigger)}/test`;
    const payload = await this._request("POST", path, options.sample === undefined ? {} : {
      json: { sample: options.sample as JsonObject },
    });
    return Operation._fromPayload<Rehearsal>(payload, { client: this._client, user: this._callScope(), kind: "agent.rehearse" });
  }

  // ── wake-ups, children, jobs and questions ──

  /**
   * Wake it later in `conversation`. At a moment (`at`), after a while (`afterS`), when an operation
   * reaches a terminal status or a platform event happens (`when`, narrowed by `filters`), or at each
   * time of a schedule (`every`, a `Cron`: a routine, until it's canceled). Then the conversation
   * takes a turn whose message is the `note`, followed by what woke it; a running turn there goes
   * first. Durable, delivered once, billed and capped like any turn; one the account can't pay for
   * fails. A recurring one stays pending, due at its schedule's next time after each turn, so times
   * it missed fold into one turn. An agent holds up to 100 pending and 20 recurring; a time wake-up is
   * 1 minute to 365 days ahead, a schedule comes round at most every minute (every 15 for one the
   * agent sets itself), and a conversation's wake-ups at a time are delivered at least a minute apart (news, an
   * operation it waited on or a child's update, comes as soon as the conversation is free). Every agent can
   * also set, list, change and cancel its own with its `wake_me`, `list_wakeups` and `cancel_wakeup`
   * tools, in the conversation it's in or, with `conversation`, another of its own (never a channel's,
   * nor from a conversation with someone outside its scope), so work nobody is waiting on runs apart
   * from the thread a person reads. A channel's conversation (`channel:<its id>`) rejects with
   * `InvalidRequest`, as `message` does: only the channel starts turns there.
   *
   * ```ts
   * await assistant.wake("briefing", { every: new Cron("0 8 * * 1-5", { tz: "user" }),
   *   note: "Brief me on today's calendar and anything urgent in my inbox." });
   * ```
   */
  async wake(conversation: string, options: WakeOptions): Promise<Wakeup> {
    const json = await wakeWire(conversation, options);
    const raw = await this._ensure();
    const scope = this._talkScope(options.user);
    const view = await this._request<JsonObject>("POST", `/v1/agents/${raw.id}/wakeups`, { json, user: scope });
    return Wakeup._from(view, { client: this._client, user: scope });
  }

  /**
   * Its wake-ups in the acting user's conversations, newest first, or in those of the users
   * `userFilter` covers. That's `ALL_USERS`, `NO_USER`, a `User` or your id for one, read without the user
   * header, as `conversations` does. They're those your code and the agent set, and NoClick's own (a job's
   * update, a connect link it asked for being done, a decided approval); `conversation` and
   * `status` narrow them. Each one's `cancel()` acts in its own thread.
   */
  async wakeups(options: ReadOptions & { conversation?: string; status?: WakeupStatus; limit?: number } = {}): Promise<Wakeup[]> {
    const raw = await this._ensure();
    return await listAll(
      {
        path: `/v1/agents/${raw.id}/wakeups`, query: { conversation: options.conversation, status: options.status },
        user: options.userFilter === undefined ? this._talkScope(options.user) : options.user,
        userFilter: options.userFilter, client: this._client, limit: options.limit,
      },
      (row, user) => Wakeup._from(row, { client: this._client, user }),
    );
  }

  /**
   * Ask it something without stopping it. By default its model answers from a snapshot of the
   * conversation as it stands, with no tools; the question and answer aren't added to the
   * conversation, and its running turn carries on untouched (an `agent.ask` operation, billed like a
   * short turn). On a coding harness the snapshot holds the conversation to its last finished turn
   * plus what the running one has done so far: its NoClick tool calls and its own commands (with
   * their output), edits and reads, as its sandbox reported them. An agent on a Claude or ChatGPT plan rejects with `NotAvailable` (answering in a
   * one-off harness session is in invite-only beta). `interject: true` joins the running turn
   * instead (the harness's own steering; on `sdk`, before its next model call): the agent sees the
   * question, may change course, and the reply that turn ends with comes back; with nothing running
   * it's an ordinary message. `conversation` defaults to its session. Asked from another agent's turn,
   * it's an ordinary message: a job of the asker's whose reply wakes it.
   */
  async ask(
    question: string,
    options: { conversation?: string; interject?: boolean; timeoutS?: number; user?: UserOption } = {},
  ): Promise<AgentReply> {
    const raw = await this._ensure();
    const scope = this._talkScope(options.user);
    const payload = await this._request("POST", `/v1/agents/${raw.id}/ask`, {
      json: compact({ question, conversation: options.conversation, interject: options.interject ? true : undefined }),
      user: scope,
    });
    const operation = Operation._fromPayload<AgentReply>(payload, { client: this._client, user: scope, kind: "agent.ask" });
    return await operation.wait({ timeoutS: options.timeoutS });
  }

  /**
   * Make a child for one task and start it at once. The child lives where its parent does, on the
   * parent's harness, model and model connection unless told otherwise, and gets only tools its
   * parent has. `child.job` is the task: it runs while the child works on it and finishes when the
   * child's conversation goes quiet. `updates` are when NoClick makes the child report (`"done"`
   * always); every update wakes the parent in `conversation`, and those that come while it's busy
   * arrive together. An agent has up to 20 live children, 3 levels below an agent with no parent.
   * `Agent.create({ parent })` still makes a child without starting it.
   */
  async spawn(task: string, options: SpawnOptions = {}): Promise<Agent> {
    if (typeof task !== "string" || !task) throw new TypeError("spawn() needs the task: what the child works on");
    const updates = updatesWire(options.updates);
    const raw = await this._ensure();
    const owner = this._ownerScope(raw.user_id);
    const scope = this._talkScope(options.user);
    const view = await this._request<JsonObject>("POST", `/v1/agents/${raw.id}/children`, {
      json: compact({
        task,
        updates,
        conversation: options.conversation,
        instructions: options.instructions,
        tools: await toolRefs(options.tools, { scope: owner }),
        budget_usd_per_month: options.budgetUsd,
        ttl_s: options.ttlS,
        model: options.model,
        harness: options.harness,
        model_connection: await modelConnectionRef(options.modelConnection, owner),
        name: options.name,
        workstream: options.workstream,
        approvals: wireSettings(options.approvals),
      }),
      user: scope,
    });
    const child = new Agent({ raw: view, client: this._client, user: owner });
    if (view.job && typeof view.job === "object") child._job = Job._from(view.job, { client: this._client, user: scope });
    return child;
  }

  /** Its children, newest first (expired ones too, for their 30 days): `Agent.list({ parent })`, read where it lives. */
  async children(options: { status?: AgentStatus; limit?: number } = {}): Promise<Agent[]> {
    const raw = await this._ensure();
    return await Agent.list({ parent: String(raw.id), status: options.status, limit: options.limit, user: this._ownerScope(raw.user_id), client: this._client });
  }

  /**
   * The jobs it started, newest first: the tasks of the children it spawned, and the messages it sent
   * with its `agents` tools (whose only update is `done`).
   */
  async jobs(options: JobFilters = {}): Promise<Job[]> {
    if (options.kind !== undefined && !(options.kind in JOB_KINDS)) {
      throw new TypeError(`kind is task or message, not ${JSON.stringify(options.kind)}`);
    }
    const raw = await this._ensure();
    return await listAll(
      {
        path: `/v1/agents/${raw.id}/jobs`,
        query: {
          status: csv(options.status), kind: options.kind ? JOB_KINDS[options.kind] : undefined,
          agent_id: await agentId(options.agent), conversation: options.conversation,
        },
        user: this._ownerScope(raw.user_id), client: this._client, limit: options.limit,
      },
      (row, user) => Job._from(row, { client: this._client, user }),
    );
  }
}


/**
 * One conversation with an agent, as a chat reads and changes it: `agent.conversation(name)`.
 *
 *     const chat = coder.conversation("main");
 *     const { model, effort, efforts } = await chat.settings();
 *     const fork = await chat.fork({ message: "4" });
 */
export class AgentConversation {
  /** The conversation's key. */
  readonly name: string;
  private readonly agent: Agent;
  private readonly user: UserOption;

  private constructor(agent: Agent, name: string, user: UserOption) {
    this.agent = agent;
    this.name = name;
    this.user = user;
  }

  /** @internal */
  static _of(agent: Agent, name: string, user: UserOption): AgentConversation {
    return new AgentConversation(agent, name, user);
  }

  private async call(method: string, suffix: string, json?: JsonObject): Promise<JsonObject> {
    const raw = await this.agent._ensure();
    return asObject(await this.agent._request(method, `/v1/agents/${raw.id}/conversations/${encodeURIComponent(this.name)}${suffix}`,
      { json, user: this.agent._talkScope(this.user) }));
  }

  /**
   * What its next turn runs on.
   * Its `model`, `effort`, `speed` and `modelConnection` are the agent's (every conversation runs on them); `efforts`
   * and `speeds` are what its harness takes on that model, `accounts` what can pay for it.
   */
  async settings(): Promise<ConversationSettings> {
    return toConversationSettings(await this.call("GET", "/settings"));
  }

  /**
   * Change it from its next message: `permissionMode`, `title` (a rename) and `archived`. `model`, `effort`, `speed`
   * and `modelConnection` change the agent itself, for every conversation, as `Agent.update` does (`null` clears
   * `effort`, `speed` or `modelConnection`). Its harness stays the agent's.
   */
  async update(changes: ConversationChanges): Promise<ConversationSettings> {
    return toConversationSettings(await this.call("PATCH", "", conversationChanges(changes)));
  }

  /**
   * Copy it into a new conversation, up to and with a message's turn.
   * `message` is a `Message.id` (the whole thread when omitted); the fork keeps its permission mode. Its agent reads
   * the copy in its own history (`agentReads` `native`), or, where it can't, as context its first turn carries.
   */
  async fork(options: { message?: string; title?: string } = {}): Promise<Conversation> {
    return toConversation(await this.call("POST", "/fork", compact({ message: options.message, title: options.title })));
  }

  /**
   * Make it the agent's session again, like `claude --resume`: everyone talking to the agent shares it from now on,
   * and a message without a `conversation` goes to it. The agent's files stay as they are. Throws `Conflict` while
   * the agent is working on a turn, and `NotFound` for a conversation the agent never had.
   *
   *     const [earlier] = (await coder.conversations({ limit: 20 })).filter((c) => !c.active);
   *     await coder.conversation(earlier.conversation).resume();
   */
  async resume(): Promise<Conversation> {
    return toConversation(await this.call("POST", "/resume"));
  }

  /**
   * Go back to before a message you sent.
   * It and everything after it leave the thread and what the agent reads; `files: true` also puts the files its
   * edits since changed back as they were, before its next turn. Resolves to what was reverted (its `text`, for the
   * composer). Throws `Conflict` while a turn runs or the agent waits on an answer there.
   */
  async revert(message: string, options: { files?: boolean } = {}): Promise<ConversationRevert> {
    return toRevert(await this.call("POST", "/revert", { message, files: options.files === true }));
  }

  /** How full the model's context was at its last turn (a chat's `/context`). */
  async context(): Promise<ConversationContext> {
    return toContext(await this.call("GET", "/context"));
  }

  /** What it cost and what pays for its model (a chat's `/usage`). */
  async usage(): Promise<ConversationUsage> {
    return toUsage(await this.call("GET", "/usage"), toModelUsage);
  }

  /** The MCP servers its coding harness reaches its tools on: connected, connecting or failed, with their tools. */
  async toolServers(): Promise<ToolServers> {
    return toToolServers(await this.call("GET", "/tool_servers"));
  }

  /**
   * Do one tool server's handshake again, where its harness can (`toolServers().reconnect`): Claude Code and OpenCode
   * reconnect that server, Codex reloads all of them. Hermes Agent and OpenClaw connect theirs at every turn, so this
   * raises `noclick.Conflict` saying the next message reconnects them.
   */
  async reconnectToolServer(name: string): Promise<ToolServers> {
    return toToolServers(await this.call("POST", `/tool_servers/${encodeURIComponent(name)}/reconnect`));
  }

  /**
   * Tell one of its coding harness's own subagents something while it works: the `Task` (Claude Code) or `task`
   * (OpenCode) call `callId` in the conversation's running turn, as its events name it. No harness takes a message
   * into its subagent, so it joins the main session's turn, which reads whom it's for and passes it on; the thread
   * keeps it as yours (`Message.subagent`). Throws `Conflict` once that turn or the subagent has ended. A NoClick agent
   * it started takes messages itself (`Agent.send`).
   *
   *     await coder.conversation("main").messageSubagent("toolu_01", "Also check the admin routes.");
   */
  async messageSubagent(callId: string, text: string): Promise<Operation<AgentReply>> {
    const scope = this.agent._talkScope(this.user);
    const payload = await this.call("POST", `/subagents/${encodeURIComponent(callId)}/messages`, { text });
    return Operation._fromPayload<AgentReply>(payload, { client: this.agent._client, user: scope, kind: "agent.ask" });
  }

  /**
   * Run a command typed in a chat.
   * One NoClick has a control for (`/model opus`, `/effort high`, `/fast`, `/new`, `/context`, `/usage`,
   * `/btw <question>`) resolves to that control's `CommandResult`; any other runs as the harness's own command, its
   * turn's `Operation`.
   */
  async runCommand(name: string, args = "", options: { delivery?: MessageDelivery } = {}):
    Promise<CommandResult | Operation<AgentReply>> {
    const raw = await this.agent._ensure();
    const scope = this.agent._talkScope(this.user);
    const payload = await this.agent._request("POST", `/v1/agents/${raw.id}/messages`, {
      json: messageBody(null, { conversation: this.name, command: { name, arguments: args }, delivery: options.delivery }),
      user: scope,
    });
    const body = asObject(payload);
    if (body.object === "command_result") return toCommandResult(body);
    return Operation._fromPayload<AgentReply>(payload, { client: this.agent._client, user: scope, kind: "agent.message" });
  }
}
