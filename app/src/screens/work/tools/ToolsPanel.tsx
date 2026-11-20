// What an agent can use, opened in place from its conversation (`/mcp`, `/tools`, `/apps`): everything on the account
// as one row (what an agent made with no tools gets), with Choose opening its profile's Tools tab, where each app and
// action is allowed, asked about first or off; its apps, its MCP servers
// and NoClick's own tools, each removable; and Add, search first, over everything, the apps Connections lists (those an
// agent can use as tools), NoClick's own and an MCP server by its URL. An app with an account already connected goes on
// at once (a choice where there are several); one with none opens the connect dialog's own flow (AppConnect), and the
// account that lands goes on. An app or NoClick tool is the agent's `tools`, written with `agent.update`; an MCP
// server is a step of its automation (`agent.addToolServer`), each drawn as the platform says it stands (ToolServers)
// and signed in to through its connect link where the server asks for a sign-in, or given the key it takes instead (a
// header the platform keeps as a credential and never shows again). Each holds from its next turn; one the platform
// refuses goes back, saying why.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { ArrowLeft, Bot, Check, ChevronRight, Compass, Globe, InfinityIcon, Plug, Plus, Search, Sparkles, User, Wallet, Wrench, X } from 'lucide-react';
import { Agent, type AgentToolServer, type Connection } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { errorText } from '@/screens/console/pages/resources/shared';
import { BrandIcon } from '@/ui/BrandIcon';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { scoreFields } from '@/lib/fuzzyRank';
import { useChanged } from '@/lib/useChanged';
import { cn } from '@/ui/utils';
import { useSlot } from '@/slots';
import { APPS, type ToolApp } from '../slots';
import { reconnectByLink } from '@/ui/connectStandards';
import { CONNECT_APP } from '@/ui/slots';
import { useWorkClient } from '../client';
import { AGENTS_KEY } from '../agents/reads';
import { HarnessMark } from '../agents/harness';
import { rereadAccounts, useConnections } from '../newAgent/catalog';
import { AppMark, catalogApp } from '../newAgent/wakes';
import { rereadAgent, useAgent, useAgentToolServers } from '../profile/reads';
import { checkedLine, ServerPage, ServerRow, useServerActions } from './ToolServers';
import { ComposerDrawer } from '../conversation/menus';
import { XS_BUTTON, XS_GHOST, XS_OUTLINE, XS_PRIMARY } from '../conversation/styles';
import { EVERYTHING, holds, keyHeaders, NOCLICK_TOOLS, refFor, toolRows, withAll, without, type ToolEntry, type ToolRow } from '@/lib/agentTools';
import { useWorkNav } from '../nav';

/** Apps people reach for, after their own. */
const POPULAR = ['automation-gmail', 'automation-slack', 'automation-github-rest', 'automation-linear', 'automation-notion', 'automation-google-sheets', 'automation-hubspot', 'automation-stripe'];

const OWN_ICON: Record<string, ReactNode> = {
    search: <Search className="h-3.5 w-3.5" strokeWidth={2} />,
    fetch: <Globe className="h-3.5 w-3.5" strokeWidth={2} />,
    browser: <Compass className="h-3.5 w-3.5" strokeWidth={2} />,
    noclick: <HarnessMark harness="sdk" className="h-3.5 w-3.5" />,
    agents: <Bot className="h-3.5 w-3.5" strokeWidth={2} />,
    card: <Wallet className="h-3.5 w-3.5" strokeWidth={2} />,
};

const ROW = 'flex min-h-11 w-full items-center gap-3 rounded-[16px] px-2 py-1.5 text-left';
const HEAD = 'px-2 pb-1 pt-3 text-[11px] font-medium leading-4 text-muted-foreground first:pt-1';

export const EVERYTHING_TITLE = 'Everything on your account';
const EVERYTHING_LINE = 'Every app you’ve connected, ones you add later too, plus the web and NoClick';
const LIST = new Intl.ListFormat('en', { type: 'conjunction' });
const EVERYTHING_ICON = <InfinityIcon className="h-3.5 w-3.5" strokeWidth={2} />;

export type Everything = Extract<ToolRow, { kind: 'everything' }>;
export type Listed = Exclude<ToolRow, Everything>;

/** The apps an agent can use as tools, as whoever shows Work lists them (`APPS`). */
export function useToolApps(): ToolApp[] {
    return useSlot(APPS).useToolApps();
}

/** The app a connection or a ref is for, as Connections draws it. */
function appOf(apps: readonly ToolApp[], connection: Connection | null, base: string): { label: string; service: ToolApp | null; nodeType: string } {
    const service = connection ? apps.find((s) => s.acceptedCredentialTypes.includes(connection.credentialType ?? '')) : apps.find((s) => s.value === `automation-${base}`);
    const named = catalogApp(connection?.integration ?? base, connection?.credentialType ? [connection.credentialType] : []);
    return { label: service?.label ?? named.label, service: service ?? null, nodeType: service?.value ?? named.nodeType };
}

function Tile({ children }: { children: ReactNode }) {
    return <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground/75 ring-1 ring-inset ring-foreground/[0.05]">{children}</span>;
}

function AppGlyph({ service, nodeType }: { service: ToolApp | null; nodeType: string }) {
    return <Tile>{service?.Icon ? <BrandIcon Icon={service.Icon} iconColor={service.iconColor} className="h-4 w-4" /> : <AppMark nodeType={service?.value ?? nodeType} className="h-4 w-4" />}</Tile>;
}

function Line({ title, line, tone }: { title: ReactNode; line?: ReactNode; tone?: 'down' }) {
    return (
        <span className="min-w-0 flex-1">
            <span className="block truncate text-[13.5px] font-medium leading-5">{title}</span>
            {line && <span className={cn('block truncate text-[12px] leading-4', tone === 'down' ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>{line}</span>}
        </span>
    );
}

/** The accounts of yours an app's tools can run on: connected, and of a kind it takes. */
const accountsFor = (service: ToolApp, connections: readonly Connection[]) => connections.filter((c) => c.connected && service.acceptedCredentialTypes.includes(c.credentialType ?? ''));
const whoOf = (c: Connection) => c.account ?? (c.origin === 'app' ? null : c.name);

/** What everything reaches of the account's connections: its scope's (the account's, or its user's), of an app an
 *  agent can use as tools, whatever state they're in. Null until they're read. */
export function useEverythingReaches(userId: string | null): Connection[] | null {
    const connections = useConnections();
    const apps = useToolApps();
    return useMemo(
        () => (connections.data ? connections.data.filter((c) => c.userId === userId && apps.some((s) => s.acceptedCredentialTypes.includes(c.credentialType ?? ''))) : null),
        [apps, connections.data, userId]
    );
}

/** The apps everything reaches, by name: "Includes Gmail, GitHub, Slack, and 2 more". */
export function includesLine(reaches: readonly Connection[], apps: readonly ToolApp[]): string {
    const labels = [...new Set(reaches.map((c) => appOf(apps, c, c.name).label))];
    return labels.length ? `Includes ${LIST.format(labels.length > 3 ? [...labels.slice(0, 3), `${labels.length - 3} more`] : labels)}` : 'No apps connected yet';
}

/** What NoClick's part of everything is narrowed to, in words: "only to read and build"; null for all of it. */
export const noclickNarrowing = (row: Everything) => (row.noclick ? `only to ${LIST.format(row.noclick)}` : null);

/** A listed row's name, as the panel shows it. */
export const rowTitle = (row: Listed, apps: readonly ToolApp[]) => (row.kind === 'app' ? appOf(apps, row.connection, row.base).label : row.title);

export interface ToolsPanelProps {
    agent: Agent;
    /** Its name as Work shows it. */
    name: string;
    /** The conversation it's opened from: its MCP servers' state as that conversation last saw them. */
    conversation: string | null;
    onClose: () => void;
}

export function ToolsPanel({ agent, name, conversation, onClose }: ToolsPanelProps) {
    const client = useWorkClient();
    const read = useAgent(agent.id);
    const live = read.data ?? agent;
    const connections = useConnections();
    const apps = useToolApps();
    const reaches = useEverythingReaches(live.userId);
    const [view, setView] = useState<'list' | 'add' | 'server'>('list');
    const nav = useWorkNav();
    const servers = useAgentToolServers(agent.id, conversation);
    const actions = useServerActions(agent.id, conversation);
    // The server whose own page is open, by its step.
    const [shown, setShown] = useState<string | null>(null);
    const page = shown ? servers.data?.find((s) => s.id === shown) : undefined;
    // What was just written, shown until the agent read again says it.
    const [pending, setPending] = useState<ToolEntry[] | null>(null);
    if (useChanged(read.data)) setPending(null);
    const tools = pending ?? (live.tools as ToolEntry[]);
    // A change reads the tools as they are when it's made (an account can land long after the panel drew).
    const latest = useRef(tools);
    latest.current = tools;
    const [connecting, setConnecting] = useState<ToolApp | null>(null);
    const { Connect: ConnectApp } = useSlot(CONNECT_APP);

    const save = async (change: (tools: ToolEntry[]) => ToolEntry[], done: string, { undo = true, description = `${name} can use it from its next turn.` } = {}) => {
        const before = latest.current;
        const next = change(before);
        latest.current = next;
        setPending(next);
        try {
            await Agent.fromId(agent.id, { client }).update({ tools: next });
            rereadAgent(agent.id);
            invalidateV1(AGENTS_KEY);
            toast(done, { description, ...(undo && { action: { label: 'Undo', onClick: () => void save(() => before, 'Put back as it was', { undo: false }) } }) });
            return true;
        } catch (error) {
            setPending(null);
            toast(`Couldn’t change what ${name} can use`, { description: errorText(error) });
            return false;
        }
    };
    const remove = (row: ToolRow, title: string) => save((now) => without(now, row), `Took ${title} away`);
    const add = async (ref: string, title: string) => {
        if (await save((now) => withAll(now, ref), `${title} added`)) setView('list');
    };
    const removeServer = async (server: AgentToolServer) => {
        try {
            await Agent.fromId(agent.id, { client }).removeToolServer(server);
            rereadAgent(agent.id);
            toast(`Took ${server.name} away`, { description: `${name} stops using its tools from its next turn. Its sign-in stays connected.` });
        } catch (error) {
            toast(`Couldn’t take ${server.name} away`, { description: errorText(error) });
        }
    };

    return (
        <div className="flex max-h-[min(30rem,58dvh)] flex-col" data-testid="tools-panel">
            {view === 'list' && page ? (
                <>
                    <PanelHead title={page.name} onBack={() => setShown(null)} onClose={onClose} />
                    <ServerPage
                        server={page}
                        actions={actions}
                        onRemove={() => {
                            setShown(null);
                            void removeServer(page);
                        }}
                    />
                </>
            ) : view === 'list' ? (
                <ToolList
                    name={name}
                    tools={tools}
                    servers={servers.data ?? []}
                    connections={connections.data ?? []}
                    reaches={reaches}
                    apps={apps}
                    actions={actions}
                    onAdd={() => setView('add')}
                    onChoose={() => {
                        nav.openProfile(agent.id, { tab: 'tools' });
                        onClose();
                    }}
                    onRemove={remove}
                    onRemoveServer={(s) => void removeServer(s)}
                    onOpenServer={(s) => setShown(s.id)}
                    onClose={onClose}
                />
            ) : view === 'server' ? (
                <AddServer agent={agent} name={name} actions={actions} onBack={() => setView('add')} onClose={onClose} onAdded={() => setView('list')} />
            ) : (
                <AddTool
                    name={name}
                    tools={tools}
                    connections={connections.data ?? []}
                    apps={apps}
                    onBack={() => setView('list')}
                    onClose={onClose}
                    onAdd={(ref, title) => void add(ref, title)}
                    onConnect={setConnecting}
                    onServer={() => setView('server')}
                />
            )}
            {connecting && (
                <ConnectApp
                    app={connecting}
                    name={name}
                    client={client}
                    onConnected={(credentialId) => {
                        rereadAccounts();
                        void add(`credential:${credentialId}`, connecting.label);
                    }}
                    onClose={() => setConnecting(null)}
                />
            )}
        </div>
    );
}

function PanelHead({ title, onBack, onClose, children }: { title: string; onBack?: () => void; onClose: () => void; children?: ReactNode }) {
    return (
        <div className="flex shrink-0 items-center gap-1.5 px-2 pb-1 pt-2.5">
            {onBack ? (
                <button type="button" aria-label="Back to what it can use" onClick={onBack} className={cn(XS_BUTTON, XS_GHOST, 'h-7 w-7 px-0')}>
                    <ArrowLeft className="h-3.5 w-3.5" strokeWidth={2} />
                </button>
            ) : (
                <span className="grid h-7 w-7 shrink-0 place-items-center text-muted-foreground max-sm:hidden">
                    <Wrench className="h-3.5 w-3.5" strokeWidth={2} />
                </span>
            )}
            <p className="min-w-0 flex-1 truncate text-sm font-medium max-sm:pl-1.5">{title}</p>
            {children}
            <button type="button" aria-label="Close" onClick={onClose} className={cn(XS_BUTTON, XS_GHOST, 'h-7 w-7 px-0')}>
                <X className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
        </div>
    );
}

/** A URL's host, as a server's line names it. */
const hostOf = (url: string | null) => {
    try {
        return url ? new URL(url).host : '';
    } catch {
        return url ?? '';
    }
};

function ToolList({
    name,
    tools,
    servers,
    connections,
    reaches,
    apps,
    actions,
    onAdd,
    onChoose,
    onRemove,
    onRemoveServer,
    onOpenServer,
    onClose,
}: {
    name: string;
    tools: ToolEntry[];
    servers: AgentToolServer[];
    connections: Connection[];
    /** What everything reaches; null until the accounts are read. */
    reaches: Connection[] | null;
    apps: ToolApp[];
    actions: ReturnType<typeof useServerActions>;
    onAdd: () => void;
    /** Opening its profile's Tools tab, where everything is narrowed app by app. */
    onChoose: () => void;
    onRemove: (row: ToolRow, title: string) => void;
    onRemoveServer: (server: AgentToolServer) => void;
    onOpenServer: (server: AgentToolServer) => void;
    onClose: () => void;
}) {
    const rows = toolRows(tools, connections);
    const everything = rows.find((r): r is Everything => r.kind === 'everything');
    const listed = rows.filter((r): r is Listed => r.kind !== 'everything');
    const groups: [string, Listed[]][] = [
        ['Apps', listed.filter((r) => r.kind === 'app')],
        ['NoClick', listed.filter((r) => r.kind === 'noclick')],
        ['Also', listed.filter((r) => r.kind === 'resource' || r.kind === 'person')],
    ];
    const empty = !rows.length && !servers.length;
    return (
        <>
            <PanelHead title={`What ${name} can use`} onClose={onClose}>
                {!empty && (
                    <button type="button" onClick={onAdd} className={cn(XS_BUTTON, XS_PRIMARY, 'pl-2')}>
                        <Plus className="h-3.5 w-3.5" strokeWidth={2.25} />
                        Add
                    </button>
                )}
            </PanelHead>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 scrollbar-subtle">
                {empty ? (
                    <div className="px-2 pb-3 pt-2">
                        <p className="text-[13.5px] leading-snug text-foreground/90">Only its own shell and files so far.</p>
                        <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">Give it an app like Gmail, Linear or GitHub, an MCP server, or one of NoClick’s tools: searching the web, a browser, your other agents.</p>
                        <button type="button" onClick={onAdd} className={cn(XS_BUTTON, XS_PRIMARY, 'mt-3 pl-2')}>
                            <Plus className="h-3.5 w-3.5" strokeWidth={2.25} />
                            Add an app or tool
                        </button>
                    </div>
                ) : (
                    <>
                        {everything && <EverythingRow row={everything} reaches={reaches} apps={apps} onChoose={onChoose} />}
                        {groups.map(
                            ([label, group]) =>
                                group.length > 0 && (
                                    <section key={label} aria-label={label}>
                                        <p className={HEAD}>{label}</p>
                                        {group.map((row) => (
                                            <ListedTool key={row.key} row={row} apps={apps} onRemove={onRemove} />
                                        ))}
                                    </section>
                                )
                        )}
                        {servers.length > 0 && (
                            <section aria-label="MCP servers">
                                <p className={HEAD}>
                                    MCP servers<span className="font-normal">{checkedLine(servers)}</span>
                                </p>
                                {servers.map((s) => (
                                    <ServerRow key={s.id} server={s} actions={actions} onOpen={() => onOpenServer(s)} remove={<RemoveButton title={s.name} onRemove={() => onRemoveServer(s)} />} />
                                ))}
                            </section>
                        )}
                    </>
                )}
                {!empty && <p className="px-2 pb-1 pt-3 text-[11.5px] leading-snug text-muted-foreground">Its own shell and files come with it.</p>}
            </div>
        </>
    );
}

/** Everything on the account as one row: what it reaches now, by app, and Choose to narrow it on its Tools tab. */
function EverythingRow({ row, reaches, apps, onChoose }: { row: Everything; reaches: Connection[] | null; apps: ToolApp[]; onChoose: () => void }) {
    const narrowed = noclickNarrowing(row);
    return (
        <section aria-label={EVERYTHING_TITLE} className="pt-1">
            <div className={cn(ROW, 'items-start bg-foreground/[0.03] py-2.5')} data-tool={row.key}>
                <Tile>{EVERYTHING_ICON}</Tile>
                <span className="min-w-0 flex-1">
                    <span className="block text-[13.5px] font-medium leading-5">{EVERYTHING_TITLE}</span>
                    <span className="block text-[12px] leading-4 text-muted-foreground">
                        {EVERYTHING_LINE}
                        {narrowed && ` (${narrowed})`}
                    </span>
                    {reaches && <span className="mt-1 block truncate text-[12px] leading-4 text-foreground/75">{includesLine(reaches, apps)}</span>}
                </span>
                <button type="button" onClick={onChoose} className={cn(XS_BUTTON, XS_OUTLINE)}>
                    Choose
                </button>
            </div>
        </section>
    );
}

function ListedTool({ row, apps, onRemove }: { row: Listed; apps: ToolApp[]; onRemove: (row: ToolRow, title: string) => void }) {
    let mark: ReactNode;
    const title = rowTitle(row, apps);
    let line: ReactNode = null;
    let down = false;
    let action: ReactNode = null;
    if (row.kind === 'app') {
        const app = appOf(apps, row.connection, row.base);
        const c = row.connection;
        mark = <AppGlyph service={app.service} nodeType={app.nodeType} />;
        const some = row.operations ? `${row.operations.length} of its actions` : null;
        if (!c) line = row.base.includes(':') ? 'Its account was removed' : ['Needs no account', some].filter(Boolean).join(' · ');
        else if (c.status === 'disconnected') {
            down = true;
            line = 'Needs reconnecting';
            action = <ReconnectButton connection={c} title={title} />;
        } else line = [whoOf(c) ?? (c.connected ? 'Connected' : 'Waiting for its account'), some].filter(Boolean).join(' · ');
    } else {
        mark = <Tile>{row.kind === 'noclick' ? OWN_ICON[row.ref] : row.kind === 'person' ? <User className="h-3.5 w-3.5" strokeWidth={2} /> : <Sparkles className="h-3.5 w-3.5" strokeWidth={2} />}</Tile>;
        line = row.line;
    }
    return (
        <div className={cn(ROW, 'group')} data-tool={row.key}>
            {mark}
            <Line title={title} line={line} tone={down ? 'down' : undefined} />
            {action}
            <RemoveButton title={title} onRemove={() => onRemove(row, title)} />
        </div>
    );
}

function RemoveButton({ title, onRemove }: { title: string; onRemove: () => void }) {
    return (
        <ShortcutTooltip label={`Take ${title} away`}>
            <button type="button" aria-label={`Remove ${title}`} onClick={onRemove} className={cn(XS_BUTTON, XS_GHOST, 'h-7 w-7 px-0 opacity-70 group-hover:opacity-100 focus-visible:opacity-100')}>
                <X className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
        </ShortcutTooltip>
    );
}

/** A connection that stopped working, connected again the way it was made: the app's dialog for one connected in the
 *  app, else its connect link. */
function ReconnectButton({ connection, title }: { connection: Connection; title: string }) {
    const client = useWorkClient();
    const connecting = useSlot(CONNECT_APP);
    const reconnect = async () => {
        if (connection.origin === 'app') return connecting.reconnect({ credentialType: connection.credentialType ?? undefined, credentialId: connection.id.replace(/^credential:/, '') }, client, title);
        await reconnectByLink(client, connection, title);
    };
    return (
        <button type="button" onClick={() => void reconnect()} className={cn(XS_BUTTON, XS_OUTLINE)}>
            Reconnect
        </button>
    );
}

/** One thing Add offers: an app (with the accounts of yours it runs on) or one of NoClick's own tools. */
type Offer = { key: string; title: string; line: string; mark: ReactNode; pick: () => void; ready: boolean; has?: boolean };

function AddTool({
    name,
    tools,
    connections,
    apps,
    onBack,
    onClose,
    onAdd,
    onConnect,
    onServer,
}: {
    name: string;
    tools: ToolEntry[];
    connections: Connection[];
    apps: ToolApp[];
    onBack: () => void;
    onClose: () => void;
    onAdd: (ref: string, title: string) => void;
    onConnect: (service: ToolApp) => void;
    /** Adding an MCP server by its URL. */
    onServer: () => void;
}) {
    const [q, setQ] = useState('');
    const [choosing, setChoosing] = useState<ToolApp | null>(null);
    const input = useRef<HTMLInputElement>(null);
    useEffect(() => input.current?.focus(), [choosing]);

    const appOffer = (s: ToolApp): Offer => {
        const mine = accountsFor(s, connections);
        const all = mine.length > 0 && mine.every((c) => holds(tools, refFor(c)));
        const who = mine.length === 1 ? whoOf(mine[0]) : null;
        return {
            key: s.value,
            title: s.label,
            line: all ? 'It has it already' : mine.length > 1 ? `${mine.length} of your accounts` : mine.length ? ['Connected', who].filter(Boolean).join(' · ') : 'Connect it as you add it',
            mark: <AppGlyph service={s} nodeType={s.value} />,
            ready: mine.length > 0,
            has: all,
            pick: () => {
                if (!mine.length) return onConnect(s);
                if (mine.length === 1) return all ? undefined : onAdd(refFor(mine[0]), s.label);
                setChoosing(s);
            },
        };
    };
    const ownOffers: Offer[] = NOCLICK_TOOLS.filter((t) => !holds(tools, t.ref)).map((t) => ({ key: t.ref, title: t.title, line: t.line, mark: <Tile>{OWN_ICON[t.ref]}</Tile>, ready: true, pick: () => onAdd(t.ref, t.title) }));
    const everythingOffers: Offer[] = holds(tools, EVERYTHING) ? [] : [{ key: EVERYTHING, title: EVERYTHING_TITLE, line: EVERYTHING_LINE, mark: <Tile>{EVERYTHING_ICON}</Tile>, ready: true, pick: () => onAdd(EVERYTHING, EVERYTHING_TITLE) }];
    const serverOffer: Offer = { key: 'mcp-server', title: 'Add an MCP server', line: 'Any server, by its URL', mark: <Tile><Plug className="h-3.5 w-3.5" strokeWidth={2} /></Tile>, ready: false, pick: onServer };

    const groups = useMemo((): [string, Offer[]][] => {
        const query = q.trim();
        if (query) {
            const scored = [
                ...everythingOffers.map((o) => ({ offer: o, fields: [o.title, 'everything', 'all apps', 'every connection'] })),
                ...apps.map((s) => ({ offer: appOffer(s), fields: [s.label, s.value.replace(/^automation-/, '')] })),
                ...ownOffers.map((o) => ({ offer: o, fields: [o.title, o.key, o.line] })),
                { offer: serverOffer, fields: ['MCP server', 'mcp', 'server', 'url'] },
            ]
                .map((x) => ({ ...x, score: scoreFields(query, x.fields) }))
                .filter((x) => x.score !== null)
                .sort((a, b) => (a.score as number) - (b.score as number) || Number(b.offer.ready) - Number(a.offer.ready))
                .slice(0, 8)
                .map((x) => x.offer);
            return [['', scored]];
        }
        const yours = apps.filter((s) => accountsFor(s, connections).some((c) => !holds(tools, refFor(c)))).slice(0, 6);
        const popular = POPULAR.map((v) => apps.find((s) => s.value === v)).filter((s): s is ToolApp => !!s && !yours.includes(s) && !accountsFor(s, connections).length);
        return [
            ['Your accounts', [...everythingOffers, ...yours.map(appOffer)]],
            ['NoClick', ownOffers],
            ['Popular', popular.map(appOffer)],
            ['Anything else', [serverOffer]],
        ];
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [q, apps, connections, tools]);
    const shown = groups.flatMap(([, g]) => g);

    if (choosing) {
        const mine = accountsFor(choosing, connections);
        return (
            <>
                <PanelHead title={`Which ${choosing.label} account?`} onBack={() => setChoosing(null)} onClose={onClose} />
                <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 scrollbar-subtle" aria-label={`Your ${choosing.label} accounts`}>
                    {mine.map((c) => {
                        const has = holds(tools, refFor(c));
                        return (
                            <button key={c.id} type="button" disabled={has} onClick={() => onAdd(refFor(c), choosing.label)} className={cn(ROW, 'transition-colors hover:bg-foreground/[0.05] disabled:opacity-60 disabled:hover:bg-transparent')}>
                                <AppGlyph service={choosing} nodeType={choosing.value} />
                                <Line title={whoOf(c) ?? c.name} line={has ? 'It has this one already' : c.origin === 'app' ? 'Connected in NoClick' : c.name} />
                            </button>
                        );
                    })}
                    <button type="button" onClick={() => onConnect(choosing)} className={cn(ROW, 'text-foreground/85 transition-colors hover:bg-foreground/[0.05] hover:text-foreground')}>
                        <Tile>
                            <Plus className="h-3.5 w-3.5" strokeWidth={2} />
                        </Tile>
                        <span className="text-[13.5px] font-medium">Connect another account</span>
                    </button>
                </div>
            </>
        );
    }

    return (
        <>
            <PanelHead title={`Add to ${name}`} onBack={onBack} onClose={onClose} />
            <div className="shrink-0 px-2 pb-1">
                <label className="flex h-10 items-center gap-2.5 rounded-full bg-foreground/[0.05] px-3.5 ring-1 ring-inset ring-border transition-shadow focus-within:ring-foreground/25 dark:ring-foreground/[0.1]">
                    <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                    <input
                        ref={input}
                        value={q}
                        onChange={(e) => setQ(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && shown[0]) {
                                e.preventDefault();
                                shown[0].pick();
                            }
                        }}
                        placeholder={`What should ${name} be able to use?`}
                        aria-label={`What should ${name} be able to use?`}
                        className="min-w-0 flex-1 bg-transparent text-[13.5px] outline-none placeholder:text-[hsl(var(--placeholder))] max-sm:text-[16px]"
                    />
                    {q && (
                        <button type="button" aria-label="Clear" onClick={() => setQ('')} className="grid h-6 w-6 place-items-center rounded-full text-muted-foreground hover:bg-foreground/[0.08] hover:text-foreground">
                            <X className="h-3 w-3" strokeWidth={2} />
                        </button>
                    )}
                </label>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 scrollbar-subtle" data-testid="tool-offers">
                {!apps.length && !q && <p className="px-2 pt-2 text-[12.5px] text-muted-foreground">Loading the apps…</p>}
                {groups.map(
                    ([label, group]) =>
                        group.length > 0 && (
                            <section key={label || 'found'} aria-label={label || 'Found'}>
                                {label && <p className={HEAD}>{label}</p>}
                                {group.map((o, i) => (
                                    <button key={o.key} type="button" onClick={o.pick} disabled={o.has} data-offer={o.key} className={cn(ROW, 'group transition-colors hover:bg-foreground/[0.05] disabled:opacity-60 disabled:hover:bg-transparent', q && i === 0 && 'bg-foreground/[0.04]')}>
                                        {o.mark}
                                        <Line title={o.title} line={o.line} />
                                        {o.has ? (
                                            <Check className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                                        ) : o.ready ? (
                                            <span className={cn(XS_BUTTON, XS_OUTLINE, 'pointer-events-none h-6 px-2.5 text-[11.5px]')}>Add</span>
                                        ) : (
                                            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5" strokeWidth={1.8} />
                                        )}
                                    </button>
                                ))}
                            </section>
                        )
                )}
                {q.trim() && !shown.length && <p className="px-2 py-3 text-[12.5px] leading-snug text-muted-foreground">Nothing called “{q.trim()}” can be an agent’s tool yet. Try the app’s own name, or “search” for the web.</p>}
            </div>
        </>
    );
}

/** An MCP server by its URL (and a name, else its host's): added as it is, with the key it takes where one is given;
 *  one that asks its client to sign in is added waiting for that, and signs in here through its connect link. */
function AddServer({ agent, name, actions, onBack, onClose, onAdded }: { agent: Agent; name: string; actions: ReturnType<typeof useServerActions>; onBack: () => void; onClose: () => void; onAdded: () => void }) {
    const client = useWorkClient();
    const [url, setUrl] = useState('');
    const [label, setLabel] = useState('');
    const [key, setKey] = useState('');
    const [header, setHeader] = useState('');
    const [busy, setBusy] = useState(false);
    const [problem, setProblem] = useState<string | null>(null);
    // Added, and waiting on a person's sign-in.
    const [added, setAdded] = useState<AgentToolServer | null>(null);
    const at = url.trim();
    const host = added?.host ?? hostOf(at);
    const signing = !!added && actions.busy[added.id] === 'signing';
    // The header the key goes in, and its value, as it'll be sent.
    const sent = key.trim() ? Object.entries(keyHeaders(key, header))[0] : null;
    const add = async () => {
        setBusy(true);
        setProblem(null);
        try {
            const server = await Agent.fromId(agent.id, { client }).addToolServer(at, { name: label.trim() || undefined, headers: sent ? Object.fromEntries([sent]) : undefined });
            rereadAgent(agent.id);
            if (server.status === 'needs_sign_in' && server.signIn === 'browser') return setAdded(server);
            toast(`${server.name} added`, { description: `${name} can use its tools from its next turn.` });
            onAdded();
        } catch (error) {
            setProblem(errorText(error));
        } finally {
            setBusy(false);
        }
    };
    const signIn = (server: AgentToolServer) =>
        actions.signIn(server, () => {
            toast(`Signed in to ${server.name}`, { description: `${name} can use its tools from its next turn.` });
            onAdded();
        });
    return (
        <>
            <PanelHead title="Add an MCP server" onBack={added ? onAdded : onBack} onClose={onClose} />
            <form
                className="flex flex-col gap-3 overflow-y-auto px-4 pb-4 pt-1 scrollbar-subtle"
                onSubmit={(e) => {
                    e.preventDefault();
                    if (added) {
                        if (!signing) signIn(added);
                    } else if (at) void add();
                }}
            >
                {added ? (
                    <>
                        <p className="text-[13.5px] leading-snug text-foreground/90">{host} asks you to sign in before {name} can use it.</p>
                        <p className="text-[12.5px] leading-snug text-muted-foreground">It opens in a new tab. NoClick keeps the sign-in, and {name} uses it from its next turn.</p>
                    </>
                ) : (
                    <>
                        <label className="block">
                            <span className="block pb-1 text-[12px] text-muted-foreground">Its URL</span>
                            {/* eslint-disable-next-line jsx-a11y/no-autofocus -- it opens to type the URL */}
                            <input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} inputMode="url" placeholder="https://mcp.example.com/mcp" aria-label="Its URL" className={FIELD} />
                        </label>
                        <label className="block">
                            <span className="block pb-1 text-[12px] text-muted-foreground">Name it · optional</span>
                            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={hostOf(at).split('.').find((p) => !['mcp', 'api', 'www'].includes(p)) || 'docs'} aria-label="Its name" className={FIELD} />
                        </label>
                        <label className="block">
                            <span className="block pb-1 text-[12px] text-muted-foreground">Its key · optional</span>
                            <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" spellCheck={false} placeholder="For a server that takes an API key" aria-label="Its key" className={FIELD} />
                        </label>
                        {sent && (
                            <label className="block">
                                <span className="block pb-1 text-[12px] text-muted-foreground">Its header</span>
                                <input value={header} onChange={(e) => setHeader(e.target.value)} autoComplete="off" spellCheck={false} placeholder="Authorization" aria-label="Its key’s header" className={FIELD} />
                                <span className="block px-1 pt-1.5 text-[12px] leading-snug text-muted-foreground">
                                    Sent as {sent[0]}: {sent[1] === key.trim() ? '' : 'Bearer '}‹your key›. NoClick keeps it and never shows it again.
                                </span>
                            </label>
                        )}
                        {at && !/^https:\/\//i.test(at) && <p className="text-[12px] leading-snug text-muted-foreground">It needs to be a public https URL: a server on your laptop can’t run here.</p>}
                    </>
                )}
                {problem && <p className="text-[12.5px] leading-snug text-red-600 dark:text-red-400">{problem}</p>}
                <div className="flex items-center justify-end gap-2 pt-1">
                    {added ? (
                        <button type="submit" disabled={signing} className={cn(XS_BUTTON, XS_PRIMARY, 'h-8 px-3.5 text-[13px]')}>
                            {signing ? 'Signing in…' : `Sign in to ${host}`}
                        </button>
                    ) : (
                        <button type="submit" disabled={!/^https:\/\//i.test(at) || busy} className={cn(XS_BUTTON, XS_PRIMARY, 'h-8 px-3.5 text-[13px]')}>
                            {busy ? 'Adding…' : 'Add server'}
                        </button>
                    )}
                </div>
            </form>
        </>
    );
}

const FIELD = 'h-9 w-full rounded-full bg-foreground/[0.05] px-3.5 text-[13.5px] outline-none ring-1 ring-inset ring-border transition-shadow placeholder:text-[hsl(var(--placeholder))] focus:ring-foreground/25 dark:ring-foreground/[0.1] max-sm:text-[16px]';

/** The panel pulled out from behind the conversation's box, as /usage and /context are. */
export function ToolsDrawer(props: ToolsPanelProps) {
    return (
        <ComposerDrawer label={`What ${props.name} can use`}>
            <ToolsPanel {...props} />
        </ComposerDrawer>
    );
}
