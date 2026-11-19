/** Files on messages: an agent's and a channel's, uploaded first and sent once; sent, the account's files. */

import { resolveClient } from "./client.ts";
import type { NoClick, RequestOptions } from "./client.ts";
import { asObject, fetchPage, parseTime, str } from "./object.ts";
import type { JsonObject, Page, PageOptions } from "./object.ts";

/**
 * A file on a message, kept as an account file at `url`. `kind` is `image`, `audio`, `video` or `file`; a
 * `voice` clip has its `durationMs` and its waveform's `peaks` (loudness 0-1). Audio is kept as
 * transcription reads it (a browser's WebM recording as MP3). A file an agent's conversation shows (in
 * `history`, or a `file` event) has its `name`, `url` and `mimeType`, and no `id`: it was sent. The account's
 * files (`attachments()`) have their `id`, to send again, and when each was made and last changed.
 */
export interface Attachment {
  id: string | null;
  name: string;
  mimeType: string;
  sizeBytes: number | null;
  kind: "image" | "audio" | "video" | "file";
  url: string;
  voice: boolean;
  durationMs: number | null;
  peaks: number[] | null;
  /** When it was made: one of the account's files has it; a file on a message has none. */
  createdAt: Date | null;
  /** When it last changed, as `createdAt`. */
  updatedAt: Date | null;
  raw: JsonObject;
}

/** What to upload: bytes, or a `Blob` / `File` (its `name` and `type` are used when not given). */
export type FileInput = Blob | Uint8Array | ArrayBuffer;

export interface UploadOptions {
  /** The file's name (a `File` has its own). */
  name?: string;
  /** Its type (a `Blob` has its own; else read from the name). */
  mimeType?: string;
  /** A recorded voice clip (audio). */
  voice?: boolean;
  /** A voice clip's waveform: loudness 0-1, at most 64 numbers. */
  peaks?: number[];
}

/** @internal */
export function toAttachment(raw: JsonObject): Attachment {
  const mimeType = str(raw.mime_type) ?? "application/octet-stream";
  const top = mimeType.split("/", 1)[0];
  return {
    id: str(raw.id),
    name: str(raw.name) ?? "",
    mimeType,
    sizeBytes: typeof raw.size_bytes === "number" ? raw.size_bytes : null,
    kind: (str(raw.kind) ?? (["image", "audio", "video"].includes(top) ? top : "file")) as Attachment["kind"],
    url: str(raw.url) ?? "",
    voice: raw.voice === true,
    durationMs: typeof raw.duration_ms === "number" ? raw.duration_ms : null,
    peaks: Array.isArray(raw.peaks) ? (raw.peaks as number[]) : null,
    createdAt: parseTime(raw.created_at),
    updatedAt: parseTime(raw.updated_at),
    raw,
  };
}

/** @internal The files a message's JSON lists, as attachments. */
export function toAttachments(raw: unknown): Attachment[] {
  return (Array.isArray(raw) ? (raw as JsonObject[]) : []).map(toAttachment);
}

type Request = (method: string, path: string, options: RequestOptions) => Promise<unknown>;

/** @internal POST `file` to an `attachments` route. */
export async function uploadFile(request: Request, path: string, file: FileInput, options: UploadOptions): Promise<Attachment> {
  const name = options.name ?? (typeof File !== "undefined" && file instanceof File ? file.name : undefined);
  if (!name) throw new TypeError("Name a file you upload as bytes: { name: 'report.pdf' }.");
  const type = options.mimeType ?? (file instanceof Blob && file.type ? file.type : undefined);
  const raw = await request("POST", path, {
    body: file,
    query: { name, mime_type: type, voice: options.voice ? "true" : undefined, peaks: options.peaks?.length ? options.peaks.join(",") : undefined },
  });
  return toAttachment(asObject(raw));
}

/** @internal The ids a message sends: attachments from `upload`, or their ids. */
export function attachmentIds(files: (Attachment | string)[] | undefined): string[] | undefined {
  return files?.length ? files.map((f) => (typeof f === "string" ? f : String(f.id))) : undefined;
}

export interface AttachmentsOptions {
  /** Keeps the files whose names contain it (any case). */
  query?: string;
  /** How many, 1 to 100 (30 by default). */
  limit?: number;
  client?: NoClick;
}

/**
 * The account's files, newest first: what its messages carried, the images and videos it made, its calls'
 * recordings, what its browsers downloaded and the pages they stopped on, each `url` a link that reads it for an
 * hour. A message to an agent sends any of them again in its
 * `files`. The account's alone: read as a user, it's refused.
 *
 *     const [report] = await attachments({ query: "q3" });
 *     await analyst.message("What changed since this?", { files: [report] });
 */
export async function attachments(options: AttachmentsOptions = {}): Promise<Attachment[]> {
  const page = asObject(await resolveClient(options.client).request("GET", "/v1/attachments", {
    query: { query: options.query, limit: options.limit }, user: null,
  }));
  return toAttachments(page.data);
}

/**
 * One page of the account's files, newest first; pass `nextCursor` back as `cursor`.
 *
 *     let page = await attachmentsPage({ limit: 50 });
 *     for (;;) {
 *       for (const file of page.data) console.log(file.name, file.sizeBytes);
 *       if (!page.nextCursor) break;
 *       page = await attachmentsPage({ limit: 50, cursor: page.nextCursor });
 *     }
 */
export async function attachmentsPage(options: Omit<AttachmentsOptions, "limit"> & PageOptions = {}): Promise<Page<Attachment>> {
  const page = await fetchPage(resolveClient(options.client), "/v1/attachments", {
    query: { query: options.query }, user: null, cursor: options.cursor, limit: options.limit,
  });
  return { data: page.data.map(toAttachment), nextCursor: page.nextCursor };
}

/**
 * Delete one of the account's files for good (an `Attachment` or its id): its record and what it stored, with no
 * trash to restore it from. A message that carried it keeps its name, and its link stops working. The account's own
 * to do: acting for one of your users, or from an app's code, it's refused.
 *
 *     for (const file of await attachments({ query: "draft" })) await deleteAttachment(file);
 */
export async function deleteAttachment(attachment: Attachment | string, options: { client?: NoClick } = {}): Promise<void> {
  const id = typeof attachment === "string" ? attachment : attachment.id;
  if (!id) throw new TypeError("Pass one of the account's files (from attachments()) or its id.");
  await resolveClient(options.client).request("DELETE", `/v1/attachments/${encodeURIComponent(id)}`, { user: null });
}
