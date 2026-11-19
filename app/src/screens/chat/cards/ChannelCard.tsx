// The channel itself, in the reply that made it (or put an agent in a channel the person named): its name with the way
// in, its agents' newest words as Work's own message row draws them, and a box to answer them. Sending posts the answer
// in the channel as you and moves you there, into Work, as Open does. Before an agent has said anything, its face and
// job stand in for its words. The card carries the agents its turn made (their own cards step aside), each one's name
// opening it to edit. Once you've been in the channel it folds to a line that opens it: by the platform's read point
// once there's anything to read there, else by Work having opened it on this device.
import { useState, type FormEvent } from 'react';
import { ArrowUp, ArrowUpRight, Hash, Loader2 } from 'lucide-react';
import { openedAt, rememberOpened } from '@/screens/work/remember';
import { useChannelReply, type ReplyAgent } from './useChannelReply';
import { CARD, PILL_QUIET, Receipt, Status } from '@/ui/chat/primitives';
import { useNewerCard } from '@/screens/chat/cards/canvases';
import { MemberAvatar } from '@/screens/channels/avatars';
import { MessageRow } from '@/screens/channels/MessageList';
import { authorMember } from '@/screens/channels/model';
import type { Channel, ChannelMember, ChannelMessage } from '@/screens/channels/types';
import { TooltipProvider } from '@/ui/tooltip';
import type { CoordinatorToolCall } from '@/lib/toolCalls';
import { openChannelInWork } from '@/screens/work/place';
import { cn } from '@/ui/utils';
import { mentions } from '@/screens/chat/cards/agentWords';
import { channelCanvas, channelCardOf } from './cardMatchers';
import { editAgent, type EditableAgent } from './PlatformCards';

/** How many of the agents' newest messages the card shows. */
const SHOWN = 2;
const NO_CHANNELS: ReadonlyMap<string, string> = new Map();
const NAME_BUTTON = 'rounded-sm font-medium text-foreground underline-offset-[3px] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70';

/** The timeline since the agent the call put in a channel arrived there (after the entry that added it: all the page
 *  holds, where the page starts after that entry); a channel the call made, all of it. Null where the history holds
 *  no such entry. */
function sinceArrival(messages: ChannelMessage[], older: boolean, joined: string | undefined): ChannelMessage[] | null {
    if (!joined) return messages;
    for (let i = messages.length - 1; i >= 0; i--) {
        const entry = messages[i].membership;
        if (entry?.action === 'added' && entry.members.some((m) => m.id === joined)) return messages.slice(i + 1);
    }
    return older ? messages : null;
}

/** Whether your read point is past the agent's arrival: fewer unread than what came since (who joined counts for
 *  none). A muted channel's count says nothing of it. */
function readSinceArrival(channel: Channel, since: ChannelMessage[] | null): boolean {
    const counted = (since ?? []).filter((m) => !m.membership).length;
    return !channel.muted && counted > 0 && channel.unread < counted;
}

/** The automation an agent in the channel runs on, where it's known. */
function workflowOf(member: ChannelMember, agents: ReadonlyMap<string, ReplyAgent>): string | null {
    return member.workflowId ?? (member.agentId ? (agents.get(member.agentId)?.workflowId ?? null) : null);
}

/** The agent in the channel as editing opens it: by its id, else its automation, where it's known. */
function editable(member: ChannelMember, agents: ReadonlyMap<string, ReplyAgent>): EditableAgent | null {
    const workflowId = workflowOf(member, agents);
    return member.agentId || workflowId ? { agentId: member.agentId, workflowId, name: member.name } : null;
}

/** An agent's name, opening it to edit. */
function AgentName({ member, agents }: { member: ChannelMember; agents: ReadonlyMap<string, ReplyAgent> }) {
    const agent = editable(member, agents);
    if (!agent) return <span className="font-medium text-foreground">{member.name}</span>;
    return (
        <button type="button" title={`Edit ${member.name}`} onClick={() => editAgent(agent)} className={NAME_BUTTON}>
            {member.name}
        </button>
    );
}

export function PlatformChannelCard({ call }: { call: CoordinatorToolCall }) {
    const card = channelCardOf(call)!;
    const newer = useNewerCard(call.id, channelCanvas(call));
    const reply = useChannelReply(card.channelId, card.joined);
    // Moved there from this card, or opened in Work on this device since the call.
    const [moved, setMoved] = useState(() => {
        const at = openedAt(card.channelId);
        return at !== null && at >= call.startedAt;
    });
    const [draft, setDraft] = useState('');
    const [sending, setSending] = useState(false);
    const [sendError, setSendError] = useState<string | null>(null);
    const { channel, messages, carried, agents } = reply;
    // A join's call names no channel: its name comes with the read.
    const name = channel?.name ?? card.name;
    const label = name ? `#${name}` : '';

    if (reply.gone) return <Receipt tone="info">{label || 'The channel'} was deleted</Receipt>;

    const move = () => {
        rememberOpened(card.channelId);
        setMoved(true);
        openChannelInWork(card.channelId);
    };
    const members = channel?.members ?? [];
    const authorOf = (m: ChannelMessage) => {
        const author = authorMember(m.author, members);
        return author && carried.some((c) => c.id === author.id) ? author : null;
    };
    const words = (messages ?? []).filter((m) => !m.membership && authorOf(m)).slice(-SHOWN);
    const opened = moved || (!!channel && !!messages && readSinceArrival(channel, sinceArrival(messages, reply.older, card.joined)));

    if (newer || opened) {
        return (
            <div data-testid="coordinator-channel-card" data-folded="">
                <Receipt tone="info" lead={<Hash className="h-4 w-4 shrink-0 text-foreground/60" />}>
                    <button type="button" onClick={move} aria-label={`Open ${label || 'the channel'}`} className={cn(NAME_BUTTON, 'inline-flex items-center gap-1')}>
                        {name ?? 'the channel'}
                        <ArrowUpRight className="h-3.5 w-3.5" />
                    </button>
                    {carried.map((m) => (
                        <span key={m.id}>
                            {' · '}
                            <AgentName member={m} agents={agents} />
                        </span>
                    ))}
                </Receipt>
            </div>
        );
    }

    const newest = words[words.length - 1];
    const to = (newest && authorOf(newest)) ?? (carried.length === 1 ? carried[0] : null);
    const placeholder = newest && to ? `Reply to ${to.name}` : to ? `Message ${to.name}` : `Message ${label}`;
    const send = async (e: FormEvent) => {
        e.preventDefault();
        const said = draft.trim();
        if (!said || sending) return;
        setSending(true);
        setSendError(null);
        try {
            // Where agents answer only when @-mentioned, the one it replies to is.
            await reply.post(channel?.mode === 'mentions' && to && !mentions(said, to.name) ? `@${to.name} ${said}` : said);
            setDraft('');
            move();
        } catch (error) {
            setSendError(error instanceof Error ? error.message : String(error));
        } finally {
            setSending(false);
        }
    };

    return (
        <section className={cn(CARD, 'overflow-hidden')} data-testid="coordinator-channel-card">
            <header className="flex items-center gap-2 pl-4 pr-2 pt-2.5">
                <h3 className="min-w-0 flex-1 truncate text-[14.5px] font-medium tracking-[-0.005em] text-foreground">
                    {label}
                    {reply.space && <span className="font-normal text-muted-foreground"> · {reply.space}</span>}
                </h3>
                <button type="button" onClick={move} className={cn(PILL_QUIET, 'h-7 text-[12.5px]')}>
                    Open
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </button>
            </header>
            {!channel || !messages ? (
                <div className="px-4 py-2.5">{reply.error ? <p className="text-[13px] text-red-600 dark:text-red-400">{reply.error}</p> : <Status state="working">Reading the channel</Status>}</div>
            ) : words.length ? (
                <TooltipProvider delayDuration={250}>
                    {words.map((m, i) => {
                        const agent = editable(authorOf(m)!, agents);
                        return (
                            <MessageRow
                                key={m.id}
                                msg={m}
                                prev={words[i - 1]}
                                members={members}
                                channels={NO_CHANNELS}
                                onChannel={openChannelInWork}
                                onReact={(_, emoji) => reply.react(m, emoji)}
                                onDismiss={() => undefined}
                                actions={agent ? { onAuthor: () => editAgent(agent) } : undefined}
                                compact
                            />
                        );
                    })}
                </TooltipProvider>
            ) : (
                <div className="space-y-3 px-4 pb-1.5 pt-2.5" data-testid="channel-card-agents">
                    {carried.length ? (
                        carried.map((m) => {
                            const role = m.agentId ? agents.get(m.agentId)?.role : undefined;
                            return (
                                <div key={m.id} className="flex items-start gap-3">
                                    <MemberAvatar member={role ? { ...m, role } : m} size={32} />
                                    <div className="min-w-0 pt-px text-[14px] leading-snug">
                                        <AgentName member={m} agents={agents} />
                                        {role && <p className="mt-0.5 text-[13px] text-muted-foreground">{role}</p>}
                                    </div>
                                </div>
                            );
                        })
                    ) : (
                        <p className="text-[13.5px] text-muted-foreground">{channel.topic || 'Nothing’s been said here yet.'}</p>
                    )}
                </div>
            )}
            {channel?.status === 'closed' ? (
                <p className="px-4 pb-3.5 pt-1 text-[13px] text-muted-foreground">It’s closed: everyone can still read it, and no one can post.</p>
            ) : (
                <form className="px-3 pb-3 pt-1.5" onSubmit={(e) => void send(e)}>
                    <div className="flex h-11 items-center gap-2 rounded-full bg-composer pl-4 pr-1.5 ring-1 ring-inset ring-border focus-within:ring-foreground/20 dark:ring-foreground/[0.09]">
                        <input
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            placeholder={placeholder}
                            aria-label={placeholder}
                            enterKeyHint="send"
                            disabled={!channel}
                            className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] disabled:opacity-60"
                        />
                        <button
                            type="submit"
                            aria-label={`Send in ${label}`}
                            disabled={!draft.trim() || sending || !channel}
                            className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:bg-foreground/[0.08] disabled:text-foreground/35"
                        >
                            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" strokeWidth={2.25} />}
                        </button>
                    </div>
                    {(sendError || (reply.error && channel && messages)) && (
                        <p role="alert" className="mt-1.5 px-3 text-[12.5px] text-red-600 dark:text-red-400">
                            {sendError ?? reply.error}
                        </p>
                    )}
                </form>
            )}
        </section>
    );
}
