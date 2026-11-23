// What a platform item's page shows under its facts, read from the platform
// API: a domain's website and DNS records, an email address's mail, a repo's
// files at a branch, a database's tables and rows, a bucket's files, an app's
// domains, requests, monthly budget, Durable Objects, deployments and log. Built from the Resources page's own pieces, so these pages look
// like every other resource's.
import { createContext, lazy, Suspense, useContext, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { useReportHeld } from '@/sdk/held';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { AlertCircle, Check, Clock, Plus } from 'lucide-react';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import type { ResourceItem } from './model';
import { usePlatformResources } from './platform';
import { DnsRecords } from './ResourceDetail';
import { ConfirmAction, Section, Surface, useResourceLink } from './ui';
import { UseForWebsiteDialog, useWebsitesFor } from './UseForWebsite';
import { Skeleton } from '@/ui/skeleton';
import { cn } from '@/ui/utils';
import { servedNames, stopServing, type ServedName } from '@/screens/console/pages/resources/appDomains';
import type { Bucket, Database, Domain, Inbox, Project, Repo } from 'noclick';
import type { DeletePreview } from './durableObjects';
import { domainRecords, freeForWebsite, repoReader, repoSummary, servingRefusal, servingState, type ServingState } from './items';
import { AddDomainDialog } from './AddDomainDialog';
import { AppDeployments, AppLog } from './AppActivity';
import { AppAnalytics } from './AppAnalytics';
import { AppBudget } from './AppBudget';
import { AppDurableObjects } from './AppDurableObjects';
import { BucketBody } from './BucketBody';
import { DatabaseBody } from './DatabaseBody';
import { MailBody } from './MailBody';
import { ROW } from './parts';

/** The SDK object behind a listed platform item. */
export type PlatformObject = Domain | Inbox | Project | Database | Bucket | Repo;

/** The SDK object behind each listed item, by its id, and the account's domains and apps. */
export const PlatformObjects = createContext<{
    byId: ReadonlyMap<string, PlatformObject>;
    domains: readonly Domain[];
    projects: readonly Project[];
    /** What the platform says `DELETE path` would do, asked as `user` (null: the account). */
    previewDeletion: DeletePreview;
}>({
    byId: new Map(),
    domains: [],
    projects: [],
    previewDeletion: () => Promise.reject(new Error('Deletions are previewed by the platform, which isn’t here.')),
});

/** One name a website is served at: what it is, where it stands, and what can be done about it. */
const STEP_LOOK = {
    live: { Icon: Check, tone: 'text-foreground/85' },
    certificate: { Icon: Clock, tone: 'text-muted-foreground' },
    waiting: { Icon: Clock, tone: 'text-muted-foreground' },
    attention: { Icon: AlertCircle, tone: 'text-red-600 dark:text-red-400' },
} as const;

function ServedRow({ title, state, action }: { title: ReactNode; state: ServingState; action?: ReactNode }) {
    const { Icon, tone } = STEP_LOOK[state.step];
    return (
        <div className={cn(ROW, 'flex-wrap')} data-testid="served-name">
            <span className="min-w-0 flex-1 basis-56">
                <span className="block truncate text-[14px] text-foreground">{title}</span>
                <span className={cn('block text-[12.5px]', state.step === 'attention' ? tone : 'text-muted-foreground')}>{state.detail}</span>
            </span>
            {/* Under the name on a phone: the status at the left, the action at the right. */}
            <span className="flex w-full items-center justify-between gap-3 sm:w-auto sm:shrink-0">
                <span className={cn('flex items-center gap-1 text-[12.5px]', tone)}>
                    <Icon className="h-3.5 w-3.5" />
                    {state.words}
                </span>
                {action}
            </span>
        </div>
    );
}

/** What the domain shows: the websites at its names, or a way to put one there. */
function DomainWebsite({ domain }: { domain: Domain }) {
    const apps = useWebsitesFor(domain.name);
    const { projects } = useContext(PlatformObjects);
    const link = useResourceLink();
    const [using, setUsing] = useState(false);
    // Every app is listed (an account holds at most a page of them), its users' at names under it included.
    const served = projects.flatMap((project) => servedNames([domain], project.id).map((name) => ({ project, name })));
    return (
        <Section
            title="Website"
            action={
                freeForWebsite(domain) && apps.length > 0 ? (
                    <button type="button" className={BUTTON_SECONDARY} onClick={() => setUsing(true)}>
                        Use for a website
                    </button>
                ) : undefined
            }
        >
            {served.length ? (
                <Surface>
                    {served.map(({ project, name }) => (
                        <ServedRow
                            key={name.hostname}
                            title={
                                <>
                                    <Link to={{ search: link('apps', project.id) }} className="hover:underline">
                                        {project.name}
                                    </Link>
                                    {name.hostname !== domain.name && <span className="text-muted-foreground"> at {name.hostname}</span>}
                                </>
                            }
                            state={servingState(name, project)}
                        />
                    ))}
                </Surface>
            ) : (
                <p className="text-[13.5px] text-muted-foreground">
                    {apps.length ? `${domain.name} doesn’t show a website yet.` : `${domain.name} doesn’t show a website yet. Once you have one, you can put it here.`}
                </p>
            )}
            <UseForWebsiteDialog domain={domain.name} open={using} onOpenChange={setUsing} />
        </Section>
    );
}

function DomainBody({ domain }: { domain: Domain }) {
    const records = domainRecords(domain);
    return (
        <>
            <DomainWebsite domain={domain} />
            {records.length > 0 && <DnsRecords records={records} title={domain.noClickDns ? 'DNS records' : 'Records to add where its DNS is hosted'} />}
        </>
    );
}

/** The domains a website is served at, each with where it stands; one added, or one removed after a confirm. */
function AppDomains({ project }: { project: Project }) {
    const platform = usePlatformResources();
    const { domains } = useContext(PlatformObjects);
    const link = useResourceLink();
    const [adding, setAdding] = useState(false);
    const served = servedNames(domains, project.id);
    const unread = platform?.errors.domains;
    const reportHeld = useReportHeld(useContext(ConsoleContext));
    const remove = async (name: ServedName) => {
        try {
            await stopServing(project, name, 'resources:');
            toast.success(`Your site is no longer at ${name.stops.join(' and ')}`, { description: `${name.domain.name} stays yours.` });
        } catch (error) {
            if (reportHeld(error, `Stop serving your site at ${name.stops.join(' and ')}`)) return;
            toast.error(servingRefusal(error));
        }
    };
    return (
        <Section
            title="Domains"
            meta={served.length || undefined}
            action={
                <button type="button" className={BUTTON_SECONDARY} onClick={() => setAdding(true)}>
                    <Plus className="h-4 w-4" />
                    Add domain
                </button>
            }
        >
            {unread ? (
                <p role="alert" className="text-[13.5px] text-muted-foreground">
                    {unread}{' '}
                    <button type="button" onClick={() => platform?.refresh()} className="font-medium text-foreground underline underline-offset-4">
                        Try again
                    </button>
                </p>
            ) : served.length ? (
                <Surface>
                    {served.map((name) => (
                        <ServedRow
                            key={name.hostname}
                            title={
                                <Link to={{ search: link('domains', name.domain.id) }} className="hover:underline">
                                    {name.hostname}
                                </Link>
                            }
                            state={servingState(name, project)}
                            action={<ConfirmAction quiet label="Remove" confirm="Stop using it" onConfirm={() => remove(name)} />}
                        />
                    ))}
                </Surface>
            ) : (
                <p className="text-[13.5px] text-muted-foreground">Your site is at {project.hostname}. Add a domain to show it at an address of your own too.</p>
            )}
            <AddDomainDialog project={project} domains={domains} open={adding} onOpenChange={setAdding} />
        </Section>
    );
}

function AppBody({ project, now }: { project: Project; now: string }) {
    const { previewDeletion } = useContext(PlatformObjects);
    return (
        <>
            <AppDomains project={project} />
            <AppAnalytics project={project} />
            <AppBudget project={project} />
            <AppDurableObjects project={project} preview={previewDeletion} />
            <AppDeployments project={project} now={now} />
            <AppLog project={project} />
        </>
    );
}

// The code browser carries the syntax highlighter and every language it reads, so it loads when a repo is opened,
// not with Resources (registering the languages alone held the page's first open for a third of a second at 4x CPU).
const RepoBrowser = lazy(() => import('./RepoBrowser').then((m) => ({ default: m.RepoBrowser })));

function RepoBody({ repo, now }: { repo: Repo; now: string }) {
    const reader = useMemo(() => repoReader(repo), [repo]);
    return (
        <Suspense fallback={<Skeleton className="h-64 w-full rounded-2xl" />}>
            <RepoBrowser reader={reader} name={repo.name} summary={repoSummary(repo)} now={now} />
        </Suspense>
    );
}

export function PlatformBody({ item, now }: { item: ResourceItem; now: string }) {
    const object = useContext(PlatformObjects).byId.get(item.id);
    if (!object) return null;
    switch (item.kind) {
        case 'domains':
            return <DomainBody domain={object as Domain} />;
        case 'email':
            return <MailBody inbox={object as Inbox} now={now} />;
        case 'apps':
            return <AppBody project={object as Project} now={now} />;
        case 'databases':
            return <DatabaseBody database={object as Database} />;
        case 'storage':
            return <BucketBody bucket={object as Bucket} now={now} />;
        case 'repos':
            return <RepoBody repo={object as Repo} now={now} />;
        default:
            return null;
    }
}
