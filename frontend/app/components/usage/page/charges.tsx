// Every charge of the period as a table, read a page at a time: grouped by day with the day's total, filtered by
// service and a search, sticky column headings, a hover that reveals the detail, and a row that opens the whole
// charge in the shell's side panel (the model and its tokens, the run it belonged to, who ran it, who paid). A
// site's hourly reading, recorded as several charges at once, reads as one line with its charges in its panel. Wide
// it reads as aligned columns; narrow (a phone, a pane) each row stacks into two lines. Downloads as CSV, every
// charge on its own line.
import { useDeferredValue, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { ChevronRight, Download, Loader2, Search, X } from 'lucide-react';
import { cn } from '~/lib/utils';
import { askNoClick } from '~/lib/askNoClick';
import { saveCsv } from '~/lib/tableCsv';
import { BUTTON_GHOST, BUTTON_SECONDARY } from '~/components/shell/buttons';
import { SidePanel } from '~/components/shell/SidePanel';
import { ROWS } from '~/components/dashboard/primitives';
import { DashboardRunDialog } from '~/components/dashboard/DashboardRunDialog';
import type { RunRow } from '~/components/dashboard/types';
import { HUED, ShareBar, serviceColor, type Ink } from './charts';
import { usageBillingSlots } from './billing';
import { SERVICES, chargeQuery, dayLabel, foldReadings, lineItem, money, planName, timeLabel, type ChargeFilter, type ConsumerKind, type LineItem, type ServiceId, type UsageView } from './derive';
import { useUsageMotion } from './motion';
import { Pills } from './parts';
import type { ChargeRow, ChargeRun, ChargesPage, ChargesSource } from './types';

const PAGE = 50;
const CSV_PAGE = 500;

/** What kind of thing used a charge, beside its name in the panel, where the name doesn't already say. */
const KIND_NOTE: Partial<Record<ConsumerKind, string>> = { step: 'a step in an automation', agent: 'an agent', site: 'a site', chat: 'your chat' };

/** Wide: aligned columns, shared by the headings and every row. "Paid by" only where someone is billed. */
const COLUMNS_BILLED = '@[640px]:grid @[640px]:grid-cols-[72px_minmax(0,1.45fr)_minmax(0,1fr)_112px_76px_84px] @[640px]:items-baseline @[640px]:gap-x-4';
const COLUMNS = '@[640px]:grid @[640px]:grid-cols-[72px_minmax(0,1.45fr)_minmax(0,1fr)_112px_84px] @[640px]:items-baseline @[640px]:gap-x-4';

interface Loaded extends ChargesPage {
    key: string;
    loading: boolean;
    failed: boolean;
}

export function ChargesTable({
    view,
    filter,
    source,
    firstPage,
    onClear,
    ink,
    id,
}: {
    view: UsageView;
    /** What the page narrowed it to (a drill, a picked day); the table owns service and search. */
    filter: ChargeFilter & { label?: string };
    source: ChargesSource;
    /** The unfiltered first page, read with the page. */
    firstPage: ChargesPage | null;
    onClear?: (what: 'day' | 'scope') => void;
    ink: Ink;
    id?: string;
}) {
    const [service, setService] = useState<ServiceId | 'all'>('all');
    const [query, setQuery] = useState('');
    const search = useDeferredValue(query);
    const [loaded, setLoaded] = useState<Loaded | null>(null);
    const [open, setOpen] = useState<LineItem | null>(null);
    const [run, setRun] = useState<ChargeRun | null>(null);
    const [exporting, setExporting] = useState(false);
    const [attempt, setAttempt] = useState(0);
    const motionCtx = useUsageMotion();
    const mounted = useRef(false);
    useEffect(() => {
        mounted.current = true;
    }, []);

    const cq = useMemo(
        () => chargeQuery(view, { match: filter.match, day: filter.day, service: service === 'all' ? null : service, query: search }),
        [view, filter.match, filter.day, service, search]
    );
    const queryKey = JSON.stringify(cq.query);
    const unfiltered = !cq.query.keys && !cq.query.day;
    // A table someone paged into keeps its place when the page re-reads; one still on its first page follows it.
    const paged = !!loaded && loaded.key === queryKey && loaded.rows.length > PAGE;
    const refresh = paged ? null : unfiltered ? firstPage : view.snap;

    useEffect(() => {
        if (cq.query.keys && !cq.query.keys.length) {
            setLoaded({ key: queryKey, rows: [], runs: {}, next: null, loading: false, failed: false });
            return;
        }
        if (unfiltered && firstPage) {
            setLoaded({ key: queryKey, ...firstPage, loading: false, failed: false });
            return;
        }
        let cancelled = false;
        setLoaded((l) => ({ ...(l ?? { rows: [], runs: {}, next: null, failed: false }), key: queryKey, loading: true }));
        source(cq.query, null, PAGE)
            .then((page) => !cancelled && setLoaded({ key: queryKey, ...page, loading: false, failed: false }))
            .catch(() => !cancelled && setLoaded({ key: queryKey, rows: [], runs: {}, next: null, loading: false, failed: true }));
        return () => {
            cancelled = true;
        };
        // `refresh` stands in for the data a re-read brings; the query is `queryKey`.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [queryKey, refresh, source, attempt]);

    const more = async () => {
        if (!loaded?.next) return;
        const at = loaded;
        setLoaded({ ...at, loading: true });
        try {
            const page = await source(cq.query, at.next, PAGE);
            setLoaded({ key: at.key, rows: [...at.rows, ...page.rows], runs: { ...at.runs, ...page.runs }, next: page.next, loading: false, failed: false });
        } catch {
            setLoaded({ ...at, loading: false, failed: true });
        }
    };

    const items = useMemo(() => (loaded ? foldReadings(loaded.rows.map((r) => lineItem(view.snap, r))) : []), [loaded, view.snap]);
    const read = loaded?.rows.length ?? 0;
    const groups = useMemo(() => {
        const out: { day: string; rows: LineItem[] }[] = [];
        for (const i of items) {
            const k = i.at.slice(0, 10);
            if (out[out.length - 1]?.day !== k) out.push({ day: k, rows: [] });
            out[out.length - 1].rows.push(i);
        }
        return out.map((g) => ({ ...g, ...(cq.byDay.get(g.day) ?? { usd: 0, count: g.rows.length }) }));
    }, [items, cq.byDay]);

    const chips: { key: 'day' | 'scope'; label: string }[] = [];
    if (filter.day) chips.push({ key: 'day', label: dayLabel(filter.day, { weekday: true }) });
    if (filter.match && filter.label) chips.push({ key: 'scope', label: filter.label });
    const filtered = service !== 'all' || !!query.trim();
    const billed = view.billed;
    const columns = billed ? COLUMNS_BILLED : COLUMNS;
    const waiting = !loaded || (loaded.loading && !loaded.rows.length);

    const download = async () => {
        setExporting(true);
        try {
            const rows: ChargeRow[] = [];
            let cursor: string | null = null;
            do {
                const page: ChargesPage = await source(cq.query, cursor, CSV_PAGE);
                rows.push(...page.rows);
                cursor = page.next;
            } while (cursor);
            const p = view.period.days;
            saveCsv(
                rows.map((r) => {
                    const i = lineItem(view.snap, r);
                    return {
                        time_utc: i.at,
                        what: i.what,
                        service: SERVICES[i.service].label,
                        for: i.thing,
                        ran_by: i.runner ?? '',
                        quantity: r.quantity,
                        unit: r.unit_type,
                        amount_usd: i.usd.toFixed(6),
                        ...(billed
                            ? { included_usd: i.split.included.toFixed(6), balance_usd: i.split.balance.toFixed(6), topup_usd: i.split.topup.toFixed(6), vendor_cost_usd: r.cost_usd?.toFixed(6) ?? '' }
                            : {}),
                        run: r.metadata.execution_id ?? '',
                        charge: r.id,
                    };
                }),
                `noclick-charges-${p[0]}-to-${p[p.length - 1]}.csv`
            );
        } finally {
            setExporting(false);
        }
    };

    return (
        <section id={id} className="@container scroll-mt-6" aria-label="Charges">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
                <h3 className="text-[15px] font-semibold tracking-[-0.005em] text-foreground">
                    Charges
                    <span className="ml-2 font-normal tabular-nums text-muted-foreground">
                        {cq.count.toLocaleString('en-US')} · {money(cq.total)}
                    </span>
                </h3>
                <button type="button" className={cn(BUTTON_GHOST, '-mr-3 h-8 gap-1.5 text-[13px]')} onClick={() => void download()} disabled={!cq.count || exporting}>
                    {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                    {exporting ? 'Preparing CSV' : 'Download CSV'}
                </button>
            </div>
            <div className="mb-3 flex flex-col gap-2.5 @[640px]:flex-row @[640px]:items-center @[640px]:justify-between">
                <div className="min-w-0 overflow-x-auto [scrollbar-width:none]">
                    {cq.services.length > 0 && (
                        <div className="w-max">
                            <Pills size="sm" value={service} onChange={setService} options={[{ value: 'all', label: 'All' }, ...cq.services.map((s) => ({ value: s, label: SERVICES[s].label }))]} />
                        </div>
                    )}
                </div>
                <label className="relative block shrink-0 @[640px]:w-56">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                    <input
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search charges"
                        aria-label="Search charges"
                        className="h-8 w-full rounded-full border border-border bg-transparent pl-8 pr-3 text-[13px] text-foreground outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/25 dark:border-foreground/[0.1]"
                    />
                </label>
            </div>
            {chips.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-2">
                    {chips.map((c) => (
                        <button key={c.key} type="button" onClick={() => onClear?.(c.key)} className="inline-flex h-7 items-center gap-1 rounded-full bg-secondary pl-3 pr-2 text-[12.5px] text-foreground transition-colors hover:bg-accent dark:bg-foreground/[0.07]">
                            {c.label}
                            <X className="h-3 w-3 text-muted-foreground" />
                        </button>
                    ))}
                </div>
            )}
            <div role="table" aria-label="Charges" aria-rowcount={cq.count} aria-busy={loaded?.loading || undefined}>
                <div role="row" className={cn('sticky top-0 z-[2] hidden border-b border-border bg-background py-2 text-[12px] text-muted-foreground dark:border-foreground/[0.08] @[640px]:grid', columns)}>
                    <span role="columnheader">Time</span>
                    <span role="columnheader">What</span>
                    <span role="columnheader">For</span>
                    <span role="columnheader" className="text-right">
                        Quantity
                    </span>
                    {billed && <span role="columnheader">Paid by</span>}
                    <span role="columnheader" className="text-right">
                        Amount
                    </span>
                </div>
                {waiting ? (
                    <ChargesSkeleton />
                ) : loaded.failed && !items.length ? (
                    <div className="py-10">
                        <p className="text-[14px] text-foreground">Charges didn’t load.</p>
                        <button type="button" className={cn(BUTTON_SECONDARY, 'mt-4 h-8')} onClick={() => setAttempt((a) => a + 1)}>
                            Try again
                        </button>
                    </div>
                ) : !items.length ? (
                    <div className="py-10">
                        <p className="text-[14px] text-foreground">{filtered || chips.length ? 'No charges match.' : 'No charges yet this period.'}</p>
                        <p className="mt-1 text-[13px] text-muted-foreground">{filtered || chips.length ? 'Try another service or clear the search.' : 'Each model call, call minute or day of hosting will show here as it’s charged.'}</p>
                        {(filtered || chips.length > 0) && (
                            <button
                                type="button"
                                className={cn(BUTTON_SECONDARY, 'mt-4 h-8')}
                                onClick={() => {
                                    setService('all');
                                    setQuery('');
                                    if (filter.day) onClear?.('day');
                                    if (filter.match) onClear?.('scope');
                                }}
                            >
                                Clear filters
                            </button>
                        )}
                    </div>
                ) : (
                    // A new filter (a drill, a day) brings its rows in with the list and the days, in the same move.
                    <motion.div key={loaded.key} initial={mounted.current ? { opacity: 0, y: motionCtx.reduced ? 0 : 4 } : false} animate={{ opacity: loaded.loading ? 0.55 : 1, y: 0 }} transition={motionCtx.t}>
                        {groups.map((g) => (
                            <div key={g.day} role="rowgroup">
                                <div role="row" className="sticky top-0 z-[1] flex items-baseline justify-between gap-3 border-b border-border bg-background pb-1.5 pt-4 text-[12.5px] dark:border-foreground/[0.08] @[640px]:top-[33px]">
                                    <span className="font-medium text-foreground">
                                        {dayLabel(g.day, { weekday: true })}
                                        {g.day === view.period.todayKey && <span className="ml-1.5 font-normal text-muted-foreground">Today</span>}
                                    </span>
                                    <span className="tabular-nums text-muted-foreground">
                                        {g.count.toLocaleString('en-US')} {g.count === 1 ? 'charge' : 'charges'} · <span className="text-foreground">{money(g.usd)}</span>
                                    </span>
                                </div>
                                <div className={ROWS}>
                                    {g.rows.map((i) => (
                                        <ChargeLine key={i.id} item={i} ink={ink} columns={columns} billed={billed} onOpen={() => setOpen(i)} />
                                    ))}
                                </div>
                            </div>
                        ))}
                    </motion.div>
                )}
            </div>
            {loaded && items.length > 0 && (loaded.next || read < cq.count) && (
                <div className="mt-4 flex flex-wrap items-center gap-3">
                    {loaded.next && (
                        <button type="button" className={cn(BUTTON_SECONDARY, 'h-8')} onClick={() => void more()} disabled={loaded.loading}>
                            {loaded.loading ? 'Loading' : `Show ${Math.min(PAGE, Math.max(1, cq.count - read))} more`}
                        </button>
                    )}
                    <span className="text-[12.5px] tabular-nums text-muted-foreground">
                        Showing {read.toLocaleString('en-US')} of {cq.count.toLocaleString('en-US')} charges
                    </span>
                </div>
            )}
            <ChargeDrawer view={view} item={open} run={open?.row.metadata.execution_id ? loaded?.runs[open.row.metadata.execution_id] ?? null : null} onClose={() => setOpen(null)} onOpenRun={setRun} />
            {run && <DashboardRunDialog run={run as unknown as RunRow} onClose={() => setRun(null)} />}
        </section>
    );
}

function ChargeLine({ item: i, ink, columns, billed, onOpen }: { item: LineItem; ink: Ink; columns: string; billed: boolean; onOpen: () => void }) {
    const dot = ink === 'services' ? serviceColor(HUED.includes(i.service) ? i.service : 'rest', ink) : null;
    return (
        <div
            role="row"
            tabIndex={0}
            onClick={onOpen}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onOpen();
                }
            }}
            className={cn('group relative -mx-2 cursor-pointer rounded-lg px-2 py-2 text-[13px] outline-none transition-colors hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.05]', columns)}
        >
            {/* Narrow: what and amount, then the rest in one quiet line. */}
            <div className="flex items-baseline justify-between gap-3 @[640px]:hidden">
                <span className="flex min-w-0 items-baseline gap-2 text-foreground">
                    {dot && <span className="h-2 w-2 shrink-0 translate-y-[-1px] self-center rounded-full" style={{ background: dot }} />}
                    <span className="truncate">{i.what}</span>
                </span>
                <span className="shrink-0 tabular-nums text-foreground">{money(i.usd)}</span>
            </div>
            <div className="mt-0.5 truncate text-[12px] text-muted-foreground @[640px]:hidden">
                {timeLabel(i.at)} · {i.thing} · {i.quantity}
                {i.paidFrom ? ` · ${i.paidFrom}` : ''}
            </div>
            {/* Wide: one cell a column. */}
            <span role="cell" className="hidden whitespace-nowrap tabular-nums text-muted-foreground @[640px]:block">
                {timeLabel(i.at)}
            </span>
            <span role="cell" className="hidden min-w-0 items-baseline gap-2 @[640px]:flex">
                {dot && <span className="h-2 w-2 shrink-0 self-center rounded-full" style={{ background: dot }} />}
                <span className="truncate text-foreground">{i.what}</span>
                {i.detail && <span className="hidden shrink-0 text-[12px] text-muted-foreground @[760px]:group-hover:inline @[760px]:group-focus-visible:inline">{i.detail}</span>}
            </span>
            <span role="cell" className="hidden min-w-0 truncate text-muted-foreground @[640px]:block">
                {i.thing}
                {i.runner && <span className="text-muted-foreground/70"> · {i.runner}</span>}
            </span>
            <span role="cell" className="hidden truncate text-right tabular-nums text-muted-foreground @[640px]:block">
                {i.quantity}
            </span>
            {billed && (
                <span role="cell" className="hidden text-[12.5px] text-muted-foreground @[640px]:block">
                    {i.paidFrom ?? 'Your key'}
                </span>
            )}
            <span role="cell" className="hidden items-baseline justify-end gap-1 tabular-nums text-foreground @[640px]:flex">
                {money(i.usd)}
                <ChevronRight className="h-3.5 w-3.5 shrink-0 self-center text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
            </span>
        </div>
    );
}

function ChargesSkeleton() {
    return (
        <div aria-label="Loading charges" className="pt-3">
            <div className="mb-3 h-3 w-40 animate-pulse rounded bg-foreground/[0.07]" />
            {Array.from({ length: 8 }, (_, k) => (
                <div key={k} className="flex items-center gap-4 py-2.5">
                    <span className="h-3 w-12 animate-pulse rounded bg-foreground/[0.06]" />
                    <span className="h-3 animate-pulse rounded bg-foreground/[0.07]" style={{ width: `${28 + ((k * 37) % 30)}%` }} />
                    <span className="ml-auto h-3 w-14 animate-pulse rounded bg-foreground/[0.06]" />
                </div>
            ))}
        </div>
    );
}

// ── one charge, whole ────────────────────────────────────────────────────────

/** A unit rate a person can check: per thousand tokens, per minute, per request, per million rows. */
function rateOf(i: LineItem): string | null {
    const r = i.row;
    if (!r.quantity) return null;
    const per = (n: number, unit: string) => `${money((r.total_cost / r.quantity) * n)} ${unit}`;
    switch (r.unit_type) {
        case 'tokens':
            return per(1000, 'per 1K tokens');
        case 'seconds':
            return per(60, 'a minute');
        case 'requests':
            return per(1, 'a request');
        case 'rows':
            return per(1_000_000, 'per million rows');
        case 'gb_hours':
            return per(1, 'per GB-hour');
        default:
            return null;
    }
}

function ChargeDrawer({ view, item, run, onClose, onOpenRun }: { view: UsageView; item: LineItem | null; run: ChargeRun | null; onClose: () => void; onOpenRun: (run: ChargeRun) => void }) {
    const i = item;
    const m = i?.row.metadata;
    const snap = view.snap;
    const parts = i?.parts;
    const Price = view.billed && !parts ? usageBillingSlots().ChargePrice : undefined;
    const facts: { label: string; value: ReactNode }[] = [];
    if (i && m) {
        facts.push({ label: 'Service', value: SERVICES[i.service].label });
        const note = KIND_NOTE[i.thingKind];
        facts.push({
            label: 'For',
            value: (
                <span>
                    {i.thing}
                    {note && <span className="text-muted-foreground"> · {note}</span>}
                </span>
            ),
        });
        if (m.execution_id)
            facts.push({
                label: 'Run',
                value: (
                    <span className="flex flex-wrap items-baseline gap-x-3">
                        <span className="font-mono text-[12.5px] text-muted-foreground">{m.execution_id.slice(0, 8)}</span>
                        {run && (
                            <button type="button" className="text-foreground underline underline-offset-4" onClick={() => onOpenRun(run)}>
                                Open run
                            </button>
                        )}
                    </span>
                ),
            });
        if (i.runner) facts.push({ label: 'Ran by', value: `${i.runner}, billed to you as the workspace’s owner` });
        if (m.model) facts.push({ label: 'Model', value: <span className="font-mono text-[12.5px]">{m.model}</span> });
        if (m.prompt_tokens != null) facts.push({ label: 'Tokens', value: `${m.prompt_tokens.toLocaleString('en-US')} in · ${(m.completion_tokens ?? 0).toLocaleString('en-US')} out` });
        if (m.number) facts.push({ label: 'Number', value: `${m.number}${m.direction ? ` · ${m.direction === 'inbound' ? 'answered' : 'placed'}` : ''}` });
        if (m.call_sid) facts.push({ label: 'Call', value: `${m.minutes ?? ''} min · ${m.call_sid}` });
        // A metered reading's from/to are the stretch it covers; an email's from is who sent it.
        if (m.from && m.to) facts.push({ label: 'Covers', value: `${timeLabel(m.from)} to ${timeLabel(m.to)} UTC` });
        else if (m.from) facts.push({ label: 'From', value: m.from });
        facts.push({ label: 'Quantity', value: i.quantity });
        const rate = parts ? null : rateOf(i);
        if (rate) facts.push({ label: 'Rate', value: rate });
        if (Price) facts.push({ label: 'Price', value: <Price item={i} view={view} /> });
        if (!parts) facts.push({ label: 'Charge', value: <span className="font-mono text-[12.5px] text-muted-foreground">{i.id}</span> });
    }
    const charges = parts ?? (i ? [i] : []);
    const plan = snap.billing?.plan;
    const paidLine = !i?.paidFrom
        ? i?.row.user_resource
            ? 'On your own key: nobody was charged'
            : 'What it cost'
        : i.paidFrom === 'Split'
          ? 'Split between your plan and your balance'
          : i.paidFrom === 'Balance'
            ? 'From your balance'
            : i.paidFrom === 'Top-up'
              ? 'From the monthly top-up'
              : `Included with ${plan ? planName(plan.tier) : 'your plan'}`;
    return (
        <SidePanel
            open={!!i}
            onOpenChange={(o) => !o && onClose()}
            title={i?.what ?? 'Charge'}
            description={i ? `${dayLabel(i.at.slice(0, 10), { weekday: true })}, ${timeLabel(i.at)} UTC · ${i.thing}` : undefined}
        >
            {i && (
                <div>
                    <div className="text-[30px] font-semibold leading-none tracking-[-0.03em] tabular-nums text-foreground">{money(i.usd)}</div>
                    <p className="mt-2 text-[13.5px] text-muted-foreground">{paidLine}</p>
                    {i.paidFrom === 'Split' && (
                        <div className="mt-3">
                            <ShareBar
                                height={6}
                                parts={[
                                    { key: 'included', usd: i.split.included, color: 'var(--ink-strong)' },
                                    { key: 'topup', usd: i.split.topup, color: 'var(--ink)' },
                                    { key: 'balance', usd: i.split.balance, color: 'var(--ink-faint)' },
                                ]}
                            />
                            <p className="mt-2 text-[12.5px] tabular-nums text-muted-foreground">
                                Included {money(i.split.included)}
                                {i.split.topup > 0 ? ` · Top-up ${money(i.split.topup)}` : ''} · Balance {money(i.split.balance)}
                            </p>
                        </div>
                    )}
                    <dl className={cn('mt-7', ROWS)}>
                        {facts.map((f) => (
                            <div key={f.label} className="grid grid-cols-[96px_minmax(0,1fr)] gap-4 py-2.5 text-[13.5px]">
                                <dt className="text-muted-foreground">{f.label}</dt>
                                <dd className="m-0 min-w-0 break-words text-foreground">{f.value}</dd>
                            </div>
                        ))}
                    </dl>
                    {parts && (
                        <div className="mt-7">
                            <h4 className="mb-1 text-[13px] font-medium text-foreground">{parts.length} charges in this reading</h4>
                            <div className={ROWS}>
                                {parts.map((p) => (
                                    <div key={p.id} className="flex items-baseline gap-3 py-2.5 text-[13.5px]">
                                        <span className="min-w-0 flex-1 truncate text-foreground">{p.what}</span>
                                        <span className="shrink-0 text-[12.5px] tabular-nums text-muted-foreground">{p.quantity}</span>
                                        <span className="w-[72px] shrink-0 text-right tabular-nums text-foreground">{money(p.usd)}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    <button
                        type="button"
                        className={cn(BUTTON_SECONDARY, 'mt-7')}
                        onClick={() => {
                            onClose();
                            askNoClick(
                                `Explain the ${money(i.usd)} ${i.what} charge on ${dayLabel(i.at.slice(0, 10))} (${charges.length > 1 ? 'charges' : 'charge'} ${charges.map((c) => c.id).join(', ')}${m?.execution_id ? `, run ${m.execution_id}` : ''}).`
                            );
                        }}
                    >
                        Ask NoClick about this charge
                    </button>
                </div>
            )}
        </SidePanel>
    );
}
