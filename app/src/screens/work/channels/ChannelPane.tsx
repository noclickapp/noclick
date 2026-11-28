// A channel (or a DM between two people) in Work's main pane, Slack's way: its name and topic over Slack's tabs
// (Messages, Pins, Files & links, Bookmarks), the timeline with each message's thread and pin, and the box. Every
// message goes to every person and agent in it. You post, share files and voice clips, react, pin, open a thread, and
// run slash commands in the box; on a phone the bar above becomes the channel's, with its way back.
import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from 'react';
import { ArchiveRestore, BellOff, BellRing, Hash, Link2, Lock, LogOut, MessageCircleQuestion, MoreHorizontal, Pencil, ScrollText, Star, StarOff, Trash2, Type, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { useReportHeld } from '@/sdk/held';
import { WorkClientContext } from '../client';
import type { AccountMenuUser } from '@/ui/accountParts';
import { HAIRLINE } from '@/ui/primitives';
import { PhoneBarActions, PhoneBarBack } from '@/ui/phoneBar';
import { MemberAvatar, presenceFace } from '@/screens/channels/avatars';
import { ChannelComposer } from '@/screens/channels/ChannelComposer';
import { channelCommands, mentionedMember, parseCommand, summarizeChannel } from '@/screens/channels/commands';
import { MessageList, MessageRow, type MessageActions } from '@/screens/channels/MessageList';
import { agentKey, modeLine, YOU } from '@/screens/channels/model';
import { ScheduleChip } from '@/screens/channels/schedules';
import { ChannelNameTaken, type ChannelsTransport } from '@/screens/channels/transport';
import type { AgentChoice, Channel, ChannelMember, ChannelMessage } from '@/screens/channels/types';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import type { Channels } from '@/screens/channels/useChannels';
import { useChannelSchedules } from '@/screens/channels/useChannelSchedules';
import { useWork } from '../context';
import { cn } from '@/ui/utils';
import { LogoMark, MARK_IN_A_SHAPE } from '@/ui/LogoMark';
import { keptByNoClick, noclickNaming, useAgentFrames, useAgentStates, useNoClickId, useSpaceNoClicks } from '../agents/reads';
import { isNoClickChannel, noclickChannelTopic, useSpaceNoClick } from '../intro';
import { ASKED_TITLE } from '../questions';
import { ChannelMembers } from './ChannelMembers';
import { ArchivedFooter, ChannelSettingsDialog, ClosedFooter, type ChannelDialog } from './settings';
import { sentFiles, type Drafts } from './drafts';
import type { ChannelShelf } from './shelf';
import { ChannelTabBar, ChannelTabBody, useChannelTabs, type ChannelTabs } from './tabs';
import { useChannelTypists, useTypingSignal } from '@/screens/channels/typing';
import { WorkingLine, workingLineOf, type LineTarget } from './WorkingLine';
import { useWorkViewer } from '../viewer';
import { NeedPills } from '../agents/needs';
import { ChannelAsks } from '@/screens/chat/cards/ChannelAsks';

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes('Files');
/** Every command where whoever shows Work hands asks to NoClick (`ask`): /remind and /automate are asks. */
const ALL_COMMANDS = channelCommands({ asksNoClick: true });
const OWN_COMMANDS = channelCommands({ asksNoClick: false });
const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.');
const ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px]';
const ICON = 'h-4 w-4 text-muted-foreground';
const DANGER = cn(ITEM, 'text-red-600 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400');
const SMALL_SECONDARY =
    'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium text-foreground ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:bg-foreground/[0.06] dark:ring-foreground/[0.08] dark:hover:bg-foreground/[0.1]';

/** An ask to draft in the box: a light chip, a suggestion rather than a button. */
const ASK =
    'inline-flex h-8 items-center rounded-full bg-foreground/[0.05] px-3 text-[13px] text-foreground/80 transition-colors hover:bg-foreground/[0.09] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

export interface ChannelPaneProps {
    channel: Channel;
    channels: Channels;
    transport: ChannelsTransport;
    shelf: ChannelShelf;
    drafts: Drafts;
    user: AccountMenuUser;
    /** The space's name, for what NoClick is asked from here. */
    spaceName: string;
    /** The space's channels by name, so a #name in a message opens it. */
    byName: ReadonlyMap<string, string>;
    /** A DM's other person, whose name the header and box use, and what's known of them (online, their role, email). */
    dmWith?: ChannelMember | null;
    dmPresence?: string | null;
    dmAbout?: string | null;
    phone: boolean;
    onBack: () => void;
    onOpenChannel: (id: string) => void;
    onThread: (messageId: string) => void;
    /** A member's name: a person's DM, an agent's profile. */
    onMember: (member: ChannelMember) => void;
    /** The channel went to the trash: go elsewhere. */
    onGone: () => void;
    /** You may change it (rename, close, reopen, delete): the account in its own space, or a space's admin. */
    manages: boolean;
    /** Its space is archived: everything in it is read, nothing posted (`onUnarchive` where the space is yours). */
    archived?: boolean;
    onUnarchive?: () => void;
    /** The space's NoClick channel: what your NoClick asked there, opened beside it. */
    asked?: { count: number; onOpen: () => void };
}

export function ChannelPane(props: ChannelPaneProps) {
    const { channel, channels, shelf, phone } = props;
    const tabs = useChannelTabs(channel.id, shelf, phone, channels.history(channel.id)?.loading === false);
    return <ChannelPaneBody key={channel.id} {...props} tabs={tabs} />;
}

function ChannelPaneBody({
    channel,
    channels,
    transport,
    drafts,
    user,
    spaceName,
    byName,
    dmWith,
    dmPresence,
    dmAbout,
    phone,
    onBack,
    onOpenChannel,
    onThread,
    onMember,
    onGone,
    manages,
    archived = false,
    onUnarchive,
    asked,
    tabs,
}: ChannelPaneProps & { tabs: ChannelTabs }) {
    const { ask } = useWork();
    const commands = ask ? ALL_COMMANDS : OWN_COMMANDS;
    const [dropping, setDropping] = useState(false);
    const dragDepth = useRef(0);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const [dialog, setDialog] = useState<ChannelDialog | null>(null);
    const reportHeld = useReportHeld({ client: useContext(WorkClientContext) });
    const scrollRef = useRef<HTMLDivElement>(null);
    const [lit, setLit] = useState<string | null>(null);

    // Each agent wears its harness's mark and says its job, from your agents; a NoClick is named and described as Work
    // names it everywhere (yours, or the space's own), both in NoClick's mark (by their ids: a member keeps the name it
    // joined under).
    const noclick = useNoClickId();
    const ours = useSpaceNoClick(channel.workspaceId ?? null);
    const personal = useSpaceNoClicks().personal.has(channel.workspaceId ?? '');
    const mentionable = useMemo(() => {
        const yours = new Map(channels.agents.map((a) => [a.id, a]));
        const named = (m: ChannelMember, space: { name: string } | null): ChannelMember => {
            const { name, line } = noclickNaming(space);
            return { ...m, name, role: line, noclick: true };
        };
        return channel.members.map((m): ChannelMember => {
            if (noclick && m.agentId === noclick) return named(m, null);
            if (m.noclick && (ours ? m.agentId === ours.agentId : !!channel.workspaceId && !personal)) return named(m, { name: spaceName });
            const agent = yours.get(agentKey(m) ?? '');
            return agent ? { ...m, ...(agent.markType ? { markType: agent.markType } : {}), ...(agent.role ? { role: agent.role } : {}) } : m;
        });
    }, [channel, channels.agents, noclick, ours, personal, spaceName]);
    const members = useMemo(() => [YOU, ...mentionable], [mentionable]);
    const history = channels.history(channel.id);
    const messages = useMemo(() => history?.messages ?? [], [history]);
    const draft = drafts.get(channel.id);
    // The space's NoClick works quietly in a channel (judging who needs to know what was posted): its turns show only
    // in its own NoClick channel, where it answers.
    const theNoClickChannel = isNoClickChannel(channel, noclick, ours?.agentId);
    const topic = theNoClickChannel ? noclickChannelTopic(channel, personal) : channel.topic;
    const shownChannel = useMemo(() => (topic === channel.topic ? channel : { ...channel, topic }), [channel, topic]);
    const busy = mentionable.filter((m) => m.busy && !(ours && m.agentId === ours.agentId && !theNoClickChannel));
    // Who is at it, over the box: agents at work or waiting on you (their steps where the reader sees agents' activity:
    // the account, never a person in its space) and the people typing, never you.
    const viewer = useWorkViewer();
    const own = viewer.type === 'account';
    const states = useAgentStates(null, { enabled: own && mentionable.some((m) => m.agentId) });
    useAgentFrames();
    const typists = useChannelTypists(transport, channel.id, own ? 'account' : (viewer.id ?? ''));
    const typing = useTypingSignal(transport, channel.id);
    const line = workingLineOf({ channelId: channel.id, members: mentionable, busy, states: own ? states.data : undefined, messages, typists });
    // What an agent's turn left waiting on a person, under its reply: an OK, and a secret's values, are the account's.
    const TurnAsks = useMemo(() => {
        const said = (askId: string, messageId: string) => transport.askConnected(channel.id, messageId, askId).catch((e) => console.warn('[channels] saying who connected failed:', e));
        return function ChannelTurnAsks({ message }: { message: ChannelMessage }) {
            return <ChannelAsks message={message} forAccount={own}onConnected={(askId) => void said(askId, message.id)} />;
        };
    }, [transport, channel.id, own]);
    const schedules = useChannelSchedules(transport, channel.id);
    const closed = channel.status === 'closed';
    const dm = channel.kind === 'dm';
    const title = dm ? (dmWith?.name ?? channel.name) : channel.name;

    // A channel opens at its newest message and stays there as messages land and late content (fonts, images)
    // settles, until you scroll up to read. Reading further back keeps your place.
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
    useEffect(() => {
        const el = scrollRef.current;
        const content = el?.firstElementChild;
        if (!el || !content || typeof ResizeObserver === 'undefined') return;
        const follow = new ResizeObserver(() => {
            if (pinned.current) el.scrollTop = el.scrollHeight;
        });
        follow.observe(content);
        // The pane itself shrinks or grows as what's over the box (the working line) comes and goes.
        follow.observe(el);
        return () => follow.disconnect();
    }, []);

    // A pin or a shared file opened from its tab lands on its message, centred and lit for a moment.
    useEffect(() => {
        if (!tabs.jump || tabs.view !== 'messages') return;
        const id = tabs.jump.id;
        let frame = requestAnimationFrame(() => {
            frame = requestAnimationFrame(() => {
                const el = scrollRef.current?.querySelector<HTMLElement>(`[data-message-id="${CSS.escape(id)}"]`);
                if (!el) return;
                pinned.current = false;
                el.scrollIntoView({ block: 'center' });
                setLit(id);
                tabs.landed();
            });
        });
        return () => cancelAnimationFrame(frame);
    }, [tabs, tabs.jump, tabs.view]);
    useEffect(() => {
        if (!lit) return;
        const t = setTimeout(() => setLit(null), 2600);
        return () => clearTimeout(t);
    }, [lit]);

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
    // Who joined or left is the channel's own record, a line in its history; nothing to add here.
    const addAgent = (agent: AgentChoice) => act(() => channels.addAgent(channel.id, agent));
    const removeMember = (member: ChannelMember) => act(() => channels.removeMember(channel.id, member.id));
    const reopenChannel = async () => {
        try {
            await channels.reopen(channel.id);
            toast(`Reopened #${channel.name}`, { description: 'Everyone can post in it again.' });
        } catch (e) {
            if (e instanceof ChannelNameTaken) setDialog('reopen');
            else toast(`Couldn’t reopen #${channel.name}`, { description: errorText(e) });
        }
    };
    const closeChannel = async () => {
        try {
            await channels.close(channel.id);
            toast(`Closed #${channel.name}`, {
                description: 'Everyone can still read it. No one can post, and its agents stop answering in it.',
                action: { label: 'Undo', onClick: () => void reopenChannel() },
            });
        } catch (e) {
            if (reportHeld(e, `Close #${channel.name}`)) return;
            note(errorText(e));
        }
    };
    // A platform that counts @-mentions (its view carries them) also lets a person join a channel again.
    const counted = channel.mentions !== undefined;
    /** Star or mute it for you alone, or undo either, saying what it does where that isn't plain. */
    const prefer = (preference: 'starred' | 'muted', on: boolean) =>
        channels.setPreference(channel.id, preference, on).then(
            () =>
                toast(
                    `${preference === 'starred' ? (on ? 'Starred' : 'Unstarred') : on ? 'Muted' : 'Unmuted'} #${channel.name}`,
                    on ? { description: preference === 'starred' ? 'It’s at the top of your channels.' : counted ? 'Only @-mentions of you still reach you.' : 'It’s never bold or counted for you, and NoClick doesn’t tell you about it.' } : undefined
                ),
            (e: unknown) => toast(`Couldn’t ${preference === 'starred' ? (on ? 'star' : 'unstar') : on ? 'mute' : 'unmute'} #${channel.name}`, { description: errorText(e) })
        );
    const leaveChannel = () =>
        channels.leave(channel.id).then(
            () =>
                toast(`You left #${channel.name}`, {
                    description: counted ? 'It carries on without you.' : 'It carries on without you. Post in it to join again.',
                    ...(counted && { action: { label: 'Undo', onClick: () => void channels.join(channel.id).catch((e: unknown) => toast(`Couldn’t join #${channel.name}`, { description: errorText(e) })) } }),
                }),
            (e: unknown) => toast(`Couldn’t leave #${channel.name}`, { description: errorText(e) })
        );
    // A person stars, mutes and leaves only a channel they're in; the account reads every one of its own.
    const yours = channel.joined !== false;
    /** A channel made mention-only before: its agents answer every message from now on. */
    const answerEveryMessage = () => act(() => channels.updateChannel(channel.id, { mode: 'all' }), `${modeLine('all', agentsInRoom)}.`);

    /** A slash command: a change to the channel, an ask handed to NoClick, or NoClick's answer to you alone. */
    const run = async ({ name, command, args }: NonNullable<ReturnType<typeof parseCommand>>) => {
        if (!command || !commands.includes(command)) {
            note(`\`/${name}\` isn't a command here. Try ${commands.map((c) => `\`/${c.name}\``).join(', ')}.`);
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
            case 'close':
                await closeChannel();
                return;
            case 'remind':
                if (!args) {
                    note('Say what and when, like `/remind me to call Maya in 2h`.');
                    return;
                }
                ask?.(`Remind ${/^me\b/i.test(args) ? args : `me ${args}`} (from #${channel.name} in ${spaceName})`);
                return;
            case 'automate':
                ask?.(`Turn this into an automation${args ? `: ${args}` : ''} (from #${channel.name} in ${spaceName})`);
                return;
        }
    };

    const post = async () => {
        const text = draft.text.trim();
        if (!text && !draft.attachments.length) return;
        const command = draft.attachments.length ? null : parseCommand(text);
        const sent = drafts.take(channel.id);
        typing.stop();
        if (command) {
            await run(command);
            return;
        }
        pinned.current = true;
        try {
            await channels.post(channel.id, text, sentFiles(sent));
        } catch (e) {
            toast.error(errorText(e));
            drafts.restore(channel.id, sent);
        }
    };

    const react = (messageId: string, emoji: string) => channels.toggleReaction(channel.id, messageId, emoji).catch((e) => toast.error(errorText(e)));
    const loadOlder = () => {
        const el = scrollRef.current;
        if (el) keepFromBottom.current = el.scrollHeight - el.scrollTop;
        channels.loadOlder(channel.id).catch((e) => toast.error(errorText(e)));
    };
    const linkTo = (messageId?: string) => {
        const url = new URL(window.location.href);
        url.searchParams.set('channel', channel.id);
        url.searchParams.delete('thread');
        if (messageId) url.hash = `m-${messageId}`;
        navigator.clipboard.writeText(url.toString()).then(
            () => toast.success('Link copied'),
            () => toast.error('Couldn’t copy the link')
        );
    };
    const actions: MessageActions = {
        onThread,
        onPin: (m: ChannelMessage) => void tabs.togglePin(m.id, !m.pinned).then((now) => now && channels.upsert(channel.id, now)),
        onCopyLink: (id) => linkTo(id),
        onSeePins: () => tabs.setView('pins'),
        onOpenMessage: (id) => tabs.open(id),
        onAnswer: (text, channelId) => {
            void channels.post(channelId ?? channel.id, text, []).catch((e) => toast.error(errorText(e)));
            if (channelId && channelId !== channel.id) onOpenChannel(channelId);
        },
        // What an agent made on an agents page still needs, connected from its message.
        Asks: NeedPills,
        TurnAsks,
        // An author's name and face open them: an agent's profile, a person's DM.
        onAuthor: onMember,
        lit,
    };

    const membersButton = (
        <ChannelMembers channel={channel} members={mentionable} agents={channels.agents} user={user} onMember={onMember} onAdd={(a) => void addAgent(a)} onRemove={(m) => void removeMember(m)} onAnswerEveryMessage={() => void answerEveryMessage()} />
    );
    const catchUp = () => note(summarizeChannel(channel.name, messages, members));
    /** The line's tap: the thread an agent's turn answers in, its profile, or the question it waits on you with. */
    const openLine = (target: LineTarget) => (target.kind === 'thread' ? onThread(target.id) : target.kind === 'question' ? tabs.open(target.messageId) : onMember(target.member));
    // Its ⋯ menu, beside its name on a laptop and in the bar on a phone.
    const channelMenu = (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label="Channel actions"
                className="grid h-8 w-8 place-items-center rounded-full max-md:h-10 max-md:w-10 text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground"
            >
                <MoreHorizontal className="h-[18px] w-[18px]" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" sideOffset={8} className="min-w-[240px] rounded-xl p-1">
                {yours && (
                    <>
                        <DropdownMenuItem onSelect={() => void prefer('starred', !channel.starred)} className={ITEM}>
                            {channel.starred ? <StarOff className={ICON} strokeWidth={1.75} /> : <Star className={ICON} strokeWidth={1.75} />}
                            {channel.starred ? 'Unstar' : 'Star'}
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => void prefer('muted', !channel.muted)} className={ITEM}>
                            {channel.muted ? <BellRing className={ICON} strokeWidth={1.75} /> : <BellOff className={ICON} strokeWidth={1.75} />}
                            {channel.muted ? 'Unmute' : 'Mute'}
                        </DropdownMenuItem>
                    </>
                )}
                {manages && (
                    <>
                        <DropdownMenuItem disabled={closed} onSelect={() => setDialog('rename')} className={ITEM}>
                            <Pencil className={ICON} strokeWidth={1.75} />
                            Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem disabled={closed} onSelect={() => setDialog('topic')} className={ITEM}>
                            <Type className={ICON} strokeWidth={1.75} />
                            Edit topic
                        </DropdownMenuItem>
                    </>
                )}
                <DropdownMenuItem onSelect={() => linkTo()} className={ITEM}>
                    <Link2 className={ICON} strokeWidth={1.75} />
                    Copy link
                </DropdownMenuItem>
                {(channel.joined || manages) && <DropdownMenuSeparator className="mx-1 bg-border dark:bg-foreground/[0.08]" />}
                {channel.joined && (
                    <DropdownMenuItem onSelect={() => void leaveChannel()} className={DANGER}>
                        <LogOut className="h-4 w-4" strokeWidth={1.75} />
                        Leave channel
                    </DropdownMenuItem>
                )}
                {manages && !archived && (
                    closed ? (
                        <DropdownMenuItem onSelect={() => void reopenChannel()} className={ITEM}>
                            <ArchiveRestore className={ICON} strokeWidth={1.75} />
                            Reopen channel
                        </DropdownMenuItem>
                    ) : (
                        <DropdownMenuItem onSelect={() => void closeChannel()} className={DANGER}>
                            <Lock className="h-4 w-4" strokeWidth={1.75} />
                            Close channel
                        </DropdownMenuItem>
                    )
                )}
                {manages && (
                    <DropdownMenuItem onSelect={() => setDialog('delete')} className={DANGER}>
                        <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                        Delete channel
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    );


    // The space's NoClick channel, before anything's said in it (who joined says nothing): what to ask NoClick, each
    // ask a tap into the box. One names an agent of yours by its own name, never a NoClick (the platform flags each,
    // whatever space it's of) or one still called what new agents are; with none, it's left out.
    const anAgent = channels.agents.find((a) => !keptByNoClick(a) && !/^(new )?agent( \d+)?$/i.test(a.name.trim()))?.name;
    const firstAsks =
        !closed && theNoClickChannel && !messages.some((m) => !m.ephemeral && !m.membership)
            ? [
                  'Add a channel for launch plans',
                  ...(anAgent ? [`Add ${anAgent} to #launch-plans`] : []),
                  // The personal space holds no people: they're a space's.
                  channel.workspaceId ? 'Invite a teammate to this space' : 'Make a space for my team',
              ]
            : null;
    const draftAsk = (ask: string) => {
        drafts.setText(channel.id, ask);
        requestAnimationFrame(() => {
            const el = textareaRef.current;
            el?.focus();
            el?.setSelectionRange(ask.length, ask.length);
        });
    };

    return (
        <section
            className="relative flex min-h-0 min-w-0 flex-1 flex-col"
            data-testid="channel-pane"
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
                Array.from(e.dataTransfer.files).forEach((file) => drafts.attach(channel.id, channel.id, file));
            }}
        >
            {phone ? (
                <>
                    <PhoneBarBack
                        label={dm ? 'DMs' : 'Channels'}
                        onBack={onBack}
                        title={
                            dm && dmWith ? (
                                <>
                                    <MemberAvatar member={dmWith} user={user} size={24} state={presenceFace(dmWith)} />
                                    <span className="truncate">{title}</span>
                                </>
                            ) : (
                                <>
                                    <Hash className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                                    <span className="truncate">{title}</span>
                                </>
                            )
                        }
                    />
                    {!dm && (
                        <PhoneBarActions>
                            {membersButton}
                            {channelMenu}
                        </PhoneBarActions>
                    )}
                </>
            ) : (
                <header className={cn('flex h-12 shrink-0 items-center gap-3 px-5', dm && 'border-b', HAIRLINE)}>
                    <div className="flex min-w-0 flex-1 items-center gap-3">
                        {dm && dmWith ? (
                            <div className="flex min-w-0 items-center gap-2.5">
                                <MemberAvatar member={dmWith} user={user} size={28} state={presenceFace(dmWith)} />
                                <span className="min-w-0">
                                    <span className="block truncate text-sm font-semibold leading-tight">{title}</span>
                                    {dmPresence && <span className="block truncate text-xs leading-tight text-muted-foreground">{dmPresence}</span>}
                                </span>
                            </div>
                        ) : (
                            <>
                                <h1 className="flex min-w-0 shrink-0 items-center gap-1 text-[17px] font-semibold tracking-[-0.01em] text-foreground">
                                    <Hash className="h-[18px] w-[18px] shrink-0 text-muted-foreground" strokeWidth={2} />
                                    <span className="truncate">{title}</span>
                                </h1>
                                {schedules.length > 0 && <ScheduleChip schedules={schedules} />}
                                <span className="truncate text-xs text-muted-foreground">{topic}</span>
                            </>
                        )}
                    </div>
                    {!dm && (
                        <div className="flex shrink-0 items-center gap-1.5">
                            {asked && (
                                // Short, so the channel's name keeps its room beside an open panel.
                                <button type="button" onClick={asked.onOpen} className={SMALL_SECONDARY} aria-label={`${ASKED_TITLE}: ${asked.count}`} data-testid="channel-asked">
                                    <MessageCircleQuestion className="h-4 w-4" strokeWidth={2} />
                                    Asked
                                    <span className="tabular-nums text-muted-foreground">{asked.count}</span>
                                </button>
                            )}
                            {membersButton}
                            <button type="button" onClick={catchUp} className={SMALL_SECONDARY}>
                                <ScrollText className="h-4 w-4" strokeWidth={2} />
                                Catch up
                            </button>
                            {channelMenu}
                        </div>
                    )}
                </header>
            )}
            {!dm && <ChannelTabBar tabs={tabs} />}
            <div className="relative flex min-h-0 flex-1 flex-col">
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
                                channel={shownChannel}
                                schedules={schedules}
                                messages={messages}
                                members={members}
                                user={user}
                                channels={byName}
                                older={!!history.older}
                                loadingOlder={history.loadingOlder}
                                onLoadOlder={loadOlder}
                                onChannel={onOpenChannel}
                                onReact={(id, emoji) => void react(id, emoji)}
                                onDismiss={(id) => channels.dismiss(channel.id, id)}
                                actions={actions}
                                introMark={theNoClickChannel ? <LogoMark alt="" className={cn('h-6 w-6', MARK_IN_A_SHAPE)} /> : undefined}
                                introAfter={
                                    firstAsks && (
                                        <div role="group" aria-label="Ask NoClick" className="mt-3 flex flex-wrap gap-1.5" data-testid="noclick-channel-asks">
                                            {firstAsks.map((ask) => (
                                                <button key={ask} type="button" onClick={() => draftAsk(ask)} className={ASK}>
                                                    {ask}
                                                </button>
                                            ))}
                                        </div>
                                    )
                                }
                                intro={
                                    dm && dmWith ? (
                                        <div className="px-5 pb-2 pt-10" data-testid="dm-intro">
                                            <MemberAvatar member={dmWith} user={user} size={48} />
                                            <h2 className="mt-4 font-brand text-[24px] font-semibold tracking-[-0.02em]">{dmWith.name}</h2>
                                            {dmAbout && <p className="mt-1 text-sm text-muted-foreground">{dmAbout}</p>}
                                            <p className="mt-3 text-xs text-muted-foreground">Only the two of you read this conversation.</p>
                                        </div>
                                    ) : undefined
                                }
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
                {!dm && (
                    <ChannelTabBody
                        tabs={tabs}
                        members={members}
                        renderMessage={(m) => <PlainMessage msg={m} members={members} user={user} byName={byName} onOpenChannel={onOpenChannel} onReact={(emoji) => void react(m.id, emoji)} />}
                    />
                )}
            </div>
            {/* Another tab hides the box, keeping what's typed in it. */}
            <div
                className={tabs.view === 'messages' || dm ? 'contents' : 'hidden'}
                onBlur={(e) => {
                    if ((e.target as Node) === textareaRef.current) typing.stop();
                }}
            >
                {channel.status === 'halted' && (
                    <p className="mx-3 mb-1 rounded-xl bg-foreground/[0.04] px-4 py-2.5 text-[13px] leading-snug text-muted-foreground sm:mx-5" data-testid="channel-halted">
                        Agents are paused{channel.haltReason ? `: ${channel.haltReason.replace(/\.$/, '')}` : ''}. They pick up again when you post.
                    </p>
                )}
                {!archived && !closed && <WorkingLine model={line} user={user} onOpen={openLine} />}
                {archived ? (
                    <ArchivedFooter spaceName={spaceName} onUnarchive={onUnarchive} />
                ) : closed ? (
                    <ClosedFooter channel={channel} onReopen={manages ? () => void reopenChannel() : undefined} />
                ) : (
                    <ChannelComposer
                        channelName={channel.name}
                        placeholder={dm ? `Message ${title}` : undefined}
                        value={draft.text}
                        onChange={(text) => {
                            drafts.setText(channel.id, text);
                            typing.input(text);
                        }}
                        attachments={draft.attachments}
                        onAddFiles={(files) => files.forEach((file) => drafts.attach(channel.id, channel.id, file))}
                        onAddClip={(clip) => drafts.attach(channel.id, channel.id, clip.file, clip)}
                        onRemoveAttachment={(localId) => drafts.remove(channel.id, localId)}
                        onSubmit={() => void post()}
                        members={mentionable}
                        user={user}
                        textareaRef={textareaRef}
                        commands={commands}
                    />
                )}
            </div>
            {dialog && <ChannelSettingsDialog kind={dialog} channel={channel} channels={channels} onClose={() => setDialog(null)} onGone={onGone} />}
            {dropping && (
                <div className="pointer-events-none absolute inset-3 z-30 grid place-items-center rounded-[26px] border-2 border-dashed border-foreground/25 bg-background/85 backdrop-blur-sm">
                    <div className="text-center">
                        <Upload className="mx-auto h-6 w-6 text-foreground/70" strokeWidth={1.75} />
                        <p className="mt-2.5 text-[15px] font-medium text-foreground">Drop to share in {dm ? title : `#${channel.name}`}</p>
                        <p className="mt-0.5 text-[13px] text-muted-foreground">Images, documents, anything</p>
                    </div>
                </div>
            )}
        </section>
    );
}

/** A message as a tab shows it: its words, files and reactions, without the timeline's actions. */
export function PlainMessage({
    msg,
    members,
    user,
    byName,
    onOpenChannel,
    onReact,
    compact,
}: {
    msg: ChannelMessage;
    members: ChannelMember[];
    user: AccountMenuUser;
    byName: ReadonlyMap<string, string>;
    onOpenChannel: (id: string) => void;
    onReact: (emoji: string) => void;
    compact?: boolean;
}): ReactNode {
    return <MessageRow msg={msg} members={members} user={user} channels={byName} onChannel={onOpenChannel} onReact={(_, emoji) => onReact(emoji)} onDismiss={() => undefined} compact={compact} />;
}
