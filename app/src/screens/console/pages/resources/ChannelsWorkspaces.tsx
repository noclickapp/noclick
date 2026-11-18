// What a channel is subscribed to (an app's events or a webhook; NoClick's own
// events are designed), and the workspace rail beside the channel list, as in
// Slack (a workspace shows its logo, else its initials), with the selected
// workspace's members and spend, and what a whole workspace is subscribed to.
import { useState, type ReactNode } from 'react';
import { MessagesSquare } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/ui/tooltip';
import { cn } from '@/ui/utils';
import { formatCount } from '@/screens/console/lib/format';
import { Workspace, type Channel, type JsonObject, type Subscription } from 'noclick';
import { subscriptionStatus } from '@/screens/console/lib/status';
import { userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { useV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { CapMeter } from '../../ui/CapMeter';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { CopyButton } from '../../ui/CopyButton';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { FacetSelect } from '../../ui/FacetSelect';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { useAgentNames } from '../lookups';
import { Section } from './shared';

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

// ── workspaces ─────────────────────────────────────────────────────────────

/** Slack's rule: the first letters of the first two words ("LT"), or one word's first letter. */
export function initialsFor(name: string): string {
    const words = name.trim().split(/\s+/).filter(Boolean);
    const first = (word = '') => Array.from(word)[0] ?? '';
    return (words.length > 1 ? first(words[0]) + first(words[1]) : first(words[0])).toUpperCase() || '?';
}

const TILE = {
    20: 'h-5 w-5 rounded-md text-[9px]',
    32: 'h-8 w-8 rounded-lg text-[13px]',
    40: 'h-10 w-10 rounded-xl text-[16px]',
} as const;

/** A workspace's mark: its logo, else its initials on a quiet tile. */
export function WorkspaceTile({ workspace, size = 40, className }: { workspace: Pick<Workspace, 'name' | 'logoUrl'>; size?: keyof typeof TILE; className?: string }) {
    if (workspace.logoUrl) {
        return (
            <span aria-hidden className={cn('relative block shrink-0 overflow-hidden bg-card', TILE[size], className)}>
                <img src={workspace.logoUrl} alt="" draggable={false} className="h-full w-full object-cover" />
                <span className="pointer-events-none absolute inset-0 rounded-[inherit] ring-1 ring-inset ring-foreground/[0.1]" />
            </span>
        );
    }
    return (
        <span
            aria-hidden
            className={cn(
                'grid shrink-0 select-none place-items-center bg-card font-semibold leading-none tracking-[-0.02em] text-foreground ring-1 ring-inset ring-border dark:bg-foreground/[0.08] dark:ring-foreground/[0.08]',
                TILE[size],
                className
            )}
        >
            {initialsFor(workspace.name)}
        </span>
    );
}

/** The workspaces in the page's user filter, for the rail and the phone's picker; null reads none. */
export function useWorkspaces(user: string | null) {
    const { client } = useConsole();
    return useV1(user === null ? null : `workspaces?${user}`, () => Workspace.list({ client, userFilter: user!, limit: 50 }));
}

function RailButton({ label, line, current, onClick, children }: { label: string; line: string; current: boolean; onClick: () => void; children: ReactNode }) {
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <button
                    type="button"
                    onClick={onClick}
                    aria-label={label}
                    aria-current={current ? 'page' : undefined}
                    className={cn(
                        'shrink-0 rounded-xl ring-offset-2 ring-offset-background transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        current ? 'ring-2 ring-foreground' : 'hover:ring-2 hover:ring-foreground/20'
                    )}
                >
                    {children}
                </button>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={10} className="rounded-lg px-2.5 py-1.5">
                <p className="m-0 text-[13px] font-medium text-foreground">{label}</p>
                <p className="m-0 text-[12px] text-muted-foreground">{line}</p>
            </TooltipContent>
        </Tooltip>
    );
}

/** Down the left of the list on a laptop: every channel, then each workspace's. */
export function WorkspaceRail({ workspaces, current, onSelect }: { workspaces: readonly Workspace[]; current: string | null; onSelect: (id: string | null) => void }) {
    return (
        <nav aria-label="Workspaces" className={cn('hidden w-14 shrink-0 flex-col items-center gap-3 border-r pr-4 pt-1 md:flex', HAIRLINE)}>
            <RailButton label="Every channel" line="In a workspace or not" current={current === null} onClick={() => onSelect(null)}>
                <span aria-hidden className="grid h-10 w-10 place-items-center rounded-xl bg-foreground/[0.05] text-muted-foreground">
                    <MessagesSquare className="h-[18px] w-[18px]" strokeWidth={1.75} />
                </span>
            </RailButton>
            {workspaces.map((w) => (
                <RailButton
                    key={w.id}
                    label={w.name}
                    line={`${plural(w.channelCount, 'channel')} · ${w.userId ? `for ${w.userId}` : 'your account'}`}
                    current={current === w.id}
                    onClick={() => onSelect(w.id)}
                >
                    <WorkspaceTile workspace={w} />
                </RailButton>
            ))}
        </nav>
    );
}

/** The rail's choice on a phone, where there's no room for it. */
export function WorkspacePicker({ workspaces, current, onSelect }: { workspaces: readonly Workspace[]; current: string | null; onSelect: (id: string | null) => void }) {
    return (
        <FacetSelect
            label="Workspace"
            value={current}
            options={workspaces.map((w) => ({ value: w.id, label: w.name }))}
            onChange={onSelect}
            anyLabel="Every channel"
            className="md:hidden"
        />
    );
}

/** The workspace the rail picked: whose it is, who's in it, what its channels spent, and what all of them hear. */
export function WorkspaceSummary({ workspace }: { workspace: Workspace }) {
    const members = workspace.members;
    const agents = members.filter((m) => m.type === 'agent');
    const people = members.filter((m) => m.type === 'user');
    return (
        <section aria-label={`Workspace ${workspace.name}`} className="mb-6 flex flex-col gap-3">
            <div className="flex min-w-0 items-start gap-3">
                <WorkspaceTile workspace={workspace} size={32} />
                <div className="min-w-0 flex-1">
                    <p className="m-0 flex flex-wrap items-baseline gap-x-2 text-[16px] font-semibold tracking-tight text-foreground">
                        {workspace.name}
                        {workspace.status === 'archived' && <StatusPill look={{ label: 'Archived', reason: 'channels closed', glyph: 'muted', tone: 'muted' }} />}
                    </p>
                    <p className="m-0 mt-0.5 text-[13px] text-muted-foreground">
                        {workspace.userId ? `For ${userLabel(workspace.userId)}` : 'Your account'} · {plural(workspace.channelCount, 'channel')} · {plural(agents.length, 'agent')}
                        {people.length > 0 && ` · ${plural(people.length, 'person', 'people')}`}
                    </p>
                </div>
                <CapMeter spent={workspace.spentUsd} cap={workspace.budgetUsdPerMonth} noCapLabel className="shrink-0 items-end text-[13px]" />
            </div>
            {members.length > 0 && (
                <p className="m-0 text-[13px] text-muted-foreground">
                    <span className="text-foreground/80">Members:</span>{' '}
                    {members.map((m, i) => (
                        <span key={m.id}>
                            {i > 0 && ', '}
                            {m.type === 'user' ? `${m.name ?? m.userId} (${m.userId})` : <span className="font-mono text-[12px] text-foreground/85">{m.name ?? m.agentId}</span>}
                        </span>
                    ))}
                </p>
            )}
            <WorkspaceSubscriptions workspace={workspace} />
        </section>
    );
}

function WorkspaceSubscriptions({ workspace }: { workspace: Workspace }) {
    const key = `workspaces/${workspace.id}/subscriptions`;
    const subscriptions = useV1(key, () => workspace.subscriptions());
    const rows = subscriptions.data ?? [];
    if (subscriptions.error !== undefined && !subscriptions.data) return <ErrorPanel error={subscriptions.error} onRetry={() => void subscriptions.refresh()} />;
    if (!rows.length) return null;
    return (
        <div>
            <h3 className="m-0 mb-1.5 text-[14px] font-semibold tracking-[-0.01em] text-foreground">Every channel here hears</h3>
            <SubscriptionList rows={rows} workspaceName={workspace.name} onRemoved={(s) => subscriptions.mutate(rows.filter((r) => r.id !== s.id))} />
        </div>
    );
}

// ── subscriptions ──────────────────────────────────────────────────────────

function filtersText(...sets: unknown[]): string {
    const pairs = sets.flatMap((f) => (f && typeof f === 'object' ? Object.entries(f as JsonObject).map(([k, v]) => `${k} = ${String(v)}`) : []));
    return pairs.length ? `where ${pairs.join(', ')}` : '';
}

/** Where a subscription's events come from, in words. */
export function SourceText({ source }: { source: JsonObject }) {
    const mono = (text: unknown) => <span className="font-mono text-[12px] text-foreground/90">{String(text)}</span>;
    if (source.kind === 'event') {
        return (
            <>
                {mono(source.connection)} events: {mono(source.event)}
            </>
        );
    }
    if (source.kind === 'webhook') return <>Webhook {mono(source.name)}</>;
    if (source.kind === 'platform') return <>NoClick events: {mono(source.type)}</>;
    return mono(JSON.stringify(source));
}

function wakeText(wake: Subscription['wake'], names: Map<string, { name: string }>): string {
    if (wake === 'all') return 'Wakes every agent';
    if (Array.isArray(wake) && wake.length) return `Wakes ${wake.map((id) => names.get(id)?.name ?? id).join(', ')}`;
    return 'Posts only; wakes no one';
}

function UnsubscribeDialog({ subscription, workspaceName, onRemoved, onClose }: { subscription: Subscription; workspaceName?: string; onRemoved: () => void; onClose: () => void }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const webhook = subscription.source.kind === 'webhook';
    const run = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await subscription.unsubscribe();
            onRemoved();
            toast.success('Unsubscribed');
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
            title="Unsubscribe?"
            description={`${workspaceName ? `No channel in ${workspaceName} hears these events any more.` : 'The channel stops hearing these events.'}${webhook ? ' Its URL stops answering at once.' : ''} Code that subscribes it adds it back when it next runs.`}
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="danger" onClick={() => void run()} disabled={busy}>
                        {busy ? 'Unsubscribing…' : 'Unsubscribe'}
                    </ConsoleButton>
                </>
            }
        >
            {error !== undefined && <ErrorPanel error={error} />}
        </ConsoleDialog>
    );
}

/** Subscriptions as rows: the source, who it wakes, its URL, and whether it's delivering. */
function SubscriptionList({ rows, workspaceName, onRemoved }: { rows: readonly Subscription[]; workspaceName?: string; onRemoved: (s: Subscription) => void }) {
    const names = useAgentNames();
    const [removing, setRemoving] = useState<Subscription | null>(null);
    return (
        <>
            <ul aria-label={workspaceName ? `${workspaceName} subscriptions` : 'Subscriptions'} className={'m-0 -mx-3 list-none p-0'}>
                {rows.map((s) => {
                    const look = subscriptionStatus(s.status);
                    const filters = filtersText(s.source.kind === 'event' ? s.source.filters : null, s.filters);
                    return (
                        <li key={s.id} className={cn('flex flex-col gap-0.5 px-3 py-2 text-[13px]')}>
                            <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                                <span className="min-w-0 text-foreground">
                                    <SourceText source={s.source} />
                                </span>
                                {look && <StatusPill look={look} />}
                                <span className="ml-auto shrink-0 text-[12px] text-muted-foreground">
                                    {s.lastEventAt ? (
                                        <>
                                            Last event <TimeCell value={s.lastEventAt} />
                                        </>
                                    ) : (
                                        'No events yet'
                                    )}
                                </span>
                            </span>
                            <span className="text-[12px] text-muted-foreground">
                                {wakeText(s.wake, names)}
                                {filters && ` · ${filters}`}
                            </span>
                            {s.url && (
                                <span className="flex min-w-0 items-center gap-1" title={s.url}>
                                    <span className="truncate font-mono text-[12px] text-foreground/80">{s.url}</span>
                                    <CopyButton value={s.url} label="Copy webhook URL" />
                                </span>
                            )}
                            {s.error && <span className="text-[12px] text-red-600 dark:text-red-400">{s.error}</span>}
                            <button type="button" onClick={() => setRemoving(s)} className="self-start text-[12px] text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline">
                                Unsubscribe
                            </button>
                        </li>
                    );
                })}
            </ul>
            {removing && <UnsubscribeDialog subscription={removing} workspaceName={workspaceName} onRemoved={() => onRemoved(removing)} onClose={() => setRemoving(null)} />}
        </>
    );
}

/** What a channel hears: its own subscriptions, then its workspace's that reach it. */
export function ChannelSubscriptions({ channel }: { channel: Channel }) {
    const { client } = useConsole();
    const key = `channels/${channel.id}/subscriptions`;
    const own = useV1(key, () => channel.subscriptions());
    const workspaceId = channel.workspaceId;
    const shared = useV1(workspaceId ? `workspaces/${workspaceId}/subscriptions?channel=${channel.id}` : null, async () => {
        const workspace = await Workspace.get(workspaceId!, { client });
        const rows = await workspace.subscriptions();
        return { name: workspace.name, rows: rows.filter((s) => s.channels === 'all' || (Array.isArray(s.channels) && s.channels.includes(channel.id))) };
    });
    const rows = own.data ?? [];
    return (
        <Section title="Subscriptions">
            {own.error !== undefined && !own.data ? (
                <ErrorPanel error={own.error} onRetry={() => void own.refresh()} />
            ) : !own.data ? (
                <div aria-busy className="h-12 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : rows.length ? (
                <SubscriptionList
                    rows={rows}
                    onRemoved={(s) => own.mutate(rows.filter((r) => r.id !== s.id))}
                />
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">
                    None. An app&apos;s events post here as messages from that app:{' '}
                    <span className="font-mono text-[12px]">channel.subscribe(noclick.OnEvent(stripe, &quot;invoice_payment_failed&quot;), wake=&quot;all&quot;)</span>.
                </p>
            )}
            {shared.data && shared.data.rows.length > 0 && (
                <div className="mt-3">
                    <h4 className="m-0 mb-1.5 text-[12px] font-medium text-muted-foreground">From the {shared.data.name} workspace</h4>
                    <SubscriptionList
                        rows={shared.data.rows}
                        workspaceName={shared.data.name}
                        onRemoved={(s) => shared.mutate({ ...shared.data!, rows: shared.data!.rows.filter((r) => r.id !== s.id) })}
                    />
                </div>
            )}
        </Section>
    );
}
