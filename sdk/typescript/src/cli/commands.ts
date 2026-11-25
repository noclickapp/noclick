/**
 * The commands made from the spec: `noclick <area> <command>` for every `/v1` operation, `noclick api`,
 * `noclick describe` and `noclick help --json`, as the Python CLI makes them (`noclick/_cli/commands.py`). Every call
 * goes through the SDK's own client (`NoClick.request`: the key, retries, typed errors).
 */

import { readFileSync } from "node:fs";

import { defaultClient } from "../client.ts";
import { NoClickError, OperationTimeout } from "../errors.ts";
import { Operation, TERMINAL_STATUSES } from "../operation.ts";
import { asUser } from "../scope.ts";
import { type ArgSpec, type FlagSpec, type Values, UsageError, helpText, parse } from "./args.ts";
import { MEANINGS } from "./exits.ts";
import * as output from "./output.ts";
import type { Io } from "./output.ts";
import { type Op, type Param, type Spec, load } from "./spec.ts";

const RESERVED = new Set(["json", "data", "wait", "no_wait", "user", "timeout", "help", "profile", "version"]);
export const WAIT_WINDOW_S = { value: 20 };

export function flagOf(name: string): string {
  return `--${(RESERVED.has(name) ? `field-${name}` : name).replace(/_/g, "-")}`;
}

export function commandsFor(spec: Spec): output.Commands {
  return new output.Commands((m, p) => spec.forCall(m, p), (n) => spec.named(n));
}

/** The flags every command made from an operation takes besides its own fields. */
export const COMMON: (FlagSpec & { help: string })[] = [
  { flag: "--json", dest: "json", type: "bool", help: "Print the whole answer as JSON." },
  { flag: "--user", dest: "user", type: "string", help: "Act for this user: your id for them." },
  { flag: "--data", dest: "data", type: "string", help: "The whole request body: JSON, @file or - for stdin." },
  { flag: "--no-wait", dest: "no_wait", type: "bool", help: "When it starts an operation, print its id instead of waiting." },
  { flag: "--timeout", dest: "timeout", type: "number", help: "Stop waiting after this many seconds (exit 124; the operation keeps going)." },
];

function flagType(param: Param): FlagSpec["type"] {
  if (param.type === "boolean") return "bool";
  if (param.type === "list") return "list";
  if (param.type === "integer" || param.type === "number") return param.type;
  return "string";
}

export function opSpecs(op: Op): { flags: (FlagSpec & { help?: string })[]; args: (ArgSpec & { help?: string })[] } {
  const args = op.params.filter((p) => p.in === "path").map((p) => ({ name: p.name, help: p.description }));
  const flags = op.params.filter((p) => p.in !== "path").map((p) => ({
    flag: flagOf(p.name), dest: `field__${p.name}`, type: flagType(p),
    choices: p.type === "list" || p.type === "json" ? undefined : p.choices, help: p.description,
  }));
  return { flags: [...flags, ...COMMON], args };
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

/** The call `values` make: its path, query and body (`--data`, then each flag given over it). */
export function requestOf(op: Op, values: Values): Request {
  const data = readData(values.data);
  let body: unknown = data && typeof data === "object" && !Array.isArray(data) && op.body === "merge" ? { ...(data as object) } : data;
  const query: Record<string, string | number | boolean> = {};
  let path = op.path;
  const missing: string[] = [];
  for (const param of op.params) {
    if (param.in === "path") {
      path = path.replace(`{${param.name}}`, encodeURIComponent(String(values[param.name])));
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
    throw new UsageError(`${op.area} ${op.command} needs ${missing.join(", ")}.`, `noclick describe ${op.area} ${op.command}`);
  }
  if (["POST", "PUT", "PATCH"].includes(op.method) && body === undefined && op.body === "merge") body = {};
  return { method: op.method, path, query, body };
}

async function call(request: Request, user: unknown): Promise<unknown> {
  const send = () => defaultClient().request(request.method, request.path, { json: request.body, query: request.query });
  return typeof user === "string" ? asUser(user, send) : send();
}

/** Wait on an operation through the SDK until it ends, or waits on a person. */
export async function waitFor(operation: Record<string, unknown>, timeoutS?: number): Promise<Record<string, unknown>> {
  const deadline = timeoutS === undefined ? null : Date.now() + timeoutS * 1000;
  const op = Operation.fromId(String(operation.id));
  let raw = operation;
  while (!TERMINAL_STATUSES.has(String(raw.status)) && !output.WAITING_STATUSES.has(String(raw.status))) {
    const window = deadline === null ? WAIT_WINDOW_S.value : Math.min(WAIT_WINDOW_S.value, (deadline - Date.now()) / 1000);
    if (window <= 0) {
      throw new OperationTimeout(`Operation ${raw.id} is still ${raw.status}.`, {
        nextStep: `noclick ops wait ${raw.id}`, details: { operation_id: raw.id },
      });
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
  let shown = answer;
  if (shown && typeof shown === "object" && (shown as { object?: unknown }).object === "operation" && !values.no_wait) {
    shown = await waitFor(shown as Record<string, unknown>, values.timeout as number | undefined);
  }
  output.answer(io, shown, { json });
  if (shown && typeof shown === "object" && !Array.isArray(shown)) {
    const view = shown as Record<string, unknown>;
    if (output.WAITING_STATUSES.has(String(view.status))) {
      if (!json) io.err(`waiting on a person (${view.status}): noclick ops wait ${view.id} when done`);
      return output.WAITING;
    }
    if (view.object === "operation" && view.status === "failed") {
      const error = (view.error ?? {}) as { type?: string; message?: string; next_step?: string };
      io.err(`error: ${error.message ?? "the operation failed"}`);
      if (error.next_step) io.err(`  next step: ${error.next_step}`);
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
    io.out(helpText(usage, `${op.summary}\n\n${op.method} ${op.path}  (${op.risk})`, flags, args));
    return output.OK;
  }
  const answer = await call(requestOf(op, values), values.user);
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
  const answer = await defaultClient().request(String(values.method).toUpperCase(), path, { json: readData(values.data), query });
  return finish(io, answer, values);
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
  if (!op) throw new UsageError(`No operation ${words.join(" ")}.`, "noclick help --json lists every command.");
  if (values.json) {
    output.printJson(io, { ...op, example: example(op, spec) });
    return output.OK;
  }
  io.out(`noclick ${op.area} ${op.command}   (${op.name})`);
  io.out(`  ${op.method} ${op.path}   risk: ${op.risk}`);
  if (op.summary) io.out(`  ${op.summary}`);
  for (const param of op.params) {
    const shown = param.in === "path" ? param.name : flagOf(param.name);
    const traits = [param.type, ...(param.required ? ["required"] : []),
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
  for (const command of curated) io.out(`noclick ${command.path.join(" ").padEnd(28)} ${command.summary}`);
  if (words.length) {
    for (const op of generated) io.out(`noclick ${op.area} ${op.command.padEnd(20)} ${op.summary}`);
  } else {
    for (const [area, ops] of [...spec.areas()].sort(([a], [b]) => a.localeCompare(b))) {
      io.out(`noclick ${area.padEnd(28)} ${ops.length} API operations`);
    }
  }
  io.out("Details: noclick <command> --help; every command as JSON: noclick help --json");
  return output.OK;
}
