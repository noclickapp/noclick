/**
 * Adding a space template: its channels, agents (with their instructions, skills and memories), automations, data
 * stores and app, made in your account as a new space (`Workspace.fromTemplate`) or beside what a space of yours
 * already holds (`workspace.addTemplate`). All of it is made, or none of it.
 *
 *     const plan = await Workspace.fromTemplate(address, { dryRun: true });
 *     console.log(plan.summary, plan.estimate.monthly_usd, plan.connections.filter((a) => !a.connected));
 *     const added = await (await Workspace.fromTemplate(address)).wait();
 *     console.log(added.workspaceId, added.channelId);
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, compact, num, refId, str } from "./object.ts";
import type { ApiObject, JsonObject, ObjectInit } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import type { UserOption } from "./scope.ts";

/** One part of a template: its `kind`, its `name` in the template, the name it'll have (`named`: a space you have
 *  carries the template's word), a line on it, the integrations it needs, and whether it comes (`included`). */
export interface TemplatePart {
  kind: "agent" | "channel" | "skill" | "memory" | "automation" | "store" | "app";
  name: string;
  named: string;
  line: string | null;
  needs: string[];
  /** A channel's agents, by the names they'll have. */
  members: string[];
  /** A channel's schedules' messages. */
  schedules: string[];
  included: boolean;
  raw: JsonObject;
}

/** An account a template's parts use: the connection of yours it'll use (`connected`), or null while it waits for
 *  you to connect one. */
export interface TemplateAccount {
  integration: string;
  label: string;
  nodeType: string | null;
  usedBy: string[];
  connected: { ref: string; name: string | null; id: string } | null;
  raw: JsonObject;
}

/** A secret a template asks for: one you hold already (`held`) is used as it is. */
export interface TemplateSecret {
  name: string;
  keys: string[];
  description: string | null;
  usedBy: string[];
  held: boolean;
  given: boolean;
}

/**
 * What adding a template would make and ask, with nothing made (a dry run): where it goes, each part under the name
 * it'll have, the month's `estimate` (its app and data stores; its agents said as the cap they stop at), the `cap`
 * shared out as its agents' budgets, each account (one you have is used, never asked again), each secret, its app's
 * deploy, whether your account can pay (`funds`), and why it can't be added (`refused`).
 */
export interface TemplatePlan {
  template: { name: string; description: string | null; word: string };
  target: { workspaceId: string | null; name: string; new: boolean };
  parts: TemplatePart[];
  /** What an unticked part leaves another without, a line each. */
  short: string[];
  connections: TemplateAccount[];
  secrets: TemplateSecret[];
  cap: { usdPerMonth: number | null; from: string | null; agents: { name: string; usdPerMonth: number | null }[] };
  app: JsonObject | null;
  /** The estimate as `POST /v1/estimates` answers it (`monthly_usd`, `items`), with `agents` (`up_to_usd`, `how`). */
  estimate: JsonObject;
  funds: JsonObject;
  refused: { message: string; nextStep: string | null } | null;
  summary: string;
  raw: JsonObject;
}

/** A template that arrived: its space, the `#noclick` its welcome post is in, and what was made. */
export interface TemplateAdded {
  workspaceId: string;
  workspaceName: string;
  channelId: string | null;
  messageId: string | null;
  agents: { id: string; name: string }[];
  channels: { id: string; name: string }[];
  /** Its app (`project_id`, `name`, `url`, `to_reveal`: the passwords NoClick made, each read once). */
  app: JsonObject | null;
  /** The accounts still waiting for you to connect. */
  waiting: JsonObject[];
  raw: JsonObject;
}

/** What adding a template takes besides its source. */
export interface TemplateOptions {
  /** Parts that stay out, each `{kind, name}` (`{kind: "app"}` for its app): every channel out brings just the agents. */
  leaveOut?: { kind: TemplatePart["kind"]; name?: string }[];
  /** What its agents may spend together in a month, shared out as their budgets (the template's own when left out). */
  capUsdPerMonth?: number;
  /** Which of your connected accounts each integration uses, by integration (the newest of its kind when left out). */
  connections?: Record<string, string>;
  /** Values for the secrets it asks for, by name: `{unsplash: {UNSPLASH_ACCESS_KEY: "..."}}`. Write-only. */
  secrets?: Record<string, Record<string, string>>;
  /** Values for the secrets its app's noclick.json asks you to set. Write-only. */
  appSecrets?: Record<string, string>;
  dryRun?: boolean;
  client?: NoClick;
}

const text = (v: unknown): string | null => str(v);

function toPart(raw: JsonObject): TemplatePart {
  return {
    kind: String(raw.kind) as TemplatePart["kind"], name: String(raw.name), named: str(raw.as) ?? String(raw.name),
    line: text(raw.line), needs: asList(raw.needs).map(String), members: asList(raw.members).map(String),
    schedules: asList(raw.schedules).flatMap((s) => (typeof s === "string" ? [s] : [])), included: raw.included === true,
    raw,
  };
}

function toAccount(raw: JsonObject): TemplateAccount {
  const held = raw.connected ? asObject(raw.connected) : null;
  return {
    integration: String(raw.integration), label: str(raw.label) ?? String(raw.integration), nodeType: str(raw.node_type),
    usedBy: asList(raw.for).map(String),
    connected: held ? { ref: String(held.ref), name: str(held.name), id: String(held.id) } : null, raw,
  };
}

/** @internal */
export function toTemplatePlan(raw: JsonObject): TemplatePlan {
  const template = asObject(raw.template);
  const target = asObject(raw.target);
  const cap = asObject(raw.cap);
  const refused = raw.refused ? asObject(raw.refused) : null;
  return {
    template: { name: String(template.name), description: str(template.description), word: str(template.word) ?? "" },
    target: { workspaceId: str(target.workspace_id), name: str(target.name) ?? "", new: target.new === true },
    parts: asList(raw.parts).map((p) => toPart(asObject(p))),
    short: asList(raw.short).map(String),
    connections: asList(raw.connections).map((c) => toAccount(asObject(c))),
    secrets: asList(raw.secrets).map((s) => {
      const one = asObject(s);
      return {
        name: String(one.name), keys: asList(one.keys).map(String), description: str(one.description),
        usedBy: asList(one.for).map(String), held: Boolean(one.held), given: one.given === true,
      };
    }),
    cap: {
      usdPerMonth: num(cap.usd_per_month) ?? null, from: str(cap.from),
      agents: asList(cap.agents).map((a) => ({ name: String(asObject(a).name), usdPerMonth: num(asObject(a).usd_per_month) ?? null })),
    },
    app: raw.app ? asObject(raw.app) : null,
    estimate: asObject(raw.estimate),
    funds: asObject(raw.funds),
    refused: refused ? { message: str(refused.message) ?? "", nextStep: str(refused.next_step) } : null,
    summary: str(raw.summary) ?? "",
    raw,
  };
}

const readAdded = (result: unknown): TemplateAdded => {
  const raw = asObject(result);
  const space = asObject(raw.workspace);
  const home = raw.channel ? asObject(raw.channel) : {};
  const named = (list: unknown) => asList(list).map((x) => ({ id: String(asObject(x).id), name: String(asObject(x).name) }));
  return {
    workspaceId: String(space.id), workspaceName: str(space.name) ?? "", channelId: str(home.id), messageId: str(raw.message_id),
    agents: named(raw.agents), channels: named(raw.channels), app: raw.app ? asObject(raw.app) : null,
    waiting: asList(raw.waiting).map((w) => asObject(w)), raw,
  };
};

registerResult("workspace.template_add", readAdded);

/**
 * A template being added: `wait()` resolves to a `TemplateAdded` once all of it is made; `progress` shows each stage
 * (copying its code, deploying its app, making its parts, saying what arrived). One that fails makes nothing: what it
 * had made goes with it.
 */
export class TemplateAdd extends Operation<TemplateAdded> {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _fromResponse(payload: unknown, init: { client?: NoClick; user?: UserOption }): TemplateAdd {
    const made = new TemplateAdd(Operation._init(payload, { ...init, kind: "workspace.template_add" }));
    made._reader = readAdded;
    return made;
  }

  /** The space it's added to, once it's there. */
  get workspaceId(): string | null {
    return str(this._known("workspace_id"));
  }
  /** The space's #noclick, its welcome post's channel. */
  get channelId(): string | null {
    return str(this._known("channel_id"));
  }
}

/** @internal A template's address (a URL), or one of your repos holding a space.json (a `Repo`, its id or name). */
export async function templateSource(source: string | ApiObject): Promise<JsonObject> {
  if (typeof source !== "string") return { repo: await refId(source) };
  const trimmed = source.trim();
  if (!trimmed) throw new TypeError("source is a template's address, or one of your repos (a Repo, its id or its name)");
  return trimmed.includes("://") || trimmed.includes("/") ? { url: trimmed } : { repo: trimmed };
}

/** @internal */
export async function templateBody(source: string | ApiObject, options: TemplateOptions, more: JsonObject = {}): Promise<JsonObject> {
  return compact({
    source: await templateSource(source), leave_out: options.leaveOut?.length ? options.leaveOut.map((p) => compact({ ...p })) : undefined,
    cap_usd_per_month: options.capUsdPerMonth, connections: options.connections, secrets: options.secrets,
    app_secrets: options.appSecrets, dry_run: options.dryRun ? true : undefined, ...more,
  });
}

/** An agent a listed template adds: its job, the channels it works in, and (a page's read) its instructions. */
export interface ListedAgent {
  name: string;
  role: string | null;
  harness: string;
  channels: string[];
  instructions: string | null;
}

/** One of a listed template's own screenshots, drawn in NoClick's `laptop` or `phone` frame. */
export interface ListedPicture {
  url: string;
  caption: string | null;
  frame: "laptop" | "phone";
}

const names = (list: unknown) => asList(list).map(String);

/**
 * A space template in NoClick's gallery, as its card and page show it: who you get (`agents`, each with its job and
 * the channels it works in), what it adds, what it asks for (`connections` by integration, `secrets` by name), what it
 * costs (`estimate`: its app and data stores a month, at cost; `budget`: where its agents stop), its `pictures` and
 * the `address` it's added from. Listed only once NoClick reviewed it; read with no key. A page's read (`get`) also
 * carries each agent's instructions, the example `conversations` and the `repository` it comes from.
 *
 *     const templates = await TemplateListing.list();
 *     const plan = await Workspace.fromTemplate(templates[0].address, { dryRun: true });
 */
export class TemplateListing {
  readonly slug: string;
  readonly name: string;
  readonly description: string | null;
  /** The job it's filed under: `marketing`, `sales`, `support`, `operations`, `engineering` or `personal`. */
  readonly job: string | null;
  /** Its address, which `Workspace.fromTemplate` and `addTemplate` take. */
  readonly address: string;
  readonly byNoClick: boolean;
  readonly agents: ListedAgent[];
  readonly channels: { name: string; topic: string | null; members: string[]; schedules: string[] }[];
  readonly skills: { name: string; description: string; lines: string[] }[];
  readonly memories: { name: string; description: string | null; entries: { name: string; description: string }[] }[];
  readonly automations: { name: string; description: string | null; steps: { type: string; label: string | null }[] }[];
  readonly stores: { kind: string; name: string }[];
  readonly app: { path: string; runtime: string | null; framework: string | null } | null;
  readonly connections: { integration: string; label: string; nodeType: string | null; usedBy: string[] }[];
  readonly secrets: { name: string; description: string | null; usedBy: string[] }[];
  readonly budget: { usdPerMonth: number | null; agents: { name: string; usdPerMonth: number | null }[] };
  readonly estimate: { monthlyUsd: number; lines: { kind: string; name: string | null; label: string | null; usd: number }[] };
  readonly pictures: ListedPicture[];
  readonly conversations: { channel: string; messages: { from: string; text: string }[] }[];
  readonly repository: { name: string; commit: string } | null;
  readonly raw: JsonObject;

  /** @internal */
  constructor(raw: JsonObject) {
    const asks = asObject(raw.asks);
    const budget = asObject(raw.budget);
    const estimate = asObject(raw.estimate);
    const app = raw.app ? asObject(raw.app) : null;
    const repository = raw.repository ? asObject(raw.repository) : null;
    const each = <T>(list: unknown, read: (o: JsonObject) => T): T[] => asList(list).map((x) => read(asObject(x)));
    this.slug = String(raw.slug);
    this.name = String(raw.name);
    this.description = str(raw.description);
    this.job = str(raw.job);
    this.address = String(raw.address);
    this.byNoClick = raw.by_noclick === true;
    this.agents = each(raw.agents, (a) => ({
      name: String(a.name), role: str(a.role), harness: str(a.harness) ?? "sdk", channels: names(a.channels), instructions: str(a.instructions),
    }));
    this.channels = each(raw.channels, (c) => ({ name: String(c.name), topic: str(c.topic), members: names(c.members), schedules: names(c.schedules) }));
    this.skills = each(raw.skills, (s) => ({ name: String(s.name), description: str(s.description) ?? "", lines: names(s.lines) }));
    this.memories = each(raw.memories, (m) => ({
      name: String(m.name), description: str(m.description), entries: each(m.entries, (e) => ({ name: String(e.name), description: str(e.description) ?? "" })),
    }));
    this.automations = each(raw.automations, (a) => ({
      name: String(a.name), description: str(a.description), steps: each(a.steps, (s) => ({ type: String(s.type), label: str(s.label) })),
    }));
    this.stores = each(raw.stores, (s) => ({ kind: String(s.kind), name: String(s.name) }));
    this.app = app ? { path: String(app.path), runtime: str(app.runtime), framework: str(app.framework) } : null;
    this.connections = each(asks.connections, (c) => ({
      integration: String(c.integration), label: str(c.label) ?? String(c.integration), nodeType: str(c.node_type), usedBy: names(c.for),
    }));
    this.secrets = each(asks.secrets, (s) => ({ name: String(s.name), description: str(s.description), usedBy: names(s.for) }));
    this.budget = { usdPerMonth: num(budget.usd_per_month) ?? null, agents: each(budget.agents, (a) => ({ name: String(a.name), usdPerMonth: num(a.usd_per_month) ?? null })) };
    this.estimate = { monthlyUsd: num(estimate.monthly_usd) ?? 0, lines: each(estimate.lines, (l) => ({ kind: String(l.kind), name: str(l.name), label: str(l.label), usd: num(l.usd) ?? 0 })) };
    this.pictures = each(raw.pictures, (p) => ({ url: String(p.url), caption: str(p.caption), frame: p.frame === "phone" ? "phone" : "laptop" }));
    this.conversations = each(raw.conversations, (c) => ({
      channel: String(c.channel), messages: each(c.messages, (m) => ({ from: String(m.from), text: String(m.text) })),
    }));
    this.repository = repository ? { name: String(repository.name), commit: String(repository.commit) } : null;
    this.raw = raw;
  }

  /** Every template in NoClick's gallery, NoClick's own first, each as its card shows it. Needs no key (a client that
   *  holds one sends it, which the gallery ignores). */
  static async list(options: { client?: NoClick } = {}): Promise<TemplateListing[]> {
    const client = resolveClient(options.client);
    const raw = asObject(await client.request("GET", "/v1/public/templates", { user: null, anonymous: !client.apiKey }));
    return asList(raw.data).map((item) => new TemplateListing(asObject(item)));
  }

  /** One template in the gallery by its `slug`, as its page shows it; `NotFound` for one that isn't listed. Needs no key. */
  static async get(slug: string, options: { client?: NoClick } = {}): Promise<TemplateListing> {
    const client = resolveClient(options.client);
    const path = `/v1/public/templates/${encodeURIComponent(slug)}`;
    return new TemplateListing(asObject(await client.request("GET", path, { user: null, anonymous: !client.apiKey })));
  }
}

/** @internal A dry run's `TemplatePlan`, else the `TemplateAdd` doing it. */
export function templateAnswer(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): TemplatePlan | TemplateAdd {
  return raw.object === "space_template_plan" ? toTemplatePlan(raw) : TemplateAdd._fromResponse(raw.operation, init);
}
