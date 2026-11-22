// A workflow's runs on the canvas this app draws on its own (WorkflowCanvas.tsx): a button that runs the workflow and
// stops what's running (useRun.ts: the canvas's pending save lands first, and each step shows how it stands as the run
// goes), the pill that opens the run log (RunLog.tsx, its pages and counts through `canvas.runs.reads`, read when the
// workflow opens and again when a run ends), and one run's results opened from a row (`canvas.runs.results`).
import { useCallback, useState, type ReactNode } from 'react';
import type { Node } from '@xyflow/react';
import { Play, Square, X } from 'lucide-react';
import type { NoClick } from 'noclick';
import { useSlot } from '@/slots';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { MENU_SURFACE } from '@/ui/menus';
import { cn } from '@/ui/utils';
import { RUN_READS, RUN_RESULTS } from '../slots';
import { RunHistoryPill } from './RunHistoryPill';
import { WorkflowExecutionLogs, type WorkflowExecutionLog } from './RunLog';
import { useWorkflowRuns } from './useRun';
import { useRunLog } from './useRunLog';

export interface CanvasRuns {
    /** Runs the workflow, or stops what's running: for the canvas's toolbar. */
    button: ReactNode;
    /** The pill, the run log it opens, a run's results and why a run didn't start: drawn over the canvas. */
    element: ReactNode;
}

/** The runs of `workflowId` on its canvas, once it's open (`open`): running it onto the canvas's steps (`setNodes`, the
 *  graph store's) and showing its log and one run's results. `onOpenStep` opens a step of a run on the canvas. */
export function useCanvasRuns({
    client,
    workflowId,
    open,
    setNodes,
    onOpenStep,
}: {
    client: NoClick;
    workflowId: string;
    open: boolean;
    setNodes: (update: (nodes: Node[]) => Node[]) => void;
    onOpenStep?: (stepId: string) => void;
}): CanvasRuns {
    const reads = useSlot(RUN_READS).useRunReads();
    const Results = useSlot(RUN_RESULTS);
    const [logs, setLogs] = useState<WorkflowExecutionLog[]>([]);
    const log = useRunLog({ workflowId: open ? workflowId : undefined, reads, setLogs });
    const { nextCursorRef, fetchPage, countsChanged } = log;
    // A run ended: the log starts over from its newest run, and its counts are read again.
    const onRunMoved = useCallback(() => {
        nextCursorRef.current = null;
        void fetchPage(null);
        countsChanged();
    }, [nextCursorRef, fetchPage, countsChanged]);
    const runs = useWorkflowRuns({ client, workflowId, setNodes, onRunMoved });
    const going = runs.busy || runs.running.length > 0;

    const [logShown, setLogShown] = useState(false);
    const [opened, setOpened] = useState<WorkflowExecutionLog | null>(null);
    const closeResults = useCallback(() => setOpened(null), []);

    const button = going ? (
        <button type="button" className={BUTTON_SECONDARY} onClick={() => void runs.stop()}>
            <Square className="h-4 w-4" /> Stop
        </button>
    ) : (
        <button type="button" className={BUTTON_PRIMARY} onClick={() => void runs.run()}>
            <Play className="h-4 w-4" /> Run
        </button>
    );

    const element = (
        <>
            <RunHistoryPill logs={logs} onOpen={() => setLogShown((shown) => !shown)} />
            {runs.error && !logShown && (
                <p role="alert" className="absolute left-4 top-16 z-20 max-w-md rounded-xl bg-card px-4 py-2 text-[13px] text-red-600 shadow-sm ring-1 ring-border dark:text-red-400">
                    {runs.error}
                </p>
            )}
            {logShown && (
                <div
                    role="dialog"
                    aria-label="Runs"
                    className={cn(MENU_SURFACE, 'absolute left-4 top-16 z-20 flex max-h-[min(560px,calc(100%-5rem))] w-[760px] max-w-[calc(100%-2rem)] flex-col overflow-hidden rounded-2xl p-3')}
                >
                    <div className="mb-2 flex shrink-0 items-center justify-between">
                        <h2 className="text-[13.5px] font-medium text-foreground">Runs</h2>
                        <button type="button" aria-label="Close" onClick={() => setLogShown(false)} className="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                    {(runs.error ?? log.error) && (
                        <p role="alert" className="mb-2 shrink-0 text-[13px] text-red-600 dark:text-red-400">
                            {runs.error ?? log.error}
                        </p>
                    )}
                    <WorkflowExecutionLogs
                        logs={logs}
                        counts={log.counts}
                        hasMore={log.hasMore}
                        loading={log.loading}
                        onFiltersChange={log.onFiltersChange}
                        onLoadMore={log.onLoadMore}
                        onRowClick={setOpened}
                        narrows={reads.narrows}
                    />
                </div>
            )}
            <Results workflowId={workflowId} runId={opened?.id ?? null} run={opened ?? undefined} onClose={closeResults} onOpenStep={onOpenStep} />
        </>
    );

    return { button, element };
}
