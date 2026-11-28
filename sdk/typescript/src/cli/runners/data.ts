/**
 * Databases and storage at the terminal, as the Python CLI's `db shell`, `bucket ls` and `bucket cp` are: the same
 * flags, lines, `--json` and exit codes.
 */

import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, join, relative, sep } from "node:path";

import { Bucket } from "../../bucket.ts";
import { Database, type QueryResult } from "../../database.ts";
import { InvalidRequest, NotFound } from "../../errors.ts";
import type { Values } from "../args.ts";
import { OK } from "../exits.ts";
import { host } from "../host.ts";
import { type Io, printJson } from "../output.ts";
import { CommandError } from "../store.ts";
import { on, str, table } from "./kit.ts";
import { size } from "../output.ts";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
// A statement that defines the schema: what the engine counts as rows written for it is its own catalog's.
const DEFINES = /^\s*(?:create|drop|alter)\b/i;

/** A result as the shell (and `db query`) prints it: its rows, else what it wrote. */
export function printResult(io: Io, result: QueryResult, json: boolean, sql = ""): void {
  if (json) {
    printJson(io, result.rows);
    return;
  }
  const took = result.durationMs !== null ? ` (${result.durationMs.toFixed(0)} ms)` : "";
  if (result.columns.length) {
    table(io, result.columns, result.rows.map((row) => result.columns.map((c) => row[c])), "(no rows)");
    io.err(`${plural(result.rows.length, "row")}${took}`);
  } else if (DEFINES.test(sql)) io.err(`Done${took}.`);
  else io.err(`${plural(result.rowsWritten, "row")} written${took}`);
}

async function shellCommand(io: Io, db: Database, command: string): Promise<void> {
  const [name, ...rest] = command.split(" ");
  const tableName = rest.join(" ").trim();
  if (name === ".tables") {
    table(io, ["TABLE", "ROWS"], (await db.schema()).map((t) => [t.name, t.rowCount]), "No tables yet.");
  } else if (name === ".schema") {
    for (const t of await db.schema()) {
      if (tableName && t.name !== tableName) continue;
      io.out(t.name);
      for (const column of t.columns) {
        const flags = column.primaryKey ? " primary key" : !column.nullable ? " not null" : "";
        io.out(`  ${column.name}  ${column.type}${flags}`);
      }
    }
  } else io.err(".tables lists the tables, .schema [table] shows their columns, .quit leaves.");
}

/** Statements ending in `;`, a line at a time; `.tables`, `.schema`, `.quit`. A SQL error is said and the shell goes on. */
export async function dbShell(values: Values, io: Io): Promise<number> {
  const name = String(values.database);
  const write = on(values, "write");
  const db = await Database.fromName(name).hydrate();
  io.err(`${name}: ${db.engine}, ${write ? "reads and writes" : "read-only"}. End each statement with ; and type .help for commands.`);
  let buffer: string[] = [];
  for await (const line of host.lines(() => (buffer.length ? "...> " : `${name}> `))) {
    const command = line.trim();
    if (!buffer.length && command.startsWith(".")) {
      if (command === ".quit" || command === ".exit") break;
      await shellCommand(io, db, command);
      continue;
    }
    buffer.push(line);
    if (!command.endsWith(";")) continue;
    const sql = buffer.join("\n");
    buffer = [];
    try {
      printResult(io, write ? await db.execute(sql) : await db.query(sql), false, sql);
    } catch (err) {
      if (!(err instanceof InvalidRequest)) throw err;
      io.err(`error: ${err.message}`);
    }
  }
  return OK;
}

const REMOTE = /^([A-Za-z0-9][A-Za-z0-9._-]+):(.*)$/s;

/** `uploads:invoices/0042.pdf` names a bucket and a key; anything else is a local path. */
function remoteOf(path: string): [string, string] | null {
  const match = REMOTE.exec(path);
  return match ? [match[1]!, match[2]!] : null;
}

export async function bucketLs(values: Values, io: Io): Promise<number> {
  const path = str(values, "path");
  if (path === undefined) {
    const buckets = await Bucket.list();
    if (on(values, "json")) {
      printJson(io, buckets);
      return OK;
    }
    table(io, ["NAME", "PUBLIC", "SIZE", "OBJECTS", "CREATED"],
      buckets.map((b) => [b.name, b.public, b.sizeBytes === null ? "-" : size(b.sizeBytes), b.objectCount, b.createdAt]), "No buckets yet.");
    return OK;
  }
  const [name, prefix] = remoteOf(path) ?? [path.split("/")[0]!, path.includes("/") ? path.slice(path.indexOf("/") + 1) : ""];
  // One level at a time, like ls; -r lists every key under the prefix.
  const objects = await Bucket.fromName(name).objects({ prefix: prefix || undefined, delimiter: on(values, "recursive") ? undefined : "/" });
  if (on(values, "json")) {
    printJson(io, objects);
    return OK;
  }
  table(io, ["SIZE", "UPDATED", "KEY"], objects.map((o) => [o.isFolder || o.size === null ? null : size(o.size), o.updatedAt, o.key]),
    `Nothing in ${name}${prefix ? `:${prefix}` : ""}.`);
  return OK;
}

// What a folder's copy never uploads: a checkout's own history.
const NOT_UPLOADED = [".git"];

function localFiles(root: string): string[] {
  const found: string[] = [];
  const walk = (folder: string) => {
    for (const entry of readdirSync(folder, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))) {
      const path = join(folder, entry.name);
      if (NOT_UPLOADED.includes(entry.name)) continue;
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile()) found.push(path);
    }
  };
  walk(root);
  return found.sort();
}

/** A file's type by its extension, for the common ones (the API keeps `application/octet-stream` for the rest). */
const TYPES: Record<string, string> = {
  ".html": "text/html", ".htm": "text/html", ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript",
  ".json": "application/json", ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv", ".xml": "application/xml",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
  ".webp": "image/webp", ".ico": "image/vnd.microsoft.icon", ".pdf": "application/pdf", ".zip": "application/zip",
  ".wasm": "application/wasm", ".mp4": "video/mp4", ".mp3": "audio/mpeg", ".woff": "font/woff", ".woff2": "font/woff2",
};

const sized = (n: number) => size(n).padStart(9);

export async function bucketCp(values: Values, io: Io): Promise<number> {
  const srcText = String(values.src);
  const dstText = String(values.dst);
  const src = remoteOf(srcText);
  const dst = remoteOf(dstText);
  if (Boolean(src) === Boolean(dst)) {
    throw new CommandError("Copy between your machine and a bucket: exactly one side is bucket:key.",
      { nextStep: "For example: noclick bucket cp invoice.pdf uploads:invoices/0042.pdf" });
  }
  const recursive = on(values, "recursive");
  if (dst) { // upload
    const bucket = Bucket.fromName(dst[0]);
    let pairs: [string, Uint8Array | string][];
    if (srcText === "-") {
      if (!dst[1] || dst[1].endsWith("/")) throw new CommandError("Name the key to write stdin to.", { nextStep: "For example: uploads:notes/today.txt" });
      pairs = [[dst[1], new Uint8Array(host.stdinBytes())]];
    } else if (recursive) {
      if (!existsSync(srcText) || !statSync(srcText).isDirectory()) throw new CommandError(`${srcText} isn't a folder.`, { nextStep: "Drop -r to copy one file." });
      const base = !dst[1] || dst[1].endsWith("/") ? dst[1] : `${dst[1]}/`;
      pairs = localFiles(srcText).map((p) => [base + relative(srcText, p).split(sep).join("/"), p]);
      if (existsSync(join(srcText, ".git"))) io.err(`Leaving out ${join(srcText, ".git")}, the checkout's own history.`);
    } else {
      pairs = [[!dst[1] || dst[1].endsWith("/") ? dst[1] + basename(srcText) : dst[1], srcText]];
    }
    for (const [key, source] of pairs) {
      const data = typeof source === "string" ? new Uint8Array(readFileSync(source)) : source;
      const kind = str(values, "content_type") ?? (key ? TYPES[extname(key).toLowerCase()] : undefined);
      await bucket.put(key, data, { contentType: kind });
      io.err(`${sized(data.length)}  ${dst[0]}:${key}`);
    }
    return OK;
  }
  const [name, key] = src!;
  const bucket = Bucket.fromName(name);
  if (recursive) {
    for (const obj of await bucket.objects({ prefix: key || undefined })) {
      const path = join(dstText, obj.key.slice(key.length).replace(/^\/+/, ""));
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, await bucket.read(obj.key));
      io.err(`${sized(obj.size ?? 0)}  ${path}`);
    }
    return OK;
  }
  let data: Uint8Array;
  try {
    data = await bucket.read(key);
  } catch (err) {
    if (!(err instanceof NotFound)) throw err;
    const folder = key.includes("/") ? key.slice(0, key.lastIndexOf("/")) : "";
    throw new NotFound(err.message, { nextStep: `List its files with: noclick bucket ls ${name}${folder ? `/${folder}` : ""}`, details: err.details });
  }
  if (dstText === "-") {
    host.writeOut(data);
    return OK;
  }
  const intoFolder = (existsSync(dstText) && statSync(dstText).isDirectory()) || dstText.endsWith("/");
  const path = intoFolder ? join(dstText, key.split("/").at(-1)!) : dstText;
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, data);
  io.err(`${sized(data.length)}  ${path}`);
  return OK;
}
