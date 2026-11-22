// A run's results where no host draws its own (the `canvas.runs.results` slot's standard, loaded with the first run
// opened): what each step did, in the workflow's order, as `GET /v1/workflows/{id}/runs/{run}` gives it: how the step
// ended, its error and what it output (long text and lists cut short there, never a secret). While the run is still
// running it is read again each time the account's change stream says one of its steps moved, where the canvas has
// the stream. A run replayed on the canvas, and the calls an agent made in it, are NoClick's app's: this says so, and
// opens the workflow there.
import { useContext, useEffect } from 'react';
import { ArrowUpRight, CheckCircle, Clock, Loader2, MinusCircle, XCircle, type LucideIcon } from 'lucide-react';
import { Workflow, type RunStep, type WorkflowRun } from 'noclick';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { errorText } from '@/screens/console/lib/errorText';
import { NOCLICK_SITE, workflowUrl } from '@/screens/console/lib/site';
import { useClient } from '@/sdk/client';
import { WorkLiveContext } from '@/sdk/live';
import { useV1 } from '@/sdk/useV1';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { IODataDisplay } from './IODataDisplay';
import type { RunResultsProps } from './reads';
import { formatDuration } from './RunLog';

const STEP_STATUS: Record<string, { label: string; Icon: LucideIcon; tone: string; spin?: boolean }> = {
    succeeded: { label: 'Succeeded', Icon: CheckCircle, tone: 'text-emerald-600 dark:text-emerald-400' },
    failed: { label: 'Failed', Icon: XCircle, tone: 'text-red-600 dark:text-red-400' },
    skipped: { label: 'Skipped', Icon: MinusCircle, tone: 'text-muted-foreground' },
    running: { label: 'Running', Icon: Loader2, tone: 'text-blue-600 dark:text-blue-400', spin: true },
};
const NOT_SAID = { label: 'Waiting', Icon: Clock, tone: 'text-muted-foreground' };

const RUN_SAID: Record<string, string> = { succeeded: 'Succeeded', failed: 'Failed', running: 'Running' };

/** The read of one run, by which a view of it is kept. */
export const runKey = (workflowId: string, runId: string) => `/v1/workflows/${workflowId}/runs/${runId}`;

/** When the run started and how long it took, as its one line. */
function runLine(run: WorkflowRun): string {
    const said = [RUN_SAID[run.status] ?? run.status];
    if (run.startedAt) said.push(run.startedAt.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }));
    if (run.startedAt && run.finishedAt) said.push(formatDuration(run.finishedAt.getTime() - run.startedAt.getTime()));
    return said.join(' · ');
}

function Step({ step, onOpen }: { step: RunStep; onOpen?: () => void }) {
    const status = STEP_STATUS[step.status] ?? NOT_SAID;
    return (
        <li className="py-3" data-testid={`run-step-${step.id}`}>
            <div className="flex items-center gap-2">
                <status.Icon className={cn('h-4 w-4 shrink-0', status.tone, status.spin && 'animate-spin')} aria-hidden />
                {onOpen ? (
                    <button type="button" onClick={onOpen} className="min-w-0 truncate text-left text-[14px] font-medium text-foreground hover:underline">
                        {step.name || step.id}
                    </button>
                ) : (
                    <span className="min-w-0 truncate text-[14px] font-medium text-foreground">{step.name || step.id}</span>
                )}
                <span className={cn('ml-auto shrink-0 text-xs', status.tone)}>{status.label}</span>
            </div>
            {step.error && <p className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-red-500/10 px-3 py-2 font-mono text-xs text-red-800 dark:text-red-200">{step.error}</p>}
            {step.output !== null && step.output !== undefined && (
                <div className="mt-2">
                    <IODataDisplay data={step.output} label="" nodeId={step.id} draggable={false} />
                </div>
            )}
            {step.withheld.length > 0 && (
                <p className="mt-1.5 text-xs text-muted-foreground">
                    Left out, as a secret: {step.withheld.join(', ')}.
                </p>
            )}
        </li>
    );
}

export default function RunSteps({ workflowId, runId, onClose, onOpenStep }: RunResultsProps) {
    const client = useClient();
    const site = useContext(ConsoleContext)?.site ?? NOCLICK_SITE;
    const live = useContext(WorkLiveContext);
    const read = useV1(runId ? runKey(workflowId, runId) : null, () => Workflow.fromId(workflowId, { client }).getRun(runId as string), { client });
    const { refresh } = read;

    // A step of this run moved, or the stream lost its place: read the run again.
    useEffect(() => {
        if (!live || !runId) return;
        const offChange = live.on('platform:resource', (frame) => {
            if (frame.kind === 'workflow_run' && frame.id === runId) void refresh();
        });
        const offReset = live.on('reset', () => void refresh());
        return () => {
            offChange();
            offReset();
        };
    }, [live, runId, refresh]);

    const run = read.data;
    return (
        <ShellDialog
            open={runId !== null}
            onOpenChange={(open) => !open && onClose()}
            size="lg"
            title="What this run did"
            description={run ? runLine(run) : undefined}
            testId="run-steps"
            footer={
                <a href={workflowUrl(site, workflowId)} target="_blank" rel="noopener noreferrer" className="mr-auto inline-flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground">
                    A run replayed on the canvas, and the calls its agents made, are in NoClick’s app
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            }
        >
            {read.error ? (
                <p className="py-6 text-sm text-red-700 dark:text-red-300" role="alert">
                    This run couldn’t be read: {errorText(read.error)}
                </p>
            ) : !run ? (
                <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    Reading the run…
                </p>
            ) : (
                <>
                    {run.error && <p className="mb-1 whitespace-pre-wrap break-words rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-800 dark:text-red-200">{run.error}</p>}
                    {run.steps.length === 0 ? (
                        <p className="py-6 text-sm text-muted-foreground">{run.status === 'running' ? 'No step has started yet.' : 'No step ran.'}</p>
                    ) : (
                        <ul className="divide-y divide-border/60">
                            {run.steps.map((step) => (
                                <Step key={step.id} step={step} onOpen={onOpenStep ? () => onOpenStep(step.id) : undefined} />
                            ))}
                        </ul>
                    )}
                </>
            )}
        </ShellDialog>
    );
}
