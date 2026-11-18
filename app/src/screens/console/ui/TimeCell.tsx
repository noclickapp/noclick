import { cn } from '@/ui/utils';
import { formatAbsolute, formatLogTime, formatRelative, formatTimeTooltip } from '@/screens/console/lib/format';
import { useConsole } from '@/screens/console/hooks/useConsole';

export type TimeTier = 'relative' | 'absolute' | 'log';

/** A time in one of the three tiers, with UTC and local on hover. */
export function TimeCell({ value, tier = 'relative', className, empty = '—' }: { value: Date | string | null | undefined; tier?: TimeTier; className?: string; empty?: string }) {
    const { now } = useConsole();
    if (value == null || value === '') return <span className={cn('text-muted-foreground', className)}>{empty}</span>;
    const text = tier === 'absolute' ? formatAbsolute(value) : tier === 'log' ? formatLogTime(value) : formatRelative(value, now());
    return (
        <time
            dateTime={value instanceof Date ? value.toISOString() : value}
            title={formatTimeTooltip(value)}
            className={cn('whitespace-nowrap tabular-nums', tier === 'log' && 'font-mono text-[12px]', className)}
        >
            {text}
        </time>
    );
}
