// What a website is doing, on its page: its deployments, each opening in a
// side panel with how its own requests went over the last day and its build
// log, and what it printed while serving (the site's requests over a period
// are AppAnalytics). Read through the platform API like the rest of Resources;
// a deployment frame reads them again (their keys sit under `resources:projects`).
import { useState } from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';
import { countOf, relTime } from '@/ui/primitives';
import { BUTTON_GHOST } from '@/ui/buttons';
import { DataGrid, type GridColumn, type GridRow } from './DataGrid';
import { RecordDrawer, type RecordField } from './RecordDrawer';
import { PillSelect, Section, Surface } from './ui';
import { cn } from '@/ui/utils';
import { AppsLogLines } from '@/screens/console/pages/resources/AppsParts';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import type { Deployment, Project, RequestOutcomes } from 'noclick';
import { Pending, ROW } from './parts';

const DEPLOYMENT_WORDS: Record<string, string> = { queued: 'Queued', building: 'Building', ready: 'Ready', failed: 'Failed', canceled: 'Canceled' };
/** A log read: its newest lines, oldest first. */
const LOG_LINES = 200;
const LOG_LEVELS = [
    { value: 'all', label: 'Everything' },
    { value: 'warn', label: 'Warnings and errors' },
    { value: 'error', label: 'Errors' },
] as const;
type LogLevel = (typeof LOG_LEVELS)[number]['value'];

const reads = (project: Project) => `resources:projects/${project.id}`;
const deploymentTitle = (d: Deployment) => d.commitMessage?.split('\n')[0] || d.commit?.slice(0, 7) || d.branch;

/** HTTP statuses by their class, answers never sent apart: "2xx 17,522 · 4xx 203 · 5xx 31 · no answer 6". */
export function statusClasses(byStatus: Record<string, number>): { label: string; count: number; failed: boolean }[] {
    const classes = new Map<string, number>();
    for (const [status, count] of Object.entries(byStatus)) {
        const label = /^\d{3}$/.test(status) ? `${status[0]}xx` : 'no answer';
        classes.set(label, (classes.get(label) ?? 0) + count);
    }
    return [...classes]
        .sort(([a], [b]) => (a === 'no answer' ? 1 : b === 'no answer' ? -1 : a.localeCompare(b)))
        .map(([label, count]) => ({ label, count, failed: label === '5xx' || label === 'no answer' }));
}

const ROUTE_COLUMNS: GridColumn[] = [
    { name: 'route' },
    { name: 'requests', numeric: true },
    { name: 'errors', numeric: true },
    { name: 'p50', numeric: true },
    { name: 'p95', numeric: true },
    { name: 'slowest', numeric: true },
];

const ms = (n: number) => `${n.toLocaleString('en-US')} ms`;

/** Requests by status class, a failed class in red: "2xx 17,522  4xx 203  5xx 31  no answer 6". */
export function StatusLine({ byStatus }: { byStatus: Record<string, number> }) {
    return (
        <span className="flex flex-wrap gap-x-3 text-[12.5px] tabular-nums text-muted-foreground">
            {statusClasses(byStatus).map((s) => (
                <span key={s.label} className={cn(s.failed && 'text-red-600 dark:text-red-400')}>
                    <span className="font-mono">{s.label}</span> {s.count.toLocaleString('en-US')}
                </span>
            ))}
        </span>
    );
}

/** How a deployment's requests went: how many failed, by status, and the slowest routes. */
export function RequestOutcomesView({ outcomes }: { outcomes: RequestOutcomes }) {
    if (!outcomes.requests) return <p className="text-[13.5px] text-muted-foreground">No requests in the last 24 hours.</p>;
    const routes: GridRow[] = outcomes.slowestRoutes.map((r) => ({
        route: `${r.method} ${r.path}`,
        requests: r.requests.toLocaleString('en-US'),
        errors: r.errors.toLocaleString('en-US'),
        p50: ms(r.p50Ms),
        p95: ms(r.p95Ms),
        slowest: ms(r.maxMs),
    }));
    return (
        <div className="space-y-3">
            <p className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[13.5px]">
                <span className="text-foreground">
                    {countOf(outcomes.requests, 'request')}
                    <span className={cn('ml-2', outcomes.errors ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                        {countOf(outcomes.errors, 'error')}
                        {outcomes.errorRate !== null && ` (${(outcomes.errorRate * 100).toFixed(outcomes.errorRate < 0.01 ? 1 : 0)}%)`}
                    </span>
                </span>
                <StatusLine byStatus={outcomes.byStatus} />
            </p>
            {routes.length > 0 && <DataGrid label="Slowest routes" columns={ROUTE_COLUMNS} rows={routes} empty="" />}
            {outcomes.sampled && <p className="text-[12.5px] text-muted-foreground">A sample: a busy site’s record keeps some requests, each standing for the ones like it.</p>}
        </div>
    );
}

/** One deployment in full: where it stands and came from, its requests and its build log. */
function DeploymentPanel({ deployment, onClose, now }: { deployment: Deployment | null; onClose: () => void; now: string }) {
    const d = deployment;
    const build = useV1(d ? `resources:projects/${d.projectId}/deployments/${d.id}/build` : null, () => d!.logs({ kind: 'build' }));
    const outcomes = useV1(d && d.status === 'ready' ? `resources:projects/${d.projectId}/deployments/${d.id}/requests` : null, () => d!.requests());
    const fields: RecordField[] = d
        ? [
              { name: 'Status', value: DEPLOYMENT_WORDS[d.status] ?? d.status },
              { name: 'Serves', value: d.production ? 'Production' : 'A preview' },
              { name: 'Branch', value: d.branch },
              ...(d.commit ? [{ name: 'Commit', value: d.commit, copy: true }] : []),
              ...(d.commitMessage ? [{ name: 'Message', value: d.commitMessage }] : []),
              ...(d.url
                  ? [
                        {
                            name: 'Address',
                            copy: true,
                            value: d.url,
                            display: (
                                <a href={d.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 underline-offset-4 hover:underline">
                                    {d.url.replace(/^https?:\/\//, '')}
                                    <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
                                </a>
                            ),
                        },
                    ]
                  : []),
              ...(d.runtime ? [{ name: 'Runs on', value: d.runtimeReason ? `${d.runtime === 'edge' ? 'The edge' : 'A container'}: ${d.runtimeReason}` : d.runtime }] : []),
              ...(d.createdAt
                  ? [{ name: 'Started', value: d.createdAt.toISOString(), display: d.createdAt.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }) }]
                  : []),
              ...(d.error ? [{ name: 'Why it failed', value: d.error }] : []),
          ]
        : [];
    return (
        <RecordDrawer
            open={!!d}
            onOpenChange={(open) => !open && onClose()}
            title={d ? `${d.branch} · ${d.commit?.slice(0, 7) ?? (DEPLOYMENT_WORDS[d.status] ?? d.status)}` : ''}
            description={d ? `${DEPLOYMENT_WORDS[d.status] ?? d.status} ${d.createdAt ? relTime(d.createdAt.toISOString(), now) : ''}`.trim() : undefined}
            fields={fields}
            names="words"
        >
            {d?.status === 'ready' && (
                <section className="mt-8">
                    <h3 className="mb-3 text-[14px] font-semibold text-foreground">Requests, last 24 hours</h3>
                    <Pending read={outcomes} rows={2} />
                    {outcomes.data && <RequestOutcomesView outcomes={outcomes.data} />}
                </section>
            )}
            <section className="mt-8">
                <h3 className="mb-3 text-[14px] font-semibold text-foreground">Build log</h3>
                <Pending read={build} rows={3} />
                {build.data && <AppsLogLines lines={build.data} label="Build log" empty="Its build printed nothing." className="rounded-xl" />}
            </section>
        </RecordDrawer>
    );
}

export function AppDeployments({ project, now }: { project: Project; now: string }) {
    const deployments = useV1(`${reads(project)}/deployments`, () => project.deployments({ limit: 8 }));
    const [open, setOpen] = useState<string | null>(null);
    const opened = deployments.data?.find((d) => d.id === open) ?? null;
    return (
        <Section title="Deployments" meta={deployments.data?.length || undefined}>
            <Pending read={deployments} />
            {deployments.data &&
                (deployments.data.length ? (
                    <Surface>
                        {deployments.data.map((d) => (
                            <div key={d.id} className={cn(ROW, 'group p-0')}>
                                <button
                                    type="button"
                                    onClick={() => setOpen(d.id)}
                                    className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.03] focus-visible:outline-none"
                                >
                                    <span className={cn('w-20 shrink-0 text-[13px]', d.status === 'failed' ? 'text-red-600 dark:text-red-400' : 'text-foreground/85')}>{DEPLOYMENT_WORDS[d.status] ?? d.status}</span>
                                    <span className="min-w-0 flex-1">
                                        <span className="block truncate text-[14px] text-foreground">{deploymentTitle(d)}</span>
                                        <span className="block truncate text-[12.5px] text-muted-foreground">
                                            {[d.branch, d.production ? 'Production' : 'Preview', d.status === 'failed' ? d.error : null].filter(Boolean).join(' · ')}
                                        </span>
                                    </span>
                                    <span className="hidden shrink-0 text-[12.5px] tabular-nums text-muted-foreground sm:inline">{d.createdAt ? relTime(d.createdAt.toISOString(), now) : ''}</span>
                                </button>
                                {d.url && d.status === 'ready' && (
                                    <a href={d.url} target="_blank" rel="noopener noreferrer" aria-label={`Open the ${d.branch} deployment`} className="mr-3 shrink-0 rounded-full p-1.5 text-muted-foreground transition-colors hover:text-foreground">
                                        <ExternalLink className="h-4 w-4" />
                                    </a>
                                )}
                            </div>
                        ))}
                    </Surface>
                ) : (
                    <p className="text-[13.5px] text-muted-foreground">Not deployed yet.</p>
                ))}
            <DeploymentPanel deployment={opened} onClose={() => setOpen(null)} now={now} />
        </Section>
    );
}

/** What the website printed while serving, newest last, at a level or above. */
export function AppLog({ project }: { project: Project }) {
    const [level, setLevel] = useState<LogLevel>('all');
    const log = useV1(`${reads(project)}/logs?${level}`, () => project.logs({ level: level === 'all' ? undefined : level, limit: LOG_LINES }));
    return (
        <Section
            title="Log"
            meta="Last 7 days"
            action={
                <span className="flex items-center gap-1">
                    <PillSelect label="Level" value={level} options={LOG_LEVELS} onChange={setLevel} />
                    <button type="button" aria-label="Read the log again" title="Read it again" onClick={() => invalidateV1(`${reads(project)}/logs`)} className={cn(BUTTON_GHOST, 'h-8 w-8 justify-center px-0')}>
                        <RefreshCw className="h-4 w-4" />
                    </button>
                </span>
            }
        >
            <Pending read={log} rows={4} />
            {log.data && (
                <AppsLogLines
                    lines={log.data}
                    label="Log"
                    empty={level === 'all' ? 'Nothing printed in the last 7 days.' : 'Nothing at this level in the last 7 days.'}
                    className="rounded-2xl bg-card dark:bg-foreground/[0.02]"
                />
            )}
        </Section>
    );
}
