// The canvas's Story popup (RunResultsDialog) for one run opened from the
// Dashboard: loads the stored snapshot through the shared run-story loader and
// shows the same native-frame story the canvas shows, so there is one run
// viewer. Whatever the hosted edition adds to the popup (the agent-inputs rail)
// arrives as story extras and is spread onto the dialog — this file ships to the
// open edition unchanged. Node clicks jump to the node on its workflow canvas.
import { useEffect, useState } from 'react';
import { RunResultsDialog } from '~/components/workflow/RunResultsDialog';
import { DEFAULT_TRIGGER, type ExecutionTrigger, type WorkflowExecutionLog } from '~/components/workflow/WorkflowExecutionLogs';
import { loadRunStory, type RunStory } from '~/lib/runResults';
import { goToWorkflowNode } from '~/lib/navigation';
import type { RunRow } from '~/components/dashboard/types';

const KNOWN_TRIGGERS = new Set<ExecutionTrigger>(['manual', 'cron', 'webhook', 'email', 'form', 'run']);

/** The switcher row for the run being shown — the popup's header reads the
 *  start time and duration off it. */
function toExecutionLog(run: RunRow): WorkflowExecutionLog {
    return {
        id: run.id,
        timestamp: new Date(run.startedAt),
        status: run.status === 'error' ? 'error' : run.status === 'completed' ? 'success' : run.status === 'running' ? 'running' : 'waiting',
        message: run.error ?? '',
        duration: run.durationMs ?? undefined,
        nodesExecuted: run.nodesExecuted,
        trigger: KNOWN_TRIGGERS.has(run.trigger as ExecutionTrigger) ? (run.trigger as ExecutionTrigger) : DEFAULT_TRIGGER,
    };
}

export function DashboardRunDialog({ run, onClose }: { run: RunRow; onClose: () => void }) {
    const [story, setStory] = useState<RunStory | null>(null);
    useEffect(() => {
        let cancelled = false;
        setStory(null);
        loadRunStory(run.workflow.id, run.id)
            .then((s) => {
                if (!cancelled) setStory(s);
            })
            .catch(() => {
                if (!cancelled) setStory({ results: [], nodes: [], extras: {} });
            });
        return () => {
            cancelled = true;
        };
    }, [run.workflow.id, run.id]);
    return (
        <RunResultsDialog
            {...(story?.extras ?? {})}
            results={story?.results ?? []}
            loading={story === null}
            runs={[toExecutionLog(run)]}
            currentExecId={run.id}
            hasMore={false}
            loadingMore={false}
            onLoadMore={() => {}}
            onSelectRun={() => {}}
            onOpenConfig={(nodeId) => {
                onClose();
                goToWorkflowNode(run.workflow.id, nodeId);
            }}
            onClose={onClose}
            workflowName={run.workflow.name}
        />
    );
}
