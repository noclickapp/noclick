// One agent, in the anatomy every detail page shares, in one column: what it's
// doing now and what it cost, its recent runs, what it uses and what wakes it,
// the code that messages it, then the facts set once (model, region, ID, share
// link) folded under Details. "Try it" swaps the body for a live conversation
// (`?tab=try`); a conversation opens in the drawer (`?conv=`).
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { AlarmClock, CalendarClock, Download, FileText, FlaskConical, GitBranch, Globe, Hash, Inbox as InboxIcon, InfinityIcon, ListOrdered, Mail, Network, Pause, Phone, Play, Plus, ShieldCheck, SquareTerminal, UserRound, Webhook, Zap, type LucideIcon } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE, LiveDot, fmtBytes } from '@/ui/primitives';
import { credentialLabel } from '@/ui/connectionMark';
import { cn } from '@/ui/utils';
import { ALL_USERS, Agent, Agents, Cron, Inbox, NO_USER, NoClickError, Event as NoClickEvent, OnEvent, OnPlatformEvent, OnQueue, OnWebhook, Operation, PhoneNumber, Policy, Queue, Repo, Secret, Usage, Volume, type AgentGrant, type AgentTrigger, type Conversation, type HarnessName, type IntegrationOperation, type JsonObject, type MemoryEntry, type Message, type PolicyVerdict, type Rehearsal } from 'noclick';
import { BUCKET_TOOLS, DATABASE_TOOLS, toMemoryEntry, toMessage } from '@/sdk/source';
import { formatCount, truncateId } from '@/screens/console/lib/format';
import { agentCodeSnippet, snippetTabs } from '@/screens/console/lib/snippets';
import { userLabel, userPath } from '@/screens/console/lib/userFilter';
import { conversationStatus, type StatusLook } from '@/screens/console/lib/status';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { regionLabel, useRegions } from '@/screens/console/hooks/useRegions';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useReportHeld } from '@/sdk/held';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { EVERYTHING, refFor } from '@/lib/agentTools';
import type { ConsolePageProps } from '../sections';
import {
    CAPABILITY_REFS,
    Field as FormField,
    ModelConnectionField,
    ModelPicker,
    ToolPicker,
    accountFreeIntegration,
    accountFreeOperations,
    agentsToolsOf,
    bindingText,
    boundToolOf,
    bucketRefOf,
    catalogOperations,
    databaseRefOf,
    entryRef,
    harnessSummary,
    inputClass,
    keepsModelConnection,
    modelIntegrationNames,
    modelUsageText,
    parseBudget,
    personLabel,
    personToolOf,
    purposeOf,
    scopeName,
    sharedConnectionOf,
    toolEntryText,
    useHarnesses,
    useOtherScopeConnections,
    useScopeBuckets,
    useScopeDatabases,
} from '../agentParts';
import { connectionLook, nodeTypeOf, useIntegrations, useScopeConnections } from '../connections';
import { PageHeader, PageSection } from '../ui/PageHeader';
import { PillTabs } from '../ui/PillTabs';
import { AsideSection, DETAIL_PAGE, Disclosure, Fact, Facts } from '../ui/Detail';
import { MoreMenu, copyId } from '../ui/MoreMenu';
import { ErrorPanel } from '../ui/ErrorPanel';
import { ConsoleButton } from '../ui/Button';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { CopyButton } from '../ui/CopyButton';
import { CodeSnippet } from '../ui/CodeSnippet';
import { IdChip } from '../ui/IdChip';
import { TimeCell } from '../ui/TimeCell';
import { Money } from '../ui/Money';
import { CapMeter } from '../ui/CapMeter';
import { StatusPill } from '../ui/StatusPill';
import { DataTable, type Column } from '../ui/DataTable';
import { Drawer } from '../ui/Drawer';
import { FacetSelect } from '../ui/FacetSelect';
import { JsonView } from '../ui/JsonView';
import { Segmented } from '../ui/Segmented';
import { conversationParam, parseConversationParam } from './OperationDrawer';
import { OperationsView } from './Operations';
import { AgentTryIt, dottedTool } from './AgentTryIt';
import { AgentLiveChips, AskSection, ChildrenSection, JobsSection, TaskSection, WakeupsSection, coordinates } from './AgentCoordination';
import { describeCron } from './Home';
import { useUsers } from './lookups';
import { QueuesTriggerTitle } from './resources/QueuesParts';

const DAY_MS = 86_400_000;
const LIST_LIMIT = 200;

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

// ── editable facts ─────────────────────────────────────────────────────────

function Editable({
    label,
    value,
    display,
    multiline = false,
    placeholder,
    input,
    parse,
    onSave,
}: {
    label: string;
    value: string;
    display: ReactNode;
    multiline?: boolean;
    placeholder?: string;
    /** A control of its own for the draft, in place of the text box. */
    input?: (draft: string, setDraft: (text: string) => void) => ReactNode;
    /** The typed text → the value to save, or an error message. */
    parse?: (text: string) => { value: unknown } | { error: string };
    onSave: (value: unknown) => Promise<void>;
}) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(value);
    const [saving, setSaving] = useState(false);
    const parsed = parse ? parse(draft) : { value: draft };
    const save = async () => {
        if ('error' in parsed) return;
        setSaving(true);
        try {
            await onSave(parsed.value);
            setEditing(false);
        } catch (err) {
            toast.error(err instanceof Error ? err.message : String(err), { description: err instanceof NoClickError ? (err.nextStep ?? undefined) : undefined });
        } finally {
            setSaving(false);
        }
    };
    if (!editing) {
        return (
            <div className="group/edit flex min-w-0 items-start justify-between gap-2">
                <div className="min-w-0 flex-1">{display}</div>
                <button
                    type="button"
                    aria-label={`Edit ${label.toLowerCase()}`}
                    onClick={() => {
                        setDraft(value);
                        setEditing(true);
                    }}
                    className="shrink-0 text-[12px] text-muted-foreground transition-opacity hover:text-foreground md:opacity-0 md:focus:opacity-100 md:group-hover/edit:opacity-100"
                >
                    Edit
                </button>
            </div>
        );
    }
    return (
        <div className="flex flex-col gap-1.5">
            {input ? (
                input(draft, setDraft)
            ) : multiline ? (
                <textarea aria-label={label} value={draft} onChange={(e) => setDraft(e.target.value)} rows={8} className={cn(inputClass, 'h-auto py-2 leading-relaxed')} />
            ) : (
                <input aria-label={label} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={placeholder} className={inputClass} />
            )}
            {'error' in parsed && <span className="text-[12px] text-red-600 dark:text-red-400">{parsed.error}</span>}
            <div className="flex gap-1.5">
                <ConsoleButton size="sm" onClick={() => void save()} disabled={saving || 'error' in parsed}>
                    {saving ? 'Saving…' : 'Save'}
                </ConsoleButton>
                <ConsoleButton size="sm" variant="ghost" onClick={() => setEditing(false)}>
                    Cancel
                </ConsoleButton>
            </div>
        </div>
    );
}

/** This month's spend: a budgeted agent's covers the agents it spawned (the limits read), any other's is its own series. */
function useAgentSpend(agent: Agent): number | null | undefined {
    const { client } = useConsole();
    const budgeted = agent.budgetUsdPerMonth != null;
    const limits = useV1(budgeted ? 'usage/limits' : null, () => Usage.limits({ client }));
    const series = useV1(budgeted ? null : `usage/series?agent=${agent.id}`, () => Usage.series({ client, agent: agent.id, groupBy: 'type', userFilter: ALL_USERS }));
    const source = budgeted ? limits : series;
    if (source.error !== undefined) return null;
    return budgeted ? limits.data && (limits.data.agents.find((a) => a.id === agent.id)?.subtreeSpent ?? 0) : series.data?.totalUsd;
}

/** The agent's A2A endpoint, from its card. */
function A2AFact({ agentId }: { agentId: string }) {
    const { client } = useConsole();
    const card = useV1(`agents/${agentId}/a2a/card`, () => client.request<{ url?: string }>('GET', `/v1/agents/${encodeURIComponent(agentId)}/a2a/card`, { user: null }));
    const url = card.data?.url;
    if (!url) return null;
    return (
        <Fact label="Agent-to-agent URL">
            <span className="inline-flex max-w-full items-center gap-1" title={url}>
                <span className="truncate">{url.replace(/^https:\/\//, '')}</span>
                <CopyButton value={url} label="Copy agent-to-agent URL" />
            </span>
        </Fact>
    );
}

/** The agent it was made under (its children are listed in the main column). */
function useParent(agent: Agent) {
    const { client } = useConsole();
    const all = useV1(agent.parentId ? 'agents?family' : null, () => Agent.list({ client, userFilter: ALL_USERS, limit: LIST_LIMIT }));
    return useMemo(() => (agent.parentId ? ((all.data ?? []).find((a) => a.id === agent.parentId) ?? null) : null), [all.data, agent.parentId]);
}

const LINK = 'underline decoration-foreground/25 underline-offset-2 hover:decoration-foreground/60';

type SaveAgent = (changes: Parameters<Agent['update']>[0]) => Promise<void>;

function EditButton({ label, onClick }: { label: string; onClick: () => void }) {
    return (
        <button
            type="button"
            aria-label={`Edit ${label.toLowerCase()}`}
            onClick={onClick}
            className="shrink-0 text-[12px] text-muted-foreground transition-opacity hover:text-foreground md:opacity-0 md:focus:opacity-100 md:group-hover/edit:opacity-100"
        >
            Edit
        </button>
    );
}

function toastError(err: unknown) {
    toast.error(err instanceof Error ? err.message : String(err), { description: err instanceof NoClickError ? (err.nextStep ?? undefined) : undefined });
}

/**
 * What runs it. A new harness takes its default model and a model connection
 * that serves it, and each conversation carries on there from its next turn:
 * the confirm says so before anything changes.
 */
function HarnessFact({ agent, save }: { agent: Agent; save: SaveAgent }) {
    const harnesses = useHarnesses();
    const connections = useScopeConnections(agent.userId);
    const current = harnesses.data?.find((h) => h.name === agent.harness);
    const [draft, setDraft] = useState<{ harness: HarnessName; connection: string } | null>(null);
    const [confirming, setConfirming] = useState(false);
    const [saving, setSaving] = useState(false);
    const target = draft ? harnesses.data?.find((h) => h.name === draft.harness) : undefined;
    const pick = (name: HarnessName) => {
        const next = harnesses.data?.find((h) => h.name === name);
        const keep = !!next && !!agent.modelConnection && keepsModelConnection(agent.modelConnection, next, connections.data);
        setDraft({ harness: name, connection: keep ? agent.modelConnection! : '' });
    };
    const moving = !!draft && draft.harness !== agent.harness;
    const ready = moving && !!target && (target.modelConnection !== 'required' || !!draft.connection);
    const apply = async () => {
        if (!draft || !target) return;
        setSaving(true);
        try {
            const connection = draft.connection !== (agent.modelConnection ?? '') ? { modelConnection: draft.connection || null } : {};
            await save({ harness: draft.harness, ...connection });
            setConfirming(false);
            setDraft(null);
        } catch (err) {
            toastError(err);
        } finally {
            setSaving(false);
        }
    };
    if (!draft) {
        return (
            <div className="group/edit flex min-w-0 items-start justify-between gap-2">
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span>
                        {current?.label ?? agent.harness}{' '}
                        <span className="font-mono text-[12px] text-muted-foreground">
                            {agent.harness}
                            {current?.version ? ` ${current.version}` : ''}
                        </span>
                    </span>
                    {current && <span className="text-[12px] text-muted-foreground">{harnessSummary(current)}</span>}
                </div>
                {harnesses.data && <EditButton label="Where it runs" onClick={() => setDraft({ harness: (agent.harness ?? 'sdk') as HarnessName, connection: agent.modelConnection ?? '' })} />}
            </div>
        );
    }
    const label = target?.label ?? draft.harness;
    return (
        <div className="flex flex-col gap-2">
            <select
                aria-label="Runs on"
                value={draft.harness}
                onChange={(e) => pick(e.target.value as HarnessName)}
                className={cn(inputClass, 'px-2 [color-scheme:light] dark:[color-scheme:dark]')}
            >
                {(harnesses.data ?? []).map((h) => (
                    <option key={h.name} value={h.name}>
                        {h.label ?? h.name}
                    </option>
                ))}
            </select>
            {moving && target && (
                <ModelConnectionField
                    key={target.name}
                    harness={target}
                    user={agent.userId}
                    value={draft.connection}
                    onChange={(connection) => setDraft({ ...draft, connection })}
                    stacked
                />
            )}
            <div className="flex gap-1.5">
                <ConsoleButton size="sm" onClick={() => setConfirming(true)} disabled={!ready}>
                    Save
                </ConsoleButton>
                <ConsoleButton size="sm" variant="ghost" onClick={() => setDraft(null)}>
                    Cancel
                </ConsoleButton>
            </div>
            {confirming && target && (
                <ConsoleDialog
                    open
                    onOpenChange={(o) => !o && setConfirming(false)}
                    size="sm"
                    title={`Move ${agent.name} to ${label}?`}
                    description={`Each of its conversations carries on on ${label} from its next turn, with its history. Its model becomes ${label}'s default, ${target.defaultModel}; change it after if you want another.`}
                    footer={
                        <>
                            <ConsoleButton variant="ghost" onClick={() => setConfirming(false)}>
                                Cancel
                            </ConsoleButton>
                            <ConsoleButton variant="primary" onClick={() => void apply()} disabled={saving}>
                                {saving ? 'Moving…' : `Move to ${label}`}
                            </ConsoleButton>
                        </>
                    }
                >
                    <p className="m-0 text-[13px] text-muted-foreground">{harnessSummary(target)}</p>
                </ConsoleDialog>
            )}
        </div>
    );
}

/** The connection it thinks with: its state (a pending one holds every turn back) and its open link, editable within its scope. */
function ModelConnectionFact({ agent, save }: { agent: Agent; save: SaveAgent }) {
    const href = useConsoleHref();
    const harnesses = useHarnesses();
    const connections = useScopeConnections(agent.userId);
    const harness = harnesses.data?.find((h) => h.name === agent.harness);
    const connection = agent.modelConnection ? connections.data?.find((c) => refFor(c) === agent.modelConnection) : undefined;
    const [draft, setDraft] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const apply = async () => {
        setSaving(true);
        try {
            await save({ modelConnection: draft || null });
            setDraft(null);
        } catch (err) {
            toastError(err);
        } finally {
            setSaving(false);
        }
    };
    if (draft !== null && harness) {
        return (
            <div className="flex flex-col gap-2">
                <ModelConnectionField harness={harness} user={agent.userId} value={draft} onChange={setDraft} stacked />
                <div className="flex gap-1.5">
                    <ConsoleButton
                        size="sm"
                        onClick={() => void apply()}
                        disabled={saving || draft === (agent.modelConnection ?? '') || (harness.modelConnection === 'required' && !draft)}
                    >
                        {saving ? 'Saving…' : 'Save'}
                    </ConsoleButton>
                    <ConsoleButton size="sm" variant="ghost" onClick={() => setDraft(null)}>
                        Cancel
                    </ConsoleButton>
                </div>
            </div>
        );
    }
    const where = agent.userId ? href(userPath(agent.userId)) : href('resources/connections');
    return (
        <div className="group/edit flex min-w-0 items-start justify-between gap-2">
            {agent.modelConnection ? (
                <div className="flex min-w-0 flex-1 flex-col items-start gap-1">
                    <Link to={where} className={LINK}>
                        {connection?.name ?? agent.modelConnection}
                    </Link>
                    {connection && <StatusPill look={connectionLook(connection)} />}
                    {connections.data && !connection && (
                        <span className="text-[12px] text-red-600 dark:text-red-400">{agent.userId ? 'Its user has' : 'Your account has'} no connection with this name.</span>
                    )}
                    {connection?.connectUrl && (
                        <span className="inline-flex items-center gap-1 text-[12px] text-muted-foreground">
                            {connection.status === 'pending' ? 'Its turns wait until someone connects it' : 'Reconnect it'} at its link
                            <CopyButton value={connection.connectUrl} label="Copy connect link" />
                        </span>
                    )}
                </div>
            ) : (
                <span className="flex-1 text-muted-foreground">None: its model runs on NoClick&apos;s key</span>
            )}
            {harness && <EditButton label="Model connection" onClick={() => setDraft(agent.modelConnection ?? '')} />}
        </div>
    );
}

/** An IANA timezone this runtime knows, or blank for none. */
function parseTimezone(text: string): { value: string | null } | { error: string } {
    const zone = text.trim();
    if (!zone) return { value: null };
    try {
        new Intl.DateTimeFormat('en-US', { timeZone: zone });
        return { value: zone };
    } catch {
        return { error: `'${zone}' isn't an IANA timezone, like Europe/London or America/New_York.` };
    }
}

/** Saves a change to the agent, then shows the agent the API sent back. */
function saverFor(agent: Agent, onSaved: (agent: Agent) => void): SaveAgent {
    return async (changes) => {
        onSaved(await agent.update(changes));
        invalidateV1('agents?');
        toast.success('Saved');
    };
}

/** This month's spend, against its budget when it has one; the budget is edited here. */
function BudgetFact({ agent, save }: { agent: Agent; save: SaveAgent }) {
    const spent = useAgentSpend(agent);
    return (
        <Fact label="This month">
            <Editable
                label="Monthly budget"
                value={agent.budgetUsdPerMonth == null ? '' : String(agent.budgetUsdPerMonth)}
                placeholder="No budget"
                parse={parseBudget}
                display={
                    agent.budgetUsdPerMonth == null ? (
                        <span>
                            <Money usd={spent} /> <span className="text-muted-foreground">with no monthly budget</span>
                        </span>
                    ) : (
                        <span className="flex flex-col gap-1">
                            <CapMeter spent={spent} cap={agent.budgetUsdPerMonth} className="w-full" />
                            <span className="text-[12px] text-muted-foreground">The budget counts the agents it spawns.</span>
                        </span>
                    )
                }
                onSave={(v) => save({ budgetUsdPerMonth: v as number | null })}
            />
        </Fact>
    );
}

/** The facts set once: its instructions, how and where it runs, whom it serves, and its addresses. */
function About({ agent, save }: { agent: Agent; save: SaveAgent }) {
    const href = useConsoleHref();
    const parent = useParent(agent);
    const harness = useHarnesses().data?.find((h) => h.name === agent.harness);
    const regions = useRegions().data;
    return (
        <section aria-label="About">
            <Facts className="grid gap-x-10 sm:grid-cols-2">
                <Fact label="Instructions" className="sm:col-span-2">
                    <Editable
                        label="Instructions"
                        multiline
                        value={agent.instructions ?? ''}
                        display={<p className="m-0 line-clamp-5 whitespace-pre-wrap text-foreground/85">{agent.instructions}</p>}
                        onSave={(v) => save({ instructions: String(v) })}
                    />
                </Fact>
                <Fact label="Runs on">
                    <HarnessFact agent={agent} save={save} />
                </Fact>
                <Fact label="Model">
                    <Editable
                        label="Model"
                        value={agent.model ?? ''}
                        input={(draft, setDraft) => <ModelPicker ariaLabel="Model" harness={harness} value={draft} onChange={setDraft} />}
                        display={<span className="break-all">{agent.model ?? "The harness's default"}</span>}
                        onSave={(v) => save({ model: String(v) })}
                    />
                </Fact>
                <Fact label="Model connection">
                    <ModelConnectionFact agent={agent} save={save} />
                </Fact>
                <Fact label="Region">
                    <span className={agent.region ? undefined : 'text-muted-foreground'}>{regionLabel(agent.region, regions)}</span>
                </Fact>
                <Fact label="Timezone">
                    <Editable
                        label="Timezone"
                        value={agent.timezone ?? ''}
                        placeholder={agent.userId ? "Its user's" : "Each user's"}
                        parse={parseTimezone}
                        display={agent.timezone ? <span>{agent.timezone}</span> : <span className="text-muted-foreground">{agent.userId ? "Its user's, else UTC" : "Each user's, else UTC"}</span>}
                        onSave={(v) => save({ timezone: v as string | null })}
                    />
                </Fact>
                <Fact label="Serves">
                    {agent.userId ? (
                        <Link to={href(userPath(agent.userId))} className={LINK}>
                            {agent.userId}
                        </Link>
                    ) : (
                        'Every user, each in their own conversations'
                    )}
                </Fact>
                {agent.parentId && (
                    <Fact label="Gets work from">
                        {parent ? (
                            <Link to={href(`agents/${parent.id}`)} className={LINK}>
                                {parent.name}
                            </Link>
                        ) : (
                            <IdChip id={agent.parentId} />
                        )}
                    </Fact>
                )}
                {agent.expiresAt && (
                    // Past its time to live an agent is expired, and readable for 30 days before it's deleted.
                    <Fact label={agent.status === 'expired' ? 'Expired' : 'Expires'}>
                        <TimeCell value={agent.expiresAt} />
                    </Fact>
                )}
                <A2AFact agentId={agent.id} />
                <Fact label="ID">
                    <IdChip id={agent.id} full />
                </Fact>
                <Fact label="Created">
                    <TimeCell value={agent.createdAt} tier="absolute" />
                </Fact>
            </Facts>
        </section>
    );
}

/** What it is beyond what it does, folded under one heading until asked for. */
function Details({ agent, save }: { agent: Agent; save: SaveAgent }) {
    return (
        <Disclosure title="Details" hint="Instructions, model, region, ID and share link" className="mt-12">
            <div className="flex flex-col gap-8">
                <About agent={agent} save={save} />
                <ShareLinkSection agent={agent} />
            </div>
        </Disclosure>
    );
}

// ── uses ───────────────────────────────────────────────────────────────────

const VERDICTS: Record<PolicyVerdict['verdict'], StatusLook> = {
    allow: { label: 'Allowed', glyph: 'check', tone: 'ink' },
    approval: { label: 'Needs approval', glyph: 'waiting', tone: 'ink' },
    deny: { label: 'Denied', glyph: 'cross', tone: 'failure' },
};

/** An integration's operations, as the catalog lists them, or why they couldn't be read. */
type Expansion = { ops: IntegrationOperation[] } | { error: unknown };

/**
 * Each tool with what policy decides for it: one line per tool, then the
 * operations that don't just run. A tool names a connection in the agent's own
 * scope, else an integration's operations that need no account (`exa.search`,
 * on NoClick's key); policy judges the integration's operations (`gmail.send_email_message`).
 */
function ToolList({ agent }: { agent: Agent }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const connections = useScopeConnections(agent.userId);
    const databases = useScopeDatabases(agent.userId);
    // A bound operation runs its `tool` ref; a person runs none.
    const refs = agent.tools.flatMap((e) => entryRef(e) ?? []);
    const bindingOf = new Map(agent.tools.flatMap((e) => (boundToolOf(e) ? [[boundToolOf(e)!.tool, boundToolOf(e)!.bind] as const] : [])));
    const people = agent.tools.flatMap((e) => personToolOf(e) ?? []);
    const hasBuckets = refs.some((t) => bucketRefOf(t));
    const buckets = useScopeBuckets(agent.userId, hasBuckets);
    // A ref names one of the scope's connections as the platform reads it: `credential:<id>` an account connected in
    // the app, any other a connection by its name.
    const byRef = new Map((connections.data ?? []).map((c) => [refFor(c), c]));
    // The agents capability: one row however its tools are listed.
    const agentsTools = [...new Set(refs.flatMap((t) => agentsToolsOf(t) ?? []))];
    // Everything on the account is its own row, never a tool policy judges: its runs are judged as the operations they run.
    const everything = refs.includes(EVERYTHING);
    const tools = refs.filter((t) => t !== 'code' && t !== EVERYTHING && !databaseRefOf(t) && !bucketRefOf(t) && !agentsToolsOf(t));
    const hasShared = tools.some((t) => sharedConnectionOf(t));
    const others = useOtherScopeConnections(agent.userId, hasShared);
    const byId = new Map((others.data ?? []).map((c) => [c.id, c]));
    const known = connections.data && (!hasShared || others.data);
    // Only a name with no connection in the scope needs the catalog: it may be an integration that needs no account.
    const unnamed = !!known && tools.some((t) => !CAPABILITY_REFS.has(t) && !sharedConnectionOf(t) && !byRef.has(t.split('.')[0]));
    const integrations = useIntegrations(unnamed);
    // A catalog that can't be read leaves those rows unjudged, not the rest.
    const settled = known && (!unnamed || integrations.data || integrations.error !== undefined);
    /** What a ref names: a connection (by name in the agent's scope, by id from another, designed), else an integration that needs no account. */
    const refOf = (ref: string) => {
        const shared = sharedConnectionOf(ref);
        if (shared) return { connection: byId.get(shared.id), op: shared.op, shared: true, name: byId.get(shared.id)?.name ?? '', free: undefined };
        const [name, op] = ref.split('.');
        const connection = byRef.get(name);
        return { connection, op: op ?? null, shared: false, name, free: connection ? undefined : accountFreeIntegration(name, integrations.data) };
    };
    /** Each database it uses, with the operations it has (the whole database is all three). */
    const databaseOps = new Map<string, string[]>();
    /** Each bucket it uses, likewise. */
    const bucketOps = new Map<string, string[]>();
    for (const ref of refs) {
        const parsed = databaseRefOf(ref);
        if (parsed) databaseOps.set(parsed.id, [...new Set([...(databaseOps.get(parsed.id) ?? []), ...(parsed.op ? [parsed.op] : DATABASE_TOOLS)])]);
        const bucket = bucketRefOf(ref);
        if (bucket) bucketOps.set(bucket.id, [...new Set([...(bucketOps.get(bucket.id) ?? []), ...(bucket.op ? [bucket.op] : BUCKET_TOOLS)])]);
    }
    /** Operations belong to the integration, so one catalog read serves every ref to it. */
    const read = settled
        ? [
              ...new Set(
                  tools.flatMap((t) => {
                      if (CAPABILITY_REFS.has(t)) return [];
                      const { connection, free } = refOf(t);
                      return connection ? [connection.integration] : free ? [free.name] : [];
                  })
              ),
          ]
        : null;
    const catalog = useV1(read?.length ? `integrations/operations?${read.join(',')}` : null, async () => {
        // One integration that can't be read marks its own rows, not the list.
        const entries = await Promise.all(
            read!.map(async (name): Promise<[string, Expansion]> => {
                try {
                    return [name, { ops: await catalogOperations(name, client) }];
                } catch (error) {
                    return [name, { error }];
                }
            })
        );
        return Object.fromEntries(entries) as Record<string, Expansion>;
    });
    /** The policy names a ref stands for; empty while unknown. */
    const judgedOf = (ref: string): string[] => {
        if (CAPABILITY_REFS.has(ref)) return [ref];
        const { connection, op, free } = refOf(ref);
        const integration = connection?.integration ?? free?.name;
        const entry = integration ? catalog.data?.[integration] : undefined;
        if (connection && op) return [`${connection.integration}.${op}`];
        if (!entry || !('ops' in entry)) return [];
        return (connection ? entry.ops.map((o) => o.name) : accountFreeOperations(entry.ops, op)).map((o) => `${integration}.${o}`);
    };
    const ready = settled && (!read?.length || catalog.data);
    const judged = ready
        ? [
              ...new Set([
                  ...tools.flatMap(judgedOf),
                  ...[...databaseOps.values()].flat().map((op) => `database.${op}`),
                  ...[...bucketOps.values()].flat().map((op) => `bucket.${op}`),
                  ...people.flatMap((p) => p.tools.map((t) => `human.${t}`)),
                  ...agentsTools.map((t) => `agents.${t}`),
              ]),
          ]
        : null;
    const verdicts = useV1(judged?.length ? `policy/evaluate?agent=${agent.id}&tools=${judged.join(',')}` : null, () =>
        Policy.evaluate(judged!, { client, user: agent.userId ?? null })
    );
    const byTool = new Map((verdicts.data ?? []).map((v) => [v.tool, v]));
    const error = connections.error ?? others.error ?? integrations.error ?? catalog.error ?? verdicts.error ?? databases.error ?? buckets.error;
    /** A bound operation's arguments, filled by NoClick on every call. */
    const bound = (ref: string) => {
        const bind = bindingOf.get(ref);
        return bind ? <span className="text-[12px] text-muted-foreground">Bound: {bindingText(bind)}</span> : null;
    };
    const heldRows = (held: PolicyVerdict[]) =>
        held.map((v) => (
            <span key={v.tool} className="flex items-center justify-between gap-2 pl-3 text-[12px]">
                <span className="truncate text-muted-foreground">{v.tool.slice(v.tool.indexOf('.') + 1)}</span>
                <StatusPill look={VERDICTS[v.verdict]} />
            </span>
        ));
    const scope = agent.userId ? 'for its user' : 'on the account';
    return (
        <ul aria-label="Tools" className={'m-0 list-none p-0'}>
            {everything && (
                <li className="flex flex-col gap-1 py-2" data-tool="everything">
                    <span className="flex min-w-0 items-center gap-2">
                        <InfinityIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <span className="truncate text-[14px] text-foreground">Everything {agent.userId ? 'on its user’s account' : 'on the account'}</span>
                    </span>
                    <span className="text-[12px] text-muted-foreground">
                        Every connection {scope}, ones made later too, every operation that needs no account, the web and NoClick, resolved each turn. Each run is judged as the operation it runs.
                    </span>
                </li>
            )}
            {tools.map((ref) => {
                if (CAPABILITY_REFS.has(ref)) {
                    const verdict = byTool.get(ref);
                    return (
                        <li key={ref} className="flex items-center justify-between gap-2 py-2">
                            <span className="truncate text-[14px] text-foreground">{ref}</span>
                            {verdict && verdict.verdict !== 'allow' && <StatusPill look={VERDICTS[verdict.verdict]} />}
                        </li>
                    );
                }
                const { connection, op, shared, name, free } = refOf(ref);
                const entry = catalog.data?.[connection?.integration ?? free?.name ?? ''];
                const judgedHere = judgedOf(ref).map((t) => byTool.get(t)).filter((v): v is PolicyVerdict => !!v);
                const held = judgedHere.filter((v) => v.verdict !== 'allow');
                // An integration's operation that needs an account reaches nothing without a connection.
                const runsFree = free && entry && 'ops' in entry ? accountFreeOperations(entry.ops, op) : null;
                const missing = known && !connection && (shared || (!!integrations.data && (!free || runsFree?.length === 0)));
                // A service's name says how to fix it: a connection of that name.
                const fixable = missing && !shared && !!integrations.data?.some((i) => i.name === name);
                return (
                    <li key={ref} className="flex flex-col gap-1 py-2">
                        <div className="flex items-center justify-between gap-2">
                            {shared ? (
                                <span className="flex min-w-0 items-baseline gap-1.5">
                                    <span className="truncate text-[14px] text-foreground">{connection ? `${name}${op ? `.${op}` : ''}` : truncateId(ref.slice(ref.indexOf(':') + 1))}</span>
                                    {connection && <span className="shrink-0 text-[12px] text-muted-foreground">from {scopeName(connection.userId)}</span>}
                                </span>
                            ) : (
                                // An account connected in the app reads by its name, not the id its ref holds.
                                <span className="truncate text-[14px] text-foreground">{connection?.origin === 'app' ? `${connection.name}${op ? `.${op}` : ''}` : ref}</span>
                            )}
                            {connection && connection.status !== 'connected' ? (
                                <StatusPill look={connectionLook(connection)} />
                            ) : (
                                op && held[0] && <StatusPill look={VERDICTS[held[0].verdict]} />
                            )}
                        </div>
                        {missing ? (
                            <>
                                <span className="text-[12px] text-red-600 dark:text-red-400">
                                    {shared
                                        ? 'The shared connection was deleted; its tools answer that it was.'
                                        : `No connection named ${name} ${scope}; its tools answer that it was deleted.`}
                                </span>
                                {fixable && (
                                    <span className="text-[12px] text-muted-foreground">
                                        {op ? `${op} needs an account. ` : ''}
                                        <Link to={href('resources/connections')} className="text-foreground underline-offset-2 hover:underline">
                                            Create a connection
                                        </Link>{' '}
                                        named <span className="font-mono">{name}</span> {scope} to use it.
                                    </span>
                                )}
                            </>
                        ) : entry && 'error' in entry ? (
                            <span className="text-[12px] text-red-600 dark:text-red-400">{"Couldn't read its operations."}</span>
                        ) : connection ? (
                            <span className="text-[12px] text-muted-foreground">
                                {credentialLabel(connection.credentialType ?? '', nodeTypeOf(connection))}
                                {op ? `: ${op}` : entry && 'ops' in entry ? `: ${plural(entry.ops.length, 'operation')}` : ''}
                                {!op && verdicts.data && held.length > 0 && `, ${held.length} limited by your approval rules`}
                            </span>
                        ) : free && runsFree ? (
                            <span className="text-[12px] text-muted-foreground">
                                {free.label ?? free.name}
                                {op ? `: ${op} · needs no account` : `: ${plural(runsFree.length, 'operation')}, no account needed`}
                                {!op && verdicts.data && held.length > 0 && `, ${held.length} limited by your approval rules`}
                            </span>
                        ) : null}
                        {bound(ref)}
                        {!op && heldRows(held)}
                        {op && held[0] && connection && connection.status !== 'connected' && (
                            <span className="self-start">
                                <StatusPill look={VERDICTS[held[0].verdict]} />
                            </span>
                        )}
                    </li>
                );
            })}
            {[...databaseOps].map(([id, ops]) => {
                const database = databases.data?.find((d) => d.id === id);
                const held = ops.map((op) => byTool.get(`database.${op}`)).filter((v): v is PolicyVerdict => !!v && v.verdict !== 'allow');
                return (
                    <li key={id} className="flex flex-col gap-1 py-2">
                        {database ? (
                            <Link to={href('resources/databases', { database: id })} className="truncate text-[14px] text-foreground underline-offset-2 hover:underline">
                                {database.name}
                            </Link>
                        ) : (
                            <span className="truncate font-mono text-[13px] text-foreground">{truncateId(id)}</span>
                        )}
                        {database ? (
                            <span className="text-[12px] text-muted-foreground">Database: {ops.join(', ')}</span>
                        ) : (
                            databases.data && (
                                <span className="text-[12px] text-red-600 dark:text-red-400">
                                    No database with this id {agent.userId ? 'for its user or the account' : 'on the account'}; its tools answer that it was deleted.
                                </span>
                            )
                        )}
                        {[...bindingOf.keys()].filter((r) => databaseRefOf(r)?.id === id).map((r) => (
                            <span key={r}>{bound(r)}</span>
                        ))}
                        {heldRows(held)}
                    </li>
                );
            })}
            {[...bucketOps].map(([id, ops]) => {
                const bucket = buckets.data?.find((b) => b.id === id);
                const held = ops.map((op) => byTool.get(`bucket.${op}`)).filter((v): v is PolicyVerdict => !!v && v.verdict !== 'allow');
                return (
                    <li key={id} className="flex flex-col gap-1 py-2">
                        {bucket ? (
                            <Link to={href('resources/storage', { bucket: id })} className="truncate text-[14px] text-foreground underline-offset-2 hover:underline">
                                {bucket.name}
                            </Link>
                        ) : (
                            <span className="truncate font-mono text-[13px] text-foreground">{truncateId(id)}</span>
                        )}
                        {bucket ? (
                            <span className="text-[12px] text-muted-foreground">Bucket: {ops.join(', ')}</span>
                        ) : (
                            buckets.data && (
                                <span className="text-[12px] text-red-600 dark:text-red-400">
                                    No bucket with this id {agent.userId ? 'for its user or the account' : 'on the account'}; its tools answer that it was deleted.
                                </span>
                            )
                        )}
                        {[...bindingOf.keys()].filter((r) => bucketRefOf(r)?.id === id).map((r) => (
                            <span key={r}>{bound(r)}</span>
                        ))}
                        {heldRows(held)}
                    </li>
                );
            })}
            {people.map((person) => {
                const held = person.tools.map((t) => byTool.get(`human.${t}`)).filter((v): v is PolicyVerdict => !!v && v.verdict !== 'allow');
                return (
                    <li key={`${personLabel(person.address)}:${person.tools.join(',')}`} className="flex flex-col gap-1 py-2">
                        <span className="flex min-w-0 items-center gap-2">
                            <UserRound className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            <span className="truncate text-[14px] text-foreground">{personLabel(person.address)}</span>
                        </span>
                        <span className="text-[12px] text-muted-foreground">Person: {person.tools.map((t) => PERSON_TOOLS[t] ?? t).join(', ')}</span>
                        {heldRows(held)}
                    </li>
                );
            })}
            {agentsTools.length > 0 && (
                <li className="flex flex-col gap-1 py-2">
                    <span className="flex min-w-0 items-center gap-2">
                        <Network className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <span className="truncate text-[14px] text-foreground">agents</span>
                    </span>
                    <span className="text-[12px] text-muted-foreground">
                        {agentsTools.length === Agents.TOOLS.length ? 'Spawns, messages, asks and tracks agents' : `Agents: ${agentsTools.join(', ')}`} {scope}
                    </span>
                    {heldRows(agentsTools.map((t) => byTool.get(`agents.${t}`)).filter((v): v is PolicyVerdict => !!v && v.verdict !== 'allow'))}
                </li>
            )}
            <li className="flex flex-col gap-1 py-2 text-[13px] text-muted-foreground">
                <span className="flex items-center gap-2">
                    <SquareTerminal className="h-3.5 w-3.5 shrink-0" />
                    {agent.shell === false ? (
                        <span>No shell: it runs no commands</span>
                    ) : (
                        <span>
                            Shell commands (<span className="font-mono">code</span>), as every agent can
                        </span>
                    )}
                </span>
                {agent.shell !== false && <ShellExtras agent={agent} />}
                <Reach agent={agent} />
                {agent.status !== 'expired' && (
                    <span className="flex items-center gap-2">
                        <AlarmClock className="h-3.5 w-3.5 shrink-0" />
                        <span>
                            Wakes itself later (<span className="font-mono">wake_me</span>)
                            {agent.jobId ? (
                                <>
                                    {' '}
                                    and reports to its parent (<span className="font-mono">tell_parent</span>)
                                </>
                            ) : (
                                ', as every agent can'
                            )}
                        </span>
                    </span>
                )}
            </li>
            {error !== undefined && <li className="py-2 text-[12px] text-red-600 dark:text-red-400">{error instanceof Error ? error.message : String(error)}</li>}
        </ul>
    );
}

/** What its shell carries: volumes mounted by path, and secrets' keys in its environment. */
function ShellExtras({ agent }: { agent: Agent }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const mounts = Object.entries(agent.volumes);
    const secretIds = agent.secretIds;
    const extras = useV1(mounts.length || secretIds.length ? `agents/${agent.id}/shell?${mounts.flat().join(',')}&${secretIds.join(',')}` : null, async () => ({
        volumes: await Promise.all(mounts.map(([, id]) => Volume.get(id, { client }))),
        secrets: await Promise.all(secretIds.map((id) => Secret.get(id, { client }))),
    }));
    if (!extras.data) return extras.error !== undefined ? <span className="pl-5 text-[12px] text-red-600 dark:text-red-400">{"Couldn't read its volumes and secrets."}</span> : null;
    const line = (key: string, left: ReactNode, name: string, to: string, kind: string) => (
        <span key={key} className="flex items-baseline justify-between gap-2 pl-5 text-[12px]">
            <span className="min-w-0 truncate font-mono text-foreground/85">{left}</span>
            <span className="shrink-0">
                <Link to={to} className="text-foreground underline-offset-2 hover:underline">
                    {name}
                </Link>
                <span className="text-muted-foreground"> · {kind}</span>
            </span>
        </span>
    );
    return (
        <>
            {mounts.map(([path], i) => line(path, path, extras.data!.volumes[i].name, href('resources/volumes', { volume: extras.data!.volumes[i].id }), 'volume'))}
            {extras.data.secrets.map((s) => line(s.id, s.keys.join(', '), s.name, href('resources/secrets', { secret: s.id }), 'secret'))}
        </>
    );
}

/** A person's tools as the list says them. */
const PERSON_TOOLS: Record<string, string> = { notify: 'notify', ask: 'ask', hand_off: 'hand off' };

/** What its shell and code reach, and the repositories cloned into its workspace. */
function Reach({ agent }: { agent: Agent }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const { network, repos } = agent;
    const hostedIds = repos.flatMap((r) => (typeof r.repo_id === 'string' ? [r.repo_id] : []));
    const hosted = useV1(hostedIds.length ? `repos?agent=${agent.id}` : null, () => Repo.list({ client, userFilter: ALL_USERS, limit: 100 }));
    // What it needs to work stays reachable whatever its network: an sdk agent's shell only clones through NoClick.
    const needs = agent.harness === 'sdk' ? (repos.length ? "NoClick's git proxy" : null) : 'NoClick and its model';
    const reach =
        agent.shell === false || network === null
            ? null
            : network === true
              ? 'Reaches any host'
              : network === false || network.length === 0
                ? needs
                    ? `No network but ${needs}`
                    : 'No network'
                : `Reaches only ${network.join(', ')}${needs ? `, and ${needs}` : ''}`;
    return (
        <>
            {reach && (
                <span className="flex items-center gap-2 pl-5 text-[12px]">
                    <Globe className="h-3 w-3 shrink-0" />
                    <span className="min-w-0 truncate">{reach}</span>
                </span>
            )}
            {repos.map((r, i) => {
                const repo = typeof r.repo_id === 'string' ? hosted.data?.find((h) => h.id === r.repo_id) : undefined;
                const repository = typeof r.repository === 'string' ? r.repository : null;
                const name = repository ?? repo?.name ?? truncateId(String(r.repo_id ?? ''));
                const folder = typeof r.path === 'string' ? r.path : (repository?.split('/').pop() ?? repo?.name ?? name);
                const push = Array.isArray(r.push) ? r.push.map(String) : null;
                const via = typeof r.connection === 'string' ? (sharedConnectionOf(r.connection) ? 'a shared connection' : r.connection) : null;
                return (
                    <span key={i} className="flex flex-col pl-5 text-[12px]">
                        <span className="flex min-w-0 items-center gap-2">
                            <GitBranch className="h-3 w-3 shrink-0" />
                            {typeof r.repo_id === 'string' ? (
                                <Link to={href('resources/repos', { repo: r.repo_id })} className="min-w-0 truncate font-mono text-foreground underline-offset-2 hover:underline">
                                    {name}
                                </Link>
                            ) : (
                                <span className="min-w-0 truncate font-mono text-foreground">{name}</span>
                            )}
                            <span className="shrink-0">
                                {via && `via ${via} · `}
                                {typeof r.branch === 'string' ? r.branch : 'default branch'}
                            </span>
                        </span>
                        <span className="pl-5">
                            In <span className="font-mono">/workspace/{folder}</span> · {push?.length ? `pushes to ${push.join(', ')}` : 'read-only'}
                        </span>
                    </span>
                );
            })}
        </>
    );
}

const GRANT_LOOKS: Record<AgentGrant['status'], StatusLook> = {
    requested: { label: 'Asked', reason: 'waiting to connect', glyph: 'waiting', tone: 'ink' },
    active: { label: 'Granted', glyph: 'check', tone: 'ink' },
};

/** Connections its user gave it at run time, each revocable, and what it may still ask for. */
function Grants({ agent }: { agent: Agent }) {
    const key = `agents/${agent.id}/grants`;
    const grants = useV1(key, () => agent.grants());
    const [revoking, setRevoking] = useState<string | null>(null);
    const reportHeld = useReportHeld(useConsole());
    const rows = grants.data ?? [];
    const ceiling = agent.canRequest;
    if (!ceiling.length && !rows.length) return null;
    const revoke = async (grant: AgentGrant) => {
        setRevoking(grant.id);
        try {
            await agent.revokeGrant(grant);
            invalidateV1(key);
            toast.success(`${agent.name} no longer uses ${grant.connection}`);
        } catch (err) {
            if (reportHeld(err, `Take ${grant.connection} from ${agent.name}`, () => invalidateV1(key))) return;
            toast.error(err instanceof Error ? err.message : String(err));
        } finally {
            setRevoking(null);
        }
    };
    return (
        <div className={cn('mt-1 border-t pt-2', HAIRLINE)}>
            {rows.length > 0 && (
                <ul aria-label="Granted by its user" className={'m-0 list-none p-0'}>
                    {rows.map((g) => (
                        <li key={g.id} className="flex flex-col gap-1 py-2">
                            <div className="flex items-center justify-between gap-2">
                                <span className="truncate text-[14px] text-foreground">{g.connection}</span>
                                <StatusPill look={GRANT_LOOKS[g.status]} />
                            </div>
                            <span className="text-[12px] text-muted-foreground">
                                {g.operations ? g.operations.join(', ') : `Every ${g.integration} operation`}
                                {g.reason && ` · “${g.reason}”`}
                            </span>
                            <button
                                type="button"
                                onClick={() => void revoke(g)}
                                disabled={revoking === g.id}
                                className="self-start text-[12px] text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline disabled:opacity-50"
                            >
                                {revoking === g.id ? 'Revoking…' : 'Revoke'}
                            </button>
                        </li>
                    ))}
                </ul>
            )}
            {grants.error !== undefined && <ErrorPanel error={grants.error} onRetry={grants.refresh} className="bg-transparent" />}
            {ceiling.length > 0 && (
                <p className="m-0 py-2 text-[12px] text-muted-foreground">
                    Can ask its user for{' '}
                    {ceiling.includes('*') ? (
                        'any service'
                    ) : (
                        ceiling.map((c, i) => (
                            <span key={c}>
                                {i > 0 && ', '}
                                <span className="font-mono text-foreground/85">{c}</span>
                            </span>
                        ))
                    )}
                    .
                </p>
            )}
        </div>
    );
}

function ToolsDialog({ agent, onSaved, onClose }: { agent: Agent; onSaved: (agent: Agent) => void; onClose: () => void }) {
    const [draft, setDraft] = useState<string[]>(agent.tools.filter((t): t is string => typeof t === 'string' && t !== 'code'));
    // Bound operations and people are your code's: kept as they are.
    const kept = agent.tools.filter((t): t is JsonObject => typeof t !== 'string');
    const [saving, setSaving] = useState(false);
    const save = async () => {
        setSaving(true);
        try {
            onSaved(await agent.update({ tools: [...draft, ...kept] }));
            invalidateV1('agents?');
            toast.success('Tools saved');
            onClose();
        } catch (err) {
            toast.error(err instanceof Error ? err.message : String(err), { description: err instanceof NoClickError ? (err.nextStep ?? undefined) : undefined });
        } finally {
            setSaving(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            title={`${agent.name}'s tools`}
            description="Changes apply from its next turn; what its user granted it stays. Your approval rules still decide what runs without asking."
            size="lg"
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="primary" onClick={() => void save()} disabled={saving}>
                        {saving ? 'Saving…' : 'Save tools'}
                    </ConsoleButton>
                </>
            }
        >
            <ToolPicker value={draft} onChange={setDraft} user={agent.userId ?? null} />
            {kept.length > 0 && (
                <div className="mt-3 flex flex-col gap-1">
                    <span className="text-[12px] text-muted-foreground">Kept as your code set them: operations with arguments bound, and people</span>
                    <ul aria-label="Kept tools" className="m-0 flex list-none flex-wrap gap-1 p-0">
                        {kept.map((t, i) => (
                            <li key={i} className="rounded bg-foreground/[0.06] px-1.5 py-[1px] font-mono text-[12px]">
                                {toolEntryText(t)}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </ConsoleDialog>
    );
}

function Uses({ agent, onSaved }: { agent: Agent; onSaved: (agent: Agent) => void }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const [editing, setEditing] = useState(false);
    const inboxes = useV1('inboxes?wiring', () => Inbox.list({ client, userFilter: ALL_USERS, limit: LIST_LIMIT }));
    const numbers = useV1('phone_numbers?wiring', () => PhoneNumber.list({ client, userFilter: ALL_USERS, limit: LIST_LIMIT }));
    const ownInboxes = (inboxes.data ?? []).filter((i) => i.agentId === agent.id);
    const ownNumbers = (numbers.data ?? []).filter((n) => n.agentId === agent.id);
    return (
        <PageSection
            title="Uses"
            right={
                <>
                    <Link to={href('settings/policy', agent.userId ? { layer: agent.userId } : {})} className="text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                        Approval rules →
                    </Link>
                    <ConsoleButton size="sm" variant="ghost" onClick={() => setEditing(true)}>
                        Edit tools
                    </ConsoleButton>
                </>
            }
        >
            <ToolList agent={agent} />
            <Grants agent={agent} />
            {(ownInboxes.length > 0 || ownNumbers.length > 0) && (
                <ul aria-label="Resources it answers" className={'m-0 list-none p-0'}>
                    {ownInboxes.map((i) => (
                        <li key={i.id}>
                            <Link to={href('resources/inboxes', { inbox: i.id })} className="flex items-center gap-3 py-2.5 text-[14px] text-foreground/85 hover:text-foreground">
                                <InboxIcon aria-label="Inbox" className="h-4 w-4 shrink-0 text-muted-foreground" />
                                <span className="truncate">{i.address}</span>
                            </Link>
                        </li>
                    ))}
                    {ownNumbers.map((n) => (
                        <li key={n.id}>
                            <Link to={href('resources/phone', { number: n.id })} className="flex items-center gap-3 py-2.5 text-[14px] tabular-nums text-foreground/85 hover:text-foreground">
                                <Phone aria-label="Phone number" className="h-4 w-4 shrink-0 text-muted-foreground" />
                                <span className="truncate">{n.number}</span>
                            </Link>
                        </li>
                    ))}
                </ul>
            )}
            {editing && <ToolsDialog agent={agent} onSaved={onSaved} onClose={() => setEditing(false)} />}
        </PageSection>
    );
}

// ── now ────────────────────────────────────────────────────────────────────

/** What it's doing: its running turns, the last day's, and what the month cost against its budget. */
function Now({ agent, save }: { agent: Agent; save: SaveAgent }) {
    const { client, now } = useConsole();
    const href = useConsoleHref();
    const [, setOp] = useSearchParam('op');
    const since = useMemo(() => new Date(now() - DAY_MS), []); // eslint-disable-line react-hooks/exhaustive-deps
    const running = useV1(
        `operations?agent-running=${agent.id}`,
        () => Operation.listPage({ client, kind: 'agent.message', agent: agent.id, status: 'live', userFilter: ALL_USERS, limit: 20 }),
        { pollMs: 10_000 }
    );
    const day = useV1(`operations/summary?agent-1d=${agent.id}`, () => Operation.summary({ client, kind: 'agent.message', agent: agent.id, createdAfter: since, userFilter: ALL_USERS }));
    const rows = running.data?.data ?? [];
    const failed = day.data?.byStatus.failed ?? 0;
    const lastDay = day.data && (
        <>
            {plural(day.data.total, 'turn')} in the last day
            {failed > 0 && (
                <>
                    {', '}
                    <Link to={href('logs', { q: `kind:agent.message agent:${agent.id} status:failed since:1d` })} className="text-red-600 underline-offset-2 hover:underline dark:text-red-400">
                        {formatCount(failed)} failed
                    </Link>
                </>
            )}
            .
        </>
    );
    return (
        <PageSection title="Now" count={rows.length}>
            {running.error !== undefined && !running.data ? (
                <ErrorPanel error={running.error} onRetry={() => void running.refresh()} />
            ) : !running.data ? (
                <div aria-busy className="h-10 animate-pulse rounded-lg bg-foreground/[0.03]" />
            ) : rows.length ? (
                <>
                    <ul aria-label="Running now" className={'m-0 list-none p-0'}>
                        {rows.map((op) => (
                            <li key={op.id}>
                                <button
                                    type="button"
                                    onClick={() => setOp(op.id, { push: true })}
                                    className="-mx-3 flex w-[calc(100%+1.5rem)] items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-foreground/[0.03]"
                                >
                                    <LiveDot className="scale-75" />
                                    <span className="min-w-0 flex-1 truncate text-[14px] text-foreground">{op.summaryText || 'A turn'}</span>
                                    <span className="hidden shrink-0 text-[13px] text-muted-foreground sm:inline">{userLabel(op.userId)}</span>
                                    <TimeCell value={op.createdAt} className="shrink-0 text-[13px] text-muted-foreground" />
                                </button>
                            </li>
                        ))}
                    </ul>
                    {lastDay && <p className="m-0 mt-3 text-[14px] text-foreground/80">{lastDay}</p>}
                </>
            ) : (
                <p className="m-0 text-[14px] text-foreground/80">
                    Nothing running right now.{lastDay && ' '}
                    {lastDay}
                </p>
            )}
            <Facts className="mt-4 max-w-sm">
                <BudgetFact agent={agent} save={save} />
            </Facts>
        </PageSection>
    );
}

// ── conversations ──────────────────────────────────────────────────────────

function conversationColumns(): Column<Conversation>[] {
    return [
        {
            id: 'title',
            header: 'Conversation',
            cell: (c) => {
                const look = conversationStatus(c.status, c.handedOffTo);
                return (
                    <span className="flex min-w-0 flex-col">
                        <span className="flex min-w-0 items-center gap-2">
                            <span className="truncate text-foreground">{c.title || <span className="font-mono text-[12px]">{c.conversation}</span>}</span>
                            {look && <StatusPill look={look} />}
                        </span>
                        {c.preview && <span className="truncate text-[12px] text-muted-foreground">{c.preview}</span>}
                    </span>
                );
            },
        },
        {
            id: 'user',
            header: 'User',
            priority: 2,
            width: '8rem',
            cell: (c) => (c.userId ? <span className="truncate">{c.userId}</span> : <span className="text-muted-foreground">Your account</span>),
        },
        { id: 'turns', header: 'Turns', priority: 3, align: 'right', width: '4.5rem', cell: (c) => <span className="tabular-nums">{c.turns ?? ''}</span> },
        { id: 'cost', header: 'Cost', priority: 3, align: 'right', width: '5.5rem', cell: (c) => <Money usd={c.costUsd} /> },
        { id: 'last', header: 'Last message', priority: 2, width: '7.5rem', cell: (c) => <TimeCell value={c.lastActivity} /> },
    ];
}

/** A thread read as the account naming whose it is (`user_id`), so a suspended user's still loads. */
async function readThread(client: ReturnType<typeof useConsole>['client'], agentId: string, userId: string | null, conversation: string): Promise<Message[]> {
    const raw = await client.request<{ messages?: JsonObject[] }>('GET', `/v1/agents/${encodeURIComponent(agentId)}/conversations/${encodeURIComponent(conversation)}`, {
        query: { user_id: userId ?? 'none' },
        user: null,
    });
    return (raw.messages ?? []).map(toMessage);
}

/** What a conversation's model calls came to, and who holds it; a handed-off one goes back to the agent here. */
function ConversationState({ agent, conversation, onHandedBack }: { agent: Agent; conversation: Conversation; onHandedBack: () => void }) {
    const [busy, setBusy] = useState(false);
    const look = conversationStatus(conversation.status, conversation.handedOffTo);
    if (!look && !conversation.modelUsage) return null;
    const handBack = async () => {
        setBusy(true);
        try {
            await agent.handBack(conversation.conversation, { user: conversation.userId });
            toast.success(`${agent.name} answers this conversation again`);
            onHandedBack();
        } catch (err) {
            toastError(err);
        } finally {
            setBusy(false);
        }
    };
    return (
        <dl className={cn('m-0 mb-4 border-b pb-3', HAIRLINE)}>
            {look && (
                <div className="flex min-h-8 flex-wrap items-center justify-between gap-2 py-1">
                    <span className="flex min-w-0 items-center gap-2">
                        <StatusPill look={look} />
                        <span className="text-[13px] text-muted-foreground">
                            {conversation.status === 'handed_off'
                                ? `${agent.name} stays quiet while ${conversation.handedOffTo ?? 'the person'} answers from their page.`
                                : 'A turn waits on a person: its question, an approval or a sign-in.'}
                        </span>
                    </span>
                    {conversation.status === 'handed_off' && (
                        <ConsoleButton size="sm" variant="soft" onClick={() => void handBack()} disabled={busy}>
                            {busy ? 'Handing back…' : 'Hand back'}
                        </ConsoleButton>
                    )}
                </div>
            )}
            {conversation.modelUsage && (
                <div className="flex items-baseline gap-3 py-1">
                    <dt className="w-24 shrink-0 text-[12px] text-muted-foreground">Model</dt>
                    <dd className="m-0 text-[13px] tabular-nums text-foreground">
                        {modelUsageText(conversation.modelUsage)}
                        <span className="text-muted-foreground">, on its model connection</span>
                    </dd>
                </div>
            )}
        </dl>
    );
}

function Transcript({ agent, userId, conversation, person = null }: { agent: Agent; userId: string | null; conversation: string; person?: string | null }) {
    const { client } = useConsole();
    const history = useV1(`agents/${agent.id}/conversations/${userId ?? 'none'}/${conversation}`, () => readThread(client, agent.id, userId, conversation));
    if (history.error !== undefined) return <ErrorPanel error={history.error} onRetry={() => void history.refresh()} />;
    if (!history.data) return <div aria-busy className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]" />;
    if (!history.data.length) return <p className="m-0 text-[13px] text-muted-foreground">No messages in this conversation.</p>;
    return (
        <ol className="m-0 flex list-none flex-col gap-3 p-0">
            {history.data.map((m, i) => (
                <li key={i} className="flex flex-col gap-0.5">
                    <span className="text-[12px] font-medium text-muted-foreground">
                        {m.role === 'user' ? 'User' : m.role === 'assistant' ? agent.name : m.role === 'person' ? (person ?? 'Person') : m.role}
                        {m.createdAt && (
                            <>
                                {' · '}
                                <TimeCell value={m.createdAt} tier="absolute" />
                            </>
                        )}
                    </span>
                    <p className="m-0 whitespace-pre-wrap text-sm text-foreground">{m.text}</p>
                </li>
            ))}
        </ol>
    );
}

function Conversations({ agent }: { agent: Agent }) {
    const { lab } = useConsole();
    const paged = usePaged(
        `agents/${agent.id}/conversations`,
        (cursor) => agent.conversationsPage({ userFilter: ALL_USERS, cursor, limit: 10 }),
        (c) => conversationParam(c.userId, c.conversation)
    );
    const [conv, setConv] = useSearchParam('conv');
    const open = conv ? parseConversationParam(conv) : null;
    const row = conv ? paged.rows.find((c) => conversationParam(c.userId, c.conversation) === conv) : undefined;
    return (
        <PageSection title="Conversations" count={paged.rows.length} note={lab ? 'Open one for its transcript and the files it worked on in it.' : undefined}>
            <DataTable
                label="Conversations"
                columns={conversationColumns()}
                rows={paged.rows}
                getRowId={(c) => conversationParam(c.userId, c.conversation)}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                empty={<p className="m-0 py-6 text-center text-[13px] text-muted-foreground">No conversations yet. Try it starts one.</p>}
                selectedId={conv}
                onRowClick={(c) => setConv(conversationParam(c.userId, c.conversation), { push: true })}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                skeletonRows={3}
            />
            {open && (
                <Drawer
                    open
                    onOpenChange={(o) => !o && setConv(null)}
                    kind="Conversation"
                    title={row?.title ?? <span className="font-mono text-[14px]">{open.conversation}</span>}
                    status={<span className="text-[12px] text-muted-foreground">{userLabel(open.userId)}</span>}
                >
                    {row && <ConversationState agent={agent} conversation={row} onHandedBack={() => void paged.refresh()} />}
                    <Transcript agent={agent} userId={open.userId} conversation={open.conversation} person={row?.handedOffTo ?? null} />
                    <WorkspaceFiles agent={agent} userId={open.userId} conversation={open.conversation} />
                </Drawer>
            )}
        </PageSection>
    );
}

// ── triggers ───────────────────────────────────────────────────────────────

const TRIGGER_KINDS: Record<string, { label: string; Icon: LucideIcon }> = {
    cron: { label: 'Schedule', Icon: CalendarClock },
    webhook: { label: 'Webhook', Icon: Webhook },
    event: { label: 'App event', Icon: Zap },
    platform: { label: 'NoClick event', Icon: Zap },
    queue: { label: 'Queue', Icon: ListOrdered },
    email: { label: 'Email', Icon: Mail },
    call: { label: 'Phone calls', Icon: Phone },
    approval: { label: 'Approvals', Icon: ShieldCheck },
    channel: { label: 'Channel', Icon: Hash },
    routine: { label: 'Routine', Icon: AlarmClock },
};

const specText = (t: AgentTrigger, key: string) => (typeof t.spec[key] === 'string' ? (t.spec[key] as string) : '');

/** What a trigger is, in one line. A queue is in the agent's user's scope. */
function triggerTitle(t: AgentTrigger, userId: string | null): ReactNode {
    switch (t.kind) {
        case 'cron':
            return describeCron(specText(t, 'cron'), specText(t, 'tz')) ?? (
                <span className="font-mono text-[13px]">
                    {specText(t, 'cron')} ({specText(t, 'tz') || 'UTC'})
                </span>
            );
        case 'webhook':
            return `Webhook ${specText(t, 'name')}`;
        case 'event': {
            const filters = Object.entries((t.spec.filters as JsonObject | undefined) ?? {});
            // An account connected in the app is named by its id: it reads as the account it hears through.
            const through = specText(t, 'connection');
            const who = through.startsWith('credential:') ? (t.summary?.account ?? t.summary?.app ?? 'Your account connected in the app') : through;
            return (
                <>
                    {who} sends {specText(t, 'event')}
                    {filters.length > 0 && <span className="text-muted-foreground"> where {filters.map(([k, v]) => `${k} is ${String(v)}`).join(', ')}</span>}
                </>
            );
        }
        case 'platform': {
            const filters = Object.entries((t.spec.filters as JsonObject | undefined) ?? {});
            return (
                <>
                    NoClick sends {specText(t, 'type')}
                    {filters.length > 0 && <span className="text-muted-foreground"> where {filters.map(([k, v]) => `${k} is ${String(v)}`).join(', ')}</span>}
                </>
            );
        }
        case 'queue':
            return <QueuesTriggerTitle name={specText(t, 'queue')} batchSize={Number(t.spec.batch_size ?? 1)} userId={userId} />;
        case 'email':
            return `Mail to ${specText(t, 'address')}`;
        case 'call':
            return <span className="tabular-nums">Calls to {specText(t, 'number')}</span>;
        case 'approval': {
            const held = Array.isArray(t.spec.tools) ? t.spec.tools.map(String) : [];
            return (
                <>
                    An answered approval of a call your rules held
                    {held.length > 0 && <span className="text-muted-foreground"> ({held.join(', ')})</span>}
                </>
            );
        }
        case 'channel':
            return `Posts in #${specText(t, 'name')}${t.spec.mode === 'mentions' ? ' that mention it' : ''}`;
        case 'routine':
            return describeCron(specText(t, 'cron'), specText(t, 'tz')) ?? `${specText(t, 'cron')} (${specText(t, 'tz') || 'UTC'})`;
        default:
            return t.kind;
    }
}

const PAUSED_LOOK: StatusLook = { label: 'Paused', glyph: 'hollow', tone: 'muted' };
const CANT_FIRE_LOOK: StatusLook = { label: "Can't fire", glyph: 'cross', tone: 'failure' };

/** One trigger in two lines: what wakes it and when it last did, then what it says and how its turns run. */
function TriggerRow({ trigger, paused, userId, onRemove }: { trigger: AgentTrigger; paused: boolean; userId: string | null; onRemove: (t: AgentTrigger) => void }) {
    const href = useConsoleHref();
    const kind = TRIGGER_KINDS[trigger.kind] ?? { label: trigger.kind, Icon: Zap };
    const message = specText(trigger, 'message');
    const look = paused ? PAUSED_LOOK : trigger.status === 'error' ? CANT_FIRE_LOOK : null;
    const owner =
        trigger.kind === 'email'
            ? { to: href('resources/inboxes', { inbox: specText(trigger, 'inbox_id') }), label: 'Change on its inbox' }
            : trigger.kind === 'call'
              ? { to: href('resources/phone', { number: specText(trigger, 'phone_number_id') }), label: 'Change on its number' }
              : trigger.kind === 'approval'
                ? { to: href('settings/policy', userId ? { layer: userId } : {}), label: 'Change in approval rules' }
                : null;
    const conversation = specText(trigger, 'conversation');
    const detail = [
        trigger.kind === 'cron' && trigger.lastFiredAt ? (
            <span key="ran">
                Last ran <TimeCell value={trigger.lastFiredAt} />.
            </span>
        ) : null,
        message ? <span key="message">“{message}”</span> : null,
        trigger.kind === 'approval' ? <span key="approval">Once someone approves or declines, it gets a turn in that call&apos;s conversation with the result.</span> : null,
        conversation ? <span key="conversation">Conversation {conversation}</span> : null,
    ].filter(Boolean);
    return (
        <li className="flex items-start gap-3 py-3">
            <kind.Icon aria-label={kind.label} className="mt-[3px] h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex min-w-0 items-baseline justify-between gap-3">
                    <p className="m-0 min-w-0 truncate text-[14px] text-foreground">{triggerTitle(trigger, userId)}</p>
                    <span className="flex shrink-0 items-center gap-2 text-[13px] text-muted-foreground">
                        {look && <StatusPill look={look} />}
                        {trigger.kind === 'cron' && !paused ? (
                            trigger.nextRun ? (
                                <span>
                                    Next <TimeCell value={trigger.nextRun} />
                                </span>
                            ) : null
                        ) : trigger.lastFiredAt ? (
                            <span>
                                Fired <TimeCell value={trigger.lastFiredAt} />
                            </span>
                        ) : (
                            !look && <span>Not fired yet</span>
                        )}
                    </span>
                </div>
                <div className="flex min-w-0 items-baseline justify-between gap-3 text-[13px] text-muted-foreground">
                    <p className="m-0 min-w-0 truncate">
                        {detail.map((part, i) => (
                            <span key={i}>
                                {i > 0 && ' '}
                                {part}
                            </span>
                        ))}
                    </p>
                    {owner ? (
                        <Link to={owner.to} className="shrink-0 text-[12px] underline-offset-2 transition-colors hover:text-foreground hover:underline">
                            {owner.label}
                        </Link>
                    ) : (
                        trigger.defined && (
                            <button type="button" onClick={() => onRemove(trigger)} className="shrink-0 text-[12px] underline-offset-2 transition-colors hover:text-foreground hover:underline">
                                Remove
                            </button>
                        )
                    )}
                </div>
                {trigger.url && (
                    <span className="flex min-w-0 items-center gap-1" title={trigger.url}>
                        <span className="truncate text-[12px] text-foreground/80">{trigger.url}</span>
                        <CopyButton value={trigger.url} label="Copy webhook URL" />
                    </span>
                )}
                {trigger.error && !paused && <span className="text-[13px] text-red-600 dark:text-red-400">{trigger.error}</span>}
            </div>
        </li>
    );
}

type TriggerKindChoice = 'cron' | 'webhook' | 'event' | 'platform' | 'queue';

/** At most this many waiting messages make one queue turn. */
const MAX_BATCH = 25;

function AddTriggerDialog({ agent, onAdded, onClose }: { agent: Agent; onAdded: (t: AgentTrigger) => void; onClose: () => void }) {
    const { client } = useConsole();
    const connections = useScopeConnections(agent.userId);
    const catalog = useIntegrations();
    // A model provider's connection has no app events, so the API refuses a trigger on one: the catalog says which they are.
    const models = modelIntegrationNames(catalog.data);
    const hearing = connections.data && models ? connections.data.filter((c) => !models.has(c.integration)) : undefined;
    const [kind, setKind] = useState<TriggerKindChoice>('cron');
    const [cron, setCron] = useState('0 8 * * 1-5');
    const [tz, setTz] = useState('UTC');
    const [name, setName] = useState('');
    const [connection, setConnection] = useState('');
    const [event, setEvent] = useState('');
    const [filter, setFilter] = useState('');
    const [queue, setQueue] = useState('');
    const [batch, setBatch] = useState('1');
    const [conversation, setConversation] = useState('');
    const [message, setMessage] = useState('');
    // A queue trigger reads a queue in the agent's own scope.
    const queues = useV1(kind === 'queue' ? `queues?scope=${agent.userId ?? NO_USER}` : null, () => Queue.list({ client, userFilter: agent.userId ?? NO_USER }));
    // The picked connection's app events, from its integration's catalog. It's held by the ref a trigger names it by:
    // an account connected in the app by `credential:<id>`, never its name.
    const picked = (hearing ?? []).find((c) => refFor(c) === connection);
    const events = useV1(kind === 'event' && picked?.integration ? `integrations/${picked.integration}/events` : null, () => picked!.events());
    const eventInfo = events.data?.find((e) => e.name === event.trim());
    // NoClick's own events, from the catalog, the ones it sends today.
    const [eventType, setEventType] = useState('');
    const eventTypes = useV1(kind === 'platform' ? 'events/types' : null, () => NoClickEvent.types({ client }));
    const batchSize = Number(batch);
    const batchOk = Number.isInteger(batchSize) && batchSize >= 1 && batchSize <= MAX_BATCH;
    // A conversation key comes from one delivery, so a batch of queue messages can't take one.
    const keyed = conversation.trim() && !(kind === 'queue' && batchSize !== 1) ? { conversation: conversation.trim() } : {};
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const preview = kind === 'cron' ? describeCron(cron, tz.trim() || 'UTC') : null;
    const filterPair = /^\s*([\w.-]+)\s*=\s*(.+?)\s*$/.exec(filter);
    const ready =
        kind === 'cron'
            ? cron.trim().split(/\s+/).length === 5
            : kind === 'webhook'
              ? !!name.trim()
              : kind === 'queue'
                ? !!queue && batchOk
                : kind === 'platform'
                  ? !!eventType && (!filter.trim() || !!filterPair)
                  : !!connection && !!event.trim() && (!filter.trim() || !!filterPair);
    const definition = () => {
        const options = message.trim() ? { message: message.trim() } : {};
        if (kind === 'cron') return new Cron(cron.trim(), { tz: tz.trim() || 'UTC', ...options });
        if (kind === 'webhook') return new OnWebhook(name.trim(), { ...options, ...keyed });
        if (kind === 'queue') return new OnQueue(queue, { batchSize, ...options, ...keyed });
        if (kind === 'platform') return new OnPlatformEvent(eventType, { ...(filterPair ? { filters: { [filterPair[1]]: filterPair[2] } } : {}), ...options, ...keyed });
        return new OnEvent(connection, event.trim(), { filters: filterPair ? { [filterPair[1]]: filterPair[2] } : {}, ...options, ...keyed });
    };
    const add = async () => {
        setSaving(true);
        setError(undefined);
        try {
            onAdded(await agent.addTrigger(definition()));
            toast.success(kind === 'webhook' ? 'Webhook added: copy its URL from the list' : 'Trigger added');
            onClose();
        } catch (err) {
            setError(err);
        } finally {
            setSaving(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            title="Add a trigger"
            description={`What wakes ${agent.name} besides a message. Mail and calls are set on an inbox or a phone number.`}
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="primary" onClick={() => void add()} disabled={saving || !ready}>
                        {saving ? 'Adding…' : 'Add trigger'}
                    </ConsoleButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <Segmented
                    label="Kind"
                    value={kind}
                    onChange={setKind}
                    options={[
                        { value: 'cron', label: 'Schedule' },
                        { value: 'webhook', label: 'Webhook' },
                        { value: 'event', label: 'App event' },
                        { value: 'platform', label: 'NoClick event' },
                        { value: 'queue', label: 'Queue' },
                    ]}
                    className="self-start"
                />
                {kind === 'cron' && (
                    <>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_12rem]">
                            <FormField label="Cron expression" hint="Minute, hour, day of month, month, day of week.">
                                <input value={cron} onChange={(e) => setCron(e.target.value)} className={cn(inputClass, 'font-mono')} placeholder="0 8 * * 1-5" />
                            </FormField>
                            <FormField label="Timezone">
                                <input value={tz} onChange={(e) => setTz(e.target.value)} className={inputClass} placeholder="Europe/London" />
                            </FormField>
                        </div>
                        <p className="m-0 text-[13px] text-foreground/85">{preview ?? <span className="text-muted-foreground">Runs on this expression; check it has five fields.</span>}</p>
                    </>
                )}
                {kind === 'webhook' && (
                    <FormField label="Name" hint="It gets a URL; each POST to it is a turn, its body the message.">
                        <input value={name} onChange={(e) => setName(e.target.value)} className={cn(inputClass, 'font-mono')} placeholder="orders" />
                    </FormField>
                )}
                {kind === 'event' && (
                    <>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                            <FormField label="Connection">
                                <select value={connection} onChange={(e) => setConnection(e.target.value)} className={inputClass}>
                                    <option value="">
                                        {hearing
                                            ? hearing.length
                                                ? 'Pick one'
                                                : 'No app connections in its scope'
                                            : connections.error !== undefined || catalog.error !== undefined
                                              ? "Couldn't load the connections"
                                              : 'Loading…'}
                                    </option>
                                    {(hearing ?? []).map((c) => (
                                        <option key={c.id} value={refFor(c)}>
                                            {c.name}
                                        </option>
                                    ))}
                                </select>
                            </FormField>
                            <FormField label="Event">
                                {events.data?.length ? (
                                    <select value={event} onChange={(e) => setEvent(e.target.value)} className={cn(inputClass, 'font-mono')}>
                                        <option value="">Pick one</option>
                                        {events.data.map((e) => (
                                            <option key={e.name} value={e.name}>
                                                {e.name}
                                            </option>
                                        ))}
                                    </select>
                                ) : (
                                    <input value={event} onChange={(e) => setEvent(e.target.value)} className={cn(inputClass, 'font-mono')} placeholder="channel_message" />
                                )}
                            </FormField>
                        </div>
                        <FormField
                            label="Only when (optional)"
                            hint={
                                eventInfo && Object.keys(eventInfo.filters).length
                                    ? `One filter as key=value. It takes: ${Object.entries(eventInfo.filters).map(([k, v]) => `${k} (${v})`).join('; ')}`
                                    : 'One filter as key=value, like channel=C0123ABCD.'
                            }
                        >
                            <input value={filter} onChange={(e) => setFilter(e.target.value)} className={cn(inputClass, 'font-mono')} placeholder="channel=C0123ABCD" />
                        </FormField>
                    </>
                )}
                {kind === 'platform' && (
                    <>
                        <FormField label="Event" hint="Its user's events; an account agent hears every event, its users' included, never its own turns'.">
                            <select value={eventType} onChange={(e) => setEventType(e.target.value)} className={cn(inputClass, 'font-mono')}>
                                <option value="">{eventTypes.data ? 'Pick one' : eventTypes.error !== undefined ? "Couldn't load the events" : 'Loading…'}</option>
                                {(eventTypes.data ?? [])
                                    .filter((t) => t.emitted)
                                    .map((t) => (
                                        <option key={t.name} value={t.name}>
                                            {t.name}
                                        </option>
                                    ))}
                            </select>
                        </FormField>
                        <FormField label="Only when (optional)" hint="One filter on the event's data as path=value, like kind=agent.task.">
                            <input value={filter} onChange={(e) => setFilter(e.target.value)} className={cn(inputClass, 'font-mono')} placeholder="kind=agent.task" />
                        </FormField>
                    </>
                )}
                {kind === 'queue' && (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_8rem]">
                        <FormField label="Queue" hint="Each message becomes a turn; a turn that fails hands it back.">
                            <select value={queue} onChange={(e) => setQueue(e.target.value)} className={inputClass}>
                                <option value="">{queues.data ? (queues.data.length ? 'Pick one' : 'No queues in its scope') : queues.error !== undefined ? "Couldn't load queues" : 'Loading…'}</option>
                                {(queues.data ?? []).map((q) => (
                                    <option key={q.id} value={q.name}>
                                        {q.name}
                                    </option>
                                ))}
                            </select>
                        </FormField>
                        <FormField label="Messages a turn" hint={`1 to ${MAX_BATCH}.`}>
                            <input value={batch} onChange={(e) => setBatch(e.target.value)} inputMode="numeric" className={cn(inputClass, 'tabular-nums')} />
                        </FormField>
                    </div>
                )}
                {kind !== 'cron' && (
                    <FormField
                        label="Conversation (optional)"
                        hint={
                            kind === 'queue' && batchSize !== 1
                                ? 'One message a turn only: a batch holds several.'
                                : 'A template over what arrives: deliveries with the same key continue one conversation.'
                        }
                    >
                        <input
                            value={conversation}
                            onChange={(e) => setConversation(e.target.value)}
                            disabled={kind === 'queue' && batchSize !== 1}
                            className={cn(inputClass, 'font-mono')}
                            placeholder={kind === 'event' ? 'issue-{issue.number}' : kind === 'platform' ? 'connection-{data.id}' : 'order-{order_id}'}
                        />
                    </FormField>
                )}
                <FormField label="Message (optional)" hint="What it's told each time it wakes, above what arrived.">
                    <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={2} className={cn(inputClass, 'h-auto py-2 leading-relaxed')} />
                </FormField>
                {error !== undefined && <ErrorPanel error={error} />}
            </div>
        </ConsoleDialog>
    );
}

function RemoveTriggerDialog({ agent, trigger, onRemoved, onClose }: { agent: Agent; trigger: AgentTrigger; onRemoved: (t: AgentTrigger) => void; onClose: () => void }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const remove = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await agent.removeTrigger(trigger);
            onRemoved(trigger);
            toast.success('Trigger removed');
            onClose();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="sm"
            title="Remove this trigger?"
            description={
                trigger.kind === 'webhook'
                    ? 'Its URL stops answering at once. Adding a webhook back gives it a new URL.'
                    : `It stops waking ${agent.name}. Code that defines ${agent.name} with this trigger adds it back when it next runs.`
            }
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="danger" onClick={() => void remove()} disabled={busy}>
                        {busy ? 'Removing…' : 'Remove trigger'}
                    </ConsoleButton>
                </>
            }
        >
            {error !== undefined && <ErrorPanel error={error} />}
        </ConsoleDialog>
    );
}

/** What wakes it besides a message, and the switch that stops all of it. */
function Triggers({ agent, onSaved }: { agent: Agent; onSaved: (agent: Agent) => void }) {
    const key = `agents/${agent.id}/triggers`;
    const triggers = useV1(key, () => agent.triggers());
    const [adding, setAdding] = useState(false);
    const [removing, setRemoving] = useState<AgentTrigger | null>(null);
    const [switching, setSwitching] = useState(false);
    const rows = triggers.data ?? [];
    const toggle = async () => {
        setSwitching(true);
        try {
            onSaved(await (agent.paused ? agent.resume() : agent.pause()));
            invalidateV1('agents?');
            toast.success(agent.paused ? `Paused ${agent.name}` : `${agent.name} wakes on its triggers again`);
        } catch (err) {
            toast.error(err instanceof Error ? err.message : String(err), { description: err instanceof NoClickError ? (err.nextStep ?? undefined) : undefined });
        } finally {
            setSwitching(false);
        }
    };
    return (
        <PageSection
            title="Triggers"
            count={rows.length}
            note={
                agent.paused
                    ? 'Paused: no trigger wakes it until you resume. Scheduled runs are skipped, webhook calls are refused with 409, and messages from your code still run.'
                    : undefined
            }
            right={
                <>
                    {rows.length > 0 && agent.status !== 'expired' && (
                        <ConsoleButton size="sm" variant="ghost" icon={agent.paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />} onClick={() => void toggle()} disabled={switching}>
                            {agent.paused ? 'Resume' : 'Pause'}
                        </ConsoleButton>
                    )}
                    {agent.status !== 'expired' && (
                        <ConsoleButton size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setAdding(true)}>
                            Add trigger
                        </ConsoleButton>
                    )}
                </>
            }
        >
            {triggers.error !== undefined && !triggers.data ? (
                <ErrorPanel error={triggers.error} onRetry={() => void triggers.refresh()} />
            ) : !triggers.data ? (
                <div aria-busy className="h-14 animate-pulse rounded-lg bg-foreground/[0.03]" />
            ) : rows.length ? (
                <ul aria-label="Triggers" className={'m-0 list-none p-0'}>
                    {rows.map((t) => (
                        <TriggerRow key={t.id} trigger={t} paused={agent.paused} userId={agent.userId} onRemove={setRemoving} />
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">
                    {'Only messages wake it. A schedule makes it an automation; a webhook gives your systems a URL to wake it at; an app event wakes it on a Slack message or a new contact; a queue hands it work one message at a time.'}
                </p>
            )}
            {adding && <AddTriggerDialog agent={agent} onAdded={(t) => triggers.mutate([...rows, t])} onClose={() => setAdding(false)} />}
            {removing && (
                <RemoveTriggerDialog agent={agent} trigger={removing} onRemoved={(t) => triggers.mutate(rows.filter((r) => r.id !== t.id))} onClose={() => setRemoving(null)} />
            )}
        </PageSection>
    );
}

// ── memory

const WHO_CHANGED: Record<string, string> = { agent: 'The agent', api: 'Your code', console: 'You' };

/** A memory route as the account, naming the layer by `user_id` (`none`: the account's) so a suspended user's still loads. */
async function memoryCall<T>(
    client: ReturnType<typeof useConsole>['client'],
    agent: Agent,
    layer: string | null,
    method: string,
    name: string | null,
    options: { json?: unknown; query?: Record<string, string | number | undefined> } = {},
): Promise<T> {
    const path = `/v1/agents/${encodeURIComponent(agent.id)}/memory${name === null ? '' : `/${encodeURIComponent(name)}`}`;
    return await client.request<T>(method, path, { ...options, query: { ...options.query, user_id: layer ?? 'none' }, user: null });
}

function MemoryEditor({
    agent,
    layer,
    entry,
    onSaved,
    onCancel,
}: {
    agent: Agent;
    /** The layer's user (null: the account's). */
    layer: string | null;
    /** The entry being edited, or null for a new one. */
    entry: MemoryEntry | null;
    onSaved: (entry: MemoryEntry) => void;
    onCancel: () => void;
}) {
    const { client } = useConsole();
    const [name, setName] = useState(entry?.name ?? '');
    const [description, setDescription] = useState(entry?.description ?? '');
    const [content, setContent] = useState(entry?.content ?? '');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const save = async () => {
        setSaving(true);
        setError(undefined);
        try {
            const saved = toMemoryEntry(
                await memoryCall<JsonObject>(client, agent, layer, 'PUT', entry ? entry.name : name.trim(), {
                    // Only lands if the agent hasn't changed it since it was opened.
                    json: { content, description: description.trim() || undefined, version: entry?.version },
                }),
            );
            toast.success(`Saved ${saved.name}`);
            onSaved(saved);
        } catch (err) {
            setError(err);
        } finally {
            setSaving(false);
        }
    };
    const stale = error instanceof NoClickError && error.type === 'conflict';
    return (
        <div className="flex flex-col gap-3">
            {!entry && (
                <FormField label="Name" hint="Lowercase letters, digits, dots, dashes and underscores.">
                    <input value={name} onChange={(e) => setName(e.target.value)} className={cn(inputClass, 'font-mono')} placeholder="refunds" />
                </FormField>
            )}
            <FormField label="Description" hint="The line the agent sees every turn: say what the entry holds.">
                <input value={description} onChange={(e) => setDescription(e.target.value)} className={inputClass} placeholder="Our refund rules" />
            </FormField>
            <FormField label="Content">
                <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={8} className={cn(inputClass, 'h-auto py-2 font-mono text-[13px] leading-relaxed')} />
            </FormField>
            {stale ? (
                <p role="alert" className="m-0 text-[13px] text-red-600 dark:text-red-400">
                    The agent changed this entry since you opened it. Close it and open it again to edit what is there now.
                </p>
            ) : (
                error !== undefined && <ErrorPanel error={error} />
            )}
            <div className="flex gap-1.5">
                <ConsoleButton size="sm" variant="primary" onClick={() => void save()} disabled={saving || stale || (!entry && (!name.trim() || !description.trim()))}>
                    {saving ? 'Saving…' : entry ? 'Save' : 'Save entry'}
                </ConsoleButton>
                <ConsoleButton size="sm" variant="ghost" onClick={onCancel}>
                    Cancel
                </ConsoleButton>
            </div>
        </div>
    );
}

function MemoryDrawer({
    agent,
    layer,
    name,
    onChanged,
    onClose,
}: {
    agent: Agent;
    layer: string | null;
    name: string;
    onChanged: (entry: MemoryEntry | null, name: string) => void;
    onClose: () => void;
}) {
    const { client } = useConsole();
    const read = useV1(`agents/${agent.id}/memory/${layer ?? 'account'}/${name}`, async () => toMemoryEntry(await memoryCall<JsonObject>(client, agent, layer, 'GET', name)));
    const [editing, setEditing] = useState(false);
    const [forgetting, setForgetting] = useState(false);
    const [busy, setBusy] = useState(false);
    const reportHeld = useReportHeld(useConsole());
    const entry = read.data;
    const forget = async () => {
        if (!entry) return;
        setBusy(true);
        try {
            await memoryCall(client, agent, layer, 'DELETE', entry.name, { query: { version: entry.version } });
            toast.success(`${agent.name} forgot ${entry.name}`);
            onChanged(null, entry.name);
            onClose();
        } catch (err) {
            if (reportHeld(err, `${agent.name} forgets ${entry.name}`, () => onChanged(null, entry.name))) return onClose();
            toast.error(err instanceof Error ? err.message : String(err), { description: err instanceof NoClickError ? (err.nextStep ?? undefined) : undefined });
        } finally {
            setBusy(false);
            setForgetting(false);
        }
    };
    return (
        <Drawer
            open
            onOpenChange={(o) => !o && onClose()}
            kind="Memory entry"
            title={<span className="font-mono text-[14px]">{name}</span>}
            status={entry && <span className="text-[12px] tabular-nums text-muted-foreground">version {entry.version}</span>}
            footer={
                entry && !editing ? (
                    <>
                        <ConsoleButton size="sm" onClick={() => setEditing(true)}>
                            Edit
                        </ConsoleButton>
                        <ConsoleButton size="sm" variant="danger" onClick={() => setForgetting(true)}>
                            Forget
                        </ConsoleButton>
                    </>
                ) : undefined
            }
        >
            {read.error !== undefined && !entry ? (
                <ErrorPanel error={read.error} onRetry={() => void read.refresh()} />
            ) : !entry ? (
                <div aria-busy className="h-32 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : editing ? (
                <MemoryEditor
                    agent={agent}
                    layer={layer}
                    entry={entry}
                    onSaved={(saved) => {
                        read.mutate(saved);
                        onChanged(saved, saved.name);
                        setEditing(false);
                    }}
                    onCancel={() => setEditing(false)}
                />
            ) : (
                <div className="flex flex-col gap-4">
                    <p className="m-0 text-[14px] text-foreground">{entry.description}</p>
                    <pre aria-label="Content" className={cn('m-0 whitespace-pre-wrap break-words rounded-lg border bg-foreground/[0.03] px-3 py-2.5 font-mono text-[13px] leading-relaxed text-foreground/90', HAIRLINE)}>
                        {entry.content || '(empty)'}
                    </pre>
                    <p className="m-0 text-[12px] text-muted-foreground">
                        {WHO_CHANGED[entry.updatedBy ?? ''] ?? 'Changed'} changed it <TimeCell value={entry.updatedAt} />.
                    </p>
                </div>
            )}
            {forgetting && entry && (
                <ConsoleDialog
                    open
                    onOpenChange={(o) => !o && setForgetting(false)}
                    size="sm"
                    title={`Forget ${entry.name}?`}
                    description="The agent stops seeing it from its next turn. It can save the name again later."
                    footer={
                        <>
                            <ConsoleButton variant="ghost" onClick={() => setForgetting(false)}>
                                Cancel
                            </ConsoleButton>
                            <ConsoleButton variant="danger" onClick={() => void forget()} disabled={busy}>
                                {busy ? 'Forgetting…' : 'Forget entry'}
                            </ConsoleButton>
                        </>
                    }
                />
            )}
        </Drawer>
    );
}

const ACCOUNT_LAYER = 'account';

/** Named notes it keeps across conversations: an account agent's shared layer, or one user's. */
function Memory({ agent }: { agent: Agent }) {
    const { client } = useConsole();
    const users = useUsers();
    const [layerParam, setLayerParam] = useSearchParam('memlayer');
    const [open, setOpen] = useSearchParam('mem');
    const [creating, setCreating] = useState(false);
    // A user's own agent has one layer, its user's; an account agent's is picked.
    const layerId = agent.userId ? null : layerParam && layerParam !== ACCOUNT_LAYER ? layerParam : null;
    const layer = agent.userId ?? layerId;
    const key = `agents/${agent.id}/memory?layer=${layer ?? ACCOUNT_LAYER}`;
    const memory = useV1(key, async () => ((await memoryCall<{ data?: JsonObject[] }>(client, agent, layer, 'GET', null)).data ?? []).map(toMemoryEntry));
    const rows = memory.data ?? [];
    const upsert = (entry: MemoryEntry | null, name: string) => {
        const rest = rows.filter((e) => e.name !== name);
        memory.mutate(entry ? [...rest, { ...entry, content: null }].sort((a, b) => a.name.localeCompare(b.name)) : rest);
    };
    const columns: Column<MemoryEntry>[] = [
        {
            id: 'name',
            header: 'Entry',
            cell: (e) => (
                <span className="flex min-w-0 flex-col">
                    <span className="truncate font-mono text-[13px] text-foreground">{e.name}</span>
                    <span className="truncate text-[12px] text-muted-foreground">{e.description}</span>
                </span>
            ),
        },
        { id: 'by', header: 'Changed by', priority: 2, width: '8rem', cell: (e) => <span className="text-muted-foreground">{WHO_CHANGED[e.updatedBy ?? ''] ?? '—'}</span> },
        { id: 'version', header: 'Version', priority: 3, align: 'right', width: '4.5rem', cell: (e) => <span className="tabular-nums">{e.version}</span> },
        { id: 'updated', header: 'Changed', priority: 2, width: '7rem', cell: (e) => <TimeCell value={e.updatedAt} /> },
    ];
    const layers = [{ value: ACCOUNT_LAYER, label: 'Account' }, ...users.map((u) => ({ value: u.id, label: u.id }))];
    return (
        <PageSection
            title="Memory"
            count={rows.length}
            note={
                agent.userId
                    ? 'Named notes it keeps across conversations. Every turn starts with each name and description; it reads a note when it needs it.'
                    : 'Named notes it keeps across conversations. The account’s notes are read in every user’s conversations; what it learns from a user stays in notes of that user’s own.'
            }
            right={
                <>
                    {!agent.userId && (
                        <FacetSelect
                            label="Notes of"
                            value={layerId ?? ACCOUNT_LAYER}
                            options={layers}
                            anyLabel={null}
                            onChange={(v) => setLayerParam(v === ACCOUNT_LAYER ? null : v)}
                        />
                    )}
                    <ConsoleButton size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setCreating(true)}>
                        New entry
                    </ConsoleButton>
                </>
            }
        >
            <DataTable
                label="Memory"
                columns={columns}
                rows={rows}
                getRowId={(e) => e.name}
                loading={memory.loading}
                error={memory.error}
                onRetry={() => void memory.refresh()}
                empty={<p className="m-0 py-6 text-center text-[13px] text-muted-foreground">Nothing remembered here yet. The agent saves what it learns; you can seed notes too.</p>}
                selectedId={open}
                onRowClick={(e) => setOpen(e.name, { push: true })}
                skeletonRows={3}
            />
            {open && <MemoryDrawer key={`${layerId ?? ''}:${open}`} agent={agent} layer={layer} name={open} onChanged={upsert} onClose={() => setOpen(null)} />}
            {creating && (
                <ConsoleDialog open onOpenChange={(o) => !o && setCreating(false)} title="New memory entry" description={`${agent.name} sees its name and description from its next turn.`} size="lg">
                    <MemoryEditor
                        agent={agent}
                        layer={layer}
                        entry={null}
                        onSaved={(saved) => {
                            upsert(saved, saved.name);
                            setCreating(false);
                        }}
                        onCancel={() => setCreating(false)}
                    />
                </ConsoleDialog>
            )}
        </PageSection>
    );
}

// ── workspace files (in the conversation drawer)

/** What the agent worked on in one conversation, under `/workspace`. */
function WorkspaceFiles({ agent, userId, conversation }: { agent: Agent; userId: string | null; conversation: string }) {
    const files = useV1(`agents/${agent.id}/workspace/${userId ?? 'none'}/${conversation}`, () => agent.workspace(conversation, { user: userId }).files());
    return (
        <section aria-label="Workspace files" className={cn('mt-6 border-t pt-4', HAIRLINE)}>
            <h3 className="m-0 mb-1 text-[14px] font-semibold tracking-[-0.01em] text-foreground">Workspace files</h3>
            <p className="m-0 mb-2 text-[12px] text-muted-foreground">What it wrote under /workspace in this conversation. Links work for an hour.</p>
            {files.error !== undefined && !files.data ? (
                <ErrorPanel error={files.error} onRetry={() => void files.refresh()} />
            ) : !files.data ? (
                <div aria-busy className="h-12 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : files.data.length ? (
                <ul aria-label="Files" className={'m-0 list-none p-0'}>
                    {files.data.map((f) => (
                        <li key={f.path} className="flex items-center gap-3 py-2 text-[13px]">
                            <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-foreground" title={f.path}>
                                {f.path}
                            </span>
                            <span className="shrink-0 tabular-nums text-[12px] text-muted-foreground">{fmtBytes(f.sizeBytes)}</span>
                            <TimeCell value={f.modifiedAt} className="hidden shrink-0 text-[12px] text-muted-foreground sm:inline" />
                            {f.url && (
                                <a
                                    href={f.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    aria-label={`Download ${f.path}`}
                                    title="Download"
                                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-foreground/[0.08] hover:text-foreground"
                                >
                                    <Download className="h-3.5 w-3.5" />
                                </a>
                            )}
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">No files in this conversation.</p>
            )}
        </section>
    );
}

// ── share link

/** Its public chat page: off, on at a URL (copy, rotate, turn off), or off at a URL it keeps. */
function ShareLinkSection({ agent }: { agent: Agent }) {
    const key = `agents/${agent.id}/share`;
    const read = useV1(key, () => agent.shareLink());
    const [busy, setBusy] = useState<'on' | 'off' | 'rotate' | null>(null);
    const [rotating, setRotating] = useState(false);
    const link = read.data;
    const act = async (what: 'on' | 'off' | 'rotate') => {
        setBusy(what);
        try {
            // Turning on is `share()`; an on link is its own for the rest.
            const on = what === 'on' || !link ? await agent.share() : link;
            read.mutate(what === 'off' ? await on.disable() : what === 'rotate' ? await on.rotate() : on);
            toast.success(what === 'on' ? 'Share link on' : what === 'off' ? 'Share link off' : 'New link made; the old one stopped');
        } catch (err) {
            toast.error(err instanceof Error ? err.message : String(err), { description: err instanceof NoClickError ? (err.nextStep ?? undefined) : undefined });
        } finally {
            setBusy(null);
            setRotating(false);
        }
    };
    return (
        <AsideSection title="Share link">
            {read.error !== undefined && read.data === undefined ? (
                <ErrorPanel error={read.error} onRetry={() => void read.refresh()} className="bg-transparent" />
            ) : read.data === undefined ? (
                <div aria-busy className="h-10 animate-pulse rounded-lg bg-foreground/[0.03]" />
            ) : link?.enabled ? (
                <div className="flex flex-col gap-2">
                    <span className="flex min-w-0 items-center gap-1" title={link.url}>
                        <span className="truncate text-[13px] text-foreground">{link.url.replace(/^https:\/\//, '')}</span>
                        <CopyButton value={link.url} label="Copy share link" />
                    </span>
                    <p className="m-0 text-[12px] text-muted-foreground">
                        Anyone with the link talks to it, no sign-in, each in their own conversations. Their turns bill to you.
                        {link.rotatedAt ? (
                            <>
                                {' '}
                                New link <TimeCell value={link.rotatedAt} />.
                            </>
                        ) : (
                            <>
                                {' '}
                                On since <TimeCell value={link.createdAt} />.
                            </>
                        )}
                    </p>
                    <div className="flex gap-1.5">
                        <ConsoleButton size="sm" variant="ghost" onClick={() => setRotating(true)} disabled={busy !== null}>
                            Rotate
                        </ConsoleButton>
                        <ConsoleButton size="sm" variant="ghost" onClick={() => void act('off')} disabled={busy !== null}>
                            {busy === 'off' ? 'Turning off…' : 'Turn off'}
                        </ConsoleButton>
                    </div>
                </div>
            ) : (
                <div className="flex flex-col gap-2">
                    <p className="m-0 text-[13px] text-muted-foreground">
                        {link
                            ? `Off. Its link shows visitors that ${agent.name} isn't available.`
                            : 'Off. A public page where anyone with the link talks to it, no sign-in; their turns bill to you.'}
                    </p>
                    <ConsoleButton size="sm" className="self-start" onClick={() => void act('on')} disabled={busy !== null}>
                        {busy === 'on' ? 'Turning on…' : 'Turn on'}
                    </ConsoleButton>
                </div>
            )}
            {rotating && (
                <ConsoleDialog
                    open
                    onOpenChange={(o) => !o && setRotating(false)}
                    size="sm"
                    title="Give it a new link?"
                    description="The current link stops working at once; conversations visitors already had stay yours to read."
                    footer={
                        <>
                            <ConsoleButton variant="ghost" onClick={() => setRotating(false)}>
                                Cancel
                            </ConsoleButton>
                            <ConsoleButton variant="danger" onClick={() => void act('rotate')} disabled={busy !== null}>
                                {busy === 'rotate' ? 'Rotating…' : 'Rotate link'}
                            </ConsoleButton>
                        </>
                    }
                />
            )}
        </AsideSection>
    );
}

// ── test runs

/** A compact one-line JSON for an argument list. */
const inlineJson = (value: unknown) => (value === undefined ? '' : JSON.stringify(value));

function RehearsalResult({ run }: { run: Rehearsal }) {
    const href = useConsoleHref();
    return (
        <div className={cn('mt-4 flex flex-col gap-3 rounded-xl border bg-card px-4 py-3.5', HAIRLINE)}>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-md bg-foreground/[0.05] px-1.5 py-[2px] text-[12px] font-medium text-muted-foreground">
                    <FlaskConical className="h-3.5 w-3.5" />
                    Simulated, nothing was sent
                </span>
                <span className="flex items-center gap-3 text-[12px] text-muted-foreground">
                    {run.costUsd !== null && (
                        <span>
                            Cost <Money usd={run.costUsd} full />
                        </span>
                    )}
                    {run.operationId && (
                        <Link to={href('logs', { op: run.operationId })} className="underline underline-offset-2 hover:text-foreground">
                            View operation
                        </Link>
                    )}
                </span>
            </div>
            {run.scenario && <p className="m-0 text-[13px] text-muted-foreground">Scenario: {run.scenario}</p>}
            <p className="m-0 whitespace-pre-wrap text-sm text-foreground">{run.reply}</p>
            {run.toolCalls.length > 0 && (
                <div>
                    <h3 className="m-0 mb-1.5 text-[14px] font-semibold tracking-[-0.01em] text-foreground">
                        {plural(run.toolCalls.length, 'tool call')}, each answered by the simulated world
                    </h3>
                    <ol aria-label="Simulated tool calls" className={'m-0 list-none p-0'}>
                        {run.toolCalls.map((call, i) => (
                            <li key={i} className="flex flex-col gap-1 py-2">
                                <span className="flex items-baseline justify-between gap-2">
                                    <span className="font-mono text-[13px] text-foreground">{dottedTool(String(call.tool ?? ''))}</span>
                                    <span className="shrink-0 text-[12px] text-muted-foreground">simulated</span>
                                </span>
                                <span className="truncate font-mono text-[12px] text-muted-foreground" title={inlineJson(call.arguments)}>
                                    {inlineJson(call.arguments)}
                                </span>
                                <details className="text-[12px]">
                                    <summary className="cursor-pointer text-muted-foreground">What the world answered</summary>
                                    <JsonView value={call.result} className="mt-1.5" />
                                </details>
                            </li>
                        ))}
                    </ol>
                </div>
            )}
        </div>
    );
}

/** A real turn of the agent where a simulated world answers every tool call. */
function TestRuns({ agent }: { agent: Agent }) {
    const href = useConsoleHref();
    const [message, setMessage] = useState('');
    const [scenario, setScenario] = useState('');
    const [running, setRunning] = useState(false);
    const [run, setRun] = useState<Rehearsal | null>(null);
    const [error, setError] = useState<unknown>(undefined);
    const rehearse = async () => {
        setRunning(true);
        setError(undefined);
        setRun(null);
        try {
            const op = await agent.rehearse(message.trim(), { scenario: scenario.trim() || undefined });
            setRun(await op.wait());
            invalidateV1('operations');
        } catch (err) {
            setError(err);
        } finally {
            setRunning(false);
        }
    };
    return (
        <PageSection
            title="Test runs"
            note="A real turn of the agent, with its model, instructions and tools, where a simulated world answers every tool call. Nothing is sent and no account is touched, so its connections needn't be connected yet."
            right={
                <Link to={href('logs', { q: `kind:agent.rehearse agent:${agent.id}` })} className="text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                    Past runs →
                </Link>
            }
        >
            <form
                className="flex flex-col gap-3"
                onSubmit={(e) => {
                    e.preventDefault();
                    void rehearse();
                }}
            >
                <FormField label="What a user says">
                    <textarea
                        value={message}
                        onChange={(e) => setMessage(e.target.value)}
                        rows={2}
                        className={cn(inputClass, 'h-auto py-2 leading-relaxed')}
                        placeholder="I was charged twice for invoice 1042. Can you fix it?"
                    />
                </FormField>
                <FormField label="Scenario (optional)" hint="What the simulated world is like; its answers keep to it.">
                    <input value={scenario} onChange={(e) => setScenario(e.target.value)} className={inputClass} placeholder="Invoice 1042 was paid twice by card on Sep 2" />
                </FormField>
                <ConsoleButton type="submit" className="self-start" icon={<FlaskConical className="h-3.5 w-3.5" />} disabled={running || !message.trim()}>
                    {running ? 'Running…' : 'Run test'}
                </ConsoleButton>
            </form>
            {error !== undefined && <ErrorPanel error={error} className="mt-4" />}
            {run && <RehearsalResult run={run} />}
        </PageSection>
    );
}

// ── page ───────────────────────────────────────────────────────────────────

function DeleteAgent({ agent, open, onOpenChange }: { agent: Agent; open: boolean; onOpenChange: (open: boolean) => void }) {
    const href = useConsoleHref();
    const navigate = useNavigate();
    const [typed, setTyped] = useState('');
    const [deleting, setDeleting] = useState(false);
    const remove = async () => {
        setDeleting(true);
        try {
            await agent.delete();
            invalidateV1('agents');
            invalidateV1('account');
            toast.success(`Deleted ${agent.name}`);
            onOpenChange(false);
            navigate(href(''));
        } catch (err) {
            toast.error(err instanceof Error ? err.message : String(err), { description: err instanceof NoClickError ? (err.nextStep ?? undefined) : undefined });
        } finally {
            setDeleting(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            size="sm"
            title={`Delete ${agent.name}?`}
            description="Code that messages it by name or id fails from now on. Its conversations and past runs stay readable."
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={() => onOpenChange(false)}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="danger" onClick={() => void remove()} disabled={typed !== agent.name || deleting}>
                        {deleting ? 'Deleting…' : 'Delete agent'}
                    </ConsoleButton>
                </>
            }
        >
            <label className="flex flex-col gap-1.5">
                <span className="text-[12px] text-muted-foreground">
                    Type <span className="font-mono text-foreground">{agent.name}</span> to confirm
                </span>
                <input value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Agent name" className={inputClass} />
            </label>
        </ConsoleDialog>
    );
}

/**
 * An agent's page, one anatomy: Overview says what it's doing now, what it did
 * lately, what wakes it, what it uses and the code that calls it; its
 * conversations and memory have tabs of their own, and Try it holds every way
 * to talk to it from here (a turn, a side question, a test run).
 */
const AGENT_TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'conversations', label: 'Conversations' },
    { id: 'memory', label: 'Memory' },
    { id: 'try', label: 'Try it' },
] as const;
type AgentTab = (typeof AGENT_TABS)[number]['id'];

export default function AgentDetail({ rest }: ConsolePageProps) {
    const id = rest[0];
    const { client } = useConsole();
    const href = useConsoleHref();
    const [params] = useSearchParams();
    const state = useV1(`agents/${id}`, () => Agent.fromId(id, { client, user: null }).hydrate());
    const [deleting, setDeleting] = useState(false);
    const agent = state.data;
    // A conversation or a memory entry opened by link lands on its tab.
    const tab: AgentTab = AGENT_TABS.find((t) => t.id === params.get('tab'))?.id ?? (params.get('conv') ? 'conversations' : params.get('mem') || params.get('memlayer') ? 'memory' : 'overview');

    useEffect(() => {
        if (agent) recordRecent({ type: 'agent', id: agent.id, label: agent.name, path: `agents/${agent.id}` });
    }, [agent?.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const crumbs = [{ label: 'Home', href: href('') }];
    if (!agent) {
        return (
            <div className={DETAIL_PAGE}>
                <PageHeader crumbs={crumbs} title={truncateId(id)} />
                {state.error !== undefined ? <ErrorPanel error={state.error} onRetry={() => void state.refresh()} /> : <div aria-busy className="h-40 animate-pulse rounded-xl bg-foreground/[0.04]" />}
            </div>
        );
    }
    const onSaved = (a: Agent) => state.mutate(a);
    const save = saverFor(agent, onSaved);
    return (
        <div className={DETAIL_PAGE}>
            <PageHeader
                crumbs={crumbs}
                title={agent.name}
                purpose={purposeOf(agent) || undefined}
                chips={
                    <>
                        <AgentLiveChips agent={agent} />
                        {agent.paused && <StatusPill look={{ label: 'Paused', reason: 'no trigger wakes it', glyph: 'hollow', tone: 'muted' }} />}
                    </>
                }
                actions={
                    <MoreMenu
                        label="More actions"
                        items={[
                            { label: 'Copy ID', onSelect: () => void copyId(agent.id) },
                            { label: 'Delete agent', danger: true, separated: true, onSelect: () => setDeleting(true) },
                        ]}
                    />
                }
            />
            <PillTabs
                label={`${agent.name} views`}
                className="-mt-3 mb-8"
                active={tab}
                tabs={AGENT_TABS.map((t) => ({ id: t.id, label: t.label, href: href(`agents/${agent.id}`, t.id === 'overview' ? {} : { tab: t.id }) }))}
            />
            {tab === 'try' ? (
                <>
                    <AgentTryIt agent={agent} />
                    {agent.status !== 'expired' && <AskSection agent={agent} />}
                    <TestRuns agent={agent} />
                </>
            ) : tab === 'conversations' ? (
                <Conversations agent={agent} />
            ) : tab === 'memory' ? (
                <Memory agent={agent} />
            ) : (
                <>
                    <Now agent={agent} save={save} />
                    <TaskSection agent={agent} />
                    <ChildrenSection agent={agent} />
                    {((agent.childCount ?? 0) > 0 || coordinates(agent)) && <JobsSection agent={agent} />}
                    <WakeupsSection agent={agent} />
                    <PageSection title="Recent runs">
                        <OperationsView pinned={`kind:agent.message agent:${agent.id}`} controls={false} limit={6} viewAllHref={href('logs', { q: `kind:agent.message agent:${agent.id}` })} />
                    </PageSection>
                    <Uses agent={agent} onSaved={onSaved} />
                    <Triggers agent={agent} onSaved={onSaved} />
                    <PageSection title="Code" note="Message it from your code. Each user gets their own conversations with it.">
                        <CodeSnippet tabs={snippetTabs(agentCodeSnippet(agent.name, agent.userId))} />
                    </PageSection>
                    <Details agent={agent} save={save} />
                </>
            )}
            {deleting && <DeleteAgent agent={agent} open onOpenChange={setDeleting} />}
        </div>
    );
}
