// Small "✓ N ago" / "✗ N ago" run-status pill shown under a node's label after it
// executes (monochrome on success, red on failure; timestamp ticks live via useTimeAgo).
// Leaf module (only useTimeAgo + lucide) so the perf-sensitive mobile ForkCanvas can
// render the identical pill without pulling NodeLabel's editor/toolbar deps — one source
// of truth for both canvases.

import { Check, X } from 'lucide-react';
import { useTimeAgo } from '~/hooks/useTimeAgo';

// Whether the "✓/✗ N ago" status chip will render, given a node's run state.
export function shouldShowStatusChip(
    lastRunStatus?: string,
    lastRunAt?: number | null,
    isRunning?: boolean,
): boolean {
    return !isRunning && lastRunAt != null && (lastRunStatus === 'completed' || lastRunStatus === 'error');
}

export function NodeStatusChip({ status, at }: { status: string; at: number }) {
    const ago = useTimeAgo(at);
    if (!ago) return null;
    const isError = status === 'error';
    return (
        <div
            className={`flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold whitespace-nowrap pointer-events-none select-none border shadow-sm ${
                isError ? 'bg-popover/90 border-red-500/50 text-red-600 dark:text-red-300' : 'bg-popover/90 border-foreground/25 text-foreground'
            }`}
        >
            {isError ? <X className="w-2.5 h-2.5" strokeWidth={3} /> : <Check className="w-2.5 h-2.5" strokeWidth={3} />}
            {ago}
        </div>
    );
}
