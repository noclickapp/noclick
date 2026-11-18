// A right sheet for a child object; the list stays behind it, dimmed. It is
// the page's own surface (near-black in dark, white in light), headed like a
// page: what kind of object, its name in the brand face, then its status and
// id. `⤢` opens the same object as a page. Footer actions stay clear of the
// bottom-right corner (the support chat bubble).
import { useRef, type ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Maximize2, X } from 'lucide-react';
import { Link } from 'react-router';
import { cn } from '@/ui/utils';
import { HAIRLINE } from '@/ui/primitives';
import { IdChip } from './IdChip';
import { READABLE_PLACEHOLDERS, SHEET_EDGE, SHEET_SURFACE } from './tokens';

export { SHEET_SURFACE };

const ICON_BUTTON =
    'inline-flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

export function Drawer({
    open,
    onOpenChange,
    kind,
    id,
    title,
    status,
    expandHref,
    wide = false,
    children,
    footer,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** The kind label (`agent.message`, `Human request`). */
    kind: ReactNode;
    id?: string;
    title?: ReactNode;
    /** The header carries the status; nothing below repeats it. */
    status?: ReactNode;
    expandHref?: string;
    /** Room for an object with many views (an app's tabs). */
    wide?: boolean;
    children: ReactNode;
    footer?: ReactNode;
}) {
    const sheet = useRef<HTMLDivElement>(null);
    return (
        <Dialog.Root open={open} onOpenChange={onOpenChange}>
            <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 z-[70] bg-foreground/[0.08] data-[state=open]:animate-in data-[state=open]:fade-in-0 dark:bg-background/60" />
                <Dialog.Content
                    ref={sheet}
                    // The sheet itself takes focus, so opening it rings no button in its header.
                    onOpenAutoFocus={(e) => {
                        e.preventDefault();
                        sheet.current?.focus();
                    }}
                    className={cn(
                        'fixed inset-y-0 right-0 z-[70] flex flex-col border-l text-foreground shadow-lg focus:outline-none data-[state=open]:animate-in data-[state=open]:slide-in-from-right',
                        wide ? 'w-[min(880px,100vw)]' : 'w-[min(720px,100vw)]',
                        SHEET_SURFACE,
                        SHEET_EDGE,
                        READABLE_PLACEHOLDERS
                    )}
                >
                    <div className="flex items-start justify-between gap-3 px-5 pb-2 pt-5 sm:px-7 sm:pt-6">
                        <div className="flex min-w-0 flex-col gap-1">
                            <Dialog.Title className="m-0 text-[13px] font-normal text-muted-foreground">{kind}</Dialog.Title>
                            {title && <div className="min-w-0 break-words font-brand text-[22px] font-medium leading-tight tracking-[-0.02em] text-foreground">{title}</div>}
                            {(status || id) && (
                                <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                                    {status}
                                    {id && <IdChip id={id} full />}
                                </div>
                            )}
                            <Dialog.Description className="sr-only">Details</Dialog.Description>
                        </div>
                        <div className="-mr-2 -mt-1 flex shrink-0 items-center gap-1">
                            {expandHref && (
                                <Link to={expandHref} aria-label="Open as a page" title="Open as a page" className={ICON_BUTTON}>
                                    <Maximize2 className="h-3.5 w-3.5" />
                                </Link>
                            )}
                            <Dialog.Close aria-label="Close" className={ICON_BUTTON}>
                                <X className="h-4 w-4" />
                            </Dialog.Close>
                        </div>
                    </div>
                    <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-6 pt-4 text-sm sm:px-7">{children}</div>
                    {footer && <div className={cn('flex flex-wrap items-center gap-2 border-t px-5 py-3 pr-20 sm:px-7 sm:pr-20', HAIRLINE)}>{footer}</div>}
                </Dialog.Content>
            </Dialog.Portal>
        </Dialog.Root>
    );
}
