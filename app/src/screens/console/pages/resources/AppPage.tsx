// An app's own page (`/resources/apps/<id>`), in the anatomy it shares with an agent's: how it stands under its name
// (production's status and its address), its deploy and the rest in the header; what stops its paid calls first, then
// what happened lately (its deploys, the domains it serves at, what it printed) and what it's given (bindings, its
// environment, schedules, email, payments and sign-in, how it deploys) on the left, and its month's spend, the facts set
// once and the code that deploys it on the right. A published interface has no code of its own: its page keeps its
// deploys, domains and log, and its automation publishes and unpublishes it.
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { toast } from 'sonner';
import { Project } from 'noclick';
import { cn } from '@/ui/utils';
import { PhoneBarBack, useInPhoneShell } from '@/ui/phoneBar';
import { truncateId } from '@/screens/console/lib/format';
import { appCodeSnippet, snippetTabs } from '@/screens/console/lib/snippets';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { ConsoleButton, consoleButtonClass } from '../../ui/Button';
import { CodeSnippet } from '../../ui/CodeSnippet';
import { CopyButton } from '../../ui/CopyButton';
import { AsideSection, ThingPage } from '../../ui/Detail';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { MoreMenu, copyId } from '../../ui/MoreMenu';
import { PageHeader, PageSection } from '../../ui/PageHeader';
import { StatusPill } from '../../ui/StatusPill';
import { AppServicesSection } from './AppServicesSection';
import { AppBindings, AppSchedules, AppSecrets, AppSettings } from './AppsConfig';
import { AppDeploys, useDeploy } from './AppsDeployments';
import { AppDurableObjectsSection } from './AppsDurableObjects';
import { appPath, deploymentLook, NOT_DEPLOYED } from './AppsFormat';
import { AppUrl } from './AppsParts';
import { AppDomains, AppFacts, AppHowItDeploys, AppLogs, AppProblem, AppSpend, useAppUsage } from './AppsOverview';
import { ConfirmAction, errorText } from './shared';

/** Deploy, the rest in a `⋯` menu: export, copy its ID, move it to the trash. */
function AppActions({ project }: { project: Project }) {
    const href = useConsoleHref();
    const navigate = useNavigate();
    const { deploy, busy } = useDeploy(project);
    const [trashing, setTrashing] = useState(false);
    const exportApp = async () => {
        try {
            await project.export();
            toast('Export started. The bundle link appears in Logs when it’s ready.');
        } catch (e) {
            toast(errorText(e));
        }
    };
    if (project.published) return <MoreMenu label="More actions" items={[{ label: 'Copy ID', onSelect: () => void copyId(project.id) }]} />;
    return (
        <>
            <a href="#logs" className={cn(consoleButtonClass('soft'), 'hidden sm:inline-flex')}>
                Logs
            </a>
            <ConsoleButton variant="primary" disabled={busy} onClick={() => void deploy({})}>
                {busy ? 'Deploying…' : `Deploy ${project.productionBranch}`}
            </ConsoleButton>
            <MoreMenu
                label="More actions"
                items={[
                    { label: 'Export', onSelect: () => void exportApp() },
                    { label: 'Copy ID', onSelect: () => void copyId(project.id) },
                    { label: 'Move to trash', danger: true, separated: true, onSelect: () => setTrashing(true) },
                ]}
            />
            <ConfirmAction
                label="Move to trash"
                open={trashing}
                onOpenChange={setTrashing}
                title={`Move ${project.name} to the trash?`}
                description="It goes offline at once. Its releases, deployments, schedules, secrets and bindings are kept, and its domains remembered: restoring it within 30 days serves it again where it was, with no build. The repo, databases and buckets it used are kept."
                confirmLabel="Move to trash"
                onConfirm={async () => {
                    await project.delete();
                    invalidateV1('projects');
                    invalidateV1('trash');
                    invalidateV1('account');
                    toast(`Moved ${project.name} to the trash`);
                    navigate(href('resources/apps'));
                }}
            />
        </>
    );
}

/** The section an address names (`#logs`, or a drawer tab's section), once the page has drawn. */
function useScrollToHash(ready: boolean) {
    const { hash } = useLocation();
    useEffect(() => {
        if (ready && hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView({ block: 'start' });
    }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps
}

export function AppPage({ id }: { id: string }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const navigate = useNavigate();
    const inPhone = useInPhoneShell();
    const state = useV1(`projects/${id}`, () => Project.get(id, { client }));
    const project = state.data;
    const usage = useAppUsage(project);
    useEffect(() => {
        if (project) recordRecent({ type: 'app', id: project.id, label: project.name, path: appPath(project.id) });
    }, [project?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    useScrollToHash(project !== undefined);

    const crumbs = inPhone
        ? undefined
        : [
              { label: 'Resources', href: href('resources') },
              { label: 'Apps', href: href('resources/apps') },
          ];
    const back = inPhone && <PhoneBarBack label="Apps" onBack={() => navigate(href('resources/apps'))} />;
    if (!project) {
        return (
            <>
                {back}
                <PageHeader crumbs={crumbs} title={truncateId(id)} />
                {state.error !== undefined ? <ErrorPanel error={state.error} onRetry={() => void state.refresh()} /> : <div aria-busy className="h-40 animate-pulse rounded-xl bg-foreground/[0.04]" />}
            </>
        );
    }
    const production = project.production;
    return (
        <>
            {back}
            <PageHeader
                crumbs={crumbs}
                title={project.name}
                status={
                    <>
                        <StatusPill look={production ? deploymentLook(production) : NOT_DEPLOYED} />
                        <span className="inline-flex min-w-0 items-center gap-0.5">
                            <AppUrl url={project.url} />
                            <CopyButton value={project.url} label="Copy the URL" />
                        </span>
                    </>
                }
                purpose={project.published ? 'Its automation publishes it: publish it again or unpublish it from the automation’s Interface tab.' : undefined}
                actions={<AppActions project={project} />}
            />
            <ThingPage
                problem={usage.data?.limitedBy ? <AppProblem project={project} usage={usage} /> : undefined}
                spend={<AppSpend project={project} usage={usage} />}
                main={
                    <>
                        <AppDeploys project={project} />
                        <AppDomains project={project} />
                        <AppLogs project={project} />
                        {!project.published && (
                            <>
                                <AppBindings project={project} />
                                <AppDurableObjectsSection project={project} />
                                <PageSection id="environment" title="Environment" note="What the running app reads from its environment. Changes reach it at its next deploy.">
                                    <div className="flex flex-col gap-6">
                                        <AppSettings project={project} />
                                        <AppSecrets project={project} />
                                    </div>
                                </PageSection>
                                <AppSchedules project={project} />
                                <PageSection id="services" title="Email, payments and sign-in">
                                    <AppServicesSection project={project} />
                                </PageSection>
                                <AppHowItDeploys project={project} />
                            </>
                        )}
                    </>
                }
                aside={
                    <>
                        <AppFacts project={project} />
                        {!project.published && (
                            <AsideSection title="Deploy it from your code">
                                <CodeSnippet tabs={snippetTabs(appCodeSnippet(project.name, project.userId))} />
                            </AsideSection>
                        )}
                    </>
                }
            />
        </>
    );
}
