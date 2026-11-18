// A page's head, the one every page draws (the shell's pages, Settings' sections, Work's): its title and the line under
// it across the page, its actions beside them where the page is wide enough and on a row of their own under them where
// it isn't (a phone), so the line is never squeezed into a column beside the buttons. Judged on the width it's given.
import type { ReactNode } from 'react';
import { cn } from '@/ui/utils';
import { PAGE_TITLE } from '@/ui/titles';

export function PageHead({
    title,
    line,
    actions,
    lead,
    editor,
    actionsAt = 'top',
    level = 1,
    children,
    className,
}: {
    /** Left out where something else names the page (a phone's top bar). */
    title?: ReactNode;
    line?: ReactNode;
    actions?: ReactNode;
    /** A mark before the title. */
    lead?: ReactNode;
    /** In the title's place while it's renamed. */
    editor?: ReactNode;
    /** Beside the title's first line, or level with the line under it. */
    actionsAt?: 'top' | 'bottom';
    /** The title's heading level: a section within a page is a 2. */
    level?: 1 | 2;
    /** Under the line. */
    children?: ReactNode;
    className?: string;
}) {
    const Title = level === 1 ? 'h1' : 'h2';
    return (
        <div className={cn('@container', className)}>
            <header className={cn('flex flex-col gap-4 @2xl:flex-row @2xl:gap-6', actionsAt === 'top' ? '@2xl:items-start' : '@2xl:items-end')}>
                <div className="flex min-w-0 items-start gap-4 @2xl:flex-1">
                    {lead}
                    <div className="min-w-0 flex-1">
                        {editor ?? (title != null && <Title className={cn(PAGE_TITLE, 'break-words')}>{title}</Title>)}
                        {line && <p className={cn('max-w-[640px] text-[14px] leading-snug text-muted-foreground', (editor || title != null) && 'mt-1')}>{line}</p>}
                        {children}
                    </div>
                </div>
                {actions && <div className={cn('flex flex-wrap items-start gap-2 @2xl:shrink-0 @2xl:justify-end', actionsAt === 'top' && '@2xl:pt-1')}>{actions}</div>}
            </header>
        </div>
    );
}
