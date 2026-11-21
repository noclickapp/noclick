// Connections: every app and AI company the account can connect, in one grid, one button away; the accounts you can
// already use (yours, your workspace's, shared with you), each opening onto proof it works, what depends on it and who
// shares it; and the other direction, using NoClick itself from Claude, ChatGPT, Cursor and any other MCP client. Its
// accounts come from the Provider around it (the `connections.reads` slot: the platform API's connections by default).
import { useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { ArrowRight, Search } from 'lucide-react';
import { useSlot } from '@/slots';
import { scoreFields } from '@/lib/fuzzyRank';
import { useClient } from '@/sdk/client';
import { MCP_URL } from '@/screens/console/lib/mcpUrl';
import { BrandIcon } from '@/ui/BrandIcon';
import { MCPSetupModal, mcpClientGuides } from '@/ui/MCPSetupModal';
import { PageFrame } from '@/ui/PageFrame';
import { SearchClearButton } from '@/ui/SearchClearButton';
import { Skeleton } from '@/ui/skeleton';
import { CONNECTION_MARK } from '@/ui/slots';
import { TileSkeletons, VirtualTileGrid } from '@/ui/Tile';
import { cn } from '@/ui/utils';
import { AccountPage } from './AccountPage';
import { CatalogTile } from './CatalogTile';
import { ConnectedList } from './ConnectedList';
import { useConnectionsContext } from './context';
import type { CatalogApp, ConnectedAccount } from './model';
import { useConnectionsAccounts } from './reads';
import { AI, APPS, CONNECT, READS, type AiCompanyEntry } from './slots';
import { CONNECTIONS_VIEWS, connectionsViews, type AccountSource, type ConnectionsView } from './views';

const FEATURED_CLIENTS = ['claude', 'chatgpt', 'claude-code', 'cursor', 'codex'];

/** What "Use NoClick from your AI apps" says under its guide's title, for NoClick's own MCP server. */
const MCP_INTRO = 'Build automations, agents, apps and more on NoClick from Claude, ChatGPT, Cursor and other MCP clients.';

// What most people connect first leads the catalog, the AI companies agents run on among the apps (`ai:` + company
// id); the rest follow alphabetically.
const POPULAR = [
    'automation-gmail',
    'automation-slack',
    'ai:openai',
    'ai:anthropic',
    'automation-github-rest',
    'automation-google-calendar',
    'automation-notion',
    'automation-google-sheets',
    'automation-outlook',
    'automation-whatsapp',
    'automation-linear',
    'automation-hubspot',
    'automation-google-drive',
    'automation-airtable',
    'ai:gemini',
    'ai:openrouter',
];

type View = ConnectionsView;

const VIEW_LABELS = Object.fromEntries(CONNECTIONS_VIEWS.map((v) => [v.id, v.label])) as Record<View, string>;

const PAGE_DESCRIPTION = 'The apps and accounts your agents and automations act through.';

function UseNoClickElsewhere() {
    const [open, setOpen] = useState(false);
    const { mcp } = useConnectionsContext();
    const clients = useMemo(() => {
        const guides = mcpClientGuides();
        return FEATURED_CLIENTS.map((key) => guides.find((g) => g.key === key)).filter((g): g is (typeof guides)[number] => !!g);
    }, []);
    return (
        <section className="mt-12">
            <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">Use NoClick from your AI apps</h2>
            <p className="mt-1 text-[14px] text-muted-foreground">Build and run your automations from any MCP client. It signs in to NoClick the first time it connects.</p>
            <button
                type="button"
                onClick={() => setOpen(true)}
                className="group mt-4 flex w-full flex-wrap items-center gap-x-4 gap-y-2.5 rounded-2xl border border-border px-4 py-3.5 text-left transition-colors hover:bg-foreground/[0.03] dark:border-foreground/[0.08]"
            >
                <span className="flex items-center -space-x-1.5">
                    {clients.map(({ key, Icon, label }) => (
                        <span key={key} title={label} className="grid h-8 w-8 place-items-center rounded-full bg-card ring-2 ring-background dark:bg-zinc-900">
                            <Icon size={16} />
                        </span>
                    ))}
                </span>
                <span className="order-last w-full text-[14px] text-foreground sm:order-none sm:w-auto sm:min-w-0 sm:flex-1">
                    {clients.map((c) => c.label).join(', ')} and more
                </span>
                <span className="ml-auto inline-flex shrink-0 items-center gap-1 text-[13.5px] font-medium text-foreground/85 transition-colors group-hover:text-foreground">
                    Set up
                    <ArrowRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
                </span>
            </button>
            <MCPSetupModal open={open} onClose={() => setOpen(false)} url={mcp?.url ?? MCP_URL} serverName="noclick" title="Connect over MCP" intro={mcp?.intro ?? MCP_INTRO} />
        </section>
    );
}

/** An app's mark in the catalog: its own glyph where the catalog carries one, else its service's mark. */
function AppMark({ app }: { app: CatalogApp }) {
    const { Mark } = useSlot(CONNECTION_MARK);
    return (
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-foreground/[0.05]">
            {app.Icon ? <BrandIcon Icon={app.Icon} iconColor={app.iconColor} className="h-[22px] w-[22px]" /> : <Mark credentialType={app.primaryCredentialType} nodeType={app.value} size="sm" />}
        </span>
    );
}

type CatalogEntry = { key: string; title: string; fields: string[] } & ({ company: AiCompanyEntry } | { app: CatalogApp });

/** Every app and AI company, one grid: the popular ones first, then alphabetical, and a search ranks them together.
 *  An AI company's Connect opens its dialog; once you have an account with anything, the rest of its tile opens that. */
function Catalog({
    query,
    apps,
    companies,
    accounts,
    onManage,
    onConnectApp,
    onConnectCompany,
}: {
    query: string;
    apps: CatalogApp[];
    companies: AiCompanyEntry[];
    accounts: ConnectedAccount[];
    onManage: (label: string, accounts: ConnectedAccount[]) => void;
    onConnectApp: (app: CatalogApp) => void;
    onConnectCompany: (company: AiCompanyEntry) => void;
}) {
    const entries = useMemo<CatalogEntry[]>(
        () => [
            ...companies.map((company) => ({ key: `ai:${company.id}`, title: company.title, fields: company.searchFields, company })),
            ...apps.filter((app) => app.listed !== false).map((app) => ({ key: app.value, title: app.label, fields: [app.label, app.acceptedCredentialTypes.join(' ')], app })),
        ],
        [companies, apps]
    );
    const shown = useMemo(() => {
        const q = query.trim();
        if (q) {
            return entries
                .map((entry) => ({ entry, score: scoreFields(q, entry.fields) }))
                .filter((x) => x.score !== null)
                .sort((a, b) => (a.score as number) - (b.score as number))
                .map((x) => x.entry);
        }
        const rank = (entry: CatalogEntry) => {
            const i = POPULAR.indexOf(entry.key);
            return i === -1 ? POPULAR.length : i;
        };
        return [...entries].sort((a, b) => rank(a) - rank(b) || a.title.localeCompare(b.title));
    }, [entries, query]);
    const accountsOf = useMemo(() => {
        const byApp = new Map<string, ConnectedAccount[]>();
        for (const account of accounts) {
            if (account.service) byApp.set(account.service.value, [...(byApp.get(account.service.value) ?? []), account]);
        }
        return (entry: CatalogEntry) =>
            'company' in entry ? accounts.filter((a) => entry.company.credentialTypes.includes(a.credential.credential_type)) : (byApp.get(entry.app.value) ?? []);
    }, [accounts]);

    // The apps load once; the grid appears whole rather than AI companies first.
    if (!apps.length) return <TileSkeletons />;
    if (!shown.length) return <p className="py-16 text-center text-[14px] text-muted-foreground">Nothing matches “{query.trim()}”.</p>;
    return (
        <VirtualTileGrid
            items={shown}
            testId="app-catalog"
            renderTile={(entry) => {
                const own = accountsOf(entry);
                return 'company' in entry ? (
                    <CatalogTile
                        key={entry.key}
                        mark={entry.company.mark}
                        title={entry.title}
                        accounts={own}
                        idle={entry.company.line || undefined}
                        onManage={() => onManage(entry.title, own)}
                        onConnect={() => onConnectCompany(entry.company)}
                        testId={`ai-tile-${entry.company.id}`}
                    />
                ) : (
                    <CatalogTile key={entry.key} mark={<AppMark app={entry.app} />} title={entry.title} accounts={own} onManage={() => onManage(entry.title, own)} onConnect={() => onConnectApp(entry.app)} />
                );
            }}
        />
    );
}

function parseView(raw: string | null, inTeam: boolean): View {
    return connectionsViews(inTeam).find((v) => v.id === raw)?.id ?? 'all';
}

/** The page while its reads load. */
export function ConnectionsLoading() {
    return (
        <PageFrame title="Connections" description={PAGE_DESCRIPTION}>
            <TileSkeletons />
        </PageFrame>
    );
}

/** The page inside the Provider that reads its accounts. */
export function ConnectionsView() {
    const Reads = useSlot(READS);
    return (
        <Reads>
            <ConnectionsContent />
        </Reads>
    );
}

export function ConnectionsContent() {
    const [params, setParams] = useSearchParams();
    const inTeam = !!useConnectionsContext().teamWorkspace;
    const view = parseView(params.get('view'), inTeam);
    const accountId = params.get('account');
    const [query, setQuery] = useState('');
    const searchRef = useRef<HTMLInputElement>(null);
    const client = useClient();
    const { accounts, loaded, error, retry } = useConnectionsAccounts();
    const apps = useSlot(APPS).useApps();
    const ai = useSlot(AI);
    const companies = ai.useCompanies();
    const connect = useSlot(CONNECT);
    const [connecting, setConnecting] = useState<AiCompanyEntry | null>(null);
    const bySource = useMemo(() => {
        const out: Record<AccountSource, ConnectedAccount[]> = { connected: [], organization: [], shared: [] };
        for (const account of accounts) out[account.source].push(account);
        return out;
    }, [accounts]);

    if (error) {
        return (
            <PageFrame title="Connections">
                <p className="text-[14px] text-muted-foreground">
                    Couldn’t read your accounts: {error}{' '}
                    <button type="button" className="text-foreground underline underline-offset-4" onClick={retry}>
                        Try again
                    </button>
                </p>
            </PageFrame>
        );
    }

    const go = (next: { view?: View; account?: string | null }, push = false) =>
        setParams(
            (prev) => {
                const out = new URLSearchParams(prev);
                const v = next.view ?? view;
                if (v === 'all') out.delete('view');
                else out.set('view', v);
                if (next.account) out.set('account', next.account);
                else out.delete('account');
                return out;
            },
            { replace: !push }
        );

    if (accountId) {
        const account = accounts.find((a) => a.credential.id === accountId);
        // Back goes to the tab the account was opened from.
        if (account) return <AccountPage account={account} backLabel={VIEW_LABELS[view]} onBack={() => go({ account: null })} onGone={() => go({ account: null })} />;
        return (
            <PageFrame title="Connections">
                {!loaded ? (
                    <div className="space-y-3">
                        <Skeleton className="h-12 w-72 rounded-xl" />
                        <Skeleton className="h-24 w-full rounded-2xl" />
                    </div>
                ) : (
                    <p className="text-[14px] text-muted-foreground">
                        This account isn’t here anymore.{' '}
                        <button type="button" className="text-foreground underline underline-offset-4" onClick={() => go({ view: 'connected', account: null })}>
                            See your accounts
                        </button>
                    </p>
                )}
            </PageFrame>
        );
    }

    const tabs: { id: View; count?: number }[] = connectionsViews(inTeam).map((v) => ({
        id: v.id,
        count: (v.id === 'all' ? (apps.length ? apps.length + companies.length : 0) : bySource[v.id].length) || undefined,
    }));
    const manage = (label: string, own: ConnectedAccount[]) => {
        if (own.length === 1) {
            go({ account: own[0].credential.id }, true);
            return;
        }
        setQuery(label);
        go({ view: own.some((a) => a.source === 'connected') ? 'connected' : own[0].source }, true);
    };
    const searchLabel = view === 'all' ? 'Search apps' : 'Search accounts';
    const switchTo = (next: View) => {
        if (next !== view) setQuery('');
        go({ view: next });
    };
    return (
        <PageFrame title="Connections" description={PAGE_DESCRIPTION}>
            <div className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-3">
                <div className="-mx-5 flex min-w-0 gap-1.5 overflow-x-auto px-5 scrollbar-hide sm:mx-0 sm:px-0" role="tablist" aria-label="Connections">
                    {tabs.map((t) => (
                        <button
                            key={t.id}
                            type="button"
                            role="tab"
                            aria-selected={view === t.id}
                            onClick={() => switchTo(t.id)}
                            className={cn(
                                'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-[13px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                                view === t.id ? 'bg-primary text-primary-foreground' : 'bg-secondary text-foreground/80 hover:bg-accent dark:bg-foreground/[0.06] dark:hover:bg-foreground/[0.1]'
                            )}
                        >
                            {VIEW_LABELS[t.id]}
                            {t.count ? <span className={cn('tabular-nums', view === t.id ? 'text-primary-foreground/60' : 'text-muted-foreground')}>{t.count}</span> : null}
                        </button>
                    ))}
                </div>
                <label className="relative ml-auto w-full sm:w-64">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                        ref={searchRef}
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder={searchLabel}
                        aria-label={searchLabel}
                        className="h-9 w-full rounded-full border border-border bg-transparent pl-9 pr-9 text-[13.5px] text-foreground outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/25 dark:border-foreground/[0.1]"
                    />
                    <SearchClearButton value={query} onClear={() => setQuery('')} inputRef={searchRef} className="absolute right-1 top-1/2 -translate-y-1/2" />
                </label>
            </div>
            {view === 'all' ? (
                <>
                    <Catalog
                        query={query}
                        apps={apps}
                        companies={companies}
                        accounts={accounts}
                        onManage={manage}
                        onConnectApp={(app) => connect(app, client)}
                        onConnectCompany={setConnecting}
                    />
                    <UseNoClickElsewhere />
                    <ai.Connect
                        company={connecting}
                        accounts={accounts}
                        onOpenChange={(open) => !open && setConnecting(null)}
                        onOpenAccount={(id) => {
                            setConnecting(null);
                            go({ account: id }, true);
                        }}
                    />
                </>
            ) : (
                <ConnectedList accounts={bySource[view]} source={view} query={query} loaded={loaded} onOpen={(id) => go({ account: id }, true)} onBrowse={() => switchTo('all')} />
            )}
        </PageFrame>
    );
}
