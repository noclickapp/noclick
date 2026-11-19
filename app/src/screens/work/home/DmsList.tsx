// Your conversations with the people in the space, newest first, each with its last line (people only: an agent's
// conversations are in Agents). The space's people you haven't written to yet follow, to start one with. Over them, as
// the Agents list has it: the way to invite more (your personal space takes people too), then a search by name, email
// or last line.
import { useState } from 'react';
import { UserPlus } from 'lucide-react';
import type { AccountMenuUser } from '@/ui/accountParts';
import { timeLabel } from '@/screens/channels/MessageList';
import { MemberAvatar } from '@/screens/channels/avatars';
import type { Channel, ChannelAuthor, ChannelMember } from '@/screens/channels/types';
import type { Intent } from '@/ui/useIntent';
import { cn } from '@/ui/utils';
import { ActionRow, Count, FindField, LIST_CURRENT, LIST_ROW, LIST_TOP, SectionHeader } from '../ui';

/** One DM as the list draws it: the other person, and the conversation. */
export interface DmRow {
    channel: Channel;
    person: ChannelMember;
}

const plain = (text: string) => text.replace(/[`*_~>#]/g, '').replace(/\s+/g, ' ').trim();

/** Newest conversation first: by its last message, else when it was started. */
export const byNewest = (a: Channel, b: Channel) => (b.lastMessage?.at ?? b.createdAt).localeCompare(a.lastMessage?.at ?? a.createdAt);

/** A DM's last line as its row reads it. */
export function lastLine(channel: Channel, myName: (author: ChannelAuthor) => boolean): string {
    const last = channel.lastMessage;
    return last ? `${myName(last.author) ? 'You: ' : ''}${plain(last.text)}` : 'No messages yet';
}

export function DmsList({
    dms,
    others,
    openId,
    user,
    myName,
    online,
    onOpen,
    ahead,
    onStart,
    onInvite,
    emailOf,
    alone = 'No one else is in this space yet.',
}: {
    dms: DmRow[];
    /** The space's people with no DM yet. */
    others: ChannelMember[];
    openId: string | null;
    user: AccountMenuUser;
    /** How the last line names you. */
    myName: (author: ChannelAuthor) => boolean;
    /** Whether a person is online now, for the dot on their face. */
    online: (person: ChannelMember) => boolean;
    onOpen: (channelId: string) => void;
    /** Reads ahead the DM a row the pointer rests on opens. */
    ahead?: Intent;
    onStart: (person: ChannelMember) => void;
    onInvite: (() => void) | null;
    /** A person's email, which the search finds them by too. */
    emailOf?: (person: ChannelMember) => string | null;
    /** What the list says while no one else is in the space. */
    alone?: string;
}) {
    const [query, setQuery] = useState('');
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const found = (...texts: (string | null | undefined)[]) => words.every((w) => texts.some((t) => t?.toLowerCase().includes(w)));
    const sorted = [...dms]
        .sort((a, b) => byNewest(a.channel, b.channel))
        .filter(({ channel, person }) => found(person.name, emailOf?.(person), channel.lastMessage ? plain(channel.lastMessage.text) : null));
    const shownOthers = others.filter((person) => found(person.name, emailOf?.(person)));
    const anyone = dms.length > 0 || others.length > 0;
    return (
        <>
            {onInvite && (
                <div className={LIST_TOP}>
                    <ActionRow icon={UserPlus} label="Invite people" onClick={onInvite} />
                </div>
            )}
            <FindField value={query} onChange={setQuery} placeholder="Find a person" />
            {query && anyone && !sorted.length && !shownOthers.length && <p className="px-2.5 pt-1 text-[13px] leading-snug text-muted-foreground">No one called “{query.trim()}”</p>}
            <ul className="flex flex-col gap-px" data-testid="dms-list">
                {sorted.map(({ channel, person }) => {
                    const last = channel.lastMessage;
                    const on = channel.id === openId;
                    return (
                        <li key={channel.id}>
                            <button type="button" onClick={() => onOpen(channel.id)} {...ahead?.(channel.id)} aria-current={on ? 'page' : undefined} className={cn(LIST_ROW, 'gap-3 py-2', on && LIST_CURRENT)}>
                                <Face person={person} user={user} online={online(person)} size={32} />
                                <span data-rail-text className="min-w-0 flex-1">
                                    <span className="flex items-baseline gap-2">
                                        <span data-rail-name className={cn('truncate text-[14px] text-foreground', channel.unread && !on ? 'font-semibold' : 'font-medium')}>{person.name}</span>
                                        {last?.at && <span className="ml-auto shrink-0 text-[11.5px] tabular-nums text-muted-foreground">{timeLabel(last.at)}</span>}
                                    </span>
                                    <span className="block truncate text-[12.5px] text-muted-foreground">{lastLine(channel, myName)}</span>
                                </span>
                                {channel.unread > 0 && !on && <Count n={channel.unread} />}
                            </button>
                        </li>
                    );
                })}
            </ul>
            {shownOthers.length > 0 && (
                <>
                    {sorted.length > 0 && <div className="h-3" />}
                    <SectionHeader label="People here" />
                    <ul className="flex flex-col gap-px">
                        {shownOthers.map((person) => (
                            <li key={person.id}>
                                <button type="button" onClick={() => onStart(person)} className={cn(LIST_ROW, 'h-10 gap-3 text-[14px] text-foreground/80 hover:text-foreground')}>
                                    <Face person={person} user={user} online={online(person)} size={28} />
                                    <span data-rail-text className="min-w-0 flex-1 truncate">
                                        <span>{person.name}</span>
                                    </span>
                                </button>
                            </li>
                        ))}
                    </ul>
                </>
            )}
            {!anyone && <p className="px-2.5 pt-1 text-[13px] leading-snug text-muted-foreground">{alone}</p>}
        </>
    );
}

/** A person's face, with a dot while they're online. */
export function Face({ person, user, online, size }: { person: ChannelMember; user: AccountMenuUser; online: boolean; size: 28 | 32 | 40 }) {
    return (
        <span className="relative inline-flex shrink-0">
            <MemberAvatar member={person} user={user} size={size} />
            {online && <span aria-label="Online" className={cn('absolute -bottom-0.5 -right-0.5 rounded-full bg-emerald-500 ring-2 ring-background', size >= 32 ? 'h-3 w-3' : 'h-2.5 w-2.5')} />}
        </span>
    );
}
