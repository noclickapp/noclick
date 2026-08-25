/**
 * Usage Drawer Component - Compact Chart Viewer
 *
 * Displays the last 7 days of usage in a drawer: bar/pie toggle, by-model only,
 * no legends, link to the full dashboard. Shares data shapes, colors, and the
 * real-time usage:event merge with UsageDashboard via ~/lib/usage — including
 * the `last7days-*` cache slot, so both surfaces MUST apply events with the
 * same pure functional-update logic or they corrupt each other's cache.
 */

import React, {
    useState,
    useEffect,
    useRef,
    useMemo,
    useCallback,
} from 'react';
import { BarStack } from '@visx/shape';
import Pie from '@visx/shape/lib/shapes/Pie';
import { Group } from '@visx/group';
import { Grid } from '@visx/grid';
import { scaleBand, scaleLinear } from '@visx/scale';
import { useTooltip, useTooltipInPortal } from '@visx/tooltip';
import { localPoint } from '@visx/event';
import { sendEventAsync, UsageDataRequest } from '~/lib/socket-sender';
import { Card } from '~/components/ui/card';
import {
    X,
    ExternalLink,
    BarChart3,
    PieChart as PieChartIcon,
} from 'lucide-react';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useOrgContext } from '~/hooks/useOrgContext';
import { useCreditUsage } from '~/hooks/useCreditUsage';
import { useSocketEvent } from '~/hooks/useSocketEvent';
import type { UsageEventUpdateEvent } from '~/types/socket-events.generated';
import { formatCredits } from '~/lib/formatCredits';
import {
    applyEventToUsageData,
    assignSeriesColors,
    CHART_THEME,
    eventMatchesWorkspace,
    formatUtcDay,
    getDisplayName,
    USAGE_TOOLTIP_STYLES,
    type CachedUsageData,
    type TimeSeriesEntry,
    type UsageData,
} from '~/lib/usage';

// Cache TTL matches the backend handler's TTLCache (5 minutes).
const CACHE_TTL_MS = 5 * 60 * 1000;

const drawerTooltipStyles: React.CSSProperties = {
    ...USAGE_TOOLTIP_STYLES,
    minWidth: 100,
    backgroundColor: 'hsl(var(--popover) / 0.98)',
    borderRadius: '6px',
    padding: '8px 10px',
    fontSize: '11px',
    zIndex: 10000,
};

interface UsageDrawerProps {
    onClose: () => void;
    onNavigateToDashboard?: () => void;
}

interface BarTooltipData {
    key: string;
    entry: TimeSeriesEntry;
    color: string;
}

// Compact Bar Chart (no legend, hover only)
function CompactBarChart({
    data,
    width,
    height,
}: {
    data: TimeSeriesEntry[];
    width: number;
    height: number;
}) {
    const {
        tooltipOpen,
        tooltipLeft,
        tooltipTop,
        tooltipData,
        hideTooltip,
        showTooltip,
    } = useTooltip<BarTooltipData>();
    const { containerRef, TooltipInPortal } = useTooltipInPortal({
        scroll: true,
    });

    const margin = { top: 5, right: 10, bottom: 15, left: 45 };

    const keys = useMemo(
        () =>
            Array.from(new Set(data.flatMap((d) => Object.keys(d.by_subtype)))),
        [data]
    );
    // Shared stable assignment — same series color as the full dashboard.
    const seriesColors = useMemo(() => assignSeriesColors(keys), [keys]);

    const maxCost = useMemo(
        () => Math.max(...data.map((d) => d.total_cost), 0),
        [data]
    );

    const xMax = width - margin.left - margin.right;
    const yMax = height - margin.top - margin.bottom;

    if (width < 10 || !data.length) return null;

    const dateScale = scaleBand<string>({
        domain: data.map((d) => d.date),
        padding: 0.3,
        range: [0, xMax],
    });

    const costScale = scaleLinear<number>({
        domain: [0, maxCost * 1.1],
        nice: true,
        range: [yMax, 0],
    });

    return (
        <div style={{ position: 'relative', width: '100%' }}>
            <svg ref={containerRef} width={width} height={height}>
                <rect
                    x={0}
                    y={0}
                    width={width}
                    height={height}
                    fill="transparent"
                />
                {/* Grid lines - rendered behind bars */}
                <Grid
                    top={margin.top}
                    left={margin.left}
                    xScale={dateScale}
                    yScale={costScale}
                    width={xMax}
                    height={yMax}
                    stroke={CHART_THEME.gridStroke}
                    strokeOpacity={0.3}
                    xOffset={dateScale.bandwidth() / 2}
                />
                <Group top={margin.top} left={margin.left}>
                    <BarStack<TimeSeriesEntry, string>
                        data={data}
                        keys={keys}
                        x={(d) => d.date}
                        xScale={dateScale}
                        yScale={costScale}
                        color={(key) => seriesColors[key]}
                        value={(d, key) => d.by_subtype[key] || 0}
                    >
                        {(barStacks) =>
                            barStacks.map((barStack) =>
                                barStack.bars.map((bar) => (
                                    <rect
                                        key={`bar-stack-${barStack.index}-${bar.index}`}
                                        x={bar.x}
                                        y={bar.y}
                                        height={bar.height}
                                        width={bar.width}
                                        fill={bar.color}
                                        onMouseLeave={hideTooltip}
                                        onMouseMove={(event) => {
                                            const coords = localPoint(event);
                                            showTooltip({
                                                tooltipData: {
                                                    key: barStack.key,
                                                    entry: data[bar.index],
                                                    color: bar.color,
                                                },
                                                tooltipTop: coords?.y,
                                                tooltipLeft: coords?.x,
                                            });
                                        }}
                                        style={{ cursor: 'pointer' }}
                                    />
                                ))
                            )
                        }
                    </BarStack>
                    {/* Y-axis labels */}
                    {costScale.ticks(4).map((tick) => (
                        <text
                            key={tick}
                            x={-8}
                            y={costScale(tick)}
                            dy="0.32em"
                            fill={CHART_THEME.textMuted}
                            fontSize={9}
                            textAnchor="end"
                        >
                            {formatCredits(tick)}
                        </text>
                    ))}
                    {/* X-axis ticks */}
                    {data.map((d, i) => (
                        <text
                            key={i}
                            x={
                                (dateScale(d.date) || 0) +
                                dateScale.bandwidth() / 2
                            }
                            y={yMax + 12}
                            fill={CHART_THEME.textMuted}
                            fontSize={9}
                            textAnchor="middle"
                        >
                            {formatUtcDay(d.date)}
                        </text>
                    ))}
                </Group>
            </svg>

            {tooltipOpen && tooltipData && (
                <TooltipInPortal
                    top={tooltipTop}
                    left={tooltipLeft}
                    style={drawerTooltipStyles}
                >
                    <div style={{ fontWeight: 600, marginBottom: '4px' }}>
                        {getDisplayName(tooltipData.key)}
                    </div>
                    <div style={{ color: tooltipData.color }}>
                        {formatCredits(
                            tooltipData.entry.by_subtype[tooltipData.key] || 0
                        )}
                    </div>
                    <div
                        style={{
                            marginTop: '4px',
                            paddingTop: '4px',
                            borderTop: `1px solid ${CHART_THEME.border}`,
                            fontSize: '10px',
                        }}
                    >
                        Total: {formatCredits(tooltipData.entry.total_cost)}
                    </div>
                </TooltipInPortal>
            )}
        </div>
    );
}

// Compact Pie Chart (no legend, hover only)
interface PieData {
    key: string;
    label: string;
    value: number;
    color: string;
    percentage: string;
}

function CompactPieChart({
    data,
    width,
    height,
}: {
    data: PieData[];
    width: number;
    height: number;
}) {
    const [hoveredSlice, setHoveredSlice] = useState<PieData | null>(null);
    const {
        tooltipOpen,
        tooltipLeft,
        tooltipTop,
        tooltipData,
        hideTooltip,
        showTooltip,
    } = useTooltip<PieData>();
    const { containerRef, TooltipInPortal } = useTooltipInPortal({
        scroll: true,
    });

    const radius = Math.min(width, height) / 2 - 20;
    const centerX = width / 2;
    const centerY = height / 2;

    const total = useMemo(
        () => data.reduce((sum, d) => sum + d.value, 0),
        [data]
    );

    return (
        <div
            style={{
                position: 'relative',
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
            }}
        >
            {/* 7d label in top left corner */}
            <div
                style={{
                    position: 'absolute',
                    top: '8px',
                    left: '8px',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: CHART_THEME.textMuted,
                    backgroundColor: 'hsl(var(--background) / 0.6)',
                    padding: '4px 8px',
                    borderRadius: '4px',
                    zIndex: 1,
                }}
            >
                7d
            </div>
            <svg ref={containerRef} width={width} height={height}>
                <Group top={centerY} left={centerX}>
                    <Pie
                        data={data}
                        pieValue={(d) => d.value}
                        outerRadius={radius}
                        innerRadius={radius * 0.6}
                        cornerRadius={3}
                        padAngle={0.02}
                    >
                        {(pie) => {
                            return pie.arcs.map((arc) => {
                                const isHovered =
                                    hoveredSlice?.key === arc.data.key;

                                return (
                                    <g
                                        key={`arc-${arc.data.key}`}
                                        onMouseEnter={(event) => {
                                            setHoveredSlice(arc.data);
                                            const coords = localPoint(event);
                                            showTooltip({
                                                tooltipData: arc.data,
                                                tooltipTop: coords?.y,
                                                tooltipLeft: coords?.x,
                                            });
                                        }}
                                        onMouseLeave={() => {
                                            setHoveredSlice(null);
                                            hideTooltip();
                                        }}
                                        style={{ cursor: 'pointer' }}
                                    >
                                        <path
                                            d={pie.path(arc) || ''}
                                            fill={arc.data.color}
                                            opacity={isHovered ? 1.0 : 0.85}
                                            style={{
                                                transition: 'opacity 0.2s ease',
                                            }}
                                        />
                                    </g>
                                );
                            });
                        }}
                    </Pie>

                    {/* Center text */}
                    <text
                        textAnchor="middle"
                        fill={CHART_THEME.text}
                        fontSize={12}
                        fontWeight={600}
                        dy="-0.5em"
                    >
                        {hoveredSlice ? hoveredSlice.label : 'Total'}
                    </text>
                    <text
                        textAnchor="middle"
                        fill={
                            hoveredSlice ? hoveredSlice.color : CHART_THEME.text
                        }
                        fontSize={14}
                        fontWeight={700}
                        dy="1em"
                    >
                        {formatCredits(
                            hoveredSlice ? hoveredSlice.value : total
                        )}
                    </text>
                    {hoveredSlice && (
                        <text
                            textAnchor="middle"
                            fill={CHART_THEME.textMuted}
                            fontSize={10}
                            dy="2.5em"
                        >
                            {hoveredSlice.percentage}%
                        </text>
                    )}
                </Group>
            </svg>

            {tooltipOpen && tooltipData && (
                <TooltipInPortal
                    top={tooltipTop}
                    left={tooltipLeft}
                    style={drawerTooltipStyles}
                >
                    <div style={{ fontWeight: 600, marginBottom: '4px' }}>
                        {tooltipData.label}
                    </div>
                    <div style={{ color: tooltipData.color }}>
                        {formatCredits(tooltipData.value)}
                    </div>
                    <div
                        style={{
                            marginTop: '4px',
                            fontSize: '10px',
                            color: CHART_THEME.textMuted,
                        }}
                    >
                        {tooltipData.percentage}% of total
                    </div>
                </TooltipInPortal>
            )}
        </div>
    );
}

export function UsageDrawer({
    onClose,
    onNavigateToDashboard,
}: UsageDrawerProps) {
    const [usageData, setUsageData] = useState<UsageData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [chartType, setChartType] = useState<'bar' | 'pie'>('bar');
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const [chartWidth, setChartWidth] = useState(300);
    const [orgContext] = useOrgContext();
    const workspaceId = orgContext.id;
    // Pool owner of the view we're showing — used to filter live usage events in
    // the personal view (see eventMatchesWorkspace).
    const { poolUserId } = useCreditUsage();

    // Cache key is partitioned by workspace so personal and per-org slots don't
    // collide. The slot is SHARED with UsageDashboard's 7d cache.
    const cacheSuffix = workspaceId ? `org-${workspaceId}` : 'personal';
    const [cachedUsage, setCachedUsage] =
        useCachedValtioState<CachedUsageData | null>(
            'noclick-usage',
            `last7days-${cacheSuffix}`,
            null
        );

    // Latest-value ref so the TTL check doesn't put the cache VALUE in
    // fetchUsageData's deps (every fetch writes the cache, which would recreate
    // the callback and re-run the fetch effect on its own write).
    const cachedUsageRef = useRef<CachedUsageData | null>(null);
    cachedUsageRef.current = cachedUsage;

    const fetchUsageData = useCallback(async () => {
        const cached = cachedUsageRef.current;
        if (cached?.timestamp && Date.now() - cached.timestamp < CACHE_TTL_MS) {
            setUsageData(cached.data);
            setLoading(false);
            return;
        }

        // Cache miss or expired - fetch from backend
        setLoading(true);
        setError(null);

        try {
            const endDate = new Date();
            const startDate = new Date();
            startDate.setDate(startDate.getDate() - 7); // Last 7 days

            const response = await sendEventAsync(
                UsageDataRequest.create({
                    start_date: startDate.toISOString(),
                    end_date: endDate.toISOString(),
                    group_by: 'day',
                    limit: 10,
                    organization_id: workspaceId ?? undefined,
                })
            );

            const data = response as UsageData;
            setUsageData(data);
            setCachedUsage({ data, timestamp: Date.now() });
        } catch (err) {
            setError(
                err instanceof Error
                    ? err.message
                    : 'Failed to fetch usage data'
            );
            console.error('[UsageDrawer] Error fetching usage data:', err);
        } finally {
            setLoading(false);
        }
    }, [setCachedUsage, workspaceId]);

    // Initial fetch + refetch when the active workspace changes. Without the
    // workspaceId-driven refetch, switching workspaces would keep showing the
    // previous workspace's totals until the drawer was closed and reopened.
    useEffect(() => {
        fetchUsageData();
    }, [fetchUsageData]);

    // Live usage events merge into both the drawer state and the shared 7d
    // cache slot. Both writes are pure functional updates (see UsageDashboard's
    // handler for the burst/StrictMode rationale). No date-window check needed:
    // a live event is always inside "the last 7 days".
    useSocketEvent('usage:event', (event: UsageEventUpdateEvent) => {
        if (!eventMatchesWorkspace(event, workspaceId, poolUserId)) return;

        setUsageData((prev) =>
            prev ? applyEventToUsageData(prev, event) : prev
        );
        setCachedUsage((prev) =>
            prev?.data
                ? {
                      data: applyEventToUsageData(prev.data, event),
                      timestamp: prev.timestamp,
                  }
                : prev
        );
    });

    // Handle chart width responsively with minimal padding
    useEffect(() => {
        if (!chartContainerRef.current) return;

        const updateWidth = () => {
            if (chartContainerRef.current) {
                const containerWidth = chartContainerRef.current.offsetWidth;
                // Use full container width for proper responsiveness
                setChartWidth(Math.max(250, containerWidth));
            }
        };

        // Initial width with delay to ensure DOM is ready
        const timeoutId = setTimeout(updateWidth, 0);

        const resizeObserver = new ResizeObserver(() => {
            updateWidth();
        });

        resizeObserver.observe(chartContainerRef.current);
        return () => {
            clearTimeout(timeoutId);
            resizeObserver.disconnect();
        };
    }, [usageData, loading]);

    // Prepare pie chart data with pre-calculated percentages; colors from the
    // shared stable assignment so slices match the dashboard.
    const pieChartData = useMemo<PieData[]>(() => {
        if (!usageData) return [];

        const entries = Object.entries(usageData.usage_by_subtype);
        const total = entries.reduce((sum, [, value]) => sum + value, 0);
        const seriesColors = assignSeriesColors(entries.map(([key]) => key));

        return entries
            .map(([key, value]) => ({
                key,
                label: getDisplayName(key),
                value,
                color: seriesColors[key],
                percentage:
                    total > 0 ? ((value / total) * 100).toFixed(1) : '0.0',
            }))
            .sort((a, b) => b.value - a.value);
    }, [usageData]);

    const handleViewFullDashboard = () => {
        if (onNavigateToDashboard) {
            onNavigateToDashboard();
        }
    };

    return (
        <div className="h-full flex flex-col bg-card text-foreground min-h-0 overflow-hidden rounded-t-xl">
            {/* Header - minimal, top-right positioning like / drawer */}
            <div className="flex items-center justify-between px-4 pt-2 pb-1 shrink-0">
                <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    Usage
                </h2>
                <button
                    onClick={onClose}
                    aria-label="Close"
                    className="text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors"
                >
                    <X className="w-4 h-4" />
                </button>
            </div>

            {/* Content - No scroll, fixed height content */}
            <div className="flex-1 min-h-0 overflow-hidden px-4 pb-4 space-y-1.5">
                {loading && (
                    <div className="space-y-3">
                        <Card className="p-4 bg-muted/50 border-border dark:border-zinc-700">
                            <div className="h-4 bg-muted dark:bg-zinc-700 rounded w-32 mb-3 animate-pulse" />
                            <div className="h-[240px] bg-muted/30 dark:bg-zinc-700/30 rounded animate-pulse" />
                        </Card>
                    </div>
                )}

                {error && !loading && (
                    <Card className="p-4 bg-muted/50 border-red-300 dark:border-red-900/50">
                        <div className="text-sm text-red-600 dark:text-red-400">
                            Error: {error}
                        </div>
                    </Card>
                )}

                {!loading && !error && usageData && (
                    <>
                        {/* Controls Row: Chart Type Toggle + Navigation Button - all same height */}
                        <div className="flex items-center justify-between gap-3">
                            {/* Chart Type Toggle */}
                            <div className="flex gap-2">
                                <button
                                    onClick={() => setChartType('bar')}
                                    aria-pressed={chartType === 'bar'}
                                    className={`h-8 px-3 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${
                                        chartType === 'bar'
                                            ? 'bg-primary text-primary-foreground'
                                            : 'bg-secondary text-muted-foreground hover:bg-secondary/80 dark:hover:bg-zinc-700'
                                    }`}
                                >
                                    <BarChart3 className="w-3.5 h-3.5" />
                                    Bar
                                </button>
                                <button
                                    onClick={() => setChartType('pie')}
                                    aria-pressed={chartType === 'pie'}
                                    className={`h-8 px-3 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${
                                        chartType === 'pie'
                                            ? 'bg-primary text-primary-foreground'
                                            : 'bg-secondary text-muted-foreground hover:bg-secondary/80 dark:hover:bg-zinc-700'
                                    }`}
                                >
                                    <PieChartIcon className="w-3.5 h-3.5" />
                                    Pie
                                </button>
                            </div>

                            {/* Navigation Button - same height as filter buttons */}
                            <button
                                onClick={handleViewFullDashboard}
                                className="h-8 px-3 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 shrink-0 bg-primary text-primary-foreground hover:bg-secondary dark:hover:bg-zinc-700 hover:text-secondary-foreground"
                            >
                                <span>Full Dashboard</span>
                                <ExternalLink className="w-3 h-3" />
                            </button>
                        </div>

                        {/* Chart - no title, chart takes up full space with minimal padding */}
                        <Card className="p-2 bg-muted/50 border-border dark:border-zinc-700">
                            <div ref={chartContainerRef} className="w-full">
                                {chartType === 'bar' ? (
                                    usageData.time_series.length > 0 ? (
                                        <CompactBarChart
                                            data={usageData.time_series}
                                            width={chartWidth}
                                            height={240}
                                        />
                                    ) : (
                                        <div className="flex items-center justify-center h-[240px] text-muted-foreground dark:text-zinc-500 text-xs">
                                            No data available
                                        </div>
                                    )
                                ) : pieChartData.length > 0 ? (
                                    <CompactPieChart
                                        data={pieChartData}
                                        width={chartWidth}
                                        height={240}
                                    />
                                ) : (
                                    <div className="flex items-center justify-center h-[240px] text-muted-foreground dark:text-zinc-500 text-xs">
                                        No data available
                                    </div>
                                )}
                            </div>
                        </Card>
                    </>
                )}
            </div>
        </div>
    );
}
