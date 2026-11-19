// An app's deployments in the Apps drawer, newest first with the production one marked and those a push started tagged
// (a push that couldn't deploy shows why). One opens (`?deployment=`) with its
// build or runtime log and the actions it allows: Promote, Cancel, Redeploy.
import { useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { toast } from 'sonner';
import { clickableRow, ROW_HOVER } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Deployment, type Project } from 'noclick';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { ConsoleButton } from '../../ui/Button';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { Segmented } from '../../ui/Segmented';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { deploymentLook, deployOnPushOptions } from './AppsFormat';
import { AppsLogLines, AppUrl, BranchName, PreviewLinkMaker, Tag } from './AppsParts';
import { errorText, Field, Section } from './shared';

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
    const act = async (write: () => Promise<unknown>, done: string) => {
        setActing(true);
        try {
            await write();
            toast(done);
            invalidateV1('projects');
        } catch (e) {
            toast(errorText(e));
        } finally {
            setActing(false);
        }
    };
    const live = deployment.status === 'queued' || deployment.status === 'building';
    return (
        <div className="flex flex-wrap items-center gap-2">
            {deployment.status === 'ready' && !deployment.production && (
                <ConsoleButton size="sm" variant="primary" disabled={acting} onClick={() => void act(() => deployment.promote(), `Promoting ${deployment.branch} to production`)}>
                    {deployment.branch === project.productionBranch ? 'Roll back to this' : 'Promote to production'}
                </ConsoleButton>
            )}
            {live && (
                <ConsoleButton size="sm" disabled={acting} onClick={() => void act(async () => onChanged(await deployment.cancel()), 'Deployment canceled')}>
                    Cancel
                </ConsoleButton>
            )}
            <ConsoleButton size="sm" disabled={busy} onClick={() => void deploy({ branch: deployment.branch, commit: deployment.commit ?? undefined })}>
                Redeploy
            </ConsoleButton>
        </div>
    );
}

function DeploymentDetail({ project, deploymentId, row, onBack }: { project: Project; deploymentId: string; row?: Deployment; onBack: () => void }) {
    const { client } = useConsole();
    const fetched = useV1(row ? null : `deployments/${deploymentId}`, () => Deployment.get(deploymentId, { client, user: project.userId }));
    const [changed, setChanged] = useState<Deployment | null>(null);
    const deployment = changed ?? row ?? fetched.data;
    const [kind, setKind] = useState<'build' | 'runtime'>('build');
    const logs = useV1(deployment ? `deployments/${deployment.id}/logs?${kind}` : null, () => deployment!.logs({ kind }));
    return (
        <div className="flex flex-col gap-4">
            <ConsoleButton variant="ghost" size="sm" className="self-start" onClick={onBack} icon={<ArrowLeft className="h-3.5 w-3.5" />}>
                All deployments
            </ConsoleButton>
            {!deployment && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!deployment && fetched.error === undefined && <div aria-busy className="h-32 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {deployment && (
                <>
                    <dl className="m-0">
                        <Field label="Status">
                            <StatusPill look={deploymentLook(deployment)} />
                        </Field>
                        <Field label="Branch">
                            <span className="inline-flex items-center gap-2">
                                <BranchName name={deployment.branch} />
                                {deployment.production && <Tag>Production</Tag>}
                            </span>
                        </Field>
                        <Field label="Commit">
                            <span className="font-mono text-[12px]">{deployment.commit?.slice(0, 7) ?? '—'}</span>
                            {deployment.commitMessage && <span className="text-muted-foreground"> · {deployment.commitMessage}</span>}
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
                    {deployment.error && (
                        <p role="alert" className="m-0 rounded-lg border border-red-600/30 bg-red-500/[0.06] px-3 py-2 text-[13px] text-red-600 dark:border-red-400/30 dark:text-red-400">
                            {deployment.error}
                        </p>
                    )}
                    <DeploymentActions project={project} deployment={deployment} onChanged={setChanged} />
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
                </>
            )}
        </div>
    );
}

export function AppDeployments({ project }: { project: Project }) {
    const [selected, setSelected] = useSearchParam('deployment');
    const deployments = useV1(`projects/${project.id}/deployments`, () => project.deployments({ limit: 50 }));
    if (selected) return <DeploymentDetail project={project} deploymentId={selected} row={deployments.data?.find((d) => d.id === selected)} onBack={() => setSelected(null)} />;
    const rows = deployments.data ?? [];
    return (
        <Section title="Deployments">
            <p className="m-0 mb-2 text-[12px] text-muted-foreground">
                A deploy of <span className="font-mono">{project.productionBranch}</span> goes live at the app’s URL; every other branch gets a preview URL of its own.
                {project.deployOnPush !== 'off' && ` ${deployOnPushOptions(project.productionBranch).find((o) => o.value === project.deployOnPush)!.sentence}`}
            </p>
            {deployments.error !== undefined ? (
                <ErrorPanel error={deployments.error} onRetry={() => void deployments.refresh()} />
            ) : deployments.loading ? (
                <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : rows.length === 0 ? (
                <p className="m-0 text-[13px] text-muted-foreground">Not deployed yet. Deploy {project.productionBranch} to put the app online.</p>
            ) : (
                <ul aria-label="Deployments" className={'m-0 list-none p-0'}>
                    {rows.map((d) => (
                        <li key={d.id} {...clickableRow(() => setSelected(d.id))} className={cn('-mx-2 flex cursor-pointer items-center gap-3 rounded-md px-2 py-2.5', ROW_HOVER)}>
                            <StatusPill look={deploymentLook({ status: d.status, startedBy: d.startedBy })} className="w-[6.5rem] shrink-0" />
                            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                                <span className="flex min-w-0 items-center gap-2">
                                    <BranchName name={d.branch} />
                                    {d.production && <Tag>Production</Tag>}
                                    {d.startedBy === 'push' && <Tag>On push</Tag>}
                                </span>
                                <span className="truncate text-[12px] text-muted-foreground">
                                    <span className="font-mono">{d.commit?.slice(0, 7)}</span>
                                    {d.commitMessage ? ` · ${d.commitMessage}` : ''}
                                </span>
                                {d.status === 'failed' && d.startedBy === 'push' && d.error && (
                                    <span className="truncate text-[12px] text-red-600 dark:text-red-400" title={d.error}>
                                        {d.error}
                                    </span>
                                )}
                            </span>
                            {d.url && d.status === 'ready' && <AppUrl url={d.url} className="hidden max-w-[14rem] min-w-0 items-center gap-1 text-[12px] text-foreground/70 hover:text-foreground hover:underline md:inline-flex" />}
                            <TimeCell value={d.createdAt} className="w-16 shrink-0 text-right text-[12px] text-muted-foreground" />
                        </li>
                    ))}
                </ul>
            )}
        </Section>
    );
}
