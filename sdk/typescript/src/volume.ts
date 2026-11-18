/** Volumes: a persistent filesystem you mount into sandboxes and agents. */

import { CONSOLE_BASE_URL, DEFAULT_BASE_URL } from "./client.ts";
import { TrashItem, trashed } from "./trash.ts";
import { Conflict, NotFound } from "./errors.ts";
import { toExportBundle } from "./export.ts";
import type { ExportBundle } from "./export.ts";
import {
  ApiObject, asList, asObject, compact, createNamed, fetchPage, isUuid, listAll, listPage, num, paginate, parseTime, refId, str,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import type { PlacementOptions, RegionName } from "./region.ts";
import { Operation, registerResult } from "./operation.ts";
import { resolveScope } from "./scope.ts";

/**
 * A file or folder in a volume: its `path` from the volume's root, its `type`, a file's `size`
 * in bytes (null for a folder) and when it last changed.
 */
export interface VolumeEntry {
  path: string;
  type: "file" | "directory";
  size: number | null;
  updatedAt: Date | null;
  raw: JsonObject;
}

/** A running sandbox, an agent or a machine that mounts a volume, and where. */
export interface VolumeMount {
  kind: "sandbox" | "agent" | "machine";
  id: string;
  /** An agent's or a machine's name (null for a sandbox). */
  name: string | null;
  /** Where it's mounted: `/data`. */
  path: string;
}

export interface VolumeListdirOptions {
  /** Everything below the folder, not just what's in it. */
  recursive?: boolean;
}

/** Bytes, text (sent as UTF-8), an `ArrayBuffer` or a `Blob`. */
export type VolumeData = string | Uint8Array | ArrayBuffer | Blob;

/** A volume to mount: a `Volume`, its id, or its name (the user's own, else the account's). */
export type VolumeRef = string | Volume;

/** @internal */
export function toVolumeEntry(value: unknown): VolumeEntry {
  const raw = asObject(value);
  return {
    path: str(raw.path) ?? "",
    type: raw.type === "directory" ? "directory" : "file",
    size: num(raw.size),
    updatedAt: parseTime(raw.updated_at),
    raw,
  };
}

registerResult("volume.export", toExportBundle);

/**
 * @internal `volumes` as the API takes them: `{mount path: volume id}`, keys sorted. A name is
 * looked up for `user` (its own volume first, then the account's).
 */
export async function volumeMountIds(
  volumes: Record<string, VolumeRef> | undefined,
  options: CallOptions,
): Promise<Record<string, string> | undefined> {
  if (volumes === undefined) return undefined;
  if (typeof volumes !== "object" || volumes === null || Array.isArray(volumes)) {
    throw new TypeError('volumes maps a mount path to a volume: { "/data": Volume.fromName("datasets") }');
  }
  const out: Record<string, string> = {};
  for (const path of Object.keys(volumes).sort()) {
    const ref = volumes[path];
    if (ref instanceof Volume) out[path] = String(await refId(ref));
    else if (typeof ref === "string") out[path] = isUuid(ref) ? ref : String(await refId(Volume.fromName(ref, options)));
    else throw new TypeError(`Mount a Volume, a volume id or its name at "${path}"`);
  }
  return out;
}

/**
 * A persistent filesystem: files by path, in folders, that outlive the sandbox or agent turn
 * that wrote them. Mount it with `Sandbox.create({ volumes: { "/data": vol } })` or an agent's
 * `volumes`, or read and write it from your own code. What a sandbox or an agent's turn writes is
 * saved every few seconds while it runs, and all of it when it ends; two writers to one file at once:
 * the last one to finish wins.
 */
export class Volume extends ApiObject {
  private _createWith: JsonObject | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create an empty volume (1-64 letters, digits and `. _ -`), unique by name per user (a taken name
   * throws `Conflict` with `existingId`, or with `allowExisting: true` returns the volume already there,
   * files and all). `region` is in invite-only beta: the sandbox provider's volumes take no location, so
   * passing one throws `NotAvailable`.
   */
  static async create(name: string, options: CallOptions & PlacementOptions & AllowExisting = {}): Promise<Volume> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/volumes", compact({ name, region: options.region }), {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new Volume({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the volume called `name`. Acting for a user, that user's own volume is
   * found first, then the account's. With `createIfMissing` the current (or given) user's is
   * created on first use.
   */
  static fromName(name: string, options: CallOptions & PlacementOptions & { createIfMissing?: boolean } = {}): Volume {
    const volume = new Volume({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing) volume._createWith = compact({ name, region: options.region });
    return volume;
  }

  static fromId(volumeId: string, options: CallOptions = {}): Volume {
    return new Volume({ hints: { id: volumeId }, client: options.client, user: options.user });
  }

  static async get(volumeId: string, options: CallOptions = {}): Promise<Volume> {
    return await Volume.fromId(volumeId, options).hydrate();
  }

  /** The current user's volumes and the account's (or those `userFilter` covers). */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<Volume[]> {
    return await listAll({ ...options, path: "/v1/volumes" }, (raw, user) => new Volume({ raw, client: options.client, user }));
  }

  /** One page of volumes; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Volume>> {
    return await listPage({ ...options, path: "/v1/volumes" }, (raw, user) => new Volume({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  get sizeBytes(): number | null {
    return this._field("size_bytes");
  }
  get fileCount(): number | null {
    return this._field("file_count");
  }
  /** The running sandboxes, the agents and the machines that mount it, and at which path. */
  get mountedBy(): VolumeMount[] {
    const rows = this._field<unknown>("mounted_by");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((m) => ({
      kind: m.kind === "sandbox" || m.kind === "machine" ? m.kind : "agent", id: str(m.id) ?? "", name: str(m.name),
      path: str(m.path) ?? "",
    }));
  }
  /** Always null for now: volumes aren't placed by region yet (`region` is in invite-only beta). */
  get region(): RegionName | null {
    return this._field("region");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** This volume in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    if (this._api.baseUrl !== DEFAULT_BASE_URL) return null;
    return `${CONSOLE_BASE_URL}/resources/volumes?volume=${encodeURIComponent(String(this._known("id")))}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/volumes/${id}`);
    const name = String(this._hints.name);
    const rows = (asList(await this._request("GET", "/v1/volumes", { query: { name } })) as JsonObject[]).filter((r) => r.name === name);
    // This scope's own volume first; a definition is only ever for its own.
    const own = rows.filter((r) => Boolean(r.user_id) === Boolean(this._scope));
    const row = this._createWith ? own[0] : (own[0] ?? rows[0]);
    if (row) return row;
    if (!this._createWith) {
      throw new NotFound(`No volume is named "${name}".`, {
        nextStep: "Create it with Volume.create(...) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/volumes", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this._request<JsonObject>("GET", `/v1/volumes/${err.existingId}`);
    }
  }

  /** This volume's route; a reference by name is looked up (or created) first. */
  private async route(suffix = ""): Promise<string> {
    if (!this._known("id")) await this._ensure();
    return `/v1/volumes/${String(this._known("id"))}${suffix}`;
  }

  private listQuery(path: string, options: VolumeListdirOptions) {
    return { path, view: "list", recursive: options.recursive ? "true" : undefined };
  }

  /** Write `data` to `path`, replacing the file and making any folders it needs (up to 100 MB). */
  async write(path: string, data: VolumeData): Promise<VolumeEntry> {
    return toVolumeEntry(await this._request("PUT", await this.route("/files"), { query: { path }, body: data }));
  }

  /** The file's bytes (up to 100 MB), as the volume last saved it; a missing file throws `NotFound`. */
  async read(path: string): Promise<Uint8Array> {
    return await this._request<Uint8Array>("GET", await this.route("/files"), { query: { path }, responseType: "bytes" });
  }

  /** What's in the folder at `path` (everything below it with `recursive`), in path order, fetched page by page. */
  async listdir(path = "/", options: VolumeListdirOptions & { limit?: number } = {}): Promise<VolumeEntry[]> {
    const rows = await paginate(this._api, await this.route("/files"), {
      query: this.listQuery(path, options),
      user: this._callScope() ?? null,
      limit: options.limit,
    });
    return rows.map(toVolumeEntry);
  }

  /** One page of `listdir`; pass `nextCursor` back as `cursor`. */
  async listdirPage(path = "/", options: VolumeListdirOptions & PageOptions = {}): Promise<Page<VolumeEntry>> {
    const page = await fetchPage(this._api, await this.route("/files"), {
      query: this.listQuery(path, options),
      user: this._callScope() ?? null,
      cursor: options.cursor,
      limit: options.limit,
    });
    return { data: page.data.map(toVolumeEntry), nextCursor: page.nextCursor };
  }

  /** Delete the file or folder at `path`; a folder that isn't empty needs `recursive`. A missing path is fine. */
  async remove(path: string, options: { recursive?: boolean } = {}): Promise<void> {
    await this._request("DELETE", await this.route("/files"), { query: { path, recursive: options.recursive ? "true" : undefined } });
  }

  /** Copy the file or folder at `src` to `dst` in this volume, replacing what `dst` held. */
  async copy(src: string, dst: string): Promise<VolumeEntry> {
    return toVolumeEntry(await this._request("POST", await this.route("/copy"), { json: compact({ src, dst }) }));
  }

  /**
   * Export every file, so the volume can move anywhere: a zip holding them in their folders (under
   * `volumes/<name>/files/`), with `index.jsonl` listing each path, its size and when it last
   * changed. `wait()` resolves to an `ExportBundle`: the zip at `url`, valid 7 days.
   */
  async export(): Promise<Operation<ExportBundle>> {
    const payload = await this._request("POST", await this.route("/export"));
    return Operation._fromPayload<ExportBundle>(payload, { client: this._client, user: this._callScope(), kind: "volume.export", reader: toExportBundle });
  }

  /**
   * Delete the volume and its files: it goes to the trash, restorable for 30 days. While a running
   * sandbox or an agent mounts it, this throws `Conflict`, and a user can't delete the account's
   * (`PermissionDenied`). Returns its `TrashItem`.
   */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this.route()), this);
  }
}
