// Usage: what platform work cost in one calendar month (UTC), grouped by key,
// user, agent or type. Daily stacked bars in the ink ramp over a breakdown
// table that is also their legend; a row opens that entity's by-type spend and
// its cap, edited in place. `?cycle=YYYY-MM`, `?group=`, `?user=`, `?row=`.
import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Link } from 'react-router';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Agent, ALL_USERS, NoClickError, Usage, User, type UsageLimits, type UsageSeriesLine } from 'noclick';
import { formatCount, formatPercent } from '@/screens/console/lib/format';
import { updateKey } from '@/sdk/owner';
import { addFundsUrl } from '@/screens/console/lib/site';
import { useOwnerOnly } from '../ownerOnly';
import { DesignedTag } from '../ui/DesignedTag';
import { userPath, type UserFilterValue } from '@/screens/console/lib/userFilter';
import { useAccount, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam, useUserParam } from '@/screens/console/hooks/useQueryState';
import { ConsoleButton } from '../ui/Button';
import { CapMeter } from '../ui/CapMeter';
import { DataTable, type Column } from '../ui/DataTable';
import { Drawer } from '../ui/Drawer';
import { ErrorPanel } from '../ui/ErrorPanel';
import { Money } from '../ui/Money';
import { PageHeader } from '../ui/PageHeader';
import { Segmented } from '../ui/Segmented';
import { UserFacet } from '../ui/UserFacet';
import { OTHER_ID, usageStack, UsageBars } from '../ui/UsageBars';

export type UsageGroupBy = 'key' | 'user' | 'agent' | 'type';

const GROUPS: readonly { value: UsageGroupBy; label: string }[] = [
    { value: 'key', label: 'Key' },
    { value: 'user', label: 'User' },
    { value: 'agent', label: 'Agent' },
    { value: 'type', label: 'Type' },
];

const CYCLE_RE = /^(\d{4})-(0[1-9]|1[0-2])$/;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export interface Cycle {
    /** `2026-09` */
    id: string;
    from: Date;
    to: Date;
}

/** A UTC calendar month (as `spend.month_bounds`); `offset` steps months. */
export function cycleOf(year: number, month: number, offset = 0): Cycle {
    const from = new Date(Date.UTC(year, month + offset, 1));
    const to = new Date(Date.UTC(from.getUTCFullYear(), from.getUTCMonth() + 1, 1));
    return { id: `${from.getUTCFullYear()}-${String(from.getUTCMonth() + 1).padStart(2, '0')}`, from, to };
}

/** `?cycle=` or the month `now` falls in. */
export function parseCycle(value: string | null, now: number): Cycle {
    const m = value ? CYCLE_RE.exec(value) : null;
    if (m) return cycleOf(Number(m[1]), Number(m[2]) - 1);
    const d = new Date(now);
    return cycleOf(d.getUTCFullYear(), d.getUTCMonth());
}

const FULL_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

/** The month a cycle is: `September 2026` (UTC). */
export function cycleLabel({ from }: Cycle): string {
    return `${FULL_MONTHS[from.getUTCMonth()]} ${from.getUTCFullYear()}`;
}

/**
 * The day spend reaches `cap` at this cycle's pace so far (a straight line from
 * the cycle start), or null when it won't before the cycle ends or already has.
 */
export function capPace(spent: number, cap: number, cycle: Cycle, now: number): Date | null {
    const elapsed = now - cycle.from.getTime();
    if (spent <= 0 || spent >= cap || elapsed <= 0 || now >= cycle.to.getTime()) return null;
    const at = cycle.from.getTime() + (cap / spent) * elapsed;
    return at < cycle.to.getTime() ? new Date(at) : null;
}

const NULL_LABEL: Record<UsageGroupBy, string> = { key: 'Unknown key', user: 'Your account', agent: 'No agent', type: 'Other usage' };

/** Spend types of designed, not built primitives: only the lab's fixtures have them, tagged. */
export const DESIGNED_SPEND_TYPES: ReadonlySet<string> = new Set(['dicts', 'queues', 'cards']);

/** Lines sorted as the chart stacks them, labelled, each with the id its swatch is keyed by. */
export function breakdownRows(series: readonly UsageSeriesLine[], group: UsageGroupBy): (UsageSeriesLine & { key: string; name: string })[] {
    return [...series]
        .sort((a, b) => b.totalUsd - a.totalUsd)
        .map((line, i) => ({ ...line, key: line.id ?? `series-${i}`, name: line.label ?? line.id ?? NULL_LABEL[group], label: line.label ?? NULL_LABEL[group] }));
}

interface CapRow {
    cap: number | null;
    spent: number;
}

function capFor(limits: UsageLimits | undefined, group: UsageGroupBy, id: string | null): CapRow | null {
    if (!limits || !id) return null;
    if (group === 'key') return limits.keys.find((k) => k.id === id) ?? null;
    if (group === 'user') return limits.users.find((u) => u.id === id) ?? null;
    if (group === 'agent') {
        const agent = limits.agents.find((a) => a.id === id);
        return agent ? { cap: agent.budget, spent: agent.subtreeSpent } : null;
    }
    return null;
}

const shortDate = (d: Date) => `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;

function CycleStepper({ cycle, current, onChange }: { cycle: Cycle; current: Cycle; onChange: (id: string) => void }) {
    const [y, m] = cycle.id.split('-').map(Number);
    const atCurrent = cycle.id >= current.id;
    return (
        <div className="inline-flex items-center gap-0.5">
            <ConsoleButton variant="ghost" size="icon" aria-label="Previous month" onClick={() => onChange(cycleOf(y, m - 1, -1).id)}>
                <ChevronLeft className="h-4 w-4" />
            </ConsoleButton>
            <span className="min-w-[10.5rem] text-center text-[13px] font-medium tabular-nums">{cycleLabel(cycle)}</span>
            <ConsoleButton variant="ghost" size="icon" aria-label="Next month" disabled={atCurrent} onClick={() => onChange(cycleOf(y, m - 1, 1).id)}>
                <ChevronRight className="h-4 w-4" />
            </ConsoleButton>
        </div>
    );
}

/** A cap shown, then edited in place: an empty field removes it. */
/** A cap against its spend, and its editor. Without `onSave` it only reads (a cap this console can't change). */
export function CapEditor({ cap, spent, noun, onSave }: { cap: number | null; spent: number | null; noun: string; onSave?: (cap: number | null) => Promise<void> }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const parsed = draft.trim() === '' ? null : Number(draft);
    const invalid = parsed !== null && (!Number.isFinite(parsed) || parsed < 0);
    const save = async () => {
        if (invalid || !onSave) return;
        setSaving(true);
        setError(null);
        try {
            await onSave(parsed);
            setEditing(false);
        } catch (e) {
            setError(e instanceof NoClickError && e.nextStep ? `${e.message} ${e.nextStep}` : e instanceof Error ? e.message : String(e));
        } finally {
            setSaving(false);
        }
    };
    if (!editing) {
        return (
            <div className="flex items-center justify-between gap-3">
                <CapMeter spent={spent} cap={cap} noCapLabel className="min-w-[10rem]" />
                {onSave && (
                    <ConsoleButton
                        size="sm"
                        onClick={() => {
                            setDraft(cap == null ? '' : String(cap));
                            setEditing(true);
                        }}
                    >
                        {cap == null ? `Set ${noun}` : `Edit ${noun}`}
                    </ConsoleButton>
                )}
            </div>
        );
    }
    return (
        <form
            className="flex flex-col gap-1.5"
            onSubmit={(e) => {
                e.preventDefault();
                void save();
            }}
        >
            <label className="flex items-center gap-2 text-[13px]">
                <span className="text-muted-foreground">$</span>
                <input
                    inputMode="decimal"
                    aria-label={`Monthly ${noun} in USD`}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="No cap"
                    className="h-8 w-28 rounded-md border border-input bg-background px-2 text-[13px] tabular-nums text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <span className="text-muted-foreground">a month</span>
                <ConsoleButton type="submit" size="sm" variant="primary" disabled={saving || invalid}>
                    {saving ? 'Saving…' : 'Save'}
                </ConsoleButton>
                <ConsoleButton size="sm" variant="ghost" onClick={() => setEditing(false)}>
                    Cancel
                </ConsoleButton>
            </label>
            {invalid && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">Enter an amount in dollars, or leave it empty for no {noun}.</p>}
            {error && (
                <p role="alert" className="m-0 text-[12px] text-red-600 dark:text-red-400">
                    {error}
                </p>
            )}
        </form>
    );
}

const ENTITY: Record<Exclude<UsageGroupBy, 'type'>, { kind: string; noun: string; path: (id: string) => [string, Record<string, string>?] }> = {
    key: { kind: 'Key', noun: 'cap', path: (id) => ['keys', { key: id }] },
    user: { kind: 'User', noun: 'cap', path: (id) => [userPath(id)] },
    agent: { kind: 'Agent', noun: 'budget', path: (id) => [`agents/${id}`] },
};

interface DrawerRow {
    id: string;
    name: string;
    /** The row's spend in the viewed cycle under the page's user filter. */
    totalUsd: number;
}

function UsageDrawer({
    group,
    row,
    cycle,
    current,
    user,
    limits,
    onClose,
}: {
    group: UsageGroupBy;
    row: DrawerRow | null;
    cycle: Cycle;
    current: boolean;
    user: UserFilterValue;
    limits: UsageLimits | undefined;
    onClose: () => void;
}) {
    const { client, lab } = useConsole();
    const href = useConsoleHref();
    const ownerCan = useOwnerOnly();
    // A key's cap and its page are the owner's.
    const reachable = group !== 'key' || ownerCan('keys');
    const entity = group === 'type' ? null : ENTITY[group];
    // A key's or agent's spend is read under the page's user filter, so the drawer agrees with its row.
    const scope = group === 'user' ? row?.id : user;
    const byType = useV1(row && entity ? `usage/series?drawer&${group}=${row.id}&${cycle.id}&${scope}` : null, () =>
        Usage.series({
            client,
            from: cycle.from,
            to: cycle.to,
            groupBy: 'type',
            userFilter: scope,
            ...(group === 'key' ? { key: row!.id } : group === 'agent' ? { agent: row!.id } : {}),
        })
    );
    const cap = row ? capFor(limits, group, row.id) : null;
    // Uncapped: the row's own figure is this cycle's spend only when it covers every user.
    const spent = cap?.spent ?? (row && current && user === ALL_USERS ? row.totalUsd : null);
    const saveCap = async (value: number | null) => {
        if (!row) return;
        if (group === 'key') await updateKey(client, row.id, { spend_cap_usd_per_month: value });
        else if (group === 'user') await User.fromId(row.id, { client }).update({ spendCapUsdPerMonth: value });
        // Loaded first: the owner read resolves across users, and a user's agent is patched as that user.
        else await (await Agent.get(row.id, { client, user: null })).update({ budgetUsdPerMonth: value });
        invalidateV1('usage/');
        invalidateV1(group === 'key' ? 'keys' : group === 'user' ? 'users' : 'agents');
    };
    const [path, params] = row && entity ? entity.path(row.id) : ['', undefined];
    return (
        <Drawer open={!!row && !!entity} onOpenChange={(open) => !open && onClose()} kind={entity?.kind ?? ''} title={row?.name} id={row && row.id !== row.name ? row.id : undefined}>
            {row && entity && (
                <div className="flex flex-col gap-6">
                    <section>
                        <h3 className="m-0 mb-2 text-[14px] font-semibold tracking-[-0.01em] text-foreground">This month against its {entity.noun}</h3>
                        <CapEditor cap={cap?.cap ?? null} spent={spent} noun={entity.noun} onSave={reachable ? saveCap : undefined} />
                    </section>
                    <section>
                        <h3 className="m-0 mb-2 text-[14px] font-semibold tracking-[-0.01em] text-foreground">By type, {cycleLabel(cycle)}</h3>
                        {byType.error !== undefined ? (
                            <ErrorPanel error={byType.error} onRetry={() => void byType.refresh()} />
                        ) : byType.loading ? (
                            <div aria-busy className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]" />
                        ) : byType.data && byType.data.series.length ? (
                            <dl className={cn('m-0 rounded-lg border', HAIRLINE)}>
                                {byType.data.series.map((line) => (
                                    <div key={line.id ?? 'none'} className={cn('flex h-8 items-center gap-3 px-3 text-[13px]')}>
                                        <dt className="flex min-w-0 flex-1 items-center gap-1.5">
                                            <span className="truncate">{line.label ?? line.id ?? NULL_LABEL.type}</span>
                                            {lab && line.id && DESIGNED_SPEND_TYPES.has(line.id) && <DesignedTag what="this spend type" />}
                                        </dt>
                                        <dd className="m-0 w-16 text-right tabular-nums text-muted-foreground">{formatCount(line.events)}</dd>
                                        <dd className="m-0 w-20 text-right">
                                            <Money usd={line.totalUsd} />
                                        </dd>
                                    </div>
                                ))}
                            </dl>
                        ) : (
                            <p className="m-0 text-[13px] text-muted-foreground">No spend this period.</p>
                        )}
                    </section>
                    {reachable && (
                        <Link to={href(path, params)} className="text-[13px] font-medium text-foreground hover:underline">
                            Go to {entity.kind.toLowerCase()} →
                        </Link>
                    )}
                </div>
            )}
        </Drawer>
    );
}

/** What pays for the month: the account's balance (never shown as 0 when unknown), and where to add funds. */
function BalanceLine() {
    const { site } = useConsole();
    const balance = useAccount().data?.balance;
    if (!balance) return null;
    if (balance.unlimited) return <span>Your balance is unlimited.</span>;
    if (balance.remaining_usd == null) return <span>Your balance couldn&apos;t be read.</span>;
    return (
        <span>
            <Money usd={balance.remaining_usd} className="text-foreground" /> left in your balance
            {balance.resets_at ? <>, renewing {shortDate(new Date(balance.resets_at))}</> : null}.{' '}
            <a href={addFundsUrl(site)} className="font-medium text-foreground hover:underline">
                Add funds
            </a>
        </span>
    );
}

export default function UsagePage() {
    const { client, now, lab } = useConsole();
    const [groupParam, setGroup] = useSearchParam('group');
    const [cycleParam, setCycle] = useSearchParam('cycle');
    const [rowParam, setRow] = useSearchParam('row');
    const [user, setUser] = useUserParam();
    const group: UsageGroupBy = GROUPS.some((g) => g.value === groupParam) ? (groupParam as UsageGroupBy) : 'key';
    const current = parseCycle(null, now());
    const cycle = parseCycle(cycleParam, now());
    const series = useV1(`usage/series?${group}&${cycle.id}&${user}`, () =>
        Usage.series({ client, from: cycle.from, to: cycle.to, interval: 'day', groupBy: group, userFilter: user })
    );
    const limits = useV1('usage/limits', () => Usage.limits({ client }));
    const rows = useMemo(() => breakdownRows(series.data?.series ?? [], group), [series.data, group]);
    const stack = useMemo(() => usageStack(rows, cycle.from, cycle.to), [rows, cycle.from, cycle.to]);
    const colorOf = (key: string) => stack.keys.find((k) => k.id === key)?.color ?? stack.keys.find((k) => k.id === OTHER_ID)?.color ?? 'transparent';
    const total = series.data?.totalUsd ?? 0;
    const capped = group !== 'type';
    const isCurrent = cycle.id === current.id;

    type Row = (typeof rows)[number];
    const columns: Column<Row>[] = [
        {
            id: 'name',
            header: GROUPS.find((g) => g.value === group)!.label,
            cell: (r) => (
                <span className="flex min-w-0 items-center gap-2">
                    <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: colorOf(r.key) }} />
                    <span className={cn('truncate', r.id === null && 'text-muted-foreground')}>{r.name}</span>
                    {lab && group === 'type' && r.id && DESIGNED_SPEND_TYPES.has(r.id) && <DesignedTag what="this spend type" />}
                </span>
            ),
        },
    ];
    // A cap bounds this month across every user: there, a row's spend is its cap meter, the one number for both.
    const capsShown = capped && isCurrent && user === ALL_USERS;
    const spendCell = (r: Row) => {
        const cap = capsShown ? capFor(limits.data, group, r.id) : null;
        if (!capsShown || !r.id) return <Money usd={r.totalUsd} />;
        if (!cap || cap.cap == null) return <CapMeter spent={r.totalUsd} cap={null} noCapLabel className="justify-end" />;
        const pace = capPace(cap.spent, cap.cap, cycle, now());
        return (
            <span className="inline-flex flex-col items-end gap-0.5 py-1">
                <CapMeter spent={cap.spent} cap={cap.cap} className="w-40" />
                {pace && <span className="text-[12px] text-muted-foreground">On pace to hit cap {shortDate(pace)}</span>}
            </span>
        );
    };
    columns.push(
        { id: 'events', header: 'Events', priority: 3, align: 'right', width: '6rem', cell: (r) => <span className="tabular-nums">{formatCount(r.events)}</span> },
        { id: 'share', header: 'Share', priority: 2, align: 'right', width: '5rem', cell: (r) => <span className="tabular-nums text-muted-foreground">{total > 0 ? formatPercent(r.totalUsd / total) : '—'}</span> },
        { id: 'usd', header: capsShown ? 'Spend, against its cap' : 'Spend', align: 'right', width: capsShown ? '13rem' : '7rem', cell: spendCell }
    );

    const selected = capped && rowParam ? rows.find((r) => r.id === rowParam) : undefined;
    const empty = !series.loading && series.error === undefined && rows.length === 0;
    return (
        <>
            <PageHeader section="usage" />
            <div className="mb-4 flex flex-wrap items-center gap-2">
                <CycleStepper cycle={cycle} current={current} onChange={(id) => setCycle(id === current.id ? null : id)} />
                <Segmented label="Group by" options={GROUPS} value={group} onChange={(g) => setGroup(g === 'key' ? null : g)} />
                <UserFacet value={user} onChange={setUser} />
            </div>
            {series.error !== undefined && !series.data ? (
                <ErrorPanel error={series.error} onRetry={() => void series.refresh()} />
            ) : (
                <>
                    <p className="m-0 mb-3 text-sm text-muted-foreground" aria-live="polite">
                        {series.loading ? (
                            <span className="inline-block h-4 w-40 animate-pulse rounded bg-foreground/[0.07] align-middle" />
                        ) : empty ? (
                            'No spend this period.'
                        ) : (
                            <>
                                <Money usd={total} className="text-[16px] font-semibold text-foreground" /> this period.
                            </>
                        )}{' '}
                        {isCurrent && <BalanceLine />}
                    </p>
                    <section aria-label="Spend each day" className="mb-6">
                        <UsageBars keys={stack.keys} days={stack.days} height={200} />
                    </section>
                    {!empty && (
                        <DataTable
                            label="Spend breakdown"
                            columns={columns}
                            rows={rows}
                            getRowId={(r) => r.key}
                            loading={series.loading}
                            onRowClick={capped ? (r) => r.id && setRow(r.id, { push: true }) : undefined}
                            selectedId={selected?.key ?? null}
                        />
                    )}
                </>
            )}
            <p className="m-0 mt-3 text-[12px] text-muted-foreground">{"A bought number's monthly rent isn't attributed yet."}</p>
            <UsageDrawer
                group={group}
                row={selected && selected.id ? { id: selected.id, name: selected.name, totalUsd: selected.totalUsd } : null}
                cycle={cycle}
                current={isCurrent}
                user={user}
                limits={limits.data}
                onClose={() => setRow(null)}
            />
        </>
    );
}
