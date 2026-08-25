/**
 * Usage Dashboard Component
 *
 * Displays usage statistics with interactive charts showing cost breakdowns
 * by usage type, model, and time periods. Chart components live in
 * UsageBarChart/UsagePieChart, tables in UsageTables, and all data shapes +
 * real-time merge logic in ~/lib/usage. Live usage:event pushes are applied
 * with PURE functional updates (state and preset caches alike) so bursts and
 * StrictMode double-invocation can't double-count.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
    sendEventAsync,
    UsageDataRequest,
    UsageLogsRequest,
} from '~/lib/socket-sender';
import { Card } from '~/components/ui/card';
import { SegmentedControl } from '~/components/ui/segmented-control';
import { cn } from '~/lib/utils';
import { ArrowLeft, BarChart3, PieChart as PieChartIcon } from 'lucide-react';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useCreditUsage } from '~/hooks/useCreditUsage';
import { useOrgContext } from '~/hooks/useOrgContext';
import { useIsMobile } from '~/hooks/useIsMobile';
import { DateRangePicker } from '~/components/ui/date-range-picker';
import { DateRange } from 'react-day-picker';
import { useSocketEvent } from '~/hooks/useSocketEvent';
import type { UsageEventUpdateEvent } from '~/types/socket-events.generated';
import { formatCredits } from '~/lib/formatCredits';
import {
    applyEventToUsageData,
    assignSeriesColors,
    colorForUsageType,
    eventMatchesLogFilters,
    eventMatchesWorkspace,
    eventWithinDayRange,
    getDisplayName,
    prependUsageLog,
    type CachedUsageData,
    type UsageData,
    type UsageLogFilters,
    type UsageLogsData,
} from '~/lib/usage';
import { UsageBarChart } from '~/components/usage/UsageBarChart';
import { UsagePieChart, type PieDatum } from '~/components/usage/UsagePieChart';
import {
    RecentUsageEventsTable,
    TopModelsTable,
} from '~/components/usage/UsageTables';

// Cache TTL matches the backend handler's TTLCache (5 minutes).
const CACHE_TTL_MS = 5 * 60 * 1000;
const LOGS_LIMIT = 20;
// Fallback log refresh; real-time usage:event pushes are the primary source.
const LOGS_REFRESH_MS = 60_000;

type RangePreset = '7d' | '30d' | '90d';
const RANGE_PRESETS: readonly RangePreset[] = ['7d', '30d', '90d'];
const PRESET_DAYS: Record<RangePreset, number> = {
    '7d': 7,
    '30d': 30,
    '90d': 90,
};

function lastNDaysRange(days: number): DateRange {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);
    return { from: start, to: end };
}


interface UsageDashboardProps {
    className?: string;
    onNavigateBack?: () => void;
    /** When true, hides the header with back button (for embedding in Settings) */
    embedded?: boolean;
}

export function UsageDashboard({
    className,
    onNavigateBack,
    embedded = false,
}: UsageDashboardProps) {
    const isMobile = useIsMobile(640);
    const [usageData, setUsageData] = useState<UsageData | null>(null);
    const [usageLogsData, setUsageLogsData] = useState<UsageLogsData | null>(
        null
    );
    const [loading, setLoading] = useState(true);
    const [logsLoading, setLogsLoading] = useState(true);
    const [logsLoadingMore, setLogsLoadingMore] = useState(false);
    const [logsHasMore, setLogsHasMore] = useState(false);
    const [logFilters, setLogFilters] = useState<UsageLogFilters>({
        search: '',
        usageType: null,
    });
    const [error, setError] = useState<string | null>(null);
    const [dateRangePreset, setDateRangePreset] = useState<
        RangePreset | 'custom'
    >('30d');
    const [dateRange, setDateRange] = useState<DateRange | undefined>(() =>
        lastNDaysRange(30)
    );
    const [chartType, setChartType] = useState<'bar' | 'pie'>('bar');
    const [viewMode, setViewMode] = useState<'type' | 'model'>('model'); // type = CPU/AI, model = individual models
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const [chartWidth, setChartWidth] = useState(0);
    const activeRequestRef = useRef<number>(0);

    // Credit-pool view replaces the legacy $-balance display. Credits are per-user
    // (not per-org) so we no longer route through orgBalance — the dashboard's
    // "remaining" number always reflects the user's own monthly grant + topup
    // minus spend.
    const credits = useCreditUsage();
    const [orgContext] = useOrgContext();
    const workspaceId = orgContext.id; // null in personal workspace, uuid in an org
    const creditsLoading = credits.period === null;
    const creditsUnlimited = !creditsLoading && credits.monthlyCap === null;
    const creditsRemaining =
        credits.monthlyCap !== null
            ? Math.max(0, credits.monthlyCap - (credits.monthlyUsed ?? 0))
            : null;
    const creditsLabel = creditsUnlimited
        ? 'Unlimited'
        : creditsRemaining !== null
          ? `${creditsRemaining.toFixed(2)} / ${credits.monthlyCap}`
          : '—';

    // Workspace-partitioned cache keys: each workspace has its own slot so switching
    // between Personal and an org never displays the previous workspace's totals from
    // IndexedDB while the fresh fetch is in flight.
    const cacheSuffix = workspaceId ? `org-${workspaceId}` : 'personal';
    const [cache7d, setCache7d] = useCachedValtioState<CachedUsageData | null>(
        'noclick-usage',
        `last7days-${cacheSuffix}`,
        null
    );
    const [cache30d, setCache30d] =
        useCachedValtioState<CachedUsageData | null>(
            'noclick-usage',
            `last30days-${cacheSuffix}`,
            null
        );
    const [cache90d, setCache90d] =
        useCachedValtioState<CachedUsageData | null>(
            'noclick-usage',
            `last90days-${cacheSuffix}`,
            null
        );

    // Latest-value ref for the TTL check inside fetchUsageData. Reading the cache
    // STATE there would put it in the callback's deps, and since every fetch and
    // every real-time event writes the cache, the fetch effect would re-run on its
    // own writes (one wasted render round-trip per event).
    const cachesRef = useRef<Record<RangePreset, CachedUsageData | null>>({
        '7d': null,
        '30d': null,
        '90d': null,
    });
    cachesRef.current = { '7d': cache7d, '30d': cache30d, '90d': cache90d };

    const cacheSetters = useMemo(
        () =>
            ({
                '7d': setCache7d,
                '30d': setCache30d,
                '90d': setCache90d,
            }) as const,
        [setCache7d, setCache30d, setCache90d]
    );

    const fetchUsageData = useCallback(
        async (
            startDate: Date,
            endDate: Date,
            rangeKey: RangePreset | 'custom'
        ) => {
            // Increment request counter to invalidate previous in-flight requests
            const requestId = ++activeRequestRef.current;

            // Serve non-custom ranges from the per-workspace cache while fresh
            if (rangeKey !== 'custom') {
                const cached = cachesRef.current[rangeKey];
                if (
                    cached?.timestamp &&
                    Date.now() - cached.timestamp < CACHE_TTL_MS
                ) {
                    setUsageData(cached.data);
                    setLoading(false);
                    return;
                }
            }

            setLoading(true);
            setError(null);

            try {
                const response = await sendEventAsync(
                    UsageDataRequest.create({
                        start_date: startDate.toISOString(),
                        end_date: endDate.toISOString(),
                        group_by: 'day',
                        limit: 100,
                        organization_id: workspaceId ?? undefined,
                    })
                );

                // Only update state if this is still the latest request
                if (requestId !== activeRequestRef.current) return;
                const data = response as UsageData;
                setUsageData(data);
                if (rangeKey !== 'custom') {
                    cacheSetters[rangeKey]({ data, timestamp: Date.now() });
                }
            } catch (err) {
                if (requestId === activeRequestRef.current) {
                    setError(
                        err instanceof Error
                            ? err.message
                            : 'Failed to fetch usage data'
                    );
                    console.error(
                        '[UsageDashboard] Error fetching usage data:',
                        err
                    );
                }
            } finally {
                if (requestId === activeRequestRef.current) {
                    setLoading(false);
                }
            }
        },
        [cacheSetters, workspaceId]
    );

    // Latest logs list + in-flight guards for pagination, read inside stable
    // callbacks (same pattern as cachesRef above).
    const usageLogsRef = useRef<UsageLogsData | null>(null);
    usageLogsRef.current = usageLogsData;
    const loadingMoreRef = useRef(false);
    const logsRequestRef = useRef(0);

    // Fetch (or re-fetch) the FIRST page for the active filters, resetting any
    // pagination the user had scrolled through.
    const fetchUsageLogs = useCallback(async () => {
        const requestId = ++logsRequestRef.current;
        setLogsLoading(true);
        try {
            const response = await sendEventAsync(
                UsageLogsRequest.create({
                    limit: LOGS_LIMIT,
                    organization_id: workspaceId ?? undefined,
                    usage_type: logFilters.usageType ?? undefined,
                    search: logFilters.search.trim() || undefined,
                })
            );
            if (requestId !== logsRequestRef.current) return; // superseded by newer filters
            const data = response as UsageLogsData;
            setUsageLogsData(data);
            setLogsHasMore(!!data.has_more);
        } catch (err) {
            // Logs are auxiliary — surface in console only, the chart error state covers real outages
            console.error('[UsageDashboard] Error fetching usage logs:', err);
        } finally {
            if (requestId === logsRequestRef.current) setLogsLoading(false);
        }
    }, [workspaceId, logFilters]);

    // Append the next (older) page, keyed on the last row's timestamp.
    const loadMoreLogs = useCallback(async () => {
        const current = usageLogsRef.current;
        if (!current || current.logs.length === 0 || loadingMoreRef.current)
            return;
        loadingMoreRef.current = true;
        setLogsLoadingMore(true);
        const requestId = logsRequestRef.current; // a filter change invalidates this page
        try {
            const response = await sendEventAsync(
                UsageLogsRequest.create({
                    limit: LOGS_LIMIT,
                    before: current.logs[current.logs.length - 1].timestamp,
                    organization_id: workspaceId ?? undefined,
                    usage_type: logFilters.usageType ?? undefined,
                    search: logFilters.search.trim() || undefined,
                })
            );
            if (requestId !== logsRequestRef.current) return;
            const page = response as UsageLogsData;
            setUsageLogsData((prev) =>
                prev ? { ...prev, logs: [...prev.logs, ...page.logs] } : page
            );
            setLogsHasMore(!!page.has_more);
        } catch (err) {
            console.error(
                '[UsageDashboard] Error loading more usage logs:',
                err
            );
        } finally {
            loadingMoreRef.current = false;
            setLogsLoadingMore(false);
        }
    }, [workspaceId, logFilters]);

    useEffect(() => {
        if (dateRange?.from && dateRange?.to) {
            fetchUsageData(dateRange.from, dateRange.to, dateRangePreset);
        }
    }, [dateRange, dateRangePreset, fetchUsageData]);

    // Fetch logs on mount and whenever filters/workspace change, then refresh
    // periodically as a fallback to the real-time events — skipping ticks
    // while the tab is hidden, catching up on return, and never resetting a
    // list the user has paginated deeper (a page-1 refetch would throw away
    // their scroll context; live events keep the top fresh regardless).
    useEffect(() => {
        fetchUsageLogs();
        const refreshIfIdle = () => {
            const paginated =
                (usageLogsRef.current?.logs.length ?? 0) > LOGS_LIMIT;
            if (!document.hidden && !paginated) fetchUsageLogs();
        };
        const interval = setInterval(refreshIfIdle, LOGS_REFRESH_MS);
        document.addEventListener('visibilitychange', refreshIfIdle);
        return () => {
            clearInterval(interval);
            document.removeEventListener('visibilitychange', refreshIfIdle);
        };
    }, [fetchUsageLogs]);

    // Real-time usage events update the log table, the live chart data, and the
    // preset caches. Scope filter mirrors the backend query (see
    // eventMatchesWorkspace). Every write below is a PURE functional update:
    // useCachedValtioState setters compute from a synchronous ref, so bursts of
    // events between renders can't clobber each other, and nothing runs inside
    // another updater (StrictMode-safe).
    useSocketEvent('usage:event', (event: UsageEventUpdateEvent) => {
        if (!eventMatchesWorkspace(event, workspaceId, credits.poolUserId))
            return;

        // Respect the active log filters (same semantics as the backend
        // query), and never truncate a list the user has paginated deeper.
        if (eventMatchesLogFilters(event, logFilters)) {
            setUsageLogsData((prev) =>
                prependUsageLog(
                    prev,
                    event,
                    prev && prev.logs.length > LOGS_LIMIT ? null : LOGS_LIMIT
                )
            );
        }

        // Live chart: presets end "now" so a live event always belongs; only a
        // custom historical range can exclude it.
        const inLiveRange =
            dateRangePreset !== 'custom' ||
            !dateRange?.from ||
            !dateRange?.to ||
            eventWithinDayRange(event, dateRange.from, dateRange.to);
        if (inLiveRange) {
            setUsageData((prev) =>
                prev ? applyEventToUsageData(prev, event) : prev
            );
        }

        // Preset caches: merge the event so switching filters shows the latest
        // data. `timestamp` is deliberately NOT bumped — it marks fetch freshness,
        // and extending it on every event would keep serving incrementally-patched
        // data forever. Empty slots stay empty (they fill on the next fetch).
        for (const key of RANGE_PRESETS) {
            cacheSetters[key]((prev) =>
                prev?.data
                    ? {
                          data: applyEventToUsageData(prev.data, event),
                          timestamp: prev.timestamp,
                      }
                    : prev
            );
        }
    });

    // Handle chart width using ResizeObserver — re-attaches when usageData appears so the
    // container div (which is conditionally rendered) is in the DOM when we observe it.
    useEffect(() => {
        const el = chartContainerRef.current;
        if (!el) return;
        const ro = new ResizeObserver((entries) => {
            const width = entries[0]?.contentRect.width;
            if (width && width > 0) setChartWidth(Math.floor(width));
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, [usageData]);

    const handlePresetChange = (preset: RangePreset) => {
        setDateRangePreset(preset);
        setDateRange(lastNDaysRange(PRESET_DAYS[preset]));
    };

    const handleDateRangeChange = (range: DateRange | undefined) => {
        setDateRange(range);
        if (range?.from && range?.to) {
            setDateRangePreset('custom');
        }
    };

    // Pie data with pre-calculated percentages; colors come from the shared
    // assignment so a series matches its bar-chart color exactly.
    const pieChartData = useMemo<PieDatum[]>(() => {
        if (!usageData) return [];

        const dataSource =
            viewMode === 'type'
                ? usageData.usage_by_type
                : usageData.usage_by_subtype;
        const entries = Object.entries(dataSource).filter(
            ([, value]) => value > 0
        );
        const total = entries.reduce((sum, [, value]) => sum + value, 0);
        const seriesColors =
            viewMode === 'model'
                ? assignSeriesColors(entries.map(([key]) => key))
                : null;

        return entries
            .map(([key, value]) => ({
                key,
                label: getDisplayName(key),
                value,
                color: seriesColors
                    ? seriesColors[key]
                    : colorForUsageType(key),
                percentage:
                    total > 0 ? ((value / total) * 100).toFixed(1) : '0.0',
            }))
            .sort((a, b) => b.value - a.value);
    }, [usageData, viewMode]);

    const handleNavigateBack = () => {
        if (onNavigateBack) {
            onNavigateBack();
        } else {
            // Dispatch event to switch back to vite tab
            window.dispatchEvent(
                new CustomEvent('noclick:switch-tab', {
                    detail: { tab: 'vite' },
                    bubbles: true,
                })
            );
        }
    };

    return (
        <div className={cn('w-full max-w-full space-y-6', className)}>
            {/* Header with balance - hidden when embedded in Settings */}
            {!embedded && (
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <button
                            onClick={handleNavigateBack}
                            aria-label="Back"
                            className="flex items-center justify-center w-9 h-9 text-muted-foreground hover:text-foreground hover:bg-accent rounded-full transition-colors"
                        >
                            <ArrowLeft className="w-4 h-4" />
                        </button>
                        <div>
                            <h2 className="text-2xl font-bold text-foreground">
                                Usage Dashboard
                            </h2>
                            <p className="text-sm text-muted-foreground dark:text-zinc-500 mt-1">
                                Track your AI, compute, and resource usage
                            </p>
                        </div>
                    </div>
                    {!creditsLoading && (
                        <div className="text-right">
                            <p className="text-sm text-muted-foreground dark:text-zinc-500">
                                Credits remaining
                            </p>
                            <p className="text-2xl font-bold text-foreground">
                                {creditsLabel}
                            </p>
                        </div>
                    )}
                </div>
            )}

            {/* Embedded header - simpler, without back button */}
            {embedded && (
                <div className="mb-4">
                    <div className="flex items-start justify-between gap-3">
                        <div>
                            <h2 className="text-xl sm:text-2xl font-semibold text-foreground tracking-tight">
                                Usage
                            </h2>
                            <p className="text-xs sm:text-sm text-muted-foreground dark:text-white/40 mt-0.5">
                                Track your AI, compute, and resource usage
                            </p>
                        </div>
                        {!creditsLoading && (
                            <div className="flex-shrink-0 bg-card dark:bg-foreground/[0.05] border border-border dark:border-white/[0.08] rounded-xl px-3 py-2 text-right">
                                <p className="text-[10px] text-muted-foreground dark:text-white/40 uppercase tracking-wider">
                                    Credits remaining
                                </p>
                                <p className="text-lg font-semibold text-foreground leading-tight">
                                    {creditsLabel}
                                </p>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Controls */}
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                {/* Row 1: Date presets + date picker */}
                <div className="flex items-center gap-2">
                    <SegmentedControl
                        options={RANGE_PRESETS.map((preset) => ({
                            value: preset,
                            label: preset,
                        }))}
                        value={dateRangePreset}
                        onChange={handlePresetChange}
                        className="flex-shrink-0"
                    />
                    <DateRangePicker
                        dateRange={dateRange}
                        onDateRangeChange={handleDateRangeChange}
                        align="start"
                        className="flex-1 min-w-0"
                    />
                </div>

                {/* Row 2: Chart type + view mode — full width on mobile */}
                <div className="flex items-center gap-2">
                    <SegmentedControl
                        options={[
                            {
                                value: 'bar',
                                label: (
                                    <>
                                        <BarChart3 className="w-3.5 h-3.5 flex-shrink-0" />
                                        Bar
                                    </>
                                ),
                            },
                            {
                                value: 'pie',
                                label: (
                                    <>
                                        <PieChartIcon className="w-3.5 h-3.5 flex-shrink-0" />
                                        Pie
                                    </>
                                ),
                            },
                        ]}
                        value={chartType}
                        onChange={setChartType}
                        className="flex-1 sm:flex-none"
                        buttonClassName="flex-1 sm:flex-none"
                    />
                    <SegmentedControl
                        options={[
                            {
                                value: 'type',
                                label: (
                                    <>
                                        <span className="hidden sm:inline">
                                            By Resource
                                        </span>
                                        <span className="sm:hidden">
                                            Resource
                                        </span>
                                    </>
                                ),
                            },
                            {
                                value: 'model',
                                label: (
                                    <>
                                        <span className="hidden sm:inline">
                                            By Model
                                        </span>
                                        <span className="sm:hidden">Model</span>
                                    </>
                                ),
                            },
                        ]}
                        value={viewMode}
                        onChange={setViewMode}
                        className="flex-1 sm:flex-none"
                        buttonClassName="flex-1 sm:flex-none"
                    />
                </div>
            </div>

            {/* Loading skeleton states */}
            {loading && (
                <>
                    <Card className="p-6 bg-card/50 border-border">
                        <div className="h-6 bg-muted rounded w-48 mb-4 animate-pulse" />
                        <div className="w-full h-[400px] bg-muted/30 dark:bg-zinc-900/30 animate-pulse rounded-lg flex items-center justify-center">
                            <div className="text-muted-foreground/70 dark:text-zinc-600 text-sm">
                                Loading visualization...
                            </div>
                        </div>
                    </Card>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {[1, 2, 3].map((i) => (
                            <Card
                                key={i}
                                className="p-6 bg-card/50 border-border"
                            >
                                <div className="h-4 bg-muted rounded w-24 mb-2 animate-pulse" />
                                <div className="h-8 bg-muted rounded w-32 animate-pulse" />
                            </Card>
                        ))}
                    </div>
                </>
            )}

            {error && !loading && (
                <Card className="p-8 bg-card/50 border-red-300 dark:border-red-900/50">
                    <div className="flex flex-col items-center gap-4">
                        <div className="text-center text-red-600 dark:text-red-400">
                            Error: {error}
                        </div>
                        <button
                            onClick={() => {
                                if (dateRange?.from && dateRange?.to) {
                                    fetchUsageData(
                                        dateRange.from,
                                        dateRange.to,
                                        dateRangePreset
                                    );
                                }
                            }}
                            className="px-4 py-2 text-foreground bg-foreground/[0.08] hover:bg-foreground/[0.12] border border-foreground/[0.08] rounded-lg transition-colors text-sm font-medium"
                        >
                            Retry
                        </button>
                    </div>
                </Card>
            )}

            {/* Main chart */}
            {!loading && !error && usageData && (
                <>
                    <Card className="p-3 sm:p-6 bg-card/50 border-border">
                        <h3 className="text-base sm:text-lg font-semibold text-foreground mb-3 sm:mb-4">
                            {chartType === 'bar'
                                ? 'Cost Over Time'
                                : viewMode === 'type'
                                  ? 'Cost by Resource Type'
                                  : 'Cost by Model/Service'}
                        </h3>
                        <div
                            ref={chartContainerRef}
                            className="w-full overflow-hidden"
                        >
                            {chartWidth > 0 &&
                                (chartType === 'bar' ? (
                                    usageData.time_series.length > 0 ? (
                                        <UsageBarChart
                                            data={usageData.time_series}
                                            width={chartWidth}
                                            height={isMobile ? 240 : 400}
                                            viewMode={viewMode}
                                        />
                                    ) : (
                                        <div className="flex items-center justify-center h-48 text-muted-foreground dark:text-zinc-500">
                                            No usage data for this period
                                        </div>
                                    )
                                ) : pieChartData.length > 0 ? (
                                    <div
                                        className={
                                            isMobile
                                                ? 'w-full'
                                                : 'flex items-center justify-center'
                                        }
                                    >
                                        <UsagePieChart
                                            data={pieChartData}
                                            width={
                                                isMobile
                                                    ? chartWidth
                                                    : Math.min(chartWidth, 500)
                                            }
                                            height={isMobile ? chartWidth : 400}
                                            title={
                                                viewMode === 'type'
                                                    ? 'Resource Usage'
                                                    : 'Model Usage'
                                            }
                                            showLabels={!isMobile}
                                        />
                                    </div>
                                ) : (
                                    <div className="flex items-center justify-center h-48 text-muted-foreground dark:text-zinc-500">
                                        No usage data for this period
                                    </div>
                                ))}
                        </div>
                    </Card>

                    {/* Summary cards */}
                    <div className="grid grid-cols-2 sm:grid-cols-1 md:grid-cols-3 gap-3 sm:gap-4">
                        <Card className="p-4 sm:p-6 bg-card/50 border-border">
                            <h4 className="text-xs sm:text-sm font-medium text-muted-foreground dark:text-zinc-500 mb-1 sm:mb-2">
                                Total Cost
                            </h4>
                            <p className="text-xl sm:text-2xl font-bold text-foreground">
                                {formatCredits(usageData.total_cost)}
                            </p>
                        </Card>

                        {Object.entries(usageData.usage_by_type).map(
                            ([type, cost]) => (
                                <Card
                                    key={type}
                                    className="p-4 sm:p-6 bg-card/50 border-border"
                                >
                                    <h4 className="text-xs sm:text-sm font-medium text-muted-foreground dark:text-zinc-500 mb-1 sm:mb-2">
                                        {type.replace('_', ' ').toUpperCase()}
                                    </h4>
                                    <p className="text-xl sm:text-2xl font-bold text-foreground">
                                        {formatCredits(cost)}
                                    </p>
                                </Card>
                            )
                        )}
                    </div>

                    <RecentUsageEventsTable
                        logsData={usageLogsData}
                        loading={logsLoading}
                        loadingMore={logsLoadingMore}
                        hasMore={logsHasMore}
                        filters={logFilters}
                        onFiltersChange={setLogFilters}
                        onLoadMore={loadMoreLogs}
                    />

                    <TopModelsTable usageData={usageData} />
                </>
            )}
        </div>
    );
}
