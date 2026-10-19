// The usage page's pieces, each answering one question: how much (Hero), where it went (Breakdown) and what's next
// (ComingUp); the charges are charges.tsx. Shell tokens and pills throughout.
import { useState, type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { cn } from '~/lib/utils';
import { ROWS, clickableRow } from '~/components/dashboard/primitives';
import { HUED, serviceColor, type Ink } from './charts';
import { useUsageMotion } from './motion';
import { dayLabel, daysFrom, money, roundMoney, type Dimension, type ServiceId, type ThingRow, type UpcomingItem, type UsageView } from './derive';

const pct = (x: number) => (x >= 0.995 ? '100%' : x < 0.01 ? '<1%' : `${Math.round(x * 100)}%`);

/** A section heading: sans, sentence case, no eyebrow above it. */
export function SectionTitle({ children, aside, className }: { children: ReactNode; aside?: ReactNode; className?: string }) {
    return (
        <div className={cn('mb-3 flex min-w-0 items-baseline justify-between gap-4', className)}>
            <h3 className="text-[15px] font-semibold tracking-[-0.005em] text-foreground">{children}</h3>
            {aside && <div className="flex shrink-0 items-center gap-2 text-[12.5px] text-muted-foreground">{aside}</div>}
        </div>
    );
}

/** Pill filters, as /templates and the console's Segmented use them. */
export function Pills<T extends string>({ value, options, onChange, size = 'md' }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; size?: 'sm' | 'md' }) {
    return (
        <div className="flex flex-wrap gap-1" role="tablist">
            {options.map((o) => (
                <button
                    key={o.value}
                    type="button"
                    role="tab"
                    aria-selected={value === o.value}
                    onClick={() => onChange(o.value)}
                    className={cn(
                        'rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        size === 'sm' ? 'h-7 px-2.5 text-[12.5px]' : 'h-8 px-3 text-[13px]',
                        value === o.value ? 'bg-accent font-medium text-foreground dark:bg-foreground/10' : 'text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground'
                    )}
                >
                    {o.label}
                </button>
            ))}
        </div>
    );
}

// ── the one number ───────────────────────────────────────────────────────────

/** The headline: what the period will come to at this pace, with its range, or where the money stops it. */
export function Hero({ view, compact }: { view: UsageView; compact?: boolean }) {
    const { projection: p, period, runway: r } = view;
    const first = dayLabel(period.days[0]);
    const last = dayLabel(period.days[period.days.length - 1]);
    let line: ReactNode;
    let sub: ReactNode;
    if (!view.chargeCount) {
        line = `nothing spent yet, ${first} to ${last}`;
        sub = 'Each model call, call minute or day of hosting counts here as it’s charged';
    } else if (p.capped) {
        line = r.blocked ? 'this month: work is paused until there’s money for it' : `this month, then work stops ${dayLabel(r.runsOut!)}`;
        sub = `The pace would need ~${roundMoney(p.demand)}; add funds to keep going`;
    } else {
        line = `projected at the current pace, ${first} to ${last}`;
        sub = p.confidence === 'early' ? `An early guess from ${p.basisDays} ${p.basisDays === 1 ? 'day' : 'days'}: anywhere from ${roundMoney(p.low)} to ${roundMoney(p.high)}` : `Likely ${roundMoney(p.low)} to ${roundMoney(p.high)} · ${money(view.spent)} so far`;
    }
    return (
        <div className="min-w-0">
            <div className={cn(compact ? 'text-[40px]' : 'text-[52px]', 'font-semibold leading-none tracking-[-0.035em] text-foreground')}>
                ~{roundMoney(p.mid)}
                <span className="ml-1 text-[0.42em] font-medium tracking-normal text-foreground/35">/mo</span>
            </div>
            <p className="mt-2.5 text-[14px] text-muted-foreground">{line}</p>
            <p className="mt-0.5 text-[13px] text-muted-foreground">{sub}</p>
        </div>
    );
}

// ── where it went ────────────────────────────────────────────────────────────

export type BreakdownStyle = 'bars' | 'stack';

function swatch(dim: Dimension | 'facet', id: string, ink: Ink): string | null {
    if (dim !== 'service') return null;
    return ink === 'mono' ? null : serviceColor(HUED.includes(id as ServiceId) ? (id as ServiceId) : 'rest', ink);
}

const RAMP = [0.85, 0.6, 0.42, 0.28, 0.18];
const HUE_STEPS = [100, 72, 52, 38, 28];

/** A row's colour, the same in the share bar, its dot and its own bar: a service's hue, steps of one hue inside a
 *  service, or steps of ink by rank. */
export function rowColor(dim: Dimension | 'facet', id: string, rank: number, ink: Ink, hue?: string | null): string {
    if (hue) return rank < 5 ? `color-mix(in srgb, ${hue} ${HUE_STEPS[rank]}%, transparent)` : `color-mix(in srgb, ${hue} 20%, transparent)`;
    const s = swatch(dim, id, ink);
    if (s) return s;
    return rank < 5 ? `hsl(var(--foreground) / ${RAMP[rank]})` : 'var(--svc-rest)';
}

/** The ids a row's parts morph by when it becomes the header of the level it opens. */
export const morphIds = (prefix: string, id: string) => ({ dot: `${prefix}-dot-${id}`, name: `${prefix}-name-${id}`, amount: `${prefix}-amt-${id}`, segment: `${prefix}-seg-${id}` });

export function Breakdown({
    rows,
    style,
    dim,
    ink,
    active,
    onPick,
    compact,
    limit = 8,
    showCount,
    hue,
    layoutPrefix,
    enter,
    keep,
    noShareBar,
}: {
    rows: ThingRow[];
    style: BreakdownStyle;
    /** 'facet': the rows inside one service (its models, lines, tools). */
    dim: Dimension | 'facet';
    ink: Ink;
    active?: string | null;
    onPick?: (row: ThingRow) => void;
    compact?: boolean;
    limit?: number;
    /** Show what drives each row's cost (tokens, minutes, requests). */
    showCount?: boolean;
    /** One hue for every row (a service's own, inside it). */
    hue?: string | null;
    /** Morph ids for this level's rows, so a picked row can become the next level's header (and back). */
    layoutPrefix?: string;
    /** The level just opened: its rows come in after the header settles. */
    enter?: boolean;
    /** The row a closing level's header returns into: it keeps its parts rather than fading in. */
    keep?: string | null;
    /** A drilled level's header already draws the split. */
    noShareBar?: boolean;
}) {
    const [all, setAll] = useState(false);
    const m = useUsageMotion();
    const ids = (id: string) => (layoutPrefix ? morphIds(layoutPrefix, id) : { dot: undefined, name: undefined, amount: undefined, segment: undefined });
    const morph = { layout: 'position' as const, transition: m.t };
    // Going in, what's inside grows down out of the header after it settles; coming back, the neighbours return
    // from where they left (above) while the row the header returns to keeps its parts in place.
    const rowIn = (i: number, id?: string) =>
        enter && id !== keep
            ? {
                  initial: { opacity: 0, y: m.reduced ? 0 : m.dir > 0 ? 6 : -8 },
                  animate: { opacity: 1, y: 0 },
                  transition: { ...m.t, delay: m.dir > 0 ? m.after(0.35) + (m.reduced ? 0 : Math.min(i, 8) * 0.022) : m.after(0.15) },
              }
            : {};
    if (!rows.length) return <p className="py-6 text-[13px] text-muted-foreground">Nothing spent here this period.</p>;
    const shown = all ? rows : rows.slice(0, limit);
    const more = rows.length - shown.length;
    const footer = more > 0 && (
        <button type="button" onClick={() => setAll(true)} className="mt-2 text-[12.5px] text-muted-foreground transition-colors hover:text-foreground">
            {more} more
        </button>
    );
    if (style === 'stack') {
        const top = rows.slice(0, 5);
        const rest = rows.slice(5).reduce((a, r) => a + r.total, 0);
        const parts = [...top.map((r, i) => ({ key: r.id, usd: r.total, color: rowColor(dim, r.id, i, ink, hue) })), { key: 'rest', usd: rest, color: 'var(--svc-rest)' }];
        const sum = parts.reduce((a, x) => a + x.usd, 0) || 1;
        const visible = parts.filter((x) => x.usd > 0);
        return (
            <div>
                <div className={cn('flex h-3 w-full gap-[2px]', noShareBar && 'hidden')}>
                    {visible.map((x, i) => (
                        <motion.span
                            key={x.key}
                            layoutId={noShareBar ? undefined : ids(x.key).segment}
                            {...morph}
                            {...(enter && x.key !== keep ? { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { ...m.t, delay: m.after(0.15) } } : {})}
                            layout
                            className="block h-full"
                            style={{ width: `${(x.usd / sum) * 100}%`, background: x.color, minWidth: 2, borderTopLeftRadius: i === 0 ? 4 : 0, borderBottomLeftRadius: i === 0 ? 4 : 0, borderTopRightRadius: i === visible.length - 1 ? 4 : 0, borderBottomRightRadius: i === visible.length - 1 ? 4 : 0 }}
                        />
                    ))}
                </div>
                <div className={cn(!noShareBar && 'mt-4', ROWS)}>
                    {shown.map((r, i) => {
                        const color = i < 5 ? parts[i].color : 'var(--svc-rest)';
                        const id = ids(r.id);
                        return (
                            <motion.div key={r.id} {...rowIn(i, r.id)} {...clickableRow(onPick ? () => onPick(r) : undefined)} className={cn('-mx-2 flex items-center gap-3 rounded-lg px-2 outline-none focus-visible:ring-2 focus-visible:ring-ring', compact ? 'h-9' : 'h-10', onPick && 'cursor-pointer transition-colors hover:bg-foreground/[0.03]', active === r.id && 'bg-foreground/[0.05]')}>
                                <motion.span layoutId={id.dot} {...morph} className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: color, borderRadius: 3 }} />
                                <motion.span layoutId={id.name} {...morph} className="min-w-0 flex-1 truncate text-[13.5px] text-foreground">
                                    {r.label}
                                </motion.span>
                                <span className="w-12 text-right text-[12.5px] tabular-nums text-muted-foreground">{pct(r.share)}</span>
                                <motion.span layoutId={id.amount} {...morph} className="w-20 text-right text-[13.5px] tabular-nums text-foreground">
                                    {money(r.total)}
                                </motion.span>
                            </motion.div>
                        );
                    })}
                </div>
                {footer}
            </div>
        );
    }
    return (
        <div>
            <div className="space-y-1">
                {shown.map((r, i) => {
                    const c = hue ? rowColor(dim, r.id, i, ink, hue) : swatch(dim, r.id, ink);
                    const faded = !!active && active !== r.id;
                    const id = ids(r.id);
                    return (
                        <motion.div
                            key={r.id}
                            {...rowIn(i, r.id)}
                            {...clickableRow(onPick ? () => onPick(r) : undefined)}
                            aria-pressed={onPick && active !== undefined ? active === r.id : undefined}
                            className={cn('-mx-2 rounded-lg px-2 outline-none focus-visible:ring-2 focus-visible:ring-ring', compact ? 'py-1.5' : 'py-2', onPick && 'cursor-pointer transition-colors hover:bg-foreground/[0.03]', active === r.id && 'bg-foreground/[0.05]')}
                        >
                            <div className="flex items-baseline gap-3">
                                <motion.span layoutId={id.name} {...morph} className="min-w-0 flex-1 truncate text-[13.5px] text-foreground">
                                    {r.label}
                                </motion.span>
                                {showCount && r.count && <span className="hidden shrink-0 text-[12.5px] tabular-nums text-muted-foreground @[360px]:inline">{r.count}</span>}
                                <span className="w-10 text-right text-[12.5px] tabular-nums text-muted-foreground">{pct(r.share)}</span>
                                <motion.span layoutId={id.amount} {...morph} className="w-[72px] text-right text-[13.5px] tabular-nums text-foreground">
                                    {money(r.total)}
                                </motion.span>
                            </div>
                            <span className="mt-1.5 block h-1 w-full rounded-full bg-foreground/[0.05]">
                                <motion.span layoutId={id.segment} {...morph} layout className="block h-full rounded-full transition-opacity" style={{ width: `${Math.max(1, r.share * 100)}%`, background: c ?? (faded ? 'var(--ink-faint)' : 'var(--ink)'), opacity: c && faded ? 0.35 : 1, borderRadius: 999 }} />
                            </span>
                            {showCount && r.count && <span className="mt-1 block text-[12px] tabular-nums text-muted-foreground @[360px]:hidden">{r.count}</span>}
                        </motion.div>
                    );
                })}
            </div>
            {footer}
        </div>
    );
}

// ── what's next ──────────────────────────────────────────────────────────────

export function ComingUp({ view, limit = 6, compact }: { view: UsageView; limit?: number; compact?: boolean }) {
    const items = view.upcoming.slice(0, limit);
    if (!items.length) return <p className="text-[13px] text-muted-foreground">Nothing scheduled.</p>;
    return (
        <div className={ROWS}>
            {items.map((u) => (
                <UpcomingRow key={u.key} item={u} today={view.period.todayKey} compact={compact} />
            ))}
        </div>
    );
}

function UpcomingRow({ item: u, today, compact }: { item: UpcomingItem; today: string; compact?: boolean }) {
    const key = u.at.slice(0, 10);
    const warn = u.kind === 'runout' || u.kind === 'capstop';
    return (
        <div className={cn('flex items-start gap-3', compact ? 'py-2' : 'py-2.5')}>
            <div className="w-[64px] shrink-0">
                <div className={cn('text-[13px] tabular-nums', warn ? 'font-medium text-red-600 dark:text-red-400' : 'text-foreground')}>{u.kind === 'whatsapp' ? 'Hourly' : dayLabel(key)}</div>
                {u.kind !== 'whatsapp' && <div className="text-[11.5px] text-muted-foreground">{daysFrom(today, key)}</div>}
            </div>
            <div className="min-w-0 flex-1">
                <div className={cn('truncate text-[13.5px]', warn ? 'text-red-600 dark:text-red-400' : 'text-foreground')}>{u.label}</div>
                {u.detail && <div className="line-clamp-2 text-[12px] text-muted-foreground">{u.detail}</div>}
            </div>
            {u.usd != null && (
                <div className="shrink-0 text-right">
                    <div className="text-[13.5px] tabular-nums text-foreground">
                        {u.kind === 'topup' ? '+' : ''}
                        {money(u.usd)}
                    </div>
                    <div className="text-[11.5px] text-muted-foreground">{u.paidBy === 'card' ? 'Card' : 'Usage'}</div>
                </div>
            )}
        </div>
    );
}
