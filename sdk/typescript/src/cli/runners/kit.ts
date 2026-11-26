/**
 * What the curated commands share: reading their values, printing their answers the convention's way (`--json` the
 * whole answer, else short lines with the useful value last and alone; notes on stderr), and finding the app a
 * command acts on, as the Python CLI's parts do.
 */

import { AgentSignup } from "../../agentSignup.ts";
import { API_KEY_ENV } from "../../client.ts";
import { NoClickError, NotFound } from "../../errors.ts";
import { Project } from "../../project.ts";
import type { Values } from "../args.ts";
import { host } from "../host.ts";
import * as links from "../link.ts";
import { type Io, printJson } from "../output.ts";
import * as screens from "../screens.ts";
import { OUT } from "../style.ts";
import { load } from "../spec.ts";
import { PROFILE_ENV, readProfiles, writeProfile } from "../store.ts";

export type Run = (values: Values, io: Io) => Promise<number>;

export const str = (values: Values, key: string): string | undefined =>
  typeof values[key] === "string" ? (values[key] as string) : undefined;
export const on = (values: Values, key: string): boolean => values[key] === true;
export const num = (values: Values, key: string): number | undefined =>
  typeof values[key] === "number" ? (values[key] as number) : undefined;

export function profileOf(values: Values): string {
  return str(values, "profile") ?? host.env[PROFILE_ENV] ?? "default";
}

/** The answer: whole as JSON with `--json`, else `lines` (the last one the value an agent wants next). */
export function answer(io: Io, values: Values, data: unknown, lines: () => string[]): void {
  if (on(values, "json")) printJson(io, data);
  else for (const line of lines()) io.out(line);
}

export function cell(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value instanceof Date) return value.toISOString().replace("T", " ").slice(0, 16);
  return String(value);
}

export function usd(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `$${value.toFixed(2)}`;
}

/** Rows under headers: at a terminal a bordered table (`title` above it), else columns lined up; `empty` as a note
 *  when there are none. */
export function table(io: Io, headers: string[], rows: unknown[][], empty: string, title?: string): void {
  const cells = rows.map((row) => row.map(cell));
  if (!cells.length) {
    io.err(empty);
    return;
  }
  if (OUT.on) {
    for (const line of OUT.table(headers.map((h) => h || " "), cells, title)) io.out(line);
    return;
  }
  const widths = headers.map((h, i) => Math.max(h.length, ...cells.map((r) => r[i]!.length)));
  for (const row of [headers, ...cells]) io.out(row.map((c, i) => c.padEnd(widths[i]!)).join("  ").trimEnd());
}

export const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The app `ref` names (its id, or its name), loaded. */
export async function lookup(ref: string): Promise<Project> {
  return await (ID.test(ref) ? Project.fromId(ref) : Project.fromName(ref)).hydrate();
}

/** The app a command acts on: `--app`, else the folder's link (as the Python CLI's `_app`). */
export async function appOf(values: Values, folder?: string): Promise<{ project: Project; link: links.Link | null }> {
  const named = str(values, "app");
  if (named) return { project: await lookup(named), link: null };
  const link = links.find(folder ?? host.cwd());
  if (!link) {
    throw new links.NotLinked("This folder isn't linked to an app.", { nextStep: "noclick link <app> (once per folder), or pass --app <app>." });
  }
  try {
    return { project: await lookup(link.appId ?? link.app), link };
  } catch (err) {
    if (!(err instanceof NotFound)) throw err;
    throw new NotFound(`${link.path} links this folder to ${link.app}, which this key doesn't reach (deleted, or another account's).`,
      { nextStep: "noclick link <app> to link another, or noclick unlink." });
  }
}

/** The app a command's words name (`settings set <app>`), else the folder's linked one. */
export async function appNamed(named: string | undefined): Promise<Project> {
  const name = links.appName(named ?? null, host.cwd());
  try {
    return await lookup(name);
  } catch (err) {
    if (!(err instanceof NotFound)) throw err;
    throw new NotFound(`No app is named '${name}'.`, { nextStep: `noclick deploy --app ${name} --create makes it (and its repo).` });
  }
}

/** On an account `noclick signup` made that no person has claimed yet, say so (and where they claim it), once the
 *  command has signed in; once it's claimed, stop asking. */
export async function noteUnclaimed(values: Values, io: Io): Promise<void> {
  const login = readProfiles(host.env)[profileOf(values)];
  if (!login?.claim_url || host.env[API_KEY_ENV]) return;
  let status: unknown;
  try {
    status = (await AgentSignup.current()).status;
  } catch (err) {
    if (err instanceof NoClickError) return;
    throw err;
  }
  if (status === "unclaimed") io.err(screens.unclaimed(login.claim_url));
  else if (status === "claimed") writeProfile(host.env, profileOf(values), { ...login, claim_url: undefined });
}

/** What `noclick signup`'s `--agent` is by default. */
export const harnessOf = () => screens.harness(load().manifest.screens, host.env);
