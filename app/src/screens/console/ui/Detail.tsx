// The pieces detail pages share. An app's and an agent's pages read in one anatomy (`ThingPage`): what's wrong with it
// first, then on a wide screen two columns, what happened lately and what it uses on the left and its spend
// (`MonthSpend`), the facts set once and its code on the right; a phone reads them in one column, its spend right after
// what's wrong. A user's page still sets its facts beside the main column (`DetailLayout`).
import type { ReactNode } from 'react';
import { cn } from '@/ui/utils';
import { HAIRLINE } from '@/ui/primitives';
import { CapMeter } from './CapMeter';

export function DetailLayout({ main, aside }: { main: ReactNode; aside: ReactNode }) {
    return (
        <div className="grid grid-cols-1 gap-x-12 gap-y-10 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="min-w-0">{main}</div>
            <aside className="flex min-w-0 flex-col gap-8">{aside}</aside>
        </div>
    );
}

/**
 * A big thing's page body. Each column is a wrapper that only lays out on a wide screen (`contents` below it), so a
 * phone orders the four parts on its own: what's wrong, the spend, what happened lately, the facts and code.
 */
export function ThingPage({ problem, spend, main, aside }: { problem?: ReactNode; spend: ReactNode; main: ReactNode; aside: ReactNode }) {
    return (
        <div className="flex flex-col gap-10 xl:flex-row xl:items-start xl:gap-12">
            <div className="contents xl:flex xl:min-w-0 xl:flex-1 xl:flex-col xl:gap-10">
                {problem && <div className="order-1 min-w-0">{problem}</div>}
                <div className="order-3 min-w-0">{main}</div>
            </div>
            <div className="contents xl:flex xl:w-72 xl:shrink-0 xl:flex-col xl:gap-10">
                <div className="order-2 min-w-0">{spend}</div>
                <div className="order-4 flex min-w-0 flex-col gap-8">{aside}</div>
            </div>
        </div>
    );
}

/** What it cost this month: the figure large, against its cap where it has one, the action that changes the cap beside
 *  the label, and what the figure is made of under it. */
export function MonthSpend({ spent, cap, action, children }: { spent: number | null | undefined; cap: number | null | undefined; action?: ReactNode; children?: ReactNode }) {
    return (
        <section aria-label="This month" className="flex flex-col gap-2">
            <div className="flex min-h-7 items-center justify-between gap-2">
                <h2 className="m-0 text-[13px] font-normal text-muted-foreground">This month</h2>
                {action}
            </div>
            <CapMeter spent={spent} cap={cap} large className="w-full" />
            {children}
        </section>
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

export function Facts({ children, className }: { children: ReactNode; className?: string }) {
    return <dl className={cn('m-0 flex flex-col', className)}>{children}</dl>;
}

/** One fact: a muted label over its value, or (`row`, a page's aside) beside it, as the facts set once read. */
export function Fact({ label, children, className, row = false }: { label: string; children: ReactNode; className?: string; row?: boolean }) {
    return (
        <div className={cn(row ? 'grid grid-cols-[6.5rem_minmax(0,1fr)] items-baseline gap-3 py-1.5' : 'flex min-w-0 flex-col gap-0.5 py-1.5', className)}>
            <dt className="text-[12px] text-muted-foreground">{label}</dt>
            <dd className="m-0 min-w-0 break-words text-[13px] text-foreground">{children}</dd>
        </div>
    );
}
