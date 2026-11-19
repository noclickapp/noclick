// What Resources costs, in US dollars. A number's price comes with the account's numbers (the platform's own monthly
// price, or what a host says it charged last month). The platform's items carry their own: a domain what a year of it
// renews at, an app what it has spent this month; a kind billed by use without a per-item split (databases) comes with
// what it has cost this month. Files aren't billed, and what an automation's tables and published interface use is the
// account's own usage, not the platform's.
import { useMemo } from 'react';
import { useResources } from './context';
import { KINDS, type ItemPrice, type KindId, type ResourceItem } from './model';
import { usePlatformResources } from './platform';

export interface ResourceCosts {
    /** False where nobody is billed: show no prices at all. */
    shown: boolean;
    /** A resource's monthly figure by its id, where it has one: a month of its price, or what it has spent this month. */
    monthly: ReadonlyMap<string, number>;
    /** What each billed kind comes to: a month of its items' prices, or what its use has cost so far this month. */
    kindMonthly: Partial<Record<KindId, number>>;
}

/** An item's price as a monthly figure. */
export function monthlyUsd(price: ItemPrice): number {
    return price.per === 'year' ? price.usd / 12 : price.usd;
}

export function useResourceCosts(items: Record<KindId, ResourceItem[]>): ResourceCosts {
    const { billing } = useResources();
    const platform = usePlatformResources();
    const numberPrices = platform?.numberPrices;
    const spentThisMonth = platform?.spentThisMonth;
    return useMemo(() => {
        const monthly = new Map<string, number>();
        const kindMonthly: Partial<Record<KindId, number>> = {};
        for (const kind of KINDS) {
            if (!kind.billed) continue;
            for (const item of items[kind.id]) {
                const price = item.price ? monthlyUsd(item.price) : item.kind === 'numbers' ? numberPrices?.get(item.id) : undefined;
                // What its use has cost so far shows at nothing too: an agent that spent nothing says so.
                if (price || item.price?.per === 'so-far') monthly.set(item.id, price ?? 0);
            }
            const spent = spentThisMonth?.[kind.id];
            const total = spent !== undefined ? spent : items[kind.id].reduce((sum, item) => sum + (monthly.get(item.id) ?? 0), 0);
            if (total) kindMonthly[kind.id] = total;
        }
        return { shown: billing, monthly, kindMonthly };
    }, [items, numberPrices, spentThisMonth, billing]);
}
