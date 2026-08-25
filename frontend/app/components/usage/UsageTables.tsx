// The usage dashboard's two tables: the live recent-events log (with search,
// category filters, and infinite scroll over the full event history) and the
// Cursor-style "Top Models & Services" cost ranking. Category chips derive
// their colors from the same RESOURCE_TYPE_COLORS the charts use, so a badge
// always matches its bar/pie slice.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { Card } from '~/components/ui/card';
import { ScrollArea } from '~/components/ui/scroll-area';
import { cn } from '~/lib/utils';
import { formatCredits } from '~/lib/formatCredits';
import { formatQuantity } from '~/lib/formatQuantity';
import {
    formatUtcDay,
    getDisplayName,
    USAGE_TYPE_LABEL,
    usageTypeBadgeStyle,
    type UsageData,
    type UsageLogFilters,
    type UsageLogsData,
} from '~/lib/usage';

const headerCell =
    'py-3 px-4 text-xs font-semibold text-muted-foreground dark:text-zinc-500 uppercase tracking-wider';
// Recent-events header sticks inside the internal scroll container; needs an
// opaque background so rows don't show through as they pass underneath.
const stickyHeaderCell = `${headerCell} sticky top-0 z-10 bg-card border-b border-border`;

const SEARCH_DEBOUNCE_MS = 300;

function formatCost(credits: number): string {
    return credits > 0 ? formatCredits(credits) : '-';
}

export function RecentUsageEventsTable({
    logsData,
    loading,
    loadingMore,
    hasMore,
    filters,
    onFiltersChange,
    onLoadMore,
}: {
    logsData: UsageLogsData | null;
    loading: boolean;
    loadingMore: boolean;
    hasMore: boolean;
    filters: UsageLogFilters;
    onFiltersChange: (filters: UsageLogFilters) => void;
    onLoadMore: () => void;
}) {
    // Local input state so typing is instant; the server-side filter fires
    // after a debounce.
    const [searchInput, setSearchInput] = useState(filters.search);
    useEffect(() => {
        if (searchInput === filters.search) return;
        const t = setTimeout(
            () => onFiltersChange({ ...filters, search: searchInput }),
            SEARCH_DEBOUNCE_MS
        );
        return () => clearTimeout(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [searchInput]);

    // Infinite scroll INSIDE the table's own scroll container (the page
    // doesn't grow): a sentinel below the rows asks for the next page as it
    // approaches the container's bottom edge. Callback via ref so the
    // observer doesn't re-attach on every render.
    const onLoadMoreRef = useRef(onLoadMore);
    onLoadMoreRef.current = onLoadMore;
    const scrollRef = useRef<HTMLDivElement>(null);
    const sentinelRef = useRef<HTMLDivElement>(null);
    const sentinelActive = hasMore && !loading;
    useEffect(() => {
        const el = sentinelRef.current;
        if (!el || !sentinelActive) return;
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0]?.isIntersecting) onLoadMoreRef.current();
            },
            { root: scrollRef.current, rootMargin: '0px 0px 200px 0px' }
        );
        observer.observe(el);
        return () => observer.disconnect();
    }, [sentinelActive]);

    const hasActiveFilters =
        filters.search.trim() !== '' || filters.usageType !== null;

    return (
        <Card className="p-3 sm:p-6 bg-card/50 border-border overflow-hidden">
            <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
                <h3 className="text-base sm:text-lg font-semibold text-foreground">
                    Recent Usage Events
                </h3>
                <div className="relative w-full sm:w-64">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/70 dark:text-white/30" />
                    <input
                        type="text"
                        placeholder="Search models & services..."
                        value={searchInput}
                        onChange={(e) => setSearchInput(e.target.value)}
                        className="w-full h-8 pl-8 pr-3 text-xs bg-foreground/[0.04] border border-input dark:border-white/[0.08] rounded-lg text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none focus:border-muted-foreground/40 dark:focus:border-white/[0.15] transition-colors"
                    />
                </div>
            </div>

            {/* Category pills — the active pill wears its chart color. */}
            <div className="flex items-center gap-1.5 flex-wrap mb-3 sm:mb-4">
                <button
                    type="button"
                    aria-pressed={filters.usageType === null}
                    onClick={() =>
                        onFiltersChange({ ...filters, usageType: null })
                    }
                    className={cn(
                        'h-7 px-2.5 text-xs font-medium rounded-md transition-colors',
                        filters.usageType === null
                            ? 'bg-foreground/[0.08] text-accent-foreground dark:text-white/90'
                            : 'text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.04]'
                    )}
                >
                    All
                </button>
                {Object.entries(USAGE_TYPE_LABEL).map(([type, label]) => {
                    const active = filters.usageType === type;
                    return (
                        <button
                            key={type}
                            type="button"
                            aria-pressed={active}
                            onClick={() =>
                                onFiltersChange({
                                    ...filters,
                                    usageType: active ? null : type,
                                })
                            }
                            className={cn(
                                'h-7 px-2.5 text-xs font-medium rounded-md transition-colors',
                                !active &&
                                    'text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.04]'
                            )}
                            style={
                                active ? usageTypeBadgeStyle(type) : undefined
                            }
                        >
                            {label}
                        </button>
                    );
                })}
            </div>

            {loading && !logsData ? (
                <div className="flex items-center justify-center h-48">
                    <div className="text-muted-foreground/70 dark:text-zinc-600 text-sm">
                        Loading recent events...
                    </div>
                </div>
            ) : logsData && logsData.logs.length > 0 ? (
                // Internal scroll with Radix overlay scrollbars: the native bar
                // (which always spans the full container and reserves a gutter
                // beside the last column) is replaced by a floating thumb whose
                // track starts BELOW the sticky header — mt-[41px] = header
                // py-3 ×2 + one text-xs line + 1px border.
                <ScrollArea
                    type="auto"
                    horizontal
                    viewportRef={scrollRef}
                    viewportClassName="max-h-[480px]"
                    scrollBarClassName="mt-[41px] mb-1"
                    className={cn(
                        'rounded-lg border border-border/60 dark:border-zinc-800/60',
                        loading && 'opacity-50 pointer-events-none'
                    )}
                >
                    <table className="w-full">
                        <thead>
                            {/* Sticky header: the border lives on the th cells
                                (a tr border wouldn't stick with them). The end
                                cells round their own top corners — the header
                                block stops at the scrollbar gutter, so the
                                container's radius clipping can't do it. */}
                            <tr>
                                <th
                                    scope="col"
                                    className={`text-left rounded-tl-lg ${stickyHeaderCell}`}
                                >
                                    Timestamp
                                </th>
                                <th
                                    scope="col"
                                    className={`text-left ${stickyHeaderCell}`}
                                >
                                    Category
                                </th>
                                <th
                                    scope="col"
                                    className={`text-left ${stickyHeaderCell}`}
                                >
                                    Resource
                                </th>
                                <th
                                    scope="col"
                                    className={`text-right ${stickyHeaderCell}`}
                                >
                                    Count
                                </th>
                                <th
                                    scope="col"
                                    className={`text-right rounded-tr-lg ${stickyHeaderCell}`}
                                >
                                    Cost
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border/50 dark:divide-zinc-800/50">
                            {logsData.logs.map((log, index) => {
                                // Full timestamps are instants — local-time display is correct
                                // here (unlike the UTC day buckets in the charts).
                                const formattedTimestamp = new Date(
                                    log.timestamp
                                ).toLocaleString('en-US', {
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                });
                                const categoryLabel = log.usage_type
                                    ? (USAGE_TYPE_LABEL[log.usage_type] ??
                                      log.usage_type)
                                    : '—';

                                return (
                                    <tr
                                        key={`${log.timestamp}-${log.model}-${index}`}
                                        className="hover:bg-accent/50 dark:hover:bg-zinc-800/30 transition-colors"
                                    >
                                        <td className="py-3 px-4 text-sm text-muted-foreground whitespace-nowrap">
                                            {formattedTimestamp}
                                        </td>
                                        <td className="py-3 px-4 whitespace-nowrap">
                                            <span
                                                className="inline-block text-[11px] font-medium px-2 py-0.5 rounded"
                                                style={usageTypeBadgeStyle(
                                                    log.usage_type
                                                )}
                                            >
                                                {categoryLabel}
                                            </span>
                                        </td>
                                        <td className="py-3 px-4 text-sm text-muted-foreground dark:text-zinc-300 font-medium">
                                            {getDisplayName(log.model)}
                                        </td>
                                        <td className="py-3 px-4 text-sm text-muted-foreground text-right font-mono">
                                            {formatQuantity(
                                                log.tokens,
                                                log.unit_type
                                            )}
                                        </td>
                                        <td className="py-3 px-4 text-sm text-foreground text-right font-mono font-medium">
                                            {formatCost(log.cost)}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                    {hasMore && (
                        <div
                            ref={sentinelRef}
                            className="flex items-center justify-center py-4"
                        >
                            <span className="text-xs text-muted-foreground/70 dark:text-zinc-600">
                                {loadingMore
                                    ? 'Loading more events...'
                                    : 'Scroll for more'}
                            </span>
                        </div>
                    )}
                </ScrollArea>
            ) : (
                <div className="flex items-center justify-center h-48 text-muted-foreground dark:text-zinc-500">
                    {hasActiveFilters
                        ? 'No events match your filters'
                        : 'No recent usage events'}
                </div>
            )}
        </Card>
    );
}

export function TopModelsTable({ usageData }: { usageData: UsageData }) {
    const rows = useMemo(
        () =>
            usageData.time_series
                .flatMap((entry) =>
                    Object.entries(entry.by_subtype)
                        .filter(([, cost]) => cost > 0)
                        .map(([model, cost]) => ({
                            date: entry.date,
                            model,
                            cost,
                            tokens: entry.tokens_by_subtype?.[model] || 0,
                        }))
                )
                .sort((a, b) =>
                    b.cost !== a.cost
                        ? b.cost - a.cost
                        : a.model.localeCompare(b.model)
                )
                .slice(0, 15),
        [usageData.time_series]
    );

    if (!rows.length) return null;

    return (
        <Card className="p-3 sm:p-6 bg-card/50 border-border overflow-hidden">
            <h3 className="text-base sm:text-lg font-semibold text-foreground mb-3 sm:mb-4">
                Top Models & Services
            </h3>
            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead>
                        <tr className="border-b border-border">
                            <th
                                scope="col"
                                className={`text-left ${headerCell}`}
                            >
                                Date
                            </th>
                            <th
                                scope="col"
                                className={`text-left ${headerCell}`}
                            >
                                Model
                            </th>
                            <th
                                scope="col"
                                className={`text-right ${headerCell}`}
                            >
                                Count
                            </th>
                            <th
                                scope="col"
                                className={`text-right ${headerCell}`}
                            >
                                Cost
                            </th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border/50 dark:divide-zinc-800/50">
                        {rows.map((row, index) => (
                            <tr
                                key={`${row.date}-${row.model}-${index}`}
                                className="hover:bg-accent/50 dark:hover:bg-zinc-800/30 transition-colors"
                            >
                                <td className="py-3 px-4 text-sm text-muted-foreground whitespace-nowrap">
                                    {formatUtcDay(row.date)}
                                </td>
                                <td className="py-3 px-4 text-sm text-muted-foreground dark:text-zinc-300 font-medium">
                                    {getDisplayName(row.model)}
                                </td>
                                <td className="py-3 px-4 text-sm text-muted-foreground text-right font-mono">
                                    {formatQuantity(
                                        row.tokens,
                                        usageData.units_by_subtype?.[row.model]
                                    )}
                                </td>
                                <td className="py-3 px-4 text-sm text-foreground text-right font-mono font-medium">
                                    {formatCost(row.cost)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </Card>
    );
}
