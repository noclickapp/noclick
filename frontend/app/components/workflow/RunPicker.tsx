// In-dialog run switcher used by RunResultsDialog: a header control showing the
// CURRENT run (status + relative time + trigger) with a chevron that reveals a
// dropdown of older runs to load. The dropdown infinite-scrolls — scrolling near
// the bottom pages in more runs (shared paginator with the Logs tab). Rendered
// inline (absolute, NOT portaled) so it doesn't trip Radix Dialog's outside-click
// / focus handling — a portaled popover would register as "outside" and close it.
import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Inbox, Loader2, Check } from 'lucide-react';
import { cn } from '~/lib/utils';
import { useTimeAgo } from '~/hooks/useTimeAgo';
import {
    STATUS_META,
    TriggerBadge,
    DEFAULT_TRIGGER,
    formatDuration,
    type WorkflowExecutionLog,
} from './WorkflowExecutionLogs';

function RunRow({ log, active, onSelect }: { log: WorkflowExecutionLog; active: boolean; onSelect: () => void }) {
    const status = STATUS_META[log.status];
    const ago = useTimeAgo(log.timestamp.getTime());
    return (
        <button
            type="button"
            onClick={onSelect}
            title={`${status.label} · ${log.timestamp.toLocaleString()}`}
            className={cn('flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-foreground/[0.06]', active && 'bg-foreground/[0.05]')}
        >
            <status.Icon className={cn('h-3.5 w-3.5 shrink-0', status.text, status.spin && 'animate-spin')} />
            <span className="min-w-0 flex-1 truncate text-[13px] text-foreground">{ago || 'just now'}</span>
            <TriggerBadge trigger={log.trigger ?? DEFAULT_TRIGGER} className="shrink-0" />
            <span className="w-12 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted-foreground/70 dark:text-zinc-500">
                {formatDuration(log.duration)}
            </span>
            {active && <Check className="h-3.5 w-3.5 shrink-0 text-muted-foreground dark:text-zinc-300" />}
        </button>
    );
}

interface RunPickerProps {
    /** Loaded executions (newest first) — shared, paginated list with the Logs tab. */
    runs: WorkflowExecutionLog[];
    /** Execution currently shown in the dialog. */
    currentExecId: string | null;
    /** True while the selected run's results are loading. */
    loading: boolean;
    /** Whether more runs can be paged in. */
    hasMore: boolean;
    /** True while the next page of runs is loading. */
    loadingMore: boolean;
    /** Page in the next batch of runs (scroll-near-bottom). */
    onLoadMore: () => void;
    /** Load a different run's results into the dialog. */
    onSelectRun: (log: WorkflowExecutionLog) => void;
}

export function RunPicker({ runs, currentExecId, loading, hasMore, loadingMore, onLoadMore, onSelectRun }: RunPickerProps) {
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);
    const scrollRef = useRef<HTMLDivElement>(null);
    const sentinelRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
        document.addEventListener('mousedown', onDown);
        return () => document.removeEventListener('mousedown', onDown);
    }, [open]);

    // Infinite scroll: page in more runs when the bottom sentinel nears view.
    const onLoadMoreRef = useRef(onLoadMore);
    useEffect(() => { onLoadMoreRef.current = onLoadMore; }, [onLoadMore]);
    useEffect(() => {
        if (!open || !hasMore || loadingMore) return;
        const root = scrollRef.current, sentinel = sentinelRef.current;
        if (!root || !sentinel) return;
        const obs = new IntersectionObserver((entries) => {
            for (const e of entries) if (e.isIntersecting) { onLoadMoreRef.current(); break; }
        }, { root, rootMargin: '120px' });
        obs.observe(sentinel);
        return () => obs.disconnect();
    }, [open, hasMore, loadingMore, runs.length]);

    const current = runs.find((r) => r.id === currentExecId) || null;
    const currentStatus = current ? STATUS_META[current.status] : null;
    const currentAgo = useTimeAgo(current?.timestamp.getTime());

    return (
        <div ref={ref} className="relative">
            <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="inline-flex items-center gap-2 rounded-lg border border-foreground/10 bg-foreground/[0.04] px-2.5 py-1.5 text-[13px] text-foreground transition-colors hover:bg-foreground/[0.07] data-[open=true]:bg-foreground/[0.07]"
                data-open={open}
            >
                {loading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                ) : currentStatus ? (
                    <currentStatus.Icon className={cn('h-3.5 w-3.5', currentStatus.text, currentStatus.spin && 'animate-spin')} />
                ) : null}
                <span className="tabular-nums">{current ? (currentAgo || 'just now') : 'Run'}</span>
                {current && <TriggerBadge trigger={current.trigger ?? DEFAULT_TRIGGER} />}
                <ChevronDown className={cn('h-3.5 w-3.5 text-muted-foreground/70 dark:text-zinc-500 transition-transform', open && 'rotate-180')} />
            </button>

            {open && (
                <div className="absolute left-0 top-full z-50 mt-1 w-[300px] overflow-hidden rounded-xl border border-border dark:border-foreground/10 bg-popover dark:bg-[#0c0c0e] shadow-lg shadow-black/[0.08] dark:shadow-xl dark:shadow-black/60">
                    <div className="border-b border-foreground/[0.06] px-3 py-2 text-[12px] font-semibold text-muted-foreground dark:text-zinc-300">Switch run</div>
                    <div ref={scrollRef} className="max-h-[300px] overflow-y-auto scrollbar-subtle">
                        {runs.length > 0 ? (
                            <>
                                {runs.map((log) => (
                                    <RunRow
                                        key={log.id}
                                        log={log}
                                        active={log.id === currentExecId}
                                        onSelect={() => { setOpen(false); onSelectRun(log); }}
                                    />
                                ))}
                                {/* Sentinel: only mounted while more pages remain, so the
                                    observer can't re-arm on the final page. */}
                                {hasMore && <div ref={sentinelRef} className="h-1" aria-hidden="true" />}
                                {loadingMore && (
                                    <div className="flex items-center justify-center gap-2 px-3 py-3 text-[12px] text-muted-foreground/70 dark:text-zinc-500">
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
                                    </div>
                                )}
                            </>
                        ) : loadingMore ? (
                            <div className="flex items-center justify-center gap-2 px-3 py-8 text-[12px] text-muted-foreground/70 dark:text-zinc-500">
                                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading runs…
                            </div>
                        ) : (
                            <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
                                <Inbox className="h-7 w-7 text-muted-foreground/60 dark:text-zinc-600" />
                                <p className="text-[12px] text-muted-foreground/70 dark:text-zinc-500">No runs yet.</p>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
