import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
    Clock,
    CheckCircle,
    XCircle,
    Loader2,
    Inbox,
    Search,
    MousePointerClick,
    CalendarClock,
    Webhook,
    FormInput,
    Mail,
    Zap,
    type LucideIcon,
} from 'lucide-react';
import { cn } from '~/lib/utils';

export type ExecutionStatus = 'running' | 'waiting' | 'success' | 'error';

// What kicked off a run. Backed by the workflow_executions.trigger_source column
// (CHECK ('manual'|'webhook'|'cron'|'mcp'|'api'|'email')). The FE labels mostly
// track that vocabulary; 'form' / 'run' are reserved for future trigger sources
// and will show count 0 until the backend stores them.
export type ExecutionTrigger =
    | 'manual'
    | 'cron'
    | 'webhook'
    | 'email'
    | 'form'
    | 'run';

export const DEFAULT_TRIGGER: ExecutionTrigger = 'manual';

// Workflow execution log entry (one per execution)
export interface WorkflowExecutionLog {
    id: string; // execution_id from database
    timestamp: Date; // started_at
    status: ExecutionStatus;
    message: string;
    duration?: number; // calculated from finished_at - started_at
    nodesExecuted?: number;
    trigger?: ExecutionTrigger; // defaults to DEFAULT_TRIGGER until the backend records it
}

// Per-status / per-trigger counts across ALL of a workflow's executions —
// server-driven (workflow:get_execution_counts), so chip badges show the true
// total rather than the loaded slice.
export interface ExecutionCounts {
    total: number;
    byStatus: Record<ExecutionStatus, number>;
    byTrigger: Partial<Record<ExecutionTrigger, number>>;
}

// Active filter state. The parent re-fetches page 1 whenever any field changes
// (debounced 250ms for `query` so we don't hit the server per keystroke).
export interface LogsFilters {
    status: ExecutionStatus | 'all';
    trigger: ExecutionTrigger | 'all';
    query: string;
}

interface WorkflowExecutionLogsProps {
    logs: WorkflowExecutionLog[];
    counts: ExecutionCounts;
    hasMore: boolean;
    loading: boolean; // true while fetching first page or next page
    onFiltersChange: (filters: LogsFilters) => void;
    onLoadMore: () => void;
    // Clicking a row opens that run's read-only replay on the canvas.
    onRowClick?: (log: WorkflowExecutionLog) => void;
}

// Status design tokens — drive the inline status icon/label, the left accent rail,
// and (errors only) a whole-row health tint. Only failures get a full-row wash so
// the list stays calm; every status still carries a colored accent rail + a neutral
// hover. Matches the /logviews "Tinted Rows + Accent Bar" direction, dialed back.
interface StatusToken {
    label: string;
    Icon: LucideIcon;
    spin?: boolean;
    text: string;
    rail: string; // left accent border color
    tint: string; // resting row background (+ hover); errors get a red wash, the rest a neutral hover
}

const NEUTRAL_TINT = 'hover:bg-foreground/[0.025]';

export const STATUS_META: Record<ExecutionStatus, StatusToken> = {
    success: {
        label: 'Success',
        Icon: CheckCircle,
        text: 'text-emerald-600 dark:text-emerald-400',
        rail: 'border-l-emerald-400/40',
        tint: NEUTRAL_TINT,
    },
    error: {
        label: 'Error',
        Icon: XCircle,
        text: 'text-red-600 dark:text-red-400',
        rail: 'border-l-red-400/50',
        tint: 'bg-red-500/[0.06] hover:bg-red-500/[0.1]',
    },
    running: {
        label: 'Running',
        Icon: Loader2,
        spin: true,
        text: 'text-blue-600 dark:text-blue-400',
        rail: 'border-l-blue-400/50',
        tint: NEUTRAL_TINT,
    },
    waiting: {
        label: 'Waiting',
        Icon: Clock,
        text: 'text-amber-600 dark:text-amber-400',
        rail: 'border-l-amber-400/50',
        tint: NEUTRAL_TINT,
    },
};

const STATUS_ORDER: ExecutionStatus[] = [
    'success',
    'error',
    'running',
    'waiting',
];

interface TriggerToken {
    label: string;
    Icon: LucideIcon;
    text: string;
    bg: string;
}

export const TRIGGER_META: Record<ExecutionTrigger, TriggerToken> = {
    manual: {
        label: 'Manual',
        Icon: MousePointerClick,
        text: 'text-foreground',
        bg: 'bg-foreground/[0.07]',
    },
    cron: {
        label: 'Schedule',
        Icon: CalendarClock,
        text: 'text-sky-700 dark:text-sky-300',
        bg: 'bg-sky-500/10',
    },
    webhook: {
        label: 'Webhook',
        Icon: Webhook,
        text: 'text-violet-700 dark:text-violet-300',
        bg: 'bg-violet-500/10',
    },
    email: {
        label: 'Email',
        Icon: Mail,
        text: 'text-amber-700 dark:text-amber-300',
        bg: 'bg-amber-500/10',
    },
    form: {
        label: 'Form',
        Icon: FormInput,
        text: 'text-teal-700 dark:text-teal-300',
        bg: 'bg-teal-500/10',
    },
    run: {
        label: 'API',
        Icon: Zap,
        text: 'text-fuchsia-700 dark:text-fuchsia-300',
        bg: 'bg-fuchsia-500/10',
    },
};

const TRIGGER_ORDER: ExecutionTrigger[] = [
    'manual',
    'cron',
    'webhook',
    'email',
    'form',
    'run',
];

// Header and every row share this one grid track template so columns line up
// exactly. Status | Trigger | Message | Time | Duration.
const GRID = '120px 104px minmax(0,1fr) 152px 92px';

const StatusCell = ({
    status,
    className,
}: {
    status: ExecutionStatus;
    className?: string;
}) => {
    const m = STATUS_META[status];
    return (
        <span
            className={cn(
                'inline-flex items-center gap-1.5 text-xs font-medium',
                m.text,
                className
            )}
        >
            <m.Icon
                className={cn('h-3.5 w-3.5 shrink-0', m.spin && 'animate-spin')}
            />
            {m.label}
        </span>
    );
};

// inline-flex + width hugging its content so the tag never stretches to the column.
export const TriggerBadge = ({
    trigger,
    className,
}: {
    trigger: ExecutionTrigger;
    className?: string;
}) => {
    const m = TRIGGER_META[trigger];
    return (
        <span
            className={cn(
                'inline-flex w-fit items-center gap-1.5 rounded-md px-2 py-0.5 text-[0.6875rem] font-medium',
                m.bg,
                m.text,
                className
            )}
        >
            <m.Icon className="h-3 w-3 shrink-0" />
            {m.label}
        </span>
    );
};

export const formatDuration = (duration?: number): string => {
    if (!duration) return '--';

    if (duration < 1000) {
        return `${duration}ms`;
    } else if (duration < 60000) {
        return `${(duration / 1000).toFixed(1)}s`;
    } else {
        const minutes = Math.floor(duration / 60000);
        const seconds = Math.floor((duration % 60000) / 1000);
        return `${minutes}m ${seconds}s`;
    }
};

const formatDateTime = (timestamp: Date): string => {
    const now = new Date();
    const isToday = timestamp.toDateString() === now.toDateString();

    if (isToday) {
        return `Today, ${timestamp.toLocaleTimeString('en-US', {
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        })}`;
    }

    return timestamp.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
    });
};

const HeaderLabel = ({
    children,
    className,
}: {
    children: React.ReactNode;
    className?: string;
}) => (
    <span
        className={cn(
            'text-[0.6875rem] font-semibold uppercase tracking-wider text-muted-foreground dark:text-white/40',
            className
        )}
    >
        {children}
    </span>
);

const Chip = ({
    active,
    onClick,
    children,
    // `bare` = rendered on a trackless bar (no bg-muted track behind it). A white
    // active pill vanishes there, so use the gray fill effect instead; the tracked
    // (default) variant keeps the white pill that pops against the track.
    bare = false,
}: {
    active: boolean;
    onClick: () => void;
    children: React.ReactNode;
    bare?: boolean;
}) => (
    <button
        type="button"
        onClick={onClick}
        className={cn(
            'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
            active
                ? bare
                    ? 'bg-foreground/[0.08] text-foreground'
                    : 'bg-card shadow-sm dark:bg-foreground/[0.08] dark:shadow-none text-foreground'
                : 'text-muted-foreground dark:text-white/45 hover:bg-foreground/[0.04] hover:text-foreground/80'
        )}
    >
        {children}
    </button>
);

const Count = ({ value }: { value: number }) => (
    <span className="tabular-nums text-muted-foreground/70 dark:text-white/30">
        {value}
    </span>
);

const LogRow = ({
    log,
    onClick,
}: {
    log: WorkflowExecutionLog;
    onClick?: () => void;
}) => {
    const status = STATUS_META[log.status];
    const trigger = log.trigger ?? DEFAULT_TRIGGER;
    return (
        <div
            onClick={onClick}
            role={onClick ? 'button' : undefined}
            tabIndex={onClick ? 0 : undefined}
            onKeyDown={
                onClick
                    ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              onClick();
                          }
                      }
                    : undefined
            }
            className={cn(
                'group border-b border-l-2 border-border/50 dark:border-white/[0.03] transition-colors',
                status.rail,
                status.tint,
                onClick && 'cursor-pointer hover:bg-foreground/[0.03]'
            )}
        >
            {/* Desktop row */}
            <div
                className="hidden items-center gap-x-4 px-4 py-3 sm:grid"
                style={{ gridTemplateColumns: GRID }}
            >
                <StatusCell
                    status={log.status}
                    className="justify-self-start"
                />
                <TriggerBadge
                    trigger={trigger}
                    className="justify-self-start"
                />
                <span
                    className="min-w-0 truncate text-sm text-muted-foreground dark:text-white/70 transition-colors group-hover:text-foreground"
                    title={log.message}
                >
                    {log.message}
                </span>
                <span className="font-mono text-xs text-muted-foreground dark:text-white/50 transition-colors group-hover:text-foreground/80">
                    {formatDateTime(log.timestamp)}
                </span>
                <span className="text-right font-mono text-xs tabular-nums text-muted-foreground dark:text-white/50 transition-colors group-hover:text-foreground/80">
                    {formatDuration(log.duration)}
                </span>
            </div>

            {/* Mobile row */}
            <div className="flex items-start gap-3 px-4 py-3 sm:hidden">
                <div className="flex w-[96px] shrink-0 flex-col items-start gap-1.5 pt-0.5">
                    <StatusCell status={log.status} />
                    <TriggerBadge trigger={trigger} />
                </div>
                <div className="min-w-0 flex-1">
                    <p className="break-words text-sm leading-relaxed text-foreground/80">
                        {log.message}
                    </p>
                    <p className="mt-1 font-mono text-xs text-muted-foreground dark:text-white/40">
                        {formatDateTime(log.timestamp)}
                    </p>
                </div>
                <div className="shrink-0 pt-0.5 text-right font-mono text-xs tabular-nums text-muted-foreground dark:text-white/55">
                    {formatDuration(log.duration)}
                </div>
            </div>
        </div>
    );
};

export const WorkflowExecutionLogs: React.FC<WorkflowExecutionLogsProps> = ({
    logs,
    counts,
    hasMore,
    loading,
    onFiltersChange,
    onLoadMore,
    onRowClick,
}) => {
    const [statusFilter, setStatusFilter] = useState<ExecutionStatus | 'all'>(
        'all'
    );
    const [triggerFilter, setTriggerFilter] = useState<
        ExecutionTrigger | 'all'
    >('all');
    const [query, setQuery] = useState('');
    const [debouncedQuery, setDebouncedQuery] = useState('');

    // Debounce search so we don't fire a request per keystroke. 250ms feels
    // responsive without battering the backend on a fast typist's run.
    useEffect(() => {
        const t = setTimeout(() => setDebouncedQuery(query), 250);
        return () => clearTimeout(t);
    }, [query]);

    // Emit filter changes to the parent whenever any filter (or the debounced
    // query) changes. The parent re-fetches page 1 with the new filters.
    const onFiltersChangeRef = useRef(onFiltersChange);
    useEffect(() => {
        onFiltersChangeRef.current = onFiltersChange;
    }, [onFiltersChange]);
    useEffect(() => {
        onFiltersChangeRef.current({
            status: statusFilter,
            trigger: triggerFilter,
            query: debouncedQuery,
        });
    }, [statusFilter, triggerFilter, debouncedQuery]);

    // Scroll-near-bottom paginator: IntersectionObserver on a sentinel element
    // pinned to the bottom of the scroll container. Triggers onLoadMore when
    // the sentinel enters the viewport. Re-arms after every page load via the
    // hasMore/loading deps.
    const sentinelRef = useRef<HTMLDivElement | null>(null);
    const scrollRef = useRef<HTMLDivElement | null>(null);
    const onLoadMoreRef = useRef(onLoadMore);
    useEffect(() => {
        onLoadMoreRef.current = onLoadMore;
    }, [onLoadMore]);
    useEffect(() => {
        if (!hasMore || loading) return;
        const sentinel = sentinelRef.current;
        const root = scrollRef.current;
        if (!sentinel || !root) return;
        const obs = new IntersectionObserver(
            (entries) => {
                for (const e of entries) {
                    if (e.isIntersecting) {
                        onLoadMoreRef.current();
                        break;
                    }
                }
            },
            { root, rootMargin: '200px' }
        ); // prefetch when ~200px from bottom
        obs.observe(sentinel);
        return () => obs.disconnect();
    }, [hasMore, loading]);

    // Map server counts (raw DB statuses, raw trigger_source values) → the
    // chip-level totals shown next to each filter. counts.byStatus is already
    // bucketed (the FE collapses 'awaiting_*' into 'waiting' on the wire
    // before passing this in).
    const statusBadgeCount = useCallback(
        (s: ExecutionStatus) => counts.byStatus[s] ?? 0,
        [counts.byStatus]
    );
    const triggerBadgeCount = useCallback(
        (t: ExecutionTrigger) => counts.byTrigger[t] ?? 0,
        [counts.byTrigger]
    );

    const hasAnyLogs = counts.total > 0;
    if (!hasAnyLogs && !loading) {
        return (
            <div className="flex h-[400px] flex-col items-center justify-center text-center">
                <Clock className="mb-4 h-12 w-12 text-muted-foreground dark:text-zinc-500" />
                <h3 className="mb-2 text-lg font-semibold text-foreground">
                    No workflow runs yet
                </h3>
                <p className="text-sm text-muted-foreground">
                    Click the &quot;Run Workflow&quot; button to execute your
                    workflow and see the results here.
                </p>
            </div>
        );
    }

    return (
        <div className="flex min-h-0 w-full flex-1 flex-col">
            {/* Filters: status chips + search, then trigger chips */}
            <div className="mb-3 flex shrink-0 flex-col gap-2.5">
                <div className="flex flex-wrap items-center gap-2">
                    <div className="flex flex-wrap items-center gap-0.5 rounded-xl border border-border dark:border-white/[0.06] bg-muted dark:bg-foreground/[0.015] p-1">
                        <Chip
                            active={statusFilter === 'all'}
                            onClick={() => setStatusFilter('all')}
                        >
                            All
                            <Count value={counts.total} />
                        </Chip>
                        {STATUS_ORDER.map((s) => {
                            const m = STATUS_META[s];
                            const active = statusFilter === s;
                            return (
                                <Chip
                                    key={s}
                                    active={active}
                                    onClick={() => setStatusFilter(s)}
                                >
                                    <m.Icon
                                        className={cn(
                                            'h-3.5 w-3.5',
                                            active && m.text,
                                            m.spin && active && 'animate-spin'
                                        )}
                                    />
                                    {m.label}
                                    <Count value={statusBadgeCount(s)} />
                                </Chip>
                            );
                        })}
                    </div>

                    <div className="relative ml-auto min-w-[160px] flex-1 sm:max-w-[260px]">
                        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/70 dark:text-white/30" />
                        <input
                            type="text"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Search error messages…"
                            className="w-full rounded-lg border border-input dark:border-white/[0.08] bg-foreground/[0.04] py-2 pl-9 pr-3 text-sm text-foreground outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-muted-foreground/40 dark:focus:border-white/[0.15]"
                        />
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                    <span className="mr-1 text-[0.6875rem] uppercase tracking-wider text-muted-foreground/70 dark:text-white/25">
                        Trigger
                    </span>
                    <Chip
                        bare
                        active={triggerFilter === 'all'}
                        onClick={() => setTriggerFilter('all')}
                    >
                        Any
                    </Chip>
                    {TRIGGER_ORDER.map((t) => {
                        const m = TRIGGER_META[t];
                        const active = triggerFilter === t;
                        return (
                            <Chip
                                key={t}
                                bare
                                active={active}
                                onClick={() => setTriggerFilter(t)}
                            >
                                <m.Icon
                                    className={cn(
                                        'h-3.5 w-3.5',
                                        active && m.text
                                    )}
                                />
                                {m.label}
                                <Count value={triggerBadgeCount(t)} />
                            </Chip>
                        );
                    })}
                </div>
            </div>

            {/* Panel */}
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border dark:border-white/[0.06] bg-foreground/[0.015]">
                <div
                    ref={scrollRef}
                    className="relative flex-1 overflow-y-auto scrollbar-subtle"
                >
                    {/* Sticky header (desktop) */}
                    <div
                        className="sticky top-0 z-10 hidden items-center gap-x-4 border-b border-l-2 border-border dark:border-white/[0.06] border-l-transparent bg-sunken/95 dark:bg-sunken/95 px-4 py-2.5 backdrop-blur sm:grid"
                        style={{ gridTemplateColumns: GRID }}
                    >
                        <HeaderLabel>Status</HeaderLabel>
                        <HeaderLabel>Trigger</HeaderLabel>
                        <HeaderLabel>Message</HeaderLabel>
                        <HeaderLabel>Time</HeaderLabel>
                        <HeaderLabel className="text-right">
                            Duration
                        </HeaderLabel>
                    </div>

                    {logs.length === 0 && !loading ? (
                        <div className="flex flex-col items-center justify-center gap-3 px-6 py-20 text-center">
                            <Inbox className="h-8 w-8 text-muted-foreground/50 dark:text-white/20" />
                            <p className="text-sm text-muted-foreground dark:text-white/40">
                                No runs match these filters
                            </p>
                        </div>
                    ) : (
                        <>
                            {logs.map((log) => (
                                <LogRow
                                    key={log.id}
                                    log={log}
                                    onClick={
                                        onRowClick
                                            ? () => onRowClick(log)
                                            : undefined
                                    }
                                />
                            ))}
                            {/* Sentinel for IntersectionObserver — sits at the bottom of
                                the list. Only mounted while there's more to fetch so the
                                observer can't re-arm on the final page. */}
                            {hasMore && (
                                <div
                                    ref={sentinelRef}
                                    className="h-1"
                                    aria-hidden="true"
                                />
                            )}
                            {loading && (
                                <div className="flex items-center justify-center gap-2 px-4 py-4 text-xs text-muted-foreground dark:text-white/40">
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    Loading…
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>

            <p className="mt-3 shrink-0 text-xs text-muted-foreground/70 dark:text-white/30">
                Showing {logs.length} of {counts.total} runs
            </p>
        </div>
    );
};
