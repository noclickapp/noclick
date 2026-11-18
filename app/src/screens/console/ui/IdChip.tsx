import { cn } from '@/ui/utils';
import { CopyButton } from './CopyButton';

/** An id: mono, whole, cut at its end only where its column runs out (never in
 *  the middle, so it reads the way it starts), copy on hover (always visible on
 *  touch widths) and the full value on hover. */
export function IdChip({ id, full = false, kind, className }: { id: string; full?: boolean; kind?: string; className?: string }) {
    const chip = (
        <span className={cn('group/id inline-flex min-w-0 max-w-full items-center gap-0.5 font-mono text-[12px] text-foreground/80', className)} title={id}>
            <span className={cn(full ? 'break-all' : 'truncate')}>{id}</span>
            <CopyButton value={id} label="Copy id" className="opacity-100 focus:opacity-100 md:opacity-0 md:group-hover/id:opacity-100" />
        </span>
    );
    if (!kind) return chip;
    return (
        <span className="inline-flex min-w-0 flex-col">
            <span className="text-[12px] font-medium text-muted-foreground">{kind}</span>
            {chip}
        </span>
    );
}
