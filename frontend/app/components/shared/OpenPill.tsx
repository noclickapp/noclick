// The "Open ↗" pill over a preview's top-right corner: a template's preview, a canvas drawn in the chat.
import { ArrowUpRight } from 'lucide-react';
import { cn } from '~/lib/utils';

export function OpenPill({ label = 'Open', onClick, className }: { label?: string; onClick: () => void; className?: string }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                'absolute right-4 top-4 z-10 inline-flex h-9 items-center gap-1.5 rounded-full bg-foreground/[0.09] px-4 text-[13px] font-medium text-foreground ring-1 ring-inset ring-foreground/10 backdrop-blur-xl transition-colors hover:bg-foreground/[0.15]',
                className,
            )}
        >
            {label}
            <ArrowUpRight className="h-3.5 w-3.5 text-foreground/70" strokeWidth={2.25} />
        </button>
    );
}
