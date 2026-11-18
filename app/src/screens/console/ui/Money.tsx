import { cn } from '@/ui/utils';
import { formatMoney, formatMoneyFull } from '@/screens/console/lib/format';

/** Dollars: two decimals (full precision on hover, or `full`), "Unknown" for null. */
export function Money({ usd, full = false, className }: { usd: number | null | undefined; full?: boolean; className?: string }) {
    const unknown = usd == null;
    return (
        <span className={cn('whitespace-nowrap tabular-nums', unknown && 'text-muted-foreground', className)} title={unknown ? undefined : formatMoneyFull(usd)}>
            {full ? formatMoneyFull(usd) : formatMoney(usd)}
        </span>
    );
}
