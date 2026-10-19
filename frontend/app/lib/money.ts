// Usage is metered in credits; what people read is dollars. How many credits a
// dollar buys is the instance's setting (billing.markup.CREDITS_PER_DOLLAR,
// reported by instance-status): the hosted service sells four, and an install
// that bills nobody counts dollars. The edition's rate stands until the
// instance answers.
import { isLocalEdition } from '~/lib/edition';

/** The hosted service's price list: 1 credit = $0.25. */
export const HOSTED_CREDITS_PER_DOLLAR = 4;

let creditsPerDollar = isLocalEdition() ? 1 : HOSTED_CREDITS_PER_DOLLAR;

/** The instance's own rate, once instance-status reports it. */
export function setCreditsPerDollar(rate: number): void {
    if (rate > 0) creditsPerDollar = rate;
}

const USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function creditsToUsd(credits: number): number {
    return credits / creditsPerDollar;
}

export function usdToCredits(usd: number): number {
    return usd * creditsPerDollar;
}

/** A credit amount as dollars: 100 → "$25.00". */
export function formatUsd(credits: number): string {
    return USD.format(creditsToUsd(credits));
}

/** A price already in dollars (a vendor's, like a domain's): 12.99 → "$12.99". */
export function formatDollars(usd: number): string {
    return USD.format(usd);
}

/** A metered amount as dollars, precise enough that a small real charge never
 *  rounds away: a 30s sandbox beat is "$0.0063", a short model call "<$0.0001". */
export function formatUsage(credits: number): string {
    const usd = creditsToUsd(credits);
    if (usd === 0) return '$0';
    if (usd >= 0.1) return USD.format(usd);
    if (usd >= 0.0001) return `$${Number(usd.toPrecision(2))}`;
    return '<$0.0001';
}
