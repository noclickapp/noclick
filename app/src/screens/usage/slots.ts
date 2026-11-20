// The Usage page's slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise. The
// money behind the page (the plan, the balance and how it's added to, what needs doing, how a charge was priced) is
// the deployment's, so a host that bills fills these; without one the page shows what each thing cost.
import type { ComponentType } from 'react';
import { slot } from '@/slots';
import type { LineItem, UsageView } from './derive';
import { BalanceOnNoClick, RunFacts } from './slotStandards';
import type { ChargeRun } from './types';

/** Under the page's title, where the deployment bills: the plan the period is on. Nothing stands there: the title
 *  says what the page shows. */
export const PLAN_LINE = slot<ComponentType<{ view: UsageView }> | null>('usage.billing.planLine', null);

/** Beside the headline, where the deployment bills: the balance. The standard shows it, read-only, with a link to add
 *  funds on NoClick. */
export const BALANCE = slot<ComponentType<{ view: UsageView }> | null>('usage.billing.balance', BalanceOnNoClick);

/** Above the headline, where the deployment bills: the one thing to act on (money owed, work paused, money running
 *  out). Nothing stands there. */
export const ALERT = slot<ComponentType<{ view: UsageView }> | null>('usage.billing.alert', null);

/** In a charge's facts, where the deployment bills: how it was priced. Nothing stands there. */
export const CHARGE_PRICE = slot<ComponentType<{ item: LineItem; view: UsageView }> | null>('usage.charge.price', null);

/** The run a charge belonged to, opened from its facts. The standard says what the charges read knows of it and links
 *  its automation on NoClick. */
export const CHARGE_RUN = slot<ComponentType<{ run: ChargeRun; onClose: () => void }>>('usage.charge.run', RunFacts);

/** Asks someone about a charge, in the words given. Nobody stands there, and a charge's facts then offer no one to ask. */
export const CHARGE_ASK = slot<((question: string) => void) | null>('usage.charge.ask', null);
