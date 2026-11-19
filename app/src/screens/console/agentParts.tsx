// What Home and an agent's page share: the tools picker, the harness catalog
// and the model-connection picker, form fields, and this month's spend per
// agent. An agent is made in code, so there is no create form (`NewAgent.tsx`
// shows the code). Kept out of pages/ so no page module imports another.
import { useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Link } from 'react-router';
import { X } from 'lucide-react';
import { HAIRLINE } from '@/ui/primitives';
import { CredentialMark } from '@/ui/connectionMark';
import { cn } from '@/ui/utils';
import { ALL_USERS, Agent, Agents, Bucket, Connection, Database, Usage, type JsonObject, type ModelUsage, type HarnessInfo, type HarnessModel, type IntegrationInfo, type IntegrationOperation, type NoClick } from 'noclick';
import { formatCount, formatMoney } from '@/screens/console/lib/format';
import { useDebounce } from '@/lib/useDebounce';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { LinkShown, connectionLook, integrationNodeType, nameProblem, nodeTypeOf, useIntegrations, useScopeConnections } from './connections';
import { ConsoleButton } from './ui/Button';

/** Tools that aren't connections: the web on NoClick's key, and the agents capability. Every agent also has a shell (`code`), listed or not. */
export const AGENT_CAPABILITIES = [
    { ref: 'search', label: 'Web search' },
    { ref: 'fetch', label: 'Web fetch' },
    { ref: 'agents', label: 'Manage agents' },
] as const;

/** Tool refs that name a capability rather than a connection (`code` still appears on older agents). */
export const CAPABILITY_REFS = new Set<string>(['search', 'fetch', 'code']);

/**
 * A ref that names no connection in its scope reaches the integration of that
 * name, when some of its operations need no account: they run on NoClick's key.
 */
export function accountFreeIntegration(name: string, catalog: readonly IntegrationInfo[] | undefined): IntegrationInfo | undefined {
    return catalog?.find((i) => i.name === name && i.accountFreeOperationCount > 0);
}

/** An integration's operations from the catalog alone: no connection is read or made. */
export function catalogOperations(integration: string, client: NoClick): Promise<IntegrationOperation[]> {
    return Connection.fromName(integration, { integration, client }).operations();
}

/** What such a ref runs: every operation that needs no account, or the one it names if it needs none. */
export function accountFreeOperations(operations: readonly IntegrationOperation[], op: string | null): string[] {
    const free = operations.filter((o) => !o.needsAccount).map((o) => o.name);
    return op ? free.filter((name) => name === op) : free;
}

/** A database in an agent's tools (designed, lab only): `database:<id>`, or `database:<id>.<op>` for one operation. */
const DATABASE_REF = /^database:([^.]+)(?:\.(\w+))?$/;
export const databaseRef = (id: string) => `database:${id}`;
export function databaseRefOf(ref: string): { id: string; op: string | null } | null {
    const match = DATABASE_REF.exec(ref);
    return match ? { id: match[1], op: match[2] ?? null } : null;
}

/** The databases an agent in this scope may use: its user's and the account's. Read only in the lab. */
export function useScopeDatabases(user: string | null) {
    const { client, lab } = useConsole();
    const all = useV1(lab ? 'databases?agent-tools' : null, () => Database.list({ client, userFilter: ALL_USERS, limit: 100 }));
    return { error: all.error, data: all.data?.filter((d) => d.userId === null || d.userId === user) };
}

/** A connection from another scope in an agent's tools (designed, lab only): `connection:<id>`, or `connection:<id>.<op>`. */
const SHARED_REF = /^connection:([^.]+)(?:\.(\w+))?$/;
export const sharedConnectionRef = (id: string) => `connection:${id}`;
export function sharedConnectionOf(ref: string): { id: string; op: string | null } | null {
    const match = SHARED_REF.exec(ref);
    return match ? { id: match[1], op: match[2] ?? null } : null;
}

/** Connections outside an agent's scope it could be given: other users' and, for a user's agent, the account's. Lab only. */
export function useOtherScopeConnections(user: string | null, enabled = true) {
    const { client, lab } = useConsole();
    const all = useV1(lab && enabled ? 'connections?all-scopes' : null, () => Connection.list({ client, userFilter: ALL_USERS, limit: 100 }));
    return { error: all.error, data: all.data?.filter((c) => c.userId !== user) };
}

/** Where a shared connection comes from, in a few words: `acme`, or `your account`. */
export function scopeName(userId: string | null): string {
    return userId ?? 'your account';
}

/** A bucket in an agent's tools: `bucket:<id>`, or `bucket:<id>.<op>`. */
const BUCKET_REF = /^bucket:([^.]+)(?:\.(\w+))?$/;
export function bucketRefOf(ref: string): { id: string; op: string | null } | null {
    const match = BUCKET_REF.exec(ref);
    return match ? { id: match[1], op: match[2] ?? null } : null;
}

/**
 * The `agents` capability in an agent's tools: `agents` is all six of its tools (spawn, message,
 * ask, status, list, cancel), `agents.<tool>` one. Null for any other ref.
 */
export function agentsToolsOf(ref: string): string[] | null {
    if (ref === 'agents') return [...Agents.TOOLS];
    const match = /^agents\.(\w+)$/.exec(ref);
    return match && (Agents.TOOLS as readonly string[]).includes(match[1]) ? [match[1]] : null;
}

/** The buckets an agent in this scope may use: its user's and the account's. */
export function useScopeBuckets(user: string | null, enabled = true) {
    const { client } = useConsole();
    const all = useV1(enabled ? 'buckets?agent-tools' : null, () => Bucket.list({ client, userFilter: ALL_USERS, limit: 100 }));
    return { error: all.error, data: all.data?.filter((b) => b.userId === null || b.userId === user) };
}

/** One entry of an agent's or MCP server's tools: a ref, or an object for what a ref can't say. */
export type ToolEntry = string | JsonObject;

/** An operation with arguments bound: `{tool, bind}`. */
export function boundToolOf(entry: ToolEntry): { tool: string; bind: JsonObject } | null {
    return typeof entry === 'object' && typeof entry.tool === 'string' ? { tool: entry.tool, bind: (entry.bind ?? {}) as JsonObject } : null;
}

/** A person as tools: `{human, tools}`, each of `notify`, `ask` and `hand_off`. */
export function personToolOf(entry: ToolEntry): { address: JsonObject; tools: string[] } | null {
    if (typeof entry !== 'object' || !entry.human || typeof entry.human !== 'object') return null;
    return { address: entry.human as JsonObject, tools: Array.isArray(entry.tools) ? entry.tools.map(String) : [] };
}

/** Who a person tool reaches: an email, a phone, one of your users, or the user each turn acts for. */
export function personLabel(address: JsonObject): string {
    for (const key of ['email', 'phone', 'user_id'] as const) if (typeof address[key] === 'string') return address[key] as string;
    return 'the user it acts for';
}

/** `to = {{user.email}}, label = support` */
export function bindingText(bind: JsonObject): string {
    return Object.entries(bind)
        .map(([k, v]) => `${k} = ${typeof v === 'string' ? v : JSON.stringify(v)}`)
        .join(', ');
}

/** Any entry as one line of text, where only text fits (a row's summary, a chip). */
export function toolEntryText(entry: ToolEntry): string {
    if (typeof entry === 'string') return entry;
    const bound = boundToolOf(entry);
    if (bound) return `${bound.tool} (${bindingText(bound.bind)})`;
    const person = personToolOf(entry);
    if (person) return `${personLabel(person.address)}: ${person.tools.join(', ')}`;
    return JSON.stringify(entry);
}

/** Its model calls on your own key or plan (designed), in one line: tokens, then their list price. */
export function modelUsageText(usage: ModelUsage): string {
    const cached = usage.cachedTokens ? `, ${formatCount(usage.cachedTokens)} cached` : '';
    return `${formatCount(usage.inputTokens)} in, ${formatCount(usage.outputTokens)} out${cached} · ${formatMoney(usage.usd)} at list price`;
}

/** The ref an entry runs: a string, or a bound operation's `tool`; a person has none. */
export function entryRef(entry: ToolEntry): string | null {
    return typeof entry === 'string' ? entry : (boundToolOf(entry)?.tool ?? null);
}

/** The harness catalog (`GET /v1/harnesses`), one read for every surface that shows it. */
export function useHarnesses() {
    const { client } = useConsole();
    return useV1('harnesses', () => Agent.harnesses({ client }));
}

/** The model providers' names (`kind: model`): an agent's model connection names one, never its tools. Null until read. */
export function modelIntegrationNames(catalog: readonly IntegrationInfo[] | undefined): Set<string> | null {
    return catalog ? new Set(catalog.filter((i) => i.kind === 'model').map((i) => i.name)) : null;
}

/** What running on a harness means: where it runs and how its reply arrives. */
export function harnessSummary(h: HarnessInfo): string {
    const where = h.shell === 'built_in' ? 'Runs in a sandbox of its own, with its own shell and files' : "NoClick's own agent loop, with the code tool as its shell";
    return `${where}; its reply ${h.streaming === 'final' ? 'arrives whole' : 'streams as it is written'}.`;
}

const PROVIDERS_NAMED = 3;

/** `Anthropic or OpenAI`: the providers that serve a harness, as the catalog labels them; a long list names the first few. */
function providersText(names: readonly string[], catalog: readonly IntegrationInfo[] | undefined): string {
    const labels = names.map((n) => catalog?.find((i) => i.name === n)?.label ?? n);
    if (labels.length > PROVIDERS_NAMED + 1) return `${labels.slice(0, PROVIDERS_NAMED).join(', ')} or ${labels.length - PROVIDERS_NAMED} other providers`;
    return labels.length > 1 ? `${labels.slice(0, -1).join(', ')} or ${labels[labels.length - 1]}` : (labels[0] ?? '');
}

/**
 * Whether a move to `harness` keeps the model connection named `name`: a CLI harness keeps one of a
 * provider that serves it; `sdk` starts on its default model, on NoClick's key, so it keeps none.
 */
export function keepsModelConnection(name: string, harness: HarnessInfo, connections: readonly Connection[] | undefined): boolean {
    const connection = connections?.find((c) => c.name === name);
    return harness.modelConnection === 'required' && !!connection && harness.integrations.includes(connection.integration);
}

/**
 * The connection a harness thinks with, from the agent's scope: those of the
 * model providers that serve it, or one made here, pending with a link where
 * someone pastes a key (or, on a user's own, signs in with their plan).
 */
export function ModelConnectionField({
    harness,
    user,
    value,
    onChange,
    stacked = false,
}: {
    harness: HarnessInfo;
    user: string | null;
    value: string;
    onChange: (name: string) => void;
    /** One column at every width (the detail page's narrow aside). */
    stacked?: boolean;
}) {
    const { client } = useConsole();
    const id = useId();
    const connections = useScopeConnections(user);
    const catalog = useIntegrations();
    const [creating, setCreating] = useState(false);
    const [integration, setIntegration] = useState(harness.integrations[0] ?? '');
    const [name, setName] = useState('');
    const [made, setMade] = useState<Connection | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const listed = (connections.data ?? []).filter((c) => harness.integrations.includes(c.integration));
    // The one just made is offered at once, before the scope's list is read again.
    const options = made && !listed.some((c) => c.name === made.name) ? [...listed, made] : listed;
    const labelOf = (n: string) => catalog.data?.find((i) => i.name === n)?.label ?? n;
    const required = harness.modelConnection === 'required';
    const plan = !!catalog.data?.find((i) => i.name === integration)?.subscription;
    const create = async () => {
        const connectionName = name.trim() || integration;
        const problem = nameProblem(connectionName);
        if (problem) return setError(problem);
        setBusy(true);
        setError(null);
        try {
            const connection = await Connection.create(connectionName, { client, user, integration });
            invalidateV1('connections');
            setMade(connection);
            setCreating(false);
            onChange(connection.name);
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setBusy(false);
        }
    };
    const hint = required
        ? `${harness.label ?? harness.name} thinks with this connection's key or plan: ${providersText(harness.integrations, catalog.data)}.`
        : `Optional. With a connection to ${providersText(harness.integrations, catalog.data)}, the model runs on your own key.`;
    return (
        <div className="flex flex-col gap-1.5">
            <Field label="Model connection" hint={hint}>
                <select value={value} onChange={(e) => onChange(e.target.value)} className={cn(inputClass, 'px-2 [color-scheme:light] dark:[color-scheme:dark]')}>
                    <option value="">{required ? 'Choose a connection' : "None: NoClick's key"}</option>
                    {options.map((c) => (
                        <option key={c.id} value={c.name}>
                            {c.name} · {labelOf(c.integration)}
                            {c.status !== 'connected' ? ` · ${connectionLook(c).label.toLowerCase()}` : ''}
                        </option>
                    ))}
                </select>
            </Field>
            {connections.error !== undefined && <span className="text-[12px] text-red-600 dark:text-red-400">Couldn&apos;t load connections.</span>}
            {creating ? (
                <div className={cn('flex flex-col gap-2 rounded-md border p-3', HAIRLINE)}>
                    <div className={cn('grid gap-2', !stacked && 'sm:grid-cols-2')}>
                        <label className="flex flex-col gap-1.5">
                            <span className="text-[12px] font-medium text-muted-foreground">Provider</span>
                            <select value={integration} onChange={(e) => setIntegration(e.target.value)} className={cn(inputClass, 'px-2 [color-scheme:light] dark:[color-scheme:dark]')}>
                                {harness.integrations.map((n) => (
                                    <option key={n} value={n}>
                                        {labelOf(n)}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="flex flex-col gap-1.5">
                            <span className="text-[12px] font-medium text-muted-foreground">Connection name</span>
                            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={integration} className={cn(inputClass, 'font-mono text-[12px]')} />
                        </label>
                    </div>
                    <span id={`${id}-plan`} className="text-[12px] text-muted-foreground">
                        {!plan
                            ? 'Its link takes an API key.'
                            : user
                              ? `Its link lets the user paste their ${labelOf(integration)} key or sign in with their plan.`
                              : `Its link lets you paste your ${labelOf(integration)} key or sign in with your plan, which suits agents that work for you; an agent serving your product's users runs on a key.`}
                    </span>
                    {error && <span className="text-[12px] text-red-600 dark:text-red-400">{error}</span>}
                    <div className="flex gap-1.5">
                        <ConsoleButton size="sm" onClick={() => void create()} disabled={busy || !integration} aria-describedby={`${id}-plan`}>
                            {busy ? 'Creating…' : 'Create connection'}
                        </ConsoleButton>
                        <ConsoleButton size="sm" variant="ghost" onClick={() => setCreating(false)}>
                            Cancel
                        </ConsoleButton>
                    </div>
                </div>
            ) : (
                <button
                    type="button"
                    onClick={() => setCreating(true)}
                    className="self-start text-[12px] text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
                >
                    Create a connection
                </button>
            )}
            {made?.connectUrl && (
                <div className="flex flex-col gap-1.5">
                    <span className="text-[12px] text-muted-foreground">
                        {made.name} waits for {user ? 'the user' : 'you'} to connect it here. The agent can be created meanwhile; its turns wait for it.
                    </span>
                    <LinkShown url={made.connectUrl} />
                </div>
            )}
        </div>
    );
}

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

export const inputClass =
    'h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] focus-visible:ring-2 focus-visible:ring-ring';

/** A labelled control; the hint sits outside the label so the control's name stays the label. */
export function Field({
    label,
    hint,
    children,
    className,
    htmlFor,
}: {
    label: string;
    hint?: string;
    children: ReactNode;
    className?: string;
    /** Label the control with this id rather than wrapping it, so a popup beside it stays out of its name. */
    htmlFor?: string;
}) {
    const caption = 'text-[12px] font-medium text-muted-foreground';
    return (
        <div className={cn('flex flex-col gap-1.5', className)}>
            {htmlFor ? (
                <>
                    <label htmlFor={htmlFor} className={caption}>
                        {label}
                    </label>
                    {children}
                </>
            ) : (
                <label className="flex flex-col gap-1.5">
                    <span className={caption}>{label}</span>
                    {children}
                </label>
            )}
            {hint && <span className="text-[12px] text-muted-foreground">{hint}</span>}
        </div>
    );
}

/** A budget as typed: dollars, or null for empty (no budget). */
export function parseBudget(text: string): { value: number | null } | { error: string } {
    const t = text.trim();
    if (!t) return { value: null };
    const n = Number(t);
    return Number.isFinite(n) && n >= 0 ? { value: n } : { error: 'A budget is a dollar amount of 0 or more; empty removes it.' };
}

/**
 * This month's spend per agent, from one series grouped by agent: a budgeted
 * agent's comes from the limits read instead (its budget covers the agents it
 * spawned, as on its page).
 */
export function useAgentMonthSpend(rows: readonly Agent[]) {
    const { client } = useConsole();
    const budgeted = rows.some((a) => a.budgetUsdPerMonth != null);
    const series = useV1('usage/series?group_by=agent', () => Usage.series({ client, groupBy: 'agent', userFilter: ALL_USERS }));
    const limits = useV1(budgeted ? 'usage/limits' : null, () => Usage.limits({ client }));
    return useMemo(() => {
        const own = { data: series.data, error: series.error, of: new Map((series.data?.series ?? []).map((s) => [s.id, s.totalUsd])) };
        const subtree = { data: limits.data, error: limits.error, of: new Map((limits.data?.agents ?? []).map((a) => [a.id, a.subtreeSpent])) };
        return (agent: Agent): number | null | undefined => {
            const source = agent.budgetUsdPerMonth != null ? subtree : own;
            if (source.error !== undefined) return null;
            if (!source.data) return undefined;
            return source.of.get(agent.id) ?? 0;
        };
    }, [series.data, series.error, limits.data, limits.error]);
}

/** The instructions' first sentence: what the agent is for. */
export function purposeOf(agent: Agent): string {
    const text = (agent.instructions ?? '').replace(/\s+/g, ' ').trim();
    const cut = text.search(/[.!?](\s|$)/);
    return cut > 0 ? text.slice(0, cut + 1) : text;
}

/**
 * Capabilities as toggles, the connections of the agent's scope (its user's,
 * or the account's): `gmail` wires every operation of the connection named
 * gmail, and the integrations whose operations need no account (`exa`).
 */
export function ToolPicker({ value, onChange, user }: { value: string[]; onChange: (tools: string[]) => void; user: string | null }) {
    const href = useConsoleHref();
    const { lab } = useConsole();
    const [search, setSearch] = useState('');
    const connections = useScopeConnections(user);
    const catalog = useIntegrations();
    const databases = useScopeDatabases(user);
    const buckets = useScopeBuckets(user, value.some((ref) => bucketRefOf(ref)));
    const hasShared = value.some((ref) => sharedConnectionOf(ref));
    // Other scopes' connections are a long list for an account agent: shown on request, or when one is already shared.
    const [sharing, setSharing] = useState(hasShared);
    const others = useOtherScopeConnections(user, sharing || hasShared);
    const toggle = (ref: string) => onChange(value.includes(ref) ? value.filter((t) => t !== ref) : [...value, ref]);
    const needle = search.trim().toLowerCase();
    // A model provider's connection is what an agent thinks with, never a tool: the catalog says which they are.
    const models = modelIntegrationNames(catalog.data);
    const tooling = connections.data && models ? connections.data.filter((c) => !models.has(c.integration)) : undefined;
    const shown = (tooling ?? []).filter((c) => !needle || c.name.includes(needle) || c.integration.includes(needle));
    const shownDatabases = (databases.data ?? []).filter((d) => !needle || d.name.includes(needle));
    // A name the scope gives a connection means that connection, so its integration isn't offered here.
    const scopeNames = new Set((connections.data ?? []).map((c) => c.name));
    const shownFree = connections.data
        ? (catalog.data ?? []).filter(
              (i) =>
                  i.kind === 'app' && i.accountFreeOperationCount > 0 && !scopeNames.has(i.name) && (!needle || i.name.includes(needle) || !!i.label?.toLowerCase().includes(needle))
          )
        : [];
    const shownOthers = sharing && models ? (others.data ?? []).filter((c) => !models.has(c.integration) && (!needle || c.name.includes(needle) || c.integration.includes(needle))) : [];
    const sharedIds = new Set(value.flatMap((ref) => sharedConnectionOf(ref)?.id ?? []));
    const toggleShared = (id: string) => onChange(sharedIds.has(id) ? value.filter((ref) => sharedConnectionOf(ref)?.id !== id) : [...value, sharedConnectionRef(id)]);
    /** A connection's tools are named after it, so an agent can't hold two of one name. */
    const namesInUse = new Set(
        value.flatMap((ref) => {
            const shared = sharedConnectionOf(ref);
            if (shared) return others.data?.find((c) => c.id === shared.id)?.name ?? [];
            return databaseRefOf(ref) || bucketRefOf(ref) ? [] : [ref.split('.')[0]];
        })
    );
    /** A database is picked whole; unpicking it drops every operation of it the agent had. */
    const usesDatabase = (id: string) => value.some((ref) => databaseRefOf(ref)?.id === id);
    const toggleDatabase = (id: string) => onChange(usesDatabase(id) ? value.filter((ref) => databaseRefOf(ref)?.id !== id) : [...value, databaseRef(id)]);
    /** A chip's text: a database or bucket by name, a shared connection as `scope/name` (and the one operation of any). */
    const chipOf = (ref: string) => {
        const shared = sharedConnectionOf(ref);
        const connection = shared && others.data?.find((c) => c.id === shared.id);
        if (shared && connection) return `${scopeName(connection.userId)}/${connection.name}${shared.op ? `.${shared.op}` : ''}`;
        const parsed = databaseRefOf(ref) ?? bucketRefOf(ref);
        const name = parsed && (databaseRefOf(ref) ? databases : buckets).data?.find((d) => d.id === parsed.id)?.name;
        return parsed && name ? (parsed.op ? `${name}.${parsed.op}` : name) : ref;
    };
    return (
        <div className="flex flex-col gap-2">
            {value.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {value.map((ref) => (
                        <span key={ref} className="inline-flex items-center gap-1 rounded bg-foreground/[0.06] px-1.5 py-[1px] font-mono text-[12px]">
                            {chipOf(ref)}
                            <button type="button" aria-label={`Remove ${chipOf(ref)}`} onClick={() => toggle(ref)} className="text-muted-foreground hover:text-foreground">
                                <X className="h-3 w-3" />
                            </button>
                        </span>
                    ))}
                </div>
            )}
            <div className="flex flex-wrap gap-1">
                {AGENT_CAPABILITIES.map((c) => (
                    <button
                        key={c.ref}
                        type="button"
                        aria-pressed={value.includes(c.ref)}
                        onClick={() => toggle(c.ref)}
                        className={cn(
                            'h-7 rounded-md px-2.5 text-[12px] font-medium transition-colors',
                            value.includes(c.ref) ? 'bg-foreground/[0.1] text-foreground' : 'bg-foreground/[0.03] text-muted-foreground hover:text-foreground'
                        )}
                    >
                        {c.label}
                    </button>
                ))}
            </div>
            <div className={cn('rounded-md border', HAIRLINE)}>
                <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search tools"
                    aria-label="Search tools"
                    className={cn(inputClass, 'rounded-b-none border-0 border-b', HAIRLINE)}
                />
                <ul className="m-0 max-h-64 list-none overflow-y-auto p-1">
                    {connections.error !== undefined && <li className="px-2 py-1 text-[12px] text-red-600 dark:text-red-400">Couldn&apos;t load connections.</li>}
                    {shown.map((c) => (
                        <li key={c.id}>
                            <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-[13px] hover:bg-foreground/[0.04]">
                                <input type="checkbox" checked={value.includes(c.name)} onChange={() => toggle(c.name)} />
                                <CredentialMark credentialType={c.credentialType ?? ''} nodeType={nodeTypeOf(c)} />
                                <span className="flex-1 font-mono text-[13px]">{c.name}</span>
                                {c.status !== 'connected' && <span className="text-[12px] text-muted-foreground">{connectionLook(c).label.toLowerCase()}</span>}
                            </label>
                        </li>
                    ))}
                    {tooling && !tooling.length && (
                        <li className="px-2 py-1.5 text-[12px] text-muted-foreground">
                            No connections {user ? 'for this user' : 'on the account'} yet.{' '}
                            <Link to={href('resources/connections')} className="underline underline-offset-2">
                                Create one
                            </Link>
                            , or let your code make it with Connection.from_name.
                        </li>
                    )}
                    {tooling && tooling.length > 0 && !shown.length && <li className="px-2 py-1 text-[12px] text-muted-foreground">No connections match.</li>}
                    {shownFree.length > 0 && (
                        <li role="presentation" className={cn('mx-2 mb-0.5 mt-1.5 border-t pt-1.5 text-[12px] font-medium text-muted-foreground', HAIRLINE)}>
                            No account needed
                        </li>
                    )}
                    {shownFree.map((i) => (
                        <li key={i.name}>
                            <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-[13px] hover:bg-foreground/[0.04]">
                                <input type="checkbox" checked={value.includes(i.name)} onChange={() => toggle(i.name)} />
                                <CredentialMark credentialType={i.credentialTypes[0] ?? ''} nodeType={integrationNodeType(i.name)} />
                                <span className="flex-1">{i.label ?? i.name}</span>
                                <span className="text-[12px] text-muted-foreground">{plural(i.accountFreeOperationCount, 'operation')}</span>
                            </label>
                        </li>
                    ))}
                    {catalog.error !== undefined && <li className="px-2 py-1 text-[12px] text-red-600 dark:text-red-400">Couldn&apos;t load the integration catalog.</li>}
                    {shownDatabases.length > 0 && (
                        <li role="presentation" className={cn('mx-2 mb-0.5 mt-1.5 border-t pt-1.5 text-[12px] font-medium text-muted-foreground', HAIRLINE)}>
                            Databases: query, execute and schema
                        </li>
                    )}
                    {shownDatabases.map((d) => (
                        <li key={d.id}>
                            <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-[13px] hover:bg-foreground/[0.04]">
                                <input type="checkbox" checked={usesDatabase(d.id)} onChange={() => toggleDatabase(d.id)} />
                                <span className="flex-1 font-mono text-[13px]">{d.name}</span>
                                <span className="text-[12px] text-muted-foreground">{d.engine === 'postgres' ? 'Postgres' : 'SQLite'}</span>
                            </label>
                        </li>
                    ))}
                    {shownOthers.length > 0 && (
                        <li role="presentation" className={cn('mx-2 mb-0.5 mt-1.5 border-t pt-1.5 text-[12px] font-medium text-muted-foreground', HAIRLINE)}>
                            {user ? 'Shared from other users or your account' : 'Shared from your users'}
                        </li>
                    )}
                    {shownOthers.map((c) => {
                        const taken = !sharedIds.has(c.id) && namesInUse.has(c.name);
                        return (
                            <li key={c.id}>
                                <label
                                    title={taken ? `This agent already has a tool named ${c.name}` : undefined}
                                    className={cn('flex items-center gap-2 rounded px-2 py-1 text-[13px]', taken ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-foreground/[0.04]')}
                                >
                                    <input type="checkbox" checked={sharedIds.has(c.id)} disabled={taken} onChange={() => toggleShared(c.id)} />
                                    <CredentialMark credentialType={c.credentialType ?? ''} nodeType={nodeTypeOf(c)} />
                                    <span className="flex-1 font-mono text-[13px]">{c.name}</span>
                                    <span className="text-[12px] text-muted-foreground">
                                        {scopeName(c.userId)}
                                        {taken && ' · name taken'}
                                    </span>
                                </label>
                            </li>
                        );
                    })}
                </ul>
            </div>
            {lab && !sharing && (
                <button type="button" onClick={() => setSharing(true)} className="self-start text-[12px] text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline">
                    {user ? "Share one of another user's connections, or your account's" : "Share one of a user's connections"}
                </button>
            )}
            <p className="m-0 text-[12px] text-muted-foreground">
                An agent holds at most 64 tools, so name single operations of a large integration (gmail.send_email_message). Every agent can also run shell commands.
            </p>
        </div>
    );
}

/** How many models a search shows; a longer list is narrowed by typing. */
export const MODEL_SEARCH_LIMIT = 50;

/** A harness's models whose id or label contains `query` (searched once typing pauses), the last results kept while the next load. */
export function useHarnessModels(harness: HarnessInfo | undefined, query: string) {
    const search = useDebounce(query.trim(), 250);
    const models = useV1(harness ? `harnesses/${harness.name}/models?q=${search}` : null, () =>
        harness!.models({ search: search || undefined, limit: MODEL_SEARCH_LIMIT })
    );
    const last = useRef<{ harness: string; data: HarnessModel[] } | null>(null);
    if (harness && models.data) last.current = { harness: harness.name, data: models.data };
    const kept = harness && last.current?.harness === harness.name ? last.current.data : undefined;
    return { data: models.data ?? kept, error: models.error, searching: !!harness && models.data === undefined && models.error === undefined };
}

const MODEL_ROW = 'flex w-full cursor-pointer flex-col rounded px-2 py-1.5 text-left';

/**
 * A harness's model: its models searched as it's typed (the whole list until
 * then), its default as the placeholder. Any id goes where the harness takes
 * custom models; otherwise only a listed one is kept, and unpicked text is
 * dropped on leaving the field. Key it by harness: a new harness starts a new search.
 */
export function ModelPicker({ harness, value, onChange, id, ariaLabel }: { harness: HarnessInfo | undefined; value: string; onChange: (model: string) => void; id?: string; ariaLabel?: string }) {
    const listId = useId();
    const [query, setQuery] = useState('');
    // Typed text that isn't a model yet, where only a listed one is kept.
    const [draft, setDraft] = useState<string | null>(null);
    const [open, setOpen] = useState(false);
    const [active, setActive] = useState(-1);
    const free = harness?.customModels ?? true;
    const models = useHarnessModels(harness, query);
    const shown = models.data ?? [];
    const pick = (model: HarnessModel) => {
        onChange(model.id);
        setDraft(null);
        setQuery('');
        setOpen(false);
        setActive(-1);
    };
    const type = (next: string) => {
        setQuery(next);
        setOpen(true);
        setActive(-1);
        if (free || !next) onChange(next);
        else setDraft(next);
    };
    const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const next = e.key === 'ArrowDown' ? Math.min(active + 1, shown.length - 1) : Math.max(active - 1, 0);
            setOpen(true);
            setActive(next);
            document.getElementById(`${listId}-${next}`)?.scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'Enter' && open && shown[active]) {
            e.preventDefault();
            pick(shown[active]);
        } else if (e.key === 'Escape') {
            setOpen(false);
        }
    };
    const status =
        models.error !== undefined ? "Couldn't search its models." : shown.length ? null : models.searching ? 'Searching…' : `No listed model matches${free ? '; any id in its format still goes' : ''}.`;
    return (
        <div className="relative">
            <input
                id={id}
                aria-label={ariaLabel}
                role="combobox"
                aria-expanded={open}
                aria-controls={listId}
                aria-autocomplete="list"
                aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
                autoComplete="off"
                spellCheck={false}
                value={draft ?? value}
                placeholder={harness?.defaultModel}
                onChange={(e) => type(e.target.value)}
                onFocus={() => setOpen(true)}
                onBlur={() => {
                    setOpen(false);
                    if (draft !== null) {
                        setDraft(null);
                        setQuery('');
                    }
                }}
                onKeyDown={onKeyDown}
                className={cn(inputClass, 'font-mono text-[12px]')}
            />
            {open && harness && (
                <ul
                    id={listId}
                    role="listbox"
                    aria-label={`${harness.label ?? harness.name}'s models`}
                    className={cn('absolute inset-x-0 top-full z-20 m-0 mt-1 max-h-64 list-none overflow-y-auto rounded-md border bg-popover p-1 shadow-md', HAIRLINE)}
                >
                    {shown.map((m, i) => (
                        // Keys go to the combobox input, which tracks the active option (aria-activedescendant).
                        // eslint-disable-next-line jsx-a11y/click-events-have-key-events
                        <li
                            key={m.id}
                            id={`${listId}-${i}`}
                            role="option"
                            aria-selected={i === active}
                            onMouseDown={(e) => e.preventDefault()}
                            onMouseEnter={() => setActive(i)}
                            onClick={() => pick(m)}
                            className={cn(MODEL_ROW, i === active && 'bg-foreground/[0.06]')}
                        >
                            <span className="flex min-w-0 items-center gap-1.5">
                                <span className="truncate font-mono text-[12px] text-foreground">{m.id}</span>
                                {m.id === harness.defaultModel && <span className="shrink-0 rounded bg-foreground/[0.06] px-1 text-[12px] text-muted-foreground">default</span>}
                            </span>
                            {m.label && m.label !== m.id && <span className="truncate text-[12px] text-muted-foreground">{m.label}</span>}
                        </li>
                    ))}
                    {status && (
                        <li role="presentation" className={cn('px-2 py-1.5 text-[12px]', models.error !== undefined ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                            {status}
                        </li>
                    )}
                    {shown.length >= MODEL_SEARCH_LIMIT && (
                        <li role="presentation" className="px-2 py-1.5 text-[12px] text-muted-foreground">
                            The first {MODEL_SEARCH_LIMIT}; type to narrow.
                        </li>
                    )}
                </ul>
            )}
        </div>
    );
}
