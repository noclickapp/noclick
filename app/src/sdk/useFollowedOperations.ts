// The long actions a coordinator agent's turns set going (a tool result's operation_id), followed on /v1 as the
// cards' jobs until each settles. What the conversation's live stream says of an operation (its status, and the
// progress its runner reports: stages, last lines) lands the moment it's said; behind that, each is read once, then
// held on the operation's own wait, which the server answers when it ends, and a read that drops is taken up again
// after a pause. The newer word on an operation wins. One the server doesn't have (deleted, or not this account's to
// see) is never asked about again: its card says it's gone.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { NotFound, Operation, OperationTimeout, type JsonObject, type NoClick } from 'noclick';
import type { CoordinatorJob, CoordinatorJobs, ThreadJobs } from '@/lib/threadJobs';
import { failed, obj, str, type CoordinatorToolCall } from '@/lib/toolCalls';

const WAIT_S = 50;
const RETRY_MS = 5000;

const STATUS: Record<string, string> = { succeeded: 'completed', failed: 'failed', canceled: 'cancelled', expired: 'cancelled', awaiting_human: 'waiting' };
// What an operation says beyond its status that its card reads: what it's doing and how far it got, and what a kind
// adds (a build: the workflow it builds and the question it waits on; a deploy or check: the site's address; an
// agent's job: its title, the agent and what it last told its parent), the workstream its work belongs to, and when it
// started and ended.
const CARRIED = ['summary', 'step', 'progress', 'workflow_id', 'question', 'url', 'title', 'agent_id', 'latest_update', 'workstream', 'started_at', 'finished_at'] as const;

/** An operation as the cards' job reads it, from its own JSON. */
export function jobOf(raw: JsonObject): CoordinatorJob {
    const created = str(raw, 'created_at') ?? new Date().toISOString();
    const error = str(raw, 'error') ?? str(obj(raw, 'error'), 'message');
    return {
        job_id: str(raw, 'id') ?? '',
        kind: str(raw, 'kind') ?? '',
        status: STATUS[str(raw, 'status') ?? ''] ?? 'running',
        created_at: created,
        updated_at: str(raw, 'updated_at') ?? created,
        ...(error ? { error } : {}),
        ...(raw.result !== null && raw.result !== undefined ? { result: raw.result } : {}),
        ...Object.fromEntries(CARRIED.filter((key) => raw[key] !== undefined && raw[key] !== null).map((key) => [key, raw[key]])),
    };
}

function asJob(op: Operation): CoordinatorJob {
    const updated = op.updatedAt ?? op.createdAt ?? new Date();
    return jobOf({ ...op.raw, id: op.id, updated_at: updated.toISOString(), created_at: (op.createdAt ?? updated).toISOString() });
}

const changed = (job: CoordinatorJob) => Date.parse(job.updated_at) || 0;

/** Two words on one operation: the newer one's, keeping what only the older said (a read's result). */
export function newest(a: CoordinatorJob | undefined, b: CoordinatorJob | undefined): CoordinatorJob | undefined {
    if (!a || !b) return a ?? b;
    return changed(b) >= changed(a) ? { ...a, ...b } : { ...b, ...a };
}

/** What a conversation's live stream has said of each operation, the newest word on each: a new map each time it
 *  hears something, so a card reading it redraws. */
export class PushedOperations {
    private said = new Map<string, CoordinatorJob>();
    private readonly listeners = new Set<() => void>();

    put(raw: JsonObject): void {
        const job = jobOf(raw);
        if (!job.job_id) return;
        this.said = new Map(this.said).set(job.job_id, newest(this.said.get(job.job_id), job)!);
        this.listeners.forEach((listener) => listener());
    }

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    };

    snapshot = (): ReadonlyMap<string, CoordinatorJob> => this.said;
}

/** The operation a call set going: the one its result names, or a coding job's (a change handed to an app's coding
 *  agent answers with the job, its operation inside). */
export function operationIdOf(call: CoordinatorToolCall): string | undefined {
    if (failed(call.result) || str(call.result, 'approval_id')) return undefined;
    const response = obj(call.result, 'response');
    return str(call.result, 'operation_id') ?? (str(response, 'object') === 'coding_job' ? str(response, 'operation_id') : undefined);
}

/** The held call a call's approval runs once it's approved: the operation its result names beside the approval. */
export function heldOperationOf(call: CoordinatorToolCall): string | undefined {
    return !failed(call.result) && str(call.result, 'approval_id') ? str(call.result, 'operation_id') : undefined;
}

/** The operation a held call's request started, once it ran (a domain's registration): its response is the
 *  operation, or names it. */
export function continuedBy(job: CoordinatorJob | undefined): string | undefined {
    const response = obj(obj(job, 'result'), 'response');
    return str(response, 'object') === 'operation' ? str(response, 'id') : str(response, 'operation_id');
}

function operationIds(calls: readonly CoordinatorToolCall[]): string[] {
    return [...new Set(calls.flatMap((call) => [operationIdOf(call), heldOperationOf(call)].filter((id): id is string => !!id)))];
}

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export const GONE = 'This is no longer here: it was removed, or this account can’t see it.';

/** An operation the server answers 404 for, as its card shows it: ended, and why. */
function goneJob(id: string, last: CoordinatorJob | undefined): CoordinatorJob {
    const now = new Date().toISOString();
    return { kind: '', created_at: now, ...last, job_id: id, status: 'cancelled', updated_at: now, error: GONE };
}

/** The cards' jobs on a thread whose work is /v1 operations, read with `client`, with what `pushed` has heard. */
export function operationFollower(client: NoClick, pushed: PushedOperations): ThreadJobs {
    return function useFollowedOperations(calls) {
        const [jobs, setJobs] = useState<Record<string, CoordinatorJob>>({});
        // A held call, once approved and run, carries on in the operation its request started: followed too.
        const named = useMemo(() => operationIds(calls), [calls]);
        const carriedOn = Object.values(jobs).flatMap((job) => continuedBy(job) ?? []).join(' ');
        const ids = useMemo(() => [...new Set([...named, ...(carriedOn ? carriedOn.split(' ') : [])])], [named, carriedOn]);
        const heard = useSyncExternalStore(pushed.subscribe, pushed.snapshot, pushed.snapshot);
        const following = useRef(new Set<string>());
        const stopped = useRef(false);

        useEffect(() => {
            stopped.current = false;
            return () => {
                stopped.current = true;
            };
        }, []);

        useEffect(() => {
            for (const id of ids) {
                if (following.current.has(id)) continue;
                following.current.add(id);
                const op = Operation.fromId(id, { client });
                void (async () => {
                    while (!stopped.current) {
                        try {
                            if (op.isHydrated) await op.wait({ timeoutS: WAIT_S });
                            else await op.refresh();
                        } catch (error) {
                            // Asking again can't bring back what the server doesn't have.
                            if (error instanceof NotFound) {
                                if (!stopped.current) setJobs((all) => ({ ...all, [id]: goneJob(id, all[id]) }));
                                return;
                            }
                            // A failed operation ends its wait with its error, and a wait the server held to its end
                            // is taken up again; anything else is a read that dropped.
                            if (!op.done && !(error instanceof OperationTimeout)) {
                                console.warn('[coordinator] operation read failed:', error);
                                await pause(RETRY_MS);
                            }
                        }
                        if (op.isHydrated && !stopped.current) setJobs((all) => ({ ...all, [id]: asJob(op) }));
                        if (op.done) return;
                    }
                })();
            }
        }, [ids]);

        return useMemo<CoordinatorJobs>(() => ({ live: true, get: (id) => (id ? newest(jobs[id], heard.get(id)) : undefined) }), [jobs, heard]);
    };
}
