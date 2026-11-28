/** Operating an app, as the Python CLI's `logs`, `db query`, `estimate` and `wait` do. */

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
import { type Io, jsonText, printJson, timeText, withRun } from "../output.ts";
import { cliWords } from "../said.ts";
import { CommandError } from "../store.ts";
import { printResult } from "./data.ts";
import { answer, appNamed, num, on, str, table } from "./kit.ts";

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

const MAX_LOG_READ = 1000;

function lineText(line: LogLine): string {
  const two = (n: number) => String(n).padStart(2, "0");
  // In this machine's time zone, as the Python CLI's `astimezone().strftime("%H:%M:%S")`.
  const at = line.at ? `${two(line.at.getHours())}:${two(line.at.getMinutes())}:${two(line.at.getSeconds())}` : String(line.raw.at ?? "None");
  return `${at}  ${(line.level ?? "").toUpperCase().padEnd(5)}  ${line.message}`;
}

/** A line for `--json`: one compact JSON object a line, as the Python CLI writes it. */
function jsonLine(line: LogLine): string {
  const extra = Object.fromEntries(["environment", "request_id", "status"].filter((k) => line.raw[k] !== null && line.raw[k] !== undefined)
    .map((k) => [k, line.raw[k]]));
  return jsonText({ at: timeText(line.raw.at), level: line.level, message: line.message, deployment_id: line.deploymentId, ...extra }, null);
}

/** The app's logs, each line as it's read; `--follow` keeps reading until interrupted. `--build` prints a build's
 *  log instead: `--deployment`'s, else the app's newest deployment's. */
export async function logs(values: Values, io: Io): Promise<number> {
  const named = str(values, "project") ?? str(values, "app");
  if (on(values, "build")) {
    let deployment: Deployment;
    const id = str(values, "deployment");
    if (id) deployment = Deployment.fromId(id);
    else {
      if (!named) throw new CommandError("Name the app, or a deployment with --deployment.");
      const found = await (await appNamed(named)).deployments({ limit: 1 });
      if (!found.length) throw withRun(new NotFound(`${named} has no deployments yet.`, { nextStep: `Deploy it with: noclick deploy ${named}` }), [`noclick deploy ${named}`]);
      deployment = found[0]!;
    }
    io.err(`Build log of ${deployment.id} (${deployment.branch}, ${(deployment.commit ?? "").slice(0, 7)}, ${deployment.status}):`);
    for (const line of await deployment.logs({ kind: "build" })) io.out(`${(line.level ?? "").toUpperCase().padEnd(5)}  ${cliWords(line.message, [])}`);
    return OK;
  }
  const project = await appNamed(named);
  const limit = num(values, "limit") ?? 100;
  const level = str(values, "level") as "warn" | "error" | undefined;
  const asked = str(values, "grep");
  const grep = asked?.toLowerCase();
  // Filtered here, so a read with --grep reads the most the API answers and shows at most --limit of what matches.
  const readLimit = grep ? MAX_LOG_READ : limit;
  const timeout = num(values, "timeout");
  const ends = timeout === undefined ? null : Date.now() + timeout * 1000;
  const follow = on(values, "follow");
  const seen = new Set<string>();
  let from: Date | undefined = str(values, "since") ? since(str(values, "since")!) : undefined;
  // One read, as the Python CLI's `show`: how many lines it read that weren't seen before.
  const show = async (): Promise<number> => {
    const lines = await project.logs({ since: from, level, limit: readLimit }); // oldest first
    const fresh: LogLine[] = [];
    let fresh_ = 0;
    for (const line of lines) {
      const mark = `${line.raw.at ?? ""}|${line.deploymentId}|${line.message}`;
      if (seen.has(mark)) continue;
      seen.add(mark);
      fresh_ += 1;
      if (!grep || line.message.toLowerCase().includes(grep)) fresh.push(line);
    }
    // The latest of them when it's the first read of the latest lines, else the first after since.
    const shown = from === undefined ? fresh.slice(-limit) : fresh.slice(0, limit);
    for (const line of shown) io.out(on(values, "json") ? jsonLine(line) : lineText(line)); // each line as it's read
    if (!follow) {
      if (fresh.length > shown.length) {
        io.err(`Showing ${shown.length} of ${fresh.length} lines${grep ? " that match" : ""}: raise --limit, or narrow it with --since, --level or --grep.`);
      } else if (lines.length >= readLimit) {
        io.err(`Showing the ${from ? "first" : "last"} ${shown.length} lines read: there may be more `
          + `(${from ? "a later --since" : "--since"} reads ${from ? "on" : "further back"}).`);
      } else if (!lines.length && lines.delayS) {
        io.err(`No lines${from ? " since then" : ""}. A line takes up to ${g(lines.delayS)}s to show after its request: read again in a moment, or follow them with -f.`);
      } else if (lines.length && !shown.length) io.err(`No lines match '${asked}'.`);
    }
    if (lines.length) from = lines.at(-1)!.at ?? from;
    return fresh_;
  };
  let read = await show();
  if (!follow) return OK;
  while (ends === null || Date.now() < ends) {
    if (read < readLimit) await host.sleep(FOLLOW_EVERY_MS); // a read full of new lines may have stopped short: read on at once
    read = await show();
  }
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
    throw withRun(new CommandError("Name what to estimate: a kind (noclick estimate database), or a JSON file of items (- for stdin).",
      { nextStep: "Run noclick estimate --kinds to see what each kind takes." }), ["noclick estimate --kinds"]);
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

/** `wait`'s polls apart, in milliseconds (tests set 0). */
export const WAIT_POLL = { ms: 2000 };

/** Where the person acts on work waiting on them, as the operation says. */
function personLink(raw: Record<string, unknown>): string | null {
  const question = raw.question && typeof raw.question === "object" ? raw.question as Record<string, unknown> : {};
  for (const found of [question.answer_url, question.url, raw.approve_url, raw.connect_url, raw.url]) {
    if (typeof found === "string" && found) return found;
  }
  return null;
}

/** `wait <operation>`: wait for long work to finish and print its result, never on a person (it says who and
 *  where, exit 3, unless `--people`); a `--timeout` that runs out exits 124 and leaves the work running. As the
 *  Python CLI's `wait` (`wait` is its old spelling). */
export async function wait(values: Values, io: Io): Promise<number> {
  const op = Operation.fromId(String(values.operation_id));
  const timeout = num(values, "timeout");
  const ends = timeout === undefined ? null : Date.now() + timeout * 1000;
  for await (const event of op.events({ intervalMs: WAIT_POLL.ms })) {
    if (event.status === "awaiting_human" && !on(values, "people")) {
      const raw = event.raw;
      const question = raw.question && typeof raw.question === "object" ? raw.question as Record<string, unknown> : {};
      const what = question.text ?? question.message ?? raw.summary ?? "a person's answer";
      const sent = Array.isArray(raw.sent_to) && raw.sent_to.length ? ` (sent to ${raw.sent_to.join(", ")})` : "";
      throw withRun(new WaitingOnPerson(`${op.kind} waits on a person: ${what}${sent}.`, {
        link: personLink(raw) ?? op.consoleUrl, nextStep: `Once they've answered: noclick wait ${op.id}`,
      }), [`noclick wait ${op.id}`]);
    }
    if (!["queued", "running", "awaiting_human"].includes(event.status)) break;
    if (ends !== null && Date.now() >= ends) {
      throw withRun(new OperationTimeout(`${op.kind} is still ${event.status} after ${timeout}s.`, {
        nextStep: `Wait again: noclick wait ${op.id}`, details: { operation_id: op.id, operation_status: event.status },
      }), [`noclick wait ${op.id}`]);
    }
  }
  await op.wait(); // finished: throws the error it failed with
  const raw = (op._raw ?? {}) as Record<string, unknown>;
  const result = raw.result as Record<string, unknown> | null | undefined;
  // A deploy or promote that went live but failed its check exits 1, whatever it prints.
  const broken = ["project.deploy", "deployment.promote"].includes(op.kind) && !!result && typeof result === "object" && typeof result.warning === "string";
  if (on(values, "json")) {
    printJson(io, raw);
    return broken ? FAILED : OK;
  }
  io.err(`${op.kind} ${op.status}`);
  if (result && typeof result === "object" && typeof result.text === "string") io.out(result.text);
  else if (result && typeof result === "object" && typeof result.url === "string") {
    io.out(jsonText(result));
    io.out(result.url);
  }
  else if (result !== null && result !== undefined) io.out(jsonText(result));
  if (["project.deploy", "deployment.promote"].includes(op.kind) && result && typeof result === "object") {
    if (typeof result.warning === "string") {
      io.err(`warning: ${result.warning}`);
      if (typeof result.next_step === "string") io.err(`  next step: ${result.next_step}`);
      return FAILED;
    }
    if (typeof result.code_unchecked === "string") io.err(`note: ${result.code_unchecked}`);
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
  if (!text.trim()) throw withRun(new CommandError("Send some text.", { nextStep: "noclick agents send <agent> 'What changed?'" }), [`noclick agents send ${name} 'What changed?'`]);
  const live = (await Agent.list({ name, user })).filter((a) => a.status !== "expired");
  const agent = live.sort((a, b) => Number(a.userId === null) - Number(b.userId === null))[0];
  if (!agent) throw withRun(new NotFound(`No agent is named '${name}'.`, { nextStep: "List agents with: noclick agents list" }), ["noclick agents list"]);
  const files = ((values.file as string[] | undefined) ?? []).map((path) => ({ data: new Uint8Array(readFileSync(path)), name: basename(path) }));
  const turn = await agent.send(text, { conversation: str(values, "conversation"), files, user });
  if (on(values, "no_wait")) {
    io.out(turn.id);
    io.err(`Sent. Read its reply with: noclick wait ${turn.id}`);
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
