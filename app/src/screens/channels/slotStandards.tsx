// What stands in the channels layer's slots when nobody fills them (slots.ts).
import { cn } from '@/ui/utils';
import { AGENT_HUES, AVATAR_HUE, initialsFor } from './model';
import type { AgentFaceProps } from './slots';

/** An agent's initials on a disc of its own colour, white on it as a face is. */
export function InitialsFace({ member, className }: AgentFaceProps) {
    const letters = member.initials ?? initialsFor(member.name);
    return (
        <span
            aria-hidden
            data-agent-initials
            className={cn(
                'inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold leading-none text-white',
                letters.length > 1 && 'tracking-[-0.04em]',
                className
            )}
            style={{ backgroundColor: AVATAR_HUE[member.hue ?? AGENT_HUES[0]] }}
        >
            {letters}
        </span>
    );
}
