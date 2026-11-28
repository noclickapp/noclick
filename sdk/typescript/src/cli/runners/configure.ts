/**
 * Configuring an app, as the Python CLI's `secret`, `env`, `settings`, `bind`, `db create`, `bucket create` and
 * `domains` do. A secret's value comes
 * from a shell variable or stdin, never an argument (a shell keeps those), and is never printed; a domain is bought
 * only under a ceiling.
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve as resolvePath } from "node:path";

import { Bucket } from "../../bucket.ts";
import { Database, type DatabaseEngine } from "../../database.ts";
import { Dict } from "../../dict.ts";
import { Domain, type DomainContact } from "../../domain.ts";
import type { Bindable, SecretEnvironment } from "../../project.ts";
import { Queue } from "../../queue.ts";
import type { RegionName } from "../../region.ts";
import { NotFound } from "../../errors.ts";
import { UsageError, type Values } from "../args.ts";
import * as links from "../link.ts";
import type { Link } from "../link.ts";
import { host } from "../host.ts";
import { OK } from "../exits.ts";
import { type Io, jsonText, printJson, withRun } from "../output.ts";
import { findWrangler, readWrangler, setTopLevel } from "../wrangler.ts";
import * as spend from "../spend.ts";
import { CommandError } from "../store.ts";
import { answer, appOf, num, on, str, table, usd } from "./kit.ts";

function environment(values: Values): SecretEnvironment {
  return (str(values, "env") as SecretEnvironment | undefined) ?? "all";
}

export async function secretSet(values: Values, io: Io): Promise<number> {
  const name = String(values.name);
  const fromEnv = str(values, "from_env");
  let value: string;
  if (fromEnv) {
    const held = host.env[fromEnv];
    if (held === undefined) {
      throw new CommandError(`${fromEnv} isn't set in this shell.`,
        { nextStep: `export ${fromEnv}=... first, or pipe it: noclick secret set ${name} --stdin.` });
    }
    value = held;
  } else {
    if (host.stdinIsTty()) {
      throw new CommandError("--stdin reads a value piped in, and stdin is a terminal.",
        { nextStep: `Pipe it: printf %s "$VALUE" | noclick secret set ${name} --stdin, or pass --from-env VAR.` });
    }
    value = (await host.stdin()).replace(/\r?\n$/, "");
  }
  if (!value) throw new CommandError("That value is empty.", { nextStep: "Pass the value through --from-env or --stdin." });
  const { project } = await appOf(values);
  await project.secrets.set(name, value, { environment: environment(values) });
  const where = { all: "production and previews", production: "production", preview: "previews" }[environment(values)];
  io.err(`Set ${name} for ${where} on ${project.name} (${value.length} characters, never shown). It reaches the app at its next deploy: noclick deploy.`);
  answer(io, values, { name, environment: environment(values), app: project.name }, () => []);
  return OK;
}

export async function secretLs(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  const found = await project.secrets.list({ environment: environment(values) });
  answer(io, values, { data: Object.entries(found).sort().map(([n, at]) => ({ name: n, updated_at: at })) }, () => {
    const seenBy = { all: "", production: " for production", preview: " for previews" }[environment(values)];
    table(io, ["NAME", "UPDATED"], Object.entries(found).sort(), `${project.name} has no secrets${seenBy}.`, `Secrets of ${project.name}${seenBy}`);
    return [];
  });
  return OK;
}

export async function secretRm(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  const names = values.names as string[];
  for (const name of names) {
    await project.secrets.delete(name, { environment: environment(values) });
    io.err(`Deleted ${name} from ${project.name} (${environment(values)}); the app stops seeing it at its next deploy.`);
  }
  answer(io, values, { deleted: names, environment: environment(values) }, () => []);
  return OK;
}

function pair(text: string): [string, string] {
  const at = text.indexOf("=");
  if (at < 1) throw new UsageError(`Each setting is KEY=value, not ${text}.`, "noclick env set PORT=8080", ["noclick env set PORT=8080"]);
  return [text.slice(0, at), text.slice(at + 1)];
}

/** Change `noclick.json`'s `section` the same way, where the linked folder's names one: the next deploy gives the app
 *  what it says, so it would undo a change made only to the app. As the Python CLI's `_keep_in_step`. */
function keepInStep(io: Io, link: Link | null, section: string, change: (held: Record<string, unknown>) => boolean): void {
  if (!link) return;
  const path = join(dirname(dirname(link.path)), "noclick.json");
  if (!existsSync(path)) return;
  let data: unknown;
  try {
    data = JSON.parse(readFileSync(path, "utf8").replace(/^\uFEFF/, ""));
  } catch (err) {
    throw new CommandError(`noclick.json isn't valid JSON (${(err as Error).message}).`, { nextStep: "Fix noclick.json, then deploy again." });
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new CommandError(`noclick.json is a JSON object, not ${Array.isArray(data) ? "list" : typeof data}.`,
      { nextStep: "Fix noclick.json, then deploy again." });
  }
  const held = (data as Record<string, unknown>)[section];
  if (!held || typeof held !== "object") return;
  if (change(held as Record<string, unknown>)) {
    writeFileSync(path, `${JSON.stringify(data, null, 2)}\n`);
    io.err(`  noclick.json's ${section} too, so the next deploy keeps it.`);
  }
}

const put = (section: Record<string, unknown>, given: Record<string, unknown>) => {
  const changed = Object.entries(given).some(([k, v]) => JSON.stringify(section[k]) !== JSON.stringify(v));
  Object.assign(section, given);
  return changed;
};

const drop = (section: Record<string, unknown>, names: string[]) => {
  const held = names.filter((n) => n in section);
  for (const n of held) delete section[n];
  return held.length > 0;
};

export async function envSet(values: Values, io: Io): Promise<number> {
  const pairs = (values.pairs as string[]).map(pair);
  const { project, link } = await appOf(values);
  for (const [name, value] of pairs) {
    await project.settings.set(name, value);
    io.err(`Set ${name} = ${value.length <= 60 ? value : `${value.slice(0, 59)}…`} on ${project.name}.`);
  }
  keepInStep(io, link, "env", (env) => put(env, Object.fromEntries(pairs)));
  io.err("They reach the app at its next deploy: noclick deploy.");
  answer(io, values, { set: Object.fromEntries(pairs), app: project.name }, () => []);
  return OK;
}

export async function envLs(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  const found = await project.settings.list();
  answer(io, values, { data: found }, () => {
    table(io, ["NAME", "VALUE"], Object.entries(found).sort(), `${project.name} has no settings.`, `Settings of ${project.name}`);
    return [];
  });
  return OK;
}

export async function envRm(values: Values, io: Io): Promise<number> {
  const { project, link } = await appOf(values);
  for (const name of values.names as string[]) {
    await project.settings.delete(name);
    io.err(`Deleted ${name} from ${project.name}; the app stops seeing it at its next deploy.`);
  }
  keepInStep(io, link, "env", (env) => drop(env, values.names as string[]));
  answer(io, values, { deleted: values.names }, () => []);
  return OK;
}

/** What `bind` calls each kind, as the Python CLI's `_BIND_KINDS`. */
const BIND_KINDS: Record<string, string> = { db: "database", database: "database", bucket: "bucket", dict: "dict", queue: "queue", objects: "objects" };

/** A lazy handle to the resource `name` of `kind`, made where it's missing when `make` holds how. */
function handle(kind: string, name: string, make?: { engine?: string; public?: boolean; region?: string | null }): Bindable {
  const region = (make?.region ?? undefined) as RegionName | undefined;
  const createIfMissing = make !== undefined;
  if (kind === "database") return Database.fromName(name, { createIfMissing, engine: make?.engine as DatabaseEngine | undefined, region });
  if (kind === "bucket") return Bucket.fromName(name, { createIfMissing, ...(make?.public ? { public: true } : {}), region });
  if (kind === "dict") return Dict.fromName(name, { createIfMissing, region });
  return Queue.fromName(name, { createIfMissing, region });
}

/** A binding's name from a resource's (`booking-db` → `BOOKING_DB`, `ChatRoom` → `CHAT_ROOM`). */
export function bindingName(resource: string): string {
  const spaced = resource.replace(/(?<=[a-z0-9])(?=[A-Z])/g, "_");
  const name = spaced.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "").toUpperCase();
  return /^[A-Za-z]/.test(name) ? name : `R_${name}`;
}

export async function bind(values: Values, io: Io): Promise<number> {
  const kind = BIND_KINDS[String(values.kind)]!;
  const resource = String(values.resource);
  const name = str(values, "as_") ?? bindingName(resource);
  if (kind === "objects") return bindObjects(values, io, name);
  const { project, link } = await appOf(values);
  const engine = str(values, "engine");
  const isPublic = on(values, "public");
  let target = handle(kind, resource);
  let made = false;
  try {
    await (target as unknown as { refresh(): Promise<unknown> }).refresh();
    if (engine || isPublic) io.err(`The ${kind} ${resource} exists already: --engine and --public only shape a new one.`);
  } catch (err) {
    if (!(err instanceof NotFound)) throw err;
    target = handle(kind, resource, { engine: kind === "database" ? engine : undefined, public: kind === "bucket" && isPublic, region: project.region });
    await (target as unknown as { refresh(): Promise<unknown> }).refresh();
    made = true;
  }
  const binding = await project.bind(name, target);
  keepInStep(io, link, "bindings", (bindings) => put(bindings, { [name]: { [kind]: resource,
    ...(kind === "database" && engine ? { engine } : {}), ...(kind === "bucket" && isPublic ? { public: true } : {}) } }));
  io.err(`${made ? "Made the" : "Bound the"} ${kind} ${resource}${made ? " and bound it" : ""} to ${project.name} as ${name}. `
    + `Its code reads it with Project.current().${kind}("${name}") from the next deploy: noclick deploy.`);
  answer(io, values, { binding: binding.raw, made }, () => [name]);
  return OK;
}

/** A Durable Object class, which a Worker's wrangler config declares: its binding, and the migration that adds it. */
function bindObjects(values: Values, io: Io, name: string): number {
  const folder = resolvePath(str(values, "dir") ?? host.cwd());
  const link = linkAt(folder);
  const root = link ? dirname(dirname(link.path)) : folder;
  const configured = rootOf(root);
  const appFolder = configured ? join(root, configured) : root;
  const path = findWrangler(appFolder);
  const cls = String(values.resource);
  const binding = { name, class_name: cls };
  if (path === null || path.endsWith(".toml")) {
    const snippet = jsonText({ durable_objects: { bindings: [binding] }, migrations: [{ tag: "v1", new_sqlite_classes: [cls] }] });
    throw new CommandError(`A Durable Object runs in a Worker its wrangler config declares, and ${appFolder} has `
      + `${path ? "a TOML one, which noclick doesn’t edit" : "none"}.`, {
      nextStep: `Declare it in ${path ? basename(path) : "wrangler.jsonc (beside the worker’s main)"}: ${snippet}`, details: { snippet },
    });
  }
  let text = readFileSync(path, "utf8").replace(/^\uFEFF/, "");
  let data: Record<string, unknown>;
  try {
    data = readWrangler(path);
  } catch (err) {
    throw new CommandError((err as Error).message, { nextStep: (err as { nextStep?: string }).nextStep });
  }
  const objects = (data.durable_objects && typeof data.durable_objects === "object" ? data.durable_objects : {}) as Record<string, unknown>;
  const bindings = Array.isArray(objects.bindings) ? [...objects.bindings] as Record<string, unknown>[] : [];
  if (bindings.some((b) => b && typeof b === "object" && b.name === name)) {
    io.err(`${basename(path)} already binds ${name}.`);
    answer(io, values, { binding: name, changed: false }, () => [name]);
    return OK;
  }
  bindings.push(binding);
  const migrations = Array.isArray(data.migrations) ? [...data.migrations] as Record<string, unknown>[] : [];
  const added = new Set<unknown>();
  for (const m of migrations) {
    if (!m || typeof m !== "object") continue;
    for (const c of [...(m.new_sqlite_classes as unknown[] ?? []), ...(m.new_classes as unknown[] ?? [])]) added.add(c);
    for (const r of (m.renamed_classes as unknown[] ?? [])) if (r && typeof r === "object") added.add((r as { to?: unknown }).to);
  }
  if (!added.has(cls)) migrations.push({ tag: `v${migrations.length + 1}`, new_sqlite_classes: [cls] });
  text = setTopLevel(text, "durable_objects", { ...objects, bindings });
  text = setTopLevel(text, "migrations", migrations);
  writeFileSync(path, text);
  io.err(`${basename(path)} binds ${name} to the Durable Object class ${cls}${added.has(cls) ? "" : ", with a migration that adds it"}. `
    + `Export class ${cls} from the worker's main (it reaches the code as env.${name}), then noclick deploy.`);
  answer(io, values, { binding: name, class_name: cls, changed: true, file: path }, () => [name]);
  return OK;
}

/** The folder's link, its unreadable one said as the Python CLI says it. */
function linkAt(folder: string): links.Link | null {
  try {
    return links.find(folder);
  } catch {
    throw withRun(new CommandError(`The folder's .noclick/project.json doesn't say which app it's linked to.`,
      { nextStep: "noclick link <app> writes it again, or noclick unlink removes it." }), ["noclick link <app>", "noclick unlink"]);
  }
}

/** `noclick.json`'s `root` at `root`, where it names one. */
function rootOf(root: string): string | null {
  const path = join(root, "noclick.json");
  if (!existsSync(path)) return null;
  try {
    const data = JSON.parse(readFileSync(path, "utf8").replace(/^\uFEFF/, "")) as { root?: unknown };
    return typeof data.root === "string" && data.root ? data.root : null;
  } catch (err) {
    throw new CommandError(`noclick.json isn't valid JSON (${(err as Error).message}).`, { nextStep: "Fix noclick.json, then deploy again." });
  }
}

export async function domainAdd(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  const domain = await project.addDomain(String(values.name));
  const records = domain.records;
  answer(io, values, domain.raw, () => {
    if (records.length) table(io, ["TYPE", "NAME", "VALUE"], records.map((r) => [r.type, r.name, r.value]), "");
    return [domain.name];
  });
  io.err(`${project.name} answers at ${domain.name} once its DNS and certificate are in (${domain.status}): noclick domains ls`);
  return OK;
}

export async function domainLs(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  const found = await project.domains();
  answer(io, values, { data: found.map((d) => d.raw) }, () => {
    table(io, ["DOMAIN", "STATUS"], found.map((d) => [d.name, d.status]), `${project.name} answers only at ${project.url}. Add one: noclick domains add <name>.`,
      `Domains of ${project.name}`);
    return [];
  });
  return OK;
}

export async function dbCreate(values: Values, io: Io): Promise<number> {
  const engine = (str(values, "engine") ?? "sqlite") as DatabaseEngine;
  await spend.check(io, [{ kind: "database", engine }], num(values, "max_usd"),
    { what: `A ${engine} database`, per: "a month at the usage NoClick assumes" });
  const db = await Database.create(String(values.name), {
    engine, region: str(values, "region") as RegionName | undefined,
  });
  io.out(db.name);
  io.err(`Created the ${db.engine} database ${db.name}. Query it with: noclick db query ${db.name} "select 1"`);
  return OK;
}

export async function bucketCreate(values: Values, io: Io): Promise<number> {
  await spend.check(io, [{ kind: "bucket" }], num(values, "max_usd"), { what: "A bucket", per: "a month at the usage NoClick assumes" });
  const bucket = await Bucket.create(String(values.name), { public: on(values, "public"), region: str(values, "region") as RegionName | undefined });
  io.out(bucket.name);
  io.err(`Created the ${on(values, "public") ? "public " : ""}bucket ${bucket.name}. Copy a file in with: noclick bucket cp <file> ${bucket.name}:`);
  return OK;
}

export async function domainsSearch(values: Values, io: Io): Promise<number> {
  const query = String(values.query);
  const offers = await Domain.search(query, { tlds: values.tld as string[] | undefined });
  if (on(values, "json")) {
    printJson(io, offers.map((o) => o.raw));
    return OK;
  }
  table(io, ["DOMAIN", "AVAILABLE", "PRICE", "RENEWAL", "PREMIUM"],
    offers.map((o) => [o.name, o.available, usd(o.priceUsd), usd(o.renewalUsd), o.premium]), `No domains found for ${query}.`, `Domains for ${query}`);
  const asked = query.trim().toLowerCase().replace(/\.+$/, "");
  if (asked.includes(".") && offers.every((o) => o.name.toLowerCase() !== asked)) {
    io.err(`${asked} isn't for sale here: it's registered, or it names a well-known brand or bank, which NoClick never offers.`);
  }
  return OK;
}

/** A registrant file's fields, in the API's words or the SDK's. */
function registrantFrom(path: string): DomainContact {
  const raw = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
  return Object.fromEntries(Object.entries(raw).map(([k, v]) => [k.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase()), v])) as unknown as DomainContact;
}

export async function domainsBuy(values: Values, io: Io): Promise<number> {
  const name = String(values.name);
  const maxPriceUsd = num(values, "max_price")!; // required: the manifest's own --max-price
  const registrant = str(values, "registrant");
  io.err(`Buying ${name} for at most ${usd(maxPriceUsd)}, charged to your account.`);
  const purchase = await Domain.buy(name, { maxPriceUsd, years: num(values, "years"), registrant: registrant ? registrantFrom(registrant) : undefined });
  if (on(values, "no_wait")) {
    io.err(`Wait for it with: noclick wait ${purchase.id}`);
    answer(io, values, { operation_id: purchase.id, domain: name }, () => [purchase.id]);
    return OK;
  }
  const domain = await purchase.wait();
  io.err(`${domain.name} is yours (${domain.status}). Serve an app there with: noclick domains add ${domain.name}`);
  answer(io, values, domain.raw, () => [domain.name]);
  return OK;
}
