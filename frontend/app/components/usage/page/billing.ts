// What a deployment that bills adds to the usage page, registered once at start-up (the hosted service's
// cloud/bootstrap.ts): the plan's line under the title, the balance beside the headline with its way to add funds,
// the one thing to act on above them, and how a charge was priced. Without it the page shows what each thing cost.
import type { ComponentType } from 'react';
import type { LineItem, UsageView } from './derive';

export interface UsageBillingSlots {
    /** Under the title: the plan and how it charges. */
    PlanLine?: ComponentType<{ view: UsageView }>;
    /** Beside the headline: the balance (or an older plan's credits) and the way to add to it. */
    Balance?: ComponentType<{ view: UsageView }>;
    /** Above the headline, when something needs doing: owed money, work paused, money about to run out. */
    Alert?: ComponentType<{ view: UsageView }>;
    /** A charge's price, as its drawer explains it. */
    ChargePrice?: ComponentType<{ item: LineItem; view: UsageView }>;
}

let slots: UsageBillingSlots = {};

export function registerUsageBilling(next: UsageBillingSlots): void {
    slots = next;
}

export function usageBillingSlots(): UsageBillingSlots {
    return slots;
}
