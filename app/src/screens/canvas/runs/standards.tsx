// What stands in the canvas's run slots (../slots.ts) when no host fills them, over the platform API alone with the
// client a `ClientProvider` above gives:
//
// - the run log's pages and counts: `GET /v1/workflows/{id}/runs` and `.../runs/counts`. The API lists runs by how
//   they ended and nothing more yet, so the log is narrowed by that alone and says so (`narrows`);
// - a step's stored outputs: `GET .../steps/{step}/outputs`, then each whole (`.../outputs/{run}?full=true`);
// - what a step of a type outputs: `GET /v1/step_types/{type}/output_shape`;
// - a run's results: each step's status, error and output from `GET .../runs/{run}` (RunSteps.tsx).
//
// Nothing is saved under a name (a pinned output is the step's mock, an edit of the workflow), no builder is asked
// about a failed step, and a fix that's done in NoClick's app (adding funds, raising the spending cap) opens there.
// The SDK loads with the first read (../standardsSdk.ts), and the results view with the first run opened.
import { lazy, Suspense, useContext, useMemo } from 'react';
import type { NoClick } from 'noclick';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { addFundsUrl, billingSettingsUrl, NOCLICK_SITE } from '@/screens/console/lib/site';
import { useClient } from '@/sdk/client';
import type { ErrorAction } from './ErrorActionButton';
import type { FixAct, OutputHistoryEntry, RunLogNarrows, RunLogPage, RunLogQuery, RunReads, RunResultsProps, SavedOutputs } from './reads';
import type { ExecutionCounts, ExecutionStatus, ExecutionTrigger, WorkflowExecutionLog } from './RunLog';
import type { SuggestedRef } from './SuggestedRefsTab';

type Json = Record<string, unknown>;

/** What the API narrows a listing of runs by: how they ended, where a run that waits lists as running. */
const V1_NARROWS: RunLogNarrows = { waiting: false, source: false, search: false };

/** A run's status as the log names it, from the API's. */
const LOG_STATUS: Record<string, ExecutionStatus> = { succeeded: 'success', failed: 'error', running: 'running' };
/** The API's status for each of the log's the API tells apart. */
const API_STATUS: Partial<Record<ExecutionStatus, string>> = { success: 'succeeded', error: 'failed', running: 'running' };
/** How a run started as the log names it, from the API's `source`: in the app by hand, on a schedule, from code (the
 *  API or the workflow's endpoint) or by an event at one of its triggers. */
const LOG_SOURCE: Record<string, ExecutionTrigger> = { app: 'manual', schedule: 'cron', api: 'run', endpoint: 'run', trigger: 'event' };
/** What a run says in the log when it has no error to say. */
const SAID: Record<ExecutionStatus, string> = { success: 'Completed.', running: 'Running…', waiting: 'Waiting.', error: 'Failed.' };

const text = (value: unknown): string | null => (typeof value === 'string' && value ? value : null);

/** A run the API lists, as a row of the log. */
export function logOfRun(run: Json): WorkflowExecutionLog {
    const status = LOG_STATUS[String(run.status)] ?? 'running';
    const started = Date.parse(String(run.started_at));
    const finished = text(run.finished_at) ? Date.parse(String(run.finished_at)) : NaN;
    const error = run.error && typeof run.error === 'object' ? text((run.error as Json).message) : text(run.error);
    return {
        id: String(run.id),
        timestamp: new Date(started),
        status,
        message: error ?? SAID[status],
        duration: Number.isNaN(finished) ? undefined : finished - started,
        trigger: LOG_SOURCE[String(run.source)] ?? 'manual',
    };
}

/** The API's query for a page of the log; a narrowing the API hasn't is refused out loud (the log never offers it). */
function runsQuery({ limit, filters, cursor }: RunLogQuery): Record<string, string | number | undefined> {
    if (filters.query) throw new Error('Searching runs isn’t on the API yet.');
    if (filters.trigger !== 'all') throw new Error('Narrowing runs by how they started isn’t on the API yet.');
    const status = filters.status === 'all' ? undefined : API_STATUS[filters.status];
    if (filters.status !== 'all' && !status) throw new Error('The API lists a run that waits as running.');
    return { limit, status, cursor: typeof cursor === 'string' ? cursor : undefined };
}

const path = (workflowId: string) => `/v1/workflows/${encodeURIComponent(workflowId)}`;

function v1RunReads(client: NoClick): RunReads {
    const sdk = () => import('../standardsSdk');
    return {
        narrows: V1_NARROWS,
        runs: async (workflowId, query): Promise<RunLogPage> => {
            const page = await client.request<Json>('GET', `${path(workflowId)}/runs`, { query: runsQuery(query) });
            const data = Array.isArray(page.data) ? (page.data as Json[]) : [];
            return { logs: data.map(logOfRun), next: text(page.next_cursor) };
        },
        counts: async (workflowId): Promise<ExecutionCounts> => {
            const { Workflow } = await sdk();
            const counted = await Workflow.fromId(workflowId, { client }).runCounts();
            const byTrigger: ExecutionCounts['byTrigger'] = {};
            for (const [source, n] of Object.entries(counted.bySource)) {
                const trigger = LOG_SOURCE[source] ?? 'manual';
                byTrigger[trigger] = (byTrigger[trigger] ?? 0) + n;
            }
            return {
                total: counted.total,
                byStatus: { success: counted.byStatus.succeeded, error: counted.byStatus.failed, running: counted.byStatus.running, waiting: 0 },
                byTrigger,
            };
        },
        history: async (workflowId, stepId, limit): Promise<OutputHistoryEntry[]> => {
            const { Workflow } = await sdk();
            const step = Workflow.fromId(workflowId, { client }).step(stepId);
            // The listing carries a line of each output; the history shows each whole.
            const listed = await step.outputs({ limit });
            return Promise.all(
                listed.map(async (row) => ({
                    execution_id: row.runId,
                    created_at: row.createdAt?.toISOString() ?? '',
                    output: (await step.output(row.runId, { full: true, iteration: row.iteration ?? undefined })).output,
                }))
            );
        },
        outputShape: async (type, operation) => {
            const { stepOutputShape } = await sdk();
            const shape = await stepOutputShape(type, { operation, client });
            return { schema: shape.shape as never, suggestedRefs: shape.suggestedRefs as SuggestedRef[] | null };
        },
    };
}

const reads = new WeakMap<NoClick, RunReads>();

/** The canvas's run reads on /v1, one set per client. */
export function useV1RunReads(): RunReads {
    const client = useClient();
    return useMemo(() => {
        let found = reads.get(client);
        if (!found) reads.set(client, (found = v1RunReads(client)));
        return found;
    }, [client]);
}

// ── outputs saved under a name ──────────────────────────────────────────────

const NOTHING_SAVED: SavedOutputs = { saved: [], save: null, remove: async () => undefined, share: null, dialogs: null };

/** No output is saved under a name here: the one shown is pinned as the step's mock, which the workflow keeps. */
export function useNothingSaved(): SavedOutputs {
    return NOTHING_SAVED;
}

// ── what can be done about a failed step ────────────────────────────────────

/** Adding funds and the spending cap are NoClick's app's, opened there; a step's account is connected from the step. */
export function useV1Fix(): (action: ErrorAction, nodeId: string) => FixAct | null {
    const site = useContext(ConsoleContext)?.site ?? NOCLICK_SITE;
    return useMemo(
        () => (action) => {
            if (action.type === 'open_topup') return { href: addFundsUrl(site) };
            if (action.type === 'open_billing') return { href: billingSettingsUrl(site) };
            return null;
        },
        [site]
    );
}

// ── a run's results ─────────────────────────────────────────────────────────

// Loaded with the first run opened: it carries the output viewer, which a host that draws its own results never needs.
const RunSteps = lazy(() => import('./RunSteps'));

/** A run's results as the API gives them: what each step did. */
export function RunStepsOnV1(props: RunResultsProps) {
    if (!props.runId) return null;
    return (
        <Suspense fallback={null}>
            <RunSteps {...props} />
        </Suspense>
    );
}
