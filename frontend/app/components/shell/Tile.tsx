// The one tile the shell's grids are made of (apps, accounts, resource kinds): a
// mark, a name, one line under it, and a slot on the right for the one action
// or figure. A tile that goes somewhere is a link (`href`); one that acts is a
// control (`onOpen`).
import type { KeyboardEvent, ReactNode } from 'react';
import { Link } from 'react-router';
import { Skeleton } from '~/components/ui/skeleton';
import { cn } from '~/lib/utils';

export const TILE_GRID = 'grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3';

const TILE =
    'group flex min-w-0 cursor-pointer items-center gap-3 rounded-2xl border border-border bg-card px-3.5 py-3 text-left transition-colors hover:bg-foreground/[0.025] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-foreground/[0.08] dark:bg-foreground/[0.02] dark:hover:bg-foreground/[0.045]';

export function Tile({
    mark,
    title,
    badge,
    detail,
    wrapDetail = false,
    trailing,
    onOpen,
    href,
    label,
    testId,
    className,
}: {
    mark: ReactNode;
    title: string;
    /** Beside the name (a Preview pill). */
    badge?: ReactNode;
    detail?: ReactNode;
    /** Let the line under the name run to two lines rather than cut off (a sentence, not an email). */
    wrapDetail?: boolean;
    /** The tile's own action (Connect, Reconnect) or a quiet hint of where a click goes. A linked tile holds no control of its own. */
    trailing?: ReactNode;
    label: string;
    testId?: string;
    className?: string;
} & ({ onOpen: () => void; href?: never } | { href: string; onOpen?: never })) {
    const body = (
        <>
            {mark}
            <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-[14px] font-medium text-foreground">{title}</span>
                    {badge}
                </span>
                {detail ? <span className={cn('mt-0.5 block text-[12.5px] text-muted-foreground', wrapDetail ? 'line-clamp-2 text-balance' : 'truncate')}>{detail}</span> : null}
            </span>
            {trailing}
        </>
    );
    if (href !== undefined) {
        return (
            <Link to={href} aria-label={label} data-testid={testId} className={cn(TILE, className)}>
                {body}
            </Link>
        );
    }
    // A div, not a button: the trailing slot can hold a button of its own.
    const onKeyDown = (event: KeyboardEvent) => {
        if (event.target !== event.currentTarget || (event.key !== 'Enter' && event.key !== ' ')) return;
        event.preventDefault();
        onOpen?.();
    };
    return (
        <div role="button" tabIndex={0} aria-label={label} onClick={onOpen} onKeyDown={onKeyDown} data-testid={testId} className={cn(TILE, className)}>
            {body}
        </div>
    );
}

export function TileSkeletons({ count = 9 }: { count?: number }) {
    return (
        <div className={TILE_GRID}>
            {Array.from({ length: count }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 rounded-2xl border border-border px-3.5 py-3 dark:border-foreground/[0.08]">
                    <Skeleton className="h-10 w-10 rounded-xl" />
                    <div className="flex-1 space-y-1.5">
                        <Skeleton className={cn('h-3.5', i % 2 ? 'w-20' : 'w-28')} />
                        <Skeleton className="h-3 w-36" />
                    </div>
                </div>
            ))}
        </div>
    );
}
