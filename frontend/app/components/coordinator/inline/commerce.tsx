// Buying in the thread: a row's choose → confirm with its price → buying, in place, so nothing is charged before the
// price is in front of you; and a plan or top-up a request needs, as the links that pay for it.
import type { ReactNode } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { cn } from '~/lib/utils';
import { InlineCard, PILL_PRIMARY, PILL_QUIET, PILL_SECONDARY, Status } from './primitives';

/** One row's purchase: its price and Choose, then Cancel and "Buy for $2.00 a month", then buying. */
export function BuyAside({
    price,
    unit,
    once,
    chosen,
    buying,
    disabled,
    onChoose,
    onCancel,
    onConfirm,
}: {
    /** The price to show; absent while the chosen row is being priced. */
    price?: string;
    unit: string;
    /** What it also costs once, when it's bought. */
    once?: string | null;
    chosen: boolean;
    buying: boolean;
    disabled?: boolean;
    onChoose: () => void;
    onCancel: () => void;
    onConfirm: () => void;
}) {
    if (!chosen) {
        return (
            <>
                {price && (
                    <span className="text-[13px] tabular-nums text-muted-foreground">
                        {price}/{unit}
                        {once ? ` + ${once} once` : ''}
                    </span>
                )}
                <button type="button" className={PILL_SECONDARY} onClick={onChoose} disabled={disabled}>
                    Choose
                </button>
            </>
        );
    }
    if (buying) return <Status state="working">Buying</Status>;
    if (!price) return <Status state="working">Pricing</Status>;
    return (
        <>
            <button type="button" className={PILL_QUIET} onClick={onCancel}>
                Cancel
            </button>
            <button type="button" className={PILL_PRIMARY} onClick={onConfirm}>
                Buy for {price} a {unit}
                {once ? ` + ${once} once` : ''}
            </button>
        </>
    );
}

export interface PayLink {
    label: string;
    href: string;
}

/** What a request needs paid for, and the links that pay for it; the first is the one NoClick suggests. */
export function PayCard({ lead, title, meta, links, children }: { lead?: ReactNode; title: ReactNode; meta?: ReactNode; links: PayLink[]; children?: ReactNode }) {
    return (
        <InlineCard
            lead={lead}
            title={title}
            meta={meta}
            actions={links.map((link, i) => (
                <a key={link.href} href={link.href} target="_blank" rel="noopener noreferrer" className={cn(i === 0 ? PILL_PRIMARY : PILL_SECONDARY)}>
                    {link.label}
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            ))}
        >
            {children}
        </InlineCard>
    );
}
