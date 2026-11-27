// Apps: a repo deployed to a URL, on the edge or container runtime, or an
// automation's interface NoClick published. The table shows each app's
// production deployment; the drawer (`?app=`, its tab in `?tab=`) holds the
// app's deployments, domains, bindings, secrets, schedules, logs and services,
// with Deploy, Export and Move to trash; the apps in the trash list under the
// table, each restorable or purged. A published interface has no code of its
// own: its drawer keeps its deployments, domains and logs, and its automation
// publishes and unpublishes it.
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { ALL_USERS, NO_USER, Project, TrashItem } from 'noclick';
import { NEW_SNIPPETS } from '@/screens/console/lib/snippets';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { TrashSection } from '@/screens/resources/TrashSection';
import type { TrashEntry } from '@/screens/resources/platform';
import { AppDurableObjectsSection } from './AppsDurableObjects';
import { NewInCode } from '../../NewInCode';
import { ConsoleButton } from '../../ui/Button';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { PillSwitch } from '../../ui/PillTabs';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { AppServicesSection } from './AppServicesSection';
import { AppBindings, AppSchedules, AppSecrets, AppSettings } from './AppsConfig';
import { AppDeployments, useDeploy } from './AppsDeployments';
import { deploymentLook, NOT_DEPLOYED, withParams } from './AppsFormat';
import { AppUrl } from './AppsParts';
import { AppDomains, AppLogs, AppOverview, useAppUsage } from './AppsOverview';
import { ConfirmAction, errorText, PanelToolbar, type PanelProps } from './shared';

const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'deployments', label: 'Deployments' },
    { id: 'domains', label: 'Domains' },
    { id: 'bindings', label: 'Bindings' },
    { id: 'secrets', label: 'Environment' },
    { id: 'schedules', label: 'Schedules' },
    { id: 'logs', label: 'Logs' },
    { id: 'services', label: 'Services' },
] as const;

type TabId = (typeof TABS)[number]['id'];

/** What a published interface's drawer shows: it has no code, so nothing to bind, configure or schedule. */
const PUBLISHED_TABS: readonly TabId[] = ['overview', 'deployments', 'domains', 'logs'];

function AppFooter({ project, onDeleted }: { project: Project; onDeleted: () => void }) {
    if (project.published) {
        return <span className="text-[13px] text-muted-foreground">Its automation publishes it: publish it again or unpublish it from the automation’s Interface tab.</span>;
    }
    return <RepoAppFooter project={project} onDeleted={onDeleted} />;
}

function RepoAppFooter({ project, onDeleted }: { project: Project; onDeleted: () => void }) {
    const { deploy, busy } = useDeploy(project);
    const [exporting, setExporting] = useState(false);
    const exportApp = async () => {
        setExporting(true);
        try {
            await project.export();
            toast('Export started. The bundle link appears in Logs when it’s ready.');
        } catch (e) {
            toast(errorText(e));
        } finally {
            setExporting(false);
        }
    };
    return (
        <>
            <ConsoleButton variant="primary" disabled={busy} onClick={() => void deploy({})}>
                {busy ? 'Deploying…' : `Deploy ${project.productionBranch}`}
            </ConsoleButton>
            <ConsoleButton disabled={exporting} onClick={() => void exportApp()}>
                Export
            </ConsoleButton>
            <span className="flex-1" />
            <ConfirmAction
                label="Move to trash"
                title={`Move ${project.name} to the trash?`}
                description="It goes offline at once. Its releases, deployments, schedules, secrets and bindings are kept, and its domains remembered: restoring it within 30 days serves it again where it was, with no build. The repo, databases and buckets it used are kept."
                confirmLabel="Move to trash"
                onConfirm={async () => {
                    await project.delete();
                    invalidateV1('projects');
                    invalidateV1('trash');
                    invalidateV1('account');
                    toast(`Moved ${project.name} to the trash`);
                    onDeleted();
                }}
            />
        </>
    );
}

function AppDrawer({ appId, row, onClose }: { appId: string | null; row?: Project; onClose: () => void }) {
    const { client } = useConsole();
    const [params, setParams] = useSearchParams();
    const tab = params.get('tab');
    const setTab = (id: string) => setParams((prev) => withParams(prev, { tab: id === 'overview' ? null : id, deployment: null }), { replace: true, preventScrollReset: true });
    const fetched = useV1(appId && !row ? `projects/${appId}` : null, () => Project.get(appId!, { client }));
    const project = row ?? fetched.data;
    const tabs = project?.published ? TABS.filter((t) => PUBLISHED_TABS.includes(t.id)) : TABS;
    const active: TabId = tabs.some((t) => t.id === tab) ? (tab as TabId) : 'overview';
    useEffect(() => {
        if (project) recordRecent({ type: 'app', id: project.id, label: project.name, path: 'resources/apps', params: { app: project.id } });
    }, [project?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const production = project?.production;
    // What's wrong leads: an app whose paid calls are failing says so in its header, not only in its Overview.
    const usage = useAppUsage(project);
    const look = usage.data?.limitedBy
        ? ({ label: 'Paid calls failing', reason: usage.data.limitedBy === 'project' ? 'budget used up' : usage.data.limitedBy === 'user' ? 'user cap' : 'balance', glyph: 'cross', tone: 'failure' } as const)
        : production
          ? deploymentLook(production)
          : NOT_DEPLOYED;
    return (
        <Drawer
            open={appId !== null}
            onOpenChange={(open) => !open && onClose()}
            kind="app"
            wide
            title={project?.name}
            id={appId ?? undefined}
            status={project ? <StatusPill look={look} /> : undefined}
            footer={project ? <AppFooter project={project} onDeleted={onClose} /> : undefined}
        >
            {!project && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!project && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {project && (
                <div className="flex flex-col gap-5">
                    <PillSwitch label="App" tabs={tabs} value={active} onChange={setTab} />
                    {active === 'overview' && <AppOverview project={project} usage={usage} />}
                    {active === 'deployments' && <AppDeployments project={project} />}
                    {active === 'domains' && <AppDomains project={project} />}
                    {active === 'bindings' && (
                        <div className="flex flex-col gap-6">
                            <AppBindings project={project} />
                            <AppDurableObjectsSection project={project} />
                        </div>
                    )}
                    {active === 'secrets' && (
                        <div className="flex flex-col gap-6">
                            <AppSettings project={project} />
                            <AppSecrets project={project} />
                        </div>
                    )}
                    {active === 'schedules' && <AppSchedules project={project} />}
                    {active === 'logs' && <AppLogs project={project} />}
                    {active === 'services' && <AppServicesSection project={project} />}
                </div>
            )}
        </Drawer>
    );
}

/** The apps in the trash the page's user filter shows, each restorable or purged now. */
function AppsTrash({ user }: { user: string }) {
    const { client } = useConsole();
    const [now] = useState(() => new Date().toISOString());
    const trash = useV1('trash?project', () => TrashItem.list({ client, kind: 'project' }));
    const shown = (trash.data ?? []).filter((t) => user === ALL_USERS || (user === NO_USER ? !t.userId : t.userId === user));
    if (!shown.length) return null;
    const entries: TrashEntry[] = shown.map((t) => ({
        id: t.id,
        name: t.name ?? t.resourceId,
        trashedAt: t.trashedAt?.toISOString() ?? null,
        purgeAfter: t.purgeAfter?.toISOString() ?? null,
    }));
    const act = (done: string, action: (item: TrashItem) => Promise<unknown>) => async (entry: TrashEntry) => {
        try {
            await action(TrashItem.fromId(entry.id, { client, user: null }));
        } catch (error) {
            throw new Error(errorText(error));
        }
        invalidateV1('trash');
        invalidateV1('projects');
        invalidateV1('account');
        toast(`${done} ${entry.name}`);
    };
    return <TrashSection entries={entries} now={now} onRestore={act('Restored', (item) => item.restore())} onPurge={act('Purged', (item) => item.purge())} />;
}

export function AppsPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const [appId, setApp] = useSearchParam('app');
    const [, setParams] = useSearchParams();
    const place = { user: defaultWriteUser(user) };
    const paged = usePaged(`projects?${user}`, (cursor) => Project.listPage({ client, userFilter: user, cursor, limit: 50 }), (p) => p.id);
    const columns: Column<Project>[] = [
        {
            id: 'name',
            header: 'App',
            cell: (p) => (
                <span className="flex min-w-0 flex-col">
                    <span className="truncate font-medium text-foreground">{p.name}</span>
                    {p.workflow?.name && <span className="truncate text-[12px] text-muted-foreground">Built in {p.workflow.name}</span>}
                </span>
            ),
        },
        {
            id: 'url',
            header: 'URL',
            priority: 2,
            cell: (p) => <AppUrl url={p.url} />,
        },
        {
            id: 'production',
            header: 'Production',
            width: '9.5rem',
            cell: (p) => <StatusPill look={p.production ? deploymentLook({ status: p.production.status }) : NOT_DEPLOYED} />,
        },
        {
            id: 'deployed',
            header: 'Deployed',
            priority: 2,
            width: '6.5rem',
            cell: (p) => <TimeCell value={p.production?.createdAt} />,
        },
        {
            id: 'domains',
            header: 'Domains',
            priority: 3,
            cell: (p) =>
                p.domainNames.length ? (
                    <span className="truncate font-mono text-[12px]" title={p.domainNames.join(', ')}>
                        {p.domainNames.join(', ')}
                    </span>
                ) : (
                    <span className="text-muted-foreground">—</span>
                ),
        },
        {
            id: 'user',
            header: 'User',
            priority: 2,
            width: '8rem',
            cell: (p) => <span className={p.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(p.userId)}</span>,
        },
    ];
    const close = () => setParams((prev) => withParams(prev, { app: null, tab: null, deployment: null }), { replace: true, preventScrollReset: true });
    return (
        <>
            <PanelToolbar user={user} setUser={setUser} action={<NewInCode kind="app" place={place} />} />
            <DataTable
                rowMenu="app"
                label="Apps"
                columns={columns}
                rows={paged.rows}
                getRowId={(p) => p.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(p) => setApp(p.id, { push: true })}
                selectedId={appId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No apps yet." hint="An app deploys a repo to a URL, with previews, domains, secrets and schedules." snippet={NEW_SNIPPETS.app(place)} />}
            />
            <AppsTrash user={user} />
            <AppDrawer appId={appId} row={paged.rows.find((p) => p.id === appId)} onClose={close} />
        </>
    );
}
