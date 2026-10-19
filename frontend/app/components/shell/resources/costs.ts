// What Resources costs, in credits (money.ts renders them as dollars). A phone
// number's price is its latest monthly charge in the usage log, the same log
// Settings → Usage reads, so the two can't disagree. The platform's items carry
// their own: a domain what a year of it renews at, an app what it has spent
// this month; a kind billed by use without a per-item split (databases) comes
// with what it has cost this month. Files aren't billed, and what an
// automation's tables and published interface use is the account's own usage
// (Settings → Usage), not the platform's.
import { useEffect, useMemo, useState } from 'react';
import { useInstanceCapabilities } from '~/hooks/useInstanceCapabilities';
import { useOrgContext } from '~/hooks/useOrgContext';
import { usdToCredits } from '~/lib/money';
import { socketCall } from '~/lib/socketCall';
import { KINDS, type ItemPrice, type KindId, type ResourceItem } from './model';
import { usePlatformResources } from './platform';

export interface ResourceCosts {
    /** False on an install that bills nobody: show no prices at all. */
    shown: boolean;
    /** A resource's monthly figure by its id, where it has one: a month of its price, or what it has spent this month. */
    monthly: ReadonlyMap<string, number>;
    /** What each billed kind comes to: a month of its items' prices, or what its use has cost so far this month. */
    kindMonthly: Partial<Record<KindId, number>>;
}

interface UsageLog {
    model?: string;
    cost?: number;
    timestamp?: string;
    metadata?: { credential_id?: string };
}

/** A number's price is its latest monthly charge: one per number per month, newest first. */
function useNumberPrices(enabled: boolean): ReadonlyMap<string, number> {
    const [orgContext] = useOrgContext();
    const [prices, setPrices] = useState<ReadonlyMap<string, number>>(new Map());
    useEffect(() => {
        if (!enabled) return;
        let live = true;
        socketCall('usage:logs', { usage_type: 'recurring', search: 'phone_number', limit: 100, organization_id: orgContext.id ?? undefined })
            .then((data) => {
                const next = new Map<string, number>();
                for (const log of (data.logs as UsageLog[] | undefined) ?? []) {
                    const id = log.metadata?.credential_id;
                    if (log.model === 'phone_number' && id && log.cost && !next.has(id)) next.set(id, log.cost);
                }
                if (live) setPrices(next);
            })
            .catch((err: unknown) => console.warn('[resources] number prices failed:', err));
        return () => {
            live = false;
        };
    }, [enabled, orgContext.id]);
    return prices;
}

/** An item's price as a monthly figure, in credits. */
export function monthlyCredits(price: ItemPrice): number {
    return usdToCredits(price.per === 'year' ? price.usd / 12 : price.usd);
}

export function useResourceCosts(items: Record<KindId, ResourceItem[]>): ResourceCosts {
    const { billing } = useInstanceCapabilities();
    const numberPrices = useNumberPrices(billing);
    const spentThisMonth = usePlatformResources()?.spentThisMonth;
    return useMemo(() => {
        const monthly = new Map<string, number>();
        const kindMonthly: Partial<Record<KindId, number>> = {};
        for (const kind of KINDS) {
            if (!kind.billed) continue;
            for (const item of items[kind.id]) {
                const price = item.price ? monthlyCredits(item.price) : item.credential ? numberPrices.get(item.id) : undefined;
                if (price) monthly.set(item.id, price);
            }
            const spent = spentThisMonth?.[kind.id];
            const total = spent !== undefined ? usdToCredits(spent) : items[kind.id].reduce((sum, item) => sum + (monthly.get(item.id) ?? 0), 0);
            if (total) kindMonthly[kind.id] = total;
        }
        return { shown: billing, monthly, kindMonthly };
    }, [items, numberPrices, spentThisMonth, billing]);
}
