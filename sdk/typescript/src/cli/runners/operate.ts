/** Operating an app, as the Python CLI's `logs`, `db query`, `estimate`, `wait` and `ops wait` do. */

import { existsSync, readFileSync } from "node:fs";
import { basename } from "node:path";

import { Agent } from "../../agent.ts";
import { Database } from "../../database.ts";
import { Estimate, type EstimateRequestItem, estimate } from "../../estimate.ts";
import { Operation } from "../../operation.ts";
import { Deployment, type LogLine } from "../../project.ts";
import { NotFound, OperationTimeout } from "../../errors.ts";
import { UsageError, type Values } from "../args.ts";
import { host } from "../host.ts";
import { FAILED, OK, WaitingOnPerson } from "../exits.ts";
import { type Io, printJson } from "../output.ts";
import { CommandError } from "../store.ts";
import { printResult } from "./data.ts";
import { answer, appNamed, num, on, str, table } from "./kit.ts";

/** `wait` reads the operation again this often. */
const WAIT_POLL_MS = 2000;

/** Say what a deploy's look at its release found (its result as the operation gave it); whether its check failed (a
 *  `warning`: it's live but not working). */
export function saidDeployment(io: Io, result: Record<string, unknown>): boolean {
  if (result.warning) {
    io.err(`warning: ${result.warning}`);
    if (result.next_step) io.err(`  next step: ${result.next_step}`);
    return true;
  }
  if (result.code_unchecked) io.err(`note: ${result.code_unchecked}`);
  return false;
}

/** `--follow` reads again this often. */
const FOLLOW_EVERY_MS = 2000;

/** `--since`: `30s`, `10m`, `2h`, `1d` ago, or an ISO time (UTC unless it says otherwise). */
export function since(text: string, now = Date.now()): Date {
  const match = /^(\d+)([smhd])$/.exec(text);
  if (match) return new Date(now - Number(match[1]) * { s: 1, m: 60, h: 3600, d: 86400 }[match[2] as "s"] * 1000);
  const when = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(text) ? text : `${text}Z`);
  if (Number.isNaN(when.getTime())) throw new UsageError(`--since takes 30s, 10m, 2h, 1d or an ISO time, not ${text}.`);
  return when;
}

function lineText(line: LogLine): string {
  const at = line.at ? line.at.toISOString().slice(11, 19) : "--:--:--";
  return `${at}  ${line.level.toUpperCase().padEnd(5)}  ${line.message}`;
}

/** The app's logs, each line as it's read; `--follow` keeps reading until interrupted. `--build` prints a build's
 *  log instead: `--deployment`'s, else the app's newest deployment's. */
export async function logs(values: Values, io: Io): Promise<number> {
  const named = str(values, "project");
  if (on(values, "build")) {
    let deployment: Deployment;
    const id = str(values, "deployment");
    if (id) deployment = Deployment.fromId(id);
    else {
      if (!named) throw new CommandError("Name the app, or a deployment with --deployment.", { nextStep: "noclick logs <app> --build" });
      const found = await (await appNamed(named)).deployments({ limit: 1 });
      if (!found.length) throw new NotFound(`${named} has no deployments yet.`, { nextStep: `Deploy it with: noclick deploy ${named}` });
      deployment = found[0]!;
    }
    for (const line of await deployment.logs({ kind: "build" })) io.out(`${(line.level ?? "").toUpperCase().padEnd(5)}  ${line.message}`);
    return OK;
  }
  if (!named) throw new CommandError("Name the app whose logs to print.", { nextStep: "noclick logs <app>" });
  const project = await appNamed(named);
  const limit = Math.min(num(values, "limit") ?? 100, 1000);
  const level = str(values, "level") as "warn" | "error" | undefined;
  const grep = str(values, "grep")?.toLowerCase();
  let from: Date | undefined = str(values, "since") ? since(str(values, "since")!) : undefined;
  const seen = new Set<string>();
  const shown: LogLine[] = [];
  const read = async (): Promise<number> => {
    const lines = await project.logs({ since: from, level, limit });
    for (const line of lines) {
      const mark = `${line.at?.getTime()}|${line.deploymentId}|${line.message}`;
      if (seen.has(mark)) continue;
      seen.add(mark);
      if (grep && !line.message.toLowerCase().includes(grep)) continue;
      shown.push(line);
      if (!on(values, "json")) io.out(lineText(line)); // each line as it's read
    }
    if (lines.length) from = lines.at(-1)!.at ?? from;
    return lines.length;
  };
  const first = await read();
  if (on(values, "follow")) {
    // Until --timeout, else until interrupted, as the Python CLI follows.
    const timeout = num(values, "timeout");
    const deadline = timeout === undefined ? Infinity : Date.now() + timeout * 1000;
    while (Date.now() < deadline) {
      await host.sleep(Math.min(FOLLOW_EVERY_MS, Math.max(0, deadline - Date.now())));
      await read();
    }
  } else if (!first) io.err("No lines. A request's lines take up to a minute to show: read again in a moment, or follow them with -f.");
  if (on(values, "json")) printJson(io, shown.map((l) => ({ at: l.at, level: l.level, message: l.message, deployment_id: l.deploymentId, request_id: l.requestId })));
  return OK;
}

function param(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function dbQuery(values: Values, io: Io): Promise<number> {
  const db = Database.fromName(String(values.database));
  const params = ((values.param as string[] | undefined) ?? []).map(param);
  const sql = String(values.sql);
  const given = params.length ? params : undefined;
  printResult(io, on(values, "write") ? await db.execute(sql, given) : await db.query(sql, given), on(values, "json"), sql);
  return OK;
}

/** A number as Python's `{:g}` writes it: six significant digits, no trailing zeros, an exponent when it's tiny or huge. */
export function g(value: number): string {
  if (value === 0 || !Number.isFinite(value)) return String(value);
  const exponent = Math.floor(Math.log10(Math.abs(value)));
  const trim = (text: string) => (text.includes(".") ? text.replace(/0+$/, "").replace(/\.$/, "") : text);
  if (exponent < -4 || exponent >= 6) {
    const [mantissa, power] = value.toExponential(5).split("e");
    const n = Number(power);
    return `${trim(mantissa!)}e${n < 0 ? "-" : "+"}${String(Math.abs(n)).padStart(2, "0")}`;
  }
  return trim(value.toPrecision(6));
}

const money = (value: number, digits: number) =>
  `$${value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

/** `NAME=VALUE` from the command line, each value a number when `number`. */
function pairs(given: string[], number = false): Record<string, string | number> {
  const found: Record<string, string | number> = {};
  for (const pair of given) {
    const at = pair.indexOf("=");
    const [name, value] = at < 0 ? [pair, ""] : [pair.slice(0, at), pair.slice(at + 1)];
    if (at < 0 || !name) throw new CommandError(`'${pair}' isn't NAME=VALUE.`, { nextStep: "Like --usage hours=40" });
    if (number) {
      const n = Number(value);
      if (value.trim() === "" || Number.isNaN(n)) throw new CommandError(`${name}'s usage is a number, not '${value}'.`);
      found[name] = n;
    } else found[name] = value;
  }
  return found;
}

/** The items in `path` (`-`: stdin): a JSON list of them, or an object holding them under `items`. */
async function itemsIn(path: string): Promise<EstimateRequestItem[]> {
  const text = path === "-" ? await host.stdin() : readFileSync(path, "utf8");
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (err) {
    throw new CommandError(`${path} isn't JSON: ${(err as Error).message}.`,
      { nextStep: 'Write a list of items, like [{"kind": "project", "usage": {"requests": 100000}}].' });
  }
  const items = data && typeof data === "object" && !Array.isArray(data) ? (data as { items?: unknown }).items : data;
  if (!Array.isArray(items)) throw new CommandError(`${path} holds no list of items.`, { nextStep: 'Write a list of items, or {"items": [...]}.' });
  return items as EstimateRequestItem[];
}

/** What a kind's variant is priced as, in a few words: its plain options. */
const optionsOf = (options: Record<string, unknown>) =>
  Object.values(options).filter((v) => v && ["string", "number"].includes(typeof v)).map(String).join(", ");

export async function estimateCmd(values: Values, io: Io): Promise<number> {
  const json = on(values, "json");
  if (on(values, "kinds")) {
    const kinds = await Estimate.kinds({ region: str(values, "region") });
    if (json) {
      printJson(io, kinds.map((k) => k.raw));
      return OK;
    }
    table(io, ["KIND", "AS", "CHARGE", "UNIT PRICE", "PER", "USAGE (DEFAULT)"],
      kinds.flatMap((k) => k.prices.map((p) => [k.kind, optionsOf(k.options), p.charge, `$${g(p.unitUsd)}`, p.unit,
        k.usage.filter((u) => p.usageFields.includes(u.name)).map((u) => `${u.name} (${g(u.default)})`).join(", ")])),
      "Nothing to estimate.");
    return OK;
  }
  const file = str(values, "file");
  if (!file) {
    throw new CommandError("Name what to estimate: a kind (noclick estimate database), or a JSON file of items (- for stdin).",
      { nextStep: "Run noclick estimate --kinds to see what each kind takes." });
  }
  let items: EstimateRequestItem[];
  if (file !== "-" && !existsSync(file) && /^[a-z_]+$/.test(file)) {
    // One item by its kind, its usage and options from the command line, its options beside its kind as the API takes them.
    const usage = (values.usage as string[] | undefined) ?? [];
    items = [{ ...pairs((values.option as string[] | undefined) ?? []), kind: file,
               ...(usage.length ? { usage: pairs(usage, true) } : {}) } as unknown as EstimateRequestItem];
  } else items = await itemsIn(file);
  const est = await estimate(items);
  if (json) {
    printJson(io, est.raw);
    return OK;
  }
  table(io, ["ITEM", "CHARGE", "QUANTITY", "UNIT", "UNIT PRICE", "A MONTH"],
    est.lines.map((line) => [line.item ?? line.kind, line.charge + (line.assumed ? " *" : ""), g(line.quantity), line.unit,
      `$${g(line.unitUsd)}`, money(line.usd, 4)]), "Nothing was priced.");
  io.out(`Total: ${money(est.monthlyUsd, 2)} a month`);
  for (const item of est.items) if (item.assumed.length) io.err(`Assumed (${item.name ?? item.kind}): ${item.assumed.join(", ")}`);
  if (est.lines.some((line) => line.assumed)) io.err("* a default decided it: give that usage or option to price it as you expect.");
  for (const item of est.items) for (const left of item.notIncluded) io.err(`Not included (${item.name ?? item.kind}): ${left}`);
  return OK;
}

/** Where a person acts on work waiting on them, as the operation says. */
function personLink(raw: Record<string, unknown>): string | null {
  const question = (raw.question && typeof raw.question === "object" ? raw.question : {}) as Record<string, unknown>;
  for (const found of [question.answer_url, question.url, raw.approve_url, raw.connect_url, raw.url]) {
    if (typeof found === "string" && found) return found;
  }
  return null;
}

/** `wait`: until the operation ends, never on a person (exit 3 says who and where; `--people` waits through). */
export async function wait(values: Values, io: Io): Promise<number> {
  const op = Operation.fromId(String(values.operation_id));
  const timeout = num(values, "timeout");
  const ends = timeout === undefined ? null : Date.now() + timeout * 1000;
  for await (const event of op.events({ intervalMs: WAIT_POLL_MS })) {
    if (event.status === "awaiting_human" && !on(values, "people")) {
      const raw = event.raw;
      const question = (raw.question && typeof raw.question === "object" ? raw.question : {}) as Record<string, unknown>;
      const what = question.text ?? question.message ?? raw.summary ?? "a person's answer";
      const sent = Array.isArray(raw.sent_to) && raw.sent_to.length ? ` (sent to ${raw.sent_to.join(", ")})` : "";
      throw new WaitingOnPerson(`${op.kind} waits on a person: ${what}${sent}.`,
        { link: personLink(raw) ?? op.consoleUrl, nextStep: `Once they've answered: noclick wait ${op.id}` });
    }
    if (!["queued", "running", "awaiting_human"].includes(event.status)) break;
    if (ends !== null && Date.now() >= ends) {
      throw new OperationTimeout(`${op.kind} is still ${event.status} after ${g(timeout!)}s.`,
        { nextStep: `Wait again: noclick wait ${op.id}`, details: { operation_id: op.id, operation_status: event.status } });
    }
  }
  await op.wait(); // finished: throws the error it failed with
  if (on(values, "json")) {
    printJson(io, op);
    return OK;
  }
  io.err(`${op.kind} ${op.status}`);
  const raw = op.result as Record<string, unknown> | null | undefined;
  if (raw && typeof raw === "object" && typeof raw.text === "string") io.out(raw.text);
  else if (raw && typeof raw === "object" && typeof raw.url === "string") {
    io.out(JSON.stringify(raw, null, 2));
    io.out(raw.url);
  } else if (raw !== null && raw !== undefined) io.out(JSON.stringify(raw, null, 2));
  return ["project.deploy", "deployment.promote"].includes(op.kind) && raw && typeof raw === "object" && saidDeployment(io, raw) ? FAILED : OK;
}

export async function opsWait(values: Values, io: Io): Promise<number> {
  const op = Operation.fromId(String(values.operation_id));
  const result = await op.wait({ timeoutS: num(values, "timeout") });
  const raw = (result && typeof result === "object" && "raw" in result ? (result as { raw: unknown }).raw : result) as Record<string, unknown> | null;
  const url = raw?.url;
  answer(io, values, { operation_id: op.id, status: "succeeded", result: raw }, () => [typeof url === "string" ? url : JSON.stringify(raw, null, 2)]);
  if (typeof raw?.warning === "string") {
    io.err(`warning: ${raw.warning}`);
    return FAILED;
  }
  return OK;
}

/** `agents send`: one message to the agent named, with each `--file` uploaded and sent with it, then its reply
 *  (`--no-wait`: the turn's operation id). `-` as the text reads it from stdin. The agent is the user's own with
 *  `--user`, else the account's, as the Python CLI finds it; an expired one takes no turns. */
export async function agentsSend(values: Values, io: Io): Promise<number> {
  const name = String(values.name);
  const user = str(values, "user");
  const text = values.text === "-" ? await host.stdin() : String(values.text ?? "");
  if (!text.trim()) throw new CommandError("Send some text.", { nextStep: "noclick agents send <agent> 'What changed?'" });
  const live = (await Agent.list({ name, user })).filter((a) => a.status !== "expired");
  const agent = live.sort((a, b) => Number(a.userId === null) - Number(b.userId === null))[0];
  if (!agent) throw new NotFound(`No agent is named '${name}'.`, { nextStep: "List agents with: noclick agents list" });
  const files = ((values.file as string[] | undefined) ?? []).map((path) => ({ data: new Uint8Array(readFileSync(path)), name: basename(path) }));
  const turn = await agent.send(text, { conversation: str(values, "conversation"), files, user });
  if (on(values, "no_wait")) {
    io.out(turn.id);
    io.err(`Sent. Read its reply with: noclick ops wait ${turn.id}`);
    return OK;
  }
  const reply = await turn.wait();
  answer(io, values, { text: reply.text, conversation: reply.conversation, tool_calls: reply.toolCalls },
    () => [reply.text]);
  if (!on(values, "json") && reply.conversation) {
    io.err(`Conversation ${reply.conversation}: continue it with --conversation ${reply.conversation}`);
  }
  return OK;
}
