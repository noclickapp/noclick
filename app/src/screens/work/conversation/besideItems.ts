// What works beside an agent's conversation, as its card counts it and its rail lists it: its harness's subagents
// (their calls in its turns, a background one still at work after its turn's reply), the NoClick agents it
// started (their tasks), the browser it works in (the card draws it as a live tile) and its loops (a prompt it takes up
// again and again until stopped). Each one's status, timing and newest moment; spend only where the platform meters it
// on its own (an agent's task). Pure: the conversation reads the thread, the agents' tasks and its loops, and the rail
// draws this.
import type { AgentStateRow, Browser, HarnessRequest, Operation, Wakeup } from 'noclick';
import { describeCronIn } from '@/lib/scheduleFormat';
import { nowWords } from '../agents/states';
import { captionOf, isLiveState, newestStep, stateOf } from '../browser/words';
import { doing, failedStep, subagentTask } from './Activity';
import { spawnedChild, type Child } from './subagents';
import { flatSteps, isSubagentCall, stepsOf, type Step, type Thread, type TurnEntry } from '@/lib/agentThread/thread';

export type BesideStatus = 'needs' | 'running' | 'done' | 'failed' | 'stopped';

export interface BesideItem {
    /** A harness subagent's call id, a NoClick agent's id, the browser's, or a loop's wake-up id. */
    id: string;
    kind: 'subagent' | 'agent' | 'browser' | 'loop';
    title: string;
    status: BesideStatus;
    startedAt: number;
    endedAt: number | null;
    /** Its newest moment, as it last moved. */
    activeAt: number;
    /** Its newest step in a line while it works, what it found once done, why it failed. */
    line: string | null;
    /** A harness subagent's call: its log. */
    call: Step | null;
    /** The turn that started a harness subagent still runs: stopping that turn is the one way to stop it. */
    turnRunning: boolean;
    /** A NoClick agent's. */
    agent: Child | null;
    /** The conversation's browser. */
    browser?: Browser;
    /** What it has cost in dollars, where the platform meters it on its own (a NoClick agent's task); null where it
     *  doesn't. */
    spendUsd: number | null;
    /** The workstream a NoClick agent's task belongs to, as its operation names it now; none where nobody named one. */
    workstream?: string | null;
    /** A loop's: how it comes round, when it runs next (null while its run works, or once it's over), and the
     *  wake-up it is, which Stop cancels. */
    loop?: { every: string; nextAt: number | null; runs: number; wakeup: Wakeup };
}

const live = (s: BesideStatus) => s === 'needs' || s === 'running';
export const isLive = (b: BesideItem) => live(b.status);

const firstLine = (text: string) => text.trim().split('\n').find(Boolean) ?? '';

/** A subagent's newest moment: its newest step, or its newest words, whichever came last. */
function newestOf(call: Step): { line: string; at: number } | null {
    const step = call.children[call.children.length - 1];
    const words = firstLine(call.said.split('\n').filter(Boolean).pop() ?? '');
    if (step && (!words || (call.saidAt ?? 0) <= step.at)) return { line: doing(step), at: step.at };
    return words ? { line: words, at: call.saidAt ?? call.at } : null;
}

function subagentItem(turn: TurnEntry, call: Step, requests: readonly HarnessRequest[]): BesideItem {
    const ids = new Set(flatSteps([call]).map((s) => s.id));
    const asked = requests.find((r) => r.status === 'pending' && typeof r.raw.call_id === 'string' && ids.has(r.raw.call_id));
    const failed = failedStep(call);
    const status: BesideStatus = asked ? 'needs' : call.running ? 'running' : failed ? 'failed' : 'done';
    const newest = newestOf(call);
    const endedAt = call.running ? null : call.durationMs !== null ? call.at + call.durationMs : (turn.endedAt ?? call.at);
    const said = firstLine(call.output);
    return {
        id: call.id,
        kind: 'subagent',
        title: subagentTask(call),
        status,
        startedAt: call.at,
        endedAt,
        activeAt: newest?.at ?? call.at,
        line: asked ? (asked.title ?? 'Waiting on you') : live(status) ? (newest?.line ?? 'Starting…') : said || (failed ? 'It failed.' : null),
        call,
        turnRunning: turn.status === 'running',
        agent: null,
        spendUsd: null,
    };
}

/** Its harness's subagents, in every turn of the conversation, in the order they started. */
export function subagentItems(thread: Thread, requests: readonly HarnessRequest[]): BesideItem[] {
    return thread.entries.flatMap((e) => (e.kind === 'turn' ? stepsOf(e).filter(isSubagentCall).map((call) => subagentItem(e, call, requests)) : []));
}

/** The NoClick agents it started (each `agents__spawn` it made), with the step that started each. */
export function startedAgents(thread: Thread): { child: Child; step: Step }[] {
    const seen = new Set<string>();
    return thread.entries.flatMap((e) => {
        if (e.kind !== 'turn') return [];
        return flatSteps(stepsOf(e)).flatMap((step) => {
            const child = spawnedChild(step);
            if (!child || seen.has(child.agentId)) return [];
            seen.add(child.agentId);
            return [{ child, step }];
        });
    });
}

const JOB_STATUS: Record<string, BesideStatus> = { queued: 'running', running: 'running', awaiting_human: 'needs', succeeded: 'done', failed: 'failed', canceled: 'stopped', expired: 'stopped' };

/** A NoClick agent it started, as its task's operation says (else where the agent itself stands), with what its task
 *  has cost. */
export function agentItem(started: { child: Child; step: Step }, job: Operation | undefined, state: AgentStateRow | undefined, spendUsd: number | null): BesideItem {
    const { child, step } = started;
    const fromState: BesideStatus | null = !state ? null : state.state === 'working' || state.state === 'waking' ? 'running' : state.state === 'needs_you' ? 'needs' : state.state === 'failed' ? 'failed' : 'done';
    const status = (job && JOB_STATUS[job.status]) ?? fromState ?? 'running';
    const startedAt = (job?.startedAt ?? job?.createdAt)?.getTime() ?? step.at;
    const endedAt = live(status) ? null : (job?.finishedAt?.getTime() ?? state?.lastActiveAt?.getTime() ?? null);
    const result = job?.result as { text?: unknown } | null | undefined;
    return {
        id: child.agentId,
        kind: 'agent',
        title: child.task || child.name,
        status,
        startedAt,
        endedAt,
        activeAt: state?.now?.since?.getTime() ?? state?.lastActiveAt?.getTime() ?? startedAt,
        line: status === 'needs' ? 'Waiting on you' : status === 'running' ? nowWords(state?.now) || 'Working' : typeof result?.text === 'string' ? firstLine(result.text) : status === 'failed' ? (state?.failed?.message ?? 'Its task failed.') : null,
        call: null,
        turnRunning: false,
        agent: child,
        spendUsd,
        workstream: job?.workstream?.name ?? null,
    };
}

/** The conversation's browser, while it's at work or since it last was today: working or waiting on a person, it's
 *  running or needs you (you, only when the step is yours or you hold it); at rest, done. */
export function browserItems(browser: Browser | null, now = Date.now()): BesideItem[] {
    if (!browser) return [];
    const state = stateOf(browser);
    const startedAt = (browser.startedAt ?? browser.createdAt)?.getTime() ?? now;
    const activeAt = newestStep(browser.steps)?.at?.getTime() ?? startedAt;
    const endedAt = isLiveState(state) ? null : (browser.closedAt?.getTime() ?? activeAt);
    const today = new Date(now);
    today.setHours(0, 0, 0, 0);
    if (endedAt !== null && endedAt < today.getTime()) return [];
    const needs = state === 'control' || (state === 'needs' && !!browser.waitingOn?.forYou);
    return [{
        id: browser.id,
        kind: 'browser',
        title: 'Browser',
        status: needs ? 'needs' : isLiveState(state) ? 'running' : browser.status === 'failed' ? 'failed' : 'done',
        startedAt,
        endedAt,
        activeAt,
        line: captionOf(browser),
        call: null,
        turnRunning: false,
        agent: null,
        browser,
        spendUsd: null,
    }];
}

/** The rail's groups: what needs you, what runs (the most recently active first), and what ended today. */
export function grouped(items: readonly BesideItem[], now = Date.now()): { needs: BesideItem[]; running: BesideItem[]; done: BesideItem[] } {
    const today = new Date(now);
    today.setHours(0, 0, 0, 0);
    return {
        needs: items.filter((b) => b.status === 'needs'),
        running: items.filter((b) => b.status === 'running').sort((a, b) => b.activeAt - a.activeAt),
        done: items.filter((b) => !isLive(b) && (b.endedAt ?? b.startedAt) >= today.getTime()),
    };
}

/** How long it has run, or took: "6h 56m", "4m 05s", "12s". */
export function clockOf(ms: number): string {
    const sec = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    return h ? `${h}h ${String(m).padStart(2, '0')}m` : m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
}

/** A wake-up that comes round until it's stopped: on a schedule, or paced by the agent itself. */
export const isLoop = (w: Wakeup) => w.every !== null || w.raw.self_paced === true;

const LOOP_STATUS: Record<string, BesideStatus> = { pending: 'running', delivered: 'done', failed: 'failed', canceled: 'stopped' };

/** A loop of the conversation: running while it comes round, its line how and when next ("Every 5 minutes · next
 *  10:35"; "· running now" while a run of it works); once over, why. `runningTurn`: the turn at work there, if any. */
export function loopItem(w: Wakeup, runningTurn: string | null = null): BesideItem {
    const status = LOOP_STATUS[w.status] ?? 'stopped';
    const every = w.every ? (describeCronIn(w.every.expr, w.every.tz) ?? `On ${w.every.expr}`) : 'Paces itself';
    const nextAt = status === 'running' ? (w.at?.getTime() ?? null) : null;
    const working = status === 'running' && (nextAt === null || (!!runningTurn && runningTurn === w.operationId));
    const next = working ? 'running now' : nextAt !== null ? `next ${new Date(nextAt).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}` : null;
    const error = w.error as { message?: unknown } | null;
    const startedAt = w.createdAt?.getTime() ?? Date.now();
    const lastRun = w.deliveredAt?.getTime() ?? null;
    return {
        id: w.id,
        kind: 'loop',
        title: firstLine(w.note) || 'A loop',
        status,
        startedAt,
        endedAt: status === 'running' ? null : (lastRun ?? startedAt),
        activeAt: lastRun ?? startedAt,
        line: status === 'running' ? [every, next].filter(Boolean).join(' · ') : status === 'failed' ? (typeof error?.message === 'string' ? error.message : 'It stopped itself.') : null,
        call: null,
        turnRunning: working,
        agent: null,
        spendUsd: null,
        loop: { every, nextAt, runs: w.fired, wakeup: w },
    };
}
