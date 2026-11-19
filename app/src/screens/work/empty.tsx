// What a Work view's main pane shows with nothing open in it, never a blank pane: Agents' agents as tiles to open (with
// none, an agent's face and the way to make one), DMs' recent conversations (with none, the way to start one or to invite
// someone), and Home's channels. Resources' nothing-open is its own overview. Built from the shell's notice and tile,
// the lists' own reads and faces, so each pane reads as its list does.
import type { ReactNode } from 'react';
import { Hash, Lock, MessagesSquare, Plus, UserPlus } from 'lucide-react';
import type { AccountMenuUser } from '@/ui/accountParts';
import { BotPlus } from '@/ui/BotPlus';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { Facepile, MemberAvatar } from '@/screens/channels/avatars';
import type { Channel, ChannelAuthor, ChannelMember } from '@/screens/channels/types';
import { Tile, TileSkeletons } from '@/ui/Tile';
import { WorkNotice } from './notices';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { errorText } from '@/screens/console/pages/resources/shared';
import { AgentRing } from './agents/AgentRing';
import { useAgentEntries } from './agents/AgentsList';
import { byNewest, Face, lastLine, type DmRow } from './home/DmsList';
import { PageHead } from '@/ui/PageHead';
import { Count } from './ui';

/** The DMs shown to pick from: the newest. */
const RECENT_DMS = 6;
/** A drawn agent that isn't one yet: the one you'd make. */
const TO_MAKE: ChannelMember = { id: 'agent-to-make', kind: 'agent', name: 'Your first agent' };
const ROUND_MARK = 'grid h-10 w-10 shrink-0 place-items-center rounded-full bg-foreground/[0.05]';

/** A view's pane with things to open: its title and a line, its pill, then them as tiles (grey while they're read). */
function Pick({ title, line, action, loading, children, testId }: { title: string; line: string; action?: ReactNode; loading?: boolean; children?: ReactNode; testId: string }) {
    return (
        <div className="@container min-h-0 flex-1 overflow-y-auto scrollbar-subtle" data-testid={testId}>
            <div className="mx-auto w-full max-w-[1040px] px-5 pb-20 pt-6 @2xl:px-10 @2xl:pt-10">
                <PageHead title={title} line={line} actions={action} actionsAt="bottom" />
                <div className="mt-8">{loading ? <TileSkeletons count={3} /> : <div className="grid gap-2.5 @xl:grid-cols-2 @4xl:grid-cols-3">{children}</div>}</div>
            </div>
        </div>
    );
}

const tile = 'rounded-[20px]';

/** Agents with no agent open: the space's agents, each with its ring and what it's doing or last did; with none, an
 *  agent's face and the way to make one. */
export function AgentsEmpty({ spaceId, onOpen, onNew }: { spaceId: string | null; onOpen: (agentId: string) => void; onNew: () => void }) {
    const { states, entries, faces, loading } = useAgentEntries(spaceId);
    if (states.error !== undefined && !states.data) return <WorkNotice testId="agents-empty" title="Couldn’t load your agents" body={errorText(states.error)} action={{ label: 'Try again', onClick: () => void states.refresh() }} />;
    if (!loading && !entries.length)
        return (
            <WorkNotice
                testId="agents-empty"
                mark={<MemberAvatar member={TO_MAKE} size={80} state="waiting" />}
                title="No agents in this space yet"
                body="Give one a job and it works here: in your channels, on its own triggers, asking you when it needs to."
                action={{ label: 'Make an agent', onClick: onNew }}
            />
        );
    return (
        <Pick
            testId="agents-empty"
            title="Agents"
            line="Open one to talk to it or see what it’s doing."
            loading={loading}
            action={
                <button type="button" onClick={onNew} className={BUTTON_SECONDARY}>
                    <BotPlus className="h-4 w-4" strokeWidth={1.75} />
                    New agent
                </button>
            }
        >
            {entries.map((e) => (
                <Tile
                    key={e.id}
                    mark={<AgentRing member={faces.get(e.id) ?? { id: e.id, kind: 'agent', name: e.name }} status={e.status} size={40} />}
                    title={e.name}
                    detail={e.line}
                    label={`Open ${e.name}`}
                    trailing={e.needs > 0 ? <Count n={e.needs} /> : undefined}
                    onOpen={() => onOpen(e.id)}
                    testId={`agent-tile-${e.id}`}
                    className={tile}
                />
            ))}
        </Pick>
    );
}

/** DMs with no DM open: the newest to pick up again; with none, the space's people to start one with (New message), or
 *  the way to invite someone where no one else is here. */
export function DmsEmpty({
    dms,
    others,
    user,
    spaceName,
    myName,
    online,
    onOpen,
    onStart,
    onInvite,
}: {
    dms: DmRow[];
    /** The space's people with no DM yet. */
    others: ChannelMember[];
    user: AccountMenuUser;
    spaceName: string;
    myName: (author: ChannelAuthor) => boolean;
    online: (person: ChannelMember) => boolean;
    onOpen: (channelId: string) => void;
    onStart: (person: ChannelMember) => void;
    onInvite: (() => void) | null;
}) {
    const newMessage = others.length ? (
        <DropdownMenu>
            <DropdownMenuTrigger className={dms.length ? BUTTON_SECONDARY : BUTTON_PRIMARY}>
                <MessagesSquare className="h-4 w-4" strokeWidth={1.75} />
                New message
            </DropdownMenuTrigger>
            <DropdownMenuContent align={dms.length ? 'end' : 'center'} sideOffset={6} className="max-h-[320px] min-w-[240px] overflow-y-auto rounded-xl p-1">
                {others.map((person) => (
                    <DropdownMenuItem key={person.id} onSelect={() => onStart(person)} className="gap-2.5 rounded-lg px-2.5 py-2 text-[14px]">
                        <Face person={person} user={user} online={online(person)} size={28} />
                        <span className="min-w-0 flex-1 truncate">{person.name}</span>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    ) : null;
    const invite = onInvite ? (
        <button type="button" onClick={onInvite} className={others.length ? BUTTON_SECONDARY : BUTTON_PRIMARY}>
            <UserPlus className="h-4 w-4" strokeWidth={1.75} />
            Invite people
        </button>
    ) : null;
    if (dms.length)
        return (
            <Pick testId="dms-empty" title="Direct messages" line={newMessage ? 'Pick one up again, or start a new one.' : 'Pick one up again.'} action={newMessage}>
                {[...dms]
                    .sort((a, b) => byNewest(a.channel, b.channel))
                    .slice(0, RECENT_DMS)
                    .map(({ channel, person }) => (
                        <Tile
                            key={channel.id}
                            mark={<Face person={person} user={user} online={online(person)} size={40} />}
                            title={person.name}
                            detail={lastLine(channel, myName)}
                            label={`Your messages with ${person.name}`}
                            trailing={channel.unread > 0 ? <Count n={channel.unread} /> : undefined}
                            onOpen={() => onOpen(channel.id)}
                            testId={`dm-tile-${channel.id}`}
                            className={tile}
                        />
                    ))}
            </Pick>
        );
    if (others.length)
        return (
            <WorkNotice testId="dms-empty" mark={<Facepile members={others.slice(0, 3)} user={user} size={40} />} title="No messages yet" body={`Message someone in ${spaceName}. Only the two of you see it.`}>
                {newMessage}
                {invite}
            </WorkNotice>
        );
    return (
        <WorkNotice
            testId="dms-empty"
            mark={
                <span className="grid h-12 w-12 place-items-center rounded-full bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
                    <MessagesSquare className="h-6 w-6 text-foreground/70" strokeWidth={1.75} />
                </span>
            }
            title="No one else is here yet"
            body={onInvite ? `Invite people to ${spaceName} and message them here.` : `Once people join ${spaceName}, you can message them here.`}
        >
            {invite}
        </WorkNotice>
    );
}

/** Home with no channel open but channels to open (a link to one that's gone): them, open ones first. */
export function HomeEmpty({ channels, spaceName, onOpen, onNewChannel }: { channels: Channel[]; spaceName: string; onOpen: (channelId: string) => void; onNewChannel: (() => void) | null }) {
    const ordered = [...channels.filter((c) => c.status !== 'closed'), ...channels.filter((c) => c.status === 'closed')];
    return (
        <Pick
            testId="home-empty"
            title={spaceName}
            line="Pick a channel to open."
            action={
                onNewChannel && (
                    <button type="button" onClick={onNewChannel} className={BUTTON_SECONDARY}>
                        <Plus className="h-4 w-4" strokeWidth={1.75} />
                        Start a channel
                    </button>
                )
            }
        >
            {ordered.map((c) => {
                const Mark = c.status === 'closed' ? Lock : Hash;
                return (
                    <Tile
                        key={c.id}
                        mark={
                            <span className={ROUND_MARK}>
                                <Mark className="h-[18px] w-[18px] text-foreground/75" strokeWidth={1.75} />
                            </span>
                        }
                        title={c.name}
                        detail={c.topic || `${c.members.length} ${c.members.length === 1 ? 'member' : 'members'}`}
                        label={`Open #${c.name}`}
                        trailing={c.status !== 'closed' && c.unread > 0 ? <Count n={c.unread} /> : undefined}
                        onOpen={() => onOpen(c.id)}
                        className={tile}
                    />
                );
            })}
        </Pick>
    );
}
