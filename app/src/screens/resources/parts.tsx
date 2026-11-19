// What every platform item's body reads with: a list row, and a read's loading rows or its error.
import { Skeleton } from '@/ui/skeleton';
import { Surface } from './ui';
import { cn } from '@/ui/utils';
import { errorText } from '@/screens/console/pages/resources/shared';
import type { V1State } from '@/sdk/useV1';

export const ROW = 'flex items-center gap-3 border-b border-border px-4 py-3 last:border-0 dark:border-foreground/[0.06]';

/** A read's loading rows, or its error with a way to try again; null once it answered. */
export function Pending<T>({ read, rows = 3 }: { read: V1State<T>; rows?: number }) {
    if (read.error !== undefined && read.data === undefined) {
        return (
            <p role="alert" className="text-[13.5px] text-muted-foreground">
                {errorText(read.error)}{' '}
                <button type="button" onClick={() => void read.refresh()} className="font-medium text-foreground underline underline-offset-4">
                    Try again
                </button>
            </p>
        );
    }
    if (read.data !== undefined) return null;
    return (
        <Surface>
            {Array.from({ length: rows }, (_, i) => (
                <div key={i} className={ROW} aria-busy>
                    <Skeleton className={cn('h-3.5', i % 2 ? 'w-1/4' : 'w-1/3')} />
                </div>
            ))}
        </Surface>
    );
}
