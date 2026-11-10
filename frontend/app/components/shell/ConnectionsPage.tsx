// Connections: every app and AI company NoClick can connect, in one grid, one
// button away (an AI company connects in its own dialog); the accounts
// you can already use (yours, your organization's, shared with you), each
// opening onto proof it works, what depends on it and who shares it; and the
// other direction, using NoClick itself from Claude, ChatGPT, Cursor and any
// other MCP client.
import { useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { AlertCircle, ArrowRight, Check, Search } from 'lucide-react';
import { openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';
import { BrandIcon } from '~/components/shared/BrandIcon';
import type { WorkflowRef } from '~/components/dashboard/types';
import { Skeleton } from '~/components/ui/skeleton';
import { MCP_CLIENT_GUIDES, NoClickMCPSetupModal } from '~/components/workflow/MCPConnectModal';
import { useCredentialList } from '~/hooks/useCachedCredentialList';
import { useDashboardOverview } from '~/hooks/useDashboardOverview';
import { useOrgContext } from '~/hooks/useOrgContext';
import { scoreFields } from '~/lib/fuzzyRank';
import type { ServiceCredentialOption } from '~/utils/credentialTypes';
import { cn } from '~/lib/utils';
import { AccountPage } from './connections/AccountPage';
import { AiMark, useAiCompanies, type AiCompany } from './connections/aiAccounts';
import { AiProviderDialog } from './connections/AiProviderDialog';
import { ConnectedList } from './connections/ConnectedList';
import { TILE_GRID, Tile, TileSkeletons } from './Tile';
import { useCatalogServices, useConnectedAccounts, type AccountSource, type ConnectedAccount } from './connections/accounts';
import { CONNECTIONS_VIEWS, connectionsViews, type ConnectionsView } from './connections/views';
import { PageFrame } from './PageFrame';

const FEATURED_CLIENTS = ['claude', 'chatgpt', 'claude-code', 'cursor', 'codex'];

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

function UseNoClickElsewhere() {
    const [open, setOpen] = useState(false);
    const clients = FEATURED_CLIENTS.map((key) => MCP_CLIENT_GUIDES.find((g) => g.key === key)).filter((g): g is (typeof MCP_CLIENT_GUIDES)[number] => !!g);
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
            <NoClickMCPSetupModal open={open} onClose={() => setOpen(false)} />
        </section>
    );
}

/** Something in the catalog: an app or an AI account. Connect always adds an account, a second Gmail as easily
 *  as the first; once you have one, the rest of the tile opens it. */
function CatalogTile({
    mark,
    title,
    accounts,
    idle,
    onManage,
    onConnect,
    testId,
}: {
    mark: ReactNode;
    title: string;
    accounts: ConnectedAccount[];
    /** The line under the name before anything is connected (an AI company's subscription). */
    idle?: string;
    onManage: () => void;
    onConnect: () => void;
    testId?: string;
}) {
    const connected = accounts.length;
    const broken = accounts.some((a) => a.problem);
    return (
        <Tile
            mark={mark}
            title={title}
            detail={
                connected ? (
                    <span className="inline-flex items-center gap-1">
                        {broken ? (
                            <>
                                <AlertCircle className="h-3.5 w-3.5 text-red-600 dark:text-red-400" strokeWidth={2.25} />
                                Needs reconnecting
                            </>
                        ) : (
                            <>
                                <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" strokeWidth={2.25} />
                                {connected === 1 ? 'Connected' : `${connected} accounts`}
                            </>
                        )}
                    </span>
                ) : (
                    idle
                )
            }
            label={connected ? `${title}: open your ${connected === 1 ? 'account' : 'accounts'}` : `Connect ${title}`}
            onOpen={connected ? onManage : onConnect}
            testId={testId}
            trailing={
                <button
                    type="button"
                    onClick={(event) => {
                        event.stopPropagation();
                        onConnect();
                    }}
                    aria-label={connected ? `Connect another ${title} account` : `Connect ${title}`}
                    className="inline-flex h-8 shrink-0 items-center rounded-full px-3.5 text-[13px] font-medium text-foreground ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:ring-foreground/[0.14]"
                >
                    Connect
                </button>
            }
        />
    );
}

/** What a company answers to in search: its name, the products it covers, how it connects. */
const companyFields = (company: AiCompany) => [company.title, ...company.members, company.uses, company.line];

type CatalogEntry = { key: string; title: string; fields: string[] } & ({ company: AiCompany } | { service: ServiceCredentialOption });

/** Every app and AI company, one grid: the popular ones first, then alphabetical, and a search ranks them together.
 *  An AI company's Connect opens its dialog; once you have an account with anything, the rest of its tile opens that. */
function Catalog({
    query,
    accounts,
    onManage,
    onConnectCompany,
}: {
    query: string;
    accounts: ConnectedAccount[];
    onManage: (label: string, accounts: ConnectedAccount[]) => void;
    onConnectCompany: (company: AiCompany) => void;
}) {
    const services = useCatalogServices();
    const companies = useAiCompanies();
    const entries = useMemo<CatalogEntry[]>(
        () => [
            ...companies.map((company) => ({ key: `ai:${company.id}`, title: company.title, fields: companyFields(company), company })),
            ...services.map((service) => ({ key: service.value, title: service.label, fields: [service.label, service.acceptedCredentialTypes.join(' ')], service })),
        ],
        [companies, services]
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
        const byService = new Map<string, ConnectedAccount[]>();
        for (const account of accounts) {
            if (account.service) byService.set(account.service.value, [...(byService.get(account.service.value) ?? []), account]);
        }
        return (entry: CatalogEntry) =>
            'company' in entry ? accounts.filter((a) => entry.company.credentialTypes.includes(a.credential.credential_type)) : (byService.get(entry.service.value) ?? []);
    }, [accounts]);

    // Apps load from the node catalog; the grid appears whole rather than AI companies first.
    if (!services.length) return <TileSkeletons />;
    if (!shown.length) return <p className="py-16 text-center text-[14px] text-muted-foreground">Nothing matches “{query.trim()}”.</p>;
    return (
        <div className={TILE_GRID} data-testid="app-catalog">
            {shown.map((entry) => {
                const own = accountsOf(entry);
                return 'company' in entry ? (
                    <CatalogTile
                        key={entry.key}
                        mark={<AiMark provider={entry.company.members[0]} />}
                        title={entry.title}
                        accounts={own}
                        idle={entry.company.line || undefined}
                        onManage={() => onManage(entry.title, own)}
                        onConnect={() => onConnectCompany(entry.company)}
                        testId={`ai-tile-${entry.company.id}`}
                    />
                ) : (
                    <CatalogTile
                        key={entry.key}
                        mark={
                            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-foreground/[0.05]">
                                <BrandIcon Icon={entry.service.Icon} iconColor={entry.service.iconColor} className="h-[22px] w-[22px]" />
                            </span>
                        }
                        title={entry.title}
                        accounts={own}
                        onManage={() => onManage(entry.title, own)}
                        onConnect={() => openCreateCredential({ credentialType: entry.service.primaryCredentialType })}
                    />
                );
            })}
        </div>
    );
}

/** What uses one account, from the overview (the same graph scan the Resources pages read). */
function AccountView({ account, backLabel, onBack }: { account: ConnectedAccount; backLabel: string; onBack: () => void }) {
    const { overview } = useDashboardOverview();
    const usedBy: WorkflowRef[] | undefined = overview ? (overview.credentials.find((c) => c.id === account.credential.id)?.usedBy ?? []) : undefined;
    return <AccountPage account={account} usedBy={usedBy} backLabel={backLabel} onBack={onBack} onGone={onBack} />;
}

function parseView(raw: string | null, hasOrg: boolean): View {
    return connectionsViews(hasOrg).find((v) => v.id === raw)?.id ?? 'all';
}

export function ConnectionsPage() {
    const [params, setParams] = useSearchParams();
    const [orgContext] = useOrgContext();
    const view = parseView(params.get('view'), !!orgContext.id);
    const accountId = params.get('account');
    const [query, setQuery] = useState('');
    const { credentials, loaded } = useCredentialList();
    const accounts = useConnectedAccounts(credentials);
    const services = useCatalogServices();
    const companies = useAiCompanies();
    const [connecting, setConnecting] = useState<AiCompany | null>(null);
    const bySource = useMemo(() => {
        const out: Record<AccountSource, ConnectedAccount[]> = { connected: [], organization: [], shared: [] };
        for (const account of accounts) out[account.source].push(account);
        return out;
    }, [accounts]);

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
        if (account) return <AccountView account={account} backLabel={VIEW_LABELS[view]} onBack={() => go({ account: null })} />;
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

    const tabs: { id: View; count?: number }[] = connectionsViews(!!orgContext.id).map((v) => ({
        id: v.id,
        count: (v.id === 'all' ? (services.length ? services.length + companies.length : 0) : bySource[v.id].length) || undefined,
    }));
    const manage = (label: string, own: ConnectedAccount[]) => {
        if (own.length === 1) {
            go({ account: own[0].credential.id }, true);
            return;
        }
        setQuery(label);
        go({ view: own.some((a) => a.source === 'connected') ? 'connected' : own[0].source }, true);
    };
    const switchTo = (next: View) => {
        if (next !== view) setQuery('');
        go({ view: next });
    };
    return (
        <PageFrame title="Connections" description="The apps and accounts your agents and automations act through.">
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
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder={view === 'all' ? 'Search apps' : 'Search accounts'}
                        className="h-9 w-full rounded-full border border-border bg-transparent pl-9 pr-3 text-[13.5px] text-foreground outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/25 dark:border-foreground/[0.1]"
                    />
                </label>
            </div>
            {view === 'all' ? (
                <>
                    <Catalog query={query} accounts={accounts} onManage={manage} onConnectCompany={setConnecting} />
                    <UseNoClickElsewhere />
                    <AiProviderDialog
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
                <ConnectedList
                    accounts={bySource[view]}
                    source={view}
                    query={query}
                    loaded={loaded}
                    onOpen={(id) => go({ account: id }, true)}
                    onBrowse={() => switchTo('all')}
                />
            )}
        </PageFrame>
    );
}
