/**
 * Configuring an app, as the Python CLI's `secret`, `env`, `settings`, `bind`, `db create`, `bucket create` and
 * `domains` do. A secret's value comes
 * from a shell variable or stdin, never an argument (a shell keeps those), and is never printed; a domain is bought
 * only under a ceiling.
 */

import { readFileSync } from "node:fs";

import { Bucket } from "../../bucket.ts";
import { Database, type DatabaseEngine } from "../../database.ts";
import { Dict } from "../../dict.ts";
import { Domain, type DomainContact } from "../../domain.ts";
import type { Bindable, SecretEnvironment } from "../../project.ts";
import { Queue } from "../../queue.ts";
import type { RegionName } from "../../region.ts";
import { UsageError, type Values } from "../args.ts";
import { host } from "../host.ts";
import { OK } from "../exits.ts";
import { type Io, printJson } from "../output.ts";
import * as spend from "../spend.ts";
import { CommandError } from "../store.ts";
import { answer, appNamed, appOf, num, on, str, table, usd } from "./kit.ts";

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
  if (!value) throw new CommandError(`The value for ${name} is empty.`, { nextStep: "Set it to something, then run it again." });
  const { project } = await appOf(values);
  await project.secrets.set(name, value, { environment: environment(values) });
  io.err(`Set ${name} on ${project.name} (${environment(values)}). The app reads it from its next deploy: noclick deploy.`);
  answer(io, values, { app: project.name, secret: name, environment: environment(values), set: true }, () => []);
  return OK;
}

export async function secretLs(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  const found = await project.secrets.list({ environment: environment(values) });
  answer(io, values, { data: Object.entries(found).sort().map(([name, at]) => ({ name, updated_at: at })) }, () => {
    table(io, ["NAME", "UPDATED"], Object.entries(found).sort(), `${project.name} has no secrets for ${environment(values)}.`,
      `Secrets of ${project.name} (${environment(values)})`);
    return [];
  });
  return OK;
}

export async function secretRm(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  const names = values.names as string[];
  for (const name of names) {
    await project.secrets.delete(name, { environment: environment(values) });
    io.err(`Deleted ${name} from ${project.name}.`);
  }
  answer(io, values, { app: project.name, deleted: names }, () => []);
  return OK;
}

function pair(text: string): [string, string] {
  const at = text.indexOf("=");
  if (at < 1) throw new UsageError(`Each setting is KEY=value, not ${text}.`, "noclick env set PORT=8080");
  return [text.slice(0, at), text.slice(at + 1)];
}

export async function envSet(values: Values, io: Io): Promise<number> {
  const pairs = (values.pairs as string[]).map(pair);
  const { project } = await appOf(values);
  for (const [name, value] of pairs) {
    await project.settings.set(name, value);
    io.err(`Set ${name} on ${project.name}.`);
  }
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
  const { project } = await appOf(values);
  for (const name of values.names as string[]) await project.settings.delete(name);
  io.err(`Deleted ${(values.names as string[]).join(", ")} from ${project.name}.`);
  answer(io, values, { app: project.name, deleted: values.names }, () => []);
  return OK;
}

const KINDS: Record<string, { kind: string; make(name: string, values: Values, region: string | null): Promise<Bindable> }> = {
  db: { kind: "database", make: (name, values, region) => Database.create(name, { allowExisting: true, engine: str(values, "engine") as "sqlite" | "postgres" | undefined, region: (region ?? undefined) as RegionName | undefined }) },
  bucket: { kind: "bucket", make: (name, values, region) => Bucket.create(name, { allowExisting: true, public: on(values, "public"), region: (region ?? undefined) as RegionName | undefined }) },
  dict: { kind: "dict", make: (name) => Dict.create(name, { allowExisting: true }) },
  queue: { kind: "queue", make: (name) => Queue.create(name, { allowExisting: true }) },
};

/** A binding's name from a resource's (`booking-db` → `BOOKING_DB`). */
function bindingName(resource: string): string {
  return resource.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^(\d)/, "_$1");
}

export async function bind(values: Values, io: Io): Promise<number> {
  const kind = String(values.kind);
  const known = KINDS[kind];
  if (!known) throw new UsageError(`npx noclick binds db, bucket, dict or queue, not ${kind}.`, `pip install noclick, then noclick bind ${kind} ...`);
  const resource = String(values.resource);
  const name = str(values, "as_") ?? bindingName(resource);
  const { project } = await appOf(values);
  const made = await known.make(resource, values, project.region);
  const binding = await project.bind(name, made);
  io.err(`Bound the ${known.kind} ${resource} to ${project.name} as ${binding.name}, from its next deploy: noclick deploy.`);
  answer(io, values, { app: project.name, binding: binding.name, kind: binding.kind, resource, variables: binding.variables },
    () => [binding.name]);
  return OK;
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

export async function settingsList(values: Values, io: Io): Promise<number> {
  const project = await appNamed(str(values, "project"));
  const found = await project.settings.list();
  answer(io, values, found, () => {
    table(io, ["NAME", "VALUE"], Object.entries(found).sort(), `${project.name} has no settings.`, `Settings of ${project.name}`);
    return [];
  });
  return OK;
}

export async function settingsSet(values: Values, io: Io): Promise<number> {
  const project = await appNamed(str(values, "project"));
  await project.settings.set(String(values.name), String(values.value));
  io.err(`Set ${values.name}. It reaches ${project.name} at its next deploy: noclick deploy ${project.name}`);
  return OK;
}

export async function settingsDelete(values: Values, io: Io): Promise<number> {
  const project = await appNamed(str(values, "project"));
  await project.settings.delete(String(values.name));
  io.err(`Deleted ${values.name}. ${project.name} stops seeing it at its next deploy.`);
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
    io.err(`Wait for it with: noclick ops wait ${purchase.id}`);
    answer(io, values, { operation_id: purchase.id, domain: name }, () => [purchase.id]);
    return OK;
  }
  const domain = await purchase.wait();
  io.err(`${domain.name} is yours (${domain.status}). Serve an app there with: noclick domains add ${domain.name}`);
  answer(io, values, domain.raw, () => [domain.name]);
  return OK;
}
