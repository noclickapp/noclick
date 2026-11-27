// Resources: everything your agents and apps use, by kind. The overview is one
// tile per kind the account has, with how many, then the kinds it can add;
// `/resources/<kind>` is that kind's list, with the user facet (`?user=`,
// default every user), a drawer and its actions; `/resources/<kind>/<page>` is
// one of the kind's own pages (card issuing, funding the cards).
import type { ReactNode } from 'react';
import { ALL_USERS, Connection } from 'noclick';
import { formatCount } from '@/screens/console/lib/format';
import { Tile } from '@/ui/Tile';
import { cn } from '@/ui/utils';
import { useAccount, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useUserParam } from '@/screens/console/hooks/useQueryState';
import { defaultWriteUser } from '@/screens/console/lib/userFilter';
import { useV1 } from '@/sdk/useV1';
import type { ConsolePageProps } from '../sections';
import { ConnectionsTable } from '../connections';
import { NewInCode } from '../NewInCode';
import { AREAS, kindLead, visibleKinds, type ResourceKind, type ResourceKindId } from '../resourceKinds';
import { DesignedTag } from '../ui/DesignedTag';
import { ErrorPanel } from '../ui/ErrorPanel';
import { PageHeader, PageSection } from '../ui/PageHeader';
import { AppsPanel } from './resources/AppsPanel';
import { BrowserProfilesPanel } from './resources/BrowserProfilesPanel';
import { CardsFundingPage } from './resources/CardsFunding';
import { CardsOnboardingPage } from './resources/CardsOnboarding';
import { CardsPanel } from './resources/CardsPanel';
import { ChannelsPanel } from './resources/ChannelsPanel';
import { DatabasesPanel } from './resources/DatabasesPanel';
import { DictsPanel } from './resources/DictsPanel';
import { DomainsPanel } from './resources/DomainsPanel';
import { InboxesPanel } from './resources/InboxesPanel';
import { MachinesPanel } from './resources/MachinesPanel';
import { PhoneNumbersPanel } from './resources/PhoneNumbersPanel';
import { QueuesPanel } from './resources/QueuesPanel';
import { ReposPanel } from './resources/ReposPanel';
import { SandboxesPanel } from './resources/SandboxesPanel';
import { SecretsPanel } from './resources/SecretsPanel';
import { StoragePanel } from './resources/StoragePanel';
import { VolumesPanel } from './resources/VolumesPanel';
import { PanelToolbar, type PanelProps } from './resources/shared';

function ConnectionsPanel({ user, setUser }: PanelProps) {
    return (
        <>
            <PanelToolbar user={user} setUser={setUser} action={<NewInCode kind="connection" place={{ user: defaultWriteUser(user) }} />} />
            <ConnectionsTable
                key={user}
                userFilter={user}
                showUser
                empty="No connections yet. Your code creates them with Connection.from_name, or an agent asks its user for one."
            />
        </>
    );
}

/** A page under a kind's list, at `/resources/<kind>/<id>`. */
interface KindPage {
    id: string;
    label: string;
    /** The sentence under its title. */
    what: string;
    Page: () => ReactNode;
}

const PANELS: Record<ResourceKindId, (props: PanelProps) => ReactNode> = {
    connections: ConnectionsPanel,
    phone: PhoneNumbersPanel,
    inboxes: InboxesPanel,
    channels: ChannelsPanel,
    sandboxes: SandboxesPanel,
    machines: MachinesPanel,
    apps: AppsPanel,
    repos: ReposPanel,
    'browser-profiles': BrowserProfilesPanel,
    databases: DatabasesPanel,
    storage: StoragePanel,
    volumes: VolumesPanel,
    dicts: DictsPanel,
    queues: QueuesPanel,
    secrets: SecretsPanel,
    domains: DomainsPanel,
    cards: CardsPanel,
};

const KIND_PAGES: Partial<Record<ResourceKindId, readonly KindPage[]>> = {
    cards: [
        {
            id: 'onboarding',
            label: 'Turn on card issuing',
            what: 'Your company applies once, with the card issuer, before it can issue cards. Card issuing is for US-registered businesses.',
            Page: CardsOnboardingPage,
        },
        {
            id: 'funding',
            label: 'Fund your cards',
            what: "Every card spends from your company's card balance, which you fund by bank transfer.",
            Page: CardsFundingPage,
        },
    ],
};

/** Connections aren't in the account's counts: one read of the first page says whether there are any. */
function useConnectionCount() {
    const { client } = useConsole();
    return useV1('connections?overview', () => Connection.listPage({ client, userFilter: ALL_USERS, limit: 100 }));
}

/** How many of a kind the account has: a number and its line, `undefined` while unknown. */
type Tally = { count: number; line: string } | undefined;

/** The kinds in use: two to a row on a phone, where each tile is its name and count alone. */
const USED_GRID = 'grid grid-cols-2 gap-2.5 lg:grid-cols-3 xl:grid-cols-4';
/** The kinds to add, each a line on what it is. */
const MORE_GRID = 'grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3';

/** The kind's glyph, bare, in the sidebar's line family. */
function KindGlyph({ kind, quiet = false, className }: { kind: ResourceKind; quiet?: boolean; className?: string }) {
    const Icon = kind.icon;
    return <Icon aria-hidden className={cn('h-5 w-5 shrink-0', quiet ? 'text-muted-foreground' : 'text-foreground/75', className)} strokeWidth={1.75} />;
}

function Overview() {
    const href = useConsoleHref();
    const { lab } = useConsole();
    const account = useAccount();
    const connections = useConnectionCount();
    const tally = (kind: ResourceKind): Tally => {
        if (kind.inUse) return account.data ? kind.inUse(account.data) : undefined;
        if (!connections.data) return undefined;
        const n = connections.data.data.length;
        return { count: n, line: `${formatCount(n)}${connections.data.nextCursor ? '+' : ''} ${n === 1 && !connections.data.nextCursor ? 'connection' : 'connections'}` };
    };
    const kinds = visibleKinds(lab).map((kind) => ({ kind, tally: tally(kind) }));
    // A kind is in use once its count says so; one that couldn't be counted stays among them, never shown as none.
    const failed = (account.error !== undefined && !account.data) || (connections.error !== undefined && !connections.data);
    const loading = !failed && kinds.some((k) => k.tally === undefined);
    const used = kinds.filter((k) => !k.tally || k.tally.count > 0);
    const rest = kinds.filter((k) => k.tally && k.tally.count === 0);
    return (
        <>
            <PageHeader section="resources" />
            {failed && (
                <ErrorPanel
                    error={account.error ?? connections.error}
                    onRetry={() => {
                        void account.refresh();
                        void connections.refresh();
                    }}
                    className="mb-8"
                />
            )}
            {loading ? (
                <div aria-busy className={USED_GRID}>
                    {Array.from({ length: 8 }, (_, i) => (
                        <span key={i} className="h-[66px] animate-pulse rounded-2xl bg-foreground/[0.04]" />
                    ))}
                </div>
            ) : (
                <>
                    {used.length > 0 && (
                        <PageSection title="In use">
                            <ByArea label="In use" kinds={used.map((u) => u.kind)} grid={USED_GRID}>
                                {(kind) => {
                                    const tally = used.find((u) => u.kind === kind)?.tally;
                                    return (
                                        <Tile
                                            href={href(`resources/${kind.id}`)}
                                            mark={<KindGlyph kind={kind} className="hidden sm:block" />}
                                            title={kind.label}
                                            detail={tally ? <span className="tabular-nums text-foreground/75">{tally.line}</span> : 'Count unavailable'}
                                            label={`${kind.label}: ${tally?.line ?? 'count unavailable'}`}
                                            className="h-full"
                                        />
                                    );
                                }}
                            </ByArea>
                        </PageSection>
                    )}
                    {rest.length > 0 && <MoreKinds kinds={rest.map((r) => r.kind)} first={!used.length && !failed} />}
                </>
            )}
        </>
    );
}

/** Kinds under their area's name, each area a grid of its own, in the areas' order. */
function ByArea({ label, kinds, grid, children }: { label: string; kinds: ResourceKind[]; grid: string; children: (kind: ResourceKind) => ReactNode }) {
    return (
        <div className="flex flex-col gap-6">
            {AREAS.map((area) => {
                const inArea = kinds.filter((k) => k.area === area);
                if (!inArea.length) return null;
                return (
                    <div key={area}>
                        <h3 className="m-0 mb-2.5 text-[13px] font-medium text-foreground/75 dark:text-muted-foreground">{area}</h3>
                        <ul aria-label={`${label}: ${area}`} className={cn('m-0 list-none p-0', grid)}>
                            {inArea.map((kind) => (
                                <li key={kind.id} className="min-w-0">
                                    {children(kind)}
                                </li>
                            ))}
                        </ul>
                    </div>
                );
            })}
        </div>
    );
}

/** The kinds the account hasn't used yet, by area: each one a line on what it is. */
function MoreKinds({ kinds, first }: { kinds: ResourceKind[]; first: boolean }) {
    const href = useConsoleHref();
    const title = first ? 'What you can use' : 'More you can add';
    return (
        <PageSection title={title} note="Each one is made from your code, or from its page here.">
            <ByArea label={title} kinds={kinds} grid={MORE_GRID}>
                {(kind) => (
                    <Tile
                        href={href(`resources/${kind.id}`)}
                        mark={<KindGlyph kind={kind} quiet />}
                        title={kind.label}
                        detail={kind.what}
                        wrapDetail
                        label={kind.label}
                        className="h-full items-start"
                    />
                )}
            </ByArea>
        </PageSection>
    );
}

export default function Resources({ rest }: ConsolePageProps) {
    const href = useConsoleHref();
    const { lab } = useConsole();
    const [user, setUser] = useUserParam();
    if (!rest[0]) return <Overview />;
    const crumbs = [{ label: 'Resources', href: href('resources') }];
    const kind = visibleKinds(lab).find((k) => k.id === rest[0]);
    if (!kind) return <PageHeader crumbs={crumbs} title="Not found" purpose={`There's no resource called "${rest[0]}".`} />;
    // Only the lab lists a designed kind, and its pages say that they are designs.
    const designed = kind.designed ? <DesignedTag what="this kind" /> : undefined;
    if (rest[1]) {
        const kindCrumbs = [...crumbs, { label: kind.label, href: href(`resources/${kind.id}`) }];
        const page = KIND_PAGES[kind.id]?.find((p) => p.id === rest[1]);
        if (!page) return <PageHeader crumbs={kindCrumbs} title="Not found" purpose={`${kind.label} has no page called "${rest[1]}".`} />;
        const { Page } = page;
        return (
            <>
                <PageHeader crumbs={kindCrumbs} title={page.label} purpose={page.what} chips={designed} />
                <Page />
            </>
        );
    }
    const Panel = PANELS[kind.id];
    return (
        <>
            <PageHeader crumbs={crumbs} title={kind.label} purpose={kindLead(kind)} chips={designed} />
            <Panel user={user} setUser={setUser} />
        </>
    );
}
