// First-load skeleton for the Dashboard tab: the same greeting, ledger and card
// grid as the Hairline layout, drawn as pulsing placeholders so the page keeps
// its shape while `dashboard:overview` is in flight. It reads the layout's own
// rhythm tokens, card order and column spans, so it cannot drift from the real
// page. Only the first load shows it — refetches keep the previous data on screen.
import { Skeleton } from '~/components/ui/skeleton';
import { cn } from '~/lib/utils';
import { HAIRLINE, LAYOUT, ROWS, SURFACE } from '~/components/dashboard/primitives';
import { ORDER, SPANS } from '~/components/dashboard/variants';
import type { FocusId } from '~/components/dashboard/types';

/** What each card's body looks like while loading. */
const SHAPES: Record<FocusId, { rows: number; chart?: boolean; chips?: boolean }> = {
    attention: { rows: 4 },
    runs: { rows: 3, chart: true },
    agents: { rows: 3 },
    upcoming: { rows: 4 },
    files: { rows: 4 },
    credentials: { rows: 0, chips: true },
    triggers: { rows: 3 },
    credits: { rows: 2 },
    notifications: { rows: 3 },
};

function Row({ wide = false }: { wide?: boolean }) {
    return (
        <div className="flex items-center gap-3 py-2.5">
            <Skeleton className="h-5 w-5 shrink-0 rounded-full" />
            <div className="min-w-0 flex-1 space-y-1.5">
                <Skeleton className={cn('h-3', wide ? 'w-3/4' : 'w-1/2')} />
                <Skeleton className="h-2.5 w-1/3" />
            </div>
            <Skeleton className="h-2.5 w-12" />
        </div>
    );
}

function Card({ id }: { id: FocusId }) {
    const { rows, chart, chips } = SHAPES[id];
    return (
        <section className={cn(SURFACE, 'flex min-w-0 flex-col', LAYOUT.cardPad, SPANS.balanced[id])} data-card={id}>
            <div className="mb-3 flex items-center justify-between">
                <Skeleton className="h-2.5 w-20" />
                <Skeleton className="h-2.5 w-10" />
            </div>
            {chart && (
                <div className="mb-3 flex items-end gap-[2px]" style={{ height: 72 }}>
                    {[38, 30, 44, 52, 48, 16, 12, 56, 60, 50, 62, 58, 68, 30].map((h, i) => (
                        <Skeleton key={i} className="flex-1 rounded-t-[4px]" style={{ height: h, maxWidth: 24 }} />
                    ))}
                </div>
            )}
            {chips ? (
                <div className="flex flex-wrap gap-1.5">
                    {[88, 120, 96, 104, 80, 132, 72].map((w, i) => (
                        <Skeleton key={i} className="h-8 rounded-md" style={{ width: w }} />
                    ))}
                </div>
            ) : (
                <div className={ROWS}>
                    {Array.from({ length: rows }, (_, i) => (
                        <Row key={i} wide={i % 2 === 0} />
                    ))}
                </div>
            )}
        </section>
    );
}

export function DashboardSkeleton() {
    return (
        <div className="scrollbar-subtle h-full overflow-y-auto" data-testid="dashboard-tab-loading" aria-busy="true" aria-label="Loading your dashboard">
            <div className={cn('mx-auto', LAYOUT.pagePad)} style={{ maxWidth: LAYOUT.pageMaxWidth }}>
                <div className={cn('space-y-2', LAYOUT.greetingGap)}>
                    <Skeleton className="h-6 w-56" />
                    <Skeleton className="h-3.5 w-80" />
                </div>
                <div className={cn(SURFACE, LAYOUT.ledgerGap, 'grid divide-x divide-border dark:divide-foreground/[0.06] overflow-hidden')} style={{ gridTemplateColumns: 'repeat(6, minmax(0, 1fr))' }}>
                    {Array.from({ length: 6 }, (_, i) => (
                        <div key={i} className={cn('space-y-2.5', LAYOUT.ledgerCell)}>
                            <Skeleton className="h-2.5 w-16" />
                            <Skeleton className="h-6 w-10" />
                            <Skeleton className="h-2.5 w-28" />
                        </div>
                    ))}
                </div>
                <div className={cn('grid', LAYOUT.gridGap)} style={{ gridTemplateColumns: 'repeat(12, minmax(0, 1fr))' }}>
                    {ORDER.balanced.map((id) => (
                        <Card key={id} id={id} />
                    ))}
                </div>
            </div>
            <span className={cn('sr-only', HAIRLINE)}>Loading your dashboard</span>
        </div>
    );
}
