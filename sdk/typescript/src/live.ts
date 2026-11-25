/**
 * Live editing: an app's site served from a dev server while you edit it, each edit swapping into the pages its
 * owner has open, and deployed when the session ends once its build and check pass. Reached through the app:
 * `app.live`.
 *
 *     const app = Project.fromName("larkspur");
 *     await app.update({ liveEditing: true });
 *     console.log((await app.live.start()).enterUrl);   // open it once to see the site in live mode
 *     await (await app.live.exec("sed -i 's/Score/Points/' src/render.js", { background: true })).wait();
 *     await (await app.live.end()).wait();
 */

import { ProjectService } from "./appServices.ts";
import { asList, asObject, compact, num, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";
import type { AgentReply } from "./agent.ts";
import { Operation, registerResult } from "./operation.ts";

/** How long a call that may wait on the session waits for its answer: the API answers within 100 seconds. */
const REQUEST_MS = 115_000;
const EXEC_DEFAULT_TIMEOUT_S = 90;
const OPEN_STATES = ["warming", "live", "idle", "ending"];

/** `warming` (starting), `live`, `idle` (no page open and no command for a minute), `ending`, `ended` or `failed`. */
export type LiveSessionState = "warming" | "live" | "idle" | "ending" | "ended" | "failed";

/** What Vite did with an edit: swapped it in place, reloaded the page, couldn't compile it, or nothing imports it. */
export type LiveEditOutcome = "hot" | "reload" | "error" | "none";

/**
 * A session's timers, in seconds. A start may only shorten them: `idleGraceS` (60: no page open and no command,
 * before it's `idle`), `idleEndS` (600: idle before it ends), `maxQuietWithViewersS` (14,400: pages open but no
 * command), `maxSessionS` (43,200) and `holdWarmingS` (30: how long a page waits for a starting session before it
 * shows that it's starting).
 */
export interface LiveTimers {
  idleGraceS?: number;
  idleEndS?: number;
  maxQuietWithViewersS?: number;
  maxSessionS?: number;
  holdWarmingS?: number;
}

export interface LiveStartOptions {
  /**
   * Wait for the session to be live, up to 60 seconds, then answer it as it stands: a first start in a place can
   * take a few minutes, so it can still come back `warming`.
   */
  wait?: boolean;
  /** Make the session's copies of the app's data again from production's. */
  refreshData?: boolean;
  /** Shorten the session's timers. */
  limits?: LiveTimers;
}

export interface LiveExecOptions {
  /** Seconds before the command is stopped: 90 by default, at most 90, or 600 with `background`. */
  timeoutS?: number;
  /**
   * Return at once with an `Operation` whose `wait()` resolves to the `LiveExecResult`: it waits for a session
   * that's still starting, then runs the command.
   */
  background?: boolean;
}

/** How a session's edits went so far. */
export interface LiveEditCounts {
  count: number;
  /** Swapped in place. */
  hot: number;
  /** Reloaded the page. */
  reload: number;
  /** Didn't compile. */
  error: number;
  /** The newest edit's sequence number: `app.live.edits({ after })` reads the ones after it. */
  lastSeq: number;
}

/** One resource the app binds that a session's code reaches a copy of, never production's. */
export interface LiveDataCopy {
  /** `database`, `bucket`, `dict` or `queue`. */
  kind: string;
  /** The binding's name. */
  name: string;
  productionId: string;
  /** The copy's id, once the session's first write made it (null until then: it reads production's). */
  copyId: string | null;
  /** Whether the copy starts with production's data. */
  withData: boolean;
  /** What the copy holds, in a sentence. */
  note: string | null;
}

/**
 * An app's live session: its site on a dev server, with its code checked out in `workdir`. `state` goes `warming`
 * (starting; `phase` says where), `live`, `idle`, `ending` (building, checking and deploying what was edited), then
 * `ended` (`release` says how) or `failed` (`error` says why).
 */
export interface LiveSession {
  id: string;
  projectId: string;
  state: LiveSessionState;
  phase: string | null;
  /** `vite` (over its package.json: its own Vite, or NoClick's for files whose package.json builds nothing) or `plain` (NoClick's Vite over a site of only files). */
  mode: "vite" | "plain";
  /** The app's own URL, where the pages open in live mode show the session. */
  url: string | null;
  /** A link that opens the app in live mode, on the session `start()` returns (null otherwise). */
  enterUrl: string | null;
  /** Where the site's code is checked out in the session's container. */
  workdir: string;
  /** The pages open in live mode. */
  viewers: { connected: number; visible: number };
  edits: LiveEditCounts;
  /** What the session's code writes to instead of production's data. */
  data: LiveDataCopy[];
  /** What keeps an edit from swapping in place: `{ ready, mode, reasons: [{ code, detail }] }`. */
  readiness: JsonObject | null;
  /** The session's branch, `noclick-live`: `{ branch, head, pushed, dirty, state, conflict }`. */
  git: JsonObject | null;
  /** The timers in force, when the session reported them. */
  limits: LiveTimers | null;
  startedAt: Date | null;
  liveAt: Date | null;
  endedAt: Date | null;
  /** Why it ended: `api` (`end()`), `idle`, `max_quiet`, `max_session`, `switch_off`, ... */
  endReason: string | null;
  /** `{ code, message }` once it failed, or once its end couldn't deploy. */
  error: JsonObject | null;
  /** How its end went: `{ outcome, deployment_id, script }`, `outcome` `deployed`, `deploy_failed`, `no_changes` or `stopped`. */
  release: JsonObject | null;
  /** Whether the session is still open (`warming`, `live`, `idle` or `ending`). */
  open: boolean;
  raw: JsonObject;
}

/** Whether an app is edited live, whether it can be, and its session. */
export interface LiveStatus {
  /** The app's `liveEditing` switch. */
  enabled: boolean;
  /** Whether the app can be edited live, as far as is known without reading its code. */
  supported: boolean;
  /** Why it can't, when it can't. */
  unsupportedReason: string | null;
  /** Its open session, else its last one (null before its first). */
  session: LiveSession | null;
  /** The agents' conversations editing it. */
  attached: { agentId: string | null; conversation: string | null }[];
  raw: JsonObject;
}

/** Why Vite reloaded the page: `reason` and the imports from the changed file up to the page (`chain`). */
export interface LiveEditReload {
  path: string;
  triggeredBy: string | null;
  reason: "no-boundary" | "html" | "config" | "dependency" | "server-restart" | "other";
  chain: string[];
}

/** Why an edit didn't compile, as Vite's error overlay shows it. */
export interface LiveEditError {
  message: string;
  file?: string;
  loc?: { line: number; column: number };
  plugin?: string;
  frame?: string;
}

/** The pages that applied a swap, and what threw as it ran. */
export interface LiveEditApplied {
  ok: number;
  failed: number;
  errors: string[];
}

/** What Vite did with one batch of changed files in the open pages. */
export interface LiveEdit {
  /** Its sequence number in the session. */
  seq: number;
  files: string[];
  outcome: LiveEditOutcome;
  /** How many pages were open. */
  clients: number;
  reload: LiveEditReload | null;
  error: LiveEditError | null;
  applied: LiveEditApplied | null;
  raw: JsonObject;
}

/** The edits a read returns, oldest first: an array of `LiveEdit`, with where the next read starts. */
export interface LiveEdits extends Array<LiveEdit> {
  /** The sequence number to pass as `after` to read the edits after these. */
  lastSeq: number;
}

/**
 * What a command run in a live session printed and how it exited (a non-zero `exitCode` is a result, not an error),
 * with what Vite did in the open pages with each file it changed.
 */
export interface LiveExecResult {
  stdout: string;
  stderr: string;
  exitCode: number | null;
  /** Whether the command exited 0. */
  ok: boolean;
  /** Whether it ran past its `timeoutS` and was stopped. */
  timedOut: boolean;
  /** How long it ran, in milliseconds. */
  ms: number;
  /** A record per batch of files the command changed; empty when it changed none. */
  vite: LiveEdit[];
  /** Edits made outside the command since the one before, when there were any. */
  earlier: LiveEdit[];
  note: string | null;
  raw: JsonObject;
}

/** A link that opens the app in live mode on whatever device opens it. */
export interface LiveEnterLink {
  url: string;
  /** When the link stops working (2 hours after it was made); it works any number of times until then. */
  expiresAt: Date | null;
  raw: JsonObject;
}

/**
 * How a live session's end went: `deployed` (what was edited serves at the app's URL, as `deploymentId`),
 * `no_changes` (nothing was edited), `stopped` (it ended without deploying) or `aborted` (an edit came in as it
 * ended, and the session is live again). A build or check that failed fails the operation instead.
 */
export interface LiveEnd {
  outcome: "deployed" | "no_changes" | "stopped" | "aborted";
  sessionId: string | null;
  /** The production deployment it released (null unless `deployed`). */
  deploymentId: string | null;
  /** It deployed, but the production branch couldn't be moved to its commit; the next session's start merges it. */
  mainBehind: boolean;
  raw: JsonObject;
}

const TIMERS = [
  ["idleGraceS", "idle_grace_s"], ["idleEndS", "idle_end_s"], ["maxQuietWithViewersS", "max_quiet_with_viewers_s"],
  ["maxSessionS", "max_session_s"], ["holdWarmingS", "hold_warming_s"],
] as const;

function timersWire(timers: LiveTimers | undefined): JsonObject | undefined {
  if (!timers) return undefined;
  const given = compact(Object.fromEntries(TIMERS.map(([name, wire]) => [wire, timers[name]])));
  return Object.keys(given).length ? given : undefined;
}

function toTimers(value: unknown): LiveTimers | null {
  if (!value || typeof value !== "object") return null;
  const raw = asObject(value);
  const timers: LiveTimers = {};
  for (const [name, wire] of TIMERS) if (typeof raw[wire] === "number") timers[name] = raw[wire] as number;
  return timers;
}

function toEditCounts(value: unknown): LiveEditCounts {
  const raw = asObject(value);
  return {
    count: num(raw.count) ?? 0, hot: num(raw.hot) ?? 0, reload: num(raw.reload) ?? 0, error: num(raw.error) ?? 0,
    lastSeq: num(raw.last_seq) ?? 0,
  };
}

function toDataCopy(value: unknown): LiveDataCopy {
  const raw = asObject(value);
  return {
    kind: str(raw.kind) ?? "", name: str(raw.name) ?? "", productionId: str(raw.production_id) ?? "",
    copyId: str(raw.copy_id), withData: raw.with_data === true, note: str(raw.note),
  };
}

const objectOrNull = (value: unknown): JsonObject | null => (value && typeof value === "object" ? asObject(value) : null);

function toSession(value: unknown): LiveSession {
  const raw = asObject(value);
  const viewers = asObject(raw.viewers);
  const state = (str(raw.state) ?? "warming") as LiveSessionState;
  return {
    id: str(raw.id) ?? "", projectId: str(raw.project_id) ?? "", state, phase: str(raw.phase),
    mode: raw.mode === "plain" ? "plain" : "vite", url: str(raw.url), enterUrl: str(raw.enter_url),
    workdir: str(raw.workdir) ?? "/site",
    viewers: { connected: num(viewers.connected) ?? 0, visible: num(viewers.visible) ?? 0 },
    edits: toEditCounts(raw.edits), data: asList(raw.data).map(toDataCopy), readiness: objectOrNull(raw.readiness),
    git: objectOrNull(raw.git), limits: toTimers(raw.limits), startedAt: parseTime(raw.started_at),
    liveAt: parseTime(raw.live_at), endedAt: parseTime(raw.ended_at), endReason: str(raw.end_reason),
    error: objectOrNull(raw.error), release: objectOrNull(raw.release), open: OPEN_STATES.includes(state), raw,
  };
}

function toStatus(value: unknown): LiveStatus {
  const raw = asObject(value);
  return {
    enabled: raw.enabled === true, supported: raw.supported === true, unsupportedReason: str(raw.unsupported_reason),
    session: raw.session ? toSession(raw.session) : null,
    attached: asList(raw.attached).map((row) => {
      const r = asObject(row);
      return { agentId: str(r.agent_id), conversation: str(r.conversation) };
    }),
    raw,
  };
}

function toEdit(value: unknown): LiveEdit {
  const raw = asObject(value);
  return {
    seq: num(raw.seq) ?? 0, files: asList(raw.files).map(String),
    outcome: (str(raw.outcome) ?? "none") as LiveEditOutcome, clients: num(raw.clients) ?? 0,
    reload: objectOrNull(raw.reload) as LiveEditReload | null, error: objectOrNull(raw.error) as LiveEditError | null,
    applied: objectOrNull(raw.applied) as LiveEditApplied | null, raw,
  };
}

function toEdits(value: unknown): LiveEdits {
  return Object.assign(asList(value).map(toEdit), { lastSeq: num(asObject(value).last_seq) ?? 0 });
}

function toExecResult(value: unknown): LiveExecResult {
  const raw = asObject(value);
  const exitCode = num(raw.exit_code);
  return {
    stdout: str(raw.stdout) ?? "", stderr: str(raw.stderr) ?? "", exitCode, ok: exitCode === 0,
    timedOut: raw.timed_out === true, ms: num(raw.ms) ?? 0, vite: asList(raw.vite).map(toEdit),
    earlier: asList(raw.earlier).map(toEdit), note: str(raw.note), raw,
  };
}

function toEnterLink(value: unknown): LiveEnterLink {
  const raw = asObject(value);
  return { url: str(raw.url) ?? "", expiresAt: parseTime(raw.expires_at), raw };
}

function toLiveEnd(value: unknown): LiveEnd {
  const raw = asObject(value);
  return {
    outcome: (str(raw.outcome) ?? "stopped") as LiveEnd["outcome"], sessionId: str(raw.session_id),
    deploymentId: str(raw.deployment_id), mainBehind: raw.main_behind === true, raw,
  };
}

registerResult("project.live_end", toLiveEnd);
registerResult("project.live_exec", toExecResult);

/**
 * `app.live`: edit the app in a live session. The site runs on a Vite dev server with its code checked out at
 * `/site`; each change swaps into the pages its owner has open (a game keeps running, a form keeps what was typed),
 * and the session's end deploys what was edited, only once its build and check pass. It's for your account's own
 * apps built with Vite (6 to 8), or of files whose package.json builds nothing or that have none, whose previews get
 * their own data (`previewResources: "branch"`), with `liveEditing` on: such an app has it on from its first
 * production release (`app.update({ liveEditing: true })` for one released before). The container is billed by the
 * minute at what it costs NoClick.
 */
export class ProjectLive extends ProjectService {
  protected readonly service = "live";

  /** Whether the app is edited live, whether it can be, its open session (else its last one) and who edits it. */
  async status(): Promise<LiveStatus> {
    return toStatus(await this._call("GET", []));
  }

  /**
   * Start the app's live session, or return the one that's open, with its `enterUrl`: a link that opens the app in
   * live mode, for 2 hours. A session reads the `noclick-live` branch (production's branch at the first one), and
   * its code writes to copies of the app's data (`refreshData: true` makes them again). It answers while the session
   * starts (`state` `warming`); `wait: true` waits for it to be live, up to 60 seconds, and answers it as it stands
   * then, so a first start in a place (which can take a few minutes) still comes back `warming`: `status()` reads it
   * again. `limits` shortens its timers. An account has at most 3 sessions open, and 24 session-hours a day.
   * Refused while your account can't pay for it (`PaymentRequired`) or the app's budget is spent
   * (`SpendCapExceeded`), and for an app live editing can't run (`Conflict`, whose `readiness` says what to change).
   *
   * ```ts
   * let session = await app.live.start({ wait: true, limits: { idleGraceS: 30, idleEndS: 30 } });
   * console.log(session.enterUrl);   // send it now: the page waits while the session starts
   * while (session.state === "warming") {
   *   await new Promise((resolve) => setTimeout(resolve, 5000));
   *   session = (await app.live.status()).session ?? session;
   * }
   * ```
   */
  async start(options: LiveStartOptions = {}): Promise<LiveSession> {
    const json = compact({
      wait: options.wait || undefined, refresh_data: options.refreshData || undefined, limits: timersWire(options.limits),
    });
    return toSession(await this._call("POST", ["sessions"], {
      ...(Object.keys(json).length ? { json } : {}), ...(options.wait ? { timeoutMs: REQUEST_MS } : {}),
    }));
  }

  /**
   * Run a bash command in the session's container, in the site's working tree (`/site`), starting a session when
   * none is open, and wait for it (`timeoutS` 90 by default, at most 90). A file it writes is committed to the
   * `noclick-live` branch by itself and swaps into the open pages; `vite` says how, per batch of files it changed. A
   * non-zero exit is a result, not an error.
   *
   * A command answers within its request, so one sent while the session is still starting or deploying what was
   * edited doesn't run: it throws `Conflict`, whose `details.state` is `warming` or `ending`. `{ background: true }`
   * returns an `Operation` at once instead, which waits for a starting session, then runs the command with `timeoutS`
   * up to 600: for a command longer than a request allows, or the first one of a session. An account runs at most 4
   * background commands at once; cancelling one stops its wait, not a command already sent.
   *
   * ```ts
   * const result = await app.live.exec("sed -i 's/Score/Points/' src/render.js");
   * for (const edit of result.vite) console.log(edit.outcome, edit.files, edit.reload?.reason, edit.error?.message);
   *
   * const installed = await (await app.live.exec("npm install canvas-confetti", { background: true, timeoutS: 300 })).wait();
   * console.log(installed.ok, installed.stderr);
   * ```
   */
  exec(command: string, options: LiveExecOptions & { background: true }): Promise<Operation<LiveExecResult>>;
  exec(command: string, options?: LiveExecOptions & { background?: false }): Promise<LiveExecResult>;
  async exec(command: string, options: LiveExecOptions = {}): Promise<LiveExecResult | Operation<LiveExecResult>> {
    const timeoutS = options.timeoutS ?? EXEC_DEFAULT_TIMEOUT_S;
    if (options.background) {
      const payload = await this._call("POST", ["exec"], { json: { command, background: true, timeout_s: timeoutS } });
      return Operation._fromPayload<LiveExecResult>(payload, {
        client: this._project._client, user: this._project._callScope(), kind: "project.live_exec", reader: toExecResult,
      });
    }
    return toExecResult(await this._call("POST", ["exec"], {
      json: { command, timeout_s: timeoutS }, timeoutMs: REQUEST_MS,
    }));
  }

  /**
   * What Vite did with each edit of the app's newest session (or `sessionId`'s) after `after` (a sequence number),
   * oldest first: up to `limit` (50 by default, at most 200), with `lastSeq` to read the next ones after. Empty when
   * no session has run.
   *
   *     const { session } = await app.live.status();
   *     if (session) for (const edit of await app.live.edits({ sessionId: session.id })) console.log(edit.seq, edit.outcome);
   */
  async edits(options: { after?: number; limit?: number; sessionId?: string } = {}): Promise<LiveEdits> {
    return toEdits(await this._call("GET", ["edits"], {
      query: { after: options.after || undefined, limit: options.limit ?? 50, session_id: options.sessionId },
    }));
  }

  /**
   * A link that opens the app in live mode (`start()` returns one too), working any number of times for 2 hours.
   * Whoever opens it sees the session's dev server at the app's own URL, on that device, for 12 hours, and can
   * change nothing; everyone else sees production.
   */
  async enterLink(): Promise<LiveEnterLink> {
    return toEnterLink(await this._call("POST", ["enter_links"]));
  }

  /**
   * Hand a change to the app's code to its coding agent, in your words: one per app, made the first time, on the
   * harness and model your account's own model keys pick (else NoClick's key, at its cost). It works in the app's live
   * session, else in its own sandbox on a branch of its own; it commits and pushes, and never deploys: ending the
   * session deploys what passes its check, and a job in its own sandbox that pushed ends with a preview of its branch
   * deploying. `wait()` resolves to its reply.
   *
   * ```ts
   * const reply = await (await app.live.change("Add a dark mode toggle to the header")).wait();
   * ```
   */
  async change(text: string, options: { title?: string; workstream?: string } = {}): Promise<Operation<AgentReply>> {
    const payload = await this._call("POST", ["changes"], { json: compact({ text, title: options.title,
      workstream: options.workstream }) });
    return Operation._fromPayload<AgentReply>(payload, {
      client: this._project._client, user: this._project._callScope(), kind: "agent.message",
    });
  }

  /**
   * End the app's live session now (it also ends on its own, about 11 minutes after the last page closed and the
   * last command ran). What it edited is committed, built and checked where production serves, and only then
   * deployed; a build or check that fails leaves production as it was (`wait()` rejects with `OperationFailed`,
   * saying why), and the edits stay on the `noclick-live` branch for the next session. `deploy: false` stops it
   * without deploying. `wait()` resolves to the `LiveEnd`.
   */
  async end(options: { deploy?: boolean } = {}): Promise<Operation<LiveEnd>> {
    const payload = await this._call("POST", ["end"], { json: { deploy: options.deploy ?? true } });
    return Operation._fromPayload<LiveEnd>(payload, {
      client: this._project._client, user: this._project._callScope(), kind: "project.live_end", reader: toLiveEnd,
    });
  }
}
