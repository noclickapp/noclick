/**
 * `noclick resources` (`noclick ls`): what the account has, grouped by kind as the app's Resources page groups it, each
 * kind read from its own `/v1` list at once, as the Python CLI's `noclick/_cli/parts/resources.py` reads them. A kind
 * with nothing is left out; one that can't be read (a key without that area's scope) says why after the rest, and the
 * command exits 1 only when it could read no kind at all.
 */

import { defaultClient } from "../../client.ts";
import { NoClickError } from "../../errors.ts";
import { ALL_USERS } from "../../scope.ts";
import type { Values } from "../args.ts";
import { FAILED, OK } from "../exits.ts";
import { type Io, errorBody, printJson, size } from "../output.ts";
import { type ResourceKind, load } from "../spec.ts";
import { OUT } from "../style.ts";
import { on, str, table, usd } from "./kit.ts";

const LIMIT = 100;
type Json = Record<string, unknown>;

function field(item: Json, path: string): unknown {
  let value: unknown = item;
  for (const part of path.split(".")) value = value && typeof value === "object" ? (value as Json)[part] : undefined;
  return value;
}

/** A column's value as the table shows it. */
export function shown(value: unknown, how: ResourceKind["columns"][number][2]): string {
  if (value === null || value === undefined || value === "") return "-";
  if (how === "usd") return usd(Number(value));
  if (how === "bytes") return size(Number(value));
  if (how === "bool") return value ? "yes" : "no";
  if (how === "date") return String(value).slice(0, 10);
  return String(value);
}

export async function resources(values: Values, io: Io): Promise<number> {
  const asked = (values.kind as string[] | undefined) ?? [];
  const kinds = load().manifest.screens.resources.filter((k) => !asked.length || asked.includes(k.kind));
  const client = defaultClient();
  const user = str(values, "user");
  const read = async (path: string, query: Record<string, string | number>) => {
    try {
      return (await client.request("GET", path, { query })) as Json;
    } catch (err) {
      if (err instanceof NoClickError) return err;
      throw err;
    }
  };
  const wantsSpend = kinds.some((k) => k.columns.some(([, f]) => f === "$spend"));
  const [lists, spend] = await Promise.all([
    Promise.all(kinds.map((k) => read(k.path, { ...(k.query ?? {}), limit: LIMIT, ...(user ? {} : { user_id: ALL_USERS }) }))),
    wantsSpend ? read("/v1/usage", { group_by: "project" }) : Promise.resolve(null),
  ]);
  const byApp = new Map(spend && !(spend instanceof NoClickError) ? ((spend.groups as Json[] | undefined) ?? []).map((g) => [g.id, g.usd]) : []);
  const found: Record<string, Json[]> = {};
  const failed: Record<string, NoClickError> = {};
  kinds.forEach((k, i) => {
    const answer = lists[i]!;
    if (answer instanceof NoClickError) failed[k.kind] = answer;
    else if ((answer.data as Json[] | undefined)?.length) found[k.kind] = answer.data as Json[];
  });
  const reasons = Object.values(failed);
  if (reasons.length === kinds.length && new Set(reasons.map((e) => e.type)).size === 1) throw reasons[0]!; // said once
  if (on(values, "json")) {
    printJson(io, { kinds: found, errors: Object.fromEntries(Object.entries(failed).map(([k, e]) => [k, errorBody(e)])) });
    return Object.keys(failed).length === kinds.length ? FAILED : OK;
  }
  kinds.forEach((k, i) => {
    const rows = found[k.kind];
    if (!rows) return;
    const title = `${k.title} (${rows.length})`;
    if (!OUT.on) io.out(title);
    table(io, k.columns.map(([h]) => h), rows.map((r) => k.columns.map(([, f, how]) => shown(f === "$spend" ? byApp.get(r.id) : field(r, f), how))), "", title);
    const cursor = (lists[i] as Json).next_cursor;
    if (cursor) io.err(`The first ${LIMIT}; the rest: noclick api GET ${k.path} -q cursor=${cursor}`);
    io.out("");
  });
  for (const [name, err] of Object.entries(failed)) io.err(`${name}: unread (${err.message})`);
  if (!Object.keys(found).length && !Object.keys(failed).length) {
    io.err("Nothing yet: no websites, machines, databases, buckets, repos, domains, numbers, inboxes, sandboxes or volumes. Start one: noclick deploy");
  }
  if (spend instanceof NoClickError && found.apps) io.err(`This month's spend is unread (${spend.message}).`);
  return Object.keys(failed).length === kinds.length ? FAILED : OK;
}
