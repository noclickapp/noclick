// Resources: the app's own page (src/screens/resources), drawn in the console's frame, so what the account owns and
// what it costs reads the same wherever it's looked at; under its tiles, the kinds only code makes. A kind the console
// has a page of its own for (its user facet, IDs and actions) opens there: `/resources/<kind>` is that kind's list,
// with the user facet (`?user=`, default every user), a drawer and its actions; `/resources/<kind>/<page>` is one of
// the kind's own pages (card issuing, funding the cards).
import { useMemo, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { InHostFrame } from '@/ui/PageFrame';
import { Tile, TILE_GRID } from '@/ui/Tile';
import { ResourcesContext, type ResourcesContextValue } from '@/screens/resources/context';
import type { KindId } from '@/screens/resources/kinds';
import { ResourcesView } from '@/screens/resources/ResourcesPage';
import { ResourcesReads } from '@/screens/resources/reads';
import { useAccount, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useUserParam } from '@/screens/console/hooks/useQueryState';
import { defaultWriteUser } from '@/screens/console/lib/userFilter';
import type { ConsolePageProps } from '../sections';
import { ConnectionsTable } from '../connections';
import { NewInCode } from '../NewInCode';
import { kindLead, visibleKinds, type ResourceKind, type ResourceKindId } from '../resourceKinds';
import { DesignedTag } from '../ui/DesignedTag';
import { PageHeader } from '../ui/PageHeader';
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

/** The app's kinds the console has a page of its own for, opened there; an agent opens on the console's Home. */
const CONSOLE_PAGES: Partial<Record<KindId, string>> = {
    agents: '',
    numbers: 'resources/phone',
    email: 'resources/inboxes',
    apps: 'resources/apps',
    databases: 'resources/databases',
    storage: 'resources/storage',
    machines: 'resources/machines',
    secrets: 'resources/secrets',
    repos: 'resources/repos',
    domains: 'resources/domains',
};

const SHOWN_IN_APP = new Set(Object.values(CONSOLE_PAGES).map((path) => path.split('/')[1]));

/** The console's kinds the app's page doesn't list: what only your code makes (designed ones in the lab). */
function codeMadeKinds(lab: boolean): readonly ResourceKind[] {
    return visibleKinds(lab).filter((kind) => !SHOWN_IN_APP.has(kind.id));
}

function CodeMade() {
    const href = useConsoleHref();
    const { lab } = useConsole();
    const account = useAccount().data;
    return (
        <section aria-label="Only your code makes these" className="mt-10">
            <h2 className="m-0 mb-3 text-[15px] font-semibold text-foreground">Only your code makes these</h2>
            <div className={TILE_GRID}>
                {codeMadeKinds(lab).map((kind) => {
                    const Icon = kind.icon;
                    const line = kind.inUse && account ? kind.inUse(account).line : kind.what;
                    return (
                        <Tile
                            key={kind.id}
                            href={href(`resources/${kind.id}`)}
                            mark={
                                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-foreground/[0.05]">
                                    <Icon aria-hidden className="h-5 w-5 text-foreground/75" strokeWidth={1.75} />
                                </span>
                            }
                            title={kind.label}
                            detail={line}
                            label={`${kind.label}: ${line}`}
                            testId={`code-kind-tile-${kind.id}`}
                        />
                    );
                })}
            </div>
        </section>
    );
}

/** The overview: the app's Resources, its kinds the console has a page for opening there, and what only code makes
 *  under its tiles, laid out in the console's own frame as its other pages are. */
function Overview() {
    const navigate = useNavigate();
    const href = useConsoleHref();
    const { country } = useConsole();
    const value = useMemo<ResourcesContextValue>(
        () => ({
            billing: true,
            country,
            openKind: (kind) => {
                const page = CONSOLE_PAGES[kind];
                if (page === undefined) return false;
                navigate(href(page));
                return true;
            },
            more: <CodeMade />,
        }),
        [country, navigate, href]
    );
    return (
        <InHostFrame.Provider value>
            <ResourcesContext.Provider value={value}>
                <ResourcesReads>
                    <ResourcesView />
                </ResourcesReads>
            </ResourcesContext.Provider>
        </InHostFrame.Provider>
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
