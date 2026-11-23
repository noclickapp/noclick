/**
 * Deploy a repository as a new app in one call: a public one on any git host, or one of your own repos.
 *
 * `deploy` copies the repository (or takes your repo as it is), makes the app, sets the secrets it reads, gives it
 * the key to your account it asks for (or has the deploy ask the account's owner), and deploys production. Ask with
 * `dryRun: true` first to see what it would do, what it would cost a month and what it asks of you, nothing made.
 *
 *     const plan = await deploy("https://github.com/acme/console", { dryRun: true });
 *     console.log(plan.runtime, `$${plan.estimate.monthlyUsd.toFixed(2)} a month`, plan.missingSecrets);
 *
 *     const done = await (await deploy("https://github.com/acme/console", {
 *       secrets: { STRIPE_SECRET_KEY: "sk_live_..." },
 *     })).wait();
 *     console.log(done.url);
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { Estimate } from "./estimate.ts";
import { asList, asObject, compact, refId, str } from "./object.ts";
import type { ApiObject, CallOptions, JsonObject, ObjectInit } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import { resolveScope } from "./scope.ts";
import type { UserOption } from "./scope.ts";

/** What `deploy` takes besides its source. */
export interface DeployOptions extends CallOptions {
  /** A branch, tag or full commit sha to deploy (the repository's default branch when omitted). */
  ref?: string;
  /** The app's name (and its copy's); omitted, the repository's own, or the first of name-2, name-3... free. */
  name?: string;
  /** Values for the secrets the repository's noclick.json asks you to set, by name. Write-only. */
  secrets?: Record<string, string>;
  /**
   * Give the app the key to your account it asks for, as part of the deploy: exactly its scopes, as the dry run
   * names them. Only you signed in, or a key holding `keys:create`; otherwise leave it out and the deploy asks the
   * account's owner.
   */
  accountKey?: string[];
  /** The most the key may spend in a calendar month (none of its own unless set). */
  keySpendCapUsdPerMonth?: number;
  /** Answer what it would do, with nothing made (only reading the repository is charged, its seconds). */
  dryRun?: boolean;
}

/** A secret the repository's noclick.json says its code reads. */
export interface DeploySecret {
  name: string;
  /** What NoClick makes for it (`secret` or `password`); null for one you set. */
  generate: string | null;
  /** What it is, in the repository's words. */
  description: string | null;
  /** For one you set: whether a deploy without it is refused. One NoClick makes is always there. */
  required: boolean;
  /** For one you set: whether the call brought its value. */
  given: boolean;
  /** For one NoClick makes: whether it's a password you read once (`app.secrets.reveal`). */
  shownOnce: boolean;
}

/** The key to your account the repository asks for, as you're shown it before you agree. */
export interface DeployKeyAsk {
  scopes: string[];
  /** What the key can do, a line per scope (`scope`, `can`, `reads_secrets`). */
  can: JsonObject[];
  /** What no app's key can do, whatever it holds. */
  cannot: string[];
  /** That whoever can change the app's code acts with the key. */
  note: string;
  /** `you`: you give it in the call (send `accountKey` with these scopes); `deploy`: the deploy asks for it. */
  givenBy: "you" | "deploy";
  /** When the deploy asks: `asks_owner`, `given` or `denied`, as the account's `app_key` approval setting decides. */
  atDeploy: string | null;
}

function toSecrets(raw: JsonObject): DeploySecret[] {
  const made = asList(raw.generated).map((s) => asObject(s)).map((s) => ({
    name: String(s.name), generate: str(s.kind), description: str(s.description), required: true, given: false,
    shownOnce: s.shown_once === true,
  }));
  const asked = asList(raw.asked).map((s) => asObject(s)).map((s) => ({
    name: String(s.name), generate: null, description: str(s.description), required: s.required === true,
    given: s.given === true, shownOnce: false,
  }));
  return [...made, ...asked];
}

function toKeyAsk(value: unknown): DeployKeyAsk | null {
  if (!value) return null;
  const raw = asObject(value);
  return {
    scopes: asList(raw.scopes).map(String), can: asList(raw.can).map((line) => asObject(line)),
    cannot: asList(raw.cannot).map(String), note: str(raw.note) ?? "",
    givenBy: raw.given_by === "you" ? "you" : "deploy", atDeploy: str(raw.at_deploy),
  };
}

/** What a deploy would do, with nothing made: `deploy(source, { dryRun: true })`. */
export class DeployPlan {
  /** What it read: `kind` (`url` or `repo`), the `url` or `repo_id`, and the `commit` and `branch`. */
  readonly source: JsonObject;
  /** The app's name (and its copy's): the one you gave, or the first free one from the repository's. */
  readonly name: string;
  /** Where the app would run (`edge` or `container`); null when it won't run as it stands. */
  readonly runtime: string | null;
  readonly framework: string | null;
  readonly reason: string | null;
  /** Whether the repository has a noclick.json. */
  readonly noclickJson: boolean;
  readonly accountKey: DeployKeyAsk | null;
  readonly secrets: DeploySecret[];
  /** The secrets you set that the call would have to bring: a deploy without them is refused. */
  readonly missingSecrets: string[];
  /** Why it won't deploy as it stands (`message`, `next_step`); null when it will. */
  readonly refused: JsonObject | null;
  /** What it would cost a month, priced for your account (usage-based: what's charged is what's used). */
  readonly estimate: Estimate;
  /** Whether your account can pay to run it now (`ok`); if not, the `refusal` a deploy would meet. */
  readonly funds: JsonObject;
  /** What it makes: `repo` (a copy) and `project` (the app). */
  readonly makes: string[];
  readonly raw: JsonObject;

  /** @internal */
  constructor(raw: JsonObject) {
    this.source = asObject(raw.source);
    this.name = String(raw.name);
    this.runtime = str(raw.runtime);
    this.framework = str(raw.framework);
    this.reason = str(raw.reason);
    this.noclickJson = raw.noclick_json === true;
    this.accountKey = toKeyAsk(raw.account_key);
    this.secrets = toSecrets(asObject(raw.secrets));
    this.missingSecrets = asList(raw.missing_secrets).map(String);
    this.refused = raw.refused ? asObject(raw.refused) : null;
    this.estimate = new Estimate(asObject(raw.estimate));
    this.funds = asObject(raw.funds);
    this.makes = asList(raw.makes).map(String);
    this.raw = raw;
  }
}

/** A deploy that ended live: what `RepoDeploy.wait()` resolves to. */
export interface DeployResult {
  projectId: string;
  name: string;
  /** Where production serves it. */
  url: string | null;
  repoId: string | null;
  deploymentId: string | null;
  commit: string | null;
  /** Where its key to the account stands (`status`: `granted`, `waiting` for the owner...); null if it asks none. */
  accountKey: JsonObject | null;
  /** The passwords NoClick made that nobody has read yet: read each once with `app.secrets.reveal(name)`. */
  toReveal: string[];
  raw: JsonObject;
}

const readDeploy = (result: unknown): DeployResult => {
  const raw = asObject(result);
  const waiting = asList(asObject(raw.secrets).to_reveal).map((w) => String(asObject(w).name));
  return {
    projectId: String(raw.project_id), name: String(raw.name), url: str(raw.url), repoId: str(raw.repo_id),
    deploymentId: str(raw.deployment_id), commit: str(raw.commit),
    accountKey: raw.account_key ? asObject(raw.account_key) : null, toReveal: waiting, raw,
  };
};

registerResult("repo.deploy", readDeploy);

/**
 * A repository being deployed as a new app: the operation `deploy` returns. `wait()` resolves to a `DeployResult`
 * once it's live; `progress` shows each stage (copying, making the app, setting its secrets and key, building and
 * deploying). A deploy that fails after the copy keeps the app and its repo, and its error says how to go on.
 */
export class RepoDeploy extends Operation<DeployResult> {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _fromResponse(payload: unknown, init: { client?: NoClick; user?: UserOption }): RepoDeploy {
    const made = new RepoDeploy(Operation._init(payload, { ...init, kind: "repo.deploy" }));
    made._reader = readDeploy;
    return made;
  }

  /** The new app's id, once it's made. */
  get projectId(): string | null {
    return str(this._known("project_id"));
  }
  /** The repo it deploys: the copy, or yours. */
  get repoId(): string | null {
    return str(this._known("repo_id"));
  }
  /** The production deployment, once it's started. */
  get deploymentId(): string | null {
    return str(this._known("deployment_id"));
  }
}

async function sourceOf(source: string | ApiObject, ref: string | undefined): Promise<JsonObject> {
  if (typeof source !== "string") return compact({ repo: await refId(source), ref });
  const trimmed = source.trim();
  if (!trimmed) throw new TypeError("source is a repository's URL, or one of your repos (a Repo, its id or its name)");
  const isUrl = trimmed.includes("://") || trimmed.includes("@");
  return compact(isUrl ? { url: trimmed, ref } : { repo: trimmed, ref });
}

/**
 * Deploy `source` as a new app of yours: a public git repository's https URL, on any host (copied into a new repo
 * of yours, the one branch it deploys), or one of your own repos (a `Repo`, its id or its name, deployed as it is).
 *
 * It makes the app, sets the secrets its noclick.json says its code reads (NoClick makes the ones marked
 * `generate`; `secrets` brings the rest), gives the app the key to your account it asks for when `accountKey` names
 * exactly its scopes (only you signed in, or a key holding `keys:create`; otherwise the deploy asks the account's
 * owner), and deploys production. Never a private repository, a URL with a login, an `ssh://` or `git@` address, or
 * another account's repo: push a private one to a repo of yours with git and deploy that. What can't deploy is
 * refused before anything is made. Needs the `apps` and `repos` scopes.
 *
 * Resolves to a `RepoDeploy` whose `wait()` gives the live app (`url`, where its key stands, passwords to read once);
 * with `dryRun: true`, to a `DeployPlan` of what it would do, what it would cost and what it asks of you.
 *
 *     const plan = await deploy("https://gitlab.com/acme/tools/console", { dryRun: true });
 *     for (const line of plan.accountKey?.can ?? []) console.log("its key can", line.can);
 *     const done = await (await deploy("https://gitlab.com/acme/tools/console", {
 *       secrets: { STRIPE_SECRET_KEY: "sk_live_..." },
 *     })).wait();
 *     const app = Project.fromId(done.projectId);
 *     for (const name of done.toReveal) console.log(name, await app.secrets.reveal(name));
 */
export async function deploy(source: string | ApiObject, options: DeployOptions & { dryRun: true }): Promise<DeployPlan>;
export async function deploy(source: string | ApiObject, options?: DeployOptions & { dryRun?: false }): Promise<RepoDeploy>;
export async function deploy(source: string | ApiObject, options: DeployOptions = {}): Promise<DeployPlan | RepoDeploy> {
  const user = resolveScope(options.user);
  const json: JsonObject = compact({
    source: await sourceOf(source, options.ref), name: options.name, secrets: options.secrets,
    account_key: options.accountKey
      ? compact({ scopes: [...options.accountKey], spend_cap_usd_per_month: options.keySpendCapUsdPerMonth })
      : undefined,
    dry_run: options.dryRun ? true : undefined,
  });
  const raw = asObject(await resolveClient(options.client).request("POST", "/v1/deploys", { json, user }));
  if (options.dryRun) return new DeployPlan(raw);
  return RepoDeploy._fromResponse(raw.operation, { client: options.client, user });
}
