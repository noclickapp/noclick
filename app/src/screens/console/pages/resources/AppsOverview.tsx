// What an app's page shows besides its deploys and what it's given: what stops its paid calls (`AppProblem`, first),
// what it spent this month against its budget (a budget dialog beside it) and where the money went, the facts set once
// (`AppFacts`: its repo, runtime, region, user), how it deploys (what a push deploys, who opens its previews, each a
// PATCH, with a link to make for a private preview and a way to stop every link made, and how each instance runs in a
// container, `AppsContainer`), the domains that serve it, added (with the records a connected one needs) and removed,
// and the lines it printed while serving.
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { cn } from '@/ui/utils';
import { Repo, type DeployOnPush, type Domain, type PreviewAccess, type Project } from 'noclick';
import { formatCount, formatDuration, formatMoney } from '@/screens/console/lib/format';
import { userLabel } from '@/screens/console/lib/userFilter';
import { addFundsUrl } from '@/screens/console/lib/site';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { regionLabel, useRegions } from '@/screens/console/hooks/useRegions';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { ConsoleButton, consoleButtonClass } from '../../ui/Button';
import { capLabel } from '../../ui/CapMeter';
import { BudgetDialog } from '../../ui/BudgetDialog';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { AsideSection, Fact, Facts, MonthSpend } from '../../ui/Detail';
import { Problem } from '../../ui/DrawerParts';
import { CopyIdChip } from '../../ui/IdChip';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { PageSection } from '../../ui/PageHeader';
import { Segmented } from '../../ui/Segmented';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { AppContainer } from './AppsContainer';
import { deployOnPushOptions, frameworkLabel, limitText, PREVIEW_ACCESS, RUNTIMES, spendTypeLabel } from './AppsFormat';
import { AppsLogLines, BranchName, Choice, PreviewLinkMaker } from './AppsParts';
import { DnsRecordList, domainLook, sourceLabel } from './DomainsParts';
import { domainName, isDomainName, servedNames, stopServing, useAddAppDomain, type ServedName } from './appDomains';
import { ConfirmAction, errorText, INPUT, LabeledInput } from './shared';

/** The first of the month after `periodStart`, when budgets and caps reset. */
function resetDay(periodStart: Date | null): string {
    const start = periodStart ?? new Date();
    return new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

function AppBudgetDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (open: boolean) => void }) {
    return (
        <BudgetDialog
            open={open}
            onOpenChange={onOpenChange}
            current={project.budgetUsdPerMonth}
            description={`The most ${project.name} may spend in a calendar month: hosting and builds, its calls to what it's bound to, email, AI and agent turns. At the budget it keeps serving, and its paid calls fail until the month turns; at twice it its pages pause too.`}
            note={project.userId ? `It counts toward ${project.userId}'s cap too.` : 'It counts toward your account’s balance like everything else.'}
            // An app with code always has a budget; only one NoClick publishes may have none.
            removable={project.published}
            onSave={async (budget) => {
                await project.update({ budgetUsdPerMonth: budget });
                invalidateV1('projects');
                invalidateV1(`projects/${project.id}/usage`);
                toast(budget == null ? `${project.name} has no budget of its own now` : `${project.name} may spend ${formatMoney(budget)} a month`);
            }}
        />
    );
}

/** An app's month: one read, shared by what stops its paid calls and its spend. */
export function useAppUsage(project: Project | undefined) {
    return useV1(project ? `projects/${project.id}/usage` : null, () => project!.usage());
}

export type AppUsage = ReturnType<typeof useAppUsage>;

/** What stops the app's paid calls, in words at the top of its page, with its fix: its budget, its user's cap, or funds. */
export function AppProblem({ project, usage }: { project: Project; usage: AppUsage }) {
    const { site } = useConsole();
    const href = useConsoleHref();
    const [editing, setEditing] = useState(false);
    const u = usage.data;
    const limit = u ? limitText(u.limitedBy, { userId: project.userId, budgetUsd: u.budgetUsd == null ? '' : capLabel(u.budgetUsd) }) : null;
    if (!u || !limit) return null;
    const fix =
        u.limitedBy === 'project' ? (
            <ConsoleButton size="sm" onClick={() => setEditing(true)}>
                Raise budget
            </ConsoleButton>
        ) : u.limitedBy === 'user' && project.userId ? (
            <Link to={href(`users/${project.userId}`)} className={consoleButtonClass('soft', 'sm')}>
                Raise {project.userId}&apos;s cap
            </Link>
        ) : u.limitedBy === 'account' ? (
            <a href={addFundsUrl(site)} target="_blank" rel="noreferrer" className={consoleButtonClass('soft', 'sm')}>
                Add funds
            </a>
        ) : null;
    return (
        <>
            <Problem title={`Paid calls stopped: ${limit}`} action={fix}>
                Pages still load and it reads its data; writes, email, AI and agent turns fail until {resetDay(u.periodStart)}. Each refusal is in its runtime log.
            </Problem>
            <AppBudgetDialog project={project} open={editing} onOpenChange={setEditing} />
        </>
    );
}

/** What it spent this month against its budget and what it served, then where the money went. */
export function AppSpend({ project, usage }: { project: Project; usage: AppUsage }) {
    const [editing, setEditing] = useState(false);
    const u = usage.data;
    const byType = u ? Object.entries(u.byType).sort(([, a], [, b]) => b - a) : [];
    if (usage.error !== undefined) return <ErrorPanel error={usage.error} onRetry={() => void usage.refresh()} />;
    if (!u) return <div aria-busy className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]" />;
    return (
        <MonthSpend
            spent={u.usd}
            cap={u.budgetUsd}
            action={
                <ConsoleButton size="sm" variant="ghost" onClick={() => setEditing(true)}>
                    {project.budgetUsdPerMonth == null ? 'Set budget' : 'Change budget'}
                </ConsoleButton>
            }
        >
            <p className="m-0 text-[12px] text-muted-foreground">
                {formatCount(u.requests)} requests · {formatDuration(u.cpuMs)} of CPU time
            </p>
            {byType.length > 0 && (
                <ul aria-label="Spend by type" className="m-0 mt-1 list-none p-0">
                    {byType.map(([type, usd]) => (
                        <li key={type} className="flex items-center justify-between gap-3 py-1 text-[13px]">
                            <span className="text-muted-foreground">{spendTypeLabel(type)}</span>
                            <span className="tabular-nums text-foreground">{formatMoney(usd)}</span>
                        </li>
                    ))}
                </ul>
            )}
            <AppBudgetDialog project={project} open={editing} onOpenChange={setEditing} />
        </MonthSpend>
    );
}

/** What a push to the app's repo deploys by itself; a change applies at once. */
function DeployOnPushSetting({ project }: { project: Project }) {
    const [value, setValue] = useState<DeployOnPush>(project.deployOnPush);
    const [busy, setBusy] = useState(false);
    useEffect(() => setValue(project.deployOnPush), [project.deployOnPush]);
    const options = deployOnPushOptions(project.productionBranch);
    const change = async (next: DeployOnPush) => {
        if (busy || next === value) return;
        const was = value;
        setValue(next);
        setBusy(true);
        try {
            await project.update({ deployOnPush: next });
            invalidateV1('projects');
            toast(options.find((o) => o.value === next)!.sentence);
        } catch (e) {
            setValue(was);
            toast(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return <Choice label="Deploy on push" options={options} value={value} onChange={(next) => void change(next)} />;
}

/** Who opens the app's previews; a change applies at once, and what NoClick adds to it (that it isn't in force yet) is
 * said with it, as is why it's refused (a container app's previews can't be kept to a link yet). While they're private:
 * the paths left open, a link to make, and a way to stop every link made so far. */
function PreviewAccessSetting({ project }: { project: Project }) {
    const [value, setValue] = useState<PreviewAccess>(project.previewAccess);
    const [busy, setBusy] = useState(false);
    // Moved on when the links are stopped, so a link shown before (which no longer opens anything) is put away.
    const [stopped, setStopped] = useState(0);
    const stopLinks = async () => {
        await project.revokePreviewLinks();
        invalidateV1('projects');
        setStopped((n) => n + 1);
        const notes = Array.isArray(project.raw.notes) ? (project.raw.notes as string[]) : [];
        toast(notes.join(' ') || 'Every preview link made before now stopped working.');
    };
    useEffect(() => setValue(project.previewAccess), [project.previewAccess]);
    const change = async (next: PreviewAccess) => {
        if (busy || next === value) return;
        const was = value;
        setValue(next);
        setBusy(true);
        try {
            await project.update({ previewAccess: next });
            invalidateV1('projects');
            const notes = Array.isArray(project.raw.notes) ? (project.raw.notes as string[]) : [];
            toast([PREVIEW_ACCESS.find((o) => o.value === next)!.sentence, ...notes].join(' '));
        } catch (e) {
            setValue(was);
            toast(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    const open = project.previewPublicPaths;
    return (
        <div className="flex flex-col gap-2">
            <Choice label="Previews" options={PREVIEW_ACCESS} value={value} onChange={(next) => void change(next)} />
            {value === 'link' && (
                <>
                    <p className="m-0 text-[12px] text-muted-foreground">
                        {open.length ? (
                            <>
                                Open to anyone: <span className="font-mono text-foreground/85">{open.join(', ')}</span>
                            </>
                        ) : (
                            'A webhook or sign-in callback to a preview is turned away too, unless its path is left open (preview_public_paths).'
                        )}
                    </p>
                    <div className="flex flex-wrap items-start gap-2">
                        <PreviewLinkMaker key={stopped} project={project} />
                        <ConfirmAction
                            label="Stop all preview links"
                            title="Stop every link to its previews?"
                            description="Each link made so far, and what it left in a browser, stops opening the previews within 30 seconds. Links you make after open them as before."
                            confirmLabel="Stop all links"
                            onConfirm={stopLinks}
                        />
                    </div>
                </>
            )}
        </div>
    );
}

/** How it deploys: what a push deploys, who opens its previews, and how each instance runs in a container. */
export function AppHowItDeploys({ project }: { project: Project }) {
    return (
        <PageSection title="How it deploys">
            <div className="flex flex-col gap-6">
                <DeployOnPushSetting project={project} />
                <PreviewAccessSetting project={project} />
                <AppContainer project={project} />
            </div>
        </PageSection>
    );
}

/** The facts set once: where it comes from, how and where it runs, whom it's for, and its ID. */
export function AppFacts({ project }: { project: Project }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const regions = useRegions();
    const repoId = project.repoId;
    const repo = useV1(`repos/${repoId}`, () => Repo.get(repoId ?? '', { client, user: project.userId }), { enabled: repoId !== null });
    const runtime = RUNTIMES.find((r) => r.value === project.runtime)?.label ?? project.runtime;
    return (
        <AsideSection title="About">
            <Facts>
                {repoId !== null ? (
                    <Fact row label="Repo">
                        <span className="inline-flex min-w-0 flex-wrap items-center gap-x-2">
                            <Link to={href('resources/repos', { repo: repoId })} className="text-foreground hover:underline">
                                {repo.data?.name ?? project.name}
                            </Link>
                            <BranchName name={project.productionBranch} className="text-muted-foreground" />
                        </span>
                    </Fact>
                ) : (
                    <Fact row label="Published from">
                        {publishedFrom(project)}
                    </Fact>
                )}
                <Fact row label="Runs on">
                    {project.framework ? `${runtime} · ${frameworkLabel(project.framework)}` : runtime}
                </Fact>
                <Fact row label="Region">
                    {regionLabel(project.region, regions.data)}
                </Fact>
                <Fact row label="User">
                    <span className={project.userId ? undefined : 'text-muted-foreground'}>{userLabel(project.userId)}</span>
                </Fact>
                <Fact row label="Created">
                    <TimeCell value={project.createdAt} tier="absolute" />
                </Fact>
                <Fact row label="ID">
                    <CopyIdChip id={project.id} />
                </Fact>
            </Facts>
        </AsideSection>
    );
}

/** Where NoClick publishes an app's files from: an automation's interface, or a page published before apps. */
export function publishedFrom(project: Project): string {
    return project.workflow ? `The ${project.workflow.name ?? 'deleted'} automation's interface` : 'A page published before apps';
}

// ── domains ──────────────────────────────────────────────────────────────

/** What an added domain that isn't serving yet still needs, in a sentence. */
function addedSentence(domain: Domain): string {
    if (domain.status !== 'pending_dns') return 'It serves the app once it’s active.';
    if (domain.source === 'connected') return `Add these where ${domain.name}'s DNS is hosted. It serves the app once NoClick sees them; it checks every few minutes.`;
    return 'NoClick is setting its DNS up; it serves the app within minutes.';
}

/** An added domain that isn't serving yet: its status, and the records it still needs. */
function AddedDomain({ domain }: { domain: Domain }) {
    const { now } = useConsole();
    return (
        <div className="flex flex-col gap-3">
            <StatusPill look={domainLook(domain, now())} className="self-start" />
            {domain.records.length > 0 && <DnsRecordList records={domain.records} label="DNS records" />}
        </div>
    );
}

function AddDomainDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (open: boolean) => void }) {
    const [name, setName] = useState('');
    const adding = useAddAppDomain(project, '');
    const { busy, error } = adding;
    const added = adding.added?.status === 'active' ? null : adding.added;
    const typed = domainName(name);
    const valid = isDomainName(typed);
    const reset = (next: boolean) => {
        if (!next) {
            setName('');
            adding.reset();
        }
        onOpenChange(next);
    };
    const add = async () => {
        const domain = await adding.add(typed);
        if (domain?.status === 'active') {
            toast(`Added ${typed}. It serves ${project.name} once its certificate is issued, within minutes.`);
            reset(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={reset}
            title={added ? (added.status === 'pending_dns' && added.source === 'connected' ? `Point ${added.name} at NoClick` : `Added ${typed}`) : 'Add a domain'}
            description={added ? addedSentence(added) : 'A domain your account bought through NoClick, or a name under it, serves the app at once; one you own elsewhere waits for its DNS records.'}
            footer={
                added ? (
                    <ConsoleButton variant="primary" onClick={() => reset(false)}>
                        Done
                    </ConsoleButton>
                ) : (
                    <ConsoleButton variant="primary" disabled={busy || !valid} onClick={() => void add()}>
                        {busy ? 'Adding…' : 'Add domain'}
                    </ConsoleButton>
                )
            }
        >
            {added ? (
                <AddedDomain domain={added} />
            ) : (
                <form
                    className="flex flex-col gap-3"
                    onSubmit={(e) => {
                        e.preventDefault();
                        if (valid) void add();
                    }}
                >
                    <LabeledInput label="Domain" id="app-domain">
                        <input id="app-domain" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value)} placeholder="book.acme.com" autoComplete="off" />
                    </LabeledInput>
                    {error !== undefined && <ErrorPanel error={error} />}
                </form>
            )}
        </ConsoleDialog>
    );
}

function DomainRow({ project, served }: { project: Project; served: ServedName }) {
    const { now } = useConsole();
    const href = useConsoleHref();
    const { domain, hostname, stops } = served;
    return (
        <li className="flex items-center gap-3 py-2.5">
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <Link to={href('resources/domains', { domain: domain.id })} className="truncate text-[13px] text-foreground hover:underline">
                    {hostname}
                </Link>
                {hostname !== domain.name && <span className="truncate text-[12px] text-muted-foreground">under {domain.name}</span>}
            </span>
            <span className="hidden text-[12px] text-muted-foreground sm:inline">{sourceLabel(domain)}</span>
            <StatusPill look={domainLook(domain, now())} />
            <ConfirmAction
                label="Remove"
                title={`Stop serving ${project.name} at ${hostname}?`}
                description={`It stops answering at ${stops.join(' and ')}. ${domain.source === 'connected' ? `${domain.name} stays connected until you delete it on the Domains page.` : `${domain.name} stays yours.`}`}
                confirmLabel="Remove"
                onConfirm={async () => {
                    await stopServing(project, served, '');
                    toast(`${project.name} no longer serves at ${stops.join(' and ')}`);
                }}
            />
        </li>
    );
}

export function AppDomains({ project }: { project: Project }) {
    // Under domains?, so a domain's frame reads it again.
    const domains = useV1(`domains?project=${project.id}`, () => project.domains());
    const [adding, setAdding] = useState(false);
    const rows = servedNames(domains.data ?? [], project.id);
    return (
        <PageSection
            id="domains"
            title="Domains"
            right={
                <ConsoleButton size="sm" onClick={() => setAdding(true)}>
                    Add domain
                </ConsoleButton>
            }
            note={
                <>
                    The app always serves at <span className="text-foreground">{project.hostname}</span>; each domain here serves it too.
                </>
            }
        >
            {domains.error !== undefined ? (
                <ErrorPanel error={domains.error} onRetry={() => void domains.refresh()} />
            ) : domains.loading ? (
                <div aria-busy className="h-20 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : rows.length === 0 ? (
                <p className="m-0 text-[13px] text-muted-foreground">No domains yet. Add one you bought through NoClick, or one you own elsewhere.</p>
            ) : (
                <ul aria-label="Domains" className={'m-0 list-none p-0'}>
                    {rows.map((served) => (
                        <DomainRow key={served.hostname} project={project} served={served} />
                    ))}
                </ul>
            )}
            <AddDomainDialog project={project} open={adding} onOpenChange={setAdding} />
        </PageSection>
    );
}

// ── runtime logs ─────────────────────────────────────────────────────────

type LevelFilter = 'all' | 'warn' | 'error';

export function AppLogs({ project }: { project: Project }) {
    const [level, setLevel] = useState<LevelFilter>('all');
    const logs = useV1(`projects/${project.id}/logs?${level}`, () => project.logs({ level: level === 'all' ? undefined : level, limit: 200 }));
    return (
        <PageSection
            id="logs"
            title="What it printed"
            note="Its runtime log while serving, oldest first. Lines are kept 7 days."
            right={
                <>
                    <Segmented
                        label="Level"
                        value={level}
                        onChange={setLevel}
                        options={[
                            { value: 'all', label: 'All' },
                            { value: 'warn', label: 'Warnings' },
                            { value: 'error', label: 'Errors' },
                        ]}
                    />
                    <ConsoleButton size="sm" variant="ghost" onClick={() => void logs.refresh()}>
                        Refresh
                    </ConsoleButton>
                </>
            }
        >
            {logs.error !== undefined ? (
                <ErrorPanel error={logs.error} onRetry={() => void logs.refresh()} />
            ) : logs.loading ? (
                <div aria-busy className="h-48 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : (
                <AppsLogLines lines={logs.data ?? []} label="Runtime log" empty={level === 'all' ? 'Nothing printed in the last 7 days.' : 'No lines at this level in the last 7 days.'} />
            )}
        </PageSection>
    );
}
