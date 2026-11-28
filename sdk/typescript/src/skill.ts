/**
 * Skills: Agent Skills folders any agent of their scope can attach.
 *
 *     const check = await Skill.create({ "SKILL.md": "---\nname: invoice-check\ndescription: Check invoices.\n---\n...",
 *                                      "scripts/match.py": "..." });
 *     const support = Agent.fromName("support", { createIfMissing: true, instructions: "...", skills: [check] });
 *
 * A skill is a folder: a `SKILL.md` whose frontmatter names it (`name`) and says what it does and when to use it
 * (`description`; `always: true` puts it whole in every turn), plus any other files. Every save is a new version;
 * an agent follows the latest unless it holds one (`skill.pinned(3)`). A coding harness finds its skills where it
 * reads skills; an `sdk` agent sees each one's name and description every turn and reads one with `skill__read`.
 */

import { Conflict, NotFound } from "./errors.ts";
import { ApiObject, asList, asObject, compact, isUuid, listAll, listPage, num, parseTime, refId, str } from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { resolveScope } from "./scope.ts";
import { TrashItem, trashed } from "./trash.ts";

/** A folder's files: path → text, or bytes for a file that isn't text. */
export type SkillFiles = Record<string, string | Uint8Array>;

/** An agent that attaches a skill, and the version it holds (null: the latest). */
export interface SkillAttachment {
  id: string;
  name: string;
  pin: number | null;
}

/** One file of a version, as its manifest lists it. */
export interface SkillFileInfo {
  path: string;
  size: number;
  sha256: string;
}

/** Who saved a version: a person in the app (`console`), a key (`api`), or an agent's turn. */
export interface SkillAuthor {
  type: "console" | "api" | "agent" | null;
  agentId: string | null;
  agentName: string | null;
}

/** One version of a skill: its frontmatter as that version has it, and its files. */
export interface SkillVersion {
  version: number;
  digest: string;
  name: string;
  description: string;
  always: boolean;
  files: SkillFileInfo[];
  size: number;
  createdBy: SkillAuthor;
  createdAt: Date | null;
  raw: JsonObject;
}

/** One file's content: its text, or base64 when it isn't UTF-8 (`encoding`). */
export interface SkillFile {
  path: string;
  version: number;
  size: number;
  sha256: string;
  content: string;
  encoding: "utf-8" | "base64";
}

/** A skill held at one version on an agent (`skill.pinned(n)`). */
export class SkillLink {
  readonly skill: Skill | string;
  readonly pin: number;

  /** @internal */
  constructor(skill: Skill | string, pin: number) {
    this.skill = skill;
    this.pin = pin;
  }
}

/** A skill to attach: a `Skill`, `skill.pinned(n)`, or a skill's id or name. */
export type SkillRef = string | Skill | SkillLink;

function toFile(path: string, content: string | Uint8Array): JsonObject {
  if (typeof content === "string") return { path, content, encoding: "utf-8" };
  let binary = "";
  for (const byte of content) binary += String.fromCharCode(byte);
  return { path, content: btoa(binary), encoding: "base64" };
}

function filesWire(files: SkillFiles): JsonObject[] {
  return Object.entries(files).map(([path, content]) => toFile(path, content));
}

function toVersion(raw: JsonObject): SkillVersion {
  const by = asObject(raw.created_by ?? {});
  return {
    version: num(raw.version) ?? 0,
    digest: str(raw.digest) ?? "",
    name: str(raw.name) ?? "",
    description: str(raw.description) ?? "",
    always: raw.always === true,
    files: (Array.isArray(raw.files) ? raw.files : []).map(asObject).map((f) => ({
      path: str(f.path) ?? "", size: num(f.size) ?? 0, sha256: str(f.sha256) ?? "",
    })),
    size: num(raw.size) ?? 0,
    createdBy: { type: str(by.type) as SkillAuthor["type"], agentId: str(by.agent_id), agentName: str(by.agent_name) },
    createdAt: parseTime(raw.created_at),
    raw,
  };
}

/**
 * An Agent Skills folder of the account's (every user's agents may use it) or one user's, versioned. Delete it
 * and it goes to the trash, off every agent that attaches it; restoring puts it back on them.
 */
export class Skill extends ApiObject {
  private _createWith: JsonObject | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * A skill from its folder, named by its `SKILL.md`; unique by name per user, or for the account outside `asUser`.
   * A taken name throws `Conflict` with `existingId`, or with `allowExisting: true` returns the skill already there
   * as it is (`saveVersion` to change it). Up to 200 files and 20 MB, `SKILL.md` up to 64 KB.
   */
  static async create(files: SkillFiles, options: CallOptions & AllowExisting = {}): Promise<Skill> {
    const scope = resolveScope(options.user);
    const skill = new Skill({ hints: {}, client: options.client, user: scope });
    try {
      skill._raw = await skill._request<JsonObject>("POST", "/v1/skills", { json: { files: filesWire(files) } });
    } catch (err) {
      if (!options.allowExisting || !(err instanceof Conflict) || !err.existingId) throw err;
      skill._raw = await skill._request<JsonObject>("GET", `/v1/skills/${err.existingId}`);
    }
    return skill;
  }

  /**
   * A lazy reference to the skill called `name`. Acting for a user, that user's own skill is found first, then the
   * account's. With `createIfMissing` it's created from `files` on first use.
   */
  static fromName(name: string, options: CallOptions & { createIfMissing?: boolean; files?: SkillFiles } = {}): Skill {
    const skill = new Skill({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing) {
      if (!options.files) throw new TypeError("createIfMissing needs the skill's files: { files: { \"SKILL.md\": ... } }");
      skill._createWith = { files: filesWire(options.files) };
    }
    return skill;
  }

  static fromId(skillId: string, options: CallOptions = {}): Skill {
    return new Skill({ hints: { id: skillId }, client: options.client, user: options.user });
  }

  static async get(skillId: string, options: CallOptions = {}): Promise<Skill> {
    return await Skill.fromId(skillId, options).hydrate();
  }

  /**
   * The current user's skills and the account's (or those `userFilter` covers), newest first. With `agent`, the
   * skills that agent attaches, in its order.
   */
  static async list(options: ReadOptions & { limit?: number; agent?: string | ApiObject } = {}): Promise<Skill[]> {
    return await listAll({ ...options, path: "/v1/skills", query: { agent_id: await refId(options.agent) } },
      (raw, user) => new Skill({ raw, client: options.client, user }));
  }

  /** One page of skills; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Skill>> {
    return await listPage({ ...options, path: "/v1/skills" }, (raw, user) => new Skill({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }

  /** Its name, from its latest `SKILL.md`. */
  get name(): string {
    return this._field("name");
  }

  get description(): string {
    return this._field("description");
  }

  /** Whether it's put whole in every turn of the agents that attach it. */
  get always(): boolean {
    return this._field("always") === true;
  }

  /** Its latest version's number. */
  get version(): number {
    return num(this._field("version")) ?? 0;
  }

  /** Its latest version's content, as a digest: what restarts a coding agent's warm sandbox when it changes. */
  get digest(): string {
    return this._field("digest");
  }

  get fileCount(): number {
    return num(this._field("file_count")) ?? 0;
  }

  /** Its latest version's size in bytes. */
  get size(): number {
    return num(this._field("size")) ?? 0;
  }

  /** The agents that attach it, and the version each holds (null: the latest). */
  get attachedTo(): SkillAttachment[] {
    const rows = this._field<unknown>("attached_to");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((a) => ({
      id: str(a.id) ?? "", name: str(a.name) ?? "", pin: num(a.pin),
    }));
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
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/skills/${id}`);
    const name = String(this._hints.name);
    const rows = (asList(await this._request("GET", "/v1/skills", { query: { name } })) as JsonObject[]).filter((r) => r.name === name);
    const own = rows.filter((r) => Boolean(r.user_id) === Boolean(this._scope));
    const row = this._createWith ? own[0] : (own[0] ?? rows[0]);
    if (row) return row;
    if (!this._createWith) {
      throw new NotFound(`No skill is named "${name}".`, {
        nextStep: "Create it with Skill.create(files) or pass { createIfMissing: true, files }.",
        details: { name, kind: "skill" },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/skills", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this._request<JsonObject>("GET", `/v1/skills/${err.existingId}`);
    }
  }

  private async route(suffix = ""): Promise<string> {
    if (!this._known("id")) await this._ensure();
    return `/v1/skills/${String(this._known("id"))}${suffix}`;
  }

  /** This skill held at one version, for an agent's `skills`. */
  pinned(version: number): SkillLink {
    return new SkillLink(this, version);
  }

  /**
   * Save a new version: `files` written over the latest (the whole folder with `replace`), `removed` taken out. With
   * `baseVersion` it saves only while the latest is still that version (else `Conflict`). Agents following the
   * latest get it in their next conversation; a running coding sandbox restarts with it.
   */
  async saveVersion(files: SkillFiles, options: { removed?: string[]; replace?: boolean; baseVersion?: number } = {}): Promise<Skill> {
    this._raw = asObject(await this._request("POST", await this.route("/versions"), {
      json: compact({ files: filesWire(files), removed: options.removed, replace: options.replace, base_version: options.baseVersion }),
    }));
    return this;
  }

  /** Rename it or change its description: a new version with its `SKILL.md` frontmatter rewritten. */
  async update(changes: { name?: string; description?: string }): Promise<Skill> {
    this._raw = asObject(await this._request("PATCH", await this.route(), { json: compact(changes) }));
    return this;
  }

  /** Every version, newest first. */
  async versions(): Promise<SkillVersion[]> {
    return (asList(await this._request("GET", await this.route("/versions"))) as JsonObject[]).map(toVersion);
  }

  /** One version, with its files. */
  async getVersion(version: number): Promise<SkillVersion> {
    return toVersion(asObject(await this._request("GET", await this.route(`/versions/${version}`))));
  }

  /** A new version holding what `version` held. */
  async restore(version: number): Promise<Skill> {
    this._raw = asObject(await this._request("POST", await this.route(`/versions/${version}/restore`)));
    return this;
  }

  /** The files of a version (the latest unless `version`), by path. */
  async files(options: { version?: number } = {}): Promise<SkillFileInfo[]> {
    const rows = asList(await this._request("GET", await this.route("/files"), { query: { version: options.version } })) as JsonObject[];
    return rows.map((f) => ({ path: str(f.path) ?? "", size: num(f.size) ?? 0, sha256: str(f.sha256) ?? "" }));
  }

  /** One file of a version (the latest unless `version`): its text, or base64 when it isn't UTF-8. */
  async read(path: string, options: { version?: number } = {}): Promise<SkillFile> {
    const raw = asObject(await this._request("GET", await this.route("/files"), { query: { path, version: options.version } }));
    return {
      path: str(raw.path) ?? path, version: num(raw.version) ?? 0, size: num(raw.size) ?? 0, sha256: str(raw.sha256) ?? "",
      content: str(raw.content) ?? "", encoding: (str(raw.encoding) ?? "utf-8") as SkillFile["encoding"],
    };
  }

  /** Delete it: to the trash, restorable for 30 days, and off every agent that attaches it until it's restored. */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this.route()), this);
  }
}

/** @internal `skills` as the API takes and shows them: `[{id, pin}]`, in order. */
export async function skillLinks(skills: SkillRef[] | undefined, options: CallOptions): Promise<JsonObject[] | undefined> {
  if (skills === undefined) return undefined;
  if (!Array.isArray(skills)) throw new TypeError("skills is a list: { skills: [Skill.fromName(\"invoice-check\")] }");
  const idOf = async (skill: Skill | string): Promise<string> =>
    typeof skill === "string" ? (isUuid(skill) ? skill : String(await refId(Skill.fromName(skill, options)))) : String(await refId(skill));
  const out: JsonObject[] = [];
  for (const ref of skills) {
    if (ref instanceof SkillLink) out.push({ id: await idOf(ref.skill), pin: ref.pin });
    else if (typeof ref === "string" || ref instanceof Skill) out.push({ id: await idOf(ref), pin: null });
    else throw new TypeError("skills takes a Skill, skill.pinned(n) or a skill's id or name");
  }
  return out;
}
