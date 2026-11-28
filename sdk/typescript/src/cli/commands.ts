/**
 * The commands made from the spec: `noclick <area> <command>` for every `/v1` operation, `noclick api`,
 * `noclick describe` and `noclick help --json`, as the Python CLI makes them (`noclick/_cli/commands.py`). Every call
 * goes through the SDK's own client (`NoClick.request`: the key, retries, typed errors). A name a command had still
 * runs it, though no list shows it (its `aliases`), and a path argument naming something that has a name takes the
 * name in place of its id (`resolveNames`: an exact name, read from its list).
 */

import { readFileSync, writeFileSync } from "node:fs";

import { defaultClient } from "../client.ts";
import { NoClickError, NotFound, OperationTimeout } from "../errors.ts";
import { Operation, TERMINAL_STATUSES } from "../operation.ts";
import { asUser } from "../scope.ts";
import { type ArgSpec, type FlagSpec, type Values, UsageError, helpText, parse } from "./args.ts";
import { MEANINGS } from "./exits.ts";
import * as output from "./output.ts";
import type { Io } from "./output.ts";
import { type Op, type Param, type Spec, load } from "./spec.ts";
import * as style from "./style.ts";

const RESERVED = new Set(["json", "data", "wait", "no_wait", "user", "timeout", "help", "profile", "version"]);
export const WAIT_WINDOW_S = { value: 20 };
/** The verbs a group lists first, in this order; its other commands follow. */
export const COMMON_VERBS = ["list", "get", "create", "update", "delete"];
/** An id NoClick made: anything else given where one goes is a name, read from the list of what it names. */
const ID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
/** How many pages of a list a name is looked for in, when the list can't be narrowed to the name. */
const LOOKUP_PAGES = 20;

export function flagOf(name: string): string {
  return `--${(RESERVED.has(name) ? `field-${name}` : name).replace(/_/g, "-")}`;
}

export function commandsFor(spec: Spec): output.Commands {
  return new output.Commands((m, p) => spec.forCall(m, p), (n) => spec.named(n), flagOf, (path) => spec.curated(path), (op) => spec.shadowed(op));
}

/** A path argument's help: what the API says of it, and that it takes a name where what it names has one. */
export function pathHelp(param: Param): string | undefined {
  if (!param.lookup) return param.description;
  return [param.description, `The ${param.lookup.noun}'s name or id.`].filter(Boolean).join(" ");
}

/** The flags every command made from an operation takes besides its own fields. */
export const COMMON: (FlagSpec & { help: string })[] = [
  { flag: "--json", dest: "json", type: "bool", help: "Print the whole answer as JSON." },
  { flag: "--user", dest: "user", type: "string", help: "Act for this user: your id for them." },
  { flag: "--data", dest: "data", type: "string", help: "The whole request body: JSON, @file or - for stdin." },
  { flag: "--no-wait", dest: "no_wait", type: "bool", help: "When it starts an operation, print its id instead of waiting." },
  { flag: "--timeout", dest: "timeout", type: "number", help: "Stop waiting after this many seconds (exit 124; the operation keeps going)." },
];

export const OUTPUT: FlagSpec & { help: string } = {
  flag: "--output", dest: "output_file", type: "string", metavar: "FILE",
  help: "Save the answer to this file (a file's bytes as they are) instead of printing it.",
};

/** An answer written as it came: a body that isn't JSON as its bytes (text as it is), JSON as JSON; to stdout, or to
 *  `path` (`--output`), whose name is then stdout's last line. */
function write(io: Io, answer: unknown, path: string | undefined): number {
  const data = answer instanceof Uint8Array ? answer : new TextEncoder().encode(`${output.jsonText(output.plain(answer))}\n`);
  if (path === undefined) {
    io.write(data);
    return output.OK;
  }
  writeFileSync(path, data);
  io.err(`Saved ${output.size(data.length)} to ${path}.`);
  io.out(path);
  return output.OK;
}

function flagType(param: Param): FlagSpec["type"] {
  if (param.type === "boolean") return "bool";
  if (param.type === "list") return "list";
  if (param.type === "integer" || param.type === "number") return param.type;
  return "string";
}

export function opSpecs(op: Op): { flags: (FlagSpec & { help?: string })[]; args: (ArgSpec & { help?: string })[] } {
  const args = op.params.filter((p) => p.in === "path").map((p) => ({ name: p.name, help: pathHelp(p) }));
  const flags = op.params.filter((p) => p.in !== "path").map((p) => ({
    flag: flagOf(p.name), dest: `field__${p.name}`, type: flagType(p),
    choices: p.type === "list" || p.type === "json" ? undefined : p.choices, help: p.description,
  }));
  // A field of its own named output wins over `--output`.
  return { flags: [...flags, ...COMMON, ...(op.params.some((p) => p.name === "output") ? [] : [OUTPUT])], args };
}

function readData(text: unknown): unknown {
  if (typeof text !== "string") return undefined;
  const raw = text === "-" ? readFileSync(0, "utf8") : text.startsWith("@") ? readFileSync(text.slice(1), "utf8") : text;
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw new UsageError(`--data isn't JSON: ${(err as Error).message}.`, "Pass a JSON object, @file.json or - for stdin.");
  }
}

function fieldValue(param: Param, value: unknown): unknown {
  if (param.type !== "json" || typeof value !== "string") return value;
  const raw = value.startsWith("@") ? readFileSync(value.slice(1), "utf8") : value;
  try {
    return JSON.parse(raw);
  } catch {
    return value;
  }
}

export interface Request {
  method: string;
  path: string;
  query: Record<string, string | number | boolean>;
  body: unknown;
}

/** The call `values` make: its path, query and body (`--data`, then each flag given over it). `ids`: the path
 *  arguments as `resolveNames` read them (a name given for an id, its id). */
export function requestOf(op: Op, values: Values, ids: Record<string, string> = {}): Request {
  const data = readData(values.data);
  let body: unknown = data && typeof data === "object" && !Array.isArray(data) && op.body === "merge" ? { ...(data as object) } : data;
  const query: Record<string, string | number | boolean> = {};
  let path = op.path;
  const missing: string[] = [];
  for (const param of op.params) {
    if (param.in === "path") {
      path = path.replace(`{${param.name}}`, encodeURIComponent(ids[param.name] ?? String(values[param.name])));
      continue;
    }
    let value = values[`field__${param.name}`];
    if (value === undefined) {
      const given = body !== null && typeof body === "object" && param.name in (body as object);
      if (param.required && !given) missing.push(flagOf(param.name));
      continue;
    }
    value = fieldValue(param, value);
    if (param.in === "query") {
      query[param.name] = Array.isArray(value) ? value.join(",") : (value as string | number | boolean);
    } else if (op.body === "wrap") {
      body = value;
    } else {
      body = body !== null && typeof body === "object" ? body : {};
      (body as Record<string, unknown>)[param.name] = value;
    }
  }
  if (missing.length) {
    throw new UsageError(`${op.area} ${op.command} needs ${missing.join(", ")}.`, `noclick describe ${op.area} ${op.command}`,
      [`noclick describe ${op.area} ${op.command}`]);
  }
  if (["POST", "PUT", "PATCH"].includes(op.method) && body === undefined && op.body === "merge") body = {};
  return { method: op.method, path, query, body };
}

async function call(request: Request, user: unknown): Promise<unknown> {
  // The API's JSON, or the bytes of an answer that isn't JSON (a file read as it is).
  const send = () => defaultClient().request(request.method, request.path, { json: request.body, query: request.query, responseType: "auto" });
  return typeof user === "string" ? asUser(user, send) : send();
}

/** The path arguments `values` give, each name given for an id read as that id: an argument whose parameter says
 *  where its names are listed (`lookup`), given something that isn't an id NoClick made or a ref (`agent:support`). */
export async function resolveNames(op: Op, values: Values, spec: Spec = load()): Promise<Record<string, string>> {
  const ids: Record<string, string> = {};
  for (const param of op.params) {
    if (param.in !== "path") continue;
    const value = String(values[param.name]);
    ids[param.name] = !param.lookup || ID.test(value) || value.includes(":") ? value : await named(spec, param.lookup, value, ids, values.user);
  }
  return ids;
}

type Row = Record<string, unknown>;

/** The id of the one thing called `name` (or called so before a rename) in its list; none, or more than one, throws
 *  with the command that lists them. */
async function named(spec: Spec, lookup: NonNullable<Param["lookup"]>, name: string, ids: Record<string, string>, user: unknown): Promise<string> {
  const listing = spec.named(lookup.list)!;
  let path = listing.path;
  for (const param of listing.params) if (param.in === "path") path = path.replace(`{${param.name}}`, encodeURIComponent(ids[param.name]!));
  const narrowed: Record<string, string> = lookup.query ? { [lookup.query]: name } : {};
  const found = new Map<string, Row>();
  let cursor: unknown = null;
  for (let page = 0; page < LOOKUP_PAGES; page++) {
    const answer = await call({ method: "GET", path, query: { ...narrowed, ...(cursor ? { cursor: String(cursor) } : {}) }, body: undefined }, user);
    const rows = Array.isArray(answer) ? answer : (answer as { data?: unknown } | null)?.data;
    for (const row of Array.isArray(rows) ? rows : []) {
      if (!row || typeof row !== "object") continue;
      const r = row as Row;
      const former = Array.isArray(r.former_names) ? r.former_names : [];
      if (r.id && (r.name === name || former.includes(name)) && !found.has(String(r.id))) found.set(String(r.id), r);
    }
    cursor = Array.isArray(answer) ? null : (answer as { next_cursor?: unknown } | null)?.next_cursor;
    if (!cursor) break;
  }
  if (found.size === 1) return [...found.keys()][0]!;
  const listed = output.commandLine(listing, path);
  if (!found.size) throw output.withRun(new NotFound(`No ${lookup.noun} named '${name}'.`, { nextStep: `List them with ${listed}.`, details: { name } }), [listed]);
  const matches = [...found.values()].map((row) => Object.fromEntries(["id", "name", "status", "user_id"]
    .filter((k) => row[k] !== null && row[k] !== undefined).map((k) => [k, row[k]])));
  const said = matches.map((m) => (m.status ? `${m.id} (${m.status})` : String(m.id))).join(", ");
  throw new UsageError(`${matches.length} ${lookup.plural} are named '${name}': ${said}.`, "Pass the id of the one you mean.", [], undefined, { name, matches });
}

/** Wait on an operation through the SDK until it ends, or waits on a person. */
export async function waitFor(operation: Record<string, unknown>, timeoutS?: number): Promise<Record<string, unknown>> {
  const deadline = timeoutS === undefined ? null : Date.now() + timeoutS * 1000;
  const op = Operation.fromId(String(operation.id));
  let raw = operation;
  while (!TERMINAL_STATUSES.has(String(raw.status)) && !output.WAITING_STATUSES.has(String(raw.status))) {
    const window = deadline === null ? WAIT_WINDOW_S.value : Math.min(WAIT_WINDOW_S.value, (deadline - Date.now()) / 1000);
    if (window <= 0) {
      throw output.withRun(new OperationTimeout(`Operation ${raw.id} is still ${raw.status}.`, {
        nextStep: `noclick wait ${raw.id}`, details: { operation_id: raw.id },
      }), [`noclick wait ${raw.id}`]);
    }
    try {
      await op.wait({ timeoutS: Math.max(1, Math.ceil(window)) });
    } catch (err) {
      if (!(err instanceof NoClickError)) throw err;
    }
    raw = op.raw as Record<string, unknown>;
  }
  return raw;
}

/** Print an answer; an operation it started is waited on (unless `--no-wait`), and one waiting on a person exits 3. */
export async function finish(io: Io, answer: unknown, values: Values): Promise<number> {
  const json = values.json === true;
  const saved = typeof values.output_file === "string" ? values.output_file : undefined;
  if (answer instanceof Uint8Array) return write(io, answer, saved);
  let shown = answer;
  if (shown && typeof shown === "object" && (shown as { object?: unknown }).object === "operation" && !values.no_wait) {
    shown = await waitFor(shown as Record<string, unknown>, values.timeout as number | undefined);
  }
  if (saved !== undefined) return write(io, shown, saved);
  output.answer(io, shown, { json });
  if (shown && typeof shown === "object" && !Array.isArray(shown)) {
    const view = shown as Record<string, unknown>;
    if (output.WAITING_STATUSES.has(String(view.status))) {
      if (!json) io.err(`waiting on a person (${view.status}): noclick wait ${view.id} when done`);
      return output.WAITING;
    }
    if (view.object === "operation" && view.status === "failed") {
      const error = (view.error ?? {}) as { type?: string; message?: string; next_step?: string };
      io.err(`error: ${error.message ?? "the operation failed"}`);
      if (error.next_step) io.err(`  next step: ${commandsFor(load()).translate(error.next_step)}`);
      return output.exitCode(error.type);
    }
  }
  return output.OK;
}

export async function runOperation(io: Io, op: Op, argv: string[]): Promise<number> {
  const usage = `noclick ${op.area} ${op.command}`;
  const { flags, args } = opSpecs(op);
  const values = parse(argv, flags, args, usage);
  if (values.help) {
    io.out(helpText(usage, `${op.description}\n\n${op.method} ${op.path}  (${op.risk})`, flags, args));
    return output.OK;
  }
  const answer = await call(requestOf(op, values, await resolveNames(op, values)), values.user);
  return finish(io, answer, values);
}

export async function runApi(io: Io, values: Values): Promise<number> {
  const query: Record<string, string> = {};
  for (const pair of (values.query as string[] | undefined) ?? []) {
    const at = pair.indexOf("=");
    if (at < 0) throw new UsageError(`--query ${pair} isn't KEY=VALUE.`, "Pass --query limit=5.");
    query[pair.slice(0, at)] = pair.slice(at + 1);
  }
  const given = String(values.path);
  const path = given.startsWith("/") ? given : `/${given}`;
  const answer = await defaultClient().request(String(values.method).toUpperCase(), path, { json: readData(values.data), query, responseType: "auto" });
  // The raw escape hatch prints the answer as it came, unless asked for rows.
  return finish(io, answer, { ...values, json: values.table !== true });
}

/** A command line making the call with its required fields. */
export function example(op: Op, spec: Spec = load()): string {
  if (spec.shadowed(op)) return `noclick api ${op.method} ${op.path.replace(/\{/g, "<").replace(/\}/g, ">")}`;
  const words = ["noclick", op.area, op.command];
  for (const param of op.params) {
    if (param.in === "path") {
      words.push(`<${param.name}>`);
    } else if (param.required) {
      let value: string = ({ integer: "1", number: "1", boolean: "", json: "'{}'", list: "<value>" } as Record<string, string>)[param.type] ?? `<${param.name}>`;
      if (param.choices?.length) value = String(param.choices[0]);
      words.push(flagOf(param.name) + (value ? ` ${value}` : ""));
    }
  }
  return words.join(" ");
}

export function runDescribe(io: Io, values: Values): number {
  const spec = load();
  const words = values.words as string[];
  const op = spec.lookup(words);
  if (!op) throw new UsageError(`No operation ${words.join(" ")}.`, "noclick help --json lists every command.", ["noclick help --json"]);
  if (values.json) {
    output.printJson(io, { ...op, example: example(op, spec) });
    return output.OK;
  }
  io.out(`noclick ${op.area} ${op.command}   (${op.name})`);
  io.out(`  ${op.method} ${op.path}   risk: ${op.risk}`);
  if (op.description) io.out(`  ${op.description}`);
  for (const param of op.params) {
    const shown = param.in === "path" ? param.name : flagOf(param.name);
    const traits = [param.type, ...(param.lookup ? ["its name or id"] : []), ...(param.required ? ["required"] : []),
      ...(param.choices ? [`one of ${param.choices.join("|")}`] : []), ...(param.secret ? ["secret"] : [])];
    io.out(`  ${shown}  (${traits.join(", ")})${param.description ? `  ${param.description}` : ""}`);
  }
  io.out(`example: ${example(op, spec)}`);
  return output.OK;
}

export const CONVENTIONS = {
  exit_codes: MEANINGS,
  json: "--json prints the whole answer, errors as {\"error\": {...}}",
  last_line: "without --json, the useful value (a URL, else an id) is the last line",
};

/** Groups of commands and what each does, a blank line between groups and every description in one column whatever a
 *  command's length: a command longer than the column has a line of its own, its description under the column.
 *  Descriptions wrap at `width`. */
export function listing(groups: [string, string][][], width: number, s: style.Style = new style.Style()): string[] {
  const rows = groups.flat();
  if (!rows.length) return [];
  const column = Math.min(Math.max(...rows.map(([name]) => name.length)), Math.max(Math.floor((width * 2) / 5), 20));
  const room = Math.max(width - column - 2, 30);
  const out: string[] = [];
  for (const group of groups) {
    if (out.length && group.length) out.push("");
    for (const [name, text] of group) {
      const lines = wrap(text, room);
      if (name.length > column) out.push(s.accent(name));
      else out.push(`${s.accent(name.padEnd(column))}  ${s.dim(lines.shift() ?? "")}`.trimEnd());
      for (const line of lines) out.push(`${" ".repeat(column + 2)}${s.dim(line)}`);
    }
  }
  return out;
}

/** `text` in lines of at most `width`, broken between words (a word longer than a line has one of its own). */
function wrap(text: string, width: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    if (line && line.length + 1 + word.length > width) {
      lines.push(line);
      line = word;
    } else {
      line = line ? `${line} ${word}` : word;
    }
  }
  if (line) lines.push(line);
  return lines;
}

/** A group's commands: the common verbs first, in `COMMON_VERBS`'s order, then the rest as they came. */
export function grouped(rows: [string, string][]): [string, string][][] {
  const verb = (name: string) => name.split(" ").at(-1)!;
  const common = rows.filter(([name]) => COMMON_VERBS.includes(verb(name))).sort(([a], [b]) => COMMON_VERBS.indexOf(verb(a)) - COMMON_VERBS.indexOf(verb(b)));
  const rest = rows.filter(([name]) => !COMMON_VERBS.includes(verb(name)));
  return [common, rest].filter((group) => group.length);
}

export function runHelp(io: Io, values: Values): number {
  const spec = load();
  const words = (values.words as string[] | undefined) ?? [];
  const prefix = (path: string[]) => words.every((w, i) => path[i] === w);
  const curated = spec.commands.filter((c) => prefix(c.path));
  const generated = spec.operations.filter((op) => prefix([op.area, op.command]));
  if (values.json) {
    output.printJson(io, { conventions: CONVENTIONS, commands: curated, operations: generated.map((op) => ({ ...op, usage: example(op, spec) })) });
    return output.OK;
  }
  const rows: [string, string][] = curated.map((c) => [`noclick ${c.path.join(" ")}`, c.summary]);
  let groups: [string, string][][];
  if (words.length) {
    const shown = new Set(rows.map(([name]) => name));
    for (const op of generated) {
      const name = `noclick ${op.area} ${op.command}`;
      if (!shown.has(name)) rows.push([name, op.summary]);
    }
    groups = grouped(rows);
  } else {
    const areas = [...spec.areas()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    groups = [rows, areas.map(([area, ops]) => [`noclick ${area}`, `${ops.length} API operations`] as [string, string])];
  }
  for (const line of listing(groups, style.OUT.width(), style.OUT)) io.out(line);
  io.out("Details: noclick <command> --help; every command as JSON: noclick help --json");
  return output.OK;
}
