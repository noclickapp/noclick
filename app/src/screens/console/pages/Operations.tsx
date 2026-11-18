// Runs: everything the account's calls started, filtered by one `?q=` query
// (the shortcut, user facet and time pill write its tokens), live while any
// row is running, with the run drawer on `?op=`. Logs shows it as its first
// view and `/logs/{id}` as a page; the agent and user pages reuse it with
// their id pinned.
import { useMemo, useRef } from 'react';
import { Link } from 'react-router';
import { ALL_USERS, Operation } from 'noclick';
import { formatCount, formatDuration, truncateId } from '@/screens/console/lib/format';
import {
    OPERATIONS_QUERY,
    getToken,
    parseQuery,
    queryToOptions,
    setToken as setQueryToken,
    type ParsedQuery,
} from '@/screens/console/lib/query';
import { OPERATIONS_EMPTY } from '@/screens/console/lib/snippets';
import { LIVE_OPERATION_STATUSES } from '@/screens/console/lib/status';
import { userLabel } from '@/screens/console/lib/userFilter';
import { useAccount, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useConsoleQuery, useSearchParam } from '@/screens/console/hooks/useQueryState';
import { usePaged } from '@/sdk/usePaged';
import { useV1 } from '@/sdk/useV1';
import { useLiveOperations } from '@/screens/console/hooks/useLiveOperations';
import { HeaderChip, PageHeader } from '../ui/PageHeader';
import { DataTable, type Column } from '../ui/DataTable';
import { QueryBar, shownBeside } from '../ui/QueryBar';
import { Segmented } from '../ui/Segmented';
import { UserFacet } from '../ui/UserFacet';
import { TimeRangePill, type TimeRange } from '../ui/TimeRangePill';
import { TimeCell } from '../ui/TimeCell';
import { Money } from '../ui/Money';
import { EmptyCode } from '../ui/EmptyCode';
import { ConsoleButton } from '../ui/Button';
import {
    OperationDetail,
    OperationDrawerHost,
    OperationStatusPill,
    SourceCell,
    durationText,
    operationCost,
    useAgentQuery,
    useConsoleNames,
    useOperation,
    type ConsoleNames,
} from './OperationDrawer';

export const OPERATIONS_EMPTY_TITLE = 'Nothing has run yet. Runs appear when you message an agent, request a connection or ask a person.';

const SHORTCUTS = [
    { value: 'live', label: 'Live' },
    { value: 'all', label: 'All' },
    { value: 'failed', label: 'Failed' },
] as const;

function shortcutOf(parsed: ParsedQuery): string | null {
    const status = getToken(parsed, 'status');
    if (getToken(parsed, 'status', true)) return null;
    if (!status) return 'all';
    return status.length === 1 && (status[0] === 'live' || status[0] === 'failed') ? status[0] : null;
}

/** A preview (a detail page's "recent") leaves out Kind, Wait and Cost so Summary keeps its room in a narrow column. */
const PREVIEW_HIDDEN = new Set(['kind', 'wait', 'cost']);

function columns(names: ConsoleNames, showCost: boolean, preview: boolean): Column<Operation>[] {
    const cols: Column<Operation>[] = [
        { id: 'status', header: 'Status', className: 'w-[7.5rem] sm:w-[11rem]', cell: (op) => <OperationStatusPill op={op} /> },
        { id: 'summary', header: 'Summary', cell: (op) => <span className="text-foreground">{op.summaryText || op.kind}</span> },
        { id: 'kind', header: 'Kind', priority: 2, width: '9.5rem', cell: (op) => <span className="font-mono text-[12px] text-muted-foreground">{op.kind}</span> },
        {
            id: 'source',
            header: 'Source',
            priority: 2,
            width: '11rem',
            cell: (op) => <SourceCell names={names} agentId={op.agentId} userId={op.userId} keyId={op.keyId} />,
        },
        { id: 'created', header: 'Created', priority: 2, width: '7rem', cell: (op) => <TimeCell value={op.createdAt} className="text-foreground/70 dark:text-foreground/50" /> },
        { id: 'wait', header: 'Wait', priority: 3, align: 'right', width: '5rem', cell: (op) => <span className="tabular-nums">{op.waitMs ? formatDuration(op.waitMs) : ''}</span> },
        { id: 'duration', header: 'Duration', priority: 2, align: 'right', width: '8rem', cell: (op) => <span className="tabular-nums">{durationText(op)}</span> },
    ];
    if (showCost) cols.push({ id: 'cost', header: 'Cost', priority: 3, align: 'right', width: '5.5rem', cell: (op) => (operationCost(op) === null ? '' : <Money usd={operationCost(op)} />) });
    return preview ? cols.filter((c) => !PREVIEW_HIDDEN.has(c.id)) : cols;
}

function expand(statuses: readonly string[]): Set<string> {
    return new Set(statuses.flatMap((s) => (s === 'live' ? [...LIVE_OPERATION_STATUSES] : [s])));
}

/** Whether a status passes the page's `status:` / `-status:` tokens (`live` stands for the held and running ones). */
export function statusPasses(status: string, include?: readonly string[], exclude?: readonly string[]): boolean {
    return (!include || expand(include).has(status)) && (!exclude || !expand(exclude).has(status));
}

function optionsKey(options: Record<string, unknown>): string {
    return Object.entries(options)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => `${k}=${v instanceof Date ? v.toISOString() : Array.isArray(v) ? v.join(',') : String(v)}`)
        .sort()
        .join('&');
}

export interface OperationsViewProps {
    /** Tokens always applied and never shown as chips (`agent:<id>`, `user:<id>`). */
    pinned?: string;
    /** False: no controls and no `?q=`, just the rows (a detail page's "recent"). Rows open the `?op=` drawer either way. */
    controls?: boolean;
    limit?: number;
    /** The "View all →" target when the view is a preview. */
    viewAllHref?: string;
}

export function OperationsView({ pinned = '', controls = true, limit = 50, viewAllHref }: OperationsViewProps) {
    const { client, now } = useConsole();
    const account = useAccount().data;
    const names = useConsoleNames();
    const [, setOp] = useSearchParam('op');
    const query = useConsoleQuery(OPERATIONS_QUERY);
    const q = controls ? query.q : '';
    const parsed = useMemo(() => parseQuery(`${q} ${pinned}`, OPERATIONS_QUERY), [q, pinned]);
    // `since:1d` is measured from when the query was set, so the request key holds still.
    const anchor = useMemo(() => now(), [q, pinned]); // eslint-disable-line react-hooks/exhaustive-deps
    const agents = useAgentQuery(parsed);
    const mapped = queryToOptions(parsed, OPERATIONS_QUERY, { now: anchor, agents: agents.handles });
    const waiting = !agents.loaded;
    const blocked = waiting || mapped.errors.length > 0 || mapped.ambiguous.length > 0;
    const key = blocked ? null : `operations?${optionsKey(mapped.options)}&limit=${limit}`;

    const paged = usePaged(key, (cursor) => Operation.listPage({ client, ...mapped.options, cursor, limit }), (op) => op.id);
    // The poll asks without the status filter: a shown row that finished no longer
    // matches `status:live`, yet its change must still land. New rows must match it.
    const { status, statusNot, ...unfiltered } = mapped.options as { status?: string[]; statusNot?: string[] } & Record<string, unknown>;
    const shown = useRef<ReadonlySet<string>>(new Set());
    const live = useLiveOperations({
        rows: paged.rows,
        resetKey: key ?? '',
        enabled: controls,
        poll: async (updatedAfter) =>
            (await Operation.listPage({ client, ...unfiltered, updatedAfter, limit: 100 })).data.filter(
                (op) => shown.current.has(op.id) || statusPasses(op.status, status, statusNot)
            ),
    });
    shown.current = new Set(live.rows.map((op) => op.id));
    const summary = useV1(controls && key ? `operations/summary?${optionsKey(mapped.options)}` : null, () => Operation.summary({ client, ...mapped.options }), {
        pollMs: live.polling ? 5000 : undefined,
    });

    const kinds = getToken(parsed, 'kind');
    const showCost = kinds?.length === 1 && kinds[0] === 'agent.message';
    const filtered = query.parsed.tokens.length > 0 || !!pinned;
    const range: TimeRange = { since: getToken(query.parsed, 'since')?.[0] ?? null, until: getToken(query.parsed, 'until')?.[0] ?? null };

    const empty = filtered ? (
        <p className="m-0 py-8 text-center text-[13px] text-muted-foreground">No runs match these filters.</p>
    ) : (
        <EmptyCode title={OPERATIONS_EMPTY_TITLE} snippet={OPERATIONS_EMPTY} />
    );

    return (
        <div className="flex min-w-0 flex-col gap-3">
            {controls && (
                <>
                    <div className="flex flex-wrap items-start gap-2">
                        <QueryBar
                            schema={OPERATIONS_QUERY}
                            value={query.q}
                            onChange={query.setQ}
                            errors={agents.error ? [agents.error] : mapped.errors.slice(parsed.errors.length)}
                            count={summary.data ? `${formatCount(summary.data.total)} ${summary.data.total === 1 ? 'run' : 'runs'}` : undefined}
                            placeholder="Filter, e.g. kind:agent.message"
                            beside={(word) => shownBeside(word, { user: !pinned.includes('user:'), statuses: ['live', 'failed'] })}
                            suggestions={{
                                kind: account?.meta.operation_kinds ?? [],
                                user: names.userIds,
                                agent: names.agentHandles.map((a) => a.name),
                                key: names.keyPrefixes,
                            }}
                            className="min-w-[16rem]"
                        />
                    </div>
                    <div className="flex flex-wrap items-center gap-1">
                        <Segmented
                            label="Status"
                            options={SHORTCUTS}
                            value={shortcutOf(query.parsed)}
                            onChange={(v) => query.setToken('status', v === 'all' ? null : [v])}
                        />
                        {!pinned.includes('user:') && (
                            <UserFacet value={getToken(query.parsed, 'user')?.[0] ?? ALL_USERS} onChange={(v) => query.setToken('user', v === ALL_USERS ? null : [v])} />
                        )}
                        <TimeRangePill
                            value={range}
                            live={live.polling && !range.until}
                            onChange={(next) => query.setQ(setQueryToken(setQueryToken(query.q, 'since', next.since ? [next.since] : null), 'until', next.until ? [next.until] : null))}
                        />
                    </div>
                    {mapped.ambiguous.map((a) => (
                        <div key={a.token} className="flex flex-wrap items-center gap-2 text-[13px]">
                            <span className="text-muted-foreground">Several agents are called {a.candidates[0].name}; pick one:</span>
                            {a.candidates.map((c) => (
                                <ConsoleButton key={c.id} size="sm" onClick={() => query.setToken('agent', [c.id])}>
                                    {c.name} · {userLabel(c.userId)}
                                </ConsoleButton>
                            ))}
                        </div>
                    ))}
                </>
            )}
            <DataTable
                label="Runs"
                columns={columns(names, showCost, !controls)}
                rows={live.rows}
                getRowId={(op) => op.id}
                loading={paged.loading || waiting}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                empty={empty}
                onRowClick={(op) => setOp(op.id, { push: true })}
                nextCursor={controls ? paged.nextCursor : null}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                skeletonRows={Math.min(limit, 8)}
            />
            {viewAllHref && live.rows.length > 0 && (
                <Link to={viewAllHref} className="self-start text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                    View all →
                </Link>
            )}
            <OperationDrawerHost />
        </div>
    );
}

/** One run as a page (`/logs/{id}`): the address the clients' consoleUrl prints. */
export function OperationPage({ id }: { id: string }) {
    const href = useConsoleHref();
    const state = useOperation(id);
    return (
        <>
            <PageHeader
                crumbs={[{ label: 'Logs', href: href('logs') }]}
                title={<span className="font-mono text-[17px]">{truncateId(id, 8, 4)}</span>}
                chips={
                    state.data && (
                        <>
                            <OperationStatusPill op={state.data} />
                            <HeaderChip label="kind">{state.data.kind}</HeaderChip>
                            {state.data.summaryText && <span className="truncate text-[13px] text-muted-foreground">{state.data.summaryText}</span>}
                        </>
                    )
                }
            />
            <div className="max-w-3xl">
                <OperationDetail id={id} state={state} />
            </div>
        </>
    );
}

