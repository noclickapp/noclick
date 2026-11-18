/**
 * Tool calls: every integration run, capability call and agent tool call your
 * platform work made, newest first.
 *
 *     const { data, nextCursor } = await ToolCall.listPage({ tool: "gmail.*", status: "error", userFilter: ALL_USERS });
 */

import { resolveClient } from "./client.ts";
import { asObject, isoTime, listAll, listPage, num, parseTime, readScope, refId, requiredNumber, str } from "./object.ts";
import type { ApiObject, JsonObject, Page, PageOptions, ReadOptions } from "./object.ts";

export interface ToolCallFilters extends ReadOptions {
  /** An `Agent` or agent id: its turns' calls. */
  agent?: string | ApiObject;
  /** A tool name or a `*` pattern (`gmail.*`), dotted or wire form. */
  tool?: string;
  status?: "success" | "error";
  /** `api`: your own calls; `agent`: your agents' turns; `mcp_server`: MCP clients' calls through your hosted servers. */
  source?: "api" | "agent" | "mcp_server";
  since?: Date | string;
  until?: Date | string;
}

export interface ToolCallSummary {
  total: number;
  success: number;
  error: number;
  raw: JsonObject;
}

async function query(filters: ToolCallFilters) {
  return {
    agent_id: await refId(filters.agent),
    tool: filters.tool,
    status: filters.status,
    source: filters.source,
    since: isoTime(filters.since),
    until: isoTime(filters.until),
  };
}

/** One recorded tool call. */
export class ToolCall {
  readonly id: string;
  /**
   * The name policy judges it by: dotted (`gmail.send_email_message`), or a capability's own (`search`,
   * `fetch`, an agent's too).
   */
  readonly toolName: string;
  readonly toolType: string | null;
  readonly operation: string | null;
  readonly status: string | null;
  readonly error: string | null;
  readonly arguments: JsonObject;
  readonly resultPreview: string | null;
  readonly durationMs: number | null;
  readonly credentialId: string | null;
  /** The connection it ran on, as the account names it (a named connection's name, else its name in the app). */
  readonly connection: string | null;
  readonly userId: string | null;
  readonly agentId: string | null;
  readonly conversation: string | null;
  readonly executionId: string | null;
  /** `api`, `agent` or `mcp_server`. */
  readonly source: string | null;
  /** The hosted MCP server an MCP client called it through (`source` `mcp_server`). */
  readonly mcpServerId: string | null;
  readonly createdAt: Date | null;
  readonly raw: JsonObject;

  /** @internal */
  constructor(raw: JsonObject) {
    this.id = String(raw.id);
    this.toolName = str(raw.tool_name) ?? "";
    this.toolType = str(raw.tool_type);
    this.operation = str(raw.operation);
    this.status = str(raw.status);
    this.error = str(raw.error);
    this.arguments = asObject(raw.arguments);
    this.resultPreview = str(raw.result_preview);
    this.durationMs = num(raw.duration_ms);
    this.credentialId = str(raw.credential_id);
    this.connection = str(raw.connection);
    this.userId = str(raw.user_id);
    this.agentId = str(raw.agent_id);
    this.conversation = str(raw.conversation);
    this.executionId = str(raw.execution_id);
    this.source = str(raw.source);
    this.mcpServerId = str(raw.mcp_server_id);
    this.createdAt = parseTime(raw.created_at);
    this.raw = raw;
  }

  /** Every matching call (or the first `limit`). */
  static async list(options: ToolCallFilters & { limit?: number } = {}): Promise<ToolCall[]> {
    return await listAll({ ...options, path: "/v1/tool_calls", query: await query(options) }, (raw) => new ToolCall(raw));
  }

  /** One page of matching calls; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ToolCallFilters & PageOptions = {}): Promise<Page<ToolCall>> {
    return await listPage({ ...options, path: "/v1/tool_calls", query: await query(options) }, (raw) => new ToolCall(raw));
  }

  /** How many calls match, and how many of them errored. */
  static async summary(options: ToolCallFilters = {}): Promise<ToolCallSummary> {
    const { user, userId } = await readScope(options);
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/tool_calls/summary", {
      query: { ...(await query(options)), user_id: userId },
      user,
    }));
    return { total: requiredNumber(raw, "total"), success: requiredNumber(raw, "success"), error: requiredNumber(raw, "error"), raw };
  }
}
