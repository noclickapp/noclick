// One operation in full: its time (a timeline when it has something to say,
// else one line), Output · Input · Tool calls · Details, Cancel and Copy as.
// Rendered in the right drawer any page opens with `?op=`, and as a page at
// `/operations/{id}`. Also the names every Pages-B table resolves ids with.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router';
import { Info } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { ALL_USERS, Agent, NoClickError, Operation, User, type JsonObject, type ToolCall } from 'noclick';
import { listKeys } from '@/sdk/owner';
import { connectionStatus, operationStatus, type StatusLook } from '@/screens/console/lib/status';
import { formatAbsolute, formatDuration, isUuid } from '@/screens/console/lib/format';
import { operationCurl, operationWaitSnippet } from '@/screens/console/lib/snippets';
import { getToken, type AgentHandle, type ParsedQuery, type QueryError } from '@/screens/console/lib/query';
import { userPath } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1, type V1State } from '@/sdk/useV1';
import { useReportHeld } from '@/sdk/held';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { Drawer } from '../ui/Drawer';
import { StatusPill } from '../ui/StatusPill';
import { IdChip } from '../ui/IdChip';
import { JsonView } from '../ui/JsonView';
import { Money } from '../ui/Money';
import { ConsoleButton } from '../ui/Button';
import { ErrorPanel } from '../ui/ErrorPanel';
import { PillSwitch } from '../ui/PillTabs';
import { TimeCell } from '../ui/TimeCell';
import { ExecutionTimeline, shouldShowTimeline, type TimelineTick } from '../ui/ExecutionTimeline';
import { useOwnerOnly } from '../ownerOnly';

// ── names ──────────────────────────────────────────────────────────────────

export interface ConsoleNames {
    agent: (id: string | null | undefined) => { name: string; userId: string | null } | null;
    key: (id: string | null | undefined) => { name: string; prefix: string } | null;
    /** For `agent:<name>` in a query. */
    agentHandles: AgentHandle[];
    /** Your users' ids, for `user:` in a query (a user's id labels itself, so there's no lookup). */
    userIds: string[];
    keyPrefixes: string[];
}

const NAMES_LIMIT = 100;

/**
 * The account's agents and keys by id: what tables print instead of ids, and
 * your users' ids for suggestions. Only the first NAMES_LIMIT of each; beyond
 * them a cell shows the id's prefix.
 */
export function useConsoleNames(): ConsoleNames {
    const { client } = useConsole();
    const ownerCan = useOwnerOnly();
    const agents = useV1('agents?names', () => Agent.listPage({ client, userFilter: ALL_USERS, limit: NAMES_LIMIT }));
    const users = useV1('users?names', () => User.listPage({ client, limit: NAMES_LIMIT }));
    // Only the owner lists keys: as a key, a call's key shows its id's prefix, like any beyond the first NAMES_LIMIT.
    const keys = useV1(ownerCan('keys') ? 'keys?names' : null, () => listKeys(client, { status: 'all', limit: NAMES_LIMIT }));
    return useMemo(() => {
        const agentMap = new Map((agents.data?.data ?? []).map((a) => [a.id, { name: a.name, userId: a.userId }]));
        const keyMap = new Map((keys.data?.data ?? []).map((k) => [k.id, { name: k.name, prefix: k.key_prefix }]));
        return {
            agent: (id) => (id ? (agentMap.get(id) ?? null) : null),
            key: (id) => (id ? (keyMap.get(id) ?? null) : null),
            agentHandles: [...agentMap].map(([id, a]) => ({ id, name: a.name, userId: a.userId })),
            userIds: (users.data?.data ?? []).map((u) => u.id),
            keyPrefixes: [...keyMap.values()].map((k) => k.prefix),
        };
    }, [agents.data, users.data, keys.data]);
}

/**
 * An agent page's `?conv=`: whose thread it is and its name, `<user id|none>:<conversation>`.
 * The user's id is encoded, since yours may hold a `:`; `none` (never a user's id) is the account.
 */
export function conversationParam(userId: string | null, conversation: string): string {
    return `${userId === null ? 'none' : encodeURIComponent(userId)}:${conversation}`;
}

export function parseConversationParam(value: string): { userId: string | null; conversation: string } {
    const cut = value.indexOf(':');
    const head = value.slice(0, cut);
    return { userId: head === 'none' ? null : decodeURIComponent(head), conversation: value.slice(cut + 1) };
}

/** The agents an `agent:<name>` token names, read by that name rather than from the names map. */
export function useAgentQuery(parsed: ParsedQuery): { handles: AgentHandle[]; loaded: boolean; error: QueryError | null } {
    const { client } = useConsole();
    const name = getToken(parsed, 'agent')?.find((v) => !isUuid(v)) ?? null;
    const found = useV1(name ? `agents?name=${name}` : null, () => Agent.listPage({ client, name: name!, userFilter: ALL_USERS, limit: NAMES_LIMIT }));
    return useMemo(
        () => ({
            handles: (found.data?.data ?? []).filter((a) => a.name === name).map((a) => ({ id: a.id, name: a.name, userId: a.userId })),
            loaded: !name || found.data !== undefined || found.error !== undefined,
            error:
                name && found.error !== undefined
                    ? { token: `agent:${name}`, message: `Couldn't look up agents: ${found.error instanceof Error ? found.error.message : String(found.error)}` }
                    : null,
        }),
        [found.data, found.error, name]
    );
}

/** "support-bot · acme": the agent and user a row came from, with the key's prefix on hover. */
export function SourceCell({ names, agentId, userId, keyId, fallback }: { names: ConsoleNames; agentId?: string | null; userId?: string | null; keyId?: string | null; fallback?: string }) {
    const key = names.key(keyId);
    const agent = names.agent(agentId)?.name ?? (agentId ? agentId.slice(0, 8) : null);
    // "support-bot for acme": the agent, and whom it acted for.
    const text = agent ? (userId ? `${agent} for ${userId}` : agent) : (userId ?? key?.name ?? fallback ?? '—');
    return (
        <span className="truncate text-muted-foreground" title={key ? `${key.name} · ${key.prefix}…` : undefined}>
            {text}
        </span>
    );
}

// ── operation helpers ──────────────────────────────────────────────────────

function errorOf(op: Operation): JsonObject | null {
    const error = op.raw.error;
    return error && typeof error === 'object' ? (error as JsonObject) : null;
}

export function operationLook(op: Operation): StatusLook {
    const error = errorOf(op);
    return operationStatus(op.status, error ? { type: String(error.type ?? ''), reason: typeof error.reason === 'string' ? error.reason : null } : null, op.kind, op.step);
}

/** The Duration cell: run time, plus ", waited 2h" on a person; a wait-only operation says "waited 2h". */
export function durationText(op: Operation): string {
    const run = op.runMs ? formatDuration(op.runMs) : '';
    const held = op.heldMs ? `waited ${formatDuration(op.heldMs)}` : '';
    return [run, held].filter(Boolean).join(', ');
}

/** The drawer's one line when there's no timeline: "Waited 120ms · ran 2.72s". */
export function timeLine(op: Operation): string | null {
    const parts = [
        op.waitMs ? `waited ${formatDuration(op.waitMs)}` : null,
        op.runMs ? `ran ${formatDuration(op.runMs)}` : null,
        op.heldMs ? `waited ${formatDuration(op.heldMs)}` : null,
    ].filter(Boolean) as string[];
    if (!parts.length) return null;
    const line = parts.join(' · ');
    return line.charAt(0).toUpperCase() + line.slice(1);
}

/** An agent's tool ref's integration mark (`gmail.send_email` → the Gmail node); web capabilities run on Exa. */
export function toolNodeType(ref: string): string {
    const integration = ref.split('.')[0];
    if (integration === 'search' || integration === 'fetch') return 'automation-exa';
    return `automation-${integration.replace(/_/g, '-')}`;
}

const BY_LABEL: Record<string, string> = { owner: 'You (console)', key: 'an API key', session: 'a session', agent: 'the agent that started it', job: 'its job ending' };

// ── tabs ───────────────────────────────────────────────────────────────────

export interface TabDef {
    id: string;
    label: ReactNode;
}

/** A label and its value, in a detail list. */
export function DetailRow({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
    return (
        <div className={cn('grid min-h-8 grid-cols-[8.5rem_minmax(0,1fr)] items-baseline gap-3 py-1.5 text-[13px]', className)}>
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="m-0 min-w-0 break-words text-foreground">{children}</dd>
        </div>
    );
}

// ── tool calls ─────────────────────────────────────────────────────────────

export const TOOL_CALL_MATCH_NOTE = 'Matched by conversation and time; two overlapping turns in one conversation can share rows.';

/** The connection a call ran on, by its name in the account, else its credential's id. */
export function CallConnection({ call }: { call: ToolCall }) {
    if (call.connection)
        return (
            <span className="block truncate" title={call.connection}>
                {call.connection}
            </span>
        );
    return call.credentialId ? <IdChip id={call.credentialId} /> : <span className="text-muted-foreground">—</span>;
}

/** One tool call's arguments, result, error, the connection it ran on and ids. */
export function ToolCallBody({ call }: { call: ToolCall }) {
    return (
        <div className="flex flex-col gap-3">
            {call.error && <p className="m-0 text-[13px] text-red-600 dark:text-red-400">{call.error}</p>}
            <div>
                <p className="m-0 mb-1 text-[12px] font-medium text-muted-foreground">Arguments</p>
                <JsonView value={call.arguments} />
            </div>
            {call.resultPreview && (
                <div>
                    <p className="m-0 mb-1 text-[12px] font-medium text-muted-foreground">Result preview</p>
                    <pre className="m-0 max-h-60 overflow-auto whitespace-pre-wrap rounded-xl bg-foreground/[0.04] px-3.5 py-3 font-mono text-[12px] dark:bg-foreground/[0.05]">{call.resultPreview}</pre>
                </div>
            )}
            <dl className="m-0">
                {call.conversation && <DetailRow label="Conversation"><span className="font-mono text-[12px]">{call.conversation}</span></DetailRow>}
                {call.executionId && <DetailRow label="Execution"><IdChip id={call.executionId} /></DetailRow>}
                {call.connection && <DetailRow label="Connection">{call.connection}</DetailRow>}
                {call.credentialId && <DetailRow label="Credential"><IdChip id={call.credentialId} /></DetailRow>}
            </dl>
        </div>
    );
}

function ToolCallList({ calls, focus }: { calls: readonly ToolCall[]; focus: string | null }) {
    const [open, setOpen] = useState<string | null>(focus);
    useEffect(() => setOpen(focus), [focus]);
    return (
        <ul className={'m-0 -mx-3 list-none p-0'}>
            {calls.map((call) => {
                const expanded = open === call.id;
                return (
                    <li key={call.id} data-call-id={call.id} className={cn('', expanded && 'bg-foreground/[0.02]')}>
                        <button
                            type="button"
                            aria-expanded={expanded}
                            onClick={() => setOpen(expanded ? null : call.id)}
                            className="flex h-9 w-full items-center gap-3 px-3 text-left text-[13px] transition-colors hover:bg-foreground/[0.03]"
                        >
                            <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{call.toolName}</span>
                            {call.status === 'error' && <span className="text-[12px] text-red-600 dark:text-red-400">Error</span>}
                            <span className="tabular-nums text-muted-foreground">{formatDuration(call.durationMs)}</span>
                        </button>
                        {expanded && (
                            <div className="px-3 pb-3">
                                <ToolCallBody call={call} />
                            </div>
                        )}
                    </li>
                );
            })}
        </ul>
    );
}

// ── output ─────────────────────────────────────────────────────────────────

const text = (value: unknown) => (typeof value === 'string' ? value : null);

function addressee(to: unknown): string {
    const t = (to && typeof to === 'object' ? to : {}) as JsonObject;
    return text(t.email) ?? text(t.phone) ?? (t.user ? 'The user' : 'Someone');
}

function ErrorOutput({ error }: { error: JsonObject }) {
    const { type, message, next_step: nextStep, ...details } = error;
    const cap = type === 'spend_cap_exceeded' && typeof details.cap === 'number';
    return (
        <div className="flex flex-col gap-2">
            <p className="m-0 font-mono text-[12px] text-red-600 dark:text-red-400">{String(type ?? 'error')}</p>
            {text(message) && <p className="m-0 text-sm text-foreground">{String(message)}</p>}
            {cap && (
                <p className="m-0 text-[13px] text-foreground">
                    Stopped by the {String(details.scope ?? 'spend')} cap: <Money usd={Number(details.spent)} /> spent of <Money usd={Number(details.cap)} />
                    {text(details.resets_at) && <> · resets {formatAbsolute(String(details.resets_at)).replace(/, \d\d:\d\d:\d\d$/, '')}</>}
                </p>
            )}
            {text(nextStep) && <p className="m-0 text-[13px] text-muted-foreground">{String(nextStep)}</p>}
            {Object.keys(details).length > 0 && <JsonView value={details} />}
        </div>
    );
}

/** Where work waiting on a person is answered: never in the console, which builds and watches. */
export const ANSWERED_ELSEWHERE = 'It’s answered in your product through the SDK, or from the link the person was sent.';

function HumanOutput({ op, input, result }: { op: Operation; input: JsonObject; result: JsonObject | null }) {
    const pending = op.status === 'awaiting_human';
    const answer = op.kind === 'human.ask' && result ? result : null;
    const options = Array.isArray(input.options) ? (input.options as string[]) : [];
    const details = input.details && typeof input.details === 'object' && Object.keys(input.details).length > 0 ? input.details : null;
    return (
        <dl className="m-0">
            <DetailRow label="To">{addressee(input.to)}</DetailRow>
            {text(input.message) && <DetailRow label="Message">{String(input.message)}</DetailRow>}
            {options.length > 0 && <DetailRow label="Options">{options.join(' · ')}</DetailRow>}
            {details !== null && (
                <DetailRow label="Details">
                    <JsonView value={details} />
                </DetailRow>
            )}
            {result && 'approved' in result && <DetailRow label="Answer">{result.approved ? 'Approved' : 'Denied'}{text(result.text) ? ` · ${String(result.text)}` : ''}</DetailRow>}
            {answer && <DetailRow label="Answer">{[text(answer.choice), text(answer.text)].filter(Boolean).join(' · ') || '—'}</DetailRow>}
            {pending && (
                <DetailRow label="Waiting on">
                    {addressee(input.to)}
                    <span className="mt-0.5 block text-[12px] text-muted-foreground">{ANSWERED_ELSEWHERE}</span>
                </DetailRow>
            )}
        </dl>
    );
}

const AGENT_REPLY_KINDS: ReadonlySet<string> = new Set(['agent.message', 'agent.task', 'agent.ask']);

function Output({ op, onConversation }: { op: Operation; onConversation?: string }) {
    const error = errorOf(op);
    if (error) return <ErrorOutput error={error} />;
    const input = op.input ?? {};
    const result = op.result && typeof op.result === 'object' ? (op.result as JsonObject) : null;
    if (op.kind.startsWith('human.')) return <HumanOutput op={op} input={input} result={result} />;
    if (!op.done) return <p className="m-0 text-[13px] text-muted-foreground">No output yet: the operation is {operationLook(op).label.toLowerCase()}.</p>;
    // A spawned task and an ask (designed) end in a reply like a turn's.
    if (AGENT_REPLY_KINDS.has(op.kind) && result) {
        return (
            <div className="flex flex-col gap-3">
                <p className="m-0 whitespace-pre-wrap text-sm text-foreground">{text(result.text) ?? ''}</p>
                <dl className="m-0">
                    {text(result.conversation) && (
                        <DetailRow label="Conversation">
                            {onConversation ? (
                                <Link to={onConversation} className="underline underline-offset-2">
                                    {String(result.conversation)}
                                </Link>
                            ) : (
                                <span className="font-mono text-[12px]">{String(result.conversation)}</span>
                            )}
                        </DetailRow>
                    )}
                    {typeof result.cost_usd === 'number' && (
                        <DetailRow label="Cost">
                            <Money usd={result.cost_usd} />
                        </DetailRow>
                    )}
                </dl>
            </div>
        );
    }
    if (op.kind === 'agent.rehearse' && result) {
        const calls = Array.isArray(result.tool_calls) ? (result.tool_calls as JsonObject[]) : [];
        return (
            <div className="flex flex-col gap-3">
                <p className="m-0 text-[12px] text-muted-foreground">A test run: a simulated world answered every tool call, so nothing was sent.</p>
                <p className="m-0 whitespace-pre-wrap text-sm text-foreground">{text(result.reply) ?? ''}</p>
                <dl className="m-0">
                    {text(result.scenario) && <DetailRow label="Scenario">{String(result.scenario)}</DetailRow>}
                    {typeof result.cost_usd === 'number' && (
                        <DetailRow label="Cost">
                            <Money usd={result.cost_usd} />
                        </DetailRow>
                    )}
                </dl>
                {calls.length > 0 && <JsonView value={calls} />}
            </div>
        );
    }
    if (op.kind === 'credential.connect' && result?.connection && typeof result.connection === 'object') {
        const connection = result.connection as JsonObject;
        const verification = (connection.verification ?? null) as JsonObject | null;
        const look = connectionStatus({ status: String(connection.status), account: text(connection.account), reachable: (verification?.reachable ?? null) as boolean | null });
        return (
            <dl className="m-0">
                <DetailRow label="Connection">
                    <span className="inline-flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[13px]">{String(connection.name)}</span>
                        <StatusPill look={look} />
                    </span>
                </DetailRow>
                {text(verification?.message) && <DetailRow label="Verification">{String(verification!.message)}</DetailRow>}
                {text(connection.id) && <DetailRow label="ID"><IdChip id={String(connection.id)} /></DetailRow>}
            </dl>
        );
    }
    return <JsonView value={op.result} />;
}

// ── the detail ─────────────────────────────────────────────────────────────

const TERMINAL_POLL_MS = 5000;

/** One operation, re-read every 5s while it isn't done. The drawer's header and body share it. */
export function useOperation(id: string) {
    const { client } = useConsole();
    const [pollMs, setPollMs] = useState<number | undefined>(undefined);
    const state = useV1(`operations/${id}`, () => Operation.fromId(id, { client, user: null }).hydrate(), { pollMs });
    const live = !!state.data && !state.data.done;
    useEffect(() => setPollMs(live ? TERMINAL_POLL_MS : undefined), [live]);
    return state;
}

export function OperationStatusPill({ op }: { op: Operation }) {
    return <StatusPill look={operationLook(op)} />;
}

export function OperationDetail({ id, state }: { id: string; state: V1State<Operation> }) {
    const { client, now, lab } = useConsole();
    const href = useConsoleHref();
    const names = useConsoleNames();
    const [params, setParams] = useSearchParams();
    const op = state.data;
    const isTurn = op?.kind === 'agent.message';
    const calls = useV1(isTurn ? `operations/${id}/tool_calls?${op!.status}` : null, () => Operation.fromId(id, { client, user: null }).toolCalls());
    const [focus, setFocus] = useState<string | null>(null);
    const [canceling, setCanceling] = useState(false);
    const reportHeld = useReportHeld(useConsole());

    const tabs: TabDef[] = [
        { id: 'output', label: 'Output' },
        { id: 'input', label: 'Input' },
        ...(isTurn ? [{ id: 'tool-calls', label: 'Tool calls' }] : []),
        { id: 'details', label: 'Details' },
    ];
    const tab = tabs.some((t) => t.id === params.get('otab')) ? params.get('otab')! : 'output';
    const setTab = useCallback(
        (next: string) =>
            setParams(
                (prev) => {
                    const out = new URLSearchParams(prev);
                    if (next === 'output') out.delete('otab');
                    else out.set('otab', next);
                    return out;
                },
                { replace: true, preventScrollReset: true }
            ),
        [setParams]
    );

    if (state.error !== undefined && !op) return <ErrorPanel error={state.error} onRetry={() => void state.refresh()} />;
    if (!op) {
        return (
            <div aria-busy className="flex flex-col gap-3">
                <div className="h-3 w-2/3 animate-pulse rounded bg-foreground/[0.07]" />
                <div className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]" />
            </div>
        );
    }

    const events = op.transitions.map((e) => ({ status: e.status, at: e.at }));
    const ticks: TimelineTick[] = (calls.data ?? []).filter((c) => c.createdAt).map((c) => ({ id: c.id, name: c.toolName, at: c.createdAt!, durationMs: c.durationMs }));
    const canceledBy = op.transitions.find((e) => e.status === 'canceled')?.by ?? null;
    const agent = names.agent(op.agentId);
    const key = names.key(op.keyId);
    const result = op.result && typeof op.result === 'object' ? (op.result as JsonObject) : null;
    // The conversation a turn ran in: its reply's, else the key it started with (a trigger's rendered template; designed, lab only).
    const replies = isTurn || (lab && (op?.kind === 'agent.task' || op?.kind === 'agent.ask'));
    const conversation = replies ? (text(result?.conversation) ?? (lab ? text(op.input?.conversation) : null)) : null;
    const conversationHref = conversation && op.agentId ? href(`agents/${op.agentId}`, { conv: conversationParam(op.userId, conversation) }) : undefined;

    const cancel = async () => {
        setCanceling(true);
        try {
            const updated = await Operation.fromId(op.id, { client, user: null }).cancel();
            state.mutate(updated);
            invalidateV1('operations?');
            invalidateV1('operations/summary');
            toast.success('Operation canceled');
        } catch (err) {
            if (reportHeld(err, 'Cancel the operation', () => (invalidateV1('operations?'), invalidateV1('operations/summary'), state.refresh()))) return;
            toast.error(err instanceof Error ? err.message : String(err), { description: err instanceof NoClickError ? (err.nextStep ?? undefined) : undefined });
        } finally {
            setCanceling(false);
        }
    };

    return (
        <div className="flex flex-col gap-5">
            <section aria-label="Time">
                {events.length && shouldShowTimeline(events) ? (
                    <ExecutionTimeline
                        events={events}
                        now={now()}
                        ticks={ticks}
                        onTick={(callId) => {
                            setFocus(callId);
                            setTab('tool-calls');
                        }}
                    />
                ) : events.length ? (
                    <p className="m-0 text-[13px] tabular-nums text-foreground">{timeLine(op) ?? 'No time recorded yet.'}</p>
                ) : (
                    <p className="m-0 text-[13px] text-muted-foreground">
                        Created {op.createdAt ? formatAbsolute(op.createdAt) : 'at an unknown time'}. Timings weren&apos;t recorded for operations this old.
                    </p>
                )}
            </section>

            <div className="flex flex-col gap-4">
                <PillSwitch tabs={tabs} value={tab} onChange={setTab} label="Operation" />
                {tab === 'output' && <Output op={op} onConversation={conversationHref} />}
                {tab === 'input' && (op.input ? <JsonView value={op.input} /> : <p className="m-0 text-[13px] text-muted-foreground">No input recorded.</p>)}
                {tab === 'tool-calls' && (
                    <div className="flex flex-col gap-2">
                        <p className="m-0 inline-flex items-center gap-1.5 text-[12px] text-muted-foreground">
                            <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />
                            {TOOL_CALL_MATCH_NOTE}
                        </p>
                        {calls.error !== undefined ? (
                            <ErrorPanel error={calls.error} onRetry={() => void calls.refresh()} />
                        ) : calls.data === undefined ? (
                            <div className="h-16 animate-pulse rounded-lg bg-foreground/[0.04]" />
                        ) : calls.data.length ? (
                            <ToolCallList calls={calls.data} focus={focus} />
                        ) : (
                            <p className="m-0 text-[13px] text-muted-foreground">This turn made no tool calls.</p>
                        )}
                    </div>
                )}
                {tab === 'details' && (
                    <dl className="m-0">
                        <DetailRow label="Kind"><span className="font-mono text-[12px]">{op.kind}</span></DetailRow>
                        <DetailRow label="User">
                            {op.userId ? (
                                <Link to={href(userPath(op.userId))} className="underline underline-offset-2">
                                    {op.userId}
                                </Link>
                            ) : (
                                <span className="text-muted-foreground">Your account</span>
                            )}
                        </DetailRow>
                        <DetailRow label="Requesting key">
                            {key ? (
                                <span>
                                    {key.name} <span className="font-mono text-[12px] text-muted-foreground">{key.prefix}…</span>
                                </span>
                            ) : op.keyId ? (
                                <IdChip id={op.keyId} />
                            ) : (
                                '—'
                            )}
                        </DetailRow>
                        {op.agentId && (
                            <DetailRow label="Agent">
                                <Link to={href(`agents/${op.agentId}`)} className="underline underline-offset-2">
                                    {agent?.name ?? op.agentId}
                                </Link>
                            </DetailRow>
                        )}
                        {lab && conversation && (
                            <DetailRow label="Conversation">
                                {conversationHref ? (
                                    <Link to={conversationHref} className="underline underline-offset-2">
                                        {conversation}
                                    </Link>
                                ) : (
                                    <span className="font-mono text-[12px]">{conversation}</span>
                                )}
                            </DetailRow>
                        )}
                        <DetailRow label="Created"><TimeCell value={op.createdAt} tier="absolute" /></DetailRow>
                        <DetailRow label="Started"><TimeCell value={op.startedAt} tier="absolute" /></DetailRow>
                        <DetailRow label="Finished"><TimeCell value={op.finishedAt} tier="absolute" /></DetailRow>
                        {canceledBy && <DetailRow label="Canceled by">{BY_LABEL[canceledBy] ?? canceledBy}</DetailRow>}
                    </dl>
                )}
            </div>

            <div className={cn('flex flex-wrap items-center gap-2 border-t pt-4', HAIRLINE)}>
                {!op.done && (
                    <ConsoleButton onClick={() => void cancel()} disabled={canceling}>
                        {canceling ? 'Canceling…' : 'Cancel'}
                    </ConsoleButton>
                )}
                <span className="text-[12px] text-muted-foreground">Copy as</span>
                <CopyAs label="curl" value={operationCurl(op.id)} />
                <CopyAs label="Python" value={operationWaitSnippet(op.id).python} />
                <CopyAs label="TypeScript" value={operationWaitSnippet(op.id).typescript} />
            </div>
        </div>
    );
}

function CopyAs({ label, value }: { label: string; value: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <ConsoleButton
            variant="ghost"
            size="sm"
            aria-label={`Copy as ${label}`}
            onClick={async () => {
                try {
                    await navigator.clipboard.writeText(value);
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1500);
                } catch (err) {
                    toast.error(`Couldn't copy: ${err instanceof Error ? err.message : String(err)}`);
                }
            }}
        >
            {copied ? 'Copied' : label}
        </ConsoleButton>
    );
}

/** The drawer's header reads the operation from the same cache the body fills. */
function DrawerFrame({ id, onClose }: { id: string; onClose: () => void }) {
    const href = useConsoleHref();
    const state = useOperation(id);
    const op = state.data;
    useEffect(() => {
        if (op) recordRecent({ type: 'operation', id: op.id, label: op.summaryText || op.kind, path: 'logs', params: { op: op.id } });
    }, [op?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    return (
        <Drawer
            open
            onOpenChange={(open) => !open && onClose()}
            kind="operation"
            id={id}
            title={op?.summaryText || undefined}
            status={op ? <OperationStatusPill op={op} /> : undefined}
            expandHref={href(`logs/${id}`)}
        >
            <OperationDetail id={id} state={state} />
        </Drawer>
    );
}

/** Opens the drawer for `?op=`; closing drops `op` and its tab. Mount once per page. */
export function OperationDrawerHost() {
    const [params, setParams] = useSearchParams();
    const id = params.get('op');
    if (!id) return null;
    const close = () =>
        setParams(
            (prev) => {
                const out = new URLSearchParams(prev);
                out.delete('op');
                out.delete('otab');
                return out;
            },
            { replace: true, preventScrollReset: true }
        );
    return <DrawerFrame id={id} onClose={close} />;
}

/** An agent turn's cost, when it has one. */
export function operationCost(op: Operation): number | null {
    const result = op.result && typeof op.result === 'object' ? (op.result as JsonObject) : null;
    return typeof result?.cost_usd === 'number' ? result.cost_usd : null;
}
