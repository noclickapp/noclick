// Who is in a channel, drawn: an agent is NoClick's mascot dressed for its job on a disc of its own colour (the colour
// its @-mentions read in too), you are your account avatar, NoClick is its mark, and anyone else is their initial on a
// quiet disc.
import { createContext, useContext, useMemo } from 'react';
import { AccountAvatar, type AccountMenuUser } from '~/components/nav/AccountMenu';
import { LogoMark, MARK_IN_A_SHAPE } from '~/components/shared/LogoMark';
import { cn } from '~/lib/utils';
import { AgentMascot, type MascotState } from './mascot/AgentMascot';
import { propsFor } from './mascot/kit';
import { AGENT_HUES, agentKey, YOU_ID } from './model';
import type { AgentHue, ChannelMember } from './types';

/** A mention's soft tint behind its hue (MENTION_HUE). */
export const MENTION_TINT: Record<AgentHue, string> = {
    sky: 'bg-sky-500/[0.14]',
    violet: 'bg-violet-500/[0.14]',
    pink: 'bg-pink-500/[0.14]',
    fuchsia: 'bg-fuchsia-500/[0.14]',
    emerald: 'bg-emerald-500/[0.14]',
    blue: 'bg-blue-500/[0.14]',
    purple: 'bg-purple-500/[0.14]',
    teal: 'bg-teal-500/[0.14]',
};

// The same hues as text, at steps that read on the page (WCAG ≥ 4.7:1 on both themes' pages and cards).
export const MENTION_HUE: Record<AgentHue, string> = {
    sky: 'text-sky-700 dark:text-sky-400',
    violet: 'text-violet-600 dark:text-violet-400',
    pink: 'text-pink-700 dark:text-pink-400',
    fuchsia: 'text-fuchsia-700 dark:text-fuchsia-400',
    emerald: 'text-emerald-700 dark:text-emerald-400',
    blue: 'text-blue-700 dark:text-blue-400',
    purple: 'text-purple-700 dark:text-purple-400',
    teal: 'text-teal-700 dark:text-teal-400',
};

const SIZE = {
    16: 'h-4 w-4 text-[9px]',
    20: 'h-5 w-5 text-[10px]',
    24: 'h-6 w-6 text-[11px]',
    28: 'h-7 w-7 text-[12px]',
    32: 'h-8 w-8 text-[13px]',
    40: 'h-10 w-10 text-[15px]',
    48: 'h-12 w-12 text-[17px]',
    80: 'h-20 w-20 text-[28px]',
} as const;
export type AvatarSize = keyof typeof SIZE;

/** Each agent's job as the account keeps it, by its `agentKey`: what dresses its mascot wherever it's drawn, so a
 *  surface that only knows its name (a channel's members) draws it as the agents list does. */
export const AgentRolesContext = createContext<ReadonlyMap<string, string>>(new Map());

/** `user` draws you; a card with no one signed in to show (the chat's agent and channel cards) draws agents alone.
 *  `state`: an agent's live state, its mascot's face and loop; without one it rests, still. `marks: false` leaves the
 *  state's marks off the mascot, where a ring round it already says the state. */
export function MemberAvatar({ member, user, size = 32, state, marks, className }: { member: ChannelMember; user?: AccountMenuUser; size?: AvatarSize; state?: MascotState; marks?: boolean; className?: string }) {
    if (member.id === YOU_ID && user) return <AccountAvatar user={user} className={cn(SIZE[size], 'shrink-0', className)} />;
    if (member.noclick)
        return (
            <span aria-hidden data-noclick-mark className={cn('inline-flex shrink-0 items-center justify-center rounded-full bg-foreground/[0.07]', SIZE[size], className)}>
                <LogoMark alt="" className={cn('h-1/2 w-1/2', MARK_IN_A_SHAPE)} />
            </span>
        );
    if (member.kind === 'agent') return <AgentFace member={member} size={size} state={state} marks={marks} className={className} />;
    return (
        <span
            aria-hidden
            className={cn(
                'inline-flex shrink-0 select-none items-center justify-center rounded-full bg-foreground/[0.1] font-semibold leading-none text-foreground/80',
                SIZE[size],
                (member.initials?.length ?? 0) > 1 && 'tracking-[-0.04em]',
                className
            )}
        >
            {member.initials ?? member.name.charAt(0)}
        </span>
    );
}

/** An agent's mascot, seeded by which agent it is and dressed by its name and job. */
function AgentFace({ member, size, state, marks, className }: { member: ChannelMember; size: AvatarSize; state?: MascotState; marks?: boolean; className?: string }) {
    const key = agentKey(member) ?? member.id;
    const role = useContext(AgentRolesContext).get(key) ?? member.role ?? '';
    const props = useMemo(() => propsFor(`${member.name} ${role}`), [member.name, role]);
    return <AgentMascot seed={key} hue={member.hue ?? AGENT_HUES[0]} props={props} state={state} size={size} marks={marks} className={cn(SIZE[size], className)} />;
}

/** The face a channel member's presence gives it: at work while it takes a turn; else it rests, still, since a
 *  channel knows nothing more of where it stands. */
export const presenceFace = (member: ChannelMember): MascotState | undefined => (member.busy ? 'working' : undefined);

/** Overlapping avatars; the ring matches the surface they sit on. */
export function Facepile({ members, user, size = 20, ring = 'ring-background' }: { members: ChannelMember[]; user?: AccountMenuUser; size?: AvatarSize; ring?: string }) {
    return (
        <span className="flex items-center -space-x-1">
            {members.map((m) => (
                <MemberAvatar key={m.id} member={m} user={user} size={size} className={cn('ring-2', ring)} />
            ))}
        </span>
    );
}
