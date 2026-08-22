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
            className={cn('h-1 w-full overflow-hidden rounded-full bg-foreground/[0.08]', className)}
        >
            <div
                className={cn(
                    'h-full rounded-full bg-blue-600 dark:bg-blue-400 transition-[width] duration-150 ease-out',
                    barClassName,
                )}
                style={{ width: `${pct}%` }}
            />
        </div>
    );
}
