// A failure's way out, as the one button a person presses: what the error itself carries (a link to pay, to connect,
// the account's own page for a paused user) or the console's page that lifts it (the cap that was reached, the rule
// that refused it). Null where nothing a person does here fixes it; the error's words then say what to do.
import { CredentialDisconnected, NeedsConnection, NoClickError, PaymentRequired, PlanRequired, PolicyDenied, SpendCapExceeded, SpendingPaused } from 'noclick';
import type { HrefParams } from '@/screens/console/hooks/useConsole';
import { addFundsUrl, billingSettingsUrl, pricingUrl } from './site';
import { userPath } from './userFilter';

export interface FailureFix {
    label: string;
    href: string;
    /** On NoClick's own site or the error's own link, so it opens apart from the console. */
    external: boolean;
}

/** Where the console is and what it links to, as the error panel reads them from the console's context. */
export interface FixPlace {
    href: (path?: string, params?: HrefParams) => string;
    site: string;
}

const detail = (error: NoClickError, key: string): string | undefined => (typeof error.details[key] === 'string' ? (error.details[key] as string) : undefined);

/** A cap that was reached, on the page where it's raised. */
function capFix(error: SpendCapExceeded, { href, site }: FixPlace): FailureFix {
    const id = detail(error, 'scope_id');
    switch (error.scope) {
        case 'key':
            if (id) return { label: 'Raise the key’s cap', href: href('keys', { key: id }), external: false };
            break;
        case 'user':
            if (id) return { label: 'Raise the user’s cap', href: href(userPath(id)), external: false };
            break;
        case 'agent':
            if (id) return { label: 'Raise the agent’s budget', href: href(`agents/${encodeURIComponent(id)}`), external: false };
            break;
        case 'project': {
            const app = detail(error, 'project_id') ?? id;
            if (app) return { label: 'Raise the app’s budget', href: href('resources/apps', { app }), external: false };
            break;
        }
    }
    return { label: 'Raise the monthly cap', href: billingSettingsUrl(site), external: true };
}

export function failureFix(error: unknown, place: FixPlace): FailureFix | null {
    if (error instanceof PaymentRequired || error instanceof PlanRequired) {
        const offer = error.offers[0];
        if (offer) return { label: offer.kind === 'plan' ? 'Choose a plan' : 'Add funds', href: offer.url, external: true };
        return error instanceof PaymentRequired ? { label: 'Add funds', href: addFundsUrl(place.site), external: true } : { label: 'See the plans', href: pricingUrl(place.site), external: true };
    }
    if (error instanceof SpendCapExceeded) return capFix(error, place);
    if (error instanceof SpendingPaused) return error.action ? { label: error.action.label, href: error.action.url, external: true } : null;
    if (error instanceof CredentialDisconnected || error instanceof NeedsConnection) {
        return error.connectUrl ? { label: error instanceof CredentialDisconnected ? 'Reconnect' : 'Connect', href: error.connectUrl, external: true } : null;
    }
    if (error instanceof PolicyDenied) return { label: 'Open approval rules', href: place.href('approval-rules'), external: false };
    return null;
}
