// What the account's agents are working on, for the Chat page's Beside, read from /v1 as the account and kept current
// by the account's frames: every coding agent and its state (GET /v1/agents/coding, read again on
// each platform:coding_agent frame), the apps they work on (GET /v1/projects, again on a platform:resource frame of a
// deployment, domain or repo), each app's live session and its newest edits while an agent edits it live (again on a
// platform:resource frame of the session), the work the chat's turns started as the thread follows it (a build's
// children, a run) with the agents behind it, and the purchases held for the owner (again on a platform:resource frame
// of an approval, and as the thread moves).
// A slow re-read stands behind them all while something's going, as the frames' backstop. The chat's own agent is
// left out of all of it: the coding agents are read once the chat has found it, so it never shows as work at all.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { NoClick } from 'noclick';
import type { CoordinatorJob, CoordinatorJobs } from '@/lib/threadJobs';
import { useWorkFrames } from '@/sdk/live';
import { obj, str, type CoordinatorToolCall } from '@/lib/toolCalls';
import { standing } from '@/slots';
import { approvalUrl, billingSettingsUrl } from '@/screens/console/lib/site';
import { atWork, type AtWork, type AtWorkLinks, type AtWorkSources } from './atWork/model';
import type { AgentSlice, CodingAgentsPage, EditsPage, FollowedOperation, HeldApproval, JobUpdate, LiveRead, LiveState, ProjectSlice } from './atWork/types';
import { CHAT_PLACES } from './slots';
import { useSite } from './site';
import { operationIdOf } from '@/sdk/useFollowedOperations';
import { openTabForLater } from '@/lib/oauthPopup';

/** How often the reads are taken again while something's going and no frame came: the frames' backstop. */
export const BACKSTOP_MS = 60_000;
// The newest edits a row shows.
const EDITS_SHOWN = 3;
const ACCOUNT = { user: null } as const;

interface Page<T> {
    data: T[];
}

/** One read kept current: taken when `key` names one, again on `reread()`, one at a time (a reread asked for while
 *  one runs runs once after it). A read that fails keeps what the last one gave. */
function useRead<T>(key: string | null, read: (signal: AbortSignal) => Promise<T>): [T | undefined, () => void] {
    const [held, setHeld] = useState<{ key: string; value: T }>();
    const reader = useRef(read);
    reader.current = read;
    const flight = useRef({ running: false, again: false, stop: new AbortController() });
    const run = useCallback(() => {
        if (key === null) return;
        const now = flight.current;
        if (now.running) {
            now.again = true;
            return;
        }
        now.running = true;
        const { signal } = now.stop;
        void (async () => {
            try {
                const value = await reader.current(signal);
                if (!signal.aborted) setHeld({ key, value });
            } catch (error) {
                if (!signal.aborted) console.warn(`[at work] reading ${key} failed:`, error);
            } finally {
                now.running = false;
                if (now.again && !signal.aborted) {
                    now.again = false;
                    run();
                }
            }
        })();
    }, [key]);
    useEffect(() => {
        flight.current = { running: false, again: false, stop: new AbortController() };
        run();
        const { stop } = flight.current;
        return () => stop.abort();
    }, [run]);
    return [held?.key === key ? held.value : undefined, run];
}

/** One read per id, each taken once its id is named and again on `reread(id)`. */
function useReads<T>(ids: readonly string[], read: (id: string, signal: AbortSignal) => Promise<T>): [Record<string, T>, (id: string) => void] {
    const [held, setHeld] = useState<Record<string, T>>({});
    const reader = useRef(read);
    reader.current = read;
    const flights = useRef(new Map<string, { running: boolean; again: boolean }>());
    const stop = useRef(new AbortController());
    const run = useCallback((id: string) => {
        const flight = flights.current.get(id) ?? { running: false, again: false };
        flights.current.set(id, flight);
        if (flight.running) {
            flight.again = true;
            return;
        }
        flight.running = true;
        const { signal } = stop.current;
        void (async () => {
            try {
                const value = await reader.current(id, signal);
                if (!signal.aborted) setHeld((all) => ({ ...all, [id]: value }));
            } catch (error) {
                if (!signal.aborted) console.warn(`[at work] reading ${id} failed:`, error);
            } finally {
                flight.running = false;
                if (flight.again && !signal.aborted) {
                    flight.again = false;
                    run(id);
                }
            }
        })();
    }, []);
    // Mounted again (as development's strict mode does), its reads start over.
    useEffect(() => {
        const current = new AbortController();
        stop.current = current;
        flights.current = new Map();
        return () => current.abort();
    }, []);
    const named = ids.join(' ');
    useEffect(() => {
        for (const id of named ? named.split(' ') : []) if (!flights.current.has(id)) run(id);
    }, [named, run]);
    return [held, run];
}

/** `fn` every `ms` while `on` and the page is in view. */
function useBackstop(on: boolean, fn: () => void, ms = BACKSTOP_MS) {
    const latest = useRef(fn);
    latest.current = fn;
    useEffect(() => {
        if (!on) return;
        const timer = window.setInterval(() => {
            if (document.visibilityState === 'visible') latest.current();
        }, ms);
        return () => window.clearInterval(timer);
    }, [on, ms]);
}

const STATUSES = new Set(['running', 'waiting', 'completed', 'failed', 'cancelled']);

/** An operation the chat follows, as the tab reads it. */
export function followedOf(job: CoordinatorJob): FollowedOperation {
    const update = obj(job, 'latest_update');
    return {
        id: job.job_id,
        kind: job.kind,
        status: (STATUSES.has(job.status) ? job.status : 'running') as FollowedOperation['status'],
        step: str(job, 'step') ?? null,
        title: str(job, 'title') ?? null,
        summary: str(job, 'summary') ?? null,
        agent_id: str(job, 'agent_id') ?? null,
        latest_update: update ? (update as unknown as JobUpdate) : null,
        created_at: job.created_at,
        finished_at: str(job, 'finished_at') ?? null,
    };
}

// The work the tab follows from the thread: a build's children, an automation's runs, and the turns of changes handed
// to coding agents (what an agent no longer at it was last asked).
const FOLLOWED = new Set(['agent.task', 'workflow.run', 'agent.message']);

/** One turn of the chat's thread, as the work it started is read from it: its calls, and what the person asked in
 *  the message it answers (none for a turn no person started). */
export interface ThreadTurn {
    asked: string | null;
    calls: readonly CoordinatorToolCall[];
}

/** The work the thread's turns started, and what the person asked in the message each turn answered. */
function threadWork(turns: readonly ThreadTurn[], jobs: CoordinatorJobs): { operations: FollowedOperation[]; requests: Record<string, string> } {
    const operations: FollowedOperation[] = [];
    const requests: Record<string, string> = {};
    for (const { asked, calls } of turns) {
        for (const call of calls) {
            const id = operationIdOf(call);
            const job = id ? jobs.get(id) : undefined;
            if (!job || !FOLLOWED.has(job.kind) || operations.some((op) => op.id === job.job_id)) continue;
            operations.push(followedOf(job));
            if (asked) requests[job.job_id] = asked;
        }
    }
    return { operations, requests };
}

/** An app's live session and its newest edits. */
async function readLive(client: NoClick, projectId: string, signal: AbortSignal): Promise<LiveRead> {
    const live = await client.request<LiveState>('GET', `/v1/projects/${projectId}/live`, { ...ACCOUNT, signal });
    const last = live.session?.edits.last_seq ?? 0;
    if (!live.session || !last) return { session: live.session, edits: [] };
    const page = await client.request<EditsPage>('GET', `/v1/projects/${projectId}/live/edits`, {
        ...ACCOUNT,
        signal,
        query: { session_id: live.session.id, after: Math.max(0, last - EDITS_SHOWN), limit: EDITS_SHOWN },
    });
    return { session: live.session, edits: page.data };
}

// A warm agent only waits for its next message: nothing's going.
const GOING = new Set(['working', 'waiting', 'paused']);

/** `own`: the chat's own agent, null until the chat has found it. */
export function useAgentsAtWork(client: NoClick, turns: readonly ThreadTurn[], jobs: CoordinatorJobs, own: string | null): AtWork {
    const [coding, rereadCoding] = useRead(own ? 'coding' : null, (signal) => client.request<CodingAgentsPage>('GET', '/v1/agents/coding', { ...ACCOUNT, signal }));
    const { operations, requests } = useMemo(() => threadWork(turns, jobs), [turns, jobs]);
    const going = (coding?.data ?? []).filter((a) => a.agent_id !== own && GOING.has(a.state));
    const tasks = operations.filter((op) => op.kind === 'agent.task');
    const someWork = going.length > 0 || operations.some((op) => op.status === 'running' || op.status === 'waiting');

    // The apps the work is in: read once there's work.
    const [projects, rereadProjects] = useRead(someWork ? 'projects' : null, async (signal) => (await client.request<Page<ProjectSlice>>('GET', '/v1/projects', { ...ACCOUNT, signal, query: { limit: 100 } })).data);

    // The agents behind the tasks: what they check out names the app they work on.
    const agentIds = useMemo(() => [...new Set(tasks.flatMap((op) => (op.agent_id ? [op.agent_id] : [])))], [tasks]);
    const [agents] = useReads(agentIds, (id, signal) => client.request<AgentSlice>('GET', `/v1/agents/${id}`, { ...ACCOUNT, signal }));

    // Each app an agent edits live: its session and newest edits.
    const liveApps = useMemo(() => [...new Set(going.flatMap((a) => (a.place === 'live' && a.app ? [a.app.project_id] : [])))], [going]);
    const [live, rereadLive] = useReads(liveApps, (id, signal) => readLive(client, id, signal));

    // What waits on the owner's OK, read again whenever the thread moves (a turn that held a purchase, an answer).
    const [approvals, rereadApprovals] = useRead('approvals', async (signal) =>
        (await client.request<Page<HeldApproval>>('GET', '/v1/approvals', { ...ACCOUNT, signal, query: { status: 'pending', limit: 20 } })).data
    );
    const moved = turns.length;
    const first = useRef(true);
    useEffect(() => {
        if (first.current) {
            first.current = false;
            return;
        }
        rereadApprovals();
    }, [moved, rereadApprovals]);

    useWorkFrames(
        'platform:coding_agent',
        (frame) => {
            // The chat's own turns move it at every message.
            if (own && frame.agent_id === own) return;
            rereadCoding();
            const app = coding?.data.find((a) => a.agent_id === frame.agent_id)?.app;
            if (app && liveApps.includes(app.project_id)) rereadLive(app.project_id);
        }
    );
    useWorkFrames(
        'platform:resource',
        (frame) => {
            if (frame.kind === 'live_session') {
                if (frame.parent_id && liveApps.includes(frame.parent_id)) rereadLive(frame.parent_id);
            } else if (frame.kind === 'deployment' || frame.kind === 'domain' || frame.kind === 'repo') {
                rereadProjects();
            } else if (frame.kind === 'approval') {
                // A call held for the owner, or an approval answered wherever it was (its page, a text, another tab).
                rereadApprovals();
            }
        }
    );
    const pending = (approvals ?? []).length > 0;
    useBackstop(someWork || pending, () => {
        rereadCoding();
        rereadApprovals();
        liveApps.forEach(rereadLive);
    });

    const site = useSite();
    const links = useMemo<AtWorkLinks>(
        () => ({
            billing: billingSettingsUrl(site),
            approval: (id) => approvalUrl(site, id),
            commit: (repo, sha) => standing(CHAT_PLACES).href('resources', { kind: 'repos', resource: repo, view: 'commit', sha }),
        }),
        [site]
    );
    return useMemo(() => {
        const sources: AtWorkSources = { links, own, coding: coding ?? null, projects: projects ?? [], operations, agents, approvals: approvals ?? [], live, requests };
        return atWork(sources);
    }, [links, own, coding, projects, operations, agents, approvals, live, requests]);
}

/** Opens the app in live mode in a new tab: a fresh link that opens it there, minted as it's opened (each lasts two
 *  hours, so one kept from when the work was handed over may have lapsed). */
export async function openLive(client: NoClick, projectId: string): Promise<void> {
    const tab = openTabForLater();
    try {
        const { url } = await client.request<{ url: string }>('POST', `/v1/projects/${projectId}/live/enter_links`, { ...ACCOUNT, json: {} });
        if (!tab.go(url)) window.location.assign(url);
    } catch (error) {
        tab.close();
        throw error;
    }
}

/** Stops a turn or a task: its operation is canceled, which its agent and NoClick hear. */
export async function stopWork(client: NoClick, operationId: string): Promise<void> {
    await client.request('POST', `/v1/operations/${operationId}/cancel`, { ...ACCOUNT, json: {} });
}
