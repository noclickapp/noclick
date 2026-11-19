// The work an agent's turns set going (a build, a request to another agent, a long action), as a thread's cards follow
// it to its end: each job read back by its id, whoever reads it (the API's operations, or a host's own source).
import type { CoordinatorToolCall, JsonObject } from '@/lib/toolCalls';

/** One job as a card reads it. */
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

export function isActiveJob(job: CoordinatorJob | undefined): boolean {
    return !!job && ACTIVE.has(job.status);
}

export interface CoordinatorJobs {
    /** Whether jobs are read back at all. */
    live: boolean;
    get(jobId: string | undefined): CoordinatorJob | undefined;
}

/** How a thread follows the work its turns' tool calls started, read from those calls; `nudge` changes with each turn. */
export type ThreadJobs = (calls: readonly CoordinatorToolCall[], nudge: unknown) => CoordinatorJobs;
