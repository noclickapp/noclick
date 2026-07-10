// Always-on top-left canvas pill. Shows the latest run's status + relative time
// and the total run count, and opens the run-results popup (which carries its own
// run-switcher for loading older runs). Always present so run history is one click
// away, even before this session's first run.
import { History } from 'lucide-react';
import { cn } from '~/lib/utils';
import { useTimeAgo } from '~/hooks/useTimeAgo';
import {
    STATUS_META,
    type WorkflowExecutionLog,
} from '../WorkflowExecutionLogs';

interface RunHistoryPillProps {
    /** Execution list (newest first) — shared with the Logs tab. */
    logs: WorkflowExecutionLog[];
    /** Open the results popup (FlowCanvas loads the most recent run). */
    onOpen: () => void;
}

export function RunHistoryPill({ logs, onOpen }: RunHistoryPillProps) {
    const latest = logs[0];
    const latestStatus = latest ? STATUS_META[latest.status] : null;
    const latestAgo = useTimeAgo(latest?.timestamp.getTime());

    return (
        <button
            type="button"
            onClick={onOpen}
            title="View this workflow's run results"
            className="absolute left-4 top-4 z-10 inline-flex items-center gap-2 rounded-full border border-foreground/10 bg-popover/90 dark:bg-[#0a0a0b]/90 px-3.5 py-1.5 text-[13px] font-medium text-foreground shadow-lg shadow-black/10 dark:shadow-black/40 backdrop-blur-sm transition-colors hover:bg-foreground/[0.08] hover:text-foreground"
        >
            <History className="h-4 w-4 text-muted-foreground" />
            Runs
            {latest && latestStatus && (
                <span className="flex items-center gap-1.5 text-muted-foreground">
                    <span className="text-muted-foreground/60">·</span>
                    <latestStatus.Icon
                        className={cn(
                            'h-3.5 w-3.5',
                            latestStatus.text,
                            latestStatus.spin && 'animate-spin'
                        )}
                    />
                    <span className="tabular-nums">
                        {latestAgo || 'just now'}
                    </span>
                </span>
            )}
        </button>
    );
}
