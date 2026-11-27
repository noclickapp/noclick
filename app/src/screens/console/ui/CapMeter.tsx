import { Info } from 'lucide-react';
import { cn } from '@/ui/utils';
import { formatMoney, formatPercent } from '@/screens/console/lib/format';
import { Money } from './Money';

export const CAP_NOTE = 'Caps are checked before work starts, so spend can pass a cap by the cost of the last call.';

/** A cap in dollars: whole dollars without cents ("$50"), else to the cent. */
export function capLabel(cap: number): string {
    return Number.isInteger(cap) ? `$${cap.toLocaleString('en-US')}` : formatMoney(cap);
}

/**
 * The only cap bar: "$12.30 of $50" over ink, red at or past 100%. Past 100%
 * the fill runs to the end with an overflow tick and the percentage, since a
 * cap is checked before work starts. No cap → just the spend. `large` leads a
 * page's aside: the figure big and first, the bar under it.
 */
export function CapMeter({
    spent,
    cap,
    noCapLabel = false,
    large = false,
    className,
}: {
    spent: number | null | undefined;
    cap: number | null | undefined;
    noCapLabel?: boolean;
    large?: boolean;
    className?: string;
}) {
    const figure = large && 'text-[22px] font-semibold tracking-[-0.02em]';
    if (cap == null) {
        return (
            <span className={cn('inline-flex items-baseline gap-1.5', className)}>
                <Money usd={spent} className={cn(figure)} />
                {noCapLabel && <span className="text-[12px] text-muted-foreground">No cap</span>}
            </span>
        );
    }
    const ratio = spent == null ? null : cap > 0 ? spent / cap : spent > 0 ? Infinity : 0;
    const over = ratio !== null && ratio >= 1;
    const past = ratio !== null && ratio > 1;
    return (
        <span className={cn('inline-flex min-w-[7rem] flex-col gap-1', className)}>
            <span className={cn('inline-flex flex-wrap items-baseline gap-x-1 tabular-nums', large ? 'justify-start' : 'justify-end')}>
                <Money usd={spent} className={cn(figure, over && 'text-red-600 dark:text-red-400')} />
                <span className={cn('text-muted-foreground', large && 'text-[13px]')}>of {capLabel(cap)}</span>
                {past && Number.isFinite(ratio) && (
                    <span className="inline-flex items-center gap-0.5 text-[12px] font-medium text-red-600 dark:text-red-400" title={CAP_NOTE}>
                        {formatPercent(ratio as number)}
                        <Info className="h-3 w-3" aria-label={CAP_NOTE} />
                    </span>
                )}
            </span>
            <span
                role="meter"
                aria-valuemin={0}
                aria-valuemax={cap}
                aria-valuenow={spent ?? undefined}
                aria-label={spent == null ? 'Spend unknown' : `${formatMoney(spent)} of ${capLabel(cap)}`}
                className="relative h-1 w-full rounded-full bg-foreground/[0.08]"
            >
                {ratio !== null && (
                    <span
                        className={cn('absolute inset-y-0 left-0 rounded-full', over ? 'bg-red-600 dark:bg-red-400' : 'bg-foreground/55')}
                        style={{ width: `${Math.min(1, ratio) * 100}%` }}
                    />
                )}
                {past && <span aria-hidden className="absolute -right-1 -top-0.5 h-2 w-0.5 rounded-full bg-red-600 dark:bg-red-400" />}
            </span>
        </span>
    );
}
