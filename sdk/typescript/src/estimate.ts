/**
 * What something would cost a month before you make it: an app, its database and bucket, a repo, live editing.
 *
 * Each charge comes back on its own line with the unit it's billed by, the unit price NoClick charges for it (what
 * the service costs NoClick, nothing added), the quantity a month and the dollars, priced for your account's plan.
 * Leave usage out and a modest default is assumed, and the line says so. Nothing is made or charged by asking.
 *
 *     const est = await estimate([
 *       { kind: "project", runtime: "edge", usage: { requests: 100_000 } },
 *       { kind: "database", engine: "sqlite" },
 *       { kind: "bucket" },
 *     ]);
 *     console.log(`$${est.monthlyUsd.toFixed(2)} a month`);
 */

import { resolveClient } from "./client.ts";
import { asList, asObject, num, requiredNumber, str } from "./object.ts";
import type { CallOptions, JsonObject } from "./object.ts";
import { containerWire } from "./project.ts";
import type { ContainerSettings } from "./project.ts";

/** One thing to estimate: its `kind`, its options, and the usage you expect a month by name. */
export interface EstimateRequestItem {
  /** `project` (an app), `durable_objects` (an app's), `database`, `bucket`, `repo` or `live_editing`. */
  kind: string;
  /** Your own label for it, said back with its lines. */
  name?: string;
  /** A project's: `edge` (the default) or `container`. */
  runtime?: "edge" | "container";
  /**
   * A container project's settings, as `Project.create` takes them (each one left out at its default): its item then
   * says what its warm instances cost with nothing calling it (`idleUsdPerMonth`, its `warm_instances` line).
   */
  container?: ContainerSettings;
  /** A database's: `sqlite` (the default) or `postgres`. */
  engine?: "sqlite" | "postgres";
  /** Where a project (or its Durable Objects) would run; omitted, where a new one of yours would go. */
  region?: string;
  /** A project's framework, as `Project.create` takes it: `nextjs` builds on a bigger machine. */
  framework?: string;
  /** What you expect a month, by the kind's usage names (`Estimate.kinds()` lists them); the rest is assumed. */
  usage?: Record<string, number>;
}

/** One charge of an estimate: what is billed, by which unit, at what price, and how much of it a month. */
export interface EstimateLine {
  /** The kind of the item it's for: `project`, `durable_objects`, `database`, `bucket`, `repo` or `live_editing`. */
  kind: string;
  /** The `name` you gave the item, if any. */
  item: string | null;
  /** Which charge it is, e.g. `front_door`, `rows_written` or `storage`. */
  charge: string;
  /** What it charges for, in words. */
  description: string;
  /** The unit it's billed by, e.g. `million requests` or `GB-month`. */
  unit: string;
  /** The price of one `unit`, in US dollars. */
  unitUsd: number;
  /** How many units a month. */
  quantity: number;
  /** What it would cost your account a month, in US dollars. */
  usd: number;
  /**
   * Whether a default decided it: its `quantity` came from usage you left out, or its price from an option you left
   * out (an edge app's `framework`, a container's `region`).
   */
  assumed: boolean;
  raw: JsonObject;
}

/** One thing you asked about, priced: its options, the usage it was priced at, and its lines. */
export interface EstimateItem {
  kind: string;
  /** For people, e.g. `App on the edge`. */
  label: string;
  name: string | null;
  /**
   * What it was priced as: a project's `runtime`, `region` and `framework` (and a container's `container` settings, as
   * the API names them: `min_instances`, ...), a database's `engine`.
   */
  options: JsonObject;
  /** Every usage it was priced at, by name: what you gave and the defaults for the rest. */
  usage: Record<string, number>;
  /** The usage names you left out, and the options you left out whose default changes a price. */
  assumed: string[];
  monthlyUsd: number;
  lines: EstimateLine[];
  /** What its meters also charge that no usage here prices (an app's calls to AI, say), in words. */
  notIncluded: string[];
  /**
   * A container app's: what its warm instances (`minInstances`) cost a month with nothing calling it, in US dollars,
   * counted in `monthlyUsd` too. Null for any other item.
   */
  idleUsdPerMonth: number | null;
  /** A container app's: what its settings cost or change beyond each request, in a sentence (null when nothing). */
  note: string | null;
  raw: JsonObject;
}

/** A usage a kind takes: what it counts, and the default assumed when you leave it out. */
export interface EstimateUsageField {
  name: string;
  unit: string;
  description: string;
  default: number;
  /** The most it can be (a share is at most 1), else null. */
  most: number | null;
}

/** A charge a kind makes, at its unit price. */
export interface EstimatePrice {
  charge: string;
  description: string;
  unit: string;
  unitUsd: number;
  /** The usage names its quantity comes from. */
  usageFields: string[];
}

/** Something an estimate takes: the usage it's priced by and the charges it makes. */
export interface EstimateKind {
  /** What `kind` an item names; a project and a database come in variants (`options`). */
  kind: string;
  label: string;
  description: string;
  /** What this variant is priced as: a project's `runtime` and `region`, a database's `engine`. */
  options: JsonObject;
  usage: EstimateUsageField[];
  prices: EstimatePrice[];
  notIncluded: string[];
  raw: JsonObject;
}

function strings(value: unknown): string[] {
  return asList(value).map((v) => String(v));
}

function toLine(raw: JsonObject, kind: string, item: string | null): EstimateLine {
  return {
    kind, item, charge: String(raw.charge), description: String(raw.description), unit: String(raw.unit),
    unitUsd: requiredNumber(raw, "unit_usd"), quantity: requiredNumber(raw, "quantity"),
    usd: requiredNumber(raw, "usd"), assumed: raw.assumed === true, raw,
  };
}

function toItem(raw: JsonObject): EstimateItem {
  const kind = String(raw.kind);
  const name = str(raw.name);
  const usage = asObject(raw.usage);
  return {
    kind, label: String(raw.label), name, options: asObject(raw.options),
    usage: Object.fromEntries(Object.entries(usage).map(([key, value]) => [key, Number(value)])),
    assumed: strings(raw.assumed), monthlyUsd: requiredNumber(raw, "monthly_usd"),
    lines: asList(raw.lines).map((line) => toLine(asObject(line), kind, name)),
    notIncluded: strings(raw.not_included), idleUsdPerMonth: num(raw.idle_usd_per_month), note: str(raw.note), raw,
  };
}

function toKind(raw: JsonObject): EstimateKind {
  return {
    kind: String(raw.kind), label: String(raw.label), description: String(raw.description),
    options: asObject(raw.options),
    usage: asList(raw.usage).map(asObject).map((u) => ({
      name: String(u.name), unit: String(u.unit), description: String(u.description),
      default: requiredNumber(u, "default"), most: num(u.most),
    })),
    prices: asList(raw.prices).map(asObject).map((p) => ({
      charge: String(p.charge), description: String(p.description), unit: String(p.unit),
      unitUsd: requiredNumber(p, "unit_usd"), usageFields: strings(p.usage_fields),
    })),
    notIncluded: strings(raw.not_included), raw,
  };
}

/** What the items would cost a month: a usage-based estimate, priced for your account's plan. */
export class Estimate {
  readonly monthlyUsd: number;
  /** Always true: these charges are by usage, so what's charged is what's used. */
  readonly estimated: boolean;
  readonly items: EstimateItem[];
  /** Every item's lines, in order. */
  readonly lines: EstimateLine[];
  /** Your account's plan, as `GET /v1/status` names it (null for a key acting for one of your users). */
  readonly plan: JsonObject | null;
  /**
   * The usage the plan includes a month, in dollars, which every charge to the account draws from (null without a
   * plan). `plan` says whether a day's share of it is capped too.
   */
  readonly includedUsdPerMonth: number | null;
  readonly raw: JsonObject;

  /** @internal */
  constructor(raw: JsonObject) {
    this.monthlyUsd = requiredNumber(raw, "monthly_usd");
    this.estimated = raw.estimated === true;
    this.items = asList(raw.items).map((item) => toItem(asObject(item)));
    this.lines = this.items.flatMap((item) => item.lines);
    this.plan = raw.plan ? asObject(raw.plan) : null;
    this.includedUsdPerMonth = num(raw.included_usd_per_month);
    this.raw = raw;
  }

  /**
   * What `estimate` takes: each kind and variant, the usage it's priced by with the default assumed for any you
   * leave out, and each charge's unit price. A container app's prices depend on its `region` (default: where a new
   * app of yours would go). Needs the `usage` scope.
   *
   *     for (const kind of await Estimate.kinds()) {
   *       console.log(kind.kind, kind.options, kind.usage.map((u) => `${u.name}=${u.default}`));
   *     }
   */
  static async kinds(options: CallOptions & { region?: string } = {}): Promise<EstimateKind[]> {
    const page = await resolveClient(options.client).request("GET", "/v1/estimates/kinds", {
      query: { region: options.region }, user: options.user,
    });
    return asList(page).map((row) => toKind(asObject(row)));
  }
}

/**
 * What `items` would cost a month, before you make any of them. Each item names its `kind`, its options (a
 * project's `runtime`, `region` and `framework`, a database's `engine`), an optional `name` of your own, and the
 * `usage` you expect a month by name (`Estimate.kinds()` lists each kind's). Usage you leave out is assumed from
 * the kind's defaults, and so is an option you leave out whose default changes a price (an edge app's `framework`
 * picks its build machine); every line a default decided says so (`assumed`). A container app (`runtime: "container"`)
 * also takes the `container` settings `Project.create` takes: its item then says what its warm instances cost with
 * nothing calling it (`idleUsdPerMonth`) and why (`note`). Prices are what each service costs NoClick, nothing added,
 * priced for your account's plan. Needs the `usage` scope; nothing is made, held or charged. A kind, option or usage
 * it can't price throws `InvalidRequest` naming the field.
 *
 *     const est = await estimate([
 *       { kind: "project", runtime: "edge", usage: { requests: 100_000 } },
 *       { kind: "database", engine: "sqlite" },
 *       { kind: "bucket" },
 *     ]);
 *     for (const line of est.lines) {
 *       const note = line.assumed ? " (assumed)" : "";
 *       console.log(`${line.kind} ${line.charge}: ${line.quantity} ${line.unit} x $${line.unitUsd} = $${line.usd}${note}`);
 *     }
 *     console.log(`$${est.monthlyUsd.toFixed(2)} a month`);
 *
 *     // A bot in a container that stays connected, before you make it.
 *     const [bot] = (await estimate([{ kind: "project", runtime: "container", container: { cpuAlways: true, minInstances: 1 } }])).items;
 *     console.log(`$${bot.monthlyUsd.toFixed(2)} a month, $${bot.idleUsdPerMonth?.toFixed(2)} of it idle: ${bot.note}`);
 */
export async function estimate(items: EstimateRequestItem[], options: CallOptions = {}): Promise<Estimate> {
  if (!Array.isArray(items)) throw new TypeError("items is a list, one entry per thing to estimate.");
  // Each container's settings as the API names them; every other field is sent as it is.
  const wire = items.map((item) => (item.container === undefined ? item : { ...item, container: containerWire(item.container) }));
  const raw = await resolveClient(options.client).request("POST", "/v1/estimates", {
    json: { items: wire }, user: options.user,
  });
  return new Estimate(asObject(raw));
}
