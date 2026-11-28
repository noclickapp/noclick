/**
 * How every `noclick` command answers: the convention both CLIs (Python's and TypeScript's) follow, as the Python
 * CLI's `noclick/_cli/output.py` writes it out.
 *
 * - Exit codes are `exits.ts`': 0 done, 1 failed, 2 usage, 3 waiting on a person, 4 refused by a limit, a price or
 *   a policy, 124 a wait ran out, 130 Ctrl-C.
 * - Short and human on stdout by default, notes on stderr; `--json` prints the whole answer as JSON, errors as
 *   `{"error": {...}}`.
 * - Without `--json`, the value an agent wants next (a URL, else an id) is stdout's last line, alone.
 * - An error's `next_step` is printed, then each command it suggests after `run:` and a link only a person opens after
 *   `open:`; an error waiting on a person is said as `waiting on a person:`, not `error:`. The commands come from
 *   fields, never out of its words: the CLI's own (`run`, set where it's raised: `withRun(err, [...])`), the API's
 *   (`details.run`), and the command that makes each API route its next step names (`GET /v1/agents`).
 *   The next step's own words say each API call and operation it names as the `noclick` command that makes it.
 */

import type { Command, Op } from "./spec.ts";

import { WAITING, exitCode } from "./exits.ts";
import { ERR, OUT } from "./style.ts";

export { FAILED, INTERRUPTED, OK, REFUSED, TIMED_OUT, USAGE, WAITING, WAITING_STATUSES, exitCode } from "./exits.ts";

const CALL = /\b(GET|POST|PUT|PATCH|DELETE)\s+(\/v1\/[^\s,;)`'"]*[^\s,;.)`'"])/g;
const NAME = /`?\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b`?/g;
const LINK = /https?:\/\/[^\s)`'"]+[^\s.,;)`'"]/g;
const LAST_KEYS = ["url", "live_url", "preview_url", "approve_url", "connect_url", "link", "id"];
const SHELL_SAFE = /^[\p{L}\p{N}_@%+=:,./-]+$/u;

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A time as the Python CLI's JSON writes it (`datetime.isoformat`, in UTC): `2026-11-20T09:15:00+00:00`, with
 *  microseconds only when it has a fraction of a second. */
export function isoformat(at: Date): string {
  const [whole, fraction] = at.toISOString().slice(0, -1).split(".");
  return `${whole}${fraction && Number(fraction) ? `.${fraction.padEnd(6, "0")}` : ""}+00:00`;
}

/** An API time string as the Python CLI writes the time it parses (`datetime.fromisoformat(...).isoformat()`): `Z` as
 *  `+00:00`, a fraction as microseconds and none when it's zero, seconds always; anything else as it is. Read from
 *  the text, never a `Date`, which keeps only milliseconds. */
export function timeText(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const m = /^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d)(?::(\d\d))?(?:[.,](\d+))?(Z|z|[+-]\d\d:?\d\d)?$/.exec(value);
  if (!m) return value;
  const [, day, hm, sec, fraction, zone] = m;
  const micro = (fraction ?? "").slice(0, 6).padEnd(6, "0");
  const tz = !zone ? "" : /z/i.test(zone) ? "+00:00" : zone.includes(":") ? zone : `${zone.slice(0, 3)}:${zone.slice(3)}`;
  return `${day}T${hm}:${sec ?? "00"}${Number(micro) ? `.${micro}` : ""}${tz}`;
}

/** `value` as JSON holds it: an SDK object as its `raw`. */
export function plain(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(plain);
  if (value instanceof Date) return isoformat(value);
  if (isObject(value)) {
    const raw = (value as { raw?: unknown }).raw;
    if (isObject(raw) && raw !== value) return plain(raw);
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plain(v)]));
  }
  return value;
}

export interface Io {
  out(line: string): void;
  err(line: string): void;
  /** Bytes to stdout as they are (a file an answer holds): no newline added. */
  write(data: Uint8Array): void;
  /** Which streams are terminals, and how wide stdout's is: only those are styled. An Io without it has none. */
  terminal?(): { out: boolean; err: boolean; columns: number };
  /** stderr as it is, no newline added (a line drawn again in place); an Io without it draws nothing in place. */
  errWrite?(text: string): void;
}

export const processIo: Io = {
  out: (line) => process.stdout.write(`${line}\n`),
  write: (data) => process.stdout.write(data),
  err: (line) => process.stderr.write(`${line}\n`),
  terminal: () => ({ out: Boolean(process.stdout.isTTY), err: Boolean(process.stderr.isTTY), columns: process.stdout.columns || 100 }),
  errWrite: (text) => process.stderr.write(text),
};

/** A size as a person reads it (1.8 GB), as the Python CLI's `output.size`. */
export function size(n: number): string {
  let amount = n;
  for (const unit of ["B", "KB", "MB", "GB", "TB"]) {
    if (amount < 1000 || unit === "TB") return unit === "B" ? `${amount.toFixed(0)} B` : `${amount.toFixed(1)} ${unit}`;
    amount /= 1000;
  }
  return String(n);
}

/** JSON as the Python CLI writes it (`json.dumps(indent=2)`): every character past ASCII as its `\\uXXXX` escape. */
export function jsonText(value: unknown, indent: number | null = 2): string {
  return JSON.stringify(value, null, indent ?? undefined).replace(/[\u0080-\uffff]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

export function printJson(io: Io, value: unknown): void {
  io.out(jsonText(plain(value)));
}

/** The value an agent wants next: an answer's URL, else its id (an operation's: its result's, if any). */
export function lastValue(value: unknown): string | null {
  if (isObject(value) && value.object === "operation" && isObject(value.result)) {
    const found = lastValue(value.result);
    if (found && found !== value.result.id) return found;
  }
  if (isObject(value)) {
    for (const key of LAST_KEYS) {
      const found = value[key];
      if (typeof found === "string" && found) return found;
    }
  }
  return null;
}

/** `noclick <area> <command>` with the path's parameters: a concrete path's values, else `<name>`; given `flag`, the
 *  query parameters the path carries as the flags that set them (`--limit 5`). */
export function commandLine(op: Op, path: string, flag?: (name: string) => string): string {
  const at = path.indexOf("?");
  const query = at < 0 ? "" : path.slice(at + 1);
  const template = op.path.replace(/^\/|\/$/g, "").split("/");
  const given = (at < 0 ? path : path.slice(0, at)).replace(/^\/|\/$/g, "").split("/");
  const values: Record<string, string> = {};
  if (template.length === given.length) {
    template.forEach((t, i) => {
      const g = given[i]!;
      if (t.startsWith("{") && !(g.startsWith("{") || g === "...")) values[t.slice(1, -1)] = g;
    });
  }
  const args = op.params.filter((p) => p.in === "path").map((p) => values[p.name] ?? `<${p.name}>`);
  const taken = new Set(op.params.filter((p) => p.in === "query").map((p) => p.name));
  const flags = flag ? [...new URLSearchParams(query)].filter(([k, v]) => v !== "" && taken.has(k)).map(([k, v]) => `${flag(k)} ${quoted(v)}`) : [];
  return ["noclick", op.area, op.command, ...args, ...flags].join(" ");
}

/** `value` as a shell reads it back: as it is when it's safe there, else in single quotes. */
function quoted(value: string): string {
  return SHELL_SAFE.test(value) ? value : `'${value.replace(/'/g, "'\\''")}'`;
}

/** The `noclick` command that makes an API route (`METHOD /v1/...`) or an operation (by its name), from the generated
 *  spec; `flag` names a query parameter's flag. */
export class Commands {
  private readonly byCall: (method: string, path: string) => Op | null;
  private readonly byName: (name: string) => Op | null;
  private readonly flag?: (name: string) => string;
  private readonly curated: (path: string[]) => Command | null | undefined;
  private readonly shadowed: (op: Op) => boolean;

  constructor(byCall: (method: string, path: string) => Op | null, byName: (name: string) => Op | null = () => null,
    flag?: (name: string) => string, curated: (path: string[]) => Command | null | undefined = () => null,
    shadowed: (op: Op) => boolean = () => false) {
    this.byCall = byCall;
    this.byName = byName;
    this.flag = flag;
    this.curated = curated;
    this.shadowed = shadowed;
  }

  forCall(method: string, path: string): string {
    const op = this.byCall(method, path);
    if (!op) return `noclick api ${method} ${path}`;
    if (!this.shadowed(op)) return commandLine(op, path, this.flag);
    // A curated command has its name (`domains search`): that one, with the arguments it needs, else the call.
    const command = this.curated([op.area, op.command]);
    if (!command) return `noclick api ${method} ${path}`;
    return ["noclick", ...command.path, ...command.args.filter((a) => !a.optional).map((a) => `<${a.name}>`)].join(" ");
  }

  /** `text` (an error's `next_step`) with each API call and operation it names said as the command that makes it:
   *  "List agents with GET /v1/agents." is "List agents with noclick agents list.". */
  translate(text: string): string;
  translate(text: string | null | undefined): string | null | undefined;
  translate(text: string | null | undefined): string | null | undefined {
    if (!text) return text;
    const called = text.replace(CALL, (_, method: string, path: string) => this.forCall(method, path));
    return called.replace(NAME, (whole: string, name: string) => {
      const op = this.byName(name);
      return op ? whole.replace(name, commandLine(op, op.path)) : whole;
    });
  }

  /** The command for each API route and each operation `text` (an error's `next_step`) names, in order. */
  routes(text: string | null | undefined): string[] {
    const found = [...(text ?? "").matchAll(CALL)].map((m) => this.forCall(m[1]!, m[2]!));
    for (const m of (text ?? "").matchAll(NAME)) {
      const op = this.byName(m[1]!);
      if (op) found.push(commandLine(op, op.path));
    }
    return [...new Set(found)];
  }
}

export interface ErrorLike {
  type?: string;
  message?: string;
  nextStep?: string | null;
  details?: Json;
  requestId?: string | null;
  /** The whole command lines that take its next step, printed after `run:`. */
  run?: string[];
  /** The usage of the command a mistake was made in, printed under it. */
  usage?: string;
}

/** `error` suggesting `commands` (each a whole `noclick` command line), printed after `run:`. */
export function withRun<T extends object>(error: T, commands: string[]): T {
  (error as ErrorLike).run = [...commands];
  return error;
}

/** The commands an error suggests: `also` (the command line's own wording of the API's step), the ones it was raised
 *  with (`run`), the API's (`details.run`), then the command for each route its `step` names. */
export function suggested(error: ErrorLike, commands: Commands | undefined, step: string | null, also: string[] = []): string[] {
  const given = error.details?.run;
  const found = [...also, ...(error.run ?? []), ...(Array.isArray(given) ? given : []), ...(commands ? commands.routes(step) : [])];
  return [...new Set(found.filter((c): c is string => typeof c === "string" && c !== ""))];
}

/** An error's words as the command line says them, in place of the API's (`said.ts`). */
export interface Said {
  message: string;
  nextStep: string | null;
  run: string[];
}

export function linksOf(error: ErrorLike): string[] {
  const details = error.details ?? {};
  const found: string[] = [];
  for (const key of ["link", "approve_url", "answer_url", "url", "connect_url", "payment_url", "checkout_url"]) {
    const value = details[key];
    if (typeof value === "string" && value.startsWith("http")) found.push(value);
  }
  for (const offer of Array.isArray(details.offers) ? details.offers : []) {
    if (isObject(offer) && typeof offer.url === "string") found.push(offer.url);
  }
  for (const m of (error.nextStep ?? "").matchAll(LINK)) found.push(m[0]);
  return [...new Set(found)];
}

export function errorBody(error: ErrorLike, commands?: Commands, said?: Said): Json {
  const given = said ? said.nextStep : (error.nextStep ?? null);
  const body: Json = {
    type: error.type ?? "error",
    message: said?.message ?? (error.message || String(error)),
    next_step: commands && given ? commands.translate(given) : given,
    exit_code: exitCode(error.type),
  };
  if (error.usage) body.usage = error.usage;
  const found = suggested(error, commands, given, said?.run ?? []);
  if (found.length) body.commands = found;
  const links = linksOf(error);
  if (links.length) body.links = links;
  if (error.requestId) body.request_id = error.requestId;
  const { run: _run, ...details } = error.details ?? {};
  if (Object.keys(details).length) body.details = plain(details);
  return body;
}

/** Print an error the convention's way; returns its exit code. */
export function report(io: Io, error: ErrorLike, options: { json: boolean; commands?: Commands; said?: Said }): number {
  const body = errorBody(error, options.commands, options.said);
  if (options.json) {
    printJson(io, { error: body });
  } else {
    const s = ERR;
    const said = body.exit_code === WAITING ? s.warn("waiting on a person:") : s.error("error:");
    io.err(`${said} ${s.bold(String(body.message))}`);
    if (body.usage) io.err(`  ${s.dim("usage:")} ${body.usage}`);
    if (body.next_step) io.err(`  ${s.dim("next step:")} ${body.next_step}`);
    for (const line of (body.commands as string[] | undefined) ?? []) {
      // Said once: a step that ends in the command already says it whole.
      if (!String(body.next_step ?? "").replace(/[. ]+$/, "").endsWith(line)) io.err(`  ${s.dim("run:")} ${s.link(line)}`);
    }
    for (const link of (body.links as string[] | undefined) ?? []) io.err(`  ${s.dim("open:")} ${s.link(link)}`);
    if (body.request_id) io.err(`  ${s.dim("request id:")} ${s.dim(String(body.request_id))}`);
  }
  return body.exit_code as number;
}

const labelOf = (item: Json) => item.name ?? item.title ?? item.email ?? item.summary ?? "";

function rows(items: unknown[]): string[] {
  if (!items.length) return ["Nothing to show."];
  if (OUT.on && items.every(isObject)) {
    const cell = (v: unknown) => (v === null || v === undefined ? "-" : String(v));
    return OUT.table(["ID", "NAME", "STATUS"], (items as Json[]).map((item) => [cell(item.id), cell(labelOf(item)), cell(item.status ?? item.state)]));
  }
  return items.map((item) => {
    if (!isObject(item)) return String(item);
    const label = labelOf(item);
    const status = item.status ?? item.state ?? "";
    return [item.id ?? "", label, status].filter((p) => p !== "").join("  ");
  });
}

/** An answer as short lines for a person. */
export function human(value: unknown): string[] {
  value = plain(value);
  if (isObject(value) && Array.isArray(value.data)) {
    const lines = rows(value.data);
    if (value.next_cursor) lines.push(`(more: add --cursor ${value.next_cursor})`);
    return lines;
  }
  if (Array.isArray(value)) return rows(value);
  if (isObject(value)) {
    const lines: string[] = [];
    for (const [key, item] of Object.entries(value)) {
      if (item === null || item === undefined || (Array.isArray(item) && !item.length)) continue;
      if (isObject(item) && !Object.keys(item).length) continue;
      lines.push(`${key}: ${typeof item === "object" ? JSON.stringify(item) : String(item)}`); // whole: a cut value reads as another
    }
    return lines;
  }
  return value === null || value === undefined ? [] : [String(value)];
}

/** Print a command's answer: whole as JSON, or short with its useful value last and alone. */
export function answer(io: Io, value: unknown, options: { json: boolean }): void {
  if (options.json) {
    printJson(io, value);
    return;
  }
  for (const line of human(value)) io.out(line);
  const last = lastValue(plain(value));
  if (last !== null) io.out(last);
}
