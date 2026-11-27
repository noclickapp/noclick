// Home: one line on what's running, what failed and what it cost, then three
// short lists in the console's one list: agents (what each is doing, what it
// uses, its last day and its month; one per-user agent is one row that opens
// onto its users), automations (agents on a schedule) and hosted MCP servers
// (`?mcp=` opens one). Three headed lists, not one with a type column, because
// each kind has its own telling column: a schedule, a server's clients. Approving a held call or answering a
// question is a person's job in the product, never the console's: work waiting
// on a person shows as a status in Logs and on its agent. An account with no
// agents gets the Quickstart.
import { useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router';
import { ChevronDown, Plus } from 'lucide-react';
import { MarkRow } from '@/ui/primitives';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import { cn } from '@/ui/utils';
import { ALL_USERS, Agent, McpServer, Operation } from 'noclick';
import type { StatusLook } from '@/screens/console/lib/status';
import { formatCount, formatMoney } from '@/screens/console/lib/format';
import { useAccount, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { usePaged, type PagedState } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { useV1, type V1State } from '@/sdk/useV1';
import { BACKSTOP_POLL_MS } from '@/sdk/staleReads';
import { Quickstart } from '../Quickstart';
import { purposeOf, toolEntryText, useAgentMonthSpend } from '../agentParts';
import { NewInCodeDialog, useNewParam } from '../NewInCode';
import { integrationNodeType } from '../connections';
import { PageHeader, PageSection } from '../ui/PageHeader';
import { ErrorPanel } from '../ui/ErrorPanel';
import { ConsoleButton } from '../ui/Button';
import { CapMeter } from '../ui/CapMeter';
import { TimeCell } from '../ui/TimeCell';
import { StatusPill } from '../ui/StatusPill';
import { DataTable, type Column } from '../ui/DataTable';
import { MoreMenu, copyId } from '../ui/MoreMenu';
import { McpServerDrawer, mcpServerLook } from './McpServerDrawer';

const DAY_MS = 86_400_000;

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

const LINE_LINK = 'underline decoration-foreground/25 underline-offset-2 hover:decoration-foreground/60';

/** What's running, what failed in the last day and what the month cost, each a link to where it's read. */
function HomeLine() {
    const href = useConsoleHref();
    const account = useAccount().data;
    if (!account) return null;
    const { counts, month } = account;
    return (
        <>
            {counts.operations_running ? (
                <Link to={href('logs', { q: 'status:live' })} className={LINE_LINK}>
                    {plural(counts.operations_running, 'run')} going now.
                </Link>
            ) : (
                'Nothing running right now.'
            )}{' '}
            {counts.operations_failed_24h > 0 && (
                <>
                    <Link to={href('logs', { q: 'status:failed since:1d' })} className={cn(LINE_LINK, 'text-red-600 decoration-red-600/30 dark:text-red-400 dark:decoration-red-400/30')}>
                        {formatCount(counts.operations_failed_24h)} failed in the last day.
                    </Link>{' '}
                </>
            )}
            <Link to={href('usage')} className={LINE_LINK}>
                {formatMoney(month.spent_usd)} spent this month.
            </Link>
        </>
    );
}

// ── agents ─────────────────────────────────────────────────────────────────

/** Each agent's failed turns in the last day, from one account-wide read. */
function useAgentFailures() {
    const { client, now } = useConsole();
    const since = useMemo(() => new Date(now() - DAY_MS), []); // eslint-disable-line react-hooks/exhaustive-deps
    const failed = useV1('operations?home=failed-1d', () =>
        Operation.listPage({ client, kind: 'agent.message', status: 'failed', createdAfter: since, userFilter: ALL_USERS, limit: 100 })
    );
    return useMemo(() => {
        if (!failed.data) return null;
        const out = new Map<string, number>();
        for (const op of failed.data.data) if (op.agentId) out.set(op.agentId, (out.get(op.agentId) ?? 0) + 1);
        return out;
    }, [failed.data]);
}

/** Working (green: it's running now), idle or expired. */
function agentLook(working: boolean, expired = false, waiting = false): StatusLook {
    if (waiting) return { label: 'Waiting', glyph: 'waiting', tone: 'ink' };
    return working ? { label: 'Working', glyph: 'live', tone: 'ink' } : expired ? { label: 'Expired', glyph: 'muted', tone: 'muted' } : { label: 'Idle', glyph: 'hollow', tone: 'muted' };
}

/** The apps an agent is wired to, as small logos; how many tools when none has a logo. */
function WiredTo({ tools }: { tools: readonly (string | Record<string, unknown>)[] }) {
    const apps = [
        ...new Set(
            tools
                // A tool bound to arguments names its tool: `{ tool: "gmail.send_email", bind }`.
                .map((t) => (typeof t === 'string' ? t : typeof t.tool === 'string' ? t.tool : ''))
                .map((name) => (name ? name.split('.')[0] : null))
                .filter((name): name is string => !!name)
                .map(integrationNodeType)
                .filter((type) => !!getNodeIconMeta(type)?.iconHtml)
        ),
    ];
    if (!tools.length) return <span className="text-muted-foreground">No tools</span>;
    return (
        <span className="inline-flex min-w-0 items-center gap-2" title={tools.map((t) => toolEntryText(t as Parameters<typeof toolEntryText>[0])).join(', ')}>
            {apps.length > 0 ? <MarkRow types={apps} size="xs" max={4} /> : <span className="truncate">{plural(tools.length, 'tool')}</span>}
        </span>
    );
}

/** The month, compact: against its budget when it has one. */
function MonthSpend({ spent, budget }: { spent: number | null | undefined; budget: number | null | undefined }) {
    if (spent === undefined) return <span className="ml-auto block h-3 w-12 animate-pulse rounded bg-foreground/[0.06]" />;
    return <CapMeter spent={spent} cap={budget} className={budget != null ? 'w-full' : undefined} />;
}

/** A row's name, with whose it is when it's one user's (beside it from sm; a phone keeps the room for the name) and its purpose muted beneath. */
function NameCell({ name, user, purpose, indent = false, after }: { name: string; user?: ReactNode; purpose?: string; indent?: boolean; after?: ReactNode }) {
    return (
        <span className={cn('flex min-w-0 flex-col', indent && 'pl-4')}>
            <span className="flex min-w-0 items-center gap-2">
                <span className="min-w-0 truncate font-medium text-foreground">{name}</span>
                {user && <span className="hidden shrink-0 items-center gap-0.5 text-[12px] text-muted-foreground sm:inline-flex">{user}</span>}
                {after}
            </span>
            {purpose && <span className="truncate text-[12px] text-muted-foreground">{purpose}</span>}
        </span>
    );
}

/** Failures in the last day, in red; nothing when there are none. */
function Failures({ count, noun }: { count: number | undefined; noun: string }) {
    if (!count) return null;
    return <span className="text-red-600 dark:text-red-400">{plural(count, noun)} failed</span>;
}

/** What it's doing: its running turns, else when it last ran. */
function activity(agent: Agent): ReactNode {
    if (agent.status === 'working') return `${plural(agent.runningTurns ?? 0, 'turn')} running`;
    return agent.lastActiveAt ? (
        <>
            Active <TimeCell value={agent.lastActiveAt} />
        </>
    ) : (
        <span className="text-muted-foreground">Never ran</span>
    );
}

/**
 * The rows Home lists: an account agent alone, and a user's agent alone unless
 * other users have one by the same name (one per-user agent), which groups.
 */
export function groupAgents(rows: readonly Agent[]): (Agent | { name: string; agents: Agent[] })[] {
    const byName = new Map<string, Agent[]>();
    for (const a of rows) if (a.userId) byName.set(a.name, [...(byName.get(a.name) ?? []), a]);
    const seen = new Set<string>();
    const out: (Agent | { name: string; agents: Agent[] })[] = [];
    for (const a of rows) {
        const group = a.userId ? byName.get(a.name)! : null;
        if (!group || group.length === 1) out.push(a);
        else if (!seen.has(a.name)) {
            seen.add(a.name);
            out.push({ name: a.name, agents: group });
        }
    }
    return out;
}

/** An automation: an agent a schedule wakes. */
const isAutomation = (a: Agent) => a.triggerKinds.includes('cron');

/** What Home's agent lists share: this month's spend and each one's failed turns, from one read each. */
interface AgentRowsData {
    paged: PagedState<Agent>;
    spentOf: ReturnType<typeof useAgentMonthSpend>;
    failed: ReturnType<typeof useAgentFailures>;
}

/** A row of the agent list: an agent, a per-user agent's group, or one of its users' agents under it. */
type AgentRow = { kind: 'agent'; id: string; agent: Agent; member: boolean } | { kind: 'group'; id: string; name: string; agents: Agent[] };

const sumOf = (agents: readonly Agent[], of: (a: Agent) => number) => agents.reduce((total, a) => total + of(a), 0);

function Agents({ paged, spentOf, failed, onCreate }: AgentRowsData & { onCreate: () => void }) {
    const href = useConsoleHref();
    const navigate = useNavigate();
    const [openGroups, setOpenGroups] = useState<ReadonlySet<string>>(new Set());
    // An agent's spawned agents are part of what it's doing (its page lists them); automations are listed apart.
    const agents = paged.rows.filter((a) => !a.parentId && !isAutomation(a));
    const grouped = groupAgents(agents);
    const rows: AgentRow[] = grouped.flatMap((g): AgentRow[] =>
        'agents' in g
            ? [{ kind: 'group', id: `group:${g.name}`, name: g.name, agents: g.agents }, ...(openGroups.has(g.name) ? g.agents.map((a): AgentRow => ({ kind: 'agent', id: a.id, agent: a, member: true })) : [])]
            : [{ kind: 'agent', id: g.id, agent: g, member: false }]
    );
    const toggle = (name: string) => setOpenGroups((prev) => (prev.has(name) ? new Set([...prev].filter((n) => n !== name)) : new Set([...prev, name])));
    const groupSpend = (group: Agent[]) => {
        const spends = group.map(spentOf);
        return spends.some((v) => v === undefined) ? undefined : spends.some((v) => v === null) ? null : spends.reduce<number>((t, v) => t + (v ?? 0), 0);
    };
    const columns: Column<AgentRow>[] = [
        {
            id: 'name',
            header: 'Name',
            cell: (r) =>
                r.kind === 'group' ? (
                    <NameCell
                        name={r.name}
                        user={`for ${plural(r.agents.length, 'user')}`}
                        after={<ChevronDown aria-hidden className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', openGroups.has(r.name) && 'rotate-180')} />}
                        purpose={purposeOf(r.agents[0])}
                    />
                ) : (
                    <NameCell name={r.agent.name} user={r.agent.userId ? `for ${r.agent.userId}` : null} purpose={r.member ? undefined : purposeOf(r.agent)} indent={r.member} />
                ),
        },
        {
            id: 'status',
            header: 'Status',
            className: 'w-[6rem] sm:w-[7rem]',
            cell: (r) => (r.kind === 'group' ? <StatusPill look={agentLook(sumOf(r.agents, (a) => a.runningTurns ?? 0) > 0)} /> : <StatusPill look={agentLook(r.agent.status === 'working', r.agent.status === 'expired', r.agent.status === 'waiting')} />),
        },
        { id: 'wired', header: 'Uses', priority: 3, width: '8rem', cell: (r) => <WiredTo tools={r.kind === 'group' ? r.agents[0].tools : r.agent.tools} /> },
        {
            id: 'failed',
            header: 'Last day',
            priority: 2,
            width: '7rem',
            cell: (r) => <Failures count={failed ? (r.kind === 'group' ? sumOf(r.agents, (a) => failed.get(a.id) ?? 0) : (failed.get(r.agent.id) ?? 0)) : undefined} noun="turn" />,
        },
        { id: 'month', header: 'This month', align: 'right', className: 'w-[8.5rem] sm:w-[9rem]', cell: (r) => <MonthSpend spent={r.kind === 'group' ? groupSpend(r.agents) : spentOf(r.agent)} budget={r.kind === 'group' ? null : r.agent.budgetUsdPerMonth} /> },
        { id: 'activity', header: 'Activity', priority: 3, width: '13rem', cell: (r) => (r.kind === 'group' ? <span className="text-muted-foreground">Across its users</span> : activity(r.agent)) },
    ];
    return (
        <PageSection title="Agents" count={paged.loading ? null : grouped.length}>
            <DataTable
                label="Agent list"
                columns={columns}
                rows={rows}
                getRowId={(r) => r.id}
                loading={paged.loading}
                skeletonRows={3}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(r) => (r.kind === 'group' ? toggle(r.name) : navigate(href(`agents/${r.agent.id}`)))}
                rowActions={(r) =>
                    r.kind === 'group' ? null : (
                        <MoreMenu
                            label={`Actions for ${r.agent.name}`}
                            items={[
                                { label: 'Open', onSelect: () => navigate(href(`agents/${r.agent.id}`)) },
                                { label: 'Copy ID', onSelect: () => void copyId(r.agent.id) },
                            ]}
                        />
                    )
                }
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={
                    <p className="m-0 py-6 text-[13px] text-muted-foreground">
                        No agents yet. Your code makes them;{' '}
                        <button type="button" onClick={onCreate} className="text-foreground underline underline-offset-2">
                            see how
                        </button>
                        .
                    </p>
                }
            />
        </PageSection>
    );
}

// ── everything else you run ────────────────────────────────────────────────

const pad2 = (n: number) => String(n).padStart(2, '0');
const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const DOW_NAMES: Record<string, number> = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };

/** A timezone as the phrase after a time: `Europe/London` → "London time". */
function zoneLabel(tz: string): string {
    return !tz || tz === 'UTC' || tz === 'Etc/UTC' ? 'UTC' : `${tz.split('/').pop()!.replace(/_/g, ' ')} time`;
}

/** A day-of-week field (`1-5`, `mon,thu`, `0,6`) as sorted day numbers, or null. */
function cronDays(field: string): number[] | null {
    const days = new Set<number>();
    for (const part of field.toLowerCase().split(',')) {
        const [a, b] = part.split('-').map((v) => (v in DOW_NAMES ? DOW_NAMES[v] : /^\d$/.test(v) ? Number(v) % 7 : NaN));
        if (Number.isNaN(a) || (b !== undefined && Number.isNaN(b))) return null;
        for (let d = a; d <= (b ?? a); d++) days.add(d % 7);
    }
    return [...days].sort((x, y) => x - y);
}

function joinWords(words: string[]): string {
    return words.length < 2 ? words.join('') : `${words.slice(0, -1).join(', ')} and ${words.at(-1)}`;
}

const ordinal = (n: number) => `${n}${n % 10 === 1 && n !== 11 ? 'st' : n % 10 === 2 && n !== 12 ? 'nd' : n % 10 === 3 && n !== 13 ? 'rd' : 'th'}`;

/**
 * A schedule in plain English: `0 8 * * 1-5` in `Europe/London` → "Weekdays at 08:00, London time".
 * Null for an expression it can't say simply (show the expression then).
 */
export function describeCron(expr: string, tz = 'UTC'): string | null {
    const fields = expr.trim().split(/\s+/);
    if (fields.length !== 5) return null;
    const [minute, hour, dom, month, dow] = fields;
    if (month !== '*') return null;
    const step = (f: string) => /^\*\/(\d+)$/.exec(f)?.[1];
    const n = (f: string, max: number) => (/^\d+$/.test(f) && Number(f) <= max ? Number(f) : null);
    const m = n(minute, 59);
    const h = n(hour, 23);
    const anyDay = dom === '*' && dow === '*';
    if (anyDay && hour === '*') {
        if (minute === '*') return 'Every minute';
        if (step(minute)) return `Every ${step(minute)} minutes`;
        if (m !== null) return m === 0 ? 'Every hour, on the hour' : `Every hour at :${pad2(m)}`;
        return null;
    }
    if (anyDay && m !== null && step(hour)) return `Every ${step(hour)} hours${m ? ` at :${pad2(m)}` : ''}, ${zoneLabel(tz)}`;
    if (m === null || h === null) return null;
    const at = `at ${pad2(h)}:${pad2(m)}, ${zoneLabel(tz)}`;
    if (anyDay) return `Every day ${at}`;
    if (dom === '*') {
        const days = cronDays(dow);
        if (!days) return null;
        const key = days.join(',');
        if (days.length === 7) return `Every day ${at}`;
        if (key === '1,2,3,4,5') return `Weekdays ${at}`;
        if (key === '0,6') return `Weekends ${at}`;
        return `${joinWords(days.map((d) => `${WEEKDAYS[d]}s`))} ${at}`;
    }
    const day = dow === '*' ? n(dom, 31) : null;
    return day ? `On the ${ordinal(day)} of every month ${at}` : null;
}

/** When an automation runs: its schedule in words, and the next run (or that it's paused). */
function ScheduleCell({ agent }: { agent: Agent }) {
    const triggers = useV1(`agents/${agent.id}/triggers`, () => agent.triggers());
    const schedules = (triggers.data ?? []).filter((t) => t.kind === 'cron');
    const [first] = schedules;
    const next = schedules.map((t) => t.nextRun).filter((d): d is Date => !!d).sort((a, b) => a.getTime() - b.getTime())[0];
    const when = first ? (describeCron(String(first.spec.cron ?? ''), String(first.spec.tz ?? 'UTC')) ?? String(first.spec.cron)) : null;
    if (triggers.error !== undefined && !triggers.data) return <span className="text-red-600 dark:text-red-400">{"Couldn't read its schedule."}</span>;
    if (!triggers.data) return <span className="block h-3 w-32 animate-pulse rounded bg-foreground/[0.06]" />;
    return (
        <span className="flex min-w-0 flex-col">
            <span className="truncate text-foreground">
                {when}
                {schedules.length > 1 && <span className="text-muted-foreground"> and {plural(schedules.length - 1, 'more')}</span>}
            </span>
            {!agent.paused && next && (
                <span className="truncate text-[12px] text-muted-foreground">
                    Next run <TimeCell value={next} />
                </span>
            )}
        </span>
    );
}

/** Agents a schedule wakes, listed apart from the ones you message. */
function Automations({ paged, spentOf, failed }: AgentRowsData) {
    const href = useConsoleHref();
    const navigate = useNavigate();
    const rows = paged.rows.filter(isAutomation);
    // They come from the agents read; its failure shows once, under Agents.
    if (paged.error !== undefined && !paged.rows.length) return null;
    const columns: Column<Agent>[] = [
        { id: 'name', header: 'Name', cell: (a) => <NameCell name={a.name} user={a.userId ? `for ${a.userId}` : null} purpose={purposeOf(a)} /> },
        {
            id: 'status',
            header: 'Status',
            className: 'w-[6rem] sm:w-[7rem]',
            cell: (a) => <StatusPill look={a.paused ? { label: 'Paused', glyph: 'hollow', tone: 'muted' } : agentLook(a.status === 'working', a.status === 'expired', a.status === 'waiting')} />,
        },
        { id: 'wired', header: 'Uses', priority: 3, width: '8rem', cell: (a) => <WiredTo tools={a.tools} /> },
        { id: 'failed', header: 'Last day', priority: 2, width: '7rem', cell: (a) => <Failures count={failed ? (failed.get(a.id) ?? 0) : undefined} noun="run" /> },
        { id: 'month', header: 'This month', align: 'right', className: 'w-[8.5rem] sm:w-[9rem]', cell: (a) => <MonthSpend spent={spentOf(a)} budget={a.budgetUsdPerMonth} /> },
        { id: 'schedule', header: 'Runs', priority: 2, width: '13rem', cell: (a) => <ScheduleCell agent={a} /> },
    ];
    return (
        <PageSection title="Automations" count={paged.loading ? null : rows.length}>
            <DataTable
                label="Automation list"
                columns={columns}
                rows={rows}
                getRowId={(a) => a.id}
                loading={paged.loading}
                skeletonRows={1}
                onRowClick={(a) => navigate(href(`agents/${a.id}`))}
                rowActions={(a) => (
                    <MoreMenu
                        label={`Actions for ${a.name}`}
                        items={[
                            { label: 'Open', onSelect: () => navigate(href(`agents/${a.id}`)) },
                            { label: 'Copy ID', onSelect: () => void copyId(a.id) },
                        ]}
                    />
                )}
                empty={
                    <p className="m-0 max-w-2xl py-6 text-[13px] leading-relaxed text-muted-foreground">
                        None yet. An agent with a schedule is an automation: give it <span className="font-mono text-[12px] text-foreground/85">triggers=[noclick.Cron(&quot;0 8 * * 1-5&quot;)]</span> and it
                        runs on its own.
                    </p>
                }
            />
        </PageSection>
    );
}

type Servers = V1State<Awaited<ReturnType<typeof McpServer.listPage>>>;

/** Hosted MCP servers, each with the two things that can go wrong apart: its tools, and its clients. */
function McpServers({ servers }: { servers: Servers }) {
    const [open, setOpen] = useSearchParam('mcp');
    const rows = servers.data?.data ?? [];
    const columns: Column<McpServer>[] = [
        { id: 'name', header: 'Name', cell: (s) => <NameCell name={s.name} user={s.userId ? `for ${s.userId}` : null} purpose={s.tools.map(toolEntryText).join(', ')} /> },
        { id: 'status', header: 'Status', className: 'w-[8.5rem] sm:w-[10rem]', cell: (s) => <StatusPill look={mcpServerLook(s)} /> },
        {
            id: 'clients',
            header: 'Clients',
            priority: 2,
            width: '12rem',
            cell: (s) =>
                s.lastClientAt ? (
                    <>
                        A client called <TimeCell value={s.lastClientAt} />
                    </>
                ) : (
                    <span className="text-muted-foreground">None connected yet</span>
                ),
        },
    ];
    return (
        <PageSection title="MCP servers" count={rows.length}>
            <DataTable
                label="MCP server list"
                columns={columns}
                rows={rows}
                getRowId={(s) => s.id}
                loading={!servers.data && servers.error === undefined}
                skeletonRows={1}
                error={servers.error}
                onRetry={() => void servers.refresh()}
                onRowClick={(s) => setOpen(s.id, { push: true })}
                selectedId={open}
                rowMenu="server"
                empty={
                    <p className="m-0 max-w-2xl py-6 text-[13px] leading-relaxed text-muted-foreground">
                        None yet. One URL gives Claude, ChatGPT or Cursor your tools:{' '}
                        <span className="font-mono text-[12px] text-foreground/85">noclick.McpServer.from_name(&quot;crm-tools&quot;, tools=[...], create_if_missing=True)</span>.
                    </p>
                }
            />
            {open && <McpServerDrawer serverId={open} row={rows.find((s) => s.id === open)} onClose={() => setOpen(null)} />}
        </PageSection>
    );
}

// ── page ───────────────────────────────────────────────────────────────────

/** Everything Home reads, once the account has agents: the agents (and automations), the MCP servers. */
function HomeBody({ onCreate }: { onCreate: () => void }) {
    const { client } = useConsole();
    // Each tile says what its agent is doing now: an agent's turns and changes are frames that read the list again
    // (ConsoleProviders); the backstop only while frames are missed.
    const paged = usePaged('agents?home', (cursor) => Agent.listPage({ client, userFilter: ALL_USERS, cursor, limit: 50 }), (a) => a.id, {
        backstopMs: BACKSTOP_POLL_MS,
    });
    const agents: AgentRowsData = { paged, spentOf: useAgentMonthSpend(paged.rows), failed: useAgentFailures() };
    const servers: Servers = useV1('mcp_servers?home', () => McpServer.listPage({ client, userFilter: ALL_USERS, limit: 50 }));
    // When every read failed, the API is down: say it once, not once per section.
    const allFailed = paged.error !== undefined && !paged.rows.length && servers.error !== undefined && !servers.data;
    if (allFailed) {
        return (
            <ErrorPanel
                error={paged.error}
                onRetry={() => {
                    void paged.refresh();
                    void servers.refresh();
                }}
            />
        );
    }
    return (
        <>
            <Agents {...agents} onCreate={onCreate} />
            <Automations {...agents} />
            <McpServers servers={servers} />
        </>
    );
}

export default function Home() {
    const account = useAccount();
    // `?new=agent` (Home's button, ⌘K) shows the code that makes an agent.
    const [creating, setCreating] = useNewParam('agent');
    const create = <NewInCodeDialog kind="agent" open={creating} onOpenChange={setCreating} />;
    if (account.data?.counts.agents === 0) {
        return (
            <>
                <Quickstart />
                {create}
            </>
        );
    }
    return (
        <>
            <PageHeader
                title="Home"
                purpose={<HomeLine />}
                actions={
                    <ConsoleButton variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setCreating(true)}>
                        New agent
                    </ConsoleButton>
                }
            />
            <HomeBody onCreate={() => setCreating(true)} />
            {create}
        </>
    );
}
