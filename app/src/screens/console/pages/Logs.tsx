// Logs, one place for everything that ran: runs (every operation, with why
// one failed in its drawer), the tool-call log (with a live tail and its
// matching count), the API request log (writes and failures) and the event log,
// one segmented control apart (`/logs/tool-calls`, `/logs/requests`,
// `/logs/events`). `/logs/{id}` is one run
// as a page. The views are reused by the agent and user pages with an id pinned.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router';
import { Check, Info, Pause, Play } from 'lucide-react';
import { ALL_USERS, ApiRequest, ToolCall } from 'noclick';
import { formatCount, formatDuration } from '@/screens/console/lib/format';
import {
    API_REQUESTS_QUERY,
    TOOL_CALLS_QUERY,
    getToken,
    parseQuery,
    queryToOptions,
    setToken as setQueryToken,
    type QuerySchema,
} from '@/screens/console/lib/query';
import { httpStatus, toolCallStatus } from '@/screens/console/lib/status';
import { TOOL_CALLS_EMPTY } from '@/screens/console/lib/snippets';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useConsoleQuery, useSearchParam, type ConsoleQuery } from '@/screens/console/hooks/useQueryState';
import { usePaged } from '@/sdk/usePaged';
import { useV1 } from '@/sdk/useV1';
import { mergeById } from '@/screens/console/hooks/useLiveOperations';
import { logViews, type ConsolePageProps, type LogView } from '../sections';
import { PageHeader } from '../ui/PageHeader';
import { DataTable, type Column } from '../ui/DataTable';
import { QueryBar, shownBeside } from '../ui/QueryBar';
import { PillTabs } from '../ui/PillTabs';
import { UserFacet } from '../ui/UserFacet';
import { TimeRangePill, type TimeRange } from '../ui/TimeRangePill';
import { TimeCell } from '../ui/TimeCell';
import { StatusPill } from '../ui/StatusPill';
import { IdChip } from '../ui/IdChip';
import { JsonView } from '../ui/JsonView';
import { Drawer } from '../ui/Drawer';
import { EmptyCode } from '../ui/EmptyCode';
import { ConsoleButton } from '../ui/Button';
import { CallConnection, DetailRow, ToolCallBody, useAgentQuery, useConsoleNames, type ConsoleNames } from './OperationDrawer';
import { EventsView } from './EventsLog';
import { HumanRequestDrawer } from './HumanRequestDrawer';
import { OperationPage, OperationsView } from './Operations';

export const TOOL_CALLS_NOTE = "Direct /v1/connections/*/operations/*/run calls aren't tied to a key in this log; the API requests view has the key.";
export const TOOL_CALLS_EMPTY_TITLE = "No tool calls yet. They appear when your code runs a connection's operation or a toolkit, or an agent uses a tool.";
const TAIL_MS = 5000;

function optionsKey(options: Record<string, unknown>): string {
    return Object.entries(options)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => `${k}=${v instanceof Date ? v.toISOString() : Array.isArray(v) ? v.join(',') : String(v)}`)
        .sort()
        .join('&');
}

/** The query a log view reads: the page's `?q=` plus pinned tokens, mapped to SDK options. */
function useLogQuery(schema: QuerySchema, pinned: string) {
    const { now } = useConsole();
    const query = useConsoleQuery(schema);
    const parsed = useMemo(() => parseQuery(`${query.q} ${pinned}`, schema), [query.q, pinned, schema]);
    const anchor = useMemo(() => now(), [query.q, pinned]); // eslint-disable-line react-hooks/exhaustive-deps
    const agents = useAgentQuery(parsed);
    const mapped = queryToOptions(parsed, schema, { now: anchor, agents: agents.handles });
    const waiting = !agents.loaded;
    const blocked = waiting || mapped.errors.length > 0 || mapped.ambiguous.length > 0;
    const range: TimeRange = { since: getToken(query.parsed, 'since')?.[0] ?? null, until: getToken(query.parsed, 'until')?.[0] ?? null };
    const mappingErrors = agents.error ? [agents.error] : mapped.errors.slice(parsed.errors.length);
    return { query, parsed, mapped, waiting, blocked, range, anchor, optionsKey: optionsKey(mapped.options), mappingErrors };
}

function Controls({
    query,
    schema,
    count,
    errors,
    range,
    live,
    userFacet,
    suggestions,
    placeholder,
    children,
}: {
    query: ConsoleQuery;
    schema: QuerySchema;
    count?: string;
    errors: ReturnType<typeof useLogQuery>['mappingErrors'];
    range: TimeRange;
    live: boolean;
    userFacet: boolean;
    suggestions: Record<string, readonly string[]>;
    placeholder: string;
    children?: ReactNode;
}) {
    return (
        <>
            <QueryBar
                schema={schema}
                value={query.q}
                onChange={query.setQ}
                errors={errors}
                count={count}
                suggestions={suggestions}
                placeholder={placeholder}
                beside={(word) => shownBeside(word, { user: userFacet })}
            />
            <div className="flex flex-wrap items-center gap-1">
                {children}
                {userFacet && (
                    <UserFacet value={getToken(query.parsed, 'user')?.[0] ?? ALL_USERS} onChange={(v) => query.setToken('user', v === ALL_USERS ? null : [v])} />
                )}
                <TimeRangePill
                    value={range}
                    live={live}
                    onChange={(next) => query.setQ(setQueryToken(setQueryToken(query.q, 'since', next.since ? [next.since] : null), 'until', next.until ? [next.until] : null))}
                />
            </div>
        </>
    );
}

// ── tool calls ─────────────────────────────────────────────────────────────

function callSource(names: ConsoleNames, call: ToolCall): string {
    const who = call.agentId
        ? (names.agent(call.agentId)?.name ?? call.agentId.slice(0, 8))
        : call.mcpServerId
          ? `MCP server ${call.mcpServerId.slice(0, 8)}`
          : 'API';
    return call.userId ? `${who} for ${call.userId}` : who;
}

export function toolCallColumns(names: ConsoleNames): Column<ToolCall>[] {
    return [
        { id: 'time', header: 'Time', width: '7.5rem', cell: (c) => <TimeCell value={c.createdAt} tier="log" /> },
        { id: 'tool', header: 'Tool', cell: (c) => <span className="font-mono text-[12px]">{c.toolName}</span> },
        { id: 'status', header: 'Status', width: '6.5rem', cell: (c) => <StatusPill look={toolCallStatus(c.status)} /> },
        { id: 'source', header: 'Source', priority: 2, width: '11rem', cell: (c) => <span className="text-muted-foreground">{callSource(names, c)}</span> },
        { id: 'duration', header: 'Duration', priority: 2, align: 'right', width: '6rem', cell: (c) => <span className="tabular-nums">{formatDuration(c.durationMs)}</span> },
        { id: 'connection', header: 'Connection', priority: 3, width: '9rem', cell: (c) => <CallConnection call={c} /> },
    ];
}

export interface ToolCallsViewProps {
    /** Tokens always applied and never shown as chips (`agent:<id>`, `user:<id>`). */
    pinned?: string;
}

export function ToolCallsView({ pinned = '' }: ToolCallsViewProps) {
    const { client } = useConsole();
    const names = useConsoleNames();
    const log = useLogQuery(TOOL_CALLS_QUERY, pinned);
    const key = log.blocked ? null : `tool_calls?${log.optionsKey}`;
    const paged = usePaged(key, (cursor) => ToolCall.listPage({ client, ...log.mapped.options, cursor, limit: 50 }), (c) => c.id);
    const [paused, setPaused] = useState(false);
    const tailing = !!key && !paused && !log.range.until;
    const tail = useTail(key, paged.rows, tailing, log.anchor, async (since) => (await ToolCall.listPage({ client, ...log.mapped.options, since, limit: 100 })).data);
    const summary = useV1(key ? `tool_calls/summary?${log.optionsKey}` : null, () => ToolCall.summary({ client, ...log.mapped.options }), { pollMs: tailing ? TAIL_MS : undefined });
    const [callId, setCallId] = useSearchParam('call');
    const open = callId ? tail.find((c) => c.id === callId) : undefined;
    const filtered = log.query.parsed.tokens.length > 0 || !!pinned;

    const count = summary.data ? (
        <span>
            {formatCount(summary.data.total)} {summary.data.total === 1 ? 'call' : 'calls'}
            {summary.data.error > 0 && <span className="text-red-600 dark:text-red-400">, {formatCount(summary.data.error)} failed</span>}
        </span>
    ) : undefined;

    return (
        <div className="flex min-w-0 flex-col gap-3">
            <Controls
                query={log.query}
                schema={TOOL_CALLS_QUERY}
                errors={log.mappingErrors}
                range={log.range}
                live={tailing}
                userFacet={!pinned.includes('user:')}
                placeholder="Filter, e.g. tool:gmail.*"
                suggestions={{ user: names.userIds, agent: names.agentHandles.map((a) => a.name) }}
            >
                <ConsoleButton variant="ghost" size="sm" onClick={() => setPaused(!paused)} aria-pressed={paused} icon={paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}>
                    {paused ? 'Resume tail' : 'Pause tail'}
                </ConsoleButton>
            </Controls>
            <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
                <span className="tabular-nums text-foreground">{count}</span>
                <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                    <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    {TOOL_CALLS_NOTE}
                </span>
            </div>
            <DataTable
                label="Tool calls"
                columns={toolCallColumns(names)}
                rows={tail}
                getRowId={(c) => c.id}
                loading={paged.loading || log.waiting}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                empty={
                    filtered ? (
                        <p className="m-0 py-8 text-center text-[13px] text-muted-foreground">No tool calls match these filters.</p>
                    ) : (
                        <EmptyCode title={TOOL_CALLS_EMPTY_TITLE} snippet={TOOL_CALLS_EMPTY} />
                    )
                }
                selectedId={callId}
                onRowClick={(c) => setCallId(c.id, { push: true })}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
            />
            {callId && (
                <Drawer
                    open
                    onOpenChange={(o) => !o && setCallId(null)}
                    kind="Tool call"
                    id={callId}
                    title={open ? <span className="font-mono text-[14px]">{open.toolName}</span> : undefined}
                    status={open ? <StatusPill look={toolCallStatus(open.status)} /> : undefined}
                >
                    {open ? (
                        <div className="flex flex-col gap-4">
                            <dl className="m-0">
                                <DetailRow label="Time"><TimeCell value={open.createdAt} tier="log" /></DetailRow>
                                <DetailRow label="Source">{callSource(names, open)}</DetailRow>
                                <DetailRow label="Duration">{formatDuration(open.durationMs)}</DetailRow>
                            </dl>
                            <ToolCallBody call={open} />
                        </div>
                    ) : (
                        <p className="m-0 text-[13px] text-muted-foreground">{paged.loading ? 'Loading…' : "This call isn't in the rows loaded here. Load more, or widen the time range."}</p>
                    )}
                </Drawer>
            )}
        </div>
    );
}

/**
 * Newer rows prepended every 5s while tailing; changing the filters starts over.
 * With no rows yet, the tail asks from `start` (when this query was set).
 */
function useTail<T extends { id: string; createdAt: Date | null }>(key: string | null, rows: T[], enabled: boolean, start: number, poll: (since: Date) => Promise<T[]>): T[] {
    const [fresh, setFresh] = useState<{ key: string | null; rows: T[] }>({ key, rows: [] });
    const merged = mergeById(rows, fresh.key === key ? fresh.rows : []);
    const latest = useRef({ merged, poll, key, start });
    latest.current = { merged, poll, key, start };
    useEffect(() => {
        if (!enabled) return;
        const timer = window.setInterval(async () => {
            if (document.hidden) return;
            const { merged: current, poll: fetchNewer, key: at, start: from } = latest.current;
            const newest = current.reduce<number | null>((max, r) => {
                const t = r.createdAt?.getTime();
                return t != null && (max === null || t > max) ? t : max;
            }, null);
            let got: T[];
            try {
                got = await fetchNewer(new Date(newest ?? from));
            } catch (err) {
                console.warn('Tool call tail failed', err);
                return;
            }
            if (got.length) setFresh((prev) => ({ key: at, rows: mergeById(prev.key === at ? prev.rows : [], got) }));
        }, TAIL_MS);
        return () => window.clearInterval(timer);
    }, [enabled]);
    return merged;
}

// ── API requests ───────────────────────────────────────────────────────────

function actorLabel(names: ConsoleNames, r: ApiRequest): string {
    if (r.actor === 'owner') return 'You (console)';
    if (r.actor === 'session') return 'Session';
    const key = names.key(r.keyId);
    return key ? `Key ${key.name}` : 'Key';
}

function requestColumns(names: ConsoleNames): Column<ApiRequest>[] {
    return [
        { id: 'time', header: 'Time', width: '7.5rem', cell: (r) => <TimeCell value={r.createdAt} tier="log" /> },
        { id: 'actor', header: 'Actor', priority: 2, width: '10rem', cell: (r) => <span className="text-muted-foreground">{actorLabel(names, r)}</span> },
        {
            id: 'route',
            header: 'Request',
            cell: (r) => (
                <span className="font-mono text-[12px]">
                    <span className="text-muted-foreground">{r.method}</span> {r.route}
                </span>
            ),
        },
        { id: 'status', header: 'Status', width: '5.5rem', cell: (r) => (r.status === null ? '—' : <StatusPill look={httpStatus(r.status)} />) },
        { id: 'error', header: 'Error', priority: 2, width: '10rem', cell: (r) => <span className="font-mono text-[12px] text-muted-foreground">{r.errorType ?? ''}</span> },
        { id: 'duration', header: 'Duration', priority: 3, align: 'right', width: '5.5rem', cell: (r) => <span className="tabular-nums">{formatDuration(r.durationMs)}</span> },
        {
            id: 'replay',
            header: 'Replay',
            priority: 3,
            width: '4.5rem',
            cell: (r) => (r.idempotencyReplayed ? <Check aria-label="Replayed" className="h-3.5 w-3.5 text-foreground/70" /> : null),
        },
        { id: 'user', header: 'User', priority: 3, width: '7rem', cell: (r) => <span className="truncate text-muted-foreground">{r.userId ?? ''}</span> },
    ];
}

export function RequestsView({ pinned = '' }: { pinned?: string }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const names = useConsoleNames();
    const log = useLogQuery(API_REQUESTS_QUERY, pinned);
    const key = log.blocked ? null : `requests?${log.optionsKey}`;
    const paged = usePaged(key, (cursor) => ApiRequest.listPage({ client, ...log.mapped.options, cursor, limit: 50 }), (r) => r.id);
    const [requestId, setRequestId] = useSearchParam('request');
    const open = requestId ? paged.rows.find((r) => r.id === requestId) : undefined;
    const openKey = open ? names.key(open.keyId) : null;

    return (
        <div className="flex min-w-0 flex-col gap-3">
            <Controls
                query={log.query}
                schema={API_REQUESTS_QUERY}
                errors={log.mappingErrors}
                range={log.range}
                live={false}
                userFacet={!pinned.includes('user:')}
                placeholder="Filter, e.g. method:POST status:4xx"
                suggestions={{ user: names.userIds, key: names.keyPrefixes }}
            />
            <DataTable
                label="API requests"
                columns={requestColumns(names)}
                rows={paged.rows}
                getRowId={(r) => r.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                empty={
                    <p className="m-0 py-8 text-center text-[13px] text-muted-foreground">
                        {log.query.parsed.tokens.length ? 'No requests match these filters.' : "No requests logged yet. Writes and failed requests appear here; successful reads aren't logged."}
                    </p>
                }
                selectedId={requestId}
                onRowClick={(r) => setRequestId(r.id, { push: true })}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
            />
            {requestId && (
                <Drawer
                    open
                    onOpenChange={(o) => !o && setRequestId(null)}
                    kind="API request"
                    id={requestId}
                    title={open ? <span className="font-mono text-[14px]">{`${open.method} ${open.route}`}</span> : undefined}
                    status={open?.status != null ? <StatusPill look={httpStatus(open.status)} /> : undefined}
                >
                    {open ? (
                        <div className="flex flex-col gap-4">
                            <dl className="m-0">
                                <DetailRow label="Time"><TimeCell value={open.createdAt} tier="log" /></DetailRow>
                                <DetailRow label="Actor">{actorLabel(names, open)}</DetailRow>
                                {openKey && (
                                    <DetailRow label="Key">
                                        {openKey.name} <span className="font-mono text-[12px] text-muted-foreground">{openKey.prefix}…</span>
                                    </DetailRow>
                                )}
                                {open.userId && <DetailRow label="User"><span>{open.userId}</span></DetailRow>}
                                {open.errorType && <DetailRow label="Error"><span className="font-mono text-[12px]">{open.errorType}</span></DetailRow>}
                                <DetailRow label="Duration">{formatDuration(open.durationMs)}</DetailRow>
                                <DetailRow label="Replayed">{open.idempotencyReplayed ? 'Yes (Idempotency-Key)' : 'No'}</DetailRow>
                                {open.operationId && (
                                    <DetailRow label="Operation">
                                        <Link to={href('logs', { op: open.operationId })} className="underline underline-offset-2">
                                            {open.operationId}
                                        </Link>
                                    </DetailRow>
                                )}
                                {open.requestId && <DetailRow label="Request id"><IdChip id={open.requestId} full /></DetailRow>}
                            </dl>
                            {Object.keys(open.pathParams).length > 0 && (
                                <div>
                                    <p className="m-0 mb-1 text-[12px] font-medium text-muted-foreground">Path params</p>
                                    <JsonView value={open.pathParams} />
                                </div>
                            )}
                        </div>
                    ) : (
                        <p className="m-0 text-[13px] text-muted-foreground">{paged.loading ? 'Loading…' : "This request isn't in the rows loaded here. Load more, or widen the time range."}</p>
                    )}
                </Drawer>
            )}
        </div>
    );
}

// ── page ───────────────────────────────────────────────────────────────────

export default function Logs({ rest }: ConsolePageProps) {
    const { lab } = useConsole();
    const href = useConsoleHref();
    const [params] = useSearchParams();
    // A request waiting on a person, opened by its id (the palette, a run's drawer): read here, answered in the product.
    const [reqId, setReq] = useSearchParam('req');
    // The Events view is designed, not built yet: the lab shows it.
    const views = logViews(lab);
    const isView = (value: string | null | undefined): value is LogView => views.some((v) => v.id === value);
    if (rest[0] && !isView(rest[0])) return <OperationPage id={rest[0]} />;
    // `?view=` is the first layout's address for the two log views.
    const legacy = params.get('view');
    const view: LogView = isView(legacy) ? legacy : isView(rest[0]) ? rest[0] : 'runs';
    // Each view has its own query language, so a tab drops the query and any open row.
    return (
        <>
            <PageHeader section="logs" />
            <PillTabs label="Logs" className="-mt-3 mb-6" active={view} tabs={views.map((v) => ({ id: v.id, label: v.label, href: href(v.id === 'runs' ? 'logs' : `logs/${v.id}`) }))} />
            {view === 'events' ? (
                <EventsView key="events" />
            ) : view === 'requests' ? (
                <RequestsView key="requests" />
            ) : view === 'tool-calls' ? (
                <ToolCallsView key="tool-calls" />
            ) : (
                <OperationsView key="runs" />
            )}
            <HumanRequestDrawer requestId={reqId} onClose={() => setReq(null)} />
        </>
    );
}
