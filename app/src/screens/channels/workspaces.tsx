// A workspace (a space in Work) as its tile: its uploaded logo, else its
// initials on a tile cut from the theme.
import { cn } from '@/ui/utils';
import { initialsFor } from './model';
import type { ChannelWorkspace } from './types';

// One letter sets larger than two, so "L" and "HH" fill their tiles alike.
const SIZE = {
    28: { box: 'h-7 w-7 rounded-lg', one: 'text-[14px]', two: 'text-[11.5px]' },
    40: { box: 'h-10 w-10 rounded-xl', one: 'text-[19px]', two: 'text-[15.5px]' },
    48: { box: 'h-12 w-12 rounded-[14px]', one: 'text-[23px]', two: 'text-[18.5px]' },
} as const;

export function WorkspaceTile({ workspace, size = 40, className }: { workspace: Pick<ChannelWorkspace, 'name' | 'logoUrl'>; size?: keyof typeof SIZE; className?: string }) {
    const { box, one, two } = SIZE[size];
    if (workspace.logoUrl) {
        return (
            <span aria-hidden className={cn('relative block shrink-0 overflow-hidden bg-card', box, className)}>
                <img src={workspace.logoUrl} alt="" draggable={false} className="h-full w-full object-cover" />
                {/* A hairline over the image keeps a dark logo's edge on a dark rail. */}
                <span className="pointer-events-none absolute inset-0 rounded-[inherit] ring-1 ring-inset ring-foreground/[0.1]" />
            </span>
        );
    }
    const initials = initialsFor(workspace.name);
    return (
        <span
            aria-hidden
            className={cn(
                'grid shrink-0 select-none place-items-center font-brand font-semibold leading-none text-foreground',
                'bg-card shadow-[0_1px_2px_rgba(0,0,0,0.06)] ring-1 ring-inset ring-border',
                'dark:bg-foreground/[0.1] dark:text-foreground/90 dark:shadow-[inset_0_1px_0_hsl(var(--foreground)/0.14)] dark:ring-foreground/[0.08]',
                box,
                initials.length > 1 ? cn(two, 'tracking-[-0.03em]') : one,
                className
            )}
        >
            {initials}
        </span>
    );
}
