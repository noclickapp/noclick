// Running a workflow from the canvas over the platform API, with no host: the whole workflow from its trigger, from one
// step on, or one step alone (`POST /v1/workflows/{id}/runs`, with `from_step` and `only`), and stopping a run
// (`POST .../runs/{run}/stop`).
//
// A run reads the saved workflow, never what the canvas holds unsaved: the canvas's pending save lands first, and a
// workflow whose changes can't be saved isn't run. While a run goes, each step shows how it stands: the account's
// change stream says a step of a run of this workflow moved (a `workflow_run` change), the run is read again
// (`GET .../runs/{run}`) and its steps' states go onto the canvas's steps, whoever started the run (a webhook's run
// shows too). When a run ends, the steps it touched take their outputs whole (`GET .../outputs?full=true`: a run's own
// read cuts long ones short). Without the stream (a host with none) a run started here still ends on its operation's
// wait, with its steps' final states.
//
// NoClick's app runs through its own transports instead (an editor's run carries its unsaved graph, a form's inputs, a
// chat's turn), so this is the canvas's running where no host has its own.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Node } from '@xyflow/react';
import { NoClickError, OperationCanceled, OperationTimeout, Workflow, type NoClick, type Operation, type RunStep, type WorkflowRun } from 'noclick';
import { errorText } from '@/screens/console/lib/errorText';
import { useWorkLive } from '@/sdk/live';
import { useReportHeld } from '@/sdk/held';
import { applyNodeUpdate } from '../applyNodeUpdate';
import { whenGraphSaved } from '../graph/liveGraphStore';

/** How long one wait on a run's operation runs before it checks the canvas still shows the workflow. */
const WAIT_S = 30;

type SetNodes = (update: (nodes: Node[]) => Node[]) => void;

/** A step's state on the canvas, from its status in a run. */
const STATE: Record<string, string> = { running: 'running', succeeded: 'completed', failed: 'error', skipped: 'skipped' };

/** What a step of a run shows on its node: how it stands now, its error, and once it ended, how its last run went. */
function stepExtras(step: RunStep, run: WorkflowRun): Record<string, unknown> | null {
    const state = STATE[step.status];
    if (!state) return null;
    const extras: Record<string, unknown> = { executionState: state, error: step.error ?? undefined, errorAction: undefined, _executionId: run.id };
    if (state === 'running') extras.progress = undefined;
    if (state === 'completed' || state === 'error') {
        extras._lastRunStatus = state;
        extras._lastRunAt = (run.finishedAt ?? new Date()).getTime();
        extras._lastRunError = state === 'error' ? (step.error ?? undefined) : undefined;
    }
    return extras;
}

/** Puts a run's steps as they stand onto the canvas's steps. */
export function applyRunSteps(setNodes: SetNodes, run: WorkflowRun): void {
    const steps = new Map(run.steps.map((step) => [step.id, step]));
    if (!steps.size) return;
    setNodes((nodes) =>
        nodes.map((node) => {
            const step = steps.get(node.id);
            const extras = step && stepExtras(step, run);
            return extras ? applyNodeUpdate(node, { extras }) : node;
        })
    );
}

/** A run ended: its steps rest (their last-run marks stay), and those it ran take their latest outputs, whole; nothing
 *  once the canvas no longer shows the workflow (`shown`). */
async function settleRun(client: NoClick, workflowId: string, setNodes: SetNodes, run: WorkflowRun, shown: () => boolean): Promise<void> {
    const ran = run.steps.filter((step) => step.status === 'succeeded' || step.status === 'failed').map((step) => step.id);
    const latest = ran.length ? await Workflow.fromId(workflowId, { client }).latestOutputs({ steps: ran, full: true }) : null;
    if (!shown()) return;
    const at = Date.now();
    setNodes((nodes) =>
        nodes.map((node) => {
            if (node.data?._executionId !== run.id) return node;
            const output = latest?.outputs[node.id];
            return applyNodeUpdate(node, {
                extras: { executionState: 'idle', ...(output !== undefined ? { output, outputTimestamp: at } : {}) },
            });
        })
    );
}

export interface RunOptions {
    /** Run this step and what comes after it, the steps before it giving what they last stored. */
    fromStep?: string;
    /** With `fromStep`: that step alone. */
    only?: boolean;
}

export interface WorkflowRuns {
    /** The runs of this workflow under way, as far as the canvas knows: the one started here, and any the change
     *  stream named. */
    running: string[];
    /** True from a run asked for here until it ends. */
    busy: boolean;
    /** Why the last run asked for here didn't start, or how it failed; null once another starts. */
    error: string | null;
    /** Starts a run and follows it; resolves once it ended (or was refused: `error` says why). */
    run: (options?: RunOptions) => Promise<void>;
    /** Stops the runs under way: each the canvas knows of, and the one started here even before it was named. */
    stop: () => Promise<void>;
}

/** The run id a failed run's error names. */
function failedRunId(error: unknown): string | null {
    const id = error instanceof NoClickError ? (error.details as Record<string, unknown> | null | undefined)?.run_id : null;
    return typeof id === 'string' ? id : null;
}

/** Running `workflowId` and following its runs onto the canvas's steps (`setNodes`, the graph store's). `onRunMoved`
 *  hears each run that started or ended (the run log reads its counts again). */
export function useWorkflowRuns({
    client,
    workflowId,
    setNodes,
    onRunMoved,
}: {
    client: NoClick;
    workflowId: string;
    setNodes: SetNodes;
    onRunMoved?: (run: WorkflowRun) => void;
}): WorkflowRuns {
    const live = useWorkLive();
    const [running, setRunning] = useState<string[]>([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    // The workflow shown now; null once the canvas is gone, when nothing more is applied.
    const shown = useRef<string | null>(null);
    const moved = useRef(onRunMoved);
    moved.current = onRunMoved;
    // Runs whose end was already taken (a run's end is heard twice where it was started here: the stream's and its
    // operation's).
    const ended = useRef(new Set<string>());
    // The newest read of each run: an older one landing late changes nothing.
    const reading = useRef(new Map<string, number>());
    // The run started here, until it ends.
    const started = useRef<Operation<WorkflowRun> | null>(null);

    useEffect(() => {
        shown.current = workflowId;
        ended.current = new Set();
        reading.current = new Map();
        started.current = null;
        setRunning([]);
        setBusy(false);
        setError(null);
        return () => void (shown.current = null);
    }, [workflowId]);

    /** Reads a run and puts its steps on the canvas; its end, once, settles it. */
    const take = useCallback(
        async (runId: string): Promise<void> => {
            const token = (reading.current.get(runId) ?? 0) + 1;
            reading.current.set(runId, token);
            const run = await Workflow.fromId(workflowId, { client }).getRun(runId);
            if (shown.current !== workflowId || reading.current.get(runId) !== token) return;
            if (run.status === 'running') {
                applyRunSteps(setNodes, run);
                setRunning((ids) => (ids.includes(runId) ? ids : [...ids, runId]));
                return;
            }
            if (ended.current.has(runId)) return;
            ended.current.add(runId);
            applyRunSteps(setNodes, run);
            setRunning((ids) => ids.filter((id) => id !== runId));
            await settleRun(client, workflowId, setNodes, run, () => shown.current === workflowId);
            moved.current?.(run);
        },
        [client, workflowId, setNodes]
    );

    // A step of a run of this workflow moved, or a run of it started or ended; and when the stream lost its place, the
    // runs known to be under way are read again.
    const known = useRef(running);
    known.current = running;
    useEffect(() => {
        const read = (runId: string) => void take(runId).catch((e: unknown) => console.error('[runs] A run that moved couldn’t be read:', e));
        const offChange = live.on('platform:resource', (frame) => {
            if (frame.kind === 'workflow_run' && frame.parent_id === workflowId) read(frame.id);
        });
        const offReset = live.on('reset', () => known.current.forEach(read));
        return () => {
            offChange();
            offReset();
        };
    }, [live, workflowId, take]);

    const follow = useCallback(
        async (op: Operation<WorkflowRun>): Promise<void> => {
            while (shown.current === workflowId) {
                try {
                    const run = await op.wait({ timeoutS: WAIT_S });
                    await take(run.id);
                    return;
                } catch (e) {
                    if (e instanceof OperationTimeout) continue;
                    const runId = failedRunId(e);
                    if (runId) await take(runId);
                    if (!(e instanceof OperationCanceled) && shown.current === workflowId) setError(errorText(e));
                    return;
                }
            }
        },
        [workflowId, take]
    );

    const run = useCallback(
        async (options: RunOptions = {}): Promise<void> => {
            setError(null);
            setBusy(true);
            try {
                if (!(await whenGraphSaved(workflowId))) {
                    setError('This didn’t run: the workflow’s last changes couldn’t be saved, and a run reads the saved workflow.');
                    return;
                }
                const op = await Workflow.fromId(workflowId, { client }).run({}, { fromStep: options.fromStep, only: options.only });
                started.current = op;
                await follow(op);
            } catch (e) {
                if (shown.current === workflowId) setError(errorText(e));
            } finally {
                started.current = null;
                if (shown.current === workflowId) setBusy(false);
            }
        },
        [client, workflowId, follow]
    );

    // Stopping a run can wait for the account's owner (a key NoClick gave this app): a toast follows it.
    const reportHeld = useReportHeld({ client });
    const stop = useCallback(async (): Promise<void> => {
        const workflow = Workflow.fromId(workflowId, { client });
        try {
            // A run started here that the stream hasn't named yet stops as its operation's cancel.
            if (!running.length) await started.current?.cancel();
            await Promise.all(running.map((runId) => workflow.stopRun(runId).then((stopped) => take(stopped.id))));
        } catch (e) {
            if (reportHeld(e, 'Stop the run')) return;
            if (shown.current === workflowId) setError(errorText(e));
        }
    }, [client, workflowId, running, take, reportHeld]);

    return { running, busy, error, run, stop };
}
