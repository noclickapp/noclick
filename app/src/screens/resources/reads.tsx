// Resources' platform kinds: every domain, email address, app, database, bucket and repo the account holds and pays
// for, its own and its users' (`user_id=all`; a user's is marked with that user, by name), read from the platform API,
// and its websites put on its domains. The client comes from the console's context the page is drawn in; a user's
// object acts for its user (the SDK sends its `user_id` as NoClick-User), so its page reads and changes it as that
// user's own calls would. The reads are cached: a frame about a moved resource makes its reads stale
// (ConsoleProviders), and while something is still settling (a domain, a deploy, a name's certificate) its list is read
// again only as a slow backstop. Work's kinds (agents, skills, memories, machines, secrets) are read beside them
// (workKinds.tsx), and the account's numbers and what a host adds (MORE_KINDS) come through their slots.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ALL_USERS, Bucket, Database, Domain, Inbox, Project, Repo, TrashItem, Usage, User, usage, type UsageSeries } from 'noclick';
import { serveAppAt } from '@/screens/console/pages/resources/appDomains';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { useSlot } from '@/slots';
import { BACKSTOP_POLL_MS } from '@/sdk/staleReads';
import { invalidateV1, useV1, type V1State } from '@/sdk/useV1';
import { KINDS, type KindId } from './kinds';
import type { ResourceItem } from './model';
import { PlatformResourcesContext, type PlatformResources } from './platform';
import { MORE_KINDS, NUMBERS, type MoreKinds, type NumbersRead } from './slots';
import { useAppsWeek } from './useAppTraffic';
import { WorkKinds } from './workKinds';
import {
    SETTLING_DOMAIN_STATUSES,
    appItem,
    awaitingCertificate,
    bucketItem,
    databaseItem,
    deletePreviewer,
    domainItem,
    inboxItem,
    mailDomains,
    removalOf,
    repoItem,
    servingRefusal,
    trashByKind,
    withOwner,
} from './items';
import { platformRegistrar } from './registrar';
import { AppRequestsFigure } from './AppAnalytics';
import { PlatformBody, PlatformObjects, type PlatformObject } from './PlatformBody';

/** One page of each list is what Resources shows; the console pages past it. */
const LIST_LIMIT = 100;
/** A deploy of an app's production that hasn't settled. */
const BUILDING = new Set(['queued', 'building']);

/** What a spend type (`/v1/usage/series?group_by=type`'s line) has cost this month. */
const spentOn = (series: UsageSeries, type: string) => series.series.find((line) => line.id === type)?.totalUsd ?? 0;

/** Every website's requests this week, read once for all their rows, and only once a row asks. */
const AppsWeek = createContext<{ ask(): void; requests: ReadonlyMap<string, number> | undefined }>({ ask: () => undefined, requests: undefined });

/** A website's row: its requests this week, from the one read every row shares. */
function AppRowFigure({ item }: { item: ResourceItem }) {
    const project = useContext(PlatformObjects).byId.get(item.id);
    const week = useContext(AppsWeek);
    const isApp = item.kind === 'apps';
    useEffect(() => {
        if (isApp) week.ask();
    }, [isApp, week]);
    return isApp && project ? <AppRequestsFigure project={project as Project} requests={week.requests?.get(item.id)} /> : null;
}

/** Resources' reads around the page: the numbers and what a host adds read through their slots, Work's kinds, then
 *  the platform's. */
export function ResourcesReads({ children }: { children: ReactNode }) {
    const Numbers = useSlot(NUMBERS);
    const More = useSlot(MORE_KINDS);
    return (
        <Numbers>
            {(numbers) => (
                <WorkKinds>
                    {(work) => (
                        <More>
                            {(more) => (
                                <Reads numbers={numbers} work={work} more={more}>
                                    {children}
                                </Reads>
                            )}
                        </More>
                    )}
                </WorkKinds>
            )}
        </Numbers>
    );
}

function Reads({ numbers, work, more, children }: { numbers: NumbersRead; work: MoreKinds; more: MoreKinds; children: ReactNode }) {
    const { client } = useConsole();
    // A domain registering or waiting on DNS, an app deploying or a name of one getting its certificate: frames say when it moves; this is the backstop.
    const [settling, setSettling] = useState({ domains: false, apps: false });
    const backstop = (on: boolean) => ({ pollMs: on ? BACKSTOP_POLL_MS : undefined });

    const domains = useV1('resources:domains', () => Domain.listPage({ client, userFilter: ALL_USERS, limit: LIST_LIMIT }), backstop(settling.domains));
    const projects = useV1('resources:projects', () => Project.listPage({ client, userFilter: ALL_USERS, limit: LIST_LIMIT }), backstop(settling.apps));
    const databases = useV1('resources:databases', () => Database.listPage({ client, userFilter: ALL_USERS, limit: LIST_LIMIT }));
    const buckets = useV1('resources:buckets', () => Bucket.listPage({ client, userFilter: ALL_USERS, limit: LIST_LIMIT }));
    const repos = useV1('resources:repos', () => Repo.listPage({ client, userFilter: ALL_USERS, limit: LIST_LIMIT }));
    const inboxes = useV1('resources:inboxes', () => Inbox.listPage({ client, userFilter: ALL_USERS, limit: LIST_LIMIT }));
    // The account acting for itself lists every user's trash with its own.
    const trash = useV1('resources:trash', () => TrashItem.listPage({ client, limit: LIST_LIMIT }));
    // Who a user's item is for, by name: read beside the lists, so a row names them as it first shows.
    const users = useV1('resources:users', () => User.listPage({ client, limit: LIST_LIMIT }));
    // What each app spent this month, and what databases and storage did between them (neither is split per item).
    const appSpend = useV1('resources:usage/projects', () => usage({ client, groupBy: 'project' }));
    const [rowsAsked, setRowsAsked] = useState(false);
    const appsWeek = useAppsWeek(rowsAsked);
    const week = useMemo(
        () => ({ ask: () => setRowsAsked(true), requests: appsWeek.data ? new Map(appsWeek.data.apps.map((a) => [a.projectId, a.requests])) : undefined }),
        [appsWeek.data]
    );
    const typeSpend = useV1('resources:usage/types', () => Usage.series({ client, groupBy: 'type', userFilter: ALL_USERS }));

    const domainRows = domains.data?.data;
    const projectRows = projects.data?.data;
    const databaseRows = databases.data?.data;
    const bucketRows = buckets.data?.data;
    const repoRows = repos.data?.data;
    const inboxRows = inboxes.data?.data;
    useEffect(
        () =>
            setSettling({
                domains: !!domainRows?.some((d) => SETTLING_DOMAIN_STATUSES.has(d.status)),
                apps: !!projectRows?.some((p) => p.production && BUILDING.has(p.production.status)) || awaitingCertificate(domainRows ?? [], projectRows ?? []),
            }),
        [domainRows, projectRows]
    );
    useEffect(() => {
        if (trash.error !== undefined) console.warn('[resources] the trash failed:', trash.error);
        if (appSpend.error !== undefined) console.warn('[resources] app spend failed:', appSpend.error);
        if (typeSpend.error !== undefined) console.warn('[resources] spend by type failed:', typeSpend.error);
        if (appsWeek.error !== undefined) console.warn("[resources] the websites' requests failed:", appsWeek.error);
        if (users.error !== undefined) console.warn("[resources] the users' names failed:", users.error);
    }, [trash.error, appSpend.error, typeSpend.error, appsWeek.error, users.error]);

    // A user read beyond the first page (or before the names answer) is named by its id.
    const userRows = users.data?.data;
    const names = useMemo(() => new Map((userRows ?? []).flatMap((u): [string, string][] => (u.name ? [[u.id, u.name]] : []))), [userRows]);
    const registrar = useMemo(() => platformRegistrar(client), [client]);
    const previewDeletion = useMemo(() => deletePreviewer(client), [client]);
    const objects = useMemo(
        () => ({
            byId: new Map<string, PlatformObject>(
                [...(domainRows ?? []), ...(projectRows ?? []), ...(databaseRows ?? []), ...(bucketRows ?? []), ...(repoRows ?? []), ...(inboxRows ?? [])].map((o) => [o.id, o])
            ),
            domains: domainRows ?? [],
            projects: projectRows ?? [],
            previewDeletion,
        }),
        [domainRows, projectRows, databaseRows, bucketRows, repoRows, inboxRows, previewDeletion]
    );

    type Read = Pick<V1State<unknown>, 'data' | 'error' | 'loading'>;
    // Each kind's list and the read it's drawn from: a kind draws once that read answers, whatever the rest still
    // wait on. A failed read has answered: the kind says why rather than waiting on it.
    const reads: [KindId, Read][] = [
        ['domains', domains],
        ['email', inboxes],
        ['apps', projects],
        ['databases', databases],
        ['storage', buckets],
        ['repos', repos],
    ];
    // Work's kinds and what a host adds, each item drawn by the parts of whichever of them holds it.
    const owners = [work, more];
    const parts = (item: ResourceItem) => owners.find((owner) => owner.owns(item)) ?? null;
    const errors: Partial<Record<KindId, string>> = { ...work.errors, ...more.errors, ...(numbers.error ? { numbers: numbers.error } : {}) };
    const loading: Partial<Record<KindId, boolean>> = { numbers: numbers.loading };
    for (const owner of owners) for (const [kind, on] of Object.entries(owner.loading) as [KindId, boolean][]) loading[kind] ||= on;
    for (const [kind, read] of reads) {
        loading[kind] = read.loading;
        if (read.error !== undefined && read.data === undefined) errors[kind] = errorText(read.error);
    }
    const spent = appSpend.data;
    const listed = <T extends PlatformObject>(rows: T[] | undefined, item: (row: T) => ResourceItem) => (rows ?? []).map((row) => withOwner(item(row), row.userId, names));
    const own: Partial<Record<KindId, ResourceItem[]>> = {
        numbers: numbers.items,
        domains: listed(domainRows, domainItem),
        email: listed(inboxRows, inboxItem),
        apps: listed(projectRows, (p) => appItem(p, spent ? spent.group(p.id).usd : undefined)),
        databases: listed(databaseRows, databaseItem),
        storage: listed(bucketRows, bucketItem),
        repos: listed(repoRows, repoItem),
    };
    const value: PlatformResources = {
        // Each kind's own items, then Work's and a host's of it (an agent's workspace among the files).
        items: Object.fromEntries(KINDS.map((k) => [k.id, [...(own[k.id] ?? []), ...owners.flatMap((owner) => owner.items[k.id] ?? [])]])),
        loading,
        errors,
        spentThisMonth: typeSpend.data ? { databases: spentOn(typeSpend.data, 'databases'), storage: spentOn(typeSpend.data, 'storage') } : {},
        numberPrices: numbers.monthly,
        numberTransport: numbers.transport,
        refresh: () => {
            invalidateV1('resources:');
            numbers.refresh();
        },
        registrar,
        async serveApp(appId, domain) {
            const project = projectRows?.find((p) => p.id === appId);
            if (!project) throw new Error('That website isn’t here anymore.');
            try {
                await serveAppAt(project, domain, 'resources:');
            } catch (error) {
                throw new Error(servingRefusal(error));
            }
        },
        mailDomains: mailDomains(domainRows ?? []),
        async createAddress(localPart, domain) {
            try {
                const inbox = await Inbox.create({ client, localPart, domain: domain ?? undefined });
                // Listed before its page opens; its domain shows what it now serves.
                await inboxes.refresh();
                invalidateV1('resources:domains');
                return inbox.id;
            } catch (error) {
                throw new Error(errorText(error));
            }
        },
        Body: (props) => {
            const Own = parts(props.item)?.Body;
            return Own ? <Own {...props} /> : <PlatformBody {...props} />;
        },
        Actions: (props) => {
            const Own = parts(props.item)?.Actions;
            return Own ? <Own {...props} /> : null;
        },
        Create: { ...work.Create, ...more.Create },
        Empty: { ...work.Empty, ...more.Empty },
        Notice: { ...work.Notice, ...more.Notice },
        unavailable: { ...work.unavailable, ...more.unavailable },
        RowFigure: AppRowFigure,
        Lead: { ...work.Lead, ...more.Lead },
        Page: { ...work.Page, ...more.Page },
        RowMenu: { ...work.RowMenu, ...more.RowMenu },
        hasOwnParts: (item) => !!parts(item),
        trash: trashByKind(trash.data?.data ?? [], names),
        // A user's entry is restored or purged acting for that user, as its resource was deleted.
        async restore(entry) {
            try {
                await TrashItem.fromId(entry.id, { client, user: entry.owner?.id ?? null }).restore();
            } catch (error) {
                throw new Error(errorText(error));
            }
            // Back in its list, out of the trash.
            invalidateV1('resources:');
        },
        async purge(entry) {
            try {
                await TrashItem.fromId(entry.id, { client, user: entry.owner?.id ?? null }).purge();
            } catch (error) {
                throw new Error(errorText(error));
            }
            invalidateV1('resources:trash');
        },
        removal(item) {
            const host = parts(item);
            if (host) return host.removal?.(item) ?? null;
            const object = objects.byId.get(item.id);
            const removal = object ? removalOf(item.kind, object, previewDeletion) : null;
            if (!removal) return null;
            return {
                ...removal,
                async preview() {
                    try {
                        return await removal.preview();
                    } catch (error) {
                        throw new Error(errorText(error));
                    }
                },
                async run() {
                    try {
                        const result = await removal.run();
                        // Its list, and a domain's what-it-serves, read again.
                        invalidateV1('resources:');
                        return result;
                    } catch (error) {
                        throw new Error(errorText(error));
                    }
                },
            };
        },
    };

    return (
        <PlatformObjects.Provider value={objects}>
            <AppsWeek.Provider value={week}>
                <PlatformResourcesContext.Provider value={value}>{children}</PlatformResourcesContext.Provider>
            </AppsWeek.Provider>
        </PlatformObjects.Provider>
    );
}
