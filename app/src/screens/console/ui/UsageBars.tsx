// Daily stacked spend bars: the top series plus "Other", in the ink ramp (the
// largest darkest), 2px surface gaps between segments, a hover tooltip with
// values sorted descending. The breakdown table under it is the legend, and
// reuses `usageStack` for its swatches.
import { useMemo } from 'react';
import { BarStack } from '@visx/shape';
import { Group } from '@visx/group';
import { AxisBottom } from '@visx/axis';
import { scaleBand, scaleLinear } from '@visx/scale';
import { ParentSize } from '@visx/responsive';
import { useTooltip, useTooltipInPortal } from '@visx/tooltip';
import { cn } from '@/ui/utils';
import { inkRamp } from '@/screens/console/lib/inkRamp';
import { formatMoney } from '@/screens/console/lib/format';
import type { UsageSeriesLine } from 'noclick';

export interface StackKey {
    id: string;
    label: string;
    color: string;
    totalUsd: number;
}

export interface StackDay {
    day: string;
    values: Record<string, number>;
}

export const OTHER_ID = '__other__';
const DAY_MS = 86_400_000;

const dayKey = (t: Date) => t.toISOString().slice(0, 10);

/** Top `top` series by spend plus "Other", coloured darkest-first; one row per UTC day in [from, to). `top = 0` is one "Spend" series. */
export function usageStack(series: readonly UsageSeriesLine[], from: Date, to: Date, top = 5): { keys: StackKey[]; days: StackDay[] } {
    const sorted = [...series].sort((a, b) => b.totalUsd - a.totalUsd);
    const head = sorted.slice(0, top);
    const tail = sorted.slice(top);
    const members = [...head.map((s, i) => ({ id: s.id ?? `series-${i}`, label: s.label ?? s.id ?? 'Unknown', lines: [s] }))];
    if (tail.length) members.push({ id: OTHER_ID, label: head.length ? 'Other' : 'Spend', lines: tail });
    // One series takes the app's bar ink; a stack takes the ramp.
    const colors = head.length ? inkRamp(members.length) : ['hsl(var(--foreground) / 0.3)'];
    const keys = members.map((m, i) => ({ id: m.id, label: m.label, color: colors[i], totalUsd: m.lines.reduce((sum, l) => sum + l.totalUsd, 0) }));
    const days: StackDay[] = [];
    const start = Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), from.getUTCDate());
    for (let t = start; t < to.getTime(); t += DAY_MS) days.push({ day: dayKey(new Date(t)), values: Object.fromEntries(keys.map((k) => [k.id, 0])) });
    const index = new Map(days.map((d, i) => [d.day, i]));
    members.forEach((m) => {
        for (const line of m.lines) {
            for (const p of line.points) {
                if (!p.t) continue;
                const i = index.get(dayKey(p.t));
                if (i !== undefined) days[i].values[m.id] += p.usd;
            }
        }
    });
    return { keys, days };
}

// Room at the sides for the first and last day's label, centred under its bar.
const MARGIN = { top: 8, right: 16, bottom: 28, left: 16 };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** `2026-09-01` → `Sep 1`. */
export function dayLabel(day: string): string {
    const [, month, date] = day.split('-').map(Number);
    return month && date ? `${MONTHS[month - 1]} ${date}` : day;
}
const GAP = 2;

function Chart({ width, height, keys, days }: { width: number; height: number; keys: StackKey[]; days: StackDay[] }) {
    const { tooltipOpen, tooltipData, tooltipLeft, tooltipTop, showTooltip, hideTooltip } = useTooltip<StackDay>();
    const { containerRef, TooltipInPortal } = useTooltipInPortal({ scroll: true, detectBounds: true });
    const innerW = Math.max(0, width - MARGIN.left - MARGIN.right);
    const innerH = Math.max(0, height - MARGIN.top - MARGIN.bottom);
    const x = scaleBand<string>({ domain: days.map((d) => d.day), range: [0, innerW], padding: 0.25 });
    const max = Math.max(0, ...days.map((d) => Object.values(d.values).reduce((a, b) => a + b, 0)));
    const y = scaleLinear<number>({ domain: [0, max || 1], range: [innerH, 0], nice: true });
    const color = (id: string) => keys.find((k) => k.id === id)?.color ?? 'transparent';
    const barW = Math.min(24, x.bandwidth());
    const tickEvery = Math.ceil(days.length / Math.max(1, Math.floor(innerW / 56)));
    return (
        <div ref={containerRef} className="relative">
            <svg width={width} height={height} role="img" aria-label="Daily spend">
                <Group left={MARGIN.left} top={MARGIN.top}>
                    <line x1={0} x2={innerW} y1={innerH} y2={innerH} stroke="hsl(var(--foreground) / 0.12)" />
                    <BarStack<StackDay, string>
                        data={days}
                        keys={keys.map((k) => k.id)}
                        x={(d) => d.day}
                        value={(d, key) => d.values[key] ?? 0}
                        xScale={x}
                        yScale={y}
                        color={color}
                    >
                        {(stacks) =>
                            stacks.map((stack) =>
                                stack.bars.map((bar) => {
                                    const h = bar.height - (bar.height > GAP * 2 ? GAP : 0);
                                    if (h <= 0) return null;
                                    return (
                                        <rect
                                            key={`${stack.key}-${bar.index}`}
                                            x={bar.x + (bar.width - barW) / 2}
                                            y={bar.y}
                                            width={barW}
                                            height={h}
                                            rx={2}
                                            fill={bar.color}
                                        />
                                    );
                                })
                            )
                        }
                    </BarStack>
                    {days.map((d) => (
                        <rect
                            key={`hit-${d.day}`}
                            x={x(d.day) ?? 0}
                            y={0}
                            width={x.step()}
                            height={innerH}
                            fill="transparent"
                            onMouseMove={() => showTooltip({ tooltipData: d, tooltipLeft: (x(d.day) ?? 0) + MARGIN.left + x.bandwidth() / 2, tooltipTop: MARGIN.top })}
                            onMouseLeave={hideTooltip}
                        />
                    ))}
                    <AxisBottom
                        top={innerH}
                        scale={x}
                        hideAxisLine
                        hideTicks
                        tickValues={days.filter((_, i) => i % tickEvery === 0).map((d) => d.day)}
                        tickFormat={(v) => dayLabel(String(v))}
                        tickLabelProps={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12, textAnchor: 'middle' }}
                    />
                </Group>
            </svg>
            {tooltipOpen && tooltipData && (
                <TooltipInPortal left={tooltipLeft} top={tooltipTop} unstyled applyPositionStyle className="pointer-events-none z-[90] rounded-md border border-border bg-popover px-2.5 py-2 text-[12px] text-popover-foreground shadow-md">
                    <div className="mb-1 font-medium">{dayLabel(tooltipData.day)}</div>
                    {keys
                        .map((k) => ({ k, v: tooltipData.values[k.id] ?? 0 }))
                        .filter((r) => r.v > 0)
                        .sort((a, b) => b.v - a.v)
                        .map(({ k, v }) => (
                            <div key={k.id} className="flex items-center gap-2">
                                <span className="h-2 w-2 rounded-sm" style={{ background: k.color }} />
                                <span className="flex-1 truncate">{k.label}</span>
                                <span className="tabular-nums">{formatMoney(v)}</span>
                            </div>
                        ))}
                </TooltipInPortal>
            )}
        </div>
    );
}

export function UsageBars({ keys, days, height = 180, className }: { keys: StackKey[]; days: StackDay[]; height?: number; className?: string }) {
    const empty = useMemo(() => days.every((d) => Object.values(d.values).every((v) => v === 0)), [days]);
    if (empty) {
        return (
            <div className={cn('relative flex items-center justify-center', className)} style={{ height }}>
                <div className="absolute inset-x-1 bottom-[22px] border-t border-dashed border-foreground/20" />
                <span className="text-[13px] text-muted-foreground">No activity</span>
            </div>
        );
    }
    return (
        <div className={className} style={{ height }}>
            <ParentSize>{({ width }) => (width > 0 ? <Chart width={width} height={height} keys={keys} days={days} /> : null)}</ParentSize>
            {/* The bars as text, for a screen reader: the hover tooltip is mouse-only. */}
            <ul className="sr-only" aria-label="Spend by day">
                {days
                    .map((d) => ({ day: d.day, total: Object.values(d.values).reduce((a, b) => a + b, 0) }))
                    .filter((d) => d.total > 0)
                    .map((d) => (
                        <li key={d.day}>
                            {dayLabel(d.day)}: {formatMoney(d.total)}
                        </li>
                    ))}
            </ul>
        </div>
    );
}
