/**
 * Hosted MCP servers: your tools at one URL for any MCP client.
 *
 *     const server = McpServer.fromName("crm-tools", { tools: ["hubspot", "search"], createIfMissing: true });
 *     console.log((await server.hydrate()).url);   // paste into Claude, ChatGPT, Cursor or any MCP client
 *
 * The tools are the ones a `Toolkit` or an agent takes (connections, single operations, `search`
 * and `fetch`), served over Streamable HTTP. Calls act in the server's user's connections, under
 * your policy, and bill like toolkit calls. A name that is no connection there serves an
 * integration's operations that need no account, on NoClick's key: `tools: ["exa.search"]` needs
 * no connection.
 */

import { toolRefs } from "./connection.ts";
import type { ToolRef } from "./connection.ts";
import { Conflict, NotFound } from "./errors.ts";
import { ApiObject, asList, createNamed, defined, listAll, listPage, num, parseTime, str } from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { resolveScope } from "./scope.ts";

/** What a server serves: the refs an agent or a `Toolkit` takes, or a `Toolkit`. */
export type McpServerTools = ToolRef[] | { refs: ToolRef[] };

/**
 * An MCP client that has connected to a server, as it named itself (`Claude`, `cursor`). `toolCount`
 * is how many tools it saw when it last listed them: fewer than the server serves means it listed
 * them before you added some, and most clients list again only when a session starts.
 */
export interface McpClient {
  name: string;
  version: string | null;
  firstSeenAt: Date | null;
  lastSeenAt: Date | null;
  toolCount: number | null;
  raw: JsonObject;
}

function toMcpClient(raw: JsonObject): McpClient {
  return {
    name: str(raw.name) ?? "unknown",
    version: str(raw.version),
    firstSeenAt: parseTime(raw.first_seen_at),
    lastSeenAt: parseTime(raw.last_seen_at),
    toolCount: num(raw.tool_count),
    raw,
  };
}

/**
 * Your tools at one URL, for Claude, ChatGPT, Cursor or any MCP client. Anyone with `url` can call
 * the tools, so keep it like a key and `rotate()` it if it leaks. `toolCount` is how many tools it
 * serves right now (a connection that isn't connected serves none); `lastClientAt` is when any
 * client last talked to it.
 */
export class McpServer extends ApiObject {
  private _createWith: { name: string; tools: McpServerTools } | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create a server called `name` (unique per account and user; a duplicate throws `Conflict`
   * with `existingId`, or with `allowExisting: true` returns the server already there, as it is: its tools
   * don't change), serving at most 64 tools. A name is a connection in the server's user (the
   * account for an account server), else an integration's operations that need no account (on
   * NoClick's key), so `"exa.search"` needs no connection. Operations with arguments bound
   * (`hubspot.only(...).bind(...)`) keep them out of every client's reach; there `{{user...}}` is the
   * server's user.
   */
  static async create(name: string, options: CallOptions & AllowExisting & { tools: McpServerTools }): Promise<McpServer> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/mcp_servers", { name, tools: (await toolRefs(options.tools, { scope })) ?? [] }, {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new McpServer({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the server called `name` for the current (or given) user. Given `tools`, it gets
   * the server and sets them, on every run. `createIfMissing` creates it when there's none; without it, a
   * missing server throws `NotFound`. Its URL stays the same either way. Each run is a write: set the tools at startup or in a
   * setup script, and take the bare `fromName` in request handlers.
   */
  static fromName(name: string, options: CallOptions & { tools?: McpServerTools; createIfMissing?: boolean } = {}): McpServer {
    const server = new McpServer({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing && !options.tools) throw new TypeError("McpServer.fromName(..., { createIfMissing: true }) needs tools");
    server._creates = Boolean(options.createIfMissing);
    if (options.tools) server._createWith = { name, tools: options.tools };
    return server;
  }

  static fromId(serverId: string, options: CallOptions = {}): McpServer {
    return new McpServer({ hints: { id: serverId }, client: options.client, user: options.user });
  }

  static async get(serverId: string, options: CallOptions = {}): Promise<McpServer> {
    return await McpServer.fromId(serverId, options).hydrate();
  }

  /** The current user's servers (the account's own outside `asUser`, or those `userFilter` covers). */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<McpServer[]> {
    return await listAll({ ...options, path: "/v1/mcp_servers" }, (raw, user) => new McpServer({ raw, client: options.client, user }));
  }

  /** One page of servers; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<McpServer>> {
    return await listPage({ ...options, path: "/v1/mcp_servers" }, (raw, user) => new McpServer({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** The URL MCP clients connect to; the path is its secret. */
  get url(): string {
    return this._field("url");
  }
  /** What it serves, as you listed it: refs, and `{ tool, bind }` for an operation with arguments bound. */
  get tools(): (string | JsonObject)[] {
    return this._field("tools") ?? [];
  }
  get toolCount(): number {
    return this._field("tool_count") ?? 0;
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** When a client last called it (null until one does). */
  get lastClientAt(): Date | null {
    return parseTime(this._field("last_client_at"));
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/mcp_servers/${id}`);
    const name = String(this._hints.name);
    const rows = (asList(await this._request("GET", "/v1/mcp_servers", { query: { name } })) as JsonObject[]).filter((row) => row.name === name);
    if (rows.length) return await this.converge(rows[0]);
    if (!this._createWith || !this._creates) {
      throw new NotFound(`No MCP server is named "${name}".`, {
        nextStep: "Create it with McpServer.create(...) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    try {
      const json = { name, tools: (await toolRefs(this._createWith.tools, { scope: this._scope })) ?? [] };
      return await this._request<JsonObject>("POST", "/v1/mcp_servers", { json });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/mcp_servers/${err.existingId}`));
    }
  }

  /** Set the tools `fromName` was given on an existing server. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    if (!this._createWith) return raw;
    const tools = (await toolRefs(this._createWith.tools, { scope: this._scope })) ?? [];
    if (JSON.stringify(raw.tools ?? null) === JSON.stringify(tools)) return raw;
    return await this._request<JsonObject>("PATCH", `/v1/mcp_servers/${raw.id}`, { json: { tools } });
  }

  private async path(): Promise<string> {
    return `/v1/mcp_servers/${(await this._ensure()).id}`;
  }

  /** Change what it serves, or its name; the URL stays. A connected client sees new tools when it next lists them. */
  async update(changes: { tools?: McpServerTools; name?: string }): Promise<this> {
    const json = defined({ name: changes.name, tools: await toolRefs(changes.tools, { scope: this._callScope() }) });
    this._raw = await this._request<JsonObject>("PATCH", await this.path(), { json });
    return this;
  }

  /** Give it a new URL; the old one stops answering at once, so reconnect your clients with the new one. */
  async rotate(): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `${await this.path()}/rotate`);
    return this;
  }

  /**
   * The MCP clients that have connected, most recently seen first: whether your agent has actually
   * started using the server, apart from whether the server is ready.
   */
  async clients(): Promise<McpClient[]> {
    return (asList(await this._request("GET", `${await this.path()}/clients`)) as JsonObject[]).map(toMcpClient);
  }

  /** Delete the server; its URL stops answering. The connections it served stay. */
  async delete(): Promise<void> {
    await this._request("DELETE", await this.path());
  }
}
