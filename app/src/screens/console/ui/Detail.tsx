// The pieces of the one anatomy detail pages share: an agent's page reads in one
// column (`DETAIL_PAGE`: Now, Recent runs, Uses, Code, then Details), a user's
// still sets its facts beside the main column (`DetailLayout`). Below lg the
// aside follows the main column.
import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { cn } from '@/ui/utils';
import { HAIRLINE } from '@/ui/primitives';

/** A detail page's width: one readable column, header included. */
export const DETAIL_PAGE = 'max-w-4xl';

export function DetailLayout({ main, aside }: { main: ReactNode; aside: ReactNode }) {
    return (
        <div className="grid grid-cols-1 gap-x-12 gap-y-10 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="min-w-0">{main}</div>
            <aside className="flex min-w-0 flex-col gap-8">{aside}</aside>
        </div>
    );
}

/** An aside block: a small heading, an optional action, then its content. */
export function AsideSection({ title, action, children, label }: { title: string; action?: ReactNode; children: ReactNode; label?: string }) {
    return (
        <section aria-label={label ?? title} className={cn('border-t pt-4 first:border-t-0 first:pt-0 lg:first:border-t lg:first:pt-4', HAIRLINE)}>
            <div className="mb-2.5 flex min-h-6 items-center justify-between gap-2">
                <h2 className="m-0 text-[13px] font-semibold text-foreground">{title}</h2>
                {action}
            </div>
            {children}
        </section>
    );
}

/** What's set once, folded under one heading until asked for. */
export function Disclosure({ title, hint, children, className }: { title: string; hint?: string; children: ReactNode; className?: string }) {
    return (
        <details className={cn('group', className)}>
            <summary className="flex cursor-pointer list-none items-baseline gap-2 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                <ChevronRight aria-hidden className="h-4 w-4 shrink-0 self-center text-muted-foreground transition-transform group-open:rotate-90" />
                <span className="text-[16px] font-semibold tracking-[-0.01em] text-foreground">{title}</span>
                {hint && <span className="min-w-0 truncate text-[13px] text-muted-foreground">{hint}</span>}
            </summary>
            <div className="mt-5 sm:pl-6">{children}</div>
        </details>
    );
}

export function Facts({ children, className }: { children: ReactNode; className?: string }) {
    return <dl className={cn('m-0 flex flex-col', className)}>{children}</dl>;
}

/** One fact: a muted label over its value (the aside is too narrow for two columns of long values). */
export function Fact({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
    return (
        <div className={cn('flex min-w-0 flex-col gap-0.5 py-1.5', className)}>
            <dt className="text-[12px] text-muted-foreground">{label}</dt>
            <dd className="m-0 min-w-0 break-words text-[13px] text-foreground">{children}</dd>
        </div>
    );
}
