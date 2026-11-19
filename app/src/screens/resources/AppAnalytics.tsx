// A website's requests on its page under Resources (GET /v1/projects/{id}/analytics), and the week's on its row in
// Websites (every row's from one read, GET /v1/projects/analytics/summary): from NoClick's record of every request its
// production site answered, whichever deployment served it. That record counts requests (pages, files and API calls, people's and bots' alike), so nothing here says
// visitors.
import { useRef, useState } from 'react';
import { toast } from 'sonner';
import { ArrowDownRight, ArrowRight, ArrowUpRight, Copy, ExternalLink } from 'lucide-react';
import { Group } from '@visx/group';
import { scaleBand, scaleLinear } from '@visx/scale';
import { ParentSize } from '@visx/responsive';
import { useTooltip } from '@visx/tooltip';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { DataGrid, type GridColumn, type GridRow } from './DataGrid';
import { PillSelect, Section, Surface } from './ui';
import { Skeleton } from '@/ui/skeleton';
import { cn } from '@/ui/utils';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useAppTraffic } from './useAppTraffic';
import { ERROR_SERIES_CLASS, ink } from '@/screens/console/lib/inkRamp';
import type { AnalyticsPeriod, Project, ProjectAnalytics, TrafficInterval } from 'noclick';
import { PERIODS, changeFrom, formatMs, formatShare, intervalLabel, periodWords, requestsLabel } from './traffic';
import { StatusLine } from './AppActivity';

/** A website's requests this week on its row in Websites (the same week its page opens on); blank until read. */
export function AppRequestsFigure({ project, requests }: { project: Project; requests: number | undefined }) {
    if (!project.production) return null;
    return (
        <span className="hidden w-[136px] shrink-0 truncate text-right text-[12.5px] tabular-nums text-muted-foreground sm:block" data-testid="app-requests-figure">
            {requests === undefined ? '' : `${requests ? requestsLabel(requests) : 'No requests'} · 7d`}
        </span>
    );
}

// The chart: answered requests in the theme's ink, failed ones in the one hue a chart keeps for errors (inkRamp).
const ANSWERED = 0.42;
const ANSWERED_HOVER = 0.62;
const MARGIN = { top: 8, right: 4, bottom: 26, left: 40 };
const GAP = 2;
// The least a bar or its failed part is drawn at, so a single request still shows.
const MIN_MARK = 2;
const BAR_MAX = 24;
const RADIUS = 4;
const HEIGHT = 196;
// Half the tooltip's width, at most: how far from the chart's ends its middle may go.
const TIP_HALF = 72;

/** An axis tick as a clean number: 500, 2,000, 20K, 1.5M. */
function tickLabel(n: number): string {
    if (n >= 1_000_000) return `${Number((n / 1_000_000).toFixed(1))}M`;
    if (n >= 10_000) return `${Number((n / 1000).toFixed(1))}K`;
    return n.toLocaleString('en-US');
}

/** A bar segment whose data end is rounded and whose baseline end is square. */
function topRounded(x: number, y: number, w: number, h: number): string {
    const r = Math.min(RADIUS, w / 2, h);
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

interface Bar {
    point: TrafficInterval;
    at: Date;
    last: boolean;
}

/** The requests chart at a given width (exported for tests: jsdom measures nothing). */
export function TrafficChart({ width, traffic }: { width: number; traffic: ProjectAnalytics }) {
    const { tooltipOpen, tooltipData, tooltipLeft = 0, tooltipTop = 0, showTooltip, hideTooltip } = useTooltip<Bar>();
    const bars: Bar[] = traffic.series.flatMap((point, i) => (point.at ? [{ point, at: point.at, last: i === traffic.series.length - 1 }] : []));
    const innerW = Math.max(0, width - MARGIN.left - MARGIN.right);
    const innerH = HEIGHT - MARGIN.top - MARGIN.bottom;
    const x = scaleBand<number>({ domain: bars.map((b) => b.at.getTime()), range: [0, innerW], padding: 0.3 });
    const y = scaleLinear<number>({ domain: [0, Math.max(1, ...bars.map((b) => b.point.requests))], range: [innerH, 0], nice: true });
    const ticks = y.ticks(3).filter((t) => Number.isInteger(t));
    const barW = Math.min(BAR_MAX, x.bandwidth());
    const labelEvery = Math.ceil(bars.length / Math.max(1, Math.floor(innerW / 64)));
    const hovered = tooltipOpen ? tooltipData?.at.getTime() : undefined;
    return (
        <div className="relative">
            <svg width={width} height={HEIGHT} role="img" aria-label={`Requests each ${traffic.interval}, the last ${periodWords(traffic.period)}`}>
                <Group left={MARGIN.left} top={MARGIN.top}>
                    {ticks.map((t) => (
                        <g key={t}>
                            <line x1={0} x2={innerW} y1={y(t)} y2={y(t)} stroke="hsl(var(--foreground) / 0.08)" />
                            <text x={-10} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="hsl(var(--muted-foreground))" style={{ fontVariantNumeric: 'tabular-nums' }}>
                                {tickLabel(t)}
                            </text>
                        </g>
                    ))}
                    {bars.map((bar) => {
                        const { requests, errors } = bar.point;
                        if (!requests) return null;
                        const left = (x(bar.at.getTime()) ?? 0) + (x.bandwidth() - barW) / 2;
                        // The failed part sits on top, a surface gap below it; the bar's height stays its total.
                        const total = Math.max(innerH - y(requests), MIN_MARK);
                        const failed = errors >= requests ? total : errors ? Math.max((total * errors) / requests, MIN_MARK) : 0;
                        const answered = errors >= requests ? 0 : errors ? Math.max(total - failed - GAP, 0) : total;
                        const lift = bar.at.getTime() === hovered;
                        return (
                            <g key={bar.at.getTime()}>
                                {answered > 0 &&
                                    (failed ? (
                                        <rect x={left} y={innerH - answered} width={barW} height={answered} fill={ink(lift ? ANSWERED_HOVER : ANSWERED)} />
                                    ) : (
                                        <path d={topRounded(left, innerH - answered, barW, answered)} fill={ink(lift ? ANSWERED_HOVER : ANSWERED)} />
                                    ))}
                                {failed > 0 && <path d={topRounded(left, innerH - total, barW, failed)} className={cn(ERROR_SERIES_CLASS, lift ? 'opacity-100' : 'opacity-90')} />}
                            </g>
                        );
                    })}
                    <line x1={0} x2={innerW} y1={innerH} y2={innerH} stroke="hsl(var(--foreground) / 0.14)" />
                    {bars.map((bar, i) =>
                        i % labelEvery === 0 ? (
                            <text key={`label-${bar.at.getTime()}`} x={(x(bar.at.getTime()) ?? 0) + x.bandwidth() / 2} y={innerH + 18} textAnchor="middle" fontSize={11} fill="hsl(var(--muted-foreground))">
                                {intervalLabel(bar.at, traffic.interval, traffic.tz)}
                            </text>
                        ) : null
                    )}
                    {bars.map((bar) => (
                        <rect
                            key={`hit-${bar.at.getTime()}`}
                            data-testid="traffic-bar"
                            x={x(bar.at.getTime()) ?? 0}
                            y={0}
                            width={x.step()}
                            height={innerH}
                            fill="transparent"
                            onMouseMove={() =>
                                showTooltip({
                                    tooltipData: bar,
                                    // Over the bar, kept inside the chart at either end.
                                    tooltipLeft: Math.min(Math.max((x(bar.at.getTime()) ?? 0) + MARGIN.left + x.bandwidth() / 2, TIP_HALF), width - TIP_HALF),
                                    tooltipTop: MARGIN.top + y(bar.point.requests) - 8,
                                })
                            }
                            onMouseLeave={hideTooltip}
                        />
                    ))}
                </Group>
            </svg>
            {tooltipOpen && tooltipData && (
                <div
                    role="tooltip"
                    style={{ left: tooltipLeft, top: tooltipTop }}
                    className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-2 text-[12.5px] text-popover-foreground shadow-md"
                >
                    <div className="mb-1 text-muted-foreground">
                        {intervalLabel(tooltipData.at, traffic.interval, traffic.tz, true)}
                        {tooltipData.last ? ' · so far' : ''}
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="h-0.5 w-3 rounded-full" style={{ background: ink(ANSWERED_HOVER) }} />
                        <span className="font-semibold tabular-nums">{tooltipData.point.requests.toLocaleString('en-US')}</span>
                        <span className="text-muted-foreground">{tooltipData.point.requests === 1 ? 'request' : 'requests'}</span>
                    </div>
                    {tooltipData.point.errors > 0 && (
                        <div className="flex items-center gap-2">
                            <span className="h-0.5 w-3 rounded-full bg-red-600 dark:bg-red-400" />
                            <span className="font-semibold tabular-nums">{tooltipData.point.errors.toLocaleString('en-US')}</span>
                            <span className="text-muted-foreground">failed</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function Legend() {
    return (
        <div className="flex items-center gap-4 text-[12.5px] text-muted-foreground" aria-hidden>
            <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: ink(ANSWERED) }} />
                Answered
            </span>
            <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-[3px] bg-red-600 dark:bg-red-400" />
                Failed
            </span>
        </div>
    );
}

const CHANGE_ICON = { up: ArrowUpRight, down: ArrowDownRight, flat: ArrowRight } as const;

function Figure({ label, value, detail }: { label: string; value: string; detail?: string }) {
    return (
        // A row on a phone (its words then its value), a column beside the others from there up.
        <div className="flex min-w-0 items-baseline justify-between gap-3 sm:block">
            <dt className="text-[12.5px] text-muted-foreground">{label}</dt>
            <dd className="text-[15px] font-semibold tracking-[-0.01em] text-foreground sm:mt-1 sm:text-[18px]">{value}</dd>
            {detail && <dd className="mt-0.5 hidden truncate text-[12.5px] text-muted-foreground sm:block">{detail}</dd>}
        </div>
    );
}

function Overview({ traffic }: { traffic: ProjectAnalytics }) {
    const change = changeFrom(traffic.requests, traffic.previousRequests, traffic.period);
    const ChangeIcon = change ? CHANGE_ICON[change.direction] : null;
    return (
        <Surface className="px-4 pb-4 pt-5 sm:px-5">
            <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
                <div>
                    <p className="m-0 flex items-baseline gap-2 text-foreground">
                        <span className="text-[32px] font-semibold leading-none tracking-[-0.02em]">{traffic.requests.toLocaleString('en-US')}</span>
                        <span className="text-[15px] text-muted-foreground">{traffic.requests === 1 ? 'request' : 'requests'}</span>
                    </p>
                    {change && ChangeIcon && (
                        <p className="m-0 mt-2 flex items-center gap-1 text-[13px] text-muted-foreground">
                            <ChangeIcon className="h-3.5 w-3.5" />
                            {change.words}
                        </p>
                    )}
                </div>
                <Legend />
            </div>
            <div className="-mx-1 mt-5">
                <ParentSize debounceTime={50}>{({ width }) => (width > 0 ? <TrafficChart width={width} traffic={traffic} /> : null)}</ParentSize>
            </div>
            {/* The bars as text, for a screen reader: the hover tooltip is a pointer's. */}
            <ul className="sr-only" aria-label={`Requests each ${traffic.interval}`}>
                {traffic.series.map((point) =>
                    point.at ? (
                        <li key={point.at.getTime()}>
                            {intervalLabel(point.at, traffic.interval, traffic.tz, true)}: {requestsLabel(point.requests)}
                            {point.errors ? `, ${point.errors} failed` : ''}
                        </li>
                    ) : null
                )}
            </ul>
            <dl className="mt-4 grid grid-cols-1 gap-2.5 border-t border-border pt-4 dark:border-foreground/[0.08] sm:grid-cols-3 sm:gap-4" aria-label="Figures">
                <Figure
                    label="Failed"
                    value={traffic.errorRate == null ? '—' : formatShare(traffic.errorRate)}
                    detail={traffic.errors ? `${traffic.errors.toLocaleString('en-US')} of ${traffic.requests.toLocaleString('en-US')}` : 'None'}
                />
                <Figure label="Typical response" value={traffic.p50Ms == null ? '—' : formatMs(traffic.p50Ms)} detail="Half answered faster" />
                <Figure label="95% answered within" value={traffic.p95Ms == null ? '—' : formatMs(traffic.p95Ms)} detail="The slowest 5% took longer" />
            </dl>
            {traffic.requests > 0 && (
                <div className="mt-4" aria-label="By status">
                    <StatusLine byStatus={traffic.byStatus} />
                </div>
            )}
        </Surface>
    );
}

const PATH_COLUMNS: GridColumn[] = [{ name: 'path' }, { name: 'requests', numeric: true }, { name: 'failed', numeric: true }, { name: 'p95', numeric: true }];

/** The period's busiest paths: pages, files and API calls alike. */
function BusiestPaths({ traffic }: { traffic: ProjectAnalytics }) {
    const rows: GridRow[] = traffic.topPaths.map((p) => ({
        path: p.path,
        requests: p.requests.toLocaleString('en-US'),
        failed: p.errors.toLocaleString('en-US'),
        p95: p.p95Ms == null ? '—' : formatMs(p.p95Ms),
    }));
    return (
        <div className="mt-6">
            <h3 className="mb-2 text-[13px] font-medium text-muted-foreground">Busiest paths</h3>
            <DataGrid label="Busiest paths" columns={PATH_COLUMNS} rows={rows} empty="" />
        </div>
    );
}

function Quiet({ project, period }: { project: Project; period: AnalyticsPeriod }) {
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(project.url);
            toast.success('Link copied');
        } catch {
            toast.error('Couldn’t copy the link');
        }
    };
    return (
        <Surface className="px-5 py-6">
            <p className="m-0 text-[14px] font-medium text-foreground">No requests in the last {periodWords(period)}</p>
            <p className="m-0 mt-1 max-w-[56ch] text-[13.5px] leading-relaxed text-muted-foreground">
                Nothing has reached {project.hostname} yet. Share its link, and each request shows up here within a minute.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" className={BUTTON_SECONDARY} onClick={() => void copy()}>
                    <Copy className="h-4 w-4" />
                    Copy link
                </button>
                <a href={project.url} target="_blank" rel="noopener noreferrer" className={BUTTON_SECONDARY}>
                    <ExternalLink className="h-4 w-4" />
                    Open site
                </a>
            </div>
        </Surface>
    );
}

function Loading() {
    return (
        <Surface className="px-4 pb-4 pt-5 sm:px-5">
            <Skeleton className="h-8 w-40" />
            <Skeleton className="mt-3 h-3.5 w-56" />
            <Skeleton className="mt-6 h-[150px] w-full rounded-lg" />
            <div className="mt-4 grid grid-cols-3 gap-4 border-t border-border pt-4 dark:border-foreground/[0.08]">
                {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-10 w-24" />
                ))}
            </div>
        </Surface>
    );
}

/** A website's requests over a period, across its deployments (each one's own last day is in its panel): by hour for a
 * day, by day otherwise, how many failed, how fast it answered, by status and its busiest paths. Shown once it has been
 * deployed. */
export function AppAnalytics({ project }: { project: Project }) {
    const [period, setPeriod] = useState<AnalyticsPeriod>('7d');
    const read = useAppTraffic(project, period);
    // A new period holds the last one's figures, dimmed, until it answers: no flash, no jump.
    const last = useRef<ProjectAnalytics | undefined>(undefined);
    if (read.data) last.current = read.data;
    const traffic = read.data ?? last.current;
    const stale = !read.data && traffic !== undefined;
    const quiet = traffic !== undefined && !traffic.requests && !traffic.previousRequests;
    if (!project.production) return null;
    return (
        <Section title="Requests" action={<PillSelect label="Period" value={period} options={PERIODS} onChange={setPeriod} />}>
            <div data-testid="app-traffic" aria-busy={stale || (!traffic && read.error === undefined)} className={cn('transition-opacity duration-200', stale && 'opacity-55')}>
                {read.error !== undefined && !read.data ? (
                    <p role="alert" className="text-[13.5px] text-muted-foreground">
                        {errorText(read.error)}{' '}
                        <button type="button" onClick={() => void read.refresh()} className="font-medium text-foreground underline underline-offset-4">
                            Try again
                        </button>
                    </p>
                ) : !traffic ? (
                    <Loading />
                ) : quiet ? (
                    <Quiet project={project} period={read.data ? period : traffic.period} />
                ) : (
                    <>
                        <Overview traffic={traffic} />
                        {traffic.topPaths.length > 0 && <BusiestPaths traffic={traffic} />}
                    </>
                )}
                {traffic && !quiet && (
                    <p className="m-0 mt-3 max-w-[72ch] text-[12.5px] leading-relaxed text-muted-foreground">
                        Requests, not visitors: every page, file and API call {project.hostname} answered counts, from people and bots alike.
                        {traffic.sampled ? ' This site is busy enough that its record is a sample, each request in it counted for the ones it stands for.' : ''}
                    </p>
                )}
            </div>
        </Section>
    );
}
