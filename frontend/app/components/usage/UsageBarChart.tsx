// Stacked-bar cost-over-time chart for the usage dashboard, with a sorted
// legend that highlights a series on hover (or click, for touch). Extracted
// from UsageDashboard.tsx; colors come from the shared usage theme so a
// series keeps the same color here, in the pie view, and in the drawer.

import React, { useMemo, useState } from 'react';
import { BarStack } from '@visx/shape';
import { Group } from '@visx/group';
import { Grid } from '@visx/grid';
import { AxisBottom, AxisLeft } from '@visx/axis';
import { scaleBand, scaleLinear } from '@visx/scale';
import { useTooltip, useTooltipInPortal } from '@visx/tooltip';
import { localPoint } from '@visx/event';
import { cn } from '~/lib/utils';
import { formatCredits } from '~/lib/formatCredits';
import {
    assignSeriesColors,
    CHART_THEME,
    colorForUsageType,
    formatUtcDay,
    getDisplayName,
    USAGE_TOOLTIP_STYLES,
    type TimeSeriesEntry,
} from '~/lib/usage';

export interface UsageBarChartProps {
    data: TimeSeriesEntry[];
    width: number;
    height: number;
    margin?: { top: number; right: number; bottom: number; left: number };
    viewMode: 'type' | 'model';
}

interface BarTooltipData {
    key: string;
    entry: TimeSeriesEntry;
}

const defaultMargin = { top: 20, right: 20, bottom: 60, left: 70 };
const mobileMargin = { top: 10, right: 10, bottom: 50, left: 70 };

export const UsageBarChart = React.memo(function UsageBarChart({
    data,
    width,
    height,
    margin,
    viewMode,
}: UsageBarChartProps) {
    const isMobileChart = width < 400;
    const resolvedMargin =
        margin ?? (isMobileChart ? mobileMargin : defaultMargin);
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
    // Hover highlights transiently; click pins (hover is useless on touch).
    const [hoveredKey, setHoveredKey] = useState<string | null>(null);
    const [pinnedKey, setPinnedKey] = useState<string | null>(null);
    const activeKey = hoveredKey ?? pinnedKey;

    // Sort series by total cost descending so the biggest contributors appear at the
    // bottom of the stack (stable visual base) and at the top of the legend (most relevant).
    const { keys, totalsByKey } = useMemo(() => {
        const dataSource = viewMode === 'type' ? 'by_type' : 'by_subtype';
        const totals: Record<string, number> = {};
        for (const entry of data) {
            for (const [k, v] of Object.entries(entry[dataSource])) {
                totals[k] = (totals[k] || 0) + (v || 0);
            }
        }
        const sortedKeys = Object.keys(totals)
            .filter((k) => totals[k] > 0)
            .sort((a, b) => totals[b] - totals[a]);
        return { keys: sortedKeys, totalsByKey: totals };
    }, [data, viewMode]);

    // Keyed colors: semantic per usage_type, stable-hash per model/service.
    const colorFor = useMemo(() => {
        if (viewMode === 'type') return colorForUsageType;
        const assigned = assignSeriesColors(keys);
        return (key: string) => assigned[key];
    }, [viewMode, keys]);

    const maxCost = useMemo(
        () => Math.max(...data.map((d) => d.total_cost), 0),
        [data]
    );

    const xMax = width - resolvedMargin.left - resolvedMargin.right;
    const yMax = height - resolvedMargin.top - resolvedMargin.bottom;

    if (width < 10 || !data.length || !keys.length) return null;

    // Pick a single precision for the y-axis based on the chart's max so we don't show
    // "$0.0900, $0.1000" with trailing zeros when the data is just a few cents.
    // All numeric values here are credits from the backend (see
    // usage_dashboard_handler.py boundary comment) — no unit math, just precision.
    const tickPrecision =
        maxCost >= 100 ? 0 : maxCost >= 10 ? 1 : maxCost >= 1 ? 2 : 3;
    const formatAxisCost = (credits: number) =>
        credits === 0 ? '0' : credits.toFixed(tickPrecision);

    // Scales — increase padding when few data points to avoid overly wide bars
    const barPadding = data.length <= 3 ? 0.6 : data.length <= 7 ? 0.4 : 0.2;
    const dateScale = scaleBand<string>({
        domain: data.map((d) => d.date),
        padding: barPadding,
    });
    const costScale = scaleLinear<number>({
        domain: [0, maxCost * 1.1],
        nice: true,
    });

    dateScale.rangeRound([0, xMax]);
    costScale.range([yMax, 0]);

    const formatDate = (dateKey: string) =>
        formatUtcDay(dateKey, { short: isMobileChart });

    return (
        <div>
            <svg
                ref={containerRef}
                width={width}
                height={height}
                style={{ overflow: 'hidden', display: 'block' }}
            >
                <rect
                    x={0}
                    y={0}
                    width={width}
                    height={height}
                    fill={CHART_THEME.background}
                    rx={8}
                />
                <Grid
                    top={resolvedMargin.top}
                    left={resolvedMargin.left}
                    xScale={dateScale}
                    yScale={costScale}
                    width={xMax}
                    height={yMax}
                    stroke={CHART_THEME.gridStroke}
                    strokeOpacity={0.3}
                    xOffset={dateScale.bandwidth() / 2}
                />
                <Group top={resolvedMargin.top} left={resolvedMargin.left}>
                    <BarStack<TimeSeriesEntry, string>
                        data={data}
                        keys={keys}
                        x={(d) => d.date}
                        xScale={dateScale}
                        yScale={costScale}
                        color={(key) => colorFor(key)}
                        value={(d, key) => {
                            const dataSource =
                                viewMode === 'type' ? d.by_type : d.by_subtype;
                            return dataSource[key] || 0;
                        }}
                    >
                        {(barStacks) =>
                            barStacks.map((barStack) =>
                                barStack.bars.map((bar) => {
                                    const dim =
                                        activeKey !== null &&
                                        activeKey !== barStack.key;
                                    return (
                                        <rect
                                            key={`bar-stack-${barStack.index}-${bar.index}`}
                                            x={bar.x}
                                            y={bar.y}
                                            height={bar.height}
                                            width={bar.width}
                                            fill={bar.color}
                                            opacity={dim ? 0.35 : 1}
                                            style={{
                                                cursor: 'pointer',
                                                filter: dim
                                                    ? 'grayscale(1)'
                                                    : 'none',
                                                transition:
                                                    'opacity 0.15s ease, filter 0.15s ease',
                                            }}
                                            onMouseLeave={() => hideTooltip()}
                                            onMouseMove={(event) => {
                                                const coords =
                                                    localPoint(event);
                                                if (!coords) return;
                                                showTooltip({
                                                    tooltipData: {
                                                        key: barStack.key,
                                                        entry: data[bar.index],
                                                    },
                                                    tooltipTop: coords.y,
                                                    tooltipLeft: coords.x,
                                                });
                                            }}
                                        />
                                    );
                                })
                            )
                        }
                    </BarStack>
                </Group>
                <AxisBottom
                    top={yMax + resolvedMargin.top}
                    left={resolvedMargin.left}
                    scale={dateScale}
                    tickFormat={formatDate}
                    stroke={CHART_THEME.text}
                    tickStroke={CHART_THEME.textMuted}
                    numTicks={
                        isMobileChart ? Math.min(data.length, 6) : undefined
                    }
                    tickLabelProps={() => ({
                        fill: CHART_THEME.textMuted,
                        fontSize: isMobileChart ? 9 : 11,
                        textAnchor: 'middle',
                    })}
                />
                <AxisLeft
                    top={resolvedMargin.top}
                    left={resolvedMargin.left}
                    scale={costScale}
                    stroke={CHART_THEME.text}
                    tickStroke={CHART_THEME.textMuted}
                    tickFormat={(value) => formatAxisCost(Number(value))}
                    numTicks={isMobileChart ? 5 : 6}
                    tickLabelProps={() => ({
                        fill: CHART_THEME.textMuted,
                        fontSize: isMobileChart ? 9 : 11,
                        textAnchor: 'end',
                        dx: '-0.25em',
                        dy: '0.25em',
                    })}
                />
            </svg>

            {/* Sorted legend below the chart — biggest spenders first, with totals. Hovering
          a row dims unrelated bars; clicking pins the highlight (touch support). */}
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-1">
                {keys.map((key) => {
                    const dim = activeKey !== null && activeKey !== key;
                    return (
                        <button
                            key={key}
                            type="button"
                            aria-pressed={pinnedKey === key}
                            onClick={() =>
                                setPinnedKey((prev) =>
                                    prev === key ? null : key
                                )
                            }
                            onMouseEnter={() => setHoveredKey(key)}
                            onMouseLeave={() => setHoveredKey(null)}
                            className={cn(
                                'flex items-center gap-2 min-w-0 text-xs rounded px-1.5 py-1 transition-opacity hover:bg-accent dark:hover:bg-zinc-800/60',
                                pinnedKey === key && 'bg-accent dark:bg-zinc-800/60',
                                dim && 'opacity-40'
                            )}
                            title={getDisplayName(key)}
                        >
                            <span
                                className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                                style={{ backgroundColor: colorFor(key) }}
                            />
                            <span className="text-muted-foreground dark:text-zinc-300 truncate flex-1 min-w-0 text-left">
                                {getDisplayName(key)}
                            </span>
                            <span className="text-muted-foreground/70 dark:text-zinc-500 font-mono flex-shrink-0">
                                {formatCredits(totalsByKey[key])}
                            </span>
                        </button>
                    );
                })}
            </div>

            {tooltipOpen && tooltipData && (
                <TooltipInPortal
                    top={tooltipTop}
                    left={tooltipLeft}
                    style={USAGE_TOOLTIP_STYLES}
                >
                    <div>
                        <strong>{formatDate(tooltipData.entry.date)}</strong>
                    </div>
                    <div
                        style={{
                            marginTop: '4px',
                            color: colorFor(tooltipData.key),
                        }}
                    >
                        <strong>{getDisplayName(tooltipData.key)}</strong>
                    </div>
                    <div style={{ color: CHART_THEME.textMuted }}>
                        {formatCredits(
                            (viewMode === 'type'
                                ? tooltipData.entry.by_type
                                : tooltipData.entry.by_subtype)[
                                tooltipData.key
                            ] || 0
                        )}
                    </div>
                    <div
                        style={{
                            marginTop: '4px',
                            paddingTop: '4px',
                            borderTop: `1px solid ${CHART_THEME.border}`,
                        }}
                    >
                        Total: {formatCredits(tooltipData.entry.total_cost)}
                    </div>
                </TooltipInPortal>
            )}
        </div>
    );
});
