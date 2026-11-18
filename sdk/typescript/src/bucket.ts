/** Buckets: files by key, private by default, with signed links. */

import { CONSOLE_BASE_URL, DEFAULT_BASE_URL } from "./client.ts";
import { TrashItem, trashed } from "./trash.ts";
import type { UsedBy } from "./database.ts";
import { Conflict, NotAvailable, NotFound } from "./errors.ts";
import { toExportBundle } from "./export.ts";
import type { ExportBundle } from "./export.ts";
import {
  ApiObject, asList, asObject, boundArguments, compact, createNamed, fetchPage, listAll, listPage, num, paginate, parseTime, refId, str,
  toolEntries,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import type { PlacementOptions, RegionName } from "./region.ts";
import { Operation, registerResult } from "./operation.ts";
import { resolveScope } from "./scope.ts";

/**
 * A file in a bucket. In a listing with a `delimiter`, an entry with `isFolder` stands for
 * every key under that prefix, and only its `key` is set.
 */
export interface BucketObject {
  key: string;
  size: number | null;
  contentType: string | null;
  /** Changes whenever the content does. */
  etag: string | null;
  metadata: Record<string, string>;
  updatedAt: Date | null;
  isFolder: boolean;
  raw: JsonObject;
}

/**
 * Short-lived keys for the bucket's S3-compatible endpoint (rclone, the AWS CLI, an S3
 * library). `bucket` is its name on that endpoint, not its NoClick name. Keys are a person's: an app's deployed code
 * gets none, and uploads a file of any size in parts (`bucket.startUpload`) instead.
 */
export interface S3Credentials {
  endpoint: string;
  bucket: string;
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken: string | null;
  region: string;
  readOnly: boolean;
  expiresAt: Date | null;
  raw: JsonObject;
}

/**
 * A file being uploaded in parts (`bucket.startUpload`): its `key` and `uploadId`, which the other upload calls take,
 * its `contentType`, and the parts it takes: each `minPartBytes` (5 MiB) to `maxPartBytes` (5 GiB), every part but the
 * last the same size, up to `maxParts` (10,000).
 */
export interface BucketUpload {
  key: string;
  uploadId: string;
  contentType: string | null;
  minPartBytes: number;
  maxPartBytes: number;
  maxParts: number;
  raw: JsonObject;
}

export interface BucketUploadOptions {
  /** Guessed from the key's extension when omitted. */
  contentType?: string;
  /** Up to 2 KB of your own string pairs, kept with the file. */
  metadata?: Record<string, string>;
}

export interface BucketPartUrlsOptions {
  /** Seconds the links work: 60 to 604,800 (a week); 3600 by default. */
  expiresIn?: number;
}

/** Part links signed in one request; `uploadPartUrls` sends as many requests as it needs. */
const PART_LINKS_PER_CALL = 1000;

export interface BucketCreateOptions extends CallOptions, PlacementOptions {
  /** Serve every file at a plain URL (`url(key)`); private by default. */
  public?: boolean;
}

export interface BucketPutOptions {
  /** Guessed from the key's extension when omitted. */
  contentType?: string;
  /** Up to 2 KB of your own string pairs, returned with the file. */
  metadata?: Record<string, string>;
}

/**
 * What a file held before a write through NoClick replaced it (`op` `changed`) or removed it
 * (`deleted`), kept 30 days. An upload through a signed link or S3 credentials keeps none.
 */
export interface ObjectVersion {
  id: string;
  key: string;
  op: "changed" | "deleted";
  size: number | null;
  replacedAt: Date | null;
  raw: JsonObject;
}

export interface BucketObjectsOptions {
  prefix?: string;
  /** `"/"` rolls keys below the next `/` into one folder entry each. */
  delimiter?: string;
}

export interface BucketSignedUrlOptions {
  /** `GET` reads the file, `PUT` uploads it (up to 5 GB). */
  method?: "GET" | "PUT";
  /** Seconds the link works: 60 to 604,800 (a week); 3600 by default. */
  expiresIn?: number;
  /** A `PUT` link's upload must send this type. */
  contentType?: string;
}

/** Bytes, text (sent as UTF-8), an `ArrayBuffer` or a `Blob`. */
export type BucketData = string | Uint8Array | ArrayBuffer | Blob;

function toBucketObject(value: unknown): BucketObject {
  const raw = asObject(value);
  const metadata = Object.fromEntries(Object.entries(asObject(raw.metadata)).map(([k, v]) => [k, String(v)]));
  return {
    key: str(raw.key) ?? "",
    size: num(raw.size),
    contentType: str(raw.content_type),
    etag: str(raw.etag),
    metadata,
    updatedAt: parseTime(raw.updated_at),
    isFolder: raw.folder === true,
    raw,
  };
}

function toBucketUpload(value: unknown): BucketUpload {
  const raw = asObject(value);
  return {
    key: str(raw.key) ?? "",
    uploadId: str(raw.upload_id) ?? "",
    contentType: str(raw.content_type),
    minPartBytes: num(raw.min_part_bytes) ?? 0,
    maxPartBytes: num(raw.max_part_bytes) ?? 0,
    maxParts: num(raw.max_parts) ?? 0,
    raw,
  };
}

function toS3Credentials(value: unknown): S3Credentials {
  const raw = asObject(value);
  return {
    endpoint: str(raw.endpoint) ?? "",
    bucket: str(raw.bucket) ?? "",
    accessKeyId: str(raw.access_key_id) ?? "",
    secretAccessKey: str(raw.secret_access_key) ?? "",
    sessionToken: str(raw.session_token),
    region: str(raw.region) ?? "auto",
    readOnly: raw.read_only === true,
    expiresAt: parseTime(raw.expires_at),
    raw,
  };
}

registerResult("bucket.export", toExportBundle);

/** What an agent may do with a bucket, each a tool of its own (in a toolkit or a hosted MCP server, invite-only beta). */
export const BUCKET_TOOLS = ["objects", "head", "put", "signed_url", "remove"] as const;
export type BucketTool = (typeof BUCKET_TOOLS)[number];

/** Where a bucket tells about new files (`notify`): the `queue` (its name) and `prefix` (null for every file). */
export interface BucketNotification {
  queue: string;
  prefix: string | null;
}

/** Some of a bucket's operations as an agent's tools (`bucket.only(...)`), with the arguments `bind(...)` fixed. */
export class BucketOperations {
  readonly bucket: Bucket;
  readonly operations: BucketTool[];
  /** The arguments NoClick fills on every call, out of the model's reach. */
  readonly bindings: JsonObject;

  constructor(bucket: Bucket, operations: BucketTool[], bindings: JsonObject = {}) {
    this.bucket = bucket;
    this.operations = operations;
    this.bindings = bindings;
  }

  /**
   * Fix arguments of these operations, as `ConnectionOperations.bind` does. `prefix` is the one to
   * bind here: every key the tools take and return is then under it, so one bucket holds a folder
   * per user.
   *
   *     uploads.only("objects", "put", "signed_url").bind({ prefix: "users/{{user.id}}/" })
   */
  bind(args: JsonObject): BucketOperations {
    return new BucketOperations(this.bucket, [...this.operations], { ...this.bindings, ...boundArguments(args) });
  }

  /** @internal */
  async _toolRefs(): Promise<(string | JsonObject)[]> {
    return toolEntries(`bucket:${await refId(this.bucket)}`, this.operations, this.bindings);
  }
}

/**
 * A bucket of files by key. Private by default: files are reached through this client or a
 * `signedUrl`; a public bucket also serves each file at `url(key)`. Its region is a location hint
 * object storage places it by when it has room there, fixed when it's created.
 */
export class Bucket extends ApiObject {
  private _createWith: JsonObject | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create a bucket, unique by name per user (a taken name throws `Conflict` with `existingId`, or with
   * `allowExisting: true` returns the bucket already there, as it is).
   */
  static async create(name: string, options: BucketCreateOptions & AllowExisting = {}): Promise<Bucket> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/buckets", compact({ name, public: options.public ?? false, region: options.region }), {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new Bucket({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the bucket called `name` for the current (or given) user. With
   * `createIfMissing` it's created on first use; one that exists is used as it is.
   */
  static fromName(name: string, options: BucketCreateOptions & { createIfMissing?: boolean } = {}): Bucket {
    const bucket = new Bucket({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing) bucket._createWith = compact({ name, public: options.public ?? false, region: options.region });
    return bucket;
  }

  static fromId(bucketId: string, options: CallOptions = {}): Bucket {
    return new Bucket({ hints: { id: bucketId }, client: options.client, user: options.user });
  }

  static async get(bucketId: string, options: CallOptions = {}): Promise<Bucket> {
    return await Bucket.fromId(bucketId, options).hydrate();
  }

  /** The current user's buckets (or those `userFilter` covers). */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<Bucket[]> {
    return await listAll({ ...options, path: "/v1/buckets" }, (raw, user) => new Bucket({ raw, client: options.client, user }));
  }

  /** One page of buckets; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Bucket>> {
    return await listPage({ ...options, path: "/v1/buckets" }, (raw, user) => new Bucket({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** Whether every file is readable at `url(key)` without a link. */
  get public(): boolean {
    return this._field("public") === true;
  }
  get sizeBytes(): number | null {
    return this._field("size_bytes");
  }
  get objectCount(): number | null {
    return this._field("object_count");
  }
  /** Where a public bucket serves its files (null while it's private). */
  get publicBaseUrl(): string | null {
    return this._field("public_base_url");
  }
  /** Who uses it: apps that bind it and agents with it in their tools. */
  get usedBy(): UsedBy[] {
    const rows = this._field<unknown>("used_by");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((u) => ({
      kind: str(u.kind) ?? "project", id: str(u.id) ?? "", name: str(u.name) ?? "", binding: str(u.binding),
    }));
  }
  /** Where it tells about new files (`notify`). */
  get notifications(): BucketNotification[] {
    const rows = this._field<unknown>("notifications");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((n) => ({ queue: str(n.queue) ?? "", prefix: str(n.prefix) }));
  }
  /** The region it keeps its data in, fixed when it was created. */
  get region(): RegionName | null {
    return this._field("region");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  /**
   * A tool ref to some of its operations, for `tools`: `"objects"`, `"head"`, `"put"` (store a
   * file from a `url` or from `text`, so the model never handles bytes), `"signed_url"` (a link
   * that reads a file) and `"remove"`. The bucket itself in `tools` gives all five, as
   * `{name}__objects` and so on; policy names them `bucket.objects`, `bucket.put`, ... (`bucket.*`).
   */
  only(...operations: BucketTool[]): BucketOperations {
    const unknown = operations.filter((op) => !(BUCKET_TOOLS as readonly string[]).includes(op));
    if (!operations.length || unknown.length) {
      throw new TypeError(`only() takes some of ${BUCKET_TOOLS.join(", ")}, not ${unknown.join(", ") || "nothing"}`);
    }
    return new BucketOperations(this, operations);
  }

  /** @internal The bucket itself in `tools`. */
  async _toolRefs(): Promise<string[]> {
    return [`bucket:${await refId(this)}`];
  }

  /** This bucket in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    if (this._api.baseUrl !== DEFAULT_BASE_URL) return null;
    return `${CONSOLE_BASE_URL}/resources/storage?bucket=${encodeURIComponent(String(this._known("id")))}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/buckets/${id}`);
    const name = String(this._hints.name);
    const found = await this._inApp("bucket", name, this._createWith);
    if (found) return found;
    const row = (asList(await this._request("GET", "/v1/buckets", { query: { name } })) as JsonObject[]).find((r) => r.name === name);
    if (row) return row;
    if (!this._createWith) {
      throw new NotFound(`No bucket is named "${name}".`, {
        nextStep: "Create it with Bucket.create(...) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/buckets", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this._request<JsonObject>("GET", `/v1/buckets/${err.existingId}`);
    }
  }

  /** This bucket's route; a reference by name is looked up (or created) first. */
  private async route(suffix = ""): Promise<string> {
    if (!this._known("id")) await this._ensure();
    return `/v1/buckets/${String(this._known("id"))}${suffix}`;
  }

  /** Store `data` at `key`, replacing what was there (up to 100 MB; larger files go through a `PUT` signed link). */
  async put(key: string, data: BucketData, options: BucketPutOptions = {}): Promise<BucketObject> {
    const query = {
      key,
      content_type: options.contentType,
      metadata: options.metadata && Object.keys(options.metadata).length ? JSON.stringify(options.metadata) : undefined,
    };
    return toBucketObject(await this._request("PUT", await this.route("/objects"), { query, body: data }));
  }

  /** The file's bytes; a missing key throws `NotFound`. */
  async read(key: string): Promise<Uint8Array> {
    return await this._request<Uint8Array>("GET", await this.route("/objects"), { query: { key }, responseType: "bytes" });
  }

  /** A file's size, type, etag and metadata, without downloading it. */
  async head(key: string): Promise<BucketObject> {
    return toBucketObject(await this._request("GET", await this.route("/objects"), { query: { key, view: "metadata" } }));
  }

  /** The files under `prefix`, in key order (or the first `limit`), fetched page by page. */
  async objects(options: BucketObjectsOptions & { limit?: number } = {}): Promise<BucketObject[]> {
    const rows = await paginate(this._api, await this.route("/objects"), {
      query: { prefix: options.prefix, delimiter: options.delimiter },
      user: this._callScope() ?? null,
      limit: options.limit,
    });
    return rows.map(toBucketObject);
  }

  /** One page of `objects`; pass `nextCursor` back as `cursor`. */
  async objectsPage(options: BucketObjectsOptions & PageOptions = {}): Promise<Page<BucketObject>> {
    const page = await fetchPage(this._api, await this.route("/objects"), {
      query: { prefix: options.prefix, delimiter: options.delimiter },
      user: this._callScope() ?? null,
      cursor: options.cursor,
      limit: options.limit,
    });
    return { data: page.data.map(toBucketObject), nextCursor: page.nextCursor };
  }

  /** Delete the file at `key` (a key that isn't there is fine). */
  async remove(key: string): Promise<void> {
    await this._request("DELETE", await this.route("/objects"), { query: { key } });
  }

  /** What `key` held before each write through NoClick of the last 30 days, newest first. */
  async versions(key: string): Promise<ObjectVersion[]> {
    const rows = asList(await this._request("GET", await this.route("/objects/versions"), { query: { key } }));
    return rows.map(asObject).map((raw) => ({
      id: str(raw.id) ?? "", key: str(raw.key) ?? key, op: raw.op as ObjectVersion["op"], size: num(raw.size),
      replacedAt: parseTime(raw.replaced_at), raw,
    }));
  }

  /** Put `key` back as `version` held it; what it holds now is kept as a version in turn. */
  async restoreVersion(key: string, version: ObjectVersion | string): Promise<BucketObject> {
    const versionId = typeof version === "string" ? version : version.id;
    return toBucketObject(await this._request("POST", await this.route("/objects/versions/restore"), { json: { key, version_id: versionId } }));
  }

  /** A link that reads (`GET`) or uploads (`PUT`) the file without a NoClick key, until it expires. */
  async signedUrl(key: string, options: BucketSignedUrlOptions = {}): Promise<string> {
    const json = compact({ key, method: options.method ?? "GET", expires_in: options.expiresIn ?? 3600, content_type: options.contentType });
    return String(asObject(await this._request("POST", await this.route("/signed_urls"), { json })).url);
  }

  /**
   * Begin uploading the file at `key` in parts: for a file bigger than a `PUT` link carries (5 GB), or one a page
   * sends a piece at a time. Sign a link per part with `uploadPartUrls`, `PUT` each part's bytes to its link (a
   * browser can, straight from a page: each answers with an `ETag` header), then join them with `completeUpload`, or
   * drop them with `abortUpload`. Each part is 5 MiB to 5 GiB, every part but the last the same size, up to 10,000
   * parts. Nothing is at `key` until the upload completes, and one left unfinished is dropped after 7 days. An app's
   * own code uploads this way, since S3 credentials stay with a person.
   *
   *     const upload = await bucket.startUpload("b737/fcom.pdf", { contentType: "application/pdf" });
   */
  async startUpload(key: string, options: BucketUploadOptions = {}): Promise<BucketUpload> {
    const metadata = options.metadata && Object.keys(options.metadata).length ? options.metadata : undefined;
    const json = compact({ key, content_type: options.contentType, metadata });
    return toBucketUpload(await this._request("POST", await this.route("/uploads"), { json }));
  }

  /**
   * A `PUT` link for each of `partNumbers` (1 to 10,000) of the upload. `PUT` a part's bytes to its link: the
   * answer's `ETag` header names the part for `completeUpload`. A part uploaded again replaces it, so a failed part
   * is simply sent again.
   *
   *     const links = await bucket.uploadPartUrls("b737/fcom.pdf", uploadId, [1, 2, 3], { expiresIn: 3600 });
   */
  async uploadPartUrls(
    key: string, uploadId: string, partNumbers: Iterable<number>, options: BucketPartUrlsOptions = {},
  ): Promise<Record<number, string>> {
    const numbers = [...partNumbers];
    const links: Record<number, string> = {};
    for (let start = 0; start < numbers.length; start += PART_LINKS_PER_CALL) {
      const json = {
        key, upload_id: uploadId, part_numbers: numbers.slice(start, start + PART_LINKS_PER_CALL),
        expires_in: options.expiresIn ?? 3600,
      };
      for (const row of asList(await this._request("POST", await this.route("/uploads/part_urls"), { json })).map(asObject)) {
        links[Number(row.part_number)] = String(row.url);
      }
    }
    return links;
  }

  /**
   * Join the uploaded parts into the file at `key`, in part number order: `parts` maps each part's number to the
   * `ETag` its upload answered with. What `key` held is kept as an earlier version, as `put` keeps it. Parts that
   * can't be joined throw `InvalidRequest` saying why (a wrong ETag, a part but the last under 5 MiB, or parts but the
   * last of different sizes); an upload already completed, aborted or over 7 days old throws `NotFound`.
   *
   *     const stored = await bucket.completeUpload("b737/fcom.pdf", uploadId, { 1: etag1, 2: etag2 });
   */
  async completeUpload(key: string, uploadId: string, parts: Record<number, string>): Promise<BucketObject> {
    const json = { key, upload_id: uploadId, parts: Object.entries(parts).map(([n, etag]) => ({ part_number: Number(n), etag })) };
    return toBucketObject(await this._request("POST", await this.route("/uploads/complete"), { json }));
  }

  /** Drop the upload and every part sent. One already completed or aborted is fine. */
  async abortUpload(key: string, uploadId: string): Promise<void> {
    await this._request("POST", await this.route("/uploads/abort"), { json: { key, upload_id: uploadId } });
  }

  /** The plain URL a public bucket serves `key` at; a private bucket throws `NotAvailable`. */
  async url(key: string): Promise<string> {
    const raw = await this._ensure();
    const base = str(raw.public_base_url);
    if (raw.public !== true || !base) {
      throw new NotAvailable(`Bucket "${String(raw.name)}" is private, so its files have no public URL.`, {
        nextStep: "Use bucket.signedUrl(key), or make it public with bucket.update({ public: true }).",
        details: { bucket_id: raw.id ?? null },
      });
    }
    return `${base.replace(/\/+$/, "")}/${key.split("/").map(encodeURIComponent).join("/")}`;
  }

  /** Change the bucket's settings; making it private stops every public URL at once. */
  async update(options: { public?: boolean }): Promise<this> {
    this._raw = asObject(await this._request("PATCH", await this.route(), { json: compact({ public: options.public }) }));
    return this;
  }

  /**
   * Put a message on `queue` (a `Queue` or its name, in the bucket's own user) for every file stored
   * under `prefix` (the whole bucket when omitted), however it arrived: `put`, a `PUT` signed link or
   * S3 credentials. The message is `{ event: "put", bucket, key, size, content_type, etag, at }`.
   * Asking again for the same queue and prefix changes nothing; `enabled: false` stops it.
   *
   *     await recordings.notify("new-recordings", { prefix: "calls/" });
   */
  async notify(queue: string | { _ensure(): Promise<JsonObject> }, options: { prefix?: string; enabled?: boolean } = {}): Promise<this> {
    const name = typeof queue === "string" ? queue : String((await queue._ensure()).name);
    const json = compact({ queue: name, prefix: options.prefix });
    const path = options.enabled === false ? "/notifications/remove" : "/notifications";
    this._raw = asObject(await this._request("POST", await this.route(path), { json }));
    return this;
  }

  /**
   * Keys for the S3-compatible endpoint, valid `ttlS` seconds (900 to 43,200; 3600 by default). They're for you and
   * your own code: an app's deployed code is refused them (`PermissionDenied`) and uploads big files in parts
   * (`startUpload`) instead.
   */
  async s3Credentials(options: { readOnly?: boolean; ttlS?: number } = {}): Promise<S3Credentials> {
    const json = compact({ ttl_s: options.ttlS ?? 3600, read_only: options.readOnly ? true : undefined });
    return toS3Credentials(await this._request("POST", await this.route("/s3_credentials"), { json }));
  }

  /**
   * Export every file, to take anywhere: a zip holding each one at its key (under
   * `buckets/<name>/files/`), with `index.jsonl` listing each key's content type and metadata. A
   * key that can't be a path in a zip (an empty, `.` or `..` part) is kept under `renamed/`, and the
   * index says which. `wait()` resolves to an `ExportBundle`: the zip at `url`, valid 7 days.
   */
  async export(): Promise<Operation<ExportBundle>> {
    const payload = await this._request("POST", await this.route("/export"));
    return Operation._fromPayload<ExportBundle>(payload, { client: this._client, user: this._callScope(), kind: "bucket.export", reader: toExportBundle });
  }

  /**
   * Delete the bucket: it goes to the trash, restorable for 30 days (its files stored, and billed,
   * until it's purged). It must be empty unless `force` (which takes its files too), and in no
   * agent's tools. Returns its `TrashItem`.
   */
  async delete(options: { force?: boolean } = {}): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this.route(), { query: { force: options.force ? "true" : undefined } }), this);
  }
}
