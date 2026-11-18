// Agents that coordinate agents, on every agent page: what will wake an agent
// and what woke it, its live status under its title, its children with their
// tasks, the jobs it started (tasks, and the messages its agents tools sent)
// with the updates each sent, the task a child was given, and a box to ask it
// something without stopping it.
import { useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { AlarmClock, ChevronRight, Code2, Hand, MessageCircleQuestion, MessageSquareText, Radio, Redo2, type LucideIcon } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE, ROWS } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { ALL_USERS, type Agent, type AgentReply, type Job, type JobUpdate, type JsonObject, type Wakeup } from 'noclick';
import { userLabel } from '@/screens/console/lib/userFilter';
import { agentStatus, operationStatus, wakeupStatus } from '@/screens/console/lib/status';
import { useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { Field as FormField, agentsToolsOf, entryRef, inputClass } from '../agentParts';
import { PageSection } from '../ui/PageHeader';
import { ErrorPanel } from '../ui/ErrorPanel';
import { ConsoleButton } from '../ui/Button';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { StatusPill } from '../ui/StatusPill';
import { TimeCell } from '../ui/TimeCell';
import { IdChip } from '../ui/IdChip';
import { useAgentNames, type AgentName } from './lookups';

const LINK = 'underline decoration-foreground/25 underline-offset-2 hover:decoration-foreground/60';
const TEXT_BUTTON = 'underline-offset-2 transition-colors hover:text-foreground hover:underline';
/** Recent wake-ups shown before "Show all": the pending ones always show. */
const RECENT_WAKEUPS = 5;

/** Whether it holds the `agents` capability, whole or in part. */
export function coordinates(agent: Agent): boolean {
    return agent.tools.some((entry) => {
        const ref = entryRef(entry);
        return ref !== null && agentsToolsOf(ref) !== null;
    });
}

// ── status ─────────────────────────────────────────────────────────────────

/** What it's doing now and when it last did anything, for the title row. */
export function AgentLiveChips({ agent }: { agent: Agent }) {
    const look = agentStatus(agent.status, agent.runningTurns);
    if (!look) return null;
    return (
        <>
            <StatusPill look={look} />
            <span className="text-[12.5px] text-muted-foreground">
                {agent.lastActiveAt ? (
                    <>
                        Last active <TimeCell value={agent.lastActiveAt} />
                    </>
                ) : (
                    'Never ran'
                )}
            </span>
        </>
    );
}

// ── jobs and their updates ─────────────────────────────────────────────────

const UPDATE_KINDS: Record<string, string> = {
    done: 'Done',
    blocked: 'Blocked',
    before: 'Before a call',
    every: 'Progress',
    message: 'Message',
};

const WAITING_ON: Record<string, string> = { approval: 'an approval', connection: 'a connection', person: 'an answer', sign_in: 'a sign-in' };

function seconds(s: number): string {
    if (s % 3600 === 0) return `${s / 3600} h`;
    return s % 60 === 0 ? `${s / 60} min` : `${s} s`;
}

/** The updates its parent required, as a phrase: "when done, when blocked, before gmail.send_email, every 10 min". */
export function requiredUpdatesText(updates: readonly (string | JsonObject)[]): string {
    return updates
        .map((u) => {
            if (typeof u === 'string') return `when ${u}`;
            if (Array.isArray(u.before)) return `before ${u.before.join(' or ')}`;
            if (typeof u.every_s === 'number') return `every ${seconds(u.every_s)}`;
            return JSON.stringify(u);
        })
        .join(', ');
}

function argumentsText(args: JsonObject | null): string {
    if (!args) return '';
    return Object.entries(args)
        .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)}`)
        .join(' · ');
}

/** One update, as its job's timeline and its parent's wake-up both show it. */
function UpdateLine({ update, compact = false }: { update: JobUpdate; compact?: boolean }) {
    const error = update.error && typeof update.error.message === 'string' ? update.error.message : null;
    const waitingOn = update.waitingOn && typeof update.waitingOn.kind === 'string' ? update.waitingOn : null;
    return (
        <span className="flex min-w-0 flex-col gap-0.5">
            <span className="flex min-w-0 items-baseline gap-2 text-[12px] text-muted-foreground">
                <span className="font-medium text-foreground/80">{UPDATE_KINDS[update.kind] ?? update.kind}</span>
                {update.kind === 'before' && update.tool && <span className="truncate font-mono text-[11.5px]">{update.tool}</span>}
                <TimeCell value={update.createdAt} className="ml-auto shrink-0" />
            </span>
            {update.text && <span className={cn('text-[13px] text-foreground/90', compact && 'line-clamp-2')}>{update.text}</span>}
            {!compact && update.kind === 'before' && update.arguments && <span className="break-words font-mono text-[11.5px] text-muted-foreground">{argumentsText(update.arguments)}</span>}
            {!compact &&
                waitingOn &&
                (typeof waitingOn.url === 'string' ? (
                    <a href={waitingOn.url} target="_blank" rel="noreferrer" className={cn('self-start text-[12px] text-muted-foreground', TEXT_BUTTON)}>
                        Waiting on {WAITING_ON[String(waitingOn.kind)] ?? String(waitingOn.kind)}: open its page
                    </a>
                ) : (
                    // A held call's page goes only to its approver: no agent approves its child's call.
                    <span className="text-[12px] text-muted-foreground">Waiting on {WAITING_ON[String(waitingOn.kind)] ?? String(waitingOn.kind)}; its approver was sent the page</span>
                ))}
            {error && <span className="text-[12px] text-red-600 dark:text-red-400">{error}</span>}
        </span>
    );
}

function JobTimeline({ job }: { job: Job }) {
    const updates = useV1(`operations/${job.id}/updates`, () => job.updates());
    if (updates.error !== undefined) return <ErrorPanel error={updates.error} onRetry={() => void updates.refresh()} className="mt-2" />;
    if (!updates.data) return <div aria-busy className="mt-2 h-10 animate-pulse rounded-lg bg-foreground/[0.03]" />;
    if (!updates.data.length) return <p className="m-0 mt-2 text-[12.5px] text-muted-foreground">No updates yet.</p>;
    return (
        <ol aria-label="Updates" className={cn('m-0 mt-2 flex list-none flex-col gap-3 border-l pl-3', HAIRLINE)}>
            {updates.data.map((u) => (
                <li key={u.id}>
                    <UpdateLine update={u} />
                </li>
            ))}
        </ol>
    );
}

function agentLink(href: (path: string) => string, id: string | null, names: Map<string, AgentName>): ReactNode {
    if (!id) return 'an agent';
    const name = names.get(id)?.name;
    return name ? (
        <Link to={href(`agents/${id}`)} className={LINK}>
            {name}
        </Link>
    ) : (
        <IdChip id={id} />
    );
}

/** One job: who does it, its status, its newest update, and (opened) every update it sent. */
function JobRow({ job, names, headline = true }: { job: Job; names: Map<string, AgentName>; headline?: boolean }) {
    const href = useConsoleHref();
    const [, setOp] = useSearchParam('op');
    const [open, setOpen] = useState(false);
    const latest = job.latestUpdate;
    const task = job.kind === 'agent.task';
    const error = job.error;
    return (
        <li className="flex flex-col gap-1.5 py-3">
            <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <p className="m-0 min-w-0 text-[13.5px] font-medium text-foreground">
                    {headline && (task ? <>Task for {agentLink(href, job.agentId, names)}</> : <>Message to {agentLink(href, job.agentId, names)}</>)}
                    {!headline && 'Its task'}
                </p>
                <span className="flex shrink-0 items-center gap-2 text-[12.5px] text-muted-foreground">
                    <StatusPill look={operationStatus(job.status, error ? { type: error.type } : null, job.kind, job.step)} />
                    <TimeCell value={job.createdAt} />
                </span>
            </div>
            {job.summaryText && <p className="m-0 line-clamp-2 text-[13px] text-muted-foreground">“{job.summaryText}”</p>}
            {latest && !open && (
                <div className={cn('border-l pl-3', HAIRLINE)}>
                    <UpdateLine update={latest} compact />
                </div>
            )}
            {open && <JobTimeline job={job} />}
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
                <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className={cn('inline-flex items-center gap-0.5', TEXT_BUTTON)}>
                    <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-90')} />
                    {open ? 'Hide updates' : 'All updates'}
                </button>
                {job.requiredUpdates.length > 0 && <span>Reports {requiredUpdatesText(job.requiredUpdates)}</span>}
                <span>
                    {job.parentConversation ? (
                        <>
                            Updates wake it in <span className="font-mono text-foreground/85">{job.parentConversation}</span>
                        </>
                    ) : (
                        'Updates wake nobody; they wait here'
                    )}
                </span>
                <button type="button" onClick={() => setOp(job.id, { push: true })} className={TEXT_BUTTON}>
                    Open run
                </button>
            </span>
        </li>
    );
}

/** The jobs it started (spawned tasks, and the messages its agents tools sent), newest first; nothing for an agent that started none. */
export function JobsSection({ agent }: { agent: Agent }) {
    const names = useAgentNames();
    const jobs = useV1(`agents/${agent.id}/jobs`, () => agent.jobs());
    const rows = jobs.data ?? [];
    const live = rows.filter((j) => !j.done).length;
    if (jobs.data && !rows.length && !coordinates(agent)) return null;
    return (
        <PageSection
            title="Jobs"
            count={rows.length}
            note={
                rows.length
                    ? `${live ? `${live} still going. ` : ''}Each update its parent asked for, and each tell_parent, wakes it in the conversation the job started from.`
                    : undefined
            }
        >
            {jobs.error !== undefined && !jobs.data ? (
                <ErrorPanel error={jobs.error} onRetry={() => void jobs.refresh()} />
            ) : !jobs.data ? (
                <div aria-busy className="h-16 animate-pulse rounded-lg bg-foreground/[0.03]" />
            ) : rows.length ? (
                <ul aria-label="Jobs" className={cn('m-0 list-none border-y p-0', HAIRLINE, ROWS)}>
                    {rows.map((job) => (
                        <JobRow key={job.id} job={job} names={names} />
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">
                    None yet. A task it spawns, or a message its agents tools send, is a job: <span className="font-mono text-[12px]">agent.spawn(task, updates=[...])</span>.
                </p>
            )}
        </PageSection>
    );
}

/** A spawned child's own task: what its parent gave it and what it has reported. */
export function TaskSection({ agent }: { agent: Agent }) {
    const href = useConsoleHref();
    const names = useAgentNames();
    const job = agent.job;
    const state = useV1(job ? `operations/${job.id}?job` : null, async () => {
        await job!.hydrate();
        return job!;
    });
    if (!job) return null;
    const loaded = state.data;
    return (
        <PageSection
            title="Task"
            note={
                loaded?.startedBy ? (
                    <>
                        Spawned by {agentLink(href, loaded.startedBy, names)}. It reports with tell_parent, and when its parent asked for more, NoClick makes it.
                    </>
                ) : undefined
            }
        >
            {state.error !== undefined && !loaded ? (
                <ErrorPanel error={state.error} onRetry={() => void state.refresh()} />
            ) : !loaded ? (
                <div aria-busy className="h-16 animate-pulse rounded-lg bg-foreground/[0.03]" />
            ) : (
                <ul aria-label="Its task" className={cn('m-0 list-none border-y p-0', HAIRLINE)}>
                    <JobRow job={loaded} names={names} headline={false} />
                </ul>
            )}
        </PageSection>
    );
}

// ── children ───────────────────────────────────────────────────────────────

/** The agents it spawned: each one's live status, its task's status and its newest update. */
export function ChildrenSection({ agent }: { agent: Agent }) {
    const href = useConsoleHref();
    const children = useV1(`agents/${agent.id}/children`, () => agent.children());
    // One read of its jobs gives each spawned child's task.
    const spawned = (children.data ?? []).some((c) => c.jobId);
    const jobs = useV1(spawned ? `agents/${agent.id}/jobs` : null, () => agent.jobs());
    const taskOf = useMemo(() => new Map((jobs.data ?? []).filter((j) => j.kind === 'agent.task').map((j) => [j.agentId, j])), [jobs.data]);
    const rows = children.data ?? [];
    // `childCount` counts live children only: the read decides for an agent whose children all expired.
    const known = (agent.childCount ?? 0) > 0 || coordinates(agent);
    if (!known && children.error === undefined && !rows.length) return null;
    return (
        <PageSection
            title="Children"
            count={children.data ? rows.length || null : agent.childCount || null}
            note={rows.length ? 'Agents made under it. Each spends from its budget and never outlives it; an expired one stays readable for 30 days.' : undefined}
        >
            {children.error !== undefined && !children.data ? (
                <ErrorPanel error={children.error} onRetry={() => void children.refresh()} />
            ) : !children.data ? (
                <div aria-busy className="h-12 animate-pulse rounded-lg bg-foreground/[0.03]" />
            ) : rows.length ? (
                <ul aria-label="Children" className={cn('m-0 list-none border-y p-0', HAIRLINE, ROWS)}>
                    {rows.map((child) => {
                        const job = taskOf.get(child.id);
                        const look = agentStatus(child.status, child.runningTurns);
                        const update = job?.latestUpdate;
                        return (
                            <li key={child.id}>
                                <Link
                                    to={href(`agents/${child.id}`)}
                                    className="-mx-3 grid grid-cols-1 items-start gap-x-6 gap-y-1.5 rounded-lg px-3 py-3 transition-colors hover:bg-foreground/[0.03] sm:grid-cols-[minmax(0,1fr)_auto]"
                                >
                                    <span className="min-w-0">
                                        <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                                            <span className="break-all text-[14px] font-medium text-foreground">{child.name}</span>
                                            {child.expiresAt && child.status !== 'expired' && (
                                                <span className="shrink-0 text-[12px] text-muted-foreground">
                                                    expires <TimeCell value={child.expiresAt} />
                                                </span>
                                            )}
                                        </span>
                                        {update ? (
                                            <span className="mt-0.5 block line-clamp-2 text-[13px] text-muted-foreground">
                                                <span className="text-foreground/75">{UPDATE_KINDS[update.kind] ?? update.kind}:</span> {update.text}
                                            </span>
                                        ) : (
                                            job?.summaryText && <span className="mt-0.5 block truncate text-[13px] text-muted-foreground">{job.summaryText}</span>
                                        )}
                                    </span>
                                    <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 sm:flex-col sm:items-end">
                                        {look && <StatusPill look={look} />}
                                        {job && (
                                            <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
                                                Task
                                                <StatusPill look={operationStatus(job.status, job.error ? { type: job.error.type } : null, job.kind, job.step)} className="text-[12px]" />
                                            </span>
                                        )}
                                    </span>
                                </Link>
                            </li>
                        );
                    })}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">
                    None yet. With the <span className="font-mono text-[12px]">agents</span> tools it spawns its own helpers; your code does with{' '}
                    <span className="font-mono text-[12px]">agent.spawn(task)</span>.
                </p>
            )}
        </PageSection>
    );
}

// ── wake-ups ───────────────────────────────────────────────────────────────

const SOURCES: Record<string, { label: string; Icon: LucideIcon }> = {
    code: { label: 'Set by your code', Icon: Code2 },
    wake_me: { label: 'Set by itself', Icon: AlarmClock },
    update: { label: 'An update', Icon: Radio },
    answer: { label: 'A connect link it asked for', Icon: MessageCircleQuestion },
    approval: { label: 'A decided approval', Icon: Hand },
    continue: { label: 'Carrying on a long turn', Icon: Redo2 },
};

function filtersText(filters: unknown): string {
    if (!filters || typeof filters !== 'object') return '';
    const pairs = Object.entries(filters as JsonObject).map(([k, v]) => `${k} = ${String(v)}`);
    return pairs.length ? ` where ${pairs.join(', ')}` : '';
}

/** What a pending wake-up waits for: a moment, an operation settling, an event. */
function WaitsFor({ wakeup, jobs }: { wakeup: Wakeup; jobs: Job[] }) {
    const [, setOp] = useSearchParam('op');
    const when = wakeup.when;
    if (when && typeof when.operation_id === 'string') {
        const job = jobs.find((j) => j.id === when.operation_id);
        return (
            <span>
                When{' '}
                <button type="button" onClick={() => setOp(String(when.operation_id), { push: true })} className={cn('text-foreground/85', LINK)}>
                    {job ? (job.kind === 'agent.task' ? 'a task it spawned' : 'a message it sent') : 'an operation'}
                </button>{' '}
                ends
            </span>
        );
    }
    if (when && typeof when.event === 'string') {
        return (
            <span>
                On <span className="font-mono text-[12px] text-foreground/85">{when.event}</span>
                {filtersText(when.filters)}
            </span>
        );
    }
    return wakeup.at ? (
        <span>
            Due <TimeCell value={wakeup.at} />
        </span>
    ) : null;
}

function CancelWakeupDialog({ agent, wakeup, onCanceled, onClose }: { agent: Agent; wakeup: Wakeup; onCanceled: (w: Wakeup) => void; onClose: () => void }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const cancel = async () => {
        setBusy(true);
        setError(undefined);
        try {
            onCanceled(await wakeup.cancel());
            toast.success('Wake-up canceled');
            onClose();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="sm"
            title="Cancel this wake-up?"
            description={`${agent.name} won't take the turn it was set for. What it waits on still happens; only the turn is skipped.`}
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Keep it
                    </ConsoleButton>
                    <ConsoleButton variant="danger" onClick={() => void cancel()} disabled={busy}>
                        {busy ? 'Canceling…' : 'Cancel wake-up'}
                    </ConsoleButton>
                </>
            }
        >
            {error !== undefined && <ErrorPanel error={error} />}
        </ConsoleDialog>
    );
}

function WakeupRow({ wakeup, jobs, onCancel, showUser }: { wakeup: Wakeup; jobs: Job[]; onCancel: (w: Wakeup) => void; showUser: boolean }) {
    const [, setOp] = useSearchParam('op');
    const source = SOURCES[wakeup.source] ?? { label: wakeup.source, Icon: AlarmClock };
    const errorType = wakeup.error && typeof wakeup.error.type === 'string' ? wakeup.error.type : null;
    const errorText = wakeup.error && typeof wakeup.error.message === 'string' ? wakeup.error.message : null;
    const update = wakeup.wokenBy && typeof wakeup.wokenBy.update === 'object' ? (wakeup.wokenBy.update as JsonObject) : null;
    return (
        <li className="flex gap-3 py-3">
            <span title={source.label} className={cn('mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border bg-foreground/[0.03] text-foreground', HAIRLINE)}>
                <source.Icon aria-label={source.label} className="h-3.5 w-3.5" />
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                    <p className="m-0 min-w-0 text-[13.5px] text-foreground">{wakeup.note}</p>
                    <span className="flex shrink-0 items-center gap-2 text-[12.5px] text-muted-foreground">
                        <StatusPill look={wakeupStatus(wakeup.status, errorType)} />
                        {wakeup.status === 'delivered' && wakeup.deliveredAt && <TimeCell value={wakeup.deliveredAt} />}
                    </span>
                </div>
                <span className="flex flex-wrap items-baseline gap-x-1.5 text-[12.5px] text-muted-foreground">
                    <span>{source.label}</span>
                    {wakeup.source === 'wake_me' && wakeup.depth > 1 && <span>· {wakeup.depth} in a row</span>}
                    {wakeup.status === 'pending' && (
                        <>
                            <span aria-hidden>·</span>
                            <WaitsFor wakeup={wakeup} jobs={jobs} />
                        </>
                    )}
                    <span aria-hidden>·</span>
                    {showUser && <span>{userLabel(wakeup.userId)}:</span>}
                    <span className="font-mono text-[12px] text-foreground/80">{wakeup.conversation}</span>
                </span>
                {update && typeof update.text === 'string' && <span className="line-clamp-2 text-[12.5px] text-muted-foreground">“{update.text}”</span>}
                {errorText && <span className="text-[12.5px] text-red-600 dark:text-red-400">{errorText}</span>}
                <span className="flex items-center gap-3 text-[12px] text-muted-foreground">
                    {wakeup.operationId && (
                        <button type="button" onClick={() => setOp(wakeup.operationId!, { push: true })} className={TEXT_BUTTON}>
                            Its turn
                        </button>
                    )}
                    {wakeup.status === 'pending' && (
                        <button type="button" onClick={() => onCancel(wakeup)} className={TEXT_BUTTON}>
                            Cancel
                        </button>
                    )}
                </span>
            </div>
        </li>
    );
}

/** What will wake it, then what woke it: its own wake_me, your code's agent.wake, and NoClick's (updates, answers, approvals). */
export function WakeupsSection({ agent }: { agent: Agent }) {
    const key = `agents/${agent.id}/wakeups`;
    // An account agent's wake-ups are in every user's threads it talks in; a user's agent has only its user's.
    const shared = !agent.userId;
    const wakeups = useV1(key, () => agent.wakeups(shared ? { userFilter: ALL_USERS } : { user: agent.userId }));
    const [all, setAll] = useState(false);
    const [canceling, setCanceling] = useState<Wakeup | null>(null);
    const rows = wakeups.data ?? [];
    // Its jobs name what a pending wake-up waits on: read only when one waits on an operation.
    const onOperation = rows.some((w) => w.status === 'pending' && typeof w.when?.operation_id === 'string');
    const jobs = useV1(onOperation ? `agents/${agent.id}/jobs` : null, () => agent.jobs());
    const pending = rows.filter((w) => w.status === 'pending');
    const past = rows.filter((w) => w.status !== 'pending');
    const shown = [...pending, ...(all ? past : past.slice(0, RECENT_WAKEUPS))];
    return (
        <PageSection
            title="Wake-ups"
            count={pending.length || null}
            note={
                rows.length
                    ? 'Each takes a turn in its conversation, after any turn running there, with its note and what woke it. They are billed and capped like any turn.'
                    : undefined
            }
        >
            {wakeups.error !== undefined && !wakeups.data ? (
                <ErrorPanel error={wakeups.error} onRetry={() => void wakeups.refresh()} />
            ) : !wakeups.data ? (
                <div aria-busy className="h-14 animate-pulse rounded-lg bg-foreground/[0.03]" />
            ) : rows.length ? (
                <>
                    <ul aria-label="Wake-ups" className={cn('m-0 list-none border-y p-0', HAIRLINE, ROWS)}>
                        {shown.map((w) => (
                            <WakeupRow key={w.id} wakeup={w} jobs={jobs.data ?? []} onCancel={setCanceling} showUser={shared} />
                        ))}
                    </ul>
                    {past.length > RECENT_WAKEUPS && (
                        <button type="button" onClick={() => setAll((a) => !a)} className="mt-3 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                            {all ? 'Show fewer' : `Show ${past.length - RECENT_WAKEUPS} more`}
                        </button>
                    )}
                </>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">
                    Nothing will wake it. It can set a wake-up itself with its <span className="font-mono text-[12px]">wake_me</span> tool, and your code with{' '}
                    <span className="font-mono text-[12px]">agent.wake(conversation, note=..., after=...)</span>.
                </p>
            )}
            {canceling && (
                <CancelWakeupDialog
                    agent={agent}
                    wakeup={canceling}
                    onCanceled={(w) => wakeups.mutate(rows.map((r) => (r.id === w.id ? w : r)))}
                    onClose={() => setCanceling(null)}
                />
            )}
        </PageSection>
    );
}

// ── ask ────────────────────────────────────────────────────────────────────

/** Ask it something without stopping it: from a snapshot, or (interject) inside its running turn. */
export function AskSection({ agent }: { agent: Agent }) {
    const [, setOp] = useSearchParam('op');
    const [question, setQuestion] = useState('');
    const [conversation, setConversation] = useState('');
    const [interject, setInterject] = useState(false);
    const [asking, setAsking] = useState(false);
    const [answer, setAnswer] = useState<{ reply: AgentReply; interject: boolean } | null>(null);
    const [error, setError] = useState<unknown>(undefined);
    const cli = agent.harness !== null && agent.harness !== 'sdk';
    const ask = async () => {
        setAsking(true);
        setError(undefined);
        setAnswer(null);
        try {
            const reply = await agent.ask(question.trim(), { conversation: conversation.trim() || undefined, interject, user: agent.userId });
            setAnswer({ reply, interject });
            invalidateV1('operations');
        } catch (err) {
            setError(err);
        } finally {
            setAsking(false);
        }
    };
    const joined = answer && typeof answer.reply.raw.joined === 'string' ? answer.reply.raw.joined : null;
    return (
        <PageSection
            title="Ask"
            note={
                <>
                    Its model answers from a snapshot of the conversation; the agent never sees the question, and nothing it is doing stops.
                    {cli && ` On ${agent.harness}, the snapshot is the conversation to its last finished turn plus the NoClick tools the running turn has called; interject to reach what it's doing right now.`}
                </>
            }
        >
            <form
                className="flex flex-col gap-3"
                onSubmit={(e) => {
                    e.preventDefault();
                    void ask();
                }}
            >
                <FormField label="Question">
                    <textarea
                        value={question}
                        onChange={(e) => setQuestion(e.target.value)}
                        rows={2}
                        className={cn(inputClass, 'h-auto py-2 leading-relaxed')}
                        placeholder="How far along is the research?"
                    />
                </FormField>
                <FormField label="Conversation (optional)" hint="Its key, as Conversations lists it; empty, a spawned child's task, else the one it last worked in.">
                    <input value={conversation} onChange={(e) => setConversation(e.target.value)} className={cn(inputClass, 'font-mono text-[12.5px]')} />
                </FormField>
                <label className="flex items-start gap-2 text-[13px] text-foreground">
                    <input type="checkbox" checked={interject} onChange={(e) => setInterject(e.target.checked)} className="mt-[3px]" />
                    <span>
                        Interject
                        <span className="block text-[12px] text-muted-foreground">Put the question into its running turn: it sees it, may change course, and answers there.</span>
                    </span>
                </label>
                <ConsoleButton type="submit" className="self-start" icon={<MessageSquareText className="h-3.5 w-3.5" />} disabled={asking || !question.trim()}>
                    {asking ? 'Asking…' : 'Ask'}
                </ConsoleButton>
            </form>
            {error !== undefined && <ErrorPanel error={error} className="mt-4" />}
            {answer && (
                <section aria-label="Answer" className={cn('mt-4 rounded-lg border p-3', HAIRLINE)}>
                    <p className="m-0 whitespace-pre-wrap text-sm text-foreground">{answer.reply.text}</p>
                    <p className="m-0 mt-2 flex flex-wrap items-center gap-x-3 text-[12px] text-muted-foreground">
                        <span>
                            {joined
                                ? 'Joined its running turn'
                                : answer.interject
                                  ? 'Nothing was running, so it took the question as a message'
                                  : 'Answered from a snapshot, not added to the conversation'}
                            {answer.reply.conversation && (
                                <>
                                    {' '}
                                    · <span className="font-mono">{answer.reply.conversation}</span>
                                </>
                            )}
                        </span>
                        {answer.reply.operationId && (
                            <button type="button" onClick={() => setOp(answer.reply.operationId!, { push: true })} className={TEXT_BUTTON}>
                                Open run
                            </button>
                        )}
                        {joined && (
                            <button type="button" onClick={() => setOp(joined, { push: true })} className={TEXT_BUTTON}>
                                The turn it joined
                            </button>
                        )}
                    </p>
                </section>
            )}
        </PageSection>
    );
}
