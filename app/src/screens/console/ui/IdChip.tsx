import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { cn } from '@/ui/utils';
import { CopyButton } from './CopyButton';

/** An object's id where its name and status lead (a drawer's or a page's header): a "Copy ID" chip that copies it,
 *  never the 36 characters beside the status. The id itself shows on hover. */
export function CopyIdChip({ id, className }: { id: string; className?: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <button
            type="button"
            title={id}
            onClick={async () => {
                try {
                    await navigator.clipboard.writeText(id);
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1500);
                } catch (err) {
                    console.error('Copy failed', err);
                }
            }}
            className={cn(
                'inline-flex h-6 shrink-0 items-center gap-1 rounded-full bg-foreground/[0.06] px-2.5 text-[12px] font-medium text-foreground/75 transition-colors hover:bg-foreground/[0.1] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                className
            )}
        >
            {copied ? 'Copied' : 'Copy ID'}
            {copied ? <Check aria-hidden className="h-3 w-3" /> : <Copy aria-hidden className="h-3 w-3" />}
        </button>
    );
}

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
