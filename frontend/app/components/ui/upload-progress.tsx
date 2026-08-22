// Thin determinate progress bar for in-flight file uploads. Shared by every
// upload surface (interface blocks, NodeConfig widgets, workspace panels,
// chat attachments) so upload progress reads the same everywhere.

import { cn } from '~/lib/utils';

export function UploadProgressBar({
    fraction,
    className,
    barClassName,
}: {
    /** 0..1 */
    fraction: number;
    className?: string;
    /** Override the fill color (e.g. white on a dark image overlay). */
    barClassName?: string;
}) {
    const pct = Math.max(0, Math.min(100, Math.round(fraction * 100)));
    return (
        <div
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            // No w-full: block flow already fills, and in absolute placements an
            // explicit width would override the right inset and overflow the frame.
            className={cn('h-1 overflow-hidden rounded-full bg-foreground/[0.08]', className)}
        >
            <div
                className={cn(
                    'h-full rounded-full transition-[width] duration-150 ease-out',
                    // Full replacement, not a merge: twMerge can't drop the default's
                    // dark: variant for an unprefixed override like bg-white.
                    barClassName ?? 'bg-blue-600 dark:bg-blue-400',
                )}
                style={{ width: `${pct}%` }}
            />
        </div>
    );
}
