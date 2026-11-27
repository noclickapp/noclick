// Channels: rooms where a user, your agents and remote (A2A) agents talk.
// The drawer (`?channel=`) tails the messages with the API's own long poll
// (pausable), posts as the account, closes the channel, and lists what it's
// subscribed to, whose events post as the app's messages. The workspace rail
// (`?workspace=`) narrows the list to one workspace. It lists the channel's
// schedules, each posting a message in the room as the account.
import { useEffect, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Channel, Workspace, type ChannelMessage } from 'noclick';
import { NEW_SNIPPETS } from '@/screens/console/lib/snippets';
import type { StatusLook } from '@/screens/console/lib/status';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { NewInCode } from '../../NewInCode';
import { ConsoleButton } from '../../ui/Button';
import { CapMeter } from '../../ui/CapMeter';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { JsonView } from '../../ui/JsonView';
import {
    ChannelSubscriptions,
    WorkspacePicker,
    WorkspaceRail,
    WorkspaceSummary,
    WorkspaceTile,
    useWorkspaces,
} from './ChannelsWorkspaces';
import {
    ConfirmAction,
    errorText,
    Field,
    INPUT,
    PanelToolbar,
    Section,
    sleep,
    type PanelProps,
} from './shared';

/** Long-poll window per request (`wait_s`). */
const TAIL_WAIT_S = 25;

export function channelStatus(
    status: string | null,
    haltReason: string | null
): StatusLook {
    if (status === 'open')
        return { label: 'Open', glyph: 'filled', tone: 'ink' };
    return {
        label: status === 'closed' ? 'Closed' : (status ?? 'Unknown'),
        reason: haltReason,
        glyph: 'muted',
        tone: 'muted',
    };
}

const money = (value: unknown) => (typeof value === 'number' ? value : null);

const specText = (spec: Record<string, unknown>, key: string) => (typeof spec[key] === 'string' ? (spec[key] as string) : null);

/** Its schedules (designed): each posts its message in the room as the account, set from code. */
function Schedules({ channel }: { channel: Channel }) {
    const triggers = useV1(`channels/${channel.id}/triggers`, () => channel.triggers());
    return (
        <Section title="Schedules">
            {triggers.error !== undefined ? (
                <ErrorPanel error={triggers.error} onRetry={() => void triggers.refresh()} />
            ) : !triggers.data ? (
                <div aria-busy className="h-12 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : triggers.data.length ? (
                <ul aria-label="Schedules" className={'m-0 -mx-3 list-none p-0'}>
                    {triggers.data.map((t) => (
                        <li key={t.id} className={cn('flex flex-col gap-0.5 px-3 py-2 text-[13px]')}>
                            <span className="flex items-baseline gap-2">
                                <span className="font-mono text-[12px]">{specText(t.spec, 'cron')}</span>
                                <span className="text-[12px] text-muted-foreground">{specText(t.spec, 'tz') ?? 'UTC'}</span>
                                {t.nextRun && (
                                    <span className="ml-auto text-[12px] text-muted-foreground">
                                        next <TimeCell value={t.nextRun} tier="absolute" />
                                    </span>
                                )}
                            </span>
                            <span className="text-foreground/85">{specText(t.spec, 'message')}</span>
                            {t.error && <span className="text-[12px] text-red-600 dark:text-red-400">{t.error}</span>}
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">
                    None. A schedule posts in the room as the account: <span className="font-mono text-[12px]">channel.add_trigger(noclick.Cron(...))</span>.
                </p>
            )}
        </Section>
    );
}

function Messages({ channel }: { channel: Channel }) {
    const [messages, setMessages] = useState<ChannelMessage[]>([]);
    const [paused, setPaused] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const [attempt, setAttempt] = useState(0);
    const last = useRef<string | undefined>(undefined);
    const [text, setText] = useState('');
    const [posting, setPosting] = useState(false);

    useEffect(() => {
        if (paused) return;
        const stop = new AbortController();
        // The first read answers at once; every later one long-polls, messages or not.
        let primed = false;
        (async () => {
            while (!stop.signal.aborted) {
                const started = Date.now();
                let batch: ChannelMessage[];
                try {
                    batch = await channel.messages({
                        after: last.current,
                        waitS: primed ? TAIL_WAIT_S : undefined,
                    });
                } catch (e) {
                    if (!stop.signal.aborted) setError(e);
                    return;
                }
                if (stop.signal.aborted) return;
                primed = true;
                setError(undefined);
                if (batch.length) {
                    last.current = batch[batch.length - 1].id;
                    setMessages((prev) => [
                        ...prev,
                        ...batch.filter(
                            (m) => !prev.some((p) => p.id === m.id)
                        ),
                    ]);
                }
                // A short poll that came back empty (a proxy, the lab) never spins.
                const spent = Date.now() - started;
                if (!batch.length && spent < 1000) await sleep(1000 - spent);
            }
        })();
        return () => stop.abort();
    }, [channel, paused, attempt]);

    const post = async () => {
        if (!text.trim()) return;
        setPosting(true);
        try {
            const sent = await channel.post(text.trim());
            setMessages((prev) =>
                prev.some((m) => m.id === sent.id) ? prev : [...prev, sent]
            );
            setText('');
        } catch (e) {
            toast.error(errorText(e));
        } finally {
            setPosting(false);
        }
    };

    return (
        <Section
            title={
                <span className="flex items-center justify-between">
                    Messages
                    <ConsoleButton
                        variant="ghost"
                        size="sm"
                        aria-pressed={paused}
                        onClick={() => setPaused((p) => !p)}
                        icon={
                            paused ? (
                                <Play className="h-3.5 w-3.5" />
                            ) : (
                                <Pause className="h-3.5 w-3.5" />
                            )
                        }
                    >
                        {paused ? 'Resume' : 'Pause'}
                    </ConsoleButton>
                </span>
            }
        >
            {error !== undefined && (
                <ErrorPanel
                    error={error}
                    onRetry={() => setAttempt((a) => a + 1)}
                    className="mb-2"
                />
            )}
            <ol
                aria-label="Messages"
                className={cn(
                    'm-0 flex max-h-[420px] list-none flex-col gap-2 overflow-y-auto rounded-lg border p-3',
                    HAIRLINE
                )}
            >
                {messages.length === 0 && (
                    <li className="text-[13px] text-muted-foreground">
                        No messages yet.
                    </li>
                )}
                {messages.map((m) => (
                    <li key={m.id} className="text-[13px]">
                        <span className="flex items-baseline gap-2">
                            <span className="font-medium text-foreground">
                                {m.author.name ?? m.author.type}
                            </span>
                            <span className="text-[12px] text-muted-foreground">
                                {m.author.type}
                            </span>
                            <TimeCell
                                value={m.createdAt}
                                tier="log"
                                className="text-[12px] text-muted-foreground"
                            />
                        </span>
                        <span className="block whitespace-pre-wrap text-foreground/90">
                            {m.text}
                        </span>
                        {/* An app's post carries the event it was subscribed to. */}
                        {m.author.type === 'app' && m.event && (
                            <details className="mt-1">
                                <summary className="cursor-pointer text-[12px] text-muted-foreground hover:text-foreground">
                                    The event
                                </summary>
                                <JsonView value={m.event} className="mt-1" />
                            </details>
                        )}
                    </li>
                ))}
            </ol>
            <form
                className="mt-2 flex gap-2"
                onSubmit={(e) => {
                    e.preventDefault();
                    void post();
                }}
            >
                <input
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    aria-label="Message"
                    placeholder="Post as the account; @mention an agent"
                    className={INPUT}
                    disabled={channel.status !== 'open'}
                />
                <ConsoleButton
                    type="submit"
                    disabled={
                        posting || !text.trim() || channel.status !== 'open'
                    }
                >
                    Post
                </ConsoleButton>
            </form>
        </Section>
    );
}

function ChannelDrawer({
    channelId,
    row,
    onClose,
}: {
    channelId: string | null;
    row?: Channel;
    onClose: () => void;
}) {
    const { client } = useConsole();
    const fetched = useV1(
        channelId && !row ? `channels/${channelId}` : null,
        () => Channel.get(channelId!, { client })
    );
    const [closed, setClosed] = useState<Channel | null>(null);
    const channel =
        (closed && channelId && closed.id === channelId ? closed : null) ??
        row ??
        fetched.data;
    useEffect(() => {
        if (channel)
            recordRecent({
                type: 'channel',
                id: channel.id,
                label: channel.name,
                path: 'resources/channels',
                params: { channel: channel.id },
            });
    }, [channel?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    return (
        <Drawer
            open={channelId !== null}
            onOpenChange={(open) => !open && onClose()}
            kind="channel"
            title={channel?.name}
            id={channelId ?? undefined}
            status={
                channel ? (
                    <StatusPill
                        look={channelStatus(
                            channel.status,
                            (channel.raw.halt_reason as string) ?? null
                        )}
                    />
                ) : undefined
            }
            footer={
                channel?.status === 'open' ? (
                    <ConfirmAction
                        label="Close channel"
                        title={`Close ${channel.name}?`}
                        description="No more posts or agent turns. A closed channel can't be reopened."
                        confirmLabel="Close channel"
                        onConfirm={async () => {
                            setClosed(await channel.close());
                            invalidateV1('channels');
                        }}
                    />
                ) : undefined
            }
        >
            {!channel && fetched.error !== undefined && (
                <ErrorPanel
                    error={fetched.error}
                    onRetry={() => void fetched.refresh()}
                />
            )}
            {channel && (
                <div className="flex flex-col gap-5">
                    <dl className="m-0">
                        <Field label="Mode">
                            <span className="font-mono text-[12px]">
                                {channel.mode}
                            </span>
                        </Field>
                        <Field label="User">
                            {userLabel(channel.userId)}
                        </Field>
                        {channel.workspaceId && (
                            <Field label="Workspace">
                                <WorkspaceName id={channel.workspaceId} />
                            </Field>
                        )}
                        <Field label="Spend">
                            <CapMeter
                                spent={money(channel.raw.spent_usd)}
                                cap={money(channel.raw.budget_usd)}
                                noCapLabel
                                className="w-48 items-start"
                            />
                        </Field>
                        <Field label="Created">
                            <TimeCell
                                value={channel.createdAt}
                                tier="absolute"
                            />
                        </Field>
                    </dl>
                    <Section title="Members">
                        <ul className="m-0 flex list-none flex-col gap-1 p-0 text-[13px]">
                            {channel.members.map((m) => (
                                <li
                                    key={m.id}
                                    className="flex items-baseline gap-2"
                                >
                                    <span className="font-medium">
                                        {m.name ?? m.type}
                                    </span>
                                    <span className="text-[12px] text-muted-foreground">
                                        {m.type}
                                    </span>
                                    {m.a2aUrl && (
                                        <span className="truncate font-mono text-[12px] text-muted-foreground">
                                            {m.a2aUrl}
                                        </span>
                                    )}
                                </li>
                            ))}
                        </ul>
                    </Section>
                    <Schedules channel={channel} />
                    <ChannelSubscriptions channel={channel} />
                    <Messages channel={channel} />
                </div>
            )}
        </Drawer>
    );
}

/** A channel's workspace by name, with its tile. */
function WorkspaceName({ id }: { id: string }) {
    const { client } = useConsole();
    const workspace = useV1(`workspaces/${id}`, () => Workspace.get(id, { client }));
    if (!workspace.data) return <span className="font-mono text-[12px]">{id}</span>;
    return (
        <span className="inline-flex items-center gap-2">
            <WorkspaceTile workspace={workspace.data} size={20} />
            {workspace.data.name}
        </span>
    );
}

export function ChannelsPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const [channelId, setChannel] = useSearchParam('channel');
    const [workspaceId, setWorkspace] = useSearchParam('workspace');
    const workspaces = useWorkspaces(user);
    const workspaceRows = workspaces.data ?? [];
    const workspace = workspaceId ? (workspaceRows.find((w) => w.id === workspaceId) ?? null) : null;
    // A channel made in the rail's workspace takes its scope; with its id, the user says whose workspace it is.
    const place = workspace ? { workspace: workspace.id, user: workspace.userId } : { user: defaultWriteUser(user) };
    const scoped = workspaceId;
    const paged = usePaged(
        `channels?${user}${scoped ? `&workspace=${scoped}` : ''}`,
        (cursor) =>
            Channel.listPage({
                client,
                userFilter: user,
                cursor,
                limit: 50,
                workspace: scoped ?? undefined,
            }),
        (c) => c.id
    );
    const tileOf = (id: string | null) =>
        id ? workspaceRows.find((w) => w.id === id) : undefined;
    const columns: Column<Channel>[] = [
        {
            id: 'name',
            header: 'Name',
            cell: (c) => {
                // Across every workspace, each channel wears its workspace's tile.
                const home = !scoped ? tileOf(c.workspaceId) : undefined;
                const rail = !scoped && workspaceRows.length > 0;
                return (
                    <span className="flex min-w-0 items-center gap-2">
                        {home ? (
                            <span title={home.name} className="shrink-0">
                                <WorkspaceTile workspace={home} size={20} />
                            </span>
                        ) : (
                            rail && <span aria-hidden className="h-5 w-5 shrink-0" />
                        )}
                        <span className="font-medium">{c.name}</span>
                    </span>
                );
            },
        },
        {
            id: 'mode',
            header: 'Mode',
            priority: 2,
            width: '6rem',
            cell: (c) => (
                <span className="font-mono text-[12px] text-muted-foreground">
                    {c.mode}
                </span>
            ),
        },
        {
            id: 'members',
            header: 'Members',
            priority: 3,
            cell: (c) => (
                <span className="text-muted-foreground">
                    {c.members.map((m) => m.name ?? m.type).join(', ') || '—'}
                </span>
            ),
        },
        {
            id: 'user',
            header: 'User',
            priority: 3,
            width: '7rem',
            cell: (c) => (
                <span
                    className={
                        c.userId
                            ? 'font-mono text-[12px]'
                            : 'text-muted-foreground'
                    }
                >
                    {userLabel(c.userId)}
                </span>
            ),
        },
        {
            id: 'spend',
            header: 'Spent',
            align: 'right',
            width: '10rem',
            cell: (c) => (
                <CapMeter
                    spent={money(c.raw.spent_usd)}
                    cap={money(c.raw.budget_usd)}
                />
            ),
        },
        {
            id: 'status',
            header: 'Status',
            width: '9rem',
            cell: (c) => (
                <StatusPill
                    look={channelStatus(
                        c.status,
                        (c.raw.halt_reason as string) ?? null
                    )}
                />
            ),
        },
        {
            id: 'created',
            header: 'Created',
            priority: 3,
            width: '6.5rem',
            cell: (c) => <TimeCell value={c.createdAt} />,
        },
    ];
    return (
        <>
            <PanelToolbar
                user={user}
                setUser={setUser}
                action={
                    <>
                        {workspaceRows.length > 0 && (
                            <WorkspacePicker
                                workspaces={workspaceRows}
                                current={workspaceId}
                                onSelect={(id) => setWorkspace(id)}
                            />
                        )}
                        <NewInCode kind="channel" place={place} title={workspace ? `New channel in ${workspace.name}` : undefined} />
                    </>
                }
            />
            <div className={cn(workspaceRows.length > 0 && 'md:flex md:gap-5')}>
                {workspaceRows.length > 0 && (
                    <WorkspaceRail
                        workspaces={workspaceRows}
                        current={workspaceId}
                        onSelect={(id) => setWorkspace(id)}
                    />
                )}
                <div className="min-w-0 flex-1">
                    {workspace && <WorkspaceSummary workspace={workspace} />}
                    <DataTable
                rowMenu="channel"
                        label="Channels"
                        columns={columns}
                        rows={paged.rows}
                        getRowId={(c) => c.id}
                        loading={paged.loading}
                        error={paged.error}
                        onRetry={() => void paged.refresh()}
                        onRowClick={(c) => setChannel(c.id, { push: true })}
                        selectedId={channelId}
                        nextCursor={paged.nextCursor}
                        onLoadMore={() => void paged.loadMore()}
                        loadingMore={paged.loadingMore}
                        empty={
                            workspace ? (
                                <p className="m-0 py-6 text-center text-[13px] text-muted-foreground">
                                    No channels in {workspace.name} yet.
                                </p>
                            ) : (
                                <EmptyCode
                                    title="No channels yet."
                                    hint="A channel is where a user, your agents and remote agents talk."
                                    snippet={NEW_SNIPPETS.channel(place)}
                                />
                            )
                        }
                    />
                </div>
            </div>
            <ChannelDrawer
                channelId={channelId}
                row={paged.rows.find((c) => c.id === channelId)}
                onClose={() => setChannel(null)}
            />
        </>
    );
}
