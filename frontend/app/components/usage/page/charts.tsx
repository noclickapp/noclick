// The usage page's figures: the period day by day, a share bar, and a meter. One ink by default (foreground alpha, as the dashboard and console charts are); `services` gives the five
// biggest kinds of spend fixed hues that follow the service, never its rank, validated for colour-blind separation
// in both themes (dataviz validate_palette: blue, orange, aqua, violet, magenta in that order). Marks follow the
// dashboard's rules: bars ≤24px with 4px rounded tops and 2px gaps, hairline solid grid, values in text ink.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { animate } from 'framer-motion';
import { cn } from '~/lib/utils';
import { useUsageMotion } from './motion';
import { SERVICES, dayLabel, money, roundMoney, type DayRow, type ServiceId, type UsageView } from './derive';

export type Ink = 'mono' | 'services';
export type ProjectionStyle = 'band' | 'point' | 'ghost';

/** The services that wear a hue, in palette order (stacking order too, so validated neighbours stay neighbours). */
export const HUED: ServiceId[] = ['ai', 'sandboxes', 'calls', 'apps', 'tools'];
const SLOT: Partial<Record<ServiceId, number>> = { ai: 1, sandboxes: 2, calls: 3, apps: 4, tools: 5 };

export function serviceColor(s: ServiceId | 'rest', ink: Ink): string {
    if (ink === 'mono') return 'var(--ink)';
    const slot = s === 'rest' ? undefined : SLOT[s];
    return slot ? `var(--svc-${slot})` : 'var(--svc-rest)';
}

/** A day's spend split into the hued services and everything else, in stacking order. */
export function stackOf(byService: Partial<Record<ServiceId, number>>, ink: Ink): { key: ServiceId | 'rest'; usd: number }[] {
    const total = Object.values(byService).reduce((a, b) => a + (b ?? 0), 0);
    if (ink === 'mono') return total > 0 ? [{ key: 'rest', usd: total }] : [];
    const out: { key: ServiceId | 'rest'; usd: number }[] = [];
    let rest = total;
    for (const s of HUED) {
        const v = byService[s] ?? 0;
        if (v > 0) out.push({ key: s, usd: v });
        rest -= v;
    }
    if (rest > 1e-9) out.push({ key: 'rest', usd: rest });
    return out;
}

export function useWidth<T extends HTMLElement>() {
    const ref = useRef<T>(null);
    const [width, setWidth] = useState(0);
    useEffect(() => {
        const el = ref.current;
        if (!el) return;
        const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
        ro.observe(el);
        return () => ro.disconnect();
    }, []);
    return [ref, width] as const;
}

/** Three or four round ticks from 0 that clear `max`. */
export function niceTicks(max: number, count = 3): number[] {
    if (max <= 0) return [0, 1];
    const raw = max / count;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
    const ticks: number[] = [];
    for (let v = 0; v < max + step * 0.999; v += step) ticks.push(Math.round(v * 100) / 100);
    return ticks;
}

/** A column with a 4px rounded top and a square foot on the baseline. */
function columnPath(x: number, y: number, w: number, h: number, round = true): string {
    if (h <= 0) return '';
    const r = round ? Math.min(4, w / 2, h) : 0;
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function Tooltip({ x, width, children }: { x: number; width: number; children: ReactNode }) {
    const w = 208;
    const left = Math.max(0, Math.min(width - w, x - w / 2));
    return (
        <div className="pointer-events-none absolute bottom-full z-10 mb-2 rounded-xl border border-border bg-popover px-3 py-2.5 text-[12px] leading-snug text-popover-foreground shadow-[0_12px_32px_-12px_rgba(0,0,0,0.35)] dark:border-foreground/[0.08]" style={{ left, width: w }}>
            {children}
        </div>
    );
}

function DayTip({ day, ink }: { day: DayRow; ink: Ink }) {
    const items = Object.entries(day.byService)
        .filter(([, v]) => (v ?? 0) > 0)
        .sort(([, a], [, b]) => (b ?? 0) - (a ?? 0))
        .slice(0, 4) as [ServiceId, number][];
    return (
        <>
            <div className="flex items-baseline justify-between gap-3">
                <span className="text-muted-foreground">{dayLabel(day.key, { weekday: true })}</span>
                <span className="font-medium tabular-nums">{day.when === 'future' ? `~${money(day.projected)}` : money(day.total)}</span>
            </div>
            {day.when !== 'future' &&
                items.map(([s, v]) => (
                    <div key={s} className="mt-1 flex items-center gap-2">
                        <span className="h-2 w-2 shrink-0 rounded-[2px]" style={{ background: serviceColor(HUED.includes(s) ? s : 'rest', ink) }} />
                        <span className="min-w-0 flex-1 truncate text-foreground/80">{SERVICES[s].label}</span>
                        <span className="tabular-nums text-muted-foreground">{money(v)}</span>
                    </div>
                ))}
            {day.when === 'today' && day.projected > 0 && <div className="mt-1 text-muted-foreground">~{money(day.projected)} more by midnight at this pace</div>}
            {day.when === 'future' && <div className="mt-1 text-muted-foreground">At this pace</div>}
            {day.scheduled.map((s) => (
                <div key={s.label} className="mt-1 flex justify-between gap-3 text-foreground/80">
                    <span className="truncate">{s.label}</span>
                    <span className="tabular-nums">{money(s.usd)}</span>
                </div>
            ))}
            {day.topup > 0 && <div className="mt-1 text-muted-foreground">Auto top-up adds {money(day.topup)}</div>}
        </>
    );
}

const AXIS_W = 40;

/** The period as one column a day: what was spent (stacked by service in `services` ink), today with what's still to
 *  come, and the days ahead as the projection draws them. `values` replaces the totals for a scoped view. */
export function DayColumns({
    view,
    ink,
    projection,
    height = 200,
    selected,
    onSelect,
    emphasis,
    values,
    bare,
    valuesColor,
}: {
    view: UsageView;
    ink: Ink;
    projection: ProjectionStyle;
    height?: number;
    selected?: string | null;
    onSelect?: (key: string | null) => void;
    /** A service drawn in full ink while the rest step back. */
    emphasis?: ServiceId | null;
    values?: number[];
    /** A glance (the meter's popover): no axis, no labels but today. */
    bare?: boolean;
    /** The hue `values` are drawn in (a service's own when the page is inside one). */
    valuesColor?: string | null;
}) {
    const [ref, width] = useWidth<HTMLDivElement>();
    const [hover, setHover] = useState<number | null>(null);
    const { days, projection: p } = view;
    const ax = bare ? 0 : AXIS_W;
    const m = useUsageMotion();
    const motionT = { duration: (m.t as { duration?: number }).duration ?? 0.28 };
    const heights = useRef(new Map<string, number>());
    const running = useRef(new Map<string, { stop: () => void }>());
    useLayoutEffect(() => {
        const root = ref.current;
        if (!root) return;
        const next = new Map<string, number>();
        root.querySelectorAll<SVGGElement>('g[data-bar]').forEach((g) => {
            const key = g.dataset.bar!;
            const h = Number(g.dataset.h) || 0;
            next.set(key, h);
            const before = heights.current.get(key);
            if (before == null || Math.abs(before - h) < 0.5 || h < 1 || m.reduced) return;
            // What the bar shows right now, a running animation's scale included, so a new drill picks up from there.
            const now = getComputedStyle(g).transform;
            const scale = now && now !== 'none' ? new DOMMatrixReadOnly(now).d : 1;
            running.current.get(key)?.stop();
            running.current.set(key, animate(g, { scaleY: [(before * scale) / h, 1] }, m.t));
        });
        heights.current = next;
    });
    const scoped = values != null;
    const totals = days.map((d, i) => (scoped ? (d.when === 'future' ? 0 : values[i] ?? 0) : d.total));
    const futureRate = scoped ? 0 : p.rate;
    const ghosts = days.map((d) => (scoped ? 0 : d.projected + d.scheduled.reduce((a, s) => a + s.usd, 0)));
    const band = projection === 'band' && !scoped ? [Math.max(0, p.rate - 1.2816 * p.sd), p.rate + 1.2816 * p.sd] : null;
    // The scale is set by what's spent and the pace; a renewal taller than that is drawn clipped, its amount above it.
    const max = Math.max(0.01, ...totals.map((t, i) => t + (days[i].when === 'today' ? ghosts[i] : 0)), projection === 'ghost' && !scoped ? futureRate * 1.05 : 0, band ? band[1] : futureRate);
    const ticks = niceTicks(max);
    const top = ticks[ticks.length - 1];
    const plotH = height - 22;
    const plotW = Math.max(0, width - ax);
    const n = days.length;
    const slot = plotW / n;
    const barW = Math.max(3, Math.min(24, slot * 0.7, slot - 2));
    const y = (v: number) => plotH - (v / top) * plotH;
    const firstFuture = days.findIndex((d) => d.when === 'future');
    const futureX = firstFuture === -1 ? null : ax + firstFuture * slot;
    // The pace runs only as far as the money does.
    const stopIdx = view.runway.blocked ? firstFuture : view.runway.runsOut ? days.findIndex((d) => d.key === view.runway.runsOut) + 1 : -1;
    const paceEnd = stopIdx > 0 ? ax + stopIdx * slot : width;
    return (
        <div ref={ref} className="relative w-full select-none" style={{ height }} onMouseLeave={() => setHover(null)}>
            {width > 0 && (
                <svg width={width} height={height} className="block overflow-visible" role="img" aria-label={`Spend each day, ${dayLabel(days[0].key)} to ${dayLabel(days[n - 1].key)}`}>
                    {!bare && ticks.map((t) => (
                        <g key={t}>
                            <line x1={ax} x2={width} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
                            <text x={ax - 8} y={y(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[11px] tabular-nums">
                                {roundMoney(t)}
                            </text>
                        </g>
                    ))}
                    {futureX != null && paceEnd > futureX && band && (
                        <g>
                            <rect x={futureX} width={paceEnd - futureX} y={y(band[1])} height={Math.max(1, y(band[0]) - y(band[1]))} fill="hsl(var(--foreground) / 0.05)" />
                            <line x1={futureX} x2={paceEnd} y1={y(p.rate)} y2={y(p.rate)} stroke="var(--ink-faint)" strokeWidth={2} />
                        </g>
                    )}
                    {futureX != null && paceEnd > futureX && projection === 'point' && !scoped && <line x1={futureX} x2={paceEnd} y1={y(p.rate)} y2={y(p.rate)} stroke="var(--ink-faint)" strokeWidth={2} />}
                    {days.map((d, i) => {
                        const x = ax + i * slot + (slot - barW) / 2;
                        const isHover = hover === i;
                        const isSel = selected === d.key;
                        const dim = (selected && !isSel) || (hover != null && !isHover);
                        if (d.when === 'future') {
                            const sched = d.scheduled.reduce((a, s) => a + s.usd, 0);
                            return (
                                <g key={d.key}>
                                    {projection === 'ghost' && !scoped && d.projected > 0 && <path d={columnPath(x + 0.5, y(d.projected) + 0.5, barW - 1, plotH - y(d.projected) - 0.5)} fill="none" stroke="var(--ink-faint)" strokeWidth={1} />}
                                    {sched > 0 && !scoped && !bare && (
                                        <g>
                                            <path d={columnPath(x, Math.max(14, y(sched)), barW, plotH - Math.max(14, y(sched)))} fill="hsl(var(--foreground) / 0.2)" />
                                            {sched > top && <path d={`M${x - 1},${20} L${x + barW + 1},${16}`} stroke="hsl(var(--background))" strokeWidth={3} />}
                                            <text x={x + barW / 2} y={Math.max(14, y(sched)) - 4} textAnchor="middle" className="fill-muted-foreground text-[10.5px] tabular-nums">
                                                {roundMoney(sched)}
                                            </text>
                                        </g>
                                    )}
                                    {d.topup > 0 && !scoped && !bare && <circle cx={x + barW / 2} cy={plotH + 1} r={3} fill="hsl(var(--background))" stroke="var(--ink)" strokeWidth={1.5} />}
                                </g>
                            );
                        }
                        const focus = emphasis ? d.byService[emphasis] ?? 0 : 0;
                        const segs: { key: ServiceId | 'rest'; usd: number }[] = scoped
                            ? totals[i] > 0
                                ? [{ key: 'rest', usd: totals[i] }]
                                : []
                            : emphasis
                              ? [
                                    { key: emphasis, usd: focus },
                                    { key: 'rest' as const, usd: d.total - focus },
                                ].filter((s) => s.usd > 1e-9)
                              : stackOf(d.byService, ink);
                        let acc = 0;
                        const barH = plotH - y(segs.reduce((a, s) => a + s.usd, 0));
                        return (
                            <g key={d.key} opacity={dim ? 0.45 : 1} style={{ transition: 'opacity 150ms' }}>
                                {/* The bar's own group: it grows or shrinks from the baseline when the drill narrows the days. */}
                                <g data-bar={d.key} data-h={barH} style={{ transformBox: 'fill-box', transformOrigin: '50% 100%' }}>
                                {segs.map((s, si) => {
                                    const y0 = y(acc + s.usd);
                                    const h = y(acc) - y0 - (si > 0 ? 2 : 0);
                                    acc += s.usd;
                                    const last = si === segs.length - 1;
                                    const fill = scoped && valuesColor
                                        ? valuesColor
                                        : emphasis
                                        ? s.key === emphasis
                                            ? ink === 'services' && HUED.includes(emphasis)
                                                ? serviceColor(emphasis, ink)
                                                : 'var(--ink-strong)'
                                            : 'var(--ink-faint)'
                                        : ink === 'mono' && (isHover || isSel)
                                          ? 'var(--ink-strong)'
                                          : serviceColor(s.key, ink);
                                    return <path key={s.key} d={columnPath(x, y0, barW, Math.max(0, h), last)} fill={fill} style={{ transition: `fill ${Math.round(motionT.duration * 1000)}ms ease-out` }} />;
                                })}
                                </g>
                                {d.when === 'today' && ghosts[i] > 0 && <path d={columnPath(x + 0.5, y(totals[i] + ghosts[i]) + 0.5, barW - 1, y(totals[i]) - y(totals[i] + ghosts[i]) - 2)} fill="none" stroke="var(--ink-faint)" strokeWidth={1} />}
                            </g>
                        );
                    })}
                    <line x1={ax} x2={width} y1={plotH + 0.5} y2={plotH + 0.5} stroke="hsl(var(--foreground) / 0.14)" />
                    {days.map((d, i) => {
                        const show = d.when === 'today' || (!bare && i === 0) || (!bare && (i % 7 === 0 && Math.abs(i - days.findIndex((x) => x.when === 'today')) > 2));
                        if (!show) return null;
                        return (
                            <text key={d.key} x={ax + i * slot + slot / 2} y={height - 4} textAnchor="middle" className={cn('text-[11px]', d.when === 'today' ? 'fill-foreground font-medium' : 'fill-muted-foreground')}>
                                {d.when === 'today' ? 'Today' : dayLabel(d.key)}
                            </text>
                        );
                    })}
                    {days.map((d, i) => (
                        <rect
                            key={d.key}
                            data-day={d.key}
                            x={ax + i * slot}
                            y={0}
                            width={slot}
                            height={plotH}
                            fill="transparent"
                            onMouseEnter={() => setHover(i)}
                            onClick={() => onSelect?.(selected === d.key || d.when === 'future' ? null : d.key)}
                            className={onSelect && d.when !== 'future' ? 'cursor-pointer' : undefined}
                        />
                    ))}
                </svg>
            )}
            {hover != null && width > 0 && (
                <Tooltip x={ax + hover * slot + slot / 2} width={width}>
                    {scoped ? (
                        <div className="flex items-baseline justify-between gap-3">
                            <span className="text-muted-foreground">{dayLabel(days[hover].key, { weekday: true })}</span>
                            <span className="font-medium tabular-nums">{days[hover].when === 'future' ? '—' : money(totals[hover])}</span>
                        </div>
                    ) : (
                        <DayTip day={days[hover]} ink={ink} />
                    )}
                </Tooltip>
            )}
        </div>
    );
}

/** What the columns' marks mean, once, under them. */
export function ColumnsKey({ view, projection, ink }: { view: UsageView; projection: ProjectionStyle; ink: Ink }) {
    const hasSched = view.days.some((d) => d.when === 'future' && d.scheduled.length);
    const hasTopup = view.days.some((d) => d.topup > 0);
    const services = ink === 'services' ? HUED.filter((s) => view.days.some((d) => (d.byService[s] ?? 0) > 0)) : [];
    const rest = view.days.some((d) => Object.entries(d.byService).some(([s, v]) => (v ?? 0) > 0 && !HUED.includes(s as ServiceId)));
    return (
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-[12px] text-muted-foreground">
            {services.length ? (
                <>
                    {services.map((s) => (
                        <span key={s} className="inline-flex items-center gap-1.5">
                            <span className="h-2 w-2 rounded-[2px]" style={{ background: serviceColor(s, ink) }} />
                            {SERVICES[s].label}
                        </span>
                    ))}
                    {rest && (
                        <span className="inline-flex items-center gap-1.5">
                            <span className="h-2 w-2 rounded-[2px]" style={{ background: 'var(--svc-rest)' }} />
                            Everything else
                        </span>
                    )}
                </>
            ) : (
                <span className="inline-flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-[2px]" style={{ background: 'var(--ink)' }} />
                    Spent
                </span>
            )}
            {projection === 'ghost' && (
                <span className="inline-flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-[2px] border border-foreground/30" />
                    At this pace
                </span>
            )}
            {projection !== 'ghost' && (
                <span className="inline-flex items-center gap-1.5">
                    <span className="h-[2px] w-3 rounded-full bg-foreground/25" />
                    {projection === 'band' ? 'Pace, and its likely range' : 'Pace'}
                </span>
            )}
            {hasSched && (
                <span className="inline-flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-[2px] bg-foreground/20" />
                    Renewals
                </span>
            )}
            {hasTopup && (
                <span className="inline-flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full border-[1.5px] border-foreground/55" />
                    Auto top-up
                </span>
            )}
        </div>
    );
}

/** One bar split by share: the honest part-to-whole for a handful of parts, gaps between, a legend beside. */
export function ShareBar({ parts, height = 10, className }: { parts: { key: string; usd: number; color: string }[]; height?: number; className?: string }) {
    const total = parts.reduce((a, p) => a + p.usd, 0) || 1;
    return (
        <div className={cn('flex w-full gap-[2px] overflow-hidden', className)} style={{ height }}>
            {parts
                .filter((p) => p.usd > 0)
                .map((p, i, arr) => (
                    <span
                        key={p.key}
                        className={cn('block h-full', i === 0 && 'rounded-l-[4px]', i === arr.length - 1 && 'rounded-r-[4px]')}
                        style={{ width: `${(p.usd / total) * 100}%`, background: p.color, minWidth: 2 }}
                    />
                ))}
        </div>
    );
}

/** A used-of-limit meter: the track one step off the surface, the fill in ink, red only once it's spent. */
export function Meter({ used, limit, danger, className }: { used: number; limit: number; /** Red: reaching the limit stops work. */ danger?: boolean; className?: string }) {
    const frac = limit > 0 ? Math.min(1, used / limit) : 0;
    return (
        <span className={cn('block h-1 w-full overflow-hidden rounded-full bg-foreground/[0.08]', className)}>
            <span className={cn('block h-full rounded-full', danger ? 'bg-red-500 dark:bg-red-400' : 'bg-foreground/55')} style={{ width: `${frac * 100}%` }} />
        </span>
    );
}
