/** Operating an app, as the Python CLI's `logs`, `db query`, `estimate` and `ops wait` do. */

import { readFileSync } from "node:fs";
import { basename } from "node:path";

import { Agent } from "../../agent.ts";
import { Database } from "../../database.ts";
import { Estimate, type EstimateRequestItem, estimate } from "../../estimate.ts";
import { Operation } from "../../operation.ts";
import { Deployment, type LogLine } from "../../project.ts";
import { NotFound } from "../../errors.ts";
import { UsageError, type Values } from "../args.ts";
import { host } from "../host.ts";
import { FAILED, OK } from "../exits.ts";
import { type Io, printJson } from "../output.ts";
import { CommandError } from "../store.ts";
import { answer, appNamed, num, on, str, table, usd } from "./kit.ts";

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
  const result = on(values, "write") ? await db.execute(sql, params) : await db.query(sql, params);
  answer(io, values, { columns: result.columns, rows: result.rows, rows_read: result.rowsRead, rows_written: result.rowsWritten }, () => {
    table(io, result.columns, result.rows.map((row) => result.columns.map((c) => row[c])), "No rows.");
    return [];
  });
  if (result.rowsWritten) io.err(`${result.rowsWritten} rows changed.`);
  return OK;
}

export async function estimateCmd(values: Values, io: Io): Promise<number> {
  if (on(values, "kinds")) {
    const kinds = await Estimate.kinds();
    answer(io, values, { data: kinds.map((k) => k.raw) }, () => kinds.map((k) => `${k.kind}: ${k.description}`));
    return OK;
  }
  const file = str(values, "file");
  if (!file) throw new UsageError("Name a JSON file of what to price (- for stdin), or pass --kinds.", "noclick estimate --kinds");
  const items = JSON.parse(file === "-" ? await host.stdin() : readFileSync(file, "utf8")) as EstimateRequestItem[];
  const region = str(values, "region");
  const priced = await estimate(region ? items.map((item) => ({ region, ...item })) : items);
  answer(io, values, priced.raw, () => [`${usd(priced.monthlyUsd)} a month${priced.estimated ? " (estimated from the usage given)" : ""}`]);
  return OK;
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
