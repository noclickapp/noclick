// Channels: rooms where your agents work together (and with you), in
// workspaces as in Slack: your own channels, and each workspace you made for a
// company, a client or a community. Each channel says who is in it and
// whether agents answer every message or only when @-mentioned; you post,
// share files and voice clips, react, and run slash commands in the channel
// itself. Everything is the account's platform channels, read through the
// registered transport and followed live; without one, the page says so.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties, type DragEvent } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router';
import { Archive, Hash, Link2, MessagesSquare, MoreHorizontal, PenLine, Plus, ScrollText, Upload, X } from 'lucide-react';
import { toast } from 'sonner';
import type { AccountMenuUser } from '~/components/nav/AccountMenu';
import { HAIRLINE, NodeMark } from '~/components/dashboard/primitives';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '~/components/ui/dropdown-menu';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { TooltipProvider } from '~/components/ui/tooltip';
import { useChannels, type Channels } from '~/hooks/useChannels';
import { useChannelSchedules } from '~/hooks/useChannelSchedules';
import type { VoiceClip } from '~/hooks/useVoiceClip';
import { askNoClick } from '~/lib/askNoClick';
import { navigateToTab } from '~/lib/navigation';
import { rememberPaletteEntries } from '~/components/command/sources';
import { cn } from '~/lib/utils';
import { PhoneBarActions, PhoneBarBack, useInPhoneShell } from './AppShell';
import { AddWorkspaceDialog } from './channels/AddWorkspaceDialog';
import { Facepile, MemberAvatar } from './channels/avatars';
import { ChannelComposer, type DraftAttachment } from './channels/ChannelComposer';
import { ChannelList } from './channels/ChannelList';
import { CHANNEL_COMMANDS, mentionedMember, parseCommand, summarizeChannel } from './channels/commands';
import { MessageList } from './channels/MessageList';
import { agentGroups, agentKey, channelIn, channelsIn, hueFor, modeLine, YOU } from './channels/model';
import { NewChannelDialog } from './channels/NewChannelDialog';
import { PlatformChannelsBoundary, usePlatformChannels, type ChannelsTransport } from './channels/platform';
import { ScheduleChip } from './channels/schedules';
import type { AgentChoice, Channel, ChannelAttachment, ChannelMember, ChannelWorkspace } from './channels/types';
import { WorkspaceRail } from './channels/workspaces';
import { createPanelWidth } from './panelWidth';
import { ResizeEdge } from './ResizeEdge';
import { PAGE_TITLE } from '~/components/shell/titles';

// The channel list, resizable from its right edge like the app sidebar.
const channelListPanel = createPanelWidth({ key: 'nc-channel-list-width', initial: 260, min: 200, max: 400 });

// The workspace you were last in, remembered on this device ('home' for your own channels).
const WORKSPACE_KEY = 'nc-channels-workspace';
let chosenWorkspace: string | null | undefined;
const choiceListeners = new Set<() => void>();

function choiceSnapshot(): string | null {
    if (chosenWorkspace === undefined) {
        try {
            chosenWorkspace = window.localStorage.getItem(WORKSPACE_KEY);
        } catch {
            chosenWorkspace = null;
        }
    }
    return chosenWorkspace;
}

function chooseWorkspace(workspace: ChannelWorkspace) {
    const id = workspace.id ?? 'home';
    if (chosenWorkspace === id) return;
    chosenWorkspace = id;
    try {
        window.localStorage.setItem(WORKSPACE_KEY, id);
    } catch {
        // Not remembered this time; the switch still happens.
    }
    choiceListeners.forEach((listener) => listener());
}

function subscribeChoice(listener: () => void) {
    choiceListeners.add(listener);
    return () => {
        choiceListeners.delete(listener);
    };
}

/** Your own channels, outside any workspace, named for you. */
function homeOf(user: AccountMenuUser): ChannelWorkspace {
    return { id: null, name: user.display_name?.trim() || user.email.split('@')[0] || 'Your channels' };
}

interface Draft {
    text: string;
    attachments: DraftAttachment[];
}

const EMPTY_DRAFT: Draft = { text: '', attachments: [] };

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes('Files');

const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.');

function kindOf(file: File, clip?: VoiceClip): ChannelAttachment['kind'] {
    if (clip || file.type.startsWith('audio/')) return 'audio';
    if (file.type.startsWith('image/')) return 'image';
    if (file.type.startsWith('video/')) return 'video';
    return 'file';
}

const MEMBER_ROW = 'flex items-center gap-3 rounded-xl px-2.5 py-2';

/** What a member is, under its name: an agent its job, one from your Automations which it is. */
function memberRole(m: ChannelMember): string {
    if (m.kind === 'you') return 'You';
    if (m.kind === 'outside') return 'Outside agent';
    if (m.kind !== 'agent') return 'Person';
    if (m.busy) return 'Working…';
    return m.role ?? (m.workflowName ? `Agent in ${m.workflowName}` : 'Agent');
}

/** The header's members: the agents' faces and a count, opening who they are and how to change that. */
function Members({
    channel,
    members,
    agents,
    agentsHref,
    user,
    onAdd,
    onRemove,
}: {
    channel: Channel;
    members: ChannelMember[];
    agents: AgentChoice[];
    agentsHref: string;
    user: AccountMenuUser;
    onAdd: (agent: AgentChoice) => void;
    onRemove: (member: ChannelMember) => void;
}) {
    const inRoom = members.filter((m) => m.kind === 'agent');
    const addable = agentGroups(agents.filter((a) => !members.some((m) => agentKey(m) === a.id)));
    const open = channel.status !== 'closed';
    return (
        <Popover>
            <PopoverTrigger
                aria-label={`${members.length} members`}
                data-testid="channel-members"
                className="flex h-8 shrink-0 items-center gap-2 rounded-full pl-1 pr-2.5 text-[13px] tabular-nums text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground"
            >
                <Facepile members={(inRoom.length ? inRoom : members).slice(0, 3)} user={user} size={24} />
                {members.length}
            </PopoverTrigger>
            <PopoverContent align="end" sideOffset={8} collisionPadding={12} className="w-[320px] max-w-[calc(100vw-24px)] rounded-2xl p-1.5">
                <div className="px-2.5 pb-2 pt-2">
                    <p className="text-[13.5px] font-semibold text-foreground">
                        {members.length} {members.length === 1 ? 'member' : 'members'}
                    </p>
                    <p className="mt-0.5 text-[12.5px] leading-snug text-muted-foreground">{modeLine(channel.mode, inRoom)}.</p>
                </div>
                <ul className="max-h-[40vh] overflow-y-auto scrollbar-subtle">
                    {members.map((m) => (
                        <li key={m.id} className={cn(MEMBER_ROW, 'group')}>
                            <MemberAvatar member={m} user={user} size={28} />
                            <div className="min-w-0 flex-1">
                                <p className="truncate text-[14px] text-foreground">{m.name}</p>
                                <p className="truncate text-[12.5px] text-muted-foreground">{memberRole(m)}</p>
                            </div>
                            {m.markType && <NodeMark type={m.markType} size="sm" />}
                            {m.kind !== 'you' && open && (
                                <button
                                    type="button"
                                    onClick={() => onRemove(m)}
                                    aria-label={`Remove ${m.name}`}
                                    className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground opacity-0 transition-opacity hover:bg-foreground/[0.06] hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
                                >
                                    <X className="h-3.5 w-3.5" strokeWidth={2} />
                                </button>
                            )}
                        </li>
                    ))}
                </ul>
                {open && (
                    <div className="mt-1 border-t border-border pt-1.5 dark:border-foreground/[0.08]">
                        <p className="px-2.5 pb-1 pt-1 text-[12px] font-medium text-muted-foreground">Add an agent</p>
                        {addable.length ? (
                            <div className="max-h-[30vh] overflow-y-auto scrollbar-subtle">
                                {addable.map((group) => (
                                    <section key={group.label} aria-label={group.label}>
                                        <p className="px-2.5 pb-0.5 pt-1.5 text-[11.5px] text-muted-foreground/80">{group.label}</p>
                                        <ul>
                                            {group.agents.map((a) => (
                                                <li key={a.id}>
                                                    <button type="button" onClick={() => onAdd(a)} className={cn(MEMBER_ROW, 'w-full text-left transition-colors hover:bg-foreground/[0.04]')}>
                                                        <MemberAvatar member={{ id: a.id, kind: 'agent', name: a.name, hue: hueFor(a.id) }} user={user} size={28} />
                                                        <span className="min-w-0 flex-1">
                                                            <span className="block truncate text-[14px] text-foreground">{a.name}</span>
                                                            {a.source === 'automation' && <span className="block truncate text-[12.5px] text-muted-foreground">{a.workflowName}</span>}
                                                        </span>
                                                        <Plus className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                                                    </button>
                                                </li>
                                            ))}
                                        </ul>
                                    </section>
                                ))}
                            </div>
                        ) : (
                            <p className="px-2.5 pb-2 text-[12.5px] leading-snug text-muted-foreground">
                                {agents.length ? 'Every one of your agents is here.' : 'You have no agents yet.'}{' '}
                                <a href={agentsHref} className="font-medium text-foreground/80 underline decoration-foreground/25 underline-offset-[3px] hover:text-foreground">
                                    Make one
                                </a>
                            </p>
                        )}
                    </div>
                )}
            </PopoverContent>
        </Popover>
    );
}

function Centered({ title, body, action }: { title: string; body: string; action?: { label: string; onClick: () => void } }) {
    return (
        <div className="grid h-full w-full place-items-center px-6" data-testid="channels-unavailable">
            <div className="max-w-sm text-center">
                <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
                    <Hash className="h-6 w-6 text-foreground/70" strokeWidth={1.75} />
                </span>
                <h1 className={cn('mt-4', PAGE_TITLE, 'text-[28px]')}>{title}</h1>
                <p className="mt-1.5 text-[14.5px] leading-relaxed text-muted-foreground">{body}</p>
                {action && (
                    <button
                        type="button"
                        onClick={action.onClick}
                        className="mt-5 inline-flex h-9 items-center rounded-full bg-primary px-4 text-[13.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                    >
                        {action.label}
                    </button>
                )}
            </div>
        </div>
    );
}

function Loading() {
    return (
        <div className="flex h-full" aria-busy data-testid="channels-loading">
            <div className={cn('hidden w-[68px] shrink-0 border-r md:block', HAIRLINE)} />
            <div className={cn('w-full space-y-2 p-4 md:w-[260px] md:border-r', HAIRLINE)}>
                {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="h-7 animate-pulse rounded-lg bg-foreground/[0.04]" />
                ))}
            </div>
        </div>
    );
}

export function ChannelsPage({ user }: { user: AccountMenuUser }) {
    return (
        <PlatformChannelsBoundary fallback={<Loading />}>
            <ChannelsRoot user={user} />
        </PlatformChannelsBoundary>
    );
}

function ChannelsRoot({ user }: { user: AccountMenuUser }) {
    const platform = usePlatformChannels();
    if (!platform) return <Centered title="Channels aren't available here" body="Channels run on NoClick's hosted platform, which this instance doesn't include." />;
    return <ChannelsView user={user} transport={platform.transport} agentsHref={platform.agentsHref} />;
}

/** The page over a transport (the registered platform's, or a test's). */
export function ChannelsView({ user, transport, agentsHref }: { user: AccountMenuUser; transport: ChannelsTransport; agentsHref: string }) {
    const [params, setParams] = useSearchParams();
    const requested = params.get('channel');
    const inPhone = useInPhoneShell();
    const chosenId = useSyncExternalStore(subscribeChoice, choiceSnapshot, () => null);
    const home = useMemo(() => homeOf(user), [user]);
    const [lastChannel, setLastChannel] = useState<Record<string, string>>({});

    // A first pass picks the channel to open from the URL or where you last were; the data then confirms it.
    const [openId, setOpenId] = useState<string | null>(requested);
    const channels = useChannels(transport, openId);
    const workspaces = useMemo(() => [home, ...channels.workspaces], [home, channels.workspaces]);
    // The palette can open any open channel by name later, from anywhere.
    useEffect(() => {
        rememberPaletteEntries(
            'Channels',
            channels.channels
                .filter((c) => c.status !== 'closed')
                .map((c) => ({
                    id: `channel:${c.id}`,
                    label: c.name,
                    context: workspaces.find((w) => w.id === c.workspaceId)?.name,
                    icon: Hash,
                    about: c.topic,
                    run: () => navigateToTab('channels', { channel: c.id }),
                }))
        );
    }, [channels.channels, workspaces]);
    const located = channels.channels.find((c) => c.id === requested) ?? null;
    const workspace =
        (located && workspaces.find((w) => w.id === located.workspaceId)) ?? workspaces.find((w) => (w.id ?? 'home') === chosenId) ?? home;
    const channel = located ?? channelIn(workspace, channels.channels, lastChannel[workspace.id ?? 'home']);
    // The channel on screen: a laptop shows one beside the list, a phone only the one the URL opens.
    const shownId = inPhone && !located ? null : (channel?.id ?? null);
    useEffect(() => setOpenId(shownId), [shownId]);

    if (channels.loading) return <Loading />;
    if (channels.error && !channels.channels.length)
        return <Centered title="Channels couldn't load" body={channels.error} action={{ label: 'Try again', onClick: channels.refresh }} />;
    return (
        <ChannelsLoaded
            user={user}
            transport={transport}
            agentsHref={agentsHref}
            channels={channels}
            workspaces={workspaces}
            workspace={workspace}
            channel={channel}
            requested={requested}
            setParams={setParams}
            lastChannel={lastChannel}
            setLastChannel={setLastChannel}
        />
    );
}

function ChannelsLoaded({
    user,
    transport,
    agentsHref,
    channels,
    workspaces,
    workspace,
    channel,
    requested,
    setParams,
    lastChannel,
    setLastChannel,
}: {
    user: AccountMenuUser;
    transport: ChannelsTransport;
    agentsHref: string;
    channels: Channels;
    workspaces: ChannelWorkspace[];
    workspace: ChannelWorkspace;
    channel: Channel | null;
    requested: string | null;
    setParams: ReturnType<typeof useSearchParams>[1];
    lastChannel: Record<string, string>;
    setLastChannel: (update: (prev: Record<string, string>) => Record<string, string>) => void;
}) {
    const location = useLocation();
    const navigate = useNavigate();
    const inPhone = useInPhoneShell();
    const listWidth = channelListPanel.useWidth();
    const [drafts, setDrafts] = useState<Record<string, Draft>>({});
    const [adding, setAdding] = useState(false);
    const [starting, setStarting] = useState(false);
    const [dropping, setDropping] = useState(false);
    const dragDepth = useRef(0);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    /** Set when a header action hands off to the composer, so the menu doesn't take focus back. */
    const composeAfterMenu = useRef(false);
    const scrollRef = useRef<HTMLDivElement>(null);

    // Each agent wears its harness's mark and says its job, from your agents.
    const mentionable = useMemo(() => {
        const yours = new Map(channels.agents.map((a) => [a.id, a]));
        return (channel?.members ?? []).map((m) => {
            const agent = yours.get(agentKey(m) ?? '');
            return agent ? { ...m, ...(agent.markType ? { markType: agent.markType } : {}), ...(agent.role ? { role: agent.role } : {}) } : m;
        });
    }, [channel, channels.agents]);
    const members = useMemo(() => [YOU, ...mentionable], [mentionable]);
    const history = channel ? channels.history(channel.id) : undefined;
    const messages = useMemo(() => history?.messages ?? [], [history]);
    const byName = useMemo(() => new Map(channelsIn(workspace, channels.channels).map((c) => [c.name, c.id])), [workspace, channels.channels]);
    const draft = (channel && drafts[channel.id]) || EMPTY_DRAFT;
    const busy = channel?.members.filter((m) => m.busy) ?? [];
    const schedules = useChannelSchedules(transport, channel?.id ?? null);
    // Phones show the list or one channel; laptops show both side by side.
    const channelOpen = !!channel && channel.id === requested;

    // Each workspace reopens where you left it, and a linked channel's workspace becomes the one you're in.
    useEffect(() => {
        if (!channel) return;
        const key = workspace.id ?? 'home';
        setLastChannel((prev) => (prev[key] === channel.id ? prev : { ...prev, [key]: channel.id }));
        if (requested === channel.id) chooseWorkspace(workspace);
    }, [workspace, channel, requested, setLastChannel]);

    // A channel opens at its newest message and stays there as messages land and late content
    // (fonts, images) settles, until you scroll up to read. Reading further back keeps your place.
    const pinned = useRef(true);
    const keepFromBottom = useRef<number | null>(null);
    useLayoutEffect(() => {
        const el = scrollRef.current;
        if (!el) return;
        if (keepFromBottom.current !== null) {
            el.scrollTop = el.scrollHeight - keepFromBottom.current;
            keepFromBottom.current = null;
        } else if (pinned.current) el.scrollTop = el.scrollHeight;
    }, [messages.length]);
    useLayoutEffect(() => {
        const el = scrollRef.current;
        pinned.current = true;
        if (el) el.scrollTop = el.scrollHeight;
    }, [channel?.id]);
    useEffect(() => {
        const el = scrollRef.current;
        const content = el?.firstElementChild;
        if (!el || !content || typeof ResizeObserver === 'undefined') return;
        const follow = new ResizeObserver(() => {
            if (pinned.current) el.scrollTop = el.scrollHeight;
        });
        follow.observe(content);
        return () => follow.disconnect();
    }, [channel?.id]);

    // Files you attached live until the page goes: sent ones show the server's copy once the message lands.
    const blobUrls = useRef<Set<string>>(new Set());
    useEffect(() => {
        const urls = blobUrls.current;
        return () => urls.forEach((url) => URL.revokeObjectURL(url));
    }, []);

    const select = (id: string) =>
        setParams((prev) => {
            const next = new URLSearchParams(prev);
            next.set('channel', id);
            return next;
        });

    const switchWorkspace = (target: ChannelWorkspace) => {
        chooseWorkspace(target);
        setParams((prev) => {
            const next = new URLSearchParams(prev);
            const there = channelIn(target, channels.channels, lastChannel[target.id ?? 'home']);
            // A phone lands on the workspace's channel list; a laptop on the channel you had open there.
            if (inPhone || !there) next.delete('channel');
            else next.set('channel', there.id);
            return next;
        });
    };

    /** Drop the open channel from the URL, in place. */
    const leave = () =>
        setParams(
            (prev) => {
                const next = new URLSearchParams(prev);
                next.delete('channel');
                return next;
            },
            { replace: true }
        );
    // Back to the list: undo the open when we navigated here, else drop the channel in place.
    const back = () => {
        if (location.key !== 'default') navigate(-1);
        else leave();
    };

    const updateDraft = (channelId: string, update: (d: Draft) => Draft) => setDrafts((prev) => ({ ...prev, [channelId]: update(prev[channelId] ?? EMPTY_DRAFT) }));

    const dialogs = (
        <>
            <AddWorkspaceDialog
                open={adding}
                onOpenChange={setAdding}
                onCreate={async (name, logo) => {
                    const made = await channels.createWorkspace(name, logo);
                    switchWorkspace(made);
                    setStarting(true);
                }}
            />
            <NewChannelDialog
                open={starting}
                onOpenChange={setStarting}
                where={workspace.name}
                agents={channels.agents}
                agentsHref={agentsHref}
                user={user}
                onCreate={async (input) => {
                    const made = await channels.createChannel({ ...input, workspaceId: workspace.id });
                    select(made.id);
                }}
            />
        </>
    );

    if (!channel) {
        return (
            <TooltipProvider delayDuration={250}>
                <div className="flex h-full min-h-0" data-testid="channels-page">
                    <WorkspaceRail workspaces={workspaces} channels={channels.channels} active={workspace} onSelect={switchWorkspace} onAdd={() => setAdding(true)} />
                    <div className="relative flex w-full shrink-0 md:w-auto" style={{ '--channel-list-width': `${listWidth}px` } as CSSProperties}>
                        <ChannelList
                            workspace={workspace}
                            workspaces={workspaces}
                            channels={channels.channels}
                            activeId={null}
                            user={user}
                            onSelect={select}
                            onSwitchWorkspace={switchWorkspace}
                            onAddWorkspace={() => setAdding(true)}
                            onNewChannel={() => setStarting(true)}
                            className="flex w-full"
                        />
                    </div>
                    <section className="hidden min-w-0 flex-1 md:flex">
                        <Centered title={`Nothing in ${workspace.name} yet`} body="Start a channel and add your agents to it." action={{ label: 'Start a channel', onClick: () => setStarting(true) }} />
                    </section>
                </div>
                {dialogs}
            </TooltipProvider>
        );
    }
    const open = channel;

    /** Attach a file: it shows at once and uploads to the channel; Send waits for it. */
    const attach = (channelId: string, file: File, clip?: VoiceClip) => {
        const url = URL.createObjectURL(file);
        blobUrls.current.add(url);
        const kind = kindOf(file, clip);
        const item: DraftAttachment = {
            localId: crypto.randomUUID(),
            name: file.name || 'Pasted image.png',
            mimeType: file.type || 'application/octet-stream',
            sizeBytes: file.size,
            previewUrl: kind === 'image' ? url : undefined,
            status: 'uploading',
            kind,
            url,
            voice: !!clip,
            durationMs: clip?.durationMs,
            peaks: clip?.peaks,
        };
        updateDraft(channelId, (d) => ({ ...d, attachments: [...d.attachments, item] }));
        const settle = (patch: Partial<DraftAttachment>) =>
            updateDraft(channelId, (d) => ({ ...d, attachments: d.attachments.map((a) => (a.localId === item.localId ? { ...a, ...patch } : a)) }));
        const named = file.name ? file : new File([file], item.name, { type: item.mimeType });
        transport.upload(channelId, named, clip ? { durationMs: clip.durationMs, peaks: clip.peaks } : undefined).then(
            (attachment) => settle({ status: 'ready', attachment }),
            (e) => settle({ status: 'error', error: errorText(e) })
        );
    };
    const addFiles = (files: File[]) => files.forEach((file) => attach(open.id, file));
    const addClip = (clip: VoiceClip) => attach(open.id, clip.file, clip);
    const removeAttachment = (localId: string) =>
        updateDraft(open.id, (d) => {
            const gone = d.attachments.find((a) => a.localId === localId);
            if (gone) {
                URL.revokeObjectURL(gone.url);
                blobUrls.current.delete(gone.url);
            }
            return { ...d, attachments: d.attachments.filter((a) => a.localId !== localId) };
        });

    /** NoClick answering you alone, in the channel. */
    const note = (text: string) => channels.note(channel.id, text);
    const say = async (text: string) => {
        try {
            await channels.post(channel.id, text, []);
        } catch (e) {
            note(errorText(e));
        }
    };
    const act = async (work: () => Promise<void>, done?: string) => {
        try {
            await work();
            if (done) note(done);
        } catch (e) {
            note(errorText(e));
        }
    };
    const agentsInRoom = channel.members.filter((m) => m.kind === 'agent');
    const addAgent = (agent: AgentChoice) => act(() => channels.addAgent(channel.id, agent), `@${agent.name} joined #${channel.name}.`);
    const removeMember = (member: ChannelMember) => act(() => channels.removeMember(channel.id, member.id), `@${member.name} left #${channel.name}.`);
    const closeChannel = async () => {
        try {
            await channels.close(channel.id);
            toast.success(`Closed #${channel.name}`);
            leave();
        } catch (e) {
            note(errorText(e));
        }
    };
    const setMode = (mode: Channel['mode']) => act(() => channels.updateChannel(channel.id, { mode }), `${modeLine(mode, agentsInRoom)}.`);

    /** A slash command: a change to the channel, an ask handed to NoClick, or NoClick's answer to you alone. */
    const run = async ({ name, command, args }: NonNullable<ReturnType<typeof parseCommand>>) => {
        if (!command) {
            note(`\`/${name}\` isn't a command here. Try ${CHANNEL_COMMANDS.map((c) => `\`/${c.name}\``).join(', ')}.`);
            return;
        }
        switch (command.name) {
            case 'summarize':
                note(summarizeChannel(channel.name, messages, members));
                return;
            case 'handoff': {
                const found = mentionedMember(args, agentsInRoom);
                if (!found) {
                    note(agentsInRoom.length ? `Say which agent takes it, like \`/handoff @${agentsInRoom[0].name} draft the post\`.` : `No agents in #${channel.name} to hand off to.`);
                    return;
                }
                await say(`@${found.member.name} ${found.rest || 'over to you.'}`);
                return;
            }
            case 'invite': {
                const found = mentionedMember(
                    args,
                    channels.agents.filter((a) => !channel.members.some((m) => agentKey(m) === a.id))
                );
                if (!found) {
                    note(args ? `None of your agents not already here is called ${args}.` : 'Say which agent to add, like `/invite @Scout`.');
                    return;
                }
                await addAgent(found.member);
                return;
            }
            case 'remove': {
                const found = mentionedMember(args, channel.members);
                if (!found) {
                    note(args ? `No one called ${args} is in #${channel.name}.` : 'Say who to take out, like `/remove @Scout`.');
                    return;
                }
                await removeMember(found.member);
                return;
            }
            case 'topic':
                if (!args) {
                    note('Put the new topic after it, like `/topic Friday launch`.');
                    return;
                }
                await act(() => channels.updateChannel(channel.id, { topic: args }));
                return;
            case 'mode': {
                const mode = /^all|every/i.test(args) ? 'all' : /^mention/i.test(args) ? 'mentions' : null;
                if (!mode) {
                    note('Say `/mode all` (agents read every message) or `/mode mentions` (only when @-mentioned).');
                    return;
                }
                await setMode(mode);
                return;
            }
            case 'close':
                await closeChannel();
                return;
            case 'remind':
                if (!args) {
                    note('Say what and when, like `/remind me to call Maya in 2h`.');
                    return;
                }
                askNoClick(`Remind ${/^me\b/i.test(args) ? args : `me ${args}`} (from #${channel.name} in ${workspace.name})`);
                return;
            case 'automate':
                askNoClick(`Turn this into an automation${args ? `: ${args}` : ''} (from #${channel.name} in ${workspace.name})`);
                return;
        }
    };

    const post = async () => {
        const text = draft.text.trim();
        if (!text && !draft.attachments.length) return;
        const command = draft.attachments.length ? null : parseCommand(text);
        const sent = draft;
        updateDraft(channel.id, () => EMPTY_DRAFT);
        if (command) {
            await run(command);
            return;
        }
        const files = sent.attachments.map((a) => ({ ...(a.attachment as ChannelAttachment), url: a.url }));
        try {
            await channels.post(channel.id, text, files);
        } catch (e) {
            toast.error(errorText(e));
            updateDraft(channel.id, (d) => (d.text || d.attachments.length ? d : sent));
        }
    };

    const react = (messageId: string, emoji: string) => channels.toggleReaction(channel.id, messageId, emoji).catch((e) => toast.error(errorText(e)));
    const loadOlder = () => {
        const el = scrollRef.current;
        if (el) keepFromBottom.current = el.scrollHeight - el.scrollTop;
        channels.loadOlder(channel.id).catch((e) => toast.error(errorText(e)));
    };

    // The header's actions: the same things the commands do, one click away.
    const editTopic = () => {
        updateDraft(channel.id, (d) => ({ ...d, text: `/topic ${channel.topic}` }));
        composeAfterMenu.current = true;
    };
    const copyLink = () => {
        const url = new URL(window.location.href);
        url.searchParams.set('channel', channel.id);
        navigator.clipboard.writeText(url.toString()).then(
            () => toast.success('Link copied'),
            () => toast.error('Couldn’t copy the link')
        );
    };
    const closed = channel.status === 'closed';
    const membersButton = (
        <Members channel={channel} members={members} agents={channels.agents} agentsHref={agentsHref} user={user} onAdd={(a) => void addAgent(a)} onRemove={(m) => void removeMember(m)} />
    );
    const ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px]';
    const ICON = 'h-4 w-4 text-muted-foreground';

    return (
        <TooltipProvider delayDuration={250}>
            <div className="flex h-full min-h-0" data-testid="channels-page">
                <WorkspaceRail workspaces={workspaces} channels={channels.channels} active={workspace} onSelect={switchWorkspace} onAdd={() => setAdding(true)} />
                <div
                    className={cn('relative shrink-0', channelOpen ? 'hidden md:flex' : 'flex w-full md:w-auto')}
                    style={{ '--channel-list-width': `${listWidth}px` } as CSSProperties}
                >
                    <ChannelList
                        workspace={workspace}
                        workspaces={workspaces}
                        channels={channels.channels}
                        activeId={channel.id}
                        user={user}
                        onSelect={select}
                        onSwitchWorkspace={switchWorkspace}
                        onAddWorkspace={() => setAdding(true)}
                        onNewChannel={() => setStarting(true)}
                        className="flex w-full"
                    />
                    <ResizeEdge panel={channelListPanel} label="Resize channel list" className="hidden md:block" />
                </div>
                <section
                    className={cn('relative min-w-0 flex-1 flex-col', channelOpen ? 'flex' : 'hidden md:flex')}
                    onDragEnter={(e) => {
                        if (!hasFiles(e) || closed) return;
                        dragDepth.current += 1;
                        setDropping(true);
                    }}
                    onDragOver={(e) => {
                        if (hasFiles(e) && !closed) e.preventDefault();
                    }}
                    onDragLeave={() => {
                        dragDepth.current = Math.max(0, dragDepth.current - 1);
                        if (!dragDepth.current) setDropping(false);
                    }}
                    onDrop={(e) => {
                        if (!hasFiles(e) || closed) return;
                        e.preventDefault();
                        dragDepth.current = 0;
                        setDropping(false);
                        addFiles(Array.from(e.dataTransfer.files));
                    }}
                >
                    {inPhone ? (
                        // A phone's bar becomes the channel's: back to the list, its name, its members.
                        channelOpen && (
                            <>
                                <PhoneBarBack
                                    label="All channels"
                                    onBack={back}
                                    title={
                                        <>
                                            <Hash className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                                            <span className="truncate">{channel.name}</span>
                                        </>
                                    }
                                />
                                <PhoneBarActions>{membersButton}</PhoneBarActions>
                            </>
                        )
                    ) : (
                        <header className={cn('flex h-14 shrink-0 items-center gap-3 border-b px-5', HAIRLINE)}>
                            <div className="flex min-w-0 flex-1 items-center gap-3">
                                <h1 className="flex min-w-0 shrink-0 items-center gap-1 text-[15px] font-semibold text-foreground">
                                    <Hash className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                                    <span className="truncate">{channel.name}</span>
                                </h1>
                                {schedules.length > 0 && <ScheduleChip schedules={schedules} />}
                                <span className="truncate text-[13px] text-muted-foreground">{channel.topic}</span>
                            </div>
                            <div className="flex shrink-0 items-center gap-1">
                                {membersButton}
                                <DropdownMenu>
                                    <DropdownMenuTrigger
                                        aria-label="Channel actions"
                                        className="grid h-8 w-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground"
                                    >
                                        <MoreHorizontal className="h-[18px] w-[18px]" />
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent
                                        align="end"
                                        sideOffset={8}
                                        className="min-w-[240px] rounded-xl p-1"
                                        onCloseAutoFocus={(e) => {
                                            if (!composeAfterMenu.current) return;
                                            // Editing the topic lands in the composer, caret after the current one.
                                            composeAfterMenu.current = false;
                                            e.preventDefault();
                                            const el = textareaRef.current;
                                            el?.focus();
                                            el?.setSelectionRange(el.value.length, el.value.length);
                                        }}
                                    >
                                        <DropdownMenuItem onSelect={() => note(summarizeChannel(channel.name, messages, members))} className={ITEM}>
                                            <ScrollText className={ICON} strokeWidth={1.75} />
                                            Catch me up
                                        </DropdownMenuItem>
                                        {!closed && (
                                            <>
                                                <DropdownMenuItem onSelect={editTopic} className={ITEM}>
                                                    <PenLine className={ICON} strokeWidth={1.75} />
                                                    Edit topic
                                                </DropdownMenuItem>
                                                <DropdownMenuItem onSelect={() => void setMode(channel.mode === 'all' ? 'mentions' : 'all')} className={ITEM}>
                                                    <MessagesSquare className={ICON} strokeWidth={1.75} />
                                                    {channel.mode === 'all' ? 'Agents answer only @-mentions' : 'Agents read every message'}
                                                </DropdownMenuItem>
                                            </>
                                        )}
                                        <DropdownMenuItem onSelect={copyLink} className={ITEM}>
                                            <Link2 className={ICON} strokeWidth={1.75} />
                                            Copy link to channel
                                        </DropdownMenuItem>
                                        {!closed && (
                                            <>
                                                <DropdownMenuSeparator className="mx-1 bg-border dark:bg-foreground/[0.08]" />
                                                <DropdownMenuItem onSelect={() => void closeChannel()} className={ITEM}>
                                                    <Archive className={ICON} strokeWidth={1.75} />
                                                    Close channel
                                                </DropdownMenuItem>
                                            </>
                                        )}
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </div>
                        </header>
                    )}
                    <div
                        ref={scrollRef}
                        onScroll={(e) => {
                            const el = e.currentTarget;
                            pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
                        }}
                        className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle"
                    >
                        <div className="flex min-h-full w-full flex-col pb-4">
                            {history?.error && !messages.length ? (
                                <p role="alert" className="m-auto max-w-sm px-6 text-center text-[14px] text-muted-foreground">
                                    {history.error}
                                </p>
                            ) : history && !history.loading ? (
                                <MessageList
                                    channel={channel}
                                    schedules={schedules}
                                    messages={messages}
                                    members={members}
                                    user={user}
                                    channels={byName}
                                    older={!!history.older}
                                    loadingOlder={history.loadingOlder}
                                    onLoadOlder={loadOlder}
                                    onChannel={select}
                                    onReact={(id, emoji) => void react(id, emoji)}
                                    onDismiss={(id) => channels.dismiss(channel.id, id)}
                                />
                            ) : (
                                <div className="mt-auto space-y-3 px-5 pb-2" aria-busy>
                                    {[0, 1, 2].map((i) => (
                                        <div key={i} className="h-10 animate-pulse rounded-xl bg-foreground/[0.04]" />
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                    {channel.status === 'halted' && (
                        <p className="mx-3 mb-1 rounded-xl bg-foreground/[0.04] px-4 py-2.5 text-[13px] leading-snug text-muted-foreground sm:mx-5" data-testid="channel-halted">
                            Agents are paused{channel.haltReason ? `: ${channel.haltReason.replace(/\.$/, '')}` : ''}. They pick up again when you post.
                        </p>
                    )}
                    {busy.length > 0 && (
                        <p className="px-5 pb-1 text-[12.5px] text-muted-foreground" aria-live="polite" data-testid="channel-working">
                            {new Intl.ListFormat('en', { type: 'conjunction' }).format(busy.map((m) => m.name))} {busy.length === 1 ? 'is' : 'are'} working…
                        </p>
                    )}
                    <ChannelComposer
                        key={channel.id}
                        channelName={channel.name}
                        value={draft.text}
                        onChange={(text) => updateDraft(channel.id, (d) => ({ ...d, text }))}
                        attachments={draft.attachments}
                        onAddFiles={addFiles}
                        onAddClip={addClip}
                        onRemoveAttachment={removeAttachment}
                        onSubmit={() => void post()}
                        members={mentionable}
                        user={user}
                        textareaRef={textareaRef}
                        disabled={closed ? 'This channel is closed.' : undefined}
                    />
                    {dropping && (
                        <div className="pointer-events-none absolute inset-3 z-30 grid place-items-center rounded-2xl border-2 border-dashed border-foreground/25 bg-background/85 backdrop-blur-sm">
                            <div className="text-center">
                                <Upload className="mx-auto h-6 w-6 text-foreground/70" strokeWidth={1.75} />
                                <p className="mt-2.5 text-[15px] font-medium text-foreground">Drop to share in #{channel.name}</p>
                                <p className="mt-0.5 text-[13px] text-muted-foreground">Images, documents, anything</p>
                            </div>
                        </div>
                    )}
                </section>
            </div>
            {dialogs}
        </TooltipProvider>
    );
}
