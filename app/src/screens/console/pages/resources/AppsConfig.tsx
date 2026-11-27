// The Apps drawer's Bindings, Secrets and Schedules tabs: what the running app is given by name (bind and unbind; an agent
// too, which the app then talks to as itself), plain settings with their values,
// secret names with when each was set (values are write-only), and its cron jobs
// in plain English with why one paused or last failed, pause, resume, run now
// and delete.
import { useEffect, useState, type ReactNode } from 'react';
import { Bot, Braces, Database as DatabaseIcon, HardDrive, ListOrdered, LockKeyhole, PlugZap, type LucideIcon } from 'lucide-react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { FieldSelect } from '@/ui/FieldSelect';
import { Agent, Bucket, Connection, Database, Dict, NO_USER, Queue, Secret, type Binding, type BindingKind, type NoClick, type Project, type Schedule, type UserFilter } from 'noclick';
import { formatTimeTooltip } from '@/screens/console/lib/format';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { describeCron, lastRunLook, scheduleLook, SCHEDULES_EMPTY, zoneLabel } from './AppsFormat';
import { ActsFor, ConfirmAction, errorText, INPUT, LabeledInput, Section } from './shared';

const NEXT_DEPLOY = 'Changes reach the app at its next deploy.';

function Header({ title, action }: { title: string; action?: ReactNode }) {
    return (
        <span className="flex items-center justify-between gap-2">
            <span>{title}</span>
            {action}
        </span>
    );
}

function Loading({ height = 'h-24' }: { height?: string }) {
    return <div aria-busy className={cn('animate-pulse rounded-lg bg-foreground/[0.04]', height)} />;
}

// ── bindings ─────────────────────────────────────────────────────────────

/** Each kind's label, icon and where its own page is (`to` the resource's id). */
const KINDS: Record<BindingKind, { label: string; icon: LucideIcon; to: (id: string) => [string, Record<string, string>?] }> = {
    database: { label: 'Database', icon: DatabaseIcon, to: (id) => ['resources/databases', { database: id }] },
    bucket: { label: 'Bucket', icon: HardDrive, to: (id) => ['resources/storage', { bucket: id }] },
    connection: { label: 'Connection', icon: PlugZap, to: () => ['resources/connections'] },
    dict: { label: 'Dict', icon: Braces, to: (id) => ['resources/dicts', { dict: id }] },
    queue: { label: 'Queue', icon: ListOrdered, to: (id) => ['resources/queues', { queue: id }] },
    secret: { label: 'Secret', icon: LockKeyhole, to: (id) => ['resources/secrets', { secret: id }] },
    agent: { label: 'Agent', icon: Bot, to: (id) => [`agents/${id}`] },
};

/** Each kind's list read. */
const LISTERS: Record<BindingKind, { list(options: { client: NoClick; userFilter: UserFilter; limit: number }): Promise<{ id: string; name: string }[]> }> = {
    database: Database,
    bucket: Bucket,
    connection: Connection,
    dict: Dict,
    queue: Queue,
    secret: Secret,
    agent: Agent,
};

/**
 * The resources the app's user has (or your account's, for an app of your own), of one kind, as
 * `{id, name}` choices. A user's app may also bind one of your account's agents, which serve every user.
 */
function useBindable(project: Project, kind: BindingKind, enabled: boolean) {
    const { client } = useConsole();
    const userFilter = project.userId ?? NO_USER;
    const scopes: UserFilter[] = kind === 'agent' && project.userId ? [project.userId, NO_USER] : [userFilter];
    return useV1(enabled ? `bindable?${kind}&${userFilter}` : null, async () => {
        const lists = await Promise.all(scopes.map((scope) => LISTERS[kind].list({ client, userFilter: scope, limit: 100 })));
        const rows = new Map(lists.flat().map((r) => [r.id, { id: r.id, name: r.name }]));
        return [...rows.values()];
    });
}

function BindDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (open: boolean) => void }) {
    const [name, setName] = useState('');
    const [kind, setKind] = useState<BindingKind>('database');
    const [resourceId, setResourceId] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const choices = useBindable(project, kind, open);
    useEffect(() => setResourceId(''), [kind]);
    useEffect(() => {
        if (open) return;
        setName('');
        setKind('database');
        setError(undefined);
    }, [open]);
    const valid = /^[A-Z][A-Z0-9_]*$/.test(name) && !!resourceId;
    const bind = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await project.bind(name, resourceId, { kind });
            invalidateV1(`projects/${project.id}/bindings`);
            toast(`Bound ${name}. ${NEXT_DEPLOY}`);
            onOpenChange(false);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            mark={<PlugZap aria-hidden className="h-5 w-5" />}
            title="Give the app a resource"
            description={`Its code reaches it under the name you give it here. ${NEXT_DEPLOY}`}
            footer={
                <ConsoleButton variant="primary" disabled={busy || !valid} onClick={() => void bind()}>
                    {busy ? 'Adding…' : 'Add'}
                </ConsoleButton>
            }
        >
            <div className="flex flex-col gap-3">
                <ActsFor userId={project.userId} />
                <LabeledInput label="Name in its code" id="binding-name">
                    <input id="binding-name" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value.toUpperCase())} placeholder="DB" autoComplete="off" />
                </LabeledInput>
                <LabeledInput label="What it is" id="binding-kind">
                    <FieldSelect id="binding-kind" value={kind} onValueChange={(k) => setKind(k as BindingKind)} options={(Object.keys(KINDS) as BindingKind[]).map((k) => ({ value: k, label: KINDS[k].label }))} />
                </LabeledInput>
                <LabeledInput label={KINDS[kind].label} id="binding-resource">
                    <FieldSelect
                        id="binding-resource"
                        value={resourceId}
                        onValueChange={setResourceId}
                        disabled={!choices.data?.length}
                        placeholder={choices.loading ? 'Loading…' : choices.data?.length ? `Choose a ${KINDS[kind].label.toLowerCase()}` : `No ${KINDS[kind].label.toLowerCase()}s ${project.userId ? `for ${project.userId}` : 'in your account'}`}
                        options={(choices.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
                    />
                </LabeledInput>
                {choices.error !== undefined && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{errorText(choices.error)}</p>}
                {error !== undefined && <ErrorPanel error={error} />}
            </div>
        </ConsoleDialog>
    );
}

function BindingRow({ project, binding }: { project: Project; binding: Binding }) {
    const href = useConsoleHref();
    const meta = KINDS[binding.kind] ?? KINDS.database;
    const Icon = meta.icon;
    const target = href(...meta.to(binding.resourceId));
    return (
        <li className="flex items-center gap-3 py-2.5">
            <span className="w-28 shrink-0 truncate font-mono text-[13px] font-medium text-foreground">{binding.name}</span>
            <span className="flex min-w-0 flex-1 items-center gap-2">
                <span className={cn('inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-foreground/70', HAIRLINE)} title={meta.label}>
                    <Icon aria-hidden className="h-3.5 w-3.5" />
                </span>
                <Link to={target} className="min-w-0 truncate text-[13px] text-foreground hover:underline">
                    {binding.resourceName ?? binding.resourceId}
                </Link>
                <span className="hidden text-[12px] text-muted-foreground sm:inline">{meta.label.toLowerCase()}</span>
            </span>
            <ConfirmAction
                label="Unbind"
                title={`Unbind ${binding.name}?`}
                description={`The app stops seeing ${binding.name} at its next deploy. ${binding.resourceName ?? 'The resource'} itself is kept.`}
                confirmLabel="Unbind"
                onConfirm={async () => {
                    await project.unbind(binding.name);
                    invalidateV1(`projects/${project.id}/bindings`);
                    toast(`Unbound ${binding.name}. ${NEXT_DEPLOY}`);
                }}
            />
        </li>
    );
}

export function AppBindings({ project }: { project: Project }) {
    const bindings = useV1(`projects/${project.id}/bindings`, () => project.bindings());
    const [binding, setBinding] = useState(false);
    const rows = bindings.data ?? [];
    return (
        <Section
            title={
                <Header
                    title="Bindings"
                    action={
                        <ConsoleButton size="sm" onClick={() => setBinding(true)}>
                            Bind
                        </ConsoleButton>
                    }
                />
            }
        >
            <p className="m-0 mb-2 text-[12px] text-muted-foreground">What the app reads by name: databases, buckets, dicts, queues, secrets, connections, and agents it talks to as itself. Previews get the same ones.</p>
            {bindings.error !== undefined ? (
                <ErrorPanel error={bindings.error} onRetry={() => void bindings.refresh()} />
            ) : bindings.loading ? (
                <Loading />
            ) : rows.length === 0 ? (
                <p className="m-0 text-[13px] text-muted-foreground">Nothing bound yet. Bind a database, a bucket, a queue or any other resource to give the app its data.</p>
            ) : (
                <ul aria-label="Bindings" className={'m-0 list-none p-0'}>
                    {rows.map((b) => (
                        <BindingRow key={b.name} project={project} binding={b} />
                    ))}
                </ul>
            )}
            <BindDialog project={project} open={binding} onOpenChange={setBinding} />
        </Section>
    );
}

// ── settings ─────────────────────────────────────────────────────────────

const SETTING_NAME = /^[A-Za-z][A-Za-z0-9_]*$/;

/** Plain values the app reads from its environment, shown and edited as they are (a key goes in Secrets). */
export function AppSettings({ project }: { project: Project }) {
    const key = `projects/${project.id}/settings`;
    const settings = useV1(key, () => project.settings.list());
    const [name, setName] = useState('');
    const [value, setValue] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const rows = Object.entries(settings.data ?? {});
    const save = async (n: string, v: string) => {
        setBusy(true);
        setError(null);
        try {
            await project.settings.set(n, v);
            invalidateV1(key);
            toast(`Set ${n}. ${NEXT_DEPLOY}`);
            setName('');
            setValue('');
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <Section title="Settings">
            <p className="m-0 mb-2 text-[12px] text-muted-foreground">Plain values the app reads from its environment, readable here. Keys and passwords go in Secrets.</p>
            {settings.error !== undefined ? (
                <ErrorPanel error={settings.error} onRetry={() => void settings.refresh()} />
            ) : settings.loading ? (
                <Loading height="h-16" />
            ) : rows.length > 0 ? (
                <ul aria-label="Settings" className={'m-0 list-none p-0'}>
                    {rows.map(([n, v]) => (
                        <li key={n} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
                            <span className="min-w-0 truncate font-mono text-[13px] font-medium text-foreground sm:w-56">{n}</span>
                            <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-foreground/85">{v}</span>
                            <ConsoleButton
                                size="sm"
                                variant="ghost"
                                onClick={() => {
                                    setName(n);
                                    setValue(v);
                                }}
                            >
                                Edit
                            </ConsoleButton>
                            <ConfirmAction
                                label="Delete"
                                title={`Delete ${n}?`}
                                description={`The app stops seeing ${n} at its next deploy.`}
                                confirmLabel="Delete setting"
                                onConfirm={async () => {
                                    await project.settings.delete(n);
                                    invalidateV1(key);
                                    toast(`Deleted ${n}. ${NEXT_DEPLOY}`);
                                }}
                            />
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">No settings yet.</p>
            )}
            <form
                aria-label="Set a setting"
                className="mt-3 flex flex-wrap items-end gap-2"
                onSubmit={(e) => {
                    e.preventDefault();
                    if (SETTING_NAME.test(name) && value) void save(name, value);
                }}
            >
                <LabeledInput label="Name" id="setting-name">
                    <input
                        id="setting-name"
                        className={cn(INPUT, 'w-48 font-mono')}
                        value={name}
                        onChange={(e) => setName(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))}
                        placeholder="SUPPORT_EMAIL"
                        autoComplete="off"
                    />
                </LabeledInput>
                <LabeledInput label="Value" id="setting-value">
                    <input id="setting-value" className={cn(INPUT, 'w-64 font-mono')} value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" />
                </LabeledInput>
                <ConsoleButton type="submit" size="sm" disabled={busy || !SETTING_NAME.test(name) || !value}>
                    {busy ? 'Saving…' : 'Set'}
                </ConsoleButton>
                {error && <span className="text-[12px] text-red-600 dark:text-red-400">{error}</span>}
            </form>
        </Section>
    );
}

// ── secrets ──────────────────────────────────────────────────────────────

function SetSecretDialog({ project, open, name: initial, onOpenChange }: { project: Project; open: boolean; name: string | null; onOpenChange: (open: boolean) => void }) {
    const [name, setName] = useState('');
    const [value, setValue] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    useEffect(() => {
        if (!open) return;
        setName(initial ?? '');
        setValue('');
        setError(undefined);
    }, [open, initial]);
    const valid = /^[A-Za-z][A-Za-z0-9_]*$/.test(name) && value.length > 0;
    const save = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await project.secrets.set(name, value);
            setValue('');
            invalidateV1(`projects/${project.id}/secrets`);
            toast(`${initial ? 'Replaced' : 'Set'} ${name}. ${NEXT_DEPLOY}`);
            onOpenChange(false);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            mark={<LockKeyhole aria-hidden className="h-5 w-5" />}
            title={initial ? `Replace ${initial}` : 'Set a secret'}
            description="Values are write-only: once saved, nobody can read one back, here or through the API."
            footer={
                <ConsoleButton variant="primary" disabled={busy || !valid} onClick={() => void save()}>
                    {busy ? 'Saving…' : 'Save'}
                </ConsoleButton>
            }
        >
            <form
                className="flex flex-col gap-3"
                onSubmit={(e) => {
                    e.preventDefault();
                    if (valid) void save();
                }}
            >
                <LabeledInput label="Name" id="secret-name">
                    <input
                        id="secret-name"
                        className={cn(INPUT, 'font-mono')}
                        value={name}
                        disabled={!!initial}
                        onChange={(e) => setName(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))}
                        placeholder="MAPS_API_KEY"
                        autoComplete="off"
                    />
                </LabeledInput>
                <LabeledInput label="Value" id="secret-value">
                    <input id="secret-value" type="password" className={cn(INPUT, 'font-mono')} value={value} onChange={(e) => setValue(e.target.value)} autoComplete="new-password" />
                </LabeledInput>
                {error !== undefined && <ErrorPanel error={error} />}
            </form>
        </ConsoleDialog>
    );
}

export function AppSecrets({ project }: { project: Project }) {
    const secrets = useV1(`projects/${project.id}/secrets`, () => project.secrets.list());
    const [editing, setEditing] = useState<{ name: string | null } | null>(null);
    const rows = Object.entries(secrets.data ?? {});
    return (
        <Section
            title={
                <Header
                    title="Secrets"
                    action={
                        <ConsoleButton size="sm" onClick={() => setEditing({ name: null })}>
                            Set secret
                        </ConsoleButton>
                    }
                />
            }
        >
            <p className="m-0 mb-2 text-[12px] text-muted-foreground">Values the app reads from its environment. Only names show here; a value never comes back.</p>
            {secrets.error !== undefined ? (
                <ErrorPanel error={secrets.error} onRetry={() => void secrets.refresh()} />
            ) : secrets.loading ? (
                <Loading />
            ) : rows.length === 0 ? (
                <p className="m-0 text-[13px] text-muted-foreground">No secrets yet. Set API keys and other values the app shouldn’t keep in its repo.</p>
            ) : (
                <ul aria-label="Secrets" className={'m-0 list-none p-0'}>
                    {rows.map(([name, updatedAt]) => (
                        <li key={name} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
                            <span className="w-full min-w-0 truncate font-mono text-[13px] font-medium text-foreground sm:w-auto sm:flex-1">{name}</span>
                            <span aria-hidden className="hidden font-mono text-[12px] tracking-widest text-muted-foreground sm:inline">
                                ••••••••
                            </span>
                            <span className="mr-auto shrink-0 text-[12px] text-muted-foreground sm:mr-0 sm:w-24 sm:text-right">
                                set <TimeCell value={updatedAt} />
                            </span>
                            <ConsoleButton size="sm" variant="ghost" onClick={() => setEditing({ name })}>
                                Replace
                            </ConsoleButton>
                            <ConfirmAction
                                label="Delete"
                                title={`Delete ${name}?`}
                                description={`The app stops seeing ${name} at its next deploy. The value can’t be recovered.`}
                                confirmLabel="Delete secret"
                                onConfirm={async () => {
                                    await project.secrets.delete(name);
                                    invalidateV1(`projects/${project.id}/secrets`);
                                    toast(`Deleted ${name}. ${NEXT_DEPLOY}`);
                                }}
                            />
                        </li>
                    ))}
                </ul>
            )}
            <SetSecretDialog project={project} open={editing !== null} name={editing?.name ?? null} onOpenChange={(open) => !open && setEditing(null)} />
        </Section>
    );
}

// ── schedules ────────────────────────────────────────────────────────────

/** `Mon, Sep 28, 9:00 AM`, on the schedule's own clock (its `tz` shows beside it); a `user` one on yours. */
function wallClock(at: Date, tz: string): string {
    return new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: tz === 'user' ? undefined : tz }).format(at);
}

function ScheduleRow({ schedule: initial }: { schedule: Schedule }) {
    const [schedule, setSchedule] = useState(initial);
    const [busy, setBusy] = useState(false);
    useEffect(() => setSchedule(initial), [initial]);
    const act = async (write: () => Promise<Schedule>, done: (s: Schedule) => string) => {
        setBusy(true);
        try {
            const next = await write();
            setSchedule(next);
            toast(done(next));
        } catch (e) {
            toast(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    const english = describeCron(schedule.cron);
    // A breaker pause already names the error it kept failing with.
    const lastError = schedule.lastStatus === 'failed' && schedule.lastError && !schedule.pausedReason?.endsWith(schedule.lastError) ? schedule.lastError : null;
    return (
        <li className="flex flex-col gap-2 py-3">
            <div className="flex items-start gap-3">
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-[14px] font-medium text-foreground">{english ?? schedule.cron}</span>
                    <span className="truncate text-[12px] text-muted-foreground">
                        {english && <span className="font-mono">{schedule.cron}</span>}
                        {english && ' · '}
                        {zoneLabel(schedule.tz)} · POST <span className="font-mono text-foreground/80">{schedule.path}</span>
                        {schedule.name !== schedule.path && <> · {schedule.name}</>}
                    </span>
                </div>
                <StatusPill look={scheduleLook(schedule)} className="shrink-0" />
            </div>
            {schedule.status === 'paused' && schedule.pausedReason && <p className="m-0 text-[13px] text-red-600 dark:text-red-400">{schedule.pausedReason}</p>}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted-foreground">
                <span>
                    Next run:{' '}
                    {schedule.status === 'active' && schedule.nextRun ? (
                        <time dateTime={schedule.nextRun.toISOString()} title={formatTimeTooltip(schedule.nextRun)} className="text-foreground/80">
                            {wallClock(schedule.nextRun, schedule.tz)}
                        </time>
                    ) : (
                        <span>none while paused</span>
                    )}
                </span>
                <span className="inline-flex items-center gap-1.5">
                    Last run:{' '}
                    {schedule.lastRun ? (
                        <>
                            <TimeCell value={schedule.lastRun} className="text-foreground/80" />
                            <StatusPill look={lastRunLook(schedule.lastStatus)} />
                            {lastError && <span className="text-red-600 dark:text-red-400">{lastError}</span>}
                        </>
                    ) : (
                        <span>never</span>
                    )}
                </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                {schedule.status === 'active' ? (
                    <ConsoleButton size="sm" disabled={busy} onClick={() => void act(() => schedule.pause(), () => `Paused ${schedule.path}`)}>
                        Pause
                    </ConsoleButton>
                ) : (
                    <ConsoleButton size="sm" disabled={busy} onClick={() => void act(() => schedule.resume(), () => `Resumed ${schedule.path}`)}>
                        Resume
                    </ConsoleButton>
                )}
                <ConsoleButton size="sm" variant="ghost" disabled={busy} onClick={() => void act(() => schedule.runNow(), (s) => `Ran ${s.path}: ${s.lastStatus === 'succeeded' ? 'it answered 2xx' : (s.lastError ?? 'it failed')}`)}>
                    {busy ? 'Working…' : 'Run now'}
                </ConsoleButton>
                <span className="flex-1" />
                <ConfirmAction
                    label="Delete"
                    title="Delete this schedule?"
                    description={`NoClick stops calling ${schedule.path}. Code that calls app.schedule with this name creates it again on its next run.`}
                    confirmLabel="Delete schedule"
                    onConfirm={async () => {
                        await schedule.delete();
                        invalidateV1(`projects/${schedule.projectId}/schedules`);
                        toast('Schedule deleted');
                    }}
                />
            </div>
        </li>
    );
}

export function AppSchedules({ project }: { project: Project }) {
    const schedules = useV1(`projects/${project.id}/schedules`, () => project.schedules());
    const rows = schedules.data ?? [];
    return (
        <Section title="Schedules">
            <p className="m-0 mb-2 text-[12px] text-muted-foreground">
                NoClick POSTs each path on its schedule, signed. When 5 runs in a row fail the same way, over at least 30 minutes, a schedule pauses itself until you resume it.
            </p>
            {schedules.error !== undefined ? (
                <ErrorPanel error={schedules.error} onRetry={() => void schedules.refresh()} />
            ) : schedules.loading ? (
                <Loading height="h-40" />
            ) : rows.length === 0 ? (
                <EmptyCode className="px-0 py-2" title="No schedules yet." hint="Your code adds one with app.schedule; calling it again with the same name updates it." snippet={SCHEDULES_EMPTY} />
            ) : (
                <ul aria-label="Schedules" className={'m-0 list-none p-0'}>
                    {rows.map((s) => (
                        <ScheduleRow key={s.id} schedule={s} />
                    ))}
                </ul>
            )}
        </Section>
    );
}
