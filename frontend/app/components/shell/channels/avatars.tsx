// Who is in a channel, drawn: an agent is its letters on a disc of its own
// colour (the colour its @-mentions read in too), you are your account avatar,
// and anyone else is their initial on a quiet disc.
import { AccountAvatar, type AccountMenuUser } from '~/components/nav/AccountMenu';
import { cn } from '~/lib/utils';
import { AGENT_HUES, YOU_ID } from './model';
import type { AgentHue, ChannelMember } from './types';

// The discs' fills, one step per theme: every pair passes the data-viz palette validator with all pairs compared
// (light on #f9f9fa: colour-blind ΔE ≥ 11.6, normal ≥ 18.5; dark on #000: ≥ 9.2 and ≥ 17.2). Light pink and amber sit
// under 3:1 against the page, so a disc never stands alone: its letters and the agent's name go with it. Each fill
// takes the ink its letters read best in (WCAG ≥ 4.2:1).
const AVATAR_HUE: Record<AgentHue, string> = {
    sky: 'bg-sky-700 text-white dark:bg-sky-600',
    violet: 'bg-violet-500 text-white dark:bg-violet-600',
    pink: 'bg-pink-400 text-neutral-900 dark:bg-pink-600 dark:text-white',
    amber: 'bg-amber-500 text-neutral-900 dark:bg-amber-600',
    emerald: 'bg-emerald-600 text-neutral-900 dark:bg-emerald-700 dark:text-white',
};

// The same hues as text, at steps that read on the page (WCAG ≥ 4.7:1 on both themes' pages and cards).
export const MENTION_HUE: Record<AgentHue, string> = {
    sky: 'text-sky-700 dark:text-sky-400',
    violet: 'text-violet-600 dark:text-violet-400',
    pink: 'text-pink-700 dark:text-pink-400',
    amber: 'text-amber-700 dark:text-amber-400',
    emerald: 'text-emerald-700 dark:text-emerald-400',
};

const SIZE = {
    16: 'h-4 w-4 text-[9px]',
    20: 'h-5 w-5 text-[10px]',
    24: 'h-6 w-6 text-[11px]',
    28: 'h-7 w-7 text-[12px]',
    32: 'h-8 w-8 text-[13px]',
} as const;
export type AvatarSize = keyof typeof SIZE;

/** `user` draws you; a card with no one signed in to show (the chat's agent and channel cards) draws agents alone. */
export function MemberAvatar({ member, user, size = 32, className }: { member: ChannelMember; user?: AccountMenuUser; size?: AvatarSize; className?: string }) {
    if (member.id === YOU_ID && user) return <AccountAvatar user={user} className={cn(SIZE[size], 'shrink-0', className)} />;
    return (
        <span
            aria-hidden
            className={cn(
                'inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold leading-none',
                SIZE[size],
                member.kind === 'agent' ? AVATAR_HUE[member.hue ?? AGENT_HUES[0]] : 'bg-foreground/[0.1] text-foreground/80',
                (member.initials?.length ?? 0) > 1 && 'tracking-[-0.04em]',
                className
            )}
        >
            {member.initials ?? member.name.charAt(0)}
        </span>
    );
}

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
