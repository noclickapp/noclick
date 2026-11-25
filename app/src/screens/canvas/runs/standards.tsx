// What stands in the canvas's run slots (../slots.ts) when no host fills them, over the platform API alone with the
// client a `ClientProvider` above gives:
//
// - the run log's pages and counts: `GET /v1/workflows/{id}/runs` and `.../runs/counts`, narrowed as the log narrows
//   them: by how a run ended, the runs that wait apart from those that run, how a run started and text in its error;
// - a step's stored outputs: `GET .../steps/{step}/outputs`, then each whole (`.../outputs/{run}?full=true`);
// - what a step of a type outputs: `GET /v1/step_types/{type}/output_shape`;
// - a run's results: each step's status, error and output from `GET .../runs/{run}` (RunSteps.tsx).
//
// Nothing is saved under a name (a pinned output is the step's mock, an edit of the workflow), no builder is asked
// about a failed step, and a fix that's done in NoClick's app (adding funds, raising the spending cap) opens there.
// The SDK loads with the first read (../standardsSdk.ts), and the results view with the first run opened.
import { lazy, Suspense, useContext, useMemo } from 'react';
import type { NoClick, PageOptions, WorkflowRunSource, WorkflowRunStatus, WorkflowRunTrigger, WorkflowRunsOptions } from 'noclick';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { addFundsUrl, billingSettingsUrl, NOCLICK_SITE } from '@/screens/console/lib/site';
import { useClient } from '@/sdk/client';
import type { ErrorAction } from './ErrorActionButton';
import { NARROWS_EVERYTHING, type FixAct, type OutputHistoryEntry, type RunLogPage, type RunLogQuery, type RunReads, type RunResultsProps, type SavedOutputs } from './reads';
import type { ExecutionCounts, ExecutionStatus, ExecutionTrigger, WorkflowExecutionLog } from './RunLog';
import type { SuggestedRef } from './SuggestedRefsTab';

type Json = Record<string, unknown>;

/** A run's status as the log names it, from the API's; a running run that waits (`waiting_on`) is the log's waiting. */
const LOG_STATUS: Record<string, ExecutionStatus> = { succeeded: 'success', failed: 'error', running: 'running' };
/** The API's narrowing for each of the log's statuses: a run that waits lists as running there, told apart by
 *  `waiting`. */
const API_STATUS: Record<ExecutionStatus, { status: WorkflowRunStatus; waiting?: boolean }> = {
    success: { status: 'succeeded' },
    error: { status: 'failed' },
    running: { status: 'running', waiting: false },
    waiting: { status: 'running', waiting: true },
};
/** How a run started as the log names it, from the API's `source`: in the app by hand, on a schedule, from code (the
 *  API or the workflow's endpoint) or by an event at one of its triggers, whose kind `trigger` names. */
const LOG_SOURCE: Record<string, ExecutionTrigger> = { app: 'manual', schedule: 'cron', api: 'run', endpoint: 'run', trigger: 'event' };
/** The kinds of event the log has a name of its own for; any other is an event. */
const LOG_TRIGGER: Record<string, ExecutionTrigger> = { webhook: 'webhook', email: 'email' };
/** The API's narrowing for each way of starting the log narrows by: its `source`, or the kind of event (`trigger`).
 *  None for a form's: the API has no word for it, so no run is one. */
const API_STARTED: Partial<Record<ExecutionTrigger, { source?: WorkflowRunSource[]; trigger?: WorkflowRunTrigger }>> = {
    manual: { source: ['app'] },
    cron: { source: ['schedule'] },
    run: { source: ['api', 'endpoint'] },
    webhook: { trigger: 'webhook' },
    email: { trigger: 'email' },
};

/** How a run started, as the log names it. */
function startedBy(source: unknown, trigger: unknown): ExecutionTrigger {
    if (source === 'trigger') return LOG_TRIGGER[String(trigger)] ?? 'event';
    return LOG_SOURCE[String(source)] ?? 'manual';
}
/** What a run says in the log when it has no error to say. */
const SAID: Record<ExecutionStatus, string> = { success: 'Completed.', running: 'Running…', waiting: 'Waiting.', error: 'Failed.' };

const text = (value: unknown): string | null => (typeof value === 'string' && value ? value : null);

/** A run the API lists, as a row of the log. */
export function logOfRun(run: Json): WorkflowExecutionLog {
    const status = text(run.waiting_on) ? 'waiting' : (LOG_STATUS[String(run.status)] ?? 'running');
    const started = Date.parse(String(run.started_at));
    const finished = text(run.finished_at) ? Date.parse(String(run.finished_at)) : NaN;
    const error = run.error && typeof run.error === 'object' ? text((run.error as Json).message) : text(run.error);
    return {
        id: String(run.id),
        timestamp: new Date(started),
        status,
        message: error ?? SAID[status],
        duration: Number.isNaN(finished) ? undefined : finished - started,
        trigger: startedBy(run.source, run.trigger),
    };
}

/** The API's query for a page of the log; null for a narrowing no run can meet (a way of starting the API has no word
 *  for), whose page is empty. */
function runsQuery({ limit, filters, cursor }: RunLogQuery): (Omit<WorkflowRunsOptions, 'limit'> & PageOptions) | null {
    const started = filters.trigger === 'all' ? {} : API_STARTED[filters.trigger];
    if (!started) return null;
    const ended = filters.status === 'all' ? undefined : API_STATUS[filters.status];
    return {
        limit,
        status: ended?.status,
        waiting: ended?.waiting,
        source: started.source,
        trigger: started.trigger,
        search: filters.query || undefined,
        cursor: typeof cursor === 'string' ? cursor : undefined,
    };
}

function v1RunReads(client: NoClick): RunReads {
    const sdk = () => import('../standardsSdk');
    return {
        narrows: NARROWS_EVERYTHING,
        runs: async (workflowId, query): Promise<RunLogPage> => {
            const narrowed = runsQuery(query);
            if (!narrowed) return { logs: [], next: null };
            const { Workflow } = await sdk();
            const page = await Workflow.fromId(workflowId, { client }).runsPage(narrowed);
            return { logs: page.data.map((run) => logOfRun(run.raw)), next: page.nextCursor };
        },
        counts: async (workflowId): Promise<ExecutionCounts> => {
            const { Workflow } = await sdk();
            const counted = await Workflow.fromId(workflowId, { client }).runCounts();
            const byTrigger: ExecutionCounts['byTrigger'] = {};
            const add = (started: ExecutionTrigger, n: number) => {
                byTrigger[started] = (byTrigger[started] ?? 0) + n;
            };
            // The runs an event started are counted by its kind, the rest by how they started.
            for (const [source, n] of Object.entries(counted.bySource)) if (source !== 'trigger') add(startedBy(source, null), n);
            for (const [trigger, n] of Object.entries(counted.byTrigger)) add(startedBy('trigger', trigger), n);
            return {
                total: counted.total,
                byStatus: {
                    success: counted.byStatus.succeeded,
                    error: counted.byStatus.failed,
                    running: counted.byStatus.running - counted.waiting,
                    waiting: counted.waiting,
                },
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
