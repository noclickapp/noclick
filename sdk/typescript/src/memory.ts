/**
 * Memories: named notes any agent of their scope can attach.
 *
 *     const company = Memory.fromName("company", { createIfMissing: true });
 *     await company.save("refunds", "Within 30 days, to the original card.", { description: "Our refund rules" });
 *     const support = Agent.fromName("support", { createIfMissing: true, instructions: "...", memories: [company] });
 *     const closer = Agent.fromName("closer", { createIfMissing: true, instructions: "...", memories: [company.writable()] });
 *
 * Every agent also has a memory of its own, `agent.memory`, which it always reads and writes. A memory
 * attached to it is read-only unless attached with `writable()`; every turn starts with the names and
 * descriptions of every entry it can read, its own memory's first.
 */

import { AgentMemory, toMemoryEntry, toMemoryEntryVersion } from "./agentExtras.ts";
import type { MemoryEntry, MemoryEntryVersion } from "./agentExtras.ts";
import { Conflict, NotFound } from "./errors.ts";
import { ApiObject, asList, asObject, compact, createNamed, isUuid, listAll, listPage, num, parseTime, refId, str } from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { resolveScope } from "./scope.ts";
import type { UserOption, UserRef } from "./scope.ts";
import { TrashItem, trashed } from "./trash.ts";

/** An agent that attaches a memory, and whether it may write it. */
export interface MemoryAttachment {
  id: string;
  name: string;
  writes: boolean;
}

/** A memory attached with writes (`memory.writable()`): the agent may change it as well as read it. */
export class MemoryLink {
  readonly memory: Memory | AgentMemory;
  readonly writes = true;

  /** @internal */
  constructor(memory: Memory | AgentMemory) {
    this.memory = memory;
  }
}

/** A memory to attach: a `Memory`, `memory.writable()`, another agent's `agent.memory`, or a memory's id or name. */
export type MemoryRef = string | Memory | MemoryLink | AgentMemory;

/**
 * Named notes any agent of its scope can attach: the account's (every user's agents may read them)
 * or one user's. Its entries are what `agent.memory` holds: a name, a one-line description, Markdown
 * content and a version. A memory of the account keeps two layers, as an account agent's own memory
 * does: its own entries, and each user's, which only that user's conversations see.
 */
export class Memory extends ApiObject {
  private _createWith: JsonObject | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create an empty memory (1-64 letters, digits and `. _ -`), unique by name per user, or for the
   * account outside `asUser` (a taken name throws `Conflict` with `existingId`, or with `allowExisting: true`
   * returns the memory already there, entries and description as they are).
   */
  static async create(name: string, options: CallOptions & AllowExisting & { description?: string } = {}): Promise<Memory> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/memories", compact({ name, description: options.description }), {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new Memory({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the memory called `name`. Acting for a user, that user's own memory is found
   * first, then the account's. With `createIfMissing` the current (or given) user's is created on first use.
   */
  static fromName(name: string, options: CallOptions & { createIfMissing?: boolean; description?: string } = {}): Memory {
    const memory = new Memory({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing) memory._createWith = compact({ name, description: options.description });
    return memory;
  }

  /** A lazy reference to a memory by id, such as an agent's own (`agent.memoryId`). */
  static fromId(memoryId: string, options: CallOptions = {}): Memory {
    return new Memory({ hints: { id: memoryId }, client: options.client, user: options.user });
  }

  static async get(memoryId: string, options: CallOptions = {}): Promise<Memory> {
    return await Memory.fromId(memoryId, options).hydrate();
  }

  /**
   * The current user's named memories and the account's (or those `userFilter` covers); an agent's own is
   * `agent.memory`. With `agent`, what that agent reads: its own memory first, then those it attaches, in order.
   */
  static async list(options: ReadOptions & { limit?: number; agent?: string | ApiObject } = {}): Promise<Memory[]> {
    const agentId = await refId(options.agent);
    return await listAll({ ...options, path: "/v1/memories", query: { agent_id: agentId } },
      (raw, user) => new Memory({ raw, client: options.client, user }));
  }

  /** One page of named memories; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Memory>> {
    return await listPage({ ...options, path: "/v1/memories" }, (raw, user) => new Memory({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }

  /** Its name, unique in its scope (null for an agent's own memory). */
  get name(): string | null {
    return this._field("name");
  }

  get description(): string | null {
    return this._field("description");
  }

  /** The agent whose own memory this is (null for a memory with a name). */
  get agentId(): string | null {
    return this._field("agent_id");
  }

  /** The agents that attach it besides, and whether each writes it. */
  get attachedTo(): MemoryAttachment[] {
    const rows = this._field<unknown>("attached_to");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((a) => ({
      id: str(a.id) ?? "", name: str(a.name) ?? "", writes: a.writes === true,
    }));
  }

  /** How many entries it holds, in all its layers. */
  get entryCount(): number | null {
    return num(this._field("entry_count"));
  }

  get userId(): string | null {
    return this._field("user_id");
  }

  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  get updatedAt(): Date | null {
    return parseTime(this._field("updated_at"));
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/memories/${id}`);
    const name = String(this._hints.name);
    const rows = (asList(await this._request("GET", "/v1/memories", { query: { name } })) as JsonObject[]).filter((r) => r.name === name);
    // This scope's own memory first; a definition is only ever for its own.
    const own = rows.filter((r) => Boolean(r.user_id) === Boolean(this._scope));
    const row = this._createWith ? own[0] : (own[0] ?? rows[0]);
    if (row) return row;
    if (!this._createWith) {
      throw new NotFound(`No memory is named "${name}".`, {
        nextStep: "Create it with Memory.create(...) or pass { createIfMissing: true }.",
        details: { name, kind: "memory" },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/memories", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this._request<JsonObject>("GET", `/v1/memories/${err.existingId}`);
    }
  }

  private async route(suffix = ""): Promise<string> {
    if (!this._known("id")) await this._ensure();
    return `/v1/memories/${String(this._known("id"))}${suffix}`;
  }

  /** Whose layer a call reads or writes: a user's memory's own user's, else the acting user's. */
  private layer(user: UserOption): UserRef | null {
    return this._ownerScope(this._known("user_id")) ?? resolveScope(user);
  }

  /**
   * This memory, for an agent's `memories`, with writes: the agent may save to it and forget from it,
   * not only read it. Only a call acting for the memory's own scope can attach it so.
   */
  writable(): MemoryLink {
    return new MemoryLink(this);
  }

  /** Rename it, or change its description; an agent's own memory takes no name. */
  async update(changes: { name?: string; description?: string }): Promise<Memory> {
    this._raw = asObject(await this._request("PATCH", await this.route(), { json: compact(changes) }));
    return this;
  }

  /**
   * Delete it and every entry in it: it goes to the trash, restorable for 30 days, and comes off every agent that
   * attaches it (restoring puts it back on them); an agent's own memory goes only with its agent.
   */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this.route()), this);
  }

  /** The entries of one layer (the account's outside `asUser`, else the user's), by name, without their content. */
  async entries(options: { user?: UserOption } = {}): Promise<MemoryEntry[]> {
    const rows = asList(await this._request("GET", await this.route("/entries"), { user: this.layer(options.user) })) as JsonObject[];
    return rows.map(toMemoryEntry);
  }

  /**
   * Search it the way an agent does (a user's entries and the account's): entries whose name, description
   * or content holds any of the query's words, best first, with content (10 unless `limit` says otherwise).
   */
  async search(query: string, options: { limit?: number; user?: UserOption } = {}): Promise<MemoryEntry[]> {
    const rows = asList(await this._request("GET", await this.route("/entries"), {
      query: { q: query, limit: options.limit }, user: this.layer(options.user),
    })) as JsonObject[];
    return rows.map(toMemoryEntry);
  }

  /** One entry in full; a name with no entry throws `NotFound`. */
  async read(name: string, options: { user?: UserOption } = {}): Promise<MemoryEntry> {
    return toMemoryEntry(asObject(await this._request("GET", await this.route(`/entries/${encodeURIComponent(name)}`), {
      user: this.layer(options.user),
    })));
  }

  /**
   * Write an entry, creating it if the name is new. `description` is the line every agent attaching the
   * memory sees each turn (required for a new entry, kept when omitted). With `version` the save only lands
   * if the entry is still at that version, else `Conflict`.
   */
  async save(name: string, content: string, options: { description?: string; version?: number; user?: UserOption } = {}): Promise<MemoryEntry> {
    const json = compact({ content, description: options.description, version: options.version });
    return toMemoryEntry(asObject(await this._request("PUT", await this.route(`/entries/${encodeURIComponent(name)}`), {
      json, user: this.layer(options.user),
    })));
  }

  /**
   * An entry's versions, newest first: the one it holds now, then those kept from earlier saves (its
   * last 50 in all), without their content. A name with no entry throws `NotFound`.
   */
  async versions(name: string, options: { user?: UserOption } = {}): Promise<MemoryEntryVersion[]> {
    const rows = asList(await this._request("GET", await this.route(`/entries/${encodeURIComponent(name)}/versions`), {
      user: this.layer(options.user),
    })) as JsonObject[];
    return rows.map(toMemoryEntryVersion);
  }

  /** One version of an entry, with its content; one it no longer keeps throws `NotFound`. */
  async getVersion(name: string, version: number, options: { user?: UserOption } = {}): Promise<MemoryEntryVersion> {
    return toMemoryEntryVersion(asObject(await this._request("GET",
      await this.route(`/entries/${encodeURIComponent(name)}/versions/${version}`), { user: this.layer(options.user) })));
  }

  /**
   * Put an entry back as it was at `version`: a new version holding that one's content and
   * description, so the one it replaces is kept too.
   */
  async restore(name: string, version: number, options: { user?: UserOption } = {}): Promise<MemoryEntry> {
    return toMemoryEntry(asObject(await this._request("POST",
      await this.route(`/entries/${encodeURIComponent(name)}/versions/${version}/restore`), { user: this.layer(options.user) })));
  }

  /** Forget an entry; with `version`, only if it is still at that version (else `Conflict`). */
  async forget(name: string, options: { version?: number; user?: UserOption } = {}): Promise<void> {
    await this._request("DELETE", await this.route(`/entries/${encodeURIComponent(name)}`), {
      query: { version: options.version }, user: this.layer(options.user),
    });
  }
}

async function memoryIdOf(memory: Memory | AgentMemory | string, options: CallOptions): Promise<string> {
  if (memory instanceof AgentMemory) return await memory._memoryId();
  if (typeof memory === "string") return isUuid(memory) ? memory : String(await refId(Memory.fromName(memory, options)));
  return String(await refId(memory));
}

/**
 * @internal `memories` as the API takes and shows them: `[{id, writes}]`, in order. A name is looked up
 * for `user` (its own memory first, then the account's).
 */
export async function memoryLinks(memories: MemoryRef[] | undefined, options: CallOptions): Promise<JsonObject[] | undefined> {
  if (memories === undefined) return undefined;
  if (!Array.isArray(memories)) throw new TypeError("memories is a list: { memories: [Memory.fromName(\"company\")] }");
  const out: JsonObject[] = [];
  for (const ref of memories) {
    if (ref instanceof MemoryLink) out.push({ id: await memoryIdOf(ref.memory, options), writes: true });
    else if (typeof ref === "string" || ref instanceof Memory || ref instanceof AgentMemory) {
      out.push({ id: await memoryIdOf(ref, options), writes: false });
    } else throw new TypeError("memories takes a Memory, memory.writable(), agent.memory or a memory's id or name");
  }
  return out;
}
