// The `⋯` menu on a row or a detail header: a round icon button, a list of
// actions (a destructive one in red, set apart), and why a disabled one is.
import { useId } from 'react';
import { MoreHorizontal } from 'lucide-react';
import { toast } from 'sonner';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { cn } from '@/ui/utils';

export interface MenuItem {
    label: string;
    onSelect: () => void;
    danger?: boolean;
    /** Separate this item from the ones above it. */
    separated?: boolean;
    disabled?: boolean;
    /** Why a disabled item is disabled, shown under the items (a disabled item takes no hover, so no tooltip). */
    reason?: string;
}

/** A menu's "Copy ID". */
export async function copyId(id: string) {
    try {
        await navigator.clipboard.writeText(id);
        toast('ID copied');
    } catch {
        toast.error("Couldn't copy the ID.");
    }
}

export function MoreMenu({ label, items, className }: { label: string; items: readonly MenuItem[]; className?: string }) {
    const noteId = useId();
    const reasons = [...new Set(items.flatMap((i) => (i.disabled && i.reason ? [i.reason] : [])))];
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label={label}
                className={cn(
                    'inline-flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    className
                )}
            >
                <MoreHorizontal className="h-4 w-4" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[11rem] max-w-[16rem]">
                {items.map((item) => (
                    <span key={item.label}>
                        {item.separated && <DropdownMenuSeparator />}
                        <DropdownMenuItem
                            disabled={item.disabled}
                            aria-describedby={item.disabled && item.reason ? noteId : undefined}
                            onSelect={item.onSelect}
                            className={cn('cursor-pointer text-[13px]', item.danger && 'text-red-600 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400')}
                        >
                            {item.label}
                        </DropdownMenuItem>
                    </span>
                ))}
                {reasons.length > 0 && (
                    <>
                        <DropdownMenuSeparator />
                        <p id={noteId} className="m-0 px-2 py-1.5 text-[12px] text-muted-foreground">
                            {reasons.join(' ')}
                        </p>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
