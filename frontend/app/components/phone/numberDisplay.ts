// How a number for sale reads: the number grouped the way its country writes it, the place it's in, what it can do,
// what it costs, and what its country asks before it's sold.
import { parsePhoneNumberFromString } from 'libphonenumber-js';
import { countryName } from '~/components/ui/country-picker';
import type { AvailableNumber } from '~/hooks/usePhoneNumberPurchase';
import { formatUsd } from '~/lib/money';

/** '+442071234567' → '+44 20 7123 4567': the country's own grouping. */
export function formatNumber(e164: string): string {
    return parsePhoneNumberFromString(e164)?.formatInternational() ?? e164;
}

/** Where it rings: its city and region, else its country. */
export function placeOf(number: Pick<AvailableNumber, 'locality' | 'region' | 'country'>): string {
    const place = [titleCase(number.locality), number.region].filter(Boolean).join(', ');
    return place || countryName(number.country);
}

/** Carriers write places in capitals ("SAN FRANCISCO"); people don't. */
function titleCase(text: string): string {
    return text && text === text.toUpperCase() ? text.toLowerCase().replace(/\b\p{L}/gu, (c) => c.toUpperCase()) : text;
}

const CAPABILITIES: [string, string][] = [
    ['voice', 'Calls'],
    ['SMS', 'Texts'],
    ['MMS', 'MMS'],
];

/** What it can do, in words: Calls, Texts, MMS. */
export function capabilityLabels(capabilities: string[]): string[] {
    return CAPABILITIES.filter(([key]) => capabilities.includes(key)).map(([, label]) => label);
}

/** Its price, in dollars: "$1.00/mo", and "+ $1.00 once" where it costs something to buy. */
export function priceText(number: Pick<AvailableNumber, 'monthly_credits' | 'upfront_credits'>): { monthly: string; upfront: string | null } {
    return { monthly: formatUsd(number.monthly_credits), upfront: number.upfront_credits > 0 ? formatUsd(number.upfront_credits) : null };
}

/** What buying it charges now: its first month and its one-time cost. */
export function dueNow(number: Pick<AvailableNumber, 'monthly_credits' | 'upfront_credits'>): string {
    return formatUsd(number.monthly_credits + number.upfront_credits);
}

/** Why texting from it waits, where it does. */
export function textingNote(number: Pick<AvailableNumber, 'texting' | 'country'>): string | null {
    if (number.texting === 'registration') return 'Texts once your business is registered with the US carriers.';
    if (number.texting === 'unavailable') return `Texting from ${countryName(number.country)} numbers isn’t available yet.`;
    return null;
}

/** Why a number's country asks who holds it, and what happens to what they give. */
export function holderNote(country: string): string {
    return `${countryName(country)} asks who holds a number before it’s sold. NoClick files these details with the carrier, which checks them; if it doesn’t accept them, nothing is bought or charged.`;
}

/** Why a number's country asks for documents, and what happens once they're filed. */
export function reviewNote(country: string): string {
    return `${countryName(country)} asks for documents before a number is sold. The carrier reviews them, which can take a few days; the number is yours, and charged, only once it approves them.`;
}

/** Whether its country asks for its holder's contact information, so a phone to reach them on as well. */
export function asksContactPhone(number: Pick<AvailableNumber, 'requirements'>): boolean {
    return number.requirements.items.some((r) => r.kind === 'contact');
}

// What a requirement is, read from the name the carrier gives it ("GST Registration Certificate" is tax, so tax first).
const DOCUMENT_KINDS: [RegExp, string][] = [
    [/\b(tax|gst|vat|pan|tin|ein)\b/i, 'tax'],
    [/compan|business|incorporat|registr|trade|commercial/i, 'business registration'],
    [/identit|passport|\bid\b|driv|onfido|verif|selfie|aadhaar/i, 'identity'],
    [/address|utility/i, 'address'],
];
const DOCUMENT_ORDER = ['business registration', 'tax', 'identity', 'address'];

/** What a country that asks for documents (or a step) wants, in plain words: "business registration, tax and identity
 *  documents". */
export function documentsSummary(requirements: AvailableNumber['requirements']): string {
    const found = new Set(requirements.items.map((r) => DOCUMENT_KINDS.find(([pattern]) => pattern.test(r.name))?.[1]));
    const kinds = DOCUMENT_ORDER.filter((k) => found.has(k));
    if (kinds.length < 2) return `${kinds[0] ?? ''} documents`.trimStart();
    return `${kinds.slice(0, -1).join(', ')} and ${kinds[kinds.length - 1]} documents`;
}

/** Each thing a country that asks for documents asks for, by the carrier's name for it. */
export function documentsAsked(requirements: AvailableNumber['requirements']): string[] {
    return [...new Set(requirements.items.map((r) => r.name).filter(Boolean))];
}
