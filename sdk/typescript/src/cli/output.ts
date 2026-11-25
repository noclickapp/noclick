/**
 * How every `noclick` command answers: the convention both CLIs (Python's and TypeScript's) follow, as the Python
 * CLI's `noclick/_cli/output.py` writes it out.
 *
 * - Exit codes are `exits.ts`': 0 done, 1 failed, 2 usage, 3 waiting on a person, 4 refused by a limit, a price or
 *   a policy, 124 a wait ran out, 130 Ctrl-C.
 * - Short and human on stdout by default, notes on stderr; `--json` prints the whole answer as JSON, errors as
 *   `{"error": {...}}`.
 * - Without `--json`, the value an agent wants next (a URL, else an id) is stdout's last line, alone.
 * - An error's `next_step` is printed, with the `noclick` command it names after `run:` and a link only a person
 *   opens after `open:`; an error waiting on a person is said as `waiting on a person:`, not `error:`.
 */

import type { Op } from "./spec.ts";

import { WAITING, exitCode } from "./exits.ts";

export { FAILED, INTERRUPTED, OK, REFUSED, TIMED_OUT, USAGE, WAITING, WAITING_STATUSES, exitCode } from "./exits.ts";

const CLI = /\bnoclick(?:[ \t]+(?:[a-z][\w.:/@<>=-]*|--[\w-]+))+/g;
const CALL = /\b(GET|POST|PUT|PATCH|DELETE)\s+(\/v1\/[^\s,;)`'"]*[^\s,;.)`'"])/g;
const LINK = /https?:\/\/[^\s)`'"]+[^\s.,;)`'"]/g;
const NAME = /`?\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b`?/g;
const LAST_KEYS = ["url", "live_url", "preview_url", "approve_url", "connect_url", "link", "id"];

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** `value` as JSON holds it: an SDK object as its `raw`. */
export function plain(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(plain);
  if (value instanceof Date) return value.toISOString();
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
}

export const processIo: Io = {
  out: (line) => process.stdout.write(`${line}\n`),
  err: (line) => process.stderr.write(`${line}\n`),
};

export function printJson(io: Io, value: unknown): void {
  io.out(JSON.stringify(plain(value), null, 2));
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

/** `noclick <area> <command>` with the path's parameters: a concrete path's values, else `<name>`. */
export function commandLine(op: Op, path: string): string {
  const template = op.path.replace(/^\/|\/$/g, "").split("/");
  const given = path.replace(/^\/|\/$/g, "").split("/");
  const values: Record<string, string> = {};
  if (template.length === given.length) {
    template.forEach((t, i) => {
      const g = given[i]!;
      if (t.startsWith("{") && !(g.startsWith("{") || g === "...")) values[t.slice(1, -1)] = g;
    });
  }
  const args = op.params.filter((p) => p.in === "path").map((p) => values[p.name] ?? `<${p.name}>`);
  return ["noclick", op.area, op.command, ...args].join(" ");
}

/** Turns what an error says into commands: a `METHOD /v1/...` call or an operation's name into its command. */
export class Commands {
  private readonly byCall: (method: string, path: string) => Op | null;
  private readonly byName: (name: string) => Op | null;

  constructor(byCall: (method: string, path: string) => Op | null, byName: (name: string) => Op | null) {
    this.byCall = byCall;
    this.byName = byName;
  }

  forCall(method: string, path: string): string {
    const op = this.byCall(method, path);
    return op ? commandLine(op, path) : `noclick api ${method} ${path}`;
  }

  runnable(text: string | null | undefined): string[] {
    const found: string[] = [];
    for (const m of (text ?? "").matchAll(CLI)) found.push(m[0].replace(/\.$/, ""));
    for (const m of (text ?? "").matchAll(CALL)) found.push(this.forCall(m[1]!, m[2]!));
    for (const m of (text ?? "").matchAll(NAME)) {
      const op = this.byName(m[1]!);
      if (op) found.push(commandLine(op, op.path));
    }
    return [...new Set(found)];
  }
}

interface ErrorLike {
  type?: string;
  message?: string;
  nextStep?: string | null;
  details?: Json;
  requestId?: string | null;
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

export function errorBody(error: ErrorLike, commands?: Commands): Json {
  const body: Json = {
    type: error.type ?? "error",
    message: error.message || String(error),
    next_step: error.nextStep ?? null,
    exit_code: exitCode(error.type),
  };
  if (commands && error.nextStep) body.commands = commands.runnable(error.nextStep);
  const links = linksOf(error);
  if (links.length) body.links = links;
  if (error.requestId) body.request_id = error.requestId;
  if (error.details && Object.keys(error.details).length) body.details = plain(error.details);
  return body;
}

/** Print an error the convention's way; returns its exit code. */
export function report(io: Io, error: ErrorLike, options: { json: boolean; commands?: Commands }): number {
  const body = errorBody(error, options.commands);
  if (options.json) {
    printJson(io, { error: body });
  } else {
    io.err(`${body.exit_code === WAITING ? "waiting on a person" : "error"}: ${body.message}`);
    if (body.next_step) io.err(`  next step: ${body.next_step}`);
    for (const line of (body.commands as string[] | undefined) ?? []) io.err(`  run: ${line}`);
    for (const link of (body.links as string[] | undefined) ?? []) io.err(`  open: ${link}`);
    if (body.request_id) io.err(`  request id: ${body.request_id}`);
  }
  return body.exit_code as number;
}

function rows(items: unknown[]): string[] {
  if (!items.length) return ["(none)"];
  return items.map((item) => {
    if (!isObject(item)) return String(item);
    const label = item.name ?? item.title ?? item.email ?? item.summary ?? "";
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
      let shown = typeof item === "object" ? JSON.stringify(item) : String(item);
      if (typeof item === "object" && shown.length > 100) shown = `${shown.slice(0, 97)}...`;
      lines.push(`${key}: ${shown}`);
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
