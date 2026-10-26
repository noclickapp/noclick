// Resources: what the account owns that its agents and automations use, and
// what it costs. The overview is one tile per kind (how many, what it comes to
// a month) to drill into; a kind (?kind=, also a row under Resources in the
// sidebar) lists them all with their prices; any item opens its detail page
// (?kind=&resource=), which Back leaves. The platform's kinds (domains, email,
// apps, databases, repos) are read inside the registered platform's boundary.
import { useEffect, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { ArrowRight, ChevronRight, Plus } from 'lucide-react';
import { MarkRow, NodeMark, agentMarkType, countOf, fmtBytes, relTime } from '~/components/dashboard/primitives';
import { parseDomainQuery } from '~/hooks/useDomainPurchase';
import { useInstanceCapabilities } from '~/hooks/useInstanceCapabilities';
import { formatDollars, formatUsd } from '~/lib/money';
import { Skeleton } from '~/components/ui/skeleton';
import { askNoClick } from '~/lib/askNoClick';
import { navigateToTab } from '~/lib/navigation';
import { cn } from '~/lib/utils';
import { rememberPaletteEntries } from '~/components/command/sources';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from './buttons';
import { PageFrame } from './PageFrame';
import { BuyDomainPage } from './resources/BuyDomainPage';
import { BuyNumberPage } from './resources/BuyNumberPage';
import { FileThumb } from './resources/fileParts';
import { NewAddressPage } from './resources/NewAddressPage';
import { useResourceCosts, type ResourceCosts } from './resources/costs';
import { INNER_PARAMS, resourceAddress } from './resources/kinds';
import { kindDef, useResourceItems, type KindDef, type KindId, type ResourceItem } from './resources/model';
import { PlatformResourcesBoundary, usePlatformResources } from './resources/platform';
import { ResourceDetail } from './resources/ResourceDetail';
import { TrashSection } from './resources/TrashSection';
import { ResourceUserIcon } from './resources/ui';
import { TILE_GRID, Tile, TileSkeletons } from './Tile';

function Lead({ item }: { item: ResourceItem }) {
    if (item.file && item.kind === 'files') return <FileThumb file={item.file.entry} size={36} />;
    const tile = 'grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-foreground/[0.05]';
    if (item.workspace) {
        return (
            <span className={tile}>
                <NodeMark type={agentMarkType(item.workspace.agent.model)} size="sm" />
            </span>
        );
    }
    const Icon = kindDef(item.kind).icon;
    return (
        <span className={tile}>
            <Icon className="h-[18px] w-[18px] text-foreground/75" strokeWidth={1.75} />
        </span>
    );
}

function Row({ item, now, price, onOpen }: { item: ResourceItem; now: string; price?: number; onOpen: () => void }) {
    const Figure = usePlatformResources()?.RowFigure;
    const used = item.usedBy[0];
    // A platform resource's apps and agents, where no automation uses it.
    const user = used ? undefined : item.users?.[0];
    // Where it came from, as a small detail: unless its name already says so (an automation's tables).
    const origin = !used && !user && item.origin && item.origin.name !== item.title ? item.origin : undefined;
    return (
        <button type="button" onClick={onOpen} className="group flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.03] focus-visible:outline-none">
            <Lead item={item} />
            <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium text-foreground">{item.title}</span>
                <span
                    className={cn(
                        'block truncate text-[12.5px]',
                        item.attention ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'
                    )}
                >
                    {item.subtitle}
                </span>
            </span>
            {used && (
                <span className="hidden min-w-0 max-w-[220px] shrink-0 items-center gap-2 text-[12.5px] text-muted-foreground md:flex">
                    {used.marks.length ? <MarkRow types={used.marks} size="xs" max={3} hideRest /> : null}
                    <span className="truncate">{used.name}</span>
                    {item.usedBy.length > 1 && <span className="shrink-0 tabular-nums">+{item.usedBy.length - 1}</span>}
                </span>
            )}
            {user && (
                <span className="hidden min-w-0 max-w-[220px] shrink-0 items-center gap-2 text-[12.5px] text-muted-foreground md:flex">
                    <ResourceUserIcon user={user} />
                    <span className="truncate">{user.name}</span>
                    {item.users!.length > 1 && <span className="shrink-0 tabular-nums">+{item.users!.length - 1}</span>}
                </span>
            )}
            {origin && <span className="hidden min-w-0 max-w-[220px] shrink-0 truncate text-[12.5px] text-muted-foreground md:block">Built in {origin.name}</span>}
            {item.owner && <span className="hidden min-w-0 max-w-[220px] shrink-0 truncate text-[12.5px] text-muted-foreground md:block">For {item.owner.name}</span>}
            {Figure && <Figure item={item} />}
            {price !== undefined && (
                <span className="min-w-[72px] shrink-0 text-right text-[13px] tabular-nums text-foreground/85">
                    {formatUsd(price)}
                    {kindDef(item.kind).billed === 'use' ? ' so far' : '/mo'}
                </span>
            )}
            <span className="hidden w-16 shrink-0 text-right text-[12.5px] tabular-nums text-muted-foreground sm:block">{item.updatedAt ? relTime(item.updatedAt, now) : ''}</span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-muted-foreground" />
        </button>
    );
}

function List({ children }: { children: ReactNode }) {
    return <div className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card dark:divide-foreground/[0.06] dark:border-foreground/[0.08] dark:bg-foreground/[0.02]">{children}</div>;
}

/** One kind, empty: what it is and the ways to get one (by hand, where there is a way, or by asking NoClick). */
function EmptyKind({ kind, manual }: { kind: KindDef; manual?: { label: string; run: () => void } }) {
    const Icon = kind.icon;
    return (
        <div className="flex flex-col items-center px-6 py-16 text-center">
            <span className="grid h-11 w-11 place-items-center rounded-full bg-foreground/[0.05]">
                <Icon className="h-5 w-5 text-foreground/70" strokeWidth={1.75} />
            </span>
            <p className="mt-4 text-[15px] font-semibold text-foreground">No {kind.label.toLowerCase()} yet</p>
            <p className="mt-1 max-w-sm text-[14px] leading-relaxed text-muted-foreground">{kind.empty}</p>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
                {manual && (
                    <button type="button" onClick={manual.run} className={BUTTON_PRIMARY}>
                        <Plus className="h-4 w-4" />
                        {manual.label}
                    </button>
                )}
                {kind.ask && (
                    <button type="button" onClick={() => askNoClick(kind.ask!)} className={cn('group', manual ? BUTTON_SECONDARY : BUTTON_PRIMARY)}>
                        Ask NoClick
                        <ArrowRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
                    </button>
                )}
            </div>
        </div>
    );
}

function LoadingList() {
    return (
        <List>
            {[0, 1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-3">
                    <Skeleton className="h-9 w-9 rounded-lg" />
                    <div className="flex-1 space-y-1.5">
                        <Skeleton className={cn('h-3.5', i % 2 ? 'w-1/3' : 'w-1/2')} />
                        <Skeleton className="h-3 w-1/4" />
                    </div>
                </div>
            ))}
        </List>
    );
}

/** What a kind holds, in a line: how many, and what they add up to. */
function kindLine(kind: KindDef, list: ResourceItem[]): string {
    if (!list.length) return 'None yet';
    if (kind.id === 'files') {
        const files = list.filter((i) => i.file);
        const workspaces = list.length - files.length;
        const bytes = files.reduce((sum, i) => sum + (i.file?.entry.size ?? 0), 0);
        return [files.length ? countOf(files.length, kind.noun) : null, bytes ? fmtBytes(bytes) : null, workspaces ? countOf(workspaces, ['agent workspace', 'agent workspaces']) : null]
            .filter(Boolean)
            .join(' · ');
    }
    const parts = [countOf(list.length, kind.noun)];
    const tables = list.flatMap((i) => i.tables ?? []);
    if (tables.length) parts.push(countOf(tables.length, 'table'));
    const waiting = list.filter((i) => i.pending).length;
    if (waiting) parts.push(`${waiting} waiting`);
    return parts.join(' · ');
}

/** A kind's monthly figure (what its use has cost this month, for one billed by use), or "Included" where nothing is billed. */
function KindPrice({ kind, costs }: { kind: KindDef; costs: ResourceCosts }) {
    if (!costs.shown) return null;
    const monthly = costs.kindMonthly[kind.id];
    if (monthly) {
        return (
            <span className="shrink-0 text-right leading-tight">
                <span className="block text-[14px] font-medium tabular-nums text-foreground">{formatUsd(monthly)}</span>
                <span className="block text-[11.5px] text-muted-foreground">{kind.billed === 'use' ? 'this month' : 'a month'}</span>
            </span>
        );
    }
    return kind.billed ? null : <span className="shrink-0 text-[12.5px] text-muted-foreground">Included</span>;
}

/** How a kind is charged, for its page's description. */
function kindCostLine(kind: KindDef, costs: ResourceCosts): string {
    if (!costs.shown) return '';
    const monthly = costs.kindMonthly[kind.id];
    if (kind.billed === 'use') return monthly ? ` Billed by what they use: ${formatUsd(monthly)} so far this month.` : ' Billed by what they use.';
    if (monthly) return ` ${formatUsd(monthly)} a month in total.`;
    return kind.billed ? '' : ' Included: there’s no charge for them.';
}

/** One item's price, in words: its own, a number's monthly charge, else how its kind is charged. */
function itemCost(item: ResourceItem, costs: ResourceCosts): string {
    if (item.price === null) return 'No charge';
    if (item.price) {
        const usd = formatDollars(item.price.usd);
        return item.price.per === 'year' ? `${usd} a year` : item.price.per === 'month' ? `${usd} a month` : `${usd} so far this month`;
    }
    const monthly = costs.monthly.get(item.id);
    if (monthly) return `${formatUsd(monthly)} a month`;
    const { billed } = kindDef(item.kind);
    return billed === 'use' ? 'Billed by use' : billed ? '—' : 'Included';
}

/** While the platform's reads load: the overview's frame, with its tiles waiting. */
function Loading() {
    return (
        <PageFrame title="Resources" description="What your account owns, and what uses it.">
            <TileSkeletons count={6} />
        </PageFrame>
    );
}

export function ResourcesPage() {
    return (
        <PlatformResourcesBoundary fallback={<Loading />}>
            <ResourcesView />
        </PlatformResourcesBoundary>
    );
}

/** The page itself, inside whatever platform context surrounds it (the registered one's, or the Resources lab's fixtures). */
export function ResourcesView() {
    const [params, setParams] = useSearchParams();
    const { items, kinds, loading, errors, now, refresh } = useResourceItems();
    // The palette can open any of these by name later, from anywhere.
    useEffect(() => {
        rememberPaletteEntries(
            'Resources',
            kinds.flatMap((k) =>
                items[k.id].map((item) => ({
                    id: `resource:${k.id}:${item.id}`,
                    label: item.title,
                    context: k.label,
                    icon: k.icon,
                    about: item.subtitle,
                    run: () => navigateToTab('resources', resourceAddress(k.id, { resource: item.id })),
                }))
            )
        );
    }, [items, kinds]);
    const costs = useResourceCosts(items);
    const platform = usePlatformResources();
    // Numbers and domains are sold by the hosted service with a recurring charge, so buying one by hand needs billing.
    const { billing } = useInstanceCapabilities();
    const openBuy = (kind: KindId) =>
        setParams((prev) => {
            const next = new URLSearchParams(prev);
            next.set('kind', kind);
            next.set('new', '1');
            next.delete('resource');
            return next;
        });
    // A kind's page for getting one by hand; one that's bought needs billing.
    const manualFor = (kind: KindId) => {
        const manual = kindDef(kind).manual;
        return manual && (billing || !manual.bought) ? { label: manual.label, short: manual.short, run: () => openBuy(kind) } : undefined;
    };
    const activeKind = kinds.find((k) => k.id === params.get('kind'))?.id ?? null;
    const resourceId = params.get('resource');
    const selected = activeKind && resourceId ? items[activeKind].find((i) => i.id === resourceId) : undefined;

    const go = (kind: KindId | null, resource: string | null = null, push = false) =>
        setParams(
            (prev) => {
                const next = new URLSearchParams(prev);
                if (kind) next.set('kind', kind);
                else next.delete('kind');
                if (resource) next.set('resource', resource);
                else next.delete('resource');
                // Where a body was inside an item (a repo's path, a database's table) belongs to that item, and a buy page to its kind.
                for (const inner of INNER_PARAMS) next.delete(inner);
                next.delete('new');
                return next;
            },
            { replace: !push }
        );

    if (resourceId && activeKind) {
        if (selected) {
            return (
                <ResourceDetail
                    item={selected}
                    now={now}
                    cost={costs.shown ? itemCost(selected, costs) : undefined}
                    onBack={(to) => go(to === 'all' ? null : activeKind)}
                    onChanged={() => {
                        refresh();
                        go(activeKind);
                    }}
                />
            );
        }
        return (
            <PageFrame title={kindDef(activeKind).label}>
                {loading ? (
                    <LoadingList />
                ) : (
                    <p className="text-[14px] text-muted-foreground">
                        This isn’t here anymore.{' '}
                        <button type="button" className="text-foreground underline underline-offset-4" onClick={() => go(activeKind)}>
                            See all {kindDef(activeKind).label.toLowerCase()}
                        </button>
                    </p>
                )}
            </PageFrame>
        );
    }

    const open = (item: ResourceItem) => go(item.kind, item.id, true);

    if (activeKind === 'numbers' && billing && params.get('new') === '1') {
        return (
            <BuyNumberPage
                onBack={() => go('numbers')}
                onBought={() => {
                    refresh();
                    go('numbers');
                }}
            />
        );
    }

    if (activeKind === 'domains' && billing && platform && params.get('new') === '1') {
        const byName = (domain: string) => items.domains.find((d) => d.title === domain);
        return (
            <BuyDomainPage
                registrar={platform.registrar}
                // Open on the name asked for (NoClick's link carries one), else on more endings for the one your domains have.
                seed={params.get('name') ?? parseDomainQuery(items.domains[0]?.title ?? '')?.name}
                owned={items.domains.map((d) => d.title)}
                onBack={() => go('domains')}
                onBought={() => {
                    refresh();
                    go('domains');
                }}
                onOpen={(domain) => go('domains', byName(domain)?.id ?? null, true)}
            />
        );
    }

    if (activeKind === 'email' && platform && params.get('new') === '1') {
        return (
            <NewAddressPage
                // An address made here is the account's, and goes only on one of the account's own domains.
                domains={platform.mailDomains.filter((name) => !items.domains.find((d) => d.title === name)?.owner)}
                create={platform.createAddress}
                onBack={() => go('email')}
                onCreated={(id) => {
                    refresh();
                    go('email', id);
                }}
                onBuyDomain={manualFor('domains')?.run}
            />
        );
    }

    if (activeKind) {
        const kind = kindDef(activeKind);
        const error = errors[activeKind];
        return (
            <PageFrame
                title={kind.label}
                description={`${kind.empty}${kindCostLine(kind, costs)}`}
                back={{ label: 'Resources', onBack: () => go(null) }}
                actions={
                    manualFor(kind.id) && items[activeKind].length > 0 ? (
                        <button type="button" onClick={manualFor(kind.id)!.run} className={BUTTON_PRIMARY}>
                            <Plus className="h-4 w-4" />
                            {manualFor(kind.id)!.label}
                        </button>
                    ) : undefined
                }
            >
                {loading ? (
                    <LoadingList />
                ) : error ? (
                    <p role="alert" className="text-[14px] text-muted-foreground">
                        {error}{' '}
                        <button type="button" className="text-foreground underline underline-offset-4" onClick={refresh}>
                            Try again
                        </button>
                    </p>
                ) : items[activeKind].length ? (
                    <List>
                        {items[activeKind].map((item) => (
                            <Row key={item.id} item={item} now={now} price={costs.shown ? costs.monthly.get(item.id) : undefined} onOpen={() => open(item)} />
                        ))}
                    </List>
                ) : (
                    <EmptyKind kind={kind} manual={manualFor(kind.id)} />
                )}
                {!loading && platform?.trash[activeKind]?.length ? (
                    <TrashSection entries={platform.trash[activeKind]!} now={now} onRestore={platform.restore} onPurge={platform.purge} />
                ) : null}
            </PageFrame>
        );
    }

    // Every tile keeps its place, the way the sidebar lists them: an overview you learn once.
    // What it costs a month: the kinds with a set price each (what use-billed kinds spent shows on their tiles).
    const total = kinds.filter((k) => k.billed === 'item').reduce((sum, k) => sum + (costs.kindMonthly[k.id] ?? 0), 0);
    return (
        <PageFrame
            title="Resources"
            description={costs.shown && total ? `What your account owns, what uses it, and what it costs: ${formatUsd(total)} a month.` : 'What your account owns, and what uses it.'}
        >
            {loading ? (
                <TileSkeletons count={kinds.length} />
            ) : (
                <div className={TILE_GRID} data-testid="resources-overview">
                    {kinds.map((k) => {
                        const KindIcon = k.icon;
                        const list = items[k.id];
                        const broken = list.filter((i) => i.attention).length;
                        const line = kindLine(k, list);
                        return (
                            <Tile
                                key={k.id}
                                mark={
                                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-foreground/[0.05]">
                                        <KindIcon className="h-5 w-5 text-foreground/75" strokeWidth={1.75} />
                                    </span>
                                }
                                title={k.label}
                                detail={broken ? <span className="text-red-600 dark:text-red-400">{broken} not reachable</span> : line}
                                label={`${k.label}: ${line}`}
                                onOpen={() => go(k.id, null, true)}
                                testId={`kind-tile-${k.id}`}
                                trailing={
                                    manualFor(k.id) && !list.length ? (
                                        <button
                                            type="button"
                                            onClick={(event) => {
                                                event.stopPropagation();
                                                manualFor(k.id)!.run();
                                            }}
                                            className="inline-flex h-8 shrink-0 items-center rounded-full px-3.5 text-[13px] font-medium text-foreground ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:ring-foreground/[0.14]"
                                        >
                                            {manualFor(k.id)!.short}
                                        </button>
                                    ) : (
                                        <KindPrice kind={k} costs={costs} />
                                    )
                                }
                            />
                        );
                    })}
                </div>
            )}
        </PageFrame>
    );
}
