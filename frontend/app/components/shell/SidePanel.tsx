// A panel that slides over the right edge of a page for a secondary view
// (the coordinator's memories), keeping the page in place behind it. Its title
// is the pages' serif, so it reads as a page of its own.
import type { ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '~/lib/utils';
import { PAGE_TITLE } from './titles';

export function SidePanel({
    open,
    onOpenChange,
    title,
    description,
    children,
    className,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    title: string;
    description?: string;
    children: ReactNode;
    className?: string;
}) {
    return (
        <Dialog.Root open={open} onOpenChange={onOpenChange}>
            <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 z-[60] bg-black/20 data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 dark:bg-black/50" />
                <Dialog.Content
                    className={cn(
                        'fixed inset-y-0 right-0 z-[70] flex w-full max-w-[560px] flex-col border-l border-border bg-background shadow-[0_0_40px_-12px_rgba(0,0,0,0.3)] outline-none duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right dark:border-foreground/[0.08]',
                        className
                    )}
                >
                    <header className="flex shrink-0 items-start gap-3 px-6 pb-6 pt-7">
                        <div className="min-w-0 flex-1">
                            <Dialog.Title className={cn(PAGE_TITLE, 'm-0')}>{title}</Dialog.Title>
                            {description ? (
                                <Dialog.Description className="m-0 mt-1.5 text-balance text-[14px] leading-snug text-muted-foreground">{description}</Dialog.Description>
                            ) : (
                                <Dialog.Description className="sr-only">{title}</Dialog.Description>
                            )}
                        </div>
                        <Dialog.Close
                            aria-label="Close"
                            className="-mr-1.5 -mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                            <X className="h-[18px] w-[18px]" />
                        </Dialog.Close>
                    </header>
                    <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-8 scrollbar-subtle">{children}</div>
                </Dialog.Content>
            </Dialog.Portal>
        </Dialog.Root>
    );
}
