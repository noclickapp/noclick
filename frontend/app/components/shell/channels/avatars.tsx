// Who is in a channel, drawn: an agent is a monogram in its own colour (the
// colour its @-mentions read in too), you are your account avatar, and anyone
// else is their initial on a quiet disc.
import { AccountAvatar, type AccountMenuUser } from '~/components/nav/AccountMenu';
import { cn } from '~/lib/utils';
import { YOU_ID } from './model';
import type { AgentHue, ChannelMember } from './types';

const AVATAR_HUE: Record<AgentHue, string> = {
    indigo: 'bg-indigo-500/15 text-indigo-700 dark:bg-indigo-400/20 dark:text-indigo-200',
    violet: 'bg-violet-500/15 text-violet-700 dark:bg-violet-400/20 dark:text-violet-200',
    teal: 'bg-teal-500/15 text-teal-700 dark:bg-teal-400/20 dark:text-teal-200',
    sky: 'bg-sky-500/15 text-sky-700 dark:bg-sky-400/20 dark:text-sky-200',
    emerald: 'bg-emerald-500/15 text-emerald-700 dark:bg-emerald-400/20 dark:text-emerald-200',
    rose: 'bg-rose-500/15 text-rose-700 dark:bg-rose-400/20 dark:text-rose-200',
    orange: 'bg-orange-500/15 text-orange-700 dark:bg-orange-400/20 dark:text-orange-200',
};

export const MENTION_HUE: Record<AgentHue, string> = {
    indigo: 'text-indigo-600 dark:text-indigo-300',
    violet: 'text-violet-600 dark:text-violet-300',
    teal: 'text-teal-700 dark:text-teal-300',
    sky: 'text-sky-700 dark:text-sky-300',
    emerald: 'text-emerald-700 dark:text-emerald-300',
    rose: 'text-rose-600 dark:text-rose-300',
    orange: 'text-orange-700 dark:text-orange-300',
};

const SIZE = {
    16: 'h-4 w-4 text-[9px]',
    20: 'h-5 w-5 text-[10px]',
    24: 'h-6 w-6 text-[11px]',
    28: 'h-7 w-7 text-[12px]',
    32: 'h-8 w-8 text-[13px]',
} as const;
export type AvatarSize = keyof typeof SIZE;

export function MemberAvatar({ member, user, size = 32, className }: { member: ChannelMember; user: AccountMenuUser; size?: AvatarSize; className?: string }) {
    if (member.id === YOU_ID) return <AccountAvatar user={user} className={cn(SIZE[size], 'shrink-0', className)} />;
    return (
        <span
            aria-hidden
            className={cn(
                'inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold leading-none',
                SIZE[size],
                member.kind === 'agent' ? AVATAR_HUE[member.hue ?? 'indigo'] : 'bg-foreground/[0.1] text-foreground/80',
                className
            )}
        >
            {member.name.charAt(0)}
        </span>
    );
}

/** Overlapping avatars; the ring matches the surface they sit on. */
export function Facepile({ members, user, size = 20, ring = 'ring-background' }: { members: ChannelMember[]; user: AccountMenuUser; size?: AvatarSize; ring?: string }) {
    return (
        <span className="flex items-center -space-x-1">
            {members.map((m) => (
                <MemberAvatar key={m.id} member={m} user={user} size={size} className={cn('ring-2', ring)} />
            ))}
        </span>
    );
}
