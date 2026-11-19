// Long work an agent set going (a deploy, a build, a call), as its card draws it: its stages with when each started
// and ended, the lines it printed last, when anything last changed, and what it made once done. `workViewOf` reads it
// from an operation and the progress its runner reports (`progress`: step, stages, last lines, updated_at); work that
// reports no progress yet is one stage, named by its step, so the card still says how fresh it is.
import { kindVerb } from '@/lib/stepLabels';

export type WorkState = 'running' | 'waiting' | 'done' | 'failed';

export interface WorkStage {
    name: string;
    start: number;
    end?: number;
    state: 'done' | 'current' | 'pending' | 'failed';
}

export interface WorkLine {
    text: string;
    error?: boolean;
}

export interface WorkView {
    kind: string;
    title: string;
    state: WorkState;
    startedAt: number;
    /** When the work going now began: its first stage, so work that waited on a person and went on counts from there. */
    workingSince: number;
    /** When it settled. */
    endedAt?: number;
    stages: WorkStage[];
    /** What it printed last, newest last. */
    lines: WorkLine[];
    /** When anything new last came from it (a stage, a line). */
    changedAt: number;
    /** How its done line starts ("Deployed"); "Done" when its kind names no action. */
    doneVerb: string;
    /** What it made, once done, and where that opens. */
    result?: { text: string; href?: string; open: string };
    /** Why it didn't finish. */
    error?: string;
    /** The action that would try it again ("Deploy again"). */
    retry: string;
}

type Json = Record<string, unknown>;

const asObject = (v: unknown): Json | undefined => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : undefined);
const text = (v: unknown): string | undefined => (typeof v === 'string' && v ? v : undefined);
const time = (v: unknown): number | undefined => {
    const t = typeof v === 'string' ? Date.parse(v) : typeof v === 'number' ? v : NaN;
    return Number.isFinite(t) ? t : undefined;
};

const STATE: Record<string, WorkState> = {
    queued: 'running',
    running: 'running',
    awaiting_human: 'waiting',
    waiting: 'waiting',
    succeeded: 'done',
    completed: 'done',
    failed: 'failed',
    canceled: 'failed',
    cancelled: 'failed',
    expired: 'failed',
};

// A line that reports the failure itself ("Build failed in 1.8s", "exit code 1") rather than what broke.
const VERDICT = /exit code|failed in/i;
const ERROR_LINE = /\berror\b|\bfailed\b|✗|ERR!/i;

function sentence(s: string): string {
    return s.charAt(0).toUpperCase() + s.slice(1);
}

/** The first link in what it made: a site's address, a recording's. */
function linkIn(value: unknown, depth = 0): string | undefined {
    const o = asObject(value);
    if (!o || depth > 3) return undefined;
    for (const key of ['url', 'href', 'live_url', 'site_url']) {
        const v = text(o[key]);
        if (v && /^https?:\/\//.test(v)) return v;
    }
    for (const v of Object.values(o)) {
        const found = linkIn(v, depth + 1);
        if (found) return found;
    }
    return undefined;
}

function resultOf(kind: string, result: unknown): WorkView['result'] {
    const href = linkIn(result);
    if (!href) return undefined;
    const url = new URL(href);
    const shown = `${url.host}${url.pathname === '/' ? '' : url.pathname}`;
    return { text: shown, href, open: /deploy|project|site|app/.test(kind) ? 'Open site' : 'Open' };
}

export interface WorkSource {
    kind?: string;
    /** What the work is, as it was asked ("Deploying sample-site"). */
    title: string;
    status?: string;
    startedAt: number;
    updatedAt?: number;
    progress?: unknown;
    error?: string;
    result?: unknown;
}

/** The card's view of long work, at the last moment anything was said about it. */
export function workViewOf(source: WorkSource): WorkView {
    const kind = source.kind ?? '';
    const state = STATE[source.status ?? ''] ?? 'running';
    const progress = asObject(source.progress);
    const settled = state === 'done' || state === 'failed';
    const endedAt = settled ? (source.updatedAt ?? source.startedAt) : undefined;
    const reported = Array.isArray(progress?.stages) ? progress.stages.map(asObject).filter((s): s is Json => !!s && !!text(s.name)) : [];
    let stages: WorkStage[] = reported.map((s) => {
        const status = text(s.status);
        return {
            name: text(s.name)!,
            start: time(s.started_at) ?? source.startedAt,
            end: time(s.ended_at),
            state: status === 'done' ? 'done' : status === 'current' ? 'current' : 'pending',
        };
    });
    if (!stages.length) {
        const step = text(progress?.step);
        const name = state === 'waiting' ? 'Waiting on you' : step ? sentence(step.replace(/[_-]+/g, ' ')) : 'Working';
        stages = [{ name, start: source.startedAt, state: 'current' }];
    }
    if (settled) {
        // Once it settled the stage it was on is where it ended, and the ones it never reached aren't drawn.
        stages = stages
            .filter((s) => s.state !== 'pending')
            .map((s) => (s.state === 'current' ? { ...s, state: state === 'failed' ? 'failed' : 'done', end: s.end ?? endedAt } : s));
    }
    const lines = (Array.isArray(progress?.lines) ? progress.lines : [])
        .map(text)
        .filter((l): l is string => !!l)
        .map((l) => ({ text: l, error: ERROR_LINE.test(l) && !VERDICT.test(l) ? true : undefined }));
    const changedAt = Math.max(source.startedAt, time(progress?.updated_at) ?? 0, ...stages.map((s) => s.start));
    const verb = kind ? kindVerb(kind, 'done') : undefined;
    const base = kind ? kindVerb(kind, 'base') : undefined;
    return {
        kind,
        title: source.title,
        state,
        startedAt: source.startedAt,
        workingSince: stages.find((s) => s.state !== 'pending')?.start ?? source.startedAt,
        endedAt,
        stages,
        lines,
        changedAt,
        doneVerb: verb ?? 'Done',
        result: state === 'done' ? resultOf(kind, source.result) : undefined,
        error: source.error,
        retry: base ? `${base} again` : 'Try again',
    };
}

/** "just now", "4s ago", "quiet 45s": how long since anything new came. */
export function quietText(quietMs: number): string {
    if (quietMs < 2000) return 'just now';
    const s = Math.round(quietMs / 1000);
    const said = s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
    return quietMs < 30000 ? `${said} ago` : `quiet ${said}`;
}

/** The line that says what broke: the last error line before the build's own verdict, else why it didn't finish. */
export function breakingLine(view: WorkView): WorkLine | undefined {
    const errors = view.lines.filter((l) => l.error).reverse();
    const line = errors.find((l) => !VERDICT.test(l.text)) ?? errors[0];
    return line ?? (view.error ? { text: view.error, error: true } : undefined);
}
