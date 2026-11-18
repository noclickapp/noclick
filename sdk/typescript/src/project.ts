/**
 * Projects: a repo deployed to a URL, with what the running app needs. A deploy of the
 * production branch goes live at `project.url`; any other branch gets a preview URL of its own.
 * Bindings, secrets and schedules apply from the next deployment.
 *
 * Inside the running app, `Project.current()` is the app itself, signed in by its deployment (no
 * key in the app's code), and the whole client acts as a key of the app's user: `app.database("DB")`
 * reaches what it's bound to, `Agent.fromName(..., { createIfMissing: true })` makes what it needs,
 * `app.ai` and `app.agent("SUPPORT")` think and talk as the app, and `app.verifyRequest(...)` checks
 * a request from its schedules or subscriptions. What the app spends counts toward its `budgetUsdPerMonth`
 * ($10 unless set) and its user's cap.
 */

import { Agent } from "./agent.ts";
import { toVersions, versionId } from "./versions.ts";
import type { Version } from "./versions.ts";
import { AI } from "./ai.ts";
import type { AIChatMessage, AIChatOptions, AIModel, AIModelKind, ChatReply, Embeddings, GeneratedImage, Transcript } from "./ai.ts";
import { ProjectEmail, ProjectPayments, ProjectSignIn } from "./appServices.ts";
import { Bucket } from "./bucket.ts";
import { Subscription } from "./channel.ts";
import { DEPLOYMENT_TOKEN_ENV, NoClick, appClient, env, resolveClient } from "./client.ts";
import { Connection } from "./connection.ts";
import { Cron } from "./cron.ts";
import { Database } from "./database.ts";
import { Dict } from "./dict.ts";
import { Domain } from "./domain.ts";
import { Conflict, InvalidRequest, NotFound, Unauthenticated } from "./errors.ts";
import { toExportBundle } from "./export.ts";
import type { ExportBundle } from "./export.ts";
import { ProjectLive } from "./live.ts";
import {
  ApiObject, asList, asObject, compact, createNamed, defined, givesFields, isoTime, listAll, listPage, num, paginate, parseTime, readScope,
  refId, requiredNumber, str,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import type { RegionName } from "./region.ts";
import { Operation, registerResult } from "./operation.ts";
import { Queue } from "./queue.ts";
import { Repo } from "./repo.ts";
import { Secret } from "./secret.ts";
import { resolveScope } from "./scope.ts";
import type { UserOption } from "./scope.ts";
import { trashed } from "./trash.ts";
import type { TrashItem } from "./trash.ts";
import { OnEvent } from "./trigger.ts";
import { verifySignature } from "./webhook.ts";
import type { WebhookHeaders } from "./webhook.ts";

/** What NoClick sets in every deployment's environment: its credential, and the key its scheduled requests are signed with. */
export { DEPLOYMENT_TOKEN_ENV };
export const SIGNING_SECRET_ENV = "NOCLICK_SIGNING_SECRET";

export type DeploymentStatus = "queued" | "building" | "ready" | "failed" | "canceled";
/** Whose secrets a deployment is built with: the production branch's, or every other branch's. */
export type DeploymentEnvironment = "production" | "preview";
/** Where a secret applies: production deployments, previews, or both. */
export type SecretEnvironment = DeploymentEnvironment | "all";
/**
 * `auto` runs each deployment where its commit says; `edge` runs a JavaScript framework (or files) in
 * isolates; `container` runs any server, in any language.
 */
export type ProjectRuntime = "auto" | "edge" | "container";
/** Where one deployment runs. */
export type DeploymentRuntime = "edge" | "container";
/** What a push to an app's repo deploys by itself. */
export type DeployOnPush = "off" | "production" | "all";
/** `branch`: each preview branch gets its own copy of what its code names; `shared`: previews use production's. */
export type PreviewResources = "branch" | "shared";
/** Where an app's pages carry NoClick's badge. */
export type BadgeCorner = "bottom-right" | "bottom-left" | "top-right" | "top-left";
export type BindingKind = "database" | "bucket" | "connection" | "dict" | "queue" | "secret" | "agent";

/** A resource the running app reads by `name`. */
export interface Binding {
  name: string;
  kind: BindingKind;
  resourceId: string;
  resourceName: string | null;
  /**
   * The variables the app's code reads it as from its next deployment: its `name`, or for a secret
   * each of its keys under the key's own name (`name` only lists it).
   */
  variables: string[];
  createdAt: Date | null;
  raw: JsonObject;
}

/**
 * One line an app printed, or its build did. A line written while serving also names its
 * `environment` and the request it was written in (`requestId`, shared by that request's lines);
 * the host's own line for a request carries the `status` it answered (0 when it never did).
 */
export interface LogLine {
  at: Date | null;
  level: "info" | "warn" | "error";
  message: string;
  deploymentId: string | null;
  environment: "production" | "preview" | null;
  requestId: string | null;
  status: number | null;
  raw: JsonObject;
}

/** The lines a log read returns, oldest first: an array of `LogLine`, with how long a line can take to show. */
export interface LogLines extends Array<LogLine> {
  /**
   * Up to how many seconds a line takes to show after a request writes it (the host's logs lag its requests): a
   * read that's empty, or misses a request just made, may only be early. Null for a build's log, kept whole as
   * it's written.
   */
  delayS: number | null;
}

/**
 * What a plain request for `path` must answer, as a check path: `status` (else any below 400), and with `json`
 * a JSON body. No browser loads it, so it has no screenshot.
 */
export interface CheckRequest {
  path: string;
  status?: number;
  json?: boolean;
}

/**
 * A path a check asks: a page's path (`/pricing`), loaded in a browser, or what a plain request for a path must
 * answer (`{ path: "/api/health", status: 200 }`). A page the app's files serve never runs its code: name the
 * code's routes as requests.
 */
export type CheckPath = string | CheckRequest;

/** A cookie a check sets on the deployment's own address, httpOnly, before its pages load. */
export interface CheckCookie {
  name: string;
  value: string;
  /** `/` unless given; a request entry is sent the cookies whose path covers it. */
  path?: string;
}

/** What a check asks beside its paths. */
export interface DeploymentCheckOptions {
  /**
   * Have a model look at the screenshots too, in one call billed at its price: `brief` says what the site is for
   * (who it's for and the idea it's built on), `facts` the owner's own words about the business, and `rubric`
   * `app` judges screens people use (their task, forms, states, density, tap targets) instead of a site people
   * read (`site`, the default). The result's `review` has the scores and issues.
   */
  review?: { brief: string; facts?: string; rubric?: "site" | "app" };
  /**
   * A CSS selector each page waits for after it loads, up to 20 seconds, before it's judged and screenshotted:
   * for a page its scripts draw (a sign-in check, then the screen). A page it never shows on fails.
   */
  waitFor?: string;
  /** How long each page is watched before its screenshot, its console errors until then counting: 1,000 unless given, at most 10,000. */
  settleMs?: number;
  /**
   * Headers sent with each request to the deployment's own address, never to another site (an `Authorization`
   * header, to check pages behind a sign-in). Secret: sealed until the check runs, then dropped.
   */
  headers?: Record<string, string>;
  /** Cookies set on the deployment's own address (a session, to check pages behind a sign-in). Secret, as `headers`. */
  cookies?: CheckCookie[];
}

/** What an app spent this month so far, against its budget. */
export interface ProjectUsage {
  requests: number;
  cpuMs: number;
  /** Everything the app spent: hosting, builds, its calls to what it's bound to, its email, its AI and its agent turns. */
  usd: number;
  periodStart: Date | null;
  /** Its `budgetUsdPerMonth` (null without one). */
  budgetUsd: number | null;
  /** What refuses its paid calls now: its own budget, its user's cap or your account's balance; null while they go through. */
  limitedBy: "project" | "user" | "account" | null;
  /** `usd` split by the spend types of `Usage.series({ groupBy: "type" })`: `apps`, `ai`, `model_tokens`, ... */
  byType: Record<string, number>;
  raw: JsonObject;
}

/** An error a page's console showed: `exception` (uncaught), `console` (`console.error`) or `browser` (a file that failed to load, ...). */
export interface ConsoleError {
  kind: "exception" | "console" | "browser";
  message: string;
}

/**
 * One path a check asked: a page, loaded in a browser, or a request entry, asked with a plain request (`expected`
 * says what it had to answer). `ok` is false when a page answered 400 or more, didn't load within 30 seconds, a
 * script threw and nothing caught it, what the check waits for never showed, or a picture it shows doesn't
 * (`brokenImages`), and when a request entry answered other than it asks (`problem` says which); other console
 * errors are reported without failing it.
 */
export interface PathCheck {
  path: string;
  /** Where it ended up. */
  url: string;
  ok: boolean;
  problem: string | null;
  status: number | null;
  /** From the navigation to the load event, or to a request's answer (null when it didn't load or answer in time). */
  loadMs: number | null;
  title: string | null;
  consoleErrors: ConsoleError[];
  /**
   * The screenshot, an account file the chat shows: `{ id, name, url, mime_type, ... }` (null when the page couldn't
   * be opened, and for a request entry).
   */
  screenshot: JsonObject | null;
  /**
   * The pictures the page shows that a browser can't (a missing file, or text committed in an image's place), each
   * the site's own path (its URL when it's elsewhere); any fails the path.
   */
  brokenImages: string[];
  /** Each address the page shows (a `mailto:` link or its text) whose domain takes no mail (no MX record), reported without failing it. */
  undeliverableEmails: string[];
  /** A request entry's `{ status, json }`, as far as it asks them (`{}`: any status below 400); null for a page. */
  expected: { status?: number; json?: boolean } | null;
  raw: JsonObject;
}

/**
 * What a model made of a check's screenshots (`check(paths, { review })`), against NoClick's design rubric for a
 * site or an app: each criterion's score from 1 to 5 (under 4 a defect), the issues to fix, most important first,
 * and of a site the `claims` its pages make that neither its brief nor the owner's words give. `passed` is true
 * when every score is 4 or more; a review that couldn't answer has its `error` instead, and leaves the check as it
 * was.
 */
export interface CheckReview {
  /** The model that looked. */
  model: string;
  /** Null when the review couldn't answer (`error` says why). */
  passed: boolean | null;
  /**
   * Each criterion's score, 1-5: a site's `belongs`, `first_screen`, `type`, `colour`, `images`, `phone`, `finish`
   * and `generated`; an app's `task`, `forms`, `states`, `density`, `touch`, `type`, `navigation` and `finish`.
   */
  scores: Record<string, number>;
  /** Each `{ where, what, fix }`, the most important first. */
  issues: { where: string; what: string; fix: string }[];
  /**
   * A site's facts on its pages (a name, number, price, hour, quote) that neither the brief nor the owner's words
   * give, each `{ where, what }`: listed, never scored. Empty for an app.
   */
  claims: { where: string; what: string }[];
  error: string | null;
  /** What the model's call cost, counted in the check's `costUsd` too. */
  costUsd: number;
  raw: JsonObject;
}

/** What `Deployment.check()` saw where the deployment serves (`url`): `passed` when every path did. */
export interface DeploymentCheck {
  deploymentId: string;
  url: string;
  passed: boolean;
  paths: PathCheck[];
  checkedAt: Date | null;
  /** What it cost: the browser at its provider's price, by the second, and the review's model call. */
  costUsd: number;
  /** The review of its screenshots, when the check asked for one (`review`). */
  review: CheckReview | null;
  /**
   * Set when every path passed but the release's static files answered each of them, so the app's server code
   * never ran: a broken API behind a working home page passes such a check. Name a route its code answers as a
   * request entry (`{ path: "/api/health", status: 200 }`) to check the code too.
   */
  codeUnchecked: string | null;
  raw: JsonObject;
}

/** One route's requests: how many, how many failed, and their times in milliseconds. */
export interface RouteTiming {
  method: string;
  path: string;
  requests: number;
  errors: number;
  p50Ms: number;
  p95Ms: number;
  maxMs: number;
}

/**
 * How the requests a deployment served between `since` and `until` went. `errors` counts answers
 * of 500 or more and requests never answered (`"none"` in `byStatus`); `sampled` is true when there
 * were more than the 2,000 newest it read, or the record of a very busy app is a sample, each request
 * in it counted for the ones it stands for.
 */
export interface RequestOutcomes {
  requests: number;
  errors: number;
  errorRate: number | null;
  byStatus: Record<string, number>;
  slowestRoutes: RouteTiming[];
  sampled: boolean;
  since: Date | null;
  until: Date | null;
  raw: JsonObject;
}

/** One hour or day of an app's traffic: the requests from `at` on, and how many of them failed. */
export interface TrafficInterval {
  at: Date | null;
  requests: number;
  errors: number;
}

/**
 * One of an app's busiest paths: its requests, how many failed, their 95th-percentile time in milliseconds, and how
 * many of them a browser made (`browserRequests`).
 */
export interface PathTraffic {
  path: string;
  requests: number;
  errors: number;
  p95Ms: number | null;
  browserRequests: number;
}

export type AnalyticsPeriod = "24h" | "7d" | "30d";

/**
 * How an app's traffic went over a `period`, from `since` up to `until`: the `requests` its sites
 * answered and the `errors` among them (an answer of 500 or more, or none) with their `errorRate`,
 * `byStatus` (`{ "200": 1180, "404": 21, none: 1 }`), how long answers took to begin (`p50Ms`,
 * `p95Ms`), each `interval`'s (`hour` or `day`, starting in `tz`) in `series`, the busiest
 * `topPaths`, and the same length of time just before `since` (`previousRequests`,
 * `previousErrors`). Counted from NoClick's record of every request, its files and API calls
 * included: requests, not visitors. `bySource` says who made them as their user agents say: `browser`
 * (a person's browser, or a program that says it's one) and `automated` (curl, an HTTP library, a
 * headless browser, a crawler), and `unknown` for any recorded before NoClick told them apart.
 * NoClick's own checks of the app are in no figure but `noclickRequests`. `sampled`: a very busy app's
 * record is a sample, each request in it counted for the ones it stands for.
 */
export interface ProjectAnalytics {
  period: AnalyticsPeriod;
  environment: NonNullable<ProjectAnalyticsOptions["environment"]>;
  interval: "hour" | "day";
  tz: string;
  since: Date | null;
  until: Date | null;
  requests: number;
  errors: number;
  errorRate: number | null;
  byStatus: Record<string, number>;
  p50Ms: number | null;
  p95Ms: number | null;
  series: TrafficInterval[];
  topPaths: PathTraffic[];
  previousRequests: number;
  previousErrors: number;
  sampled: boolean;
  bySource: Record<string, number>;
  noclickRequests: number;
  raw: JsonObject;
}

function toProjectAnalytics(value: unknown): ProjectAnalytics {
  const raw = asObject(value);
  return {
    period: (str(raw.period) ?? "7d") as AnalyticsPeriod,
    environment: (str(raw.environment) ?? "production") as ProjectAnalytics["environment"],
    interval: raw.interval === "hour" ? "hour" : "day",
    tz: str(raw.tz) ?? "UTC", since: parseTime(raw.since), until: parseTime(raw.until),
    requests: num(raw.requests) ?? 0, errors: num(raw.errors) ?? 0, errorRate: num(raw.error_rate),
    byStatus: asObject(raw.by_status) as Record<string, number>, p50Ms: num(raw.p50_ms), p95Ms: num(raw.p95_ms),
    series: asList(raw.series).map((value) => {
      const r = asObject(value);
      return { at: parseTime(r.at), requests: num(r.requests) ?? 0, errors: num(r.errors) ?? 0 };
    }),
    topPaths: asList(raw.top_paths).map((value) => {
      const r = asObject(value);
      return {
        path: str(r.path) ?? "", requests: num(r.requests) ?? 0, errors: num(r.errors) ?? 0, p95Ms: num(r.p95_ms),
        browserRequests: num(r.browser_requests) ?? 0,
      };
    }),
    previousRequests: num(raw.previous_requests) ?? 0, previousErrors: num(raw.previous_errors) ?? 0,
    sampled: raw.sampled === true, bySource: asObject(raw.by_source) as Record<string, number>,
    noclickRequests: num(raw.noclick_requests) ?? 0, raw,
  };
}

/**
 * One app's requests to its production site over a summary's period, how many failed and how many a
 * browser made; NoClick's own checks of it are in none of them but `noclickRequests`.
 */
export interface AppRequests {
  projectId: string;
  requests: number;
  errors: number;
  browserRequests: number;
  noclickRequests: number;
}

/**
 * Every app's requests over a `period` (from `since` up to `until`, days starting in `tz`), read at
 * once: `apps` newest first, an app nobody reached at 0. Requests, not visitors, NoClick's own checks
 * left out. `sampled`: a very busy app's record is a sample, each request in it counted for the ones it
 * stands for.
 */
export interface AnalyticsSummary {
  period: AnalyticsPeriod;
  tz: string;
  since: Date | null;
  until: Date | null;
  apps: AppRequests[];
  sampled: boolean;
  raw: JsonObject;
  /** One app's line (a `Project` or its id); one the summary didn't cover reads as 0. */
  of(app: Project | string): AppRequests;
}

function toAnalyticsSummary(value: unknown): AnalyticsSummary {
  const raw = asObject(value);
  const apps = asList(raw.data).map((value) => {
    const r = asObject(value);
    return {
      projectId: str(r.project_id) ?? "", requests: num(r.requests) ?? 0, errors: num(r.errors) ?? 0,
      browserRequests: num(r.browser_requests) ?? 0, noclickRequests: num(r.noclick_requests) ?? 0,
    };
  });
  return {
    period: (str(raw.period) ?? "7d") as AnalyticsPeriod, tz: str(raw.tz) ?? "UTC", since: parseTime(raw.since), until: parseTime(raw.until),
    apps, sampled: raw.sampled === true, raw,
    of(app: Project | string): AppRequests {
      const projectId = typeof app === "string" ? app : app.id;
      return apps.find((a) => a.projectId === projectId)
        ?? { projectId, requests: 0, errors: 0, browserRequests: 0, noclickRequests: 0 };
    },
  };
}

function toPathCheck(value: unknown): PathCheck {
  const raw = asObject(value);
  return {
    path: str(raw.path) ?? "", url: str(raw.url) ?? "", ok: raw.ok === true, problem: str(raw.problem),
    status: num(raw.status), loadMs: num(raw.load_ms), title: str(raw.title),
    consoleErrors: asList(raw.console_errors).map((e) => asObject(e) as unknown as ConsoleError),
    screenshot: raw.screenshot ? asObject(raw.screenshot) : null,
    brokenImages: (raw.broken_images as string[] | undefined) ?? [],
    undeliverableEmails: (raw.undeliverable_emails as string[] | undefined) ?? [],
    expected: raw.expected ? (asObject(raw.expected) as PathCheck["expected"]) : null, raw,
  };
}

function toCheckReview(value: unknown): CheckReview {
  const raw = asObject(value);
  return {
    model: str(raw.model) ?? "", passed: typeof raw.passed === "boolean" ? raw.passed : null,
    scores: asObject(raw.scores) as Record<string, number>,
    issues: (raw.issues as CheckReview["issues"] | undefined) ?? [],
    claims: (raw.claims as CheckReview["claims"] | undefined) ?? [],
    error: str(raw.error), costUsd: num(raw.cost_usd) ?? 0, raw,
  };
}

function toDeploymentCheck(value: unknown): DeploymentCheck {
  const raw = asObject(value);
  return {
    deploymentId: str(raw.deployment_id) ?? "", url: str(raw.url) ?? "", passed: raw.passed === true,
    paths: asList(raw.paths).map(toPathCheck), checkedAt: parseTime(raw.checked_at), costUsd: num(raw.cost_usd) ?? 0,
    review: raw.review ? toCheckReview(raw.review) : null, codeUnchecked: str(raw.code_unchecked), raw,
  };
}

function toRequestOutcomes(value: unknown): RequestOutcomes {
  const raw = asObject(value);
  return {
    requests: num(raw.requests) ?? 0, errors: num(raw.errors) ?? 0, errorRate: num(raw.error_rate),
    byStatus: asObject(raw.by_status) as Record<string, number>,
    slowestRoutes: asList(raw.slowest_routes).map((value) => {
      const r = asObject(value);
      return {
        method: str(r.method) ?? "", path: str(r.path) ?? "", requests: num(r.requests) ?? 0, errors: num(r.errors) ?? 0,
        p50Ms: num(r.p50_ms) ?? 0, p95Ms: num(r.p95_ms) ?? 0, maxMs: num(r.max_ms) ?? 0,
      };
    }),
    sampled: raw.sampled === true, since: parseTime(raw.since), until: parseTime(raw.until), raw,
  };
}

function toBinding(value: unknown): Binding {
  const raw = asObject(value);
  return {
    name: str(raw.name) ?? "",
    kind: raw.kind as BindingKind,
    resourceId: str(raw.resource_id) ?? "",
    resourceName: str(raw.resource_name),
    variables: Array.isArray(raw.variables) ? raw.variables.map(String) : [],
    createdAt: parseTime(raw.created_at),
    raw,
  };
}

/** A log read's lines, with the read's `delay_s`. */
function toLogLines(value: unknown): LogLines {
  return Object.assign(asList(value).map(toLogLine), { delayS: num(asObject(value).delay_s) });
}

function toLogLine(value: unknown): LogLine {
  const raw = asObject(value);
  const level = raw.level === "warn" || raw.level === "error" ? raw.level : "info";
  const environment = raw.environment === "production" || raw.environment === "preview" ? raw.environment : null;
  return {
    at: parseTime(raw.at), level, message: str(raw.message) ?? "", deploymentId: str(raw.deployment_id), environment,
    requestId: str(raw.request_id), status: num(raw.status), raw,
  };
}

// --- deployments ---------------------------------------------------------------

const readDeployment = (result: unknown, op: Operation<unknown>): Deployment =>
  Deployment._fromRaw(asObject(result), { client: op._client, user: op._scope });

registerResult("project.deploy", readDeployment);
registerResult("deployment.promote", readDeployment);
registerResult("deployment.check", toDeploymentCheck);
registerResult("project.export", toExportBundle);

/**
 * One build of a project at one commit. `status` goes `queued`, `building`, then `ready`
 * (serving at `url`), `failed` (`error` says why) or `canceled`. `production` is true for the one
 * serving the project's own URL.
 */
export class Deployment extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal From a deployment view another call returned. */
  static _fromRaw(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): Deployment {
    return new Deployment({ raw, client: init.client, user: init.user });
  }

  static fromId(deploymentId: string, options: CallOptions = {}): Deployment {
    return new Deployment({ hints: { id: deploymentId }, client: options.client, user: options.user });
  }

  static async get(deploymentId: string, options: CallOptions = {}): Promise<Deployment> {
    return await Deployment.fromId(deploymentId, options).hydrate();
  }

  get id(): string {
    return this._field("id");
  }
  get projectId(): string {
    return this._field("project_id");
  }
  get branch(): string {
    return this._field("branch");
  }
  /** The sha it was built from. */
  get commit(): string | null {
    return this._field("commit");
  }
  get commitMessage(): string | null {
    return this._field("commit_message");
  }
  get status(): DeploymentStatus {
    return this._field("status");
  }
  /** Where this deployment serves (a preview URL unless it's production). */
  get url(): string | null {
    return this._field("url");
  }
  get production(): boolean {
    return this._field("production") === true;
  }
  /**
   * `production` for a deploy of the production branch, `preview` for any other: whose secrets it
   * was built with. A promoted preview keeps `preview` and serves with production's secrets.
   */
  get environment(): DeploymentEnvironment {
    return this._field("environment");
  }
  /** `deploy` (a `deploy()`, or promoting a retired one) or `push` (the app deploys on push). */
  get startedBy(): "deploy" | "push" {
    return this._field("started_by");
  }
  /** Why the build failed, or why a push couldn't deploy, in one line (null unless `failed`). */
  get error(): string | null {
    return this._field("error");
  }
  /** Where it runs: `edge` or `container`, chosen when its build starts (null until then). */
  get runtime(): DeploymentRuntime | null {
    return this._field("runtime");
  }
  /** Why it runs there, in words: the app's pinned runtime, or what its commit has ("a Dockerfile describes its server"). */
  get runtimeReason(): string | null {
    return this._field("runtime_reason");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  get readyAt(): Date | null {
    return parseTime(this._field("ready_at"));
  }
  /**
   * Its latest check, in short: `{ operation_id, passed, url, checked_at, paths: [{ path, ok, status, problem }] }`,
   * with `code_unchecked` when its code never ran (null before its first). The check's operation has the whole of
   * it; a promote's check is kept here too.
   */
  get lastCheck(): JsonObject | null {
    return this._field("check") ?? null;
  }
  /**
   * Each URL it answers now: production's (the app's URL) and its branch's preview URL, each null when it doesn't
   * serve there. A promoted preview serves both, while its `environment` stays the one it was built for.
   */
  get serves(): { production: string | null; preview: string | null } | null {
    return this._field("serves") ?? null;
  }
  /**
   * On the deployment a deploy's `wait()` gives: it went live, but a page answered 500 or more, one of the app's
   * `checkPaths` answered other than it asks, or nothing answered, with the error the app logged then. It stays live
   * (nothing is rolled back): read the app's runtime log, fix the cause and deploy again. Null when everything asked
   * answered as asked, and on a deployment read later.
   */
  get warning(): string | null {
    return this._field("warning") ?? null;
  }
  /**
   * On the deployment a deploy's `wait()` gives: its static files answered every path asked, so its server code
   * never ran, and a broken API would pass unseen. Add a route its code answers to the app's `checkPaths` as a
   * request entry (`{ path: "/api/health", status: 200 }`). Null otherwise.
   */
  get codeUnchecked(): string | null {
    return this._field("code_unchecked") ?? null;
  }
  /**
   * On the deployment a preview's deploy gives, when the app's `previewResources` is `branch`: what the preview
   * writes to (its own copies of what its code reaches, made at its first write), when the copies go to the trash,
   * and that promoting never carries them to production. Null for production, and for an app whose previews use
   * production's resources.
   */
  get previewData(): string | null {
    return this._field("preview_data") ?? null;
  }

  private get path(): string {
    return `/v1/deployments/${this._known("id")}`;
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", this.path);
  }

  /**
   * Its build output (`kind: "build"`, the default) or what it printed while serving (`"runtime"`), oldest first:
   * every line, or the last `limit`. Of runtime lines, `level` keeps `warn` or `error` lines only and
   * `environment` one environment's (a promoted preview writes in both); a request's lines are never cut apart,
   * and `delayS` says how long a line can take to show.
   *
   * ```ts
   * const tail = await preview.logs({ kind: "runtime", level: "error", environment: "preview", limit: 20 });
   * for (const line of tail) console.log(line.requestId, line.status, line.message);
   * if (!tail.length) console.log(`Nothing yet: a line takes up to ${tail.delayS}s to show.`);
   * ```
   */
  async logs(
    options: { kind?: "build" | "runtime"; limit?: number; level?: "warn" | "error"; environment?: DeploymentEnvironment } = {},
  ): Promise<LogLines> {
    return toLogLines(await this._request("GET", `${this.path}/logs`, {
      query: { kind: options.kind ?? "build", limit: options.limit, level: options.level, environment: options.environment },
    }));
  }

  /** Stop a deployment that's still `queued` or `building`; one that already finished is left as it is. */
  async cancel(): Promise<this> {
    const raw = asObject(await this._request("POST", `${this.path}/cancel`));
    if (raw.id) this._raw = raw;
    return this;
  }

  /**
   * Check up to 10 `paths` of this `ready` deployment where it serves (its preview URL, or the app's URL in
   * production), one after another. A path given as a string is a page, loaded in a browser: its HTTP status,
   * load time, console errors and a screenshot kept as a file the chat shows. One given as
   * `{ path: "/api/health", status: 200 }` is what a plain request for it must answer (that status; else any below
   * 400), with `json: true` for a JSON body: no browser, no screenshot. A page the app's files serve never runs its
   * code, so name the code's routes as requests. Without `paths`, the app's `checkPaths` (else its home page). A
   * deployment no URL serves now can't be checked (`Conflict`). The browser is billed at its provider's price, by
   * the second. `review` has a model look at the screenshots too; `waitFor`, `settleMs`, `headers` and `cookies`
   * check a page its scripts draw, or one behind a sign-in (`DeploymentCheckOptions`). `wait()` resolves to a
   * `DeploymentCheck`.
   *
   * ```ts
   * const checked = await (await preview.check(["/", "/book"])).wait();
   * for (const page of checked.paths) console.log(page.path, page.status, page.problem, page.screenshot?.url);
   *
   * const reviewed = await (await preview.check(
   *   ["/", { path: "/api/bookings", status: 200, json: true }],
   *   { review: { brief: "A booking page for Le Comptoir, a bistro in Lyon" } },
   * )).wait();
   * console.log(reviewed.passed, reviewed.codeUnchecked, reviewed.review?.scores);
   * ```
   */
  async check(paths?: CheckPath[], options: DeploymentCheckOptions = {}): Promise<Operation<DeploymentCheck>> {
    const json = compact({
      paths, review: options.review, wait_for: options.waitFor, settle_ms: options.settleMs, headers: options.headers,
      cookies: options.cookies,
    });
    const payload = await this._request("POST", `${this.path}/check`, Object.keys(json).length ? { json } : {});
    return Operation._fromPayload<DeploymentCheck>(payload, {
      client: this._client, user: this._callScope(), kind: "deployment.check", reader: toDeploymentCheck,
    });
  }

  /**
   * How the requests this deployment served went since `since` (the last 24 hours when omitted, at
   * most 7 days back): how many, by status, the error rate and the slowest routes, from what its
   * host recorded of each request.
   */
  async requests(options: { since?: Date | string } = {}): Promise<RequestOutcomes> {
    return toRequestOutcomes(await this._request("GET", `${this.path}/requests`, {
      query: { since: isoTime(options.since) },
    }));
  }

  /**
   * Make this `ready` deployment the production one; its URL starts serving this build within a
   * minute. A preview is released again with production's secrets, without a build. Instant
   * rollback covers the app's last 10 production deployments, and each branch's newest preview for
   * 30 days; promoting an older one builds its commit again (a `project.deploy` operation). `wait()`
   * resolves to the deployment now `production`.
   *
   * An app with `checkPaths` checks the deployment first and doesn't promote one that fails (the
   * operation fails with the check in its error; production keeps serving); `force: true` promotes
   * it without the check. The databases the app binds are bookmarked first: undoing the promote
   * (`Operation.undo()`) puts them back as they were, with the release before.
   */
  async promote(options: { force?: boolean } = {}): Promise<Operation<Deployment>> {
    const payload = await this._request("POST", `${this.path}/promote`, options.force ? { json: { force: true } } : {});
    return Operation._fromPayload<Deployment>(payload, {
      client: this._client, user: this._callScope(), kind: "deployment.promote", reader: readDeployment,
    });
  }
}

// --- schedules -----------------------------------------------------------------

/**
 * A project's cron job: NoClick POSTs `path` on the app on every tick of `cron` (read in `tz`).
 * When 5 runs in a row fail the same way over at least 30 minutes it pauses itself (`pausedReason`
 * says why) until `resume()`.
 */
export class Schedule extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _fromRaw(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): Schedule {
    return new Schedule({ raw, client: init.client, user: init.user });
  }

  static fromId(scheduleId: string, options: CallOptions = {}): Schedule {
    return new Schedule({ hints: { id: scheduleId }, client: options.client, user: options.user });
  }

  static async get(scheduleId: string, options: CallOptions = {}): Promise<Schedule> {
    return await Schedule.fromId(scheduleId, options).hydrate();
  }

  get id(): string {
    return this._field("id");
  }
  get projectId(): string {
    return this._field("project_id");
  }
  /** What keys it within the project (the path unless you named it). */
  get name(): string {
    return this._field("name");
  }
  /** The five-field cron expression. */
  get cron(): string {
    return this._field("cron");
  }
  get tz(): string {
    return this._field("tz");
  }
  get path(): string {
    return this._field("path");
  }
  get status(): "active" | "paused" {
    return this._field("status");
  }
  get pausedReason(): string | null {
    return this._field("paused_reason");
  }
  get nextRun(): Date | null {
    return parseTime(this._field("next_run"));
  }
  get lastRun(): Date | null {
    return parseTime(this._field("last_run"));
  }
  /** `succeeded` (a 2xx answer) or `failed`; null before the first run. */
  get lastStatus(): "succeeded" | "failed" | null {
    return this._field("last_status");
  }
  /** Why the last run failed, in one line (`Answered 500.`); null after a success. */
  get lastError(): string | null {
    return this._field("last_error");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  private get base(): string {
    return `/v1/schedules/${this._known("id")}`;
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", this.base);
  }

  private async act(verb: string): Promise<this> {
    const raw = asObject(await this._request("POST", `${this.base}/${verb}`));
    if (raw.id) this._raw = raw;
    return this;
  }

  /** Stop firing until `resume()`. */
  async pause(): Promise<this> {
    return await this.act("pause");
  }

  /** Fire again from the next tick, clearing `pausedReason`. */
  async resume(): Promise<this> {
    return await this.act("resume");
  }

  /** Call its path once now and wait for the answer (at most 30 seconds); a paused schedule stays paused. */
  async runNow(): Promise<this> {
    return await this.act("run");
  }

  async delete(): Promise<void> {
    await this._request("DELETE", this.base);
  }
}

// --- Durable Objects -------------------------------------------------------------

/** One object of a Durable Object class, as its host lists it. What it stores is reached only by the app's own code. */
export interface DurableObjectInstance {
  id: string;
  hasStoredData: boolean;
}

/**
 * One of an app's Durable Object classes in one environment (production's, or a preview branch's): its `name`, the
 * `binding` its code reaches it by, how many objects it has (`objectsMore` when there were more than were counted) and
 * what they store (`storedBytes`, the latest the host reported; null when it couldn't be read). `status` is `trashed`
 * while it's in the trash, `parked` while no release that serves exports it (a live edit's release that never went
 * live added it), and `stopped` while its environment's objects are stopped (`stoppedFor`: the app in the trash, or
 * past its hard spending limit), their data kept.
 */
export class DurableObjectClass extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _fromRaw(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): DurableObjectClass {
    return new DurableObjectClass({ raw, client: init.client, user: init.user });
  }

  get id(): string {
    return this._field("id");
  }
  get projectId(): string {
    return this._field("project_id");
  }
  get name(): string {
    return this._field("name");
  }
  /** The name the app's code reaches it by (`env.ROOM`). */
  get binding(): string | null {
    return this._field("binding");
  }
  get environment(): "production" | "preview" {
    return this._field("environment");
  }
  /** A preview's branch; null in production. */
  get branch(): string | null {
    return this._field("branch");
  }
  get status(): "live" | "trashed" | "parked" | "stopped" {
    return this._field("status");
  }
  /** Why its objects are stopped (`trash`, or `budget`: the app past its hard spending limit); null when they run. */
  get stoppedFor(): "trash" | "budget" | null {
    return this._field("stopped_for") ?? null;
  }
  /** How many objects it has; null when the host couldn't say. */
  get objectsCount(): number | null {
    return this._field("objects");
  }
  get objectsMore(): boolean {
    return Boolean(this._field("objects_more"));
  }
  get storedBytes(): number | null {
    return this._field("stored_bytes");
  }
  get addedByDeploymentId(): string | null {
    return this._field("added_by_deployment_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  get parkedAt(): Date | null {
    return parseTime(this._field("parked_at"));
  }
  get trashedAt(): Date | null {
    return parseTime(this._field("trashed_at"));
  }
  /** Its entry in the trash while it's there. */
  get trashId(): string | null {
    return this._field("trash_id");
  }
  get restorableUntil(): Date | null {
    return parseTime(this._field("restorable_until"));
  }

  private get base(): string {
    return `/v1/projects/${this._known("project_id")}/durable_objects/${this._known("id")}`;
  }

  protected async _load(): Promise<JsonObject> {
    const listed = asObject(await this._request("GET", `/v1/projects/${this._known("project_id")}/durable_objects`));
    const found = asList(listed.data).map(asObject).find((row) => row.id === this._known("id"));
    if (!found) throw new NotFound("The app has no such Durable Object class.", { nextStep: "List them with app.durableObjects()." });
    return found;
  }

  /** A page of its objects, as the host lists them; pass `nextCursor` back as `cursor` for the next. */
  async objects(options: PageOptions = {}): Promise<Page<DurableObjectInstance>> {
    const query: Record<string, string | number> = { limit: options.limit ?? 100 };
    if (options.cursor) query.cursor = options.cursor;
    const found = asObject(await this._request("GET", `${this.base}/objects`, { query }));
    return {
      data: asList(found.data).map(asObject).map((row) => ({ id: String(row.id), hasStoredData: Boolean(row.has_stored_data) })),
      nextCursor: (found.next_cursor as string | null | undefined) ?? null,
    };
  }

  /**
   * Move the class to the trash for 30 days: its objects and their data are kept, and every request and alarm reaching
   * it is refused meanwhile. From code, an agent or an MCP connection it's held for the account's owner
   * (`ApprovalRequired`). Restore it from the trash to have it back; a release that deletes the class
   * (`deleted_classes`) deploys once it's there.
   */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", this.base), this);
  }
}

/**
 * An app's classes; `unread` names a figure the host couldn't report this time (`stored_bytes` or `objects`), and
 * `cost` what the app's Durable Objects were charged this month (every environment's together; null with no classes).
 */
export interface DurableObjectClasses extends Array<DurableObjectClass> {
  unread: string[];
  cost: { usd: number; periodStart: Date | null } | null;
}

// --- secrets -------------------------------------------------------------------

/**
 * `project.secrets`: values the running app reads from its environment by name, set for production
 * deployments, previews or both. Values are write-only; nothing reads one back. An app's environment
 * holds 128 values in all, NoClick's own and each bound secret's included.
 */
export class ProjectSecrets {
  private readonly project: Project;

  constructor(project: Project) {
    this.project = project;
  }

  private async path(name?: string): Promise<string> {
    return await this.project._projectPath("secrets", ...(name === undefined ? [] : [encodeURIComponent(name)]));
  }

  /**
   * Set `name` to `value` (at most 5 KB), replacing any value it had, for `environment`:
   * `production` (deploys of the production branch, and what's promoted), `preview` (every other
   * branch) or `all` (the default). It reaches the app at the next deployment; keep a larger value in
   * a bound `Secret` or bucket the app reads.
   */
  async set(name: string, value: string, options: { environment?: SecretEnvironment } = {}): Promise<void> {
    await this.project._request("PUT", await this.path(name), { json: { value, ...environmentOf(options) } });
  }

  /** Each secret set for `environment` (`all` by default) and when its value was last set, never the value. */
  async list(options: { environment?: SecretEnvironment } = {}): Promise<Record<string, Date | null>> {
    const page = await this.project._request("GET", await this.path(), { query: environmentOf(options) });
    const out: Record<string, Date | null> = {};
    for (const row of asList(page).map(asObject)) out[String(row.name)] = parseTime(row.updated_at);
    return out;
  }

  /** Delete `name` from `environment` (`all` by default); the app stops seeing it at the next deployment. */
  async delete(name: string, options: { environment?: SecretEnvironment } = {}): Promise<void> {
    await this.project._request("DELETE", await this.path(name), { query: environmentOf(options) });
  }

  /**
   * What `name` held before each change or deletion of the last 30 days, newest first, in
   * `environment` (`all` by default), never the values.
   */
  async versions(name: string, options: { environment?: SecretEnvironment } = {}): Promise<Version[]> {
    return toVersions(await this.project._request("GET", `${await this.path(name)}/versions`, { query: environmentOf(options) }));
  }

  /** Set `name` back to `version`'s value in its environment (deleted since, it's back). */
  async restore(name: string, version: Version | string): Promise<void> {
    await this.project._request("POST", `${await this.path(name)}/versions/${versionId(version)}/restore`);
  }
}

/** A secret's `environment` on the wire: left out for `all`. */
function environmentOf(options: { environment?: SecretEnvironment }): { environment?: DeploymentEnvironment } {
  return options.environment === undefined || options.environment === "all" ? {} : { environment: options.environment };
}

/**
 * `project.settings`: plain values the running app reads from its environment by name, such as a
 * feature flag or a public URL. Unlike secrets they read back and show in the console.
 */
export class ProjectSettings {
  private readonly project: Project;

  constructor(project: Project) {
    this.project = project;
  }

  private async path(name?: string): Promise<string> {
    return await this.project._projectPath("settings", ...(name === undefined ? [] : [encodeURIComponent(name)]));
  }

  /** Set `name` to `value` (at most 4 KB); it reaches the app at the next deployment. */
  async set(name: string, value: string): Promise<void> {
    await this.project._request("PUT", await this.path(name), { json: { value } });
  }

  /** Each setting's name and value. */
  async list(): Promise<Record<string, string>> {
    const page = await this.project._request("GET", await this.path());
    const out: Record<string, string> = {};
    for (const row of asList(page).map(asObject)) out[String(row.name)] = str(row.value) ?? "";
    return out;
  }

  /** Delete `name`; the app stops seeing it at the next deployment. */
  async delete(name: string): Promise<void> {
    await this.project._request("DELETE", await this.path(name));
  }

  /** What `name` held before each change or deletion of the last 30 days, newest first, with each `value`. */
  async versions(name: string): Promise<Version[]> {
    return toVersions(await this.project._request("GET", `${await this.path(name)}/versions`));
  }

  /** Set `name` back to `version`'s value (deleted since, it's back); returns the value it holds again. */
  async restore(name: string, version: Version | string): Promise<string> {
    const raw = asObject(await this.project._request("POST", `${await this.path(name)}/versions/${versionId(version)}/restore`));
    return str(raw.value) ?? "";
  }
}

// --- AI as the app -------------------------------------------------------------

/**
 * `project.ai`: `AI` acting as the app, from the app's own code (`Project.current()`). Every call is
 * billed to your account and attributed to the app and its user: it counts toward the app's
 * `budgetUsdPerMonth` and its user's cap, and throws `SpendCapExceeded` once either is used up
 * (`PaymentRequired` once your account's balance is). Only the app acts as the app: on a project
 * reached with your own key, each call throws `InvalidRequest` (use `AI` there, for the app's user).
 */
export class ProjectAI {
  private readonly project: Project;

  constructor(project: Project) {
    this.project = project;
  }

  private client(): NoClick {
    if (this.project._hints.current !== true) {
      throw new InvalidRequest("app.ai acts as the app, so it runs in the app's own code, from Project.current().", {
        nextStep: "From your own code, call AI with { user: <the app's user> }.",
      });
    }
    return resolveClient(this.project._client);
  }

  /** The OpenAI-compatible endpoint, for an OpenAI client in the app's code; pair it with `headers()`. */
  get baseUrl(): string {
    return `${this.client().baseUrl}/v1/ai`;
  }

  /** `AI.chat` as the app; `model: "agent:<name>"` reaches only an agent bound to the app, in its own conversations. */
  async chat(messages: string | readonly (AIChatMessage | string)[], options: Omit<AIChatOptions, "user" | "client"> = {}): Promise<ChatReply> {
    return await AI.chat(messages, { ...options, user: null, client: this.client() });
  }

  /** `AI.embed` as the app. */
  async embed(texts: string | readonly string[], options: { model?: string; dimensions?: number } = {}): Promise<Embeddings> {
    return await AI.embed(texts, { ...options, user: null, client: this.client() });
  }

  /** `AI.image` as the app. */
  async image(prompt: string, options: { model?: string; size?: string; images?: readonly string[] } = {}): Promise<GeneratedImage> {
    return await AI.image(prompt, { ...options, user: null, client: this.client() });
  }

  /** `AI.transcribe` as the app: an `https` URL to a recording, or its bytes. */
  async transcribe(
    audio: string | Uint8Array | ArrayBuffer | Blob,
    options: { model?: string; language?: string; speakers?: boolean | string[] } = {},
  ): Promise<Transcript> {
    return await AI.transcribe(audio, { ...options, user: null, client: this.client() });
  }

  /** The models the app can call; `kind: "agent"` lists the agents bound to it. */
  async models(options: { kind?: AIModelKind } = {}): Promise<AIModel[]> {
    return await AI.models({ ...options, user: null, client: this.client() });
  }

  /** The deployment's credential as the bearer, for an OpenAI client's `defaultHeaders`: every call is the app's. */
  async headers(): Promise<Record<string, string>> {
    return await AI.headers({ user: null, client: this.client() });
  }
}

// --- the project ---------------------------------------------------------------

export interface ProjectCreateOptions extends CallOptions {
  /** The repo it deploys (a `Repo` or its id); a new, empty repo of the project's name when omitted. */
  repo?: Repo | string;
  /**
   * `auto` (the default) runs each deployment where its commit says: on the edge (a wrangler config
   * naming its entry, a JavaScript framework, or only files: server code in isolates, static files
   * served from everywhere) or in a container that scales to zero (a Dockerfile, or a server in
   * another language: Flask, Django, Go, or a Node server with a `start` script), and the deployment
   * says which and why. `edge` or `container` pins it there whatever the commit has.
   */
  runtime?: ProjectRuntime;
  /**
   * On `edge`: `nextjs`, `remix`, `astro`, `vite` or `static`; on `container`: `python`, `node` or
   * `docker` (the repo's own Dockerfile); under `auto` either, which names its runtime. Detected from
   * the repo at each build when omitted.
   */
  framework?: string;
  /** The branch whose deploys go live; the repo's default branch when omitted. */
  productionBranch?: string;
  /**
   * The most the app may spend in a calendar month, in US dollars: hosting and builds, its calls to
   * what it's bound to, its email, its AI and its agent turns. Every app gets one: $10 unless you
   * pass another (an agent making a site sets one that fits it). At it the app's paid calls stop and
   * its pages keep serving; at twice it its pages pause. In `fromName`, `null` removes it.
   */
  budgetUsdPerMonth?: number | null;
  /**
   * The region its server code is placed near (`regions()`), for good: put it with the database it
   * binds, so its queries stay short. Omitted, your account's default region, else `us-east`; its
   * static files are served from everywhere. It says where the code runs, not where data stays (that's
   * the database's and bucket's region). An existing app elsewhere makes `fromName` throw `Conflict`
   * naming its `region`.
   */
  region?: RegionName;
  /**
   * What a push deploys by itself: `off` (the default: only `deploy()` deploys), `production` (a push
   * to the production branch deploys it) or `all` (a push to any other branch deploys a preview too).
   */
  deployOnPush?: DeployOnPush;
  /**
   * `branch` (the default): each preview branch gets its own copy of every database, bucket, dict and queue its
   * code reaches, made at its first write, so a preview never changes production's data; `shared`: previews use
   * production's.
   */
  previewResources?: PreviewResources;
  /**
   * Up to 10: what a deploy of code asks once it's live, what a promote checks and what `Deployment.check()` asks
   * when it names none. Each a page's path (`/pricing`), loaded in a browser, or what a plain request for a path
   * must answer (`{ path: "/api/health", status: 200 }`, with `json: true` for a JSON body).
   */
  checkPaths?: CheckPath[];
}

export interface ProjectLogsOptions {
  /** The first `limit` lines after this time; the last `limit` lines when omitted. */
  since?: Date | string;
  level?: "warn" | "error";
  /** One deployment's lines (a `Deployment` or its id). */
  deployment?: Deployment | string;
  /** 100 by default, at most 1,000. A request's lines are never cut apart. */
  limit?: number;
  /** One environment's lines; both when omitted. */
  environment?: "production" | "preview";
}

export interface ProjectAnalyticsOptions {
  /** `7d` by default. */
  period?: AnalyticsPeriod;
  /** Its production site (the default), its previews, or both. */
  environment?: "production" | "preview" | "all";
  /** The IANA time zone its hours and days start in (`Europe/Paris`); UTC when omitted. */
  tz?: string;
}

/** What `fromName` sets on an existing project. */
const CONVERGED = [
  "repo_id",
  "runtime",
  "framework",
  "production_branch",
  "budget_usd_per_month",
  "region",
  "deploy_on_push",
  "preview_resources",
  "check_paths",
] as const;

async function wireBody(name: string, options: ProjectCreateOptions): Promise<JsonObject> {
  return {
    ...compact({
      name,
      repo_id: await refId(options.repo),
      runtime: options.runtime,
      framework: options.framework,
      production_branch: options.productionBranch,
      region: options.region,
      deploy_on_push: options.deployOnPush,
      preview_resources: options.previewResources,
      check_paths: options.checkPaths,
    }),
    ...defined({ budget_usd_per_month: options.budgetUsdPerMonth }), // null: only an app NoClick publishes has none
  };
}

/** What an app can be given, by kind. */
export type Bindable = Database | Bucket | Connection | Dict | Queue | Secret | Agent;

function bindingKind(resource: Bindable): BindingKind {
  if (resource instanceof Database) return "database";
  if (resource instanceof Bucket) return "bucket";
  if (resource instanceof Connection) return "connection";
  if (resource instanceof Dict) return "dict";
  if (resource instanceof Queue) return "queue";
  if (resource instanceof Secret) return "secret";
  if (resource instanceof Agent) return "agent";
  throw new TypeError("Bind a Database, Bucket, Connection, Dict, Queue, Secret or Agent.");
}

const article = (kind: string) => (/^[aeiou]/.test(kind) ? `an ${kind}` : `a ${kind}`);

/**
 * An app: a repo deployed to a URL. `Project.fromName("booking", { repo, createIfMissing: true })`
 * is lazy; `project.deploy()` builds and ships it.
 */
export class Project extends ApiObject {
  private _createWith: { name: string; options: ProjectCreateOptions } | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create a project (unique per user; a duplicate throws `Conflict` with `existingId`, or with
   * `allowExisting: true` returns the project already there, as it is) that deploys `repo`, or a new,
   * empty repo of the same name when omitted. Nothing is deployed until `deploy()`.
   *
   * ```ts
   * const app = await Project.create("booking", {
   *   repo, previewResources: "branch", checkPaths: ["/", { path: "/api/health", status: 200 }],
   * });
   * ```
   */
  static async create(name: string, options: ProjectCreateOptions & AllowExisting = {}): Promise<Project> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/projects", await wireBody(name, options), {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new Project({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the project called `name` for the current (or given) user. Given fields, it gets
   * the project and sets the ones you pass, on every run: an existing project whose repo, runtime,
   * framework, production branch, budget, `deployOnPush`, `previewResources` or `checkPaths` differ gets
   * yours (one you leave out is never changed). `createIfMissing` creates it when there's none; without
   * it, a missing project throws `NotFound`. Its `region` is fixed: an existing app in another throws `Conflict` naming it. Each run with
   * fields is a write: set them in a setup script or at deploy, and take the bare `fromName` in the app's
   * handlers.
   */
  static fromName(name: string, options: ProjectCreateOptions & { createIfMissing?: boolean } = {}): Project {
    const project = new Project({ hints: { name }, client: options.client, user: options.user });
    project._creates = Boolean(options.createIfMissing);
    if (project._creates || givesFields(options)) project._createWith = { name, options };
    return project;
  }

  /**
   * The app this code runs in, from inside a deployment. NoClick puts the deployment's own
   * credential in its environment (`NOCLICK_DEPLOYMENT_TOKEN`), so the app's code holds no key, and
   * the whole client (`Agent`, `Database`, `AI`, ...) acts as a key of the app's user, attributed to
   * the app. What its code makes or buys (a phone number, a domain) is the app's own; its user's other
   * resources it reads and uses but never changes or deletes (on one bound to the app, it may clear its
   * data); it never reaches another app, another user or what another app's code made, and never mints
   * keys, sets a cap or budget, changes policy, answers approvals, accepts terms for a person or reads
   * secrets' values (`PermissionDenied`). What it spends, buys (each renewal too) and starts that bills
   * later (its numbers' calls and texts, its automations, MCP servers, channels, machines and cards)
   * counts toward the app's budget: a purchase must fit what's left of it, and one in a person's name
   * throws `ApprovalRequired` until they approve it. The app's code decides who may make it do what:
   * policy doesn't judge its calls. Outside a deployment it throws `Unauthenticated`; pass `client` to
   * act with a key of your own instead.
   */
  static current(options: { client?: NoClick } = {}): Project {
    return new Project({ hints: { current: true }, client: options.client ?? appClient(), user: null });
  }

  static fromId(projectId: string, options: CallOptions = {}): Project {
    return new Project({ hints: { id: projectId }, client: options.client, user: options.user });
  }

  static async get(projectId: string, options: CallOptions = {}): Promise<Project> {
    return await Project.fromId(projectId, options).hydrate();
  }

  /** The current user's projects (the account's own outside `asUser`, or those `userFilter` covers). */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<Project[]> {
    return await listAll({ ...options, path: "/v1/projects" }, (raw, user) => new Project({ raw, client: options.client, user }));
  }

  /**
   * Every app's requests over the last `period` (`7d` by default) and how many failed, in one read
   * however many apps there are: each production site's, over the same window `analytics` reads, its
   * days starting in `tz` (UTC when omitted). Which apps: the current user's, or those `userFilter`
   * covers, as `list`. Requests, not visitors.
   */
  static async analyticsSummary(options: ReadOptions & { period?: AnalyticsPeriod; tz?: string } = {}): Promise<AnalyticsSummary> {
    const { user, userId } = await readScope(options);
    return toAnalyticsSummary(await resolveClient(options.client).request("GET", "/v1/projects/analytics/summary", {
      query: { period: options.period ?? "7d", tz: options.tz, user_id: userId },
      user,
    }));
  }

  /** One page of projects; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Project>> {
    return await listPage({ ...options, path: "/v1/projects" }, (raw, user) => new Project({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** Its production URL (`https://<name>.noclick.site` until a domain serves it). */
  get url(): string {
    return this._field("url");
  }
  /** Its own name under NoClick's user-sites domain (`booking.noclick.site`), which never changes (NoClick moves
   * only an app it publishes, when it's renamed where it was published from). */
  get hostname(): string {
    return this._field("hostname");
  }
  /** Null for an app NoClick publishes (`published`). */
  get repoId(): string | null {
    return this._field<string | null>("repo_id");
  }
  /** NoClick publishes its files itself (an automation's interface): it has no repo, and deploys when it's
   * published again from there. */
  get published(): boolean {
    return this._field<boolean | null>("published") ?? false;
  }
  /** The automation it was published from, or null for every other app. */
  get workflow(): { id: string; name: string | null } | null {
    return this._field<{ id: string; name: string | null } | null>("workflow") ?? null;
  }
  get runtime(): ProjectRuntime {
    return this._field("runtime");
  }
  get framework(): string | null {
    return this._field("framework");
  }
  /** The branch whose deploys go live. */
  get productionBranch(): string {
    return this._field("production_branch");
  }
  /** The live hostnames of the domains serving it, oldest first; `domains()` loads the domains. */
  get domainNames(): string[] {
    return this._field<string[] | null>("domain_names") ?? [];
  }
  /** What a push to its repo deploys by itself: `off`, `production` or `all`. */
  get deployOnPush(): DeployOnPush {
    return this._field("deploy_on_push");
  }
  /**
   * `branch`: each preview branch gets its own copy of every resource its code names, made the first
   * time it writes to one (until then it reads production's), so preview data never reaches production;
   * `shared`: previews use production's resources. New apps start with `branch`.
   */
  get previewResources(): PreviewResources {
    return this._field("preview_resources");
  }
  /** The most it may spend in a calendar month, in US dollars: $10 unless its maker set another; null only for an app NoClick publishes. */
  get budgetUsdPerMonth(): number | null {
    return num(this._field("budget_usd_per_month"));
  }
  /**
   * What a `Deployment.check()` asks when it names no paths, what a promote checks where the release serves and then
   * at production's URL, and what a deploy of code asks once it's live: each a page's path, loaded in a browser, or
   * what a plain request for a path must answer (`{ path: "/api/health", status: 200 }`). Empty: promotes aren't
   * checked, and a deploy asks only the home page.
   */
  get checkPaths(): CheckPath[] {
    return (this._field("check_paths") as CheckPath[] | undefined) ?? [];
  }
  /** The region its server code is placed near, fixed when it was created. */
  get region(): RegionName | null {
    return this._field("region");
  }
  /** Whether it's edited live (`app.live`): each edit swaps into the pages its owner has open, and deploys when the session ends. On from its first production release for an app live editing can run. */
  get liveEditing(): boolean {
    return this._field("live_editing") === true;
  }
  /** Who set `liveEditing` last: `owner` (set with `update`, which NoClick never turns back on), `noclick` (its default), or null while nobody has. */
  get liveEditingSetBy(): "owner" | "noclick" | null {
    return this._field("live_editing_set_by") ?? null;
  }
  /** Whether its production pages carry the "Built with NoClick" link: while its paying account's plan keeps NoClick's branding. */
  get badge(): boolean {
    return this._field("badge") === true;
  }
  /** The corner of its pages the badge sits in, where it carries one: `bottom-right` unless set with `update`. */
  get badgeCorner(): BadgeCorner {
    return this._field("badge_corner");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** The deployment serving `url` (null before the first production deploy). */
  get production(): Deployment | null {
    const raw = this._field<JsonObject | null>("production");
    return raw ? Deployment._fromRaw(raw, { client: this._client, user: this._callScope() }) : null;
  }
  /** The repo it deploys from (null for an app NoClick publishes). */
  get repo(): Repo | null {
    const repoId = this.repoId;
    return repoId === null ? null : Repo.fromId(repoId, { client: this._client, user: this._callScope() });
  }
  get secrets(): ProjectSecrets {
    return new ProjectSecrets(this);
  }
  /** Its plain settings: `project.settings.set("PUBLIC_BASE_URL", "...")`. */
  get settings(): ProjectSettings {
    return new ProjectSettings(this);
  }
  get email(): ProjectEmail {
    return new ProjectEmail(this);
  }
  get payments(): ProjectPayments {
    return new ProjectPayments(this);
  }
  get signIn(): ProjectSignIn {
    return new ProjectSignIn(this);
  }
  /** `AI` acting as the app, from its own code: `app.ai.chat(...)`. */
  get ai(): ProjectAI {
    return new ProjectAI(this);
  }
  /** Its live editing session: `app.live.start()`. */
  get live(): ProjectLive {
    return new ProjectLive(this);
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/projects/${id}`);
    if (this._hints.current === true) return await this._request<JsonObject>("GET", "/v1/projects/current");
    const name = String(this._hints.name);
    const page = await this._request("GET", "/v1/projects", { query: { name } });
    const row = (asList(page) as JsonObject[]).find((r) => r.name === name);
    if (row) return await this.converge(row);
    if (!this._createWith || !this._creates) {
      throw new NotFound(`No project is named "${name}".`, {
        nextStep: "Create it with Project.create(...) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/projects", { json: await wireBody(name, this._createWith.options) });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/projects/${err.existingId}`));
    }
  }

  /** Set the fields `fromName` was given on an existing project. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    if (!this._createWith) return raw;
    const wanted = await wireBody(this._createWith.name, this._createWith.options);
    const changes: JsonObject = {};
    for (const key of CONVERGED) {
      if (key in wanted && JSON.stringify(raw[key] ?? null) !== JSON.stringify(wanted[key])) changes[key] = wanted[key];
    }
    if (!Object.keys(changes).length) return raw;
    return await this._request<JsonObject>("PATCH", `/v1/projects/${raw.id}`, { json: changes });
  }

  /** @internal */
  async _projectPath(...rest: string[]): Promise<string> {
    return [`/v1/projects/${await refId(this)}`, ...rest].join("/");
  }

  /**
   * Change the `repo` it deploys, its `runtime`, its `framework` (`null`: detected at each build), its
   * `productionBranch`, its `budgetUsdPerMonth` (an app with code always has one: `null` throws `InvalidRequest`), what a push deploys
   * (`deployOnPush`), what deploys, promotes and checks ask (`checkPaths`, up to 10: a page's path, or what a plain
   * request for a path must answer, `{ path: "/api/health", status: 200 }`; `[]` stops checking promotes),
   * whether previews get their own resources (`previewResources`: `branch` or `shared`), whether it's edited live
   * (`liveEditing`, see `app.live`) or the corner its badge sits in (`badgeCorner`: away from a chat's composer or a
   * corner button, say). A new repo, runtime, framework or branch applies from the next deployment
   * (what's live keeps serving where it runs until then), the rest at once; its user's cap still
   * applies either way. A field you leave out is unchanged. Pinning a runtime the app's framework
   * doesn't run on throws `InvalidRequest`: change the framework with it.
   */
  async update(changes: {
    repo?: Repo | string;
    runtime?: ProjectRuntime;
    framework?: string | null;
    productionBranch?: string;
    budgetUsdPerMonth?: number | null;
    deployOnPush?: DeployOnPush;
    previewResources?: PreviewResources;
    checkPaths?: CheckPath[];
    liveEditing?: boolean;
    badgeCorner?: BadgeCorner;
  }): Promise<this> {
    this._raw = await this._request<JsonObject>("PATCH", await this._projectPath(), {
      json: defined({
        repo_id: changes.repo === undefined ? undefined : await refId(changes.repo),
        runtime: changes.runtime,
        framework: changes.framework,
        production_branch: changes.productionBranch,
        budget_usd_per_month: changes.budgetUsdPerMonth,
        deploy_on_push: changes.deployOnPush,
        preview_resources: changes.previewResources,
        check_paths: changes.checkPaths,
        live_editing: changes.liveEditing,
        badge_corner: changes.badgeCorner,
      }),
    });
    return this;
  }

  private get scope(): { client?: NoClick; user: UserOption } {
    return { client: this._client, user: this._callScope() };
  }

  /**
   * Build and deploy `branch` (the production branch when omitted) at its head, or at `commit`.
   * `wait()` resolves to the `ready` `Deployment`; a failed build rejects with `OperationFailed`,
   * whose `details.deployment_id` names the deployment to read the build log of. A release that runs
   * code is asked for its home page and the app's `checkPaths` once it serves: one that answers wrong
   * stays live, and the deployment's `warning` says what answered; `codeUnchecked` says when its static
   * files answered every path, so its code never ran. A preview of an app whose `previewResources` is
   * `branch` says what it writes to in `previewData`.
   */
  async deploy(options: { branch?: string; commit?: string } = {}): Promise<Operation<Deployment>> {
    const payload = await this._request("POST", await this._projectPath("deployments"), {
      json: compact({ branch: options.branch, commit: options.commit }),
    });
    return Operation._fromPayload<Deployment>(payload, { ...this.scope, kind: "project.deploy", reader: readDeployment });
  }

  /** Its deployments, newest first: `limit` of them (20 by default), of every branch or of `branch`. */
  async deployments(options: { branch?: string; limit?: number } = {}): Promise<Deployment[]> {
    const rows = await paginate(this._api, await this._projectPath("deployments"), {
      query: { branch: options.branch },
      user: this._callScope() ?? null,
      limit: options.limit ?? 20,
    });
    return rows.map((raw) => Deployment._fromRaw(raw, this.scope));
  }

  /**
   * Serve an earlier `ready` deployment at `url` again, without rebuilding: one routing change, live
   * within a minute (`to.promote()`). It covers the app's last 10 production deployments; an older one
   * is built again from its commit.
   */
  async rollback(to: Deployment | string): Promise<Operation<Deployment>> {
    const deployment = typeof to === "string" ? Deployment.fromId(to, this.scope) : to;
    return await deployment.promote();
  }

  /**
   * Give the app `resource` under `name`: a `Database`, `Bucket`, `Connection`, `Dict`, `Queue`,
   * `Secret` or `Agent`, or its id with `kind`. Binding a name again replaces what it pointed at; it
   * takes effect at the next deployment. An agent is the app's user's own or one of your account's,
   * and the app talks to it as itself (see `agent`).
   *
   * A `Secret` reaches the app as one variable per key, each under the key's own name, and `name` only
   * lists it. The app's environment holds a name once, so a key that another bound secret holds, or that
   * another binding, the app's own `secrets` or `settings` or NoClick sets, throws `Conflict`; a secret
   * that gains such a key after it's bound fails the next deployment the same way.
   */
  async bind(name: string, resource: Bindable | string, options: { kind?: BindingKind } = {}): Promise<Binding> {
    let kind: BindingKind;
    if (typeof resource === "string") {
      if (!options.kind) throw new TypeError("With a resource id, pass { kind }: 'database', 'bucket', 'connection', 'dict', 'queue', 'secret' or 'agent'.");
      kind = options.kind;
    } else {
      kind = bindingKind(resource);
    }
    const json = { name, kind, id: await refId(resource) };
    return toBinding(await this._request("POST", await this._projectPath("bindings"), { json }));
  }

  /** What the app is given, by name. */
  async bindings(): Promise<Binding[]> {
    return (await paginate(this._api, await this._projectPath("bindings"), { user: this._callScope() ?? null })).map(toBinding);
  }

  /** Take `name` away from the app at the next deployment; the resource itself is kept. */
  async unbind(name: string): Promise<void> {
    await this._request("DELETE", await this._projectPath("bindings", encodeURIComponent(name)));
  }

  private async bound(name: string, kind: BindingKind): Promise<{ id: string; scope: CallOptions }> {
    const binding = toBinding(await this._request("GET", await this._projectPath("bindings", encodeURIComponent(name))));
    if (binding.kind !== kind) {
      throw new InvalidRequest(`${name} is bound to ${article(binding.kind)}, not ${article(kind)}.`, {
        nextStep: `Read it with app.${binding.kind}(${JSON.stringify(name)}).`,
        details: { name, kind: binding.kind },
      });
    }
    return { id: binding.resourceId, scope: this.scope };
  }

  /** The database bound to the app as `name` (from the app's own code, `Project.current()`, or yours). */
  async database(name: string): Promise<Database> {
    const { id, scope } = await this.bound(name, "database");
    return Database.fromId(id, scope);
  }

  /** The bucket bound to the app as `name`. */
  async bucket(name: string): Promise<Bucket> {
    const { id, scope } = await this.bound(name, "bucket");
    return Bucket.fromId(id, scope);
  }

  /** The dict bound to the app as `name`. */
  async dict(name: string): Promise<Dict> {
    const { id, scope } = await this.bound(name, "dict");
    return Dict.fromId(id, scope);
  }

  /** The queue bound to the app as `name`. */
  async queue(name: string): Promise<Queue> {
    const { id, scope } = await this.bound(name, "queue");
    return Queue.fromId(id, scope);
  }

  /** The connection bound to the app as `name`: the app runs its operations as the account that connected it. */
  async connection(name: string): Promise<Connection> {
    const { id, scope } = await this.bound(name, "connection");
    return Connection.fromId(id, scope);
  }

  /**
   * The agent bound to the app as `name`. From the app's own code it acts as the app: `message`,
   * `send` and `ask` start turns in the app's own conversations, and `history` and `conversations`
   * read only those. A key the app passes (`visitor-91c2`) always names a thread of the app's
   * (`app:<app id>:visitor-91c2` to your own key, which reads it; no other app reaches it). The
   * agent's policy still judges its tool calls, and its turns are billed like any turn, attributed to
   * the app. Anything else (`update`, `delete`, its triggers, memory, wake-ups or children) throws
   * `PermissionDenied` from the app, unless its code made the agent. A preview's code talks to it in
   * threads of the preview's own (`app-preview:<app id>:<key>`), its tools answering from a simulated
   * world; no app's code talks to an agent holding the `noclick` tool.
   *
   * ```ts
   * const assistant = await Project.current().agent("ASSISTANT");
   * const reply = await assistant.message(text, { conversation: visitorId });
   * ```
   */
  async agent(name: string): Promise<Agent> {
    const { id, scope } = await this.bound(name, "agent");
    return Agent.fromId(id, scope);
  }

  /**
   * Check that a request to the app came from NoClick (one of its schedules or subscriptions): `payload` is
   * the raw body exactly as it arrived, `headers` its headers. Its `NoClick-Signature` is checked against the app's signing
   * secret, which NoClick sets in the deployment's environment (`NOCLICK_SIGNING_SECRET`); a timestamp
   * more than `toleranceS` (300) from now is refused. Sends nothing; throws `WebhookSignatureError`.
   *
   *     await app.verifyRequest(await request.text(), request.headers);
   */
  async verifyRequest(payload: string | Uint8Array | ArrayBuffer, headers: WebhookHeaders, options: { toleranceS?: number } = {}): Promise<void> {
    const secret = env(SIGNING_SECRET_ENV);
    if (!secret) {
      throw new Unauthenticated(`verifyRequest() runs inside a deployed app, where NoClick sets ${SIGNING_SECRET_ENV}.`, {
        nextStep: "Call it from the app's own code, in a deployment.",
      });
    }
    await verifySignature(payload, headers, secret, options.toleranceS ?? 300);
  }

  /**
   * POST `path` on the app on every tick of `cron`. A schedule is keyed by `name` (the path when
   * omitted), so calling this again with the same one updates it rather than adding another.
   */
  async schedule(cron: Cron, options: { path: string; name?: string }): Promise<Schedule> {
    if (!(cron instanceof Cron)) throw new TypeError("Pass a Cron.");
    // An app's schedule calls a path, so a Cron's `message` (an agent's turn) isn't sent.
    const raw = await this._request<JsonObject>("POST", await this._projectPath("schedules"), {
      json: { cron: cron.expr, tz: cron.tz, ...compact({ path: options.path, name: options.name }) },
    });
    return Schedule._fromRaw(raw, this.scope);
  }

  /**
   * Its Durable Object classes in every environment, production's first, with how many objects each has and what they
   * store; `unread` names a figure the host couldn't report.
   *
   *     for (const room of await Project.fromName("chat").durableObjects()) console.log(room.name, room.objectsCount);
   */
  async durableObjects(): Promise<DurableObjectClasses> {
    const found = asObject(await this._request("GET", await this._projectPath("durable_objects")));
    const out = asList(found.data).map((raw) => DurableObjectClass._fromRaw(asObject(raw), this.scope)) as DurableObjectClasses;
    out.unread = asList(found.unread).map((v) => String(v));
    const cost = found.cost == null ? null : asObject(found.cost);
    out.cost = cost == null ? null : { usd: Number(cost.usd), periodStart: parseTime(cost.period_start as string | null | undefined) };
    return out;
  }

  async schedules(): Promise<Schedule[]> {
    const rows = await paginate(this._api, await this._projectPath("schedules"), { user: this._callScope() ?? null });
    return rows.map((raw) => Schedule._fromRaw(raw, this.scope));
  }

  /**
   * POST each of a connection's app events to `path` on the app, signed as its schedules' calls are, so the app runs
   * its own pipeline with no agent in between. `source` is an `OnEvent` (a connection of the app's own scope, one of
   * its integration's events, its filters). The body is JSON: `{ object: "app_event", id, subscription_id,
   * connection, integration, event, text, thread, data, test, created_at }`, where `data` is the event as the
   * integration sent it, `text` the same in words and `thread` the conversation it belongs to (a WhatsApp chat, a
   * Slack thread). Check it with `verifyRequest`, answer 2xx within 10 seconds (do slow work after answering), and
   * key on `id`: an event the app didn't take is sent again, the same body, for three days. Up to 20 an app; one
   * whose connection isn't connected yet is `error` until it is.
   *
   *     const whatsapp = Connection.fromName("whatsapp", { integration: "whatsapp" });
   *     await Project.current().subscribe(new OnEvent(whatsapp, "receive_message"), { path: "/hooks/whatsapp" });
   */
  async subscribe(source: OnEvent, options: { path: string }): Promise<Subscription> {
    if (!(source instanceof OnEvent)) throw new TypeError("An app subscribes to a connection's app events: pass an OnEvent.");
    if (source.message !== null || source.conversation !== null) {
      throw new TypeError("An app's subscription takes no message or conversation: the app gets the event itself, with its thread.");
    }
    const raw = await this._request<JsonObject>("POST", await this._projectPath("subscriptions"), {
      json: { source: await source.toWire(), path: options.path },
    });
    return Subscription._from(raw, this.scope);
  }

  /** Its subscriptions, oldest first. */
  async subscriptions(): Promise<Subscription[]> {
    const rows = asList(await this._request("GET", await this._projectPath("subscriptions"))) as JsonObject[];
    return rows.map((raw) => Subscription._from(raw, this.scope));
  }

  /**
   * Serve the app at the domain `name` too: pointed at once if bought through NoClick (at its name
   * and `www`), else connected and `pending_dns` until its records are set; each name is live once
   * its certificate is issued. A subdomain of a domain your account holds (`ana.acmebooking.com`)
   * can serve any project, a user's included, from a key acting for the whole account: its record is
   * written under a bought domain, none is needed under one connected with `wildcard` (live within
   * minutes), and `records` lists it otherwise.
   */
  async addDomain(name: string): Promise<Domain> {
    const raw = await this._request<JsonObject>("POST", await this._projectPath("domains"), { json: { name } });
    return Domain._fromRaw(raw, this.scope);
  }

  /** The domains that serve the app. */
  async domains(): Promise<Domain[]> {
    const rows = await paginate(this._api, await this._projectPath("domains"), { user: this._callScope() ?? null });
    return rows.map((raw) => Domain._fromRaw(raw, this.scope));
  }

  /**
   * Stop serving the app at `name` (a bare domain's `www` too). The domain itself is kept: a bought
   * one stays yours, and one connected for the app stays connected until you delete it.
   */
  async removeDomain(name: string): Promise<void> {
    await this._request("DELETE", await this._projectPath("domains", encodeURIComponent(name)));
  }

  /**
   * What the app printed while serving, oldest first; lines are kept 7 days, and take up to `delayS`
   * seconds (about a minute) to show after a request writes them, so an empty read may only be early.
   */
  async logs(options: ProjectLogsOptions = {}): Promise<LogLines> {
    const page = await this._request("GET", await this._projectPath("logs"), {
      query: {
        since: isoTime(options.since),
        level: options.level,
        deployment_id: options.deployment === undefined ? undefined : await refId(options.deployment),
        limit: options.limit ?? 100,
        environment: options.environment,
      },
    });
    return toLogLines(page);
  }

  /**
   * How the app's traffic went over the last `period` (`24h`, `7d` by default, or `30d`): its
   * requests each hour (`24h`) or day, starting in `tz` (an IANA time zone; UTC when omitted), how
   * many failed, the totals against the same length of time before, by status, how long answers
   * took to begin and the busiest paths. `environment`: its production site (the default), its
   * previews (`preview`) or both (`all`). Every request its sites answered counts, its static files
   * and API calls included, people's and bots' alike: requests, not visitors.
   */
  async analytics(options: ProjectAnalyticsOptions = {}): Promise<ProjectAnalytics> {
    return toProjectAnalytics(await this._request("GET", await this._projectPath("analytics"), {
      query: { period: options.period ?? "7d", environment: options.environment ?? "production", tz: options.tz },
    }));
  }

  /**
   * What the app has spent this month, against its budget: everything it cost in `usd`, split
   * `byType`, and `limitedBy`, what refuses its paid calls now.
   */
  async usage(): Promise<ProjectUsage> {
    const raw = asObject(await this._request("GET", await this._projectPath("usage")));
    const byType = asObject(raw.by_type);
    return {
      requests: requiredNumber(raw, "requests"),
      cpuMs: requiredNumber(raw, "cpu_ms"),
      usd: requiredNumber(raw, "usd"),
      periodStart: parseTime(raw.period_start),
      budgetUsd: num(raw.budget_usd),
      limitedBy: (str(raw.limited_by) as ProjectUsage["limitedBy"]) ?? null,
      byType: Object.fromEntries(Object.keys(byType).map((type) => [type, requiredNumber(byType, type)])),
      raw,
    };
  }

  /**
   * Package everything the app is, to run it elsewhere: its code as a git bundle, `apps/<name>.json`
   * with its settings, bindings and secret names (never values), and each database, bucket, dict and
   * queue it binds, each in its own export's format. `wait()` resolves to the `ExportBundle`. To put
   * the code on GitHub, use the repo's `exportToGithub`.
   */
  async export(): Promise<Operation<ExportBundle>> {
    const payload = await this._request("POST", await this._projectPath("export"), { json: {} });
    return Operation._fromPayload<ExportBundle>(payload, { ...this.scope, kind: "project.export", reader: toExportBundle });
  }

  /**
   * Delete the app: it goes offline within seconds and to the trash, restorable for 30 days with everything
   * it had (releases, settings, secrets, bindings, schedules, domains), served again with no build.
   * The repo and bound data are kept unless `deleteData`, which moves the repo to the trash too, with
   * whatever no other app binds. Returns its `TrashItem`.
   */
  async delete(options: { deleteData?: boolean } = {}): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this._projectPath(),
      { query: { delete_data: options.deleteData ? "true" : undefined } }), this);
  }
}
