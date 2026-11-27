// What a drawer leads with and what it ends on. Every drawer reads in one order: what it's doing and what it cost
// (its status in the header; anything wrong with it in words, with its fix, as a `Problem`; its spend as `Spend`),
// then what happened lately (each drawer's own lists), and last the facts set once and its code, folded where they're
// long (`Folded`).
import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { CapMeter } from './CapMeter';

/** Something wrong with it, in words: what happened, what it means, and the button that fixes it where there is one. */
export function Problem({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
    return (
        <div role="status" className="flex flex-col gap-2.5 rounded-2xl bg-red-500/[0.07] px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <p className="m-0 text-[13px] font-medium text-red-600 dark:text-red-400">{title}</p>
                {children && <p className="m-0 text-[12px] leading-relaxed text-muted-foreground">{children}</p>}
            </div>
            {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
        </div>
    );
}

/**
 * What it cost: `$33.05 of $50` over a cap meter where it has a cap, the figure alone where it doesn't, or what's
 * given (`$1.44 a month`, `Included`). An action (change the budget) sits beside the label.
 */
export function Spend({ label = 'This month', spent, cap, action, children }: { label?: string; spent?: number | null; cap?: number | null; action?: ReactNode; children?: ReactNode }) {
    return (
        <div className="flex items-start gap-4 text-[13px]">
            <span className="flex shrink-0 items-center gap-2 leading-5 text-muted-foreground">
                {label}
                {action}
            </span>
            <span className="flex min-w-0 flex-1 justify-end text-right leading-5 text-foreground">{children ?? <CapMeter spent={spent} cap={cap} className={cap != null ? 'w-full' : undefined} />}</span>
        </div>
    );
}

/** A quiet summary beside the header's status: what a store holds (`12 keys · 3.1 KB`), or how something stands. */
export function HeaderNote({ children }: { children: ReactNode }) {
    return <span className="min-w-0 text-[13px] text-muted-foreground">{children}</span>;
}

/** The facts set once and the code, under one line that opens them (`Details: region, created, code`). */
export function Folded({ title, children, open = false }: { title: string; children: ReactNode; open?: boolean }) {
    return (
        <details className="group" open={open}>
            <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-sm text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90" />
                <span className="min-w-0 truncate">{title}</span>
            </summary>
            <div className="mt-4 flex flex-col gap-6">{children}</div>
        </details>
    );
}
