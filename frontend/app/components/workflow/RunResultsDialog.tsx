// Post-run results modal: opens when a manual workflow run finishes and for
// any past run via the run-history pill. Renders the Story view (came in →
// what the agent did → what went out → also ran): the trigger event and the
// agent's sends in their apps' native frames, the tool calls as a quiet log —
// see components/design/run-results/. This file adapts FlowCanvas's data
// (NodeRunResult rows and execution logs) into that view.
import { useMemo } from 'react';
import { Inbox, Loader2 } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle } from '~/components/ui/dialog';
import {
    buildRunStory,
    type StoryNodeResult,
} from '~/components/design/run-results/runStory';
import {
    RunSwitcher,
    StoryVariant,
    useStoryIcons,
    type RunSwitcherData,
    type SwitcherRun,
} from '~/components/design/run-results/variants';
import {
    DEFAULT_TRIGGER,
    formatDuration,
    type ExecutionTrigger,
    type WorkflowExecutionLog,
} from './WorkflowExecutionLogs';

export interface NodeRunResult extends StoryNodeResult {
    /** Serialized brand icon — kept for callers that render node rows
        directly; the Story view resolves marks from the icon registry. */
    iconHtml?: string;
    iconColor?: string;
}

/** The execution log's trigger kinds → switcher-row tooltips. Provider-level
    identity (which app's webhook) isn't stored on the log row yet; when the
    backend stamps it, map it to the provider slug here for a brand mark. */
const TRIGGER_TOOLTIP: Record<ExecutionTrigger, string> = {
    manual: 'Started manually',
    cron: 'On a schedule',
    webhook: 'Fired by a webhook',
    email: 'Inbound email',
    form: 'Form submission',
    run: 'Started from a run',
};

function toSwitcherRun(log: WorkflowExecutionLog): SwitcherRun {
    const trigger = log.trigger ?? DEFAULT_TRIGGER;
    return {
        id: log.id,
        iso: log.timestamp.toISOString(),
        failed: log.status === 'error',
        running: log.status === 'running' || log.status === 'waiting',
        durationLabel: log.duration !== undefined ? formatDuration(log.duration) : undefined,
        triggerSlug: trigger,
        triggerTooltip: TRIGGER_TOOLTIP[trigger],
        nodes: log.nodesExecuted,
        error: log.status === 'error' ? log.message : undefined,
    };
}

interface RunResultsDialogProps {
    results: NodeRunResult[];
    onClose: () => void;
    /** Open a node's config panel (expanded), like the trigger-info popup. */
    onOpenConfig: (nodeId: string) => void;
    /** Stop auto-showing this popup after future runs (re-enable in Settings).
     *  Omitted by hosts that never auto-show (the Dashboard). */
    onDontShowAgain?: () => void;
    /** Loaded runs (newest first) for the in-popup run-switcher. */
    runs: WorkflowExecutionLog[];
    /** Execution whose results are currently shown. */
    currentExecId: string | null;
    /** True while a switched run's results are loading. */
    loading: boolean;
    /** Whether more runs can be paged into the switcher. */
    hasMore: boolean;
    /** True while the switcher's next page of runs is loading. */
    loadingMore: boolean;
    /** Page in more runs for the switcher. */
    onLoadMore: () => void;
    /** Load a different run's results into this popup. */
    onSelectRun: (log: WorkflowExecutionLog) => void;
    /** Header title — the run is ABOUT this workflow. */
    workflowName?: string;
}

export function RunResultsDialog({
    results, onClose, onOpenConfig, onDontShowAgain,
    runs, currentExecId, loading, hasMore, loadingMore, onLoadMore, onSelectRun,
    workflowName,
}: RunResultsDialogProps) {
    const current = runs.find((r) => r.id === currentExecId);
    const story = useMemo(
        () =>
            buildRunStory({
                results,
                workflowName: workflowName || 'Run results',
                startedAt: current?.timestamp.toISOString(),
                durationMs: current?.duration,
            }),
        [results, workflowName, current]
    );
    const icons = useStoryIcons(story);
    const switcher: RunSwitcherData = useMemo(
        () => ({
            runs: runs.map(toSwitcherRun),
            currentId: currentExecId,
            latestId: runs[0]?.id,
            hasMore,
            loadingMore,
            onLoadMore,
            onSelect: (id) => {
                const log = runs.find((r) => r.id === id);
                if (log && log.id !== currentExecId) onSelectRun(log);
            },
        }),
        [runs, currentExecId, hasMore, loadingMore, onLoadMore, onSelectRun]
    );
    return (
        <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
            <DialogContent
                className="flex max-w-none flex-col gap-0 overflow-hidden border-foreground/10 bg-card p-0 dark:bg-zinc-950"
                style={{ width: 'min(760px, 92vw)', height: '84vh' }}
            >
                <DialogTitle className="sr-only">Run results</DialogTitle>
                {loading || results.length === 0 ? (
                    // The switcher stays reachable while a run loads AND on an
                    // empty run — a run that retained nothing must not
                    // dead-end the whole history.
                    <>
                        <div className="flex shrink-0 items-center justify-end border-b border-foreground/[0.06] px-5 py-4 pr-12">
                            <RunSwitcher data={switcher} icons={icons} />
                        </div>
                        {loading ? (
                            <div className="flex min-h-0 flex-1 items-center justify-center text-muted-foreground/70 dark:text-zinc-500">
                                <Loader2 className="h-5 w-5 animate-spin" />
                            </div>
                        ) : (
                            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                                <Inbox className="h-9 w-9 text-muted-foreground/60 dark:text-zinc-600" />
                                <p className="text-[13px] text-muted-foreground/70 dark:text-zinc-500">
                                    No node outputs were retained for this run.
                                </p>
                            </div>
                        )}
                    </>
                ) : (
                    <StoryVariant
                        story={story}
                        icons={icons}
                        onOpenConfig={onOpenConfig}
                        switcher={switcher}
                        onDontShowAgain={onDontShowAgain ? () => {
                            onDontShowAgain();
                            onClose();
                        } : undefined}
                        builtinClose
                    />
                )}
            </DialogContent>
        </Dialog>
    );
}
