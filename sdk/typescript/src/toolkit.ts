/**
 * Toolkits: your connections' operations, the operations that need no account, and capabilities
 * as LLM tools.
 *
 *     const gmail = Connection.fromName("gmail", { integration: "gmail", createIfMissing: true });
 *     const toolkit = new Toolkit(["search", gmail]);
 *     const response = await anthropic.messages.create({ ..., tools: await toolkit.definitions() });
 *     messages.push({ role: "user", content: await toolkit.handle(response) });
 *
 * A call never throws for something the model can act on: a missing connection, a policy refusal
 * or a hold for approval comes back as an `isError` result. A hold's `approvalRequired` is never
 * shown to the model; pass `onApproval` to the handle helpers to receive it, and `onConnect` to
 * receive each result that needs a connection. Once the person approves, the identical call goes
 * through.
 */

import { BucketOperations } from "./bucket.ts";
import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { Connection, ConnectionOperations, toolRefs } from "./connection.ts";
import type { ToolRef, WireTool } from "./connection.ts";
import { HumanRequest } from "./human.ts";
import { McpServer } from "./mcpServer.ts";
import { asObject, compact, str } from "./object.ts";
import type { JsonObject } from "./object.ts";
import { resolveScope } from "./scope.ts";
import type { UserOption } from "./scope.ts";
import { Database, DatabaseOperations } from "./database.ts";

export type ToolFormat = "anthropic" | "openai" | "mcp";

/** An unconnected account's `needs_connection` note: which connection, and where to (re)connect it. */
export interface NeedsConnectionInfo {
  connection?: string;
  integration?: string;
  connect_url?: string;
  [key: string]: unknown;
}

/**
 * A call held for a person's approval. `request_id` (the request a person answers), `approve_url`
 * and `operation` (the approval's operation object) are null unless the request is addressed to
 * you; the approver is emailed either way. Once approved, retry the identical call.
 */
export interface ApprovalRequiredInfo {
  approval_id?: string;
  request_id?: string | null;
  approve_url?: string | null;
  operation?: JsonObject | null;
  approver?: "user" | "owner";
  [key: string]: unknown;
}

/** The outcome of one tool call. An unconnected account is a normal result with `needsConnection`. */
export interface ToolResult {
  name: string;
  content: unknown;
  isError: boolean;
  needsConnection: NeedsConnectionInfo | null;
  connectUrl: string | null;
  approvalRequired: ApprovalRequiredInfo | null;
  /** The approval link, when the call waits for your approval; once approved, repeat the identical call. */
  approveUrl: string | null;
  /**
   * The approval a held call waits on, as a request: `wait()` resolves to `true` once approved. Null
   * unless the call was held and the request is addressed to you.
   */
  approval: HumanRequest<boolean> | null;
  /** The arguments the call was made with, as the model gave them. */
  arguments: JsonObject;
  /** The model's id for the call when it came through `handle` or `handleOpenAI`; null from `call`. */
  callId: string | null;
  /** The content as one string (what an OpenAI tool message carries). */
  text: string;
  raw: JsonObject;
}

export interface AnthropicToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: unknown;
  is_error: boolean;
}

/** Receives each call held for approval, in call order (the model sees only its error content). */
export type OnApproval = (result: ToolResult) => void | Promise<void>;
/** Receives each call whose `needsConnection` is set, in call order, so your app can show the connect link. */
export type OnConnect = (result: ToolResult) => void | Promise<void>;

export interface HandleOptions {
  user?: UserOption;
  onApproval?: OnApproval;
  onConnect?: OnConnect;
}

async function report(results: ToolResult[], options: HandleOptions): Promise<void> {
  for (const result of results) {
    if (result.approvalRequired && options.onApproval) await options.onApproval(result);
    if (result.needsConnection && options.onConnect) await options.onConnect(result);
  }
}

export type OpenAIToolOutput =
  | { role: "tool"; tool_call_id: string; content: string }
  | { type: "function_call_output"; call_id: string; output: string };

function get(obj: unknown, key: string): unknown {
  return obj && typeof obj === "object" ? (obj as Record<string, unknown>)[key] : undefined;
}

function asText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content) && content.length && content.every((b) => get(b, "type") === "text")) {
    return content.map((b) => String(get(b, "text") ?? "")).join("\n");
  }
  return JSON.stringify(content ?? null);
}

function asAnthropicContent(content: unknown): unknown {
  if (typeof content === "string") return content;
  if (Array.isArray(content) && content.every((b) => b && typeof b === "object" && "type" in b)) return content;
  return JSON.stringify(content ?? null);
}

function toolRef(ref: ToolRef): ToolRef {
  const source = typeof ref === "object" && ref !== null && typeof (ref as { _toolRefs?: unknown })._toolRefs === "function";
  if (typeof ref === "string" || ref instanceof Connection || ref instanceof ConnectionOperations || ref instanceof Database || source) {
    return ref;
  }
  throw new TypeError(`Toolkit tools are Connections, Databases or names like "gmail" or "gmail.send_email_message", not ${JSON.stringify(ref)}`);
}

/** `[id, name, input]` for each `tool_use` block in a Message, a message object, or a list of blocks. */
function anthropicToolUses(content: unknown): [string, string, JsonObject][] {
  let blocks: unknown = content;
  if (!Array.isArray(blocks) && get(blocks, "type") !== "tool_use") blocks = get(blocks, "content") ?? blocks;
  if (!Array.isArray(blocks)) blocks = [blocks];
  return (blocks as unknown[])
    .filter((block) => get(block, "type") === "tool_use")
    .map((block) => [String(get(block, "id")), String(get(block, "name")), asObject(get(block, "input"))]);
}

/** `[id, name, rawArguments, shape]` from a ChatCompletion, a message, a tool_calls list, or Responses items. */
function openAIToolCalls(input: unknown): [string, string, unknown, "chat" | "responses"][] {
  let calls: unknown = input;
  const choices = get(calls, "choices");
  if (Array.isArray(choices)) calls = get(choices[0], "message");
  if (!Array.isArray(calls)) {
    const inner = get(calls, "tool_calls") ?? get(calls, "output");
    calls = Array.isArray(inner) ? inner : [calls];
  }
  const found: [string, string, unknown, "chat" | "responses"][] = [];
  for (const call of calls as unknown[]) {
    if (get(call, "type") === "function_call") {
      found.push([String(get(call, "call_id")), String(get(call, "name")), get(call, "arguments"), "responses"]);
    } else if (get(call, "function")) {
      const fn = get(call, "function");
      found.push([String(get(call, "id")), String(get(fn, "name")), get(fn, "arguments"), "chat"]);
    }
  }
  return found;
}

/**
 * A set of tools for your LLM. Entries are connections (a `Connection` or its
 * name: every operation, as `{connection}__{operation}` tools), single
 * operations (`"gmail.send_email_message"`), capabilities (`"search"`,
 * `"fetch"`, `"code"`) or a `Database` (`{database}__query`, `__execute` and `__schema`;
 * invite-only beta), a `Bucket` and operations with arguments bound
 * (`gmail.only("send_email_message").bind({ to })`: the bound parameters leave the tool's schema and
 * are filled on every call, so a toolkit sends its entries with each call). A `Connection` object
 * from another scope, another user's or the
 * account's, stays that connection (a key acting for the whole account only). A name resolves for the user the calls
 * act for (`user` if given, else the user current at each call, `asUser`), so one module-level
 * toolkit serves every user: a connection there, else an integration's operations that need no
 * account (on NoClick's key), so `"exa.search"` needs no connection.
 */
export class Toolkit {
  /** What was passed: names, `"name.operation"` strings and `Connection` objects. */
  readonly refs: ToolRef[];
  private readonly scope: UserOption;
  private readonly client: NoClick | undefined;
  private readonly cache = new Map<string, JsonObject[]>();
  /**
   * Whether a simulated world answers every call instead of the real accounts: the definitions are the real
   * ones, nothing is read or sent, and each answer is billed as AI at NoClick's model price.
   */
  readonly simulated: boolean;
  /** What that world is like; its answers keep to it. */
  readonly scenario: string | null;
  /** One toolkit is one world: what a call creates, later calls see (for 30 minutes after the last). */
  private readonly world: string | null;

  constructor(
    tools: ToolRef | ToolRef[],
    options: { user?: UserOption; client?: NoClick; simulated?: boolean; scenario?: string } = {},
  ) {
    this.refs = (Array.isArray(tools) ? tools : [tools]).map(toolRef);
    this.scope = options.user;
    this.client = options.client;
    this.simulated = options.simulated ?? false;
    if (options.scenario !== undefined && !this.simulated) {
      throw new TypeError("A scenario describes the simulated world; pass simulated: true with it.");
    }
    this.scenario = options.scenario ?? null;
    this.world = this.simulated ? `world_${(globalThis.crypto?.randomUUID?.() ?? `${Date.now()}${Math.random()}`).replace(/[^0-9a-z]/g, "")}` : null;
  }

  /** The refs as names (a `Connection` known only by id shows its id until used). */
  get tools(): string[] {
    const nameOf = (c: Connection | Database) => String(c._known("name") ?? c._known("id"));
    return this.refs.flatMap((ref) =>
      typeof ref === "string"
        ? [ref]
        : ref instanceof ConnectionOperations
          ? ref.operations.map((op) => `${nameOf(ref.connection)}.${op}`)
          : ref instanceof DatabaseOperations
            ? ref.operations.map((op) => `${nameOf(ref.database)}.${op}`)
            : ref instanceof BucketOperations
              ? ref.operations.map((op) => `${String(ref.bucket._known("name") ?? ref.bucket._known("id"))}.${op}`)
              : ref instanceof Connection || ref instanceof Database
                ? [nameOf(ref)]
                : "_known" in ref && typeof ref._known === "function"
                  ? [String(ref._known("name") ?? ref._known("id"))]
                  : [],
    );
  }

  /** The wire refs for the user a call acts for (a connection from another scope goes by id). */
  private wireRefs(user: UserOption): Promise<WireTool[] | undefined> {
    return toolRefs(this.refs, { scope: user !== undefined ? user : this.scope });
  }

  private post(path: string, body: JsonObject, user: UserOption): Promise<unknown> {
    return resolveClient(this.client).request("POST", path, {
      json: body,
      user: user !== undefined ? user : this.scope,
    });
  }

  /**
   * These tools as a hosted MCP server called `name`, in the toolkit's user (`McpServer.fromName`
   * with `createIfMissing`). Sends nothing yet.
   */
  mcpServer(name: string): McpServer {
    if (this.simulated) throw new TypeError("A hosted MCP server calls the real accounts; build it from a toolkit without simulated.");
    return McpServer.fromName(name, { tools: this.refs, createIfMissing: true, user: this.scope, client: this.client });
  }

  /** Tool definitions to pass straight to your LLM API. Cached per format. */
  async definitions(options: { format?: ToolFormat; user?: UserOption } = {}): Promise<JsonObject[]> {
    const format = options.format ?? "anthropic";
    let tools = this.cache.get(format);
    if (!tools) {
      const refs = await this.wireRefs(options.user);
      const response = asObject(await this.post("/v1/toolkits/definitions", { tools: refs ?? [], format }, options.user));
      tools = Array.isArray(response.tools) ? (response.tools as JsonObject[]) : [];
      this.cache.set(format, tools);
    }
    return tools;
  }

  /**
   * Run one tool by its wire name (`gmail__send_email_message`, `search`). A policy refusal or a hold is
   * an `isError` result, never a throw; a held call goes through once approved when it is repeated
   * with the same arguments (`approvalId` names the approval explicitly).
   */
  async call(
    name: string,
    args: JsonObject = {},
    options: { approvalId?: string; user?: UserOption } = {},
  ): Promise<ToolResult> {
    const simulated = this.world ? compact({ world: this.world, scenario: this.scenario }) : undefined;
    // A name resolves for the acting user; a connection from another scope, and bound arguments or a
    // person, need their refs.
    const refs = this.refs.some((ref) => typeof ref !== "string" && !(ref instanceof Database)) ? ((await this.wireRefs(options.user)) ?? []) : [];
    const tools = refs.some((ref) => typeof ref !== "string" || ref.startsWith("connection:")) ? refs : undefined;
    const raw = asObject(await this.post(
      "/v1/toolkits/call",
      compact({ name, arguments: args, approval_id: options.approvalId, simulated, tools }),
      options.user,
    ));
    const needs = raw.needs_connection && typeof raw.needs_connection === "object" ? (raw.needs_connection as NeedsConnectionInfo) : null;
    const approval = raw.approval_required && typeof raw.approval_required === "object"
      ? (raw.approval_required as ApprovalRequiredInfo) : null;
    return {
      name: str(raw.name) ?? name,
      content: raw.content,
      isError: Boolean(raw.is_error),
      needsConnection: needs,
      connectUrl: needs ? str(needs.connect_url) : null,
      approvalRequired: approval,
      approveUrl: approval ? str(approval.approve_url) : null,
      approval: approval && HumanRequest._held(approval, {
        client: this.client, user: resolveScope(options.user !== undefined ? options.user : this.scope),
      }),
      arguments: { ...args },
      callId: null,
      text: asText(raw.content),
      raw,
    };
  }

  /**
   * Run every Anthropic `tool_use` block (from a Message, its `content` list,
   * or plain objects) concurrently and return the `tool_result` blocks for the
   * next user turn. `onApproval` receives each call held for approval, and `onConnect` each one whose
   * `needsConnection` is set, so your app can show the user the connect link itself. Each result
   * carries the model's `callId` and the `arguments`.
   */
  async handle(content: unknown, options: HandleOptions = {}): Promise<AnthropicToolResultBlock[]> {
    const uses = anthropicToolUses(content);
    const results = await Promise.all(
      uses.map(async ([id, name, input]) => ({ ...(await this.call(name, input, { user: options.user })), callId: id })),
    );
    await report(results, options);
    return uses.map(([id], i) => ({
      type: "tool_result",
      tool_use_id: id,
      content: asAnthropicContent(results[i].content),
      is_error: results[i].isError,
    }));
  }

  /** @deprecated Use `handle`. */
  async handleAnthropic(content: unknown, options: HandleOptions = {}): Promise<AnthropicToolResultBlock[]> {
    return await this.handle(content, options);
  }

  /**
   * Run OpenAI tool calls (a ChatCompletion, its message, a `tool_calls` list,
   * or Responses `function_call` items) and return `{ role: "tool" }` messages
   * (or `function_call_output` items). `onApproval` and `onConnect` work as in `handle`.
   */
  async handleOpenAI(toolCalls: unknown, options: HandleOptions = {}): Promise<OpenAIToolOutput[]> {
    const calls = openAIToolCalls(toolCalls);
    const outputs = await Promise.all(calls.map(async ([id, name, rawArgs]): Promise<string | ToolResult> => {
      let args: unknown = rawArgs;
      if (typeof rawArgs === "string") {
        try {
          args = rawArgs.trim() ? JSON.parse(rawArgs) : {};
        } catch {
          return `The arguments for ${name} were not valid JSON: ${rawArgs.slice(0, 200)}`;
        }
      }
      return { ...(await this.call(name, asObject(args), { user: options.user })), callId: id };
    }));
    await report(outputs.filter((o): o is ToolResult => typeof o !== "string"), options);
    const texts = outputs.map((o) => (typeof o === "string" ? o : o.text));
    return calls.map(([id, , , shape], i): OpenAIToolOutput =>
      shape === "responses"
        ? { type: "function_call_output", call_id: id, output: texts[i] }
        : { role: "tool", tool_call_id: id, content: texts[i] },
    );
  }
}
