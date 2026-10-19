// The app's dialog, which every popup that makes, renames, shares or deletes something is built from (and the
// developer console's `ConsoleDialog`): the page's own surface (white in light, near-black in dark, never a lighter
// grey) over a dimmed page, a header with an optional mark, the title in the brand face and one line under it, then
// the body and pill buttons with no rules between them. Focus goes back to whatever opened it.
import type { FormEvent, KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '~/lib/utils';
import { useReturnFocus } from '~/hooks/useReturnFocus';

const SIZES = { sm: 'max-w-[440px]', md: 'max-w-[580px]', lg: 'max-w-[780px]' } as const;

export const DIALOG_OVERLAY = 'fixed inset-0 z-[70] bg-foreground/[0.08] data-[state=open]:animate-in data-[state=open]:fade-in-0 dark:bg-background/60';

/** The tile a dialog's mark sits on. */
export const DIALOG_MARK = 'grid h-11 w-11 shrink-0 place-items-center rounded-[12px] bg-foreground/[0.06] text-foreground';
const MARK_TONES = { neutral: '', warning: 'bg-amber-500/10 text-amber-600 dark:text-amber-400', danger: 'bg-red-500/10 text-red-600 dark:text-red-400' } as const;

export interface ShellDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    title: ReactNode;
    description?: ReactNode;
    /** A mark beside the title (an icon on a tile), where one says what the dialog does. */
    mark?: ReactNode;
    /** False: the mark brings its own tile (an app's logo, a workspace's picture). */
    markTile?: boolean;
    tone?: keyof typeof MARK_TONES;
    children?: ReactNode;
    footer?: ReactNode;
    /** Makes the body and footer one form, so Enter and a `type="submit"` footer button submit it. */
    onSubmit?: (e: FormEvent<HTMLFormElement>) => void;
    size?: keyof typeof SIZES;
    /** False: no ✕, and Escape and outside clicks don't close it (reveal-once). */
    dismissible?: boolean;
    /** Drawn in place, open and not modal, so a design lab can lay several side by side. */
    inline?: boolean;
    /** Keys anywhere in the dialog, wherever focus sits in it (a list's ↑/↓). */
    onKeyDown?: (e: ReactKeyboardEvent<HTMLDivElement>) => void;
    className?: string;
    testId?: string;
}

export function ShellDialog({ open, onOpenChange, title, description, mark, markTile = true, tone = 'neutral', children, footer, onSubmit, size = 'sm', dismissible = true, inline = false, onKeyDown, className, testId }: ShellDialogProps) {
    const returnFocus = useReturnFocus();
    const hold = (e: Event) => {
        if (!dismissible) e.preventDefault();
    };
    // Radix hears Escape first (document, capture): an open combobox closes its own list instead.
    const escape = (e: KeyboardEvent) => {
        if (!dismissible || (e.target instanceof Element && e.target.closest('[role="combobox"][aria-expanded="true"]'))) e.preventDefault();
    };
    const body = (
        <>
            {children != null && <div className="min-h-0 flex-1 overflow-y-auto px-6 py-2 text-sm">{children}</div>}
            {footer && <div className="flex flex-wrap items-center justify-end gap-2 px-6 pb-6 pt-4">{footer}</div>}
        </>
    );
    const content = (
        <Dialog.Content
            {...returnFocus}
            // Drawn in place, it never takes focus from the page around it.
            onOpenAutoFocus={inline ? (e) => e.preventDefault() : returnFocus.onOpenAutoFocus}
            data-testid={testId}
            onEscapeKeyDown={escape}
            onKeyDown={onKeyDown}
            onPointerDownOutside={hold}
            onInteractOutside={hold}
            className={cn(
                'flex flex-col rounded-2xl border border-border bg-card text-foreground shadow-lg focus:outline-none dark:border-foreground/[0.12] dark:bg-sunken',
                inline ? 'relative w-full' : 'fixed left-1/2 top-1/2 z-[70] max-h-[calc(100dvh-32px)] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2',
                SIZES[size],
                className
            )}
        >
            <div className={cn('px-6 pt-6', children != null || footer ? 'pb-3' : 'pb-6', dismissible && 'pr-14')}>
                <div className="flex min-w-0 items-center gap-3.5">
                    {mark && (markTile ? <span className={cn(DIALOG_MARK, MARK_TONES[tone])}>{mark}</span> : mark)}
                    <div className="min-w-0">
                        <Dialog.Title className="m-0 font-brand text-[20px] font-medium leading-tight tracking-[-0.02em] text-foreground [text-wrap:balance]">{title}</Dialog.Title>
                        {description ? (
                            <Dialog.Description className="m-0 mt-1 text-[13px] leading-snug text-muted-foreground [text-wrap:balance]">{description}</Dialog.Description>
                        ) : (
                            <Dialog.Description className="sr-only">{typeof title === 'string' ? title : 'Dialog'}</Dialog.Description>
                        )}
                    </div>
                </div>
            </div>
            {onSubmit ? (
                <form onSubmit={onSubmit} className="flex min-h-0 flex-1 flex-col">
                    {body}
                </form>
            ) : (
                body
            )}
            {/* Last in order, so opening a dialog focuses its first field rather than ✕. */}
            {dismissible && (
                <Dialog.Close
                    className="absolute right-4 top-5 inline-flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label="Close"
                >
                    <X className="h-4 w-4" />
                </Dialog.Close>
            )}
        </Dialog.Content>
    );
    return (
        <Dialog.Root open={open} modal={!inline} onOpenChange={(next) => (dismissible || next ? onOpenChange(next) : undefined)}>
            {inline ? (
                content
            ) : (
                <Dialog.Portal>
                    <Dialog.Overlay className={DIALOG_OVERLAY} />
                    {content}
                </Dialog.Portal>
            )}
        </Dialog.Root>
    );
}
