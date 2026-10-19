// The work the coordinator started (builds, agent requests, videos, payment links), read back by id with
// coordinator:jobs so the chat's cards follow each job to its end and show its true state after a reload. One read
// covers every card in the thread, repeated while any job is still moving, except a `pushed` job: its kind sends
// every change to the owner's chats as it happens, which its card follows, so it is read with the rest and never on
// a timer. A job that handed its wait to another (`continued_by`: an approved purchase, to the registration it
// started) is followed through that one too. A server that can't answer the read (one older than it) leaves `live`
// false, and the cards say only what the tool itself reported.
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { CoordinatorToolCall, JsonObject } from '~/lib/coordinatorToolCalls';
import { sendEventAsync } from '~/lib/socket-sender';
import { CoordinatorJobsRequest } from '~/types/socket-events.generated';

export interface CoordinatorJob extends JsonObject {
    job_id: string;
    kind: string;
    status: string;
    created_at: string;
    updated_at: string;
    /** Its kind sends every change as it happens; the card follows those. */
    pushed?: boolean;
}

const ACTIVE = new Set(['queued', 'running', 'waiting']);
const POLL_MS = 5000;
const READ_TIMEOUT_MS = 10_000;
// The ledger keeps the newest; a thread with more jobs than one read takes follows its latest.
const MAX_IDS = 50;

export function isActiveJob(job: CoordinatorJob | undefined): boolean {
    return !!job && ACTIVE.has(job.status);
}

export interface CoordinatorJobs {
    /** Whether this server reads jobs back at all. */
    live: boolean;
    get(jobId: string | undefined): CoordinatorJob | undefined;
}

/** How a thread follows the work its turns' tool calls started, read from those calls; `nudge` changes with each turn. */
export type ThreadJobs = (calls: readonly CoordinatorToolCall[], nudge: unknown) => CoordinatorJobs;

const NONE: CoordinatorJobs = { live: false, get: () => undefined };
export const CoordinatorJobsContext = createContext<CoordinatorJobs>(NONE);

export function useCoordinatorJob(jobId: string | undefined): { live: boolean; job: CoordinatorJob | undefined } {
    const jobs = useContext(CoordinatorJobsContext);
    return { live: jobs.live, job: jobs.get(jobId) };
}

/** Reads `jobIds` back, again every few seconds while one is moving and whenever `nudge` changes (a new turn). */
export function useCoordinatorJobs(jobIds: readonly string[], nudge: unknown): CoordinatorJobs {
    const [jobs, setJobs] = useState<Record<string, CoordinatorJob>>({});
    const [live, setLive] = useState(false);
    const answered = useRef(false);
    const unanswered = useRef(false);
    const handedOn = Object.values(jobs)
        .map((job) => job.continued_by)
        .filter((id): id is string => typeof id === 'string');
    const key = [...new Set([...jobIds, ...handedOn])].slice(-MAX_IDS).join(',');
    const moving = Object.values(jobs).some((job) => isActiveJob(job) && !job.pushed);

    useEffect(() => {
        if (!key || unanswered.current) return;
        let cancelled = false;
        const read = async () => {
            try {
                const reply = (await sendEventAsync(
                    CoordinatorJobsRequest.create({ request_id: crypto.randomUUID(), job_ids: key.split(',') as [string, ...string[]] }),
                    undefined,
                    READ_TIMEOUT_MS
                )) as { jobs?: CoordinatorJob[]; error?: string };
                if (cancelled) return;
                if (reply.error || !reply.jobs) throw new Error(reply.error || 'No jobs in the reply');
                answered.current = true;
                setLive(true);
                setJobs(Object.fromEntries(reply.jobs.map((job) => [job.job_id, job])));
            } catch (error) {
                if (cancelled) return;
                // A server that never answered doesn't have the read: it isn't asked again on this page.
                if (!answered.current) unanswered.current = true;
                console.warn('[coordinator] job read failed:', error);
            }
        };
        void read();
        const timer = moving ? window.setInterval(() => void read(), POLL_MS) : undefined;
        return () => {
            cancelled = true;
            window.clearInterval(timer);
        };
    }, [key, moving, nudge]);

    return useMemo(() => ({ live, get: (id) => (id ? jobs[id] : undefined) }), [live, jobs]);
}
