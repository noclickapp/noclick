/**
 * A release as it happens (`noclick deploy`, `rollback`, `promote`): each stage with a spinner and its time, the
 * work's own lines (a build's log) as they come, then a tick or a cross. The Python CLI's `_cli/progress.py` draws the
 * same, line for line (`python/tests/cli_progress_cases.json` holds both to it).
 *
 * At a terminal (stderr styled, `style.ERR.on`) the stage under way is one line drawn again in place; anywhere else
 * (piped, `CI`, `NO_COLOR`) each stage's start and end is a plain line of its own, so a log reads top to bottom.
 *
 * The operation is followed through its own long-poll: each read of `GET /v1/operations/{id}/wait` names the
 * `updated_at` it last saw (`changed_since`), so the server answers as soon as anything moves, one request per
 * change, never a page read on a timer. Ctrl-C stops following; the work goes on.
 */

import { ERR, Style } from "./style.ts";

export const SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
const TICK_MS = 100;
/** A stage's name as a person reads it, by the name the operation reports it under. */
export const NAMES: Record<string, string> = { Queued: "Queue", Building: "Build", Shipping: "Release", Live: "Health check" };
const PAD = 12;
export const TERMINAL = new Set(["succeeded", "failed", "canceled", "expired"]);
/** The longest one read lets the server hold it (the server caps it near this). */
export const WINDOW_S = 50;

/** `3.4s` under a minute, `2m 05s` past it (cut to tenths, never rounded, as the Python CLI cuts). */
export function took(seconds: number): string {
  const tenths = Math.max(Math.floor(seconds * 10 + 1e-9), 0);
  if (tenths < 600) return `${Math.floor(tenths / 10)}.${tenths % 10}s`;
  const whole = Math.floor(tenths / 10);
  return `${Math.floor(whole / 60)}m ${String(whole % 60).padStart(2, "0")}s`;
}

export interface StepsOptions {
  /** Draw in place (a terminal): default, when stderr is styled. */
  live?: boolean;
  /** Seconds, from any start. */
  clock?: () => number;
  paint?: Style;
  /** A timer turns the spinner while a stage is under way (a test turns it with `tick`). */
  ticker?: boolean;
}

/** Stages and the lines between them, written to `write`: drawn in place when live, else a line each. */
export class Steps {
  readonly live: boolean;
  current: string | null = null;
  printedLines = 0;
  private since = 0;
  private frame = 0;
  private drawn = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private readonly write: (text: string) => void;
  private readonly clock: () => number;
  private readonly paint: Style;
  private readonly ticker: boolean;

  constructor(write: (text: string) => void, options: StepsOptions = {}) {
    this.write = write;
    this.live = options.live ?? ERR.on;
    this.clock = options.clock ?? (() => performance.now() / 1000);
    this.paint = options.paint ?? ERR;
    this.ticker = options.ticker ?? true;
  }

  /** Start a stage (the one under way, if any, ends first). */
  start(name: string): void {
    this.end(true);
    this.current = name;
    this.since = this.clock();
    if (this.live) this.draw();
    else this.write(`${name}…\n`);
    if (this.live && this.ticker && !this.timer) {
      this.timer = setInterval(() => this.tick(), TICK_MS);
      this.timer.unref?.();
    }
  }

  /** End the stage under way; `seconds` is how long it took where the work says, else the time seen here. */
  end(ok = true, seconds?: number | null): void {
    if (this.current === null) return;
    const name = this.current;
    const spent = took(seconds ?? this.clock() - this.since);
    this.current = null;
    this.stopTicking();
    if (this.live) {
      this.clear();
      const mark = ok ? this.paint.ok("✓") : this.paint.error("✗");
      this.write(`${mark} ${name.padEnd(PAD)} ${this.paint.dim(spent)}\n`);
    } else {
      this.write(ok ? `${name}: ${spent}\n` : `${name}: failed after ${spent}\n`);
    }
  }

  line(text: string): void {
    this.printedLines++;
    if (this.live) {
      this.clear();
      this.write(`  ${this.paint.dim(text)}\n`);
      this.draw();
    } else {
      this.write(`  ${text}\n`);
    }
  }

  tick(): void {
    this.frame++;
    this.draw();
  }

  /** Stop drawing: the line in place is cleared, the stage left as it was. */
  close(): void {
    this.stopTicking();
    this.clear();
  }

  private stopTicking(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  private draw(): void {
    if (!this.live || this.current === null) return;
    const spin = this.paint.accent(SPIN[this.frame % SPIN.length]!);
    this.write(`\r\x1b[2K${spin} ${this.current.padEnd(PAD)} ${this.paint.dim(took(this.clock() - this.since))}`);
    this.drawn = true;
  }

  private clear(): void {
    if (this.drawn) {
      this.write("\r\x1b[2K");
      this.drawn = false;
    }
  }
}

type Raw = Record<string, unknown>;
interface Stage { name?: string; status?: string; started_at?: string | null; ended_at?: string | null }
interface Progress { lines?: string[]; line_count?: number; stages?: Stage[] }

/** How long a stage took, by the work's own clock. */
function secondsOf(stage: Stage): number | null {
  if (!stage.started_at || !stage.ended_at) return null;
  const spent = (Date.parse(stage.ended_at) - Date.parse(stage.started_at)) / 1000;
  return Number.isFinite(spent) ? spent : null;
}

/** What an operation's reads say, as stages and lines: each read its `progress` (stages, the last lines and how many
 *  there have been), only what's new drawn. `single`: the one stage shown for work that reports none (a promote). */
export class Follower {
  private shown = 0;
  private readonly started = new Set<string>();
  private readonly steps: Steps;
  private readonly single: string | undefined;

  constructor(steps: Steps, single?: string) {
    this.steps = steps;
    this.single = single;
  }

  /** A read's new lines go under the stage that was under way before it (they're what it printed until it moved on:
   *  a build's last lines come with the move to its release); the first read's, and those read as it leaves the
   *  queue (which prints nothing), under the stage it's at. */
  apply(raw: Raw): void {
    const progress = (raw.progress ?? {}) as Progress;
    if (this.steps.current === null || this.steps.current === NAMES.Queued) {
      this.stages(progress);
      this.lines(progress);
    } else {
      this.lines(progress);
      this.stages(progress);
    }
    if (TERMINAL.has(String(raw.status))) this.steps.end(raw.status === "succeeded");
  }

  private lines(progress: Progress): void {
    const lines = progress.lines ?? [];
    const count = progress.line_count ?? 0;
    const fresh = Math.min(count - this.shown, lines.length);
    if (fresh > 0) for (const text of lines.slice(lines.length - fresh)) this.steps.line(text);
    this.shown = Math.max(this.shown, count);
  }

  private stages(progress: Progress): void {
    const stages = progress.stages ?? [];
    for (const stage of stages) {
      const name = NAMES[stage.name ?? ""] ?? stage.name ?? "";
      if ((stage.status === "current" || stage.status === "done") && !this.started.has(name)) {
        this.steps.start(name);
        this.started.add(name);
      }
      if (stage.status === "done" && this.steps.current === name) this.steps.end(true, secondsOf(stage));
    }
    if (!stages.length && this.single && !this.started.has(this.single)) {
      this.steps.start(this.single);
      this.started.add(this.single);
    }
  }
}

/** One long-poll: the operation once it moved past `changedSince`, or as it stands after `windowS`. */
export type Read = (opId: string, windowS: number, changedSince: string | null) => Promise<Raw>;

/** Ctrl-C while following: it stops following, never the work. */
export class Detached extends Error {}

/**
 * Follow the operation from `raw` (as it stands) until it ends or `timeoutS` passes, drawing it: the operation as last
 * read. Ctrl-C (`interrupted`, a promise that settles on it) rejects with `Detached`; a read that fails ends the
 * stage under way with a cross, and rejects.
 */
export async function follow(opId: string, raw: Raw, steps: Steps, read: Read, options: {
  timeoutS?: number; single?: string; interrupted?: Promise<void>; clock?: () => number;
} = {}): Promise<Raw> {
  const clock = options.clock ?? (() => performance.now() / 1000);
  const follower = new Follower(steps, options.single);
  const deadline = options.timeoutS === undefined ? null : clock() + options.timeoutS;
  const stopped = options.interrupted?.then(() => { throw new Detached(); });
  stopped?.catch(() => {});
  try {
    follower.apply(raw);
    while (!TERMINAL.has(String(raw.status))) {
      let window = WINDOW_S;
      if (deadline !== null) {
        const left = deadline - clock();
        if (left <= 0) break;
        window = Math.min(WINDOW_S, Math.max(1, Math.ceil(left)));
      }
      const next = read(opId, window, typeof raw.updated_at === "string" ? raw.updated_at : null);
      raw = await (stopped ? Promise.race([next, stopped]) : next);
      follower.apply(raw);
    }
  } catch (err) {
    if (err instanceof Detached) steps.close();
    else steps.end(false);
    throw err;
  }
  return raw;
}
