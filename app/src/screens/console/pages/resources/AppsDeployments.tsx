// An app's deploys on its page: the latest few as a list (each commit, what it says, its status, production or which
// preview, when; a failed one says why), all of them on asking. One opens in a drawer (`?deployment=`) with its build
// or runtime log and the actions it allows: Promote, Cancel, Redeploy.
import { useState } from 'react';
import { toast } from 'sonner';
import { Deployment, type Project } from 'noclick';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useReportHeld } from '@/sdk/held';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { ConsoleButton } from '../../ui/Button';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { HeaderNote, Problem } from '../../ui/DrawerParts';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { PageSection } from '../../ui/PageHeader';
import { Segmented } from '../../ui/Segmented';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { deploymentLook, deployOnPushOptions } from './AppsFormat';
import { AppsLogLines, AppUrl, BranchName, PreviewLinkMaker, Tag } from './AppsParts';
import { errorText, Field, Section } from './shared';

/** How many deploys the page lists before "Show all". */
const RECENT = 5;

/** Start a deploy from the console: a toast, and the list re-read. */
export function useDeploy(project: Project) {
    const [busy, setBusy] = useState(false);
    const deploy = async (options: { branch?: string; commit?: string }) => {
        setBusy(true);
        try {
            await project.deploy(options);
            const what = `${options.branch ?? project.productionBranch}${options.commit ? ` at ${options.commit.slice(0, 7)}` : ''}`;
            toast(`Deploying ${what}. It shows here as it builds.`);
            invalidateV1(`projects/${project.id}/deployments`);
        } catch (e) {
            toast(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return { deploy, busy };
}

function DeploymentActions({ project, deployment, onChanged }: { project: Project; deployment: Deployment; onChanged: (d: Deployment) => void }) {
    const { deploy, busy } = useDeploy(project);
    const [acting, setActing] = useState(false);
    const reportHeld = useReportHeld(useConsole());
    const act = async (write: () => Promise<unknown>, done: string, what: string) => {
        setActing(true);
        try {
            await write();
            toast(done);
            invalidateV1('projects');
        } catch (e) {
            if (!reportHeld(e, what, () => invalidateV1('projects'))) toast(errorText(e));
        } finally {
            setActing(false);
        }
    };
    const live = deployment.status === 'queued' || deployment.status === 'building';
    return (
        <>
            {deployment.status === 'ready' && !deployment.production && (
                <ConsoleButton variant="primary" disabled={acting} onClick={() => void act(() => deployment.promote(), `Promoting ${deployment.branch} to production`, `Promote ${deployment.branch}`)}>
                    {deployment.branch === project.productionBranch ? 'Roll back to this' : 'Promote to production'}
                </ConsoleButton>
            )}
            {live && (
                <ConsoleButton disabled={acting} onClick={() => void act(async () => onChanged(await deployment.cancel()), 'Deployment canceled', 'Cancel the deployment')}>
                    Cancel
                </ConsoleButton>
            )}
            <ConsoleButton disabled={busy} onClick={() => void deploy({ branch: deployment.branch, commit: deployment.commit ?? undefined })}>
                Redeploy
            </ConsoleButton>
        </>
    );
}

/** Where a deploy went: production, or which branch's preview. */
const where = (d: Deployment) => (d.environment === 'production' ? 'production' : `preview of ${d.branch}`);

/** One deploy in a drawer: why it failed, what it is, its log, and what can be done with it. */
function DeploymentDrawer({ project, deploymentId, row, onClose }: { project: Project; deploymentId: string; row?: Deployment; onClose: () => void }) {
    const { client } = useConsole();
    const fetched = useV1(row ? null : `deployments/${deploymentId}`, () => Deployment.get(deploymentId, { client, user: project.userId }));
    const [changed, setChanged] = useState<Deployment | null>(null);
    const deployment = changed ?? row ?? fetched.data;
    const [kind, setKind] = useState<'build' | 'runtime'>('build');
    const logs = useV1(deployment ? `deployments/${deployment.id}/logs?${kind}` : null, () => deployment!.logs({ kind }));
    return (
        <Drawer
            open
            onOpenChange={(open) => !open && onClose()}
            kind="Deployment"
            title={deployment ? deployment.commitMessage || `Deploy of ${deployment.branch}` : undefined}
            id={deploymentId}
            status={
                deployment ? (
                    <>
                        <StatusPill look={deploymentLook(deployment)} />
                        <HeaderNote>
                            {where(deployment)} · <TimeCell value={deployment.createdAt} />
                        </HeaderNote>
                    </>
                ) : undefined
            }
            footer={deployment ? <DeploymentActions project={project} deployment={deployment} onChanged={setChanged} /> : undefined}
        >
            {!deployment && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!deployment && fetched.error === undefined && <div aria-busy className="h-32 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {deployment && (
                <div className="flex flex-col gap-6">
                    {deployment.error && <Problem title={deployment.status === 'failed' ? 'It didn’t deploy' : 'Its last attempt failed'}>{deployment.error}</Problem>}
                    <Section
                        title={
                            <span className="flex items-center justify-between gap-2">
                                <span>{kind === 'build' ? 'Build log' : 'Runtime log'}</span>
                                <Segmented
                                    label="Log"
                                    value={kind}
                                    onChange={setKind}
                                    options={[
                                        { value: 'build', label: 'Build' },
                                        { value: 'runtime', label: 'Runtime' },
                                    ]}
                                />
                            </span>
                        }
                    >
                        {logs.error !== undefined ? (
                            <ErrorPanel error={logs.error} onRetry={() => void logs.refresh()} />
                        ) : logs.loading ? (
                            <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />
                        ) : (
                            <AppsLogLines
                                lines={logs.data ?? []}
                                label={kind === 'build' ? 'Build log' : 'Runtime log'}
                                empty={kind === 'build' ? 'No build output.' : 'Nothing printed while it served, in the last 7 days.'}
                            />
                        )}
                    </Section>
                    <dl className="m-0">
                        <Field label="Branch">
                            <span className="inline-flex items-center gap-2">
                                <BranchName name={deployment.branch} />
                                {deployment.production && <Tag>Production</Tag>}
                            </span>
                        </Field>
                        <Field label="Commit">
                            <span className="font-mono text-[12px]">{deployment.commit?.slice(0, 7) ?? '—'}</span>
                        </Field>
                        <Field label="URL">{deployment.url ? <AppUrl url={deployment.url} /> : <span className="text-muted-foreground">None: it isn’t serving</span>}</Field>
                        {project.previewAccess === 'link' && deployment.status === 'ready' && deployment.environment === 'preview' && deployment.url && (
                            <Field label="Private link">
                                <PreviewLinkMaker project={project} branch={deployment.branch} />
                            </Field>
                        )}
                        <Field label="Started">
                            <TimeCell value={deployment.createdAt} tier="absolute" />
                            <span className="text-muted-foreground"> · {deployment.startedBy === 'push' ? `by a push to ${deployment.branch}` : 'by a deploy'}</span>
                        </Field>
                        <Field label="Environment">
                            {deployment.environment === 'production' ? 'Production' : 'Preview'}
                            <span className="text-muted-foreground"> · built with {deployment.environment === 'production' ? 'production' : 'preview'} secrets</span>
                        </Field>
                        {deployment.readyAt && (
                            <Field label="Ready">
                                <TimeCell value={deployment.readyAt} tier="absolute" />
                            </Field>
                        )}
                    </dl>
                </div>
            )}
        </Drawer>
    );
}

const COLUMNS: Column<Deployment>[] = [
    {
        id: 'message',
        header: 'Message',
        cell: (d) => (
            <span className="flex min-w-0 flex-col">
                <span className="truncate">{d.commitMessage || `Deploy of ${d.branch}`}</span>
                {d.status === 'failed' && d.error ? (
                    <span className="truncate text-[12px] text-red-600 dark:text-red-400" title={d.error}>
                        {d.error}
                    </span>
                ) : (
                    <span className="truncate text-[12px] text-muted-foreground md:hidden">
                        <span className="font-mono">{d.commit?.slice(0, 7) ?? d.branch}</span> · <TimeCell value={d.createdAt} />
                    </span>
                )}
            </span>
        ),
    },
    { id: 'commit', header: 'Commit', priority: 3, width: '5.5rem', cell: (d) => <span className="font-mono text-[12px]">{d.commit?.slice(0, 7) ?? '—'}</span> },
    { id: 'status', header: 'Status', width: '9.5rem', cell: (d) => <StatusPill look={deploymentLook({ status: d.status, startedBy: d.startedBy })} /> },
    { id: 'where', header: 'Where', priority: 2, width: '10rem', cell: (d) => <span className="truncate">{where(d)}</span> },
    { id: 'when', header: 'When', priority: 2, width: '5.5rem', align: 'right', cell: (d) => <TimeCell value={d.createdAt} /> },
];

/** Its latest deploys, newest first; every one it keeps on asking. */
export function AppDeploys({ project }: { project: Project }) {
    const [open, setOpen] = useSearchParam('deployment');
    const [all, setAll] = useState(false);
    const deployments = useV1(`projects/${project.id}/deployments`, () => project.deployments({ limit: 50 }));
    const rows = deployments.data ?? [];
    const shown = all ? rows : rows.slice(0, RECENT);
    const onPush = project.deployOnPush !== 'off' ? ` ${deployOnPushOptions(project.productionBranch).find((o) => o.value === project.deployOnPush)!.sentence}` : '';
    return (
        <PageSection
            id="deploys"
            title="Recent deploys"
            count={rows.length}
            right={
                rows.length > RECENT && (
                    <ConsoleButton size="sm" variant="ghost" onClick={() => setAll(!all)}>
                        {all ? 'Show fewer' : `Show all ${rows.length}`}
                    </ConsoleButton>
                )
            }
            note={
                project.published ? undefined : (
                    <>
                        A deploy of <span className="font-mono">{project.productionBranch}</span> goes live at the app’s URL; every other branch gets a preview URL of its own.{onPush}
                    </>
                )
            }
        >
            <DataTable
                label="Deployments"
                columns={COLUMNS}
                rows={shown}
                getRowId={(d) => d.id}
                loading={deployments.loading}
                error={deployments.error}
                onRetry={() => void deployments.refresh()}
                onRowClick={(d) => setOpen(d.id, { push: true })}
                selectedId={open}
                skeletonRows={3}
                empty={<p className="m-0 py-6 text-center text-[13px] text-muted-foreground">Not deployed yet. Deploy {project.productionBranch} to put the app online.</p>}
            />
            {open && <DeploymentDrawer key={open} project={project} deploymentId={open} row={rows.find((d) => d.id === open)} onClose={() => setOpen(null)} />}
        </PageSection>
    );
}
