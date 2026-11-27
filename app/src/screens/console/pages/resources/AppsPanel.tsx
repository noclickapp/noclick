// Apps: a repo deployed to a URL, on the edge or container runtime, or an automation's interface NoClick published. The
// table shows each app's production deployment, and an app opens on a page of its own (`AppPage`); the apps in the
// trash list under the table, each restorable or purged. An address from when an app opened in a drawer here
// (`?app=`, its tab in `?tab=`, a deployment in `?deployment=`) opens that page.
import { useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { ALL_USERS, NO_USER, Project, TrashItem } from 'noclick';
import { NEW_SNIPPETS } from '@/screens/console/lib/snippets';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { TrashSection } from '@/screens/resources/TrashSection';
import type { TrashEntry } from '@/screens/resources/platform';
import { NewInCode } from '../../NewInCode';
import { DataTable, type Column } from '../../ui/DataTable';
import { EmptyCode } from '../../ui/EmptyCode';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { appPath, deploymentLook, NOT_DEPLOYED } from './AppsFormat';
import { AppUrl } from './AppsParts';
import { errorText, PanelToolbar, type PanelProps } from './shared';

/** The drawer's tabs, as the sections of the app's page they became. */
const TAB_SECTIONS: Record<string, string> = { deployments: 'deploys', domains: 'domains', bindings: 'bindings', secrets: 'environment', schedules: 'schedules', logs: 'logs', services: 'services' };

/** Where an address from the drawer opens on the app's page: its deployment drawer, or the section its tab became. */
export function appPageAddress(params: URLSearchParams): { path: string; params: Record<string, string>; hash: string } {
    const deployment = params.get('deployment');
    const section = TAB_SECTIONS[params.get('tab') ?? ''];
    return { path: appPath(params.get('app')!), params: deployment ? { deployment } : {}, hash: section ? `#${section}` : '' };
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
    const href = useConsoleHref();
    const navigate = useNavigate();
    const [params] = useSearchParams();
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
    if (params.get('app')) {
        const to = appPageAddress(params);
        return <Navigate replace to={`${href(to.path, to.params)}${to.hash}`} />;
    }
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
                onRowClick={(p) => navigate(href(appPath(p.id)))}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No apps yet." hint="An app deploys a repo to a URL, with previews, domains, secrets and schedules." snippet={NEW_SNIPPETS.app(place)} />}
            />
            <AppsTrash user={user} />
        </>
    );
}
